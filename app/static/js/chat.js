// 工作台对话：消息流 / SSE Agent / 上传 PDF 翻译 / 对话后收藏论文
window.chatApp = function () {
  return {
    messages: [],
    draft: "",
    busy: false,
    conversationId: null,
    suggestPapers: [],
    collectedPapers: [],

    async init() {
      const params = new URLSearchParams(window.location.search);
      const conv = params.get("conv");
      const pdf = params.get("pdf");
      if (conv) await this.loadConversation(Number(conv));
      if (pdf) await this.attachPdfById(Number(pdf));
    },

    async loadConversation(id) {
      const resp = await fetch("/api/conversations/" + id);
      if (!resp.ok) return;
      const data = await resp.json();
      this.conversationId = data.id;
      this.messages = data.messages.map((m) => ({
        role: m.role,
        content: m.content,
        tools: [],
        pdf: { filename: "", status: "", segments: [] },
      }));
      this.scrollToBottom();
    },

    ask(text) {
      this.draft = text;
      this.send();
    },

    async send() {
      const text = this.draft.trim();
      if (!text || this.busy) return;
      this.draft = "";
      await this.ensureConversation(text);
      this.pushMessage({ role: "user", content: text });
      await this.saveMessage("user", text);
      this.busy = true;
      const assistant = this.pushMessage({ role: "assistant", content: "" });
      try {
        const resp = await fetch("/api/agent/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query: text, max_iterations: 6 }),
        });
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split("\n\n");
          buffer = parts.pop();
          for (const part of parts) this.handleEvent(part, assistant);
        }
        if (assistant.content) await this.saveMessage("assistant", assistant.content);
        if (this.collectedPapers.length) {
          if (localStorage.getItem("sm_auto_save") !== "0") {
            await this.autoSavePapers();
          } else {
            this.suggestPapers = [...this.collectedPapers];
          }
        }
      } catch (err) {
        assistant.content = "请求失败: " + err.message;
      } finally {
        this.busy = false;
        this.scrollToBottom();
      }
    },

    handleEvent(part, assistant) {
      const type = this.lineValue(part, "event:");
      const raw = this.lineValue(part, "data:");
      if (!raw) return;
      let payload;
      try {
        payload = JSON.parse(raw);
      } catch {
        return;
      }
      if (type === "tool_call") {
        if (!assistant.tools) assistant.tools = [];
        assistant.tools.push(payload.name);
        this.scrollToBottom();
      } else if (type === "tool_result") {
        this.collectPapers(payload.name, payload.content);
      } else if (type === "message") {
        assistant.content += payload.content || "";
        this.scrollToBottom();
      } else if (type === "error") {
        assistant.content = "错误: " + payload.content;
      }
    },

    collectPapers(toolName, raw) {
      let data;
      try {
        data = JSON.parse(raw);
      } catch {
        return;
      }
      if (!Array.isArray(data)) return;
      const fallbackSource = toolName === "search_arxiv" ? "arxiv" : "s2";
      for (const p of data) {
        if (!p || !p.title) continue;
        this.collectedPapers.push({
          title: p.title,
          source: p.source || fallbackSource,
          external_id: String(p.external_id || p.title).slice(0, 128),
          year: p.year || null,
          citation_count: p.citation_count || 0,
          url: p.url || "",
          authors: p.authors || [],
        });
      }
    },

    async savePapers() {
      const resp = await fetch("/api/papers/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ papers: this.suggestPapers }),
      });
      if (resp.ok) {
        const data = await resp.json();
        this.suggestPapers = [];
        this.pushMessage({ role: "assistant", content: this.importSummary(data) });
        window.dispatchEvent(new CustomEvent("library:changed"));
      } else {
        alert("保存失败: HTTP " + resp.status);
      }
    },

    async autoSavePapers() {
      const papers = [...this.collectedPapers];
      this.collectedPapers = [];
      const resp = await fetch("/api/papers/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ papers: papers }),
      });
      if (resp.ok) {
        const data = await resp.json();
        this.pushMessage({
          role: "assistant",
          content: "已自动收藏论文：" + this.importSummary(data),
        });
        window.dispatchEvent(new CustomEvent("library:changed"));
      }
    },

    importSummary(data) {
      const parts = [];
      if (data.imported) parts.push("新增 " + data.imported + " 篇");
      if (data.updated) parts.push("更新引用量 " + data.updated + " 篇");
      if (data.skipped) parts.push("跳过重复 " + data.skipped + " 篇");
      return parts.length ? parts.join("，") + "。" : "无变化。";
    },

    async attachPdf(event) {
      const file = event.target.files && event.target.files[0];
      if (!file) return;
      event.target.value = "";
      if (this.busy) {
        alert("请等待当前任务完成");
        return;
      }
      this.busy = true;
      const msg = this.pushMessage({
        role: "user",
        content: "📎 " + file.name,
        pdf: { filename: file.name, status: "上传中…", segments: [] },
      });
      try {
        const form = new FormData();
        form.append("file", file);
        const resp = await fetch("/api/pdf/upload", { method: "POST", body: form });
        if (!resp.ok) {
          const body = await resp.json().catch(() => ({}));
          msg.pdf.status = "上传失败: " + (body.detail || ("HTTP " + resp.status));
          return;
        }
        const data = await resp.json();
        msg.pdf.pdfId = data.pdf_id;
        await this.translatePdf(msg);
      } catch (err) {
        msg.pdf.status = "上传失败: " + err.message;
      } finally {
        this.busy = false;
        this.scrollToBottom();
      }
    },

    async attachPdfById(pdfId) {
      if (this.busy) return;
      this.busy = true;
      const resp = await fetch("/api/papers");
      const papers = resp.ok ? await resp.json() : [];
      const meta = papers.find((p) => p.id === pdfId);
      const msg = this.pushMessage({
        role: "user",
        content: "📎 " + (meta ? meta.filename : "PDF #" + pdfId),
        pdf: {
          filename: meta ? meta.filename : "PDF",
          status: "准备翻译…",
          segments: [],
        },
      });
      try {
        await this.translatePdf(msg, pdfId);
      } finally {
        this.busy = false;
        this.scrollToBottom();
      }
    },

    async translatePdf(msg, pdfIdOverride) {
      const pdfId = pdfIdOverride || msg.pdf.pdfId;
      const resp = await fetch("/api/pdf/" + pdfId + "/translate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_lang: "zh", max_paragraphs: 20 }),
      });
      if (!resp.ok) {
        msg.pdf.status = "翻译请求失败: HTTP " + resp.status;
        return;
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      msg.pdf.status = "翻译中…";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop();
        for (const part of parts) this.handlePdfEvent(part, msg);
      }
    },

    handlePdfEvent(part, msg) {
      const type = this.lineValue(part, "event:");
      const raw = this.lineValue(part, "data:");
      if (!raw) return;
      let payload;
      try {
        payload = JSON.parse(raw);
      } catch {
        return;
      }
      if (type === "progress") {
        msg.pdf.status = "翻译中… " + payload.done + "/" + payload.total;
      } else if (type === "segment") {
        msg.pdf.segments.push({
          source: payload.source,
          translation: payload.translation,
        });
        msg.pdf.status = "翻译中… " + (payload.index + 1) + "/" + payload.total;
        this.scrollToBottom();
      } else if (type === "done") {
        msg.pdf.status = "翻译完成（" + payload.total + " 段）";
      } else if (type === "error") {
        msg.pdf.status = "错误: " + payload.content;
      }
    },

    async ensureConversation(title) {
      if (this.conversationId) return;
      const resp = await fetch("/api/conversations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: title ? title.slice(0, 30) : "新会话" }),
      });
      if (resp.ok) {
        const data = await resp.json();
        this.conversationId = data.id;
        window.dispatchEvent(new CustomEvent("library:changed"));
      }
    },

    async saveMessage(role, content) {
      if (!this.conversationId || !content) return;
      await fetch("/api/conversations/" + this.conversationId + "/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role: role, content: content }),
      });
    },

    pushMessage(m) {
      if (!m.pdf) m.pdf = { filename: "", status: "", segments: [] };
      this.messages.push(m);
      this.scrollToBottom();
      return m;
    },

    lineValue(part, prefix) {
      const line = part.split("\n").find((l) => l.startsWith(prefix));
      return line ? line.slice(prefix.length).trim() : "";
    },

    scrollToBottom() {
      const log = document.getElementById("chat-log");
      if (log) log.scrollTop = log.scrollHeight;
    },
  };
};
