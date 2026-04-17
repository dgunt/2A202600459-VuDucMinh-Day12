import json
import logging
import signal
import sys
from typing import List

import redis
from fastapi import Body, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI

from .auth import verify_api_key
from .config import settings
from .cost_guard import check_budget, record_cost
from .rate_limiter import check_rate_limit

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.ALLOWED_ORIGINS.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)


class AskRequest(BaseModel):
    question: str


def setup_json_logging():
    logger = logging.getLogger()
    logger.setLevel(settings.LOG_LEVEL if hasattr(settings, "LOG_LEVEL") else "INFO")

    handler = logging.StreamHandler(sys.stdout)

    class JsonFormatter(logging.Formatter):
        def format(self, record):
            payload = {
                "level": record.levelname,
                "message": record.getMessage(),
                "logger": record.name,
            }
            return json.dumps(payload)

    handler.setFormatter(JsonFormatter())
    logger.handlers = [handler]


setup_json_logging()
logger = logging.getLogger(__name__)


def handle_shutdown(signum, frame):
    logger.info("Shutting down gracefully")
    sys.exit(0)


signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGINT, handle_shutdown)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    try:
        redis_client.ping()
        return {"status": "ready"}
    except redis.RedisError:
        raise HTTPException(status_code=503, detail="Redis not ready")


def get_conversation_history(user_id: str) -> List[dict]:
    key = f"history:{user_id}"
    try:
        items = redis_client.lrange(key, 0, -1)
        return [json.loads(item) for item in items]
    except (redis.RedisError, json.JSONDecodeError):
        return []


def save_message(user_id: str, role: str, content: str) -> None:
    key = f"history:{user_id}"
    message = {"role": role, "content": content}
    try:
        redis_client.rpush(key, json.dumps(message))
        redis_client.expire(key, 60 * 60 * 24)
    except redis.RedisError:
        pass


def estimate_cost_from_usage(usage) -> float:
    """
    Lab-friendly estimation only.
    Không phải pricing chính thức.
    """
    if usage is None:
        return 0.001

    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0

    # Ước lượng nội bộ cho lab
    input_cost = input_tokens * 0.0000005
    output_cost = output_tokens * 0.0000015
    return round(input_cost + output_cost, 6)


def call_llm(question: str, history: List[dict]) -> tuple[str, float]:
    system_prompt = (
        "You are a helpful AI assistant. "
        "Answer clearly and concisely."
    )

    history_text = "\n".join(
        f"{item['role']}: {item['content']}" for item in history[-10:]
    )

    user_input = f"""
Conversation history:
{history_text}

Current user question:
{question}
""".strip()

    response = openai_client.responses.create(
        model=settings.LLM_MODEL,
        instructions=system_prompt,
        input=user_input
    )

    answer = getattr(response, "output_text", None)
    if not answer:
        answer = "I could not generate a response."

    cost_usd = estimate_cost_from_usage(getattr(response, "usage", None))
    return answer, cost_usd


@app.post("/ask")
def ask(
    question: str | None = None,
    body: AskRequest | None = Body(default=None),
    user_id: str = Depends(verify_api_key),
    _rate_limit: None = Depends(check_rate_limit),
    _budget: None = Depends(check_budget)
):
    final_question = question or (body.question if body else None)

    if not final_question or not final_question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    final_question = final_question.strip()
    history = get_conversation_history(user_id)

    try:
        answer, cost_usd = call_llm(final_question, history)
    except Exception as e:
        logger.error(f"OpenAI call failed: {str(e)}")
        raise HTTPException(status_code=500, detail="LLM call failed")

    save_message(user_id, "user", final_question)
    save_message(user_id, "assistant", answer)
    total_spend = record_cost(user_id, cost_usd)

    logger.info(f"Processed question for user_id={user_id}")

    return {
        "user_id": user_id,
        "question": final_question,
        "answer": answer,
        "history_count": len(history),
        "estimated_cost_usd": cost_usd,
        "daily_total_usd": total_spend,
    }