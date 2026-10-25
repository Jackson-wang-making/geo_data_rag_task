/**
 * Shared helpers for the Streamlit E2E drills.
 *
 * Security: never print process.env, request headers, or file contents that
 * could contain the API key. `scanForSecrets` returns booleans only.
 */
const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const RAG = path.resolve(__dirname, '..', '..');
const PW = __dirname;
const OUT = process.env.E2E_OUT
  ? path.resolve(process.env.E2E_OUT)
  : path.join(PW, 'out');
const ART = path.join(RAG, 'artifacts');
const DEFAULT_PDF = path.resolve(RAG, '..', 'inputs', 'brand', 'Trendee品宣-公开版.pdf');
const PY = process.env.PYTHON
  || path.join(
    RAG,
    '.venv',
    process.platform === 'win32' ? 'Scripts' : 'bin',
    process.platform === 'win32' ? 'python.exe' : 'python'
  );

for (const dir of [OUT, path.join(OUT, 'downloads'), path.join(OUT, 'logs')]) {
  fs.mkdirSync(dir, { recursive: true });
}

function assert(condition, message) {
  if (!condition) throw new Error('ASSERT_FAILED: ' + message);
}

async function launch() {
  return chromium.launch({ channel: 'chrome', headless: true });
}

async function newPage(browser) {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1200 },
    deviceScaleFactor: 1,
    acceptDownloads: true,
  });
  const page = await context.newPage();
  page.setDefaultTimeout(120000);
  page.on('pageerror', (err) => console.log('PAGE_ERROR', err.message));
  page.on('console', (msg) => {
    if (msg.type() === 'error') console.log('CONSOLE_ERROR', msg.text());
  });
  return { context, page };
}

async function hideDeploy(page) {
  await page.addStyleTag({
    content: '[data-testid="stAppDeployButton"]{display:none !important}',
  });
}

async function waitHealth(port, timeoutMs = 180000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/_stcore/health`);
      if (res.status === 200) return;
    } catch (_) {
      // server not up yet
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(`health check timed out on port ${port}`);
}

async function isHealthy(port) {
  try {
    const res = await fetch(`http://127.0.0.1:${port}/_stcore/health`);
    return res.status === 200;
  } catch (_) {
    return false;
  }
}

function spawnServer(port, extraEnv, logName) {
  const logFile = path.join(OUT, 'logs', logName);
  const out = fs.createWriteStream(logFile, { flags: 'a' });
  const args = [
    '-m',
    'streamlit',
    'run',
    'app.py',
    '--server.address',
    '127.0.0.1',
    '--server.port',
    String(port),
    '--server.headless',
    'true',
    '--browser.gatherUsageStats',
    'false',
  ];
  const child = spawn(PY, args, {
    cwd: RAG,
    env: { ...process.env, ...extraEnv },
    windowsHide: true,
  });
  child.stdout.pipe(out);
  child.stderr.pipe(out);
  child.on('exit', (code) => {
    out.write(`\n[streamlit exited code=${code}]\n`);
    out.end();
  });
  console.log(`spawned streamlit port=${port} pid=${child.pid} log=${logFile}`);
  return child;
}

async function stopServer(child, port) {
  if (!child) return;
  child.kill('SIGTERM');
  for (let i = 0; i < 30; i++) {
    await new Promise((resolve) => setTimeout(resolve, 500));
    if (!(await isHealthy(port))) {
      console.log(`stopped port=${port}`);
      return;
    }
  }
  console.log(`port ${port} still healthy; using taskkill /T /F`);
  spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true });
  await new Promise((resolve) => setTimeout(resolve, 3000));
}

async function metrics(page) {
  return page.$$eval('[data-testid="stMetric"]', (elements) =>
    elements.map((el) => ({
      label: (el.querySelector('[data-testid="stMetricLabel"]')?.innerText || '').trim(),
      value: (el.querySelector('[data-testid="stMetricValue"]')?.innerText || '').trim(),
    }))
  );
}

function metricMap(rows) {
  const map = {};
  for (const row of rows) map[row.label] = row.value;
  return map;
}

async function waitForMetrics(page, expected, timeoutMs = 600000) {
  const deadline = Date.now() + timeoutMs;
  let last = null;
  while (Date.now() < deadline) {
    const rows = await metrics(page);
    last = metricMap(rows);
    const ok = Object.entries(expected).every(([label, value]) => last[label] === String(value));
    if (ok) return last;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error('metric wait timed out; last=' + JSON.stringify(last));
}

async function waitForDoc(page, docName, timeoutMs = 600000) {
  await page.waitForFunction(
    (name) => {
      const text = document.body.innerText;
      return text.includes('文档：' + name) && text.includes('覆盖状态：');
    },
    docName,
    { timeout: timeoutMs }
  );
}

async function mainAlerts(page) {
  return page.$$eval('[data-testid="stMain"] [data-testid="stAlert"]', (elements) =>
    elements.map((el) => el.innerText.trim())
  );
}

async function listArtifactDirs() {
  if (!fs.existsSync(ART)) return [];
  return fs
    .readdirSync(ART, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort();
}

async function artifactDirFromCaption(page) {
  const captions = page.locator('[data-testid="stCaptionContainer"]');
  const count = await captions.count();
  for (let i = count - 1; i >= 0; i--) {
    const text = (await captions.nth(i).innerText()).trim();
    if (text.includes('已写入：')) {
      return text.split('已写入：')[1].trim();
    }
  }
  throw new Error('artifact caption not found');
}

function normalizeNewlines(text) {
  return text.replace(/\r\n/g, '\n');
}

function scanForSecrets(text) {
  const patterns = [/sk-[A-Za-z0-9_-]{16,}/, /Bearer\s+[A-Za-z0-9._-]{16,}/];
  return patterns.some((pattern) => pattern.test(text));
}

function saveScreenshot(page, name, fullPage = true) {
  return page.screenshot({ path: path.join(OUT, name), fullPage });
}

module.exports = {
  RAG,
  PW,
  OUT,
  ART,
  DEFAULT_PDF,
  PY,
  assert,
  launch,
  newPage,
  hideDeploy,
  waitHealth,
  isHealthy,
  spawnServer,
  stopServer,
  metrics,
  metricMap,
  waitForMetrics,
  waitForDoc,
  mainAlerts,
  listArtifactDirs,
  artifactDirFromCaption,
  normalizeNewlines,
  scanForSecrets,
  saveScreenshot,
};
