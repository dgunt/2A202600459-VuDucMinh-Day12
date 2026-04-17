from datetime import datetime
import redis
from fastapi import Depends, HTTPException

from .config import settings
from .auth import verify_api_key

r = redis.from_url(settings.REDIS_URL, decode_responses=True)


def _daily_budget_key(user_id: str) -> str:
    day = datetime.utcnow().strftime("%Y-%m-%d")
    return f"budget:{user_id}:{day}"


def check_budget(user_id: str = Depends(verify_api_key)) -> None:
    key = _daily_budget_key(user_id)

    try:
        current_spend = r.get(key)
        current_spend = float(current_spend) if current_spend else 0.0

        if current_spend >= settings.DAILY_BUDGET_USD:
            raise HTTPException(status_code=402, detail="Daily budget exceeded")

    except redis.RedisError:
        raise HTTPException(status_code=503, detail="Budget checker unavailable")


def record_cost(user_id: str, amount_usd: float) -> float | None:
    key = _daily_budget_key(user_id)
    try:
        new_total = r.incrbyfloat(key, amount_usd)
        r.expire(key, 60 * 60 * 24 * 2)
        return new_total
    except redis.RedisError:
        return None