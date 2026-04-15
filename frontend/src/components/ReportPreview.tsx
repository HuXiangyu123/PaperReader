import { useEffect, useState } from 'react';
import type { SourceType, Task } from '../types/task';
import { MarkdownRenderer } from './MarkdownRenderer';
import { ResearchFollowupForm } from './ResearchFollowupForm';

interface Props {
  taskId: string | null;
  isDone: boolean;
  sourceType?: SourceType | null;
  onTaskCreated: (taskId: string, sourceType: SourceType) => void;
}

interface JsonSectionProps {
  title: string;
  data: unknown;
}

function JsonSection({ title, data }: JsonSectionProps) {
  return (
    <section className="mb-5 rounded-xl border border-stone-200 bg-stone-50 p-4">
      <h3 className="mb-3 text-sm font-semibold text-stone-800">{title}</h3>
      <pre className="overflow-x-auto rounded-lg bg-stone-900 px-4 py-3 text-[12px] leading-6 text-stone-100">
        {JSON.stringify(data, null, 2)}
      </pre>
    </section>
  );
}

export function ReportPreview({ taskId, isDone, sourceType, onTaskCreated }: Props) {
  const [task, setTask] = useState<Task | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!taskId || !isDone) {
      setTask(null);
      return;
    }

    setLoading(true);
    fetch(`/tasks/${taskId}`)
      .then(r => r.json())
      .then((data: Task) => {
        setTask(data);
      })
      .catch(() =>
        setTask({
          task_id: taskId,
          status: 'failed',
          created_at: '',
          source_type: sourceType ?? undefined,
          error: 'Failed to load result',
        }),
      )
      .finally(() => setLoading(false));
  }, [isDone, sourceType, taskId]);

  const effectiveSourceType = task?.source_type ?? sourceType ?? null;
  const isResearchTask = effectiveSourceType === 'research';

  if (!taskId) {
    return (
      <div className="rounded-xl border border-dashed border-stone-300 bg-white/80 p-8 text-center text-stone-500 shadow-sm">
        <p className="mb-1 text-lg font-display text-stone-600">No task selected</p>
        <p className="text-sm">Start a paper report or research workflow to see the output here.</p>
      </div>
    );
  }

  if (!isDone) {
    return (
      <div className="rounded-xl border border-stone-300 bg-white p-8 text-center text-stone-500 shadow-sm">
        <p className="text-sm animate-pulse">
          {isResearchTask
            ? 'Research brief and search plan will appear when the workflow finishes…'
            : 'Report will appear when the pipeline finishes…'}
        </p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="rounded-xl border border-stone-300 bg-white p-8 shadow-sm">
        <p className="text-sm text-stone-500">Loading…</p>
      </div>
    );
  }

  if (isResearchTask) {
    return (
      <div className="max-h-[600px] overflow-y-auto rounded-xl border border-stone-300 bg-white p-8 shadow-sm">
        <div className="mb-4 flex flex-wrap items-center gap-2 text-xs">
          <span className="rounded-full bg-stone-100 px-2.5 py-1 text-stone-700">
            mode: research
          </span>
          {task?.current_stage && (
            <span className="rounded-full bg-stone-100 px-2.5 py-1 text-stone-700">
              stage: {task.current_stage}
            </span>
          )}
        </div>

        {task?.brief && <JsonSection title="Research Brief" data={task.brief} />}
        {task?.search_plan && <JsonSection title="Search Plan" data={task.search_plan} />}

        {task?.brief?.needs_followup && !task?.search_plan && (
          <>
            <div className="mb-5 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
              当前 brief 仍需要人工补充澄清，因此 search plan 暂停在 `clarify` 阶段。
            </div>
            <ResearchFollowupForm brief={task.brief} onTaskCreated={onTaskCreated} />
          </>
        )}

        {task?.error && (
          <div className="mb-5 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900">
            {task.error}
          </div>
        )}

        {!task?.brief && (
          <div className="rounded-lg border border-stone-200 bg-stone-50 p-4 text-sm text-stone-600">
            {task?.error || task?.result_markdown || 'No research result'}
          </div>
        )}
      </div>
    );
  }

  const activeMarkdown =
    task?.report_mode === 'full'
      ? task?.full_markdown || task?.result_markdown
      : task?.draft_markdown || task?.result_markdown;

  return (
    <div className="max-h-[600px] overflow-y-auto rounded-xl border border-stone-300 bg-white p-8 shadow-sm">
      {task && (
        <div className="mb-4 flex flex-wrap items-center gap-2 text-xs">
          <span className="rounded-full bg-stone-100 px-2.5 py-1 text-stone-700">
            mode: {task.report_mode ?? 'draft'}
          </span>
          <span className="rounded-full bg-stone-100 px-2.5 py-1 text-stone-700">
            paper: {task.paper_type ?? 'regular'}
          </span>
        </div>
      )}
      {task?.paper_type === 'survey' && task?.followup_hints && task.followup_hints.length > 0 && (
        <div className="mb-5 rounded-lg border border-stone-200 bg-stone-50 p-4 text-sm text-stone-700">
          <p className="mb-2 font-medium">建议追问</p>
          <ul className="list-disc pl-5 space-y-1">
            {task.followup_hints.map((hint, idx) => (
              <li key={idx}>{hint}</li>
            ))}
          </ul>
        </div>
      )}
      <MarkdownRenderer content={activeMarkdown || task?.error || 'No result'} />
    </div>
  );
}
