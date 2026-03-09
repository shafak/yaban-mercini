"""
FreeSWITCH ESL (Event Socket Library) Outbound Handler
------------------------------------------------------
FreeSWITCH is configured to route calls to this TCP server on port 8084
using the "socket" dialplan application in outbound/async full mode.

Protocol (async full mode):
  1. FreeSWITCH connects TCP → sends channel data block
  2. We send: "connect\\n\\n"
  3. FreeSWITCH replies: channel variables block
  4. We subscribe to events: "myevents\\n\\n"
  5. We send commands to answer/record, then keep alive
  6. FreeSWITCH sends CHANNEL_HANGUP when call ends

Architecture:
  Netgsm (SIP) → FreeSWITCH → TCP:8084 → This Handler
                                               │  WebSocket
                                           OpenAI Realtime API
"""
import asyncio
import logging
import os
import json
import websockets

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_WS_URL  = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01"

SYSTEM_PROMPT = (
    "Sen samimi ve yardımsever bir asistansın. "
    "Türkçe konuş, kısa ve net cevaplar ver."
)


class FreeSwitchESLHandler:
    """Handles a single ESL outbound socket session (one call)."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self.uuid: str = ""
        self.openai_ws = None
        self._closed = False

    # ── ESL wire protocol ──────────────────────────────────────────────────

    async def _read_block(self, timeout: float = 30.0) -> dict:
        """Read one ESL message block (headers + optional body)."""
        headers: dict = {}
        try:
            while True:
                raw = await asyncio.wait_for(self.reader.readline(), timeout=timeout)
                if not raw:
                    return {}
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if line == "":
                    break
                if ":" in line:
                    k, _, v = line.partition(":")
                    headers[k.strip()] = v.strip()

            if "Content-Length" in headers:
                length = int(headers["Content-Length"])
                body_bytes = await asyncio.wait_for(
                    self.reader.readexactly(length), timeout=timeout
                )
                headers["_body"] = body_bytes.decode("utf-8", errors="replace")
        except asyncio.TimeoutError:
            logger.warning("[ESL] Timeout reading block")
            return {}
        except Exception as e:
            logger.debug(f"[ESL] Read block error: {e}")
            return {}
        return headers

    def _write(self, text: str):
        """Write a raw command to FreeSWITCH."""
        self.writer.write((text + "\n\n").encode())

    async def _sendmsg(self, app: str, arg: str = ""):
        """Send sendmsg to execute a dialplan app on this call."""
        msg = (
            f"sendmsg {self.uuid}\n"
            f"call-command: execute\n"
            f"execute-app-name: {app}\n"
        )
        if arg:
            msg += f"execute-app-arg: {arg}\n"
        self._write(msg.rstrip())
        await self.writer.drain()

    # ── Main session ───────────────────────────────────────────────────────

    async def run(self):
        """Main entry point — called once per inbound TCP connection."""
        try:
            # Step 1: Send 'connect' to get the channel data
            self._write("connect")
            await self.writer.drain()

            channel_data = await self._read_block()
            if not channel_data:
                logger.warning("[ESL] Empty channel data on connect")
                return

            self.uuid = channel_data.get(
                "Unique-ID",
                channel_data.get("Channel-Unique-ID", "unknown")
            )
            answer_state = channel_data.get("Answer-State", "")
            logger.info(f"[ESL] Connected — UUID={self.uuid} AnswerState={answer_state}")

            # Step 2: Subscribe to events for this channel
            self._write("myevents")
            await self.writer.drain()
            await self._read_block(timeout=3)  # consume +OK

            # Step 3: Answer the call
            await self._sendmsg("answer")
            await asyncio.sleep(0.5)

            # Step 4: Play a pleasant greeting tone immediately so caller hears audio
            # tone_stream: alternating tones (like a pleasant notification)
            await self._sendmsg("playback", "tone_stream://%(300,100,523);%(300,100,659);%(300,100,784)")
            await asyncio.sleep(1.5)

            # Step 5: Connect to OpenAI
            await self._connect_openai()

            # Step 6: Play looping hold music via tone_stream (no external files needed)
            # This is a simple repeating tone that keeps the audio channel active
            await self._sendmsg("playback", "tone_stream://%(400,200,440,480);loops=-1")

            # Step 6: Event loop until hangup
            await self._event_loop()

        except Exception as e:
            logger.exception(f"[ESL] Session error for UUID={self.uuid}: {e}")
        finally:
            self._closed = True
            try:
                self.writer.close()
            except Exception:
                pass
            if self.openai_ws:
                try:
                    await self.openai_ws.close()
                except Exception:
                    pass
            logger.info(f"[ESL] Session ended UUID={self.uuid}")

    async def _connect_openai(self):
        """Connect to OpenAI Realtime API."""
        if not OPENAI_API_KEY:
            logger.warning("[ESL] No OPENAI_API_KEY — skipping AI connection")
            return
        try:
            headers = [
                ("Authorization", f"Bearer {OPENAI_API_KEY}"),
                ("OpenAI-Beta", "realtime=v1"),
            ]
            try:
                self.openai_ws = await websockets.connect(
                    OPENAI_WS_URL, additional_headers=headers
                )
            except TypeError:
                self.openai_ws = await websockets.connect(
                    OPENAI_WS_URL, extra_headers=dict(headers)
                )

            await self.openai_ws.send(json.dumps({
                "type": "session.update",
                "session": {
                    "turn_detection": {"type": "server_vad"},
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",
                    "voice": "alloy",
                    "instructions": SYSTEM_PROMPT,
                    "modalities": ["text", "audio"],
                }
            }))
            logger.info("[ESL] OpenAI Realtime API connected")
        except Exception as e:
            logger.error(f"[ESL] OpenAI connect failed: {e}")
            self.openai_ws = None

    async def _event_loop(self):
        """Process ESL events until hangup or timeout."""
        while not self._closed:
            event = await self._read_block(timeout=120)
            if not event:
                logger.warning(f"[ESL] No event received, ending session UUID={self.uuid}")
                break

            name = event.get("Event-Name", "")
            logger.debug(f"[ESL] Event: {name}")

            if name in ("CHANNEL_HANGUP", "CHANNEL_HANGUP_COMPLETE", "CHANNEL_DESTROY"):
                logger.info(f"[ESL] Hangup received for UUID={self.uuid}")
                break


# ── TCP Server ──────────────────────────────────────────────────────────────

async def handle_connection(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
):
    """Called once per TCP connection from FreeSWITCH."""
    peer = writer.get_extra_info("peername")
    logger.info(f"[ESL] Incoming connection from {peer}")
    handler = FreeSwitchESLHandler(reader, writer)
    await handler.run()


async def start_esl_server(host: str = "0.0.0.0", port: int = 8084):
    """Start the ESL outbound socket server."""
    server = await asyncio.start_server(handle_connection, host, port)
    addrs = ", ".join(str(s.getsockname()) for s in server.sockets)
    logger.info(f"[ESL] FreeSWITCH ESL server listening on {addrs}")
    async with server:
        await server.serve_forever()
