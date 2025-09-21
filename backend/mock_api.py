from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_state = {"status": "stopped", "config": {"risk_pct": 0.5, "max_position_pct": 0.2}}

@app.get("/api/config")
def get_config():
    return _state["config"]

@app.post("/api/config")
def save_config(cfg: dict):
    _state["config"].update(cfg)
    return {"ok": True}

@app.post("/api/start")
def start():
    _state["status"] = "running"
    return {"status": "running"}

@app.post("/api/stop")
def stop():
    _state["status"] = "stopped"
    return {"status": "stopped"}
