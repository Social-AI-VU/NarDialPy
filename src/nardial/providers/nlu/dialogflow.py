from typing import Any

import numpy as np
from sic_framework.services.dialogflow.dialogflow import (
    Dialogflow,
    DialogflowConf,
    GetIntentRequest,
    StopListeningMessage,
)

from nardial.providers.nlu import NLUResult


class DialogflowNLUProvider:
    """NLU provider backed by the SIC Dialogflow service.

    The ``timeout`` passed to :meth:`listen` is enforced on the client side: when it
    expires, a ``StopListeningMessage`` is sent so the service stops streaming too.
    Otherwise the service keeps listening after ``listen()`` returned and the next
    request queues behind it. Leave ``DialogflowConf.timeout`` at ``None`` (or above
    the longest per-move timeout), since it caps every request on the service side.
    """

    def __init__(self, conf: DialogflowConf, mic: Any | None = None):
        self._dialogflow = Dialogflow(ip="localhost", conf=conf, input_source=mic)
        self._request_id = np.random.randint(10000)
        self._dialogflow.register_callback(self._on_dialog)


    def listen(self, context: str | None = None, timeout: float = 10.0) -> NLUResult:
        try:
            reply = self._dialogflow.request(
                GetIntentRequest(self._request_id, context), timeout=timeout
            )
        except TimeoutError as e:
            print("Dialogflow timeout:", e)
            self._stop_listening()
            return NLUResult(transcript="", intent=None)

        print("The detected intent:", reply.intent)
        # The service returns QueryResult(dict()) when the stream ends without a query result.
        query_result = getattr(reply.response, "query_result", None)
        transcript = (query_result.query_text if query_result else "") or ""
        intent = reply.intent if reply.intent else None
        parameters = self._parameters_to_dict(query_result) if query_result else {}
        if parameters:
            print("The detected parameters:", parameters)
        return NLUResult(transcript=transcript, intent=intent, parameters=parameters)

    def cancel(self) -> None:
        self._stop_listening()

    def _stop_listening(self) -> None:
        try:
            self._dialogflow.send_message(StopListeningMessage(self._request_id))
        except Exception as e:
            print("Dialogflow stop listening failed:", e)

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
