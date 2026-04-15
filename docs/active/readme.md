#基于2026-4-7的架构设计


##需要复现简历要求

技术栈： Python ｜ LangGraph ｜ FastAPI ｜ RAG ｜ Multi-Agent ｜ MCP ｜ Skills
项目简介： 面向科研选题调研、论文精读与综述写作场景，设计并实现闭环式 Research Workflow Agent。系统支持需求澄清、检索规划、论文获取、单篇抽取、跨文献对比、综述生成与审查修订，能够结合本地论文库与在线学术检索结果生成带引用的结构化调研结果与综述初稿。
核心工作：
•
设计并实现 Scope → Search → Read → Synthesize → Review → Write 的科研工作流，将单轮文献问答升级为面向科研调研场景的闭环式 Agent 系统。
•
基于 LangGraph 构建多 Agent 协作框架，拆分 Planner、Retriever、Analyst、Reviewer 等角色，实现需求澄清、检索规划、论文抽取、结果审查与报告生成等模块化分工。
•
构建面向科研任务的 Skills / MCP 工具层，封装论文检索、PDF 获取、本地文档读取、结构化 Paper Card 抽取、跨论文对比、综述大纲生成等能力，提升工作流可扩展性与工具复用能力。
•
设计 Research Workspace 机制，沉淀 research brief、query plan、paper cards、comparison matrix、review log 与report draft 等中间产物，支持多轮调研任务的持续迭代与上下文复用。
•
引入基于 Reviewer 的反思与补检索回路，对覆盖不足、证据薄弱与结论过满等问题进行审查，并驱动二轮检索与综述修订，提升结果完整性、结构化程度与引用可靠性。


#文档

##api.md
设计的api接口


##prd.md

完整workflow的模块架构拆解文档