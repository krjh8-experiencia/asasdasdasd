from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import zipfile
import subprocess
import uuid
import os

# =====================
# CONFIG
# =====================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSIONS_DIR = os.path.join(BASE_DIR, "sessions")
CFR_JAR = os.path.join(BASE_DIR, "cfr-0.152.jar")

os.makedirs(SESSIONS_DIR, exist_ok=True)

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

# =====================
# UTILS
# =====================

def build_tree(files):
    tree = {}
    for path in files:
        cur = tree
        parts = path.split("/")
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = None
    return tree


def read_text_file(path):
    with open(path, "rb") as f:
        data = f.read()
    return data.decode("utf-8", errors="replace")


def decompile_class(class_path, jar_path):
    """
    CFR REAL:
    - usa el JAR como classpath
    - stdout forzado
    - nunca devuelve vacío
    """
    try:
        result = subprocess.run(
            [
                "java", "-jar", CFR_JAR,
                class_path,
                "--extraclasspath", jar_path,
                "--stdout", "true",
                "--recover", "true",
                "--silent", "false"
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60
        )

        if result.stdout.strip():
            return result.stdout

        if result.stderr.strip():
            return "// CFR ERROR\n" + result.stderr

        return "// CFR no devolvió salida.\n// Clase ofuscada o dependencias faltantes."

    except subprocess.TimeoutExpired:
        return "// ERROR: CFR tardó demasiado"
    except Exception as e:
        return f"// ERROR EJECUTANDO CFR\n{e}"


# =====================
# ROUTES
# =====================

@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    if not file.filename.endswith(".jar"):
        raise HTTPException(status_code=400, detail="Solo .jar")

    session_id = str(uuid.uuid4())
    session_dir = os.path.join(SESSIONS_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)

    jar_path = os.path.join(session_dir, file.filename)

    with open(jar_path, "wb") as f:
        f.write(await file.read())

    with zipfile.ZipFile(jar_path, "r") as jar:
        jar.extractall(session_dir)
        files = [f for f in jar.namelist() if not f.endswith("/")]

    return {
        "session_id": session_id,
        "tree": build_tree(files)
    }


@app.get("/file/{session_id}/{path:path}")
def get_file(session_id: str, path: str):
    base = os.path.join(SESSIONS_DIR, session_id)
    real_path = os.path.join(base, path)

    if not os.path.isfile(real_path):
        return JSONResponse(
            {"content": "// Archivo no encontrado", "type": "text", "editable": False},
            status_code=404
        )

    # localizar el JAR original
    jar_file = next(
        (f for f in os.listdir(base) if f.endswith(".jar")),
        None
    )
    jar_path = os.path.join(base, jar_file) if jar_file else None

    # ===== .CLASS =====
    if path.endswith(".class"):
        if not jar_path:
            return {
                "content": "// JAR original no encontrado",
                "type": "java",
                "editable": False
            }

        java_code = decompile_class(real_path, jar_path)
        return {
            "content": java_code,
            "type": "java",
            "editable": False
        }

    # ===== TEXTO (.yml, .java, etc) =====
    content = read_text_file(real_path)

    return {
        "content": content,
        "type": "yaml" if path.endswith((".yml", ".yaml")) else "text",
        "editable": True
    }
