import threading
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

    Dialogflow keeps streaming until the stream is closed, so the ``timeout`` passed to
    :meth:`listen` is how long the user can speak: when it expires a ``StopListeningMessage``
    closes the stream, and the final result for the audio so far follows within
    ``stop_grace_seconds``. Leave ``DialogflowConf.timeout`` at ``None`` (or above the
    longest per-move timeout), since it caps every request on the service side.
    """

    def __init__(self, conf: DialogflowConf, mic: Any | None = None, stop_grace_seconds: float = 5.0):
        self._dialogflow = Dialogflow(ip="localhost", conf=conf, input_source=mic)
        self._request_id = np.random.randint(10000)
        self.stop_grace_seconds = stop_grace_seconds
        self._dialogflow.register_callback(self._on_dialog)

    def listen(self, context: str | None = None, timeout: float = 10.0) -> NLUResult:
        stopper = threading.Timer(timeout, self._stop_listening)
        stopper.daemon = True
        stopper.start()
        try:
            reply = self._dialogflow.request(
                GetIntentRequest(self._request_id, context), timeout=timeout + self.stop_grace_seconds
            )
        except TimeoutError as e:
            print("Dialogflow timeout:", e)
            return NLUResult(transcript="", intent=None)
        finally:
            stopper.cancel()

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
