import os
import redis
import json


def get_redis_connection():
    """Return Redis connection if available, otherwise None."""
    redis_url = os.getenv("REDIS_URL")  # e.g. redis://localhost:6379

    if not redis_url:
        return None

    try:
        r = redis.from_url(redis_url, decode_responses=True)
        # test connection
        r.ping()
        return r
    except Exception:
        return None


TTL_DAYS = 5
TTL_SECONDS = TTL_DAYS * 24 * 60 * 60
REDIS_KEY_PREFIX = "processed_email:"


def mark_processed(r, message_id):
    """Store processed message ID with TTL."""
    r.setex(f"{REDIS_KEY_PREFIX}{message_id}", TTL_SECONDS, "1")


def is_processed(r, message_id):
    """Check if message was processed in Redis."""
    return r.exists(f"{REDIS_KEY_PREFIX}{message_id}") == 1


PROCESSED_FILE = "processed.json"

def load_from_file():
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_to_file(processed_ids):
    with open(PROCESSED_FILE, "w") as f:
        json.dump(list(processed_ids), f)
