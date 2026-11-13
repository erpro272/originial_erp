"""Short-lived signed links for stored files (invoice pages, originals).

<img src> can't send an Authorization header, so the API issues a token bound to the
tenant, the object key and an expiry, signed with HMAC-SHA256. Default lifetime 5 minutes.
"""

import base64
import hashlib
import hmac
import json
import time
import uuid

from app.core.config import get_settings


def _key() -> bytes:
    return hashlib.sha256(b"file-token|" + get_settings().jwt_secret.get_secret_value().encode()).digest()


def make(tenant_id: uuid.UUID, object_key: str, ttl: int | None = None) -> str:
    body = {
        "t": str(tenant_id),
        "k": object_key,
        "e": int(time.time()) + (ttl or get_settings().signed_url_ttl_seconds),
    }
    raw = base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(_key(), raw.encode(), hashlib.sha256).hexdigest()[:40]
    return f"{raw}.{sig}"


def verify(token: str) -> tuple[uuid.UUID, str] | None:
    try:
        raw, sig = token.rsplit(".", 1)
        good = hmac.new(_key(), raw.encode(), hashlib.sha256).hexdigest()[:40]
        if not hmac.compare_digest(sig, good):
            return None
        body = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        if int(body["e"]) < time.time():
            return None
        tenant = uuid.UUID(body["t"])
        key = str(body["k"])
        if not key.startswith(f"{tenant}/"):
            return None
        return tenant, key
    except (ValueError, KeyError, TypeError):
        return None
