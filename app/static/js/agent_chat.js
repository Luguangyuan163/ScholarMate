// Agent 对话：fetch 流式解析 SSE（EventSource 不支持 POST，故手动解析）
window.chatApp = function () {
  return {
    query: "",
    busy: false,
    init() {},
    async send() {
      const text = this.query.trim();
      if (!text || this.busy) return;
      this.query = "";
      this.busy = true;
      this.clearPlaceholder();
      this.appendMessage("user", text);
      const assistantNode = this.appendMessage("assistant", "");
      const statusNode = this.appendStatus("Agent 思考中…");
      try {
        const resp = await fetch("/api/agent/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query: text, max_iterations: 5 }),
        });
        if (!resp.ok) {
          this.setStatus(statusNode, "请求失败: HTTP " + resp.status);
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
          for (const part of parts) {
            this.handleEvent(part, assistantNode, statusNode);
          }
        }
        this.setStatus(statusNode, "完成");
      } catch (err) {
        this.setStatus(statusNode, "错误: " + err.message);
      } finally {
        this.busy = false;
        this.scrollToBottom();
      }
    },
    handleEvent(part, assistantNode, statusNode) {
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
      if (type === "tool_call") {
        const args = JSON.stringify(payload.arguments || {});
        this.setStatus(statusNode, "调用工具 " + payload.name + " " + args);
      } else if (type === "tool_result") {
        this.setStatus(
          statusNode,
          "工具 " + payload.name + " 返回 " + payload.content.length + " 字符"
        );
      } else if (type === "message") {
        this.appendChunk(assistantNode, payload.content || "");
        this.scrollToBottom();
      } else if (type === "error") {
        this.setStatus(statusNode, "错误: " + payload.content);
      } else if (type === "done") {
        this.setStatus(statusNode, "完成");
      }
    },
    lineValue(lines, prefix) {
      const line = lines.find((l) => l.startsWith(prefix));
      return line ? line.slice(prefix.length).trim() : "";
    },
    clearPlaceholder() {
      const placeholder = document.querySelector(".chat-placeholder");
      if (placeholder) placeholder.remove();
    },
    appendMessage(role, text) {
      const log = document.getElementById("chat-log");
      const node = document.createElement("div");
      node.className = "chat-msg " + role;
      node.textContent = text;
      log.appendChild(node);
      this.scrollToBottom();
      return node;
    },
    appendChunk(node, text) {
      node.textContent += text;
    },
    appendStatus(text) {
      const log = document.getElementById("chat-log");
      const node = document.createElement("div");
      node.className = "chat-status";
      node.textContent = text;
      log.appendChild(node);
      return node;
    },
    setStatus(node, text) {
      node.textContent = text;
    },
    scrollToBottom() {
      const log = document.getElementById("chat-log");
      if (log) log.scrollTop = log.scrollHeight;
    },
  };
};
