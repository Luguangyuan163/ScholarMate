// 回归测试：翻译记录页——已保存版本列表、查看对照、删除。
// 需要服务器使用独立临时数据库运行；脚本自行种入数据并清理。
//
// 用法（服务器需以临时库启动）：
//   node scripts/verify_translate_history.js http://127.0.0.1:8877 <dbPath> <uploadDir>
const puppeteer = require("puppeteer-core");
const { DatabaseSync } = require("node:sqlite");

const baseUrl = process.argv[2] || "http://127.0.0.1:8765";
const dbPath = process.argv[3];
const uploadDir = process.argv[4];
const edgePath =
  process.env.EDGE_PATH ||
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitFor(page, fn, timeout = 8000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await page.evaluate(fn)) return;
    await sleep(250);
  }
  throw new Error("waitFor 超时: " + fn.toString());
}

function seedData() {
  const db = new DatabaseSync(dbPath);
  db.prepare(
    "INSERT INTO uploaded_pdfs (filename, original_name, file_path, status, created_at) " +
      "VALUES (?, ?, ?, ?, datetime('now'))",
  ).run("hist-seed.pdf", "历史论文.pdf", uploadDir + "\\hist.pdf", "ready");
  const pdfId = db
    .prepare("SELECT id FROM uploaded_pdfs WHERE filename = ?")
    .get("hist-seed.pdf").id;
  db.prepare(
    "INSERT INTO translation_records (pdf_id, filename, target_lang, segments_json, total, created_at) " +
      "VALUES (?, ?, ?, ?, ?, datetime('now'))",
  ).run(
    pdfId,
    "历史论文.pdf",
    "zh",
    JSON.stringify([
      { source: "First sentence of paper.", translation: "论文的第一句。" },
      { source: "Second sentence of paper.", translation: "论文的第二句。" },
    ]),
    2,
  );
  db.close();
}

function cleanupDb() {
  const db = new DatabaseSync(dbPath);
  db.exec("DELETE FROM translation_records WHERE filename = '历史论文.pdf'");
  db.exec("DELETE FROM uploaded_pdfs WHERE filename = 'hist-seed.pdf'");
  db.close();
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
    page.on("dialog", (dialog) => dialog.accept());

    seedData();
    await page.goto(baseUrl + "/translate", {
      waitUntil: "networkidle2",
      timeout: 20000,
    });
    await waitFor(page, () => document.querySelectorAll(".history-item").length === 1);

    const listState = await page.evaluate(() => ({
      count: document.querySelectorAll(".history-item").length,
      name: document.querySelector(".history-name")
        ? document.querySelector(".history-name").textContent.trim()
        : "",
    }));

    await page.evaluate(() => {
      const item = document.querySelector(".history-item");
      item.querySelector('button[class*="btn-outline"]').click();
    });
    await waitFor(page, () => document.querySelectorAll(".segment").length === 2);
    const viewState = await page.evaluate(() => {
      const segments = Array.from(document.querySelectorAll(".segment")).map((s) =>
        s.textContent.trim(),
      );
      return {
        segments: segments,
        status: document.querySelector(".translate-status")
          ? document.querySelector(".translate-status").textContent.trim()
          : "",
      };
    });

    await page.evaluate(() => {
      const item = document.querySelector(".history-item");
      item.querySelector('button[class*="btn-danger"]').click();
    });
    await waitFor(page, () => document.querySelectorAll(".history-item").length === 0);

    const failures = [];
    if (listState.count !== 1 || listState.name !== "历史论文.pdf") {
      failures.push("翻译记录列表异常: " + JSON.stringify(listState));
    }
    if (
      viewState.segments.length !== 2 ||
      !viewState.segments[0].includes("论文的第一句。") ||
      !viewState.status.includes("已加载保存的翻译版本")
    ) {
      failures.push("查看保存版本异常: " + JSON.stringify(viewState));
    }
    if (errors.length) failures.push("JS 错误: " + errors.join(" | "));

    if (failures.length) {
      console.error("TRANSLATE HISTORY FAILED:\n" + failures.join("\n"));
      process.exitCode = 1;
    } else {
      console.log("TRANSLATE HISTORY OK: list=1, view=2 segments, delete ok");
    }
  } finally {
    if (browser) await browser.close();
    cleanupDb();
  }
}

run().catch((err) => {
  console.error("TRANSLATE HISTORY ERROR: " + (err.stack || err.message));
  process.exit(1);
});
