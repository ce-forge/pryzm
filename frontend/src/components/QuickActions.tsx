import React from "react";
import { ZapIcon, WrenchIcon, MailIcon, ClipboardIcon, PryzmIcon } from "./Icons";

interface QuickActionsProps {
  setPrompt: (p: string) => void;
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
}

export default function QuickActions({ setPrompt, inputRef }: QuickActionsProps) {
  const quickActions = [
    { 
      title: 'Optimize Code', 
      desc: 'Refactor scripts for performance', 
      Icon: ZapIcon, 
      prompt: 'Review the following code and suggest optimizations for performance and readability. Explain the logic behind your changes: \n\n',
      hoverBorder: 'hover:border-red-500/30',
      hoverText: 'group-hover:text-red-400'
    },
    { 
      title: 'System Troubleshooter', 
      desc: 'Diagnose OS or hardware errors', 
      Icon: WrenchIcon, 
      prompt: 'I am experiencing a system issue. Based on these symptoms/logs, walk me through the causes and terminal commands to fix it: \n\n',
      hoverBorder: 'hover:border-green-500/30',
      hoverText: 'group-hover:text-green-400'
    },
    { 
      title: 'Draft Professional Email', 
      desc: 'Write concise, action-oriented mail', 
      Icon: MailIcon, 
      prompt: 'Draft a polite and professional email regarding [Topic]. Keep it clear and ensure there is a distinct call to action.',
      hoverBorder: 'hover:border-blue-500/30',
      hoverText: 'group-hover:text-blue-400'
    },
    { 
      title: 'Project Blueprint', 
      desc: 'Break ideas into actionable steps', 
      Icon: ClipboardIcon, 
      prompt: 'I want to start a new project: [Project Description]. Create a comprehensive blueprint with phases, tasks, and suggested tools.',
      hoverBorder: 'hover:border-yellow-500/30',
      hoverText: 'group-hover:text-yellow-400'
    }
  ];

  return (
    <div className="flex flex-col items-center justify-center flex-1 w-full animate-in fade-in slide-in-from-bottom-4 duration-700 px-4">
      <div className="w-16 h-16 bg-[#282a2c]/50 rounded-2xl flex items-center justify-center mb-6 border border-[#333537]">
        <PryzmIcon className="w-12 h-auto text-gray-400" />
      </div>
      
      <h2 className="text-2xl font-bold text-[#e3e3e3] mb-2 text-center">How can I help you today?</h2>
      <p className="text-gray-400 text-sm mb-8 text-center">Select a template or start typing to begin.</p>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 w-full max-w-2xl">
        {quickActions.map((action, i) => (
          <button
            key={i}
            onClick={() => { setPrompt(action.prompt); inputRef.current?.focus(); }}
            className={`flex flex-col items-start p-4 bg-[#1e1f20]/50 hover:bg-[#282a2c] border border-[#333537] rounded-xl transition-all text-left group ${action.hoverBorder}`}
          >
            <div className={`mb-3 text-gray-500 transition-colors ${action.hoverText}`}>
              <action.Icon />
            </div>
            <span className="text-[#e3e3e3] text-sm font-medium mb-1">{action.title}</span>
            <span className="text-gray-500 text-xs line-clamp-1">{action.desc}</span>
          </button>
        ))}
      </div>
    </div>
  );
}