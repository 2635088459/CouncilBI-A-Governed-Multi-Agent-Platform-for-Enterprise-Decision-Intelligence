"""KnowledgePromotionService: the FR-FV10-033/034 admin promotion workflow.

Promoting copies a user file's already-embedded chunks (computed once during
ingestion by ``worker.py``) into the shared knowledge base ``VectorStore``
under an open access policy — no more user/file scoping — and records
``promoted_to_doc_id`` on the source file. Demoting disables that document so
RAG stops surfacing it and clears ``promoted_to_doc_id``. Neither step
re-embeds anything; the vectors are copied, not recomputed.

The ``VectorStore`` above is a separate abstraction from the
``InMemoryKnowledgeStore`` that ``RagAgentRunner`` actually queries during a
live chat request (that store is loaded once from ``knowledge.documents`` /
``knowledge.doc_chunks`` at process startup — see
``http._load_knowledge_store_from_db``). Writing only to ``VectorStore``
promotes a file "on paper" but leaves it invisible to real RAG answers. To
close that gap, ``promote_file``/``demote_document`` optionally also write
straight into the live in-process ``InMemoryKnowledgeStore`` (so a promoted
file is searchable immediately, no restart needed) and into the same
``knowledge.*`` Postgres tables (so it survives a restart).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from chatbi.core.architecture_contracts import UserRoleV2
from chatbi.embedding_vector_rag import DocumentRecord, VectorChunk, VectorStore
from chatbi.files.contracts import UserUploadedFile
from chatbi.files.repository import FileRepository
from chatbi.files.worker import FileVectorSource
from chatbi.knowledge import ChunkEmbedding, DocumentChunk, InMemoryKnowledgeStore, KnowledgeDocument, text_embedding


class NotAuthorizedToPromoteError(Exception):
    """Raised when a non-admin role attempts to promote or demote a document."""


class FileNotPromotableError(Exception):
    """Raised when a file cannot be promoted (unknown, not unstructured, or not ready)."""


class DocumentNotPromotedError(Exception):
    """Raised when demote() targets a doc_id that isn't a live promotion."""


def new_promoted_document_id() -> str:
    return f"doc_{uuid4().hex}"


class KnowledgePromotionService:
    """Promote a user's ready unstructured file into the org knowledge base."""

    def __init__(
        self,
        *,
        repository: FileRepository,
        vector_store: VectorStore,
        vector_source: FileVectorSource,
        live_knowledge_store: InMemoryKnowledgeStore | None = None,
        knowledge_connection: Any | None = None,
    ) -> None:
        self._repository = repository
        self._vector_store = vector_store
        self._vector_source = vector_source
        self._live_knowledge_store = live_knowledge_store
        self._knowledge_connection = knowledge_connection

    def promote_file(self, file_id: str, *, role: UserRoleV2, org_id: str) -> UserUploadedFile:
        _require_admin(role)

        file = self._repository.get(file_id)
        if (
            file is None
            or file.org_id != org_id
            or file.file_type != "unstructured"
            or file.status != "ready"
        ):
            raise FileNotPromotableError(file_id)

        chunks_with_vectors = self._vector_source.chunks_with_vectors_for_file(file_id)
        if not chunks_with_vectors:
            # The vector source is in-process and does not survive a
            # restart (see module docstring). Promoting with nothing to
            # copy would otherwise silently create a document row with zero
            # chunks — permanently invisible to RAG retrieval but with no
            # error to explain why. Fail loudly instead: the caller needs
            # to re-upload the file so it gets re-chunked in this process.
            raise FileNotPromotableError(file_id)

        document_id = new_promoted_document_id()
        self._vector_store.upsert_document(
            DocumentRecord(
                document_id=document_id,
                org_id=file.org_id,
                title=file.original_name,
                source_type="user_promoted",
                owner_user_id=file.user_id,
                version="1",
                access_policy={"permission_tags": ()},
            )
        )

        if chunks_with_vectors:
            vector_chunks = tuple(
                VectorChunk(
                    chunk_id=f"{document_id}_{chunk.chunk_index}",
                    document_id=document_id,
                    org_id=file.org_id,
                    text=chunk.text,
                    token_count=len(chunk.text.split()),
                    vector_ref=f"{document_id}_{chunk.chunk_index}",
                )
                for chunk, _ in chunks_with_vectors
            )
            vectors = tuple(vector for _, vector in chunks_with_vectors)
            self._vector_store.upsert_chunks(vector_chunks, vectors)

        chunk_texts = tuple(chunk.text for chunk, _ in chunks_with_vectors)
        self._index_into_live_rag(document_id, file.original_name, chunk_texts, file.user_id)

        promoted = replace(file, promoted_to_doc_id=document_id)
        self._repository.save(promoted)
        return promoted

    def demote_document(self, doc_id: str, *, role: UserRoleV2, org_id: str) -> UserUploadedFile:
        _require_admin(role)

        # source_file (backed by FileRepository, i.e. Postgres) is the
        # durable source of truth for "is this doc still promoted" — unlike
        # self._vector_store, which is an in-process store that does not
        # survive a restart. Checking that ephemeral store first would wrongly
        # reject a demote for a document promoted in a previous process
        # lifetime, even though it is still live in the real RAG-facing store.
        source_file = self._find_source_file(doc_id, org_id)
        if source_file is None:
            raise DocumentNotPromotedError(doc_id)

        document = self._vector_store.get_document(doc_id)
        if document is not None and document.org_id == org_id:
            self._vector_store.upsert_document(replace(document, status="disabled"))

        self.remove_from_live_rag(doc_id)
        demoted = replace(source_file, promoted_to_doc_id=None)
        self._repository.save(demoted)
        return demoted

    def _find_source_file(self, doc_id: str, org_id: str) -> UserUploadedFile | None:
        for file in self._repository.list_active():
            if file.promoted_to_doc_id == doc_id and file.org_id == org_id:
                return file
        return None

    def _index_into_live_rag(
        self, document_id: str, title: str, chunk_texts: tuple[str, ...], owner_user_id: str
    ) -> None:
        """Make a promoted document immediately searchable by RagAgentRunner.

        Writes the same shape ``http._load_knowledge_store_from_db`` reads at
        startup, so a freshly promoted file behaves exactly like a seeded
        document for the rest of this process's life, and (if a Postgres
        connection is available) survives a restart too.

        FR-FV10-040: ``owner_user_id`` is stamped from the uploading user
        (``file.user_id``), not the admin performing the promotion, so the
        promoted document stays private to its uploader per Spec FV10.1
        until a share grant or admin-widened policy says otherwise.
        """

        publish_time = datetime.now(timezone.utc)

        if self._live_knowledge_store is not None:
            self._live_knowledge_store.save_document(
                KnowledgeDocument(
                    source_id=document_id,
                    title=title,
                    doc_type="user_promoted",
                    publish_time=publish_time,
                    owner_user_id=owner_user_id,
                )
            )
            for index, text in enumerate(chunk_texts, start=1):
                chunk_id = f"{document_id}_chunk_{index}"
                self._live_knowledge_store.save_chunk(
                    DocumentChunk(
                        chunk_id=chunk_id,
                        source_id=document_id,
                        chunk_index=index,
                        chunk_text=text,
                    )
                )
                self._live_knowledge_store.save_embedding(
                    ChunkEmbedding(
                        embedding_id=f"{chunk_id}_emb",
                        chunk_id=chunk_id,
                        embedding_vector=text_embedding(text),
                    )
                )

        if self._knowledge_connection is not None:
            with self._knowledge_connection.cursor() as cur:
                cur.execute(
                    "INSERT INTO knowledge.documents (source_id, title, doc_type, publish_time, owner_user_id) "
                    "VALUES (%s, %s, %s, %s, %s) "
                    "ON CONFLICT (source_id) DO UPDATE SET "
                    "title = EXCLUDED.title, doc_type = EXCLUDED.doc_type, "
                    "publish_time = EXCLUDED.publish_time, owner_user_id = EXCLUDED.owner_user_id",
                    (document_id, title, "user_promoted", publish_time, owner_user_id),
                )
                for index, text in enumerate(chunk_texts, start=1):
                    chunk_id = f"{document_id}_chunk_{index}"
                    cur.execute(
                        "INSERT INTO knowledge.doc_chunks (chunk_id, source_id, chunk_index, chunk_text) "
                        "VALUES (%s, %s, %s, %s) "
                        "ON CONFLICT (chunk_id) DO UPDATE SET chunk_text = EXCLUDED.chunk_text",
                        (chunk_id, document_id, index, text),
                    )
                    cur.execute(
                        "INSERT INTO knowledge.doc_embeddings "
                        "(embedding_id, chunk_id, embedding_model, embedding_dimensions, vector_ref) "
                        "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (embedding_id) DO NOTHING",
                        (f"{chunk_id}_emb", chunk_id, "local-deterministic-v1", 16, f"pgvector://knowledge.doc_chunks/{chunk_id}"),
                    )
            self._knowledge_connection.commit()

    def remove_from_live_rag(self, document_id: str) -> None:
        """Remove a promoted document from the live store and Postgres.

        Public so ``RetentionWorker`` can reuse this exact removal logic
        when archiving a promoted file (Spec FV10.3 FR-FV10-048), without
        going through ``demote_document()``'s admin-role authorization,
        which does not apply to an automated background sweep.
        """

        if self._live_knowledge_store is not None:
            self._live_knowledge_store.remove_document(document_id)

        if self._knowledge_connection is not None:
            with self._knowledge_connection.cursor() as cur:
                cur.execute(
                    "DELETE FROM knowledge.doc_embeddings WHERE chunk_id IN "
                    "(SELECT chunk_id FROM knowledge.doc_chunks WHERE source_id = %s)",
                    (document_id,),
                )
                cur.execute("DELETE FROM knowledge.doc_chunks WHERE source_id = %s", (document_id,))
                cur.execute("DELETE FROM knowledge.documents WHERE source_id = %s", (document_id,))
            self._knowledge_connection.commit()


def _require_admin(role: UserRoleV2) -> None:
    if role != "admin":
        raise NotAuthorizedToPromoteError(role)
