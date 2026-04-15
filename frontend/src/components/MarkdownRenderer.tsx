import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';

interface Props {
  content: string;
  compact?: boolean;
}

export function MarkdownRenderer({ content, compact = false }: Props) {
  return (
    <div
      className={
        compact
          ? 'prose prose-sm prose-stone max-w-none text-sm leading-relaxed'
          : 'prose prose-stone max-w-none text-sm leading-[1.75]'
      }
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          h1: ({ children }) => (
            <h1 className="text-xl font-bold mt-6 mb-3 pb-1.5 border-b border-stone-200 text-[#1e3a5f]">
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2 className="text-lg font-semibold mt-5 mb-2 text-[#1e3a5f]">{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 className="text-base font-semibold mt-4 mb-1.5 text-stone-800">{children}</h3>
          ),
          p: ({ children }) => <p className="my-2 text-stone-800">{children}</p>,
          ul: ({ children }) => <ul className="my-2 pl-5 list-disc space-y-1">{children}</ul>,
          ol: ({ children }) => <ol className="my-2 pl-5 list-decimal space-y-1">{children}</ol>,
          li: ({ children }) => <li className="text-stone-800">{children}</li>,
          blockquote: ({ children }) => (
            <blockquote className="border-l-3 border-[#1e3a5f]/30 pl-4 my-3 text-stone-600 italic">
              {children}
            </blockquote>
          ),
          code: ({ className, children, ...props }) => {
            const isBlock = className?.startsWith('language-');
            if (isBlock) {
              return (
                <pre className="bg-stone-50 border border-stone-200 rounded-lg p-3 my-3 overflow-x-auto text-xs leading-relaxed">
                  <code className={className} {...props}>
                    {children}
                  </code>
                </pre>
              );
            }
            return (
              <code className="bg-stone-100 text-[#b91c1c] rounded px-1.5 py-0.5 text-[0.85em] font-mono" {...props}>
                {children}
              </code>
            );
          },
          pre: ({ children }) => <>{children}</>,
          table: ({ children }) => (
            <div className="my-3 overflow-x-auto">
              <table className="min-w-full border-collapse border border-stone-200 text-xs">
                {children}
              </table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-stone-50">{children}</thead>,
          th: ({ children }) => (
            <th className="border border-stone-200 px-3 py-1.5 text-left font-semibold text-stone-700">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border border-stone-200 px-3 py-1.5 text-stone-700">{children}</td>
          ),
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[#1e40af] underline underline-offset-2 hover:text-[#1e3a5f]"
            >
              {children}
            </a>
          ),
          hr: () => <hr className="my-4 border-stone-200" />,
          strong: ({ children }) => <strong className="font-semibold text-stone-900">{children}</strong>,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
