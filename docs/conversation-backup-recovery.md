# Conversation Backup and Recovery

更新时间：2026-06-10

本项目的本地会话数据默认存放在 `data/conversations`。实际运行目录以 `/api/version` 返回的 `data_dir` 为准；native 部署可用 `deploy/native/status.sh` 查看当前后端 commit、PID、启动时间和数据目录。

## 备份前检查

```bash
cd /data/projects/llm-council
bash deploy/native/status.sh
curl -fsS http://127.0.0.1:8001/api/version
```

确认：

- `commit` 是预期版本。
- `pid` 是当前正在服务的后端进程。
- `data_dir` 是将要备份的 conversations 目录。

## 标准备份

先停后端，避免复制到写入中的 JSON 或附件目录：

```bash
cd /data/projects/llm-council
bash deploy/native/stop-backend.sh
```

创建带时间戳的备份目录，并复制 conversations 数据和附件：

```bash
BACKUP_ROOT="/data/projects/llm-council/backups"
STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_ROOT/conversations-$STAMP"
rsync -a data/conversations/ "$BACKUP_ROOT/conversations-$STAMP/"
```

重启并确认版本：

```bash
bash deploy/native/start-backend.sh
bash deploy/native/status.sh
```

## 恢复流程

恢复前先保留当前状态，避免覆盖后无法回滚：

```bash
cd /data/projects/llm-council
bash deploy/native/stop-backend.sh

SAFETY_ROOT="/data/projects/llm-council/backups"
SAFETY_STAMP="$(date +%Y%m%d-%H%M%S)-before-restore"
mkdir -p "$SAFETY_ROOT/conversations-$SAFETY_STAMP"
rsync -a data/conversations/ "$SAFETY_ROOT/conversations-$SAFETY_STAMP/"
```

用目标备份替换数据目录：

```bash
RESTORE_DIR="/data/projects/llm-council/backups/conversations-YYYYMMDD-HHMMSS"
rsync -a --delete "$RESTORE_DIR/" data/conversations/
```

重启并检查：

```bash
bash deploy/native/start-backend.sh
bash deploy/native/status.sh
pytest tests/test_conversation_export_api.py tests/test_conversation_metadata_api.py -q
```

## 导出 smoke

恢复后至少检查一个历史会话能导出 Markdown：

```bash
curl -fsS http://127.0.0.1:8001/api/conversations | python3 -m json.tool | head -80
curl -fsS -D /tmp/export.headers   "http://127.0.0.1:8001/api/conversations/<conversation-id>/export?format=markdown"   -o /tmp/conversation-export.md
sed -n '1,80p' /tmp/export.headers
sed -n '1,120p' /tmp/conversation-export.md
```

期望：

- HTTP 200。
- `Content-Disposition` 同时包含 ASCII `filename=` 和 UTF-8 `filename*=`。
- Markdown 包含标题、`Conversation summary`、`Transcript` 和 turn 内容。
- 中断或旧 schema 会话输出可读状态，不返回 500。

## 兼容性要求

恢复旧 JSON 时，列表、详情和导出都必须对缺字段容忍：

- 缺失 `updated_at`、`title_source`、`title_locked` 等 metadata 时，列表仍可显示。
- assistant `stage1`、`stage2`、`stage3` 缺失或为 `null` 时，导出应输出可读 incomplete/interrupted 状态。
- 附件目录应随 conversations 一起备份和恢复，避免 branch 或历史图片引用断链。
