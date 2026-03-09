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

    # Start FreeSWITCH ESL outbound socket server on port 8084
    # FreeSWITCH routes inbound calls here via: socket 127.0.0.1:8084 async full
    try:
        from src.handlers.freeswitch_handler import start_esl_server
        asyncio.create_task(start_esl_server(host="0.0.0.0", port=8084))
        print("FreeSWITCH ESL outbound server started on port 8084")
    except Exception as esl_err:
        print(f"WARNING: Could not start ESL server: {esl_err}")

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
        # Netgsm / FreeSWITCH ESL Originate
        import socket as _socket
        try:
            fs_host = os.getenv("FS_HOST", "172.18.0.1")
            fs_port = int(os.getenv("FS_PORT", "8021"))
            fs_pass = os.getenv("FS_PASS", "ClueCon")
            esl_handler_host = os.getenv("ESL_HANDLER_HOST", "127.0.0.1")

            # Normalize phone number to E.164 Turkish format
            clean_number = req.phone_number.strip().replace("+", "").replace(" ", "")
            if len(clean_number) == 10 and clean_number.startswith("5"):
                clean_number = "90" + clean_number
            elif len(clean_number) == 11 and clean_number.startswith("0"):
                clean_number = "9" + clean_number

            def _run_esl_call():
                """Runs in a thread: originate call, wait for CHANNEL_ANSWER, then connect socket."""
                import socket as _tsock, time, logging as _log
                log = _log.getLogger("outbound_esl")
                try:
                    conn = _tsock.socket(_tsock.AF_INET, _tsock.SOCK_STREAM)
                    conn.settimeout(10)
                    conn.connect((fs_host, fs_port))
                    conn.recv(1024)  # auth/request
                    conn.sendall(f"auth {fs_pass}\n\n".encode())
                    if "+OK accepted" not in conn.recv(1024).decode():
                        log.error("ESL auth failed")
                        return

                    # Subscribe to CHANNEL_ANSWER events
                    conn.sendall(b"event plain CHANNEL_ANSWER CHANNEL_HANGUP\n\n")
                    conn.recv(1024)  # +OK

                    # Originate: dial via Netgsm, park until answered
                    cmd = (
                        f"bgapi originate {{"
                        f"originate_caller_id_number=8503074343,"
                        f"originate_caller_id_name=YabanMercini,"
                        f"originate_timeout=60"
                        f"}}sofia/gateway/netgsm/{clean_number} "
                        f"&park()\n\n"
                    )
                    conn.sendall(cmd.encode())
                    time.sleep(0.2)
                    resp = conn.recv(2048).decode(errors="replace")
                    log.info(f"[Outbound] originate: {resp.strip()[:80]}")

                    # Wait for CHANNEL_ANSWER (up to 90 seconds = ring timeout)
                    conn.settimeout(90)
                    buf = ""
                    call_uuid = ""
                    while True:
                        chunk = conn.recv(4096).decode(errors="replace")
                        if not chunk:
                            break
                        buf += chunk
                        # Parse event blocks
                        while "\n\n" in buf:
                            block, buf = buf.split("\n\n", 1)
                            headers = {}
                            for line in block.splitlines():
                                if ": " in line:
                                    k, v = line.split(": ", 1)
                                    headers[k.strip()] = v.strip()
                            event = headers.get("Event-Name", "")
                            uuid = headers.get("Unique-ID", "")
                            if event == "CHANNEL_ANSWER" and uuid:
                                call_uuid = uuid
                                log.info(f"[Outbound] Call answered! UUID={uuid}")
                                break
                            elif event == "CHANNEL_HANGUP":
                                log.info(f"[Outbound] Call hung up before answer UUID={uuid}")
                                conn.close()
                                return
                        if call_uuid:
                            break

                    if call_uuid:
                        # Connect the answered call to our ESL AI handler
                        conn.settimeout(5)
                        sendmsg = (
                            f"sendmsg {call_uuid}\n"
                            f"call-command: execute\n"
                            f"execute-app-name: socket\n"
                            f"execute-app-arg: {esl_handler_host}:8084 async full\n\n"
                        )
                        conn.sendall(sendmsg.encode())
                        log.info(f"[Outbound] socket sendmsg sent for {call_uuid}")
                        time.sleep(1)

                    conn.close()
                except Exception as ex:
                    log.exception(f"[Outbound] ESL thread error: {ex}")

            # Run ESL call management in a background thread
            import threading
            t = threading.Thread(target=_run_esl_call, daemon=True)
            t.start()

            return {
                "status": "calling",
                "provider": "netgsm",
                "to": clean_number,
            }
        except Exception as e:
            return {"status": "error", "message": f"FreeSWITCH ESL error: {e}"}

            with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
                s.settimeout(8)
                s.connect((fs_host, fs_port))
                
                # FreeSWITCH sends auth/request on connect
                s.recv(1024)
                
                # Authenticate
                s.sendall(f"auth {fs_pass}\n\n".encode())
                auth_resp = s.recv(1024).decode()
                if "Reply-Text: +OK accepted" not in auth_resp:
                    return {"status": "error", "message": f"FreeSWITCH auth failed: {auth_resp.strip()}"}

                # Normalize phone number to E.164 Turkish format
                clean_number = req.phone_number.strip().replace("+", "").replace(" ", "")
                if len(clean_number) == 10 and clean_number.startswith("5"):
                    clean_number = "90" + clean_number
                elif len(clean_number) == 11 and clean_number.startswith("0"):
                    clean_number = "9" + clean_number
                
                # originate: dial via Netgsm gateway, then connect answered call to our
                # Python ESL AI handler running on port 8084 inside the FastAPI container.
                # FreeSWITCH is on host → ESL handler is in Docker container.
                # The container's host-facing IP is the Docker default bridge gateway.
                esl_handler_host = os.getenv("ESL_HANDLER_HOST", "127.0.0.1")
                originate_cmd = (
                    f"bgapi originate {{"
                    f"originate_caller_id_number=8503074343,"
                    f"originate_caller_id_name=YabanMercini,"
                    # ignore_early_media: don't wait for SDP before dialing
                    # socket app runs after connect, answer happens in ESL handler
                    f"ignore_early_media=true,"
                    f"originate_timeout=60"
                    f"}}sofia/gateway/netgsm/{clean_number} "
                    f"&socket({esl_handler_host}:8084 async full)\n\n"
                )
                
                s.sendall(originate_cmd.encode())
                
                import asyncio as _asyncio
                await _asyncio.sleep(0.2)  # let FreeSWITCH queue the originate
                orig_resp = s.recv(2048).decode(errors="replace")
                
                logger = __import__('logging').getLogger(__name__)
                logger.info(f"[Outbound] originate response: {orig_resp.strip()}")
                
                return {
                    "status": "calling",
                    "provider": "netgsm",
                    "to": clean_number,
                    "fs_response": orig_resp.strip()
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
