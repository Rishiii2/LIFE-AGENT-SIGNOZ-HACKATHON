import os
import sys
import httpx
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
if not BOT_TOKEN or BOT_TOKEN == "your_telegram_token_here":
    print("Error: Please set your TELEGRAM_BOT_TOKEN in the .env file!")
    sys.exit(1)

if len(sys.argv) < 2:
    print("Usage: python set_webhook.py <your_ngrok_url>")
    print("Example: python set_webhook.py https://1234-abcd.ngrok-free.app")
    sys.exit(1)

NGROK_URL = sys.argv[1].rstrip("/")
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()

payload = {
    "url": f"{NGROK_URL}/webhook",
    "allowed_updates": ["message"],
    "drop_pending_updates": True,
}

if WEBHOOK_SECRET:
    payload["secret_token"] = WEBHOOK_SECRET

print(f"Setting Webhook to: {payload['url']}")

try:
    response = httpx.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
        json=payload,
        timeout=20,
    )
    print("HTTP status:", response.status_code)
    print("Telegram response:", response.text)
    
    response.raise_for_status()
    
    data = response.json()
    if data.get("ok") is not True:
        raise RuntimeError(data.get("description", "Webhook registration failed"))
        
    print("✅ Webhook registered successfully!")
except Exception as e:
    print(f"❌ Failed to set webhook: {e}")
    sys.exit(1)
