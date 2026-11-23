"""M3: chunk + embed + store in ChromaDB; retrieval with freshness boost and source diversity.

python -m spai.kb            # index data/processed/documents.jsonl (only new chunks are embedded)
python -m spai.kb "query"    # test a search
"""
import sys
from datetime import date

import chromadb
from langchain_text_splitters import RecursiveCharacterTextSplitter

from . import config, llm
from .ingest import _id, load_docs

def _coll_name():
    """One collection per embedding model, so switching models never mixes vector sizes."""
    import re
    return "kb_" + re.sub(r"[^a-zA-Z0-9]+", "_", llm.embed_tag()).strip("_").lower()


def _col():
    c = chromadb.PersistentClient(path=str(config.CHROMA))
    return c.get_or_create_collection(_coll_name(), metadata={"hnsw:space": "cosine"})


def index(batch=200):
    docs = load_docs()
    split = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=200)
    col = _col()
    existing = set(col.get(include=[])["ids"])
    ids, texts, metas = [], [], []
    for d in docs:
        for j, ch in enumerate(split.split_text(d["text"])):
            cid = _id(d["id"], str(j), ch[:64])
            if cid in existing or cid in ids:
                continue
            ids.append(cid)
            texts.append(f"{d['title']}\n{ch}")
            metas.append({"doc_id": d["id"], "source": d["source"], "kind": d["kind"],
                          "title": d["title"][:300], "url": d["url"], "date": d["date"] or "",
                          "date_known": d["date_known"]})
    print(f"{len(docs)} documents, {len(existing)} chunks already indexed, {len(ids)} new")
    for i in range(0, len(ids), batch):
        vecs = llm.embed(texts[i:i + batch])
        col.upsert(ids=ids[i:i + batch], embeddings=vecs, documents=texts[i:i + batch],
                   metadatas=metas[i:i + batch])
        print(f"  indexed {min(i + batch, len(ids))}/{len(ids)}", flush=True)
    print("collection size:", col.count())


def _age_days(d: str):
    try:
        return (date.today() - date.fromisoformat(d)).days
    except ValueError:
        return None


def retrieve(query: str, k: int = 8, kinds: list[str] | None = None, prefer_fresh=True,
             per_doc=2) -> list[dict]:
    """Return up to k chunks: cosine similarity + small freshness boost, max per_doc per document."""
    col = _col()
    where = {"kind": {"$in": kinds}} if kinds else None
    r = col.query(query_embeddings=[llm.embed_query(query)], n_results=k * 4, where=where)
    fresh = config.sources()["freshness_days"]
    hits = []
    for cid, txt, m, dist in zip(r["ids"][0], r["documents"][0], r["metadatas"][0], r["distances"][0]):
        score = 1 - dist
        age = _age_days(m["date"]) if m.get("date_known") else None
        if prefer_fresh and age is not None and age <= fresh:
            score += 0.04 * (1 - age / fresh)
        hits.append({"chunk_id": cid, "text": txt, "score": round(score, 4), "age_days": age, **m})
    hits.sort(key=lambda h: -h["score"])
    out, per = [], {}
    for h in hits:
        if per.get(h["doc_id"], 0) >= per_doc:
            continue
        per[h["doc_id"]] = per.get(h["doc_id"], 0) + 1
        out.append(h)
        if len(out) == k:
            break
    return out


def stats():
    col = _col()
    metas = col.get(include=["metadatas"])["metadatas"]
    from collections import Counter
    return {"chunks": len(metas), "by_kind": dict(Counter(m["kind"] for m in metas)),
            "by_source": dict(Counter(m["source"] for m in metas))}


if __name__ == "__main__":
    if len(sys.argv) > 1:
        for h in retrieve(" ".join(sys.argv[1:])):
            print(f"{h['score']:.3f} [{h['source']}] {h['date'] or '-'} {h['title'][:80]}")
    else:
        index()
