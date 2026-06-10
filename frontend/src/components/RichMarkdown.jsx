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
const LONG_CODE_LINES = 120;
const COLLAPSED_CODE_LINES = 80;
const CODE_FILE_EXTENSIONS = {
  javascript: 'js',
  typescript: 'ts',
  python: 'py',
  bash: 'sh',
  json: 'json',
  yaml: 'yaml',
  markdown: 'md',
  css: 'css',
  xml: 'xml',
  sql: 'sql',
  go: 'go',
  rust: 'rs',
  java: 'java',
  cpp: 'cpp',
  csharp: 'cs',
  diff: 'diff',
  text: 'txt',
};

const PLAIN_TEXT_LANGUAGES = new Set(['text', 'txt', 'plain', 'plaintext']);

let katexPromise;
let highlightPromise;
let mermaidPromise;
let mermaidRenderCounter = 0;
const highlightCache = new Map();
const katexCache = new Map();
const mermaidCache = new Map();
const compactContentCache = new Map();
const markdownSegmentsCache = new Map();

function estimateCacheChars(value, depth = 0) {
  if (value === null || value === undefined) return 0;
  if (typeof value === 'string') return value.length;
  if (typeof value === 'number' || typeof value === 'boolean') return 8;
  if (depth > 3) return 32;
  if (Array.isArray(value)) {
    return value.reduce((total, item) => total + estimateCacheChars(item, depth + 1), 0);
  }
  if (typeof value === 'object') {
    return Object.entries(value).reduce(
      (total, [entryKey, entryValue]) => total + entryKey.length + estimateCacheChars(entryValue, depth + 1),
      0
    );
  }
  return 0;
}

function cacheChars(cache) {
  let total = 0;
  cache.forEach((value, key) => {
    total += String(key).length + estimateCacheChars(value);
  });
  return total;
}

function remember(cache, key, value, limits = {}) {
  const maxEntries = limits.maxEntries ?? 80;
  const maxChars = limits.maxChars ?? 1_500_000;
  if (cache.has(key)) cache.delete(key);
  cache.set(key, value);

  while (cache.size > maxEntries || cacheChars(cache) > maxChars) {
    const oldestKey = cache.keys().next().value;
    if (oldestKey === undefined) break;
    cache.delete(oldestKey);
  }
}

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

function contentFingerprint(value) {
  const source = String(value || '');
  return `${source.length}:${stableHash(source)}`;
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


const downloadText = (filename, content, mimeType = 'text/plain;charset=utf-8') => {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
};

const codeFilenameFor = (language) => `snippet.${CODE_FILE_EXTENSIONS[language] || 'txt'}`;

const diffLineClass = (line) => {
  if (line.startsWith('+++') || line.startsWith('---')) return 'metadata';
  if (line.startsWith('@@')) return 'hunk';
  if (line.startsWith('+')) return 'addition';
  if (line.startsWith('-')) return 'deletion';
  return '';
};

const textFromChildren = (children) => {
  if (children === null || children === undefined) return '';
  if (typeof children === 'string' || typeof children === 'number') return String(children);
  if (Array.isArray(children)) return children.map(textFromChildren).join('');
  if (children?.props?.children !== undefined) return textFromChildren(children.props.children);
  return '';
};

function useTimedReset(initialValue) {
  const [value, setValue] = useState(initialValue);
  const timeoutRef = useRef(null);

  useEffect(() => () => {
    if (timeoutRef.current) {
      window.clearTimeout(timeoutRef.current);
    }
  }, []);

  const setTemporarily = (nextValue, resetValue = initialValue, delay = 1600) => {
    if (timeoutRef.current) {
      window.clearTimeout(timeoutRef.current);
    }
    setValue(nextValue);
    timeoutRef.current = window.setTimeout(() => {
      setValue(resetValue);
      timeoutRef.current = null;
    }, delay);
  };

  return [value, setTemporarily, setValue];
}

function CopyControl({ content, label = 'Copy' }) {
  const [copied, setCopiedTemporarily] = useTimedReset(false);

  const handleCopy = async () => {
    const ok = await copyText(content);
    if (!ok) return;
    setCopiedTemporarily(true, false, 1600);
  };

  return (
    <button type="button" className={`rich-copy ${copied ? 'copied' : ''}`} onClick={handleCopy}>
      {copied ? 'Copied' : label}
    </button>
  );
}

function rawLanguage(className = '') {
  const match = /language-([^\s]+)/.exec(className);
  return (match?.[1] || '').toLowerCase();
}

function normalizeLanguage(className = '') {
  const language = rawLanguage(className);
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
  const cacheKey = useMemo(() => `${mode}:${language}:${contentFingerprint(code)}`, [code, language, mode]);
  const cached = highlightCache.get(cacheKey);
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
        const nextResult = { cacheKey, html: highlighted, state: 'highlighted' };
        remember(highlightCache, cacheKey, nextResult, { maxEntries: 80, maxChars: 4_000_000 });
        setResult(nextResult);
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
  if (cached) return cached;
  if (result?.cacheKey === cacheKey) return result;
  return { html: fallback, state: 'loading' };
}

function CodeBlock({ className, children, mode }) {
  const code = String(children || '').replace(/\n$/, '');
  const rawLang = rawLanguage(className);
  const language = normalizeLanguage(className);
  const lineCount = Math.max(1, code.split('\n').length);
  const isLongCode = mode === 'full' && lineCount > LONG_CODE_LINES;
  const [isExpanded, setIsExpanded] = useState(false);
  const isCollapsed = isLongCode && !isExpanded;
  const displayedLines = isCollapsed ? code.split('\n').slice(0, COLLAPSED_CODE_LINES) : code.split('\n');
  const displayedCode = displayedLines.join('\n');
  const visibleLineCount = displayedLines.length;
  const lineNumbers = Array.from({ length: visibleLineCount }, (_, index) => index + 1);
  const isDiff = language === 'diff';
  const { html, state } = useHighlightedCode(displayedCode, language, mode, language !== 'mermaid' && !isDiff);

  if (language === 'mermaid') {
    return <MermaidBlock code={code} mode={mode} />;
  }

  if (rawLang && PLAIN_TEXT_LANGUAGES.has(language)) {
    return <PlainTextBlock code={code} />;
  }

  return (
    <div className={`rich-code-block ${state === 'plain' ? 'plain-code' : ''} ${isDiff ? 'diff-code' : ''} ${isCollapsed ? 'collapsed-code' : ''}`.trim()}>
      <div className="rich-code-header">
        <span>{language}</span>
        <div className="rich-header-actions">
          {state === 'loading' && <span className="rich-runtime-status">highlighting</span>}
          {state === 'large' && <span className="rich-runtime-status">plain large block</span>}
          {lineCount > 1 && <span className="rich-runtime-status">{lineCount} lines</span>}
          <button type="button" className="rich-copy" onClick={() => downloadText(codeFilenameFor(language), code)}>
            Download
          </button>
          <CopyControl content={code} label="Copy code" />
        </div>
      </div>
      <pre className={`rich-code language-${language}`}>
        <code className="rich-code-with-lines">
          <span className="rich-code-line-numbers" aria-hidden="true">
            {lineNumbers.map((lineNumber) => (
              <span key={lineNumber}>{lineNumber}</span>
            ))}
          </span>
          {isDiff ? (
            <span className="rich-code-content rich-diff-lines">
              {displayedLines.map((line, index) => (
                <span className={`rich-diff-line ${diffLineClass(line)}`.trim()} key={`${index}-${line.slice(0, 12)}`}>
                  {line || ' '}
                </span>
              ))}
            </span>
          ) : (
            <span className="rich-code-content" dangerouslySetInnerHTML={{ __html: html || '&nbsp;' }} />
          )}
        </code>
      </pre>
      {isLongCode && (
        <div className="rich-code-footer">
          <button type="button" onClick={() => setIsExpanded((expanded) => !expanded)}>
            {isExpanded ? 'Collapse code' : `Show all ${lineCount} lines`}
          </button>
          {isCollapsed && <span>Showing first {Math.min(COLLAPSED_CODE_LINES, lineCount)} lines</span>}
        </div>
      )}
    </div>
  );
}

function PlainTextBlock({ code }) {
  return <div className="rich-plain-text-block">{code}</div>;
}

function useMermaidSvg(code, mode) {
  const cacheKey = useMemo(() => `${mode}:${contentFingerprint(code)}`, [code, mode]);
  const cached = mermaidCache.get(cacheKey);
  const [result, setResult] = useState(null);

  useEffect(() => {
    if (mode !== 'full' || cached) {
      return undefined;
    }

    let cancelled = false;
    loadMermaid()
      .then((mermaid) => {
        const renderId = `rich-mermaid-${stableHash(code)}-${mermaidRenderCounter += 1}`;
        return mermaid.render(renderId, code);
      })
      .then((rendered) => {
        if (!cancelled) {
          const nextResult = { cacheKey, svg: rendered.svg || '', error: '' };
          remember(mermaidCache, cacheKey, nextResult, { maxEntries: 40, maxChars: 3_000_000 });
          setResult(nextResult);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          const nextResult = {
            cacheKey,
            svg: '',
            error: error?.message || 'Unable to render Mermaid diagram.',
          };
          remember(mermaidCache, cacheKey, nextResult, { maxEntries: 40, maxChars: 3_000_000 });
          setResult(nextResult);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [cacheKey, cached, code, mode]);

  if (mode !== 'full') return { svg: '', error: '', state: 'deferred' };
  if (cached) return { ...cached, state: cached.error ? 'error' : 'ready' };
  if (result?.cacheKey === cacheKey) return { ...result, state: result.error ? 'error' : 'ready' };
  return { svg: '', error: '', state: 'loading' };
}

function MermaidBlock({ code, mode }) {
  const { svg, error, state } = useMermaidSvg(code, mode);
  const [previewOpen, setPreviewOpen] = useState(false);
  const isDeferred = state === 'deferred';
  const filename = `diagram-${stableHash(code)}.svg`;

  const downloadPng = async () => {
    if (!svg) return;
    const image = new Image();
    const svgUrl = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml;charset=utf-8' }));
    image.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1, image.naturalWidth || image.width || 1200);
      canvas.height = Math.max(1, image.naturalHeight || image.height || 800);
      const context = canvas.getContext('2d');
      context?.drawImage(image, 0, 0);
      canvas.toBlob((blob) => {
        if (!blob) return;
        const pngUrl = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = pngUrl;
        link.download = filename.replace(/\.svg$/, '.png');
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(pngUrl);
      }, 'image/png');
      URL.revokeObjectURL(svgUrl);
    };
    image.onerror = () => URL.revokeObjectURL(svgUrl);
    image.src = svgUrl;
  };

  return (
    <div className="rich-mermaid-block">
      <div className="rich-code-header">
        <span>mermaid</span>
        <div className="rich-header-actions">
          {state === 'loading' && <span className="rich-runtime-status">rendering</span>}
          {svg && <button type="button" className="rich-copy" onClick={() => setPreviewOpen(true)}>Preview</button>}
          {svg && <CopyControl content={svg} label="Copy SVG" />}
          {svg && <button type="button" className="rich-copy" onClick={() => downloadText(filename, svg, 'image/svg+xml;charset=utf-8')}>SVG</button>}
          {svg && <button type="button" className="rich-copy" onClick={downloadPng}>PNG</button>}
          <CopyControl content={code} label="Copy source" />
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
      {previewOpen && (
        <div className="rich-mermaid-preview" role="dialog" aria-modal="true" aria-label="Mermaid diagram preview">
          <div className="rich-mermaid-preview-toolbar">
            <span>Mermaid preview</span>
            <button type="button" className="rich-copy" onClick={() => setPreviewOpen(false)}>Close</button>
          </div>
          <div className="rich-mermaid-preview-canvas" dangerouslySetInnerHTML={{ __html: svg }} />
        </div>
      )}
    </div>
  );
}

function useKatexHtml(expression, displayMode, mode) {
  const cacheKey = useMemo(() => `${mode}:${displayMode}:${contentFingerprint(expression)}`, [displayMode, expression, mode]);
  const cached = katexCache.get(cacheKey);
  const [result, setResult] = useState(null);

  useEffect(() => {
    if (mode !== 'full') {
      return undefined;
    }

    let cancelled = false;
    loadKatex()
      .then((katex) => {
        if (cancelled) return;
        const nextResult = {
          cacheKey,
          html: katex.renderToString(expression, { throwOnError: false, displayMode }),
        };
        remember(katexCache, cacheKey, nextResult, { maxEntries: 160, maxChars: 1_000_000 });
        setResult(nextResult);
      })
      .catch(() => {
        if (!cancelled) setResult({ cacheKey, html: '' });
      });

    return () => {
      cancelled = true;
    };
  }, [cacheKey, displayMode, expression, mode]);

  if (mode !== 'full') return '';
  if (cached) return cached.html;
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

const LATEX_COMMAND_PATTERN = /\\[a-zA-Z]+/;
const MATH_STRUCTURE_PATTERN = /(?:[_^{}=<>]|\\[,;:!]|[A-Za-z0-9)]\s*_\s*[A-Za-z0-9{\\])/;

function looksLikeMathExpression(value, { inline = false } = {}) {
  const text = String(value || '').trim();
  if (!text) return false;
  if (inline && text.length > 160) return false;
  if (!inline && text.length > 12000) return false;
  if (/^\[[ xX]\]/.test(text)) return false;
  if (LATEX_COMMAND_PATTERN.test(text)) return true;
  return MATH_STRUCTURE_PATTERN.test(text);
}

function isEscaped(text, index) {
  let slashes = 0;
  for (let pos = index - 1; pos >= 0 && text[pos] === '\\'; pos -= 1) {
    slashes += 1;
  }
  return slashes % 2 === 1;
}

function findUnescapedDollar(text, start) {
  for (let pos = start; pos < text.length; pos += 1) {
    if (text[pos] === '\n') return -1;
    if (text[pos] === '$' && !isEscaped(text, pos)) return pos;
  }
  return -1;
}

function findBalancedParenEnd(text, start) {
  let depth = 0;
  for (let pos = start; pos < text.length; pos += 1) {
    const char = text[pos];
    if (char === '\n') return -1;
    if (isEscaped(text, pos)) continue;
    if (char === '(') depth += 1;
    if (char === ')') {
      depth -= 1;
      if (depth === 0) return pos;
    }
  }
  return -1;
}

function findNextInlineMath(text, startAt) {
  for (let pos = startAt; pos < text.length; pos += 1) {
    if (text[pos] === '$' && !isEscaped(text, pos)) {
      const end = findUnescapedDollar(text, pos + 1);
      if (end > pos + 1) {
        const expression = text.slice(pos + 1, end).trim();
        if (expression) {
          return { start: pos, end: end + 1, expression };
        }
      }
    }

    if (text[pos] === '\\' && text[pos + 1] === '(') {
      const end = text.indexOf('\\)', pos + 2);
      if (end > pos + 2) {
        const expression = text.slice(pos + 2, end).trim();
        if (expression && !expression.includes('\n')) {
          return { start: pos, end: end + 2, expression };
        }
      }
    }

    if (text[pos] === '(' && !isEscaped(text, pos)) {
      const end = findBalancedParenEnd(text, pos);
      if (end > pos + 1) {
        const expression = text.slice(pos + 1, end).trim();
        if (LATEX_COMMAND_PATTERN.test(expression) && looksLikeMathExpression(expression, { inline: true })) {
          return { start: pos, end: end + 1, expression };
        }
      }
    }
  }
  return null;
}

function renderInlineMathText(text, mode, keyPrefix) {
  const parts = [];
  let cursor = 0;
  let index = 0;
  let match = findNextInlineMath(text, cursor);

  while (match) {
    if (match.start > cursor) {
      parts.push(text.slice(cursor, match.start));
    }
    parts.push(<MathInline expression={match.expression} mode={mode} key={`${keyPrefix}-math-${index}`} />);
    cursor = match.end;
    index += 1;
    match = findNextInlineMath(text, cursor);
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
  const [copied, setCopiedTemporarily] = useTimedReset('');
  const [filter, setFilter] = useState('');
  const [sortConfig, setSortConfig] = useState({ column: '', direction: 'asc' });
  const [columnLabels, setColumnLabels] = useState([]);

  const rowsForExport = () => Array.from(tableRef.current?.querySelectorAll('tr') || [])
    .filter(row => row.style.display !== 'none');

  const tableAs = (format) => {
    const rows = rowsForExport();
    const serialized = rows.map(row => {
      const cells = Array.from(row.querySelectorAll('th,td')).map(cell => (
        cell.dataset.plainText || cell.textContent.trim()
      ));
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
    setCopiedTemporarily(format, '', 1600);
  };

  const compareCells = (a, b, columnIndex) => {
    const aText = a.children[columnIndex]?.textContent.trim() || '';
    const bText = b.children[columnIndex]?.textContent.trim() || '';
    const aNumber = Number(aText.replace(/,/g, ''));
    const bNumber = Number(bText.replace(/,/g, ''));
    if (!Number.isNaN(aNumber) && !Number.isNaN(bNumber)) return aNumber - bNumber;
    const aDate = Date.parse(aText);
    const bDate = Date.parse(bText);
    if (!Number.isNaN(aDate) && !Number.isNaN(bDate)) return aDate - bDate;
    return aText.localeCompare(bText, undefined, { numeric: true, sensitivity: 'base' });
  };

  useEffect(() => {
    let cancelled = false;
    window.queueMicrotask(() => {
      if (cancelled) return;
      const table = tableRef.current?.querySelector('table');
      const firstRow = table?.querySelector('tr');
      if (!firstRow) return;
      setColumnLabels(Array.from(firstRow.querySelectorAll('th,td')).map((cell, index) => cell.textContent.trim() || `Column ${index + 1}`));
    });
    return () => {
      cancelled = true;
    };
  }, [children]);

  useEffect(() => {
    const table = tableRef.current?.querySelector('table');
    const body = table?.querySelector('tbody');
    if (!body) return;

    const rows = Array.from(body.querySelectorAll('tr'));
    const normalizedFilter = filter.trim().toLowerCase();
    rows.forEach((row) => {
      row.style.display = !normalizedFilter || row.textContent.toLowerCase().includes(normalizedFilter) ? '' : 'none';
    });

    if (sortConfig.column !== '') {
      const columnIndex = Number(sortConfig.column);
      rows
        .sort((a, b) => compareCells(a, b, columnIndex) * (sortConfig.direction === 'desc' ? -1 : 1))
        .forEach(row => body.appendChild(row));
    }
  }, [filter, sortConfig]);

  return (
    <div className="rich-table-wrap">
      <div className="rich-table-actions">
        <span>Table</span>
        <input
          type="search"
          className="rich-table-search"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="Find rows"
          aria-label="Search table rows"
        />
        <select
          className="rich-table-sort"
          value={sortConfig.column}
          onChange={(event) => setSortConfig({ column: event.target.value, direction: 'asc' })}
          aria-label="Sort table column"
        >
          <option value="">No sort</option>
          {columnLabels.map((label, index) => <option value={index} key={`${label}-${index}`}>{label}</option>)}
        </select>
        {sortConfig.column !== '' && (
          <button type="button" className="rich-copy" onClick={() => setSortConfig((current) => ({ ...current, direction: current.direction === 'asc' ? 'desc' : 'asc' }))}>
            {sortConfig.direction === 'asc' ? 'Asc' : 'Desc'}
          </button>
        )}
        <button type="button" className={`rich-copy ${copied === 'markdown' ? 'copied' : ''}`} onClick={() => handleCopy('markdown')}>
          {copied === 'markdown' ? 'Copied' : 'Copy Markdown'}
        </button>
        <button type="button" className={`rich-copy ${copied === 'csv' ? 'copied' : ''}`} onClick={() => handleCopy('csv')}>
          {copied === 'csv' ? 'Copied' : 'Copy CSV'}
        </button>
        <button type="button" className="rich-copy" onClick={() => downloadText('table.csv', tableAs('csv'), 'text/csv;charset=utf-8')}>
          Download CSV
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
  const source = String(content || '');
  const cacheKey = contentFingerprint(source);
  const cached = compactContentCache.get(cacheKey);
  if (cached) return cached;

  const text = source
    .replace(/```[\s\S]*?```/g, '[code block]')
    .replace(/!\[[^\]]*\]\([^)]+\)/g, '[image]')
    .replace(/\$\$[\s\S]*?\$\$/g, '[formula]')
    .replace(/\\\[[\s\S]*?\\\]/g, '[formula]')
    .replace(/(^|\n{2,})[ \t]*\[([\s\S]+?)\][ \t]*(?=\n{2,}|$)/g, (match, prefix, expression) => (
      looksLikeMathExpression(expression) ? `${prefix}[formula]` : match
    ))
    .replace(/\|(.+)\|/g, '[table]')
    .replace(/\s+/g, ' ')
    .trim();
  const compact = text.length > 420 ? `${text.slice(0, 420)}...` : text;
  remember(compactContentCache, cacheKey, compact, { maxEntries: 160, maxChars: 250_000 });
  return compact;
}

function collectBlockMathMatches(source) {
  const matches = [];
  const addPatternMatches = (pattern, getMatch) => {
    let match;
    while ((match = pattern.exec(source)) !== null) {
      const next = getMatch(match);
      if (next?.expression && (next.explicit || looksLikeMathExpression(next.expression))) {
        matches.push(next);
      }
    }
  };

  addPatternMatches(/\$\$([\s\S]+?)\$\$/g, (match) => ({
    start: match.index,
    end: match.index + match[0].length,
    expression: match[1].trim(),
    explicit: true,
  }));
  addPatternMatches(/\\\[([\s\S]+?)\\\]/g, (match) => ({
    start: match.index,
    end: match.index + match[0].length,
    expression: match[1].trim(),
    explicit: true,
  }));
  addPatternMatches(/(^|\n{2,})[ \t]*\[([\s\S]+?)\][ \t]*(?=\n{2,}|$)/g, (match) => {
    const start = match.index + match[1].length;
    return {
      start,
      end: match.index + match[0].length,
      expression: match[2].trim(),
    };
  });

  return matches
    .sort((a, b) => (a.start - b.start) || (b.end - a.end))
    .reduce((accepted, match) => {
      const last = accepted[accepted.length - 1];
      if (last && match.start < last.end) return accepted;
      accepted.push(match);
      return accepted;
    }, []);
}

function splitBlockMath(content) {
  const source = String(content || '');
  const cacheKey = contentFingerprint(source);
  const cached = markdownSegmentsCache.get(cacheKey);
  if (cached) return cached;

  const segments = [];
  let cursor = 0;
  const matches = collectBlockMathMatches(source);

  matches.forEach((match) => {
    if (match.start > cursor) {
      segments.push({ type: 'markdown', value: source.slice(cursor, match.start) });
    }
    segments.push({ type: 'math', value: match.expression });
    cursor = match.end;
  });

  if (cursor < source.length) {
    segments.push({ type: 'markdown', value: source.slice(cursor) });
  }

  const result = segments.length ? segments : [{ type: 'markdown', value: source }];
  remember(markdownSegmentsCache, cacheKey, result, { maxEntries: 80, maxChars: 2_000_000 });
  return result;
}

function useDeferredFullMode(requestedMode) {
  const rootRef = useRef(null);
  const idleHandleRef = useRef(null);
  const [hasEnteredViewport, setHasEnteredViewport] = useState(
    () => typeof IntersectionObserver === 'undefined'
  );

  useEffect(() => {
    if (requestedMode !== 'full' || hasEnteredViewport) {
      return undefined;
    }

    const node = rootRef.current;
    if (!node) {
      return undefined;
    }

    const cancelIdle = () => {
      const handle = idleHandleRef.current;
      if (!handle) return;
      if (handle.type === 'idle') {
        window.cancelIdleCallback?.(handle.id);
      } else {
        window.clearTimeout(handle.id);
      }
      idleHandleRef.current = null;
    };

    const promoteToFull = () => {
      if (idleHandleRef.current) return;
      if (typeof window.requestIdleCallback === 'function') {
        const id = window.requestIdleCallback(() => {
          idleHandleRef.current = null;
          setHasEnteredViewport(true);
        }, { timeout: 900 });
        idleHandleRef.current = { type: 'idle', id };
      } else {
        const id = window.setTimeout(() => {
          idleHandleRef.current = null;
          setHasEnteredViewport(true);
        }, 80);
        idleHandleRef.current = { type: 'timeout', id };
      }
    };

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          promoteToFull();
          observer.disconnect();
        }
      },
      { rootMargin: '640px 0px' }
    );
    observer.observe(node);
    return () => {
      observer.disconnect();
      cancelIdle();
    };
  }, [hasEnteredViewport, requestedMode]);

  const effectiveMode = requestedMode === 'full' && !hasEnteredViewport ? 'compact' : requestedMode;
  return [rootRef, effectiveMode];
}

function RichMarkdown({ content, mode = 'full', className = '' }) {
  const [rootRef, effectiveMode] = useDeferredFullMode(mode);
  const source = effectiveMode === 'compact' ? compactContent(content) : String(content || '');
  const segments = useMemo(
    () => (effectiveMode === 'compact' ? [{ type: 'markdown', value: source }] : splitBlockMath(source)),
    [effectiveMode, source]
  );
  const components = useMemo(() => ({
    code({ inline, node, className: codeClassName, children }) {
      const hasLanguage = Boolean(rawLanguage(codeClassName));
      const isSingleLineCode = node?.position?.start?.line === node?.position?.end?.line;
      const isInlineCode = inline ?? (!hasLanguage && isSingleLineCode);
      if (isInlineCode) {
        return <code className={`rich-inline-code ${codeClassName || ''}`.trim()}>{children}</code>;
      }
      return <CodeBlock className={codeClassName} mode={effectiveMode}>{children}</CodeBlock>;
    },
    table({ children }) {
      return <MarkdownTable>{children}</MarkdownTable>;
    },
    p(props) {
      return <InlineMathContainer as="p" mode={effectiveMode} {...props} />;
    },
    li(props) {
      return <InlineMathContainer as="li" mode={effectiveMode} {...props} />;
    },
    td(props) {
      return <InlineMathContainer as="td" mode={effectiveMode} data-plain-text={textFromChildren(props.children).trim()} {...props} />;
    },
    th(props) {
      return <InlineMathContainer as="th" mode={effectiveMode} data-plain-text={textFromChildren(props.children).trim()} {...props} />;
    },
    img: ImageRenderer,
  }), [effectiveMode]);
  const deferredClass = mode === 'full' && effectiveMode !== 'full' ? 'rich-markdown-deferred' : '';

  return (
    <div ref={rootRef} className={`markdown-content rich-markdown rich-markdown-${effectiveMode} ${deferredClass} ${className}`.trim()}>
      {segments.map((segment, index) => (
        segment.type === 'math' ? (
          <MathBlock expression={segment.value} mode={effectiveMode} key={`${segment.type}-${index}`} />
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
