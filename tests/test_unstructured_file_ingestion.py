import io

from docx import Document

from chatbi.files import SentenceAwareChunker, TextExtractor


def _build_minimal_pdf_bytes(text: str) -> bytes:
    """Hand-build a minimal single-page PDF so tests need no PDF-writer dependency."""

    content = f"BT /F1 12 Tf 72 712 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
        b"/MediaBox [0 0 612 792] /Contents 5 0 R >>\nendobj\n",
        b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
        b"5 0 obj\n<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream\nendobj\n",
    ]

    buffer = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for obj in objects:
        offsets.append(len(buffer))
        buffer += obj
    xref_offset = len(buffer)
    buffer += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        buffer += ("%010d 00000 n \n" % offset).encode("latin-1")
    buffer += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (
        len(objects) + 1,
        xref_offset,
    )
    return bytes(buffer)


def _build_docx_bytes(paragraphs: list[str]) -> bytes:
    document = Document()
    for paragraph_text in paragraphs:
        document.add_paragraph(paragraph_text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_text_extractor_extracts_non_empty_text_from_pdf() -> None:
    pdf_bytes = _build_minimal_pdf_bytes("Quarterly revenue grew twelve percent.")

    text = TextExtractor().extract_pdf(pdf_bytes)

    assert text.strip() != ""
    assert "Quarterly revenue grew twelve percent." in text


def test_text_extractor_extracts_paragraph_text_from_docx_fixture() -> None:
    docx_bytes = _build_docx_bytes(["First paragraph about revenue.", "Second paragraph about costs."])

    text = TextExtractor().extract_docx(docx_bytes)

    assert "First paragraph about revenue." in text
    assert "Second paragraph about costs." in text


def _sample_paragraph(sentence_count: int, words_per_sentence: int = 8) -> str:
    sentences: list[str] = []
    for sentence_index in range(sentence_count):
        words = " ".join(f"word{sentence_index}_{word_index}" for word_index in range(words_per_sentence))
        sentences.append(f"{words}.")
    return " ".join(sentences)


def test_chunker_produces_chunks_no_longer_than_500_tokens() -> None:
    text = _sample_paragraph(sentence_count=80, words_per_sentence=8)

    chunks = SentenceAwareChunker().chunk(text, max_tokens=400, overlap=50)

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.text.split()) <= 500


def test_chunker_never_splits_a_sentence_mid_word() -> None:
    text = _sample_paragraph(sentence_count=60, words_per_sentence=8)
    all_words = set(text.split())

    chunks = SentenceAwareChunker().chunk(text, max_tokens=400, overlap=50)

    for chunk in chunks:
        for token in chunk.text.split():
            assert token in all_words


def test_chunker_applies_configured_overlap_between_adjacent_chunks() -> None:
    text = _sample_paragraph(sentence_count=80, words_per_sentence=8)

    chunks = SentenceAwareChunker().chunk(text, max_tokens=400, overlap=50)

    assert len(chunks) > 1
    previous_tail = chunks[0].text.split()[-50:]
    next_head = chunks[1].text.split()[:50]
    assert previous_tail == next_head


def test_chunker_tags_every_chunk_with_org_user_and_file_scope() -> None:
    text = _sample_paragraph(sentence_count=10)

    chunks = SentenceAwareChunker().chunk(
        text,
        max_tokens=400,
        overlap=50,
        org_id="org_1",
        user_id="user_1",
        file_id="ufile_abc123",
    )

    assert chunks
    for chunk in chunks:
        assert chunk.org_id == "org_1"
        assert chunk.user_id == "user_1"
        assert chunk.file_id == "ufile_abc123"
