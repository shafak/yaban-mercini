from twilio.rest import Client
import os
from dotenv import load_dotenv

load_dotenv()

# Twilio bilgilerin (Console'dan al)
account_sid = os.getenv("TWILIO_ACCOUNT_SID")
auth_token = os.getenv("TWILIO_AUTH_TOKEN")

# Twilio numaran (FROM)
from_number = os.getenv("TWILIO_PHONE_NUMBER")

# Aramak istediğin gerçek numara (TO)
to_number = "+491608161214"   # kendi telefonun
# to_number = "+905511098751"

# Twilio webhook URL (ngrok + /voice)
voice_url = "https://lukewarm-operably-sherryl.ngrok-free.dev/voice"

client = Client(account_sid, auth_token)

call = client.calls.create(
    to=to_number,
    from_=from_number,
    url=voice_url,
    method="POST"
)

print("Call SID:", call.sid)

