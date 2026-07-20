# 智能出题系统（Exam Generator）

上传教材或讲义，自动构建知识库，按知识点智能出题、组卷、审核并导出 PDF 试卷。全流程本地运行：出题模型走本地 Ollama，数据存本地 PostgreSQL，不依赖任何云服务。

## 功能特性

- **教材解析**：上传 PDF / Word（.docx），自动提取「章 → 节」知识点体系；支持「第X章 / 第X讲 / Chapter N / Lecture N」等标题格式，无章节结构的单篇讲义也能通过 AI 自动提取主题和核心知识点
- **知识库构建**：全文切片（Context-Aware，每个切片注入所属章节上下文），AI 打知识点标签，向量化入库（pgvector + nomic-embed-text，768 维）
- **智能出题**：支持单选、多选、简答三种题型，从 6 个维度出题（定义理解、对比辨析、应用场景、反例排除、原理机制、优缺点），内置出题质量规则（题干自包含、干扰项对位构造、禁止组合型选项等）
- **质量控制**：AI 出题后自动质检（judge），向量相似度查重（阈值 0.92），重复题自动丢弃
- **组卷审核**：配置题型数量与分值、圈定知识点范围后一键组卷；边出题边审核，支持逐题编辑、一键换题
- **题库沉淀**：成卷过的题目自动进入题库，可在题库中勾选题目快速组成新试卷，支持编辑和废弃
- **试卷导出**：一键生成题目版（学生用）和答案版（教师用）两份 A4 PDF
- **历史试卷**：所有试卷可随时重新下载 PDF 或删除

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | React 19（Create React App） |
| 后端 | FastAPI + Uvicorn |
| 数据库 | PostgreSQL + pgvector（HNSW 向量索引） |
| 模型 | Ollama：qwen2.5:7b（出题/质检），nomic-embed-text（向量化） |
| 文档解析 | pdfplumber / python-docx |
| PDF 导出 | WeasyPrint |

## 安装步骤

### 1. PostgreSQL + pgvector

```bash
# macOS（Homebrew）
brew install postgresql@16 pgvector
brew services start postgresql@16

# 创建数据库并初始化表结构（schema 中会自动 CREATE EXTENSION vector）
createdb exam_generator
psql -d exam_generator -f database/schema_v2.sql
```

Linux 请参考 [pgvector 官方安装文档](https://github.com/pgvector/pgvector#installation)。

### 2. Ollama

```bash
# 安装 Ollama：https://ollama.com/download
ollama pull qwen2.5:7b        # 出题/质检模型（约 4.7GB）
ollama pull nomic-embed-text  # 向量模型（约 274MB）
```

### 3. 后端

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

WeasyPrint 依赖系统图形库，macOS 需要：`brew install pango`（Linux：`apt install libpango-1.0-0 libpangocairo-1.0-0`）。

配置（可选）：在项目根目录创建 `.env`，不创建则使用默认值：

```ini
DB_NAME=exam_generator
DB_USER=postgres
DB_HOST=localhost
DB_PORT=5432
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_EMBED_MODEL=nomic-embed-text
BACKEND_PORT=8000
```

启动：

```bash
python main.py    # 服务运行在 http://localhost:8000
```

### 4. 前端

```bash
cd frontend
npm install
npm start         # 打开 http://localhost:3000
```

## 使用流程

1. **教材管理**：上传 PDF/Word 教材或讲义，系统后台自动完成解析 → 知识点提取 → 切片 → 向量化，状态变为「✓ 就绪」后即可出题；点击教材可查看提取出的知识点体系
2. **组卷**：选择教材，配置各题型的数量和分值，圈定知识点范围（不勾选 = 全部），点击生成——出题是流式的，已出的题目立刻可以开始审核
3. **审核**：逐题检查，不满意的可以「编辑」修改或「换一题」重新生成；全部确认后点「全部通过，生成试卷」成卷，即可下载题目版 / 答案版 PDF
4. **题库管理**：成卷过的题目自动沉淀入题库；勾选题目、设定分值即可快速组成新试卷（免出题等待），也可以编辑或废弃题目
5. **历史试卷**：查看所有生成过的试卷，随时重新下载 PDF 或删除

## 已知限制

- **文件格式**：只支持 PDF 和 .docx，不支持 PPT/pptx、Markdown、纯文本；扫描版（图片型）PDF 无法提取文字
- **标题格式**：章节识别针对「第X章 / 第X讲 / Chapter N / Lecture N + X.X 小节」的格式做规则匹配，其他格式的文档会走 AI 主题提取兜底，知识点粒度取决于模型发挥
- **出题质量**：依赖本地模型（默认 qwen2.5:7b），复杂推理题、计算题质量有限；AI 质检和查重能过滤大部分坏题，但仍建议人工审核每道题
- **出题速度**：本地推理，一道题约 30–60 秒（取决于硬件），组卷页有预估时间提示
- **单用户设计**：无登录鉴权，前端 API 地址硬编码 `localhost:8000`，CORS 只放行 `localhost:3000`，仅适合本机使用，不能直接部署公网
- **数据库连接**：暂不支持密码认证（`DB_PASSWORD` 未接入配置），默认依赖本地 trust/peer 认证
- **任务进度存内存**：后台任务（知识库构建、出题）进度存在进程内存中，后端重启后进行中的任务丢失进度，需重新发起
- **同名文件覆盖**：上传同名文件会清空该文件名对应的旧数据（知识点、切片会被重建）
