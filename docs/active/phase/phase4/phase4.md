Phase 4：最后才做更强的 multi-agent 和 MCP，skills

要做：

- `mcp_adapter.py`
- skills实现接口
- planner / retriever / analyst / reviewer 多角色拆分
- re-plan

##guide
你自己的 agent 想获得 skills 能力，推荐走这条路线：

直接兼容 Agent Skills 开放格式，不要自己再造一个“类似 skill 的 prompt 文件格式”。
实现“发现 → 解析 → 目录注入 → 激活 → 懒加载 → 资源执行”这 6 个环节。
默认支持多个主流 skill 根目录，至少兼容 .agents/skills 和 .claude/skills，这样市面上已有 skill 仓库能直接复用。
不要把 skills 当成“启动时一次性拼进 system prompt 的所有 markdown”。真正成熟的做法是 progressive disclosure：平时只给模型看 name + description 目录，命中后再加载完整 SKILL.md，需要时再读 scripts/、references/、assets/。官方 Agent Skills 文档就是这么设计的；Claude 和 Codex 也都明确用了这种按需加载思路。

你的 agent 想获得 MCP 配置与调用能力，推荐走这条路线：

先做 MCP client，不要一上来做 server。
先支持 stdio，再支持 remote HTTP。
先接 tools，再接 resources/prompts。
底层直接用官方 MCP SDK，不要自己手搓协议层。 MCP 官方现在有 TypeScript、Python、C#、Go 的 Tier 1 SDK

---

**保留 Phase 1 的外层** **`StateGraph / task / workspace / artifact / trace / eval`** **作为控制平面，把 Phase 4 的 multi-agent、MCP、skills 作为节点内部或节点上层的协作平面接进去。**

这和你文档里的两条主线是完全一致的：

一条是 Phase 1 明确要求“Keep the outer StateGraph as the control plane”，并且 `SearchPlanAgent` 是当时唯一真 agent，`Clarify` 和 `PaperCardExtractor` 都不是 agent。

另一条是 Phase 4 明确只补：
`mcp_adapter.py`、`planner / retriever / analyst / reviewer` 多角色拆分、`re-plan`，而不是推翻前面三阶段。

---