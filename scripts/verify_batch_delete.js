// 回归：论文库批量删除 + 自动收藏默认关闭。
// 用法（服务器以临时库启动）：
//   node scripts/verify_batch_delete.js http://127.0.0.1:8877 <dbPath> <uploadDir>
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
  const ids = [];
  for (let i = 0; i < count; i++) {
    const name = "batch-seed-" + i + ".pdf";
    const file = path.join(uploadDir, name);
    fs.writeFileSync(file, "%PDF-1.7 fake");
    db.prepare(
      "INSERT INTO uploaded_pdfs (filename, original_name, file_path, status, created_at) " +
        "VALUES (?, ?, ?, ?, datetime('now'))",
    ).run(name, "批量测试论文" + i + ".pdf", file, "ready");
    ids.push(
      db.prepare("SELECT id FROM uploaded_pdfs WHERE filename = ?").get(name).id,
    );
  }
  db.close();
  return ids;
}

function cleanupDb(ids) {
  const db = new DatabaseSync(dbPath);
  db.prepare(
    "DELETE FROM uploaded_pdfs WHERE filename LIKE 'batch-seed-%'",
  ).run();
  db.close();
  for (const id of ids || []) {
    const file = path.join(uploadDir, "batch-seed-" + id + ".pdf");
    if (fs.existsSync(file)) fs.unlinkSync(file);
  }
}

async function run() {
  let browser;
  let seededIds = [];
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
    page.on("dialog", (dialog) => dialog.accept());

    seededIds = seedPdfs(3);
    await page.goto(baseUrl + "/papers", {
      waitUntil: "networkidle2",
      timeout: 20000,
    });
    await waitFor(page, () => document.querySelectorAll(".paper-card").length === 3);

    await page.evaluate(() => {
      const cards = Array.from(document.querySelectorAll(".paper-card"));
      cards[0].querySelector('input[type="checkbox"]').click();
      cards[1].querySelector('input[type="checkbox"]').click();
    });
    await sleep(300);
    const selectState = await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll(".library-actions button")).find(
        (b) => b.textContent.includes("批量删除"),
      );
      return {
        checked: document.querySelectorAll(
          '.paper-card input[type="checkbox"]:checked',
        ).length,
        buttonText: btn ? btn.textContent.trim() : "",
        disabled: btn ? btn.disabled : true,
      };
    });

    await page.evaluate(() => {
      Array.from(document.querySelectorAll(".library-actions button"))
        .find((b) => b.textContent.includes("批量删除"))
        .click();
    });
    await waitFor(page, () => document.querySelectorAll(".paper-card").length === 1);

    const afterDelete = await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll(".library-actions button")).find(
        (b) => b.textContent.includes("批量删除"),
      );
      return {
        cards: document.querySelectorAll(".paper-card").length,
        selected: document.querySelectorAll(
          '.paper-card input[type="checkbox"]:checked',
        ).length,
        disabled: btn ? btn.disabled : true,
      };
    });

    await page.evaluate(() => {
      const allBox = Array.from(
        document.querySelectorAll(".library-actions label input[type='checkbox']"),
      )[0];
      allBox.click();
    });
    await sleep(300);
    const checkedAll = await page.evaluate(
      () =>
        document.querySelectorAll('.paper-card input[type="checkbox"]:checked')
          .length,
    );
    await page.evaluate(() => {
      const allBox = Array.from(
        document.querySelectorAll(".library-actions label input[type='checkbox']"),
      )[0];
      allBox.click();
    });
    await sleep(300);
    const cleared = await page.evaluate(
      () =>
        document.querySelectorAll('.paper-card input[type="checkbox"]:checked')
          .length,
    );

    // 自动收藏默认关闭：无 localStorage 值时侧边栏复选框应为未选中
    await page.evaluate(() => localStorage.removeItem("sm_auto_save"));
    await page.goto(baseUrl + "/", { waitUntil: "networkidle2", timeout: 20000 });
    await waitFor(page, () => document.querySelector(".sidebar-toggle input") !== null);
    const defaultOff = await page.evaluate(
      () => document.querySelector(".sidebar-toggle input").checked === false,
    );
    await page.evaluate(() => localStorage.setItem("sm_auto_save", "1"));
    await page.reload({ waitUntil: "networkidle2" });
    await waitFor(page, () => document.querySelector(".sidebar-toggle input") !== null);
    const explicitOn = await page.evaluate(
      () => document.querySelector(".sidebar-toggle input").checked === true,
    );

    const failures = [];
    if (
      selectState.checked !== 2 ||
      !selectState.buttonText.includes("(2)") ||
      selectState.disabled
    ) {
      failures.push("批量删除按钮状态异常: " + JSON.stringify(selectState));
    }
    if (afterDelete.cards !== 1 || afterDelete.selected !== 0 || !afterDelete.disabled) {
      failures.push("批量删除后状态异常: " + JSON.stringify(afterDelete));
    }
    if (checkedAll !== 1 || cleared !== 0) {
      failures.push("全选/取消全选异常: checkedAll=" + checkedAll + " cleared=" + cleared);
    }
    if (!defaultOff) {
      failures.push("自动收藏默认未关闭");
    }
    if (!explicitOn) {
      failures.push("显式开启自动收藏未生效");
    }
    if (errors.length) failures.push("JS 错误: " + errors.join(" | "));

    if (failures.length) {
      console.error("BATCH DELETE FAILED:\n" + failures.join("\n"));
      process.exitCode = 1;
    } else {
      console.log(
        "BATCH DELETE OK: select 2 -> delete -> 1 left, select-all works, auto-save default off",
      );
    }
  } finally {
    if (browser) await browser.close();
    cleanupDb(seededIds);
  }
}

run().catch((err) => {
  console.error("BATCH DELETE ERROR: " + (err.stack || err.message));
  process.exit(1);
});
