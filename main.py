from fastapi import FastAPI, UploadFile, File, Request, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import zipfile
import os
import subprocess
import tempfile
import shutil
import uuid
from typing import Dict

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

sessions: Dict[str, str] = {}

# ⚠️ Asegurate que ESTE archivo exista
CFR_JAR = "cfr-0.152.jar"


def build_file_tree(directory: str) -> Dict:
    tree = {}
    for root, _, files in os.walk(directory):
        current = tree
        rel = os.path.relpath(root, directory)
        if rel != ".":
            for part in rel.split(os.sep):
                current = current.setdefault(part, {})
        for f in files:
            current[f] = None
    return tree


def safe_join(base: str, path: str) -> str:
    base = os.path.abspath(base)
    full = os.path.abspath(os.path.join(base, *path.split("/")))
    if not full.startswith(base):
        raise ValueError("Ruta inválida")
    return full


@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.post("/upload")
async def upload_jar(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".jar"):
        raise HTTPException(400, "Debe ser .jar")

    session_id = str(uuid.uuid4())
    temp_dir = tempfile.mkdtemp()
    sessions[session_id] = temp_dir

    jar_path = os.path.join(temp_dir, "original.jar")
    with open(jar_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    extracted = os.path.join(temp_dir, "extracted")
    os.makedirs(extracted)

    with zipfile.ZipFile(jar_path, "r") as zipf:
        zipf.extractall(extracted)

    return {
        "session_id": session_id,
        "tree": build_file_tree(extracted)
    }


@app.get("/file/{session_id}/{path:path}")
async def get_file(session_id: str, path: str):
    if session_id not in sessions:
        raise HTTPException(404, "Sesión inválida")

    extracted_dir = os.path.join(sessions[session_id], "extracted")

    # 🔥 RUTA DIRECTA, SIN safe_join
    full_path = os.path.abspath(os.path.join(extracted_dir, path))

    print("DEBUG PATH:", full_path)

    if not full_path.startswith(os.path.abspath(extracted_dir)):
        raise HTTPException(400, "Ruta fuera del directorio")

    if not os.path.exists(full_path):
        raise HTTPException(404, "Archivo no encontrado")

    ext = os.path.splitext(path)[1].lower()

    # ---------- TEXTO ----------
    if ext in {".yml", ".yaml", ".txt", ".json", ".properties", ".cfg", ".conf", ".md"}:
        with open(full_path, "rb") as f:
            content = f.read().decode("utf-8", errors="replace")

        return {
            "content": content,
            "type": "yaml",
            "editable": True
        }

    # ---------- .CLASS ----------
    if ext == ".class":
        decomp_dir = os.path.join(sessions[session_id], "decompiled")
        os.makedirs(decomp_dir, exist_ok=True)

        cmd = ["java", "-jar", CFR_JAR, full_path, "--outputdir", decomp_dir]
        subprocess.run(cmd, capture_output=True)

        class_name = os.path.basename(path).replace(".class", ".java")
        java_file = None

        for root, _, files in os.walk(decomp_dir):
            if class_name in files:
                java_file = os.path.join(root, class_name)
                break

        if not java_file:
            return {
                "content": "// CFR no pudo generar el .java",
                "type": "java",
                "editable": False
            }

        with open(java_file, "r", encoding="utf-8", errors="replace") as f:
            return {
                "content": f.read(),
                "type": "java",
                "editable": True
            }

    return {
        "content": "[Archivo binario]",
        "type": "text",
        "editable": False
    }


@app.post("/save/{session_id}/{path:path}")
async def save_file(session_id: str, path: str, request: Request):
    if session_id not in sessions:
        raise HTTPException(404, "Sesión inválida")

    data = await request.json()
    content = data.get("content")

    extracted = os.path.join(sessions[session_id], "extracted")
    full = safe_join(extracted, path)

    with open(full, "w", encoding="utf-8") as f:
        f.write(content)

    return {"message": "Guardado"}


@app.get("/download/{session_id}")
async def download(session_id: str):
    if session_id not in sessions:
        raise HTTPException(404, "Sesión inválida")

    base = sessions[session_id]
    extracted = os.path.join(base, "extracted")
    jar = os.path.join(base, "modified.jar")

    shutil.make_archive(jar.replace(".jar", ""), "zip", extracted)
    os.rename(jar.replace(".jar", "") + ".zip", jar)

    return FileResponse(jar, filename="modified.jar")
