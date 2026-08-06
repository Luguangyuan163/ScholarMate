// 回归测试：聊天气泡按内容自适应宽度——短消息不得默认撑满、长消息受上限约束，
// 用户气泡右对齐。
// 拦截 /api/agent/chat-stream：第一轮返回短消息、第二轮返回长消息，
// 分别测量两个助手气泡的实际渲染宽度。
//
// 用法：node scripts/verify_chat_bubbles.js http://127.0.0.1:8877
const puppeteer = require("puppeteer-core");

const baseUrl = process.argv[2] || "http://127.0.0.1:8765";
const edgePath =
  process.env.EDGE_PATH ||
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const SHORT_TEXT = "好的，已为你完成检索。";
const LONG_TEXT =
  "低秩适配（Low-Rank Adaptation, LoRA）是一种参数高效的微调方法，它通过冻结预训练权重并注入低秩矩阵来减少可训练参数量，从而在保持下游任务性能的同时显著降低显存与算力开销。" +
  "该方法在保持下游任务性能的同时显著降低显存与算力开销，已在自然语言处理与多模态模型上被广泛采用。" +
  "低秩适配通过冻结预训练权重并注入低秩矩阵来减少可训练参数量，从而在保持下游任务性能的同时显著降低显存与算力开销。";

const FAKE_SSE_SHORT =
  [
    'event: message\ndata: {"type":"message","content":"' + SHORT_TEXT + '"}',
    'event: done\ndata: {"type":"done"}',
  ].join("\n\n") + "\n\n";

const FAKE_SSE_LONG =
  [
    'event: message\ndata: {"type":"message","content":"' + LONG_TEXT + '"}',
    'event: done\ndata: {"type":"done"}',
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
  let createdConvId = null;
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

    let streamCount = 0;
    await page.setRequestInterception(true);
    page.on("request", (req) => {
      if (req.url().includes("/api/agent/chat-stream")) {
        streamCount += 1;
        req.respond({
          status: 200,
          contentType: "text/event-stream",
          headers: { "Cache-Control": "no-cache" },
          body: streamCount === 1 ? FAKE_SSE_SHORT : FAKE_SSE_LONG,
        });
        return;
      }
      req.continue();
    });

    await page.goto(baseUrl + "/agent", {
      waitUntil: "networkidle2",
      timeout: 20000,
    });
    await page.evaluate(() => localStorage.setItem("sm_auto_save", "0"));
    await page.type(
      'input[type="text"][placeholder*="输入问题"]',
      "测试气泡尺寸",
      { delay: 5 },
    );
    await page.click('button[type="submit"]');
    await waitFor(
      page,
      () =>
        document.querySelectorAll(".chat-msg.assistant").length >= 1 &&
        Array.from(document.querySelectorAll(".chat-msg.assistant")).some(
          (el) => el.textContent.includes("好的，已为你完成检索"),
        ),
    );
    await page.type(
      'input[type="text"][placeholder*="输入问题"]',
      "第二个问题",
      { delay: 5 },
    );
    await page.click('button[type="submit"]');
    await waitFor(
      page,
      () => document.querySelectorAll(".chat-msg.assistant").length >= 2,
    );

    const measure = await page.evaluate(() => {
      const log = document.querySelector(".chat-log");
      const logRect = log.getBoundingClientRect();
      const assts = Array.from(document.querySelectorAll(".chat-msg.assistant"));
      const users = Array.from(document.querySelectorAll(".chat-msg.user"));
      const userRect = users.length ? users[0].getBoundingClientRect() : null;
      return {
        logWidth: logRect.width,
        logRight: logRect.right,
        widths: assts.map((el) => Math.round(el.getBoundingClientRect().width)),
        userRight: userRect ? Math.round(userRect.right) : null,
      };
    });

    const convs = await page.evaluate(async () => {
      const resp = await fetch("/api/conversations");
      if (!resp.ok) return [];
      return (await resp.json()).filter((c) => c.title === "测试气泡尺寸");
    });
    if (convs.length) createdConvId = convs[0].id;
    if (createdConvId) {
      await page.evaluate(async (id) => {
        await fetch("/api/conversations/" + id, { method: "DELETE" });
      }, createdConvId);
    }

    const shortWidth = measure.widths[0];
    const longWidth = measure.widths[1];
    const failures = [];
    if (measure.widths.length !== 2) {
      failures.push("助手气泡数量异常: " + JSON.stringify(measure.widths));
    }
    if (!(shortWidth < longWidth)) {
      failures.push(
        "短消息气泡未按内容收缩: short=" + shortWidth + " long=" + longWidth,
      );
    }
    if (!(shortWidth < measure.logWidth * 0.7)) {
      failures.push(
        "短消息气泡仍默认过大: width=" + shortWidth + " logWidth=" + measure.logWidth,
      );
    }
    if (!(longWidth <= measure.logWidth * 0.85)) {
      failures.push(
        "长消息气泡超过宽度上限: width=" + longWidth + " logWidth=" + measure.logWidth,
      );
    }
    if (
      measure.userRight === null ||
      measure.userRight < measure.logRight - 30 ||
      measure.userRight > measure.logRight + 2
    ) {
      failures.push(
        "用户气泡未右对齐: userRight=" + measure.userRight + " logRight=" + measure.logRight,
      );
    }
    if (errors.length) failures.push("JS 错误: " + errors.join(" | "));

    if (failures.length) {
      console.error("CHAT BUBBLES FAILED:\n" + failures.join("\n"));
      process.exitCode = 1;
    } else {
      console.log(
        "CHAT BUBBLES OK: short=" +
          shortWidth +
          "px long=" +
          longWidth +
          "px logWidth=" +
          measure.logWidth +
          "px, user right-aligned",
      );
    }
  } finally {
    if (browser) await browser.close();
  }
}

run().catch((err) => {
  console.error("CHAT BUBBLES ERROR: " + (err.stack || err.message));
  process.exit(1);
});
