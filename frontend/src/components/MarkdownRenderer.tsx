import React, { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";
import { DatabaseIcon, AlertIcon, TerminalIcon } from "./Icons";

const CodeBlock = ({ language, value }: { language: string, value: string }) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="relative rounded-xl overflow-hidden border border-[#333537] my-4 shadow-lg bg-[#0d0d0d]">
      <div className="flex items-center justify-between px-4 py-1.5 bg-[#1a1b1c] border-b border-[#333537] text-xs text-gray-400 select-none">
        <span className="font-mono lowercase tracking-wide">{language || 'text'}</span>
        <button onClick={handleCopy} className="flex items-center gap-1.5 hover:text-[#e3e3e3] transition-colors focus:outline-none" title="Copy code">
          {copied ? (
            <React.Fragment>
              <svg className="w-3.5 h-3.5 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" /></svg>
              <span className="text-emerald-400">Copied!</span>
            </React.Fragment>
          ) : (
            <React.Fragment>
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>
              <span>Copy</span>
            </React.Fragment>
          )}
        </button>
      </div>
      <SyntaxHighlighter language={language} style={vscDarkPlus} customStyle={{ margin: 0, padding: '1rem', background: 'transparent', fontSize: '13px' }} wrapLines={true} wrapLongLines={true}>
        {value}
      </SyntaxHighlighter>
    </div>
  );
};

// FIX: Changed from "export default function" to just "function"
function MarkdownRenderer({ content, searchQuery }: { content: string, searchQuery?: string }) {
  
  const highlightText = (text: string, query: string): React.ReactNode => {
    if (!query) return text;
    const escapedQuery = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const parts = text.split(new RegExp(`(${escapedQuery})`, 'gi'));
    
    return parts.map((part, i) =>
      part.toLowerCase() === query.toLowerCase() ? (
        <mark 
          key={i} 
          className="search-match rounded-[3px] px-0.5 text-inherit transition-colors duration-200"
          style={{ 
            backgroundColor: 'rgba(59, 130, 246, 0.2)',
            color: '#93c5fd'
          }}
        >
          {part}
        </mark>
      ) : part
    );
  };

  const highlightChildren = (children: React.ReactNode, query: string): React.ReactNode => {
    if (!query) return children;
    return React.Children.map(children, (child) => {
      if (typeof child === 'string') return highlightText(child, query);
      
      if (React.isValidElement(child)) {
        const element = child as React.ReactElement<any>;
        if (element.type === 'mark') return element;
        if (element.type === CodeBlock) return element;
        
        if (element.props?.children) {
           return React.cloneElement(element, {
              ...element.props,
              children: highlightChildren(element.props.children, query)
           });
        }
      }
      return child;
    });
  };

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        h1({ children }) { return <h1 className="text-2xl font-bold mb-4">{highlightChildren(children, searchQuery || "")}</h1>; },
        h2({ children }) { return <h2 className="text-xl font-bold mb-3">{highlightChildren(children, searchQuery || "")}</h2>; },
        h3({ children }) { return <h3 className="text-lg font-bold mb-2">{highlightChildren(children, searchQuery || "")}</h3>; },
        h4({ children }) { return <h4 className="text-base font-bold mb-2">{highlightChildren(children, searchQuery || "")}</h4>; },
        h5({ children }) { return <h5 className="text-sm font-bold mb-1">{highlightChildren(children, searchQuery || "")}</h5>; },
        h6({ children }) { return <h6 className="text-xs font-bold mb-1">{highlightChildren(children, searchQuery || "")}</h6>; },
        p({ children }) { 
          if (!children || (typeof children === 'string' && children.trim() === '')) return null;
          return <p className="mb-2 last:mb-0">{highlightChildren(children, searchQuery || "")}</p>; 
        },
        blockquote({ children }) {
          const extractText = (nodes: React.ReactNode): string => {
            return React.Children.toArray(nodes).map(node => {
              if (typeof node === 'string') return node;
              if (React.isValidElement(node)) {
                const element = node as React.ReactElement<any>;
                if (element.props?.children) return extractText(element.props.children);
              }
              return '';
            }).join('');
          };
          const textContent = extractText(children);
          let Icon = <svg className="w-4 h-4 text-blue-400 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>;

          if (textContent.includes("Knowledge Base") || textContent.includes("File Analyzed")) Icon = <DatabaseIcon />;
          else if (textContent.includes("Error")) Icon = <AlertIcon />;
          else if (textContent.includes("System Action") || textContent.includes("Executing")) Icon = <TerminalIcon />;

          return (
            <blockquote className="bg-[#1a1b1c] border border-[#333537] border-l-4 border-l-blue-500 text-gray-300 px-4 py-3 rounded-r-lg shadow-md text-[13px] my-3 flex items-start gap-3">
              {Icon}
              <div className="flex-1 w-full">{highlightChildren(children, searchQuery || "")}</div>
            </blockquote>
          );
        },
        pre({ children }: any) { 
          if (children && children.props) {
            const { className, children: codeContent } = children.props;
            const match = /language-(\w+)/.exec(className || "");
            const lang = match ? match[1] : "text";
            const codeString = String(codeContent).replace(/\n$/, "");
            return <CodeBlock language={lang} value={codeString} />;
          }
          return <pre className="my-1.5">{children}</pre>; 
        },
        code({ children, ...rest }: any) {
          return <code {...rest} className="bg-[#1e1f20] text-emerald-300 px-1.5 py-0.5 rounded text-[13px] border border-[#333537]">{children}</code>;
        },
        table({ children }) {
          return (
            <div className="overflow-x-auto my-4 rounded-lg border border-[#333537]">
              <table className="w-full text-left border-collapse text-[13px]">{children}</table>
            </div>
          );
        },
        thead({ children }) { return <thead className="bg-[#1a1b1c] text-gray-400 text-xs uppercase tracking-wider">{children}</thead>; },
        tbody({ children }) { return <tbody className="divide-y divide-[#333537]">{children}</tbody>; },
        tr({ children }) { return <tr className="hover:bg-[#1e1f20]/50 transition-colors">{children}</tr>; },
        th({ children }) { return <th className="px-4 py-2.5 font-semibold border-b border-[#333537]">{highlightChildren(children, searchQuery || "")}</th>; },
        td({ children }) { return <td className="px-4 py-2.5 text-gray-300">{highlightChildren(children, searchQuery || "")}</td>; },
        strong({ children }) { return <strong className="font-semibold text-white">{children}</strong>; },
        ul({ children }) { return <ul className="list-disc list-outside mb-3 ml-4 space-y-1">{children}</ul>; },
        ol({ children }) { return <ol className="list-decimal list-outside mb-3 ml-4 space-y-1">{children}</ol>; },
        li({ children }) { return <li className="leading-snug">{highlightChildren(children, searchQuery || "")}</li>; },
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

// FIX: Wrap the export in React.memo!
export default React.memo(MarkdownRenderer);