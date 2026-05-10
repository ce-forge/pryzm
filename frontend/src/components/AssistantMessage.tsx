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
  
  // Recursive function to highlight text within markdown nodes
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

      // THE FIX: Type assertion to ReactElement<{ children?: ReactNode }>
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
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        p({ children }) { return <p className="mb-4 last:mb-0 leading-relaxed">{highlightChildren(children, searchQuery || "")}</p>; },
        blockquote({ children }) {
          const extractText = (nodes: React.ReactNode): string => {
            return React.Children.toArray(nodes).map(node => {
              if (typeof node === 'string') return node;
              
              // THE FIX: Same type assertion here for the extractor
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
              <div className="flex-1 text-[13px]">{highlightChildren(children, searchQuery || "")}</div>
            </blockquote>
          );
        },
        pre({ children }: any) {
          if (children?.props) {
            const { className, children: codeContent } = children.props;
            const match = /language-(\w+)/.exec(className || "");
            return <CodeBlock language={match ? match[1] : "text"} value={String(codeContent).replace(/\n$/, "")} />;
          }
          return <pre>{children}</pre>;
        },
        code({ children }) {
          return <code className="bg-[#1e1f20] text-emerald-300 px-1.5 py-0.5 rounded text-[13px] border border-[#333537]">{children}</code>;
        },
        ul({ children }) { return <ul className="list-disc ml-6 mb-4 space-y-2">{children}</ul>; },
        ol({ children }) { return <ol className="list-decimal ml-6 mb-4 space-y-2">{children}</ol>; },
        li({ children }) { return <li className="mb-1">{highlightChildren(children, searchQuery || "")}</li>; },
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

export default React.memo(AssistantMessage);