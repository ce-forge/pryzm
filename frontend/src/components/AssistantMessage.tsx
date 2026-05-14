import React, { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";
import { DatabaseIcon, AlertIcon, TerminalIcon } from "./Icons";

const CodeBlock = ({ language, value }: { language: string, value: string }) => {
  const [copied, setCopied] = useState(false);
  
  const handleCopy = async () => {
    if (!value) return;
    try {
      // Try modern API first (requires localhost or HTTPS)
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(value);
      } else {
        // Fallback for non-secure HTTP connections (like local network testing)
        const textArea = document.createElement("textarea");
        textArea.value = value;
        textArea.style.position = "fixed"; // Avoid scrolling to bottom
        textArea.style.left = "-999999px";
        textArea.style.top = "-999999px";
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        document.execCommand('copy');
        textArea.remove();
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy text: ', err);
    }
  };

  return (
    <div className="relative rounded-xl overflow-hidden border border-[#333537] my-4 shadow-lg bg-[#0d0d0d] w-full max-w-full">
      <div className="flex items-center justify-between px-4 py-1.5 bg-[#1a1b1c] border-b border-[#333537] text-xs text-gray-400 select-none">
        <span className="font-mono lowercase tracking-wide">{language || 'text'}</span>
        <button onClick={handleCopy} className="flex items-center gap-1.5 hover:text-[#e3e3e3] transition-colors focus:outline-none">
          {copied ? <span className="text-emerald-400">Copied!</span> : <span>Copy</span>}
        </button>
      </div>
      <SyntaxHighlighter 
        language={language} 
        style={vscDarkPlus} 
        customStyle={{ margin: 0, padding: '1rem', background: 'transparent', fontSize: '13px' }} 
        wrapLines={true} 
        wrapLongLines={true}
      >
        {value}
      </SyntaxHighlighter>
    </div>
  );
};

function AssistantMessage({ content, searchQuery }: { content: string, searchQuery?: string }) {
  
  const highlightChildren = (children: React.ReactNode, query: string): React.ReactNode => {
    if (!query) return children;

    return React.Children.map(children, (child) => {
      if (typeof child === 'string') {
        const escapedQuery = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const parts = child.split(new RegExp(`(${escapedQuery})`, 'gi'));
        return parts.map((part, i) =>
          part.toLowerCase() === query.toLowerCase() ? (
            <mark key={i} className="bg-blue-500/30 text-blue-200 rounded-sm px-0.5">{part}</mark>
          ) : part
        );
      }

      if (React.isValidElement(child)) {
        const element = child as React.ReactElement<{ children?: React.ReactNode }>;
        if (element.props && element.props.children) {
          return React.cloneElement(element, {
            children: highlightChildren(element.props.children, query)
          } as any);
        }
      }
      return child;
    });
  };

  return (
    <div className="w-full">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p({ children }) { return <p className="mb-4 last:mb-0 leading-relaxed w-full">{highlightChildren(children, searchQuery || "")}</p>; },
          blockquote({ children }) {
            const extractText = (nodes: React.ReactNode): string => {
              return React.Children.toArray(nodes).map(node => {
                if (typeof node === 'string') return node;
                if (React.isValidElement(node)) {
                  const element = node as React.ReactElement<{ children?: React.ReactNode }>;
                  if (element.props && element.props.children) {
                      return extractText(element.props.children);
                  }
                }
                return '';
              }).join('');
            };

            const text = extractText(children);
            let Icon = <TerminalIcon />;
            if (text.includes("Knowledge Base") || text.includes("File Analyzed")) Icon = <DatabaseIcon />;
            else if (text.includes("Error")) Icon = <AlertIcon />;

            return (
              <blockquote className="bg-[#1a1b1c] border border-[#333537] border-l-4 border-l-blue-500 text-gray-300 px-4 py-3 rounded-r-lg my-4 flex items-start gap-3">
                {Icon}
                <div className="flex-1 text-[13px] break-words min-w-0">{highlightChildren(children, searchQuery || "")}</div>
              </blockquote>
            );
          },
          pre({ children }: any) {
            if (children?.props) {
              const { className, children: codeContent } = children.props;
              const match = /language-(\w+)/.exec(className || "");
              return <CodeBlock language={match ? match[1] : "text"} value={String(codeContent).replace(/\n$/, "")} />;
            }
            return <pre className="max-w-full overflow-x-auto">{children}</pre>;
          },
          code({ children }) {
            // whitespace-nowrap keeps inline tokens (tool names, paths, etc.)
            // as a single visual pill. The old `break-all` let the browser
            // split mid-token (e.g. `search_knowledge_` + `base` on separate
            // lines), which looked broken. With nowrap the paragraph wraps
            // BEFORE the code element instead of through it.
            //
            // inline-block + max-w-full + overflow-x-auto bounds the pill to
            // the chat width — for very long content (tool-arg dicts, UUIDs,
            // long paths) the pill becomes horizontally scrollable instead of
            // bleeding past the right edge.
            return (
              <code className="bg-[#1e1f20] text-emerald-300 px-1.5 py-0.5 rounded text-[13px] border border-[#333537] whitespace-nowrap inline-block max-w-full overflow-x-auto align-middle">
                {children}
              </code>
            );
          },
          ul({ children }) { return <ul className="list-disc ml-6 mb-4 space-y-2">{children}</ul>; },
          ol({ children }) { return <ol className="list-decimal ml-6 mb-4 space-y-2">{children}</ol>; },
          li({ children }) { return <li className="mb-1">{highlightChildren(children, searchQuery || "")}</li>; },
          
          // --- NEW: Beautiful Table Styling ---
          table({ children }) { 
            return (
              <div className="overflow-x-auto my-6 w-full rounded-lg border border-[#333537]">
                <table className="w-full text-left border-collapse text-sm text-[#e3e3e3]">{children}</table>
              </div>
            ); 
          },
          thead({ children }) { 
            return <thead className="bg-[#1a1b1c] text-gray-400 border-b border-[#333537]">{children}</thead>; 
          },
          tbody({ children }) { 
            return <tbody className="divide-y divide-[#333537] bg-[#0d0d0d]">{children}</tbody>; 
          },
          tr({ children }) { 
            return <tr className="hover:bg-[#1e1f20]/50 transition-colors">{children}</tr>; 
          },
          th({ children }) { 
            return <th className="px-4 py-3 font-medium whitespace-nowrap">{children}</th>; 
          },
          td({ children }) { 
            return <td className="px-4 py-3 min-w-[120px]">{highlightChildren(children, searchQuery || "")}</td>; 
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

export default React.memo(AssistantMessage);