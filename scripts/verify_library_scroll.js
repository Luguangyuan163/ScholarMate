// 回归测试：论文库列表可完整滚动查看，且所有页面的主内容区都不会被裁剪。
// 需要服务器使用独立临时库运行；脚本自行种入数据并在结束时清理。
//
// 用法（服务器需以临时库启动）：
//   $env:SM_DB_PATH = "E:\tmp\sm_e2e\test.db"
//   $env:SM_UPLOAD_DIR = "E:\tmp\sm_e2e\uploads"
//   $env:DATABASE_URL = "sqlite+aiosqlite:///E:/tmp/sm_e2e/test.db"
//   $env:CHROMA_PERSIST_DIR = "E:\tmp\sm_e2e\chroma"
//   $env:PDF_UPLOAD_DIR = "E:\tmp\sm_e2e\uploads"
//   node scripts/verify_library_scroll.js http://127.0.0.1:8877 E:\tmp\sm_e2e\test.db E:\tmp\sm_e2e\uploads
const puppeteer = require("puppeteer-core");
const { DatabaseSync } = require("node:sqlite");
const fs = require("fs");
const path = require("path");

const baseUrl = process.argv[2] || "http://127.0.0.1:8765";
const dbPath = process.argv[3];
const uploadDir = process.argv[4];
const edgePath =
  process.env.EDGE_PATH ||
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const SEED_COUNT = 12;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitFor(page, fn, timeout = 8000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await page.evaluate(fn)) return;
    await sleep(250);
  }
  throw new Error("waitFor 超时: " + fn.toString());
}

function seedPdfs(count) {
  const db = new DatabaseSync(dbPath);
  fs.mkdirSync(uploadDir, { recursive: true });
  for (let i = 0; i < count; i++) {
    const name = "scroll-seed-" + i + ".pdf";
    db.prepare(
      "INSERT INTO uploaded_pdfs (filename, original_name, file_path, status, created_at) " +
        "VALUES (?, ?, ?, ?, datetime('now'))",
    ).run(name, "滚动回归论文" + i + ".pdf", path.join(uploadDir, name), "ready");
  }
  db.close();
}

function cleanupDb() {
  const db = new DatabaseSync(dbPath);
  db.prepare("DELETE FROM uploaded_pdfs WHERE filename LIKE 'scroll-seed-%'").run();
  db.close();
}

async function libraryScrollState(page) {
  return page.evaluate(() => {
    const content = document.querySelector(".content");
    const style = getComputedStyle(content);
    const cards = document.querySelectorAll(".paper-card");
    const last = cards[cards.length - 1];
    const lastRect = last ? last.getBoundingClientRect() : null;
    const contentRect = content.getBoundingClientRect();
    return {
      cardCount: cards.length,
      scrollable:
        style.overflowY === "auto" ||
        style.overflowY === "scroll" ||
        style.overflow === "auto" ||
        style.overflow === "scroll",
      scrollHeight: content.scrollHeight,
      clientHeight: content.clientHeight,
      scrollTop: content.scrollTop,
      lastVisible:
        lastRect !== null &&
        lastRect.top < contentRect.bottom &&
        lastRect.bottom > contentRect.top,
    };
  });
}

async function checkContentScrollable(page, route) {
  await page.goto(baseUrl + route, { waitUntil: "networkidle2", timeout: 20000 });
  await sleep(500);
  return page.evaluate(() => {
    const content = document.querySelector(".content");
    const style = getComputedStyle(content);
    return (
      style.overflowY === "auto" ||
      style.overflowY === "scroll" ||
      style.overflow === "auto" ||
      style.overflow === "scroll"
    );
  });
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

    seedPdfs(SEED_COUNT);
    await page.goto(baseUrl + "/papers", {
      waitUntil: "networkidle2",
      timeout: 20000,
    });
    await waitFor(
      page,
      () => document.querySelectorAll(".paper-card").length === 12,
    );

    const before = await libraryScrollState(page);
    // 尝试滚动到内容底部
    const after = await page.evaluate(async () => {
      const content = document.querySelector(".content");
      content.scrollTop = content.scrollHeight;
      await new Promise((resolve) => setTimeout(resolve, 200));
      const cards = document.querySelectorAll(".paper-card");
      const last = cards[cards.length - 1];
      const lastRect = last.getBoundingClientRect();
      const contentRect = content.getBoundingClientRect();
      return {
        scrollTop: content.scrollTop,
        scrollHeight: content.scrollHeight,
        clientHeight: content.clientHeight,
        lastVisible:
          lastRect.top < contentRect.bottom && lastRect.bottom > contentRect.top,
      };
    });

    // 检查其他页面：主内容区都应是可滚动容器，防止长内容再次被裁剪
    const routes = ["/search", "/", "/agent", "/translate"];
    const scrollableRoutes = {};
    for (const route of routes) {
      scrollableRoutes[route] = await checkContentScrollable(page, route);
    }

    const failures = [];
    if (before.cardCount !== SEED_COUNT) {
      failures.push("论文卡片未全部渲染: " + before.cardCount + " / " + SEED_COUNT);
    }
    if (!before.scrollable) {
      failures.push("论文库主内容区不可滚动，列表被裁切");
    }
    if (after.scrollTop <= 0 || after.scrollHeight <= after.clientHeight) {
      failures.push(
        "论文库主内容区无法滚动: scrollTop=" +
          after.scrollTop +
          " scrollHeight=" +
          after.scrollHeight +
          " clientHeight=" +
          after.clientHeight,
      );
    }
    if (!after.lastVisible) {
      failures.push("滚动到底后最后一篇论文仍不可见，论文库不完整");
    }
    for (const route of routes) {
      if (!scrollableRoutes[route]) {
        failures.push("页面 " + route + " 的主内容区不可滚动，长内容会被裁剪");
      }
    }
    if (errors.length) failures.push("JS 错误: " + errors.join(" | "));

    if (failures.length) {
      console.error("LIBRARY SCROLL FAILED:\n" + failures.join("\n"));
      process.exitCode = 1;
    } else {
      console.log(
        "LIBRARY SCROLL OK: " +
          SEED_COUNT +
          " 篇全部渲染且可滚动查看完整，其他页面主内容区均可滚动",
      );
    }
  } finally {
    if (browser) await browser.close();
    cleanupDb();
  }
}

run().catch((err) => {
  console.error("LIBRARY SCROLL ERROR: " + (err.stack || err.message));
  process.exit(1);
});
