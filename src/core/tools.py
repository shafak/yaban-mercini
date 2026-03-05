import json
import os
from twilio.rest import Client as TwilioClient

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")

def get_openai_tools():
    return [
        {
            "type": "function",
            "name": "hang_up",
            "description": "Görüşmeyi sonlandırır. Adayla konuşma bittiğinde veya aday kapatmak istediğinde çağır.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        },
        {
            "type": "function",
            "name": "send_recruitment_sms",
            "description": "Adaya Yandex Pro indirme linkini ve Kaptango seçim talimatını içeren SMS gönderir.",
            "parameters": {
                "type": "object",
                "properties": {
                    "phone_number": {
                        "type": "string",
                        "description": "SMS gönderilecek telefon numarası."
                    },
                    "message": {
                        "type": "string",
                        "description": "Gönderilecek SMS içeriği."
                    }
                },
                "required": ["phone_number", "message"]
            }
        }
    ]

async def handle_hang_up(call_sid: str):
    try:
        client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        if call_sid:
            client.calls(call_sid).update(status="completed")
            return True
    except Exception as e:
        print(f"Hang up error: {e}")
    return False

async def handle_send_sms(to_num: str, msg_body: str):
    try:
        client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        msg = client.messages.create(
            body=msg_body,
            from_=TWILIO_PHONE_NUMBER,
            to=to_num
        )
        return msg.sid
    except Exception as e:
        print(f"SMS Error: {e}")
        raise e
