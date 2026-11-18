# AgentForge v0.12 — Atomic 1 Knowledge API Integration

> 第 1–12 节保留历史实现与修复记录。当前基线及最新验证结论以文末第 13 节 Final Review Corrections 为准。

## 1. Baseline Verification

2026-11-18 本地实现。开始时 `git status --short` 无输出，工作区干净；分支 `main`，HEAD 和 `git rev-list -n 1 v0.11.0` 均为 `32e4c0c6ec94d709b16f628a9b9810b6ac867656`。通过解析 Alembic revision/down_revision 源码图确认唯一 head 为 `0046_add_workflow_run_actor_identity`；没有连接数据库或执行 migration。

## 2. Implementation Summary / Scope

完成独立 Knowledge Frontend Data Layer：15 个类型化 API 方法、9 个 Next.js Route Handler、multipart 上传、私有二进制下载、11 类 Query/Mutation Hooks、独立查询键、身份校验、请求取消、缓存及敏感 mutation 结果清理、结构化错误和单元/回归测试。

Atomic 1 不包含 Knowledge UI、导航、索引轮询、Workflow Editor 改动、Conversation/Session/Memory、新 Backend API、migration、运行时依赖或 HTTP client 框架。Version 仍然为 **0.11.0**。

## 3. Created Files

以下路径均相对于仓库根目录；所有新增文件保留为本地 untracked 文件。

| 文件 | 职责 |
|---|---|
| `frontend/src/types/knowledge.ts` | 后端 wire schemas 与真实状态联合类型 |
| `frontend/src/lib/auth-identity.ts` | 用户及认证代次快照，识别退出后重新登录同一用户 |
| `frontend/src/lib/knowledge/knowledge-api.ts` | 15 个 facade 方法；显式请求字段、路径编码、分页白名单、资源权限二次确认 |
| `frontend/src/lib/knowledge/knowledge-lifecycle.ts` | 请求登记、取消、身份和资源范围清理、QueryClient 绑定 |
| `frontend/src/lib/knowledge/knowledge-error.ts` | 从 ApiError.data.error.code 提取稳定业务码 |
| `frontend/src/hooks/use-knowledge.ts` | 按需读取、CRUD、索引提交、主动 Search/Ask、下载及结果隔离 |
| `frontend/src/lib/knowledge/knowledge-api.test.ts` | 方法/请求契约、认证刷新、取消、错误、成员权限二次确认 |
| `frontend/src/lib/knowledge/knowledge-proxy.test.ts` | 全部 Handler、Cookie/CSRF、multipart、binary、安全错误 |
| `frontend/src/hooks/use-knowledge.test.tsx` | 查询键、Hooks、精确 invalidation、删除、身份切换和迟到响应 |
| `frontend/src/lib/server-api.test.ts` | raw text 回归、原始 Response、实际 multipart/二进制代理链路 |
| `docs/v0.12/atomic1-knowledge-api-integration.md` | 本实现记录和验证边界 |

9 个新增 route 文件的公共目录为 `frontend/src/app/api/workspaces/[workspaceId]/knowledge-bases/`：

| 相对该目录的文件 | 职责 |
|---|---|
| `route.ts` | 列表、创建 |
| `[knowledgeBaseId]/route.ts` | KB 读取、更新、删除 |
| `[knowledgeBaseId]/search/route.ts` | 主动检索 |
| `[knowledgeBaseId]/ask/route.ts` | 无会话问答 |
| `[knowledgeBaseId]/documents/route.ts` | 文档列表、文件上传 |
| `[knowledgeBaseId]/documents/[documentId]/route.ts` | 文档元数据读取、删除 |
| `[knowledgeBaseId]/documents/[documentId]/content/route.ts` | 解析内容 |
| `[knowledgeBaseId]/documents/[documentId]/download/route.ts` | 私有文件流 |
| `[knowledgeBaseId]/documents/[documentId]/index/route.ts` | 提交索引、读取状态 |

## 4. Modified Files

| 文件 | 修改原因 |
|---|---|
| `frontend/src/types/index.ts` | 导出新类型，保留旧类型 |
| `frontend/src/hooks/index.ts` | 导出新 Hooks |
| `frontend/src/lib/api-client.ts` | FormData、download、AbortSignal、原认证刷新中的身份校验和安全读取失败处理 |
| `frontend/src/lib/server-api.ts` | 新增 rawResponse；保留 raw=true 返回文本 |
| `frontend/src/lib/platform-api-proxy.ts` | 共享认证/CSRF/错误逻辑，新增 Knowledge no-store、multipart 和 streaming download 选项 |
| `frontend/src/lib/query-keys.ts` | 独立 qk.knowledge；保留既有 key |
| `frontend/src/app/providers.tsx` | 绑定当前 QueryClient 的身份切换清理订阅并释放订阅 |
| `frontend/src/hooks/use-auth.ts` | Logout 开始时先清除本地身份，立即使旧 Knowledge 请求失效 |
| `frontend/src/hooks/use-workspaces.ts` | 删除 Workspace 或确认 membership 不可访问时清理对应 Knowledge；晚到回调校验原始身份 |
| `frontend/src/lib/api-client.test.ts` | 原 JSON 方法、204、取消、单次刷新重试回归 |
| `frontend/src/lib/platform-api-proxy.test.ts` | 原 Workflow JSON/Location 语义回归 |

## 5. Architecture

### JSON

调用方把 workspaceId、资源 ID、类型化 payload 和可选 AbortSignal 传给 `knowledgeApi`。Facade 从认证状态取得用户快照，以 QueryKey 范围登记请求；userId 只参与本地校验，不发给后端。浏览器 `apiClient` 只请求同源 `/api/workspaces/.../knowledge-bases`，将 JSON 序列化；Next Handler 解析异步 params、分别编码 ID，将固定路径交给 `proxyPlatformApi`。代理从 access_token Cookie 构建 Bearer 认证，忽略浏览器 Authorization，执行 CSRF 和查询参数白名单后调用已有 `backendFetch`，通过现有 BACKEND_URL 请求 FastAPI。

成功状态由固定 Handler 契约确定，DELETE 204 返回空 body。BackendApiError 的 status/data 被保留；网络故障是安全 502。所有 Knowledge 上游请求 cache=no-store、redirect=error，并传递 request.signal；JSON 和错误响应 Cache-Control=no-store。

### Multipart Upload

Facade 创建 `FormData`，只 append `file` 和原始 filename。ApiClient 不 stringify，也不设置 multipart Content-Type；浏览器生成 boundary。代理先校验 Cookie 和 CSRF，再 `request.formData()`，检查 file 是文件，创建新的 FormData 并保留 File 的名称、类型和字节。`backendFetch` 已有 FormData 处理被复用。没有代理文件大小/格式规则，后端负责权威校验；非法 multipart 是本地 400，缺少文件是 422。201 + parse_status=failed 正常返回，不伪装成 HTTP 错误。

上传仅在 401 且原身份/代次/取消状态仍有效时，使用相同 FormData 经现有共享 refreshPromise 至多重试一次。403/409/422/500/502/503 不重发上传；403 可以触发只读 membership 二次确认。

### Private Binary Download

`knowledgeApi.downloadDocument` → `apiClient.download` → 固定下载 Handler → 同一代理的 download 分支 → `backendFetch({rawResponse:true})`。BackendFetch 先检查 HTTP 成功，错误仍抛 BackendApiError；成功直接返回未消费的 Response，代理以 `upstream.body` 构建 NextResponse，不做二次文件缓冲。

代理仅选择 Content-Type 和 Content-Disposition 文件名参数（保留合法 RFC 5987 Unicode filename），强制 attachment，添加 `private, no-store` 和 `nosniff`。不转发 Set-Cookie、Authorization、Location 或全部上游 headers。上传/下载不自动跟随上游重定向。

ApiClient 仅成功响应调用 blob()，返回 `{blob, contentDisposition, contentType}`，错误仍为 ApiError。没有 DOM 下载按钮、自动保存或 Object URL。原有 JSON get/post/put/patch/delete 和空响应返回 null 保留。

## 6. API Coverage

令 BASE=`/api/workspaces/{workspaceId}/knowledge-bases`，KB=`BASE/{knowledgeBaseId}`，DOC=`KB/documents/{documentId}`。后端对应 `/api/v1/workspaces/{workspace_id}/knowledge-bases`。

| Method | Frontend path | knowledgeApi method | Route file（相对公共目录） | Status |
|---|---|---|---|---|
| GET | BASE | listKnowledgeBases | route.ts | 200 |
| POST | BASE | createKnowledgeBase | route.ts | 201 |
| GET | KB | getKnowledgeBase | [knowledgeBaseId]/route.ts | 200 |
| PATCH | KB | updateKnowledgeBase | [knowledgeBaseId]/route.ts | 200 |
| DELETE | KB | deleteKnowledgeBase | [knowledgeBaseId]/route.ts | 204 |
| GET | KB/documents | listDocuments | [knowledgeBaseId]/documents/route.ts | 200 |
| POST | KB/documents | uploadDocument | [knowledgeBaseId]/documents/route.ts | 201 |
| GET | DOC | getDocument | [knowledgeBaseId]/documents/[documentId]/route.ts | 200 |
| GET | DOC/content | getDocumentContent | [knowledgeBaseId]/documents/[documentId]/content/route.ts | 200 |
| GET | DOC/download | downloadDocument | [knowledgeBaseId]/documents/[documentId]/download/route.ts | 200 |
| DELETE | DOC | deleteDocument | [knowledgeBaseId]/documents/[documentId]/route.ts | 204 |
| POST | DOC/index | requestIndex | [knowledgeBaseId]/documents/[documentId]/index/route.ts | 202 |
| GET | DOC/index | getIndexStatus | [knowledgeBaseId]/documents/[documentId]/index/route.ts | 200 |
| POST | KB/search | search | [knowledgeBaseId]/search/route.ts | 200 |
| POST | KB/ask | ask | [knowledgeBaseId]/ask/route.ts | 200 |

Index POST 不发送配置；无 job detail API、虚构 Location 或任意上游地址。列表只传 skip/limit，缺省使用后端 0/50。

### TypeScript Schema Mapping

15 个接口逐字段对应 `backend/app/schemas/knowledge.py`；UUID/datetime 均为 string，parse_metadata 为 `Record<string, unknown>`，没有 any。Create.name、Search.query、Ask.question 必填；Update.name 可省略但不能为 null，description 可省略或为 null；read 的 nullable 字段保留必需属性和 null。

- KB：KnowledgeBaseCreate / Update / Read / List。
- 文档：KnowledgeDocumentRead / List / Content；parse_status 仅 ready | failed，无 parsing。
- 索引：KnowledgeIndexJobRead / StatusRead；pending | running | succeeded | failed，Status 额外允许 not_indexed。job_id、active_generation_id、embedding_model、index_version、error_code 可为 null。最新 job 状态不代表 active generation 被覆盖。
- 检索：KnowledgeSearchRequest / ItemRead / Response；query 1–2000，top_k 可省略（后端默认 5，范围 1–20），min_score 可省略或 null（-1–1）。
- 问答：KnowledgeAskRequest / KnowledgeAgentSourceRead / KnowledgeAskResponse；请求只构造 question（1–2000），answered | no_evidence。

不映射 storage_path、embedding vectors 或 Provider Credentials；输入范围仍由后端进行最终验证。

## 7. Cache and Security Design

### Query Key Design

独立 `qk.knowledge`：

```text
[knowledge]
[knowledge, userId]
[knowledge, userId, workspaceId]
[knowledge, userId, workspaceId, list, skip, limit]
[knowledge, userId, workspaceId, base, knowledgeBaseId]
[knowledge, userId, workspaceId, base, knowledgeBaseId, documents, skip, limit]
[knowledge, userId, workspaceId, base, knowledgeBaseId, document, documentId]
[knowledge, userId, workspaceId, base, knowledgeBaseId, document, documentId, content]
[knowledge, userId, workspaceId, base, knowledgeBaseId, document, documentId, index]
```

额外提供 lists、documentLists 等精确前缀。不使用 qk.kb/qk.rag。

### Cache Lifecycle / Invalidation

读取必须有匹配当前认证用户的 userId、workspaceId 和所需资源 ID；queryFn 同样检查，手动 refetch 不能绕过缺失身份或 ID 的限制。Query 全部 staleTime=0、gcTime=0、retry=false，挂载/重连总是重新验证，窗口聚焦重新验证；文档内容显式 enabled=true 才查询，索引不轮询。不使用 placeholderData/keepPreviousData。

创建 KB 使对应列表分页失效；更新使同一列表和 exact KB 详情失效；删除 KB 清理 base 前缀全部子级。上传使当前 KB 文档列表分页失效；删除文档清理 document 前缀的详情/content/index/私有下载结果；索引提交只刷新对应 index key。成功回调不跨 workspace、user 或其他 KB。没有乐观伪造写入。

`clearKnowledgeScope` 同步 abort 已登记请求、通知 Mutation observer 清空，再 cancelQueries/removeQueries 和删除匹配 Mutation Cache。资源已知的 mutation variables 带 resourceKey，创建/上传成功后关联实际资源 ID，因此后续删除可清除对应结果。取消及身份 guard 阻止已被清理的操作晚到后重新写入。

### Identity / Race Conditions

认证快照包含 userId 和递增 generation；切换用户、logout、同一用户 logout 后重新登录都会使旧快照失效。Providers 为当前 QueryClient 订阅 auth store，只清理旧身份的 Knowledge 范围。Logout 在发送网络注销前先清理本地身份，立即触发上述机制。不会误删新用户的缓存。

每次 mutation 保存原始资源范围、payload、回调、controller、身份和序号。Workspace/KB/User 改变时，render 阶段遮蔽旧结果，effect 取消旧请求并 reset observer。晚返回的 Promise 必须仍匹配原身份、资源和序号才执行成功回调。写入 pending 时同一 observer 的相同输入重复提交合并到原 Promise；不同输入返回明确的本地 InvalidStateError，不能把前一次写入结果当成另一次成功。下载/Search/Ask 采用最新请求优先。不做自动重试。

Search/Ask 使用主动 Mutation，retry=false、gcTime=0，无页面自动请求，无长期 Query Cache，无 localStorage 持久化。连续请求取消旧 controller，旧响应不能覆盖新结果；已完成结果在资源变化、logout 或 scope 清理时也会清空。下载复用相同机制。reset/cancel 同时取消请求与清除可见状态。

401 刷新沿用唯一 refreshPromise，重试前后检查 AbortSignal、身份代次和资源 lease；旧请求不会在新用户身份下重放。刷新成功也只为仍然相同的身份更新内存 token。已取消的请求不在 refresh 后重发。

### Workspace Access / 403 and 404

成功删除 Workspace 时清理对应 Knowledge。成员列表返回 403/404，且原始身份仍匹配时，按该 Workspace 授权边界确认不可访问并清理。

Knowledge 资源返回 403/404 时，使用同一个取消/身份 guard 只读重新验证 `GET /api/workspaces/{id}`。只有 Workspace 本身也返回 403/404 才清理整个 Workspace。单独文档 404 且 Workspace 仍可访问，保留其他合法范围。二次验证网络失败不被解释为权限丢失，原始资源 ApiError 的 status/data 仍保留。授权失败不触发写入重试。

浏览器不能实时获知服务端权限变化；重新验证前可能仍有当前页面已经取得的数据。上述保证是资源隔离、合理重新验证和已确认失效后的本地清理，后端授权始终是最终安全边界。

### Authentication and CSRF / Error Handling

Cookie token 是代理唯一身份来源；浏览器 Authorization 不能覆盖。Mutation 拒绝 cross-site Fetch Metadata 或不匹配/非法 Origin，且在 multipart 解析之前拒绝。所有动态 segment 单独 encodeURIComponent。

ApiError 与 BackendApiError 保留 status/data；getApiErrorMessage 保留 detail string、422 detail array 和 structured error 的 message。getKnowledgeErrorCode 仅读取 error.code，不通过英文 message 分类；因此支持 DOCUMENT_TOO_LARGE、DOCUMENT_TYPE_UNSUPPORTED、DOCUMENT_MIME_MISMATCH、DOCUMENT_CONTENT_UNAVAILABLE、DOCUMENT_NOT_READY_FOR_INDEXING、KNOWLEDGE_INDEX_MODEL_INCOMPATIBLE、KNOWLEDGE_AGENT_DISABLED、KNOWLEDGE_AGENT_MODEL_NOT_CONFIGURED、KNOWLEDGE_AGENT_TIMEOUT、KNOWLEDGE_AGENT_EXECUTION_FAILED、EMBEDDING_PROVIDER_UNAVAILABLE、EMBEDDING_TIMEOUT 及其他后端稳定码，原 details 不丢失。

代理网络异常返回通用 UPSTREAM_UNAVAILABLE/502；客户端 Knowledge 网络/响应流异常为安全通用消息，非法成功 JSON 为 Invalid server response。不透传原始网络异常、URL、密钥、stack 或私有路径。没有完整 UI 国际化。

## 8. Tests

定向测试命令：

```powershell
bun run test:run -- src/lib/knowledge src/lib/server-api.test.ts src/hooks/use-knowledge.test.tsx src/lib/api-client.test.ts src/lib/platform-api-proxy.test.ts
```

测试覆盖 15 个方法及 Handler 的路径、method、JSON、分页和状态；Cookie 优先及全部变更方法 CSRF；真实 multipart Request 的解析及二次序列化，Unicode filename/MIME/含 0 和 255 的字节；201 parse failed；二进制 body 及安全响应头；结构化错误/422/安全 502；JSON/raw text 回归；取消、401 单次刷新、同用户重新登录、新用户切换、Workspace 切换、迟到 mutation/query、按范围删除、敏感完成结果清理、Membership 二次确认。

最终验证结果（2026-11-18）：

| 命令 | 结果 |
|---|---|
| bun install --frozen-lockfile | PASS，839 installs / 950 packages，无依赖和 lockfile 改动 |
| 上述 targeted tests | PASS，6 files / 149 tests |
| bun run lint | PASS，0 errors / 13 warnings（12 条既有 UI 可访问性告警及 coverage 生成文件 1 条告警） |
| bun run type-check | PASS |
| bun run test:run | PASS，24 files / 337 tests |
| bun run test:coverage | PASS，24 files / 337 tests，既有阈值通过 |
| bun run build | PASS，Next.js 15.5.23；105 个静态页面生成完毕，9 个 Knowledge API routes 均进入构建路由表 |
| git diff --check | PASS，无输出 |

Configured coverage：Statements 58.85%，Branches 100%，Functions 52.17%，Lines 58.85%。统计范围仅为原配置的四个既有文件，不代表 Knowledge 新代码覆盖率。构建有既有 Next.js runtimeConfig 弃用提示和 UI 可访问性 warnings，没有通过关闭检查消除它们。

原有测试、coverage include/thresholds、类型检查和运行时依赖配置未被删改或放宽。

## 9. Known Limitations

- 不等同于真实前后端全链路验收完成；未执行真实浏览器全生命周期、商业 Provider Staging Smoke Test 或全部 Backend CI。
- 未连接 PostgreSQL，不声明数据库实际运行中的 migration 状态。Alembic head 验证基于仓库源码图。
- AbortSignal 取消与迟到结果隔离不能撤销已经被后端接受的写入；再次进入时读取权威状态。
- 既有全局 refresh HTTP 请求可能由其他请求共享，单个 Knowledge 请求取消不会终止全局刷新；身份变化后不重放旧 Knowledge 请求、不写入旧内存 token。没有宣称本 Atomic 解决全部浏览器 Cookie 并发登录/注销问题。
- 调用方已取得的 Blob/Promise 返回值不能被 JavaScript 远程撤回；Hooks/QueryClient 中的敏感结果按上述机制清理，调用方应避免自行持久化。
- 默认 coverage 配置只统计 auth-cookies.ts、utils.ts、auth-store.ts、button.tsx 四个既有文件；该百分比不代表新增 Knowledge 源码的覆盖率。新增功能由明确的行为测试验证。
- 最初受限执行下 Bun 1.3.14 安装崩溃：`panic(main thread): reached unreachable code`；后续受限运行报告 `CouldntReadCurrentDirectory`。提升执行权限后 frozen install 正常（839 installs / 950 packages，no changes），后续规定命令使用同样执行方式。安装 prepare 有 `.git can't be found` 提示，但命令退出 0，没有修改 Git 状态。
- 不开始 Atomic 2。

## 10. Git Status

最终只读 Git 核查：Branch 仍为 main，HEAD / v0.11.0 仍为 32e4c0c6ec94d709b16f628a9b9810b6ac867656。11 个 tracked 文件修改、20 个 untracked 新文件（含本文件）。git diff --stat 只计 tracked 修改，不包含新增文件。所有变更仅保留在本地。

`git status --short`：

```text
 M frontend/src/app/providers.tsx
 M frontend/src/hooks/index.ts
 M frontend/src/hooks/use-auth.ts
 M frontend/src/hooks/use-workspaces.ts
 M frontend/src/lib/api-client.test.ts
 M frontend/src/lib/api-client.ts
 M frontend/src/lib/platform-api-proxy.test.ts
 M frontend/src/lib/platform-api-proxy.ts
 M frontend/src/lib/query-keys.ts
 M frontend/src/lib/server-api.ts
 M frontend/src/types/index.ts
?? docs/v0.12/
?? frontend/src/app/api/workspaces/[workspaceId]/knowledge-bases/
?? frontend/src/hooks/use-knowledge.test.tsx
?? frontend/src/hooks/use-knowledge.ts
?? frontend/src/lib/auth-identity.ts
?? frontend/src/lib/knowledge/
?? frontend/src/lib/server-api.test.ts
?? frontend/src/types/knowledge.ts
```

`git diff --stat`：

```text
 frontend/src/app/providers.tsx              |   6 +-
 frontend/src/hooks/index.ts                 |   2 +
 frontend/src/hooks/use-auth.ts              |   1 +
 frontend/src/hooks/use-workspaces.ts        |  29 ++++++-
 frontend/src/lib/api-client.test.ts         |  49 ++++++++++-
 frontend/src/lib/api-client.ts              | 130 ++++++++++++++++++----------
 frontend/src/lib/platform-api-proxy.test.ts |  15 ++++
 frontend/src/lib/platform-api-proxy.ts      |  42 ++++++++-
 frontend/src/lib/query-keys.ts              |  20 +++++
 frontend/src/lib/server-api.ts              |   5 +-
 frontend/src/types/index.ts                 |   2 +
 11 files changed, 250 insertions(+), 51 deletions(-)
```

`git diff --name-only` 仅包含上文 11 个 frontend 修改；对 backend、Alembic、frontend/package.json、bun.lock/bun.lockb、版本元数据的 diff 为空，没有新增依赖或版本变更。

## 11. Restrictions Confirmation

- No branch creation.
- No branch switching.
- No git add.
- No commit.
- No push.
- No merge.
- No reset or stash.
- No tag.
- No release or GitHub PR.

Backend、Alembic、Version Metadata、lockfile 不修改。等待 ChatGPT 审查本实现报告。


## 12. Main CI #173 Fix — 2026-11-18

### 12.1 Baseline Verification

修复任务开始和结束均要求保持 main / `02ab18b4c6e2b800fdb847531c1fbc6024107a91`。开始时 `git status --short` 无输出，工作区干净。PR #29 已合并；任务提供的 [Main CI #173](https://github.com/WmsL2/agentforge/actions/runs/44258962940) 中 test-frontend（Job 134647363018）为 334 passed / 3 failed。本次不创建分支、不提交、不推送、不启动 Atomic 2。

### 12.2 三项 CI 失败的实际根因

在现有 Docker Linux 引擎的临时 oven/bun:1 容器中，使用官方原生 Node **v24.22.3**、Bun **1.3.14**、Vitest **2.1.9** 和 jsdom **25.0.1**，从 HEAD 的只读 git archive 提取合并基线，以 frozen lockfile 安装依赖后运行三个相关测试文件。实际结果为 **94 tests / 91 passed / 3 failed**，三项错误与任务提供的 CI 日志一致：

| 场景 | 复现错误 | 根因 |
|---|---|---|
| reads only successful binary as Blob | result.blob.arrayBuffer is not a function | 默认 jsdom 环境的 Blob API 不完整；测试把浏览器 Blob 当作一定支持 Node arrayBuffer 的 Blob。本机 Node 22 的通过不能证明 Node 24 中相同混合环境兼容 |
| fixed route … POST | WebIDL assert: USVString(value) or File(value) | 混合 jsdom File/Blob 与原生 Request/FormData；仅替换 FormData constructor 不能统一 WebIDL 对象归属 |
| real multipart proxy/server client preserves Unicode filename, MIME and bytes | expected 400 to be 201 | 原生 Request、Node File、jsdom 全局及 constructor 替换混用，使 multipart 处理失败并进入代理现有安全 400 分支；TypeScript cast 不会改变运行时对象归属 |

这些不是后端契约变化。使用一致的原生 Node Web API 后，现有生产 multipart 代理通过真实编码、解析和二次转发测试，因此未修改 platform-api-proxy.ts 或 server-api.ts 的生产上传/下载逻辑。

### 12.3 修复前后行为

- server-api.test.ts、knowledge-proxy.test.ts、platform-api-proxy.test.ts 显式使用 `@vitest-environment node`。保留真实 Request/NextRequest、FormData、File、编码 boundary、解析和转发，不替换为返回成功的 mock。
- 移除两个 multipart 测试的 FormData constructor 全局替换；server-api 测试直接使用同一 Node 环境的 File/FormData，不再用 Node File 与 jsdom File 的强制转换。
- vitest.setup.ts 的 window.localStorage 与 matchMedia 初始化仅在 window 存在时执行；没有为 Node 环境伪造 window，也没有修改 CI 或降低 Coverage 阈值。
- 浏览器侧下载测试使用功能检测：支持 arrayBuffer 时直接读取，否则通过 FileReader 读取字节。新增实际 jsdom Blob 的字节测试，保留 `[0,255,128]` 等逐字节断言。
- Unicode filename、MIME、multipart boundary、201 + parse_status=failed、Cookie Authorization、CSRF、私有下载 headers、结构化错误和全部原有测试均保留。

### 12.4 Authentication Race Condition 审查与修复

原 generation 检查只能阻止旧结果写内存，不能撤销浏览器已经处理的 Set-Cookie。原始 /auth/me、/auth/refresh 都可能修改或清除 Cookie；AuthGuard、auth-store.checkAuth、定时刷新、Chat WebSocket 重连和 OAuth 回调还存在分散调用或写入入口。

新增轻量 `auth-transition.ts`，在同一页面 JavaScript 实例内对以下 Cookie 写入入口使用同一个顺序屏障：Login、Logout、Refresh、具有刷新副作用的 /auth/me，以及 OAuth Callback / Magic Link Verify。

1. Login/Logout 调用开始时同步推进 transition epoch，清除旧 user/token，立即触发原有 Knowledge 清理；此时即便旧用户本来就是 null，epoch 也能使旧请求失效。
2. 已开始的 Cookie 写请求必须先取得并消费响应，再允许下一个认证写入开始。不会把 AbortSignal 传给已协调的底层 fetch 来提前释放屏障；调用方取消只使其结果不再被采纳。认证响应很小，使用 clone.arrayBuffer 保持原响应供既有 JSON 解析。
3. 旧 Refresh 成功设置的 Cookie，或者失败时清除的 Cookie，都先于 Logout / 新 Login 完成；Logout 因而能携带刷新后实际生效的 refresh_token，新的 Login Cookie 最后生效。
4. Logout / Login 转换期间拒绝自动 /me、Refresh；Logout 后继续禁止自动重新认证，直到显式成功登录。屏障中排队但已过期的 Probe 不发送 HTTP。
5. 身份快照包含 userId、generation 和 transition epoch；转换期间身份不可用于 Knowledge 请求。旧 Knowledge 请求不通过新用户 Cookie 重试，已完成的 Search/Ask/Download 结果也由既有 scope 清理。
6. ApiClient 统一负责认证结果写入 Auth Store，只有当前操作可以提交。旧成功、错误和 finally 回调不覆盖新用户、Token、Loading 或导航。Logout 响应不采纳 Token 字段。
7. 原自动 401 刷新仍只有一套共享 flight，现按身份快照限定共享，旧 flight 的 finally 不能清除新 flight。新 Login 等待旧 Cookie 写入结束属于必要屏障；新会话创建后不复用旧会话的刷新结果。
8. auth-store.checkAuth 通过同一 apiClient 执行，启动导入前后都校验 epoch。AuthGuard 使用 checkAuth，未认证时不渲染受保护 children。
9. useAuth 的 Login/Logout、显式刷新、十分钟刷新均进入同一链路；同一挂载 Hook 退出后再次登录会恢复定时器，最后一个消费者卸载时停止定时器。
10. Chat 重连不再直接 fetch /api/auth/me；OAuth 回调不再自行写入用户和 Token。额外审查到 Profile / Avatar 的异步 setUser 回调，均增加原始身份检查，避免晚返回后恢复旧用户。

没有重写服务器认证架构，没有修改 Backend 授权或 Session 策略。

### 12.5 Created / Modified Files

新增三个源码/测试文件：

| 文件 | 职责 |
|---|---|
| frontend/src/lib/auth-transition.ts | 页面内 Cookie 写入顺序、转换 epoch、Probe 准入 |
| frontend/src/lib/auth-transition.test.ts | 真实 Next Auth Handler + 延迟后端 + Cookie Jar 的竞态测试 |
| frontend/src/hooks/use-auth.test.tsx | 实际 AuthGuard、Hooks、定时刷新、Profile/Avatar 晚返回测试 |

修改文件：

| 文件 | 修改职责 |
|---|---|
| frontend/src/lib/api-client.ts | 认证请求统一协调、集中提交状态、身份限定 refresh flight、禁止跨身份重试 |
| frontend/src/lib/auth-identity.ts | 快照包含 transition epoch，转换期间不提供 Knowledge 身份 |
| frontend/src/stores/auth-store.ts | checkAuth 统一接入和启动取消，Logout 禁止自动恢复 |
| frontend/src/hooks/use-auth.ts | 移除分散状态提交；统一登录、退出、刷新与定时器生命周期 |
| frontend/src/components/layout/auth-guard.tsx | 统一 checkAuth，退出时隐藏 children |
| frontend/src/hooks/use-chat.ts | 重连认证接入统一入口 |
| frontend/src/app/[locale]/auth/callback/page.tsx | 移除旧异步回调的重复身份写入 |
| frontend/src/app/[locale]/(dashboard)/settings/profile/page.tsx | Profile/Avatar 迟到回调身份检查 |
| frontend/src/lib/knowledge/knowledge-api.test.ts | 浏览器 Blob 字节读取兼容及实际字节断言 |
| frontend/src/lib/knowledge/knowledge-proxy.test.ts | 统一 Node HTTP 环境，移除 constructor 替换 |
| frontend/src/lib/server-api.test.ts | 原生 Node File/FormData 真实 multipart 链路 |
| frontend/src/lib/platform-api-proxy.test.ts | Server HTTP 回归测试使用 Node 环境 |
| frontend/vitest.setup.ts | window 初始化有条件执行，支持 Node 测试 |
| frontend/src/stores/auth-store.test.ts | checkAuth 启动前退出，不发送旧 Probe |
| frontend/src/lib/utils.test.ts | Profile 实际依赖的缺省/非法/Date/string 日期边界 |
| docs/v0.12/atomic1-knowledge-api-integration.md | 本修复记录 |

### 12.6 新增与保留测试

保留原有 **337** 项测试，新增 **25** 项，共 **362** 项、**26** 个测试文件：

- Blob 实际字节读取 1 项。
- Node Authentication Transition 11 项：三种登录入口、Logout、Refresh/Logout 并发、成功/失败 Cookie 写入与新 Login 顺序、旧 /me 与排队 Probe、取消不释放 Cookie 屏障、新身份独立 refresh flight、同身份共享刷新、Knowledge 清理和不跨用户重试。
- 浏览器 Hooks/Guard 11 项：隐藏 children、Login/Logout、旧退出不影响新登录导航、十分钟刷新及再次登录恢复、显式刷新、失败登录、过期 /me、Profile/Avatar 在 Logout 和新 Login 后的晚返回。
- auth-store 启动前退出 1 项；Profile 日期边界 1 项。

Cookie 竞态测试调用真实 Next Route Handler 生成 Set-Cookie，用 Cookie Jar 在 fetch Promise 返回前应用这些真实响应 Cookie；只 mock 后端业务响应并加入延迟，验证的是实际请求发送顺序和状态结果。它不是一次真实浏览器/真实后端 E2E，不能把该 Cookie Jar 模型声称为浏览器全生命周期验收。

### 12.7 本地验证结果

Windows：Node v22.13.0 / Bun 1.3.14。规定的 frozen install 成功（839 installs / 950 packages，no changes）；规定的原定向命令 **6 files / 150 tests PASS**。新增认证专项测试另由完整 suite 执行。

最终 Windows 规定命令结果（全部退出 0）：

| 命令 | 结果 |
|---|---|
| bun install --frozen-lockfile | PASS，无依赖或锁文件改动 |
| 任务指定的六文件定向测试命令 | PASS，6 files / 150 tests |
| bun run lint | PASS，0 errors / 13 warnings |
| bun run type-check | PASS |
| bun run test:run | PASS，26 files / 362 tests |
| bun run test:coverage | PASS，26 files / 362 tests，所有原阈值通过 |
| bun run build | PASS，Next.js 15.5.23，105 个静态页面生成完毕 |
| git diff --check | PASS，无输出 |

Windows Node 22.13.0 与 Linux Node 24.22.3 的完整测试和 Coverage 均通过。Linux 最终原始测试日志保存在 `frontend/coverage/atomic1-fix-linux-node24.log`（ignored 验证产物，非源码变更）。

Coverage 保留既有 include 和所有 thresholds。中途完整测试已通过，但新增 Profile 测试使原先未执行的日期分支进入统计，分支 Coverage 为 88.57%，未达到原 90% 阈值；新增实际日期边界和 Probe 启动取消用例后，最终配置范围为 Statements/Lines **69.23%**、Branches **100%**、Functions **60.86%**，auth-store.ts 的 Statements/Lines/Branches 为 **100%**。没有降低阈值或修改统计范围。该聚合百分比只对应原配置的四个文件，不代表 auth-transition.ts / Knowledge 源码的整体覆盖率。

Lint/Build 保留既有可访问性和 runtimeConfig 弃用告警。Node HTTP 认证测试中，真实 Zustand Store 在无 window 的服务器环境会输出 storage unavailable 提示；测试未伪造 window 或隐藏诊断，浏览器 Store/Guard 行为另在 jsdom 测试中验证。

### 12.8 Linux / CI Runtime 验证

- 使用已有 Docker Linux 引擎及已有 oven/bun:1 镜像；原生 Node v24.22.3 从官方发布存档解压到临时容器，没有安装新的大型环境或更改宿主 Node。
- 使用锁文件对应依赖和相同 Vitest/jsdom。合并基线三个文件为 **91 passed / 3 failed**，精确复现任务列出的三项失败。
- 修复版本完整 Linux 单元测试及 Coverage：**26 files / 362 tests PASS**，原 Coverage 阈值通过；Linux TypeScript 类型检查也通过（LINUX_TYPE_CHECK_PASS）。
- 工作流使用 ubuntu-latest，Setup Bun 没有固定版本，也没有显式固定 Node 版本。本次是关键运行时复现，不能宣称临时容器的发行版及补丁版本与失败 Job 完全相同。
- 未触发 GitHub Actions 重跑，**不能声明 Main CI PASS**。也未执行该 Job 后续的真实 PostgreSQL/Redis/Playwright E2E 或其他 Backend CI。

### 12.9 Known Limitations / 安全边界

- 单页面保证：仅覆盖当前页面中已审查并统一接入的认证 HTTP 入口；已开始的 Cookie 写操作顺序完成，旧身份结果不再被采纳。没有仅靠 Abort fetch 或 generation 宣称解决 Set-Cookie。
- 跨标签页、另一浏览器窗口、重新载入页面或其他客户端不共享本页内存屏障；未新增 BroadcastChannel、跨页锁或服务端 Session 代次协议，不能保证这些场景的 Cookie 并发顺序。
- 服务端 Session / Token 失效仍由已有 Backend Logout/JWT 策略决定；本次没有修改该策略，也没有证明所有 Session 即时失效。
- Cookie 写请求若持续不返回，后续认证转换会等待；本地旧数据立即隐藏，不以提前释放屏障换取表面成功。
- 网络失败时仍会保持本地退出和禁止自动恢复，但无法声称服务器 Logout 已完成或浏览器一定收到清 Cookie 响应；重新加载是另一个生命周期。
- Profile/Avatar 等已被后端接受的业务写入不能撤销；这里只隔离晚返回的本地身份更新。
- 不开始 Knowledge UI、不新增 Migration、不新增运行时依赖、不更新 Version（仍 0.11.0）。

### 12.10 Git Status

结束时仍为 main，HEAD 为 `02ab18b4c6e2b800fdb847531c1fbc6024107a91`。16 个 tracked 文件修改、3 个 untracked 新文件；全部为上表 frontend 源码/测试和本文件。

`git status --short`：

```text
 M docs/v0.12/atomic1-knowledge-api-integration.md
 M frontend/src/app/[locale]/(dashboard)/settings/profile/page.tsx
 M frontend/src/app/[locale]/auth/callback/page.tsx
 M frontend/src/components/layout/auth-guard.tsx
 M frontend/src/hooks/use-auth.ts
 M frontend/src/hooks/use-chat.ts
 M frontend/src/lib/api-client.ts
 M frontend/src/lib/auth-identity.ts
 M frontend/src/lib/knowledge/knowledge-api.test.ts
 M frontend/src/lib/knowledge/knowledge-proxy.test.ts
 M frontend/src/lib/platform-api-proxy.test.ts
 M frontend/src/lib/server-api.test.ts
 M frontend/src/lib/utils.test.ts
 M frontend/src/stores/auth-store.test.ts
 M frontend/src/stores/auth-store.ts
 M frontend/vitest.setup.ts
?? frontend/src/hooks/use-auth.test.tsx
?? frontend/src/lib/auth-transition.test.ts
?? frontend/src/lib/auth-transition.ts
```

`git diff --name-only` 与上表一致；Backend、Alembic、Version Metadata、package.json、bun.lock/bun.lockb、vitest.config.ts 和 .github/workflows/ci.yml 的 diff 为空。git diff --stat 仅统计 tracked 修改，不包含三个新增文件。临时容器只挂载 frontend 为只读来源，测试运行于容器临时目录，验证后停止并自动移除；没有创建其他持久环境或改动 CI。

### 12.11 Git Restrictions Confirmation

No branch creation/switching. No git add. No commit. No push. No merge. No reset/stash. No PR, tag or release. 所有改动留在本地，等待审查，不开始 Atomic 2。


## 13. Final Review Corrections — Queued Logout / Stale 401

### 13.1 基线与范围

开始时工作区干净，分支为 `review/v012-atomic1-fix-ci-auth`，HEAD 为 `f105389c8d40812329e58cd1f00b66d17db1d80d`。任务提供的 PR #30 / CI #174 已通过 362 项 Unit Tests 和 26 项 Playwright E2E；这些属于修正前提交的结果，不作为本地未提交修正已经通过远端 CI 的证明。

本次只处理 Queued Logout 和 Stale 401；生产代码仅修改 api-client.ts 两处，auth-transition.ts 的现有 FIFO 框架不变。无新增依赖、Backend、Migration、CI 配置、Version 或 Atomic 2 改动。

### 13.2 Queued Logout

新增测试先在未修复源码中复现：Refresh A 阻塞时，Logout A 和 Login B 依次排队；Login B 推进 epoch 后，Logout 的 `identityGuard: current()` 在实际发送前失败。观察到的 HTTP 顺序是 Refresh → Login，Logout 被跳过。

修复仅对已分类为 logout 的协调请求放行其传输准入，使其在 FIFO 中继续发送；perform 在出队时仍取得身份快照，其余取消/身份检查保留。认证结果提交处的 `if (!current()) aborted()`、状态更新与 finally 的 current 检查均不放宽，useAuth 的导航 epoch 检查也保持不变。故旧 Logout 可以完成后端注销与 Cookie 清理，却仍不能采纳旧结果或更改新会话导航。旧 Logout 调用方收到 AbortError 是过期结果隔离，不代表 HTTP 被跳过。

使用真实 Next Refresh / Logout / Login Handler 和响应 Cookie Jar 验证：

1. Refresh A 响应延迟，Logout A 与 Login B 尚未发 HTTP。
2. Refresh A 返回 access_token=a2、refresh_token=ra2。
3. Logout A 必须发送，后端收到刷新后的 ra2；Logout 响应也被延迟，此时 Login B 仍不得发送。
4. Logout 响应清 Cookie 后才发送 Login B。
5. 最终实际顺序严格为 Refresh A → Logout A → Login B，Cookie 为 b/rb，Auth Store 为用户 B / Token b。

另一个实际 useAuth Hook 测试验证相同排队顺序，且只有新 Login 的 Chat 导航，没有旧 Logout 的 Login 导航。

### 13.3 Stale 401

普通请求并不总是进入 Knowledge 的 identityGuard，所以只在刷新之后校验身份太晚。新增测试在未修复源码中观察到：A 的普通 /users/me 请求延迟返回 401，而 B 已登录；旧请求触发了 B 的 Refresh，虽然之后被 Abort，B 的 Cookie 已被改变。

现在所有非 coordinated 请求进入 401 分支后，在 `refreshAccessToken()` 之前显式检查最初捕获的 identity；不匹配立即 Abort。原有刷新后的检查和重试前检查保留。没有放宽普通请求、Knowledge 请求或其他认证操作的保护。

回归测试验证：旧普通请求仅发送一次；B 登录后旧 401 不产生任何 /auth/refresh HTTP 或后端 Refresh 调用、不重发旧请求；B 的 Cookie、User、Token 与 epoch 均保持不变。

### 13.4 修改文件与回归测试

仅四个 tracked 文件修改，无新增源码文件：

| 文件 | 改动 |
|---|---|
| frontend/src/lib/api-client.ts | Queued Logout 传输准入；Stale 401 刷新前身份校验 |
| frontend/src/lib/auth-transition.test.ts | 真实 Auth Handler / Cookie Jar 排队注销测试；普通请求旧 401 测试 |
| frontend/src/hooks/use-auth.test.tsx | 排队注销实际发送且不影响 B 导航的 Hook 测试 |
| docs/v0.12/atomic1-knowledge-api-integration.md | 本次修正和验证记录 |

新增三项测试在修复前全部失败（原认证专项 22 项通过 / 新增 3 项失败），修复后认证专项为 2 个文件 / 25 项通过。原 362 项测试全部保留，完整套件为 26 个文件 / 365 项；没有删改旧断言、跳过测试或降低阈值。

### 13.5 实际验证结果

Windows Node v22.13.0 / Bun 1.3.14：

| 命令 | 实际结果 |
|---|---|
| bun run test:run -- src/lib/auth-transition.test.ts src/hooks/use-auth.test.tsx | 2 files / 25 tests PASS |
| bun run lint | PASS，0 errors / 13 条既有告警 |
| bun run type-check | PASS |
| bun run test:run | 26 files / 365 tests PASS |
| bun run test:coverage | 26 files / 365 tests PASS，既有全部阈值通过 |
| bun run build | PASS |
| git diff --check | PASS，无输出 |

Configured Coverage：Statements/Lines 69.23%，Branches 100%（40/40），Functions 60.86%；include/thresholds 未修改，聚合百分比仍只对应原配置的四个文件。

复用现有 oven/bun:1 镜像，在只读挂载源码的独立临时 Linux 容器中使用原生 Node v24.22.3 / Bun 1.3.14：完整 Unit Tests + Coverage 为 **26 files / 365 tests PASS**，TypeScript 检查通过。Linux 原始日志保存为 `frontend/coverage/atomic1-final-review-linux-node24.log`（ignored 验证产物）。该临时容器已移除，未修改或停止现有服务。

本次未重新运行远端 CI 或 Playwright E2E，不能将任务提供的 CI #174 成功直接当作此未提交补丁的 CI 结果。既有 Node HTTP 测试的 Zustand 无浏览器存储提示、Lint/Build 的既有告警仍如实保留。

### 13.6 限制与 Git

本次真实 Handler / Cookie Jar 测试包含延迟响应，但仍不是跨标签页或真实浏览器全链路验收；单页面协调、跨标签页及服务端 Session 边界保持第 12.9 节说明。本次不将 CI #174 或之前的 26 项 Playwright 结果宣称为未提交补丁的重新验收。

最终只读核查：工作分支仍为 `review/v012-atomic1-fix-ci-auth`，HEAD 仍为 `f105389c8d40812329e58cd1f00b66d17db1d80d`。仅第 13.4 节列出的四个 tracked 文件修改，无新增源码文件；Backend、依赖锁文件、版本元数据、CI 和 Coverage 配置均无修改，git diff --check 无输出。未创建或切换分支，未执行 git add、commit、push、merge、reset、stash，等待审查，不开始 Atomic 2。
