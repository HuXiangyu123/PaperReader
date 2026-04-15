import { useState, useEffect } from 'react';

interface ModelConfigResponse {
  current_provider: string;
  reason_model: string;
  quick_model: string;
  provider_reason_models: string[];
  provider_quick_models: string[];
  provider_display_names: Record<string, string>;
  all_providers: { id: string; name: string; key_set: boolean }[];
}

function ProviderDot({ configured }: { configured: boolean }) {
  return (
    <div
      className={`w-2 h-2 rounded-full flex-shrink-0 ${configured ? 'bg-green-400' : 'bg-stone-300'}`}
      title={configured ? 'API key configured' : 'API key not configured'}
    />
  );
}

export function ModelConfigPanel() {
  const [config, setConfig] = useState<ModelConfigResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  // Local editing state
  const [reasonModel, setReasonModel] = useState('');
  const [quickModel, setQuickModel] = useState('');

  useEffect(() => {
    fetch('/tasks/model-config')
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data) {
          setConfig(data);
          setReasonModel(data.reason_model);
          setQuickModel(data.quick_model);
        }
        setLoading(false);
      })
      .catch(err => { setError(err.message); setLoading(false); });
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setSaveMsg(null);
    try {
      const params = new URLSearchParams();
      if (reasonModel) params.set('reason_model', reasonModel);
      if (quickModel) params.set('quick_model', quickModel);
      const res = await fetch(`/tasks/model-config?${params}`, { method: 'PATCH' });
      const data = await res.json();
      if (res.ok) {
        setSaveMsg(`Saved — reason: ${data.reason_model}, quick: ${data.quick_model}`);
        // Refresh config
        const r2 = await fetch('/tasks/model-config');
        const d2 = await r2.json();
        setConfig(d2);
        setReasonModel(d2.reason_model);
        setQuickModel(d2.quick_model);
      } else {
        setSaveMsg(`Error: ${JSON.stringify(data)}`);
      }
    } catch (e: unknown) {
      setSaveMsg(`Error: ${e instanceof Error ? e.message : String(e)}`);
    }
    setSaving(false);
    setTimeout(() => setSaveMsg(null), 4000);
  };

  if (loading) {
    return (
      <div className="p-3">
        <div className="flex items-center gap-2 text-xs text-stone-400">
          <div className="w-3 h-3 border border-stone-300 border-t-[#1e3a5f] rounded-full animate-spin" />
          Loading model config...
        </div>
      </div>
    );
  }

  if (error || !config) {
    return (
      <div className="p-3 text-xs text-red-500">
        Failed to load model config: {error}
      </div>
    );
  }

  const providerName = config.provider_display_names[config.current_provider] || config.current_provider;

  return (
    <div className="p-3 text-xs space-y-3 overflow-y-auto max-h-full">
      {/* Provider */}
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-stone-400 mb-0.5">LLM Provider</div>
          <div className="font-semibold text-[#1e3a5f]">{providerName}</div>
        </div>
        <div className="flex items-center gap-1" title="Dots: green=API key configured, gray=not set">
          {config.all_providers.map(p => (
            <ProviderDot key={p.id} configured={p.key_set} />
          ))}
        </div>
      </div>

      {/* Model selectors */}
      <div className="rounded-lg bg-stone-50 border border-stone-200 p-2.5 space-y-2.5">
        <div className="text-[10px] uppercase tracking-wider text-stone-400 mb-1.5">Active Models</div>

        {/* Reason */}
        <div>
          <div className="flex items-center gap-1 mb-1">
            <svg className="w-3 h-3 text-blue-500 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
            </svg>
            <span className="text-stone-600 font-medium text-[11px]">Reason Model</span>
            <span className="ml-auto text-[9px] text-stone-400">complex reasoning</span>
          </div>
          <select
            value={reasonModel}
            onChange={e => setReasonModel(e.target.value)}
            className="w-full text-[11px] font-mono bg-white rounded border border-stone-200 px-2 py-1 text-stone-800 focus:outline-none focus:border-blue-400"
          >
            {config.provider_reason_models.map(m => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
          <div className="text-[9px] text-stone-400 mt-0.5 ml-4">
            Used in: clarify · extract · draft · review
          </div>
        </div>

        {/* Quick */}
        <div>
          <div className="flex items-center gap-1 mb-1">
            <svg className="w-3 h-3 text-green-500 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path d="M13 10V3L4 14h7v7l9-11h-7z"/>
            </svg>
            <span className="text-stone-600 font-medium text-[11px]">Quick Model</span>
            <span className="ml-auto text-[9px] text-stone-400">fast & lightweight</span>
          </div>
          <select
            value={quickModel}
            onChange={e => setQuickModel(e.target.value)}
            className="w-full text-[11px] font-mono bg-white rounded border border-stone-200 px-2 py-1 text-stone-800 focus:outline-none focus:border-green-400"
          >
            {config.provider_quick_models.map(m => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
          <div className="text-[9px] text-stone-400 mt-0.5 ml-4">
            Used in: search_plan · repair · persist · tools
          </div>
        </div>

        {/* Save button */}
        <button
          onClick={handleSave}
          disabled={saving}
          className={`w-full py-1.5 rounded text-[11px] font-medium transition-colors ${
            saving
              ? 'bg-stone-200 text-stone-400 cursor-not-allowed'
              : 'bg-[#1e3a5f] text-white hover:bg-[#2a4f7a]'
          }`}
        >
          {saving ? 'Saving...' : 'Apply & Restart Context'}
        </button>

        {saveMsg && (
          <div className={`text-[10px] px-2 py-1 rounded ${saveMsg.startsWith('Error') ? 'bg-red-50 text-red-600' : 'bg-green-50 text-green-700'}`}>
            {saveMsg}
          </div>
        )}
      </div>

      {/* Routing explanation */}
      <div className="rounded-lg bg-stone-50 border border-stone-200 p-2.5">
        <div className="text-[10px] uppercase tracking-wider text-stone-400 mb-1.5">Model Routing</div>
        <div className="space-y-1">
          <div className="flex items-center gap-1.5">
            <div className="w-2 h-2 rounded-full bg-blue-400 flex-shrink-0" />
            <span className="text-stone-600 text-[11px]">Reason: clarify, extract, draft, review</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-2 h-2 rounded-full bg-green-400 flex-shrink-0" />
            <span className="text-stone-600 text-[11px]">Quick: search_plan, repair, persist</span>
          </div>
        </div>
      </div>

      {/* Note */}
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-2.5 text-[10px] text-amber-700 leading-relaxed">
        <div className="flex items-center gap-1.5 font-semibold mb-1">
          <svg className="w-3 h-3 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <circle cx="12" cy="12" r="10"/>
            <path d="M12 8v4m0 4h.01"/>
          </svg>
          Note
        </div>
        <p>Changes apply immediately to new tasks. Running tasks keep their original model. For permanent config, edit <code className="bg-amber-100 px-0.5 rounded font-mono">.env</code> and restart backend.</p>
      </div>
    </div>
  );
}
