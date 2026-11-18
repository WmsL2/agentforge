# AgentForge v0.12 — Atomic 1 Knowledge API Integration

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
