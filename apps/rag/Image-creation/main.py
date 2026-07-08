import os, time
from typing import Optional
import httpx, requests
import psycopg2
from pgvector.psycopg2 import register_vector
from fastapi import FastAPI, Header, HTTPException, UploadFile, Form, Request
from fastapi.responses import StreamingResponse
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
import jwt
from jwt import PyJWKClient
from sentence_transformers import SentenceTransformer

# ---------------- Config ----------------
DATABASE_URL  = os.environ["DATABASE_URL"]
EMBED_MODEL   = os.environ.get("EMBED_MODEL", "intfloat/multilingual-e5-base")
VLLM_URL      = os.environ.get("VLLM_URL", "http://vllm-router-service.vllm.svc.cluster.local/v1")
VLLM_MODEL    = os.environ.get("VLLM_MODEL", "Qwen/Qwen2.5-14B-Instruct-AWQ")
PUBLIC_MODEL  = os.environ.get("PUBLIC_MODEL", "mirecloud-rag")
JWKS_URL      = os.environ.get("KEYCLOAK_JWKS", "")
ISSUER        = os.environ.get("KEYCLOAK_ISSUER", "")
GROUPS_CLAIM  = os.environ.get("GROUPS_CLAIM", "groups")
ADMIN_GROUP   = os.environ.get("ADMIN_GROUP", "admin")
TOP_K         = int(os.environ.get("TOP_K", "5"))
MIN_SCORE     = float(os.environ.get("MIN_SCORE", "0.30"))
# --- Keycloak admin : résolution email -> groupes (pour Open WebUI) ---
KC_TOKEN_URL  = os.environ.get("KC_TOKEN_URL", "https://keycloak.mirecloud.com/auth/realms/mirecloud/protocol/openid-connect/token")
KC_ADMIN_API  = os.environ.get("KC_ADMIN_API", "https://keycloak.mirecloud.com/auth/admin/realms/mirecloud")
KC_SA_CLIENT  = os.environ.get("KC_SA_CLIENT_ID", "rag-backend")
KC_SA_SECRET  = os.environ.get("KC_SA_CLIENT_SECRET", "")

SYSTEM_PROMPT = ("Tu es l'assistant interne de Mirecloud. Réponds à la question en te basant "
                 "UNIQUEMENT sur le contexte fourni. Cite la source entre crochets. "
                 "Si l'information n'y figure pas, dis-le clairement.")

app = FastAPI(title="mirecloud-rag")
_model: Optional[SentenceTransformer] = None
_jwks = PyJWKClient(JWKS_URL) if JWKS_URL else None
_sa = {"tok": None, "exp": 0.0}


@app.on_event("startup")
def _startup():
    global _model
    _model = SentenceTransformer(EMBED_MODEL)


# ---------------- Embeddings / DB ----------------
def embed_query(text: str):
    return _model.encode(["query: " + text], normalize_embeddings=True)[0]

def embed_passages(texts):
    return _model.encode(["passage: " + t for t in texts], normalize_embeddings=True)

def get_conn():
    conn = psycopg2.connect(DATABASE_URL); register_vector(conn); return conn


# ---------------- Keycloak : email -> groupes ----------------
def _sa_token():
    if _sa["tok"] and time.time() < _sa["exp"] - 30:
        return _sa["tok"]
    r = requests.post(KC_TOKEN_URL, data={"grant_type": "client_credentials",
        "client_id": KC_SA_CLIENT, "client_secret": KC_SA_SECRET}, timeout=10)
    r.raise_for_status(); j = r.json()
    _sa.update(tok=j["access_token"], exp=time.time() + j.get("expires_in", 60))
    return _sa["tok"]

def groups_from_email(email: str):
    h = {"Authorization": f"Bearer {_sa_token()}"}
    u = requests.get(f"{KC_ADMIN_API}/users", params={"email": email, "exact": "true"}, headers=h, timeout=10)
    u.raise_for_status()
    users = u.json()
    if not users:
        return []
    uid = users[0]["id"]
    g = requests.get(f"{KC_ADMIN_API}/users/{uid}/groups", headers=h, timeout=10)
    g.raise_for_status()
    return [x["name"].lstrip("/") for x in g.json()]


# ---------------- Identité -> groupes (3 sources) ----------------
def resolve_groups(authorization: Optional[str], x_user_groups: Optional[str], email: Optional[str] = None):
    print(f"IDENTITY jwt={'yes' if authorization and authorization.startswith('Bearer ') else 'no'} "
          f"x_groups={x_user_groups!r} email={email!r}", flush=True)   # debug
    # 1. JWT Keycloak (clients directs)
    if authorization and authorization.startswith("Bearer ") and _jwks:
        try:
            token = authorization.split(" ", 1)[1]
            key = _jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["RS256"], issuer=ISSUER or None,
                                options={"verify_aud": False, "verify_iss": bool(ISSUER)})
            g = claims.get(GROUPS_CLAIM) or []
            if g:
                return [x.lstrip("/") for x in g]
        except Exception:
            pass
    # 2. header groupes (si Open WebUI le forwarde)
    if x_user_groups:
        return [s.strip().lstrip("/") for s in x_user_groups.split(",") if s.strip()]
    # 3. email -> Keycloak (Open WebUI ne forwarde que l'email)
    if email and KC_SA_SECRET:
        g = groups_from_email(email)
        if g:
            return g
    raise HTTPException(401, "Identité absente : Bearer JWT, X-User-Groups, ou X-OpenWebUI-User-Email")


def retrieve(groups, question, k=TOP_K):
    qvec = embed_query(question)
    is_admin = ADMIN_GROUP in groups
    with get_conn() as conn, conn.cursor() as cur:
        if is_admin:
            cur.execute("""SELECT document_id, content, 1-(embedding <=> %s)
                           FROM rag_chunks WHERE length(content) > 60
                           ORDER BY embedding <=> %s LIMIT %s""", (qvec, qvec, k))
        else:
            cur.execute("""SELECT document_id, content, 1-(embedding <=> %s)
                           FROM rag_chunks WHERE allowed_groups && %s::text[] AND length(content) > 60
                           ORDER BY embedding <=> %s LIMIT %s""", (qvec, groups, qvec, k))
        rows = cur.fetchall()
    return [(d, c, float(s)) for d, c, s in rows if s >= MIN_SCORE]

def build_context(chunks):
    return "\n\n".join(f"[{d}]\n{c}" for d, c, _ in chunks) if chunks else "(aucun document accessible)"


@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": PUBLIC_MODEL, "object": "model", "owned_by": "mirecloud"}]}


class QueryReq(BaseModel):
    question: str
    top_k: Optional[int] = None

@app.post("/query")
def query(req: QueryReq, authorization: Optional[str] = Header(None),
          x_user_groups: Optional[str] = Header(None),
          x_openwebui_user_email: Optional[str] = Header(None)):
    groups = resolve_groups(authorization, x_user_groups, x_openwebui_user_email)
    chunks = retrieve(groups, req.question, req.top_k or TOP_K)
    if not chunks:
        return {"answer": "Aucun document pertinent accessible.", "groups": groups, "sources": []}
    r = requests.post(f"{VLLM_URL}/chat/completions", json={"model": VLLM_MODEL,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": f"Contexte:\n{build_context(chunks)}\n\nQuestion: {req.question}"}],
        "temperature": 0.2}, timeout=180)
    r.raise_for_status()
    return {"answer": r.json()["choices"][0]["message"]["content"], "groups": groups,
            "sources": [{"document_id": d, "score": s} for d, c, s in chunks]}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request,
                           authorization: Optional[str] = Header(None),
                           x_openwebui_user_groups: Optional[str] = Header(None),
                           x_openwebui_user_email: Optional[str] = Header(None)):
    body = await request.json()
    messages = body.get("messages", [])
    stream = bool(body.get("stream", False))
    question = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")

    groups = resolve_groups(authorization, x_openwebui_user_groups, x_openwebui_user_email)
    chunks = await run_in_threadpool(retrieve, groups, question)
    augmented = [{"role": "system", "content": f"{SYSTEM_PROMPT}\n\nContexte:\n{build_context(chunks)}"}] + messages
    payload = {"model": VLLM_MODEL, "messages": augmented,
               "temperature": body.get("temperature", 0.2), "stream": stream}

    if stream:
        async def proxy():
            async with httpx.AsyncClient(timeout=None) as c:
                async with c.stream("POST", f"{VLLM_URL}/chat/completions", json=payload) as r:
                    async for chunk in r.aiter_bytes():
                        yield chunk
        return StreamingResponse(proxy(), media_type="text/event-stream")
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(f"{VLLM_URL}/chat/completions", json=payload)
        r.raise_for_status()
        return r.json()