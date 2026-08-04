// PDF 翻译：上传/选择论文 → SSE 流式逐段翻译 → 双语对照
window.translateApp = function () {
  return {
    busy: false,
    targetLang: "zh",
    maxParagraphs: 20,
    selectedPdf: "",
    papers: [],
    segments: [],
    status: "",

    async init() {
      await this.loadPapers();
    },

    async loadPapers() {
      const resp = await fetch("/api/papers");
      if (resp.ok) this.papers = await resp.json();
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
      } catch (err) {
        this.status = "错误: " + err.message;
      } finally {
        this.busy = false;
        this.selectedPdf = "";
      }
    },

    async translateSelected() {
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
      const resp = await fetch("/api/pdf/" + pdfId + "/translate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target_lang: this.targetLang,
          max_paragraphs: this.maxParagraphs || 0,
        }),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        this.status = "翻译请求失败: " + (body.detail || ("HTTP " + resp.status));
        return;
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop();
        for (const part of parts) this.handleEvent(part);
      }
    },

    handleEvent(part) {
      const lines = part.split("\n");
      const type = this.lineValue(lines, "event:");
      const raw = this.lineValue(lines, "data:");
      if (!raw) return;
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

    lineValue(lines, prefix) {
      const line = lines.find((l) => l.startsWith(prefix));
      return line ? line.slice(prefix.length).trim() : "";
    },
  };
};
