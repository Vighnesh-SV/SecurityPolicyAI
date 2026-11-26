"""Gemini wrapper: model fallback, retries, disk cache, rate-limited embeddings."""
import hashlib
import json
import re
import time
from collections import deque

from google import genai
from google.genai import errors, types

from . import config

_clients: dict[str, genai.Client] = {}
LLM_CACHE = config.CACHE / "llm"
EMB_CACHE = config.CACHE / "emb"
LLM_CACHE.mkdir(parents=True, exist_ok=True)
EMB_CACHE.mkdir(parents=True, exist_ok=True)


def keys() -> list[str]:
    """All Gemini keys: GEMINI_API_KEY, GEMINI_API_KEY_2 … _9, and/or GEMINI_API_KEYS=a,b,c.
    Free-tier quota is per Google Cloud PROJECT, so backup keys must come from different projects."""
    import os
    found = [os.environ.get("GEMINI_API_KEY", "")]
    found += [os.environ.get(f"GEMINI_API_KEY_{i}", "") for i in range(2, 10)]
    found += os.environ.get("GEMINI_API_KEYS", "").split(",")
    out = []
    for k in (k.strip() for k in found):
        if k and k not in out:
            out.append(k)
    if not out:
        config.key("GEMINI_API_KEY")          # raises the usual "missing key" error
    return out


def client(key: str | None = None):
    key = key or keys()[0]
    if key not in _clients:
        # Our own fallback handles busy models, so turn off the SDK's long internal retries.
        _clients[key] = genai.Client(api_key=key, http_options=types.HttpOptions(
            timeout=120_000, retry_options=types.HttpRetryOptions(attempts=1)))
    return _clients[key]


def key_status() -> list[dict]:
    """For /health: which keys are usable right now (keys shown masked)."""
    now = time.time()
    return [{"key": f"…{k[-4:]}", "benched_models": sorted(m for (kk, m), t in _benched.items() if kk == k and t > now)}
            for k in keys()]


def _h(*parts) -> str:
    return hashlib.sha256("\x1f".join(map(str, parts)).encode("utf-8")).hexdigest()[:32]


def _retry_delay(e: Exception, default: float) -> float:
    m = re.search(r"retry in ([\d.]+)s", str(e))
    return float(m.group(1)) + 1 if m else default


class LLMError(RuntimeError):
    pass


_benched: dict[tuple[str, str], float] = {}   # (key, model) -> time until which we skip it
BENCH_SECONDS = 600     # quota hit (429) on this key+model
BUSY_SECONDS = 120      # model overloaded (503): same for every key, retry soon


def generate(prompt: str, role: str = "generator", system: str | None = None,
             json_out: bool = False, temperature: float = 0.6, use_cache: bool = True,
             max_rounds: int = 3) -> dict:
    """Return {"text", "model", "cached"}. Tries every (model, key) pair; rotates on 503/429."""
    chain = config.models()[role]
    ck = LLM_CACHE / f"{_h(role, system, prompt, json_out, temperature)}.json"
    if use_cache and ck.exists():
        d = json.loads(ck.read_text(encoding="utf-8"))
        return {**d, "cached": True}
    cfg = types.GenerateContentConfig(
        system_instruction=system, temperature=temperature,
        response_mime_type="application/json" if json_out else None)
    last = None
    for rnd in range(max_rounds):
        pairs = [(m, k) for m in chain for k in keys()]
        live = [p for p in pairs if _benched.get((p[1], p[0]), 0) < time.time()]
        all_benched = not live
        for model, key in (live or pairs):
            if not all_benched and _benched.get((key, model), 0) > time.time():
                continue                      # benched earlier in this same round (e.g. model busy)
            try:
                r = client(key).models.generate_content(model=model, contents=prompt, config=cfg)
                text = r.text or ""
                if json_out:
                    json.loads(text)          # raise now if the model returned broken JSON
                d = {"text": text, "model": model}
                ck.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
                return {**d, "cached": False}
            except errors.APIError as e:
                last = e
                if e.code == 429 or e.code == 404:          # this key's quota (or model closed to it)
                    _benched[(key, model)] = time.time() + BENCH_SECONDS
                    continue
                if e.code in (500, 503, 504):                # model busy for everyone
                    for k in keys():
                        _benched[(k, model)] = time.time() + BUSY_SECONDS
                    continue
                if e.code in (400, 401, 403) and "key" in str(e).lower():   # bad / revoked key
                    for m in chain:
                        _benched[(key, m)] = time.time() + 3600
                    continue
                raise
            except json.JSONDecodeError as e:
                last = e
                continue
            except Exception as e:            # network timeout etc.
                last = e
                _benched[(key, model)] = time.time() + 120
                continue
        time.sleep(_retry_delay(last, 10 * (rnd + 1)))
    raise LLMError(f"all models failed for role '{role}': {last}")


def generate_json(prompt: str, **kw) -> tuple[dict, str]:
    r = generate(prompt, json_out=True, **kw)
    return json.loads(r["text"]), r["model"]


# ---------------- embeddings ----------------
_calls = deque()     # (timestamp, n_texts, est_tokens) for the last minute
_local = None


def _est_tokens(t: str) -> int:
    return len(t) // 3 + 8          # conservative: real ratio is ~4 chars/token for English


def _throttle(n: int, tok: int):
    """Free tier: 100 texts/min and 30k tokens/min per model. Stay below both."""
    e = config.models()["embedding"]
    cap_n, cap_t = e["per_minute"], e.get("tokens_per_minute", 25000)
    while True:
        now = time.time()
        while _calls and now - _calls[0][0] > 60:
            _calls.popleft()
        used_n = sum(c[1] for c in _calls)
        used_t = sum(c[2] for c in _calls)
        if used_n + n <= cap_n and used_t + tok <= cap_t:
            _calls.append((now, n, tok))
            return
        wait = 61 - (now - _calls[0][0])
        print(f"  [embed] free-tier limit, waiting {wait:.0f}s", flush=True)
        time.sleep(max(wait, 1))


def _batches(texts, max_n, max_tok):
    cur, cur_t = [], 0
    for t in texts:
        k = _est_tokens(t)
        if cur and (len(cur) >= max_n or cur_t + k > max_tok):
            yield cur
            cur, cur_t = [], 0
        cur.append(t)
        cur_t += k
    if cur:
        yield cur


def _embed_remote(texts, task):
    e = config.models()["embedding"]
    out = []
    for batch in _batches(texts, min(90, e["per_minute"]), e.get("tokens_per_minute", 25000) // 2):
        tok = sum(map(_est_tokens, batch))
        for attempt in range(6):
            _throttle(len(batch), tok)
            try:
                r = client().models.embed_content(
                    model=e["model"], contents=batch,
                    config=types.EmbedContentConfig(task_type=task, output_dimensionality=e["dim"]))
                if len(r.embeddings) != len(batch):
                    raise LLMError("embedding count mismatch")
                out += [x.values for x in r.embeddings]
                break
            except errors.APIError as ex:
                if ex.code != 429 or attempt == 5:
                    raise
                time.sleep(_retry_delay(ex, 30))
    return out


BGE_QUERY = "Represent this sentence for searching relevant passages: "


def _embed_local(texts, task):
    global _local
    if _local is None:
        import os
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        from sentence_transformers import SentenceTransformer
        _local = SentenceTransformer(config.models()["embedding"]["local_model"])
    if task == "RETRIEVAL_QUERY" and "bge" in config.models()["embedding"]["local_model"].lower():
        texts = [BGE_QUERY + t for t in texts]          # bge expects an instruction on queries
    return [v.tolist() for v in _local.encode(texts, normalize_embeddings=True, batch_size=32)]


def embed_tag() -> str:
    e = config.models()["embedding"]
    return e["model"] if e["provider"] == "gemini" else e["local_model"]


def embed(texts: list[str], task: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    """Embed with a per-text disk cache, so re-indexing never re-spends quota."""
    e = config.models()["embedding"]
    tag = embed_tag()
    keys = [_h(tag, e["dim"], task, t) for t in texts]
    vecs: dict[int, list[float]] = {}
    todo = []
    for i, k in enumerate(keys):
        f = EMB_CACHE / f"{k}.json"
        if f.exists():
            vecs[i] = json.loads(f.read_text())
        else:
            todo.append(i)
    if todo:
        new = (_embed_remote([texts[i] for i in todo], task) if e["provider"] == "gemini"
               else _embed_local([texts[i] for i in todo], task))
        for i, v in zip(todo, new):
            vecs[i] = v
            (EMB_CACHE / f"{keys[i]}.json").write_text(json.dumps(v))
    return [vecs[i] for i in range(len(texts))]


def embed_query(text: str) -> list[float]:
    return embed([text], task="RETRIEVAL_QUERY")[0]
