import os
import httpx
import html
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
import uvicorn

from sqlmodel import Session, select
from database import create_db_and_tables, engine, PlayerState, ProcessedUpdate, get_session

from opentelemetry import trace, metrics
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

# ----------------- OpenTelemetry Setup -----------------
resource = Resource(attributes={
    "service.name": os.getenv("OTEL_SERVICE_NAME", "liferpg-api"),
    "service.version": os.getenv("OTEL_SERVICE_VERSION", "0.2.0"),
    "deployment.environment": os.getenv("OTEL_DEPLOYMENT_ENVIRONMENT", "hackathon-local")
})

# Tracing
trace_provider = TracerProvider(resource=resource)
span_processor = BatchSpanProcessor(OTLPSpanExporter())
trace_provider.add_span_processor(span_processor)
trace.set_tracer_provider(trace_provider)
tracer = trace.get_tracer("liferpg.tracer")

# Metrics
metric_reader = PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=int(os.getenv("OTEL_METRIC_EXPORT_INTERVAL_MS", 5000)))
meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
metrics.set_meter_provider(meter_provider)
meter = metrics.get_meter("liferpg.meter")

# Custom Metrics
events_processed = meter.create_counter("liferpg.events.processed", description="Total events processed")
rules_decisions = meter.create_counter("liferpg.rules.decisions", description="Rules engine executions")
telegram_updates = meter.create_counter("liferpg.telegram.updates", description="Telegram webhook updates")
telegram_replies = meter.create_counter("liferpg.telegram.replies", description="Telegram replies sent")
error_counter = meter.create_counter("liferpg.errors", description="Total errors encountered")

# ----------------- App Lifecycle -----------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET")

# Reusable HTTP client
http_client = httpx.AsyncClient(timeout=20.0)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    create_db_and_tables()
    
    if TELEGRAM_BOT_TOKEN:
        try:
            res = await http_client.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe")
            res.raise_for_status()
            data = res.json()
            if data.get("ok"):
                print(f"Success: Telegram token valid for @{data['result']['username']}")
            else:
                print(f"Error: Telegram getMe failed: {data.get('description')}")
        except Exception as e:
            print(f"Error: Telegram API Error on startup: {e}")
            
    yield
    
    # Shutdown
    await http_client.aclose()
    span_processor.force_flush()
    metric_reader.force_flush()

app = FastAPI(title="LifeRPG API", lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app)
# Note: Intentionally NOT using RequestsInstrumentor globally to prevent leaking tokens.

# ----------------- Models & Core Logic -----------------
class ActionReport(BaseModel):
    message: str
    telegram_id: str

def get_or_create_player(session: Session, telegram_id: str) -> PlayerState:
    player = session.exec(select(PlayerState).where(PlayerState.telegram_id == telegram_id)).first()
    if not player:
        player = PlayerState(
            telegram_id=telegram_id,
            hp=int(os.getenv("LIFERPG_DEFAULT_HP", 100)),
            mana=int(os.getenv("LIFERPG_DEFAULT_MANA", 100)),
            xp=int(os.getenv("LIFERPG_DEFAULT_XP", 0))
        )
        session.add(player)
        session.commit()
        session.refresh(player)
    return player

def clamp(value, min_val, max_val):
    return max(min_val, min(value, max_val))

def mock_llm_extract(message: str) -> dict:
    """Mock LLM extraction since API key is missing."""
    with tracer.start_as_current_span("liferpg.activity.extract") as span:
        message_lower = message.lower()
        if "code" in message_lower or "work" in message_lower:
            res = {"activity": "coding", "duration_minutes": 120, "category": "deep_work", "confidence": 0.95}
        elif "doomscroll" in message_lower or "twitter" in message_lower or "tiktok" in message_lower:
            res = {"activity": "doomscrolling", "duration_minutes": 60, "category": "distraction", "confidence": 0.9}
        elif "pizza" in message_lower or "junk food" in message_lower:
            res = {"activity": "junk_food", "duration_minutes": 30, "category": "diet", "confidence": 0.85}
        else:
            res = {"activity": "unknown", "duration_minutes": 0, "category": "other", "confidence": 0.5}
            
        span.set_attribute("liferpg.activity", res["activity"])
        span.set_attribute("liferpg.confidence", res["confidence"])
        return res

def evaluate_rules(extracted_data: dict) -> dict:
    """Deterministic Rules Engine."""
    with tracer.start_as_current_span("liferpg.rules.evaluate") as span:
        rules_decisions.add(1)
        category = extracted_data["category"]
        ruleset = os.getenv("LIFERPG_RULESET_VERSION", "2026.07.1")
        span.set_attribute("liferpg.ruleset", ruleset)
        
        if category == "deep_work":
            res = {"xp_delta": 80, "mana_delta": -20, "hp_delta": 0, "ruleset": ruleset}
        elif category == "distraction":
            res = {"xp_delta": 0, "mana_delta": -30, "hp_delta": 0, "ruleset": ruleset}
        elif category == "diet":
            res = {"xp_delta": 0, "mana_delta": 0, "hp_delta": -10, "ruleset": ruleset}
        else:
            res = {"xp_delta": 5, "mana_delta": 0, "hp_delta": 0, "ruleset": ruleset}
            
        span.set_attribute("liferpg.delta.xp", res["xp_delta"])
        span.set_attribute("liferpg.delta.hp", res["hp_delta"])
        return res

async def report_action(action: ActionReport, session: Session) -> dict:
    with tracer.start_as_current_span("liferpg.action.process") as span:
        span.set_attribute("player.telegram_id.hashed", str(hash(action.telegram_id)))
        events_processed.add(1)
        
        extracted = mock_llm_extract(action.message)
        changes = evaluate_rules(extracted)
        
        with tracer.start_as_current_span("liferpg.player.load"):
            player = get_or_create_player(session, action.telegram_id)
            
        with tracer.start_as_current_span("liferpg.player.commit"):
            try:
                player.xp += changes["xp_delta"]
                player.mana = clamp(player.mana + changes["mana_delta"], 0, int(os.getenv("LIFERPG_MAX_MANA", 100)))
                player.hp = clamp(player.hp + changes["hp_delta"], 0, int(os.getenv("LIFERPG_MAX_HP", 100)))
                
                session.add(player)
                session.commit()
                session.refresh(player)
            except Exception as e:
                session.rollback()
                error_counter.add(1)
                raise e
            
        return {
            "status": "success",
            "extracted": extracted,
            "changes": changes,
            "new_state": player.model_dump()
        }

# ----------------- Webhook & Telegram Integration -----------------
async def send_telegram_reply(chat_id: str, text: str, trace_id: str = None):
    if not TELEGRAM_BOT_TOKEN:
        return
    
    with tracer.start_as_current_span("telegram.bot_api.sendMessage") as span:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        
        if trace_id:
            text += f"\n\n<pre>Trace ID: {trace_id[:12]}</pre>"
            
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        
        try:
            res = await http_client.post(url, json=payload)
            span.set_attribute("http.status_code", res.status_code)
            res.raise_for_status()
            
            data = res.json()
            if not data.get("ok"):
                error_msg = data.get("description", "Unknown Telegram Error")
                span.set_attribute("telegram.error", error_msg)
                print(f"Telegram reply failed: {error_msg}")
                error_counter.add(1)
            else:
                telegram_replies.add(1)
        except httpx.HTTPStatusError as e:
            span.set_attribute("telegram.error", str(e))
            print(f"Telegram HTTP Error: {e.response.text}")
            error_counter.add(1)
        except Exception as e:
            span.set_attribute("telegram.error", str(e))
            print(f"Telegram Network Error: {e}")
            error_counter.add(1)

@app.post("/webhook")
async def telegram_webhook(request: Request, session: Session = Depends(get_session)):
    telegram_updates.add(1)
    
    # Verify Webhook Secret
    if TELEGRAM_WEBHOOK_SECRET:
        secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if secret_header != TELEGRAM_WEBHOOK_SECRET:
            raise HTTPException(status_code=401, detail="Unauthorized webhook secret")

    update = await request.json()
    update_id = update.get("update_id")
    
    # Idempotency Check
    if update_id:
        processed = session.exec(select(ProcessedUpdate).where(ProcessedUpdate.update_id == update_id)).first()
        if processed:
            return {"status": "already_processed"}
            
    try:
        if "message" in update and "text" in update["message"]:
            message_text = update["message"]["text"]
            chat_id = str(update["message"]["chat"]["id"])
            
            # Get current Trace ID for correlation
            current_span = trace.get_current_span()
            trace_id = format(current_span.get_span_context().trace_id, '032x') if current_span.is_recording() else None
            
            # Handle commands
            if message_text.startswith("/start") or message_text.startswith("/help"):
                await send_telegram_reply(chat_id, "Welcome to <b>LifeRPG</b>! Send me your daily actions (e.g. 'I coded for 2 hours') and I will adjust your stats.", trace_id)
                return {"status": "command_processed"}
            elif message_text.startswith("/stats"):
                player = get_or_create_player(session, chat_id)
                await send_telegram_reply(chat_id, f"📊 <b>Your Stats</b>\n❤️ HP: {player.hp}\n💧 Mana: {player.mana}\n🌟 XP: {player.xp}", trace_id)
                return {"status": "command_processed"}
            
            # Process normal action
            report = ActionReport(message=message_text, telegram_id=chat_id)
            result = await report_action(report, session)
            
            changes = result["changes"]
            new_state = result["new_state"]
            activity_name = html.escape(result['extracted']['activity'].replace('_', ' ').title())
            
            reply_text = (
                f"🎲 <b>The DM has ruled!</b>\n"
                f"Action: {activity_name}\n"
                f"Changes: XP {changes['xp_delta']:+d} | HP {changes['hp_delta']:+d} | Mana {changes['mana_delta']:+d}\n\n"
                f"❤️ HP: {new_state['hp']}\n"
                f"💧 Mana: {new_state['mana']}\n"
                f"🌟 XP: {new_state['xp']}"
            )
            
            await send_telegram_reply(chat_id, reply_text, trace_id)
            
        # Mark as processed
        if update_id:
            session.add(ProcessedUpdate(update_id=update_id, processed_at="now"))
            session.commit()
            
        return {"status": "success"}
    except Exception as e:
        error_counter.add(1)
        print(f"Error processing webhook: {e}")
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    uvicorn.run(app, host="::", port=8888)
