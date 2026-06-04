# Chatbox 对话管理与上下文系统报告


## 0. 当前进度更新（2026-06-02）

本轮已补齐会话组织元数据，并完成一组性能与部署稳定性优化。本文中“当前新增功能总览”可按以下进度补充理解。

已完成：

- conversation 顶层新增并持久化 `updated_at`、`favorite`、`archived`、`pinned`、`tags`。
- 列表 API 返回完整会话元数据，并按置顶优先、更新时间倒序排序。
- 前端 Sidebar 支持 Active / Archived、收藏筛选、标签筛选、Pinned 分组、标签编辑、Archive/Restore。
- 会话级 `pinned` 与消息级 `pinned` 已分离：前者用于列表组织，后者用于上下文构建。
- `RichMarkdown` 增加视口懒渲染，减少长会话中 Markdown、KaTeX、Mermaid、代码高亮的初始渲染成本。
- native 非 systemd 部署新增独立后端启动脚本，状态脚本增加 API 健康探测。

仍待实现：

- 会话内全文搜索和跳转。
- 左侧搜索结果、命中片段、过滤器和点击跳转。
- 标签批量管理、标签颜色、会话 badges。
- 错误恢复面板和 Council Run Summary。

## 1. 背景与目标

当前项目是一个本地部署的 chatbox 服务，包含前端和后端。它与常规 chatbox 的主要区别是支持 council mode：一次用户请求会经过多模型候选回答、交叉评价、主席综合等阶段；同时也需要 quick mode，用于低延迟的普通单模型对话。

模型 API 调用本质上是无状态的。服务端每次请求模型时，都不能假设模型“记得”之前发生过什么。因此，一个可靠的 chatbox 需要在本地维护会话状态，并在每次调用前把需要的历史、摘要、文件、记忆和当前消息重新组装成模型可消费的 prompt/context。

这轮工程的核心目标是：

- 让 quick mode 和 council mode 都能稳定使用同一套会话上下文。
- 避免每次简单发送全量历史导致 token 不可控、延迟高、隐私和审计困难。
- 支持长对话、文件对话、多模态图片、重试、恢复、分叉、截断和删除。
- 让用户能在前端看到“下一次模型到底会收到什么上下文”。
- 让模型回答中的 Markdown、代码、表格、LaTeX 和 Mermaid 能正常渲染。

## 2. 当前新增功能总览

### 2.1 无状态 API 的本地会话状态层

新增的会话管理逻辑把每个 conversation 作为本地状态实体保存。模型 API 不保存历史，后端负责保存、裁剪和重建历史。

当前 conversation 中可持久化的信息包括：

- `messages`：用户消息和助手消息。
- `turns`：一次用户请求及对应模型运行结果的结构化记录。
- `context_policy`：当前会话的上下文打包策略。
- `context_memory`：用户或系统提取出的长期上下文记忆。
- `context_summary`：长对话摘要缓存。
- `updated_at`、`favorite`、`archived`、`pinned`、`tags`：会话列表组织元数据。
- message 级别的 `pinned` 状态。
- message 级别的 context visibility，即是否参与后续上下文。
- 文件元信息和多模态图片的本地附件引用。
- 每轮模型调用的 `context_payload` 审计快照。

这样，每次发起模型调用时，后端都从本地状态重新构建上下文，而不是依赖 provider 侧状态。

### 2.2 Context Package：模型调用前的上下文打包

新增了统一的 context package 构建流程。它把会话历史拆成不同来源，并按预算组合成最终模型消息。

当前上下文来源包括：

- system / 模式指令。
- 当前用户消息。
- 最近若干轮消息。
- 会话摘要。
- pinned 重要消息。
- context memory。
- 文件内容或文件相关 chunk。
- quick/council/resume/retry 等模式元信息。

context package 会输出：

- `model_messages`：真正发送给模型的消息。
- `audit_messages`：用于前端和审计展示的安全版本。
- `current_message`：当前用户消息的结构化表示。
- `context_snapshot`：本次上下文策略、预算和来源快照。
- `compaction`：是否进行了图片脱敏、文本截断等审计压缩。

这解决了三个关键问题：

- 长对话不会无脑堆满 provider context window。
- 用户能理解模型回答时参考了哪些内容。
- retry/replay 能复现当时模型输入，而不是事后猜测。

### 2.3 Context Policy：每个会话独立的上下文策略

新增了 per-conversation context policy。不同会话可以有不同的上下文预算和构建方式。

当前策略支持的方向包括：

- 是否启用摘要。
- 是否启用 memory。
- 是否使用 pinned messages。
- 最近消息数量和预算。
- summary、memory、pinned、recent、current message 的预算分配。
- 文件内容进入上下文的预算。

前端新增了策略编辑入口，可以查看并调整当前会话的上下文策略。

### 2.4 Context Preview：发送前预览模型上下文

新增了发送前上下文预览能力。用户在输入下一条消息前，可以预览模型将收到的上下文包。

预览能力包括：

- 展示 model-facing messages。
- 展示上下文来源。
- 展示 token/字符预算分布。
- 对带文件的消息执行文件上下文预览。
- 在输入区提示下一条消息会携带多少历史上下文。

这个能力对本地 API chatbox 很重要，因为用户不应该只看到聊天记录，还应该能看到“哪些聊天记录真的进入了模型输入”。

### 2.5 Context Replay：历史消息上下文复盘

每个 turn 保存了 `context_payload`。前端可以对历史用户消息执行 context replay。

replay 有两种价值：

- 如果当时保存了 `context_payload`，优先展示当时实际使用的上下文。
- 如果需要，也可以按当前策略重建上下文，并与当时快照比较 drift。

这样可以回答：

- 为什么这次模型忽略了某段历史？
- 当时是否使用了 summary？
- 当时是否包含了某个文件？
- 后来调整策略后，同一条消息的上下文会发生什么变化？

### 2.6 Context Memory：会话级长期记忆

新增了会话级 context memory CRUD。

当前支持：

- 添加 memory。
- 修改 memory。
- 删除 memory。
- 启用/禁用 memory。
- 从本地历史搜索结果中复用内容作为 memory。

memory 适合保存不应该随最近消息窗口滑出而丢失的信息，例如：

- 用户偏好。
- 项目约束。
- 长期任务目标。
- 代码仓库背景。
- 当前会话中的重要决策。

### 2.7 Message Pin 与 Context Visibility

新增了消息级上下文控制：

- Pin：把某条消息标记为重要上下文，优先进入后续 context package。
- Exclude：把某条消息从后续模型上下文中排除，但仍保留在聊天记录里。

这比单纯删除消息更适合真实 chatbox：

- 用户可以保留历史可读性。
- 可以避免错误回答、无关内容、敏感内容继续污染上下文。
- 可以把关键需求或最终决策固定在上下文里。

### 2.8 会话组织元数据

新增了会话级组织字段，用于长期单用户使用中的快速定位和整理。

当前支持：

- `favorite`：收藏会话，可在侧边栏筛选。
- `archived`：归档会话，默认从 Active 视图隐藏，可在 Archived 视图恢复。
- `pinned`：置顶会话，在 Active 视图中进入 Pinned 分组。
- `tags`：简单字符串标签，支持编辑和筛选。
- `updated_at`：会话更新时间，列表排序优先使用该字段。

注意：会话级 `pinned` 只影响列表组织；消息级 `pinned` 仍用于上下文构建，两者职责不同。

### 2.9 会话搜索与复用

新增了本地会话历史搜索能力。用户可以搜索已有 conversation 的历史内容，并把有价值的信息复用为当前会话 memory。

这为后续跨会话记忆、项目知识库和语义检索打下基础。

### 2.10 Retry：失败或不满意回答的无重复重试

新增了针对已保存用户消息的 retry 能力。

设计重点：

- 不重复追加同一条用户消息。
- 截断该用户消息之后的旧助手回答和后续内容。
- 重新构建上下文。
- 支持 quick/council 模式。
- 多模态图片通过 `attachment_ref` 恢复为模型可用输入。

这解决了常见 chatbox 里的问题：用户点击重试后，历史里出现重复用户消息，或者模型拿到的上下文和原始请求不一致。

### 2.11 Resume：流式中断后的恢复

当前实现支持对中断的 council run 进行恢复。对于流式输出或多阶段 council 流程，客户端断开连接后，后端可以基于已保存的 turn/run 状态继续处理。

这对 council mode 很关键，因为 council mode 比 quick mode 更长，失败面更大：

- 多模型并发调用可能部分完成。
- 主席综合可能失败。
- 浏览器可能断开。
- 网络可能中断。

恢复能力使得系统不会因为一次中断就丢弃整个多阶段任务。

### 2.12 Conversation Fork：会话分叉

新增了按消息边界 fork conversation 的能力。

用途：

- 从某个历史节点开新分支。
- 保留旧会话，不破坏原路径。
- 比“删除后重问”更适合探索不同方向。
- 对长任务、方案比较、prompt 调试尤其有价值。

对于图片附件，fork 会复制附件引用到新会话目录，并把 `attachment_ref.conversation_id` 改为新分支 ID，避免分支删除时误删父会话附件。

### 2.13 Truncate/Delete 与附件生命周期

新增并修正了图片附件生命周期管理：

- 图片上传后，原始 base64 不长期保存在 conversation JSON。
- 图片字节存到本地附件目录。
- JSON 中只保留 redacted image URL 和 `attachment_ref`。
- retry/replay 时用 `attachment_ref` 恢复 data URI。
- truncate 会删除不再被剩余消息/turn 引用的附件。
- delete conversation 会删除该 conversation 的附件目录。
- fork 会复制附件，避免父子会话生命周期互相影响。

这让多模态对话既可审计，又避免 JSON 过大和敏感 payload 长期暴露。

### 2.14 富 Markdown 渲染

新增了 `RichMarkdown` 组件，用于渲染模型输出。

当前支持：

- 标准 Markdown。
- GitHub 风格表格。
- 代码块。
- 语法高亮。
- LaTeX/KaTeX 数学公式。
- Mermaid 图。
- 表格复制。
- 代码复制。
- 图表渲染失败时的降级展示。

Stage1、Stage2、Stage3 和最终聊天消息都接入了富文本渲染。

### 2.15 代码语法高亮

当前使用 `highlight.js`，并按需注册常用语言：

- JavaScript / TypeScript。
- Python。
- Bash。
- JSON / YAML / Markdown。
- CSS / XML。
- SQL。
- Go / Rust / Java / C++ / C#。
- Diff。

代码块会根据 fenced code block 的语言标识选择高亮语言。纯 text 不强制套用彩色方案，避免普通文本被错误着色。

为了控制性能，当前实现中有高亮长度限制，较大的代码块会降级为普通文本显示。

### 2.16 LaTeX/KaTeX 公式渲染

当前通过 `katex` 渲染公式，支持 inline 和 display 形式。

优势：

- 渲染速度快。
- 不依赖外部 CDN。
- 适合本地部署。

当前采用懒加载方式加载 KaTeX，避免首屏立即加载完整数学渲染库。

### 2.17 Mermaid 图渲染

当前通过 `mermaid` 渲染 fenced code block 中的 Mermaid 图。

设计点：

- 只有在需要渲染 Mermaid 时才加载 Mermaid。
- 渲染失败时显示错误和原始代码，避免页面空白。
- 对预览/简化模式可延迟渲染，减少长消息中的渲染压力。
- `RichMarkdown` 已在组件层加入视口懒渲染，长会话中未接近视口的完整富内容会先以 compact 形式展示，进入附近视口后再完整渲染。

### 2.18 浅色/深色模式

新增了深色模式开关，位于左上角标题区域。

当前行为：

- 用户可以手动切换 light/dark。
- 主题写入 `localStorage`。
- 根节点通过 `data-theme` 控制 CSS 变量。
- 代码块主题随页面主题切换。

对代码块而言，浅色模式和深色模式不应该固定使用同一个主题。当前实现方向是页面主题驱动代码块配色，从而避免浅色页面里出现突兀的 dark-only 代码块。

### 2.19 长消息和 turn 导航

针对长回答难以滚动的问题，新增了 turn/message 导航。

当前支持：

- 按 turn 定位。
- 上一轮/下一轮跳转。
- 回到消息区域顶部。
- 回到底部。
- 当前 turn 状态显示。
- 高亮当前定位消息。

这对 council mode 尤其重要，因为一次回答可能包含 Stage1、Stage2、Stage3 和最终综合，单条消息会很长。

### 2.20 前端上下文审计面板

聊天消息旁新增了上下文审计相关展示：

- turn 编号。
- 模式标识。
- 使用的上下文信息。
- 文件信息。
- 模型运行状态。
- context replay 操作。
- replay 结果和 drift 信息。

用户可以在聊天界面直接追踪模型回答背后的输入和运行过程。

### 2.21 回归测试覆盖

新增和扩展了多组后端测试：

- context package 构建。
- context preview。
- context replay。
- context policy。
- context memory。
- context summary。
- context pin。
- context visibility。
- conversation fork。
- conversation search。
- retry message。
- file upload。
- image attachment audit/retry/lifecycle。
- storage partial/truncate。
- storage concurrency。
- quick stream。
- resume stream。

最近验证结果：

- `python3 -m py_compile backend/storage.py tests/test_file_upload_api.py` 通过。
- `pytest tests/test_file_upload_api.py tests/test_conversation_fork_api.py tests/test_storage_partial.py` 通过，17 passed。
- `pytest` 通过，82 passed。
- `npm run build` 通过。
- `git diff --check` 通过。

## 3. 当前核心技术栈

### 3.1 后端

当前后端技术栈：

- Python。
- FastAPI。
- Pydantic request/response model。
- 本地 JSON conversation storage。
- 文件系统附件存储。
- pytest 回归测试。

当前后端设计特点：

- conversation 是本地状态源。
- provider API 只作为无状态推理引擎。
- context package 是每次模型调用的唯一输入构建入口。
- `context_payload` 是审计和 replay 的事实依据。
- 附件字节与 conversation JSON 分离。

### 3.2 前端

当前前端技术栈：

- React。
- Vite。
- CSS variables / `data-theme` 主题控制。
- `react-markdown`。
- `remark-gfm`。
- `highlight.js`。
- `katex`。
- `mermaid`。
- 原生 Fetch / SSE 风格流式处理。

当前前端设计特点：

- chat 主界面仍是第一屏核心体验。
- context 面板承担策略、预览、记忆、摘要和历史复用。
- RichMarkdown 负责模型输出的统一渲染。
- 重组件按需加载，降低首屏成本。
- turn navigator 解决长对话定位问题。

### 3.3 存储与审计

当前存储方式：

- conversation JSON 存储会话结构。
- attachment directory 存储图片等二进制内容。
- `attachment_ref` 连接 JSON 和附件。
- `context_payload` 保存每轮模型输入快照。

这种设计适合本地部署、小团队使用和快速迭代。后续如果扩展到多用户、多实例或高并发，需要迁移到数据库和对象存储。

## 4. 当前架构如何处理“API 无状态”

### 4.1 基本原则

模型 API 无状态意味着：

- 每次请求都必须显式提供上下文。
- provider 不知道本地 conversation ID。
- provider 不知道哪些消息被删除、隐藏、置顶或摘要。
- provider 不知道本地文件是否还存在。
- provider 不知道上次请求的 prompt 结构。

因此，系统必须把“聊天历史管理”和“模型推理调用”解耦：

- 聊天历史管理在本地完成。
- 模型调用只接收本次构造出的 `model_messages`。

### 4.2 当前一次请求的上下文流程

一次普通请求的流程是：

1. 用户在前端输入消息，可附带文件。
2. 前端调用后端 API。
3. 后端读取 conversation。
4. 后端根据 `context_policy`、summary、memory、pinned、recent messages 和当前消息构建 `context_package`。
5. 如果包含图片附件，后端在模型调用前恢复 image data URI。
6. 后端把 `model_messages` 发送给 quick model 或 council pipeline。
7. 后端保存用户消息、助手消息、turn、模型 run metadata 和 `context_payload`。
8. 前端刷新 conversation 和 context audit。

### 4.3 为什么不直接发送全量历史

不建议全量发送历史的原因：

- 长对话很快超过上下文窗口。
- 每次请求成本和延迟持续上升。
- 多模态图片 base64 会让 payload 暴涨。
- 错误回答或无关内容会持续污染后续请求。
- 用户无法知道模型实际参考了哪些历史。
- replay 和 debug 很困难。

当前 context package 的设计是更可控的方式：明确来源、预算、裁剪和审计。

## 5. 还可以继续优化的方向

### 5.1 语义检索上下文

当前上下文主要依赖最近消息、摘要、pin 和 memory。后续可以增加语义检索，把长历史和文件内容向量化。

建议技术栈：

- Embedding model：OpenAI embeddings、bge-m3、gte、e5、nomic-embed-text 等。
- 向量库：Qdrant、pgvector、Chroma、LanceDB。
- 文档切分：LangChain text splitters、LlamaIndex node parser，或自研 token-aware splitter。
- rerank：bge-reranker、Cohere Rerank、Jina Reranker。

建议实现：

- message、turn、summary、file chunk 都生成 embedding。
- 每次请求根据当前问题检索 top-k 历史片段。
- 检索结果进入 context package 的 `retrieved` section。
- 前端展示“本次召回了哪些历史”。
- 对召回内容记录审计，避免黑箱。

### 5.2 Token 精确预算

当前上下文预算可以按字符和估算控制。后续应接入真实 tokenizer。

建议技术栈：

- OpenAI/tiktoken。
- Hugging Face tokenizers。
- Anthropic/OpenRouter 特定模型 tokenizer 映射。

建议实现：

- 为每个 provider/model 配置 tokenizer。
- context package 使用 token 而不是字符作为硬预算。
- 前端显示估算 token 数、剩余预算和截断原因。
- 针对不同模型窗口自动选择策略。

### 5.3 Prompt Cache / Provider Cache

长上下文重复发送会增加延迟和成本。部分 provider 支持 prompt caching，可以利用稳定前缀。

建议技术栈：

- Provider 原生 prompt cache。
- OpenRouter provider-specific metadata。
- 自研 context hash。

建议实现：

- 对 system、summary、memory、pinned 生成稳定 hash。
- 尽量把稳定内容放在 prompt 前缀。
- 记录每次请求的 cache key 和 cache hit/miss。
- 前端 context audit 展示 cache 状态。

### 5.4 自动摘要质量控制

当前摘要可重建和清理，但摘要质量可以继续加强。

建议技术栈：

- LLM summarizer。
- structured summary schema。
- JSON schema validation。
- eval set / golden conversations。

建议实现：

- 摘要拆成事实、决策、待办、用户偏好、开放问题。
- 每次摘要更新只处理新增区间，避免全量重写。
- 摘要中保留来源 message index。
- 提供摘要 diff 和手动编辑。
- 对摘要进行一致性检查，避免模型编造历史。

### 5.5 Memory 的确认、过期和作用域

当前 memory 是会话级 CRUD。后续可以增强为更成熟的记忆系统。

建议技术栈：

- SQLite/PostgreSQL。
- pgvector 或 Qdrant。
- Pydantic schema。
- 可选的规则引擎。

建议实现：

- memory 分 scope：conversation、project、global user。
- memory 分类型：偏好、事实、约束、身份、任务状态。
- memory 增加 TTL/过期时间。
- 模型建议新增 memory，但需要用户确认。
- memory 有来源引用和置信度。
- 支持敏感 memory 标记和一键删除。

### 5.6 Conversation Tree 可视化

当前支持 fork，但前端还可以更明确地展示分叉结构。

建议技术栈：

- React Flow。
- D3。
- Elkjs / Dagre layout。

建议实现：

- 每个 conversation 保存 parent_id、fork_from_message_index。
- 前端展示会话树。
- 支持从任一节点跳转。
- 支持比较两个分支的上下文和回答。

### 5.7 多用户与权限隔离

当前更偏本地单用户服务。后续如果多人使用，需要权限模型。

建议技术栈：

- FastAPI auth middleware。
- JWT / session cookie。
- PostgreSQL。
- Row-level ownership。
- S3/MinIO 对象存储。

建议实现：

- conversation 绑定 owner。
- attachment 绑定 owner 和 conversation。
- API 层做权限校验。
- 支持分享只读会话。
- context replay 和附件读取都必须校验权限。

### 5.8 从 JSON 存储迁移到数据库

本地 JSON 适合当前阶段，但功能继续增长后会遇到并发、搜索和迁移问题。

建议技术栈：

- SQLite：适合本地单机。
- PostgreSQL：适合多人和服务化部署。
- SQLAlchemy / SQLModel / Alembic。
- MinIO/S3：存储附件。

建议实现：

- conversations 表。
- messages 表。
- turns 表。
- model_runs 表。
- context_payloads 表。
- context_memories 表。
- attachments 表。
- vector_chunks 表。

迁移时保留 JSON export/import，避免破坏已有本地数据。

### 5.9 前端虚拟滚动

长对话和富内容会让 DOM 变大。当前已有 turn 跳转，但还可以进一步优化渲染性能。

建议技术栈：

- `@tanstack/react-virtual`。
- IntersectionObserver。
- React memo。

建议实现：

- 消息列表虚拟滚动。
- Mermaid/KaTeX 只在进入视口后渲染。
- 长代码块默认折叠。
- 大表格横向滚动和局部渲染。
- context replay panel 默认懒加载。

### 5.10 Mermaid 与 KaTeX 的性能优化

构建产物显示 Mermaid 和 KaTeX 相关 chunk 较大。当前已使用动态加载，但还可以继续细分。

建议技术栈：

- Vite dynamic import。
- manualChunks。
- Web Worker。
- requestIdleCallback。

建议实现：

- Mermaid 只在用户展开图表时加载。
- 大图渲染放到 idle time。
- Mermaid SVG 缓存到 message render cache。
- KaTeX 公式按消息级缓存。
- 预览模式不渲染重组件，只显示占位。

### 5.11 表格能力增强

当前支持 Markdown 表格和复制。后续可以增加更接近生产 chatbox 的表格交互。

建议技术栈：

- `@tanstack/react-table`。
- Papa Parse。
- SheetJS。

建议实现：

- 复制 Markdown。
- 复制 CSV。
- 下载 CSV/XLSX。
- 列宽拖拽。
- 大表格折叠。
- 表格搜索和排序。

### 5.12 代码块能力增强

当前支持语法高亮和复制。后续可以加强代码阅读体验。

建议技术栈：

- Shiki：更高质量主题和 TextMate grammar。
- highlight.js：继续保留轻量模式。
- Monaco Editor：仅用于可编辑/大型代码场景。

建议实现：

- 语言自动识别。
- 行号。
- 折叠长代码。
- 复制指定行。
- 下载代码文件。
- diff 代码块特殊显示。
- light/dark 主题精确切换。

### 5.13 文件模式增强

当前已支持文件进入 quick/council 对话，但可以继续提升文件理解能力。

建议技术栈：

- unstructured。
- pypdf / pdfplumber。
- python-docx。
- pandas。
- OCR：PaddleOCR、Tesseract。
- 向量库：Qdrant/pgvector。

建议实现：

- PDF 分页提取。
- 表格文件结构化读取。
- 图片 OCR。
- 文件 chunk embedding。
- 文件引用出处展示。
- 文件内容变更后重新索引。

### 5.14 Council Mode 的对话管理增强

Council mode 比 quick mode 更复杂，后续可以把上下文管理做得更适配多模型协作。

建议技术栈：

- Pydantic structured outputs。
- JSON schema validation。
- event log。
- DAG run model。

建议实现：

- Stage1/Stage2/Stage3 分别记录使用了哪些上下文。
- 不同模型可以使用不同上下文预算。
- Stage2 评价时可选择是否暴露完整历史。
- 主席综合保留引用来源。
- 失败模型的结果不污染最终上下文。
- council run 可视化为执行 DAG。

### 5.15 自动评测与回归集

当前已有 pytest，但可以增加面向 chatbox 行为的评测。

建议技术栈：

- pytest。
- Playwright。
- MSW 或本地 mock provider。
- promptfoo / DeepEval / OpenAI Evals 风格评测。

建议实现：

- 长对话上下文是否保留关键事实。
- excluded message 是否不会进入模型输入。
- pinned message 是否优先进入。
- summary 是否不丢关键约束。
- retry 是否不重复用户消息。
- fork 是否不污染父会话。
- Mermaid/LaTeX/表格/代码块视觉回归。

### 5.16 可观测性与成本统计

当前已有模型 run metadata 和 context audit，后续可以增加更系统的观测指标。

建议技术栈：

- OpenTelemetry。
- Prometheus。
- Grafana。
- Langfuse / Phoenix。

建议实现：

- 每次请求 token 用量。
- context package 各来源 token 占比。
- provider latency。
- council 各 stage latency。
- fallback 触发次数。
- retry/resume 成功率。
- prompt cache hit rate。

### 5.17 安全与隐私

当前已经避免原始图片 base64 长期保存在 JSON。后续可继续加强。

建议技术栈：

- Secret scanning。
- 本地加密：age/libsodium。
- PII detection。
- access log redaction。

建议实现：

- conversation export 前脱敏。
- context audit 可选择隐藏敏感内容。
- memory 增加敏感标记。
- 附件加密存储。
- 日志不打印 provider API key 和大 payload。

## 6. 推荐后续实施优先级

### P0：稳定性与可维护性

- 补 Playwright 基础 UI 回归。
- 为 context package 增加更清晰的 schema 文档。
- 增加真实 tokenizer 预算。
- 给 summary/memory 增加来源引用。

### P1：长对话质量

- 引入语义检索。
- memory 分 scope 和类型。
- 摘要结构化和增量更新。
- 支持 context replay 的 drift diff 可视化。

### P2：性能与成本

- 消息虚拟滚动。
- Mermaid/KaTeX 视口懒渲染。
- provider prompt cache。
- context package hash。

### P3：生产化部署

- JSON 存储迁移到 SQLite/PostgreSQL。
- 附件迁移到 MinIO/S3。
- 多用户权限。
- OpenTelemetry 和成本看板。

## 7. 当前功能到技术栈映射

| 功能 | 当前技术 | 后续可选技术 |
| --- | --- | --- |
| 会话持久化 | JSON storage | SQLite, PostgreSQL, SQLAlchemy, Alembic |
| 附件存储 | 本地文件系统 | MinIO, S3 |
| 上下文打包 | Python storage/context builder | token-aware packer, provider-specific tokenizer |
| 摘要 | LLM summary cache | structured summary schema, incremental summarization |
| Memory | conversation JSON list | pgvector, Qdrant, scoped memory DB |
| 历史搜索 | 本地文本搜索 | embeddings, reranker |
| Markdown | react-markdown, remark-gfm | MDX for controlled components |
| 代码高亮 | highlight.js | Shiki, Monaco |
| LaTeX | KaTeX | MathJax for broader syntax |
| Mermaid | Mermaid dynamic import | Worker rendering, SVG cache |
| 长消息导航 | DOM anchors | virtual list, IntersectionObserver |
| 自动测试 | pytest, Vite build | Playwright, promptfoo, DeepEval |
| 可观测性 | model run metadata | OpenTelemetry, Langfuse, Phoenix |

## 8. 结论

当前系统已经从“把聊天记录直接拼给 API”的简单模式，升级为一个可控的本地会话上下文系统。它能在无状态模型 API 之上维护有状态 chatbox 体验，并支持长对话、文件、多模态图片、重试、恢复、分叉、上下文预览和审计复盘。

下一阶段最值得投入的是三件事：

1. 用真实 tokenizer 和语义检索提升长对话质量。
2. 用虚拟滚动和重组件懒渲染降低前端长会话性能压力。
3. 用数据库、对象存储和可观测性把本地服务推向更生产化的形态。

