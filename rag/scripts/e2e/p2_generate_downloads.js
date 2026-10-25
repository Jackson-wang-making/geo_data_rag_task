/** Generate a real article and click both Streamlit download buttons. */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const {
  ART,
  OUT,
  assert,
  launch,
  newPage,
  hideDeploy,
  waitForMetrics,
  waitForDoc,
  artifactDirFromCaption,
  normalizeNewlines,
  saveScreenshot,
} = require('./lib_streamlit');

const TOPIC = '为什么中国出海品牌需要 GEO 优化';
const DEFAULT_EXPECTED = {
  'PDF 总页数': 36,
  '有 chunk 的页': 33,
  '无 chunk 的页': 3,
  'OCR 不可用页': 0,
  'Chunk 数': 43,
};

function sha256(text) {
  return crypto.createHash('sha256').update(text, 'utf8').digest('hex');
}

(async () => {
  const browser = await launch();
  const { context, page } = await newPage(browser);
  try {
    await page.goto('http://127.0.0.1:8501', { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForSelector('text=PDF 总页数', { timeout: 600000 });
    await hideDeploy(page);
    await waitForDoc(page, 'Trendee品宣-公开版.pdf');
    await waitForMetrics(page, DEFAULT_EXPECTED, 600000);

    const topicInput = page.getByLabel('主题');
    await topicInput.fill(TOPIC);
    await topicInput.press('Enter');

    const generate = page.getByRole('button', { name: '生成文章' });
    await generate.waitFor({ state: 'visible', timeout: 120000 });
    let enabled = false;
    for (let i = 0; i < 120; i++) {
      if (await generate.isEnabled()) {
        enabled = true;
        break;
      }
      await page.waitForTimeout(500);
    }
    assert(enabled, 'generate button never became enabled');
    console.log('clicking generate (real DeepSeek call, one click)');
    await generate.click();

    await page.waitForSelector('text=生成结果', { timeout: 1200000 });
    await page.waitForFunction(
      () =>
        /引用校验通过|文章状态为 partial|现有资料不足以支持|GENERATION_FAILED|LLM_UNAVAILABLE/.test(
          document.body.innerText
        ),
      { timeout: 1200000 }
    );
    await page.waitForTimeout(1500);

    const bodyText = await page.locator('body').innerText();
    if (bodyText.includes('引用校验通过')) {
      console.log('ARTICLE_STATUS complete');
    } else if (bodyText.includes('文章状态为 partial')) {
      console.log('ARTICLE_STATUS partial');
    } else {
      console.log('ARTICLE_BODY_HEAD\n' + bodyText.slice(0, 3000));
      throw new Error('generation did not produce a complete/partial article');
    }

    await page.getByText('下载本次产物', { exact: false }).first().waitFor({ timeout: 120000 });
    const downloadButtons = page.locator('[data-testid="stDownloadButton"] button');
    const buttonCount = await downloadButtons.count();
    assert(buttonCount === 2, `expected 2 download buttons, found ${buttonCount}`);

    const articleButton = page.getByRole('button', { name: '下载 article.md', exact: true });
    const evidenceButton = page.getByRole('button', { name: '下载 evidence.json', exact: true });
    assert((await articleButton.count()) === 1, 'article download button not found');
    assert((await evidenceButton.count()) === 1, 'evidence download button not found');

    const runDir = await artifactDirFromCaption(page);
    const resolved = path.resolve(runDir);
    const relative = path.relative(path.resolve(ART), resolved);
    assert(relative && !relative.startsWith('..') && !path.isAbsolute(relative), `run dir outside artifacts: ${runDir}`);
    const runId = path.basename(resolved);
    assert(fs.existsSync(path.join(resolved, 'article.md')), 'artifact article.md missing');
    assert(fs.existsSync(path.join(resolved, 'evidence.json')), 'artifact evidence.json missing');
    console.log('RUN_DIR ' + resolved);
    console.log('RUN_ID ' + runId);

    await saveScreenshot(page, '07-article-downloads.png', true);

    const downloadDir = path.join(OUT, 'downloads', runId);
    fs.mkdirSync(downloadDir, { recursive: true });

    const articleSave = path.join(downloadDir, 'article.md');
    const [articleDownload] = await Promise.all([
      page.waitForEvent('download', { timeout: 60000 }),
      articleButton.click(),
    ]);
    await articleDownload.saveAs(articleSave);
    assert((await articleDownload.failure()) === null, 'article download failed');
    console.log('ARTICLE_SUGGESTED ' + articleDownload.suggestedFilename());

    const evidenceSave = path.join(downloadDir, 'evidence.json');
    const [evidenceDownload] = await Promise.all([
      page.waitForEvent('download', { timeout: 60000 }),
      evidenceButton.click(),
    ]);
    await evidenceDownload.saveAs(evidenceSave);
    assert((await evidenceDownload.failure()) === null, 'evidence download failed');
    console.log('EVIDENCE_SUGGESTED ' + evidenceDownload.suggestedFilename());

    const downloadedArticle = fs.readFileSync(articleSave, 'utf8');
    const artifactArticle = fs.readFileSync(path.join(resolved, 'article.md'), 'utf8');
    const downloadedEvidenceText = fs.readFileSync(evidenceSave, 'utf8');
    const artifactEvidenceText = fs.readFileSync(path.join(resolved, 'evidence.json'), 'utf8');

    assert(
      normalizeNewlines(downloadedArticle) === normalizeNewlines(artifactArticle),
      'downloaded article content differs from artifact (after CRLF normalization)'
    );
    const downloadedEvidence = JSON.parse(downloadedEvidenceText);
    const artifactEvidence = JSON.parse(artifactEvidenceText);
    assert(
      JSON.stringify(downloadedEvidence) === JSON.stringify(artifactEvidence),
      'downloaded evidence JSON differs from artifact'
    );
    assert(downloadedEvidence.run_id === runId, 'downloaded evidence run_id mismatch');

    console.log('ARTICLE_BYTES ' + fs.statSync(articleSave).size + ' ARTIFACT_BYTES ' + Buffer.byteLength(artifactArticle));
    console.log('ARTICLE_SHA_DOWNLOADED ' + sha256(downloadedArticle));
    console.log('ARTICLE_SHA_ARTIFACT ' + sha256(artifactArticle));
    console.log('EVIDENCE_SHA_DOWNLOADED ' + sha256(downloadedEvidenceText));
    console.log('EVIDENCE_SHA_ARTIFACT ' + sha256(artifactEvidenceText));
    console.log('NORMALIZED_EQUAL true');

    const downloadText = downloadedArticle + downloadedEvidenceText;
    assert(!/sk-[A-Za-z0-9_-]{16,}/.test(downloadText), 'possible API key in downloaded artifacts');
    assert(!/Bearer\s+[A-Za-z0-9._-]{16,}/.test(downloadText), 'possible bearer token in downloads');
    console.log('SECRET_SCAN_CLEAN true');

    await saveScreenshot(page, '08-after-downloads.png', true);
    console.log('PASS generate_downloads');
    await context.close();
  } finally {
    await browser.close();
  }
})().catch((err) => {
  console.error('FLOW_FAILED', err);
  process.exit(1);
});
