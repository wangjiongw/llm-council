# Chatbox 功能优化核对与工程方案


## 0. 进度快照（2026-06-04）

本轮已完成一组偏“日常使用效率 + 部署可靠性”的工程项，当前方案进度需要从原先的规划状态更新为以下状态。

### 0.1 已完成

- 会话组织基础版：conversation JSON、列表 API 和前端 Sidebar 已支持 `favorite`、`archived`、`pinned`、`tags`、`updated_at`。
- 会话列表交互：默认 Active 视图、Archived 视图、收藏筛选、标签筛选、Pinned 独立分组、Archive/Restore、标签编辑已完成。
- 会话排序：后端列表按 `pinned` 优先，其次 `updated_at/created_at` 倒序；前端也按同样规则分组展示。
- 长会话性能：`RichMarkdown` 已加入视口懒渲染，完整 Markdown/KaTeX/Mermaid/代码高亮在靠近视口后再展开。
- 部署稳定性：新增 `deploy/native/start-backend.sh`；非 systemd 模式优先直接执行 `.venv/bin/python3 -m backend.main`，PID 文件记录真实后端进程。
- 健康检查：`deploy/native/status.sh` 不再只看 PID，也会探测后端 `/api/conversations` 是否响应。
- 停止流程：`deploy/native/stop-backend.sh` 增加等待退出和兜底终止，减少旧进程残留。
- 验证覆盖：新增 `tests/test_conversation_metadata_api.py`，覆盖会话元数据 PATCH、标签规范化、置顶排序和错误校验。
- 当前会话搜索：聊天区已支持本地全文搜索、范围筛选、命中片段、Prev/Next 跳转和目标消息高亮。
- 左侧历史搜索：Sidebar 已支持 `/api/conversations/search`、结果片段、来源标识、Active/Archived/Favorite/Tag 筛选联动、键盘导航和点击跳转到具体消息。
- 运行摘要：Quick/Council 消息已加入紧凑 summary，展示阶段成功/失败、fallback attempts、tokens、duration 和慢模型等信息。
- 错误恢复：失败/中断消息已加入 ErrorActionPanel，按错误类型提供 Retry、Continue、LLM Settings、Context Policy、Diagnostics 等操作入口。
- 富内容第一阶段：代码块支持语法高亮、行号、长代码折叠；表格已有 Markdown/CSV 复制；Mermaid/KaTeX/代码高亮已做缓存与视口懒渲染。
- 长回答折叠修复：最终答案只保留 `Stage3` 一层折叠控制，避免 `show full answer` 后仍被外层 `max-height` 截断。
- 搜索增强第二轮：搜索 API 返回 mode、tags、favorite、文件、失败、pinned、context excluded 等过滤元数据；Sidebar 和当前会话搜索条件已持久化到 localStorage。
- 搜索增强第三轮：Sidebar 搜索结果已按 conversation 分组，组内命中可展开；打开 message 命中会把 query 注入会话内搜索，memory 命中会滚动到 Context 区。
- 性能增强第二轮：`RichMarkdown` 增加 compact 内容缓存、Markdown/公式分段缓存，并在进入视口后通过 idle callback 切换完整渲染。
- 性能增强第三轮：长会话消息列表已加入轻量虚拟滚动试点，保留搜索跳转、turn 跳转和流式底部滚动兼容逻辑。
- 富内容第三轮：表格已支持搜索、排序、sticky header、CSV 下载；代码块已支持下载和 diff 专用样式；Mermaid 已支持 Preview、Copy SVG、Download SVG/PNG。
- 前端测试第三轮：已引入 Vitest + Testing Library + jsdom，覆盖 Sidebar 搜索分组/跳转和 RichMarkdown 表格/代码/Mermaid 基础交互。

### 0.2 已验证

- `python3 -m py_compile backend/main.py backend/storage.py` 通过。
- `uv run pytest tests/test_conversation_metadata_api.py`：4 passed。
- 会话相关回归：`test_conversation_fork_api.py`、`test_conversation_search_api.py`、`test_context_pin_api.py`、`test_context_policy_api.py`、`test_context_memory_api.py` 共 15 passed。
- `npm run lint` 通过。
- `npm run build` 通过。
- `bash -n deploy/native/start-backend.sh deploy/native/stop-backend.sh deploy/native/status.sh deploy/native/install.sh` 通过。
- 18080 smoke：前端返回最新构建产物；`/api/conversations` 返回新增元数据字段；临时会话元数据 PATCH 后已删除。
- `npm run lint` 和 `npm run build` 已在长回答折叠修复后重新通过。
- 18080 smoke 已确认返回最新前端构建资源，后端 `127.0.0.1:8001` API 响应正常。

### 0.3 当前仍未完成

- 搜索增强：基础搜索、跳转、命中高亮、状态持久化、常用过滤器、结果分组和组件测试已完成，仍可补更多审计类过滤器、保存搜索视图和更完整的批量结果导航。
- Retry with edit：后端和前端已有基础能力，但仍需要更完整的输入区编辑态、文件/图片编辑规则和重试前预览。
- Council 深化：已有 summary 和 model status，仍需补模型贡献解释、成本估算、部分失败归因和更清晰的成功/失败影响说明。
- 诊断产品化：已有 ErrorActionPanel，仍需补 provider 网络诊断、Context Policy 问题检测、API key/限流/禁用模型的更明确修复路径。
- 长消息体验：已有最终答案折叠、代码行号/折叠、表格搜索/排序/下载、Mermaid 放大/下载和公式源码复制；仍可补 Markdown heading outline、块级折叠和 XLSX 导出。
- 长会话性能：已有 RichMarkdown 视口懒渲染、Markdown 分段缓存、idle 完整渲染和消息列表虚拟滚动试点，仍缺真实 Markdown AST 缓存、虚拟滚动视觉 smoke 和 Mermaid/KaTeX 更细粒度缓存失效策略。

### 0.4 下一轮建议优先级

1. 工作区收敛：按功能拆分提交当前已完成改动，并保留验证证据。
2. 搜索增强：已补更多过滤器和搜索状态持久化；下一步补结果分组、批量导航和组件级测试。
3. 长会话性能：已补 Markdown 分段缓存和 idle 完整渲染；下一步引入消息虚拟滚动试点和真实 Markdown AST 缓存。
4. Council 深化：补模型贡献解释、成本/耗时统计、部分失败归因和更完整的 run 诊断。
5. 富内容高级操作：表格排序/下载、Mermaid 放大/下载、公式源码复制、diff 专用样式。

## 1. 文档目标

本文针对当前提到的一组体验与功能优化项，先逐项核对现有代码是否已经实现，再分析是否仍需要优化，最后按综合优先级整理成可执行的工程方案。

使用场景假设：

- 单用户本地/云服务器部署。
- 优先优化个人使用体验、上下文准确性和复杂对话效率。
- 暂不优先考虑多用户、跨设备同步、企业权限等生产级能力。

核对依据包括：

- 后端：`backend/storage.py`、`backend/main.py`、`backend/council.py`、`backend/openrouter.py`、`backend/provider_audit.py`。
- 前端：`frontend/src/components/Sidebar.jsx`、`ChatInterface.jsx`、`ConversationContext.jsx`、`RichMarkdown.jsx`。
- 测试：`tests/test_*` 中的 context、retry、resume、file、provider audit 相关用例。

## 2. 总体现状

当前系统已经不是普通的“消息数组 + API 调用”式 chatbox，而是具备本地会话状态、上下文审计、模型运行审计和富内容渲染的本地 chatbox。

已经实现的基础能力包括：

- Quick / Council 两种对话模式。
- 会话标题编辑。
- 会话时间分组折叠、收藏、归档、标签、置顶和标签筛选。
- 本地 conversation search API 与 context 面板中的历史搜索。
- Context preview / replay / policy / memory / pin / exclude。
- Retry、resume、fork。
- 文件和图片上传，支持拖拽和粘贴图片。
- Council 阶段进度、model status、失败模型展示。
- Stage1 / Stage2 默认折叠。
- Markdown、表格、代码高亮、LaTeX、Mermaid。
- 表格 Copy Markdown / Copy CSV。
- 代码复制，Mermaid 源码复制，数学公式渲染失败降级。
- Light / dark mode。
- Turn 导航和消息定位。
- RichMarkdown 视口懒渲染，减少长会话初始渲染压力。
- native 部署脚本的真实 PID 启动、停止和 API 健康检查。
- 本轮新增的 `context_payload_v2` 与 `provider_request_audit`，用于记录真实 provider-boundary 请求。

当前主要缺口集中在四类：

- 历史定位：搜索结果缺少左侧产品化入口、命中跳转、过滤器。
- 长内容操作：长消息折叠、内部目录、表格/代码/Mermaid 高级操作不足。
- 输入工作流：retry with edit、草稿自动保存、命令菜单、模板还不完整。
- 诊断解释：错误分类、操作建议、引用来源、Council 贡献解释还不够清晰。

## 3. 逐项核对与优化分析

### 3.1 会话搜索

当前实现状态：部分实现。

已有能力：

- 后端已有 conversation search。测试文件 `tests/test_conversation_search_api.py` 覆盖搜索 API。
- `ConversationContext.jsx` 中已有 “Search history” 面板，可以搜索 previous conversations and memory。
- 搜索结果展示 conversation title、source、role、message index、excerpt。
- 搜索结果可以保存为当前会话 memory。

当前缺口：

- 搜索入口在 context 面板里，不在左侧会话列表主入口，日常找会话不够直接。
- 搜索结果只能作为 memory 复用，不能点击跳转到具体 conversation/message。
- 没有当前会话内全文搜索。
- 没有过滤器：quick/council、有文件、有 pin、有失败 run、包含 memory、包含 provider audit 等。
- 命中片段可以展示 excerpt，但缺少命中词高亮。

是否需要优化：需要，优先级高。

原因：

- 单用户长期使用后，历史会话会快速增长。
- 当前系统的 turn/context audit 很强，但如果找不到历史 turn，审计能力利用率会下降。
- 会话搜索和会话内搜索是长对话工作流的基础入口。

建议实现：

- 左侧 Sidebar 增加搜索框，调用现有 search API。
- 搜索结果按 conversation 分组展示，显示命中片段和消息序号。
- 点击结果：
  - 如果命中非当前会话，先切换 conversation。
  - 再将 `targetMessageIndex` 传给 `ChatInterface` 高亮并滚动。
- 增加过滤器：
  - mode：quick / council / all。
  - has files。
  - has pinned。
  - has failed run。
  - source：message / memory / summary。
- 会话内搜索独立实现：只搜索当前 `conversation.messages`，前端即可先实现，不必等待后端。

### 3.2 Council 进度与过程展示

当前实现状态：部分实现。

已有能力：

- `ChatInterface.jsx` 中已有 `ModelStatusList`，展示每个模型的 status、first event、duration、error_type。
- Stage1 / Stage2 使用 `CollapsibleStage`，默认折叠。
- Stage1 / Stage2 / Stage3 loading block 会显示当前运行阶段。
- interrupted / failed / running assistant message 有状态 banner。
- 后端 `council.py` 会记录 stage 级事件，并保留 failed model 结果。
- `storage.py` 会把 stage1、stage2、stage3 转换为 turn runs。

当前缺口：

- 进度仍偏“状态列表”，缺少整体阶段进度条，例如 Stage1 3/5 done、1 failed。
- Stage3/fallback attempts 的可视解释还不够明确。
- 没有展示 Council 的成本/耗时汇总。
- 没有“只看最终答案 / 展开 Council details”的全局偏好。
- 没有模型贡献解释：最终答案采用了哪些模型观点，哪些被排除。

是否需要优化：需要，优先级中高。

原因：

- Council mode 是本项目的核心差异化功能。
- 用户需要理解多模型流程是否仍在工作、哪里失败、失败是否影响最终答案。
- 默认折叠已实现，下一步应提升“摘要级可理解性”。

建议实现：

- 在 assistant message 顶部增加 Council Run Summary：
  - Stage1：completed / failed / total。
  - Stage2：completed / failed / total。
  - Stage3：primary/fallback attempts。
  - total duration、first token latency。
- 默认只展示 Stage3 最终答案和 Run Summary，Stage1/Stage2 继续折叠。
- 在 ContextAuditDetails 中把 runs 聚合为阶段摘要，而不是只列 flat run rows。
- 后端可补充 `metadata.duration_summary`，前端也可先从 runs 中聚合。
- 模型贡献解释先不要求模型自动标注来源，第一阶段可展示：
  - Stage1 成功模型列表。
  - Stage2 排名。
  - Chairman 使用的最终模型和 fallback attempts。

### 3.3 错误恢复

当前实现状态：部分实现。

已有能力：

- `openrouter.py` 已将 provider 错误分类为 `timeout`、`http_status`、`network_error`、`invalid_response`、`disabled_model`、`unknown_error`。
- `query_model_with_fallbacks` 会记录 attempts。
- Quick、title、summarization、chairman 都有 fallback 相关能力。
- `ChatInterface.jsx` 对 interrupted / failed / running 显示 banner。
- assistant message 上有 Continue 和 Retry from scratch。
- Stage1 / Stage2 tabs 中会显示 failed 和错误摘要。
- Context audit 中显示 run status 和 error_type。

当前缺口：

- 用户看到的错误仍偏技术字段，没有统一成可操作的错误类型。
- 不同错误没有对应动作建议：
  - API key/config 错误 -> 打开 LLM Settings。
  - context 超限 -> 缩减上下文 / 打开 context policy。
  - 文件解析失败 -> 移除文件 / 重新上传。
  - provider 限流 -> 等待后重试 / 切换 fallback。
  - interrupted -> Continue。
- 缺少失败 run 诊断面板，把 attempts、latency、provider、model、error 摘要集中展示。
- 缺少“用 Quick 重新生成”“换模型后 retry”等动作。

是否需要优化：需要，优先级高。

原因：

- 本地部署经常遇到 API key、provider 网络、模型配置、文件解析问题。
- 错误恢复不产品化会导致用户需要读日志或猜测原因。
- 当前已有错误元数据，前端转译和动作按钮的投入较小，收益高。

建议实现：

- 新增前端 `ErrorActionPanel`：
  - 输入：assistant message、turnAudit、latest run。
  - 输出：错误分类、简短解释、建议动作按钮。
- 错误映射表：
  - `disabled_model` -> Open settings。
  - `timeout` / `network_error` -> Retry / Continue。
  - `http_status` 401/403 -> Open settings。
  - `http_status` 429 -> Retry later / fallback model。
  - context 相关错误 -> Open context policy / preview.
  - file parsing error -> remove file / upload again.
- 保留技术细节在 details 中，避免默认界面过重。

### 3.4 富内容能力

当前实现状态：部分实现。

已有能力：

- `RichMarkdown.jsx` 支持 Markdown、GFM table、代码块、highlight.js、KaTeX、Mermaid。
- 代码高亮动态加载 highlight.js 常用语言，并对大代码块降级。
- Mermaid 动态加载，渲染失败时显示错误和源码。
- KaTeX 动态加载，失败时显示源码。
- 表格已有 Copy Markdown 和 Copy CSV。
- 代码块已有 Copy code。
- Mermaid 目前可 Copy diagram 源码。
- 表格已经有横向滚动容器。

当前缺口：

- 表格没有 Download CSV / XLSX。
- 表格没有排序、搜索、sticky 表头。
- 代码块没有行号、长代码折叠、下载为文件、复制指定行。
- Diff code block 没有专用行级样式。
- Mermaid 没有大图折叠、放大查看、复制 SVG、下载 PNG/SVG。
- 数学公式没有复制源码按钮。
- 长内容和重组件没有视口懒渲染。

是否需要优化：需要，优先级中。

原因：

- 当前基础渲染已经可用，增强项主要提升复杂输出的操作效率。
- 对代码、表格、Mermaid 的增强会明显改善开发/分析场景。

建议实现顺序：

1. 轻量增强：
   - 表格 Download CSV。
   - 代码块行号和长代码折叠。
   - Mermaid 全屏/放大 modal。
   - Math block 复制公式源码。
2. 中等增强：
   - 表格 sticky header、搜索。
   - Diff 专用样式。
   - Mermaid copy SVG / download SVG。
3. 重型增强：
   - `@tanstack/react-table` 管理大表。
   - SheetJS 导出 XLSX。
   - Shiki 替代 highlight.js。

### 3.5 会话重命名、时间分组、收藏、标签、归档、置顶

当前实现状态：基础版已实现。

已有能力：

- `Sidebar.jsx` 有 inline title edit，支持 Enter 保存、Esc 取消。
- 侧边栏显示 message count。
- 后端 `PATCH /api/conversations/{conversation_id}` 已支持 `title`、`favorite`、`archived`、`pinned`、`tags`。
- conversation JSON 会持久化 `favorite`、`archived`、`pinned`、`tags`、`updated_at`。
- 左侧列表默认显示 Active 会话，可切换 Archived 视图。
- 支持收藏筛选、标签筛选、标签编辑。
- 置顶会话在未归档视图中进入 Pinned 独立分组。
- 时间分组与分组折叠已实现。

当前缺口：

- 标签还没有颜色、批量管理、重命名或删除入口。
- 收藏/归档/置顶操作还没有 undo toast。
- 没有按 mode、文件、失败状态显示 badges。
- 分支会话仍只作为普通会话展示，没有分支树。

是否需要优化：继续优化，优先级从“基础能力”降为中。

下一步建议：

- P1：给 Archive/Restore、Pin、Favorite 增加 toast 和撤销。
- P1：显示 mode/file/failed-run badges。
- P2：标签颜色、标签管理面板。
- P2：分支树、标签颜色、自定义项目分组。

### 3.6 会话内全文搜索和跳转

当前实现状态：未完整实现。

已有能力：

- Turn navigator 可以滚动到 turn。
- `ChatInterface` 支持高亮 message index。
- Context preview 支持 jump to message。

当前缺口：

- 没有当前 conversation 内搜索框。
- 没有命中列表。
- 没有上一个/下一个命中跳转。
- 没有命中词高亮。
- 不能限定搜索范围：用户消息、助手消息、代码块、文件名、context audit。

是否需要优化：需要，优先级高。

建议实现：

- 在 ChatInterface 顶部或浮动工具栏增加 search input。
- 前端本地遍历 `conversation.messages`：
  - 文本内容：`contentToText`。
  - assistant stage3 response。
  - stage1/stage2 可选。
  - files metadata。
- 维护 `matches[]`，包含 `messageIndex`、`snippet`、`matchStart`。
- 使用现有 `scrollToMessage` / anchor map 跳转。
- 给当前命中 message 加高亮；后续再做词级高亮。

### 3.7 编辑并重发用户消息，支持 retry with edit

当前实现状态：部分实现。

已有能力：

- 用户消息上已有 Edit 按钮。
- 点击 Edit 会把该消息内容放回输入框。
- 后端已有 retry API，能对指定 user message 截断后续并重跑。

当前缺口：

- 当前 Edit 只是填充输入框，不会绑定“这次发送是修改历史消息”。
- 发送后会作为新消息，而不是替换原 user message 并 truncate 后续。
- retry API 目前没有接收 edited content。
- 多模态消息 edit 时文件/图片附件的保留、删除、替换规则未定义。

是否需要优化：需要，优先级高。

建议实现：

- 前端新增 `editingMessageIndex` 状态。
- 用户点击 Edit 后，输入区显示“Editing message #N”，并提供 Cancel edit。
- 发送时调用新 API：
  - `POST /api/conversations/{id}/messages/{message_index}/retry`
  - body 增加 `content`、`mode`、可选 `files`。
- 后端行为：
  - 替换原 user message content。
  - 截断该 user message 后续消息和 turns。
  - 重建 context package。
  - 重新运行 quick/council。
- 对文件/图片先支持文本编辑，不改变附件；后续再支持附件编辑。

### 3.8 输入草稿自动保存

当前实现状态：部分实现。

已有能力：

- `App.jsx` 有 `draftToRestore`，主要用于 stop query 后恢复 in-flight draft。
- `ChatInterface.jsx` 接收 draftToRestore 并回填输入框。

当前缺口：

- 没有按 conversation 自动保存未发送草稿。
- 切换会话后未发送输入不会持久保留。
- 页面刷新后草稿不会恢复。
- 文件队列草稿和文本草稿没有统一管理。

是否需要优化：需要，优先级中高。

建议实现：

- localStorage key：`llm-council:draft:{conversationId}`。
- 保存字段：
  - text。
  - mode preference。
  - updated_at。
  - file queue ids 或 pending file metadata。
- 输入 debounce 300-500ms 保存。
- 成功发送后清除草稿。
- 切换会话时恢复对应草稿。
- 文件草稿先只保存已进入 file queue 的 metadata，不保存 raw File 对象。

### 3.9 `/` 命令菜单和 prompt 模板

当前实现状态：未实现。

已有能力：

- 输入区支持 Enter / Ctrl+Enter / Shift+Enter。
- 支持 Quick / Council 两个按钮。
- 支持 context preview。

当前缺口：

- 没有 `/` 命令菜单。
- 没有 prompt 模板。
- 没有模板变量填充。

是否需要优化：中优先级。

建议实现：

- 输入框检测 `/` 开头弹出 command palette。
- 初始命令：
  - `/quick` 切换或发送 quick。
  - `/council` 切换或发送 council。
  - `/preview` 打开 context preview。
  - `/memory` 保存当前输入为 memory。
  - `/clear` 清空输入。
  - `/template` 插入模板。
- 模板先存 localStorage：
  - name。
  - body。
  - tags。
  - variables。
- 后续可放入 settings 或 conversation JSON。

### 3.10 拖拽/粘贴上传、上传/解析进度

当前实现状态：拖拽/粘贴已实现，进度未完整实现。

已有能力：

- `ChatInterface.jsx` 支持 drag over / drop。
- `ChatInterface.jsx` 支持 paste image。
- `FileQueue` 展示待上传文件。
- `utils/fileUtils.js` 做前端文件校验。
- 后端支持文件处理和文件队列。

当前缺口：

- 没有细粒度上传进度。
- 文件解析进度不可见。
- 大文件只有成功/失败，没有“解析中、部分进入上下文、被预算裁剪”的状态。
- 发送后文件是否进入本轮 context 的反馈还不够明确。

是否需要优化：需要，优先级中。

建议实现：

- 前端 file queue 增加 status：
  - queued。
  - uploading。
  - parsing。
  - ready。
  - failed。
  - included / omitted。
- 后端文件发送 endpoint 可返回每个文件的 parse summary。
- 大文件处理可先同步返回简单状态；后续再做后台任务/SSE。
- Context preview/files 中展示每个文件预计占用预算和裁剪情况。

### 3.11 长消息折叠和消息内部目录

当前实现状态：Council stage 折叠已实现，长消息/目录未实现。

已有能力：

- Stage1 / Stage2 默认折叠。
- turn navigator 支持按 turn 跳转。
- RichMarkdown 渲染 heading。

当前缺口：

- 单条 assistant 最终回答过长时没有默认折叠。
- 代码块、表格、Mermaid 没有按块折叠策略。
- 没有从 Markdown heading 自动生成目录。
- 不能跳转到消息内部 heading。

是否需要优化：需要，优先级中高。

建议实现：

- `MessageBody` 增加 max-height collapsed 模式，例如超过 1200px 显示 “Expand full answer”。
- RichMarkdown 在渲染前提取 heading：
  - text。
  - level。
  - anchor id。
- 在消息工具栏增加 “Outline”。
- 点击 outline item 滚动到对应 heading。
- 对大型代码块默认折叠；Mermaid 大图默认显示预览。

### 3.12 回答引用来源、文件片段引用、Council 贡献来源

当前实现状态：部分实现上下文来源审计，未实现回答内引用。

已有能力：

- context audit 能展示本次上下文来源统计。
- `provider_request_audit` 能记录真实 provider payload source_map。
- 文件 metadata 和 attachment_ref 已持久化。
- Stage1/Stage2/Stage3 结果和 runs 已保留。

当前缺口：

- 模型回答正文里没有结构化 citation。
- 文件问答没有显示引用 chunk、页码、行号。
- Council 最终答案没有标注来自哪个模型观点。
- source_map 是审计数据，不等于回答内引用。

是否需要优化：中长期需要，优先级中。

建议实现：

- 文件解析阶段产生 chunk id、page/line metadata。
- context package 中给文件 chunk 加 source id。
- prompt 要求模型用 `[file:chunk_id]` 或结构化引用。
- 前端把 citation 渲染为可点击 chip，点击显示文件片段。
- Council 贡献来源先做非 LLM 版本：
  - 展示 Stage2 排名。
  - 展示主席模型。
  - 展示最终回答可追溯的 provider audit。
- 后续再做 structured synthesis，让主席输出 `claims[]` + `source_models[]`。

### 3.13 表格增强

当前实现状态：Copy Markdown / Copy CSV 已实现；下载、排序、搜索未实现。

优化价值：

- 对数据分析类回答很有用。
- CSV 下载比复制更适合大表格。
- 排序/搜索会增加组件复杂度，需控制范围。

建议实现：

- P1：
  - Download CSV。
  - sticky table header。
  - 大表默认限制高度并滚动。
- P2：
  - 表格搜索。
  - 简单列排序。
- P3：
  - SheetJS 下载 XLSX。
  - `@tanstack/react-table` 替换纯 Markdown table wrapper。

### 3.14 代码块增强

当前实现状态：语法高亮和复制已实现；行号、折叠、下载、diff 样式未实现。

优化价值：

- 对代码生成、代码审查、错误日志分析很重要。
- 行号和折叠是低成本高收益。

建议实现：

- P1：
  - 行号。
  - 长代码块折叠。
  - Download file，文件名根据 language 推断扩展名。
- P2：
  - Diff 专用样式。
  - 复制指定行或选中行。
- P3：
  - Shiki 主题。
  - Monaco 只用于可编辑代码，不作为普通渲染默认依赖。

### 3.15 Mermaid 增强

当前实现状态：基础渲染、错误降级、源码复制已实现；放大/下载未实现。

优化价值：

- Mermaid 图经常超出消息宽度。
- 放大查看和下载 SVG 是实际使用中的高频需求。

建议实现：

- P1：
  - Mermaid block 增加 Open large。
  - Modal 中展示 SVG，支持 pan/zoom 的简化版本。
  - Copy SVG。
- P2：
  - Download SVG。
  - Download PNG，通过 canvas 转换或浏览器原生 SVG blob。
- P3：
  - 大图默认折叠。
  - SVG 缓存。
  - requestIdleCallback 延迟渲染。

### 3.16 前端性能：虚拟滚动、缓存和懒渲染

当前实现状态：已实现视口懒渲染基础版和消息列表虚拟滚动试点，Markdown AST 缓存未实现。

已有能力：

- RichMarkdown 对 highlight、Mermaid 使用动态 import。
- highlight 有长度上限，大代码块降级。
- Mermaid 有基于 code/mode 的缓存 key。
- KaTeX 动态加载。
- ChatInterface 使用 memo 和 turn anchor。

当前缺口：

- 消息列表已有轻量虚拟滚动试点，超过阈值时按 message group 窗口化渲染。
- Mermaid/KaTeX/代码高亮已通过 `RichMarkdown` 的视口懒渲染延后完整渲染；但 MermaidBlock/MathBlock 还没有更细粒度的块级缓存和 idle 调度。
- Markdown AST 没有缓存。
- 长消息中多个重组件同时渲染时仍可能卡顿。

是否需要优化：需要，但应排在核心交互之后。

建议实现：

- P2：
  - 使用 IntersectionObserver 包装 MermaidBlock / MathBlock，进入视口再渲染。
  - replay panel 展开后再加载详细 payload。
  - 长代码块默认折叠，减少初始 DOM。
- P3：
  - `@tanstack/react-virtual` 做消息列表虚拟滚动。
  - Markdown AST 缓存。
  - Mermaid SVG cache。

## 4. 综合优先级排序

排序依据：

- 对日常单用户使用体验的提升。
- 与当前已实现能力的耦合程度。
- 实现复杂度和风险。
- 是否能提升上下文准确性、长对话定位和失败恢复效率。

### P0：立即值得实现

1. 会话内全文搜索和跳转。
   - 当前已有 message anchor 和高亮能力，实现成本低。
   - 直接解决长对话找内容问题。

2. 左侧会话搜索产品化。
   - 复用后端 search API。
   - 增加命中片段、点击跳转、基础过滤。

3. Retry with edit。
   - 当前 Edit 和 retry 都已分别存在，但没有串起来。
   - 这是 chatbox 高频操作。

4. 错误恢复面板。
   - 后端已有 error_type/attempts/fallback metadata。
   - 前端补用户可见分类和动作按钮即可产生明显价值。

5. Council Run Summary。
   - 当前有 modelStatus/runs。
   - 聚合展示阶段完成数、失败数、耗时，让 council mode 更可解释。

### P1：下一阶段实现

6. 输入草稿自动保存。
   - localStorage 即可完成第一版。
   - 提升切换会话和刷新页面的可靠性。

7. 长消息折叠和消息内部目录。
   - 解决 council/代码/长报告阅读效率问题。

8. 会话时间分组、收藏、归档、标签、置顶。
   - 状态：基础版已完成。
   - 后续转为增强项：undo toast、mode/file/failed badges、标签颜色、分支树。

9. 文件解析状态和文件上下文反馈。
   - 拖拽/粘贴已实现，下一步补状态可见性。

10. 表格 Download CSV、sticky 表头。
    - 当前已能 Copy CSV，下载 CSV 是自然扩展。

11. 代码块行号、长代码折叠。
    - 低成本提升代码阅读体验。

12. Mermaid 放大查看和 Copy SVG。
    - 解决图太大和复用问题。

### P2：增强型能力

13. `/` 命令菜单和 prompt 模板。
    - 对高频用户有帮助，但不是基础可靠性问题。

14. 表格搜索、排序。
    - 对数据类回答有价值，但复杂度高于 CSV 下载。

15. 代码块下载文件、diff 专用样式。
    - 开发场景有价值。

16. Math 公式源码复制。
    - 小功能，可和 RichMarkdown 工具栏一起做。

17. 回答引用来源、文件片段引用。
    - 需要后端 chunk/source id 和 prompt 配合，工程面更大。

18. Council 贡献来源解释。
    - 需要 structured output 或额外归因逻辑，先做 run summary 和排名展示。

### P3：性能和高级架构优化

19. Mermaid/KaTeX/Markdown 视口懒渲染。
    - 状态：RichMarkdown 层基础版已完成。
    - 后续增强：块级 idle 渲染、Mermaid SVG cache、虚拟滚动联动。

20. Markdown AST 缓存。
    - 需要评估缓存 invalidation。

21. 前端虚拟滚动。
    - 长会话最终需要，但会影响 scroll anchor、turn navigation、highlight、Mermaid render lifecycle，需谨慎。

22. 表格 XLSX 导出和 `@tanstack/react-table`。
    - 重依赖，等轻量表格能力到瓶颈后再引入。

## 5. 建议工程拆分

### Phase 1：搜索、编辑重试、错误恢复

目标：

- 让用户能找到、修改、恢复关键 turn。

任务：

- 当前会话内搜索。
- Sidebar 全局会话搜索。
- retry with edit。
- ErrorActionPanel。
- Council Run Summary。

验证：

- 前端组件单测或 e2e smoke。
- 后端 retry API 新增 edited content 测试。
- 搜索跳转测试：命中结果能定位 message index。

### Phase 2：长内容和输入可靠性

进度：会话组织基础版、RichMarkdown 视口懒渲染、草稿自动保存、长消息折叠、代码行号、表格下载/搜索/排序、Mermaid 下载/预览和组件测试已完成。

目标：

- 让长回答、长代码、长会话更易阅读。
- 避免输入草稿丢失。

任务：

- 草稿自动保存。
- 长消息折叠。
- Markdown heading outline。
- 代码行号和长代码折叠。
- 表格 Download CSV 和 sticky header。

验证：

- RichMarkdown table/code 行为测试。
- 手动视觉检查长消息、宽表、长代码。
- localStorage draft 恢复测试。

### Phase 3：文件与引用解释

目标：

- 让文件问答可追溯。

任务：

- 文件解析状态。
- context preview 显示文件预算与裁剪。
- 文件 chunk source id。
- 回答 citation 渲染。

验证：

- 文件上传 API 返回 parse summary。
- context package 包含 chunk source_map。
- replay 能显示引用来源。

### Phase 4：富内容高级操作和性能

进度：已完成 RichMarkdown 视口懒渲染基础版、高级富内容操作基础版和长会话虚拟滚动试点。

目标：

- 提升复杂内容复用和长会话性能。

任务：

- Mermaid modal、copy/download SVG。
- 表格搜索/排序。
- 代码 download/diff style。
- IntersectionObserver 懒渲染。
- 虚拟滚动评估和试点。

验证：

- Playwright 截图/交互 smoke。
- 长会话性能对比。
- 大 Mermaid/KaTeX/表格页面无明显卡顿。

## 6. 推荐先做的最小闭环

如果下一轮只做一个小闭环，建议选择：

1. 会话内全文搜索。
2. Retry with edit。
3. ErrorActionPanel。
4. Council Run Summary。

这四项都能复用现有数据结构，不需要引入新依赖，也最贴近当前使用痛点：长对话定位、问题修正、失败恢复和 council mode 可理解性。

