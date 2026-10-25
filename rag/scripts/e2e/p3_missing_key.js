/** Missing LLM key: the app must fail closed with LLM_UNAVAILABLE and write no artifact. */
const {
  assert,
  launch,
  newPage,
  hideDeploy,
  waitHealth,
  spawnServer,
  stopServer,
  waitForMetrics,
  waitForDoc,
  mainAlerts,
  listArtifactDirs,
  saveScreenshot,
} = require('./lib_streamlit');

const PORT = 8502;
const TOPIC = '为什么中国出海品牌需要 GEO 优化';
const EXPECTED = {
  'PDF 总页数': 36,
  '有 chunk 的页': 33,
  '无 chunk 的页': 3,
  'OCR 不可用页': 0,
  'Chunk 数': 43,
};

(async () => {
  const before = await listArtifactDirs();
  // Empty-but-present override: dotenv(override=False) will not reload .env's key.
  // Keep the default local bge-m3 path so this drill also covers the normal setup.
  const server = spawnServer(PORT, { LLM_API_KEY: '' }, 'p3-missing-key.log');
  const browser = await launch();
  const { context, page } = await newPage(browser);
  let passed = false;
  try {
    await waitHealth(PORT);
    await page.goto(`http://127.0.0.1:${PORT}`, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForFunction(
      () => document.body.innerText.includes('未配置 LLM_API_KEY'),
      { timeout: 300000 }
    );
    await hideDeploy(page);
    await waitForDoc(page, 'Trendee品宣-公开版.pdf', 600000);
    const sidebarText = await page.locator('[data-testid="stSidebar"]').innerText();
    assert(sidebarText.includes('Provider：local'), 'expected default local embedding provider');
    assert(sidebarText.includes('目录：'), 'local model directory missing from sidebar');
    const metrics = await waitForMetrics(page, EXPECTED, 600000);
    console.log('FINGERPRINT provider=local indexed=true metrics=' + JSON.stringify(metrics));

    const topicInput = page.getByLabel('主题');
    await topicInput.fill(TOPIC);
    await topicInput.press('Enter');
    const generate = page.getByRole('button', { name: '生成文章' });
    await generate.waitFor({ state: 'visible', timeout: 120000 });
    for (let i = 0; i < 120 && !(await generate.isEnabled()); i++) await page.waitForTimeout(500);
    assert(await generate.isEnabled(), 'generate button never enabled');
    await generate.click();

    await page.waitForFunction(
      () =>
        Array.from(document.querySelectorAll('[data-testid="stMain"] [data-testid="stAlert"]')).some((el) =>
          /LLM_UNAVAILABLE\s*—/.test(el.innerText)
        ),
      { timeout: 180000 }
    );
    const alerts = await mainAlerts(page);
    console.log('MAIN_ALERTS ' + JSON.stringify(alerts));
    await page.waitForFunction(
      () => /\[1\] Trendee品宣-公开版\.pdf · PDF 第 \d+ 页/.test(document.body.innerText),
      { timeout: 60000 }
    );
    const bodyText = await page.locator('body').innerText();
    assert(bodyText.includes('生成结果'), 'error result block missing');
    assert(bodyText.includes('未生成文章。已检索到的来源仍保留在下方'), 'retained-sources notice missing');
    assert(/\[1\] Trendee品宣-公开版\.pdf · PDF 第 \d+ 页/.test(bodyText), 'source card missing');
    assert(!bodyText.includes('引用校验通过'), 'article rendered despite missing key');
    assert(!bodyText.includes('下载本次产物'), 'downloads rendered despite missing key');
    assert((await page.locator('[data-testid="stDownloadButton"]').count()) === 0, 'download buttons exist');
    await saveScreenshot(page, '09-llm-unavailable.png', true);

    const after = await listArtifactDirs();
    assert(JSON.stringify(before) === JSON.stringify(after), 'artifact directories changed');
    console.log('ARTIFACTS_UNCHANGED true');
    console.log('PASS missing_key');
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
