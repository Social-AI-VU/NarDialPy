import asyncio
import base64
import json
import sys
import types

if "websockets" not in sys.modules:
    websocket_exceptions = types.SimpleNamespace(
        ConnectionClosed=Exception,
        ConnectionClosedOK=Exception,
        ConnectionClosedError=Exception,
    )
    sys.modules["websockets"] = types.SimpleNamespace(
        connect=lambda *args, **kwargs: None,
        exceptions=websocket_exceptions,
    )

from nardial.tts_manager import ElevenLabsTTS


class _FakeWebSocket:
    def __init__(self, messages):
        self._messages = list(messages)
        self.closed = False
        self.sent_messages = []

    async def send(self, payload):
        self.sent_messages.append(payload)

    async def recv(self):
        if not self._messages:
            await asyncio.sleep(0)
            return json.dumps({"isFinal": True})
        return self._messages.pop(0)

    async def ping(self):
        return True


def test_elevenlabs_speak_collects_all_audio_chunks():
    audio_1 = base64.b64encode(b"hello ").decode()
    audio_2 = base64.b64encode(b"world").decode()
    fake_ws = _FakeWebSocket([
        json.dumps({"audio": audio_1}),
        json.dumps({"audio": audio_2}),
        json.dumps({"isFinal": True}),
    ])

    tts = ElevenLabsTTS(elevenlabs_key="k", voice_id="v", model_id="m")
    tts.websocket = fake_ws
    tts.connect = lambda: None
    tts.drain_socket = lambda: asyncio.sleep(0)
    tts.ping_connection = lambda: asyncio.sleep(0, result=True)

    audio = asyncio.run(tts.speak("test sentence"))

    assert audio == b"hello world"
    assert json.loads(fake_ws.sent_messages[0]) == {"text": "test sentence", "flush": True}
