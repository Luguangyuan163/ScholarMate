// 回归测试：知识图谱页与主题管理页的真实渲染与交互。
// 需要服务器已存在检索会话与论文实体（可用 scripts 里的检索流程生成）。
// 用法：node scripts/verify_graph_ui.js http://127.0.0.1:8877
const puppeteer = require("puppeteer-core");

const baseUrl = process.argv[2] || "http://127.0.0.1:8765";
const edgePath =
  process.env.EDGE_PATH ||
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitFor(page, fn, timeout = 20000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await page.evaluate(fn)) return true;
    await sleep(250);
  }
  return false;
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
    await page.setViewport({ width: 1440, height: 900 });
    const errors = [];
    page.on("pageerror", (err) => errors.push("PAGEERROR " + err.message));
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push("CONSOLE " + msg.text());
    });

    const failures = [];

    await page.goto(baseUrl + "/graph", {
      waitUntil: "networkidle2",
      timeout: 30000,
    });
    const graphReady = await waitFor(
      page,
      () => window.__graphCy && window.__graphCy.nodes().length > 0,
    );
    if (!graphReady) failures.push("图谱页未渲染出节点");

    const sessionState = await page.evaluate(() => ({
      nodes: window.__graphCy ? window.__graphCy.nodes().length : 0,
      edges: window.__graphCy ? window.__graphCy.edges().length : 0,
      canvas: document.querySelectorAll(".graph-canvas canvas").length,
      stats: ((document.querySelector(".graph-stats") || {}).textContent || "").trim(),
    }));
    if (sessionState.canvas < 1) failures.push("图谱画布未创建");
    if (!sessionState.stats.includes("论文")) failures.push("图谱统计文案缺失");

    // 点击论文节点 → 批注抽屉
    await page.evaluate(() => {
      const node = window.__graphCy.nodes('node[type="paper"]')[0];
      if (node) node.emit("tap");
    });
    const notesOpen = await waitFor(page, () => {
      const el = document.querySelector(".graph-notes");
      return el && getComputedStyle(el).display !== "none";
    }, 6000);
    if (!notesOpen) failures.push("节点详情抽屉未打开");

    // 切到历史综合图谱
    await page.evaluate(() => {
      const button = Array.from(document.querySelectorAll(".mode-switch button"))
        .find((item) => item.textContent.includes("历史综合"));
      if (button) button.click();
    });
    const globalReady = await waitFor(
      page,
      () => window.__graphCy && window.__graphCy.nodes().length > 0,
    );
    if (!globalReady) failures.push("历史综合图谱为空");

    // 主题页
    await page.goto(baseUrl + "/topics", {
      waitUntil: "networkidle2",
      timeout: 30000,
    });
    const topicsReady = await waitFor(
      page,
      () => document.querySelectorAll(".topic-card").length > 0,
    );
    if (!topicsReady) failures.push("主题页未渲染主题卡片");

    // 新建主题 → 出现在列表 → 删除（清理）
    await page.evaluate(() => {
      const button = Array.from(document.querySelectorAll(".topics-head button"))
        .find((item) => item.textContent.includes("新建主题"));
      if (button) button.click();
    });
    await waitFor(page, () => {
      const form = document.querySelector(".topic-form");
      return form && getComputedStyle(form).display !== "none";
    }, 6000);
    await page.type('.topic-form input[type="text"]', "UI回归临时主题");
    await page.evaluate(() => {
      const form = document.querySelector(".topic-form");
      form.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
    });
    const created = await waitFor(
      page,
      () =>
        Array.from(document.querySelectorAll(".topic-card h3")).some((el) =>
          el.textContent.includes("UI回归临时主题"),
        ),
    );
    if (!created) failures.push("新建主题后列表未更新");

    if (created) {
      await page.evaluate(async () => {
        const topics = await fetch("/api/topics").then((r) => r.json());
        const temp = topics.find((item) => item.name === "UI回归临时主题");
        if (temp) await fetch("/api/topics/" + temp.id, { method: "DELETE" });
      });
    }

    if (errors.length) failures.push("JS 错误: " + errors.join(" | "));

    if (failures.length) {
      console.error("GRAPH UI FAILED:\n" + failures.join("\n"));
      process.exitCode = 1;
    } else {
      console.log(
        "GRAPH UI OK: 单次图谱 " +
          sessionState.nodes +
          " 节点/" +
          sessionState.edges +
          " 边，详情抽屉可用，历史图谱可切换，主题页可新建主题",
      );
    }
  } finally {
    if (browser) await browser.close();
  }
}

run().catch((err) => {
  console.error("GRAPH UI ERROR: " + (err.stack || err.message));
  process.exit(1);
});
