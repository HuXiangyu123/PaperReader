/**
 * TraceTimeline — Execution trace viewer.
 *
 * Design: "Execution Ledger"
 * - Vertical timeline with dot markers
 * - Node runs as primary, tool runs as secondary (indented)
 * - Duration heat map (green → amber → red)
 * - Collapsible sections with smooth expand
 */

import { useState, useEffect } from 'react';
import type { TaskTraceResponse } from '../types/phase34';

const STATUS_META: Record<string, { color: string; dot: string; label: string }> = {
  succeeded: { color: '#16a34a', dot: '#22c55e', label: 'Succeeded' },
  failed:    { color: '#dc2626', dot: '#ef4444', label: 'Failed'    },
  running:   { color: '#2563eb', dot: '#3b82f6', label: 'Running'   },
  pending:   { color: '#9ca3af', dot: '#d1d5db', label: 'Pending'   },
  skipped:   { color: '#d97706', dot: '#f59e0b', label: 'Skipped'   },
};

const EVENT_META: Record<string, { color: string; label: string }> = {
  task_created:       { color: '#6366f1', label: 'Created'         },
  node_started:       { color: '#3b82f6', label: 'Node Started'     },
  node_finished:      { color: '#22c55e', label: 'Node Finished'   },
  node_failed:        { color: '#ef4444', label: 'Node Failed'     },
  tool_started:       { color: '#8b5cf6', label: 'Tool Started'    },
  tool_finished:      { color: '#10b981', label: 'Tool Finished'  },
  tool_failed:        { color: '#f87171', label: 'Tool Failed'    },
  artifact_saved:     { color: '#06b6d4', label: 'Artifact Saved'  },
  review_generated:   { color: '#f59e0b', label: 'Review'         },
  warning:            { color: '#eab308', label: 'Warning'         },
  task_completed:     { color: '#22c55e', label: 'Task Completed'  },
  task_failed:        { color: '#ef4444', label: 'Task Failed'     },
  stage_changed:      { color: '#6366f1', label: 'Stage Changed'   },
};

function formatDuration(ms?: number): string {
  if (ms == null) return '—';
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
}

function getDurationColor(ms?: number): string {
  if (ms == null) return '#d1d5db';
  if (ms < 500)   return '#22c55e';
  if (ms < 2000)  return '#eab308';
  return '#ef4444';
}

interface Props {
  taskId?: string | null;
  compact?: boolean;
}

export function TraceTimeline({ taskId, compact = false }: Props) {
  const [trace, setTrace] = useState<TaskTraceResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set(['nodes']));

  useEffect(() => {
    if (!taskId) return;
    setLoading(true);
    setError(null);
    fetch(`/tasks/${taskId}/trace`)
      .then(r => r.json())
      .then((d: TaskTraceResponse) => setTrace(d))
      .catch(() => setError('Failed to load trace'))
      .finally(() => setLoading(false));
  }, [taskId]);

  const toggleSection = (section: string) => {
    setExpandedSections(prev => {
      const next = new Set(prev);
      if (next.has(section)) next.delete(section);
      else next.add(section);
      return next;
    });
  };

  if (!taskId) return (
    <div className="flex flex-col items-center justify-center py-10 text-stone-400 gap-2">
      <svg className="w-8 h-8 opacity-40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1} strokeLinecap="round" strokeLinejoin="round">
        <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/>
      </svg>
      <p className="text-[11px]">No task selected</p>
    </div>
  );

  if (loading) return (
    <div className="flex flex-col gap-2">
      <div className="h-8 rounded-lg bg-stone-100 animate-pulse" />
      <div className="h-6 rounded-lg bg-stone-100 animate-pulse" />
      <div className="h-6 rounded-lg bg-stone-100 animate-pulse" />
    </div>
  );

  if (error) return <p className="text-xs text-rose-600">{error}</p>;

  const nodeRuns = trace?.node_runs ?? [];
  const toolRuns = trace?.tool_runs ?? [];
  const events   = trace?.events ?? [];

  const totalDuration = nodeRuns.reduce((sum, r) => sum + (r.duration_ms ?? 0), 0);
  const succeededCount = nodeRuns.filter(r => r.status === 'succeeded').length;
  const failedCount    = nodeRuns.filter(r => r.status === 'failed').length;

  if (nodeRuns.length === 0 && toolRuns.length === 0 && events.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-10 text-stone-400 gap-2">
        <svg className="w-8 h-8 opacity-40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1} strokeLinecap="round" strokeLinejoin="round">
          <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01"/>
        </svg>
        <p className="text-[11px]">No trace data yet</p>
        <p className="text-[9px] text-stone-300">Runs will appear as tasks execute</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Summary bar */}
      <div className="flex items-center gap-3 px-3 py-2 rounded-xl bg-white border border-stone-200">
        <div className="flex items-center gap-1.5">
          <span className="text-[9px] font-semibold text-stone-400 uppercase tracking-widest">Nodes</span>
          <span className="text-[11px] font-bold text-stone-700">{nodeRuns.length}</span>
        </div>
        <div className="w-px h-4 bg-stone-200" />
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-emerald-400" />
          <span className="text-[11px] font-semibold text-emerald-600">{succeededCount}</span>
        </div>
        {failedCount > 0 && (
          <>
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-red-400" />
              <span className="text-[11px] font-semibold text-red-500">{failedCount}</span>
            </div>
          </>
        )}
        <div className="ml-auto flex items-center gap-1.5">
          <span className="text-[9px] text-stone-400">Total</span>
          <span className="text-[11px] font-semibold text-stone-600">{formatDuration(totalDuration)}</span>
        </div>
      </div>

      {/* Node runs */}
      {!compact && nodeRuns.length > 0 && (
        <div>
          <button
            onClick={() => toggleSection('nodes')}
            className="flex items-center gap-2 w-full text-left cursor-pointer group mb-2"
          >
            <div className="w-0.5 h-4 rounded-full bg-stone-300 group-hover:bg-[#1e3a5f] transition-colors" />
            <span className="text-[10px] font-semibold uppercase tracking-widest text-stone-400 group-hover:text-stone-600 transition-colors">
              Nodes ({nodeRuns.length})
            </span>
            <svg className={`w-3 h-3 text-stone-300 transition-transform duration-200 ${expandedSections.has('nodes') ? 'rotate-180' : ''}`}
              viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path d="M19 9l-7 7-7-7"/>
            </svg>
          </button>
          {expandedSections.has('nodes') && (
            <div className="flex flex-col gap-1.5 pl-3 border-l border-stone-200">
              {nodeRuns.map((run, i) => {
                const meta = STATUS_META[run.status] ?? STATUS_META.pending;
                return (
                  <div key={run.run_id} className="flex items-center gap-2.5 group">
                    <div className="relative flex flex-col items-center">
                      <div className="w-2.5 h-2.5 rounded-full border-2 border-white shadow-sm z-10"
                        style={{ backgroundColor: meta.dot }} />
                      {i < nodeRuns.length - 1 && (
                        <div className="w-px flex-1 bg-stone-200 mt-0.5" />
                      )}
                    </div>
                    <div className="flex-1 min-w-0 flex items-center gap-2">
                      <span className="text-[10px] font-medium text-stone-700 truncate">{run.node_name}</span>
                      <span
                        className="text-[9px] px-1.5 py-0.5 rounded-full font-medium flex-shrink-0"
                        style={{ backgroundColor: `${meta.color}15`, color: meta.color }}
                      >
                        {meta.label}
                      </span>
                      {run.duration_ms != null && (
                        <span
                          className="text-[9px] font-mono ml-auto flex-shrink-0"
                          style={{ color: getDurationColor(run.duration_ms) }}
                        >
                          {formatDuration(run.duration_ms)}
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Tool runs */}
      {!compact && toolRuns.length > 0 && (
        <div>
          <button
            onClick={() => toggleSection('tools')}
            className="flex items-center gap-2 w-full text-left cursor-pointer group mb-2"
          >
            <div className="w-0.5 h-4 rounded-full bg-stone-300 group-hover:bg-[#1e3a5f] transition-colors" />
            <span className="text-[10px] font-semibold uppercase tracking-widest text-stone-400 group-hover:text-stone-600 transition-colors">
              Tools ({toolRuns.length})
            </span>
            <svg className={`w-3 h-3 text-stone-300 transition-transform duration-200 ${expandedSections.has('tools') ? 'rotate-180' : ''}`}
              viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path d="M19 9l-7 7-7-7"/>
            </svg>
          </button>
          {expandedSections.has('tools') && (
            <div className="flex flex-col gap-1 pl-6 border-l border-stone-100">
              {toolRuns.map(run => {
                const meta = STATUS_META[run.status] ?? STATUS_META.pending;
                return (
                  <div key={run.tool_run_id} className="flex items-center gap-2 py-0.5">
                    <div className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: meta.dot }} />
                    <span className="text-[10px] font-mono text-stone-600 truncate flex-1">{run.tool_name}</span>
                    {run.duration_ms != null && (
                      <span className="text-[9px] font-mono text-stone-400 flex-shrink-0">
                        {formatDuration(run.duration_ms)}
                      </span>
                    )}
                    <span className="text-[9px] px-1.5 py-0.5 rounded-full font-medium"
                      style={{ backgroundColor: `${meta.color}10`, color: meta.color }}>
                      {meta.label}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Recent events */}
      {events.length > 0 && (
        <div>
          <button
            onClick={() => toggleSection('events')}
            className="flex items-center gap-2 w-full text-left cursor-pointer group mb-2"
          >
            <div className="w-0.5 h-4 rounded-full bg-stone-300 group-hover:bg-[#1e3a5f] transition-colors" />
            <span className="text-[10px] font-semibold uppercase tracking-widest text-stone-400 group-hover:text-stone-600 transition-colors">
              Events ({events.length})
            </span>
            <svg className={`w-3 h-3 text-stone-300 transition-transform duration-200 ${expandedSections.has('events') ? 'rotate-180' : ''}`}
              viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path d="M19 9l-7 7-7-7"/>
            </svg>
          </button>
          {expandedSections.has('events') && (
            <div className="flex flex-col gap-1 pl-3 border-l border-stone-200">
              {events.slice(-15).map((evt) => {
                const meta = EVENT_META[evt.event_type] ?? { color: '#9ca3af', label: evt.event_type };
                return (
                  <div key={evt.event_id} className="flex items-start gap-2 py-0.5">
                    <div className="w-1.5 h-1.5 rounded-full mt-1.5 flex-shrink-0" style={{ backgroundColor: meta.color }} />
                    <span className="text-[9px] text-stone-500 leading-tight flex-1">{meta.label}</span>
                    <span className="text-[8px] text-stone-400 font-mono flex-shrink-0">
                      {new Date(evt.ts).toLocaleTimeString()}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
