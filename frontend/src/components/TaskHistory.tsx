import { useEffect, useState } from 'react';
import type { SourceType } from '../types/task';

interface TaskSummary {
  task_id: string;
  status: string;
  created_at: string;
  source_type?: SourceType;
}

interface Props {
  onSelect: (taskId: string, sourceType?: SourceType) => void;
  refreshTrigger: number;
}

export function TaskHistory({ onSelect, refreshTrigger }: Props) {
  const [tasks, setTasks] = useState<TaskSummary[]>([]);

  useEffect(() => {
    fetch('/tasks')
      .then(r => r.json())
      .then(setTasks)
      .catch(() => {});
  }, [refreshTrigger]);

  if (tasks.length === 0) return null;

  return (
    <div className="space-y-1">
      <h3 className="text-xs font-semibold text-stone-500 uppercase tracking-wider px-1">
        History
      </h3>
      {tasks.map(t => (
        <button
          key={t.task_id}
          onClick={() => onSelect(t.task_id, t.source_type)}
          className="w-full text-left px-3 py-2 rounded-lg border border-transparent hover:bg-white hover:border-stone-200 hover:shadow-sm transition-all text-sm"
        >
          <span className="text-stone-800 font-mono text-xs">{t.task_id.slice(0, 8)}…</span>
          {t.source_type && (
            <span className="ml-2 rounded-full bg-stone-100 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-stone-600">
              {t.source_type === 'research' ? 'research' : 'report'}
            </span>
          )}
          <span
            className={`ml-2 text-xs font-medium ${
              t.status === 'completed'
                ? 'text-[#166534]'
                : t.status === 'failed'
                  ? 'text-[#b91c1c]'
                  : t.status === 'running'
                    ? 'text-[#1e40af]'
                    : 'text-stone-500'
            }`}
          >
            {t.status}
          </span>
        </button>
      ))}
    </div>
  );
}
