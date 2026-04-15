/**
 * AgentPanel — Multi-agent switcher with manual run & re-plan.
 *
 * Design: "Agent Cards with Status Halo"
 * - Role-specific color halos (left border + icon tint)
 * - Staggered card entrance animation
 * - Run button with progress state
 * - Re-plan drawer with spring expand
 */

import { useState, useEffect } from 'react';
import type { AgentDescriptor } from '../types/phase34';

const AGENT_META: Record<string, { accent: string; bg: string; label: string; desc: string }> = {
  supervisor: {
    accent: '#1e3a5f', bg: '#eff6ff',
    label: 'Supervisor', desc: 'Orchestrates workflow routing & mode switching',
  },
  planner: {
    accent: '#6d28d9', bg: '#f5f3ff',
    label: 'Planner', desc: 'Builds search plans from brief',
  },
  retriever: {
    accent: '#065f46', bg: '#ecfdf5',
    label: 'Retriever', desc: 'Corpus search & paper retrieval',
  },
  analyst: {
    accent: '#92400e', bg: '#fffbeb',
    label: 'Analyst', desc: 'Evidence synthesis & claim checking',
  },
  reviewer: {
    accent: '#be123c', bg: '#fff1f2',
    label: 'Reviewer', desc: 'Feedback generation & revision triggers',
  },
};

const ROLE_ICONS: Record<string, React.FC<{ className?: string }>> = {
  supervisor: ({ className }) => (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/>
    </svg>
  ),
  planner: ({ className }) => (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01"/>
    </svg>
  ),
  retriever: ({ className }) => (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
    </svg>
  ),
  analyst: ({ className }) => (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/>
    </svg>
  ),
  reviewer: ({ className }) => (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
    </svg>
  ),
};

interface Props {
  taskId?: string | null;
  workspaceId?: string | null;
  onAgentRun?: (agentId: string, result: unknown) => void;
}

export function AgentPanel({ taskId, workspaceId, onAgentRun }: Props) {
  const [agents, setAgents] = useState<AgentDescriptor[]>([]);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [runningId, setRunningId] = useState<string | null>(null);
  const [runResult, setRunResult] = useState<unknown>(null);
  const [replanOpen, setReplanOpen] = useState(false);
  const [replanReason, setReplanReason] = useState('');
  const [replanLoading, setReplanLoading] = useState(false);

  useEffect(() => {
    fetch('/api/v1/agents')
      .then(r => r.json())
      .then(d => setAgents(d.items ?? []))
      .catch(() => {});
  }, []);

  const runAgent = async (agent: AgentDescriptor) => {
    if (!taskId) return;
    setRunningId(agent.agent_id);
    setRunResult(null);
    const resolvedWorkspaceId = workspaceId ?? taskId;
    try {
      const res = await fetch('/api/v1/agents/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace_id: resolvedWorkspaceId,
          task_id: taskId,
          role: agent.role,
          inputs: {},
        }),
      });
      const data = await res.json();
      setRunResult(data);
      onAgentRun?.(agent.agent_id, data);
    } catch (e) {
      setRunResult({ error: String(e) });
    } finally {
      setRunningId(null);
    }
  };

  const handleReplan = async () => {
    if (!taskId || !replanReason.trim()) return;
    setReplanLoading(true);
    const resolvedWorkspaceId = workspaceId ?? taskId;
    try {
      const res = await fetch('/api/v1/agents/replan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workspace_id: resolvedWorkspaceId,
          task_id: taskId,
          trigger: 'user',          // backend maps string → ReplanTrigger
          reason: replanReason,
          target_stage: 'search_plan',
        }),
      });
      const data = await res.json();
      setRunResult(data);
      setReplanOpen(false);
      setReplanReason('');
    } catch (e) {
      setRunResult({ error: String(e) });
    } finally {
      setReplanLoading(false);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      {/* Agent cards */}
      <div className="flex flex-col gap-2">
        {agents.map((agent, i) => {
          const meta = AGENT_META[agent.agent_id] ?? { accent: '#374151', bg: '#f9fafb', label: agent.role, desc: agent.description };
          const isExpanded = expandedId === agent.agent_id;
          const isRunning = runningId === agent.agent_id;
          const Icon = ROLE_ICONS[agent.agent_id] ?? (({ className }) => <span className={className}>✦</span>);

          return (
            <div
              key={agent.agent_id}
              className="relative rounded-xl border overflow-hidden transition-all duration-200"
              style={{
                borderColor: isExpanded ? meta.accent : '#e5e0da',
                animationDelay: `${i * 60}ms`,
              }}
            >
              {/* Left accent bar */}
              <div
                className="absolute left-0 top-0 bottom-0 w-0.5 rounded-l-xl"
                style={{ backgroundColor: meta.accent }}
              />

              <button
                onClick={() => setExpandedId(isExpanded ? null : agent.agent_id)}
                className="w-full text-left pl-3 pr-3 py-3 flex items-center gap-3 cursor-pointer transition-colors duration-150 hover:bg-black/[0.02]"
              >
                {/* Icon */}
                <div
                  className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
                  style={{ backgroundColor: meta.bg }}
                >
                  <span style={{ color: meta.accent }}>
                    <Icon className="w-4 h-4" />
                  </span>
                </div>

                {/* Text */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="text-[11px] font-semibold text-stone-800">{meta.label}</p>
                    {agent.supported_skills.length > 0 && (
                      <span className="text-[8px] rounded-full px-1.5 py-0.5 font-medium"
                        style={{ backgroundColor: `${meta.accent}15`, color: meta.accent }}>
                        {agent.supported_skills.length} skills
                      </span>
                    )}
                  </div>
                  <p className="text-[9px] text-stone-400 leading-tight mt-0.5 truncate">{meta.desc}</p>
                </div>

                {/* Status indicator */}
                {isRunning && (
                  <svg className="w-4 h-4 animate-spin flex-shrink-0" style={{ color: meta.accent }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                    <path d="M12 2v4m0 12v4m-8-10H2m20 0h-2M6.34 6.34L4.93 4.93m14.14 14.14l-1.41-1.41M6.34 17.66l-1.41 1.41"/>
                  </svg>
                )}
                {!isRunning && (
                  <svg className={`w-4 h-4 flex-shrink-0 text-stone-300 transition-transform duration-200 ${isExpanded ? 'rotate-180' : ''}`}
                    viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                    <path d="M19 9l-7 7-7-7"/>
                  </svg>
                )}
              </button>

              {/* Expanded actions */}
              {isExpanded && (
                <div className="border-t px-3 pb-3 pt-2" style={{ borderColor: `${meta.accent}20` }}>
                  <div className="flex gap-1.5 mb-2">
                    <button
                      onClick={() => runAgent(agent)}
                      disabled={!taskId || isRunning}
                      className={`
                        flex-1 py-2 rounded-lg text-[10px] font-semibold text-white
                        transition-all duration-150 cursor-pointer flex items-center justify-center gap-1.5
                        ${(!taskId || isRunning)
                          ? 'opacity-40 cursor-not-allowed'
                          : 'hover:opacity-90 active:scale-95'
                        }
                      `}
                      style={{ backgroundColor: meta.accent }}
                    >
                      {isRunning ? (
                        <>
                          <svg className="w-3 h-3 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                            <path d="M12 2v4m0 12v4m-8-10H2m20 0h-2M6.34 6.34L4.93 4.93m14.14 14.14l-1.41-1.41M6.34 17.66l-1.41 1.41"/>
                          </svg>
                          Running…
                        </>
                      ) : '▶ Run'}
                    </button>
                    {agent.supported_skills.length > 0 && (
                      <button
                        className="flex-1 py-2 rounded-lg border text-[10px] font-semibold transition-all duration-150 cursor-pointer hover:bg-black/[0.03]"
                        style={{ borderColor: `${meta.accent}40`, color: meta.accent }}
                      >
                        Skills ({agent.supported_skills.length})
                      </button>
                    )}
                  </div>
                  {!taskId && (
                    <p className="text-[9px] text-stone-400 text-center">
                      Select a task to enable run
                    </p>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Divider */}
      <div className="flex items-center gap-2">
        <div className="flex-1 h-px bg-gradient-to-r from-transparent via-stone-200 to-transparent" />
        <span className="text-[9px] text-stone-400 font-medium uppercase tracking-widest">or</span>
        <div className="flex-1 h-px bg-gradient-to-r from-transparent via-stone-200 to-transparent" />
      </div>

      {/* Re-plan */}
      <button
        onClick={() => setReplanOpen(o => !o)}
        className={`
          flex items-center justify-between px-4 py-2.5 rounded-xl border
          text-[11px] font-medium transition-all duration-200 cursor-pointer
          ${replanOpen
            ? 'border-stone-400 bg-stone-50 text-stone-700'
            : 'border-dashed border-stone-300 text-stone-500 hover:border-stone-400 hover:text-stone-600'
          }
        `}
      >
        <span className="flex items-center gap-2">
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
          </svg>
          Trigger Re-plan
        </span>
        <svg className={`w-3.5 h-3.5 transition-transform duration-200 ${replanOpen ? 'rotate-180' : ''}`}
          viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
          <path d="M19 9l-7 7-7-7"/>
        </svg>
      </button>

      {replanOpen && (
        <div className="flex flex-col gap-2">
          <textarea
            value={replanReason}
            onChange={e => setReplanReason(e.target.value)}
            placeholder="e.g. 'coverage gap in section 3 — need more recent papers on RAG fusion'"
            rows={3}
            className="w-full px-3 py-2.5 rounded-xl border border-stone-200 text-[11px] text-stone-700
              resize-none transition-all duration-150
              focus:outline-none focus:border-stone-400 focus:ring-1 focus:ring-stone-200
              placeholder-stone-300"
            style={{ fontFamily: 'inherit' }}
          />
          <button
            onClick={handleReplan}
            disabled={replanLoading || !replanReason.trim() || !taskId}
            className={`
              py-2.5 rounded-xl text-[11px] font-semibold text-white
              transition-all duration-150 cursor-pointer
              disabled:opacity-40 disabled:cursor-not-allowed
              hover:opacity-90 active:scale-95
            `}
            style={{ backgroundColor: '#1e3a5f' }}
          >
            {replanLoading ? 'Replanning…' : '↺ Trigger Re-plan'}
          </button>
        </div>
      )}

      {/* Run result */}
      {!!runResult && (
        <div className="rounded-xl border border-stone-200 bg-stone-50 p-3">
          <p className="text-[9px] font-semibold text-stone-400 uppercase tracking-widest mb-1.5">Result</p>
          <pre className="text-[9px] text-stone-600 overflow-x-auto leading-relaxed">
            {(typeof runResult === 'object' ? JSON.stringify(runResult, null, 2) : String(runResult)).slice(0, 500)}
            {typeof runResult === 'object' && JSON.stringify(runResult).length > 500 ? '…' : ''}
          </pre>
        </div>
      )}
    </div>
  );
}
