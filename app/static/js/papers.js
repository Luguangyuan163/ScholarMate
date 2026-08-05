// 论文库：列表加载、单项/批量删除
window.libraryApp = function () {
  return {
    papers: [],
    selected: [],
    loading: true,
    busy: false,

    async init() {
      await this.load();
    },

    async load() {
      this.loading = true;
      try {
        const resp = await fetch("/api/papers");
        if (resp.ok) this.papers = await resp.json();
      } finally {
        this.loading = false;
      }
    },

    async remove(p) {
      if (this.busy) return;
      if (!confirm("确定删除《" + p.filename + "》？删除后不可恢复。")) return;
      this.busy = true;
      try {
        const resp = await fetch("/api/papers/" + p.id, { method: "DELETE" });
        if (resp.ok) {
          this.papers = this.papers.filter((x) => x.id !== p.id);
        } else {
          const body = await resp.json().catch(() => ({}));
          alert("删除失败: " + (body.detail || ("HTTP " + resp.status)));
        }
      } finally {
        this.busy = false;
      }
    },

    isSelected(p) {
      return this.selected.includes(p.id);
    },

    toggleSelect(p) {
      this.selected = this.isSelected(p)
        ? this.selected.filter((id) => id !== p.id)
        : [...this.selected, p.id];
    },

    get allSelected() {
      return this.papers.length > 0 && this.selected.length === this.papers.length;
    },

    toggleAll(event) {
      this.selected = event.target.checked ? this.papers.map((p) => p.id) : [];
    },

    async batchDelete() {
      if (!this.selected.length || this.busy) return;
      const count = this.selected.length;
      if (!confirm("确定删除选中的 " + count + " 篇论文？删除后不可恢复。")) return;
      this.busy = true;
      try {
        const resp = await fetch("/api/papers/batch-delete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ids: this.selected }),
        });
        if (resp.ok) {
          const data = await resp.json();
          const removed = new Set(this.selected);
          this.papers = this.papers.filter((p) => !removed.has(p.id));
          this.selected = [];
          window.dispatchEvent(new CustomEvent("library:changed"));
          if (data.deleted < data.requested) {
            alert(
              "部分论文删除失败（跳过 " +
                (data.requested - data.deleted) +
                " 条）。",
            );
          }
        } else {
          const body = await resp.json().catch(() => ({}));
          alert("批量删除失败: " + (body.detail || ("HTTP " + resp.status)));
        }
      } finally {
        this.busy = false;
      }
    },

    statusText(status) {
      const labels = {
        uploaded: "已上传",
        processing: "处理中",
        ready: "可翻译",
        failed: "处理失败",
      };
      return labels[status] || status;
    },
  };
};
