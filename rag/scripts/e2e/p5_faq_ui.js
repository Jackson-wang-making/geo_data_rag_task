/** Generate a real FAQ in the UI and verify the partial/manual-review surface. */
const {
  assert,
  launch,
  newPage,
  hideDeploy,
  waitForMetrics,
  waitForDoc,
  saveScreenshot,
  spawnServer,
  waitHealth,
  stopServer,
} = require('./lib_streamlit');

const PORT = 8504;
const TOPIC = '中国出海品牌如何做 GEO 优化';
const EXPECTED = {
  'PDF 总页数': 36,
  '有 chunk 的页': 33,
  '无 chunk 的页': 3,
  'OCR 不可用页': 0,
  'Chunk 数': 43,
};

(async () => {
  const provider = process.env.E2E_EMBEDDING_PROVIDER || 'local';
  const overrides = {
    EMBEDDING_PROVIDER: provider,
    MAX_OUTPUT_TOKENS: '16000',
  };
  if (provider === 'ollama') {
    overrides.OLLAMA_BASE_URL = process.env.OLLAMA_BASE_URL || 'http://127.0.0.1:11434';
  }
  const server = spawnServer(PORT, overrides, 'p5-faq.log');
  const browser = await launch();
  const { context, page } = await newPage(browser);
  try {
    await waitHealth(PORT, 300000);
    await page.goto(`http://127.0.0.1:${PORT}`, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForSelector('text=PDF 总页数', { timeout: 600000 });
    await hideDeploy(page);
    await waitForDoc(page, 'Trendee品宣-公开版.pdf');
    await waitForMetrics(page, EXPECTED, 600000);

    const combo = page.getByRole('combobox');
    await combo.click();
    await page.getByText('FAQ', { exact: true }).last().click();
    await page.getByLabel('主题').fill(TOPIC);
    await page.getByLabel('主题').press('Enter');

    const generate = page.getByRole('button', { name: '生成文章' });
    await generate.waitFor({ state: 'visible', timeout: 120000 });
    for (let i = 0; i < 120; i++) {
      if (await generate.isEnabled()) break;
      await page.waitForTimeout(500);
    }
    assert(await generate.isEnabled(), 'generate button never enabled');
    console.log('clicking generate FAQ (real DeepSeek call, one click)');
    await generate.click();

    await page.waitForSelector('text=生成结果', { timeout: 1200000 });
    await page.waitForFunction(
      () => /引用校验通过|文章状态为 partial|现有资料不足以支持|GENERATION_FAILED|LLM_UNAVAILABLE/.test(document.body.innerText),
      { timeout: 1200000 }
    );
    await page.waitForTimeout(1500);

    const bodyText = await page.locator('body').innerText();
    const partial = bodyText.includes('文章状态为 partial');
    const complete = bodyText.includes('引用校验通过');
    assert(partial || complete, 'FAQ did not produce a complete/partial article');
    console.log('FAQ_STATUS ' + (partial ? 'partial' : 'complete'));

    if (partial) {
      const expander = page.getByText('需要人工复核', { exact: true });
      assert((await expander.count()) > 0, 'manual review expander missing for partial');
      const reviewText = await page.locator('[data-testid="stExpander"]').filter({ hasText: '需要人工复核' }).innerText();
      assert(reviewText.length > 20, 'manual review expander is empty');
      assert(/不支持|不确定|校验|修复|缺失/.test(reviewText), 'manual review text does not describe an issue');
      if (reviewText.includes('自动修复')) {
        assert(
          reviewText.includes('首次生成未通过引用校验；自动修复后通过，但仍降级为 partial。'),
          'repair downgrade message is not the documented exact text'
        );
      }
      console.log('MANUAL_REVIEW_VISIBLE true');
      console.log('MANUAL_REVIEW_HEAD ' + reviewText.replace(/\s+/g, ' ').slice(0, 300));
    }

    await saveScreenshot(page, '11-faq-partial.png', true);
    console.log('PASS faq_ui status=' + (partial ? 'partial' : 'complete'));
    await context.close();
  } finally {
    await browser.close();
    await stopServer(server, PORT);
  }
})().catch((err) => {
  console.error('FLOW_FAILED', err);
  process.exit(1);
});
