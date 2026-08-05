// 工作台对话：消息流 / SSE Agent / 上传 PDF 翻译 / 对话后收藏论文
window.chatApp = function () {
  return {
    messages: [],
    draft: "",
    busy: false,
    conversationId: null,
    suggestPapers: [],
    collectedPapers: [],
    view: "chat",
    translation: {
      pdfId: null,
      pdfName: "",
      selectedPdf: "",
      papers: [],
      records: [],
      segments: [],
      status: "",
      busy: false,
      source: null,
    },

    async init() {
      const params = new URLSearchParams(window.location.search);
      const conv = params.get("conv");
      const pdf = params.get("pdf");
      if (
        window.location.pathname === "/translate" ||
        params.get("view") === "translate"
      ) {
        this.view = "translate";
        this.loadTranslationPapers();
        this.loadTranslationRecords();
      }
      if (conv) await this.loadConversation(Number(conv));
      if (pdf) {
        await this.loadTranslationPapers();
        const meta = this.translation.papers.find((p) => String(p.id) === pdf);
        this.openTranslation(Number(pdf), meta ? meta.filename : "PDF #" + pdf);
      }
      window.addEventListener("sm:open-translation", (event) => {
        this.openTranslation(event.detail.pdfId, event.detail.filename);
      });
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
        phase: "idle",
        statusText: "",
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
      const assistant = this.pushMessage({
        role: "assistant",
        content: "",
        phase: "thinking",
        statusText: "正在思考…",
      });
      this.streamAssistant(text, assistant);
    },

    streamAssistant(text, assistant) {
      const source = new EventSource(
        "/api/agent/chat-stream?query=" +
          encodeURIComponent(text) +
          "&max_iterations=6",
      );
      let finished = false;
      const close = () => {
        if (finished) return;
        finished = true;
        source.close();
      };
      const onEvent = (type) => (event) =>
        this.handleEvent(type, event.data, assistant);
      source.addEventListener("message", onEvent("message"));
      source.addEventListener("tool_call", onEvent("tool_call"));
      source.addEventListener("tool_result", onEvent("tool_result"));
      source.addEventListener("error", onEvent("error"));
      source.addEventListener("done", (event) => {
        this.handleEvent("done", event.data, assistant);
        close();
        this.finishSend(assistant);
      });
      source.onerror = () => {
        if (finished) return;
        close();
        if (!assistant.content) {
          assistant.phase = "error";
          assistant.statusText = "连接中断，请重试";
        }
        this.finishSend(assistant);
      };
    },

    async finishSend(assistant) {
      try {
        if (assistant.content) {
          await this.saveMessage("assistant", assistant.content);
        }
        if (this.collectedPapers.length) {
          if (localStorage.getItem("sm_auto_save") !== "0") {
            await this.autoSavePapers();
          } else {
            this.suggestPapers = [...this.collectedPapers];
          }
        }
      } finally {
        this.busy = false;
        this.scrollToBottom();
      }
    },

    handleEvent(type, raw, assistant) {
      let payload;
      try {
        payload = JSON.parse(raw);
      } catch {
        return;
      }
      if (type === "tool_call") {
        assistant.tools = assistant.tools || [];
        assistant.tools.push(payload.name);
        assistant.phase = "tool";
        assistant.statusText = this.toolLabel(payload.name);
        this.scrollToBottom();
      } else if (type === "tool_result") {
        assistant.statusText = this.toolSummary(payload.name, payload.content);
        this.collectPapers(payload.name, payload.content);
        this.scrollToBottom();
      } else if (type === "message") {
        assistant.phase = "streaming";
        assistant.statusText = "";
        assistant.content += payload.content || "";
        this.scrollToBottom();
      } else if (type === "error") {
        assistant.phase = "error";
        if (!assistant.content) {
          assistant.content = "请求失败: " + (payload.content || "");
        }
        assistant.statusText = "";
      } else if (type === "done") {
        assistant.phase = "done";
        assistant.statusText = "";
      }
    },

    toolLabel(name) {
      const labels = {
        search_arxiv: "正在检索 arXiv…",
        search_semantic_scholar: "正在检索 Semantic Scholar…",
        search_local: "正在检索本地论文库…",
        get_paper_detail: "正在获取论文详情…",
        translate_text: "正在翻译文本…",
      };
      return labels[name] || ("正在执行 " + name + "…");
    },

    toolSummary(name, raw) {
      let count = null;
      try {
        const data = JSON.parse(raw);
        if (Array.isArray(data)) count = data.length;
      } catch {
        // 非 JSON 结果（如错误信息）不统计条数
      }
      const summaries = {
        search_arxiv:
          count !== null ? "arXiv 返回 " + count + " 篇" : "arXiv 检索完成",
        search_semantic_scholar:
          count !== null
            ? "Semantic Scholar 返回 " + count + " 篇"
            : "Semantic Scholar 检索完成",
        search_local:
          count !== null ? "本地论文库返回 " + count + " 条" : "本地检索完成",
        get_paper_detail: "已获取论文详情",
        translate_text: "翻译完成",
      };
      return summaries[name] || ("已完成 " + name);
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
          pdf_url: p.pdf_url || "",
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
      try {
        const form = new FormData();
        form.append("file", file);
        const resp = await fetch("/api/pdf/upload", { method: "POST", body: form });
        if (!resp.ok) {
          const body = await resp.json().catch(() => ({}));
          alert("上传失败: " + (body.detail || ("HTTP " + resp.status)));
          return;
        }
        const data = await resp.json();
        this.openTranslation(data.pdf_id, file.name);
      } catch (err) {
        alert("上传失败: " + err.message);
      } finally {
        this.busy = false;
      }
    },

    async openTranslation(pdfId, name) {
      this.view = "translate";
      this.translation.pdfId = pdfId;
      this.translation.pdfName = name || "";
      this.translation.selectedPdf = String(pdfId);
      this.translation.segments = [];
      this.translation.status = "";
      await this.loadTranslationRecords();
      const saved = this.translation.records.find(
        (r) => String(r.pdf_id) === String(pdfId),
      );
      if (saved) {
        await this.viewSavedRecord(saved);
      } else {
        await this.startTranslation();
      }
    },

    closeTranslation() {
      this.closeTranslationSource();
      this.translation.pdfId = null;
      this.translation.pdfName = "";
      this.translation.segments = [];
      this.translation.status = "";
      this.view = "chat";
    },

    closeTranslationSource() {
      if (this.translation.source) {
        this.translation.source.close();
        this.translation.source = null;
      }
    },

    async loadTranslationPapers() {
      const resp = await fetch("/api/papers");
      if (resp.ok) this.translation.papers = await resp.json();
    },

    async loadTranslationRecords() {
      const resp = await fetch("/api/translations");
      if (resp.ok) this.translation.records = await resp.json();
    },

    async viewSavedRecord(record) {
      const resp = await fetch("/api/translations/" + record.id);
      if (!resp.ok) return;
      const data = await resp.json();
      this.translation.segments = data.segments;
      this.translation.pdfName = data.filename;
      this.translation.status =
        "已加载保存的翻译版本（" + (data.created_at || "").slice(0, 16) + "）";
    },

    async deleteRecord(record) {
      if (!confirm("确定删除该翻译记录？")) return;
      const resp = await fetch("/api/translations/" + record.id, {
        method: "DELETE",
      });
      if (resp.ok) {
        this.translation.records = this.translation.records.filter(
          (r) => r.id !== record.id,
        );
        this.translation.segments = [];
        this.translation.status = "";
      } else {
        alert("删除失败: HTTP " + resp.status);
      }
    },

    async translateUpload(event) {
      const input = event.target.querySelector('input[type="file"]');
      const file = input.files && input.files[0];
      if (!file || this.translation.busy) return;
      this.translation.busy = true;
      this.translation.segments = [];
      this.translation.status = "上传中…";
      const form = new FormData();
      form.append("file", file);
      try {
        const resp = await fetch("/api/pdf/upload", {
          method: "POST",
          body: form,
        });
        if (!resp.ok) {
          const body = await resp.json().catch(() => ({}));
          this.translation.status =
            "上传失败: " + (body.detail || ("HTTP " + resp.status));
          return;
        }
        const data = await resp.json();
        await this.openTranslation(data.pdf_id, file.name);
      } catch (err) {
        this.translation.status = "错误: " + err.message;
      } finally {
        this.translation.busy = false;
      }
    },

    async translateSelect() {
      if (!this.translation.selectedPdf || this.translation.busy) return;
      const meta = this.translation.papers.find(
        (p) => String(p.id) === this.translation.selectedPdf,
      );
      this.openTranslation(
        Number(this.translation.selectedPdf),
        meta ? meta.filename : "",
      );
    },

    async startTranslation() {
      if (!this.translation.pdfId || this.translation.busy) return;
      this.translation.busy = true;
      this.translation.segments = [];
      this.translation.status = "准备翻译…";
      const params = new URLSearchParams({
        target_lang: "zh",
        max_paragraphs: "0",
      });
      this.closeTranslationSource();
      const source = new EventSource(
        "/api/pdf/" + this.translation.pdfId + "/translate-stream?" + params,
      );
      this.translation.source = source;
      let finished = false;
      const close = () => {
        if (finished) return;
        finished = true;
        this.closeTranslationSource();
      };
      source.addEventListener("progress", (event) =>
        this.handleTranslationEvent("progress", event.data),
      );
      source.addEventListener("segment", (event) =>
        this.handleTranslationEvent("segment", event.data),
      );
      source.addEventListener("error", (event) =>
        this.handleTranslationEvent("error", event.data),
      );
      source.addEventListener("done", (event) => {
        this.handleTranslationEvent("done", event.data);
        close();
        this.loadTranslationRecords();
      });
      source.onerror = () => {
        if (finished) return;
        close();
        if (!this.translation.status.includes("完成")) {
          this.translation.status = "翻译连接中断，请重试";
        }
        this.translation.busy = false;
      };
    },

    handleTranslationEvent(type, raw) {
      let payload;
      try {
        payload = JSON.parse(raw);
      } catch {
        return;
      }
      if (type === "progress") {
        this.translation.status =
          "翻译进度 " + payload.done + "/" + payload.total;
      } else if (type === "segment") {
        this.translation.segments.push({
          source: payload.source,
          translation: payload.translation,
        });
        this.translation.status =
          "翻译进度 " + (payload.index + 1) + "/" + payload.total;
      } else if (type === "done") {
        this.translation.status = "翻译完成，共 " + payload.total + " 段";
        this.translation.busy = false;
      } else if (type === "error") {
        this.translation.status = "错误: " + payload.content;
        this.translation.busy = false;
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
      if (!m.phase) m.phase = "idle";
      if (!m.statusText) m.statusText = "";
      this.messages.push(m);
      this.scrollToBottom();
      // 必须返回响应式代理而非原始对象：Alpine 只追踪经代理的写入，
      // 若返回原始对象，后续 assistant.content / msg.pdf.status 等变更
      // 不会触发 DOM 重渲染，消息要到重新进入会话才会显示。
      return this.messages[this.messages.length - 1];
    },

    scrollToBottom() {
      const log = document.getElementById("chat-log");
      if (log) log.scrollTop = log.scrollHeight;
    },
  };
};
