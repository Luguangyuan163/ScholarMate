// 回归：上传 PDF 后立即进入翻译视图；翻译流 status 心跳与上传进度轮询正常渲染。
// 拦截 /api/pdf/*/translate-stream 返回确定性 SSE，避免真实 LLM 调用。
// 用法：node scripts/verify_upload_flow.js http://127.0.0.1:8877 <pdfPath>
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
    'event: status\ndata: {"type":"status","content":"正在翻译剩余 2 段（已输出 0/2 段）…"}',
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
    const errors = [];
    page.on("pageerror", (err) => errors.push("PAGEERROR " + err.message));
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push("CONSOLE " + msg.text());
    });
    page.on("framenavigated", (frame) => {
      if (frame === page.mainFrame()) {
        console.log("NAVIGATED TO", frame.url());
      }
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
    if (!page.url().startsWith(baseUrl + "/") || page.url().includes("?")) {
      throw new Error("上传后不应整页跳转，当前 url=" + page.url());
    }

    await waitFor(page, () => document.querySelectorAll(".segment").length === 2);
    const state = await page.evaluate(() => {
      const translate = document.querySelector(".translate-main");
      const status = document.querySelector(".translate-status");
      const upload = document.querySelector(".translate-status.upload");
      return {
        translateVisible:
          translate !== null &&
          getComputedStyle(translate).display !== "none",
        segments: document.querySelectorAll(".segment").length,
        status: status ? status.textContent.trim() : "",
        uploadStatus: upload ? upload.textContent.trim() : "",
      };
    });

    await sleep(3000);
    const uploadAfter = await page.evaluate(() => {
      const upload = document.querySelector(".translate-status.upload");
      return upload ? upload.textContent.trim() : "";
    });

    const failures = [];
    if (!state.translateVisible) failures.push("翻译视图未打开");
    if (state.segments !== 2) failures.push("段落未渲染: " + state.segments);
    if (!state.status.includes("翻译完成")) {
      failures.push("翻译状态异常: " + state.status);
    }
    if (!uploadAfter.includes("文档已处理完成")) {
      failures.push("上传进度轮询未完成: " + uploadAfter);
    }
    if (errors.length) failures.push("JS 错误: " + errors.join(" | "));

    if (failures.length) {
      console.error("UPLOAD FLOW FAILED:\n" + failures.join("\n"));
      process.exitCode = 1;
    } else {
      console.log(
        "UPLOAD FLOW OK: translate view immediate, 2 segments, status=" +
          state.status +
          ", upload=" +
          uploadAfter,
      );
    }
  } finally {
    if (browser) await browser.close();
  }
}

run().catch((err) => {
  console.error("UPLOAD FLOW ERROR: " + (err.stack || err.message));
  process.exit(1);
});
