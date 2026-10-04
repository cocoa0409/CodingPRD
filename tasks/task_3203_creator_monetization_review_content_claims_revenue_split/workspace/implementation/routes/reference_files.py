"""Reference files and the retroactive capture of already-classified items."""

from flask import Blueprint

import db
from errors import raise_error
from middleware import require_role
from response import ok
from routes.common import body, get_reference_file, paginated, sort_by_created_at
from services import content as content_svc

bp = Blueprint("reference_files", __name__, url_prefix="/api")


def _fingerprint_taken(fingerprint):
    return db.find_first("reference_files", reference_fingerprint=fingerprint) is not None


@bp.post("/reference-files")
def register_reference_file():
    require_role("RightsHolder", "PlatformAdmin")
    payload = body()

    fingerprint = payload.get("reference_fingerprint")
    if fingerprint is None:
        raise_error("ERR_INVALID_STATE", "reference_fingerprint is required.")
    if _fingerprint_taken(fingerprint):
        raise_error("ERR_DUPLICATE_REFERENCE_FINGERPRINT")

    reference = db.common_fields(
        {
            "rights_holder_name": payload.get("rights_holder_name"),
            "asset_kind": payload.get("asset_kind"),
            "reference_fingerprint": fingerprint,
            "policy_mode": payload.get("policy_mode"),
            "claimed_segment_seconds": int(payload.get("claimed_segment_seconds") or 0),
            "is_active": bool(payload.get("is_active", True)),
        }
    )
    db.insert("reference_files", reference)

    # Retroactive capture: every CLASSIFIED item whose fingerprint matches at or
    # above 0.500 is settled forward and claimed (PRD section 3.4).
    for item in db.all_of("content_items"):
        if item["upload_status"] != "CLASSIFIED":
            continue
        score = content_svc.reference_match_score(item, reference)
        if score < content_svc.MATCH_THRESHOLD:
            continue
        # PRD section 3.4: "if the channel's posture is `OPEN` ... that claim is
        # `ACTIVE` with `lock_reason` set to `PENDING_RETRO`".  The whole
        # retroactive capture is written under that `OPEN` condition, so a
        # channel the posture recomputation has narrowed or frozen does not
        # capture the reference at all.
        channel = db.get("channels", item["channel_id"])
        if channel is None or channel.get("monetization_posture") != "OPEN":
            continue
        content_svc.create_auto_claim(item, reference, score)
        item["upload_status"] = "CLAIM_SCAN_COMPLETE"
        content_svc.recompute_item(item)
        db.touch(item)

    db.touch(reference)
    return ok(dict(reference), 201)


@bp.get("/reference-files")
def list_reference_files():
    require_role("Any")
    rows = sort_by_created_at(db.all_of("reference_files"))
    return paginated([dict(r) for r in rows])


@bp.get("/reference-files/<reference_file_id>")
def get_one_reference_file(reference_file_id):
    require_role("Any")
    return ok(dict(get_reference_file(reference_file_id)))