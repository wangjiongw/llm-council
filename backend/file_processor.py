"""File processing utilities for uploaded context files."""

import base64
import io
import os
import re
from pathlib import Path
from typing import List, Dict, Any, Union, Tuple

try:
    from pypdf import PdfReader
    PDF_TEXT_SUPPORT = True
except ImportError:
    PDF_TEXT_SUPPORT = False


class FileProcessor:
    """Handle file processing for text, image, and PDF uploads."""

    # File size limits (in bytes)
    MAX_TEXT_SIZE = 2 * 1024 * 1024  # 2MB
    MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20MB
    MAX_PDF_SIZE = 50 * 1024 * 1024  # 50MB
    MAX_TEXT_CHARS = 120_000
    DEFAULT_CONTEXT_TEXT_CHARS = 16_000
    DEFAULT_CHUNK_CHARS = 2_000
    DEFAULT_MAX_SELECTED_CHUNKS = 6

    # Supported MIME types
    SUPPORTED_TEXT_TYPES = [
        'text/plain',
        'text/markdown',
        'text/x-markdown',
        'application/markdown',
        'application/x-markdown',
        'application/json',
        'text/csv',
        'text/tab-separated-values',
        'application/xml',
        'text/xml',
        'application/x-yaml',
        'text/yaml',
    ]

    SUPPORTED_TEXT_EXTENSIONS = {
        '.txt',
        '.md',
        '.markdown',
        '.json',
        '.csv',
        '.tsv',
        '.xml',
        '.yaml',
        '.yml',
        '.log',
    }

    SUPPORTED_IMAGE_TYPES = [
        'image/jpeg',
        'image/png',
        'image/gif',
        'image/webp'
    ]

    SUPPORTED_PDF_TYPES = [
        'application/pdf'
    ]

    @staticmethod
    def validate_file(
        filename: str,
        content: bytes,
        file_type: str
    ) -> Tuple[bool, str]:
        """
        Validate file before processing.

        Args:
            filename: Original filename
            content: Raw file bytes
            file_type: MIME type

        Returns:
            Tuple of (is_valid, error_message)
        """
        file_type = file_type or ''
        suffix = Path(filename or '').suffix.lower()

        # Check file type
        if file_type in FileProcessor.SUPPORTED_TEXT_TYPES or suffix in FileProcessor.SUPPORTED_TEXT_EXTENSIONS:
            max_size = FileProcessor.MAX_TEXT_SIZE
            type_name = "text file"
        elif file_type in FileProcessor.SUPPORTED_IMAGE_TYPES:
            max_size = FileProcessor.MAX_IMAGE_SIZE
            type_name = "image"
        elif file_type in FileProcessor.SUPPORTED_PDF_TYPES:
            max_size = FileProcessor.MAX_PDF_SIZE
            type_name = "PDF"
        else:
            return False, f"Unsupported file type: {file_type}"

        # Check file size
        if len(content) > max_size:
            size_mb = len(content) / (1024 * 1024)
            max_mb = max_size / (1024 * 1024)
            return False, f"{type_name.capitalize()} too large: {size_mb:.1f}MB (max {max_mb:.0f}MB)"

        return True, None

    @staticmethod
    def decode_text(content: bytes, filename: str) -> str:
        """
        Decode a text-like upload to Unicode.

        Args:
            content: Raw file bytes
            filename: Original filename

        Returns:
            Decoded text, truncated to a context-safe length.
        """
        last_error = None
        for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
            try:
                text = content.decode(encoding)
                break
            except UnicodeDecodeError as exc:
                last_error = exc
        else:
            raise ValueError(f"Could not decode text file {filename}: {last_error}")

        if len(text) > FileProcessor.MAX_TEXT_CHARS:
            text = (
                text[:FileProcessor.MAX_TEXT_CHARS]
                + f"\n\n[Truncated {filename} to {FileProcessor.MAX_TEXT_CHARS} characters]"
            )

        return text

    @staticmethod
    def _context_limits() -> Tuple[int, int, int]:
        max_context_chars = int(os.getenv(
            "FILE_CONTEXT_MAX_CHARS",
            str(FileProcessor.DEFAULT_CONTEXT_TEXT_CHARS),
        ))
        chunk_chars = int(os.getenv(
            "FILE_CONTEXT_CHUNK_CHARS",
            str(FileProcessor.DEFAULT_CHUNK_CHARS),
        ))
        max_chunks = int(os.getenv(
            "FILE_CONTEXT_MAX_CHUNKS",
            str(FileProcessor.DEFAULT_MAX_SELECTED_CHUNKS),
        ))
        return max(1000, max_context_chars), max(500, chunk_chars), max(1, max_chunks)

    @staticmethod
    def _query_terms(query: str) -> List[str]:
        terms = []
        seen = set()
        for term in re.findall(r"[\w\u4e00-\u9fff]{2,}", query.lower()):
            if term not in seen:
                seen.add(term)
                terms.append(term)
        return terms

    @staticmethod
    def _chunk_text(text: str, chunk_chars: int) -> List[Dict[str, Any]]:
        chunks = []
        current = []
        current_len = 0

        blocks = re.split(r"\n{2,}", text)
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            while len(block) > chunk_chars:
                part = block[:chunk_chars].rstrip()
                chunks.append({"index": len(chunks) + 1, "text": part})
                block = block[chunk_chars:].lstrip()
            block_len = len(block) + 2
            if current and current_len + block_len > chunk_chars:
                chunks.append({"index": len(chunks) + 1, "text": "\n\n".join(current).strip()})
                current = []
                current_len = 0
            current.append(block)
            current_len += block_len

        if current:
            chunks.append({"index": len(chunks) + 1, "text": "\n\n".join(current).strip()})

        return chunks or [{"index": 1, "text": text[:chunk_chars]}]

    @staticmethod
    def _score_chunk(text: str, terms: List[str]) -> int:
        if not terms:
            return 0
        lowered = text.lower()
        score = 0
        for term in terms:
            hits = lowered.count(term)
            if hits:
                score += 4 + hits
        return score

    @staticmethod
    def select_relevant_text(filename: str, text: str, query: str = "") -> Dict[str, Any]:
        max_context_chars, chunk_chars, max_chunks = FileProcessor._context_limits()
        if len(text) <= max_context_chars:
            return {
                "text": text,
                "selected_chunks": 1 if text else 0,
                "total_chunks": 1 if text else 0,
                "truncated": False,
            }

        chunks = FileProcessor._chunk_text(text, chunk_chars)
        terms = FileProcessor._query_terms(query)
        scored = [
            {
                "index": chunk["index"],
                "text": chunk["text"],
                "score": FileProcessor._score_chunk(chunk["text"], terms),
            }
            for chunk in chunks
        ]
        if terms and any(item["score"] > 0 for item in scored):
            selected = sorted(scored, key=lambda item: (-item["score"], item["index"]))[:max_chunks]
            selected = sorted(selected, key=lambda item: item["index"])
        else:
            selected = scored[:max_chunks]

        selected_text = "\n\n".join(
            f"[Chunk {item['index']} of {len(chunks)}]\n{item['text']}"
            for item in selected
        )
        selected_text += (
            f"\n\n[Selected {len(selected)} of {len(chunks)} chunks from {filename} "
            "for the current query and context budget]"
        )
        return {
            "text": selected_text,
            "selected_chunks": len(selected),
            "total_chunks": len(chunks),
            "truncated": True,
        }

    @staticmethod
    def text_content_item(filename: str, text: str, query: str = "") -> Dict[str, Any]:
        """
        Wrap extracted file text as a normal chat-completions text item.

        This keeps uploads compatible with OpenAI-compatible servers that only
        support ordinary text chat messages.
        """
        selected = FileProcessor.select_relevant_text(filename, text, query)
        item = {
            "type": "text",
            "text": f"\n\n[Attached file: {filename}]\n{selected['text']}\n[/Attached file: {filename}]"
        }
        if selected["truncated"]:
            item["file_context"] = {
                "filename": filename,
                "strategy": "query_relevant_chunks_v1",
                "selected_chunks": selected["selected_chunks"],
                "total_chunks": selected["total_chunks"],
            }
        return item

    @staticmethod
    def encode_image_to_base64(content: bytes, file_type: str) -> str:
        """
        Encode image content to base64 data URI.

        Args:
            content: Raw image bytes
            file_type: MIME type (e.g., 'image/png')

        Returns:
            Base64-encoded data URI string
        """
        base64_str = base64.b64encode(content).decode('utf-8')
        return f"data:{file_type};base64,{base64_str}"

    @staticmethod
    def extract_pdf_text(
        content: bytes,
        filename: str,
        max_pages: int = 50,
        query: str = "",
    ) -> Dict[str, Any]:
        """
        Extract selectable text from a PDF and wrap it as a text content item.
        """
        if not PDF_TEXT_SUPPORT:
            raise ValueError("PDF text extraction requires pypdf. Install dependency pypdf or upload txt/md.")

        reader = PdfReader(io.BytesIO(content))
        page_texts = []

        for index, page in enumerate(reader.pages[:max_pages], 1):
            extracted = page.extract_text() or ""
            if extracted.strip():
                page_texts.append(f"[Page {index}]\n{extracted.strip()}")

        if not page_texts:
            raise ValueError(f"No selectable text found in PDF {filename}")

        text = "\n\n".join(page_texts)
        if len(reader.pages) > max_pages:
            text += f"\n\n[Truncated PDF {filename} to first {max_pages} pages]"

        if len(text) > FileProcessor.MAX_TEXT_CHARS:
            text = (
                text[:FileProcessor.MAX_TEXT_CHARS]
                + f"\n\n[Truncated {filename} to {FileProcessor.MAX_TEXT_CHARS} characters]"
            )

        return FileProcessor.text_content_item(filename, text, query=query)

    @staticmethod
    def process_file(
        filename: str,
        content: bytes,
        file_type: str,
        query: str = "",
    ) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Process a single file and return multimodal content.

        Args:
            filename: Original filename
            content: Raw file bytes
            file_type: MIME type

        Returns:
            - Text files: Single content dict with extracted text
            - Image: Single content dict with image_url
            - PDF: Single text item when selectable text is available
        """
        # Validate file first
        is_valid, error = FileProcessor.validate_file(filename, content, file_type)
        if not is_valid:
            raise ValueError(error)

        # Process based on file type
        file_type = file_type or ''
        suffix = Path(filename or '').suffix.lower()

        if file_type in FileProcessor.SUPPORTED_TEXT_TYPES or suffix in FileProcessor.SUPPORTED_TEXT_EXTENSIONS:
            text = FileProcessor.decode_text(content, filename)
            return FileProcessor.text_content_item(filename, text, query=query)

        elif file_type in FileProcessor.SUPPORTED_IMAGE_TYPES:
            # Image: encode as base64
            base64_uri = FileProcessor.encode_image_to_base64(content, file_type)
            return {
                "type": "image_url",
                "image_url": {
                    "url": base64_uri
                }
            }

        elif file_type in FileProcessor.SUPPORTED_PDF_TYPES:
            # Prefer text extraction for OpenAI-compatible server portability.
            return FileProcessor.extract_pdf_text(content, filename, query=query)

        else:
            raise ValueError(f"Unsupported file type: {file_type}")


async def process_uploaded_files(files: List[Dict[str, Any]], query: str = "") -> List[Dict[str, Any]]:
    """
    Process multiple uploaded files.

    Args:
        files: List of dicts with 'filename', 'content', 'file_type'

    Returns:
        List of content items for OpenRouter API.
        Note: PDFs return multiple items (one per page), images return one item.
    """
    results = []

    for file_data in files:
        processed = FileProcessor.process_file(
            file_data['filename'],
            file_data['content'],
            file_data['file_type'],
            query=query,
        )

        # Image: single dict
        if isinstance(processed, dict):
            results.append(processed)
        # PDF: list of dicts (one per page), expand
        elif isinstance(processed, list):
            results.extend(processed)

    return results
