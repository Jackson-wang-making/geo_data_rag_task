/** Embedding outage: app must show EMBED_UNAVAILABLE, build no index, write no artifact. */
const {
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

const PORT = 8503;
const OVERRIDES = {
  EMBEDDING_PROVIDER: 'ollama',
  OLLAMA_BASE_URL: 'http://127.0.0.1:1',
  EMBEDDING_TIMEOUT: '2',
  NO_PROXY: '127.0.0.1',
  no_proxy: '127.0.0.1',
};

(async () => {
  const before = await listArtifactDirs();
  const server = spawnServer(PORT, OVERRIDES, 'p4-embed-outage.log');
  const browser = await launch();
  const { context, page } = await newPage(browser);
  let passed = false;
  try {
    await waitHealth(PORT);
    await page.goto(`http://127.0.0.1:${PORT}`, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForFunction(
      () => {
        const text = document.body.innerText;
        return text.includes('Provider：ollama') && text.includes('服务：http://127.0.0.1:1');
      },
      { timeout: 300000 }
    );
    await hideDeploy(page);
    console.log('FINGERPRINT provider=ollama service=http://127.0.0.1:1');

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
      bodyText.includes('未建立索引。启动 embedding 服务后刷新页面重试。'),
      'actionable no-index message missing'
    );
    assert(!bodyText.includes('PDF 总页数'), 'coverage metrics rendered despite outage');
    assert(!bodyText.includes('Chunk 数'), 'chunk metric rendered despite outage');
    assert(!bodyText.includes('生成结果'), 'article rendered despite outage');
    assert(!bodyText.includes('下载本次产物'), 'downloads rendered despite outage');
    assert((await page.getByRole('button', { name: '生成文章' }).count()) === 0, 'generate button exists');
    assert((await page.locator('[data-testid="stDownloadButton"]').count()) === 0, 'download buttons exist');
    await saveScreenshot(page, '10-embed-unavailable.png', true);

    const after = await listArtifactDirs();
    assert(JSON.stringify(before) === JSON.stringify(after), 'artifact directories changed');
    console.log('ARTIFACTS_UNCHANGED true');
    console.log('PASS embed_outage');
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
