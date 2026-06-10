import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import RichMarkdown from './RichMarkdown';

vi.mock('mermaid', () => ({
  default: {
    initialize: vi.fn(),
    render: vi.fn(async () => ({ svg: '<svg role="img"><text>Graph</text></svg>' })),
  },
}));

beforeEach(() => {
  vi.clearAllMocks();
  navigator.clipboard.writeText.mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('RichMarkdown', () => {
  it('adds table search, sort, and CSV copy controls', async () => {
    render(<RichMarkdown content={`| Name | Score |\n| --- | ---: |\n| Alpha | 2 |\n| Beta | 10 |`} />);

    expect(await screen.findByText('Table')).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('Search table rows'), 'Beta');

    expect(screen.getByText('Alpha').closest('tr').style.display).toBe('none');
    expect(screen.getByText('Beta').closest('tr').style.display).toBe('');

    await userEvent.selectOptions(screen.getByLabelText('Sort table column'), '1');
    expect(screen.getByRole('button', { name: 'Asc' })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Copy CSV' }));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(expect.stringContaining('"Beta","10"'));
  });

  it('keeps backticked table text inline and copies clean table values', async () => {
    const { container } = render(<RichMarkdown content={`| Kind | Value |\n| --- | --- |\n| Mode | \`text\` |`} />);

    expect(await screen.findByText('Table')).toBeInTheDocument();
    expect(container.querySelector('.rich-table-scroll .rich-code-block')).toBeNull();
    expect(container.querySelector('.rich-table-scroll .rich-inline-code')).toHaveTextContent('text');

    await userEvent.click(screen.getByRole('button', { name: 'Copy CSV' }));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('"Kind","Value"\n"Mode","text"');
  });

  it('renders explicit text fences as plain text instead of full code tools', async () => {
    const { container } = render(<RichMarkdown content={`Before\n\n\`\`\`text\nplain text only\n\`\`\`\n\nAfter`} />);

    expect(await screen.findByText('plain text only')).toHaveClass('rich-plain-text-block');
    expect(container.querySelector('.rich-code-block')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Download' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Copy code' })).not.toBeInTheDocument();
  });

  it('renders diff code with line classes and download control', async () => {
    render(<RichMarkdown content={`\`\`\`diff\n@@ hunk\n+added\n-removed\n\`\`\``} />);

    expect(await screen.findByText('diff')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Download' })).toBeInTheDocument();
    expect(document.querySelector('.rich-diff-line.addition')).toHaveTextContent('+added');
    expect(document.querySelector('.rich-diff-line.deletion')).toHaveTextContent('-removed');
  });

  it('renders Mermaid diagrams with source and SVG operations', async () => {
    render(<RichMarkdown content={`\`\`\`mermaid\ngraph TD; A-->B;\n\`\`\``} />);

    expect(await screen.findByText('Copy SVG')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Copy source' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Preview' }));
    expect(screen.getByRole('dialog', { name: 'Mermaid diagram preview' })).toBeInTheDocument();
  });

  it('renders loose bracket math blocks and parenthesized LaTeX inline math', async () => {
    const content = String.raw`如果采用 Transformer，可以使用连续时间编码：

[ \mathbf{e}_i = \text{Time2Vec}(\log(1+t_i)) ]

并在注意力中加入相对时间偏置：

[ \text{Attention}(i,j)
\frac{Q_i K_j^\top}{\sqrt{d}} + b(\log(1+|t_i-t_j|)) ]

其中 (b(\cdot)) 可以由一个小型 MLP 学习得到。

如果采用 Mamba，可以设计 (\Delta t)-aware Mamba，在状态更新前引入时间衰减：

[ \tilde{\mathbf{h}}_{i-1}
\mathbf{h}_{i-1} \odot \exp(-\gamma \Delta t_i) ]

[ \mathbf{h}_i
\text{MambaUpdate}(\mathbf{z}_i,\tilde{\mathbf{h}}_{i-1}) ]

其中 (\gamma) 是可学习参数。标准 $x$ 仍可渲染。普通括号 (text) 保持文本。`;

    const { container } = render(<RichMarkdown content={content} />);

    await waitFor(() => {
      expect(container).toHaveTextContent('如果采用 Transformer');
    });

    await waitFor(() => {
      expect(container.querySelectorAll('.rich-math-block')).toHaveLength(4);
      expect(container.querySelectorAll('.rich-math-rendered .katex-display')).toHaveLength(4);
      expect(container.querySelectorAll('.rich-math-inline .katex')).toHaveLength(4);
    });
    expect(container).toHaveTextContent('-aware Mamba');
    expect(container).toHaveTextContent('普通括号 (text) 保持文本。');
  });

  it('clears table copy feedback timers when unmounted', async () => {
    const clearTimeoutSpy = vi.spyOn(window, 'clearTimeout');
    const { unmount } = render(<RichMarkdown content={`| Name | Score |\n| --- | --- |\n| Alpha | 2 |`} />);

    expect(await screen.findByText('Table')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Copy CSV' }));
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument();

    unmount();

    expect(clearTimeoutSpy).toHaveBeenCalled();
  });
});
