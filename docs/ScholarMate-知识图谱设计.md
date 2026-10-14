# 论文知识图谱与主题管理设计

> 项目：智能学术论文检索与管理系统（ScholarMate）
> 文档编号：SM-DESIGN-003 · 版本 v1.0 · 编制日期 2026-10-14
> 适用阶段：本科毕业设计（指导教师要求落地检索、分类、主题管理、两级知识图谱）

---

## 0. 摘要

导师给出的要求可以拆成四件事：

1. 用户输入一个或多个领域关键词，系统完成检索；
2. 检索结果分类保存，并支持主题管理；
3. 生成前端渲染的论文知识图谱；
4. 图谱分两种：单次检索的图谱、历史检索的综合图谱，逻辑参考 Obsidian。

把视线收回到今天的代码，会看到比较稳定的规律：检索链路是通的，但每次检索的结果只活在内存和 24 小时缓存里，系统里没有「论文」这个实体，也没有「主题」和「图」。因此这次设计的重点不在检索本身，而在检索之后——把结果存下来、归好类、连成图。

本文给出四组内容：现状与差距、来源与检索编排、主题与分类模型、图谱模型与前端渲染。第 11 节是分阶段实施计划，第 12 节把导师的四条要求翻译成可验证的验收指标。

---

## 1. 要求原文与课题定位

### 1.1 指导教师要求

1. 用户提出一个或多个领域关键词，系统负责检索，并将检索结果分类保存，生成前端技术下的论文知识图谱，支持论文主题的管理、多检索知识图谱关联。
2. 需要解决检索来源问题，保证学术文章来源的多样性。
3. 知识图谱做成两方面：① 单独一次检索的图谱；② 历史检索的综合性图谱。
4. 详情可参考 Obsidian 的实现逻辑。

### 1.2 课题名称

**智能学术论文检索与管理系统的设计与实现**

原名「ScholarMate 学术智能检索与翻译 Agent 桌面应用」随之调整。翻译、ReAct 对话、本地论文库仍然是系统能力的一部分，但论文的定位从「演示性功能」变成「检索与管理的入口」。

---

## 2. 现状拆解

以下结论都来自当前代码，不包含推测。

| 能力 | 现状 | 证据 |
|---|---|---|
| 多源检索 | arXiv 为主源，S2 提供引用量，OpenAlex 兜底；单次请求只查一个源 | `app/api/search.py` 的 `_fetch`、`_search_metadata` |
| 来源数量 | 外部 3 个（arXiv / Semantic Scholar / OpenAlex）+ 本地向量库 | `app/services/` 下四个 service |
| 检索输入 | 单个 `query` 字符串（1–200 字符）+ 单个 `source` | `app/schemas/search.py` 的 `SearchRequest` |
| 结果保存 | 只写 24 小时缓存表 `search_cache`，到期后被清理 | `app/services/cache_service.py`（`CACHE_TTL_SECONDS = 86400`） |
| 检索历史 | `search_history` 表已建模型，但全仓库没有写入点 | `app/models/search_history.py`；grep `SearchHistory` 只命中模型定义与 `__init__` 导入 |
| 论文实体 | 不存在。`uploaded_pdfs` 面向「上传的 PDF 文件」，元数据只有文件名与页数 | `app/models/uploaded_pdf.py` |
| 主题与分类 | 不存在 | grep `topic` / `图谱` 无命中 |
| 图谱 | 不存在 | 同上 |
| Agent 检索 | 5 个工具把结果拼成 JSON 字符串交给 LLM，不落库 | `app/agent/tools.py` |
| 前端 | 侧边栏（会话 / 本地论文库）+ 工作台（对话 / 翻译）+ 检索页 + 论文库页；vendor 目录已本地化 htmx 与 Alpine | `app/templates/`、`app/static/vendor/` |
| 离线约束 | 前端依赖全部本地化，桌面窗口（WebView2）运行，不依赖外网 CDN | `app/templates/base.html` 引用 `/static/vendor/*` |

可以归纳出三处断层：

1. **实体断层**：检索到的论文没有在本地形成稳定标识，同一个 DOI 查两次就是两份数据，跨次检索无法关联；
2. **结构断层**：结果之间只有「同一次返回」这一层关系，没有主题、引用、相似度这些可以连成边的结构；
3. **呈现断层**：前端只有列表，没有关系视图。

---

## 3. 要求到差距的映射

| 导师要求 | 现状 | 需要补的能力 | 对应工作包 |
|---|---|---|---|
| 一个或多个领域关键词 | 单 query 字符串 | 关键词列表输入 + 查询编排 | WBS-12.2 |
| 检索结果分类保存 | 只进 24h 缓存 | 论文实体表 + 检索会话表 + 持久化 | WBS-12.1 |
| 前端论文知识图谱 | 无 | 节点/边模型 + 图谱 API + 图渲染页面 | WBS-13.1 ~ 13.4 |
| 论文主题管理 | 无 | 主题 CRUD + 论文归属调整 | WBS-12.3 |
| 多检索知识图谱关联 | 无 | 跨会话论文归一 + 全局图 | WBS-13.3 |
| 学术文章来源的多样性 | 3 个外部源 | 增加到 6 个来源并做归一合并 | WBS-12.2 |
| 单次检索图谱 | 无 | 以检索会话为范围的子图 | WBS-13.2 |
| 历史综合图谱 | 无 | 全库图 + 过滤与深度控制 | WBS-13.3 |

---

## 4. 检索来源的多样性设计

### 4.1 来源清单

现有三个来源的覆盖面和盲区都比较清楚：arXiv 只覆盖预印本，Semantic Scholar 与 OpenAlex 覆盖全学科元数据但以英文期刊为主。要在答辩时说明「来源多样性」，需要让每个来源承担一个明确的领域角色。

| 来源 | 覆盖范围 | 认证 | 在本系统中的角色 | 状态 |
|---|---|---|---|---|
| arXiv | 物理、数学、计算机、生物等预印本 | 无 | 预印本主力，提供 PDF 直链 | 已接入 |
| Semantic Scholar | 全学科，提供引用量与引用关系 | 可选 key | 引用量与参考文献来源 | 已接入 |
| OpenAlex | 全学科开放元数据 | 无（`mailto` 进礼貌池） | 免 key 兜底 + 引用关系 | 已接入 |
| Crossref | 全学科期刊与会议论文，DOI 权威 | 无（`mailto` 进礼貌池） | DOI 归一与期刊论文覆盖 | 待接入 |
| Europe PMC | 生物医学（含 PubMed 全文记录） | 无 | 生物医学领域覆盖 | 待接入 |
| DBLP | 计算机会议与期刊 | 无 | 计算机领域会议论文覆盖 | 待接入 |

选这六个来源的理由：分别覆盖预印本、通用元数据、出版物登记、生物医学、计算机会议五类数据，接口都是免 key 的公开 HTTP API，符合计划书里「不引入需要海外支付或代理的服务」这条约束（三个新源在国内均可直连，必要时可走已有的本地代理）。

### 4.2 统一来源接口

四个来源各自返回不同结构的 JSON，需要在适配层归一。接口保持在最小集合，避免每接一个源就改一次编排层：

```python
class PaperSource(Protocol):
    name: str                      # "arxiv" | "crossref" | ...
    domains: list[str]             # ["cs"] | ["bio"] | ["general"]
    async def search(self, query: str, *, limit: int,
                     year_from: int | None, year_to: int | None) -> list[PaperItem]: ...
    async def expand(self, external_id: str, kind: str) -> list[PaperItem]: ...
```

`expand(kind)` 用于图谱的按需扩展：`kind="references"` 取该论文的参考文献，`kind="citations"` 取被引论文。arXiv 不提供引用数据，`expand` 抛 `NotSupported`，由编排层回落到 Semantic Scholar 或 OpenAlex。

注册表按领域和全局两级组织：

```python
SOURCE_REGISTRY = SourceRegistry({
    "arxiv": ArxivService(...), "s2": SemanticScholarService(...),
    "openalex": OpenAlexService(...), "crossref": CrossrefService(...),
    "europepmc": EuropePmcService(...), "dblp": DblpService(...),
})
```

### 4.3 归一与去重

跨来源合并的前提是能判断「这两条记录是同一篇论文」。判定顺序按标识强度排列：

1. DOI 归一（小写、去掉 `https://doi.org/` 前缀）；
2. arXiv ID 归一（去掉版本号后缀 `v2`）；
3. Semantic Scholar CorpusId；
4. OpenAlex Work ID；
5. 标题指纹：归一化标题（小写、去标点、去空白）+ 首作者姓氏 + 年份。

合并时字段取并集，冲突按下面的规则处理：

| 字段 | 规则 |
|---|---|
| 标题、摘要 | 取字符最长的一条（摘要通常以 S2 / OpenAlex 最完整） |
| 引用量 | 取最大值 |
| 年份 | 取最早的非空值 |
| 作者 | 取元素最多的列表 |
| `pdf_url` | 优先开放获取直链，其次 arXiv |
| `sources` | 记录全部命中来源，用于前端展示来源覆盖 |

合并结果写回 `papers` 表，`sources_json` 会随检索次数累积，这本身就是「来源多样性」的可展示证据。

### 4.4 限流与降级

各来源的限流参数不同，已有的两个 service 已经提供了限速器和重试策略，新来源沿用同一套写法：

| 来源 | 限速 | 失败处理 |
|---|---|---|
| arXiv | ≥1 次 / 3s（约定） | 失败后回退 S2 / OpenAlex |
| Semantic Scholar | 无 key 时 1 RPS | 429 重试 3 次后回退 OpenAlex |
| OpenAlex | 10 RPS（礼貌池） | 429/5xx 重试 3 次 |
| Crossref | 礼貌池（建议 ≤5 RPS） | 失败单独记录，不影响其他源 |
| Europe PMC | 建议 ≤3 RPS | 同上 |
| DBLP | 建议 ≤1 RPS | 同上 |

编排层对每个来源设置独立超时（8s）与失败隔离：一个来源超时只影响该来源，聚合结果里标注 `failed_sources`，前端提示「Crossref 本次未返回」。

---

## 5. 多关键词检索编排

### 5.1 输入模型

```python
class SearchRunRequest(BaseModel):
    keywords: list[str]              # 1..8 个关键词，去重后按输入顺序
    sources: list[str] = ["all"]     # ["all"] 或指定来源集合
    year_from: int | None = None
    year_to: int | None = None
    per_source: int = 10             # 每个来源的条数上限
    topic_id: int | None = None      # 指定归入主题；为空时走自动分类
```

关键词支持中英文混输。中文关键词在调用英文源前做一次术语映射（例如「低秩适配」→「Low-Rank Adaptation」），映射表存在配置文件里，MVP 先覆盖 30 组常见术语，后续可由 LLM 生成候选映射并缓存。

### 5.2 查询生成

多关键词的检索召回取决于查询怎么拆。策略按顺序执行：

1. 每个关键词单独成一条查询（保证每个方向的召回）；
2. 关键词两两组合成查询（发现交叉方向的论文，例如「LoRA + 医学影像」）；
3. 关键词数量 ≤ 3 时，额外发一条全体合取查询。

单次检索的查询条数上限设为 `2 * len(keywords) + 1`，避免来源限流被打满。

### 5.3 执行与打分

```
keywords -> 查询生成 -> 各来源并行执行（asyncio.gather + 超时隔离）
        -> 归一去重 -> 相关度打分 -> 落库 -> 返回 session_id
```

相关度分数由四项加权，权重写进配置便于论文里做对比实验：

| 因子 | 说明 | 初始权重 |
|---|---|---|
| 关键词命中 | 命中的关键词个数 / 关键词总数 | 0.45 |
| 引用量 | `log1p(citation_count)` 归一化 | 0.25 |
| 年份新鲜度 | 距当前年份越近越高 | 0.20 |
| 来源数量 | 命中来源越多越高（体现多源验证） | 0.10 |

打分结果写入 `search_session_papers.score`，图谱里的节点大小可以直接复用这个分数。

### 5.4 落库

一次检索产生一条 `search_sessions` 记录与若干条 `search_session_papers` 关联。这一步同时补上了当前 `search_history` 只建表不写入的问题。

---

## 6. 主题与分类

### 6.1 主题模型

主题是用户可管理的分类单元，例如「大模型参数高效微调」「兽医影像诊断」。一个主题包含名称、描述、关键词集合与颜色（供图谱着色）。

论文与主题是多对多关系，归属记录带两个属性：

| 字段 | 取值 | 用途 |
|---|---|---|
| `confidence` | 0.0–1.0 | 前端按置信度调整边的透明度 |
| `assigned_by` | `user` / `keyword` / `llm` | 区分人工与自动归属，论文里可做准确率对比 |

### 6.2 三类归类来源

1. **用户指定**：检索时选择已有主题，或新建主题，全部结果归入（`assigned_by=user`，置信度 1.0）；
2. **关键词规则**：主题维护关键词集合，检索关键词命中主题关键词时自动归属（`assigned_by=keyword`，置信度取命中比例）；
3. **LLM 建议**：对未命中的论文批量调用 LLM，输出候选主题与置信度，写入待确认队列，由用户在主题页确认（`assigned_by=llm`）。批量按 20 篇一组，结果按论文指纹缓存，避免重复计费。

规则优先、LLM 兜底的分工，可以控制调用成本：规则能覆盖的常见术语不进入 LLM。

### 6.3 主题管理操作

- 新建、重命名、修改描述与关键词、删除（删除时级联清理归属，不删除论文）；
- 主题合并：把 A 的归属并入 B，A 标记为归档；
- 手动调整论文归属（增量添加 / 移除）；
- 主题统计：论文数、时间跨度、来源分布、平均引用量，用于论文的实验章节。

---

## 7. 知识图谱

### 7.1 节点与边

节点类型：

| 类型 | 标识 | 主要属性 | 大小映射 |
|---|---|---|---|
| `paper` | 归一后的论文 ID | 标题、年份、引用量、来源集合 | 相关度分数或被引量 |
| `topic` | 主题 ID | 名称、颜色 | 关联论文数 |
| `keyword` | 关键词文本 | 命中次数 | 命中论文数 |
| `author` | 作者名归一 | 论文数 | 论文数（全局图默认折叠） |
| `session` | 检索会话 ID | 关键词、时间 | 结果数 |

边类型：

| 边 | 方向 | 来源数据 | 权重 |
|---|---|---|---|
| `belongs_to` | paper → topic | `paper_topics` | confidence |
| `matches` | paper → keyword | 检索命中的关键词 | 命中次数 |
| `cites` | paper → paper | S2 / OpenAlex 引用关系 | 1.0 |
| `similar` | paper — paper | 摘要向量余弦相似度（阈值 0.8） | 相似度 |
| `co_topic` | topic — topic | 同一论文或同一会话共现 | 共现次数 |
| `in_session` | paper → session | `search_session_papers` | 相关度分数 |

`cites` 与 `similar` 落在 `paper_edges` 表；`belongs_to`、`matches`、`in_session`、`co_topic` 由已有关系表在查询时投影，不重复存储。

### 7.2 单次检索图谱

范围是一次检索会话：`session` 节点为中心，向外连该次命中的 `paper`，再接这些论文的 `keyword` 与 `topic`。

用途是回答「这次检索到底检出了什么结构」：哪些关键词检出最多论文、这些论文落在哪些主题上、来源分布如何。

### 7.3 历史综合图谱

范围是全部会话与主题，节点按归一 ID 合并，同一个 DOI 在不同次检索中只出现一次。这样「多检索知识图谱关联」就有了具体含义：两次检索命中同一篇论文时，这篇论文成为连接两个检索的关键词簇与主题簇的桥节点。

全局图默认按度数排序截断到 300 个节点，并提供过滤条件：

- 主题（多选）、年份区间、来源（多选）、最低引用量；
- 邻域深度 1–3 度（以选中节点为中心）；
- 是否展示作者节点、是否只保留有引用边的论文。

### 7.4 与 Obsidian 的对应关系

导师要求参考 Obsidian，两边的概念可以逐项对上：

| Obsidian | 本系统 |
|---|---|
| Note（笔记） | Paper（论文） |
| Folder / Tag | Topic（主题） |
| Wikilink（双链） | 引用边 `cites`、相似边 `similar` |
| Backlink（反向链接） | 论文详情中的「被引 / 引用了谁」列表 |
| Local graph（局部图） | 单次检索图谱 |
| Global graph（全局图） | 历史综合图谱 |
| Graph filter（过滤器） | 主题 / 年份 / 来源 / 引用量过滤 |
| Node size | 相关度分数或引用量 |
| Color group | 主题分组 |
| Depth slider | 邻域深度 1–3 度 |
| Drag to pin | 拖拽固定节点位置 |

差别在于 Obsidian 的边来自用户手写的链接，本系统的边来自检索与引用数据，需要显式区分边类型并在图例中标明。

### 7.5 图数据构建策略

分三档，按成本从低到高：

1. **检索时构建（默认）**：写入 `papers`、`paper_topics`、`search_session_papers`，并计算同批论文之间的 `similar` 边（复用已有的 DashScope Embedding 与余弦相似度）；
2. **按需扩展（用户触发）**：点击节点后调用 `/api/graph/expand`，用 S2 / OpenAlex 拉取该论文的参考文献与被引，写 `cites` 边。这样把限流成本摊到用户操作上，不做全量爬取；
3. **后台补全（可选）**：对引用量高于阈值的论文，在空闲时批量补 `cites` 边，界面显示补全进度。

### 7.6 存储选型

三个候选：

| 方案 | 说明 |
|---|---|
| A. SQLite 关系表 | 复用现有数据库，节点与边分别建表，查询时组图 |
| B. 嵌入式图数据库（Kùzu / SQLite 图扩展） | 支持 Cypher 风格查询与多跳遍历 |
| C. 独立图数据库（Neo4j） | 图能力最完整，但需要额外进程与 JVM |

四个方面对比：

| 维度 | A. SQLite 表 | B. 嵌入式图库 | C. Neo4j |
|---|---|---|---|
| 长期技术债 | 低（无新依赖，SQL 稳定） | 中（库较新，API 可能变动） | 中（版本升级需要迁移） |
| 可扩展性 | 中（多跳查询需写递归 CTE） | 高（原生多跳） | 高 |
| 安全面 | 低（无新进程与端口） | 低 | 中（新增服务端口与认证） |
| 生存风险 | 低（SQLite 为开放标准） | 中（社区规模有限） | 中（商业公司主导，社区版维护节奏不定） |
| 部署成本 | 零 | 低 | 高（桌面应用需内置 JVM） |

选 A。判断依据是部署约束：系统最终要打成 Windows 单机可执行程序，引入 JVM 或额外服务进程会让打包与首启时间明显变差，而毕设规模（数千节点、数万条边）用 SQLite 加索引足够，多跳遍历用递归 CTE 或应用层 BFS 实现。若后续图规模超出预期，`papers` / `paper_edges` 两张表的结构可以直接迁移到图库，迁移成本可控。

### 7.7 前端渲染选型

| 方案 | 说明 |
|---|---|
| A. Cytoscape.js | 图论库，内置力导向 / 同心 / 层次布局与大量图交互，单文件离线可用 |
| B. ECharts graph | 图表库自带关系图，配置化程度高，邻域筛选与节点固定等交互需要自己补 |
| C. D3-force | 灵活度最高，但布局、缩放、拖拽、命中检测都要自己实现 |
| D. sigma.js | WebGL 渲染，万级节点性能好，样式与交互定制成本较高 |

对比：

| 维度 | A. Cytoscape.js | B. ECharts | C. D3 | D. sigma.js |
|---|---|---|---|---|
| 开箱交互 | 高（缩放/拖拽/框选/高亮） | 中 | 低 | 中 |
| 布局算法 | 多（cose、concentric、breadthfirst、grid） | 少 | 需自取 d3-force | 需自取 |
| 离线打包 | 单文件，直接放 vendor 目录 | 单文件 | 单文件 | 单文件 + 依赖 |
| 文档与生态 | 完整，图数据库与生物信息领域常用 | 完整但偏图表 | 完整但偏底层 | 中等 |
| 适用规模 | 千级节点流畅 | 千级 | 取决于自实现 | 万级 |

选 A。系统规模在千级节点以内，Cytoscape.js 自带的多布局与交互省掉大量自研代码，同时与现有做法一致：前端依赖全部本地化到 `app/static/vendor/`，不依赖外网 CDN。

### 7.8 图规模控制

- 服务端：全局图默认 `limit=300`，按度数降序截断；提供 `total` 与 `truncated` 字段，前端提示「已显示 300 / 1240 个节点」；
- 前端：节点数 >500 时关闭标签渲染，只保留 hover 显示；
- 边渲染：`similar` 边按权重取前 N 条，避免密集网格；
- 布局：切换布局时不重新请求数据，只重跑布局算法。

---

## 8. 数据模型

新增五张表，另有一张旧表需要处理。

```sql
-- 论文实体：跨来源归一后的唯一记录
CREATE TABLE papers (
  id                INTEGER PRIMARY KEY,
  doi               TEXT,            -- 小写，已去掉 https://doi.org/ 前缀
  arxiv_id          TEXT,            -- 已去掉版本号后缀
  s2_id             TEXT,
  openalex_id       TEXT,
  title             TEXT NOT NULL,
  normalized_title  TEXT,            -- 标题指纹，用于去重
  abstract          TEXT,
  authors_json      TEXT,            -- ["作者1","作者2"]
  year              INTEGER,
  venue             TEXT,
  citation_count    INTEGER DEFAULT 0,
  sources_json      TEXT,            -- ["arxiv","openalex"]
  url               TEXT,
  pdf_url           TEXT,
  created_at        DATETIME,
  updated_at        DATETIME
);
CREATE UNIQUE INDEX idx_papers_doi ON papers(doi) WHERE doi IS NOT NULL;
CREATE INDEX idx_papers_title_fp ON papers(normalized_title, year);

-- 主题
CREATE TABLE topics (
  id             INTEGER PRIMARY KEY,
  name           TEXT NOT NULL UNIQUE,
  description    TEXT DEFAULT '',
  keywords_json  TEXT,               -- ["lora","低秩适配"]
  color          TEXT DEFAULT '#1f3a5f',
  archived       INTEGER DEFAULT 0,
  created_at     DATETIME
);

-- 论文与主题的归属
CREATE TABLE paper_topics (
  paper_id     INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  topic_id     INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
  confidence   REAL DEFAULT 1.0,
  assigned_by  TEXT DEFAULT 'user',  -- user | keyword | llm
  created_at   DATETIME,
  PRIMARY KEY (paper_id, topic_id)
);

-- 一次检索
CREATE TABLE search_sessions (
  id             INTEGER PRIMARY KEY,
  keywords_json  TEXT NOT NULL,
  sources_json   TEXT,
  year_from      INTEGER,
  year_to        INTEGER,
  status         TEXT DEFAULT 'done',   -- running | done | failed
  result_count   INTEGER DEFAULT 0,
  failed_sources TEXT,
  created_at     DATETIME
);

-- 检索结果与论文的关联
CREATE TABLE search_session_papers (
  session_id         INTEGER NOT NULL REFERENCES search_sessions(id) ON DELETE CASCADE,
  paper_id           INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  rank               INTEGER,
  score              REAL,
  matched_keywords_json TEXT,
  PRIMARY KEY (session_id, paper_id)
);

-- 论文之间的边（引用、相似）
CREATE TABLE paper_edges (
  id            INTEGER PRIMARY KEY,
  src_paper_id  INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  dst_paper_id  INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  edge_type     TEXT NOT NULL,       -- cites | similar
  weight        REAL DEFAULT 1.0,
  created_at    DATETIME,
  UNIQUE (src_paper_id, dst_paper_id, edge_type)
);
CREATE INDEX idx_edges_src ON paper_edges(src_paper_id, edge_type);
CREATE INDEX idx_edges_dst ON paper_edges(dst_paper_id, edge_type);
```

`search_history` 表保留为历史记录的兼容视图，或在启动迁移中合并进 `search_sessions` 后删除——当前该表没有任何写入点，删除不会丢数据。

---

## 9. 接口设计

### 9.1 检索

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/search/run` | 多关键词检索：并行多源、归一去重、打分、落库，返回 `session_id` |
| GET | `/api/search/sessions` | 历史检索列表（分页） |
| GET | `/api/search/sessions/{id}` | 单次检索详情（关键词、来源、结果列表） |
| GET | `/api/search/sources` | 可用来源及其状态（供前端勾选） |

`POST /api/search/run` 请求示例：

```json
{
  "keywords": ["LoRA", "医学影像"],
  "sources": ["all"],
  "year_from": 2024,
  "year_to": 2026,
  "per_source": 10,
  "topic_id": null
}
```

响应包含分来源统计，便于前端展示来源多样性：

```json
{
  "session_id": 12,
  "total": 38,
  "by_source": {"arxiv": 10, "s2": 8, "openalex": 10, "crossref": 6, "europepmc": 3, "dblp": 1},
  "merged": 9,
  "failed_sources": ["dblp"],
  "items": [ /* PaperItem，含 sources 字段 */ ]
}
```

### 9.2 图谱

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/graph/session/{id}` | 单次检索图谱 |
| GET | `/api/graph/global` | 历史综合图谱，支持主题、年份、来源、引用量、深度过滤 |
| POST | `/api/graph/expand` | 按需扩展节点的引用边 |

统一响应结构：

```json
{
  "nodes": [
    {"id": "paper:42", "type": "paper", "label": "Low-Rank Adaptation...",
     "size": 18, "group": "大模型微调", "meta": {"year": 2024, "citations": 91,
     "sources": ["arxiv", "openalex"]}}
  ],
  "edges": [
    {"source": "paper:42", "target": "topic:3", "type": "belongs_to", "weight": 0.8}
  ],
  "stats": {"total": 1240, "shown": 300, "truncated": true}
}
```

### 9.3 主题与论文

| 方法 | 路径 | 说明 |
|---|---|---|
| GET / POST | `/api/topics` | 主题列表 / 新建 |
| PATCH / DELETE | `/api/topics/{id}` | 修改 / 删除 |
| POST | `/api/topics/{id}/merge` | 合并主题 |
| POST / DELETE | `/api/topics/{id}/papers` | 批量增加 / 移除论文归属 |
| POST | `/api/papers/{id}/classify` | 触发自动分类，返回候选主题 |
| GET | `/api/papers` | 论文元数据列表（主题、年份、来源过滤，分页） |

---

## 10. 前端设计

### 10.1 新增页面

| 页面 | 路径 | 内容 |
|---|---|---|
| 知识图谱 | `/graph` | 左控制栏 + 图画布 + 右侧详情抽屉 |
| 主题管理 | `/topics` | 主题卡片列表、关键词维护、论文数、合并与删除 |
| 检索页改造 | `/search` | 关键词标签输入、来源多选、结果写入会话并给出「查看本次图谱」入口 |

### 10.2 图页面交互

- 顶部切换「本次检索 / 历史综合」，选择具体会话；
- 左侧过滤：主题多选、年份区间、来源多选、最低引用量、深度滑块；
- 画布：滚轮缩放、拖拽固定、框选、双击节点展开引用；
- hover 节点高亮一跳邻居并淡化其余节点（对齐 Obsidian 的邻域高亮）；
- 点击节点：右侧抽屉显示论文详情与「引用了谁 / 被谁引用」（反链）列表；
- 布局切换：力导向（默认）/ 同心（按主题分组）/ 层次（按年份）；
- 图例：边类型与节点类型说明。

### 10.3 视觉风格

沿用现有设计系统的纸白、墨色、朱砂三色：节点按主题分配朱砂系的深浅色，边用淡墨线条区分类型（实线为引用、虚线为相似、点线为归属），画布背景保持宣纸质感。图例与筛选控件复用现有 `.btn` / `.tag` 样式，不引入新的设计语言。

---

## 11. 实施阶段

| 阶段 | 内容 | 主要产出 | 预估工期 | 依赖 |
|---|---|---|---|---|
| S1 | 数据层：五张新表 + Repository + 启动迁移 | 模型、仓储、迁移脚本、单测 | 2 天 | - |
| S2 | 来源扩展：统一接口 + Crossref / Europe PMC / DBLP 适配器 + 注册表 | 三个新 service、归一合并、单测 | 3 天 | S1 |
| S3 | 检索编排：多关键词、并行多源、打分、落库 | `SearchOrchestrator`、`POST /api/search/run`、单测 | 3 天 | S2 |
| S4 | 主题与分类：CRUD、规则分类、LLM 建议 | 主题接口、分类服务、主题页 | 3 天 | S3 |
| S5 | 图构建与图谱接口：边计算、单次图、全局图、扩展 | 图服务、三个图接口、单测 | 3 天 | S4 |
| S6 | 前端图谱：Cytoscape 本地化、图页面、详情抽屉 | `/graph` 页面、交互、UI 回归脚本 | 3 天 | S5 |
| S7 | 测试、文档与实验：覆盖率、召回对比实验、来源分布统计 | 测试报告、实验数据、文档 | 3 天 | S6 |

合计约 20 个工作日。与 `Plan.md` 的里程碑对照，S1–S7 安排在 M5 之后、M6（桌面打包）之前，占用 2027 年 1 月上旬到 2 月中旬；若时间紧，S2 可先接 Crossref 一个源，其余两个源后补。

---

## 12. 验收标准

把导师要求逐条翻译成可验证的检查项：

| 编号 | 要求 | 验收方式 | 通过标准 |
|---|---|---|---|
| A1 | 一个或多个关键词检索 | 输入 1 个、3 个关键词各跑一次 | 两次都返回结果，且 3 关键词时命中论文覆盖每个关键词 |
| A2 | 来源多样性 | 查看响应中的 `by_source` | 至少 4 个来源返回结果；`failed_sources` 有明确提示 |
| A3 | 结果分类保存 | 重启应用后查询论文库 | 检索结果仍在库中，可按主题筛选 |
| A4 | 单次检索图谱 | 打开 `/graph` 的本次检索视图 | 节点数 = 论文数 + 关键词数 + 主题数，边包含 `in_session` / `matches` / `belongs_to` |
| A5 | 历史综合图谱 | 先后执行两次含同一论文的检索 | 该论文在图谱中只出现一次，且同时连接两次检索的关键词簇 |
| A6 | 主题管理 | 新建、重命名、合并、删除主题 | 四种操作生效，论文归属随之更新，论文本身不被删除 |
| A7 | 图谱交互 | 过滤、缩放、拖拽、点击查看详情与反链 | 交互全部可用，详情包含引用与被引列表 |
| A8 | 图规模控制 | 全库图谱节点超过上限时 | 响应返回 `truncated=true`，界面提示已显示数量 |

另外补充三组可写进论文的实验数据：

1. **来源覆盖对比**：同一组 20 个查询在「单源 arXiv」与「六源聚合」下的召回数量与去重率；
2. **分类准确率**：100 篇论文的规则分类与 LLM 分类结果对比人工标注；
3. **图谱规模与性能**：100 / 500 / 1000 节点下的接口响应时间与前端首帧时间。

---

## 13. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 新增来源限流或临时不可用 | 聚合结果缺失 | 每源独立超时与失败隔离，响应标注 `failed_sources`，缓存 24h 结果 |
| DOI 缺失导致去重不准 | 同一论文出现多个节点 | 多级标识回退到标题指纹，提供手动合并入口 |
| 引用数据获取成本高 | 图谱边稀疏 | 默认只建同批相似边，引用边按需扩展，不做全量爬取 |
| LLM 分类费用超出预算 | 成本失控 | 规则优先，LLM 只处理未命中论文，结果按论文指纹缓存 |
| 图谱规模增长导致前端卡顿 | 交互体验下降 | 服务端截断 + 度数排序，前端节点数超阈值时关闭标签 |
| 中文关键词在英文源召回低 | 结果为空 | 术语映射表 + LLM 生成候选映射并缓存 |
| 工期与论文撰写冲突 | 无法按时交付 | 阶段计划留 3 天缓冲，S2 可裁剪到单源，实验数据随阶段产出一并记录 |

---

## 14. 对既有文档与代码的影响

需要同步修改的地方：

1. `Plan.md`
   - 1.2 项目定位：课题名称改为「智能学术论文检索与管理系统的设计与实现」；
   - 2.2 范围内功能：新增「论文实体库与主题管理」「论文知识图谱」两条；
   - 2.3 范围外：删除「引文网络分析与学术影响力图谱」这一条（已进入范围）；
   - 5.1 里程碑 / 5.2 阶段计划：插入 S1–S7 阶段；
   - 6.1 WBS：新增 WBS-12（论文库与主题管理）与 WBS-13（知识图谱）。
2. `README.md`：更新项目定位与路线表。
3. 代码层：新增 `app/models/paper.py`、`app/services/search_orchestrator.py`、`app/services/graph_service.py`、`app/api/graph.py`、`app/api/topics.py`；`app/api/search.py` 增加 `/run` 入口，保留现有 `POST /api/search` 供检索页使用。

---

## 15. 收束

导师的四条要求落到工程上，是「把检索结果从一次性输出变成可复用资产」这件事的三个侧面：论文实体解决唯一标识，主题解决分类归属，图谱解决关系呈现。单次检索图谱与历史综合图谱的差别，本质上是查询范围与节点合并粒度的差别，和 Obsidian 的局部图与全局图是同一个结构。

下一步按 S1 → S3 的顺序推进，先把数据层与检索编排做出来，图谱与前端接在其后。数据层一旦稳定，图谱和主题管理都是在同一套表上追加查询与视图，不会反复改动已有模块。
