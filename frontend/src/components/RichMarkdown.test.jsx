import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
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
});
