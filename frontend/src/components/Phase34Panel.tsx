/**
 * Phase34Panel — unified Phase 3-4 control surface.
 *
 * Design: "Scholarly Precision"
 * - Dot-grid texture background
 * - Sliding tab indicator with spring animation
 * - Staggered fade-in for content panels
 * - Thin rule dividers, serif headings, micro-animations
 */

import { useState, useEffect, useRef } from 'react';
import { ConfigPanel } from './ConfigPanel';
import { AgentPanel } from './AgentPanel';
import { SkillPalette } from './SkillPalette';
import { TraceTimeline } from './TraceTimeline';
import { ReviewFeedbackPanel } from './ReviewFeedbackPanel';
import type { Phase3_4Tab } from '../types/phase34';

const TABS: { id: Phase3_4Tab; label: string; accent: string; icon: React.FC<{ className?: string }> }[] = [
  {
    id: 'config',
    label: 'Config',
    accent: '#1e3a5f',
    icon: ({ className }) => (
      <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
        <path d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/>
        <path d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
      </svg>
    ),
  },
  {
    id: 'agents',
    label: 'Agents',
    accent: '#6d28d9',
    icon: ({ className }) => (
      <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
        <path d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z"/>
      </svg>
    ),
  },
  {
    id: 'skills',
    label: 'Skills',
    accent: '#065f46',
    icon: ({ className }) => (
      <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
        <path d="M13 10V3L4 14h7v7l9-11h-7z"/>
      </svg>
    ),
  },
  {
    id: 'review',
    label: 'Review',
    accent: '#92400e',
    icon: ({ className }) => (
      <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
        <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
      </svg>
    ),
  },
  {
    id: 'trace',
    label: 'Trace',
    accent: '#be123c',
    icon: ({ className }) => (
      <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
        <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01"/>
      </svg>
    ),
  },
];

interface Props {
  taskId?: string | null;
  workspaceId?: string;
}

export function Phase34Panel({ taskId, workspaceId }: Props) {
  const [tab, setTab] = useState<Phase3_4Tab>('agents');
  const tabRef = useRef<HTMLDivElement>(null);
  const [indicatorStyle, setIndicatorStyle] = useState({ left: 0, width: 0 });

  const activeTab = TABS.find(t => t.id === tab)!;

  // Update sliding indicator
  useEffect(() => {
    const container = tabRef.current;
    if (!container) return;
    const activeBtn = container.querySelector<HTMLButtonElement>(`[data-tab="${tab}"]`);
    if (!activeBtn) return;
    const containerRect = container.getBoundingClientRect();
    const btnRect = activeBtn.getBoundingClientRect();
    setIndicatorStyle({
      left: btnRect.left - containerRect.left,
      width: btnRect.width,
    });
  }, [tab]);

  return (
    <div
      className="flex-1 min-h-0 flex flex-col rounded-2xl border border-stone-300 overflow-hidden shadow-sm"
      style={{
        background: '#fafaf8',
        backgroundImage: `radial-gradient(circle, #d4cfc9 1px, transparent 1px)`,
        backgroundSize: '18px 18px',
      }}
    >
      {/* Header */}
      <div className="relative flex-shrink-0 border-b border-stone-200/80 bg-white/80 backdrop-blur-sm px-4 pt-3 pb-0">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            {/* Decorative rule */}
            <div className="w-1 h-5 rounded-full" style={{ backgroundColor: activeTab.accent }} />
            <div>
              <h2 className="text-[13px] font-semibold leading-tight text-stone-800"
                style={{ fontFamily: 'Georgia, "Nimbus Roman No9 L", "Book Antiqua", Palatino, serif' }}>
                Phase 3-4
              </h2>
              <p className="text-[10px] text-stone-400 leading-tight">
                {taskId
                  ? <span className="font-mono">{taskId.slice(0, 8)}…</span>
                  : <span>No task active</span>
                }
              </p>
            </div>
          </div>
          {/* Active badge */}
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full border"
            style={{ borderColor: `${activeTab.accent}30`, backgroundColor: `${activeTab.accent}0a` }}>
            <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ backgroundColor: activeTab.accent }} />
            <span className="text-[9px] font-semibold uppercase tracking-widest" style={{ color: activeTab.accent }}>
              {tab}
            </span>
          </div>
        </div>

        {/* Tab bar with sliding indicator */}
        <div ref={tabRef} className="relative flex gap-0.5">
          {/* Sliding indicator */}
          <div
            className="absolute bottom-0 h-0.5 rounded-t-full transition-all duration-300 ease-out"
            style={{
              left: indicatorStyle.left,
              width: indicatorStyle.width,
              backgroundColor: activeTab.accent,
            }}
          />
          {TABS.map(t => (
            <button
              key={t.id}
              data-tab={t.id}
              onClick={() => setTab(t.id)}
              className={`
                relative flex items-center gap-1.5 px-3 pb-2.5 pt-1.5
                text-[11px] font-medium transition-colors duration-150
                cursor-pointer select-none whitespace-nowrap
                ${tab === t.id ? '' : 'text-stone-400 hover:text-stone-600'}
              `}
              style={tab === t.id ? { color: t.accent } : {}}
            >
              <t.icon className="w-3.5 h-3.5 flex-shrink-0" />
              <span>{t.label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4">
        <div
          key={tab}
          className="animate-fadeIn"
          style={{ animationDuration: '240ms', animationTimingFunction: 'cubic-bezier(0.16, 1, 0.3, 1)' }}
        >
          {tab === 'config' && <ConfigPanel />}
          {tab === 'agents' && <AgentPanel taskId={taskId} workspaceId={workspaceId} />}
          {tab === 'skills' && <SkillPalette taskId={taskId} workspaceId={workspaceId} />}
          {tab === 'review' && <ReviewFeedbackPanel taskId={taskId} compact />}
          {tab === 'trace' && <TraceTimeline taskId={taskId} />}
        </div>
      </div>

      <style>{`
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(6px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        .animate-fadeIn {
          animation: fadeIn 240ms cubic-bezier(0.16, 1, 0.3, 1) both;
        }
      `}</style>
    </div>
  );
}
