import { useEffect, useState } from 'react';
import type { Task } from '../types/task';
import { MarkdownRenderer } from './MarkdownRenderer';

interface Props {
  taskId: string | null;
  isDone: boolean;
}

export function ChatPanel({ taskId, isDone }: Props) {
  const [messages, setMessages] = useState<Array<{ role: 'user' | 'assistant'; content: string }>>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!taskId || !isDone) {
      setMessages([]);
      return;
    }
    fetch(`/tasks/${taskId}`)
      .then(r => r.json())
      .then((task: Task) => setMessages(task.chat_history ?? []))
      .catch(() => setMessages([]));
  }, [taskId, isDone]);

  const send = async () => {
    if (!taskId || !input.trim() || loading) return;
    const userMessage = input.trim();
    setMessages(prev => [...prev, { role: 'user', content: userMessage }]);
    setInput('');
    setLoading(true);
    try {
      const resp = await fetch(`/tasks/${taskId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userMessage }),
      });
      const data = await resp.json();
      setMessages(prev => [...prev, { role: 'assistant', content: data.content ?? data.detail ?? 'No response' }]);
    } catch {
      setMessages(prev => [...prev, { role: 'assistant', content: 'Chat request failed.' }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mt-5 rounded-xl border border-stone-300 bg-white shadow-sm">
      <div className="border-b border-stone-200 px-4 py-3">
        <h3 className="font-display text-base text-[#1e3a5f]">Paper Follow-up</h3>
      </div>
      <div className="max-h-[280px] overflow-y-auto px-4 py-4 space-y-3">
        {messages.length === 0 ? (
          <p className="text-sm text-stone-500">Ask follow-up questions about the paper or the generated report.</p>
        ) : (
          messages.map((m, idx) => (
            <div
              key={idx}
              className={`rounded-lg px-3 py-2 text-sm leading-relaxed ${
                m.role === 'user'
                  ? 'bg-[#1e3a5f] text-white ml-8'
                  : 'bg-stone-100 text-stone-800 mr-8'
              }`}
            >
              {m.role === 'assistant' ? (
                <MarkdownRenderer content={m.content} compact />
              ) : (
                m.content
              )}
            </div>
          ))
        )}
      </div>
      <div className="border-t border-stone-200 px-4 py-3 flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
          placeholder="Ask a follow-up question..."
          className="flex-1 rounded-lg border border-stone-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1e3a5f]/30"
          disabled={!taskId || !isDone || loading}
        />
        <button
          type="button"
          onClick={() => void send()}
          disabled={!taskId || !isDone || loading || !input.trim()}
          className="px-4 py-2 rounded-lg bg-[#1e3a5f] text-white text-sm disabled:bg-stone-300"
        >
          {loading ? 'Sending…' : 'Send'}
        </button>
      </div>
    </div>
  );
}
