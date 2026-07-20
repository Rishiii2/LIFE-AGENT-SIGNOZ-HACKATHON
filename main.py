import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends
from pydantic import BaseModel
from typing import Optional
import uvicorn

from sqlmodel import Session, select
from database import create_db_and_tables, engine, PlayerState, get_session

from opentelemetry import trace, metrics
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

# Initialize OpenTelemetry
resource = Resource(attributes={
    "service.name": os.getenv("OTEL_SERVICE_NAME", "liferpg-api")
})

trace_provider = TracerProvider(resource=resource)
processor = BatchSpanProcessor(OTLPSpanExporter())
trace_provider.add_span_processor(processor)
trace.set_tracer_provider(trace_provider)

metric_reader = PeriodicExportingMetricReader(OTLPMetricExporter())
meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
metrics.set_meter_provider(meter_provider)

tracer = trace.get_tracer("liferpg.tracer")
meter = metrics.get_meter("liferpg.meter")

# Define Custom OTel Metrics
event_counter = meter.create_counter("liferpg.events.total", description="Total events processed")
quests_completed = meter.create_counter("liferpg.quests.completed", description="Total quests completed")
override_counter = meter.create_counter("liferpg.dm.overrides", description="Times a DM decision was appealed")

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield

app = FastAPI(title="LifeRPG API", lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app)
RequestsInstrumentor().instrument()

class ActionReport(BaseModel):
    message: str
    telegram_id: str

def mock_llm_extract(message: str) -> dict:
    """Mock LLM extraction since API key is missing."""
    message = message.lower()
    if "code" in message or "work" in message:
        return {"activity": "coding", "duration_minutes": 120, "category": "deep_work", "confidence": 0.95}
    elif "doomscroll" in message or "twitter" in message or "tiktok" in message:
        return {"activity": "doomscrolling", "duration_minutes": 60, "category": "distraction", "confidence": 0.9}
    elif "pizza" in message or "junk food" in message:
        return {"activity": "junk_food", "duration_minutes": 30, "category": "diet", "confidence": 0.85}
    else:
        return {"activity": "unknown", "duration_minutes": 0, "category": "other", "confidence": 0.5}

def evaluate_rules(extracted_data: dict) -> dict:
    """Deterministic Rules Engine."""
    category = extracted_data["category"]
    
    if category == "deep_work":
        return {"xp_delta": 80, "mana_delta": -20, "hp_delta": 0, "ruleset": "2026.07.1"}
    elif category == "distraction":
        return {"xp_delta": 0, "mana_delta": -30, "hp_delta": 0, "ruleset": "2026.07.1"}
    elif category == "diet":
        return {"xp_delta": 0, "mana_delta": 0, "hp_delta": -10, "ruleset": "2026.07.1"}
    
    return {"xp_delta": 5, "mana_delta": 0, "hp_delta": 0, "ruleset": "2026.07.1"}

def get_or_create_player(session: Session, telegram_id: str) -> PlayerState:
    player = session.exec(select(PlayerState).where(PlayerState.telegram_id == telegram_id)).first()
    if not player:
        player = PlayerState(telegram_id=telegram_id)
        session.add(player)
        session.commit()
        session.refresh(player)
    return player

@app.post("/action")
async def report_action(action: ActionReport, session: Session = Depends(get_session)):
    with tracer.start_as_current_span("telegram.update.process") as root_span:
        root_span.set_attribute("player.telegram_id", action.telegram_id)
        event_counter.add(1)
        
        # 1. LLM Extraction
        with tracer.start_as_current_span("gen_ai.activity_extract") as span:
            span.set_attribute("gen_ai.request.model", "mock-llm-v1")
            extracted = mock_llm_extract(action.message)
            span.set_attribute("liferpg.decision.confidence", extracted["confidence"])
            span.set_attribute("liferpg.event.category", extracted["category"])

        # 2. Rules Evaluation
        with tracer.start_as_current_span("rules.evaluate") as span:
            changes = evaluate_rules(extracted)
            span.set_attribute("liferpg.ruleset.version", changes["ruleset"])
            span.set_attribute("liferpg.delta.hp", changes["hp_delta"])
            span.set_attribute("liferpg.delta.mana", changes["mana_delta"])

        # 3. State Commit
        with tracer.start_as_current_span("state.commit"):
            player = get_or_create_player(session, action.telegram_id)
            player.xp += changes["xp_delta"]
            player.mana += changes["mana_delta"]
            player.hp += changes["hp_delta"]
            session.add(player)
            session.commit()
            session.refresh(player)
            
        return {
            "status": "success",
            "extracted": extracted,
            "changes": changes,
            "new_state": player.model_dump()
        }

@app.post("/webhook")
async def telegram_webhook(request: Request, session: Session = Depends(get_session)):
    """Webhook endpoint for Telegram."""
    update = await request.json()
    
    if "message" in update and "text" in update["message"]:
        message = update["message"]["text"]
        chat_id = str(update["message"]["chat"]["id"])
        
        # Internally trigger the action processing
        report = ActionReport(message=message, telegram_id=chat_id)
        
        # For a full implementation, you'd want to use httpx to send a reply via the Telegram API here.
        # But for the hackathon MVP, we process the state synchronously.
        result = await report_action(report, session)
        return {"status": "processed", "result": result}
        
    return {"status": "ignored"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
