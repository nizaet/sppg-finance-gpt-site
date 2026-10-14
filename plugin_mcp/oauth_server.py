from __future__ import annotations

import base64, hashlib, html, json, os, time
from urllib.parse import urlencode
import httpx, jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

_CODES: dict[str, dict] = {}
CORE = os.getenv("SPPG_CORE_API_URL", "https://sppg-finance-gpt-site-production-5b7d.up.railway.app").rstrip("/")

def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")

def _key():
    raw=os.getenv("SPPG_OAUTH_PRIVATE_KEY_B64","").strip()
    if not raw: raise RuntimeError("OAuth signing key missing")
    pem=base64.b64decode(raw)
    return serialization.load_pem_private_key(pem,password=None)

def jwks():
    pub=_key().public_key().public_numbers()
    return {"keys":[{"kty":"RSA","use":"sig","alg":"RS256","kid":"sppg-owner-1","n":_b64(pub.n.to_bytes((pub.n.bit_length()+7)//8,"big")),"e":_b64(pub.e.to_bytes((pub.e.bit_length()+7)//8,"big"))}]}

def metadata(issuer: str):
    return {"issuer":issuer,"authorization_endpoint":issuer+"/authorize","token_endpoint":issuer+"/token","registration_endpoint":issuer+"/register","jwks_uri":issuer+"/jwks.json","response_types_supported":["code"],"grant_types_supported":["authorization_code"],"code_challenge_methods_supported":["S256"],"token_endpoint_auth_methods_supported":["none"],"scopes_supported":["sppg:read"]}

def _valid_redirect(uri:str)->bool:
    return uri.startswith("https://") and "@" not in uri.split("://",1)[1].split("/",1)[0]

async def authorize_get(request: Request, issuer:str):
    q=request.query_params
    needed=("client_id","redirect_uri","state","code_challenge")
    if q.get("response_type")!="code" or q.get("code_challenge_method")!="S256" or any(not q.get(x) for x in needed) or not _valid_redirect(q["redirect_uri"]):
        return JSONResponse({"error":"invalid_request"},400)
    fields="".join(f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(q.get(k,""))}">' for k in ("client_id","redirect_uri","state","code_challenge","scope","resource"))
    return HTMLResponse(f"""<!doctype html><meta name=viewport content="width=device-width"><title>SPPG Plugin Login</title><style>body{{font-family:system-ui;max-width:420px;margin:10vh auto;padding:24px}}input,button{{box-sizing:border-box;width:100%;padding:12px;margin:8px 0}}small{{color:#555}}</style><h2>SPPG Operations</h2><p>Masuk sebagai <b>YAYASAN / OWNER</b>.</p><form method=post action="/authorize">{fields}<input type=password name=password autocomplete=current-password placeholder="Password OWNER" required><button type=submit>Izinkan akses baca</button></form><small>Akses plugin: MAJA + CEMPLANG, read-only.</small>""")

async def authorize_post(request: Request, issuer:str):
    form=await request.form()
    redirect=str(form.get("redirect_uri") or ""); state=str(form.get("state") or "")
    if not _valid_redirect(redirect): return JSONResponse({"error":"invalid_redirect_uri"},400)
    password=str(form.get("password") or "")
    async with httpx.AsyncClient(timeout=15) as c:
        r=await c.post(CORE+"/v1/auth/login",json={"username":"OWNER","password":password,"remember":False})
    if r.status_code!=200:
        return HTMLResponse("<h3>Login OWNER gagal</h3><p>Password tidak cocok. Kembali dan coba lagi.</p>",401)
    me=r.json()
    if str(me.get("role","")).upper()!="OWNER": return JSONResponse({"error":"access_denied"},403)
    code=_b64(os.urandom(32)); now=int(time.time())
    _CODES[code]={"client_id":str(form.get("client_id") or ""),"redirect_uri":redirect,"challenge":str(form.get("code_challenge") or ""),"scope":"sppg:read","iat":now}
    return RedirectResponse(redirect+"?"+urlencode({"code":code,"state":state}),303)

async def token(request:Request, issuer:str, audience:str):
    form=await request.form(); code=str(form.get("code") or ""); rec=_CODES.pop(code,None)
    if not rec or int(time.time())-rec["iat"]>300: return JSONResponse({"error":"invalid_grant"},400)
    if str(form.get("grant_type"))!="authorization_code" or str(form.get("redirect_uri"))!=rec["redirect_uri"] or str(form.get("client_id") or "")!=rec["client_id"]:
        return JSONResponse({"error":"invalid_grant"},400)
    verifier=str(form.get("code_verifier") or "")
    if _b64(hashlib.sha256(verifier.encode()).digest())!=rec["challenge"]: return JSONResponse({"error":"invalid_grant"},400)
    now=int(time.time()); claims={"iss":issuer,"sub":"SPPG_OWNER","aud":audience,"iat":now,"exp":now+3600,"scope":"sppg:read"}
    tok=jwt.encode(claims,_key(),algorithm="RS256",headers={"kid":"sppg-owner-1"})
    return JSONResponse({"access_token":tok,"token_type":"Bearer","expires_in":3600,"scope":"sppg:read"})

async def register(request:Request, issuer:str):
    body=await request.json(); uris=body.get("redirect_uris") or []
    if not uris or any(not _valid_redirect(str(u)) for u in uris): return JSONResponse({"error":"invalid_redirect_uris"},400)
    seed=json.dumps(sorted(uris),separators=(",",":")).encode()
    cid="chatgpt-"+hashlib.sha256(seed).hexdigest()[:24]
    return JSONResponse({"client_id":cid,"client_id_issued_at":int(time.time()),"redirect_uris":uris,"token_endpoint_auth_method":"none","grant_types":["authorization_code"],"response_types":["code"]},201)
