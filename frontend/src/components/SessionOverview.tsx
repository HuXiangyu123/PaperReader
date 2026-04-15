/**
 * SessionOverview — replaces GraphView in the left panel.
 *
 * Provides a dense, at-a-glance summary of the current research session:
 *   - Brief card (collapsible topic / goal / sub-questions)
 *   - Phase progress rail (Clarify → Plan → Search → Draft → Review)
 *   - Search stats (queries / recall / relevance counts)
 *   - Node stage detail (current running / last completed)
 *   - Quick actions (pause, terminate, export)
 *
 * Design: "Warm Editorial"
 *   - Stone / warm-white palette, serif headings
 *   - Compact cards with subtle dividers
 *   - Phase rail with animated progress dots
 */

import { useState } from 'react';
import type {
  NodeStatus,
  ResearchBrief,
  SearchPlan,
  SearchQueryGroup,
} from '../types/task';
import { getNodeLabel } from '../types/task';

// ─── Phase rail ────────────────────────────────────────────────────────────────

const PHASE_ORDER = [
  { key: 'clarify', label: 'Clarify', accent: '#7c3aed' },
  { key: 'search_plan', label: 'Plan', accent: '#0369a1' },
  { key: 'search', label: 'Search', accent: '#065f46' },
  { key: 'draft', label: 'Draft', accent: '#92400e' },
  { key: 'review', label: 'Review', accent: '#9f1239' },
  { key: 'persist_artifacts', label: 'Persist', accent: '#4c1d95' },
];

// Maps node name → phase key
function nodeToPhase(node: string): string {
  if (node === 'clarify') return 'clarify';
  if (node === 'search_plan') return 'search_plan';
  if (node.startsWith('search')) return 'search';
  if (node === 'draft_report' || node === 'repair_report') return 'draft';
  if (node === 'review') return 'review';
  if (node === 'persist_artifacts') return 'persist_artifacts';
  return '';
}

interface PhaseRailProps {
  currentNode: string | null;
  nodeStatuses: Record<string, NodeStatus>;
}

function PhaseRail({ currentNode, nodeStatuses: _nodeStatuses }: PhaseRailProps) {
  const activePhase = currentNode ? nodeToPhase(currentNode) : '';
  const currentIdx = PHASE_ORDER.findIndex(p => p.key === activePhase);

  return (
    <div className="px-4 py-3 border-b border-stone-200">
      <div className="flex items-center gap-0">
        {PHASE_ORDER.map((phase, idx) => {
          const isDone = idx < currentIdx;
          const isActive = idx === currentIdx;
          const { accent } = phase;

          return (
            <div key={phase.key} className="flex items-center">
              {/* Step dot */}
              <div className="flex flex-col items-center gap-0.5">
                <div
                  className="w-5 h-5 rounded-full border-2 flex items-center justify-center transition-all duration-300"
                  style={{
                    background: isDone ? accent : isActive ? accent : '#f5f5f4',
                    borderColor: isDone || isActive ? accent : '#d6d3d1',
                    boxShadow: isActive ? `0 0 0 3px ${accent}25` : 'none',
                  }}
                >
                  {isDone && (
                    <svg className="w-2.5 h-2.5 text-white" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round">
                      <path d="M2 6l3 3 5-5" />
                    </svg>
                  )}
                  {isActive && (
                    <div className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
                  )}
                </div>
                <span
                  className="text-[9px] font-medium whitespace-nowrap leading-none"
                  style={{ color: isDone || isActive ? accent : '#a8a29e' }}
                >
                  {phase.label}
                </span>
              </div>

              {/* Connector line */}
              {idx < PHASE_ORDER.length - 1 && (
                <div
                  className="h-0.5 flex-1 mx-1 mt-[-10px]"
                  style={{
                    background: isDone ? accent : '#e7e5e4',
                    minWidth: '12px',
                    maxWidth: '28px',
                  }}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Brief card ───────────────────────────────────────────────────────────────

function BriefCard({ brief }: { brief: ResearchBrief }) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className="border-b border-stone-200">
      <button
        onClick={() => setCollapsed(c => !c)}
        className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-stone-50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <svg className="w-3.5 h-3.5 text-stone-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round">
            <path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
          </svg>
          <span className="text-[11px] font-semibold text-stone-700">Brief</span>
        </div>
        <svg
          className={`w-3.5 h-3.5 text-stone-400 transition-transform duration-200 ${collapsed ? '' : 'rotate-180'}`}
          viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round"
        >
          <path d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {!collapsed && (
        <div className="px-4 pb-3 space-y-1.5">
          <p className="text-[11px] font-semibold text-stone-800 leading-snug">{brief.topic}</p>
          {brief.goal && (
            <p className="text-[10px] text-stone-600 leading-relaxed">{brief.goal}</p>
          )}
          {brief.sub_questions && brief.sub_questions.length > 0 && (
            <div className="space-y-0.5">
              <span className="text-[9px] font-semibold text-stone-400 uppercase tracking-wider">Sub-questions</span>
              {brief.sub_questions.map((q, i) => (
                <div key={i} className="flex items-start gap-1.5">
                  <span className="mt-0.5 w-1 h-1 rounded-full bg-stone-400 flex-shrink-0" />
                  <span className="text-[10px] text-stone-600 leading-snug">{q}</span>
                </div>
              ))}
            </div>
          )}
          {brief.focus_dimensions && brief.focus_dimensions.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1">
              {brief.focus_dimensions.map(d => (
                <span key={d} className="px-1.5 py-0.5 rounded bg-stone-100 text-[9px] text-stone-600 border border-stone-200">
                  {d}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Search stats ─────────────────────────────────────────────────────────────

function SearchStats({ plan }: { plan: SearchPlan | undefined }) {
  if (!plan) return null;

  const totalQueries = plan.query_groups.reduce(
    (acc: number, g: SearchQueryGroup) => acc + g.queries.length, 0
  );
  const expectedHits = plan.query_groups.reduce(
    (acc: number, g: SearchQueryGroup) => acc + (g.expected_hits ?? 0), 0
  );

  return (
    <div className="border-b border-stone-200 px-4 py-2.5">
      <div className="flex items-center gap-2 mb-1.5">
        <svg className="w-3.5 h-3.5 text-[#0369a1]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round">
          <path d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
        </svg>
        <span className="text-[11px] font-semibold text-stone-700">Search Plan</span>
        {plan.coverage_strategy && (
          <span className="ml-auto text-[9px] font-medium px-1.5 py-0.5 rounded bg-[#0369a1]/10 text-[#0369a1] border border-[#0369a1]/20">
            {plan.coverage_strategy}
          </span>
        )}
      </div>

      <div className="grid grid-cols-3 gap-2">
        <div className="text-center p-1.5 rounded-lg bg-stone-50 border border-stone-200">
          <div className="text-[15px] font-bold text-stone-800 leading-none">{totalQueries}</div>
          <div className="text-[9px] text-stone-500 mt-0.5">queries</div>
        </div>
        <div className="text-center p-1.5 rounded-lg bg-stone-50 border border-stone-200">
          <div className="text-[15px] font-bold text-stone-800 leading-none">{plan.query_groups.length}</div>
          <div className="text-[9px] text-stone-500 mt-0.5">groups</div>
        </div>
        <div className="text-center p-1.5 rounded-lg bg-stone-50 border border-stone-200">
          <div className="text-[15px] font-bold text-stone-800 leading-none">{expectedHits}</div>
          <div className="text-[9px] text-stone-500 mt-0.5">est. hits</div>
        </div>
      </div>

      {plan.query_groups.length > 0 && (
        <div className="mt-2 space-y-1">
          {plan.query_groups.slice(0, 3).map((g: SearchQueryGroup) => (
            <div key={g.group_id} className="flex items-start gap-1.5">
              <span className="mt-0.5 w-1 h-1 rounded-full bg-[#0369a1] flex-shrink-0" />
              <span className="text-[10px] text-stone-600 leading-snug truncate flex-1">{g.queries[0]}</span>
              {g.expected_hits && (
                <span className="text-[9px] text-stone-400 flex-shrink-0">~{g.expected_hits}</span>
              )}
            </div>
          ))}
          {plan.query_groups.length > 3 && (
            <span className="text-[9px] text-stone-400 pl-2.5">+{plan.query_groups.length - 3} more groups</span>
          )}
        </div>
      )}

      {plan.planner_warnings && plan.planner_warnings.length > 0 && (
        <div className="mt-2 space-y-0.5">
          {plan.planner_warnings.map((w, i) => (
            <div key={i} className="flex items-start gap-1.5">
              <svg className="w-3 h-3 text-amber-500 flex-shrink-0 mt-0.5" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
              </svg>
              <span className="text-[9px] text-amber-700 leading-snug">{w}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Node stage detail ─────────────────────────────────────────────────────────

const STATUS_META: Record<NodeStatus, { color: string; bg: string; dot: string; label: string }> = {
  pending:  { color: '#78716c', bg: '#f5f5f4', dot: '#d6d3d1', label: 'Pending' },
  running:  { color: '#1e40af', bg: '#eff6ff', dot: '#3b82f6', label: 'Running' },
  done:     { color: '#166534', bg: '#f0fdf4', dot: '#22c55e', label: 'Done' },
  failed:   { color: '#b91c1c', bg: '#fef2f2', dot: '#ef4444', label: 'Failed' },
  skipped:  { color: '#78716c', bg: '#f5f5f4', dot: '#a8a29e', label: 'Skipped' },
};

function NodeStageDetail({
  currentNode,
  nodeStatuses,
}: {
  currentNode: string | null;
  nodeStatuses: Record<string, NodeStatus>;
}) {
  // Find the last non-pending node (for "last completed" summary)
  const lastDone = Object.entries(nodeStatuses)
    .filter(([, s]) => s === 'done')
    .pop()?.[0] ?? null;

  const running = Object.entries(nodeStatuses)
    .filter(([, s]) => s === 'running')
    .pop()?.[0] ?? null;

  const active = running ?? currentNode ?? lastDone;
  const status = active ? (nodeStatuses[active] ?? 'pending') : 'pending';
  const meta = STATUS_META[status];

  return (
    <div className="border-b border-stone-200 px-4 py-2.5">
      <div className="flex items-center gap-2 mb-1.5">
        <svg className="w-3.5 h-3.5 text-stone-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round">
          <path d="M13 10V3L4 14h7v7l9-11h-7z"/>
        </svg>
        <span className="text-[11px] font-semibold text-stone-700">Stage</span>
      </div>

      <div
        className="flex items-center gap-2 px-3 py-2 rounded-lg border"
        style={{ borderColor: `${meta.dot}40`, background: meta.bg }}
      >
        <div
          className="w-2 h-2 rounded-full flex-shrink-0"
          style={{
            background: meta.dot,
            boxShadow: status === 'running' ? `0 0 0 3px ${meta.dot}30` : 'none',
            animation: status === 'running' ? 'pulse-dot 1.5s infinite' : 'none',
          }}
        />
        <div className="flex-1 min-w-0">
          <div className="text-[11px] font-semibold leading-tight" style={{ color: meta.color }}>
            {active ? getNodeLabel(active) : 'Idle'}
          </div>
          <div className="text-[9px]" style={{ color: meta.color, opacity: 0.7 }}>{meta.label}</div>
        </div>
      </div>

      {/* Done nodes list */}
      <div className="mt-2 space-y-0.5">
        {Object.entries(nodeStatuses)
          .filter(([, s]) => s === 'done')
          .map(([node]) => (
            <div key={node} className="flex items-center gap-1.5 pl-1">
              <svg className="w-2.5 h-2.5 text-[#22c55e] flex-shrink-0" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round">
                <path d="M2 6l3 3 5-5" />
              </svg>
              <span className="text-[9px] text-stone-500">{getNodeLabel(node)}</span>
            </div>
          ))}
      </div>

      <style>{`
        @keyframes pulse-dot {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      `}</style>
    </div>
  );
}

// ─── Quick actions ─────────────────────────────────────────────────────────────

function QuickActions({ taskId }: { taskId: string | null }) {
  const [confirmTerminate, setConfirmTerminate] = useState(false);

  if (!taskId) return null;

  const handleTerminate = () => {
    if (!confirmTerminate) {
      setConfirmTerminate(true);
      setTimeout(() => setConfirmTerminate(false), 3000);
      return;
    }
    fetch(`/tasks/${taskId}/terminate`, { method: 'POST' }).catch(() => {});
    setConfirmTerminate(false);
  };

  return (
    <div className="px-4 py-2.5">
      <div className="flex items-center gap-2">
        <button
          onClick={handleTerminate}
          className={`flex-1 text-[10px] font-medium px-3 py-1.5 rounded-lg border transition-all ${
            confirmTerminate
              ? 'bg-red-50 border-red-300 text-red-700'
              : 'bg-white border-stone-200 text-stone-600 hover:border-stone-300 hover:text-stone-800'
          }`}
        >
          {confirmTerminate ? '⚠ Confirm stop' : 'Stop task'}
        </button>
        <button
          onClick={() => window.open(`/tasks/${taskId}/export`, '_blank')}
          className="flex-1 text-[10px] font-medium px-3 py-1.5 rounded-lg border bg-white border-stone-200 text-stone-600 hover:border-stone-300 hover:text-stone-800 transition-all"
        >
          Export report
        </button>
      </div>
    </div>
  );
}

// ─── Main export ───────────────────────────────────────────────────────────────

interface Props {
  taskId: string | null;
  brief: import('../types/task').ResearchBrief | null;
  searchPlan: import('../types/task').SearchPlan | null;
  currentNode: string | null;
  nodeStatuses: Record<string, NodeStatus>;
}

export function SessionOverview({ taskId, brief, searchPlan, currentNode, nodeStatuses }: Props) {
  return (
    <div className="h-full flex flex-col bg-white overflow-hidden">
      {/* Header */}
      <div className="flex-shrink-0 px-4 py-3 border-b border-stone-200">
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-5 rounded-full bg-[#1e3a5f]" />
          <div>
            <h2
              className="text-[12px] font-semibold leading-tight text-stone-800"
              style={{ fontFamily: 'Georgia, serif' }}
            >
              Session
            </h2>
            <p className="text-[9px] text-stone-400 leading-tight">
              {taskId ? (
                <span className="font-mono">{taskId.slice(0, 8)}…</span>
              ) : (
                'No active task'
              )}
            </p>
          </div>
        </div>
      </div>

      {/* Scrollable body */}
      <div className="flex-1 overflow-y-auto divide-y divide-stone-100">
        {/* Phase rail */}
        <PhaseRail currentNode={currentNode} nodeStatuses={nodeStatuses} />

        {/* Brief */}
        {brief && <BriefCard brief={brief} />}

        {/* Search plan */}
        {searchPlan && <SearchStats plan={searchPlan} />}

        {/* Node stage */}
        <NodeStageDetail currentNode={currentNode} nodeStatuses={nodeStatuses} />

        {/* Quick actions */}
        <QuickActions taskId={taskId} />
      </div>
    </div>
  );
}
