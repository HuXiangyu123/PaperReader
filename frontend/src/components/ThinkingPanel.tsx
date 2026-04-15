import { useState, useEffect, useRef } from 'react';
import type { ThinkingEntry } from '../types/task';

interface Props {
  thinkingEntries: ThinkingEntry[];
  totalDurationMs: number;
  isDone: boolean;
  isRunning: boolean;
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function ThinkingPanel({ thinkingEntries, totalDurationMs, isDone, isRunning }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef<number | null>(null);

  useEffect(() => {
    if (isRunning && !startRef.current) {
      startRef.current = Date.now();
    }
    if (isDone) {
      startRef.current = null;
    }
  }, [isRunning, isDone]);

  useEffect(() => {
    if (!isRunning) {
      setElapsed(0);
      return;
    }
    const interval = setInterval(() => {
      if (startRef.current) {
        setElapsed(Date.now() - startRef.current);
      }
    }, 100);
    return () => clearInterval(interval);
  }, [isRunning]);

  if (!isRunning && thinkingEntries.length === 0) {
    return null;
  }

  const hasThinking = thinkingEntries.length > 0;
  const displayTime = isDone ? totalDurationMs : elapsed;
  const latestThinking = hasThinking ? thinkingEntries[thinkingEntries.length - 1] : null;

  return (
    <div className="mb-4 rounded-xl border border-stone-200 bg-white shadow-sm overflow-hidden">
      <button
        type="button"
        onClick={() => hasThinking && setExpanded(e => !e)}
        className={`w-full flex items-center gap-2 px-4 py-2.5 text-left text-sm ${
          hasThinking ? 'cursor-pointer hover:bg-stone-50' : 'cursor-default'
        }`}
      >
        {isRunning && !isDone ? (
          <>
            <span className="inline-flex gap-[2px]">
              <span className="w-1.5 h-1.5 rounded-full bg-[#1e40af] animate-bounce [animation-delay:0ms]" />
              <span className="w-1.5 h-1.5 rounded-full bg-[#1e40af] animate-bounce [animation-delay:150ms]" />
              <span className="w-1.5 h-1.5 rounded-full bg-[#1e40af] animate-bounce [animation-delay:300ms]" />
            </span>
            <span className="text-stone-600 font-medium">
              Thinking{displayTime > 0 ? ` ${formatDuration(displayTime)}` : ''}...
            </span>
          </>
        ) : (
          <>
            <span className="text-stone-400 text-xs">
              {hasThinking ? (expanded ? '▼' : '▶') : '●'}
            </span>
            <span className="text-stone-600">
              Thought for {formatDuration(totalDurationMs)}
            </span>
          </>
        )}
      </button>

      {hasThinking && latestThinking && (
        <div className="border-t border-stone-100 px-4 py-2 text-xs text-stone-600 bg-stone-50/60">
          <span className="font-medium text-stone-500">{latestThinking.node}: </span>
          {latestThinking.content.length > 160
            ? latestThinking.content.slice(0, 160) + '...'
            : latestThinking.content}
        </div>
      )}

      {expanded && hasThinking && (
        <div className="border-t border-stone-100 px-4 py-3 max-h-[300px] overflow-y-auto">
          {thinkingEntries.map((entry, idx) => (
            <div key={idx} className="mb-3 last:mb-0">
              <p className="text-xs font-medium text-stone-500 mb-1">{entry.node}</p>
              <pre className="whitespace-pre-wrap text-xs text-stone-600 leading-relaxed bg-stone-50 rounded-lg p-3 border border-stone-100">
                {entry.content.length > 2000
                  ? entry.content.slice(0, 2000) + '\n\n... (truncated)'
                  : entry.content}
              </pre>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
