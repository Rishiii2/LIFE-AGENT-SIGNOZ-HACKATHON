# LifeRPG: The Observable AI Game Master 🎲

**LifeRPG** is a gamified habit-tracking Telegram Bot that turns your daily real-life actions into an RPG game. You simply text the bot what you did (e.g., "I went to the gym", "I ate junk food", "I coded for 3 hours"), and an AI Game Master (DM) evaluates your actions in real-time to adjust your HP, Mana, and XP.

What makes LifeRPG special is its **deep observability**. Built specifically for the **SigNoz Hackathon**, the entire AI decision-making process is fully instrumented using OpenTelemetry. Every single message you send to the bot generates a unique Trace ID, allowing developers to see the exact hierarchical "thought process" of the AI in the SigNoz dashboard.

## 🚀 Features
- **AI Game Master:** Uses Google's Gemini LLM to naturally parse unstructured text and evaluate real-life actions against RPG mechanics.
- **Dynamic Stats:** Positive habits grant XP and Mana. Bad habits damage your HP.
- **Idempotent Webhooks:** Built with FastAPI, the Telegram webhook is completely resilient against duplicate events.
- **Deep Tracing:** Full OpenTelemetry instrumentation (`liferpg.action.process` -> `liferpg.activity.extract` -> `liferpg.rules.evaluate` -> `liferpg.player.commit` -> `telegram.bot_api.sendMessage`).
- **Trace Transparency:** The bot replies to the user with the exact Trace ID for the transaction, bridging the gap between the end-user experience and backend observability.

## 🛠 Tech Stack
- **Backend:** Python, FastAPI, SQLite (SQLModel)
- **AI/LLM:** `google-genai` (Gemini 2.5)
- **Observability:** OpenTelemetry (OTLP), SigNoz
- **Integration:** Telegram Bot API
- **Tunneling:** ngrok

## 📊 SigNoz Integration
This project demonstrates how AI agents can be made highly transparent. By sending a custom Trace ID back to the user in Telegram, we've created a system where users can report "AI hallucinations" or unfair rulings simply by providing the Trace ID. 

Developers can instantly search for that Trace ID in the **SigNoz Explorer** and see a beautiful waterfall chart detailing:
1. How long the LLM took to extract the activity.
2. The exact JSON payload the LLM generated.
3. How the rules engine evaluated that payload.
4. The exact milliseconds spent committing to the SQLite database.
5. The HTTP response times from the Telegram API.

## 🏃‍♂️ How to Run Locally

### 1. Setup SigNoz
Use `foundryctl` or Docker Compose to spin up a local instance of SigNoz:
```bash
docker compose -f docker/docker-compose.yaml up -d
```
The SigNoz dashboard will be available at `http://localhost:8080`.

### 2. Configure Environment Variables
Create a `.env` file in the root directory:
```env
TELEGRAM_BOT_TOKEN="your_bot_token_here"
TELEGRAM_WEBHOOK_SECRET="HackathonSecret123"
GEMINI_API_KEY="your_gemini_api_key"

OTEL_SERVICE_NAME=liferpg-api
OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"
```

### 3. Start the Server
```bash
# Create a virtual environment and install dependencies
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# Start the FastAPI server on Port 8888
python main.py
```

### 4. Expose to the Internet
Use `ngrok` to tunnel Port 8888 to a public URL:
```bash
ngrok http 8888
```

### 5. Register the Webhook
Run the included webhook registration script with your new ngrok URL:
```bash
python set_webhook.py https://your-ngrok-url.ngrok-free.dev
```

## 🏆 Hackathon Submission Details
**Team:** Rishikant
**Project Focus:** AI Observability & Tracing with SigNoz
