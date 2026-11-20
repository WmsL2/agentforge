# AgentForge v0.12 — Atomic 2: Knowledge Base Management

## 1. Baseline Verification

2026-11-20 开始时 `git status --short` 无输出，工作区干净；分支 `main`，HEAD 为 `e2933c1abcdaae72e7f260800f6178f73e6892c3`。任务提供的基线为 Atomic 1 COMPLETE、Main CI #177 SUCCESS（16/16 Jobs）、365 Unit Tests / 26 Playwright E2E。上述 CI 是既有基线，不是本次未提交工作区的远端验收。Version 保持 0.11.0。

## 2. 实际实现功能

提供 Knowledge Base 列表和详情、URL Workspace 选择、创建/编辑/确认删除、真实 Workspace Membership RBAC、服务端分页、加载/空/错误/Retry 状态、Desktop Header / Sidebar / Mobile 导航和英/波翻译。

没有 Document Management、文件上传/下载 UI、Index、Search/Ask、Workflow Knowledge Node 或执行结果 UI；没有新增 Backend API、Migration、运行时依赖、版本变更或 Atomic 3 内容。

## 3. 页面与组件结构

| 新增文件 | 职责 |
|---|---|
| frontend/src/app/[locale]/(dashboard)/knowledge/page.tsx | 列表入口；复用 useAuth 并等待身份验证完成 |
| frontend/src/app/[locale]/(dashboard)/knowledge/[knowledgeBaseId]/page.tsx | 详情入口；读取动态 ID，复用 Dashboard Layout/AuthGuard |
| frontend/src/components/knowledge/knowledge-management.tsx | 身份 Session 边界、授权 Workspace 列表、URL 恢复、成员授权边界 |
| frontend/src/components/knowledge/knowledge-base-list.tsx | 真实列表、总数、10 条分页和 CRUD 入口 |
| frontend/src/components/knowledge/knowledge-base-detail.tsx | 真实元数据、严格资源 Scope、编辑/删除与返回 |
| frontend/src/components/knowledge/knowledge-base-form-dialog.tsx | 创建/编辑表单、删除确认、防重复提交与迟到回调隔离 |
| frontend/src/components/knowledge/knowledge-ui.ts | 安全错误映射、跨 realm AbortError 识别、异步 lease、UTC 日期显示 |
| frontend/src/components/knowledge/knowledge-management.test.tsx | 真实 Hooks/QueryClient/API facade 的组件集成测试，HTTP 边界 mock |
| frontend/src/components/knowledge/knowledge-navigation.test.tsx | 三端实际导航组件、默认/波兰语路径、翻译 keys 一致性 |
| docs/v0.12/atomic2-knowledge-base-management.md | 本实现记录 |

页面复用现有 PageHeader、Card、DataTable、Dialog、Select、FormField、Input、Textarea、Button 和 states。名称/描述仅作为 React 文本显示；不使用 dangerouslySetInnerHTML，不展示虚构文档/向量/索引统计。日期使用真实 API 时间戳的 UTC 日历日期，空 Updated At 显示破折号。

## 4. Knowledge CRUD 调用链

页面 → KnowledgeManagement → 已验证的 KnowledgeWorkspace → List/Detail/Dialog → 原有 useKnowledgeBases/useKnowledgeBase/useKnowledgeBaseMutations → 原 knowledgeApi → apiClient → 原同源 Next API → 原 Backend API。

没有第二套 Knowledge Data Layer，组件不直接调用 Knowledge HTTP 或 FastAPI。

- Create：name trim 后必填，按 Unicode 码点计数不超过 255；description trim 后空值发 null。只有真实成功才关闭弹窗和回到列表第一页。
- Update：初值来自真实 KnowledgeBaseRead；只提交 name/description，明确清空 description 发 null，name 不为 null。
- Delete：先显示影响文档和索引的确认弹窗，Cancel 不请求；按钮和同步 busy ref 防重复。成功由 Atomic 1 Mutation 完成缓存清理。详情删除成功只返回原 Workspace 的列表。
- Failure：保留用户输入并显示安全错误；403 关闭写弹窗并重新验证成员身份；无乐观伪造数据。
- Pagination：skip=page*10、limit=10，total 取后端响应。初次请求完成前不显示虚构的 0；禁止超出有效页码，删除末页最后一条后退到有效页并重新读取，Workspace 切换从第 0 页开始。

## 5. Workspace Selection / Scope 隔离

使用 URL `workspace_id`，且必须属于当前用户重新取得的授权 Workspace 列表。列表缺失或无效参数时选择第一个授权项并 replace URL；没有 Workspace 时显示 Empty State，提供保留 locale 的 Workflows 入口，不重复实现 Workspace CRUD。

详情缺少/无效 workspace_id 显示错误并提供返回列表，不在其他 Workspace 搜索 KB ID。详情请求固定携带已验证 Workspace，并核对响应的 workspace_id 与 knowledgeBaseId，异常响应不显示其名称或描述。

KnowledgeManagement 按 userId + generation + transitionEpoch 创建 Session 边界；内容再按 Workspace + KB ID 建立 key。退出、账号切换、同用户重新登录、Workspace 或资源变化都卸载旧作用域，关闭旧弹窗、清除表单及 Mutation observer。API 层仍保留 Atomic 1 的取消与身份保护。

UI 异步提交、失败、finally 和重试回调还使用 mounted + 原认证身份 lease；晚返回不能关闭新弹窗、改写新输入、显示旧错误 Toast 或导航到旧 Workspace。AbortError 被忽略。取消不能撤销已被后端接受的写入。

## 6. Workspace RBAC / 重新验证

写权限只来自 `useWorkspaceMembers(userId, workspaceId)` 中当前 userId 且 workspace_id 一致的 Membership；owner/admin 允许 Create/Edit/Delete，member 只读。App Admin、Workspace 创建者和 URL 均不授予写权限。未知、缺失、查询失败或重新验证过程中 fail closed。

对既有 Workspace Hooks 增加兼容的可选 `{ authorizationFresh: true }`，仅 Knowledge 页面启用：

- 保留原 qk.workspaces 前缀，附加 knowledge-access / generation / transitionEpoch，避免旧会话或默认 Workflow 缓存直接授予 Admin 权限。
- staleTime=0、gcTime=0、retry=false，挂载/重连/窗口聚焦重新验证；传递 AbortSignal、identityGuard 和 no-store。
- UI 必须 isFetchedAfterMount + isSuccess 且非 isFetching 后才采纳授权数据。重新验证时暂停当前内容，关闭可写弹窗，不保留旧资源 placeholder。
- 成员 403/404 或成功响应确认当前成员不存在时，调用原 clearKnowledgeScope，阻止已确认撤销的 Workspace 被自动重新选中，并重新取得授权列表；用户可以显式 Retry。
- Workspace 列表成功返回时，比较之前的 Workspace 与当前用户已存在的 Knowledge Query/Mutation scope；列表中已不存在的范围按原机制取消和清理，保留其他合法 Workspace/用户。
- 单个 KB 404 不被解释为整个 Workspace 失权。读取 Retry 先重新验证 Membership，再按当前 lease 重读资源；兼容 React 合并同步状态更新的情况，不依赖组件一定先卸载。

Workspace API facade 只为 listWorkspaces/listMembers 增加可选 RequestOptions。未启用新选项时，Workflow 的 query key、默认 freshness 和原单参数 HTTP 调用保持原行为。没有全局 QueryClient 策略变更。

前端不能实时获知尚未返回的服务端权限撤销；Backend 授权始终是最终边界。

## 7. Navigation / Internationalization

新增 ROUTES.KNOWLEDGE 和编码 ID 的 ROUTES.KNOWLEDGE_DETAIL，保留 legacy KB/KB_DETAIL。URL 为 /knowledge、/knowledge?workspace_id=…、/knowledge/{id}?workspace_id=…，通过 localizeHref 保留当前 locale。

Header、Sidebar、MobileTabBar 都使用现有 nav.knowledge，普通用户和 App Admin 均可见。列表及详情均 active；Mobile 使用现有 stripLocale 避免默认路径被错误截断，保留原五个入口，六入口使用 min-width/truncate/紧凑字距控制窄屏标签，不移除旧操作。

新增独立 knowledgeManagement namespace，en/pl keys 完全一致；未复用旧 knowledgeBases 的 Personal/Organization/App Scope 语义。按钮、弹窗、校验、状态和错误均有英/波文本。

## 8. Modified Files

| 修改文件 | 原因 |
|---|---|
| frontend/messages/en.json | 新 knowledgeManagement namespace |
| frontend/messages/pl.json | 对应波兰语 namespace |
| frontend/src/components/layout/header.tsx | Knowledge 入口，保留其他导航与样式 |
| frontend/src/components/layout/sidebar.tsx | Knowledge 入口及 active/locale |
| frontend/src/components/layout/mobile-tab-bar.tsx | Knowledge 入口、正确 locale 匹配和六项布局 |
| frontend/src/hooks/use-workspaces.ts | opt-in 授权 freshness、signal、identity guard、确认撤权清理 |
| frontend/src/lib/workflow/workspace-api.ts | 兼容的可选请求选项 |
| frontend/src/lib/constants.ts | 新 Knowledge routes，保留旧 routes |

## 9. 新增与保留的测试

原有 365 项测试保留。新增真实组件测试覆盖：

- 三端导航在普通用户/App Admin、默认及 /pl 列表/详情的入口、locale、active，以及翻译 keys 一致性。
- 真实列表及 total、默认/非法 Workspace 恢复、无 Workspace、失败/Retry、未授权 URL 不请求、Selector、分页及 Workspace 切换重置。
- Create/Edit/Delete 的成功/失败、清空 description、trim/长度校验、防重复、删除确认/Cancel/级联缓存清理、末页恢复。
- Owner/Admin 写、Member 只读、旧 Admin 缓存不直接授权、成员加载/错误/缺失、权限降级关闭弹窗、403 重新验证、单资源 404 保留其他 Workspace。
- Workspace/账号切换、Logout、同用户重新登录、迟到 Membership/Knowledge/Mutation 响应、旧回调不改新弹窗/输入/Toast/Navigation。
- 首次加载不伪造 0、初始授权列表清理不再可访问的旧 scope 且不影响其他用户、普通文本防 HTML 注入。
- 详情 metadata、响应范围核对、缺少/无效 workspace_id、404/Retry、返回、编辑/删除、Member 只读。
- 页面入口在匿名或身份验证中不启动管理数据请求。

组件测试使用真实 TanStack Query、Workspace/Knowledge Hooks、API facade、Auth Store 和生命周期清理；只在 fetch 边界提供受控响应及延迟，不通过替换 Hooks 为固定成功数据来获得通过。

## 10. Windows / Linux Verification

Windows：Node v22.13.0 / Bun 1.3.14。实际执行结果：

| 命令 | 结果 |
|---|---|
| bun install --frozen-lockfile | PASS，839 installs / 950 packages，无依赖或锁文件改动 |
| bun run test:run -- src/components/knowledge src/hooks/use-knowledge.test.tsx src/lib/workflow/workflow-api.test.ts | PASS，4 files / 113 tests（含 85 项新增组件测试） |
| bun run lint | PASS，0 errors / 13 条既有告警，无本次新增告警 |
| bun run type-check | PASS |
| bun run test:run | PASS，28 files / 450 tests |
| bun run test:coverage | PASS，28 files / 450 tests，所有原阈值通过 |
| bun run build | PASS，Next.js 15.5.23，Knowledge 列表及动态详情进入构建路由表 |
| git diff --check | PASS，无输出 |

新增 85 项中：Knowledge management 实际页面/组件集成测试 60 项，三端 Navigation/locale/翻译一致性测试 25 项。原有 365 项全部保留，没有 skip 或放宽断言。

Configured Coverage：Statements/Lines 69.23%，Branches 100%，Functions 60.86%。原 include/thresholds 均未改动；这些数字只对应原配置的四个文件，不代表所有新 UI 源码的覆盖率。

Linux：复用既有 oven/bun:1 镜像，在本任务隔离的临时容器中使用官方原生 Node v24.22.3 / Bun 1.3.14；源码只读挂载，依赖由 frozen lockfile 安装于容器临时目录。最终完整 Unit Tests + Coverage **28 files / 450 tests PASS**，同一阈值通过，Linux Type Check 通过。完整通过结果已在本次工具输出中确认；容器原始日志为 `/tmp/atomic2-linux.log`。验证结束后 Docker Desktop 被手动暂停，导致最后的 docker cp / docker rm 均失败，因此没有声称日志已拷回，也没有声称容器已清理。未擅自恢复 Docker，未改动现有运行服务。待清理容器为 `agentforge-v012-atomic2-verify-20261120`。

Windows 每个检查的原始日志位于 `frontend/node_modules/.cache/atomic2-*.log`（ignored）。保留既有 UI 可访问性告警、runtimeConfig 弃用提示及 Node HTTP 测试的 Zustand 无浏览器存储提示，未通过屏蔽诊断获得通过。

未触发远端 CI，未运行真实浏览器/真实后端 Knowledge Playwright 验收，未宣称基线 CI/E2E 是新工作区的验证。

## 11. Known Limitations

- 验证后的 Linux 日志拷回和临时容器删除受 Docker Desktop 手动暂停阻塞；验证本身已经成功完成，待恢复 Docker 后清理 `agentforge-v012-atomic2-verify-20261120`。
- 未执行新的真实后端 Knowledge Playwright 全链路验收；完整集成验收属于 Atomic 8。基线的 26 项 E2E / CI #177 成功不当作本工作区的重新验收。
- 未重新运行 Backend CI、数据库 Migration 或商业 Provider Smoke Test；没有新增相应功能。
- 导航的窄屏布局有组件/DOM 与样式约束验证，未声明已完成真实设备的视觉验收。
- 授权重新验证采取保守策略：重新进入、聚焦或重连时可能暂停内容并关闭表单，避免继续使用旧权限；有额外读取成本。
- 不能撤销已被服务器接受的写入；切回作用域后重新读取权威状态。跨标签页 Cookie 并发和服务端 Session 边界继续遵循 Atomic 1，不新增认证架构。
- 默认 coverage 配置仍只统计原先的四个文件，不能把其百分比当作全部新增 UI 源码覆盖率。没有降低阈值、删测试或修改 CI。

## 12. Git Status

最终仍为 main / e2933c1abcdaae72e7f260800f6178f73e6892c3。8 个 tracked 文件修改、10 个 untracked 新文件，均为上文列出的 frontend 和本 Atomic 文档。git diff --name-only 与修改文件表一致；Backend、Alembic、Version Metadata、package.json、bun.lock/bun.lockb、vitest.config.ts 与 CI 配置 diff 为空。git diff --stat 不包含新增文件；所有修改保留本地，未 stage。

实际 `git status --short`：

```text
 M frontend/messages/en.json
 M frontend/messages/pl.json
 M frontend/src/components/layout/header.tsx
 M frontend/src/components/layout/mobile-tab-bar.tsx
 M frontend/src/components/layout/sidebar.tsx
 M frontend/src/hooks/use-workspaces.ts
 M frontend/src/lib/constants.ts
 M frontend/src/lib/workflow/workspace-api.ts
?? docs/v0.12/atomic2-knowledge-base-management.md
?? frontend/src/app/[locale]/(dashboard)/knowledge/
?? frontend/src/components/knowledge/
```


## 13. Git Restrictions Confirmation / Deferred Features

No branch creation/switching. No git add. No commit. No push. No merge. No reset/stash. No PR/tag/release。Version 保持 0.11.0；不增加 Migration、Backend API、运行时依赖，不开始 Atomic 3。

后续 Document、Upload/Download UI、Index、Search/Ask、Workflow Knowledge Node 与执行输出均未实现；页面没有伪造数据或不可用按钮。
