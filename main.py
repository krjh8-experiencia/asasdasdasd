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
CFR_JAR = "cfr-0.152.jar"

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

@app.get("/")
async def root():
    return FileResponse("static/index.html")

@app.post("/upload")
async def upload_jar(file: UploadFile = File(...)):
    if not file.filename.lower().endswith('.jar'):
        raise HTTPException(status_code=400, detail="Must be a .jar file")
    
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

# FUNCIÓN AUXILIAR PARA RUTA SEGURA
def safe_join(base: str, path: str) -> str:
    base = os.path.abspath(base)
    full = os.path.abspath(os.path.join(base, *path.split('/')))
    if not full.startswith(base):
        raise ValueError("Attempted path traversal")
    return full

@app.get("/file/{session_id}/{path:path}")
async def get_file(session_id: str, path: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    extracted_dir = os.path.join(sessions[session_id], "extracted")
    
    try:
        full_path = safe_join(extracted_dir, path)
    except:
        raise HTTPException(status_code=400, detail="Invalid path")
    
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    ext = os.path.splitext(path)[1].lower()
    
    if ext in {'.yml', '.yaml'}:
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return {"content": content, "type": "yaml", "editable": True}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error reading file: {str(e)}")
    
    elif ext == '.class':
        decomp_dir = os.path.join(sessions[session_id], "decompiled")
        os.makedirs(decomp_dir, exist_ok=True)
        
        java_rel_path = os.path.splitext(path)[0] + '.java'
        java_full_path = safe_join(decomp_dir, java_rel_path)
        os.makedirs(os.path.dirname(java_full_path), exist_ok=True)
        
        try:
            subprocess.check_call(["java", "-jar", CFR_JAR, full_path, "--outputdir", decomp_dir])
            
            if os.path.exists(java_full_path):
                with open(java_full_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                return {"content": content, "type": "java", "editable": True}
            else:
                raise Exception("Decompiled Java file not generated")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Decompile failed: {str(e)}")
    
    else:
        return {"content": "[Not editable - binary or unsupported]", "type": "text", "editable": False}

@app.post("/save/{session_id}/{path:path}")
async def save_file(session_id: str, path: str, request: Request):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    data = await request.json()
    content = data.get("content")
    if content is None:
        raise HTTPException(status_code=400, detail="Missing content")
    
    extracted_dir = os.path.join(sessions[session_id], "extracted")
    full_path = safe_join(extracted_dir, path)
    
    ext = os.path.splitext(path)[1].lower()
    
    if ext in {'.yml', '.yaml'}:
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return {"message": "Saved successfully"}
    
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
                return {"message": "Compiled and saved successfully"}
            else:
                raise Exception("Compiled .class not generated")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Compile failed: {str(e)}")
    
    else:
        raise HTTPException(status_code=400, detail="File type not editable")

@app.get("/download/{session_id}")
async def download_modified(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    temp_dir = sessions[session_id]
    extracted_dir = os.path.join(temp_dir, "extracted")
    modified_jar = os.path.join(temp_dir, "modified.jar")
    
    shutil.make_archive(modified_jar[:-4], 'zip', extracted_dir)
    os.rename(modified_jar[:-4] + '.zip', modified_jar)
    
    return FileResponse(modified_jar, filename="modifiedkrjh8.jar", media_type="application/java-archive")
