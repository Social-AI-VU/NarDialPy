# NarDialPy
Python implementation of the Narrative Dialog Management System.

--- 

## Demo 

[Here](./src/demo_general_conversation.py) is a demo showcasing an agent-driven conversation utilizing Google Dialogflow, Google TTS, and OpenAI's GPT4

First, you need to set-up Google Cloud Console with dialogflow and Google TTS:

1. Dialogflow: https://socialrobotics.atlassian.net/wiki/spaces/CBSR/pages/2205155343/Getting+a+google+dialogflow+key 
2. TTS: https://console.cloud.google.com/apis/api/texttospeech.googleapis.com/
**Note:** you need to set-up a paid account with a credit card. You get $300,- free tokens, which is more then enough
for testing this agent. So in practice it will not cost anything.
3. Create a keyfile as instructed in (1) and save it conf/dialogflow/google_keyfile.json
   **_(Never share the keyfile online!)_** 

Secondly you need to configure your dialogflow agent.
4. In your empty dialogflow agent do the following things:
   - Remove all default intents 
   - Go to settings -> import and export -> and import the resources/droomrobot_dialogflow_agent.zip into your
   dialogflow agent. That gives all the necessary intents and entities that are part of this example (and many more)

Thirdly, you need an openAI key:
5. Generate your personal openai api key here: https://platform.openai.com/api-keys
6. Either add your openai key to your systems variables or
create a .openai_env file in the conf/openai folder and add your key there like this:
OPENAI_API_KEY="your key"

Forth, the redis server, Dialogflow, Google TTS and OpenAI gpt service need to be running:

7. Run:
```bash 
pip install --upgrade social-interaction-cloud[dialogflow,google-tts,openai-gpt]
   ```
8. Run: 
```bash 
conf/redis/redis-server.exe conf/redis/redis.conf
```
9. Run in new terminal: 
```bash 
run-dialogflow 
```
10. Run in new terminal: 
```bash
run-google-tts
```
11. Run in new terminal: 
```bash 
run-gpt
```
12. Connect a device e.g. desktop, nao, pepper, alphamini
13. Run [this script](./src/demo_general_conversation.py) in  a new terminal. 

---