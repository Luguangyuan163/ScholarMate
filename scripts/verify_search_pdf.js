// 回归测试：检索结果卡片提供「打开 PDF」与「导入并翻译」，且 URL 导入
// 与本地 PDF 查看接口可用（真实 arXiv 检索 + 下载，无需真实 LLM）。
//
// 用法：
//   $env:NODE_PATH = "$env:TEMP\sm_puppeteer\node_modules"
//   node scripts/verify_search_pdf.js http://127.0.0.1:8877
const puppeteer = require("puppeteer-core");

const baseUrl = process.argv[2] || "http://127.0.0.1:8765";
const edgePath =
  process.env.EDGE_PATH ||
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function run() {
  let browser;
  let importedId = null;
  try {
    browser = await puppeteer.launch({
      executablePath: edgePath,
      headless: "new",
      args: ["--no-sandbox", "--disable-gpu"],
    });
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", (err) => errors.push("PAGEERROR " + err.message));
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push("CONSOLE " + msg.text());
    });

    await page.goto(baseUrl + "/search", { waitUntil: "networkidle2", timeout: 20000 });
    await page.type('.hero input[name="query"]', "LoRA low-rank adaptation", {
      delay: 8,
    });
    await page.click('.hero button[type="submit"]');

    await page.waitForSelector(".paper-card", { timeout: 120000 });
    await sleep(1000);
    const cardState = await page.evaluate(() => {
      const cards = Array.from(document.querySelectorAll(".paper-card"));
      const withPdf = cards.filter(
        (c) => c.querySelector('a[href*="pdf"]') !== null,
      );
      const importButtons = cards.filter(
        (c) => c.querySelector(".import-translate") !== null,
      );
      return {
        total: cards.length,
        withPdf: withPdf.length,
        importButtons: importButtons.length,
        firstPdfHref: withPdf[0]
          ? withPdf[0].querySelector('a[href*="pdf"]').getAttribute("href")
          : "",
      };
    });

    const importResult = await page.evaluate(async () => {
      const resp = await fetch("/api/pdf/import-url", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: "https://arxiv.org/pdf/2106.09685",
          title: "LoRA E2E",
        }),
      });
      return { status: resp.status, body: await resp.json().catch(() => ({})) };
    });

    const fileCheck =
      importResult.body && importResult.body.pdf_id
        ? await page.evaluate(async (id) => {
            const resp = await fetch("/api/pdf/" + id + "/file");
            const buf = await resp.arrayBuffer();
            const head = new Uint8Array(buf.slice(0, 4));
            return {
              status: resp.status,
              contentType: resp.headers.get("content-type"),
              disposition: resp.headers.get("content-disposition") || "",
              magic: String.fromCharCode(...head),
            };
          }, importResult.body.pdf_id)
        : null;
    if (importResult.body && importResult.body.pdf_id) {
      importedId = importResult.body.pdf_id;
    }

    const failures = [];
    if (cardState.total < 1 || cardState.withPdf < 1 || cardState.importButtons < 1) {
      failures.push("检索卡片缺少 PDF/导入按钮: " + JSON.stringify(cardState));
    }
    if (!/arxiv\.org\/pdf\//.test(cardState.firstPdfHref || "")) {
      failures.push("PDF 链接异常: " + cardState.firstPdfHref);
    }
    if (importResult.status !== 200 || !importResult.body.pdf_id) {
      failures.push("URL 导入失败: " + JSON.stringify(importResult));
    }
    if (
      !fileCheck ||
      fileCheck.status !== 200 ||
      fileCheck.contentType !== "application/pdf" ||
      fileCheck.magic !== "%PDF"
    ) {
      failures.push("本地 PDF 查看接口异常: " + JSON.stringify(fileCheck));
    }
    if (errors.length) failures.push("JS 错误: " + errors.join(" | "));

    if (failures.length) {
      console.error("SEARCH PDF FAILED:\n" + failures.join("\n"));
      process.exitCode = 1;
    } else {
      console.log(
        "SEARCH PDF OK: cards=" + cardState.total +
          ", pdfButtons=" + cardState.withPdf +
          ", importPdfId=" + importedId,
      );
    }
  } finally {
    if (importedId && browser) {
      try {
        const page = await browser.newPage();
        await page.goto(baseUrl + "/search", {
          waitUntil: "domcontentloaded",
          timeout: 15000,
        });
        await page.evaluate(
          (id) => fetch("/api/papers/" + id, { method: "DELETE" }),
          importedId,
        );
        await page.close();
      } catch {
        // 清理失败不影响断言结果
      }
    }
    if (browser) await browser.close();
  }
}

run().catch((err) => {
  console.error("SEARCH PDF ERROR: " + (err.stack || err.message));
  process.exit(1);
});
