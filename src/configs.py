class DialogFlowConfig:
    def __init__(self, google_keyfile_path, sample_rate_dialogflow_hertz=44100, dialogflow_language="en"):
        self.google_keyfile_path = google_keyfile_path
        self.sample_rate_dialogflow_hertz = sample_rate_dialogflow_hertz
        self.dialogflow_language = dialogflow_language


class GoogleTTSConfig:
    def __init__(self, google_keyfile_path, google_tts_voice_name="en-US-Standard-C", google_tts_voice_gender="FEMALE", default_speaking_rate=1.0):
        self.google_keyfile_path = google_keyfile_path
        self.google_tts_voice_name = google_tts_voice_name
        self.google_tts_voice_gender = google_tts_voice_gender
        self.default_speaking_rate = default_speaking_rate


class OpenAIConfig:
    def __init__(self, openai_key_path=None):
        self.openai_key_path = openai_key_path
