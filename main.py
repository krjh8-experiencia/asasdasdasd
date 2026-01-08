from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import zipfile, os, uuid, subprocess

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

TEMP = "temp"
VINE = "vineflower-1.11.2.jar"
CFR = "cfr-0.152.jar"

TEXT_EXT = (
    ".yml", ".yaml", ".txt", ".json",
    ".xml", ".properties", ".mf"
)

FILES = {}  # cache global

os.makedirs(TEMP, exist_ok=True)

@app.get("/")
def home():
    return FileResponse("index.html")

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    global FILES
    FILES = {}

    if not file.filename.endswith(".jar"):
        raise HTTPException(400, "Solo .jar")

    uid = str(uuid.uuid4())
    base = os.path.join(TEMP, uid)
    jar_path = base + ".jar"
    extract_dir = base + "_extract"
    java_dir = base + "_java"

    os.makedirs(extract_dir, exist_ok=True)
    os.makedirs(java_dir, exist_ok=True)

    with open(jar_path, "wb") as f:
        f.write(await file.read())

    # Extraer JAR
    with zipfile.ZipFile(jar_path) as jar:
        jar.extractall(extract_dir)

    # 1️⃣ Vineflower
    subprocess.run(
        ["java", "-jar", VINE, extract_dir, java_dir],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    # Leer .java
    for root, _, files in os.walk(java_dir):
        for f in files:
            if f.endswith(".java"):
                p = os.path.join(root, f)
                rel = os.path.relpath(p, java_dir)
                FILES[rel] = open(p, "r", encoding="utf-8", errors="ignore").read()

    # 2️⃣ CFR fallback
    for root, _, files in os.walk(extract_dir):
        for f in files:
            if f.endswith(".class"):
                rel = os.path.relpath(os.path.join(root, f), extract_dir)
                java_name = rel.replace(".class", ".java")
                if java_name in FILES:
                    continue

                out = subprocess.run(
                    ["java", "-jar", CFR, os.path.join(root, f)],
                    capture_output=True,
                    text=True
                )
                if out.stdout.strip():
                    FILES[java_name] = out.stdout

    # 3️⃣ Archivos de texto
    for root, _, files in os.walk(extract_dir):
        for f in files:
            if f.lower().endswith(TEXT_EXT):
                p = os.path.join(root, f)
                rel = os.path.relpath(p, extract_dir)
                FILES[rel] = open(p, "r", encoding="utf-8", errors="ignore").read()

    return {
        "files": list(FILES.keys())
    }

@app.get("/file/{path:path}")
def get_file(path: str):
    if path not in FILES:
        raise HTTPException(404, "Archivo no encontrado")
    return {"content": FILES[path]}
