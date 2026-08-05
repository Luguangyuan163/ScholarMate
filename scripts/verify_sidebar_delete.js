// 回归测试：侧边栏删除功能（会话 / 上传 PDF）。
// 需要服务器使用独立临时数据库运行；脚本自行种入数据并在结束时清理。
//
// 用法（服务器需以临时库启动）：
//   $env:SM_DB_PATH = "E:\tmp\sm_e2e\test.db"
//   $env:SM_UPLOAD_DIR = "E:\tmp\sm_e2e\uploads"
//   $env:DATABASE_URL = "sqlite+aiosqlite:///E:/tmp/sm_e2e/test.db"
//   $env:CHROMA_PERSIST_DIR = "E:\tmp\sm_e2e\chroma"
//   $env:PDF_UPLOAD_DIR = "E:\tmp\sm_e2e\uploads"
//   node scripts/verify_sidebar_delete.js http://127.0.0.1:8877 E:\tmp\sm_e2e\test.db E:\tmp\sm_e2e\uploads
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

async function seedData(page) {
  const results = {};
  const convs = [];
  for (const title of ["会话A", "会话B"]) {
    const resp = await page.evaluate(
      (t) =>
        fetch("/api/conversations", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: t }),
        }).then((r) => r.json()),
      title,
    );
    convs.push(resp.id);
  }
  results.conversations = convs;
  return results;
}

function seedUploadedPdf() {
  const db = new DatabaseSync(dbPath);
  db.prepare(
    "INSERT INTO uploaded_pdfs (filename, original_name, file_path, status, created_at) " +
      "VALUES (?, ?, ?, ?, datetime('now'))",
  ).run("e2e-seed.pdf", "e2e_test.pdf", uploadDir + "\\e2e_seed.pdf", "ready");
  db.close();
}

function cleanupDb(seededConvIds) {
  const db = new DatabaseSync(dbPath);
  for (const id of seededConvIds) {
    db.prepare("DELETE FROM conversations WHERE id = ?").run(id);
    db.prepare("DELETE FROM messages WHERE conversation_id = ?").run(id);
  }
  db.prepare("DELETE FROM uploaded_pdfs WHERE filename = ?").run("e2e-seed.pdf");
  db.close();
}

async function sidebarState(page) {
  return page.evaluate(() => {
    const rows = Array.from(document.querySelectorAll(".sidebar-row"));
    const convRows = rows.filter((r) => r.querySelector('a[href*="conv="]'));
    const uploadRows = rows.filter((r) => r.querySelector(".sidebar-pdf-open"));
    return {
      conversations: convRows.length,
      uploaded: uploadRows.length,
    };
  });
}

async function clickDelete(page, rowSelector) {
  await page.evaluate((sel) => {
    const anchor = document.querySelector(sel);
    if (!anchor) throw new Error("删除行不存在: " + sel);
    const row = anchor.closest(".sidebar-row, .sidebar-collection");
    if (!row) throw new Error("未找到删除行容器: " + sel);
    const del = row.querySelector(".sidebar-del");
    if (!del) throw new Error("删除按钮不存在: " + sel);
    del.click();
  }, rowSelector);
}

async function run() {
  let browser;
  const seededConvIds = [];
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

    seedUploadedPdf();
    await page.goto(baseUrl + "/", { waitUntil: "networkidle2", timeout: 20000 });
    const seeded = await seedData(page);
    seededConvIds.push(...seeded.conversations);
    await page.reload({ waitUntil: "networkidle2", timeout: 20000 });

    await waitFor(page, () => {
      const rows = document.querySelectorAll(".sidebar-row").length;
      return rows >= 3;
    });
    const before = await sidebarState(page);

    await clickDelete(page, '.sidebar-row a[href*="conv="]');
    await waitFor(page, () => {
      const rows = Array.from(document.querySelectorAll(".sidebar-row")).filter(
        (r) => r.querySelector('a[href*="conv="]'),
      );
      return rows.length === 1;
    });

    await clickDelete(page, ".sidebar-row .sidebar-pdf-open");
    await waitFor(page, () => {
      const rows = Array.from(document.querySelectorAll(".sidebar-row")).filter(
        (r) => r.querySelector(".sidebar-pdf-open"),
      );
      return rows.length === 0;
    });

    const after = await sidebarState(page);
    const apiState = await page.evaluate(async () => {
      const convs = await fetch("/api/conversations").then((r) => r.json());
      const papers = await fetch("/api/papers").then((r) => r.json());
      return {
        conversations: convs.length,
        papers: papers.length,
      };
    });

    const failures = [];
    if (before.conversations !== 2 || before.uploaded !== 1) {
      failures.push("初始侧边栏状态异常: " + JSON.stringify(before));
    }
    if (after.conversations !== 1 || after.uploaded !== 0) {
      failures.push("删除后侧边栏状态异常: " + JSON.stringify(after));
    }
    if (
      apiState.conversations !== 1 ||
      apiState.papers !== 0
    ) {
      failures.push("API 数据未同步删除: " + JSON.stringify(apiState));
    }
    if (errors.length) failures.push("JS 错误: " + errors.join(" | "));

    if (failures.length) {
      console.error("SIDEBAR DELETE FAILED:\n" + failures.join("\n"));
      process.exitCode = 1;
    } else {
      console.log(
        "SIDEBAR DELETE OK: conversations 2→1, uploaded 1→0",
      );
    }
  } finally {
    if (browser) await browser.close();
    cleanupDb(seededConvIds);
  }
}

run().catch((err) => {
  console.error("SIDEBAR DELETE ERROR: " + (err.stack || err.message));
  process.exit(1);
});
