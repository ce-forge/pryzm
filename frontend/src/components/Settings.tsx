import React, { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { apiFetch, getToken, setToken, clearToken } from "@/utils/apiClient";
import ModelsSection from "@/components/SettingsModels";

export default function SettingsModal({ workspace: _workspace, close }: { workspace: string, close: () => void }) {
  const [prompts, setPrompts] = useState<Record<string, string>>({});
  const [initialPrompts, setInitialPrompts] = useState<Record<string, string>>({});

  const [isSaving, setIsSaving] = useState(false);
  const [showSuccess, setShowSuccess] = useState(false);

  // Token section state — stored token is NEVER bound to an input value
  const [storedToken, setStoredToken] = useState<string | null>(() => typeof window !== 'undefined' ? getToken() : null);
  const [isEditingToken, setIsEditingToken] = useState(false);
  const [newToken, setNewToken] = useState("");

  useEffect(() => {
    apiFetch("/api/prompts")
      .then(r => r.json())
      .then(data => {
        setPrompts(data);
        setInitialPrompts(data);
      })
      .catch(() => {});
  }, []);

  const isLoaded = Object.keys(initialPrompts).length > 0;
  const hasChanges = isLoaded && JSON.stringify(prompts) !== JSON.stringify(initialPrompts);

  const handleSave = async () => {
    setIsSaving(true);
    try {
      await apiFetch("/api/prompts", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(prompts)
      });

      setInitialPrompts(prompts);

      setShowSuccess(true);
      setTimeout(() => setShowSuccess(false), 3000);
    } catch {}
    setIsSaving(false);
  };

  const handleTokenSave = () => {
    const trimmed = newToken.trim();
    if (!trimmed) return;
    setToken(trimmed);
    setStoredToken(trimmed);
    setNewToken("");
    setIsEditingToken(false);
  };

  const handleTokenCancel = () => {
    setNewToken("");
    setIsEditingToken(false);
  };

  const handleTokenClear = () => {
    clearToken();
    setStoredToken(null);
    setNewToken("");
    setIsEditingToken(false);
  };

  const modalContent = (
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
            {storedToken && !isEditingToken ? (
              <div className="flex items-center justify-between bg-[#131314] border border-[#333537] rounded-lg px-3 py-2">
                <span className="text-sm text-slate-400">Token configured</span>
                <div className="flex gap-2">
                  <button
                    onClick={() => setIsEditingToken(true)}
                    className="px-4 py-1.5 rounded-lg text-sm font-medium bg-blue-600 hover:bg-blue-500 text-white transition-colors"
                  >
                    Change
                  </button>
                  <button
                    onClick={handleTokenClear}
                    className="px-4 py-1.5 rounded-lg text-sm font-medium bg-[#282a2c] hover:bg-[#333537] text-gray-400 transition-colors"
                  >
                    Clear
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex gap-2">
                <input
                  type="password"
                  value={newToken}
                  onChange={(e) => setNewToken(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleTokenSave()}
                  placeholder="Paste new token"
                  className="flex-1 bg-[#131314] border border-[#333537] text-[#e3e3e3] rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors"
                  autoFocus={isEditingToken}
                />
                <button
                  onClick={handleTokenSave}
                  disabled={!newToken.trim()}
                  className="px-4 py-2 rounded-lg text-sm font-medium bg-blue-600 hover:bg-blue-500 text-white disabled:bg-[#282a2c] disabled:text-gray-500 disabled:cursor-not-allowed transition-all"
                >
                  Save
                </button>
                {isEditingToken && (
                  <button
                    onClick={handleTokenCancel}
                    className="px-4 py-2 rounded-lg text-sm font-medium bg-[#282a2c] hover:bg-[#333537] text-gray-400 transition-colors"
                  >
                    Cancel
                  </button>
                )}
              </div>
            )}
          </div>

          <ModelsSection />

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

  // Portal to body — escapes the sidebar's transform containing block.
  if (typeof document === "undefined") return null;
  return createPortal(modalContent, document.body);
}
