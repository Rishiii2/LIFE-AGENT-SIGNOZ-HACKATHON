import os
import random
from datetime import datetime
from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import Optional, List
import uvicorn
import httpx

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

# Define Metrics
player_hp_gauge = meter.create_observable_gauge("liferpg.player.hp", description="Current HP")
player_mana_gauge = meter.create_observable_gauge("liferpg.player.mana", description="Current Mana")
player_xp_gauge = meter.create_observable_gauge("liferpg.player.xp", description="Current XP")

# In-memory state for demo purposes (ideally use SQLite)
player_state = {
    "hp": 100,
    "mana": 100,
    "xp": 0,
    "level": 1
}

def get_hp_callback(options):
    yield metrics.Observation(player_state["hp"], {})

def get_mana_callback(options):
    yield metrics.Observation(player_state["mana"], {})

def get_xp_callback(options):
    yield metrics.Observation(player_state["xp"], {})

meter.register_callback([get_hp_callback], player_hp_gauge)
meter.register_callback([get_mana_callback], player_mana_gauge)
meter.register_callback([get_xp_callback], player_xp_gauge)

app = FastAPI(title="LifeRPG API")

@app.on_event("startup")
def startup_event():
    FastAPIInstrumentor.instrument_app(app)
    RequestsInstrumentor().instrument()

class ActionReport(BaseModel):
    message: str

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

@app.post("/action")
async def report_action(action: ActionReport):
    with tracer.start_as_current_span("telegram.update.process"):
        
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
            player_state["xp"] += changes["xp_delta"]
            player_state["mana"] += changes["mana_delta"]
            player_state["hp"] += changes["hp_delta"]
            
        return {
            "status": "success",
            "extracted": extracted,
            "changes": changes,
            "new_state": player_state
        }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
