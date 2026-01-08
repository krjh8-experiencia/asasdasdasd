from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import zipfile, os, uuid, subprocess, shutil

app = FastAPI()

# montar static/
app.mount("/static", StaticFiles(directory="static"), name="static")

TEMP = "temp"
CFR = "cfr-0.152.jar"
VINE = "vineflower-1.11.2.jar"

TEXT_EXT = (".yml", ".yaml", ".txt", ".json", ".xml", ".properties", ".mf")

os.makedirs(TEMP, exist_ok=True)

@app.get("/", response_class=HTMLResponse)
def home():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    if not file.filename.endswith(".jar"):
        raise HTTPException(400, "Solo archivos .jar")

    uid = str(uuid.uuid4())
    jar_path = f"{TEMP}/{uid}.jar"
    extract_dir = f"{TEMP}/{uid}_ext"
    out_java = f"{TEMP}/{uid}_java"

    os.makedirs(extract_dir)
    os.makedirs(out_java)

    with open(jar_path, "wb") as f:
        f.write(await file.read())

    # extraer jar
    with zipfile.ZipFile(jar_path) as jar:
        jar.extractall(extract_dir)

    results = {}

    # ejecutar Vineflower
    proc = subprocess.run(
        ["java", "-jar", VINE, extract_dir, out_java],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if proc.returncode != 0:
        raise HTTPException(500, proc.stderr)

    # leer .java
    for root, _, files in os.walk(out_java):
        for name in files:
            if name.endswith(".java"):
                path = os.path.join(root, name)
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    results[path.replace(out_java + "/", "")] = f.read()

    # leer archivos texto originales
    for root, _, files in os.walk(extract_dir):
        for name in files:
            if name.endswith(TEXT_EXT):
                path = os.path.join(root, name)
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    results[path.replace(extract_dir + "/", "")] = f.read()

    shutil.rmtree(extract_dir, ignore_errors=True)
    shutil.rmtree(out_java, ignore_errors=True)
    os.remove(jar_path)

    return JSONResponse(results)
