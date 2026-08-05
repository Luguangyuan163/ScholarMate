// 回归：对照翻译页"原文 PDF"预览——按页渲染原排版、可展开/收起、图片真实加载。
// 拦截 /api/pdf/*/translate-stream 返回确定性 SSE；页面图片走真实渲染端点。
// 用法：node scripts/verify_pdf_preview.js http://127.0.0.1:8877 <pdfPath>
const puppeteer = require("puppeteer-core");

const baseUrl = process.argv[2] || "http://127.0.0.1:8765";
const pdfPath = process.argv[3];
const edgePath =
  process.env.EDGE_PATH ||
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const FAKE_TRANSLATE_SSE =
  [
    'event: progress\ndata: {"type":"progress","done":0,"total":2}',
    'event: segment\ndata: {"type":"segment","index":0,"source":"S1","translation":"T1","total":2}',
    'event: segment\ndata: {"type":"segment","index":1,"source":"S2","translation":"T2","total":2}',
    'event: done\ndata: {"type":"done","total":2}',
  ].join("\n\n") + "\n\n";

async function waitFor(page, fn, timeout = 15000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await page.evaluate(fn)) return;
    await sleep(250);
  }
  throw new Error("waitFor 超时: " + fn.toString());
}

async function run() {
  let browser;
  try {
    browser = await puppeteer.launch({
      executablePath: edgePath,
      headless: "new",
      args: ["--no-sandbox", "--disable-gpu"],
    });
    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 800 });
    const errors = [];
    page.on("pageerror", (err) => errors.push("PAGEERROR " + err.message));
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push("CONSOLE " + msg.text());
    });

    await page.setRequestInterception(true);
    page.on("request", (req) => {
      if (req.url().includes("/translate-stream")) {
        req.respond({
          status: 200,
          contentType: "text/event-stream",
          headers: { "Cache-Control": "no-cache" },
          body: FAKE_TRANSLATE_SSE,
        });
        return;
      }
      req.continue();
    });

    await page.goto(baseUrl + "/", { waitUntil: "networkidle2", timeout: 20000 });
    const fileInput = await page.$(".chat-main input[type='file']");
    await fileInput.uploadFile(pdfPath);
    await waitFor(page, () => document.querySelectorAll(".segment").length === 2);

    await page.evaluate(() => {
      document.querySelector(".preview-toggle").click();
    });
    await waitFor(
      page,
      () =>
        document.querySelectorAll(".preview-page img").length === 2 &&
        document.querySelectorAll(".preview-page img")[0].naturalWidth > 0,
    );

    const openState = await page.evaluate(() => {
      const aside = document.querySelector(".translate-preview");
      const toggle = document.querySelector(".preview-toggle");
      const imgs = Array.from(document.querySelectorAll(".preview-page img"));
      return {
        visible:
          aside !== null && getComputedStyle(aside).display !== "none",
        count: document.querySelectorAll(".preview-page").length,
        loaded: imgs.every((img) => img.naturalWidth > 0),
        countText: document.querySelector(".preview-count")
          ? document.querySelector(".preview-count").textContent.trim()
          : "",
        toggleText: toggle ? toggle.textContent.trim() : "",
        src0: imgs[0] ? imgs[0].src : "",
        sideBySide: (() => {
          const seg = document.querySelector(".segments").getBoundingClientRect();
          const pre = document.querySelector(".translate-preview").getBoundingClientRect();
          return pre.x >= seg.x + seg.width - 5 && pre.y < seg.y + seg.height;
        })(),
      };
    });

    await page.evaluate(() => {
      document.querySelector(".preview-toggle").click();
    });
    await sleep(500);
    const closed = await page.evaluate(() => {
      const aside = document.querySelector(".translate-preview");
      return aside === null || getComputedStyle(aside).display === "none";
    });

    const failures = [];
    if (!openState.visible) failures.push("原文预览面板未显示");
    if (openState.count !== 2) failures.push("页数错误: " + openState.count);
    if (!openState.loaded) failures.push("存在未加载成功的页面图片");
    if (!openState.countText.includes("2")) {
      failures.push("页数文本异常: " + openState.countText);
    }
    if (openState.toggleText !== "收起原文") {
      failures.push("展开后按钮文案异常: " + openState.toggleText);
    }
    if (!openState.src0.includes("/api/pdf/") || !openState.src0.includes("pages/1/image")) {
      failures.push("图片 src 异常: " + openState.src0);
    }
    if (!openState.sideBySide) failures.push("原文与翻译未左右分栏显示");
    if (!closed) failures.push("收起后预览面板未隐藏");
    if (errors.length) failures.push("JS 错误: " + errors.join(" | "));

    if (failures.length) {
      console.error("PDF PREVIEW FAILED:\n" + failures.join("\n"));
      process.exitCode = 1;
    } else {
      console.log(
        "PDF PREVIEW OK: 2 pages rendered, images loaded, toggle works",
      );
    }
  } finally {
    if (browser) await browser.close();
  }
}

run().catch((err) => {
  console.error("PDF PREVIEW ERROR: " + (err.stack || err.message));
  process.exit(1);
});
