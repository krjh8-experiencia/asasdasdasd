from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import zipfile, os, uuid, subprocess, shutil

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

TEMP = "temp"
VINE = "vineflower-1.11.2.jar"

TEXT_EXT = (".yml", ".yaml", ".json", ".txt", ".properties", ".xml", ".mf")

os.makedirs(TEMP, exist_ok=True)
SESSIONS = {}  # sid -> dict


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
    decomp_dir = f"{base}_java"

    os.makedirs(extract_dir)
    os.makedirs(decomp_dir)

    with open(jar_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    with zipfile.ZipFile(jar_path) as jar:
        jar.extractall(extract_dir)

    # decompilar TODOS los .class
    subprocess.run(
        ["java", "-jar", VINE, extract_dir, decomp_dir],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    SESSIONS[sid] = {
        "ext": extract_dir,
        "java": decomp_dir
    }

    return {"session": sid}


# ================= TREE =================
@app.get("/tree/{sid}")
def tree(sid: str):
    if sid not in SESSIONS:
        raise HTTPException(404)

    ext = SESSIONS[sid]["ext"]
    files = []

    for root, _, fs in os.walk(ext):
        rel = root.replace(ext, "").lstrip("/")
        for f in fs:
            full = os.path.join(root, f)
            e = os.path.splitext(f)[1].lower()

            files.append({
                "path": f"{rel}/{f}".lstrip("/"),
                "editable": e in TEXT_EXT,
                "type": "class" if e == ".class" else "text"
            })

    return files


# ================= READ =================
@app.get("/read/{sid}")
def read_file(
    sid: str,
    path: str = Query(...)
):
    if sid not in SESSIONS:
        raise HTTPException(404)

    ext_dir = SESSIONS[sid]["ext"]
    java_dir = SESSIONS[sid]["java"]

    full = os.path.join(ext_dir, path)

    if not os.path.isfile(full):
        raise HTTPException(404)

    ext = os.path.splitext(path)[1].lower()

    # TEXT FILES (YML ETC)
    if ext in TEXT_EXT:
        with open(full, "r", encoding="utf-8", errors="ignore") as f:
            return {
                "content": f.read(),
                "editable": True
            }

    # CLASS → JAVA DECOMPILADO
    if ext == ".class":
        java_path = os.path.splitext(path)[0] + ".java"
        java_full = os.path.join(java_dir, java_path)

        if os.path.exists(java_full):
            with open(java_full, "r", encoding="utf-8", errors="ignore") as f:
                return {
                    "content": f.read(),
                    "editable": False
                }

        return {
            "content": "// No se pudo decompilar esta clase",
            "editable": False
        }

    return {
        "content": "// Archivo binario",
        "editable": False
    }


# ================= SAVE =================
@app.post("/save/{sid}")
def save(
    sid: str,
    path: str = Query(...),
    body: dict = None
):
    if sid not in SESSIONS:
        raise HTTPException(404)

    full = os.path.join(SESSIONS[sid]["ext"], path)

    if not full.endswith(TEXT_EXT):
        raise HTTPException(400, "No editable")

    with open(full, "w", encoding="utf-8") as f:
        f.write(body["content"])

    return {"ok": True}


# ================= DOWNLOAD =================
@app.get("/download/{sid}")
def download(sid: str):
    if sid not in SESSIONS:
        raise HTTPException(404)

    base = SESSIONS[sid]["ext"]
    out = f"{TEMP}/{sid}_MOD.jar"

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as jar:
        for root, _, files in os.walk(base):
            for f in files:
                full = os.path.join(root, f)
                jar.write(full, arcname=full.replace(base + "/", ""))

    return FileResponse(out, filename="plugin_modificado.jar")
