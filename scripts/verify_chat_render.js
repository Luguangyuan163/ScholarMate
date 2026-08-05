// 回归测试：对话回复必须实时渲染到 DOM（无需离开/重新进入会话），
// 且 EventSource 流式 + 工具状态反馈正常。
// 拦截 /api/agent/chat-stream 返回确定性 SSE，避免依赖真实 LLM；同时覆盖
// 「普通浏览器」与「WebView2（pywebview 桌面窗口）模拟」两种环境。
//
// 用法：
//   $env:NODE_PATH = "$env:TEMP\sm_puppeteer\node_modules"
//   node scripts/verify_chat_render.js http://127.0.0.1:8877 normal
//   node scripts/verify_chat_render.js http://127.0.0.1:8877 webview2
const puppeteer = require("puppeteer-core");

const baseUrl = process.argv[2] || "http://127.0.0.1:8765";
const scenario = process.argv[3] || "normal";
const edgePath =
  process.env.EDGE_PATH ||
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const EXPECTED_REPLY = "回复第一段内容。回复第二段内容。";
const FAKE_SSE =
  [
    'event: tool_call\ndata: {"type":"tool_call","name":"search_arxiv","arguments":{}}',
    'event: tool_result\ndata: {"type":"tool_result","name":"search_arxiv","content":"[{\\"title\\":\\"Paper A\\"},{\\"title\\":\\"Paper B\\"}]"}',
    'event: message\ndata: {"type":"message","content":"回复第一段内容。"}',
    'event: message\ndata: {"type":"message","content":"回复第二段内容。"}',
    'event: done\ndata: {"type":"done"}',
  ].join("\n\n") + "\n\n";

async function run() {
  let browser;
  let page;
  let createdConvId = null;
  try {
    browser = await puppeteer.launch({
      executablePath: edgePath,
      headless: "new",
      args: ["--no-sandbox", "--disable-gpu"],
    });
    page = await browser.newPage();
    const errors = [];
    page.on("pageerror", (err) => errors.push("PAGEERROR " + err.message));
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push("CONSOLE " + msg.text());
    });

    if (scenario === "webview2") {
      await page.evaluateOnNewDocument(() => {
        if (window.chrome && !window.chrome.webview) {
          Object.defineProperty(window.chrome, "webview", {
            value: {},
            configurable: true,
          });
        } else if (!window.chrome) {
          Object.defineProperty(window, "chrome", {
            value: { webview: {} },
            configurable: true,
          });
        }
      });
    }

    await page.setRequestInterception(true);
    page.on("request", (req) => {
      if (req.url().includes("/api/agent/chat-stream")) {
        req.respond({
          status: 200,
          contentType: "text/event-stream",
          headers: { "Cache-Control": "no-cache" },
          body: FAKE_SSE,
        });
        return;
      }
      if (req.url().includes("/api/agent/chat")) {
        // 旧 POST 端点不应再被前端调用
        req.respond({
          status: 501,
          contentType: "application/json",
          body: JSON.stringify({ detail: "obsolete endpoint" }),
        });
        return;
      }
      req.continue();
    });

    await page.goto(baseUrl + "/", { waitUntil: "networkidle2", timeout: 20000 });
    await page.evaluate(() => localStorage.setItem("sm_auto_save", "0"));
    await page.type(
      'input[type="text"][placeholder*="输入问题"]',
      "测试消息",
      { delay: 10 },
    );
    await page.click('button[type="submit"]');
    await sleep(8000);

    const domTexts = await page.evaluate(() =>
      Array.from(document.querySelectorAll(".chat-msg")).map((m) =>
        m.textContent.trim(),
      ),
    );
    const feedbackState = await page.evaluate(() => {
      const tags = Array.from(document.querySelectorAll(".tool-tag")).map((t) =>
        t.textContent.trim(),
      );
      const lastAssistant = Array.from(
        document.querySelectorAll(".chat-msg.assistant"),
      ).pop();
      const status = lastAssistant
        ? lastAssistant.querySelector(".msg-status")
        : null;
      return {
        toolTags: tags,
        statusVisible:
          status !== null &&
          status.getAttribute("style") !== null &&
          !status.getAttribute("style").includes("display: none"),
      };
    });

    const convData = await page.evaluate(async () => {
      const resp = await fetch("/api/conversations");
      if (!resp.ok) return { ok: false, status: resp.status, convs: [] };
      const convs = await resp.json();
      const mine = convs.find((c) => c.title === "测试消息");
      if (!mine) return { ok: true, convs: [] };
      const detail = await fetch("/api/conversations/" + mine.id);
      const data = await detail.json();
      return {
        ok: true,
        convId: mine.id,
        messages: data.messages.map((m) => ({ role: m.role, content: m.content })),
      };
    });
    if (convData.ok && convData.convId) createdConvId = convData.convId;
    if (createdConvId) {
      await page
        .evaluate(
          async (id) => {
            const resp = await fetch("/api/conversations/" + id, {
              method: "DELETE",
            });
            return resp.status;
          },
          createdConvId,
        )
        .catch(() => {});
    }

    const failures = [];
    if (!domTexts.some((t) => t.includes(EXPECTED_REPLY))) {
      failures.push(
        "回复未实时渲染到 DOM（当前消息: " + JSON.stringify(domTexts) + "）",
      );
    }
    if (!feedbackState.toolTags.includes("search_arxiv")) {
      failures.push("工具状态标签未渲染: " + JSON.stringify(feedbackState.toolTags));
    }
    if (feedbackState.statusVisible) {
      failures.push("完成后状态反馈未收起");
    }
    const savedAssistant = (convData.messages || []).filter(
      (m) => m.role === "assistant" && m.content.includes(EXPECTED_REPLY),
    );
    if (!savedAssistant.length) {
      failures.push("回复未成功入库: " + JSON.stringify(convData));
    }
    if (errors.length) failures.push("JS 错误: " + errors.join(" | "));

    if (failures.length) {
      console.error(
        "CHAT RENDER FAILED [" + scenario + "]:\n" + failures.join("\n"),
      );
      process.exitCode = 1;
    } else {
      console.log(
        "CHAT RENDER OK [" + scenario +
          "] reply rendered live and persisted (messages=" + domTexts.length + ")",
      );
    }
  } finally {
    if (browser) await browser.close();
  }
}

run().catch((err) => {
  console.error("CHAT RENDER ERROR: " + (err.stack || err.message));
  process.exit(1);
});
