// 主题管理页：新建、编辑、合并、删除主题，查看主题下的论文
window.topicsApp = function () {
  return {
    topics: [],
    loading: true,
    creating: false,
    editingId: null,
    papersTopicId: null,
    topicPapers: [],
    mergeTarget: "",
    error: "",
    form: { name: "", description: "", keywordsText: "", color: "#1f3a5f" },
    edit: { name: "", description: "", keywordsText: "", color: "#1f3a5f" },

    async init() {
      await this.load();
    },

    async load() {
      this.loading = true;
      try {
        const resp = await fetch("/api/topics");
        if (resp.ok) this.topics = await resp.json();
      } finally {
        this.loading = false;
      }
    },

    toggleCreate() {
      this.creating = !this.creating;
      this.error = "";
      if (this.creating) {
        this.form = { name: "", description: "", keywordsText: "", color: "#1f3a5f" };
      }
    },

    parseKeywords(text) {
      return String(text || "")
        .split(/[,，\n]/)
        .map((item) => item.trim())
        .filter(Boolean);
    },

    async createTopic() {
      this.error = "";
      const resp = await fetch("/api/topics", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: this.form.name.trim(),
          description: this.form.description.trim(),
          keywords: this.parseKeywords(this.form.keywordsText),
          color: this.form.color,
        }),
      });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        this.error = data.detail || "创建失败";
        return;
      }
      this.creating = false;
      await this.load();
    },

    startEdit(topic) {
      this.editingId = topic.id;
      this.mergeTarget = "";
      this.edit = {
        name: topic.name,
        description: topic.description || "",
        keywordsText: (topic.keywords || []).join(", "),
        color: topic.color || "#1f3a5f",
      };
    },

    async saveEdit(topic) {
      const resp = await fetch("/api/topics/" + topic.id, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: this.edit.name.trim(),
          description: this.edit.description.trim(),
          keywords: this.parseKeywords(this.edit.keywordsText),
          color: this.edit.color,
        }),
      });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        this.error = data.detail || "保存失败";
        return;
      }
      this.editingId = null;
      await this.load();
    },

    async removeTopic(topic) {
      if (!confirm("确定删除主题《" + topic.name + "》？论文本身不会被删除。")) return;
      const resp = await fetch("/api/topics/" + topic.id, { method: "DELETE" });
      if (resp.ok) await this.load();
    },

    async mergeTopic(topic) {
      if (!this.mergeTarget) {
        this.error = "请先选择要并入的目标主题";
        return;
      }
      const target = this.topics.find((item) => String(item.id) === String(this.mergeTarget));
      if (!confirm("把《" + topic.name + "》并入《" + (target ? target.name : this.mergeTarget) + "》并归档该主题？")) return;
      const resp = await fetch("/api/topics/" + topic.id + "/merge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_id: Number(this.mergeTarget) }),
      });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        this.error = data.detail || "合并失败";
        return;
      }
      this.editingId = null;
      this.mergeTarget = "";
      await this.load();
    },

    async togglePapers(topic) {
      if (this.papersTopicId === topic.id) {
        this.papersTopicId = null;
        return;
      }
      this.papersTopicId = topic.id;
      this.topicPapers = [];
      const resp = await fetch("/api/topics/" + topic.id + "/papers?limit=50");
      if (resp.ok) {
        const data = await resp.json();
        this.topicPapers = data.items || [];
      }
    },
  };
};
