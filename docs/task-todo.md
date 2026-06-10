# Chatbox 下一轮任务 TODO

更新时间：2026-06-10

本文记录当前工程状态和下一轮任务规划。项目已经具备稳定的 Quick / Council 对话、会话管理、搜索、富 Markdown 渲染、导出、运行时诊断和核心回归保护。上一轮 P0 可靠性工作已经落地并提交；下一轮重点转为补齐少量 P0 缺口、提升高频使用效率，并为后续拆分大组件/大模块做测试护栏。

## 当前状态基线

当前代码已完成并提交以下近期修复与保护：

- `cefec19`：后续对话发送被拒时不再清空草稿，只有消息真正被接受发送后才清空输入框。
- `78a2e3e`：Markdown 导出支持中文会话标题文件名，能处理不完整 assistant stage，并输出更可读的 transcript。
- `249f734`：RichMarkdown 支持模型常见的松散 LaTeX 写法，包括独立 `[ ... ]` 公式块和 `\(\gamma\)` 一类行内公式。
- `db9e193`：新增 `/api/version` 运行时诊断接口；native status 显示 commit、PID、started_at；设置弹窗显示后端状态；前端导出错误包含 conversation id 和后端原因。
- `673d824`：新增独立 Markdown export fixture 回归测试，覆盖 Quick、Council、中文标题、中断会话和历史脏数据。
- `6873da2`：新增 ChatInterface 组件测试和 Playwright smoke，覆盖 Council / Quick 发送失败恢复草稿、成功发送清空草稿、Quick 重复点击不重复落库。
- `c551ad4`：新增 RichMarkdown 富内容 fixture 测试，覆盖标准公式、松散公式、普通括号/方括号反例、Markdown checklist、Mermaid、长代码和表格。

当前可用能力：

- Quick / Council 两种对话模式可用，支持 resume / retry / fork / branch 等基础恢复路径。
- 会话列表具备时间分组、搜索、收藏、归档、标签、置顶、批量操作和 saved views 基础能力。
- 会话内搜索、左侧历史搜索、命中跳转、长会话虚拟滚动试点已可支撑日常定位。
- Context preview / replay / policy / memory / pin / exclude 已构成基础上下文管理链路。
- Markdown、代码、表格、Mermaid、KaTeX/LaTeX 渲染已具备增强操作和懒渲染基础。
- Markdown export 已具备恢复路径属性：即使历史会话存在部分中断数据，也应尽量导出可读内容。
- 后端 pytest、前端 Vitest、lint、build、Playwright smoke 已成为常规验收命令。
- native 后端部署现在可通过 `/api/version` 和 `deploy/native/status.sh` 识别旧进程、旧 commit、PID 和启动时间。

最近一轮验证证据：

- `pytest tests/test_conversation_export_api.py tests/test_version_api.py tests/test_conversation_metadata_api.py -q`：通过，`12 passed, 5 subtests passed`。
- `pytest tests/test_quick_stream.py tests/test_resume_stream.py tests/test_conversation_fork_api.py -q`：通过，`11 passed`。
- `npm test -- ChatInterface.test.jsx RichMarkdown.test.jsx`：通过，`17 passed`。
- `npm run lint`：通过。
- `npm run build`：通过。
- `bash deploy/native/stop-backend.sh && bash deploy/native/start-backend.sh && bash deploy/native/status.sh`：通过；status 显示 commit 与 `git rev-parse --short HEAD` 一致。
- `npm run test:e2e`：通过，`5 passed`。

当前仍需关注的工程风险：

- 发送可靠性已有 Council / Quick smoke，但 branch/fork 后发送失败恢复还没有独立 Playwright 用例。
- RichMarkdown 已有组件级富内容 fixture，但还缺一个页面级“含公式 + Mermaid 的真实会话”smoke。
- 数据备份和恢复流程还没有文档化，旧 conversation JSON 的运维恢复路径仍靠经验。
- `App.jsx`、`storage.py`、`RichMarkdown.jsx` 仍承担较多职责，后续功能继续堆叠会提高回归概率。

## 下一轮优先级

### P0：剩余可靠性缺口

目标：补齐上一轮 P0 中尚未覆盖的页面级和运维级保护，避免局部测试通过但真实长会话/恢复场景仍失效。

1. Branch / fork 发送可靠性 smoke。
   - 使用现有 fork API 创建 branch，再覆盖 Council / Quick 的失败恢复草稿和成功清空路径。
   - 验证 branch 已选择、branch 未选择、会话切换后的发送不会把草稿丢失或写入错误会话。
   - 验证重复点击发送不会产生重复 user message。

   验收标准：branch 场景下没有实际创建 user message / assistant placeholder 时，输入框必须恢复原草稿；成功发送后才清空草稿。

2. 富内容页面级 smoke。
   - 创建或拦截一个含标准 LaTeX、松散公式和 Mermaid 的测试会话。
   - 等待 KaTeX/Mermaid 渲染节点出现。
   - 断言没有 `.error` 状态、没有空白 Mermaid 容器，源码/错误 fallback 不影响整条消息阅读。

   验收标准：真实页面路径能展示公式和 Mermaid；渲染失败时不会吞掉消息正文。

3. 数据备份和恢复说明。
   - 增加 conversations 数据目录备份命令。
   - 文档化恢复步骤：停服务、备份当前数据、替换 JSON、重启、跑导出 smoke。
   - 对 metadata 新字段保持向后兼容检查。

   验收标准：旧 conversation JSON 缺字段时列表、详情、导出均不崩溃；恢复流程可按文档执行。

4. 回归命令文档化。
   - 在 README 或 docs 中列出快速验收、提交前验收、发布前验收三档命令。
   - 明确后端 export/version/metadata、stream/fork、前端 ChatInterface/RichMarkdown、lint/build、Playwright smoke 的使用场景。

   验收标准：每次修复可以选择合适测试层级，而不是只靠手工试。

### P1：高频使用效率

目标：提升长时间使用后的定位、整理、诊断和输入效率。

1. 会话管理继续产品化。
   - 搜索结果增加更多分面：tag、favorite、archive、pinned、failed、files、memory。
   - 搜索结果组内批量展开/收起，命中片段高亮更稳定。
   - 批量整理增加撤销提示或最近操作记录。

   验收标准：历史会话增多后，常用会话能通过搜索、saved view、标签和批量操作快速整理。

2. Council 可解释性。
   - 在最终回答旁提供简洁贡献摘要：成功模型、失败模型、关键观点来源、是否 fallback。
   - 对部分失败、all failed、chairman fallback、context limit、disabled model 给出不同提示。
   - 汇总 duration、tokens、fallback attempts；usage 不完整时明确标注。

   验收标准：不展开 Stage1/Stage2 也能判断本轮是否可信、是否值得重试。

3. Provider 和错误诊断产品化。
   - ErrorActionPanel 根据错误类型给出入口：LLM settings、Context Policy、provider diagnostics、retry/resume。
   - 增加只读 provider diagnostics：base URL、认证、模型列表、限流、超时。
   - 对配置错误和网络错误给出可复制诊断信息。

   验收标准：常见 provider/config/context 错误能在 UI 中看到下一步动作，而不是只看堆栈或泛化错误。

4. 长会话性能和富内容效率。
   - 强化虚拟滚动：远距离搜索命中、turn 跳转、streaming 自动滚动、移动端窄屏。
   - 评估 Markdown AST 缓存，减少同一消息重复 parse。
   - Mermaid / KaTeX 改成更细的块级懒渲染和错误缓存。
   - 表格增加 XLSX 导出、列宽控制、表内命中计数。

   验收标准：100+ turn 会话打开、搜索、跳转、滚动不卡到不可用；富内容不阻塞首屏交互。

5. 输入工作流。
   - 草稿按 conversation 持久化，包含输入文本、模式选择和待上传文件队列。
   - Retry with edit 完整化：重试前显示将发送内容、上下文范围、模式变化。
   - 增加 `/` 命令菜单和本地 prompt 模板：总结、翻译、代码 review、debug、测试生成、文档整理。

   验收标准：切换会话不丢未发送输入；常用 prompt 可键盘快速插入；重试前能确认上下文。

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

1. 补 `P0-1` Branch / fork 发送可靠性 smoke。
   - 原因：发送草稿恢复已经覆盖普通 Council / Quick，branch 是同一核心路径里剩下的高风险分支。

2. 补 `P0-2` 富内容页面级 smoke。
   - 原因：组件测试已经精确锁住解析数量，页面级 smoke 用来确认真实消息列表里的懒渲染、fallback 和布局没有断。

3. 完成 `P0-3` 数据备份和恢复说明。
   - 原因：导出现在具备恢复路径属性，但运维恢复步骤还没有沉淀到文档。

4. 完成 `P0-4` 回归命令文档化。
   - 原因：当前测试矩阵已成型，应把快速/提交前/发布前验收固化，减少后续修复时的漏测。

5. 进入 `P1-2` Council 可解释性和 `P1-3` Provider 诊断。
   - 原因：Council 的价值依赖“为什么可信”和“失败后怎么办”，这两项应一起设计。

6. 推进 `P1-1` 会话管理产品化和 `P1-5` 输入工作流。
   - 原因：它们提升长期使用效率，但应建立在核心可靠性继续稳定的基础上。

7. 最后进入 `P2` 工程结构整理。
   - 原因：等 P0/P1 的高风险路径被测试锁住后，再拆大组件和大模块更稳。

## 下一轮最小交付包

建议下一轮只拿以下 4 个任务作为一个可完成批次：

1. Branch / fork 发送失败恢复和成功发送 smoke。
2. 含公式和 Mermaid 的页面级富内容 smoke。
3. conversations 数据备份 / 恢复文档和导出 smoke 操作说明。
4. 标准回归命令矩阵文档化。

完成后再进入 Council 解释性和 Provider 诊断。这样可以把上一轮 P0 的剩余缺口收尾，再继续做高频效率功能。
