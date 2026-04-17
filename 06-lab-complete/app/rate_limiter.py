import time
import redis
from fastapi import Depends, HTTPException

from .config import settings
from .auth import verify_api_key

r = redis.from_url(settings.REDIS_URL, decode_responses=True)


def check_rate_limit(user_id: str = Depends(verify_api_key)) -> None:
    now = time.time()
    window_start = now - 60
    key = f"rate_limit:{user_id}"

    try:
        pipe = r.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, 60)
        _, _, request_count, _ = pipe.execute()

        if request_count > settings.RATE_LIMIT_PER_MINUTE:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")

    except redis.RedisError:
        raise HTTPException(status_code=503, detail="Rate limiter unavailable")