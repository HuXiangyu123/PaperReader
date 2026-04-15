import { useState } from 'react';
import type { ReportMode, SourceType, WorkflowMode } from '../types/task';

interface Props {
  onTaskCreated: (taskId: string, sourceType: SourceType) => void;
  workflowMode: WorkflowMode;
  onWorkflowModeChange: (mode: WorkflowMode) => void;
}

export function TaskSubmitForm({
  onTaskCreated,
  workflowMode,
  onWorkflowModeChange,
}: Props) {
  const [input, setInput] = useState('');
  const [reportMode, setReportMode] = useState<ReportMode>('draft');
  const [loading, setLoading] = useState(false);

  const activeSourceType: SourceType = workflowMode === 'research' ? 'research' : 'arxiv';

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;

    setLoading(true);
    try {
      const payload = {
        input_type: workflowMode === 'research' ? 'research' : 'arxiv',
        input_value: input.trim(),
        source_type: activeSourceType,
        report_mode: reportMode,
      };

      const resp = await fetch('/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      onTaskCreated(data.task_id, activeSourceType);
      setInput('');
    } catch (err) {
      console.error('Failed to create task:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setLoading(true);
    try {
      const text = await file.text();
      const sourceType: SourceType = workflowMode === 'research' ? 'research' : 'pdf';
      const payload = {
        input_type: 'pdf',
        input_value: text,
        source_type: sourceType,
        report_mode: reportMode,
      };

      const resp = await fetch('/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      onTaskCreated(data.task_id, sourceType);
    } catch (err) {
      console.error('Failed to upload PDF:', err);
    } finally {
      setLoading(false);
      e.target.value = '';
    }
  };

  const inputPlaceholder =
    workflowMode === 'research'
      ? 'e.g. 最近多模态大模型在医学影像诊断方向有哪些进展？'
      : 'e.g. 1706.03762 or https://arxiv.org/abs/1706.03762';

  const inputLabel = workflowMode === 'research' ? 'Research Query' : 'arXiv ID or URL';
  const uploadLabel = workflowMode === 'research' ? 'Upload PDF / Notes' : 'Upload PDF';

  return (
    <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
      <div className="min-w-[220px]">
        <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-stone-600">
          Workflow
        </label>
        <div className="grid grid-cols-2 rounded-xl border border-stone-300 bg-white p-1 shadow-inner">
          <button
            type="button"
            onClick={() => onWorkflowModeChange('report')}
            disabled={loading}
            className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
              workflowMode === 'report'
                ? 'bg-[#1e3a5f] text-white shadow-sm'
                : 'text-stone-700 hover:bg-stone-100'
            }`}
          >
            Report
          </button>
          <button
            type="button"
            onClick={() => onWorkflowModeChange('research')}
            disabled={loading}
            className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
              workflowMode === 'research'
                ? 'bg-[#1e3a5f] text-white shadow-sm'
                : 'text-stone-700 hover:bg-stone-100'
            }`}
          >
            Research
          </button>
        </div>
      </div>

      <div className="min-w-[240px] flex-1">
        <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-stone-600">
          {inputLabel}
        </label>
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder={inputPlaceholder}
          className="w-full rounded-lg border border-stone-300 bg-white px-3 py-2.5 text-sm text-stone-900 shadow-inner transition-shadow placeholder-stone-400 focus:border-[#1e3a5f] focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30"
          disabled={loading}
        />
      </div>

      {workflowMode === 'report' && (
        <div className="min-w-[160px]">
          <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-stone-600">
            Report Mode
          </label>
          <select
            value={reportMode}
            onChange={e => setReportMode(e.target.value as ReportMode)}
            className="w-full rounded-lg border border-stone-300 bg-white px-3 py-2.5 text-sm text-stone-900 shadow-inner focus:border-[#1e3a5f] focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30"
            disabled={loading}
          >
            <option value="draft">草稿报告</option>
            <option value="full">完整报告</option>
          </select>
        </div>
      )}

      <button
        type="submit"
        disabled={loading || !input.trim()}
        className="rounded-lg bg-[#1e3a5f] px-5 py-2.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-[#152a47] disabled:bg-stone-300 disabled:text-stone-500"
      >
        {loading ? 'Submitting…' : workflowMode === 'research' ? 'Start Research' : 'Generate Report'}
      </button>

      <label className="cursor-pointer rounded-lg border border-stone-300 bg-white px-5 py-2.5 text-sm font-medium text-stone-800 shadow-sm transition-colors hover:bg-stone-50">
        {uploadLabel}
        <input
          type="file"
          accept=".pdf,.txt"
          onChange={handleFileUpload}
          className="hidden"
          disabled={loading}
        />
      </label>
    </form>
  );
}
