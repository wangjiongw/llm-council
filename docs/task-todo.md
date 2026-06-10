# Chatbox 下一轮任务 TODO

更新时间：2026-06-10

本文记录当前工程状态和下一轮任务规划。项目已经具备稳定的 Quick / Council 对话、会话管理、搜索、富 Markdown 渲染、导出、运行时诊断、核心回归保护、备份恢复说明和标准回归矩阵。P0 可靠性与回归保护已经收口；下一轮重点转为高频使用效率、Council 可解释性、Provider 诊断和后续工程结构整理。

## 当前状态基线

当前代码已完成以下近期修复与保护：

- `cefec19`：后续对话发送被拒时不再清空草稿，只有消息真正被接受发送后才清空输入框。
- `78a2e3e`：Markdown 导出支持中文会话标题文件名，能处理不完整 assistant stage，并输出更可读的 transcript。
- `249f734`：RichMarkdown 支持模型常见的松散 LaTeX 写法，包括独立 `[ ... ]` 公式块和 `\(\gamma\)` 一类行内公式。
- `db9e193`：新增 `/api/version` 运行时诊断接口；native status 显示 commit、PID、started_at；设置弹窗显示后端状态；前端导出错误包含 conversation id 和后端原因。
- `673d824`：新增独立 Markdown export fixture 回归测试，覆盖 Quick、Council、中文标题、中断会话和历史脏数据。
- `6873da2`：新增 ChatInterface 组件测试和 Playwright smoke，覆盖 Council / Quick 发送失败恢复草稿、成功发送清空草稿、Quick 重复点击不重复落库。
- `c551ad4`：新增 RichMarkdown 富内容 fixture 测试，覆盖标准公式、松散公式、普通括号/方括号反例、Markdown checklist、Mermaid、长代码和表格。
- `cbac6aa`：新增 fork branch Council / Quick 发送失败恢复与成功发送 Playwright smoke；新增公式 + Mermaid 页面级 rich content smoke；新增 conversations 备份/恢复文档；新增标准回归命令矩阵。
- 当前 P1 执行批次：完成会话管理分面第一版和输入工作流第一版；会话列表支持 failed/files/memory/pinned 分面，搜索结果支持组级展开/收起；输入框支持模式随草稿持久化、Retry with edit 预览和本地 prompt 模板入口。

当前可用能力：

- Quick / Council 两种对话模式可用，支持 resume / retry / fork / branch 等基础恢复路径。
- 会话列表具备时间分组、搜索、收藏、归档、标签、置顶、批量操作、saved views 和 failed/files/memory/pinned 分面筛选基础能力。
- 会话内搜索、左侧历史搜索、命中跳转、搜索结果组级展开/收起、长会话虚拟滚动试点已可支撑日常定位。
- Context preview / replay / policy / memory / pin / exclude 已构成基础上下文管理链路。
- Markdown、代码、表格、Mermaid、KaTeX/LaTeX 渲染已具备增强操作和懒渲染基础。
- Markdown export 已具备恢复路径属性：即使历史会话存在部分中断数据，也应尽量导出可读内容。
- 输入框草稿按 conversation 保存输入文本和 Quick/Council 模式，兼容旧纯文本草稿；Retry with edit 会显示将使用的模式、内容长度和重建 turn。
- 本地 prompt 模板入口已提供总结、翻译、代码 review、debug、测试生成和文档整理模板。
- 后端 pytest、前端 Vitest、lint、build、Playwright smoke 已成为常规验收命令。
- native 后端部署现在可通过 `/api/version` 和 `deploy/native/status.sh` 识别旧进程、旧 commit、PID 和启动时间。
- 设置弹窗现在提供只读 Provider Diagnostics，显示配置模型、base URL、API key 是否配置、timeout、stream/enabled 状态和缺配置问题；该诊断不调用 provider、不暴露 secrets。
- Council Run Summary 已有组件级回归，覆盖成功/失败模型、fallback attempt、tokens、duration 和 warnings。
- 备份/恢复流程见 `docs/conversation-backup-recovery.md`。
- 快速验收、提交前验收、发布前验收命令矩阵见 `docs/regression-matrix.md`。

最近一轮验证证据：

- `pytest tests/test_conversation_export_api.py tests/test_version_api.py tests/test_conversation_metadata_api.py -q`：通过，`12 passed, 5 subtests passed`。
- `pytest tests/test_quick_stream.py tests/test_resume_stream.py tests/test_conversation_fork_api.py -q`：通过，`11 passed`。
- `npm test -- ChatInterface.test.jsx RichMarkdown.test.jsx`：通过，`17 passed`。
- `npm test -- ChatInterface.test.jsx LLMSettingsModal.test.jsx`：通过，`13 passed`。
- `pytest tests/test_llm_settings.py tests/test_council_failures.py -q`：通过，`13 passed`。
- `pytest tests/test_llm_settings.py tests/test_stage_model_status_events.py tests/test_quick_stream.py -q`：通过，`14 passed`。
- `npm run lint`：通过。
- `npm run build`：通过。
- `bash deploy/native/stop-backend.sh && bash deploy/native/start-backend.sh && bash deploy/native/status.sh`：通过；status 显示 commit 与 `git rev-parse --short HEAD` 一致。
- `npm run test:e2e`：通过，`8 passed`。
- `pytest tests/test_conversation_metadata_api.py tests/test_conversation_search_api.py -q`：通过，`13 passed`。
- `npm test -- ChatInterface.test.jsx Sidebar.test.jsx`：通过，`26 passed`。

当前仍需关注的工程风险：

- Playwright 发送 smoke 使用受控 SSE mock，不覆盖真实 provider outage、限流或慢响应链路。
- 输入工作流第一版暂不持久化待上传文件队列，`/` 命令菜单也尚未落地；当前仅提供本地模板选择入口。
- 会话管理第一版覆盖 failed/files/memory/pinned 常用分面和搜索结果组级展开/收起；tag/favorite/archive 搜索分面、批量整理撤销仍待后续。
- 备份/恢复文档已经固化，但尚未在一次真实历史备份恢复演练中执行全流程。
- `App.jsx`、`storage.py`、`RichMarkdown.jsx` 仍承担较多职责，后续功能继续堆叠会提高回归概率。

## 下一轮优先级

### P0：可靠性和回归保护收口完成

目标：把近期真实暴露的问题转化为自动化验收和运维文档。当前 P0 最小交付包已完成：

1. Branch / fork 发送可靠性 smoke。
   - 已使用真实 fork API 创建 branch fixture。
   - 已覆盖 branch Council 发送失败恢复草稿、成功发送清空草稿、只追加一个 accepted user turn。
   - 已覆盖 branch Quick 发送失败恢复草稿、成功发送清空草稿、快速重复点击不重复落库。

2. 富内容页面级 smoke。
   - 已覆盖真实消息视图中的标准 LaTeX、松散公式、行内公式和 Mermaid。
   - 已断言 KaTeX/Mermaid 渲染节点非空，且没有 Mermaid error placeholder。

3. 数据备份和恢复说明。
   - 已新增 `docs/conversation-backup-recovery.md`。
   - 已记录停服务、备份、恢复、重启、status 检查和导出 smoke。

4. 回归命令文档化。
   - 已新增 `docs/regression-matrix.md`。
   - 已区分快速验收、提交前验收、发布前验收和备份/恢复验收。

验收证据：

- `npm run test:e2e -- -g "forked branch|formula and Mermaid"`：通过，`3 passed`。
- `npm run test:e2e`：通过，`8 passed`。
- `pytest tests/test_conversation_metadata_api.py tests/test_conversation_search_api.py -q`：通过，`13 passed`。
- `npm test -- ChatInterface.test.jsx Sidebar.test.jsx`：通过，`26 passed`。
- `pytest tests/test_conversation_export_api.py tests/test_version_api.py tests/test_conversation_metadata_api.py -q`：通过，`12 passed, 5 subtests passed`。
- `pytest tests/test_quick_stream.py tests/test_resume_stream.py tests/test_conversation_fork_api.py -q`：通过，`11 passed`。
- `npm test -- ChatInterface.test.jsx RichMarkdown.test.jsx`：通过，`17 passed`。
- `npm run lint`：通过。
- `npm run build`：通过。

### P1：高频使用效率

目标：提升长时间使用后的定位、整理、诊断和输入效率。

1. 会话管理继续产品化。
   - 第一版已完成：后端会话 metadata 暴露 `has_files`、`has_failed_run`、`has_memory`、`pinned_message_count`。
   - 第一版已完成：会话列表支持 failed/files/memory/pinned 分面筛选，saved views 会保存这些筛选条件。
   - 第一版已完成：搜索结果支持组级 Expand all / Collapse all，并保持高亮命中片段可读。
   - 后续可继续增强：tag/favorite/archive 搜索分面、批量整理撤销提示或最近操作记录。

   验收标准：历史会话增多后，常用会话能通过搜索、saved view、标签和批量操作快速整理。当前第一版已满足常用分面筛选和搜索结果组操作。

2. Council 可解释性。
   - 第一版已完成：最终回答旁已有 Council Run Summary，展示 Stage 1/2 成功失败数、chair 模型、失败模型数、fallback attempt、tokens、slowest duration 和 warnings。
   - 第一版已补组件测试，覆盖成功模型、失败模型、fallback attempt、tokens、duration 和 warning。
   - 后续可继续增强：关键观点来源的更细粒度引用、usage 缺失时的显式标注、all failed/chairman fallback 的更细文案。

   验收标准：不展开 Stage1/Stage2 也能判断本轮是否可信、是否值得重试。当前第一版已满足主要路径。

3. Provider 和错误诊断产品化。
   - 第一版已完成：新增只读 `/api/settings/llm/diagnostics`，返回配置模型、角色、base URL、key 是否配置、timeout、stream/enabled、问题列表和 read-only 检查状态。
   - 第一版已完成：设置弹窗展示 Provider Diagnostics；provider 相关错误面板提供 Provider Diagnostics 入口；技术细节仍可复制。
   - 后续可继续增强：真实 provider 模型列表探测、限流探测和网络连通性探测需要显式用户触发，避免只读诊断产生外部调用。

   验收标准：常见 provider/config/context 错误能在 UI 中看到下一步动作，而不是只看堆栈或泛化错误。当前配置类和 provider 错误入口第一版已完成。

4. 长会话性能和富内容效率。
   - 强化虚拟滚动：远距离搜索命中、turn 跳转、streaming 自动滚动、移动端窄屏。
   - 评估 Markdown AST 缓存，减少同一消息重复 parse。
   - Mermaid / KaTeX 改成更细的块级懒渲染和错误缓存。
   - 表格增加 XLSX 导出、列宽控制、表内命中计数。

   验收标准：100+ turn 会话打开、搜索、跳转、滚动不卡到不可用；富内容不阻塞首屏交互。

5. 输入工作流。
   - 第一版已完成：草稿按 conversation 持久化输入文本和 Quick/Council 模式，并兼容旧纯文本草稿。
   - 第一版已完成：Enter 使用当前模式发送，Ctrl/Cmd+Enter 使用备用模式；发送成功后只清空内容、不清空模式偏好。
   - 第一版已完成：Retry with edit 显示将发送的模式、字符数和上下文重建起点。
   - 第一版已完成：新增本地 prompt 模板入口，覆盖总结、翻译、代码 review、debug、测试生成、文档整理。
   - 后续可继续增强：待上传文件队列持久化、`/` 命令菜单和完整键盘模板选择。

   验收标准：切换会话不丢未发送输入；常用 prompt 可快速插入；重试前能确认上下文。当前第一版已满足模式草稿、重试预览和模板入口。

### P2：工程结构和长期维护

目标：降低继续迭代时的改动风险，让常见功能有清晰落点。

1. 前端状态边界整理。
   - 从 `App.jsx` 中拆出 conversation selection、send lifecycle、export/download、draft restore 等 hook。
   - `ChatInterface` 继续拆分搜索、composer、message list、error recovery 子模块。
   - 拆分前先补组件测试，避免行为回归。

   验收标准：新增发送或导出功能时，不需要在单个巨型组件里跨多段状态修改。

2. 后端存储和导出模块化。
   - 从 `storage.py` 中拆出 export serializer、metadata migration、search/context audit 边界。
   - 导出逻辑保留纯函数入口，便于 fixture 测试。
   - 对旧 JSON schema 做集中 normalize。

   验收标准：新增导出格式或 metadata 字段时，有明确模块和测试入口。

3. RichMarkdown 解析边界整理。
   - 将 block math、inline math、Mermaid、table/code utilities 分成小 helper，并保留测试覆盖。
   - 明确“显式分隔符”和“松散模型输出启发式”的规则，避免后续误改。

   验收标准：富内容支持继续扩展时，不会把普通 Markdown 误解析为公式或图表。

## 建议执行顺序

1. `P1-2` Council 可解释性和 `P1-3` Provider 诊断第一版已完成。
   - 已落地 Council Run Summary 测试、只读 provider diagnostics API、设置弹窗诊断面板和错误入口。
   - 后续增强项保留为真实 provider 探测、关键观点来源引用和 usage 缺失标注。

2. `P1-1` 会话管理产品化和 `P1-5` 输入工作流第一版已完成。
   - 已落地 failed/files/memory/pinned 会话分面、搜索结果组级展开/收起、模式草稿持久化、Retry with edit 预览和本地 prompt 模板入口。
   - 后续增强项保留为搜索 tag/favorite/archive 分面、批量整理撤销、文件队列持久化和 `/` 命令菜单。

3. 下一步推进 `P1-4` 长会话性能和富内容效率。
   - 原因：页面级 rich content smoke 已建立，后续可以更安全地优化懒渲染和缓存。

4. 再回到 `P1-2` / `P1-3` 第二版增强。
   - 原因：真实 provider 探测会产生外部调用，Council 来源引用也需要更稳定的展示模型，适合在高频使用效率完成后单独推进。

5. 最后进入 `P2` 工程结构整理。
   - 原因：等 P1 的产品行为更稳定后，再拆大组件和大模块更稳。

## 下一轮最小交付包

建议下一轮只拿以下 4 个任务作为一个可完成批次：

1. `P1-4` 长会话性能 smoke 扩展：100+ turn fixture、远距离搜索命中跳转、streaming 自动滚动和移动端窄屏检查。
2. 富内容效率第一版：评估 Markdown parse 缓存边界，给 Mermaid / KaTeX 懒渲染和错误缓存补组件级保护。
3. 会话管理剩余小项：tag/favorite/archive 搜索分面、批量整理撤销提示或最近操作记录。
4. 输入工作流剩余小项：待上传文件队列持久化和 `/` 命令菜单。

P0 可靠性批次已收口；P1 可解释性、Provider 诊断第一版、会话管理第一版和输入工作流第一版已完成。下一轮建议进入长会话性能和富内容效率。
