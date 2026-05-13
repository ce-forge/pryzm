import React, { useEffect, useState } from "react";
import { apiFetch, getToken, setToken, clearToken } from "@/utils/apiClient";

export default function SettingsModal({ workspace, close }: { workspace: string, close: () => void }) {
  const [models, setModels] = useState<string[]>([]);

  const[selectedModel, setSelectedModel] = useState(() => typeof window !== 'undefined' ? localStorage.getItem("pryzm_model") || "gemma4:e4b" : "gemma4:e4b");
  const[initialModel, setInitialModel] = useState(() => typeof window !== 'undefined' ? localStorage.getItem("pryzm_model") || "gemma4:e4b" : "gemma4:e4b");

  const [prompts, setPrompts] = useState<Record<string, string>>({});
  const[initialPrompts, setInitialPrompts] = useState<Record<string, string>>({});

  const [isSaving, setIsSaving] = useState(false);
  const [showSuccess, setShowSuccess] = useState(false);

  // Token section state
  const [tokenValue, setTokenValue] = useState(() => typeof window !== 'undefined' ? (getToken() ?? "") : "");
  const [tokenSaved, setTokenSaved] = useState(false);

  useEffect(() => {
    apiFetch("/api/models")
      .then(r => r.json())
      .then(setModels)
      .catch(() => {});

    apiFetch("/api/prompts")
      .then(r => r.json())
      .then(data => {
        setPrompts(data);
        setInitialPrompts(data);
      })
      .catch(() => {});
  },[]);

  const isLoaded = Object.keys(initialPrompts).length > 0;
  const hasChanges = selectedModel !== initialModel || (isLoaded && JSON.stringify(prompts) !== JSON.stringify(initialPrompts));

  const handleSave = async () => {
    setIsSaving(true);
    localStorage.setItem("pryzm_model", selectedModel);
    try {
      await apiFetch("/api/prompts", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(prompts)
      });

      setInitialModel(selectedModel);
      setInitialPrompts(prompts);

      setShowSuccess(true);
      setTimeout(() => setShowSuccess(false), 3000);
    } catch (e) {}
    setIsSaving(false);
  };

  const handleTokenSave = () => {
    const trimmed = tokenValue.trim();
    if (trimmed) {
      setToken(trimmed);
    } else {
      clearToken();
    }
    setTokenSaved(true);
    setTimeout(() => setTokenSaved(false), 2000);
  };

  const handleTokenClear = () => {
    clearToken();
    setTokenValue("");
    setTokenSaved(true);
    setTimeout(() => setTokenSaved(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-[#1e1f20] w-full max-w-3xl rounded-2xl border border-[#333537] shadow-2xl flex flex-col overflow-hidden max-h-[85vh]">
        <div className="flex justify-between items-center p-5 border-b border-[#333537] bg-[#131314]">
          <h2 className="text-lg font-bold text-[#e3e3e3]">Pryzm Settings</h2>
          <button onClick={close} className="text-gray-400 hover:text-white transition-colors">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto custom-scrollbar p-6 space-y-6">

          {/* Connection / API Token */}
          <div>
            <h3 className="text-sm font-semibold text-[#e3e3e3] mb-1">Connection</h3>
            <p className="text-xs text-gray-500 mb-3">The bearer token used to authenticate with the backend. Matches <code className="font-mono text-xs bg-[#131314] px-1 py-0.5 rounded">PRYZM_API_TOKEN</code> in the backend&apos;s <code className="text-xs">.env</code> file.</p>
            <div className="flex gap-2">
              <input
                type="password"
                value={tokenValue}
                onChange={(e) => setTokenValue(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleTokenSave()}
                placeholder={tokenValue ? "••••••••" : "Paste token"}
                className="flex-1 bg-[#131314] border border-[#333537] text-[#e3e3e3] rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors"
              />
              <button
                onClick={handleTokenSave}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${tokenSaved ? 'bg-emerald-600 text-white' : 'bg-blue-600 hover:bg-blue-500 text-white'}`}
              >
                {tokenSaved ? "Saved" : "Save"}
              </button>
              {tokenValue && (
                <button
                  onClick={handleTokenClear}
                  className="px-4 py-2 rounded-lg text-sm font-medium bg-[#282a2c] hover:bg-[#333537] text-gray-400 transition-colors"
                >
                  Clear
                </button>
              )}
            </div>
          </div>

          <div className="border-t border-[#333537] pt-6">
            <label className="block text-sm font-semibold text-[#e3e3e3] mb-2">Default AI Model</label>
            <p className="text-xs text-gray-500 mb-3">Used when a workspace doesn&apos;t pin its own model. Workspaces with a pinned model override this.</p>
            <select value={selectedModel} onChange={(e) => setSelectedModel(e.target.value)} className="w-full bg-[#131314] border border-[#333537] text-[#e3e3e3] rounded-lg px-4 py-2.5 outline-none focus:border-blue-500 transition-colors appearance-none">
              {models.length === 0 && <option value={selectedModel}>{selectedModel} (Loading...)</option>}
              {models.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>

          <div className="border-t border-[#333537] pt-6">
            <h3 className="text-sm font-semibold text-[#e3e3e3] mb-1">Micro-Prompts</h3>
            <p className="text-xs text-gray-500 mb-4">Customize the Just-In-Time (JIT) instructions injected into the engine during edge cases.</p>
            <div className="space-y-6">
              {Object.entries(prompts).map(([key, value]) => (
                <div key={key} className="flex flex-col gap-1.5">
                  <label className="text-[11px] font-mono text-gray-400 uppercase tracking-wider">{key.replace(/_/g, ' ')}</label>
                  <textarea value={value} onChange={(e) => setPrompts({ ...prompts,[key]: e.target.value })} className="w-full bg-[#131314] border border-[#333537] text-gray-300 text-sm rounded-lg px-3 py-2 outline-none focus:border-blue-500 min-h-[60px] resize-y custom-scrollbar" />
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="p-4 border-t border-[#333537] flex justify-end items-center bg-[#131314] shrink-0">
          <button onClick={close} className="px-5 py-2 text-gray-400 hover:text-white font-medium text-sm transition-colors mr-2">Close</button>

          <button
            onClick={handleSave}
            disabled={!hasChanges || isSaving}
            className={`px-6 py-2 font-semibold rounded-lg text-sm transition-all flex items-center gap-2
              ${showSuccess ? 'bg-emerald-600 text-white' :
                hasChanges ? 'bg-blue-600 hover:bg-blue-500 text-white shadow-lg shadow-blue-900/20' :
                'bg-[#282a2c] text-gray-500 cursor-not-allowed'}`}
          >
            {isSaving ? 'Saving...' : showSuccess ? (
              <><svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" /></svg> Settings Applied</>
            ) : 'Apply Settings'}
          </button>
        </div>
      </div>
    </div>
  );
}
