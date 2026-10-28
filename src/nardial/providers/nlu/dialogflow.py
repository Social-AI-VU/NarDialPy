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
            query_result = reply.response.query_result
            transcript = query_result.query_text or ""
            intent = reply.intent if reply.intent else None
            parameters = self._parameters_to_dict(query_result)
            if parameters:
                print("The detected parameters:", parameters)
            return NLUResult(transcript=transcript, intent=intent, parameters=parameters)
        except TimeoutError as e:
            print("Dialogflow timeout:", e)
            return NLUResult(transcript="", intent=None)

    def cancel(self) -> None:
        pass

    @staticmethod
    def _parameters_to_dict(query_result) -> dict:
        """Convert the ``parameters`` Struct of a Dialogflow query result to a plain dict."""
        params = getattr(query_result, "parameters", None)
        if not params:
            return {}
        result = {}
        for name, value in params.items():
            if not isinstance(value, (str, int, float, bool, dict)) and hasattr(value, "__iter__"):
                value = list(value)
            result[name] = value
        return result

    def _on_dialog(self, message) -> None:
        if message.response:
            transcript = message.response.recognition_result.transcript
            print("Transcript:", transcript)
