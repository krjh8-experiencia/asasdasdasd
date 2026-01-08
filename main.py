from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
import zipfile, os, uuid, subprocess, shutil

app = FastAPI()

TEMP = "temp"
VINE = "vineflower-1.11.2.jar"   # o fernflower.jar
CFR = "cfr-0.152.jar"

TEXT_EXT = (
    ".yml", ".yaml", ".txt", ".json",
    ".xml", ".properties", ".mf"
)

os.makedirs(TEMP, exist_ok=True)

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    if not file.filename.endswith(".jar"):
        raise HTTPException(400, "Solo archivos .jar")

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
    with zipfile.ZipFile(jar_path, "r") as jar:
        jar.extractall(extract_dir)

    subprocess.run(
        ["java", "-jar", VINE, extract_dir, java_dir],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    results = {}

    for root, _, files in os.walk(java_dir):
        for name in files:
            if name.endswith(".java"):
                path = os.path.join(root, name)
                rel = os.path.relpath(path, java_dir)
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    results[rel] = f.read()

    for root, _, files in os.walk(extract_dir):
        for name in files:
            if name.endswith(".class"):
                rel = os.path.relpath(os.path.join(root, name), extract_dir)
                java_name = rel.replace(".class", ".java")

                if java_name in results:
                    continue

                try:
                    out = subprocess.run(
                        ["java", "-jar", CFR, os.path.join(root, name)],
                        capture_output=True,
                        text=True,
                        timeout=20
                    )
                    if out.stdout.strip():
                        results[java_name] = out.stdout
                except:
                    pass

    for root, _, files in os.walk(extract_dir):
        for name in files:
            if name.lower().endswith(TEXT_EXT):
                path = os.path.join(root, name)
                rel = os.path.relpath(path, extract_dir)
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    results[rel] = f.read()

    return JSONResponse({
        "files": results,
        "total": len(results)
    })
