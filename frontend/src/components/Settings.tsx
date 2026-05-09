import React, { useEffect, useState } from "react";
import { APP_DEFAULTS } from "@/utils/constants";

interface SettingsProps {
  workspace: string;
  close: () => void;
  selectedModel: string;
  setSelectedModel: (m: string) => void;
}

export default function SettingsModal({ workspace, close, selectedModel, setSelectedModel }: SettingsProps) {
  const [activeTab, setActiveTab] = useState<"general" | "behavior">("general");
  const [models, setModels] = useState<string[]>([]);
  const [prompts, setPrompts] = useState<Record<string, string>>({});
  const [initialPrompts, setInitialPrompts] = useState<Record<string, string>>({});
  const [initialModel, setInitialModel] = useState(selectedModel);
  const [isSaving, setIsSaving] = useState(false);
  const [showSuccess, setShowSuccess] = useState(false);

  useEffect(() => {
    fetch(`${APP_DEFAULTS.API_URL}/api/models`)
      .then(r => r.json())
      .then(setModels);

    fetch(`${APP_DEFAULTS.API_URL}/api/prompts`)
      .then(r => r.json())
      .then(data => {
        setPrompts(data);
        setInitialPrompts(data);
      });
  }, []);

  const hasChanges = selectedModel !== initialModel || JSON.stringify(prompts) !== JSON.stringify(initialPrompts);

  const handleSave = async () => {
    setIsSaving(true);
    localStorage.setItem("pryzm_model", selectedModel);
    try {
      await fetch(`${APP_DEFAULTS.API_URL}/api/prompts`, {
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

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-[#1e1f20] w-full max-w-2xl rounded-2xl border border-[#333537] shadow-2xl flex flex-col overflow-hidden max-h-[85vh]">
        <div className="flex justify-between items-center p-5 border-b border-[#333537] bg-[#131314]">
          <h2 className="text-lg font-bold text-[#e3e3e3]">Pryzm Settings</h2>
          <button onClick={close} className="text-gray-400 hover:text-white">✕</button>
        </div>

        <div className="flex flex-1 overflow-hidden min-h-[400px]">
          <div className="w-48 border-r border-[#333537] bg-[#131314]/50 p-4 space-y-2">
            <button onClick={() => setActiveTab("general")} className={`w-full text-left px-3 py-2 rounded-lg text-sm ${activeTab === 'general' ? 'bg-[#282a2c] text-blue-400' : 'text-gray-400'}`}>General</button>
            <button onClick={() => setActiveTab("behavior")} className={`w-full text-left px-3 py-2 rounded-lg text-sm ${activeTab === 'behavior' ? 'bg-[#282a2c] text-blue-400' : 'text-gray-400'}`}>AI Behavior</button>
          </div>

          <div className="flex-1 p-6 overflow-y-auto bg-[#1e1f20]">
            {activeTab === "general" && (
              <div className="space-y-6">
                <label className="block text-sm font-semibold text-[#e3e3e3]">Active AI Model</label>
                <select value={selectedModel} onChange={(e) => setSelectedModel(e.target.value)} className="w-full bg-[#131314] border border-[#333537] text-white rounded-lg px-4 py-2 outline-none">
                  {models.map(m => <option key={m} value={m}>{m}</option>)}
                </select>
              </div>
            )}
            {activeTab === "behavior" && (
              <div className="space-y-4">
                {Object.entries(prompts).map(([key, value]) => (
                  <div key={key}>
                    <label className="text-[11px] font-mono text-gray-400 uppercase">{key}</label>
                    <textarea value={value} onChange={(e) => setPrompts({ ...prompts, [key]: e.target.value })} className="w-full bg-[#131314] border border-[#333537] text-gray-300 text-sm rounded-lg px-3 py-2 outline-none min-h-[60px]" />
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="p-4 border-t border-[#333537] flex justify-end bg-[#131314]">
          <button onClick={handleSave} disabled={!hasChanges || isSaving} className={`px-6 py-2 rounded-lg text-sm font-bold ${hasChanges ? 'bg-blue-600 text-white' : 'bg-[#282a2c] text-gray-500'}`}>
            {isSaving ? 'Saving...' : showSuccess ? 'Applied!' : 'Apply Settings'}
          </button>
        </div>
      </div>
    </div>
  );
}