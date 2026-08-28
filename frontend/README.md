# AgentForge Frontend

AgentForge Frontend 基于：

```text
Next.js 15
React 19
TypeScript
Tailwind CSS
```

主要负责 AgentForge 的 Web UI、Authentication UI、Dashboard、Chat UI、Settings、Admin UI、Next.js API Proxy 和 WebSocket Client。

---

## 开发环境要求

需要安装：

```text
Bun
```

同时需要保证 AgentForge Backend 已经运行：

```text
http://localhost:8000
```

从项目根目录启动 Backend：

```bash
make dev
```

---

## 日常开发

Frontend 日常开发统一使用：

```bash
bun run dev
```

首次进入 Frontend：

```bash
cd frontend
bun install
```

启动：

```bash
bun run dev
```

或者在项目根目录运行：

```bash
make frontend-dev
```

Frontend 地址：

```text
http://localhost:3000
```

这是 AgentForge Frontend 的标准开发方式。

---

## 为什么日常开发不使用 Frontend Docker？

Frontend Dockerfile 在 Build 阶段会将源码复制进 Docker Image。

流程：

```text
Frontend Source
        ↓
docker build
        ↓
Next.js Production Build
        ↓
Docker Image
```

如果已经构建过一次 Image，之后继续修改：

```text
frontend/src/*
```

旧 Image 不会自动获得这些修改。

因此可能出现：

```text
Working Tree
        ≠
Running Frontend Container
```

这就是 Stale Frontend Image。

为了避免这种问题，日常开发统一：

```text
Current Source
        ↓
bun run dev
        ↓
Next.js Hot Reload
        ↓
Browser
```

---

## Frontend Docker 的用途

Frontend Docker 只用于：

```text
Container Verification
```

也就是验证：

```text
Dockerfile
        ↓
Production Build
        ↓
Standalone Runtime
        ↓
Container
```

是否可以正常工作。

它不是普通 Frontend 开发环境。

---

## Frontend Docker 验收

首先停止：

```bash
bun run dev
```

确保：

```text
localhost:3000
```

端口空闲。

然后从项目根目录执行：

```bash
make docker-frontend
```

该命令会：

```text
Current Source
        ↓
Fresh Docker Build
        ↓
Force Recreate Container
        ↓
localhost:3000
```

验收完成以后：

```bash
make docker-frontend-down
```

不要让旧 Frontend Verification Container 长期运行。

---

## 环境变量

本地 Frontend 使用：

```text
frontend/.env.local
```

主要变量：

| 环境变量 | 使用位置 | 作用 |
|---|---|---|
| `BACKEND_URL` | Next.js Server | FastAPI Backend 地址 |
| `COOKIE_SECURE` | Next.js Server | 控制 Authentication Cookie 的 `Secure` |
| `NEXT_PUBLIC_WS_URL` | Browser | Chat WebSocket Backend 地址 |
| `NEXT_PUBLIC_API_URL` | Browser | Backend Public URL |
| `NEXT_PUBLIC_SITE_URL` | Browser | Frontend Canonical URL |
| `NEXT_PUBLIC_MAX_UPLOAD_SIZE_MB` | Browser / Build | Frontend Upload Limit |
| `NEXT_PUBLIC_RAG_ENABLED` | Browser / Build | RAG UI Feature Flag |

---

## `NEXT_PUBLIC_*` 为什么特殊？

Next.js 会在：

```bash
bun run build
```

阶段将：

```text
NEXT_PUBLIC_*
```

写入 Browser Bundle。

例如 Build 时：

```text
NEXT_PUBLIC_WS_URL=ws://localhost:8000
```

即使 Build 完成后再修改环境变量，已经生成的旧 Bundle 仍然使用原来的值。

因此修改：

```text
NEXT_PUBLIC_*
```

之后必须重新 Build。

对于 Frontend Docker，就是：

```text
Change Environment
        ↓
Rebuild Image
        ↓
Recreate Container
```

而不是简单 Restart Container。

---

## Browser URL 与 Docker Service URL

例如：

```text
NEXT_PUBLIC_WS_URL
```

由 Browser 使用。

因此不能写：

```text
ws://app:8000
```

因为：

```text
app
```

只是 Docker Network 内部 Service Name，Browser 无法解析。

本地开发通常使用：

```text
ws://localhost:8000
```

而：

```text
BACKEND_URL
```

由 Next.js Server 使用。

如果 Next.js 运行在 Docker 中，可以使用：

```text
http://host.docker.internal:8000
```

因为这是 Server-side Runtime。

---

## HTTP API 请求架构

普通 HTTP API 使用：

```text
Browser
    ↓
Next.js API Route
    ↓
FastAPI Backend
```

Next.js API Proxy 位于：

```text
src/app/api/*
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

这样可以统一处理：

```text
Authentication Cookie
Backend URL
Server-side Proxy Logic
Error Normalization
```

---

## WebSocket 请求架构

Chat WebSocket 不经过普通 Next.js API Route。

而是：

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

本地：

```text
ws://localhost:8000
```

---

## 常用命令

安装依赖：

```bash
bun install
```

开发：

```bash
bun run dev
```

Lint：

```bash
bun run lint
```

Lint 自动修复：

```bash
bun run lint:fix
```

TypeScript 检查：

```bash
bun run type-check
```

Unit Test：

```bash
bun run test:run
```

Production Build：

```bash
bun run build
```

运行 Production Build：

```bash
bun run start
```

E2E：

```bash
bun run test:e2e
```

---

## Frontend 修改后的推荐验证顺序

推荐：

```text
Lint
  ↓
Type Check
  ↓
Unit Test
  ↓
Production Build
  ↓
Browser Manual Test
```

对应：

```bash
bun run lint
bun run type-check
bun run test:run
bun run build
```

修改 Authentication 之类关键功能时，还应该实际测试：

```text
Successful Login
Failed Login
Logout
Refresh Token
```

---

## 目录结构

```text
frontend/
│
├── src/
│   ├── app/
│   │   ├── [locale]/
│   │   └── api/
│   │
│   ├── components/
│   ├── hooks/
│   ├── lib/
│   ├── stores/
│   ├── types/
│   ├── i18n.ts
│   └── middleware.ts
│
├── messages/
├── public/
├── package.json
├── bun.lock
├── next.config.ts
└── Dockerfile
```

---

## `src/app`

Next.js App Router。

主要负责：

```text
Page Route
Layout
Server Route
Next.js API Proxy
```

---

## `src/components`

React UI Components。

例如：

```text
auth
chat
dashboard
layout
settings
ui
```

---

## `src/hooks`

React Hooks。

例如：

```text
useAuth
useChat
useConversations
```

---

## `src/lib`

Frontend 共享基础能力。

例如：

```text
api-client
server-api
auth-cookies
error-message
utils
```

---

## `src/stores`

Zustand Store。

主要管理：

```text
Authentication State
Chat State
Conversation State
```

---

## `src/types`

Frontend TypeScript Type Definitions。

---

## API 错误处理

Frontend 最终交给 React UI 的 Error Message 必须是：

```text
string
```

FastAPI 可能返回：

```json
{
  "detail": [
    {
      "msg": "Invalid email address"
    }
  ]
}
```

AgentForge Backend Domain Exception 也可能返回：

```json
{
  "error": {
    "code": "AUTHENTICATION_ERROR",
    "message": "Invalid email or password"
  }
}
```

Frontend 应该统一转换成：

```text
Invalid email address
```

或者：

```text
Invalid email or password
```

不能把：

```text
object
array
```

直接送进 React JSX。

否则可能触发：

```text
Objects are not valid as a React child
```

---

## 国际化

AgentForge Frontend 当前使用：

```text
next-intl
```

语言文件：

```text
messages/
```

当前主要包括：

```text
en.json
pl.json
```

新增 Locale 时需要同步更新：

```text
i18n configuration
message catalog
route behavior
```

---

## Production Build

执行：

```bash
bun run build
```

运行：

```bash
bun run start
```

Dockerfile 同样会执行 Next.js Production Build，并产生 Standalone Runtime Image。

---

## Vercel 部署

执行：

```bash
npx vercel --prod
```

至少需要配置：

```text
BACKEND_URL=https://api.your-domain.com
NEXT_PUBLIC_API_URL=https://api.your-domain.com
NEXT_PUBLIC_WS_URL=wss://api.your-domain.com
NEXT_PUBLIC_SITE_URL=https://your-domain.com
```

由于：

```text
NEXT_PUBLIC_*
```

属于 Build-time Environment，修改后必须重新 Deployment。