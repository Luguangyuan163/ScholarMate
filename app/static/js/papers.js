// 论文库：列表加载与删除
window.libraryApp = function () {
  return {
    papers: [],
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
