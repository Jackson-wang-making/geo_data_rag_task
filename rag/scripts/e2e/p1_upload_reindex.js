/** Upload the Raku 6.d brochure and assert a real re-index from the new PDF. */
const fs = require('fs');
const path = require('path');
const {
  OUT,
  assert,
  launch,
  newPage,
  hideDeploy,
  waitForMetrics,
  waitForDoc,
  metrics,
  metricMap,
  mainAlerts,
  saveScreenshot,
} = require('./lib_streamlit');

const RAKU = process.env.E2E_OTHER_PDF || path.join(OUT, 'raku-6d-brochure.pdf');
const UPLOAD_NAME = path.basename(RAKU);
const IS_RAKU = UPLOAD_NAME === 'raku-6d-brochure.pdf';
const QUERY = process.env.E2E_QUERY || (IS_RAKU ? 'What is being released in Raku 6.d?' : '');
const DEFAULT_EXPECTED = {
  'PDF 总页数': 36,
  '有 chunk 的页': 33,
  '无 chunk 的页': 3,
  'OCR 不可用页': 0,
  'Chunk 数': 43,
};
const RAKU_EXPECTED = {
  'PDF 总页数': 9,
  '有 chunk 的页': 8,
  '无 chunk 的页': 1,
  'OCR 不可用页': 0,
  'Chunk 数': 16,
};

(async () => {
  if (!fs.existsSync(RAKU)) {
    console.error(
      'SKIP p1_upload_reindex: set E2E_OTHER_PDF to a small PDF (plus E2E_QUERY for its search), or place the Raku fixture at ' + RAKU
    );
    return;
  }
  const browser = await launch();
  const { context, page } = await newPage(browser);
  try {
    await page.goto('http://127.0.0.1:8501', { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForSelector('text=PDF 总页数', { timeout: 600000 });
    await hideDeploy(page);

    await waitForDoc(page, 'Trendee品宣-公开版.pdf');
    const baseline = await waitForMetrics(page, DEFAULT_EXPECTED);
    console.log('BASELINE_METRICS ' + JSON.stringify(baseline));
    assert(baseline['Chunk 数'] === '43', 'baseline chunk count');

    const upload = page.locator('[data-testid="stFileUploaderDropzoneInput"]');
    assert((await upload.count()) === 1, 'upload input not found');
    await upload.setInputFiles(RAKU);
    console.log('uploaded ' + UPLOAD_NAME + ', waiting for re-index...');

    await waitForDoc(page, UPLOAD_NAME, 900000);
    let uploaded;
    if (IS_RAKU) {
      uploaded = await waitForMetrics(page, RAKU_EXPECTED, 900000);
    } else {
      const deadline = Date.now() + 900000;
      while (Date.now() < deadline) {
        const current = metricMap(await metrics(page));
        if (Number(current['PDF 总页数'] || 0) > 0 && Number(current['Chunk 数'] || 0) > 0) {
          uploaded = current;
          break;
        }
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
      assert(uploaded, 'uploaded document never produced page/chunk metrics');
    }
    console.log('UPLOAD_METRICS ' + JSON.stringify(uploaded));

    const mainText = await page.locator('[data-testid="stMain"]').innerText();
    assert(!mainText.includes('Trendee品宣-公开版.pdf'), 'main area still references the Trendee document');
    assert(mainText.includes('文档：' + UPLOAD_NAME), 'coverage caption is not the uploaded document');

    const alerts = await mainAlerts(page);
    const errors = alerts.filter((text) => /EMBED_|索引失败|无法解析|GENERATION_FAILED/.test(text));
    assert(errors.length === 0, 'error alert after upload: ' + errors.join(' | '));
    console.log('MAIN_ALERTS ' + JSON.stringify(alerts));

    await saveScreenshot(page, '05-upload-reindex.png');

    // Optional proof that the new index is searchable, not just re-metered.
    // A generic PDF needs E2E_QUERY, because the lexical topic anchor intentionally
    // refuses a query with no term in the new corpus.
    if (!QUERY) {
      console.log('RETRIEVAL_SKIPPED set E2E_QUERY to test search for a generic PDF');
    } else {
      const topicInput = page.getByLabel('主题');
      await topicInput.fill(QUERY);
      await topicInput.press('Enter');
      await page.waitForTimeout(1200);

      await page.getByText('检索证据预览（不生成文章）', { exact: false }).first().click();
      await page.waitForTimeout(800);
      const searchButton = page.getByRole('button', { name: '检索证据' });
      await searchButton.click();
      console.log('clicked retrieval preview');

      await page.waitForFunction(
        () => /检索到 \d+ 条证据|没有检索到证据|EMBED_/.test(document.body.innerText),
        { timeout: 300000 }
      );
      const afterSearch = await page.locator('[data-testid="stMain"]').innerText();
      if (afterSearch.includes('检索到')) {
        const match = afterSearch.match(/检索到 (\d+) 条证据/);
        console.log('UPLOAD_RETRIEVAL ' + (match ? match[0] : 'found'));
        assert(afterSearch.includes(UPLOAD_NAME), 'retrieval source label is not the uploaded document');
        assert(!afterSearch.includes('Trendee品宣-公开版.pdf'), 'retrieval source label still Trendee');
        await saveScreenshot(page, '06-upload-retrieval.png');
      } else {
        await saveScreenshot(page, '06-upload-retrieval-empty.png');
        throw new Error('retrieval preview returned no evidence after re-index');
      }
    }

    const pageText = await page.locator('body').innerText();
    assert(!/sk-[A-Za-z0-9_-]{16,}/.test(pageText), 'possible API key in page text');
    console.log('PASS upload_reindex');
    await context.close();
  } finally {
    await browser.close();
  }
})().catch((err) => {
  console.error('FLOW_FAILED', err);
  process.exit(1);
});
