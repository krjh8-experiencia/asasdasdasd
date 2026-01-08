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

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Servir frontend
app.mount("/static", StaticFiles(directory="static"), name="static")

# Sesiones en memoria
sessions: Dict[str, str] = {}

# Decompilador CFR (asegurate de tener cfrig-0.152.jar en la raíz)
CFR_JAR = "cfr-0.152.jar"

# Construye el árbol de archivos
def build_file_tree(directory: str) -> Dict:
    tree = {}
    for root, dirs, files in os.walk(directory):
        current = tree
        rel_path = os.path.relpath(root, directory)
        if rel_path != '.':
            parts = rel_path.split(os.sep)
            for part in parts:
                current = current.setdefault(part, {})
        for file in files:
            current[file] = None
    return tree

# Ruta segura (evita path traversal y maneja / correctamente en Linux)
def safe_join(base: str, path: str) -> str:
    base = os.path.abspath(base)
    full = os.path.abspath(os.path.join(base, *path.split('/')))
    if not full.startswith(base):
        raise ValueError("Invalid path - traversal attempt")
    return full

@app.get("/")
async def root():
    return FileResponse("static/index.html")

@app.post("/upload")
async def upload_jar(file: UploadFile = File(...)):
    if not file.filename.lower().endswith('.jar'):
        raise HTTPException(status_code=400, detail="Debe ser un archivo .jar")

    session_id = str(uuid.uuid4())
    temp_dir = tempfile.mkdtemp()
    sessions[session_id] = temp_dir

    jar_path = os.path.join(temp_dir, "original.jar")
    with open(jar_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    extracted_dir = os.path.join(temp_dir, "extracted")
    os.makedirs(extracted_dir)
    with zipfile.ZipFile(jar_path, 'r') as zip_ref:
        zip_ref.extractall(extracted_dir)

    tree = build_file_tree(extracted_dir)
    return {"session_id": session_id, "tree": tree}

@app.get("/file/{session_id}/{path:path}")
async def get_file(session_id: str, path: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    extracted_dir = os.path.join(sessions[session_id], "extracted")

    try:
        full_path = safe_join(extracted_dir, path)
    except:
        raise HTTPException(status_code=400, detail="Ruta inválida")

    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    ext = os.path.splitext(path)[1].lower()

    # Archivos de texto editables (.yml, .yaml, .txt, .json, etc.)
    if ext in {'.yml', '.yaml', '.txt', '.json', '.properties', '.cfg', '.conf'}:
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return {"content": content, "type": "yaml" if ext in {'.yml', '.yaml'} else "text", "editable": True}
        except Exception as e:
            return {"content": f"// Error leyendo archivo:\n// {str(e)}", "type": "text", "editable": False}

    # .class → decompilar con CFR
    elif ext == '.class':
        decomp_dir = os.path.join(sessions[session_id], "decompiled")
        os.makedirs(decomp_dir, exist_ok=True)

        java_rel_path = os.path.splitext(path)[0] + '.java'
        java_full_path = safe_join(decomp_dir, java_rel_path)
        os.makedirs(os.path.dirname(java_full_path), exist_ok=True)  # Crea carpetas del paquete

        try:
            result = subprocess.run(
                ["java", "-jar", CFR_JAR, full_path, "--outputdir", decomp_dir],
                capture_output=True, text=True, timeout=30
            )

            if result.returncode != 0:
                raise Exception(f"CFR error: {result.stderr or result.stdout}")

            if not os.path.exists(java_full_path):
                raise Exception(f"Archivo Java no generado. CFR dijo: {result.stdout or result.stderr or 'sin salida'}")

            with open(java_full_path, 'r', encoding='utf-8') as f:
                content = f.read()

            return {"content": content, "type": "java", "editable": True}

        except subprocess.TimeoutExpired:
            error = "Decompilación tardó demasiado (>30s)"
        except Exception as e:
            error = str(e)

        fallback = f"// ERROR AL DESCOMPILAR {path}\n// {error}\n// Posibles causas: plugin ofuscado, versión Java incompatible o clase corrupta."
        return {"content": fallback, "type": "java", "editable": True}

    else:
        return {"content": "[Archivo binario o no soportado - solo lectura]", "type": "text", "editable": False}

@app.post("/save/{session_id}/{path:path}")
async def save_file(session_id: str, path: str, request: Request):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    data = await request.json()
    content = data.get("content")
    if content is None:
        raise HTTPException(status_code=400, detail="Falta contenido")

    extracted_dir = os.path.join(sessions[session_id], "extracted")
    full_path = safe_join(extracted_dir, path)
    ext = os.path.splitext(path)[1].lower()

    if ext in {'.yml', '.yaml', '.txt', '.json', '.properties', '.cfg', '.conf'}:
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return {"message": "Guardado correctamente"}

    elif ext == '.class':
        java_rel_path = os.path.splitext(path)[0] + '.java'
        temp_dir = os.path.join(sessions[session_id], "temp")
        os.makedirs(temp_dir, exist_ok=True)
        temp_java_path = safe_join(temp_dir, java_rel_path)
        os.makedirs(os.path.dirname(temp_java_path), exist_ok=True)

        with open(temp_java_path, 'w', encoding='utf-8') as f:
            f.write(content)

        try:
            subprocess.check_call(["javac", temp_java_path])
            new_class_path = os.path.splitext(temp_java_path)[0] + '.class'
            if os.path.exists(new_class_path):
                shutil.move(new_class_path, full_path)
                return {"message": "Compilado y guardado correctamente"}
            else:
                raise Exception("No se generó el .class compilado")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error al compilar: {str(e)}")

    else:
        raise HTTPException(status_code=400, detail="Tipo de archivo no editable")

@app.get("/download/{session_id}")
async def download_modified(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    temp_dir = sessions[session_id]
    extracted_dir = os.path.join(temp_dir, "extracted")
    modified_jar = os.path.join(temp_dir, "modified.jar")

    shutil.make_archive(modified_jar[:-4], 'zip', extracted_dir)
    os.rename(modified_jar[:-4] + '.zip', modified_jar)

    return FileResponse(modified_jar, filename="modified.jar", media_type="application/java-archive")
