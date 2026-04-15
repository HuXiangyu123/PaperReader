import { useEffect, useMemo, useState } from 'react';
import type { ResearchAmbiguity, ResearchBrief, SourceType } from '../types/task';

interface Props {
  brief: ResearchBrief;
  onTaskCreated: (taskId: string, sourceType: SourceType) => void;
}

type DesiredOutputOption = {
  value: string;
  label: string;
};

const DESIRED_OUTPUT_OPTIONS: DesiredOutputOption[] = [
  { value: 'survey_outline', label: '综述大纲' },
  { value: 'paper_cards', label: '论文卡片' },
  { value: 'reading_notes', label: '阅读笔记' },
  { value: 'related_work_draft', label: 'Related Work 草稿' },
  { value: 'research_brief', label: 'Research Brief' },
];

const TOPIC_PLACEHOLDERS = new Set(['未明确', '未提供研究主题']);

function normalizeTopic(topic?: string): string {
  if (!topic || TOPIC_PLACEHOLDERS.has(topic.trim())) {
    return '';
  }
  return topic.trim();
}

function splitFocusDimensions(raw: string): string[] {
  return raw
    .split(/[\n,，、/]/)
    .map(item => item.trim())
    .filter(Boolean);
}

function findOutputLabel(value: string): string {
  return DESIRED_OUTPUT_OPTIONS.find(option => option.value === value)?.label ?? value;
}

function buildRefinedQuery(params: {
  topic: string;
  desiredOutput: string;
  timeRange: string;
  domainScope: string;
  focusDimensions: string;
}): string {
  const { topic, desiredOutput, timeRange, domainScope, focusDimensions } = params;
  const focusList = splitFocusDimensions(focusDimensions);

  const parts = [
    `调研 ${[timeRange.trim(), topic.trim()].filter(Boolean).join(' ')}`.trim(),
    domainScope.trim() ? `研究范围聚焦 ${domainScope.trim()}` : '',
    `输出 ${desiredOutput}（${findOutputLabel(desiredOutput)}）`,
    focusList.length > 0 ? `重点关注 ${focusList.join('、')}` : '',
  ].filter(Boolean);

  return parts.join('，') + '。';
}

export function ResearchFollowupForm({ brief, onTaskCreated }: Props) {
  const [topic, setTopic] = useState(normalizeTopic(brief.topic));
  const [desiredOutput, setDesiredOutput] = useState(brief.desired_output || 'survey_outline');
  const [timeRange, setTimeRange] = useState(brief.time_range || '');
  const [domainScope, setDomainScope] = useState(brief.domain_scope || '');
  const [focusDimensions, setFocusDimensions] = useState((brief.focus_dimensions || []).join('、'));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setTopic(normalizeTopic(brief.topic));
    setDesiredOutput(brief.desired_output || 'survey_outline');
    setTimeRange(brief.time_range || '');
    setDomainScope(brief.domain_scope || '');
    setFocusDimensions((brief.focus_dimensions || []).join('、'));
    setError(null);
  }, [brief]);

  const refinedQuery = useMemo(
    () =>
      buildRefinedQuery({
        topic,
        desiredOutput,
        timeRange,
        domainScope,
        focusDimensions,
      }),
    [desiredOutput, domainScope, focusDimensions, timeRange, topic],
  );

  const applySuggestion = (ambiguity: ResearchAmbiguity, suggestion: string) => {
    if (ambiguity.field === 'desired_output') {
      setDesiredOutput(suggestion);
      return;
    }

    if (ambiguity.field === 'topic') {
      setTopic(prev => (prev && !TOPIC_PLACEHOLDERS.has(prev) ? prev : suggestion));
      return;
    }

    if (ambiguity.field === 'time_range') {
      setTimeRange(suggestion);
      return;
    }

    if (ambiguity.field === 'domain_scope') {
      setDomainScope(suggestion);
      return;
    }
  };

  const handleSubmit = async () => {
    if (!topic.trim() || !desiredOutput.trim() || submitting) {
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const resp = await fetch('/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          input_type: 'research',
          input_value: refinedQuery,
          source_type: 'research',
          report_mode: 'draft',
        }),
      });

      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        throw new Error(data.detail || 'Failed to submit follow-up task');
      }

      const data = await resp.json();
      onTaskCreated(data.task_id, 'research');
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : 'Failed to submit follow-up task');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="mb-5 rounded-xl border border-amber-200 bg-amber-50/70 p-5">
      <div className="mb-4">
        <h3 className="text-base font-semibold text-amber-950">补充研究约束</h3>
        <p className="mt-1 text-sm leading-relaxed text-amber-900">
          当前 brief 还不足以进入 `Search Plan`。把下面几项补全后，直接重新提交一条更具体的
          research query。
        </p>
      </div>

      {brief.ambiguities && brief.ambiguities.length > 0 && (
        <div className="mb-4 space-y-3">
          {brief.ambiguities.map((ambiguity, index) => (
            <div key={`${ambiguity.field}-${index}`} className="rounded-lg border border-amber-200 bg-white/80 p-3">
              <p className="text-sm font-medium text-stone-800">{ambiguity.field}</p>
              <p className="mt-1 text-sm text-stone-600">{ambiguity.reason}</p>
              {ambiguity.suggested_options && ambiguity.suggested_options.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {ambiguity.suggested_options.map(option => (
                    <button
                      key={`${ambiguity.field}-${option}`}
                      type="button"
                      onClick={() => applySuggestion(ambiguity, option)}
                      className="rounded-full border border-amber-300 bg-amber-50 px-2.5 py-1 text-xs text-amber-900 hover:bg-amber-100"
                    >
                      {option}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <label className="block">
          <span className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-stone-600">
            Research Topic
          </span>
          <input
            value={topic}
            onChange={e => setTopic(e.target.value)}
            placeholder="例如：AI agent 在医学影像诊断方向的新论文"
            className="w-full rounded-lg border border-stone-300 bg-white px-3 py-2.5 text-sm text-stone-900 focus:border-[#1e3a5f] focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30"
          />
        </label>

        <label className="block">
          <span className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-stone-600">
            Desired Output
          </span>
          <select
            value={desiredOutput}
            onChange={e => setDesiredOutput(e.target.value)}
            className="w-full rounded-lg border border-stone-300 bg-white px-3 py-2.5 text-sm text-stone-900 focus:border-[#1e3a5f] focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30"
          >
            {DESIRED_OUTPUT_OPTIONS.map(option => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-stone-600">
            Time Range
          </span>
          <input
            value={timeRange}
            onChange={e => setTimeRange(e.target.value)}
            placeholder="例如：2023-2026 或 近三年"
            className="w-full rounded-lg border border-stone-300 bg-white px-3 py-2.5 text-sm text-stone-900 focus:border-[#1e3a5f] focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30"
          />
        </label>

        <label className="block">
          <span className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-stone-600">
            Domain Scope
          </span>
          <input
            value={domainScope}
            onChange={e => setDomainScope(e.target.value)}
            placeholder="例如：医学影像诊断 / 临床决策支持"
            className="w-full rounded-lg border border-stone-300 bg-white px-3 py-2.5 text-sm text-stone-900 focus:border-[#1e3a5f] focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30"
          />
        </label>
      </div>

      <label className="mt-4 block">
        <span className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-stone-600">
          Focus Dimensions
        </span>
        <input
          value={focusDimensions}
          onChange={e => setFocusDimensions(e.target.value)}
          placeholder="例如：多模态 agent、工具调用、数据集、评测指标、局限性"
          className="w-full rounded-lg border border-stone-300 bg-white px-3 py-2.5 text-sm text-stone-900 focus:border-[#1e3a5f] focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30"
        />
      </label>

      <div className="mt-4 rounded-lg border border-stone-200 bg-white p-4">
        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-stone-500">
          Refined Query Preview
        </p>
        <p className="text-sm leading-relaxed text-stone-700">{refinedQuery}</p>
      </div>

      {error && (
        <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-900">
          {error}
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-stone-500">
          会创建一条新的 research task，并自动切换到新结果。
        </p>
        <button
          type="button"
          onClick={() => void handleSubmit()}
          disabled={submitting || !topic.trim() || !desiredOutput.trim()}
          className="rounded-lg bg-[#1e3a5f] px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-[#152a47] disabled:bg-stone-300 disabled:text-stone-500"
        >
          {submitting ? 'Submitting…' : '继续澄清并重新生成'}
        </button>
      </div>
    </section>
  );
}
