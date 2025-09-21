# backend/live_ws.py
import json
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException, Header
from fastapi.responses import JSONResponse
import uvicorn
import os

app = FastAPI(title="Trading Live WS")

clients = set()

# use env var if set, fallback
API_TOKEN = os.getenv("DASHBOARD_API_TOKEN", "CHANGE_ME_TO_A_STRONG_TOKEN")

@app.websocket("/ws/dashboard")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    try:
        while True:
            # keep connection alive; front-end won't send, but this waits for pings or disconnects
            try:
                await ws.receive_text()
            except Exception:
                # ignore client-to-server messages; continue to wait
                await asyncio.sleep(1)
    except WebSocketDisconnect:
        clients.discard(ws)
    except Exception:
        clients.discard(ws)

async def broadcast(obj: dict):
    text = json.dumps(obj)
    dead = []
    for ws in list(clients):
        try:
            await ws.send_text(text)
        except Exception:
            dead.append(ws)
    for d in dead:
        clients.discard(d)

@app.post("/emit")
async def emit(request: Request, authorization: str = Header(None)):
    """
    POST JSON messages to this endpoint to forward them to connected dashboard clients.
    Header must include: Authorization: Bearer <API_TOKEN>
    """
    if authorization is None or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=403, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1]
    if token != API_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")

    body = await request.json()
    if not isinstance(body, dict) or "type" not in body or "payload" not in body:
        raise HTTPException(status_code=400, detail="Bad payload")

    # broadcast asynchronously
    await broadcast(body)
    return JSONResponse({"ok": True})

if __name__ == "__main__":
    uvicorn.run("live_ws:app", host="0.0.0.0", port=8000, reload=True)

