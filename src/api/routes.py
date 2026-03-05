from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse, Connect
from src.handlers.twilio_ws import handle_media_stream
from src.database.mysql_manager import db_manager
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

@app.on_event("startup")
async def startup():
    await db_manager.init_db()

@app.post("/voice")
async def voice(request: Request):
    form_data = await request.form()
    from_number = form_data.get("From", "Unknown")
    
    print(f"Incoming call from {from_number}")
    host = request.headers.get("host")
    
    vr = VoiceResponse()
    c = Connect()
    s = c.stream(url=f"wss://{host}/media")
    s.parameter(name="from", value=from_number)
    vr.append(c)
    
    return Response(str(vr), media_type="text/xml")

@app.websocket("/media")
async def media(ws: WebSocket):
    await handle_media_stream(ws)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
