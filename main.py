from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import zipfile, os, uuid, subprocess, shutil, json

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

TEMP = "temp"
VINE = "vineflower-1.11.2.jar"

TEXT_EXT = (".yml", ".yaml", ".txt", ".json", ".xml", ".properties", ".mf")

os.makedirs(TEMP, exist_ok=True)

SESSIONS = {}  # session_id -> extract_dir

@app.get("/", response_class=HTMLResponse)
def home():
    return FileResponse("static/index.html")


# ================= UPLOAD =================
@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    if not file.filename.endswith(".jar"):
        raise HTTPException(400, "Solo .jar")

    sid = str(uuid.uuid4())
    base = f"{TEMP}/{sid}"
    jar_path = f"{base}.jar"
    extract_dir = f"{base}_ext"

    os.makedirs(extract_dir)

    # streaming (NO RAM)
    with open(jar_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    with zipfile.ZipFile(jar_path) as jar:
        jar.extractall(extract_dir)

    SESSIONS[sid] = extract_dir

    return {"session": sid}


# ================= TREE =================
@app.get("/tree/{sid}")
def tree(sid: str):
    if sid not in SESSIONS:
        raise HTTPException(404)

    base = SESSIONS[sid]
    tree = []

    for root, dirs, files in os.walk(base):
        rel = root.replace(base, "").lstrip("/")
        for d in dirs:
            tree.append({"path": f"{rel}/{d}", "type": "dir"})
        for f in files:
            ext = os.path.splitext(f)[1]
            tree.append({
                "path": f"{rel}/{f}",
                "type": "file",
                "editable": ext in TEXT_EXT
            })

    return tree


# ================= READ =================
@app.get("/read/{sid}")
def read_file(sid: str, path: str):
    base = SESSIONS.get(sid)
    full = os.path.join(base, path)

    if not os.path.isfile(full):
        raise HTTPException(404)

    if not full.endswith(TEXT_EXT):
        return {"binary": True}

    with open(full, "r", encoding="utf-8", errors="ignore") as f:
        return {"content": f.read()}


# ================= SAVE =================
@app.post("/save/{sid}")
def save_file(sid: str, path: str, body: dict):
    base = SESSIONS.get(sid)
    full = os.path.join(base, path)

    if not full.endswith(TEXT_EXT):
        raise HTTPException(400, "No editable")

    with open(full, "w", encoding="utf-8") as f:
        f.write(body["content"])

    return {"ok": True}


# ================= DOWNLOAD =================
@app.get("/download/{sid}")
def download(sid: str):
    base = SESSIONS.get(sid)
    out = f"{TEMP}/{sid}_modified.jar"

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as jar:
        for root, _, files in os.walk(base):
            for f in files:
                full = os.path.join(root, f)
                jar.write(full, arcname=full.replace(base + "/", ""))

    return FileResponse(out, filename="plugin_modificado.jar")
