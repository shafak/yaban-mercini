import json
import asyncio
import websockets
import ssl
import certifi
import os
from fastapi import WebSocket
from src.personality.prompt_templates import get_personalized_prompt
from src.core.tools import get_openai_tools, handle_hang_up, handle_send_sms
from src.database.mysql_manager import db_manager

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

PHONE_LIST = {
    "+905511098751": {
        "ad_soyad": "Şafak Bey",
        "ilce": "Beşiktaş",
        "durak_adi": "Merkez Taksi",
        "plaka": "34 ABC 123",
        "basvuru_tarihi": "01.03.2026"
    }
}

async def handle_media_stream(ws: WebSocket):
    await ws.accept()
    print("Twilio WS connected")

    stream_sid = None
    call_sid = None
    phone_number = "Unknown"
    call_id = None
    transcript = []
    call_result = "Pending"

    ssl_context = ssl.create_default_context(cafile=certifi.where())

    async with websockets.connect(
        "wss://api.openai.com/v1/realtime?model=gpt-4o-mini-realtime-preview",
        additional_headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "OpenAI-Beta": "realtime=v1"
        },
        ssl=ssl_context
    ) as openai_ws:
        print("Connected to OpenAI Realtime API")
        
        session_update = {
            "type": "session.update",
            "session": {
                "instructions": "Initial connection",
                "input_audio_format": "g711_ulaw",
                "output_audio_format": "g711_ulaw",
                "voice": "alloy",
                "turn_detection": {"type": "server_vad"},
                "tools": get_openai_tools(),
                "input_audio_transcription": {"model": "whisper-1"}
            }
        }
        await openai_ws.send(json.dumps(session_update))

        async def receive_from_twilio():
            nonlocal stream_sid, call_sid, phone_number, call_id
            try:
                while True:
                    msg = await ws.receive_text()
                    data = json.loads(msg)
                    if data["event"] == "start":
                        stream_sid = data["start"].get("streamSid")
                        call_sid = data["start"].get("callSid")
                        custom_params = data["start"].get("customParameters", {})
                        phone_number = custom_params.get("from", "Unknown")
                        print(f"Call started: {call_sid} from {phone_number}")
                        
                        # Save initial call record
                        call_id = await db_manager.start_call(call_sid, stream_sid, phone_number)
                        
                        caller_data = PHONE_LIST.get(phone_number, {"ad_soyad": "Değerli Müşterimiz"})
                        personalized_instructions = get_personalized_prompt(caller_data)
                        
                        await openai_ws.send(json.dumps({
                            "type": "session.update",
                            "session": {
                                "instructions": personalized_instructions,
                                "input_audio_transcription": {"model": "whisper-1"}
                            }
                        }))
                        await openai_ws.send(json.dumps({"type": "response.create"}))
                    elif data["event"] == "media":
                        await openai_ws.send(json.dumps({
                            "type": "input_audio_buffer.append",
                            "audio": data["media"]["payload"]
                        }))
                    elif data["event"] == "stop":
                        print(f"Call stopped: {stream_sid}")
                        break
            except Exception as e:
                print(f"Error in receive_from_twilio: {e}")

        async def receive_from_openai():
            nonlocal call_result, transcript, call_id
            try:
                async for message in openai_ws:
                    response = json.loads(message)
                    
                    if response["type"] == "input_audio_buffer.speech_started":
                        if stream_sid:
                            await ws.send_text(json.dumps({"event": "clear", "streamSid": stream_sid}))
                        await openai_ws.send(json.dumps({"type": "response.cancel"}))

                    elif response["type"] == "response.done":
                        resp_obj = response.get("response", {})
                        for item in resp_obj.get("output", []):
                            if item.get("type") == "function_call":
                                name = item.get("name")
                                args = json.loads(item.get("arguments", "{}"))
                                
                                if name == "hang_up":
                                    print(f"TOOL: Hanging up call {call_sid}")
                                    await handle_hang_up(call_sid or stream_sid)
                                    await ws.close()
                                    return
                                elif name == "send_recruitment_sms":
                                    try:
                                        print(f"TOOL: Sending SMS to {args.get('phone_number')}")
                                        await handle_send_sms(args.get("phone_number"), args.get("message"))
                                        await openai_ws.send(json.dumps({
                                            "type": "conversation.item.create",
                                            "item": {
                                                "type": "function_call_output",
                                                "call_id": item["call_id"],
                                                "output": "SMS sent successfully"
                                            }
                                        }))
                                        await openai_ws.send(json.dumps({"type": "response.create"}))
                                    except Exception as e:
                                        await openai_ws.send(json.dumps({
                                            "type": "conversation.item.create",
                                            "item": {
                                                "type": "function_call_output",
                                                "call_id": item["call_id"],
                                                "output": f"Error: {str(e)}"
                                            }
                                        }))

                    elif response["type"] == "response.audio.delta":
                        await ws.send_text(json.dumps({
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {"payload": response["delta"]}
                        }))
                    
                    elif response["type"] == "response.audio_transcript.done":
                        txt = response.get("transcript", "")
                        print(f"AI: {txt}")
                        if call_id:
                            await db_manager.add_transcript(call_id, 'assistant', txt)
                    
                    elif response["type"] == "conversation.item.input_audio_transcription.completed":
                        txt = response.get("transcript", "")
                        print(f"USER: {txt}")
                        if call_id:
                            await db_manager.add_transcript(call_id, 'user', txt)
                        if any(w in txt.lower() for w in ["evet", "tamam", "olur"]):
                            call_result = "Interested"

            except Exception as e:
                print(f"OpenAI error: {e}")

        await asyncio.gather(receive_from_twilio(), receive_from_openai())

    if call_id:
        await db_manager.update_call_status(call_id, call_result)
