# 智能出题系统（Exam Generator）

上传教材或讲义，自动构建知识库，按知识点智能出题、组卷、审核并导出试卷。全流程本地运行：出题模型走本地 Ollama，数据存本地 PostgreSQL，不依赖任何云服务。

## 功能特性

- **教材解析**：上传 PDF / Word（.docx），自动提取「章 → 节」知识点体系；支持「第X章 / 第X讲 / Chapter N / Lecture N」等标题格式，无章节结构的单篇讲义也能通过 AI 自动提取主题和核心知识点
- **知识库构建**：全文切片（Context-Aware，每个切片注入所属章节上下文），AI 打知识点标签，向量化入库（pgvector + nomic-embed-text，768 维）
- **智能出题**：单选、多选、简答三种题型 × 6 个出题维度（定义理解、对比辨析、应用场景、反例排除、原理机制、优缺点）× 易/中/难三档难度（prompt 引导 + AI 标注）
- **组卷策略**：按题型配置数量与分值；圈定知识点范围；设置易/中/难比例；可选自定义章节比例（权重 0 = 该章不出题），默认策略优先铺满所有选中章节
- **质量控制**（多层拦截）：LLM-as-a-Judge 质检 + 向量查重（阈值 0.88，只对比仍在使用的题）+ 程序化硬校验（空选项 / 选项正误标注污染 / 绝对化措辞干扰项 / 孪生选项 / 关键词回声秒杀题 / 答案-解析矛盾 / 简答题选择题化）+ 选项洗牌消除"正确答案总在A"的位置偏差
- **组卷审核**：边出题边审核，实时进度条（百分比、分题型进度、按本机实测速度动态估算的剩余时间）；章节分布 dashboard 一眼看出覆盖盲区；逐题编辑、换一题（可指定换到哪个章节的知识点）
- **断点续出**：出题中断（刷新 / 重启 / 断电）后，历史试卷页点「继续出题」按落库配置补齐缺口
- **题库沉淀**：成卷过的题目自动进入题库，可勾选快速组成新试卷，支持编辑和废弃
- **导出**：题目版 / 答案版 A4 PDF（数学公式渲染为真正的数学式）；在线考试系统通用格式（Excel 每题一行 / 结构化 JSON）
- **数学公式**：`$...$` 包裹的 LaTeX 公式在网页端（KaTeX）和 PDF（matplotlib mathtext → SVG）都渲染为数学式

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | React 19（Create React App）+ react-katex |
| 后端 | FastAPI + Uvicorn |
| 数据库 | PostgreSQL + pgvector（HNSW 向量索引） |
| 模型 | Ollama：qwen3:8b（出题/质检），nomic-embed-text（向量化） |
| 文档解析 | pdfplumber / python-docx |
| 导出 | WeasyPrint（PDF）/ openpyxl（Excel）/ matplotlib（公式渲染） |

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
ollama pull qwen3:8b          # 出题/质检模型（约 5.2GB）
ollama pull nomic-embed-text  # 向量模型（约 274MB）
```

**强烈建议开启 2 路并发**（实测约 2 倍出题提速）：

```bash
launchctl setenv OLLAMA_NUM_PARALLEL 2   # macOS；设置后需重启 Ollama 应用
```

注意此设置**重启电脑后会丢失**。要持久化，创建 `~/Library/LaunchAgents/com.user.ollama-env.plist`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.user.ollama-env</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/launchctl</string><string>setenv</string>
        <string>OLLAMA_NUM_PARALLEL</string><string>2</string>
    </array>
    <key>RunAtLoad</key><true/>
</dict>
</plist>
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
OLLAMA_MODEL=qwen3:8b
OLLAMA_EMBED_MODEL=nomic-embed-text
BACKEND_PORT=8000
```

> 换回 qwen2.5:7b 等旧模型只需改 `OLLAMA_MODEL`，代码无需改动（代码里的
> `think=False` 参数对不支持思考模式的模型会自动忽略；qwen3 系列必须保持
> 该参数，否则每次调用会多花 40 秒以上思考）。

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

首页点「进入系统」后共四个标签页：

1. **教材管理**：上传 PDF/Word 教材或讲义，后台自动完成解析 → 知识点提取 → 切片 → 向量化，状态变为「✓ 就绪」后即可出题（状态自动轮询刷新）；点击教材可查看知识点体系
2. **组卷**：选择教材 → 配置各题型数量与分值 → 设置难度比例（易/中/难相对权重）→ 可选勾选「自定义章节比例」逐章设权重 → 圈定知识点范围（不勾选 = 全部）→ 生成。出题是流式的：进度条实时显示百分比、分题型进度和预计剩余时间（按本机实际速度动态估算），已出的题目可立即开始审核
3. **审核**：页面顶部章节分布图可发现覆盖盲区；逐题检查，「编辑」修改内容，「换一题」重新生成（下拉可指定换到其他章节的知识点）；全部确认后点「全部通过，生成试卷」成卷
4. **导出**：成卷后可下载题目版 / 答案版 PDF，或导出 Excel / JSON 给在线考试系统导入
5. **题库管理**：成卷过的题目自动入题库；勾选题目、设分值快速组新卷（免出题等待）
6. **历史试卷**：查看所有试卷；「出题中」的可点「继续出题」断点续跑，「待审核」的可点「继续审核」回到审核页；随时重新下载 / 导出 / 删除

## 性能建议（实测经验）

- **内存是第一瓶颈**：16GB 内存的机器建议出题前关闭多余的浏览器标签页和大型应用。实测同一台机器：内存剩 100MB 时一道题可能要几分钟甚至卡死，腾出 5GB 后约 90 秒/题
- **开启 OLLAMA_NUM_PARALLEL=2**（见安装步骤 2），实测约 2 倍提速
- **定期清理题库**：某知识点下积累的题越多，新题查重命中率越高、重试越多、越慢
- **进度长时间不动**：大概率是 Ollama 挂死（内存高压下会发生）。重启 Ollama（退出菜单栏图标再打开），再到历史试卷页点「继续出题」。代码内置 300 秒调用超时自愈，彻底卡死的情况已大幅减少
- 参考速度（M 系列 Mac、16GB、内存充足、并发开启）：单选约 60–90 秒/题，多选/简答约 90–150 秒/题（多一次 CoT 分析调用）

## 已知限制

- **文件格式**：只支持 PDF 和 .docx，不支持 PPT/pptx、Markdown、纯文本；扫描版（图片型）PDF 无法提取文字
- **标题格式**：章节识别针对「第X章 / 第X讲 / Chapter N / Lecture N + X.X 小节」做规则匹配，其他格式走 AI 主题提取兜底，知识点粒度取决于模型发挥
- **出题质量**：本地 8B 模型的天花板——格式类坏题（空选项、秒杀题、答案解析矛盾、孪生选项等）有程序化拦截兜底，但**概念混淆、前沿技术事实错误、解析论证瑕疵**这类深层问题自动质检抓不稳，必须人工审核每道题
- **难度标注**：难度由 prompt 引导 + 模型自标注，遵从度有限，审核时可人工修正
- **单用户设计**：无登录鉴权，前端 API 地址硬编码 `localhost:8000`，CORS 只放行 `localhost:3000`，仅适合本机使用
- **数据库连接**：暂不支持密码认证（`DB_PASSWORD` 未接入配置），默认依赖本地 trust/peer 认证
- **任务进度存内存**：后台任务进度存在进程内存中，后端重启后进行中的任务中断——但出题配置已落库，历史试卷页「继续出题」可恢复
- **后端热重载**：开发模式（`reload=True`）下修改后端代码会自动重启进程并杀死进行中的出题线程，同样用「继续出题」恢复
- **同名文件覆盖**：上传同名文件会清空该文件名对应的旧数据（知识点、切片会被重建）
