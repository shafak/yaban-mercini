import asyncio
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse, Connect
from src.handlers.twilio_ws import handle_media_stream
from src.handlers.netgsm_handler import router as netgsm_router
from src.database.mysql_manager import db_manager
from pydantic import BaseModel, EmailStr
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# Include the new FreeSWITCH WebSocket router
app.include_router(netgsm_router)

@app.on_event("startup")
async def startup():
    await db_manager.init_db()

    # Start our internal SIP AI Endpoint on port 5062
    try:
        from src.handlers.sip_ai_endpoint import start_sip_ai
        start_sip_ai()
        print("SIP AI Endpoint started on port 5062")
    except Exception as e:
        print(f"WARNING: Could not start SIP AI Endpoint: {e}")

    print("FastAPI server started with FreeSWITCH integration")

class LeadRequest(BaseModel):
    full_name: str
    company: str
    phone: str
    email: EmailStr

class CallRequest(BaseModel):
    phone_number: str

@app.post("/api/leads")
async def create_lead(lead: LeadRequest):
    try:
        await db_manager.create_lead(
            lead.full_name, 
            lead.company, 
            lead.phone, 
            lead.email
        )
        return {"status": "success", "message": "Başvurunuz başarıyla alındı."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/calls")
async def make_call(req: CallRequest):
    provider = os.getenv("TELEPHONY_PROVIDER", "netgsm")
    
    if provider == "twilio":
        from twilio.rest import Client
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        from_number = os.getenv("TWILIO_PHONE_NUMBER")
        
        host = os.getenv("PUBLIC_URL") 
        if not host:
             return {"status": "error", "message": "PUBLIC_URL not set in .env"}
             
        client = Client(account_sid, auth_token)
        call = client.calls.create(
            to=req.phone_number,
            from_=from_number,
            url=f"{host}/voice"
        )
        return {"status": "calling", "provider": "twilio", "call_sid": call.sid}
    else:
        # Netgsm / FreeSWITCH Native Bridge
        import socket as _socket
        try:
            fs_host = os.getenv("FS_HOST", "172.18.0.1")
            fs_port = int(os.getenv("FS_PORT", "8021"))
            fs_pass = os.getenv("FS_PASS", "ClueCon")
            
            # Docker container internal IP as seen by host FreeSWITCH
            esl_handler_host = os.getenv("ESL_HANDLER_HOST", "127.0.0.1")

            clean_number = req.phone_number.strip().replace("+", "").replace(" ", "")
            if len(clean_number) == 10 and clean_number.startswith("5"):
                clean_number = "90" + clean_number
            elif len(clean_number) == 11 and clean_number.startswith("0"):
                clean_number = "9" + clean_number

            with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
                s.settimeout(5)
                s.connect((fs_host, fs_port))
                s.recv(1024)  # auth/request
                
                s.sendall(f"auth {fs_pass}\n\n".encode())
                auth_resp = s.recv(1024).decode()
                if "+OK accepted" not in auth_resp:
                    return {"status": "error", "message": "FreeSWITCH auth failed"}

                # Originate call to Netgsm, when answered, bridge to our local SIP AI endpoint on port 5062
                originate_cmd = (
                    f"bgapi originate {{"
                    f"originate_caller_id_number=8503074343,"
                    f"originate_caller_id_name=YabanMercini,"
                    f"originate_timeout=60"
                    f"}}sofia/gateway/netgsm/{clean_number} "
                    f"&bridge(sofia/external/ai@{esl_handler_host}:5062)\n\n"
                )
                
                s.sendall(originate_cmd.encode())
                import asyncio
                await asyncio.sleep(0.1) # Wait briefly so FreeSWITCH queues it
                
                logger = __import__('logging').getLogger(__name__)
                logger.info(f"[Outbound] originate bridge command sent for {clean_number}")

            return {
                "status": "calling",
                "provider": "netgsm",
                "to": clean_number
            }
        except Exception as e:
            return {"status": "error", "message": f"FreeSWITCH ESL error: {e}"}

@app.post("/voice")
async def voice(request: Request):
    provider = os.getenv("TELEPHONY_PROVIDER", "netgsm")
    
    if provider == "twilio":
        form_data = await request.form()
        from_number = form_data.get("From", "Unknown")
        print(f"Incoming Twilio call from {from_number}")
        host = request.headers.get("host")
        vr = VoiceResponse()
        c = Connect()
        s = c.stream(url=f"wss://{host}/media")
        s.parameter(name="from", value=from_number)
        vr.append(c)
        return Response(str(vr), media_type="text/xml")
    else:
        # For Netgsm/Asterisk, the call is already handled by Asterisk
        # This endpoint might be used for callbacks or status updates in the future
        return {"status": "ok", "provider": "netgsm"}

@app.websocket("/media")
async def media(ws: WebSocket):
    await handle_media_stream(ws)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
