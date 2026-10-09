# ToshiBot DWG reader: POST raw DWG bytes -> {version, release, texts, dims, attrs, layers, png(base64), warnings}.
# Transient only: each request uses a private temp dir that is deleted before the response. Nothing is logged or stored.
import os, hmac, json, tempfile, subprocess, sys, hashlib
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
# Only the SHA-256 of the shared secret is configured here; the plaintext lives in the caller (Supabase secrets).
SECRET_SHA = os.environ.get("DWG_SECRET_SHA256", "").strip().lower()
MAX = int(os.environ.get("DWG_MAX_BYTES", str(30 * 1024 * 1024)))
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

@app.get("/health")
def health(): return {"ok": True}

@app.post("/read")
async def read(req: Request):
    got = hashlib.sha256(req.headers.get("x-dwg-secret", "").encode()).hexdigest()
    if len(SECRET_SHA) != 64 or not hmac.compare_digest(got, SECRET_SHA): raise HTTPException(401, "unauthorized")
    body = await req.body()
    if not body: raise HTTPException(400, "empty file")
    if len(body) > MAX: raise HTTPException(413, "file too large")
    if not body[:4] == b"AC10": return JSONResponse({"error": "not a DWG file"}, 422)
    with tempfile.TemporaryDirectory() as tmp:
        dwg = os.path.join(tmp, "in.dwg")
        with open(dwg, "wb") as f: f.write(body)
        try:
            p = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "worker.py"), dwg, tmp], capture_output=True, timeout=100)
        except subprocess.TimeoutExpired:
            return JSONResponse({"error": "timed out reading this drawing"}, 504)
        if p.returncode != 0:
            last = p.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or ["failed"]
            return JSONResponse({"error": "could not read this DWG", "detail": last[0][:200]}, 422)
        return JSONResponse(json.loads(p.stdout))
