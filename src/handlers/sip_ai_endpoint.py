import socket
import threading
import time
import json
import uuid
import re
import os
import asyncio
import websockets
import ssl
import certifi
import base64
import audioop

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
LOCAL_SIP_PORT = 5062
RTP_PORT_START = 10000

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

MY_IP = get_local_ip()

def parse_sdp_rtp(sdp):
    remote_ip = None
    remote_port = None
    for line in sdp.splitlines():
        line = line.strip()
        if line.startswith("c=IN IP4 "):
            remote_ip = line.split("c=IN IP4 ")[1].strip()
        elif line.startswith("m=audio "):
            pts = line.split()
            if len(pts) >= 2:
                try:
                    remote_port = int(pts[1])
                except ValueError:
                    pass
    return remote_ip, remote_port

class SIPAIEndpoint:
    def __init__(self):
        self.sip_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sip_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sip_sock.bind(("0.0.0.0", LOCAL_SIP_PORT))
        self.sip_sock.settimeout(0.5)
        self.running = True
        self.active_calls = {}

    def start(self):
        threading.Thread(target=self.sip_loop, daemon=True).start()
        print(f"[SIP AI] Listening for FreeSWITCH INVITEs on 0.0.0.0:{LOCAL_SIP_PORT}")

    def sip_loop(self):
        while self.running:
            try:
                data, addr = self.sip_sock.recvfrom(4096)
                msg = data.decode(errors='ignore')
                first = msg.split("\r\n")[0]
                
                if first.startswith("INVITE"):
                    self.handle_invite(msg, addr)
                elif first.startswith("ACK"):
                    print(f"[SIP AI] Received ACK from {addr[0]}")
                elif first.startswith("BYE"):
                    self.handle_bye(msg, addr)
                
            except socket.timeout:
                continue
            except Exception as e:
                print(f"[SIP AI] Recv Error: {e}")

    def handle_invite(self, msg, addr):
        print(f"[SIP AI] Incoming INVITE from {addr[0]}")
        
        call_id = ""
        cseq = ""
        from_header = ""
        to_header = ""
        via = ""
        
        for line in msg.split("\r\n"):
            ll = line.lower()
            if ll.startswith("call-id:"): call_id = line.split(":", 1)[1].strip()
            if ll.startswith("cseq:"): cseq = line.split(":", 1)[1].strip()
            if ll.startswith("from:"): from_header = line.split(":", 1)[1].strip()
            if ll.startswith("to:"): to_header = line.split(":", 1)[1].strip()
            if ll.startswith("via:"): via = line.split(":", 1)[1].strip()

        parts = msg.split("\r\n\r\n", 1)
        sdp = parts[1] if len(parts) > 1 else ""
        fs_ip, fs_rtp_port = parse_sdp_rtp(sdp)
        if not fs_ip or not fs_rtp_port:
            print("[SIP AI] Could not parse RTP info from FreeSWITCH SDP")
            return
            
        print(f"[SIP AI] FreeSWITCH RTP at {fs_ip}:{fs_rtp_port}")
        
        # Add to_tag
        to_tag = uuid.uuid4().hex[:8]
        to_header = f"{to_header};tag={to_tag}"
        
        # Allocate local RTP port
        local_rtp_port = RTP_PORT_START + len(self.active_calls) * 2
        
        # Build 200 OK
        sdp_ans = (
            "v=0\r\n"
            f"o=- 0 0 IN IP4 {MY_IP}\r\n"
            "s=ai_call\r\n"
            f"c=IN IP4 {MY_IP}\r\n"
            "t=0 0\r\n"
            f"m=audio {local_rtp_port} RTP/AVP 0 101\r\n"
            "a=rtpmap:0 PCMU/8000\r\n"
            "a=rtpmap:101 telephone-event/8000\r\n"
            "a=sendrecv\r\n"
        )
        
        ok = (
            "SIP/2.0 200 OK\r\n"
            f"Via: {via}\r\n"
            f"From: {from_header}\r\n"
            f"To: {to_header}\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: {cseq}\r\n"
            f"Contact: <sip:ai@{MY_IP}:{LOCAL_SIP_PORT}>\r\n"
            "Content-Type: application/sdp\r\n"
            f"Content-Length: {len(sdp_ans)}\r\n\r\n"
            f"{sdp_ans}"
        )
        
        self.sip_sock.sendto(ok.encode(), addr)
        print(f"[SIP AI] Replied 200 OK. Starting AI RTP bridge on port {local_rtp_port}")
        
        # Start AI RTP Bridge
        self.start_ai_rtp(call_id, local_rtp_port, fs_ip, fs_rtp_port)

    def handle_bye(self, msg, addr):
        call_id = ""
        cseq = ""
        from_header = ""
        to_header = ""
        via = ""
        for line in msg.split("\r\n"):
            ll = line.lower()
            if ll.startswith("call-id:"): call_id = line.split(":", 1)[1].strip()
            if ll.startswith("cseq:"): cseq = line.split(":", 1)[1].strip()
            if ll.startswith("from:"): from_header = line.split(":", 1)[1].strip()
            if ll.startswith("to:"): to_header = line.split(":", 1)[1].strip()
            if ll.startswith("via:"): via = line.split(":", 1)[1].strip()

        ok = (
            "SIP/2.0 200 OK\r\n"
            f"Via: {via}\r\n"
            f"From: {from_header}\r\n"
            f"To: {to_header}\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: {cseq}\r\n"
            "Content-Length: 0\r\n\r\n"
        )
        self.sip_sock.sendto(ok.encode(), addr)
        
        # terminate call
        if call_id in self.active_calls:
            self.active_calls[call_id]['running'] = False
            del self.active_calls[call_id]
            print(f"[SIP AI] Call {call_id} ended by BYE.")

    def start_ai_rtp(self, call_id, local_port, remote_ip, remote_port):
        call_ctx = {'running': True}
        self.active_calls[call_id] = call_ctx
        
        rtp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        rtp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        rtp_sock.bind(("0.0.0.0", local_port))
        rtp_sock.settimeout(0.1)

        def rtp_to_ai_loop():
            # Send RTP to an asyncio queue
            asyncio.run(self.ai_loop(call_id, rtp_sock, remote_ip, remote_port, call_ctx))
            
        threading.Thread(target=rtp_to_ai_loop, daemon=True).start()

    async def ai_loop(self, call_id, rtp_sock, remote_ip, remote_port, call_ctx):
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        try:
            async with websockets.connect(
                "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01",
                additional_headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "OpenAI-Beta": "realtime=v1"
                },
                ssl=ssl_context
            ) as openai_ws:
                print(f"[SIP AI] Connected to OpenAI for {call_id}")
                
                # We use generic text instructions. 
                # (You can load from DB here like twilio_ws.py does)
                session_update = {
                    "type": "session.update",
                    "session": {
                        "instructions": "Sen yardımsever ve kısa konuşan bir asistansın. Her zaman Türkçe ve samimi yanıt ver.",
                        "input_audio_format": "g711_ulaw",
                        "output_audio_format": "g711_ulaw",
                        "voice": "alloy",
                        "turn_detection": {"type": "server_vad"}
                    }
                }
                await openai_ws.send(json.dumps(session_update))

                async def recv_from_rtp():
                    while call_ctx['running']:
                        try:
                            # Use asyncio to recv UDP so we don't block
                            loop = asyncio.get_running_loop()
                            pkt = await loop.run_in_executor(None, rtp_sock.recv, 4096)
                            if len(pkt) > 12:
                                pt = pkt[1] & 0x7F
                                # G711 ULAW is payload type 0
                                if pt == 0:
                                    payload = pkt[12:]
                                    b64 = base64.b64encode(payload).decode("utf-8")
                                    await openai_ws.send(json.dumps({
                                        "type": "input_audio_buffer.append",
                                        "audio": b64
                                    }))
                        except socket.timeout:
                            pass
                        except Exception as e:
                            print(f"[SIP AI] RTP Recv Err: {e}")
                            break

                async def recv_from_openai():
                    seq = 0
                    ts = 0
                    ssrc = 12345
                    while call_ctx['running']:
                        msg = await openai_ws.recv()
                        resp = json.loads(msg)
                        if resp["type"] == "response.audio.delta":
                            b64 = resp["delta"]
                            payload = base64.b64decode(b64)
                            
                            # Packetize into 160-byte chunks for FreeSWITCH bridging smoothly
                            chunk_size = 160
                            for i in range(0, len(payload), chunk_size):
                                chunk = payload[i:i+chunk_size]
                                seq = (seq + 1) & 0xFFFF
                                ts = (ts + len(chunk)) & 0xFFFFFFFF
                                rtp_hdr = bytes([
                                    0x80, 0x00, # ULAW PT=0
                                    (seq >> 8) & 0xFF, seq & 0xFF,
                                    (ts >> 24) & 0xFF, (ts >> 16) & 0xFF, (ts >> 8) & 0xFF, ts & 0xFF,
                                    (ssrc >> 24) & 0xFF, (ssrc >> 16) & 0xFF, (ssrc >> 8) & 0xFF, ssrc & 0xFF,
                                ])
                                rtp_sock.sendto(rtp_hdr + chunk, (remote_ip, remote_port))
                                await asyncio.sleep(0.015) # Send smoothly ~20ms
                        elif resp["type"] == "response.audio_transcript.done":
                            print(f"[SIP AI] AI: {resp.get('transcript')}")
                        elif resp["type"] == "conversation.item.input_audio_transcription.completed":
                            print(f"[SIP AI] USER: {resp.get('transcript')}")

                await asyncio.gather(recv_from_rtp(), recv_from_openai())

        except Exception as e:
            print(f"[SIP AI] Terminated session for {call_id}: {e}")
        finally:
            rtp_sock.close()
            call_ctx['running'] = False

endpoint = SIPAIEndpoint()

def start_sip_ai():
    endpoint.start()
