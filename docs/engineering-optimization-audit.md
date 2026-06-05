# LLM Council Chatbox 工程优化审计与落地方案

更新时间：2026-06-05

## 1. 当前功能要点

当前项目已经从原始多模型 Council demo 扩展成单用户本地/云服务器部署的 Chatbox：

- 对话模式：支持 Council 三阶段工作流和 Quick 单模型低延迟回复，二者可在同一会话中穿插使用。
- 模型配置：支持 OpenAI-compatible provider、运行时 LLM 设置、模型状态、fallback、timeout、错误分类和诊断入口。
- 会话管理：支持本地 JSON 会话持久化、重命名、删除、收藏、置顶、归档、标签、标签颜色、保存视图、批量操作、导出、AI 标题建议。
- 搜索导航：支持左侧全局历史搜索、命中片段、按会话分组、过滤器、键盘导航、点击跳转；会话内支持全文搜索、Prev/Next、turn 跳转、top/bottom。
- 上下文管理：支持 context audit、历史策略、summary cache、pinned/excluded message、context replay/rebuild。
- 文件模式：支持上传、拖拽/粘贴、文件元数据渲染和搜索。
- 富内容渲染：RichMarkdown 支持 GFM、表格搜索/排序/CSV、代码高亮/行号/折叠/下载/diff、KaTeX、Mermaid 预览和 SVG/PNG 下载。
- 长会话体验：已有消息虚拟化试点、RichMarkdown 视口懒渲染、compact 渲染、草稿保存、长消息预览折叠。
- 验收：已有 backend pytest、frontend Vitest、Playwright deployed smoke 测试入口。

## 2. 关键实现方案检查

### 2.1 前端渲染路径

- `ChatInterface.jsx` 持有当前会话、输入框、搜索、turn 导航、虚拟窗口和消息锚点。
- `RichMarkdown.jsx` 负责富内容解析、动态加载 highlight.js/KaTeX/Mermaid、表格增强和 block 级工具栏。
- `Stage1/Stage2/Stage3` 负责 Council 阶段展示，复制能力已收敛到共享 `CopyButton`。

判断：前端功能聚合度仍高，但近期已经把 CopyButton 和 conversationUtils 拆出，减少了部分重复。下一步最大的结构性收益是继续把 ChatInterface 的搜索/虚拟滚动/输入管理拆成 hooks，而不是继续扩大单组件。

### 2.2 本地状态和 API 边界

- Provider API 本身无状态，项目通过后端 JSON 会话、summary cache、context policy 和 message metadata 管理历史。
- 前端 localStorage 只保存 UI 偏好：theme、sidebar width、sidebar filters、conversation search state、draft。
- 会话组织元数据由后端管理，避免把真实业务状态仅放在浏览器。

判断：这个边界符合当前单用户部署目标。风险不是“没有中心数据库”，而是长会话 JSON 和前端渲染缓存需要体量控制。

## 3. 工程风险排名

| 优先级 | 风险 | 影响 | 当前状态 | 本轮处理 |
| --- | --- | --- | --- | --- |
| P0 | RichMarkdown 模块级缓存按条数限制，但 cache key 包含完整内容 | 长代码/长 Mermaid/长公式会让 key 和 value 双重持有大字符串，长会话使用中可能内存膨胀 | 已有 entry-count LRU，但缺少体量预算 | 已改为 content fingerprint key，并加入字符预算 LRU |
| P0 | 会话详情加载没有竞态保护 | 快速切换会话或搜索跳转时，旧请求可能晚返回并覆盖当前会话 | `loadConversationDetails` 直接 set state | 已加入 request sequence，只允许最新请求落地 |
| P1 | 复制反馈计时器未统一清理 | 组件卸载后仍可能执行短生命周期 setState 回调，长会话频繁折叠/虚拟卸载时噪声增多 | CopyButton、RichMarkdown table/copy 有 timer | 已加入卸载清理测试和实现 |
| P1 | 虚拟滚动仍按消息 index 做高度估算 | 极长消息高度差异大时，远距离跳转需要二次校正 | 已有 pending target 强制窗口和精确 scrollIntoView | 保持现状，后续建议引入前缀高度缓存/二分 offset |
| P2 | Markdown AST 缓存仍不是结构化 AST cache | 重复渲染仍要经过 ReactMarkdown 解析 | 已有 compact/分段 cache 和视口懒渲染 | 后续优化 |
| P2 | localStorage 草稿和搜索状态缺少总量清理 | 长期大量会话后会留下过期 key | 当前每会话 key 持久保存 | 后续优化 |

## 4. 本轮已实现优化

### 4.1 RichMarkdown 缓存体量控制

变更点：

- 缓存 key 从 `mode:language:完整内容` 改成 `mode:language:length:hash`，避免 Map key 自身持有完整长文本。
- `remember()` 从单纯最大 entry 数升级为 entry 数 + 估算字符预算。
- 不同缓存使用不同预算：highlight cache 最多 80 项/约 4M 字符；Mermaid SVG cache 最多 40 项/约 3M 字符；KaTeX cache 最多 160 项/约 1M 字符；compact content cache 最多 160 项/约 250K 字符；Markdown segment cache 最多 80 项/约 2M 字符。

收益：长会话反复浏览时，缓存仍能保留最近结果，但不会因为少量超长块把内存长期顶高。

### 4.2 复制反馈 timer 生命周期

变更点：

- `CopyButton` 使用 ref 保存 reset timer，重复复制先清旧 timer，组件卸载时清理 timer。
- `RichMarkdown` 内部 CopyControl 和 MarkdownTable 复用 `useTimedReset`，卸载时清理 pending timer。
- 新增组件测试覆盖 CopyButton 和 RichMarkdown table copy 的卸载清理。

收益：虚拟滚动卸载消息、切换会话、折叠长回答时，不再遗留复制反馈回调。

### 4.3 会话详情加载竞态保护

变更点：

- `App.jsx` 为 `loadConversationDetails` 增加 request sequence。
- 每次加载会话详情都会生成新的 request id。
- 只有当前最新 request 能更新 `currentConversation`、`currentContextAudit`、`currentContextPolicy`。

收益：快速点击 sidebar 会话、搜索结果跳转、stream 后刷新当前会话时，旧请求不会覆盖新选择的会话。

## 5. 后续工程优化方案

### P0/P1：稳定性与正确性

1. 为 `App` 增加会话切换竞态测试：mock 两个 `api.getConversation` 延迟返回，验证旧请求不会覆盖新会话。
2. 为 SSE reader 增加最大 buffer 防护：如果 provider 长时间不发送 `\n\n`，需要限制 `buffer` 最大长度并返回可诊断错误。
3. 为 localStorage UI key 增加按会话清理策略：删除会话或超过 N 个 draft/search state 时清理旧 key。
4. 为 Mermaid PNG 导出增加超大 SVG 尺寸限制，避免 canvas 分配过大。

### P1/P2：长会话性能

1. 将 ChatInterface 的虚拟滚动逻辑拆成 `useVirtualMessageWindow`，便于单测高度估算、pending target 和 scroll correction。
2. 引入 prefix height cache，避免每次 scroll 都 O(n) 累加 offset；对 1000+ 消息会话更稳。
3. 对 message search 建立当前会话的 memoized text index，避免每次 query/scope 变化都重新拼接所有 stage 文本。
4. RichMarkdown 后续可做 AST 级缓存，但需要确认 react-markdown/remark 的 AST 复用边界，避免缓存 React node 导致状态错乱。

### P2：可观测性

1. 前端开发模式增加轻量 perf counters：RichMarkdown full render 次数、cache hit/miss、virtual window item count。
2. 后端 context audit 增加 summary cache hit/miss 和 context token 分布，帮助判断 prompt cache/summary 是否有效。
3. Playwright smoke 增加长会话 fixture 页面，验证虚拟滚动远距离跳转和 RichMarkdown 懒渲染不空白。

## 6. 当前结论

当前项目的功能实现方案符合单用户本地部署目标，主要工程风险不在多用户隔离或跨设备同步，而在长会话前端渲染的资源边界。经过本轮处理后，最直接的缓存膨胀、短 timer 泄漏和会话加载竞态风险已经收敛。下一轮应优先补 App 级竞态测试、SSE buffer 上限、localStorage 清理和虚拟滚动 prefix height cache。
