# 4.7

### A. 面向前端/产品的外部 API

这些是真正给前端或用户调用的。

#### 1. 任务入口

`POST /api/v1/research/tasks`

用途：创建一个研究任务
支持输入：

- `query`
- `topic`
- `goal`
- `mode`（single\_paper / survey / related\_work）
- `sources`（arxiv / local / pdf\_upload）
- `workspace_id`
- `output_format`

返回：

- `task_id`
- `workspace_id`
- `status`

#### 2. 查询任务状态

`GET /api/v1/research/tasks/{task_id}`

返回：

- `status`
- `current_stage`
- `node_statuses`
- `artifacts`
- `warnings`
- `summary`

这个接口一定要把 `node_statuses` 带上，因为当前 demo 最大问题之一就是 trace 不真实。repo 总结也明确建议在 `/tasks/{id}` 直接返回 `node_statuses`。

#### 3. 任务事件流

`GET /api/v1/research/tasks/{task_id}/events`

用途：SSE
事件类型建议：

- `task_started`
- `node_started`
- `tool_called`
- `artifact_created`
- `warning`
- `node_finished`
- `task_finished`
- `task_failed`

#### 4. 取消任务

`POST /api/v1/research/tasks/{task_id}/cancel`

---

### B. 面向 workspace 的资源 API

这些是长期研究记忆的核心。

#### 5. 创建工作区

`POST /api/v1/workspaces`

#### 6. 查询工作区

`GET /api/v1/workspaces/{workspace_id}`

#### 7. 查询工作区产物

`GET /api/v1/workspaces/{workspace_id}/artifacts`

产物包括：

- brief
- plans
- paper cards
- matrix
- review log
- report drafts

#### 8. 获取某类 paper cards

`GET /api/v1/workspaces/{workspace_id}/paper-cards`

#### 9. 获取 comparison matrix

`GET /api/v1/workspaces/{workspace_id}/comparison-matrix`

#### 10. 获取最终报告

`GET /api/v1/workspaces/{workspace_id}/report`

---

### C. 面向输入源的 API

#### 11. 上传 PDF

`POST /api/v1/uploads/pdf`

这条很重要，因为 repo 总结明确指出当前前端上传 PDF 走的是 `file.text()`，不是真正二进制 PDF 上传。这个坑你应该尽早填。

#### 12. 注册本地文档目录

`POST /api/v1/corpus/local-folders`

#### 13. 单篇 arXiv 拉取

`POST /api/v1/corpus/arxiv/fetch`

#### 14. 触发 ingest / indexing

`POST /api/v1/corpus/index`

---

### D. 面向研究阶段的调试 / 半自动 API

#### 15. 生成 research brief

`POST /api/v1/research/clarify`

#### 16. 生成 search plan

`POST /api/v1/research/search-plan`

#### 17. 执行 search

`POST /api/v1/research/search`

#### 18. 抽取单篇 paper card

`POST /api/v1/research/paper-card`

#### 19. 生成 comparison matrix

`POST /api/v1/research/compare`

#### 20. reviewer 审查

`POST /api/v1/research/review`

#### 21. 生成报告

`POST /api/v1/research/report`

这些接口的价值在于：
你可以在前期先“半自动跑 workflow”，每个阶段都能单独调试，不必每次都跑整条长链。

---

### E. 面向平台底座的内部 API

#### 22. 统一工具调用

`POST /internal/tools/invoke`

用途：所有 graph 节点调用工具都走这里
这就是把 repo 总结里提到的“不要节点直接 import 业务函数”落地。

#### 23. trace 查询

`GET /internal/traces/{task_id}`

#### 24. eval 运行

`POST /internal/evals/run`

#### 25. regression gate

`POST /internal/evals/gate`