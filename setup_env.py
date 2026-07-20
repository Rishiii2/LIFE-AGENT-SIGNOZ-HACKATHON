import os
import json
import urllib.request
import subprocess

# 1. Get ngrok URL
try:
    req = urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels")
    data = json.loads(req.read())
    ngrok_url = data['tunnels'][0]['public_url']
    print(f"Found ngrok URL: {ngrok_url}")
except Exception as e:
    print(f"Error getting ngrok URL: {e}")
    ngrok_url = None

if ngrok_url:
    # 2. Update .env
    env_content = """TELEGRAM_BOT_TOKEN="8913952753:AAEDA0BezCUnFLwNvnzZgeEh10VIPbVZIAE"
OPENAI_API_KEY="your_openai_key_here"

OTEL_SERVICE_NAME="liferpg-api"
OTEL_RESOURCE_ATTRIBUTES="deployment.environment=hackathon"
OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318"
OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"
OTEL_TRACES_EXPORTER="otlp"
OTEL_METRICS_EXPORTER="otlp"
OTEL_LOGS_EXPORTER="otlp"
"""
    with open(".env", "w") as f:
        f.write(env_content)
    
    # 3. Run set_webhook.py
    print("Setting webhook...")
    subprocess.run([r".\venv\Scripts\python", "set_webhook.py", ngrok_url])
