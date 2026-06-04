# Chatbox 下一轮任务 TODO

更新时间：2026-06-04

本文记录当前工程优化的下一轮重点任务。目标是优先提升单用户本地部署场景下的定位效率、Council 可解释性、错误恢复效率和长内容阅读体验。

## 总体优先级

1. 会话内全文搜索和跳转。
2. 左侧会话搜索产品化。
3. Council Run Summary。
4. ErrorActionPanel。
5. 长消息折叠与代码行号。

优先顺序依据：日常使用频率、与现有能力耦合程度、实现复杂度、对长对话效率和问题恢复的收益。

## 2026-06-04 实施进度

本轮已完成五项 P0/P1 功能的第一阶段工程落地，并已通过本地验证：

- 前端：`npm run lint` 通过。
- 前端：`npm run build` 通过，已生成新的 `frontend/dist`。
- 后端：`python -m py_compile backend/main.py backend/storage.py` 通过。
- 后端关键回归：`pytest tests/test_conversation_metadata_api.py tests/test_conversation_search_api.py tests/test_quick_stream.py tests/test_council_failures.py tests/test_resume_stream.py -q`，18 passed。

本轮实现文件：

- `frontend/src/App.jsx`：新增侧栏搜索结果到聊天消息的跨组件跳转状态。
- `frontend/src/components/Sidebar.jsx` / `Sidebar.css`：新增全局会话搜索框、debounce、结果片段、来源标识、筛选联动和点击跳转。
- `frontend/src/components/ChatInterface.jsx` / `ChatInterface.css`：扩展会话内搜索范围、接收外部 message jump、Quick/Council Summary、ErrorActionPanel 技术细节折叠、长 assistant 回答折叠。
- `frontend/src/components/RichMarkdown.jsx` / `RichMarkdown.css`：新增代码行号、长代码折叠/展开，Copy code 保持复制原始代码。

补充进度：搜索命中高亮和 Sidebar 键盘导航已补齐基础版；长回答折叠已修复双层 `max-height` 冲突，`show full answer` 现在只由 `Stage3` 单层控制。第二轮已补齐 Sidebar 搜索状态持久化、当前会话搜索状态持久化、mode/files/failed/pinned/excluded 搜索过滤器、搜索 API 元数据字段，以及 RichMarkdown compact/分段缓存和 idle 完整渲染。剩余后续增强仍按本文各节的“后续增强/非目标”推进，例如搜索结果分组、消息虚拟滚动、表格排序/下载、Mermaid 下载、diff 专用样式和组件级测试。

## 1. 会话内全文搜索和跳转

优先级：P0

当前状态：已完成第一版落地。聊天区顶部搜索会本地遍历当前 `conversation.messages`，支持用户消息、assistant 最终回答、Stage1/Stage2 内容、附件名和 metadata；Prev/Next/当前片段点击都会复用 message anchor 滚动并高亮，切换会话会重置搜索状态。

### 目标

让用户在当前长会话中快速定位历史内容，并能在多个命中之间跳转。当前已有 turn 导航、message anchor 和消息高亮基础，因此这是下一轮性价比最高的任务。

### 当前基础

- `ChatInterface` 已有按 turn/message 定位的机制。
- 当前会话数据已完整保存在 `conversation.messages`。
- assistant 消息中已有 stage3/final response、stage1、stage2 等结构化字段。

### 实现范围

- 在聊天区域顶部或浮动工具栏增加当前会话搜索入口。
- 前端本地遍历当前 `conversation.messages`，先不依赖后端。
- 支持搜索范围：
  - 用户消息文本。
  - assistant 最终回答。
  - 文件名和文件 metadata。
  - 可选：stage1 / stage2 / council details。
- 生成 `matches[]`：
  - `messageIndex`。
  - `role`。
  - `snippet`。
  - `matchCount`。
- 支持上一个/下一个命中跳转。
- 跳转时复用现有 message anchor，并短暂高亮目标消息。

### 非目标

- 第一版不做后端索引。
- 第一版不做复杂正则搜索。
- 第一版不做全文分词和语义搜索。

### 验收标准

- 输入关键词后能列出当前会话命中数量。
- 点击或按上下按钮能跳转到对应消息。
- 当前命中消息有明显但不干扰阅读的高亮。
- 切换会话时搜索状态正确重置。
- 空搜索、无命中、超长会话均不报错。

### 测试建议

- 前端构建和 lint。
- 手工 smoke：长会话中搜索用户消息、assistant 最终回答、文件名。
- 可补组件级测试：给定 messages，搜索函数返回正确 `messageIndex/snippet`。

## 2. 左侧会话搜索产品化

优先级：P0

当前状态：已完成第一版落地。Sidebar 新增历史会话搜索框，250ms debounce 后调用现有 `/api/conversations/search`；结果显示会话标题、来源/角色/消息序号和 excerpt；点击结果可打开目标会话并跳转到 `message_index`。搜索结果会按当前 Active/Archived、Favorite only、tag 过滤器裁剪，API 失败时显示轻量错误提示。

### 目标

把已有后端 conversation search 从 context 面板能力提升为日常找会话入口。用户应能在左侧直接搜索历史会话，看到命中片段，并点击跳转到具体会话和消息。

### 当前基础

- 后端已有 `/api/conversations/search`。
- `tests/test_conversation_search_api.py` 已覆盖基础搜索。
- `ConversationContext.jsx` 已能展示历史搜索结果并保存为 memory。
- Sidebar 已有会话分组、收藏、标签、归档、置顶筛选。

### 实现范围

- Sidebar 增加搜索框。
- 输入 debounce 后调用现有 search API。
- 搜索结果显示：
  - 会话标题。
  - source 类型：message / memory / summary 等。
  - role。
  - message index。
  - excerpt 命中片段。
- 点击结果：
  - 如果不是当前会话，先切换到目标 conversation。
  - 再把 `targetMessageIndex` 传给聊天区定位并高亮。
- 支持基础过滤：
  - Active / Archived 复用现有视图。
  - Favorite only 复用现有筛选。
  - tag 复用现有筛选。

### 后续增强

当前第二轮已完成：命中词高亮、mode 过滤、has file / pinned / failed / context excluded 过滤、键盘导航、搜索条件持久化。

剩余后续增强：

- 搜索结果按会话分组。
- has provider audit / has memory / has image 等更细筛选。
- 搜索状态导出或保存为快捷视图。
- 组件级测试。

### 非目标

- 第一版不做语义检索。
- 第一版不做跨设备索引。
- 第一版不引入外部搜索引擎。

### 验收标准

- 左侧输入关键词能返回搜索结果。
- 点击搜索结果能打开目标会话。
- 若结果包含 message index，聊天区能滚动到对应消息。
- 搜索不影响已有 Active/Archived、收藏、标签筛选的基本使用。
- API 失败时有轻量错误提示，不导致 Sidebar 崩溃。

### 测试建议

- 后端沿用并扩展 search API 测试，目前已覆盖搜索结果 metadata：mode、tags、favorite、conversation_pinned、has_files。
- 前端 smoke：搜索标题、用户消息、assistant 回答、memory。
- 构造 archived/favorite/tag 会话，检查筛选与搜索结果组合行为。

## 3. Council Run Summary

优先级：P1

当前状态：已完成第一版落地。assistant message 顶部会显示 Council summary 或 Quick summary；Council 模式汇总 Stage1/Stage2 成功/失败数、chair model、fallback attempts、tokens、slowest duration 和模型失败数量；Quick 模式显示 quick 状态、模型、fallback/tokens/duration。Stage1/Stage2 仍默认折叠。

### 目标

让 council mode 的执行状态更容易理解。用户默认不需要展开 Stage1/Stage2 细节，也能知道本轮多模型流程是否成功、失败了几个模型、最终是否用了 fallback、耗时多少。

### 当前基础

- `ModelStatusList` 已展示每个模型的 status、duration、first event、error_type。
- Stage1 / Stage2 已默认折叠。
- assistant message 中已有 `modelStatus`、`metadata`、stage results。
- turn audit 中已有 runs。
- 后端 fallback attempts 已有结构化记录。

### 实现范围

- 在 assistant message 顶部增加 Council Run Summary 卡片或紧凑状态条。
- 汇总内容：
  - Stage1：成功数 / 失败数 / 总数。
  - Stage2：成功数 / 失败数 / 总数。
  - Stage3：最终模型、是否 fallback、attempts 数。
  - 总耗时：优先从 metadata/runs 聚合；缺失时显示 unknown。
  - 失败摘要：最多显示 1-2 个主要 error_type。
- 默认展示摘要，Stage1/Stage2 继续折叠。
- 对 quick mode 显示轻量 Quick Run Summary。

### 后端增强选项

第一版可纯前端聚合；如果前端聚合逻辑过散，再补后端 `duration_summary` 或 `run_summary` 字段。

### 非目标

- 第一版不做模型观点自动归因。
- 第一版不要求 chairman 输出 structured claims。
- 第一版不展示 token 成本明细，除非 provider usage 已稳定可用。

### 验收标准

- 正常 council 回答显示成功阶段摘要。
- 部分模型失败但最终成功时，摘要明确显示“部分失败，不影响最终完成”。
- Stage3 fallback 时能显示 fallback attempts。
- quick mode 不显示 council 三阶段摘要，而显示 quick run 状态。
- 中断、失败、恢复中的消息状态不被摘要覆盖。

### 测试建议

- 用已有 stage model status 测试数据补前端聚合函数测试。
- 手工 smoke：正常 council、部分模型失败、Stage3 fallback、interrupted/resume。

## 4. ErrorActionPanel

优先级：P1

当前状态：已完成第一版落地。failed/interrupted assistant message 会显示恢复面板，按 `disabled_model`、401/403、429、timeout/network、all_stage1_models_failed、invalid_response 等类型给出不同说明和动作；Retry、Continue 复用现有 handler，LLM Settings 可直接打开现有设置弹窗，技术细节默认折叠。

### 目标

把当前偏技术化的错误字段转成用户可理解、可操作的恢复建议。用户遇到失败时，应能直接选择 Retry、Continue、Open Settings、Open Context Policy 等动作，而不是读日志或猜测。

### 当前基础

- 后端 `openrouter.py` 已有错误分类：`timeout`、`http_status`、`network_error`、`invalid_response`、`disabled_model`、`unknown_error`。
- fallback attempts 已记录。
- assistant message 已有 interrupted / failed / running banner。
- UI 已有 Continue 和 Retry from scratch。
- LLM Settings modal 已存在。
- Context Policy/Preview 已存在。

### 实现范围

- 新增前端 `ErrorActionPanel` 组件。
- 输入：assistant message、turn audit、model status、metadata attempts。
- 输出：
  - 用户可读错误类型。
  - 简短原因说明。
  - 建议操作按钮。
  - 可展开技术细节。
- 错误映射：
  - `disabled_model`：Open LLM Settings。
  - `http_status` 401/403：Open LLM Settings。
  - `http_status` 429：Retry later / use fallback。
  - `timeout`：Retry / Continue。
  - `network_error`：Retry / check provider network。
  - `invalid_response`：Retry / switch model。
  - context 超限类错误：Open Context Policy / Preview。
  - interrupted：Continue / Retry from scratch。

### 非目标

- 第一版不自动修改模型配置。
- 第一版不自动切换 provider，除非已有 fallback 配置。
- 第一版不暴露完整 provider payload，仍遵循现有 redaction/audit 策略。

### 验收标准

- failed assistant message 显示错误恢复面板。
- 不同 error_type 显示不同建议动作。
- Open Settings 能打开现有 LLM Settings modal。
- Retry / Continue 能复用现有 handler。
- 技术细节默认折叠。

### 测试建议

- 组件级测试错误映射表。
- 手工 smoke：disabled model、timeout/network error、interrupted resume。
- 确认错误面板不会遮挡最终成功回答。

## 5. 长消息折叠与代码行号

优先级：P1

当前状态：已完成第一版落地。长 assistant 最终回答完成后默认折叠并提供展开/收起；折叠区域保留 Markdown、表格、公式、Mermaid 等 RichMarkdown 渲染结果。代码块按行渲染行号，超过 120 行时默认展示前 80 行并可展开，Copy code 仍复制原始代码，不包含行号。

### 目标

改善长回答、长代码、复杂报告的阅读体验。当前已有 turn 导航和 RichMarkdown 懒渲染，但单条消息过长时仍需要更好的折叠、定位和代码阅读能力。

### 当前基础

- `RichMarkdown` 已支持 Markdown、表格、代码高亮、LaTeX、Mermaid。
- 代码块已有 Copy code。
- 大代码块已有高亮长度上限，过大时降级普通文本。
- Stage1 / Stage2 已折叠。
- turn navigator 已支持按 turn 跳转。

### 实现范围

第一阶段：长消息折叠。

- 对 assistant 最终回答设置高度阈值，例如 1200px。
- 超过阈值时默认折叠，显示渐隐遮罩和 `Expand full answer`。
- 展开后提供 `Collapse`。
- 折叠状态按 message index 保存在前端状态中。
- 正在 streaming 的消息不默认折叠，完成后再判断。

第二阶段：代码行号和长代码折叠。

- `CodeBlock` 增加行号列。
- 长代码块超过阈值时默认折叠，例如超过 120 行或高度超过 600px。
- 保留 Copy code。
- text/plain 代码块不强制高亮，但仍可显示行号。
- diff 代码块先只显示行号，后续再做 diff 专用颜色。

### 后续增强

- Markdown heading outline。
- Mermaid Open Large / Copy SVG / Download SVG。
- 表格 sticky header / Download CSV。
- 代码 Download file。

### 非目标

- 第一版不做虚拟滚动。
- 第一版不引入 Monaco。
- 第一版不替换 highlight.js。
- 第一版不做复杂代码选行复制。

### 验收标准

- 长 assistant 回答不会一次占满整个滚动体验。
- 展开/折叠不丢失 Markdown、表格、公式、Mermaid 渲染结果。
- 长代码块显示行号，并可折叠/展开。
- Copy code 仍复制原始代码，不包含行号。
- 构建和 lint 通过。

### 测试建议

- 手工 smoke：长 Markdown、长代码、Mermaid、表格、公式混合消息。
- 前端构建和 lint。
- 可补 `CodeBlock` 行号渲染的组件测试。

## 执行建议

### 推荐拆分

第一批：搜索定位

- 会话内全文搜索和跳转。
- 左侧会话搜索产品化。

原因：这两项共享 message index、scroll/highlight、搜索结果模型，适合一起设计。

第二批：诊断解释

- Council Run Summary。
- ErrorActionPanel。

原因：这两项共享 run/model status/error metadata，适合一起抽取聚合函数和展示组件。

第三批：长内容阅读

- 长消息折叠。
- 代码行号和长代码折叠。

原因：这两项都在消息渲染/RichMarkdown 层，完成后再考虑 Mermaid 和表格高级操作。

### 风险点

- 搜索跳转需要和现有 turn navigator、message anchor、归档会话切换协同。
- Council summary 需要兼容 quick/council/resume/retry/interrupted 多种 message shape。
- ErrorActionPanel 不能泄露 provider payload 或密钥相关信息。
- 长消息折叠不能破坏 streaming 更新和 Markdown 懒渲染。

### 完成定义

一轮任务完成时应满足：

- 对应功能可在 18080 当前部署入口使用。
- 前端 lint 和 build 通过。
- 后端涉及 API 变更时有 pytest 覆盖。
- 至少完成一组真实会话 smoke test。
- docs 中同步更新已完成/待完成状态。
