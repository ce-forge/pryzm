import React from "react";

const baseProps: React.SVGProps<SVGSVGElement> = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  className: "w-5 h-5"
};

export const PryzmIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} viewBox="0 0 40 24" className="w-10 h-6" {...props}>
    <polygon 
      points="16,5 24,19 8,19" 
      stroke="currentColor" 
      strokeWidth="1.5" 
      strokeLinejoin="round" 
    />
    
    <path 
      d="M0 13h16" 
      stroke="currentColor" 
      strokeWidth="1.5" 
      strokeLinecap="round" 
      opacity="0.8"
    />

    <g opacity="0.6">
      <path d="M16 13l18-8" stroke="#ff4757" strokeWidth="1.2" strokeLinecap="round" />
      <path d="M16 13l20-3" stroke="#ffa502" strokeWidth="1.2" strokeLinecap="round" />
      <path d="M16 13l20 3" stroke="#2ed573" strokeWidth="1.2" strokeLinecap="round" />
      <path d="M16 13l18 8" stroke="#1e90ff" strokeWidth="1.2" strokeLinecap="round" />
    </g>
  </svg>
);

export const ZapIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...props}>
    <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
  </svg>
);

export const WrenchIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...props}>
    <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
  </svg>
);

export const MailIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...props}>
    <rect width="20" height="16" x="2" y="4" rx="2" />
    <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
  </svg>
);

export const ClipboardIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg {...baseProps} {...props}>
    <rect width="8" height="4" x="8" y="2" rx="1" ry="1" />
    <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
    <path d="M12 11h4M12 16h4M8 11h.01M8 16h.01" />
  </svg>
);

export const DatabaseIcon = (props: React.SVGProps<SVGSVGElement>) => (
    <svg className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
    </svg>
);

export const AlertIcon = (props: React.SVGProps<SVGSVGElement>) => (
    <svg className="w-4 h-4 text-red-400 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
    </svg>
);

export const TerminalIcon = (props: React.SVGProps<SVGSVGElement>) => (
    <svg className="w-4 h-4 text-orange-400 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
    </svg>
);
