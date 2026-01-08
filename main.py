from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import zipfile
import uuid
import os
import subprocess

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSIONS_DIR = os.path.join(BASE_DIR, "sessions")
CFR_JAR = os.path.join(BASE_DIR, "cfr-0.152.jar")

os.makedirs(SESSIONS_DIR, exist_ok=True)

# =========================
# UTILIDADES
# =========================

def build_tree(file_list):
    tree = {}
    for path in file_list:
        parts = path.split("/")
        cur = tree
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = None
    return tree


def decompile_class(class_path):
    try:
        result = subprocess.run(
            [
                "java",
                "-jar",
                CFR_JAR,
                class_path,
                "--stdout",
                "true",
                "--recover",
                "true",
                "--silent",
                "false"
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if result.stdout.strip():
            return result.stdout

        if result.stderr.strip():
            return "// CFR STDERR\n" + result.stderr

        return "// CFR NO DEVOLVIÓ NADA\n// El .class puede estar ofuscado o incompleto"

    except Exception as e:
        return f"// ERROR EJECUTANDO CFR\n{e}"


# =========================
# FRONTEND
# =========================

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def index():
    return FileResponse("static/index.html")


# =========================
# SUBIR JAR
# =========================

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    session_id = str(uuid.uuid4())
    session_path = os.path.join(SESSIONS_DIR, session_id)
    os.makedirs(session_path, exist_ok=True)

    jar_path = os.path.join(session_path, file.filename)

    with open(jar_path, "wb") as f:
        f.write(await file.read())

    with zipfile.ZipFile(jar_path, "r") as jar:
        jar.extractall(session_path)
        files = [f for f in jar.namelist() if not f.endswith("/")]

    return {
        "session_id": session_id,
        "tree": build_tree(files)
    }


# =========================
# LEER ARCHIVOS
# =========================

@app.get("/file/{session_id}/{path:path}")
def get_file(session_id: str, path: str):
    base = os.path.join(SESSIONS_DIR, session_id)
    real_path = os.path.join(base, path)

    if not os.path.isfile(real_path):
        return JSONResponse(
            {"content": "// Archivo no encontrado", "type": "text", "editable": False},
            status_code=404
        )

    # -------- .CLASS --------
    if path.endswith(".class"):
        return {
            "content": decompile_class(real_path),
            "type": "java",
            "editable": False
        }

    # -------- TEXTO --------
    try:
        with open(real_path, "rb") as f:
           content = f.read().decode("utf-8", errors="replace")

        file_type = "yaml" if path.endswith((".yml", ".yaml")) else "text"

        return {
            "content": content,
            "type": file_type,
            "editable": True
        }

    except Exception as e:
        return {
            "content": f"// Error leyendo archivo\n{e}",
            "type": "text",
            "editable": False
        }
