 Corpus / RAG / Eval 做成 research workflow 里的正式基础设施层，直接服务 search_corpus → select_papers → extract_cards → review，并且支持通过 API 显式切换检索策略。这个方向和你 PRD 里给出的 Phase 2 目标是一致的：统一入库、结构化 RagResult、candidate papers、dedup、rerank

 