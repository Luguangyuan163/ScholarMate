// 侧边栏：会话列表 / 本地论文库 / 上传 PDF / 导航
window.appSidebar = function () {
  return {
    conversations: [],
    uploaded: [],
    collection: [],
    loading: true,
    currentId: null,
    autoSave: false,

    async init() {
      const params = new URLSearchParams(window.location.search);
      this.currentId = params.get("conv") ? Number(params.get("conv")) : null;
      // 默认关闭自动收藏：仅当用户显式开启（sm_auto_save=1）时才自动入库
      this.autoSave = localStorage.getItem("sm_auto_save") === "1";
      await this.refresh();
      window.addEventListener("library:changed", () => this.refresh());
    },

    persistAutoSave() {
      localStorage.setItem("sm_auto_save", this.autoSave ? "1" : "0");
    },

    async refresh() {
      await Promise.all([this.loadConversations(), this.loadLibrary()]);
      this.loading = false;
    },

    async loadConversations() {
      const resp = await fetch("/api/conversations");
      if (resp.ok) this.conversations = await resp.json();
    },

    async loadLibrary() {
      const [pdfResp, colResp] = await Promise.all([
        fetch("/api/papers"),
        fetch("/api/papers/collection"),
      ]);
      if (pdfResp.ok) this.uploaded = await pdfResp.json();
      if (colResp.ok) this.collection = await colResp.json();
    },

    newConversation() {
      window.location.href = "/agent";
    },

    async uploadPdf(event) {
      const file = event.target.files && event.target.files[0];
      if (!file) return;
      const form = new FormData();
      form.append("file", file);
      try {
        const resp = await fetch("/api/pdf/upload", { method: "POST", body: form });
        if (!resp.ok) {
          const body = await resp.json().catch(() => ({}));
          alert("上传失败: " + (body.detail || ("HTTP " + resp.status)));
          return;
        }
        const data = await resp.json();
        window.location.href = "/translate?pdf=" + data.pdf_id;
      } catch (err) {
        alert("上传失败: " + err.message);
      } finally {
        event.target.value = "";
      }
    },

    openUploadedPdf(p) {
      const workbench = ["/", "/agent", "/translate"].includes(
        window.location.pathname,
      );
      if (workbench) {
        window.dispatchEvent(
          new CustomEvent("sm:open-translation", {
            detail: { pdfId: p.id, filename: p.filename },
          }),
        );
      } else {
        window.location.href = "/?pdf=" + p.id;
      }
    },

    async deleteConversation(c) {
      if (!confirm("确定删除会话《" + c.title + "》？删除后不可恢复。")) return;
      const resp = await fetch("/api/conversations/" + c.id, { method: "DELETE" });
      if (resp.ok) {
        if (this.currentId === c.id) window.location.href = "/agent";
        window.dispatchEvent(new CustomEvent("library:changed"));
      } else {
        alert("删除失败: HTTP " + resp.status);
      }
    },

    async deleteUploaded(p) {
      if (!confirm("确定删除论文《" + p.filename + "》？删除后不可恢复。")) return;
      const resp = await fetch("/api/papers/" + p.id, { method: "DELETE" });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        alert("删除失败: " + (body.detail || ("HTTP " + resp.status)));
        return;
      }
      window.dispatchEvent(new CustomEvent("library:changed"));
    },

    async deleteCollection(p) {
      if (!confirm("确定删除收藏《" + p.title + "》？")) return;
      const resp = await fetch("/api/papers/collection/" + p.id, { method: "DELETE" });
      if (!resp.ok) {
        alert("删除失败: HTTP " + resp.status);
        return;
      }
      window.dispatchEvent(new CustomEvent("library:changed"));
    },

    isPage(path) {
      return window.location.pathname === path;
    },
  };
};
