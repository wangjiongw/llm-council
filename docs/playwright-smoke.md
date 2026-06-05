# Playwright Smoke Test

本项目新增一组轻量 Playwright smoke，用于验证真实部署页面。它和 `npm test` 分离，避免普通组件测试变慢。

## 覆盖范围

测试默认用 headless Chromium 访问已经部署好的服务：

```bash
http://127.0.0.1:18080
```

当前覆盖：

- 部署后的 app shell 能加载；
- `/api/conversations` 返回会话元数据契约；
- `/api/conversations/search` 返回搜索契约；
- 左侧历史搜索能显示结果并打开命中会话；
- 深色/浅色主题切换后主聊天控件仍可见。

这些 smoke 不调用 LLM provider，也不发送真实聊天消息。

## Headless 云服务器首次准备

在 `frontend/` 下安装 npm 依赖：

```bash
npm install
```

安装 Playwright Chromium 浏览器二进制：

```bash
npm run test:e2e:install
```

如果 Chromium 启动时报缺少系统库，需要在服务器上一次性安装 OS 依赖：

```bash
sudo npx playwright install-deps chromium
```

Ubuntu 上等价的包通常是：

```bash
sudo apt-get install libnspr4 libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
  libxkbcommon0 libasound2 libgbm1 libcairo2 libpango-1.0-0 libxcomposite1 \
  libxdamage1 libxrandr2 libatspi2.0-0
```

本机当前已安装 Playwright Chromium 到 `~/.cache/ms-playwright`，但实际运行还缺系统库，例如 `libnspr4.so`。

## 运行

确认 native 服务已经在 18080 运行后执行：

```bash
E2E_BASE_URL=http://127.0.0.1:18080 npm run test:e2e
```

如果以后在有图形界面的环境调试，可使用：

```bash
npm run test:e2e:headed
```

`test-results/`、`playwright-report/` 和 `.blob-report/` 是生成产物，已加入 gitignore。
