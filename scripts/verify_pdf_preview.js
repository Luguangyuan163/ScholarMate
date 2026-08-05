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
        mainWidth: Math.round(
          document.querySelector(".translate-main").getBoundingClientRect().width,
        ),
        count: document.querySelectorAll(".preview-page").length,
        loaded: imgs.every((img) => img.naturalWidth > 0),
        countText: document.querySelector(".preview-count")
          ? document.querySelector(".preview-count").textContent.trim()
          : "",
        toggleText: toggle ? toggle.textContent.trim() : "",
        src0: imgs[0] ? imgs[0].src : "",
        previewLeft: (() => {
          const seg = document.querySelector(".segments").getBoundingClientRect();
          const pre = document.querySelector(".translate-preview").getBoundingClientRect();
          return pre.x + pre.width <= seg.x + 5 && pre.y < seg.y + seg.height;
        })(),
        splitRatio: (() => {
          const main = document.querySelector(".translate-main");
          const cols = getComputedStyle(main)
            .gridTemplateColumns.split(" ")
            .map((s) => parseFloat(s));
          if (cols.length !== 2) return -1;
          return Math.max(cols[0], cols[1]) / (cols[0] + cols[1]);
        })(),
      };
    });

    const zoomBefore = await page.evaluate(
      () => document.querySelector(".preview-page img").getBoundingClientRect().width,
    );
    await page.evaluate(() => {
      Array.from(document.querySelectorAll(".preview-tools button"))
        .find((b) => b.textContent.includes("放大"))
        .click();
    });
    await sleep(300);
    const zoomAfter = await page.evaluate(
      () => document.querySelector(".preview-page img").getBoundingClientRect().width,
    );
    const zoomLeftReachable = await page.evaluate(() => {
      const pages = document.querySelector(".preview-pages");
      pages.scrollLeft = 0;
      const img = document.querySelector(".preview-page img").getBoundingClientRect();
      const pr = pages.getBoundingClientRect();
      return img.left >= pr.left - 1;
    });
    await page.evaluate(() => {
      Array.from(document.querySelectorAll(".preview-tools button"))
        .find((b) => b.textContent.includes("适应"))
        .click();
    });
    await sleep(300);
    const zoomFit = await page.evaluate(
      () => document.querySelector(".preview-page img").getBoundingClientRect().width,
    );

    await page.evaluate(() => {
      Array.from(document.querySelectorAll(".preview-tools button"))
        .find((b) => b.textContent.includes("全屏"))
        .click();
    });
    await sleep(400);
    const fs = await page.evaluate(() => {
      const aside = document.querySelector(".translate-preview");
      const r = aside.getBoundingClientRect();
      return {
        isFullscreen: aside.classList.contains("fullscreen"),
        position: getComputedStyle(aside).position,
        w: Math.round(r.width),
        h: Math.round(r.height),
        winW: window.innerWidth,
        winH: window.innerHeight,
      };
    });
    await page.evaluate(() => {
      Array.from(document.querySelectorAll(".preview-tools button"))
        .find((b) => b.textContent.includes("全屏"))
        .click();
    });
    await sleep(400);
    const fsExited = await page.evaluate(() => {
      const aside = document.querySelector(".translate-preview");
      return aside !== null && !aside.classList.contains("fullscreen");
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
    if (openState.mainWidth < 900) {
      failures.push("翻译界面宽度不足: " + openState.mainWidth);
    }
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
    if (!openState.previewLeft) failures.push("原文未显示在左侧");
    if (Math.abs(openState.splitRatio - 0.5) > 0.05) {
      failures.push("原文与译文占比不是各一半: " + openState.splitRatio);
    }
    if (!(zoomAfter > zoomBefore + 5)) {
      failures.push("放大未生效: " + zoomBefore + " -> " + zoomAfter);
    }
    if (!zoomLeftReachable) failures.push("放大后图片左侧不可达（被遮挡）");
    if (!(Math.abs(zoomFit - zoomBefore) < 5)) {
      failures.push("适应宽度未恢复: " + zoomBefore + " -> " + zoomFit);
    }
    if (!fs.isFullscreen || fs.position !== "fixed") {
      failures.push("全屏模式未生效: " + JSON.stringify(fs));
    }
    if (fs.w < fs.winW - 40 || fs.h < fs.winH - 40) {
      failures.push("全屏未覆盖窗口: " + JSON.stringify(fs));
    }
    if (!fsExited) failures.push("退出全屏失败");
    if (!openState.src0.includes("scale=3")) {
      failures.push("未使用高清渲染(scale=3): " + openState.src0);
    }
    if (!closed) failures.push("收起后预览面板未隐藏");
    if (errors.length) failures.push("JS 错误: " + errors.join(" | "));

    if (failures.length) {
      console.error("PDF PREVIEW FAILED:\n" + failures.join("\n"));
      process.exitCode = 1;
    } else {
      console.log(
        "PDF PREVIEW OK: original on left, zoom + fullscreen work, chart text skipped",
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
