/**
 * SkillPalette — Skill marketplace with grid layout.
 *
 * Design: "Skill Grid with Detail Drawer"
 * - Masonry-inspired 2-col grid with hover lift
 * - Backend-type color coding
 * - Detail panel slides in from right
 * - Run with loading state
 */

import { useState, useEffect } from 'react';
import type { SkillMeta, SkillManifest } from '../types/phase34';

const BACKEND_META: Record<string, { color: string; bg: string; label: string }> = {
  local_graph: { color: '#1e3a5f', bg: '#eff6ff', label: 'Graph' },
  local_function: { color: '#065f46', bg: '#ecfdf5', label: 'Function' },
  mcp_prompt: { color: '#6d28d9', bg: '#f5f3ff', label: 'MCP Prompt' },
  mcp_toolchain: { color: '#92400e', bg: '#fffbeb', label: 'MCP Chain' },
};

const SKILL_ICONS: Record<string, React.FC<{ className?: string; style?: React.CSSProperties }>> = {
  research_lit_scan: ({ className, style }) => (
    <svg className={className} style={style} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 15.804 7.5 7.5 0 0015.803 5.803z"/>
      <circle cx="10" cy="10" r="2"/>
      <path d="M21 21l-2-2"/>
    </svg>
  ),
  paper_plan_builder: ({ className, style }) => (
    <svg className={className} style={style} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
    </svg>
  ),
  citation_verifier: ({ className, style }) => (
    <svg className={className} style={style} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/>
    </svg>
  ),
};

interface Props {
  taskId?: string | null;
  workspaceId?: string;
}

export function SkillPalette({ taskId, workspaceId }: Props) {
  const [skills, setSkills] = useState<SkillMeta[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [manifest, setManifest] = useState<SkillManifest | null>(null);
  const [loadingManifest, setLoadingManifest] = useState(false);
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState<unknown>(null);

  useEffect(() => {
    fetch('/api/v1/skills')
      .then(r => r.json())
      .then(d => setSkills(d.items ?? []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!selectedId) { setManifest(null); return; }
    setLoadingManifest(true);
    fetch(`/api/v1/skills/${selectedId}`)
      .then(r => r.json())
      .then(d => setManifest(d.manifest ?? null))
      .catch(() => setManifest(null))
      .finally(() => setLoadingManifest(false));
  }, [selectedId]);

  const runSkill = async (skillId: string) => {
    if (!taskId) return;
    setRunning(true);
    setRunResult(null);
    try {
      const res = await fetch('/api/v1/skills/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ skill_id: skillId, task_id: taskId, workspace_id: workspaceId }),
      });
      const data = await res.json();
      setRunResult(data);
    } catch (e) {
      setRunResult({ error: String(e) });
    } finally {
      setRunning(false);
    }
  };

  const selectedMeta = skills.find(s => s.skill_id === selectedId);
  const selectedBackend = selectedMeta ? BACKEND_META[selectedMeta.backend] : null;

  return (
    <div className="flex flex-col gap-3">
      {/* Grid */}
      {skills.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-10 text-stone-400">
          <svg className="w-8 h-8 mb-2 opacity-40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1} strokeLinecap="round" strokeLinejoin="round">
            <path d="M13 10V3L4 14h7v7l9-11h-7z"/>
          </svg>
          <p className="text-[11px]">No skills discovered</p>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-2">
          {skills.map(skill => {
            const backend = BACKEND_META[skill.backend] ?? { color: '#374151', bg: '#f9fafb', label: skill.backend };
            const icon = SKILL_ICONS[skill.skill_id];
            const isSelected = selectedId === skill.skill_id;
            const iconEl: React.ReactNode = icon ? (icon({ className: 'w-5 h-5' }) as React.ReactNode) : null;
            return (
              <button
                key={skill.skill_id}
                onClick={() => setSelectedId(isSelected ? null : skill.skill_id)}
                className={`
                  relative flex flex-col items-start gap-2 p-3 rounded-xl border
                  transition-all duration-200 cursor-pointer overflow-hidden
                  group
                  ${isSelected
                    ? 'border-2 shadow-sm'
                    : 'border border-stone-200 hover:border-stone-300 hover:shadow-sm hover:-translate-y-0.5'
                  }
                `}
                style={isSelected
                  ? { borderColor: backend.color, backgroundColor: backend.bg }
                  : { backgroundColor: '#fafaf8' }
                }
              >
                {/* Icon */}
                <div
                  className="w-9 h-9 rounded-lg flex items-center justify-center transition-transform duration-200 group-hover:scale-110"
                  style={{ backgroundColor: `${backend.color}12` }}
                >
                  {iconEl !== null
                    ? <span style={{ color: backend.color }}>{iconEl}</span>
                    : <span className="text-sm" style={{ color: backend.color }}>✦</span>
                  }
                </div>

                {/* Content */}
                <div className="w-full text-left">
                  <p className="text-[10px] font-semibold leading-tight text-stone-800 line-clamp-2">
                    {skill.name}
                  </p>
                  <p className="text-[9px] text-stone-400 mt-0.5 leading-tight">
                    {backend.label}
                  </p>
                </div>

                {/* Tags */}
                {skill.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1 w-full">
                    {skill.tags.slice(0, 2).map(tag => (
                      <span
                        key={tag}
                        className="text-[8px] rounded-full px-1.5 py-0.5 font-medium leading-none"
                        style={{ backgroundColor: `${backend.color}15`, color: backend.color }}
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
              </button>
            );
          })}
        </div>
      )}

      {/* Detail panel */}
      <DetailPanel
        manifest={manifest}
        loadingManifest={loadingManifest}
        selectedBackend={selectedBackend}
        selectedMeta={selectedMeta}
        running={running}
        taskId={taskId}
        onRun={runSkill}
        onClose={() => setSelectedId(null)}
      />

      {/* Run result */}
      {!!runResult && (
        <div className="rounded-xl border border-stone-200 bg-stone-50 p-3">
          <p className="text-[9px] font-semibold text-stone-400 uppercase tracking-widest mb-1.5">Result</p>
          <pre className="text-[9px] text-stone-600 overflow-x-auto leading-relaxed">
            {JSON.stringify(runResult).slice(0, 500)}
          </pre>
        </div>
      )}
    </div>
  );
}

// ─── Detail panel sub-component ─────────────────────────────────────────────────
// Extracted to avoid type widening caused by Record<string, unknown> in SkillManifest

type BackendMeta = { color: string; bg: string; label: string } | null;

function DetailPanel({
  manifest,
  loadingManifest,
  selectedBackend,
  selectedMeta,
  running,
  taskId,
  onRun,
  onClose,
}: {
  manifest: SkillManifest | null;
  loadingManifest: boolean;
  selectedBackend: BackendMeta;
  selectedMeta: SkillMeta | undefined;
  running: boolean;
  taskId: string | null | undefined;
  onRun: (skillId: string) => void;
  onClose: () => void;
}) {
  if (loadingManifest) {
    return (
      <div className="rounded-xl border p-4" style={{ borderColor: '#e5e0da', backgroundColor: '#fafaf8' }}>
        <div className="flex flex-col gap-2">
          <div className="h-4 w-32 rounded bg-stone-100 animate-pulse" />
          <div className="h-3 w-48 rounded bg-stone-100 animate-pulse" />
          <div className="h-8 w-full rounded bg-stone-100 animate-pulse mt-2" />
        </div>
      </div>
    );
  }

  if (!manifest) {
    return null;
  }

  const schemaStr = Object.keys(manifest.input_schema).length > 0
    ? JSON.stringify(manifest.input_schema, null, 2).slice(0, 200)
    : '';

  return (
    <div className="rounded-xl border p-4" style={{ borderColor: selectedBackend ? `${selectedBackend.color}30` : '#e5e0da', backgroundColor: '#fafaf8' }}>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-[12px] font-semibold text-stone-800">{manifest.name}</p>
          <p className="text-[10px] text-stone-500 mt-1 leading-relaxed">{manifest.description}</p>
        </div>
        <button
          onClick={onClose}
          className="text-stone-400 hover:text-stone-600 transition-colors cursor-pointer p-0.5"
        >
          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <path d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>
      </div>

      <div className="flex flex-wrap gap-1.5 mt-2">
        {selectedBackend && (
          <span className="text-[9px] rounded-full px-2.5 py-1 font-semibold"
            style={{ backgroundColor: `${selectedBackend.color}15`, color: selectedBackend.color }}>
            {selectedBackend.label}
          </span>
        )}
        <span className="text-[9px] rounded-full px-2.5 py-1 font-semibold bg-stone-100 text-stone-600">
          agent: {manifest.default_agent}
        </span>
        {manifest.output_artifact_type && (
          <span className="text-[9px] rounded-full px-2.5 py-1 font-semibold bg-blue-50 text-blue-600">
            → {manifest.output_artifact_type}
          </span>
        )}
      </div>

      {manifest.backend_ref && (
        <div className="px-2.5 py-1.5 rounded-lg bg-stone-100 border border-stone-200 mt-2">
          <p className="text-[9px] text-stone-400 mb-0.5">backend_ref</p>
          <p className="text-[9px] font-mono text-stone-600 truncate">{manifest.backend_ref}</p>
        </div>
      )}

      {schemaStr && (
        <div className="mt-2">
          <p className="text-[9px] text-stone-400 mb-1">input_schema</p>
          <pre className="text-[8px] text-stone-600 bg-stone-50 rounded-lg p-2 overflow-x-auto leading-relaxed">
            {schemaStr}
          </pre>
        </div>
      )}

      <button
        onClick={() => selectedMeta && onRun(selectedMeta.skill_id)}
        disabled={running || !taskId}
        className={`
          w-full py-2.5 rounded-xl text-[11px] font-semibold text-white
          transition-all duration-150 cursor-pointer flex items-center justify-center gap-2
          disabled:opacity-40 disabled:cursor-not-allowed
          ${taskId ? 'hover:opacity-90 active:scale-95' : ''}
        `}
        style={{ backgroundColor: selectedBackend?.color ?? '#374151' }}
      >
        {running ? (
          <>
            <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path d="M12 2v4m0 12v4m-8-10H2m20 0h-2M6.34 6.34L4.93 4.93m14.14 14.14l-1.41-1.41M6.34 17.66l-1.41 1.41"/>
            </svg>
            Running…
          </>
        ) : taskId ? '▶ Run Skill' : 'Select a task first'}
      </button>
    </div>
  );
}
