"""The association logical clock and its credential-expiry checkpoint."""
from flask import Blueprint

from core import DB, auth, body, ok, fail, parse_dt, touch, now_date
import domain

bp = Blueprint("clock", __name__)


@bp.post("/athletics/_clock/set_current_utc")
def set_clock():
    auth(["AssociationAdmin"])
    b = body()
    raw = b.get("to_iso8601")
    instant = parse_dt(raw)
    if instant is None:
        fail("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 UTC instant")

    DB.clock = instant
    today = now_date()

    expired_credential_count = 0
    creds = sorted(DB.credentials.values(), key=lambda c: (c["created_at"], c["_seq"]))
    for cred in creds:
        if cred["status"] != "CLEARED":
            continue
        if cred["certification_expires_on"] > today:
            continue
        cred["status"] = "EXPIRED"
        touch(cred)
        expired_credential_count += 1
        school = DB.schools.get(cred["school_id"])
        if school is not None:
            domain.apply_credential_lost(cred, school)

    expired_document_count = sum(
        1 for d in DB.documents.values() if d["expires_on"] < today)

    return ok({
        "current_utc": instant.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (instant.microsecond // 1000),
        "expired_credential_count": expired_credential_count,
        "expired_document_count": expired_document_count,
    })
