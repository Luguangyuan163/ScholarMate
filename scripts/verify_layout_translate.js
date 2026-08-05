// 回归：版面对照翻译 —— 译文按原 PDF 坐标渲染、双向定位、模式切换、缩放。
// 拦截 /api/pdf/*/translate-stream 返回带 page/bbox 的确定性 SSE；页图走真实渲染端点。
// 用法：node scripts/verify_layout_translate.js http://127.0.0.1:8877 <pdfPath>
const puppeteer = require("puppeteer-core");

const baseUrl = process.argv[2] || "http://127.0.0.1:8765";
const pdfPath = process.argv[3];
const edgePath =
  process.env.EDGE_PATH ||
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const FAKE_LAYOUT_SSE =
  [
    'event: layout\ndata: {"type":"layout","pages":[{"page":1,"width":612,"height":792},{"page":2,"width":612,"height":792}],"total":4}',
    'event: segment\ndata: {"type":"segment","index":0,"page":1,"page_width":612,"page_height":792,"bbox":[72,60,500,107],"font_size":10.5,"bold":false,"source":"S1","translation":"低秩适配（LoRA）通过注入低秩矩阵减少可训练参数。","total":4}',
    'event: segment\ndata: {"type":"segment","index":1,"page":1,"page_width":612,"page_height":792,"bbox":[72,180,500,220],"font_size":10.5,"bold":true,"source":"S2","translation":"这是第二段短标题。","total":4}',
    'event: segment\ndata: {"type":"segment","index":2,"page":2,"page_width":612,"page_height":792,"bbox":[72,60,500,120],"font_size":10,"bold":false,"source":"S3","translation":"第二页的第一段译文内容。","total":4}',
    'event: segment\ndata: {"type":"segment","index":3,"page":2,"page_width":612,"page_height":792,"bbox":[72,160,500,200],"font_size":10,"bold":false,"source":"S4","translation":"第二页的第二段译文内容。","total":4}',
    'event: done\ndata: {"type":"done","total":4}',
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
          body: FAKE_LAYOUT_SSE,
        });
        return;
      }
      req.continue();
    });

    await page.goto(baseUrl + "/", { waitUntil: "networkidle2", timeout: 20000 });
    const fileInput = await page.$(".chat-main input[type='file']");
    await fileInput.uploadFile(pdfPath);
    await waitFor(
      page,
      () => document.querySelectorAll(".layout-para").length === 4,
    );

    const layoutState = await page.evaluate(() => {
      const pages = document.querySelectorAll(".layout-page");
      const paras = Array.from(document.querySelectorAll(".layout-para"));
      const zones = document.querySelectorAll(".layout-zone");
      const firstPara = paras[0] ? paras[0].getBoundingClientRect() : null;
      const firstStyle = paras[0] ? paras[0].style : null;
      const secondStyle = paras[1] ? paras[1].style : null;
      const segmentsHidden =
        document.querySelector(".segments") !== null &&
        getComputedStyle(document.querySelector(".segments")).display === "none";
      const previewOpen =
        document.querySelector(".translate-main") !== null &&
        document
          .querySelector(".translate-main")
          .classList.contains("with-preview");
      return {
        pageCount: pages.length,
        paraCount: paras.length,
        zoneCount: zones.length,
        segmentsHidden: segmentsHidden,
        previewOpen: previewOpen,
        left: firstStyle ? firstStyle.left : "",
        top: firstStyle ? firstStyle.top : "",
        fontSize: firstStyle ? firstStyle.fontSize : "",
        fontWeight: firstStyle ? firstStyle.fontWeight : "",
        secondFontWeight: secondStyle ? secondStyle.fontWeight : "",
        pageWidth: pages[0] ? Math.round(pages[0].getBoundingClientRect().width) : 0,
      };
    });

    const modeBefore = await page.evaluate(
      () => document.querySelector(".layout-pages").className,
    );
    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll(".translate-head button")).find(
        (b) => b.textContent.trim() === "叠加原文",
      );
      if (btn) btn.click();
    });
    await sleep(200);
    const modeAfter = await page.evaluate(
      () => document.querySelector(".layout-pages").className,
    );

    await page.evaluate(() => {
      const zone = document.querySelector(".layout-zone");
      if (zone) zone.dispatchEvent(new MouseEvent("mouseenter", { bubbles: true }));
    });
    await sleep(200);
    const hoverState = await page.evaluate(() => {
      const zone = document.querySelector(".layout-zone");
      const hovered = document.querySelector(".layout-para.hovered");
      return {
        zoneKey: zone ? zone.getAttribute("data-para") : "",
        hoveredKey: hovered ? hovered.getAttribute("data-para") : "",
      };
    });

    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll(".view-mode-toggle button")).find(
        (b) => b.textContent.trim() === "列表对照",
      );
      if (btn) btn.click();
    });
    await waitFor(
      page,
      () =>
        getComputedStyle(document.querySelector(".segments")).display !== "none" &&
        document.querySelector(".layout-pages") !== null &&
        getComputedStyle(document.querySelector(".layout-pages")).display === "none",
    );
    const listVisible = await page.evaluate(
      () => getComputedStyle(document.querySelector(".segments")).display !== "none",
    );

    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll(".view-mode-toggle button")).find(
        (b) => b.textContent.trim() === "版面对照",
      );
      if (btn) btn.click();
    });
    await waitFor(
      page,
      () => getComputedStyle(document.querySelector(".layout-pages")).display !== "none",
    );

    const zoomBefore = await page.evaluate(
      () => document.querySelector(".layout-page").getBoundingClientRect().width,
    );
    await page.evaluate(() => {
      Array.from(document.querySelectorAll(".preview-tools button"))
        .find((b) => b.textContent.includes("放大"))
        .click();
    });
    await sleep(400);
    const zoomAfter = await page.evaluate(
      () => document.querySelector(".layout-page").getBoundingClientRect().width,
    );

    const failures = [];
    const expectedLeft = (72 / 612) * 100;
    const expectedTop = (60 / 792) * 100;
    if (
      layoutState.pageCount !== 2 ||
      layoutState.paraCount !== 4 ||
      layoutState.zoneCount !== 4
    ) {
      failures.push("版面对照元素数量异常: " + JSON.stringify(layoutState));
    }
    if (!layoutState.segmentsHidden || !layoutState.previewOpen) {
      failures.push("布局/预览切换异常: " + JSON.stringify(layoutState));
    }
    if (
      Math.abs(parseFloat(layoutState.left) - expectedLeft) > 0.2 ||
      Math.abs(parseFloat(layoutState.top) - expectedTop) > 0.2
    ) {
      failures.push("译文坐标未对齐: " + JSON.stringify(layoutState));
    }
    if (!layoutState.fontSize || parseFloat(layoutState.fontSize) <= 0) {
      failures.push("译文字号未应用: " + JSON.stringify(layoutState));
    }
    if (layoutState.secondFontWeight !== "700") {
      failures.push("加粗段落未应用粗体: " + JSON.stringify(layoutState));
    }
    if (!modeBefore.includes("mode-translation") || !modeAfter.includes("mode-contrast")) {
      failures.push("对照/译文模式切换异常: " + modeBefore + " -> " + modeAfter);
    }
    if (!hoverState.zoneKey || hoverState.zoneKey !== hoverState.hoveredKey) {
      failures.push("悬停双向定位异常: " + JSON.stringify(hoverState));
    }
    if (!listVisible) {
      failures.push("切换回列表对照后 segments 未显示");
    }
    if (!(zoomAfter > zoomBefore)) {
      failures.push("版面对照缩放未生效: " + zoomBefore + " -> " + zoomAfter);
    }
    if (errors.length) failures.push("JS 错误: " + errors.join(" | "));

    if (failures.length) {
      console.error("LAYOUT TRANSLATE FAILED:\n" + failures.join("\n"));
      process.exitCode = 1;
    } else {
      console.log(
        "LAYOUT TRANSLATE OK: 2 pages, 4 paragraphs aligned, hover sync, modes, zoom",
      );
    }
  } finally {
    if (browser) await browser.close();
  }
}

run().catch((err) => {
  console.error("LAYOUT TRANSLATE ERROR: " + (err.stack || err.message));
  process.exit(1);
});
