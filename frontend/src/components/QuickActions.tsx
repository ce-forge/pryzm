import React from "react";

interface QuickActionsProps {
  setPrompt: (p: string) => void;
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
}

export default function QuickActions({ setPrompt, inputRef }: QuickActionsProps) {
  const quickActions =[
    { title: 'Scan Subnet', desc: 'Run a quick ping sweep on a subnet', icon: '🔍', prompt: 'Please run a network scan on the subnet 192.168.1.0/24' },
    { title: 'Check SSL Certs', desc: 'Verify expiration for a domain', icon: '🔒', prompt: 'Check the SSL certificate status for google.com' },
    { title: 'Analyze Config', desc: 'Summarize a device config', icon: '📝', prompt: 'I am going to attach a router configuration file. Please review it for security vulnerabilities.' },
    { title: 'Check Open Ports', desc: 'Scan common ports for an IP', icon: '🌐', prompt: 'Run a port scan on 8.8.8.8 to see what is open' }
  ];

  return (
    <div className="flex flex-col items-center justify-center flex-1 w-full animate-in fade-in slide-in-from-bottom-4 duration-700">
      <div className="w-16 h-16 bg-blue-500/10 rounded-2xl flex items-center justify-center mb-6 border border-blue-500/20">
        <svg className="w-8 h-8 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13 10V3L4 14h7v7l9-11h-7z" />
        </svg>
      </div>
      <h2 className="text-2xl font-bold text-[#e3e3e3] mb-2">How can I help you today?</h2>
      <p className="text-gray-400 text-sm mb-8">Select a quick action or start typing to begin.</p>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 w-full max-w-2xl">
        {quickActions.map((action, i) => (
          <button
            key={i}
            onClick={() => { setPrompt(action.prompt); inputRef.current?.focus(); }}
            className="flex flex-col items-start p-4 bg-[#1e1f20]/50 hover:bg-[#282a2c] border border-[#333537] rounded-xl transition-all text-left group"
          >
            <span className="text-xl mb-2 grayscale opacity-70 group-hover:grayscale-0 group-hover:opacity-100 transition-all">{action.icon}</span>
            <span className="text-[#e3e3e3] text-sm font-medium mb-1">{action.title}</span>
            <span className="text-gray-500 text-xs">{action.desc}</span>
          </button>
        ))}
      </div>
    </div>
  );
}