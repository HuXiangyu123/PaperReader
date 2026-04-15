# Task API 全流程用例：生成报告并持久化到数据库

本文档演示一条完整接口链路：

1. 创建任务 `POST /tasks`
2. 轮询任务状态 `GET /tasks/{task_id}`
3. 获取最终结果 `GET /tasks/{task_id}/result`
4. 验证报告已落库，可长期回读

## 前置条件

- 已配置 `DATABASE_URL`
- 后端已启动，例如：

```bash
uvicorn src.api.app:app --reload --port 8000
```

## 1. 创建任务

请求：

```bash
curl -s http://127.0.0.1:8000/tasks \
  -H 'Content-Type: application/json' \
  -d '{
    "input_type": "arxiv",
    "input_value": "1706.03762",
    "report_mode": "draft"
  }'
```

示例响应：

```json
{
  "task_id": "8e870f80-4f24-4bfc-b49d-7a34aa84f4c7",
  "status": "pending",
  "workspace_id": "ws_8e870f80-4f2"
}
```

记下 `task_id`。

## 2. 轮询任务状态

请求：

```bash
curl -s http://127.0.0.1:8000/tasks/8e870f80-4f24-4bfc-b49d-7a34aa84f4c7
```

完成后，返回中会包含：

- `status: "completed"`
- `result_markdown`
- `persisted_to_db: true`
- `persisted_report_id`

典型片段：

```json
{
  "task_id": "8e870f80-4f24-4bfc-b49d-7a34aa84f4c7",
  "status": "completed",
  "source_type": "arxiv",
  "workspace_id": "ws_8e870f80-4f2",
  "persisted_to_db": true,
  "persisted_report_id": "rep_1e31f0a885b34d72",
  "result_markdown": "# Attention Is All You Need\n..."
}
```

## 3. 获取最终结果

请求：

```bash
curl -s http://127.0.0.1:8000/tasks/8e870f80-4f24-4bfc-b49d-7a34aa84f4c7/result
```

示例响应：

```json
{
  "task_id": "8e870f80-4f24-4bfc-b49d-7a34aa84f4c7",
  "report_id": "rep_1e31f0a885b34d72",
  "report_kind": "final_report",
  "source_type": "arxiv",
  "persisted": true,
  "result_markdown": "# Attention Is All You Need\n\n## 核心贡献\n...",
  "result_json": null,
  "updated_at": 1775871169.245807
}
```

这里的 `persisted: true` 表示结果已从数据库持久化层可读。

## 4. 数据库校验

可以直接查两张表：

```sql
SELECT task_id, status, workspace_id, persisted_report_id
FROM persisted_tasks
WHERE task_id = '8e870f80-4f24-4bfc-b49d-7a34aa84f4c7';
```

```sql
SELECT report_id, task_id, report_kind, source_type
FROM persisted_reports
WHERE task_id = '8e870f80-4f24-4bfc-b49d-7a34aa84f4c7';
```

## 说明

- `/tasks/{task_id}` 现在会优先读内存态，若当前进程内存中不存在，则回退到数据库快照。
- `/tasks/{task_id}/result` 会优先返回数据库中的持久化报告；如果数据库不可用，才回退到当前进程内存中的结果。
- 默认会为每个任务生成 `workspace_id`，方便后续把 report / review / trace 关联到同一工作区。
