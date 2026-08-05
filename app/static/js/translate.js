// PDF 翻译：上传/选择论文 → SSE 流式逐段翻译 → 双语对照
window.translateApp = function () {
  return {
    busy: false,
    targetLang: "zh",
    maxParagraphs: 20,
    selectedPdf: "",
    papers: [],
    records: [],
    segments: [],
    status: "",

    async init() {
      await this.loadPapers();
      await this.loadRecords();
      const params = new URLSearchParams(window.location.search);
      const pdf = params.get("pdf");
      if (pdf && this.papers.some((p) => String(p.id) === pdf)) {
        this.selectedPdf = pdf;
        await this.translateSelected();
      }
    },

    async loadPapers() {
      const resp = await fetch("/api/papers");
      if (resp.ok) this.papers = await resp.json();
    },

    async loadRecords() {
      const resp = await fetch("/api/translations");
      if (resp.ok) this.records = await resp.json();
    },

    async viewRecord(record) {
      const resp = await fetch("/api/translations/" + record.id);
      if (!resp.ok) return;
      const data = await resp.json();
      this.segments = data.segments;
      this.status =
        "已加载保存的翻译版本（" + (data.created_at || "").slice(0, 16) + "）";
    },

    async removeRecord(record) {
      if (!confirm("确定删除该翻译记录？")) return;
      const resp = await fetch("/api/translations/" + record.id, {
        method: "DELETE",
      });
      if (resp.ok) {
        this.records = this.records.filter((r) => r.id !== record.id);
        this.segments = [];
        this.status = "";
      } else {
        alert("删除失败: HTTP " + resp.status);
      }
    },

    async uploadAndTranslate(event) {
      const input = event.target.querySelector('input[type="file"]');
      const file = input.files && input.files[0];
      if (!file || this.busy) return;
      this.busy = true;
      this.segments = [];
      this.status = "上传中…";
      const form = new FormData();
      form.append("file", file);
      try {
        const resp = await fetch("/api/pdf/upload", { method: "POST", body: form });
        if (!resp.ok) {
          const body = await resp.json().catch(() => ({}));
          this.status = "上传失败: " + (body.detail || ("HTTP " + resp.status));
          return;
        }
        const data = await resp.json();
        await this.translatePdf(data.pdf_id);
        await this.loadRecords();
      } catch (err) {
        this.status = "错误: " + err.message;
      } finally {
        this.busy = false;
        this.selectedPdf = "";
      }
    },

    async translateSelected() {
      if (!this.selectedPdf || this.busy) return;
      const saved = this.records.find(
        (r) => String(r.pdf_id) === this.selectedPdf,
      );
      if (saved) {
        await this.viewRecord(saved);
        return;
      }
      await this.forceTranslate();
    },

    async forceTranslate() {
      if (!this.selectedPdf || this.busy) return;
      this.busy = true;
      this.segments = [];
      try {
        await this.translatePdf(Number(this.selectedPdf));
      } finally {
        this.busy = false;
      }
    },

    async translatePdf(pdfId) {
      this.status = "准备翻译…";
      const params = new URLSearchParams({
        target_lang: this.targetLang,
        max_paragraphs: String(this.maxParagraphs || 0),
      });
      const source = new EventSource(
        "/api/pdf/" + pdfId + "/translate-stream?" + params,
      );
      let finished = false;
      const close = () => {
        if (finished) return;
        finished = true;
        source.close();
      };
      source.addEventListener("progress", (event) =>
        this.handleEvent("progress", event.data),
      );
      source.addEventListener("segment", (event) =>
        this.handleEvent("segment", event.data),
      );
      source.addEventListener("error", (event) =>
        this.handleEvent("error", event.data),
      );
      source.addEventListener("done", (event) => {
        this.handleEvent("done", event.data);
        close();
        this.loadRecords();
      });
      source.onerror = () => {
        if (finished) return;
        close();
        if (!this.status.includes("完成")) {
          this.status = "翻译连接中断，请重试";
        }
      };
    },

    handleEvent(type, raw) {
      let payload;
      try {
        payload = JSON.parse(raw);
      } catch {
        return;
      }
      if (type === "progress") {
        this.status = "翻译进度 " + payload.done + "/" + payload.total;
      } else if (type === "segment") {
        this.segments.push({
          source: payload.source,
          translation: payload.translation,
        });
        this.status = "翻译进度 " + (payload.index + 1) + "/" + payload.total;
      } else if (type === "done") {
        this.status = "翻译完成，共 " + payload.total + " 段";
      } else if (type === "error") {
        this.status = "错误: " + payload.content;
      }
    },
  };
};
