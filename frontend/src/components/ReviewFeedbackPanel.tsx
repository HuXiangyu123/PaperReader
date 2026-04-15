/**
 * ReviewFeedbackPanel — Issue viewer with severity hierarchy.
 *
 * Design: "Scholarly Review"
 * - Severity-coded left borders with color halos
 * - Coverage gap chips with animated entrance
 * - Revision action pills with priority dots
 * - Compact mode for sidebar
 */

import { useState, useEffect } from 'react';
import type { ReviewFeedback, ReviewSeverity } from '../types/phase34';

const SEVERITY_META: Record<ReviewSeverity, { color: string; bg: string; label: string; dot: string }> = {
  blocker: { color: '#991b1b', bg: '#fef2f2', dot: '#dc2626', label: 'Blocker' },
  error:   { color: '#9a3412', bg: '#fff7ed', dot: '#ea580c', label: 'Error'   },
  warning: { color: '#854d0e', bg: '#fefce8', dot: '#ca8a04', label: 'Warning' },
  info:    { color: '#075985', bg: '#f0f9ff', dot: '#0284c7', label: 'Info'    },
};

const PASS_META: Record<string, { color: string; bg: string; icon: React.FC<{ className?: string }> }> = {
  true: {
    color: '#166534', bg: '#f0fdf4',
    icon: ({ className }) => (
      <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
        <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
      </svg>
    ),
  },
  false: {
    color: '#991b1b', bg: '#fef2f2',
    icon: ({ className }) => (
      <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
        <path d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"/>
      </svg>
    ),
  },
};

interface Props {
  taskId?: string | null;
  reviewFeedback?: ReviewFeedback | null;
  compact?: boolean;
}

export function ReviewFeedbackPanel({ taskId, reviewFeedback: propFeedback, compact = false }: Props) {
  const [feedback, setFeedback] = useState<ReviewFeedback | null>(propFeedback ?? null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (propFeedback !== undefined) { setFeedback(propFeedback); return; }
    if (!taskId) return;
    setLoading(true);
    setError(null);
    fetch(`/tasks/${taskId}/review`)
      .then(r => r.json())
      .then((d: { review_feedback: ReviewFeedback | null }) => {
        setFeedback(d.review_feedback ?? null);
      })
      .catch(() => setError('Failed to load review'))
      .finally(() => setLoading(false));
  }, [taskId, propFeedback]);

  if (loading) return (
    <div className="flex flex-col gap-2">
      <div className="h-10 rounded-xl bg-stone-100 animate-pulse" />
      <div className="h-16 rounded-xl bg-stone-100 animate-pulse" />
    </div>
  );

  if (error) return <p className="text-xs text-rose-600">{error}</p>;
  if (!taskId) return (
    <div className="flex flex-col items-center justify-center py-10 text-stone-400 gap-2">
      <svg className="w-8 h-8 opacity-40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1} strokeLinecap="round" strokeLinejoin="round">
        <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
      </svg>
      <p className="text-[11px]">Select a task to see review</p>
    </div>
  );

  if (!feedback) return (
    <div className="flex flex-col items-center justify-center py-10 text-stone-400 gap-2">
      <svg className="w-8 h-8 opacity-40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1} strokeLinecap="round" strokeLinejoin="round">
        <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
      </svg>
      <p className="text-[11px]">No review feedback yet</p>
    </div>
  );

  const passKey = String(feedback.passed);
  const passMeta = PASS_META[passKey] ?? PASS_META['false'];
  const PassIcon = passMeta.icon;

  const blockerCount = feedback.issues.filter(i => i.severity === 'blocker').length;
  const errorCount   = feedback.issues.filter(i => i.severity === 'error'  ).length;
  const warnCount    = feedback.issues.filter(i => i.severity === 'warning').length;

  return (
    <div className="flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ backgroundColor: passMeta.bg }}>
            <span style={{ color: passMeta.color }} className="w-5 h-5">
              <PassIcon className="w-5 h-5" />
            </span>
          </div>
          <div>
            <p className="text-[11px] font-semibold" style={{ color: passMeta.color }}>
              {feedback.passed ? 'Review Passed' : 'Review Failed'}
            </p>
            <p className="text-[9px] text-stone-400 font-mono">{feedback.review_id.slice(0, 12)}</p>
          </div>
        </div>
        {feedback.created_at && (
          <p className="text-[9px] text-stone-400">
            {new Date(feedback.created_at).toLocaleTimeString()}
          </p>
        )}
      </div>

      {/* Summary pills */}
      {(blockerCount > 0 || errorCount > 0 || warnCount > 0 || feedback.coverage_gaps.length > 0) && (
        <div className="flex flex-wrap gap-1.5">
          {blockerCount > 0 && (
            <span className="flex items-center gap-1 text-[10px] font-semibold px-2.5 py-1 rounded-full"
              style={{ backgroundColor: SEVERITY_META.blocker.bg, color: SEVERITY_META.blocker.color }}>
              <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: SEVERITY_META.blocker.dot }} />
              {blockerCount} blocker
            </span>
          )}
          {errorCount > 0 && (
            <span className="flex items-center gap-1 text-[10px] font-semibold px-2.5 py-1 rounded-full"
              style={{ backgroundColor: SEVERITY_META.error.bg, color: SEVERITY_META.error.color }}>
              <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: SEVERITY_META.error.dot }} />
              {errorCount} error
            </span>
          )}
          {warnCount > 0 && (
            <span className="flex items-center gap-1 text-[10px] font-semibold px-2.5 py-1 rounded-full"
              style={{ backgroundColor: SEVERITY_META.warning.bg, color: SEVERITY_META.warning.color }}>
              <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: SEVERITY_META.warning.dot }} />
              {warnCount} warning
            </span>
          )}
          {feedback.coverage_gaps.length > 0 && (
            <span className="text-[10px] font-semibold px-2.5 py-1 rounded-full bg-stone-100 text-stone-600">
              {feedback.coverage_gaps.length} coverage gap{feedback.coverage_gaps.length > 1 ? 's' : ''}
            </span>
          )}
        </div>
      )}

      {/* Summary text */}
      {feedback.summary && !compact && (
        <p className="text-[11px] text-stone-600 leading-relaxed bg-stone-50 rounded-xl px-4 py-3 border border-stone-200">
          {feedback.summary}
        </p>
      )}

      {/* Issues */}
      {!compact && feedback.issues.length > 0 && (
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <div className="w-0.5 h-4 rounded-full bg-stone-300" />
            <span className="text-[10px] font-semibold uppercase tracking-widest text-stone-400">
              Issues ({feedback.issues.length})
            </span>
          </div>
          {feedback.issues.map((issue) => {
            const sev = SEVERITY_META[issue.severity];
            return (
              <div
                key={issue.issue_id}
                className="flex gap-0 rounded-xl border overflow-hidden"
                style={{ borderColor: `${sev.dot}25` }}
              >
                {/* Left severity bar */}
                <div className="w-1 flex-shrink-0" style={{ backgroundColor: sev.dot }} />
                <div className="flex-1 p-3" style={{ backgroundColor: sev.bg }}>
                  <div className="flex items-center gap-1.5 mb-1">
                    <span className="text-[9px] font-bold uppercase tracking-wide" style={{ color: sev.color }}>
                      {sev.label}
                    </span>
                    <span className="text-[9px] text-stone-400 rounded-full bg-white/60 px-1.5 py-0.5">
                      {issue.category.replace(/_/g, ' ')}
                    </span>
                  </div>
                  <p className="text-[11px] text-stone-700 leading-relaxed">{issue.summary}</p>
                  {issue.target && (
                    <p className="text-[9px] text-stone-400 mt-1">→ {issue.target}</p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Coverage gaps (compact) */}
      {compact && feedback.coverage_gaps.length > 0 && (
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <div className="w-0.5 h-4 rounded-full bg-amber-400" />
            <span className="text-[10px] font-semibold uppercase tracking-widest text-stone-400">
              Coverage Gaps
            </span>
          </div>
          {feedback.coverage_gaps.map((gap, i) => (
            <div key={i} className="flex gap-2 items-start">
              <div className="w-1.5 h-1.5 rounded-full bg-amber-400 mt-1.5 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                {gap.missing_topics.length > 0 && (
                  <p className="text-[10px] text-stone-600 truncate">
                    topics: {gap.missing_topics.slice(0, 3).join(', ')}
                  </p>
                )}
                {gap.missing_papers.length > 0 && (
                  <p className="text-[10px] text-stone-500 truncate">
                    papers: {gap.missing_papers.slice(0, 2).join(', ')}
                  </p>
                )}
                {gap.note && (
                  <p className="text-[9px] text-stone-400 mt-0.5">{gap.note}</p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Revision actions */}
      {!compact && feedback.revision_actions.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-2">
            <div className="w-0.5 h-4 rounded-full bg-[#1e3a5f]" />
            <span className="text-[10px] font-semibold uppercase tracking-widest text-stone-400">
              Revision Actions
            </span>
          </div>
          {feedback.revision_actions.map((action, i) => (
            <div
              key={i}
              className="flex items-center gap-2.5 px-3 py-2 rounded-xl bg-white border border-stone-200"
            >
              {/* Priority dot */}
              <div className={`w-2 h-2 rounded-full flex-shrink-0 ${
                action.priority >= 3 ? 'bg-rose-500' :
                action.priority === 2 ? 'bg-amber-400' : 'bg-stone-300'
              }`} />

              <span className="text-[9px] font-bold rounded-lg px-2 py-0.5 flex-shrink-0"
                style={{ backgroundColor: '#eff6ff', color: '#1e3a5f' }}>
                {action.action_type.replace(/_/g, ' ')}
              </span>
              <span className="text-[10px] text-stone-600 flex-1 truncate">{action.target}</span>
              <span className="text-[9px] text-stone-400 flex-shrink-0">#{action.priority}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
