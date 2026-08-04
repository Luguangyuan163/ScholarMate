# ScholarMate 开发规范

## 常用命令

- 测试：`python -m pytest`
- 静态检查：`ruff check .`
- 启动（桌面）：`python run.py`
- 启动（无窗口）：`SM_HEADLESS=1 python run.py`
- 初始化数据库：`python scripts/init_db.py`

## 编码约束

- 函数体 ≤ 60 行（编排函数 ≤ 100 行），超过则提取辅助函数；
- 依赖注入优先：服务通过构造函数接收依赖，不在方法内部直接创建具体实现；
- 内部稳定结构用 `@dataclass`，API 边界用 pydantic `BaseModel`，动态结构用 dict；
- 禁止 barrel export（不在 `__init__.py` 里聚合导出），直接 import 源模块；
- 同步库（PyMuPDF / pdfplumber / ChromaDB）必须经 `anyio.to_thread` 执行，禁止阻塞事件循环；
- 提交信息遵循 Conventional Commits：`feat` / `fix` / `docs` / `test` / `refactor`。

## 阶段路线

- P1 骨架 + arXiv 搜索（当前）
- P2 PDF 提取 + 向量检索
- P3 ReAct Agent + SSE 流式
- P4 翻译 + 界面打磨
- P5 桌面集成 + PyInstaller 打包
- P6 测试 + 文档完善
