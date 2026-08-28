# AgentForge

Enterprise Agent Workflow Platform

中文：企业级 Agent 工作流平台。

> AgentForge 使用成熟的 FastAPI + Next.js 全栈工程能力作为 Web Engineering Foundation，并在此基础上逐步建设自研的 Agent Platform Core。

---

## 项目定位

AgentForge 的目标不是简单封装一个聊天机器人，而是构建面向企业场景的 Agent 工作流平台。

当前 v0.1 主要建设稳定的工程基础，包括：

- FastAPI Backend
- Next.js Frontend
- PostgreSQL
- SQLAlchemy
- Alembic
- JWT Authentication
- Redis
- Celery
- Docker
- Test / CI 基础能力

后续版本将在这一基础上逐步实现 AgentForge 自研的平台核心：

```text
Workflow Engine
Agent Runtime
Tool Registry
MCP Integration
Checkpoint
Pause / Resume
Human In The Loop
Run / Step / Trace
Observability
Workspace / RBAC
```

LangGraph 当前属于模板继承能力及未来 Runtime Adapter 的参考实现。

**LangGraph 不是 AgentForge 的 Workflow Engine。**

---

## 技术栈

| 模块 | 技术 |
|---|---|
| Backend | FastAPI + Pydantic v2 |
| Database | PostgreSQL |
| ORM | SQLAlchemy |
| Migration | Alembic |
| Authentication | JWT + Refresh Token + API Key |
| Cache / Broker | Redis |
| Background Tasks | Celery |
| Frontend | Next.js 15 + React 19 |
| Language | TypeScript |
| Styling | Tailwind CSS |
| AI Framework Reference | LangGraph |
| Container | Docker / Docker Compose |
| Python Package Manager | uv |
| Frontend Package Manager | Bun |

---

## 开发环境要求

| 工具 | 建议版本 |
|---|---|
| Docker | Desktop / Engine 24+ |
| Python | 3.12 |
| uv | 最新稳定版 |
| Bun | 1.x |
| Node.js | 22.x |
| Git | 2.x |
| GNU Make | 4.x |

Windows 环境下，由于 Makefile 中部分命令依赖 Bash，推荐使用 Git Bash 或 WSL2。

如果需要在 PowerShell 中执行 Makefile，可以使用：

```powershell
& "D:\Tool\Git\Git-2.41.0.3-64\Git\bin\bash.exe" -lc "cd /d/agent_project/agentforge && make <target>"
```

例如：

```powershell
& "D:\Tool\Git\Git-2.41.0.3-64\Git\bin\bash.exe" -lc "cd /d/agent_project/agentforge && make dev"
```

---

## 本地开发运行方式

AgentForge 日常开发采用混合运行模式：

```text
Docker
├── FastAPI Backend
├── PostgreSQL
├── Redis
├── Celery Worker
├── Celery Beat
└── Flower

Host
└── Next.js Frontend
```

Backend Stack 由根目录：

```text
docker-compose.yml
```

统一管理。

Backend application source 通过 bind mount 挂载到 Backend 和 Celery Container 中。

Uvicorn 开启 reload，因此普通：

```text
backend/app/*
```

源码修改后通常不需要重新构建 Docker Image。

Frontend 日常开发直接在 Host 上运行：

```bash
bun run dev
```

这样可以保证浏览器始终运行当前 Working Tree 中最新的 Frontend 源码。

`docker-compose.frontend.yml` 仅用于 Frontend Container Verification，不作为日常 Frontend 开发方式。

---

## 为什么 Frontend 日常开发不运行在 Docker 中？

Frontend Dockerfile 在 Build 阶段会复制源码：

```text
Frontend Source
        ↓
docker build
        ↓
Docker Image
```

假设：

```text
上午构建 Frontend Image
        ↓
下午修改 frontend/src
        ↓
仍然运行上午的 Container
```

那么浏览器看到的仍可能是旧代码。

这会造成：

```text
Local Source
        ≠
Running Frontend
```

为了避免 Stale Frontend Image，日常 Frontend 开发统一使用：

```bash
bun run dev
```

---

## 首次启动

在项目根目录执行：

```bash
make bootstrap
```

`make bootstrap` 会完成：

1. 构建 Backend Docker Image；
2. 启动 Backend Stack；
3. 启动 PostgreSQL；
4. 启动 Redis；
5. 启动 Celery Worker；
6. 启动 Celery Beat；
7. 启动 Flower；
8. 等待 PostgreSQL Ready；
9. 执行 Alembic Migration；
10. 创建默认开发管理员（如果不存在）。

然后打开第二个终端启动 Frontend：

```bash
make frontend-dev
```

或者：

```bash
cd frontend
bun run dev
```

---

## 日常启动

启动 Backend Stack：

```bash
make dev
```

启动 Frontend：

```bash
make frontend-dev
```

或者：

```bash
cd frontend
bun run dev
```

---

## 本地服务地址

| 服务 | 地址 |
|---|---|
| Frontend | <http://localhost:3000> |
| Backend API | <http://localhost:8000> |
| Swagger Docs | <http://localhost:8000/docs> |
| Flower | <http://localhost:5555> |
| PostgreSQL | `localhost:5432` |
| Redis | `localhost:6379` |

---

## 常用开发命令

```bash
make dev
make frontend-dev
make dev-down
make dev-logs
make dev-restart-workers
make dev-rebuild
```

### `make dev`

负责：

```text
启动 Docker Backend Stack
        ↓
等待 PostgreSQL Ready
        ↓
执行 Alembic Upgrade
```

普通：

```text
backend/app/*
```

源码已经通过 bind mount 挂载到 Container，因此通常不需要重新 Build Image。

---

### `make frontend-dev`

执行：

```bash
cd frontend && bun run dev
```

这是 AgentForge 日常 Frontend 开发的标准方式。

---

### `make dev-restart-workers`

Celery 不会像 Uvicorn 一样自动重新加载 Python Module。

因此修改：

```text
Celery Task
Worker Logic
Background Task
```

以后执行：

```bash
make dev-restart-workers
```

它会重启：

```text
celery_worker
celery_beat
flower
```

---

### `make dev-rebuild`

如果修改以下内容：

```text
backend/pyproject.toml
backend/uv.lock
backend/Dockerfile
Python Dependencies
System Dependencies
```

执行：

```bash
make dev-rebuild
```

这类内容属于 Docker Image Build Layer，不能单靠 bind mount 更新。

---

## Frontend Container 验收

Frontend Docker 仅用于验证生产风格 Container 是否可以正常构建和运行。

首先停止：

```bash
bun run dev
```

确保：

```text
localhost:3000
```

没有被本地 Next.js 占用。

然后执行：

```bash
make docker-frontend
```

该命令会：

```text
Current Frontend Source
        ↓
Fresh Docker Build
        ↓
Force Recreate Container
        ↓
localhost:3000
```

验收完成后：

```bash
make docker-frontend-down
```

不要长期保留 Frontend Verification Container。

---

## 为什么删除 `docker-compose.dev.yml`？

以前项目同时存在：

```text
docker-compose.yml
docker-compose.dev.yml
```

两份 Backend Development Compose。

两份长期独立维护容易产生：

```text
Configuration Drift
```

例如：

```text
docker-compose.yml
已经修改 WebSocket 配置

docker-compose.dev.yml
仍然保留旧配置
```

最终可能导致：

```text
不同启动命令
        ↓
不同运行环境
```

因此 AgentForge v0.1 开始统一：

```text
docker-compose.yml
        ↓
Single Backend Development Compose
```

不再维护单独的：

```text
docker-compose.dev.yml
```

---

## 当前开发运行环境

| 服务 | 开发运行方式 | 端口 |
|---|---|---:|
| Next.js Frontend | Host / Bun | 3000 |
| FastAPI Backend | Docker | 8000 |
| PostgreSQL | Docker | 5432 |
| Redis | Docker | 6379 |
| Flower | Docker | 5555 |
| Celery Worker | Docker | - |
| Celery Beat | Docker | - |

---

## 停止开发环境

停止 Backend Docker Stack：

```bash
make dev-down
```

该操作不会删除 Named Volume。

因此 PostgreSQL 数据仍然保留。

---

## 清空本地 Docker 数据

只有明确需要重新初始化本地环境时才执行：

```bash
make docker-clean
```

这个命令会删除：

```text
PostgreSQL Volume
Redis Volume
Uploaded File Volume
Containers
Networks
```

也就是说：

**本地数据库数据会被删除。**

日常开发不要因为普通 Container 错误就执行：

```bash
docker compose down -v
```

---

## Backend 本机调试

如果需要 IDE Debug 或 Breakpoint，可以让 Backend 在 Host 上运行。

首先停止 Docker Backend：

```bash
make dev-down
```

只启动 PostgreSQL 和 Redis：

```bash
docker compose up -d db redis
```

安装 Backend Dependency：

```bash
make install
```

执行 Migration：

```bash
make db-upgrade
```

运行 Backend：

```bash
make run
```

注意不要同时运行：

```text
Docker FastAPI
+
Local FastAPI
```

否则都会尝试占用：

```text
8000
```

端口。

---

## Backend 架构分层

主要调用链：

```text
API Route
    ↓
Service
    ↓
Repository
    ↓
SQLAlchemy Model
    ↓
PostgreSQL
```

### API Route

负责：

- HTTP Request / Response
- Dependency Injection
- 参数接收
- 调用 Service

不负责复杂业务逻辑。

### Service

负责：

- Business Logic
- Business Rule
- 权限判断
- 调用多个 Repository
- Domain Exception

### Repository

负责：

- SQLAlchemy Query
- CRUD
- Database Access

### Model

负责：

- ORM Mapping
- Table Definition
- Relationship

---

## 数据库 Migration

查看当前 Revision：

```bash
make db-current
```

升级：

```bash
make db-upgrade
```

查看历史：

```bash
make db-history
```

创建 Migration：

```bash
make db-migrate
```

回退：

```bash
make db-downgrade
```

原则：

```text
Historical Migration
        ↓
Preserve

New Schema Change
        ↓
New Migration
```

不要为了修改当前 Schema 去直接改已经执行过的历史 Migration。

---

## Backend 测试与代码质量

运行测试：

```bash
make test
```

Coverage：

```bash
make test-cov
```

Lint / Type Check：

```bash
make lint
```

格式化：

```bash
make format
```

---

## Frontend 开发验证

进入：

```bash
cd frontend
```

推荐依次运行：

```bash
bun run lint
bun run type-check
bun run test:run
bun run build
```

修改重要功能后，还需要进行 Browser Manual Test。

例如 Authentication 修改至少验证：

```text
Successful Login
Failed Login
Logout
Refresh Token
```

---

## Frontend HTTP 请求链路

普通 HTTP 请求：

```text
Browser
    ↓
Next.js API Route
    ↓
FastAPI
    ↓
Service
    ↓
Repository
    ↓
PostgreSQL
```

例如 Login：

```text
Browser

POST /api/auth/login
        ↓
Next.js
src/app/api/auth/login/route.ts
        ↓
FastAPI
POST /api/v1/auth/login
```

这样 Authentication Cookie 和 Server-side Proxy Logic 可以统一由 Next.js Server 管理。

---

## WebSocket 请求链路

Chat WebSocket 与普通 HTTP 不同：

```text
Browser
    ↓
FastAPI WebSocket
```

因此：

```text
NEXT_PUBLIC_WS_URL
```

必须是 Browser 可以直接访问的地址。

本地通常为：

```text
ws://localhost:8000
```

---

## 项目目录结构

```text
agentforge/
│
├── backend/
│   ├── app/
│   │   ├── agents/
│   │   ├── api/
│   │   ├── clients/
│   │   ├── commands/
│   │   ├── core/
│   │   ├── db/
│   │   ├── repositories/
│   │   ├── schemas/
│   │   ├── services/
│   │   └── worker/
│   │
│   ├── alembic/
│   ├── tests/
│   ├── pyproject.toml
│   └── Dockerfile
│
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   ├── components/
│   │   ├── hooks/
│   │   ├── lib/
│   │   ├── stores/
│   │   └── types/
│   │
│   ├── messages/
│   ├── package.json
│   └── Dockerfile
│
├── docs/
├── docker-compose.yml
├── docker-compose.frontend.yml
├── docker-compose.prod.yml
├── Makefile
└── README.md
```

---

## Backend 环境变量

Backend：

```text
backend/.env
```

示例：

```text
backend/.env.example
```

典型开发配置：

```text
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=agentforge
```

其他主要配置包括：

```text
REDIS_HOST
REDIS_PORT
SECRET_KEY
OPENAI_API_KEY
```

生产环境禁止将真实 Secret 提交到 Git。

---

## Frontend 环境变量

本地 Frontend：

```text
frontend/.env.local
```

常用：

```text
BACKEND_URL
NEXT_PUBLIC_API_URL
NEXT_PUBLIC_WS_URL
NEXT_PUBLIC_SITE_URL
NEXT_PUBLIC_MAX_UPLOAD_SIZE_MB
```

其中：

```text
NEXT_PUBLIC_*
```

属于 Build-time Browser Environment。

修改以后需要重新执行 Frontend Build。

---

## 生产部署

Production Compose：

```text
docker-compose.prod.yml
```

启动：

```bash
make prod
```

日志：

```bash
make prod-logs
```

停止：

```bash
make prod-down
```

生产环境还需要正确配置：

```text
PostgreSQL
Redis
JWT Secret
LLM API Key
Domain
HTTPS
Nginx
CORS
```

---

## AgentForge 架构边界

AgentForge 使用成熟的 Full-Stack 工程能力作为 Web Engineering Foundation。

继承和保留的基础能力包括：

```text
Authentication
Database Integration
Redis
Celery
Docker
CI
Repository / Service Layer
Frontend Application Shell
```

AgentForge 后续主要自研：

```text
Workflow Engine
Agent Runtime
Tool / MCP Platform
Checkpoint / HITL
Run / Step / Trace
Observability
Workspace / RBAC
```

可以理解为：

```text
Full-Stack Foundation
解决：
“How to build a modern Web system”

AgentForge
解决：
“How to define, execute, pause, resume, observe,
audit and manage enterprise Agent workflows”
```

---

## Attribution

AgentForge 的 Web Engineering Foundation 最初由：

[Full-Stack AI Agent Template](https://github.com/vstorm-co/full-stack-ai-agent-template)

生成。

Template version:

```text
v0.2.19
```

AgentForge 在此基础上持续进行功能裁剪、架构重构以及 Agent Platform Core 的独立设计与实现。