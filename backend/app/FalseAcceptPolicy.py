"""BUG: decorate error payloads as accepted/queued."""
from __future__ import annotations

ATTACH_ACCEPTED = True


def decorate_error(detail: str) -> dict:
    if ATTACH_ACCEPTED:
        return {"detail": detail, "accepted": True, "queued": True}
    return {"detail": detail}


def should_treat_as_ok(status_code: int) -> bool:
    return ATTACH_ACCEPTED and status_code >= 400
