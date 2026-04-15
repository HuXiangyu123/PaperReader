/**
 * useTaskDetail — 补充 useTaskSSE，额外拉取完整 task 记录（含 brief / search_plan）。
 *
 * useTaskSSE 负责实时 SSE 事件流，这里负责拿到 Task 对象的完整字段。
 * 数据刷新时机与 useTaskSSE 对齐（taskId 变化时重新拉取）。
 */

import { useState, useEffect } from 'react';
import type { Task } from '../types/task';

interface TaskDetailState {
  task: Task | null;
  loading: boolean;
  error: string | null;
}

export function useTaskDetail(taskId: string | null): TaskDetailState {
  const [state, setState] = useState<TaskDetailState>({
    task: null,
    loading: false,
    error: null,
  });

  useEffect(() => {
    if (!taskId) {
      setState({ task: null, loading: false, error: null });
      return;
    }

    let cancelled = false;
    setState({ task: null, loading: true, error: null });

    fetch(`/tasks/${taskId}`)
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data: Task) => {
        if (cancelled) return;
        setState({ task: data, loading: false, error: null });
      })
      .catch(err => {
        if (cancelled) return;
        setState({ task: null, loading: false, error: String(err) });
      });

    return () => {
      cancelled = true;
    };
  }, [taskId]);

  return state;
}
