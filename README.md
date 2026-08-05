# ScholarMate（学术伴侣）

面向学术论文的智能检索、翻译与分类 Agent **桌面应用**（Windows，毕业设计）。

形态：pywebview 桌面窗口 + FastAPI 本地服务（仅监听 127.0.0.1）+ SQLite/ChromaDB + 多 LLM 可切换。

## 环境要求

- Windows 10/11（Windows 11 内置 WebView2 运行时）
- Python 3.11+

## 快速开始

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
copy .env.example .env        # 填入 DeepSeek / DashScope API Key；S2 Key 可选，无 Key 时自动用 OpenAlex
python run.py                 # 桌面窗口（P5 前可用浏览器访问 http://127.0.0.1:8765）
```

无窗口模式（调试 / CI）：

```bash
SM_HEADLESS=1 python run.py
```

## 按阶段安装可选依赖

```bash
pip install -e ".[llm]"       # OpenAI / Anthropic SDK（P1 接入 LLM 时）
pip install -e ".[rag]"       # ChromaDB（P2 向量检索）
pip install -e ".[pdf]"       # PyMuPDF / pdfplumber（P2 PDF 处理）
```

## 测试与检查

```bash
python -m pytest
ruff check .
```

## 项目结构

```
app/
  desktop/    # 桌面壳（服务生命周期 + pywebview 窗口）
  api/        # 路由层
  services/   # 业务逻辑（arXiv / S2 / OpenAlex / PDF / 向量 / 翻译）
  agent/      # ReAct Agent 引擎
  core/       # 数据库 / LLM 工厂 / 异常
  models/     # SQLAlchemy ORM
  schemas/    # Pydantic 请求/响应
  templates/  # Jinja2 页面
  static/     # CSS / JS / 图片
    css/      # 设计系统（学术手稿风）
    js/       # 页面交互（对话 / 翻译 / 论文库）
    vendor/   # 本地化 htmx / Alpine（离线可打包）
tests/        # pytest 测试
scripts/      # 初始化 / 演示数据 / LLM 连通性
build/        # PyInstaller 打包配置
docs/         # 设计方案 / 计划书 / 答辩素材
```

## 开发路线

| 阶段 | 内容 | 状态 |
|---|---|---|
| P1 | 骨架 + 多源搜索（arXiv + S2 回退 + OpenAlex 兜底 + 缓存） | 完成（OpenAlex 实机验证通过） |
| P2 | PDF 提取 + 向量检索 + 本地搜索 | 完成（真实论文验证通过） |
| P3 | ReAct Agent + SSE 流式对话 | 完成（本地检索场景实测通过） |
| P4 | 翻译 + 双语对照（SSE 流式逐段翻译） | 完成（真实论文端到端验证通过） |
| P5 | 桌面集成 + PyInstaller 打包 | 计划 |
| P6 | 测试 + 文档完善 | 计划 |

详细设计见 `docs/ScholarMate-设计方案.md`，项目计划见 `Plan.md`。

## 测试与质量

```bash
ruff check .                     # 代码风格（E/F/I/UP/B/SIM）
pytest -q                        # 单元测试（88 个）
pytest --cov=app --cov-report=term-missing   # 覆盖率（≥90%）
pip-audit                        # 依赖漏洞审计（CI 中执行）
```

安全基线：服务仅绑定 `127.0.0.1`；上传文件做后缀 + `%PDF` 魔数双重校验；
删除接口校验文件路径必须位于上传目录内；外部 API 均通过参数化 HTTP 请求（无 SSRF 注入面）；
Jinja2/Alpine 默认转义防止 XSS；密钥仅存于 `.env`（已 gitignore）。
