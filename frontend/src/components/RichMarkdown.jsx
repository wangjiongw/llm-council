import { memo, useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './RichMarkdown.css';

const COMMON_LANGUAGE_ALIASES = {
  js: 'javascript',
  jsx: 'javascript',
  ts: 'typescript',
  tsx: 'typescript',
  py: 'python',
  rb: 'ruby',
  sh: 'bash',
  shell: 'bash',
  zsh: 'bash',
  yml: 'yaml',
  md: 'markdown',
  html: 'xml',
  txt: 'text',
  plain: 'text',
};

const HIGHLIGHT_LANGUAGES = new Set([
  'javascript',
  'typescript',
  'python',
  'bash',
  'json',
  'yaml',
  'markdown',
  'css',
  'xml',
  'sql',
  'go',
  'rust',
  'java',
  'cpp',
  'csharp',
  'diff',
]);

const MAX_HIGHLIGHT_CHARS = 80000;

let katexPromise;
let highlightPromise;
let mermaidPromise;
let mermaidRenderCounter = 0;

function loadKatex() {
  if (!katexPromise) {
    katexPromise = Promise.all([
      import('katex'),
      import('katex/dist/katex.min.css'),
    ]).then(([module]) => module.default || module);
  }
  return katexPromise;
}

function loadHighlight() {
  if (!highlightPromise) {
    highlightPromise = Promise.all([
      import('highlight.js/lib/core'),
      import('highlight.js/lib/languages/javascript'),
      import('highlight.js/lib/languages/typescript'),
      import('highlight.js/lib/languages/python'),
      import('highlight.js/lib/languages/bash'),
      import('highlight.js/lib/languages/json'),
      import('highlight.js/lib/languages/yaml'),
      import('highlight.js/lib/languages/markdown'),
      import('highlight.js/lib/languages/css'),
      import('highlight.js/lib/languages/xml'),
      import('highlight.js/lib/languages/sql'),
      import('highlight.js/lib/languages/go'),
      import('highlight.js/lib/languages/rust'),
      import('highlight.js/lib/languages/java'),
      import('highlight.js/lib/languages/cpp'),
      import('highlight.js/lib/languages/csharp'),
      import('highlight.js/lib/languages/diff'),
    ]).then(([core, ...modules]) => {
      const hljs = core.default || core;
      const languages = [
        ['javascript', modules[0]],
        ['typescript', modules[1]],
        ['python', modules[2]],
        ['bash', modules[3]],
        ['json', modules[4]],
        ['yaml', modules[5]],
        ['markdown', modules[6]],
        ['css', modules[7]],
        ['xml', modules[8]],
        ['sql', modules[9]],
        ['go', modules[10]],
        ['rust', modules[11]],
        ['java', modules[12]],
        ['cpp', modules[13]],
        ['csharp', modules[14]],
        ['diff', modules[15]],
      ];
      languages.forEach(([name, languageModule]) => {
        if (!hljs.getLanguage(name)) {
          hljs.registerLanguage(name, languageModule.default || languageModule);
        }
      });
      return hljs;
    });
  }
  return highlightPromise;
}

function loadMermaid() {
  if (!mermaidPromise) {
    mermaidPromise = import('mermaid').then((module) => {
      const mermaid = module.default || module;
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: 'strict',
        theme: 'default',
      });
      return mermaid;
    });
  }
  return mermaidPromise;
}

function stableHash(value) {
  let hash = 5381;
  for (let index = 0; index < value.length; index += 1) {
    hash = ((hash << 5) + hash) ^ value.charCodeAt(index);
  }
  return (hash >>> 0).toString(36);
}

const copyText = async (content) => {
  try {
    await navigator.clipboard.writeText(content);
    return true;
  } catch {
    const textArea = document.createElement('textarea');
    textArea.value = content;
    textArea.setAttribute('readonly', '');
    textArea.style.position = 'fixed';
    textArea.style.top = '-9999px';
    document.body.appendChild(textArea);
    textArea.select();
    try {
      return document.execCommand('copy');
    } catch {
      return false;
    } finally {
      document.body.removeChild(textArea);
    }
  }
};

function CopyControl({ content, label = 'Copy' }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    const ok = await copyText(content);
    if (!ok) return;
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  };

  return (
    <button type="button" className={`rich-copy ${copied ? 'copied' : ''}`} onClick={handleCopy}>
      {copied ? 'Copied' : label}
    </button>
  );
}

function normalizeLanguage(className = '') {
  const match = /language-([^\s]+)/.exec(className);
  const language = (match?.[1] || '').toLowerCase();
  return COMMON_LANGUAGE_ALIASES[language] || language || 'text';
}

function escapeHtml(value) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function useHighlightedCode(code, language, mode, enabled = true) {
  const fallback = useMemo(() => escapeHtml(code), [code]);
  const cacheKey = useMemo(() => `${mode}:${language}:${code}`, [code, language, mode]);
  const [result, setResult] = useState(null);

  useEffect(() => {
    if (
      !enabled ||
      mode !== 'full' ||
      code.length > MAX_HIGHLIGHT_CHARS ||
      !HIGHLIGHT_LANGUAGES.has(language)
    ) {
      return undefined;
    }

    let cancelled = false;
    loadHighlight()
      .then((hljs) => {
        if (cancelled) return;
        const highlighted = hljs.highlight(code, { language, ignoreIllegals: true }).value;
        setResult({ cacheKey, html: highlighted, state: 'highlighted' });
      })
      .catch(() => {
        if (!cancelled) setResult({ cacheKey, html: fallback, state: 'plain' });
      });

    return () => {
      cancelled = true;
    };
  }, [cacheKey, code, enabled, fallback, language, mode]);

  if (!enabled || mode !== 'full' || !HIGHLIGHT_LANGUAGES.has(language)) {
    return { html: fallback, state: 'plain' };
  }
  if (code.length > MAX_HIGHLIGHT_CHARS) return { html: fallback, state: 'large' };
  if (result?.cacheKey === cacheKey) return result;
  return { html: fallback, state: 'loading' };
}

function CodeBlock({ className, children, mode }) {
  const code = String(children || '').replace(/\n$/, '');
  const language = normalizeLanguage(className);
  const { html, state } = useHighlightedCode(code, language, mode, language !== 'mermaid');

  if (language === 'mermaid') {
    return <MermaidBlock code={code} mode={mode} />;
  }

  return (
    <div className={`rich-code-block ${state === 'plain' ? 'plain-code' : ''}`.trim()}>
      <div className="rich-code-header">
        <span>{language}</span>
        <div className="rich-header-actions">
          {state === 'loading' && <span className="rich-runtime-status">highlighting</span>}
          {state === 'large' && <span className="rich-runtime-status">plain large block</span>}
          <CopyControl content={code} label="Copy code" />
        </div>
      </div>
      <pre className={`rich-code language-${language}`}>
        <code dangerouslySetInnerHTML={{ __html: html }} />
      </pre>
    </div>
  );
}

function useMermaidSvg(code, mode) {
  const cacheKey = useMemo(() => `${mode}:${code}`, [code, mode]);
  const [result, setResult] = useState(null);

  useEffect(() => {
    if (mode !== 'full') {
      return undefined;
    }

    let cancelled = false;
    loadMermaid()
      .then((mermaid) => {
        const renderId = `rich-mermaid-${stableHash(code)}-${mermaidRenderCounter += 1}`;
        return mermaid.render(renderId, code);
      })
      .then((rendered) => {
        if (!cancelled) setResult({ cacheKey, svg: rendered.svg || '', error: '' });
      })
      .catch((error) => {
        if (!cancelled) {
          setResult({
            cacheKey,
            svg: '',
            error: error?.message || 'Unable to render Mermaid diagram.',
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [cacheKey, code, mode]);

  if (mode !== 'full') return { svg: '', error: '', state: 'deferred' };
  if (result?.cacheKey === cacheKey) return { ...result, state: result.error ? 'error' : 'ready' };
  return { svg: '', error: '', state: 'loading' };
}

function MermaidBlock({ code, mode }) {
  const { svg, error, state } = useMermaidSvg(code, mode);
  const isDeferred = state === 'deferred';

  return (
    <div className="rich-mermaid-block">
      <div className="rich-code-header">
        <span>mermaid</span>
        <div className="rich-header-actions">
          {state === 'loading' && <span className="rich-runtime-status">rendering</span>}
          <CopyControl content={code} label="Copy diagram" />
        </div>
      </div>
      {svg ? (
        <div className="rich-mermaid-rendered" dangerouslySetInnerHTML={{ __html: svg }} />
      ) : (
        <>
          <div className={`rich-mermaid-placeholder ${error ? 'error' : ''}`}>
            {isDeferred ? 'Diagram rendering is deferred for performance.' : error || 'Preparing diagram...'}
          </div>
          {!isDeferred && (state === 'error' || state === 'loading') && (
            <pre className="rich-code rich-mermaid-source">
              <code>{code}</code>
            </pre>
          )}
        </>
      )}
    </div>
  );
}

function useKatexHtml(expression, displayMode, mode) {
  const cacheKey = useMemo(() => `${mode}:${displayMode}:${expression}`, [displayMode, expression, mode]);
  const [result, setResult] = useState(null);

  useEffect(() => {
    if (mode !== 'full') {
      return undefined;
    }

    let cancelled = false;
    loadKatex()
      .then((katex) => {
        if (cancelled) return;
        setResult({
          cacheKey,
          html: katex.renderToString(expression, { throwOnError: false, displayMode }),
        });
      })
      .catch(() => {
        if (!cancelled) setResult({ cacheKey, html: '' });
      });

    return () => {
      cancelled = true;
    };
  }, [cacheKey, displayMode, expression, mode]);

  if (mode !== 'full') return '';
  return result?.cacheKey === cacheKey ? result.html : '';
}

function MathInline({ expression, mode }) {
  const html = useKatexHtml(expression, false, mode);

  if (html) {
    return <span className="rich-math-inline" dangerouslySetInnerHTML={{ __html: html }} />;
  }

  return <code className="rich-math-inline-fallback">${expression}$</code>;
}

function MathBlock({ expression, mode }) {
  const html = useKatexHtml(expression, true, mode);

  return (
    <div className="rich-math-block">
      <div className="rich-code-header">
        <span>math</span>
        <div className="rich-header-actions">
          {!html && mode === 'full' && <span className="rich-runtime-status">rendering</span>}
          <CopyControl content={expression} label="Copy formula" />
        </div>
      </div>
      {html ? (
        <div className="rich-math-rendered" dangerouslySetInnerHTML={{ __html: html }} />
      ) : (
        <code className="rich-math-fallback">{expression}</code>
      )}
    </div>
  );
}

function renderInlineMathText(text, mode, keyPrefix) {
  const parts = [];
  let cursor = 0;
  let index = 0;
  const pattern = /(^|[^\\])\$([^$\n]+?)(?<!\\)\$/g;
  let match;

  while ((match = pattern.exec(text)) !== null) {
    const dollarStart = match.index + match[1].length;
    if (dollarStart > cursor) {
      parts.push(text.slice(cursor, dollarStart));
    }
    parts.push(<MathInline expression={match[2].trim()} mode={mode} key={`${keyPrefix}-math-${index}`} />);
    cursor = dollarStart + match[2].length + 2;
    index += 1;
  }

  if (cursor < text.length) {
    parts.push(text.slice(cursor));
  }

  return parts.length ? parts : text;
}

function renderInlineMathChildren(children, mode, keyPrefix = 'inline') {
  if (typeof children === 'string') return renderInlineMathText(children, mode, keyPrefix);
  if (!Array.isArray(children)) return children;

  return children.flatMap((child, index) => (
    typeof child === 'string'
      ? renderInlineMathText(child, mode, `${keyPrefix}-${index}`)
      : child
  ));
}

function InlineMathContainer({ as: Tag, children, mode, ...props }) {
  const { node, ...rest } = props;
  void node;
  return <Tag {...rest}>{renderInlineMathChildren(children, mode, Tag)}</Tag>;
}

function MarkdownTable({ children }) {
  const tableRef = useRef(null);
  const [copied, setCopied] = useState('');

  const tableAs = (format) => {
    const rows = Array.from(tableRef.current?.querySelectorAll('tr') || []);
    const serialized = rows.map(row => {
      const cells = Array.from(row.querySelectorAll('th,td')).map(cell => cell.textContent.trim());
      if (format === 'csv') {
        return cells.map(cell => `"${cell.replace(/"/g, '""')}"`).join(',');
      }
      return `| ${cells.join(' | ')} |`;
    });

    if (format === 'markdown' && rows[0]?.querySelector('th')) {
      const count = rows[0].querySelectorAll('th,td').length;
      serialized.splice(1, 0, `| ${Array.from({ length: count }, () => '---').join(' | ')} |`);
    }

    return serialized.join('\n');
  };

  const handleCopy = async (format) => {
    const ok = await copyText(tableAs(format));
    if (!ok) return;
    setCopied(format);
    window.setTimeout(() => setCopied(''), 1600);
  };

  return (
    <div className="rich-table-wrap">
      <div className="rich-table-actions">
        <span>Table</span>
        <button type="button" className={`rich-copy ${copied === 'markdown' ? 'copied' : ''}`} onClick={() => handleCopy('markdown')}>
          {copied === 'markdown' ? 'Copied' : 'Copy Markdown'}
        </button>
        <button type="button" className={`rich-copy ${copied === 'csv' ? 'copied' : ''}`} onClick={() => handleCopy('csv')}>
          {copied === 'csv' ? 'Copied' : 'Copy CSV'}
        </button>
      </div>
      <div className="rich-table-scroll" ref={tableRef}>
        <table>{children}</table>
      </div>
    </div>
  );
}

function ImageRenderer(props) {
  const { node, ...imgProps } = props;
  void node;
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className="rich-image-button" onClick={() => setOpen(true)}>
        <img loading="lazy" decoding="async" {...imgProps} />
      </button>
      {open && (
        <div className="rich-image-preview" role="presentation" onClick={() => setOpen(false)}>
          <img src={imgProps.src} alt={imgProps.alt || ''} />
        </div>
      )}
    </>
  );
}

function compactContent(content) {
  const text = String(content || '')
    .replace(/```[\s\S]*?```/g, '[code block]')
    .replace(/!\[[^\]]*\]\([^)]+\)/g, '[image]')
    .replace(/\$\$[\s\S]*?\$\$/g, '[formula]')
    .replace(/\|(.+)\|/g, '[table]')
    .replace(/\s+/g, ' ')
    .trim();
  return text.length > 420 ? `${text.slice(0, 420)}...` : text;
}

function splitBlockMath(content) {
  const source = String(content || '');
  const segments = [];
  let cursor = 0;
  const pattern = /\$\$([\s\S]+?)\$\$/g;
  let match;

  while ((match = pattern.exec(source)) !== null) {
    if (match.index > cursor) {
      segments.push({ type: 'markdown', value: source.slice(cursor, match.index) });
    }
    segments.push({ type: 'math', value: match[1].trim() });
    cursor = match.index + match[0].length;
  }

  if (cursor < source.length) {
    segments.push({ type: 'markdown', value: source.slice(cursor) });
  }

  return segments.length ? segments : [{ type: 'markdown', value: source }];
}

function RichMarkdown({ content, mode = 'full', className = '' }) {
  const source = mode === 'compact' ? compactContent(content) : String(content || '');
  const segments = mode === 'compact' ? [{ type: 'markdown', value: source }] : splitBlockMath(source);
  const components = {
    code({ inline, className: codeClassName, children }) {
      if (inline) {
        return <code className={codeClassName}>{children}</code>;
      }
      return <CodeBlock className={codeClassName} mode={mode}>{children}</CodeBlock>;
    },
    table({ children }) {
      return <MarkdownTable>{children}</MarkdownTable>;
    },
    p(props) {
      return <InlineMathContainer as="p" mode={mode} {...props} />;
    },
    li(props) {
      return <InlineMathContainer as="li" mode={mode} {...props} />;
    },
    td(props) {
      return <InlineMathContainer as="td" mode={mode} {...props} />;
    },
    th(props) {
      return <InlineMathContainer as="th" mode={mode} {...props} />;
    },
    img: ImageRenderer,
  };

  return (
    <div className={`markdown-content rich-markdown rich-markdown-${mode} ${className}`.trim()}>
      {segments.map((segment, index) => (
        segment.type === 'math' ? (
          <MathBlock expression={segment.value} mode={mode} key={`${segment.type}-${index}`} />
        ) : (
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={components} key={`${segment.type}-${index}`}>
            {segment.value}
          </ReactMarkdown>
        )
      ))}
    </div>
  );
}

export default memo(RichMarkdown);
