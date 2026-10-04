"""Consumer endpoints."""

from flask import Blueprint, request

from core import (
    DB, new_record, store, ok, ok_list, resolve_actor, consumer,
    body_of, reject_unknown, require_fields, as_int, as_str, as_bool,
    read_pagination, paginate, ordered_rows,
)
from errors import ApiError

bp = Blueprint("consumers", __name__)

ALL_ROLES = [
    "BureauAdministrator", "ModelDeveloper", "ValidationAnalyst", "ComplianceOfficer",
    "FairLendingOfficer", "ReasonCodeAdministrator", "ScoreConsumer",
]


@bp.post("/consumers")
def create_consumer():
    resolve_actor(request, ["ModelDeveloper", "ValidationAnalyst", "FairLendingOfficer",
                            "ReasonCodeAdministrator"])
    body = body_of(request)
    reject_unknown(body, {"consumer_ref", "age_years", "is_protected_class"})
    require_fields(body, ["consumer_ref", "age_years"])

    consumer_ref = as_str(body["consumer_ref"], "consumer_ref")

    # Priority 12 (uniqueness) is evaluated before priority 14 (magnitude bounds).
    for existing in DB["consumers"].values():
        if existing["consumer_ref"] == consumer_ref:
            raise ApiError("ERR_DUPLICATE_CONSUMER_REF")

    age_years = as_int(body["age_years"])
    if age_years < 18 or age_years > 120:
        raise ApiError("ERR_INVALID_REQUEST", "age_years must lie between 18 and 120.")
    is_protected_class = as_bool(body["is_protected_class"]) if "is_protected_class" in body else False

    rec = new_record()
    rec.update({
        "consumer_ref": consumer_ref,
        "age_years": age_years,
        "is_protected_class": is_protected_class,
        "model_undecided_count": 0,
        "latest_uploaded_at": None,
    })
    store("consumers", rec)
    return ok(rec, 201)


@bp.get("/consumers/<consumer_id>")
def get_consumer(consumer_id):
    resolve_actor(request, ALL_ROLES)
    return ok(consumer(consumer_id))


@bp.get("/consumers")
def list_consumers():
    resolve_actor(request, ALL_ROLES)
    limit, offset = read_pagination(request)
    rows = ordered_rows("consumers")

    ref = request.args.get("consumer_ref")
    if ref is not None:
        rows = [r for r in rows if r["consumer_ref"] == ref]
    protected = request.args.get("is_protected_class")
    if protected is not None:
        wanted = as_bool(protected)
        rows = [r for r in rows if r["is_protected_class"] is wanted]

    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)