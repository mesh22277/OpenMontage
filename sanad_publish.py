#!/usr/bin/env python3
"""SANAD Publish: staging approved video files for publishing connectors."""
import os, re, json, time, uuid, hmac, hashlib, secrets, shutil, subprocess
from pathlib import Path
from email.parser import BytesParser
from email.policy import default
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
PORT = int(os.environ.get("SANAD_PUBLISH_PORT", "8765"))
TOKEN = os.environ.get("SANAD_PUBLISH_TOKEN") or secrets.token_urlsafe(32)
if len(TOKEN) < 32:
    raise SystemExit("SANAD_PUBLISH_TOKEN must have at least 32 characters")
ROOT = Path(os.environ.get("SANAD_PUBLISH_DIR", str(Path.home() / ".sanad-publish"))).resolve()
ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
DOMAIN = os.environ.get("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN")
NAME = os.environ.get("CODESPACE_NAME")
BASE = os.environ.get("SANAD_PUBLISH_BASE_URL") or (f"https://{NAME}-{PORT}.{DOMAIN}" if NAME and DOMAIN else f"http://localhost:{PORT}")
BASE = BASE.rstrip("/")
LIMIT = 100 * 1024 * 1024
TTL = 6 * 3600
PAGE = """<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SANAD PUBLISH 1.1</title><style>body{background:#101010;color:#eee;font:16px system-ui;margin:32px auto;max-width:680px;padding:0 20px}h1{color:#dec18a}form,section{border:1px solid #383838;padding:20px;border-radius:14px}input,button{box-sizing:border-box;width:100%;padding:12px;margin:8px 0;background:#202020;color:#eee;border:1px solid #666;border-radius:8px}button{background:#dec18a;color:#111;font-weight:bold}pre,a{white-space:pre-wrap;overflow-wrap:anywhere;color:#eee}small{color:#aaa}</style><h1>SANAD PUBLISH 1.1</h1><p>رفع النسخة المعتمدة وإصدار رابط مؤقت للنشر</p><form action="/api/upload" method="post" enctype="multipart/form-data"><label>رمز الدخول</label><input type="password" name="token" required autocomplete="off"><label>الفيديو النهائي MP4</label><input name="video" type="file" accept="video/mp4,.mp4" required><label><input type="checkbox" name="approved" value="yes" required style="width:auto"> هذه النسخة معتمدة للنشر</label><button type="submit">رفع وفحص الفيديو</button><small>طريقة رفع مباشرة متوافقة مع نماذج Safari. الرابط صالح ست ساعات.</small></form></html>"""
def sign(asset, expires):
    return hmac.new(TOKEN.encode(), f"{asset}:{expires}".encode(), hashlib.sha256).hexdigest()
def valid(asset, expires, sig):
    return bool(re.fullmatch(r"[0-9a-f]{32}", asset) and time.time() <= expires <= time.time()+TTL+30 and hmac.compare_digest(sign(asset, expires), sig))
def probe(path):
    p = subprocess.run(["ffprobe","-v","error","-show_streams","-show_format","-of","json",str(path)],capture_output=True,timeout=30,check=True)
    data=json.loads(p.stdout)
    v=next(s for s in data["streams"] if s["codec_type"]=="video")
    if "mp4" not in data["format"]["format_name"].split(",") or v["codec_name"]!="h264":
        raise ValueError("MP4/H.264 required")
    duration=float(data["format"]["duration"])
    if not 3 <= duration <= 900: raise ValueError("Duration must be 3–900 seconds")
    return {"width":v["width"],"height":v["height"],"duration":duration,"codec":v["codec_name"],"bytes":path.stat().st_size,"audio":any(s["codec_type"]=="audio" for s in data["streams"])}
class Handler(BaseHTTPRequestHandler):
    protocol_version="HTTP/1.0"
    def log_message(self,*args): pass
    def setup(self):
        super().setup()
        self.connection.settimeout(60)
    def reply(self,status,body,ctype="application/json"):
        if not isinstance(body,bytes): body=json.dumps(body,ensure_ascii=False).encode()
        self.send_response(status);self.send_header("Content-Type",ctype);self.send_header("Content-Length",str(len(body)));self.send_header("Cache-Control","no-store");self.send_header("X-Content-Type-Options","nosniff");self.send_header("Referrer-Policy","no-referrer");self.end_headers()
        if self.command!="HEAD": self.wfile.write(body)
    def error_json(self,status,message):
        self.close_connection=True
        self.reply(status,{"error":message})
    def upload_result(self,status,message,url=None,meta=None):
        body='<html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><body style="background:#101010;color:white;font:18px system-ui;padding:24px"><h1>SANAD PUBLISH 1.1</h1><p>'+escape(message)+'</p>'
        if url:
            safe=escape(url,quote=True)
            body+='<pre dir="ltr" style="overflow-wrap:anywhere;white-space:pre-wrap">'+escape(url)+'</pre><input id="link" readonly dir="ltr" style="width:100%;padding:12px;box-sizing:border-box" value="'+safe+'"><button style="padding:12px" onclick="navigator.clipboard.writeText(document.getElementById(\'link\').value).catch(()=>document.getElementById(\'link\').select())">نسخ رابط النشر</button><p><a style="color:gold" href="'+safe+'">فتح الفيديو للاختبار</a></p><pre>'+escape(json.dumps(meta,ensure_ascii=False))+'</pre>'
        body+='<p><a style="color:gold" href="/">رجوع</a></p></body></html>'
        self.reply(status,body.encode(),"text/html; charset=utf-8")
    def do_POST(self):
        if self.path!="/api/upload": return self.error_json(404,"Not found")
        ct=self.headers.get("Content-Type","")
        if not ct.startswith("multipart/form-data;"): return self.upload_result(415,"Use the upload form")
        try: size=int(self.headers.get("Content-Length","0"))
        except ValueError: return self.upload_result(400,"Invalid length")
        if not 0<size<=LIMIT+65536: return self.upload_result(413,"Maximum 100 MiB")
        asset=uuid.uuid4().hex; tmp=ROOT/(asset+".part"); dest=ROOT/(asset+".mp4")
        try:
            body=self.rfile.read(size)
            if len(body)!=size: raise ValueError("Incomplete upload")
            message=BytesParser(policy=default).parsebytes(("Content-Type: "+ct+"\r\nMIME-Version: 1.0\r\n\r\n").encode()+body)
            parts={p.get_param("name",header="content-disposition"):p.get_payload(decode=True) for p in message.iter_parts()}
            if not hmac.compare_digest(parts.get("token") or b"",TOKEN.encode()): return self.upload_result(401,"رمز الدخول غير صحيح")
            if parts.get("approved")!=b"yes": return self.upload_result(400,"اعتماد النسخة مطلوب")
            video=parts.get("video") or b""
            if not 0<len(video)<=LIMIT: return self.upload_result(413,"Maximum 100 MiB")
            with tmp.open("xb") as file: file.write(video)
            meta=probe(tmp);tmp.replace(dest)
            expires=int(time.time())+TTL
            url=f"{BASE}/media/{asset}/{expires}/{sign(asset,expires)}/video.mp4"
            self.upload_result(201,"تم رفع الفيديو وفحصه بنجاح",url,meta)
        except (ValueError,KeyError,StopIteration,subprocess.SubprocessError,OSError) as exc:
            self.upload_result(400,"فشل الرفع أو فحص الفيديو: "+type(exc).__name__)
        finally: tmp.unlink(missing_ok=True)
    def do_HEAD(self): self.do_GET()
    def do_GET(self):
        path=urlsplit(self.path).path
        if path=="/": return self.reply(200,PAGE.encode(),"text/html; charset=utf-8")
        m=re.fullmatch(r"/media/([0-9a-f]{32})/(\d{1,12})/([0-9a-f]{64})/video\.mp4",path)
        if not m or not valid(m[1],int(m[2]),m[3]): return self.error_json(404,"Not found or expired")
        file=ROOT/(m[1]+".mp4")
        if not file.is_file(): return self.error_json(404,"Not found")
        size=file.stat().st_size; start=0; end=size-1; status=200
        if self.headers.get("Range"):
            r=re.fullmatch(r"bytes=(\d*)-(\d*)",self.headers["Range"])
            if not r or not (r[1] or r[2]): return self.error_json(416,"Invalid range")
            if not r[1]: start=max(0,size-int(r[2]))
            else: start=int(r[1]);end=min(end,int(r[2])) if r[2] else end
            if start>end or start>=size: return self.error_json(416,"Invalid range")
            status=206
        self.send_response(status);self.send_header("Content-Type","video/mp4");self.send_header("Accept-Ranges","bytes");self.send_header("Content-Length",str(end-start+1));self.send_header("Cache-Control","private, no-store");self.send_header("X-Content-Type-Options","nosniff");self.send_header("Referrer-Policy","no-referrer")
        if status==206:self.send_header("Content-Range",f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command=="HEAD":return
        with file.open("rb") as f:
            f.seek(start);left=end-start+1
            while left:
                chunk=f.read(min(left,1024*1024))
                if not chunk:break
                self.wfile.write(chunk);left-=len(chunk)
if __name__=="__main__":
    if not shutil.which("ffprobe"): raise SystemExit("ffprobe required")
    print("SANAD PUBLISH:",BASE,flush=True)
    print("Private upload token (do not share):",TOKEN,flush=True)
    ThreadingHTTPServer(("0.0.0.0",PORT),Handler).serve_forever()
