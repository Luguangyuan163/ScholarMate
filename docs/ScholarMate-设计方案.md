# ScholarMate（学术伴侣）设计方案 v3.0 —— Windows 桌面版

> **项目定位**：面向学术论文的智能检索、翻译与分类 Agent 桌面应用（毕业设计）
> **技术栈**：Python FastAPI（本地服务）+ pywebview（桌面壳）+ SQLite + ChromaDB + 多 LLM 可切换
> **文档版本**：v3.0（2026-08-04）

## 修订记录

| 版本 | 日期 | 修订内容 |
|---|---|---|
| v1.0 | 2026-08-03 | 初稿（Web 应用形态） |
| v2.0 | 2026-08-03 | 模型名、Embedding、SSE、S2 优先级等技术修正 |
| v3.0 | 2026-08-04 | 应用形态改为 Windows 桌面应用：新增 pywebview 桌面壳与本地服务生命周期设计、线程模型、PyInstaller 打包方案；调整目录结构、依赖、阶段计划与风险表 |

---

## 一、项目概述

ScholarMate 是一个基于大语言模型的智能学术助手，交付形态为 **Windows 桌面应用**（单机 exe，双击即用，不依赖浏览器）。核心功能：

1. **论文查询**：多源检索（arXiv + Semantic Scholar + 用户上传 PDF）；
2. **PDF 翻译**：论文 PDF 内容提取 + LLM 翻译 + 双语对照输出；
3. **智能 Agent**：ReAct 模式——理解用户意图 → 调用搜索工具 → 分类整理 → 流式输出结果。

应用内部运行一个仅监听本机回环地址的 FastAPI 本地服务，UI 由内嵌 WebView2 渲染为原生桌面窗口。该形态在业界有成熟先例（Windows 大量应用基于 WebView2，Electron 类应用同理），且不依赖外部部署设施。

---

## 二、环境与工具准备

### 2.1 基础环境

| 项目 | 要求 | 说明 |
|---|---|---|
| Python | 3.11+ | 已验证本机 Python 3.12.2 |
| 包管理 | Poetry 或 pip + venv | 本方案按 Poetry 编写 |
| Git | 2.x | 已验证本机 Git 2.45.1 |
| IDE | VS Code + Python/Pylance | 或 PyCharm |
| 数据库 | SQLite 3.35+ | Python 内置，支持 WAL 模式 |
| 桌面运行时 | WebView2 | Windows 11 内置；Windows 10 需安装，打包程序启动时检测 |
| OCR（可选） | Tesseract 5.x | 默认不做；如需启用，Windows 使用 UB-Mannheim 安装包，并确保 `tesseract` 在 PATH |

### 2.2 初始化命令

```bash
python --version                # 确认 ≥ 3.11
mkdir scholar-mate && cd scholar-mate
git init
python -m venv .venv
.venv\Scripts\activate          # Windows
poetry add pywebview fastapi uvicorn ...  # 依赖见 §6
```

### 2.3 外部账号与服务申请（优先级排序）

| 序号 | 服务 | 用途 | 费用 | 申请方式 |
|---|---|---|---|---|
| 1 | **DeepSeek API** | 主力 LLM | 极低（V4-Pro 输入 ¥3/百万 token、输出 ¥6/百万 token，缓存命中 ¥0.025/百万 token） | [platform.deepseek.com](https://platform.deepseek.com)，注册后充值 ¥20 |
| 2 | **DashScope（阿里云百炼）** | Embedding 向量 + 备用 LLM | 免费额度 | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com) |
| 3 | **arXiv API** | 论文检索（主力数据源） | 免费，无需 Key | 无需注册 |
| 4 | **Semantic Scholar API** | 引用量 + 论文详情（核心） | 免费（申请 key 后 1 RPS） | [api.semanticscholar.org](https://api.semanticscholar.org/api-docs) |
| 5 | Anthropic API Key | Claude 模型（可选） | 按量付费 | 暂不申请 |

> **策略**：当前需申请 DeepSeek、DashScope、Semantic Scholar 三个账号；arXiv 无需注册。Claude 作为可选增强，不进入核心路径。

---

## 三、技术选型与理由

### 3.1 应用形态：pywebview 桌面壳

| 对比 | pywebview + FastAPI | PySide6 / Qt | Electron |
|---|---|---|---|
| 应用形态 | 原生窗口 + WebView2 渲染 | 原生控件 | 原生窗口 + Chromium |
| 对现有后端复用 | 完全复用（服务层不变） | 服务层复用，前端全重写 | 需 Node + Python 双栈 |
| UI 开发效率 | 高（HTML/CSS） | 中（QSS/QML） | 高 |
| 打包体积 | 中（~100-200MB，含 Python） | 中 | 大（~200MB+ Chromium） |
| 技术栈统一度 | 单一 Python | 单一 Python | Python + JavaScript 双栈 |
| 答辩解释成本 | 中（本地服务 + 内嵌 WebView） | 低 | 低 |

**结论**：选择 pywebview。理由：

1. 本项目核心竞争力在 Agent 与检索后端，服务层代码在桌面化过程中零改动；
2. UI 复用 HTML/CSS/JS，开发效率高于 Qt 控件布局，界面更容易做出现代观感；
3. 单一 Python 技术栈，避免 Electron 的 Node sidecar 复杂度；
4. 本地服务仅监听 127.0.0.1，不对外暴露，单机交付形态清晰。

### 3.2 本地服务框架：FastAPI

| 维度 | FastAPI | Flask |
|---|---|---|
| 异步支持 | 原生 async/await | 需 Quart 等扩展 |
| LLM API 调用 | 异步非阻塞（2-10s 不卡界面） | 同步阻塞 |
| API 文档 | `/docs` 自动生成 Swagger | 需手动或插件 |
| 流式响应 | 支持 SSE | 需额外处理 |
| 数据校验 | Pydantic 内置 | 需手动或 marshmallow |

**结论**：FastAPI。LLM 调用是 I/O 密集场景，异步是刚性需求。

> 注意：PyMuPDF、pdfplumber、ChromaDB、tiktoken 为同步库，在 async 路由中需通过 `anyio.to_thread`（线程池）执行，避免阻塞事件循环与 SSE 流。

### 3.3 前端方案：Jinja2 + HTMX + Alpine.js（在桌面窗口内渲染）

- 页面由本地服务渲染，WebView2 加载 `http://127.0.0.1:<port>`；
- Jinja2 模板 + HTMX（处理 AJAX）+ Alpine.js（处理客户端状态），零构建步骤；
- 与浏览器开发模式完全一致：开发期用浏览器调试，打包后同一套页面在桌面窗口内运行。

### 3.4 数据库：SQLite + ChromaDB

| 数据库 | 用途 | 特性 |
|---|---|---|
| SQLite | 论文元数据、查询历史、翻译缓存 | WAL 模式、SQLAlchemy 2.0 ORM、零运维 |
| ChromaDB | 向量存储（语义检索） | 嵌入式运行，数据落盘到 `data/chroma_db` |

### 3.5 PDF 处理

| 库 | 用途 | 选型理由 |
|---|---|---|
| PyMuPDF (fitz) | 文本提取（主力） | 速度最快，中英文混排支持好 |
| pdfplumber | 表格/双栏提取（辅助） | 复杂排版容错更好 |
| pytesseract + Pillow | OCR（默认不做） | 扫描版 PDF 后备，需额外安装 Tesseract 二进制 |

> **务实策略**：翻译输出为段对段双语对照 Markdown/HTML，不追求 PDF 排版 1:1 还原。PDF 双栏/公式提取是最高风险项，阶段二开工前先用 3 篇目标论文做提取小样验证。

### 3.6 Agent 框架：自建 ReAct 循环

不使用 LangChain，理由：

- LangChain 版本兼容问题频发，调试成本高；
- 本项目 Agent 工作流是固定的 ReAct 模式（Think → Act → Observe → Loop），约 200 行代码；
- 自建 Agent 在答辩中更能体现技术深度。

自建 ReAct 主循环：

```python
async def agent_loop(user_query: str, tools: list[Tool], max_iter: int = 5):
    messages = [SystemMessage(SYSTEM_PROMPT), HumanMessage(user_query)]
    for _ in range(max_iter):
        response = await llm.chat(messages, tools=tools)
        if response.has_tool_calls():
            for tc in response.tool_calls:
                result = await execute_tool(tc)
                messages.append(ToolMessage(result))
        else:
            yield response.content  # 流式输出最终结果
            return
```

> 实现要点：工具调用结果需解析 JSON；循环需设置最大迭代次数与超时；工具执行失败应作为观察结果回传，而不是终止对话。

### 3.7 LLM 多模型支持

**主力模型：DeepSeek**（`deepseek-v4-flash` 通用对话 / `deepseek-v4-pro` 复杂规划）。

| 对比 | DeepSeek | 通义千问 | Claude |
|---|---|---|---|
| 价格（2026-08 价目） | V4-Pro 输入 ¥3、输出 ¥6 / 百万 token | ¥2-4 / 百万 token | ~¥100 / 百万 token |
| API 兼容 | 完全兼容 OpenAI SDK | 兼容 OpenAI SDK | 需专用 SDK |
| 中英文能力 | 双语优秀 | 中文优秀 | 英文强、中文弱 |
| 国内访问 | 直连 | 直连 | 需代理 |

> 模型名说明：`deepseek-chat` / `deepseek-reasoner` 已于 2026-07-24 弃用（旧名分别对应 `deepseek-v4-flash` 的非思考与思考模式）。代码与配置统一使用新模型名。

工厂模式实现多模型切换：

```python
# core/llm_client.py
def get_llm_client() -> LLMClient:
    provider = settings.LLM_PROVIDER  # "deepseek" | "qwen" | "claude"
    if provider == "deepseek":
        return DeepSeekClient(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com"
        )
    elif provider == "qwen":
        return QwenClient(settings.DASHSCOPE_API_KEY)
    elif provider == "claude":
        return ClaudeClient(settings.ANTHROPIC_API_KEY)
```

DeepSeek 兼容 OpenAI SDK：

```python
from openai import AsyncOpenAI

client = AsyncOpenAI(
    api_key="sk-xxx",
    base_url="https://api.deepseek.com"
)

response = await client.chat.completions.create(
    model="deepseek-v4-flash",  # 通用对话
    # model="deepseek-v4-pro",  # 复杂规划
    messages=[...]
)
```

### 3.8 Embedding 方案

**选择 DashScope text-embedding-v3**，理由：

- DeepSeek 官方 API 未提供 Embedding 接口（截至 2026-08，社区仍在申请该功能）；
- DashScope 国内直连、有免费额度、兼容 OpenAI SDK；
- 备选：本地 BGE-M3（离线运行，答辩断网时仍可演示向量检索；打包体积较大，默认不内置）。

```python
from openai import AsyncOpenAI

embed_client = AsyncOpenAI(
    api_key=settings.DASHSCOPE_API_KEY,
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

resp = await embed_client.embeddings.create(
    model="text-embedding-v3",
    input=["论文段落文本"]
)
```

> 离线演示策略：`seed_demo.py` 预置少量论文及其**预生成向量**，答辩断网时本地检索与翻译缓存仍可演示，不依赖 Embedding API。

### 3.9 SSE 流式方案

接口设计为 `POST /api/agent/chat`（SSE 响应）。由于浏览器 `EventSource` 仅支持 GET，前端采用 **fetch + ReadableStream 解析 SSE**：

```js
const resp = await fetch("/api/agent/chat", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ query }),
});
const reader = resp.body.getReader();
const decoder = new TextDecoder();
while (true) {
  const { value, done } = await reader.read();
  if (done) break;
  const text = decoder.decode(value, { stream: true });
  // 按 "data: " 前缀逐条解析并追加到消息区
}
```

### 3.10 桌面生命周期与线程模型

**启动时序**：

1. `run.py` 解析配置（host=127.0.0.1，port 优先固定值、冲突时自动分配空闲端口）；
2. 后台线程启动 Uvicorn（独立 asyncio 事件循环）；
3. 轮询 `/api/health` 直至服务就绪（超时 10s）；
4. 主线程创建 pywebview 窗口，加载 `http://127.0.0.1:<port>`；
5. 窗口关闭 → 向服务线程发送停止信号 → 等待退出 → 进程结束。

**线程模型**：

| 线程 | 职责 | 说明 |
|---|---|---|
| 主线程 | pywebview 窗口事件循环 | Windows 上 pywebview 必须在主线程创建 |
| 服务线程 | Uvicorn / asyncio 事件循环 | 承载全部 API 与 LLM 调用 |
| 工作线程 | 同步库执行 | PyMuPDF / pdfplumber / ChromaDB 经 `anyio.to_thread` 执行 |

**端口安全**：仅监听 127.0.0.1；同源访问，无需 CORS；单用户本地使用，不做鉴权。

### 3.11 打包方案（PyInstaller）

- 模式：one-folder（启动更快、数据文件路径更稳定），产出 `dist/ScholarMate/`，可选 Inno Setup 制作安装包；
- 需要打包的资源：`templates/`、`static/`、`docs/`（可选）、运行时生成的 `data/`（首次运行创建）；
- 隐藏导入：chromadb、uvicorn 相关依赖通过 `.spec` 文件显式声明，避免打包遗漏；
- WebView2：Windows 11 内置；Windows 10 启动时检测，缺失则提示安装；
- 验证清单：未安装 Python 的机器上运行全流程（搜索 / Agent / 翻译 / 本地检索）。

---

## 四、系统架构

### 4.1 整体架构图

```
┌──────────────────────────────────────────────────────────────┐
│               pywebview 桌面窗口（WebView2 渲染）             │
│   搜索页 │ Agent 对话页（SSE）│ PDF 翻译页 │ 论文库管理页      │
│           Jinja2 + HTMX + Alpine.js + fetch/SSE              │
└─────────────────────────────┬────────────────────────────────┘
                              │ http://127.0.0.1:<port>
┌─────────────────────────────┴────────────────────────────────┐
│              FastAPI 本地服务（仅监听 127.0.0.1）              │
│   /api/search  /api/agent/chat  /api/pdf/*  /api/papers/*    │
└─────────────────────────────┬────────────────────────────────┘
                              │
┌─────────────────────────────┴────────────────────────────────┐
│                       服务层 (Services)                       │
│  ┌──────────────┐  ┌──────────────────┐  ┌────────────────┐ │
│  │ ArxivService │  │SemanticScholarSvc│  │   PDFService   │ │
│  │  (arXiv API) │  │  (S2, 引用量)    │  │ (提取/分块)    │ │
│  └──────┬───────┘  └────────┬─────────┘  └───────┬────────┘ │
│         └───────────────────┼────────────────────┘          │
│                     ┌───────┴────────┐                       │
│                     │   Agent 层      │                       │
│                     │  ReAct 主循环    │                       │
│                     │  Tool 工具集     │                       │
│                     └───────┬────────┘                       │
└─────────────────────────────┼───────────────────────────────┘
                              │
┌─────────────────────────────┴───────────────────────────────┐
│                       基础设施层                               │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐  ┌──────────┐ │
│  │ SQLite   │  │ ChromaDB │  │ LLM Client   │  │FileSystem│ │
│  │ (元数据) │  │ (向量)   │  │ (多模型工厂) │  │(PDF存储) │ │
│  │          │  │          │  │ Embedding:   │  │          │ │
│  │          │  │          │  │ DashScope v3 │  │          │ │
│  └──────────┘  └──────────┘  └──────────────┘  └──────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 启动时序图

```
run.py ──▶ 启动 Uvicorn 服务线程 ──▶ 轮询 /api/health
    │                                     │ 就绪
    │◀────────────────────────────────────┘
    ├─▶ 创建 pywebview 窗口（主线程）
    │        │
    │        ▼
    │   加载 http://127.0.0.1:<port>
    │        │
    │        ▼
    │   用户操作（SSE 流式 / 检索 / 翻译）
    │        │
    │        ▼
    │   窗口关闭 ──▶ 停止服务线程 ──▶ 进程退出
```

### 4.3 Agent 工作流（ReAct 模式）

用户示例：「找 5 篇 2024 年关于 LoRA 微调的论文，按引用量排序，翻译摘要」

```
┌─ Agent Loop ──────────────────────────────────────────────┐
│                                                            │
│  ┌──────────┐    ┌──────────────┐    ┌─────────────────┐  │
│  │  THINK   │───▶│     ACT      │───▶│    OBSERVE      │  │
│  │ LLM 分析  │    │ 执行工具调用  │    │ 收集工具返回结果 │  │
│  │ 意图+规划│    │              │    │                  │  │
│  └──────────┘    └──────────────┘    └────────┬─────────┘  │
│       ↑                                       │            │
│       │          结果不充分，继续循环           │            │
│       └───────────────────────────────────────┘            │
│                      结果充分                              │
│                         ↓                                  │
│               ┌─────────────────┐                          │
│               │   SYNTHESIZE    │                          │
│               │ LLM 综合输出结果 │                          │
│               └─────────────────┘                          │
└────────────────────────────────────────────────────────────┘
                             │
                             ▼
              SSE 流式输出 → 分类论文列表 + 摘要翻译
```

> 说明：「按引用量排序」依赖 Semantic Scholar 的 `citationCount` 字段，arXiv API 不提供引用数据。因此 S2 为核心工具而非可选。

### 4.4 Agent 工具清单

| 工具名 | 功能 | 参数 | 优先级 |
|---|---|---|---|
| `search_arxiv` | 搜索 arXiv 论文 | query, max_results, year_from, year_to | 核心 |
| `search_semantic_scholar` | 语义搜索 S2 + 引用量 | query, limit | 核心 |
| `search_local` | 语义搜索本地 PDF | query, top_k | 核心 |
| `get_paper_detail` | 获取论文详情（含引用量） | paper_id | 核心 |
| `translate_text` | 翻译指定文本 | text, target_lang | 核心 |

---

## 五、项目目录结构

```
scholar-mate/
│
├── README.md                     # 项目说明 + 安装步骤 + 截图
├── CLAUDE.md                     # 开发规范
├── pyproject.toml                # Poetry 依赖管理
├── .env.example                  # 环境变量模板
├── .gitignore
├── run.py                        # 桌面启动入口（服务 + 窗口）
│
├── app/
│   ├── __init__.py
│   ├── main.py                   # FastAPI 应用工厂 + 生命周期 + 路由注册
│   ├── config.py                 # pydantic-settings 配置管理
│   │
│   ├── desktop/                  # 桌面应用层（桌面版新增）
│   │   ├── __init__.py
│   │   ├── bootstrap.py          # 启动/停止 Uvicorn 服务线程 + 健康检查
│   │   └── window.py             # pywebview 窗口配置与关闭退出流程
│   │
│   ├── api/                      # 路由层（薄层：参数校验 + 调用 service）
│   │   ├── __init__.py
│   │   ├── search.py             # GET/POST /api/search
│   │   ├── agent.py              # POST /api/agent/chat (SSE)
│   │   ├── pdf.py                # POST /api/pdf/upload, /api/pdf/{id}/translate
│   │   └── papers.py             # GET/PUT/DELETE /api/papers
│   │
│   ├── models/                   # SQLAlchemy ORM 模型
│   │   ├── __init__.py
│   │   ├── paper.py
│   │   ├── search_history.py
│   │   └── uploaded_pdf.py
│   │
│   ├── schemas/                  # Pydantic 请求/响应 Schema
│   │   ├── __init__.py
│   │   ├── search.py
│   │   ├── agent.py
│   │   └── pdf.py
│   │
│   ├── services/                 # 业务逻辑层（核心，桌面化后不变）
│   │   ├── __init__.py
│   │   ├── arxiv_service.py
│   │   ├── semantic_scholar_service.py
│   │   ├── pdf_service.py
│   │   ├── translation_service.py
│   │   ├── embedding_service.py
│   │   └── vector_store_service.py
│   │
│   ├── agent/                    # Agent 引擎（核心差异化模块）
│   │   ├── __init__.py
│   │   ├── agent_loop.py         # ReAct 主循环
│   │   ├── tools.py              # 工具定义与注册
│   │   └── prompts.py            # System Prompt + 工具描述
│   │
│   ├── core/                     # 基础设施
│   │   ├── __init__.py
│   │   ├── database.py
│   │   ├── llm_client.py         # 多模型 LLM 工厂
│   │   └── exceptions.py
│   │
│   ├── templates/                # Jinja2 模板（桌面窗口内渲染）
│   │   ├── base.html
│   │   ├── index.html
│   │   ├── search.html
│   │   ├── agent.html
│   │   ├── translate.html
│   │   ├── papers.html
│   │   └── partials/
│   │       ├── paper_card.html
│   │       └── search_results.html
│   │
│   └── static/
│       ├── css/app.css
│       ├── js/agent_chat.js      # fetch 流式解析 SSE + 消息渲染
│       └── img/logo.svg
│
├── tests/
│   ├── conftest.py
│   ├── test_search.py
│   ├── test_agent.py
│   ├── test_pdf.py
│   ├── test_desktop.py           # 服务生命周期 / 端口分配（mock pywebview）
│   └── test_services/
│       ├── test_arxiv_service.py
│       └── test_vector_store.py
│
├── data/                         # 运行时数据（gitignore，打包后首次运行生成）
│   ├── uploads/
│   ├── chroma_db/
│   └── scholar_mate.db
│
├── scripts/
│   ├── init_db.py
│   ├── seed_demo.py              # 演示数据（含预生成向量，支持离线演示）
│   └── test_llm.py               # 阶段一验证 LLM 连接与工具调用
│
├── build/
│   ├── scholar_mate.spec         # PyInstaller 打包配置
│   └── build_exe.py              # 一键打包脚本
│
└── docs/
    ├── architecture.md
    ├── experiment/               # 实验报告与数据
    ├── decisions/                # 关键决策记录
    └── screenshots/              # 答辩素材
```

---

## 六、关键依赖包

```txt
# ===== 桌面应用 =====
pywebview>=5.0,<6.0         # 桌面壳（Windows 使用 WebView2）

# ===== 本地服务框架 =====
fastapi>=0.115,<1.0
uvicorn[standard]>=0.34,<1.0
python-multipart>=0.0.12
jinja2>=3.1,<4.0

# ===== 数据库 =====
sqlalchemy>=2.0,<3.0
aiosqlite>=0.20
chromadb>=0.5,<1.0

# ===== LLM SDK =====
openai>=1.0,<2.0            # DeepSeek + DashScope（OpenAI 兼容端点）
anthropic>=0.40,<1.0        # Claude（可选，默认不安装）

# ===== PDF 处理 =====
pymupdf>=1.24,<2.0
pdfplumber>=0.11,<1.0
pytesseract>=0.3,<1.0       # OCR（可选，默认不启用）

# ===== HTTP =====
httpx>=0.28,<1.0            # 异步 HTTP（arXiv/S2）
aiofiles>=24.0,<25.0

# ===== 工具 =====
pydantic>=2.0,<3.0
pydantic-settings>=2.0,<3.0
python-dotenv>=1.0,<2.0
tenacity>=9.0,<10.0         # API 重试
tiktoken>=0.8,<1.0          # Token 估算（近似）

# ===== 开发与打包 =====
pytest>=8.0,<9.0
pytest-asyncio>=0.24,<1.0
httpx                        # ASGI TestClient
ruff>=0.6,<1.0
pyinstaller>=6.0,<7.0        # 打包 exe
```

> 可选：本地 Embedding 备选方案（BGE-M3）时增加 `sentence-transformers` 或 `FlagEmbedding`，默认不安装、不打包。

---

## 七、.env 配置设计

```bash
# ===== 应用形态 =====
APP_HOST=127.0.0.1             # 仅本机监听
APP_PORT=8765                  # 0 表示自动分配空闲端口
APP_TITLE=ScholarMate
APP_SIZE=1280x800

# ===== LLM 主模型 =====
LLM_PROVIDER=deepseek        # deepseek | qwen | claude

# DeepSeek（2026-07-24 起使用 V4 模型名）
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_MODEL=deepseek-v4-flash   # 通用对话
# DEEPSEEK_MODEL=deepseek-v4-pro   # 复杂规划

# 通义千问（备用模型，OpenAI 兼容端点）
DASHSCOPE_API_KEY=sk-xxx
DASHSCOPE_MODEL=qwen-plus

# Anthropic Claude（可选）
ANTHROPIC_API_KEY=sk-ant-xxx
ANTHROPIC_MODEL=claude-sonnet-4-20250514

# ===== Embedding（DashScope，DeepSeek 无 Embedding 接口）=====
EMBEDDING_PROVIDER=dashscope   # dashscope | local
EMBEDDING_MODEL=text-embedding-v3
# EMBEDDING_MODEL=bge-m3        # 本地备选（需安装 FlagEmbedding）

# ===== 外部 API =====
SEMANTIC_SCHOLAR_API_KEY=      # 免费申请，提升限速至 1 RPS

# ===== 应用配置 =====
DATABASE_URL=sqlite+aiosqlite:///./data/scholar_mate.db
CHROMA_PERSIST_DIR=./data/chroma_db
PDF_UPLOAD_DIR=./data/uploads
MAX_UPLOAD_MB=50
```

---

## 八、分阶段开发计划

### 第一阶段：项目骨架 + 基础搜索（预计 3-5 天）

**目标**：项目能跑，能搜 arXiv 并展示结果。

- [x] Project Initialization（Poetry / Git / 目录结构）
- [x] FastAPI 入口 + 配置管理
- [x] SQLAlchemy 模型 + 数据库初始化
- [x] LLM 客户端工厂（DeepSeek V4 / Qwen，`scripts/test_llm.py` 验证）
- [x] arXiv API 集成（User-Agent、限速 ≥1 次/3s、条件重试）
- [x] Semantic Scholar 集成（引用量、双源回退）
- [x] 搜索结果 24h 缓存
- [x] `/api/search` 搜索端点（JSON / HTMX 双返回，失败降级 502）
- [x] Jinja2 首页 + 搜索结果页
- [ ] 验证：配置 API Key 后，浏览器输入关键词 → 返回论文列表（本机待验证）

### 第二阶段：PDF 处理 + 向量检索（预计 3-5 天）

**目标**：上传 PDF，提取内容，语义搜索。

- [x] PDF 上传接口 + 文件存储（类型/大小校验）
- [x] 文本提取（PyMuPDF）+ 分块（段落累积，≤800 字符）
- [x] DashScope Embedding 服务（待真实 Key 联调）
- [x] ChromaDB 存储与查询封装（含删除）
- [x] `/api/search?source=local` 语义检索
- [x] 论文库管理 API（列表 / 删除）
- [x] 用真实论文（arXiv LoRA 2106.09685）验证提取 → 分块 → 向量化 → 语义检索全链路
- [x] 文本规范化（NFKC 分解 PDF 连字，实测 ﬁne-tuning → fine-tuning）
- [x] Embedding 分批调用（DashScope 单次上限 10 条，实测批量超限后修复）
- [ ] 双栏论文提取效果：待用 3 篇双栏排版论文验证

### 第三阶段：Agent 智能检索（预计 3-5 天）

**目标**：Agent 理解自然语言，自主调用工具，综合输出。

- [ ] System Prompt 设计（角色、能力边界、输出格式）
- [ ] 工具定义（search_arxiv / search_semantic_scholar / search_local / get_paper_detail / translate_text）
- [ ] ReAct 主循环实现（约 200 行，含 JSON 解析与最大迭代限制）
- [ ] SSE 流式输出 + 前端 fetch 流式解析
- [ ] Agent 对话页面（聊天界面 + 打字机效果）
- [ ] 验证：「找 5 篇 2024 年 LoRA 微调论文并按引用量排序」→ 自动搜索 → 排序 → 输出

### 第四阶段：PDF 翻译 + 界面打磨（预计 3-5 天）

**目标**：完整功能路径，UI 可演示。

- [ ] LLM 分段翻译服务
- [ ] 翻译结果双语对照展示
- [ ] 论文详情页
- [ ] 搜索历史保存
- [ ] 全局错误处理 + Loading 状态
- [ ] UI 美化
- [ ] 验证：上传论文 PDF → 翻译 → 双语阅读

### 第五阶段：桌面集成与打包（预计 3-5 天）

**目标**：从「浏览器调试」切换为「桌面窗口交付」。

- [ ] `app/desktop/bootstrap.py`：Uvicorn 服务线程启动/停止 + 健康检查
- [ ] `app/desktop/window.py`：pywebview 窗口配置与关闭退出流程
- [ ] 端口分配与冲突规避（127.0.0.1 + 空闲端口）
- [ ] `scripts/test_llm.py` 验证在桌面形态下的调用链路
- [ ] PyInstaller spec + 打包脚本，产出 exe
- [ ] 数据目录、静态资源打包验证
- [ ] 新机验证：未安装 Python 的机器运行全流程
- [ ] 验证：双击 exe → 窗口启动 ≤ 5s → 完成全部核心演示

### 第六阶段：测试 + 答辩准备（预计 2-4 天）

**目标**：代码可靠，答辩从容。

- [ ] 核心 service 单元测试（外部 API mock）
- [ ] API 集成测试 + 桌面生命周期测试
- [ ] `seed_demo.py` 演示数据（含预生成向量，支持离线演示）
- [ ] README + 架构文档完善
- [ ] 系统截图 + 架构图
- [ ] 一键启动脚本 + 一键打包脚本
- [ ] 验证：新环境 clone → 配置 .env → `python run.py` → 完整演示

### 第七阶段：论文撰写与答辩（预计 6-10 周，与开发并行启动）

**目标**：论文达标，答辩通过。

- [ ] 三组实验数据收集（检索 / 翻译 / Agent）
- [ ] 论文初稿 → 导师评审 → 修改
- [ ] 查重与格式
- [ ] 答辩 PPT + 演示视频

**开发阶段总计**：16-28 天（每天 4-6 小时，含桌面集成与打包）；论文与答辩另计 6-10 周。

---

## 九、毕业设计论文切入点

| 章节 | 可写内容 | 技术亮点 |
|---|---|---|
| 背景 | 学术文献检索的痛点（信息过载、语言障碍） | 数据佐证 |
| 相关工作 | arXiv API、Semantic Scholar、LLM 翻译、RAG、Agent 模式、桌面应用形态 | 文献综述 |
| 系统设计 | 本地服务 + 桌面壳架构、ReAct Agent 循环、多模型切换、线程模型 | **核心章节** |
| 实现 | PDF 处理管线、向量检索、SSE 流式、桌面生命周期、打包 | 代码片段 |
| 实验 | 检索准确率、翻译质量、Agent 任务完成率 | 量化指标 |
| 总结 | 自建 Agent vs LangChain、桌面交付形态的取舍 | 技术反思 |

### 实验方法论（答辩前必须完成）

1. **检索准确率**：固定 20-30 个查询，对比 arXiv 关键词搜索 vs 向量检索 vs Agent 检索，人工判定相关性，用 MRR@k 或命中率打分；
2. **翻译质量**：抽取 20-30 段论文文本，与百度翻译基线对比，人工 5 分制评分，附带成本与延迟对比；
3. **Agent 完成率**：定义 15-20 个带成功标准的任务，统计完成率、平均迭代轮数、工具调用正确率、成本与延迟，并与「无工具的单次 LLM 直答」基线对比。

---

## 十、关键风险与对策

| 风险 | 概率 | 影响 | 对策 |
|---|---|---|---|
| LLM API 不稳定/欠费 | 低 | Agent 不可用 | DeepSeek 充值 ¥20 足够；配置 DashScope 备用；缓存与重试 |
| 模型名/接口变更 | 中 | 调用失败 | LLM 客户端工厂 + 配置化；阶段一先行验证 |
| arXiv/S2 限流或不可达 | 中 | 搜索无结果 | 限速器 + 24h 缓存 + 退避重试；arXiv 不可达时自动回退 Semantic Scholar（2026-08 实测 export.arxiv.org 在当前网络超时，S2 可达） |
| PDF 双栏/公式提取乱序 | 高 | 翻译质量差 | 阶段二前置小样验证；pdfplumber 布局分析 + LLM 清洗 |
| SSE 联调复杂 | 中 | 流式输出异常 | 先跑通最小流式 Demo；前端 fetch 流式解析 |
| PyInstaller 打包兼容问题 | 中 | exe 无法运行 | one-folder 模式 + 隐藏导入清单 + 新机验证清单 |
| 目标机缺少 WebView2 | 中 | 窗口无法打开 | 启动时检测并引导安装（Win11 内置） |
| 答辩现场网络故障 | 低 | 演示翻车 | 离线演示数据（预生成向量）+ 录屏 |
| 论文写作量/查重不达标 | 中 | 影响答辩资格 | 文档随开发同步产出；实验数据先行；提前 2 个月启动论文 |

---

## 附录：参考链接

- pywebview：[pywebview.flowrl.com](https://pywebview.flowrl.com)
- DeepSeek API：[platform.deepseek.com](https://platform.deepseek.com) / [api-docs.deepseek.com](https://api-docs.deepseek.com)
- arXiv API：[info.arxiv.org/help/api](https://info.arxiv.org/help/api)
- Semantic Scholar API：[api.semanticscholar.org](https://api.semanticscholar.org/api-docs)
- 阿里云百炼 DashScope：[dashscope.console.aliyun.com](https://dashscope.console.aliyun.com)
- FastAPI：[fastapi.tiangolo.com](https://fastapi.tiangolo.com)
- ChromaDB：[docs.trychroma.com](https://docs.trychroma.com)
- PyMuPDF：[pymupdf.readthedocs.io](https://pymupdf.readthedocs.io)
- PyInstaller：[pyinstaller.org](https://pyinstaller.org)
