/** Local bge-m3 load failure: app must show EMBED_UNAVAILABLE and build no index. */
const fs = require('fs');
const path = require('path');
const {
  OUT,
  RAG,
  assert,
  launch,
  newPage,
  hideDeploy,
  waitHealth,
  spawnServer,
  stopServer,
  mainAlerts,
  listArtifactDirs,
  saveScreenshot,
} = require('./lib_streamlit');

const PORT = 8505;
// The app resolves a relative EMBEDDING_MODEL_PATH against the rag project root,
// while this script's cwd is scripts/e2e. Resolve once, then pass an absolute path.
const BAD_MODEL_DIR = path.resolve(
  RAG,
  process.env.E2E_EMPTY_MODEL_DIR || path.join(OUT, 'empty-bge-m3')
);
fs.mkdirSync(BAD_MODEL_DIR, { recursive: true });
const OVERRIDES = {
  EMBEDDING_PROVIDER: 'local',
  EMBEDDING_MODEL_PATH: BAD_MODEL_DIR,
  EMBEDDING_DEVICE: 'cpu',
};

(async () => {
  const before = await listArtifactDirs();
  const server = spawnServer(PORT, OVERRIDES, 'p4b-local-embed-failure.log');
  const browser = await launch();
  const { context, page } = await newPage(browser);
  let passed = false;
  try {
    await waitHealth(PORT);
    await page.goto(`http://127.0.0.1:${PORT}`, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForFunction(
      () => {
        const text = document.body.innerText;
        return text.includes('Provider：local') && text.includes('目录：');
      },
      { timeout: 300000 }
    );
    await hideDeploy(page);
    console.log('FINGERPRINT provider=local model_path=' + BAD_MODEL_DIR);

    await page.waitForFunction(
      () =>
        Array.from(document.querySelectorAll('[data-testid="stMain"] [data-testid="stAlert"]')).some((el) =>
          /EMBED_UNAVAILABLE\s*—/.test(el.innerText)
        ),
      { timeout: 300000 }
    );
    const alerts = await mainAlerts(page);
    console.log('MAIN_ALERTS ' + JSON.stringify(alerts));
    const bodyText = await page.locator('body').innerText();
    assert(
      bodyText.includes('未建立索引。请检查本地 bge-m3 模型目录与依赖后刷新页面重试。'),
      'actionable no-index message missing'
    );
    assert(!bodyText.includes('PDF 总页数'), 'coverage metrics rendered despite failure');
    assert(!bodyText.includes('Chunk 数'), 'chunk metric rendered despite failure');
    assert(!bodyText.includes('生成结果'), 'article rendered despite failure');
    assert(!bodyText.includes('下载本次产物'), 'downloads rendered despite failure');
    assert((await page.getByRole('button', { name: '生成文章' }).count()) === 0, 'generate button exists');
    assert((await page.locator('[data-testid="stDownloadButton"]').count()) === 0, 'download buttons exist');
    await saveScreenshot(page, '12-local-embed-unavailable.png', true);

    const after = await listArtifactDirs();
    assert(JSON.stringify(before) === JSON.stringify(after), 'artifact directories changed');
    console.log('ARTIFACTS_UNCHANGED true');
    console.log('PASS local_embed_failure');
    passed = true;
    await context.close();
  } finally {
    await browser.close();
    await stopServer(server, PORT);
    if (!passed) process.exitCode = 1;
  }
})().catch((err) => {
  console.error('FLOW_FAILED', err);
  process.exit(1);
});
