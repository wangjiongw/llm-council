# Regression Matrix

更新时间：2026-06-10

本文记录当前项目的标准回归命令。选择最小能证明当前改动的层级；发布前跑完整矩阵。

## 快速验收

适用：文档、窄范围测试补充、单个前端组件或后端接口的小改动。

后端导出/版本/metadata：

```bash
pytest tests/test_conversation_export_api.py tests/test_version_api.py tests/test_conversation_metadata_api.py -q
```

后端 stream/fork：

```bash
pytest tests/test_quick_stream.py tests/test_resume_stream.py tests/test_conversation_fork_api.py -q
```

前端核心组件：

```bash
cd frontend
npm test -- ChatInterface.test.jsx RichMarkdown.test.jsx LLMSettingsModal.test.jsx
```

前端会话管理 / 输入工作流：

```bash
cd frontend
npm test -- ChatInterface.test.jsx Sidebar.test.jsx
```

前端长会话 / 富内容效率：

```bash
cd frontend
npm test -- ChatInterface.test.jsx RichMarkdown.test.jsx
```

## 提交前验收

适用：任何会影响发送、导出、渲染、部署诊断或主页面状态的代码改动。

```bash
pytest tests/test_conversation_export_api.py tests/test_version_api.py tests/test_conversation_metadata_api.py -q
pytest tests/test_quick_stream.py tests/test_resume_stream.py tests/test_conversation_fork_api.py -q
cd frontend
npm test -- ChatInterface.test.jsx RichMarkdown.test.jsx LLMSettingsModal.test.jsx
npm test -- ChatInterface.test.jsx Sidebar.test.jsx
npm run lint
npm run build
```

如果改动会影响侧栏、会话管理或搜索，再补：

```bash
cd frontend
npm test -- Sidebar.test.jsx
cd ..
pytest tests/test_conversation_search_api.py -q
```

## 发布前验收

适用：准备 native 部署、合并可靠性批次、修改 e2e smoke 或部署脚本。

```bash
cd /data/projects/llm-council
bash deploy/native/stop-backend.sh
bash deploy/native/start-backend.sh
bash deploy/native/status.sh

cd frontend
E2E_BASE_URL=http://127.0.0.1:18080 npm run test:e2e
```

当前 Playwright smoke 覆盖：

- app shell 和核心 API contract。
- 左侧历史搜索打开命中会话。
- 主题切换后主聊天控件仍可见。
- 普通 Council / Quick 发送失败恢复草稿，成功发送清空草稿。
- fork branch Council / Quick 发送失败恢复草稿，成功发送只追加一个 user turn。
- 100+ turn 移动端长会话：虚拟列表、远距离搜索命中、Bottom 导航和 Quick stream 追加可见。
- 公式和 Mermaid 在真实消息视图中渲染出非空节点且无 error placeholder。

验证当前源码但不重启 native/nginx 时，先启动临时 Vite server，再指定 `E2E_BASE_URL`：

```bash
cd frontend
npm run dev -- --host 127.0.0.1 --port 18180
E2E_BASE_URL=http://127.0.0.1:18180 npx playwright test tests/e2e/acceptance-smoke.spec.js -g "100 turn mobile|formula and Mermaid"
```

## 备份/恢复验收

恢复 conversations 数据后运行：

```bash
bash deploy/native/status.sh
pytest tests/test_conversation_export_api.py tests/test_conversation_metadata_api.py -q
curl -fsS -D /tmp/export.headers   "http://127.0.0.1:8001/api/conversations/<conversation-id>/export?format=markdown"   -o /tmp/conversation-export.md
```

详见 [conversation-backup-recovery.md](conversation-backup-recovery.md)。

## 失败处理

- 先看 `/api/version` 或 `deploy/native/status.sh`，确认没有旧后端进程。
- 后端失败先缩小到 pytest 单文件，再检查 `data/conversations` fixture 或本地数据。
- 前端组件失败先跑目标 Vitest 文件，再跑 lint/build。
- Playwright 失败先查看 `frontend/test-results/` 的 screenshot 和 `error-context.md`，确认是否是测试数据污染或部署服务未刷新。
