# 司法竞争性证据 Legal RAG

> 面向司法辅助场景，通过动态争议焦点识别、竞争性证据检索与可追溯证据核查，减少单向查询造成的证据暴露不足。

## 核心流程

```
案件输入
→ 动态争点识别（Method B）
→ Dynamic Query Planning
→ Bounded Legal Corpus（CV-0005 真实语料 / 内置示例语料）
→ Competitive Retrieval（neutral / support / counter）
→ Runtime Evidence Audit（Authority + Applicability）
→ Grounded Synthesis（G1_RUNTIME_V1）
→ HTTP API
→ Evidence Workspace（React 前端）
```

**关键边界：**

- `support route` / `counter route` 是**检索意图**，不是证据关系。支持/削弱归类来自实时 G1 的内容判断与证据引用。
- Authority / Applicability Audit 是**辅助筛查信号**，不是终局法律判断。
- 数据库宿主（如裁判文书网、商业数据库）**不等于**权威发布机构。
- `unknown` / `unavailable` 永远保留为未知/不可用，不会被提升为 PASS 或 failed。

## Quick Start（本地真实运行）

### 环境

- Python 3.11+
- Node 18+

### 1. 安装后端依赖

```powershell
pip install -r requirements.txt
```

### 2. 配置 LLM provider（必需）

本系统的争点识别与综合分析通过 OpenAI-compatible API 调用模型。默认使用 OpenRouter。

```powershell
$env:OPENROUTER_API_KEY="your-key"
```

将密钥放在工作目录下的 `openrouter key.txt`（该文件已在 .gitignore 中），或通过环境变量 `OPENROUTER_API_KEY` 提供。**不要把密钥提交到仓库。**

可选环境变量：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `OPENROUTER_API_KEY` | — | OpenRouter API key（或用 key 文件） |
| `LEGAL_RAG_MODEL` | `deepseek/deepseek-v4.1-flash` | 运行时模型 |
| `LEGAL_RAG_BASE_URL` | `https://openrouter.ai/api/v1` | OpenAI-compatible endpoint |
| `LEGAL_RAG_CORPUS_PATH` | `corpus_expansion/CV-0005` | 真实语料路径；示例运行设为 `data/sample_corpus` |

### 3. 启动后端 API

完整语料（需要本地 CV-0005）：

```powershell
python -m src.legal_rag.api_server --host 127.0.0.1 --port 8000
```

使用内置示例语料（开箱即测，无需外部数据）：

```powershell
$env:LEGAL_RAG_CORPUS_PATH="data/sample_corpus"
python -m src.legal_rag.api_server --host 127.0.0.1 --port 8000
```

### 4. 启动前端

```powershell
cd frontend/justice-evidence-rag
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

### 5. 验证

```powershell
# 健康检查
Invoke-RestMethod http://127.0.0.1:8000/api/health

# 一次真实案件分析（PowerShell）
$body = @{ mode = "case-analysis"; facts = "某高校依据校规对学生作出退学处理，未听取申辩，随后拒发毕业证。" } | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/analysis -Method Post -ContentType "application/json" -Body $body
```

### 6. 测试

```powershell
python -m unittest discover -s tests -v
```

## 目录结构

```
justice-competitive-rag/
├── src/legal_rag/           # 后端运行时（issue spotting / query planning / retrieval / audit / synthesis / api）
├── frontend/justice-evidence-rag/   # React + TypeScript 前端（真实 HttpAnalysisService）
├── prompts/                 # 版本化 prompt
├── data/sample_corpus/      # 开箱即测的示例语料（真实全文，可用于离线检索/审计）
├── tests/                   # 单元测试
├── docs/                    # ARCHITECTURE / METHOD / RUNTIME_AUDIT / LIMITATIONS
└── examples/                # 示例输入
```

完整研究语料（CV-0005）不含在本仓库中；通过 `LEGAL_RAG_CORPUS_PATH` 指向本地 corpus 即可接入。

## 文档

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/METHOD.md](docs/METHOD.md)
- [docs/RUNTIME_AUDIT.md](docs/RUNTIME_AUDIT.md)
- [docs/LIMITATIONS.md](docs/LIMITATIONS.md)

## 与静态展示页 repo 的边界

本仓库是**独立正式工程**，不与 `justice-evidence-rag-demo` 等静态展示页共享 Git 历史、remote 或 Pages 配置。前端视觉模板从展示版复制而来，但正式工程默认连接真实 HTTP API，不使用 mock 结果。
