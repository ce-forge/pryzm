import React, { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import "katex/dist/katex.min.css";
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
        style={oneDark}
        customStyle={{ margin: 0, padding: '1rem', background: 'transparent', fontSize: '13px' }}
        wrapLines={true}
        wrapLongLines={true}
      >
        {value || ""}
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
            <mark key={i} className="search-match bg-blue-500/30 text-blue-200 rounded-sm px-0.5 text-inherit transition-colors duration-200">{part}</mark>
          ) : part
        );
      }

      if (React.isValidElement(child)) {
        const element = child as React.ReactElement<{ children?: React.ReactNode }>;
        if (element.props && element.props.children) {
          return React.cloneElement(element, {
            children: highlightChildren(element.props.children, query),
          } as React.HTMLAttributes<HTMLElement>);
        }
      }
      return child;
    });
  };

  return (
    <div className="w-full">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          h1({ children }) { return <h1 className="text-2xl font-semibold tracking-tight mt-6 mb-3 first:mt-0">{highlightChildren(children, searchQuery || "")}</h1>; },
          h2({ children }) { return <h2 className="text-xl font-semibold tracking-tight mt-5 mb-2.5 first:mt-0">{highlightChildren(children, searchQuery || "")}</h2>; },
          h3({ children }) { return <h3 className="text-lg font-semibold tracking-tight mt-4 mb-2 first:mt-0">{highlightChildren(children, searchQuery || "")}</h3>; },
          h4({ children }) { return <h4 className="text-base font-semibold mt-3 mb-1.5 first:mt-0">{highlightChildren(children, searchQuery || "")}</h4>; },
          a({ href, children }) { return <a href={href} target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:text-blue-300 underline underline-offset-2 decoration-blue-400/30 hover:decoration-blue-300">{children}</a>; },
          hr() { return <hr className="my-6 border-[#2a2a2c]" />; },
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
          pre({ children }: { children?: React.ReactNode }) {
            // react-markdown wraps fenced code in <pre><code className="language-x">…</code></pre>.
            // Drill in to read the language + raw text, then render via CodeBlock.
            const codeChild = children as React.ReactElement<{ className?: string; children?: React.ReactNode }> | undefined;
            if (codeChild?.props) {
              const { className, children: codeContent } = codeChild.props;
              const match = /language-(\w+)/.exec(className || "");
              // Guard against empty / undefined code bodies — happens when
              // the streaming markdown parser sees ```lang before the
              // body has buffered, or when the model emits an empty
              // fence. `String(undefined)` would render the literal text
              // "undefined" otherwise.
              const raw = codeContent == null ? "" : String(codeContent);
              return <CodeBlock language={match ? match[1] : "text"} value={raw.replace(/\n$/, "")} />;
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
          img({ src, alt }) {
            // Bound rendered images so attached-file thumbnails (emitted
            // as base64 data URLs by format_file_analyzed) don't blow up
            // the chat width. Same renderer also handles any markdown
            // image the user/LLM pastes into chat.
            //
            // Return null when src is missing or empty — Next warns that
            // an empty-string src triggers a whole-page reload. This can
            // happen mid-stream when the markdown parser sees `![alt](`
            // before the url is fully buffered.
            if (typeof src !== "string" || !src) return null;
            return (
              // eslint-disable-next-line @next/next/no-img-element -- data: URLs don't work with next/Image without a custom loader
              <img
                src={src}
                alt={alt || "attached image"}
                loading="lazy"
                className="my-2 max-w-[240px] max-h-[240px] rounded-lg border border-[#333537] object-contain"
              />
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