// UI 冒烟验证（可选工具）：驱动 Edge/Chrome 打开工作台，
// 输入文字 → 点击发送 → 断言无 Alpine 错误且消息成功发送。
//
// 用法（需要 Node + puppeteer-core）：
//   npm install --prefix %TEMP%\sm_puppeteer puppeteer-core --no-save
//   $env:NODE_PATH = "$env:TEMP\sm_puppeteer\node_modules"
//   $env:EDGE_PATH = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
//   node scripts/verify_ui.js http://127.0.0.1:8765
//
// 回归点：Alpine 3.14 CDN 构建在脚本加载后立即启动，
// 组件函数（chatApp / appSidebar）必须在 alpine.min.js 之前定义。

const puppeteer = require("puppeteer-core");

const baseUrl = process.argv[2] || "http://127.0.0.1:8765";
const edgePath =
  process.env.EDGE_PATH ||
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

(async () => {
  const browser = await puppeteer.launch({
    executablePath: edgePath,
    headless: "new",
    args: ["--no-sandbox", "--disable-gpu"],
  });
  const page = await browser.newPage();
  const errors = [];
  page.on("console", (msg) => {
    if (msg.type() === "error" || msg.type() === "warn") {
      errors.push(`CONSOLE[${msg.type()}] ${msg.text()}`);
    }
  });
  page.on("pageerror", (err) => errors.push(`PAGEERROR ${err.message}`));

  await page.goto(baseUrl + "/", { waitUntil: "networkidle2", timeout: 20000 });
  await page.type(
    'input[type="text"][placeholder*="输入问题"]',
    "你好",
    { delay: 15 },
  );
  await sleep(400);
  const buttonDisabled = await page.$eval(
    'button[type="submit"]',
    (btn) => btn.disabled,
  );
  await page.click('button[type="submit"]');
  const deadline = Date.now() + 30000;
  let replyText = "";
  while (Date.now() < deadline) {
    replyText = await page.$$eval(
      ".chat-msg",
      (els) => (els.length > 1 ? els[els.length - 1].textContent.trim() : ""),
    );
    if (replyText) break;
    await sleep(500);
  }
  const messageCount = await page.$$eval(".chat-msg", (els) => els.length);

  const failures = [];
  if (errors.length) failures.push("Alpine/JS errors: " + errors.join(" | "));
  if (buttonDisabled) failures.push("发送按钮在输入后仍为禁用状态");
  if (messageCount < 2) failures.push(`消息未发送（仅 ${messageCount} 条）`);
  if (!replyText) failures.push("AI 回复内容未实时渲染到界面（重进会话才显示的回归）");

  console.log(
    failures.length
      ? "UI SMOKE FAILED:\n" + failures.join("\n")
      : `UI SMOKE OK (messages=${messageCount}, no JS errors)`,
  );
  await browser.close();
  process.exit(failures.length ? 1 : 0);
})().catch((err) => {
  console.error("UI SMOKE ERROR: " + (err.stack || err.message));
  process.exit(1);
});
