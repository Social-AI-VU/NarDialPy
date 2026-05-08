from typing import Any

import numpy as np
from sic_framework.services.dialogflow.dialogflow import (
    Dialogflow,
    DialogflowConf,
    GetIntentRequest,
)

from nardial.providers.nlu import NLUResult


class DialogflowNLUProvider:
    def __init__(self, conf: DialogflowConf, mic: Any | None = None):
        self._dialogflow = Dialogflow(ip="localhost", conf=conf, input_source=mic)
        self._request_id = np.random.randint(10000)
        self._dialogflow.register_callback(self._on_dialog)

    def listen(self, context: str | None = None, timeout: float = 10.0) -> NLUResult:
        try:
            reply = self._dialogflow.request(
                GetIntentRequest(self._request_id, context), timeout=timeout
            )
            print("The detected intent:", reply.intent)
            transcript = reply.response.query_result.query_text or ""
            intent = reply.intent if reply.intent else None
            return NLUResult(transcript=transcript, intent=intent)
        except TimeoutError as e:
            print("Dialogflow timeout:", e)
            return NLUResult(transcript="", intent=None)

    def _on_dialog(self, message) -> None:
        if message.response:
            transcript = message.response.recognition_result.transcript
            print("Transcript:", transcript)
