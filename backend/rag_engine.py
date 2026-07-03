"""
GEM RAG Engine v4.0 (Native Python & Pure OpenSource)
- Direct FAISS integration via python-faiss
- Direct SentenceTransformers embeddings generation (no LangChain overhead)
- Custom Recursive Character Text Splitter
- SHA256 content deduplication
- Metadata-aware document indexing (vendor_id, tender_id, doc_type, doc_id)
- Filtered RAG queries with metadata constraints
- Index statistics reporting
- Auto-save & auto-load from ./rag_index/
"""
import os
import io
import json
import hashlib
from typing import Dict, Any, Optional, Set, List
import numpy as np

# Native replacements for LangChain components
class Document:
    def __init__(self, page_content: str, metadata: dict):
        self.page_content = page_content
        self.metadata = metadata

class NativeTextSplitter:
    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50, separators: List[str] = None):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or ["\n\n", "\n", ". ", " ", ""]

    def split_text(self, text: str) -> List[str]:
        return self._split(text, self.separators)

    def _split(self, text: str, separators: List[str]) -> List[str]:
        if len(text) <= self.chunk_size:
            return [text]
            
        if not separators:
            return [text[i:i+self.chunk_size] for i in range(0, len(text), self.chunk_size - self.chunk_overlap)]
            
        separator = separators[0]
        next_seps = separators[1:]
        
        if separator == "":
            splits = list(text)
        else:
            splits = text.split(separator)
            
        chunks = []
        current_chunk = []
        current_len = 0
        
        for split in splits:
            split_text = split + (separator if separator != "" else "")
            split_len = len(split_text)
            
            if split_len > self.chunk_size:
                if current_chunk:
                    chunks.append("".join(current_chunk))
                    current_chunk = []
                    current_len = 0
                sub_chunks = self._split(split, next_seps)
                chunks.extend(sub_chunks)
            elif current_len + split_len > self.chunk_size:
                chunks.append("".join(current_chunk))
                overlap_text = "".join(current_chunk)
                overlap_start = max(0, len(overlap_text) - self.chunk_overlap)
                overlap_part = overlap_text[overlap_start:]
                
                current_chunk = [overlap_part, split_text]
                current_len = len(overlap_part) + split_len
            else:
                current_chunk.append(split_text)
                current_len += split_len
                
        if current_chunk:
            chunks.append("".join(current_chunk))
            
        return [c.strip() for c in chunks if c.strip()]

class NativeEmbeddingsModel:
    def __init__(self, model_name: str = "all-mpnet-base-v2"):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_name)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        embeddings = self.model.encode(texts, convert_to_numpy=True)
        return embeddings.tolist()

    def embed_query(self, text: str) -> List[float]:
        embedding = self.model.encode(text, convert_to_numpy=True)
        return embedding.tolist()

class DummyDocstore:
    def __init__(self, d):
        self._dict = dict(d)

class NativeFaissStore:
    def __init__(self, index, docstore, index_to_docstore_id, vectors=None):
        self.index = index
        self.docstore = docstore
        self.index_to_docstore_id = index_to_docstore_id
        self.vectors = vectors if vectors is not None else []

    @classmethod
    def from_documents(cls, documents: List[Document], embeddings_model):
        import faiss
        index = faiss.IndexFlatL2(768)
        store = cls(index, {}, {})
        store.add_documents(documents, embeddings_model)
        return store

    def save_local(self, folder_path: str):
        import faiss
        import pickle
        os.makedirs(folder_path, exist_ok=True)
        faiss.write_index(self.index, os.path.join(folder_path, "index.faiss"))
        with open(os.path.join(folder_path, "index.pkl"), "wb") as f:
            pickle.dump((DummyDocstore(dict(self.docstore)), dict(self.index_to_docstore_id), list(self.vectors)), f)

    @classmethod
    def load_local(cls, folder_path: str, embeddings_model, allow_dangerous_deserialization=True):
        import faiss
        import pickle
        index = faiss.read_index(os.path.join(folder_path, "index.faiss"))
        with open(os.path.join(folder_path, "index.pkl"), "rb") as f:
            data = pickle.load(f)
            
        docstore_obj = data[0]
        index_to_docstore_id = data[1]
        vectors = data[2] if len(data) > 2 else None
        
        if vectors is None:
            vectors = []
            for idx in range(index.ntotal):
                try:
                    vectors.append(index.reconstruct(idx).tolist())
                except Exception:
                    vectors.append([0.0] * index.d)
                    
        if hasattr(docstore_obj, "_dict"):
            docstore = docstore_obj._dict
        else:
            docstore = docstore_obj
        return cls(index, docstore, index_to_docstore_id, vectors)

    def add_documents(self, documents: List[Document], embeddings_model=None):
        emb_model = embeddings_model or globals().get("embeddings_model")
            
        texts = [doc.page_content for doc in documents]
        embeddings = emb_model.embed_documents(texts)
        embeddings_np = np.array(embeddings, dtype=np.float32)
        
        import uuid
        start_idx = self.index.ntotal
        self.index.add(embeddings_np)
        
        for i, doc in enumerate(documents):
            doc_id = str(uuid.uuid4())
            idx = start_idx + i
            self.docstore[doc_id] = doc
            self.index_to_docstore_id[idx] = doc_id
            self.vectors.append(embeddings[i])

    def similarity_search_with_score(self, query: str, k: int = 4) -> List[tuple]:
        global embeddings_model
        query_vector = embeddings_model.embed_query(query)
        query_vector_np = np.array([query_vector], dtype=np.float32)
        
        distances, indices = self.index.search(query_vector_np, k)
        
        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx == -1 or idx not in self.index_to_docstore_id:
                continue
            doc_id = self.index_to_docstore_id[idx]
            doc = self.docstore.get(doc_id)
            if doc:
                results.append((doc, float(dist)))
        return results

    def delete(self, ids_to_delete: List[str]):
        ids_set = set(ids_to_delete)
        
        import faiss
        new_index = faiss.IndexFlatL2(self.index.d)
        new_docstore = {}
        new_index_to_docstore_id = {}
        new_vectors = []
        
        for idx in range(self.index.ntotal):
            doc_id = self.index_to_docstore_id.get(idx)
            if doc_id and doc_id not in ids_set:
                new_docstore[doc_id] = self.docstore[doc_id]
                new_vectors.append(self.vectors[idx])
        
        if new_vectors:
            new_vectors_np = np.array(new_vectors, dtype=np.float32)
            new_index.add(new_vectors_np)
            for i, doc_id in enumerate(new_docstore.keys()):
                new_index_to_docstore_id[i] = doc_id
        
        self.index = new_index
        self.docstore = new_docstore
        self.index_to_docstore_id = new_index_to_docstore_id
        self.vectors = new_vectors

HAS_RAG = True

# ─────────────────────────────────────────────────────────────────
#  GLOBALS
# ─────────────────────────────────────────────────────────────────
import threading
_rag_lock = threading.RLock()

vector_store = None
embeddings_model = None
_doc_hashes: Set[str] = set()
_chunk_count: int = 0
DEFAULT_INDEX_DIR = os.path.join(".", "rag_index")
RAG_VECTOR_DB = os.environ.get("RAG_VECTOR_DB", "faiss").lower().strip()
QDRANT_URL = os.environ.get("QDRANT_URL", "").strip()
qdrant_client = None
QDRANT_COLLECTION = "gem_tender_docs"

# ─────────────────────────────────────────────────────────────────
#  INITIALIZATION
# ─────────────────────────────────────────────────────────────────
def _init_qdrant() -> bool:
    global qdrant_client
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.http.models import Distance, VectorParams
        
        if QDRANT_URL:
            if QDRANT_URL.lower().strip() == ":memory:":
                qdrant_client = QdrantClient(location=":memory:")
            else:
                qdrant_client = QdrantClient(url=QDRANT_URL)
        else:
            qdrant_db_path = os.path.join(".", "qdrant_db")
            os.makedirs(qdrant_db_path, exist_ok=True)
            qdrant_client = QdrantClient(path=qdrant_db_path)
            
        collections = qdrant_client.get_collections().collections
        exists = any(c.name == QDRANT_COLLECTION for c in collections)
        if not exists:
            qdrant_client.create_collection(
                collection_name=QDRANT_COLLECTION,
                vectors_config=VectorParams(size=768, distance=Distance.COSINE),
            )
        print(f"[rag_engine] Qdrant client initialized (Collection: {QDRANT_COLLECTION})")
        return True
    except Exception as e:
        print(f"[rag_engine] Qdrant init failed: {e}")
        qdrant_client = None
        return False

def load_metadata_only(path: Optional[str] = None) -> bool:
    global _doc_hashes, _chunk_count
    load_dir = path or DEFAULT_INDEX_DIR
    meta_path = os.path.join(load_dir, "_rag_meta.json")
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            _doc_hashes = set(meta.get("doc_hashes", []))
            _chunk_count = meta.get("chunk_count", 0)
            return True
        except Exception:
            pass
    return False

def save_metadata_only(path: Optional[str] = None) -> bool:
    global _doc_hashes, _chunk_count
    save_dir = path or DEFAULT_INDEX_DIR
    try:
        os.makedirs(save_dir, exist_ok=True)
        meta = {
            "doc_hashes": list(_doc_hashes),
            "chunk_count": _chunk_count,
        }
        meta_path = os.path.join(save_dir, "_rag_meta.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f)
        return True
    except Exception:
        return False

def init_rag():
    """Initialize embeddings model and attempt to load persisted index (FAISS or Qdrant)."""
    global embeddings_model, vector_store, RAG_VECTOR_DB
    try:
        embeddings_model = NativeEmbeddingsModel(model_name="all-mpnet-base-v2")
        print("[rag_engine] SentenceTransformers initialized successfully.")
    except Exception as e:
        print(f"[rag_engine] Error initializing embeddings: {e}")
        return

    if RAG_VECTOR_DB == "qdrant":
        success = _init_qdrant()
        if success:
            load_metadata_only()
    else:
        try:
            loaded = load_index(DEFAULT_INDEX_DIR)
            if loaded:
                print(f"[rag_engine] Auto-loaded persisted FAISS index from {DEFAULT_INDEX_DIR}")
        except Exception as e:
            print(f"[rag_engine] No persisted FAISS index found or load failed: {e}")

# ─────────────────────────────────────────────────────────────────
#  INDEX PERSISTENCE
# ─────────────────────────────────────────────────────────────────
def save_index(path: Optional[str] = None) -> bool:
    """Save the index metadata and files."""
    global vector_store, _doc_hashes, _chunk_count, RAG_VECTOR_DB
    with _rag_lock:
        save_dir = path or DEFAULT_INDEX_DIR
        if RAG_VECTOR_DB == "qdrant":
            return save_metadata_only(save_dir)

        if vector_store is None:
            return False

        try:
            os.makedirs(save_dir, exist_ok=True)
            vector_store.save_local(save_dir)
            return save_metadata_only(save_dir)
        except Exception as e:
            print(f"[rag_engine] Error saving FAISS index to {save_dir}: {e}")
            return False

def load_index(path: Optional[str] = None) -> bool:
    """Load a persisted index from disk."""
    global vector_store, embeddings_model, _doc_hashes, _chunk_count, RAG_VECTOR_DB
    with _rag_lock:
        if embeddings_model is None:
            return False

        load_dir = path or DEFAULT_INDEX_DIR
        if RAG_VECTOR_DB == "qdrant":
            return load_metadata_only(load_dir)

        if not os.path.isdir(load_dir):
            return False

        index_file = os.path.join(load_dir, "index.faiss")
        if not os.path.isfile(index_file):
            return False

        try:
            vector_store = NativeFaissStore.load_local(
                load_dir, embeddings_model, allow_dangerous_deserialization=True
            )
            return load_metadata_only(load_dir)
        except Exception as e:
            print(f"[rag_engine] Error loading FAISS index from {load_dir}: {e}")
            return False

# ─────────────────────────────────────────────────────────────────
#  DOCUMENT INDEXING (with deduplication & metadata)
# ─────────────────────────────────────────────────────────────────
def add_document_to_index(text: str, metadata: Optional[dict] = None) -> bool:
    """
    Chunks the text and adds it to the FAISS vector database.
    """
    global vector_store, embeddings_model, _doc_hashes, _chunk_count
    with _rag_lock:
        if not embeddings_model:
            return False

        if not text or not text.strip():
            return False

        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if content_hash in _doc_hashes:
            return True
        
        if metadata is None:
            metadata = {}
        
        standard_fields = ["vendor_id", "tender_id", "doc_type", "doc_id", "filename"]
        chunk_metadata = {}
        for field in standard_fields:
            if field in metadata:
                chunk_metadata[field] = metadata[field]
        for key, value in metadata.items():
            if key not in chunk_metadata:
                try:
                    json.dumps(value)
                    chunk_metadata[key] = value
                except (TypeError, ValueError):
                    chunk_metadata[key] = str(value)

        chunk_metadata["content_hash"] = content_hash

        try:
            text_splitter = NativeTextSplitter(
                chunk_size=500,
                chunk_overlap=50,
                separators=["\n\n", "\n", ". ", " ", ""]
            )
            chunks = text_splitter.split_text(text)

            docs = []
            for i, chunk in enumerate(chunks):
                meta = dict(chunk_metadata)
                meta["chunk_index"] = i
                meta["total_chunks"] = len(chunks)
                docs.append(Document(page_content=chunk, metadata=meta))

            if RAG_VECTOR_DB == "qdrant":
                if qdrant_client is None:
                    _init_qdrant()
                if qdrant_client is not None:
                    texts = [doc.page_content for doc in docs]
                    embeddings = embeddings_model.embed_documents(texts)
                    
                    from qdrant_client.http.models import PointStruct
                    import uuid
                    
                    points = []
                    for idx, (text_chunk, emb, doc_obj) in enumerate(zip(texts, embeddings, docs)):
                        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{content_hash}_{idx}"))
                        points.append(
                            PointStruct(
                                id=point_id,
                                vector=emb,
                                payload={
                                    "page_content": text_chunk,
                                    "metadata": doc_obj.metadata
                                }
                            )
                        )
                    qdrant_client.upsert(collection_name=QDRANT_COLLECTION, points=points)
            else:
                if vector_store is None:
                    vector_store = NativeFaissStore.from_documents(docs, embeddings_model)
                else:
                    vector_store.add_documents(docs, embeddings_model)

            _doc_hashes.add(content_hash)
            _chunk_count += len(docs)

            save_index()
            return True
        except Exception as e:
            print(f"[rag_engine] Error adding to index: {e}")
            return False


def delete_document_from_index(filter_metadata: dict) -> bool:
    """
    Remove all chunks matching filter_metadata from the index.
    This prevents duplicate or outdated chunks when a document changes.
    """
    global vector_store, _doc_hashes, _chunk_count, RAG_VECTOR_DB, qdrant_client
    with _rag_lock:
        if not HAS_RAG:
            return False
            
        if not filter_metadata:
            return False
            
        try:
            if RAG_VECTOR_DB == "qdrant":
                if qdrant_client is None:
                    _init_qdrant()
                if qdrant_client is not None:
                    from qdrant_client.http import models as qmodels
                    must_clauses = []
                    for fkey, fval in filter_metadata.items():
                        val = fval
                        if isinstance(val, str) and val.isdigit():
                            val = int(val)
                        must_clauses.append(
                            qmodels.FieldCondition(
                                key=f"metadata.{fkey}",
                                match=qmodels.MatchValue(value=val)
                            )
                        )
                    q_filter = qmodels.Filter(must=must_clauses)
                    
                    # Fetch points to get their metadata content_hash to clean up _doc_hashes
                    scroll_res = qdrant_client.scroll(
                        collection_name=QDRANT_COLLECTION,
                        scroll_filter=q_filter,
                        limit=1000,
                        with_payload=True,
                        with_vectors=False
                    )
                    points = scroll_res[0] if isinstance(scroll_res, tuple) else scroll_res.points
                    deleted_count = len(points)
                    for point in points:
                        meta = point.payload.get("metadata", {}) if point.payload else {}
                        h = meta.get("content_hash")
                        if h:
                            _doc_hashes.discard(h)
                    
                    qdrant_client.delete(
                        collection_name=QDRANT_COLLECTION,
                        points_selector=qmodels.FilterSelector(filter=q_filter)
                    )
                    _chunk_count = max(0, _chunk_count - deleted_count)
            else:
                if vector_store is None:
                    return True
                    
                # Find all docstore IDs matching filter_metadata
                ids_to_delete = []
                hashes_to_remove = []
                
                doc_dict = vector_store.docstore._dict if hasattr(vector_store.docstore, "_dict") else (vector_store.docstore if isinstance(vector_store.docstore, dict) else getattr(vector_store.docstore, "_dict", {}))
                for chunk_id, doc_obj in list(doc_dict.items()):
                    match = True
                    for fkey, fval in filter_metadata.items():
                        doc_val = doc_obj.metadata.get(fkey)
                        if doc_val is None or str(doc_val) != str(fval):
                            match = False
                            break
                    if match:
                        ids_to_delete.append(chunk_id)
                        h = doc_obj.metadata.get("content_hash")
                        if h:
                            hashes_to_remove.append(h)
                            
                if ids_to_delete:
                    vector_store.delete(ids_to_delete)
                    for h in hashes_to_remove:
                        _doc_hashes.discard(h)
                    _chunk_count = max(0, _chunk_count - len(ids_to_delete))
                    
            # Auto-save index to disk after deletion
            save_index()
            return True
        except Exception as e:
            print(f"[rag_engine] Error deleting document from index: {e}")
            return False


# ─────────────────────────────────────────────────────────────────
#  QUERY (Original — backward compatible)
# ─────────────────────────────────────────────────────────────────
def query_rag(question: str) -> Dict[str, Any]:
    """Queries the local FAISS DB for context and asks Ollama to answer."""
    res = query_rag_filtered(question, k=3)
    if "filtered_count" in res:
        # Clean up key to keep backward compatibility
        res.pop("filtered_count", None)
    return res


# ─────────────────────────────────────────────────────────────────
#  FILTERED QUERY (NEW)
# ─────────────────────────────────────────────────────────────────
def retrieve_relevant_chunks(question: str, filter_metadata: Optional[Dict] = None,
                             k: int = 3, semantic_weight: Optional[float] = None) -> List[Any]:
    """
    Retrieve and re-rank relevant document chunks using hybrid search.
    """
    global vector_store, embeddings_model, RAG_VECTOR_DB, qdrant_client
    if not HAS_RAG or not embeddings_model:
        return []

    if semantic_weight is None:
        try:
            import llm_client
            semantic_weight = float(llm_client.config_data.get("rag_semantic_weight", 0.7))
        except Exception:
            semantic_weight = 0.7

    try:
        # Retrieve more results than needed to allow post-filtering & re-ranking
        fetch_k = max(25, k * 5)
        filtered_results = []
        
        if RAG_VECTOR_DB == "qdrant":
            if qdrant_client is None:
                _init_qdrant()
            if qdrant_client is not None:
                query_vector = embeddings_model.embed_query(question)
                
                from qdrant_client.http import models as qmodels
                q_filter = None
                if filter_metadata:
                    must_clauses = []
                    for fkey, fval in filter_metadata.items():
                        val = fval
                        if isinstance(val, str) and val.isdigit():
                            val = int(val)
                        must_clauses.append(
                            qmodels.FieldCondition(
                                key=f"metadata.{fkey}",
                                match=qmodels.MatchValue(value=val)
                            )
                        )
                    q_filter = qmodels.Filter(must=must_clauses)
                
                search_res = qdrant_client.query_points(
                    collection_name=QDRANT_COLLECTION,
                    query=query_vector,
                    query_filter=q_filter,
                    limit=fetch_k
                )
                for hit in search_res.points:
                    doc = Document(
                        page_content=hit.payload.get("page_content", ""),
                        metadata=hit.payload.get("metadata", {})
                    )
                    # For hybrid search, score is cosine similarity [0, 1]
                    # We store L2 distance equivalent (1 - similarity)
                    filtered_results.append((doc, float(1.0 - hit.score)))
        else:
            if vector_store is None:
                return []
            try:
                with _rag_lock:
                    results_with_scores = vector_store.similarity_search_with_score(question, k=fetch_k)
            except Exception as e:
                print(f"[rag_engine] FAISS search with score failed, using simple search: {e}")
                with _rag_lock:
                    results = vector_store.similarity_search(question, k=fetch_k)
                results_with_scores = [(doc, 1.0) for doc in results]

            if not results_with_scores:
                return []

            # Apply metadata filter
            if filter_metadata:
                for doc, score in results_with_scores:
                    match = True
                    for fkey, fval in filter_metadata.items():
                        doc_val = doc.metadata.get(fkey)
                        # Support both exact match and string comparison
                        if doc_val is None or str(doc_val) != str(fval):
                            match = False
                            break
                    if match:
                        filtered_results.append((doc, score))
            else:
                filtered_results = results_with_scores

        if not filtered_results:
            return []

        # ── Advanced Lexical-Semantic Hybrid Re-Ranking ──────────────────────────────
        import numpy as np
        from sklearn.feature_extraction.text import TfidfVectorizer

        docs = [item[0] for item in filtered_results]
        distances = [item[1] for item in filtered_results]
        doc_texts = [doc.page_content for doc in docs]

        # 1. Calculate Semantic Similarities
        # FAISS returns L2 distance: lower distance = higher similarity.
        # Normalize FAISS distances to a [0.1, 1.0] similarity range.
        d_arr = np.array(distances, dtype=float)
        max_dist = d_arr.max() if len(d_arr) > 0 else 1.0
        min_dist = d_arr.min() if len(d_arr) > 0 else 0.0
        dist_range = max_dist - min_dist
        
        if dist_range == 0:
            semantic_scores = np.ones(len(docs))
        else:
            semantic_scores = 1.0 - (d_arr - min_dist) / (dist_range + 1e-9)

        # 2. Refine Semantic Scores using Bi-Encoder Cosine Similarity
        if embeddings_model is not None:
            try:
                doc_embeddings = np.array(embeddings_model.embed_documents(doc_texts))
                query_embedding = np.array(embeddings_model.embed_query(question))
                
                dot_products = np.dot(doc_embeddings, query_embedding)
                doc_norms = np.linalg.norm(doc_embeddings, axis=1)
                query_norm = np.linalg.norm(query_embedding)
                cosine_similarities = dot_products / (doc_norms * query_norm + 1e-9)
                
                # Combine L2 distance similarity and Bi-Encoder Cosine Similarity
                semantic_scores = 0.3 * semantic_scores + 0.7 * cosine_similarities
            except Exception as embed_err:
                print(f"[rag_engine] Exact embedding re-ranking failed: {embed_err}")

        # 3. Calculate Lexical Similarities (TF-IDF)
        lexical_scores = np.zeros(len(docs))
        try:
            tfidf = TfidfVectorizer(stop_words='english', token_pattern=r'(?u)\b\w+\b')
            # Fit TF-IDF on retrieved chunks + the question itself
            corpus = doc_texts + [question]
            tfidf_matrix = tfidf.fit_transform(corpus)
            
            # Extract TF-IDF vectors
            query_vector = tfidf_matrix[-1]
            doc_vectors = tfidf_matrix[:-1]
            
            # Compute lexical similarity using dot product since TF-IDF vectors are L2 normalized
            lex_similarities = np.array((doc_vectors * query_vector.T).toarray()).flatten()
            lexical_scores = lex_similarities
        except Exception as tfidf_err:
            print(f"[rag_engine] TF-IDF lexical re-ranking failed: {tfidf_err}")

        # 4. Compute RRF (Reciprocal Rank Fusion) Score
        # Sort indices by semantic/lexical scores descending to calculate ranks
        semantic_ranks = np.argsort(np.argsort(semantic_scores)[::-1])
        lexical_ranks = np.argsort(np.argsort(lexical_scores)[::-1])
        
        # Calculate RRF scores: score = 1 / (60 + rank)
        rrf_scores = []
        for i in range(len(docs)):
            r_sem = semantic_ranks[i] + 1
            r_lex = lexical_ranks[i] + 1
            score = (1.0 / (60.0 + r_sem)) + (1.0 / (60.0 + r_lex))
            rrf_scores.append(score)
            
        rrf_scores = np.array(rrf_scores)
        
        # Sort documents by RRF score descending
        sorted_indices = np.argsort(rrf_scores)[::-1]
        
        # Slice to the top k
        results = []
        for idx in sorted_indices[:k]:
            doc = docs[idx]
            max_possible_rrf = 2.0 / 61.0
            percentage = max(0.0, min(100.0, float(rrf_scores[idx] / max_possible_rrf) * 100.0))
            doc.metadata["relevance_score"] = round(percentage, 1)
            results.append(doc)
            
        return results
    except Exception as e:
        print(f"[rag_engine] Error in retrieve_relevant_chunks: {e}")
        return []


def query_rag_filtered(question: str, filter_metadata: Optional[Dict] = None,
                       k: int = 3, semantic_weight: float = 0.7) -> Dict[str, Any]:
    """
    Query FAISS with advanced Lexical-Semantic Hybrid Search & Bi-Encoder Re-ranking.
    """
    global vector_store

    if not HAS_RAG or vector_store is None:
        return {
            "success": False,
            "error": "Vector database is empty or not initialized."
        }

    try:
        results = retrieve_relevant_chunks(question, filter_metadata, k=k, semantic_weight=semantic_weight)
        if not results:
            filter_desc = ", ".join(f"{k}={v}" for k, v in (filter_metadata or {}).items())
            return {
                "success": False,
                "error": f"No results matching filter: {filter_desc}" if filter_metadata else "No relevant information found."
            }

        # Filter by minimum relevance threshold to prevent hallucinations from weak matches
        import llm_client
        min_relevance = float(llm_client.config_data.get("rag_min_relevance", 40.0))
        relevant_results = [doc for doc in results if doc.metadata.get("relevance_score", 0.0) >= min_relevance]
        if not relevant_results:
            return {
                "success": False,
                "error": f"No highly relevant information found matching threshold ({min_relevance}%). Query rejected to prevent hallucinations."
            }

        context_text = "\n---\n".join([
            f"Context (File: {doc.metadata.get('filename', 'Unknown')}, "
            f"Vendor: {doc.metadata.get('vendor_id', 'N/A')}, "
            f"Relevance: {doc.metadata.get('relevance_score', '0.0')}%): {doc.page_content}"
            for doc in relevant_results
        ])

        prompt = f"""You are an elite procurement intelligence auditor.
Use the following retrieved context from vendor documents to answer the question.
If the answer is not in the context, say "I cannot find the answer in the provided documents."

CONTEXT:
{context_text}

QUESTION: {question}

Provide a concise, professional answer and cite the source file if possible.
ANSWER:"""

        try:
            import llm_client
            llm_response = llm_client.generate_text(prompt, temperature=0.0)
            return {
                "success": True,
                "answer": llm_response,
                "citations": [doc.metadata for doc in relevant_results],
                "filtered_count": len(relevant_results),
            }
        except Exception as llm_err:
            print(f"[rag_engine] LLM generation failed: {llm_err}")
            return {
                "success": True,
                "answer": f"Found relevant text, but LLM is offline. Extracted snippet: {relevant_results[0].page_content}",
                "citations": [doc.metadata for doc in relevant_results],
                "filtered_count": len(relevant_results),
            }

    except Exception as e:
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────────
#  ADVANCED RAG: Multi-Query + Cross-Encoder Re-Ranking
# ─────────────────────────────────────────────────────────────────

# Cross-encoder model (loaded once, lazily)
_cross_encoder = None
_cross_encoder_model_name = "cross-encoder/ms-marco-MiniLM-L-6-v2"

def _get_cross_encoder():
    """Lazily load the cross-encoder model."""
    global _cross_encoder
    if _cross_encoder is None:
        try:
            from sentence_transformers import CrossEncoder
            _cross_encoder = CrossEncoder(_cross_encoder_model_name, max_length=512)
            print(f"[rag_engine] Cross-encoder '{_cross_encoder_model_name}' loaded.")
        except Exception as e:
            print(f"[rag_engine] Cross-encoder unavailable: {e}")
    return _cross_encoder


def multi_query_retrieve(
    question: str,
    filter_metadata: Optional[Dict] = None,
    k: int = 5,
    num_queries: int = 3
) -> List:
    """
    Multi-Query RAG Retrieval — generates several query variants,
    retrieves chunks for each, and deduplicates results.

    Why: A single query often misses relevant chunks due to vocabulary
    mismatch. Multiple reformulations catch what one query misses.

    Args:
        question: Original user question
        filter_metadata: Optional metadata filter (e.g., vendor_id)
        k: Final number of chunks to return
        num_queries: Number of query variants to generate

    Returns:
        Deduplicated list of the most relevant Document chunks
    """
    if not HAS_RAG or vector_store is None:
        return []

    # Step 1: Generate query variants using LLM
    query_variants = [question]
    try:
        import llm_client
        variant_prompt = (
            f"Generate {num_queries} different ways to ask the following question "
            f"for a procurement document search. Use different keywords and phrasing. "
            f"Each variant should focus on a different aspect.\n\n"
            f"ORIGINAL QUESTION: {question}\n\n"
            f"Return ONLY a JSON array of {num_queries} question strings. "
            f"No explanation. Example: [\"variant 1\", \"variant 2\", \"variant 3\"]"
        )
        result_text = llm_client.generate_text(
            variant_prompt,
            system_instruction="You generate search query variants for procurement document retrieval.",
            temperature=0.3,
            is_verification_query=True
        )
        # Parse the JSON array
        import json as _json
        clean = result_text.strip()
        start = clean.find("[")
        end = clean.rfind("]")
        if start != -1 and end != -1:
            variants = _json.loads(clean[start:end+1])
            if isinstance(variants, list) and variants:
                query_variants = [question] + [v for v in variants if isinstance(v, str)]
    except Exception as e:
        print(f"[rag_engine] Multi-query variant generation failed: {e}")

    # Step 2: Retrieve chunks for each query variant
    seen_hashes = set()
    all_chunks = []
    per_query_k = max(k, 8)  # retrieve more per query, prune later

    for variant in query_variants[:num_queries + 1]:
        try:
            chunks = retrieve_relevant_chunks(variant, filter_metadata, k=per_query_k)
            for chunk in chunks:
                # Deduplicate by content hash
                content_hash = hashlib.sha256(chunk.page_content.encode()).hexdigest()
                if content_hash not in seen_hashes:
                    seen_hashes.add(content_hash)
                    all_chunks.append(chunk)
        except Exception as e:
            print(f"[rag_engine] Retrieval failed for variant '{variant[:40]}...': {e}")

    if not all_chunks:
        return []

    # Step 3: Sort by relevance score and return top-k
    all_chunks.sort(
        key=lambda d: d.metadata.get("relevance_score", 0.0),
        reverse=True
    )
    return all_chunks[:k]


def cross_encoder_rerank(question: str, chunks: List, top_k: int = 5) -> List:
    """
    Re-rank document chunks using a cross-encoder model.

    The cross-encoder reads the question AND document together —
    much more accurate than bi-encoder similarity alone.
    Falls back to original order if model unavailable.

    Args:
        question: The original question
        chunks: List of Document chunks (from multi_query_retrieve or retrieve_relevant_chunks)
        top_k: Number of top-ranked chunks to return

    Returns:
        Re-ranked list of top_k Document chunks
    """
    if not chunks:
        return []

    cross_enc = _get_cross_encoder()
    if cross_enc is None:
        return chunks[:top_k]

    try:
        pairs = [(question, chunk.page_content[:500]) for chunk in chunks]
        scores = cross_enc.predict(pairs)
        # Attach cross-encoder score to metadata
        for chunk, score in zip(chunks, scores):
            chunk.metadata["cross_encoder_score"] = round(float(score), 4)
        # Sort by cross-encoder score descending
        ranked = sorted(chunks, key=lambda c: c.metadata.get("cross_encoder_score", 0.0), reverse=True)
        print(f"[rag_engine] Cross-encoder re-ranked {len(chunks)} chunks -> top {top_k}")
        return ranked[:top_k]
    except Exception as e:
        print(f"[rag_engine] Cross-encoder re-ranking failed: {e}")
        return chunks[:top_k]


def advanced_query(
    question: str,
    filter_metadata: Optional[Dict] = None,
    k: int = 5,
    vendor_name: str = ""
) -> Dict[str, Any]:
    """
    Gold-standard RAG query pipeline:
      1. Multi-Query Retrieval (3 query variants)
      2. Cross-Encoder Re-Ranking (ms-marco-MiniLM)
      3. LLM Answer Generation with citations

    Significantly more accurate than single-query retrieval.
    Falls back to query_rag_filtered() if advanced pipeline fails.

    Args:
        question: The user's question
        filter_metadata: Optional vendor_id/tender_id filter
        k: Number of context chunks to include
        vendor_name: Optional vendor name for context

    Returns:
        Standard RAG response dict with answer + citations
    """
    if not HAS_RAG or vector_store is None:
        return {"success": False, "error": "Vector database is not initialized."}

    try:
        # Step 1: Multi-query retrieval
        candidates = multi_query_retrieve(question, filter_metadata, k=k * 3, num_queries=3)

        if not candidates:
            return {"success": False, "error": "No relevant documents found in knowledge base."}

        # Step 2: Cross-encoder re-ranking
        top_chunks = cross_encoder_rerank(question, candidates, top_k=k)

        # Step 3: Build context and generate LLM answer
        context_text = "\n---\n".join([
            f"[Source {i+1} | File: {c.metadata.get('filename', 'Unknown')} "
            f"| Vendor: {c.metadata.get('vendor_id', 'N/A')} "
            f"| Score: {c.metadata.get('cross_encoder_score', c.metadata.get('relevance_score', 0))}]: "
            f"{c.page_content}"
            for i, c in enumerate(top_chunks)
        ])

        vendor_context = f" about vendor '{vendor_name}'" if vendor_name else ""
        prompt = (
            f"You are a precise Government procurement intelligence system.\n"
            f"Answer the following question{vendor_context} using ONLY the retrieved document context.\n"
            f"Cite the source number [Source N] for every factual claim.\n"
            f"If the answer is not in the context, say: 'Information not found in uploaded documents.'\n\n"
            f"RETRIEVED CONTEXT:\n{context_text}\n\n"
            f"QUESTION: {question}\n\n"
            f"ANSWER (cite sources):"
        )

        try:
            import llm_client
            answer = llm_client.generate_text(prompt, temperature=0.0, is_verification_query=False)
            return {
                "success": True,
                "answer": answer,
                "citations": [c.metadata for c in top_chunks],
                "retrieval_method": "multi_query + cross_encoder",
                "chunks_retrieved": len(candidates),
                "chunks_used": len(top_chunks),
            }
        except Exception as llm_err:
            return {
                "success": True,
                "answer": f"LLM offline. Top context: {top_chunks[0].page_content[:300]}...",
                "citations": [c.metadata for c in top_chunks],
                "retrieval_method": "multi_query + cross_encoder (LLM offline)",
                "chunks_retrieved": len(candidates),
                "chunks_used": len(top_chunks),
            }

    except Exception as e:
        print(f"[rag_engine] advanced_query failed, falling back: {e}")
        return query_rag_filtered(question, filter_metadata, k=k)


def get_index_stats() -> Dict[str, Any]:
    """
    Returns statistics about the current FAISS index.

    Returns:
        dict with:
            - document_count: number of unique documents (by hash)
            - chunk_count: total chunks in the index
            - unique_hashes: count of unique content hashes
            - index_size_bytes: approximate index file size on disk
            - initialized: whether the RAG system is ready
    """
    global vector_store, _doc_hashes, _chunk_count

    with _rag_lock:
        stats = {
            "initialized": HAS_RAG and embeddings_model is not None,
            "has_index": vector_store is not None,
            "document_count": len(_doc_hashes),
            "chunk_count": _chunk_count,
            "unique_hashes": len(_doc_hashes),
            "index_size_bytes": 0,
        }

    # Check persisted index size
    index_file = os.path.join(DEFAULT_INDEX_DIR, "index.faiss")
    if os.path.isfile(index_file):
        stats["index_size_bytes"] = os.path.getsize(index_file)
        # Also include the pkl file if present
        pkl_file = os.path.join(DEFAULT_INDEX_DIR, "index.pkl")
        if os.path.isfile(pkl_file):
            stats["index_size_bytes"] += os.path.getsize(pkl_file)

    return stats


# ─────────────────────────────────────────────────────────────────
#  MODULE INITIALIZATION
# ─────────────────────────────────────────────────────────────────
# Initialize on module load
init_rag()
