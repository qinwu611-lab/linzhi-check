import os
import json
from flask import Flask, request, jsonify, send_file
from datetime import datetime

app = Flask(__name__)

BASE_DIR = os.path.join(os.path.dirname(__file__), "managed_files")
os.makedirs(BASE_DIR, exist_ok=True)

@app.route("/ping")
def ping():
    return "pong"

@app.route("/files", methods=["GET"])
def list_files():
    files = []
    for f in os.listdir(BASE_DIR):
        fp = os.path.join(BASE_DIR, f)
        if os.path.isfile(fp):
            files.append({
                "name": f,
                "size": os.path.getsize(fp),
                "modified": datetime.fromtimestamp(os.path.getmtime(fp)).isoformat()
            })
    return jsonify(files)

@app.route("/files/<path:filename>", methods=["GET"])
def read_file(filename):
    fp = os.path.join(BASE_DIR, filename)
    if not os.path.exists(fp):
        return jsonify({"error": "not found"}), 404
    return send_file(fp)

@app.route("/files/<path:filename>", methods=["POST"])
def write_file(filename):
    data = request.get_data(as_text=True)
    fp = os.path.join(BASE_DIR, filename)
    with open(fp, "w", encoding="utf-8") as f:
        f.write(data)
    return jsonify({"status": "ok", "path": fp})

@app.route("/files/<path:filename>", methods=["DELETE"])
def delete_file(filename):
    fp = os.path.join(BASE_DIR, filename)
    if os.path.exists(fp):
        os.remove(fp)
    return jsonify({"status": "deleted"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
