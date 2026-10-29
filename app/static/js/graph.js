// 知识图谱页：Cytoscape 渲染、过滤、节点详情与按需扩展
// 注意：cytoscape 实例放在模块作用域，避免被 Alpine 的响应式代理包装。
let cy = null;

const GRAPH_STYLE = [
  {
    selector: "node",
    style: {
      "background-color": "#2a251e",
      width: "data(size)",
      height: "data(size)",
      label: "data(label)",
      "font-family": "Georgia, 'Noto Serif SC', serif",
      "font-size": 10,
      color: "#2a251e",
      "text-valign": "bottom",
      "text-margin-y": 6,
      "text-wrap": "ellipsis",
      "text-max-width": "120px",
      "border-width": 1,
      "border-color": "rgba(42,37,30,0.22)",
      "transition-property": "background-color, border-color, opacity",
      "transition-duration": "150ms",
    },
  },
  {
    selector: 'node[type="topic"]',
    style: {
      "background-color": "#a8452c",
      shape: "round-rectangle",
      "text-valign": "center",
      "text-margin-y": 0,
      color: "#f6f1e6",
      "font-size": 11,
      "border-width": 0,
    },
  },
  {
    selector: 'node[type="keyword"]',
    style: {
      "background-color": "#3f5d43",
      shape: "diamond",
      "font-size": 10,
      color: "#3f5d43",
    },
  },
  {
    selector: 'node[type="session"]',
    style: {
      "background-color": "#1f3a5f",
      shape: "round-rectangle",
      "text-valign": "center",
      "text-margin-y": 0,
      color: "#f6f1e6",
      "font-size": 11,
      "border-width": 0,
    },
  },
  {
    selector: "edge",
    style: {
      width: "mapData(weight, 0, 1, 0.8, 3)",
      "line-color": "rgba(42,37,30,0.32)",
      "curve-style": "bezier",
      opacity: 0.8,
    },
  },
  {
    selector: 'edge[type="cites"]',
    style: {
      "line-color": "rgba(168,69,44,0.6)",
      "target-arrow-shape": "triangle",
      "target-arrow-color": "rgba(168,69,44,0.6)",
      "arrow-scale": 0.7,
    },
  },
  {
    selector: 'edge[type="belongs_to"]',
    style: { "line-color": "rgba(168,69,44,0.32)", "line-style": "dashed" },
  },
  {
    selector: 'edge[type="matches"]',
    style: { "line-color": "rgba(63,93,67,0.4)", "line-style": "dotted" },
  },
  {
    selector: 'edge[type="in_session"]',
    style: { "line-color": "rgba(31,58,95,0.32)" },
  },
  { selector: ".faded", style: { opacity: 0.1 } },
  {
    selector: "node:selected",
    style: { "border-width": 3, "border-color": "#a8452c" },
  },
];

window.graphApp = function () {
  return {
    mode: "session",
    loading: false,
    sessions: [],
    topics: [],
    sessionId: null,
    topicId: "",
    yearFrom: "",
    yearTo: "",
    source: "",
    minCitations: 0,
    layoutName: "cose",
    nodeCount: 0,
    stats: { total: 0, shown: 0, truncated: false },
    selected: null,
    selectedLinks: [],
    expanding: false,
    toast: "",

    async init() {
      await Promise.all([this.loadTopics(), this.loadSessions()]);
      if (!this.sessionId && this.sessions.length) {
        this.sessionId = this.sessions[0].id;
      }
      await this.reload();
    },

    async loadTopics() {
      const resp = await fetch("/api/topics");
      if (resp.ok) this.topics = await resp.json();
    },

    async loadSessions() {
      const resp = await fetch("/api/search/sessions?limit=30");
      if (!resp.ok) return;
      this.sessions = await resp.json();
      if (!this.sessionId && this.sessions.length) {
        this.sessionId = this.sessions[0].id;
      }
    },

    subtitle() {
      if (this.mode === "session") {
        const current = this.sessions.find((s) => s.id === this.sessionId);
        return current
          ? "单次检索 · " + current.keywords.join(" / ") + " · " + current.result_count + " 篇"
          : "单次检索 · 选择一次检索查看其结构";
      }
      return "历史综合 · 跨会话合并同一篇论文，展示主题与引用关系";
    },

    sessionLabel(session) {
      const keywords = session.keywords.length ? session.keywords.join(" / ") : "未命名检索";
      return "#" + session.id + " · " + keywords + " · " + session.result_count + " 篇";
    },

    setMode(mode) {
      if (this.mode === mode) return;
      this.mode = mode;
      this.closeDetail();
      this.reload();
    },

    buildUrl() {
      if (this.mode === "session") {
        return this.sessionId ? "/api/graph/session/" + this.sessionId : "";
      }
      const params = new URLSearchParams();
      if (this.topicId) params.set("topic_id", this.topicId);
      if (this.yearFrom) params.set("year_from", this.yearFrom);
      if (this.yearTo) params.set("year_to", this.yearTo);
      if (this.source) params.set("source", this.source);
      if (this.minCitations) params.set("min_citations", this.minCitations);
      const query = params.toString();
      return "/api/graph/global" + (query ? "?" + query : "");
    },

    async reload() {
      const url = this.buildUrl();
      if (!url) {
        this.nodeCount = 0;
        this.stats = { total: 0, shown: 0, truncated: false };
        return;
      }
      this.loading = true;
      try {
        const resp = await fetch(url);
        if (!resp.ok) {
          this.nodeCount = 0;
          return;
        }
        const data = await resp.json();
        this.stats = data.stats || { total: 0, shown: 0, truncated: false };
        this.render(data);
      } finally {
        this.loading = false;
      }
    },

    render(data) {
      const elements = [
        ...data.nodes.map((node) => ({
          data: {
            id: node.id,
            label: node.label,
            type: node.type,
            size: node.size,
            meta: node.meta || {},
          },
        })),
        ...data.edges.map((edge, index) => ({
          data: {
            id: "edge-" + index,
            source: edge.source,
            target: edge.target,
            type: edge.type,
            weight: edge.weight,
          },
        })),
      ];
      this.nodeCount = data.nodes.length;
      if (!cy) {
        cy = cytoscape({
          container: this.$refs.canvas,
          elements,
          style: GRAPH_STYLE,
          layout: this.layoutOptions(),
          wheelSensitivity: 0.18,
          minZoom: 0.2,
          maxZoom: 3,
        });
        cy.on("tap", "node", (event) => this.selectNode(event.target));
        cy.on("tap", (event) => {
          if (event.target === cy) this.closeDetail();
        });
        cy.on("mouseover", "node", (event) => this.highlight(event.target));
        cy.on("mouseout", "node", () => this.clearHighlight());
        cy.on("dbltap", 'node[type="paper"]', (event) =>
          this.expandNode(event.target),
        );
        // 供 UI 回归脚本读取实例状态
        window.__graphCy = cy;
      } else {
        cy.elements().remove();
        cy.add(elements);
        cy.layout(this.layoutOptions()).run();
      }
      if (data.nodes.length) {
        cy.fit(undefined, 46);
      }
    },

    layoutOptions() {
      const options = { name: this.layoutName, animate: false, padding: 46 };
      if (this.layoutName === "cose") {
        options.nodeRepulsion = 4200;
        options.idealEdgeLength = 92;
        options.gravity = 0.35;
        options.numIter = 900;
      }
      if (this.layoutName === "concentric") {
        options.concentric = (node) => node.degree();
        options.levelWidth = 14;
        options.minNodeSpacing = 18;
      }
      if (this.layoutName === "breadthfirst") {
        options.spacingFactor = 1.2;
        options.directed = false;
      }
      return options;
    },

    runLayout() {
      if (!cy) return;
      cy.layout(this.layoutOptions()).run();
      cy.fit(undefined, 46);
    },

    highlight(node) {
      cy.elements().addClass("faded");
      node.removeClass("faded");
      node.neighborhood().removeClass("faded");
    },

    clearHighlight() {
      if (cy) cy.elements().removeClass("faded");
    },

    selectNode(node) {
      this.selected = {
        id: node.id(),
        type: node.data("type"),
        label: node.data("label"),
        meta: node.data("meta") || {},
      };
      this.selectedLinks = node
        .neighborhood("node")
        .map((neighbor) => ({
          id: neighbor.id(),
          type: neighbor.data("type"),
          label: neighbor.data("label"),
        }))
        .slice(0, 12);
    },

    closeDetail() {
      this.selected = null;
      this.selectedLinks = [];
    },

    focusNode(id) {
      if (!cy) return;
      const node = cy.getElementById(id);
      if (!node || node.empty()) return;
      cy.animate({ center: { eles: node }, zoom: 1.4 }, { duration: 260 });
      this.selectNode(node);
    },

    async expandSelected() {
      if (!this.selected || this.selected.type !== "paper" || this.expanding) return;
      await this.expandPaper(Number(this.selected.id.replace("paper:", "")));
    },

    async expandNode(node) {
      await this.expandPaper(Number(node.id().replace("paper:", "")));
    },

    async expandPaper(paperId) {
      if (this.expanding) return;
      this.expanding = true;
      try {
        const resp = await fetch("/api/graph/expand", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ paper_id: paperId, kinds: ["references"] }),
        });
        const data = await resp.json();
        if (!resp.ok) {
          this.toast = data.detail || "扩展失败";
          return;
        }
        this.toast = data.reason
          ? data.reason
          : "关联 " + data.related_papers + " 篇，新增 " + data.added_edges + " 条引用边";
        if (this.mode === "global") await this.reload();
      } catch (err) {
        this.toast = "扩展失败：" + err.message;
      } finally {
        this.expanding = false;
        setTimeout(() => {
          this.toast = "";
        }, 4200);
      }
    },

    typeLabel(type) {
      const labels = {
        paper: "论文",
        topic: "主题",
        keyword: "关键词",
        session: "检索会话",
      };
      return labels[type] || type || "";
    },

    statsText() {
      if (!this.nodeCount) return "";
      const base = this.stats.shown + " 个节点";
      return this.stats.truncated
        ? base + " · 已截断（总计 " + this.stats.total + "）"
        : base + " · 共 " + this.stats.total + " 篇论文";
    },
  };
};
