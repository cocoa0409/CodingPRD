"""Migration event endpoints: recalibration, consumption and voiding."""

from flask import Blueprint, request

from core import (
    DB, new_record, store, touch, ok, ok_list, resolve_actor, score_variant,
    migration_event, reason_code, body_of, reject_unknown, require_fields, as_int,
    as_str, as_enum, read_pagination, paginate, ordered_rows, now_iso,
)
from errors import ApiError
from calculations import cutoff_recalibration
from services import model_family_of_variant_id, recompute_license_window

bp = Blueprint("migration_events", __name__)

ALL_ROLES = [
    "BureauAdministrator", "ModelDeveloper", "ValidationAnalyst", "ComplianceOfficer",
    "FairLendingOfficer", "ScoreConsumer",
]

EVENT_TYPES = {"RECALIBRATED", "SNAPSHOT_COMPILED", "MIGRATED"}


@bp.post("/migration-events")
def create_migration_event():
    resolve_actor(request, ["ComplianceOfficer", "ModelDeveloper"])
    body = body_of(request)
    reject_unknown(body, {"lender_code", "from_score_variant_id", "to_score_variant_id",
                          "event_type", "evidence_ref", "old_cutoff_score",
                          "carried_decision_reason_code_id"})
    require_fields(body, ["lender_code", "from_score_variant_id", "to_score_variant_id",
                          "event_type", "evidence_ref"])

    lender_code = as_str(body["lender_code"], "lender_code")
    source = score_variant(as_str(body["from_score_variant_id"], "from_score_variant_id"))
    target = score_variant(as_str(body["to_score_variant_id"], "to_score_variant_id"))
    event_type = as_enum(body["event_type"], EVENT_TYPES, "event_type")
    evidence_ref = as_str(body["evidence_ref"], "evidence_ref")

    carried_id = body.get("carried_decision_reason_code_id")
    carried = None
    if carried_id is not None:
        carried = reason_code(as_str(carried_id, "carried_decision_reason_code_id"))
        if model_family_of_variant_id(carried["score_variant_id"]) != model_family_of_variant_id(target["id"]):
            raise ApiError("ERR_REASON_CODE_VARIANT_MISMATCH")

    source_model = DB["score_models"][source["score_model_id"]]
    target_model = DB["score_models"][target["score_model_id"]]

    rec = new_record(common=False)
    rec.update({
        "lender_code": lender_code,
        "from_score_variant_id": source["id"],
        "to_score_variant_id": target["id"],
        "event_type": event_type,
        "evidence_ref": evidence_ref,
        "carried_decision_reason_code_id": carried["id"] if carried else None,
        "credited_delta_bps": target["ref_score"] - source["ref_score"],
        "voided_at": None,
        "_consumed_by_license_id": None,
        "_recalibration_echoes": None,
    })

    score_preserving = None
    odds_preserving = None
    disagreement = None
    if event_type == "RECALIBRATED":
        old_cutoff = body.get("old_cutoff_score")
        old_cutoff = as_int(old_cutoff) if old_cutoff is not None else target["cutoff_baseline"]
        computed = cutoff_recalibration(source, source_model, target, target_model, old_cutoff)
        score_preserving = computed["new_cutoff_score_preserving"]
        odds_preserving = computed["new_cutoff_odds_preserving"]
        disagreement = computed["cutoff_disagreement_points"]
        rec["_recalibration_echoes"] = dict(computed)

    store("migration_events", rec)

    # PRD §2.2/§4: a create returns the created resource object; PRD §3.9 says the
    # recalibration event additionally "echoes" both competing cut-off conversions
    # for the reviewer.
    payload = dict(rec)
    if rec["_recalibration_echoes"] is not None:
        payload.update(rec["_recalibration_echoes"])
    return ok(payload, 201)


@bp.get("/migration-events/<event_id>")
def get_migration_event(event_id):
    resolve_actor(request, ALL_ROLES)
    return ok(migration_event(event_id))


@bp.get("/migration-events")
def list_migration_events():
    resolve_actor(request, ALL_ROLES)
    limit, offset = read_pagination(request)
    rows = ordered_rows("migration_events")

    for param in ("lender_code", "from_score_variant_id", "to_score_variant_id",
                  "carried_decision_reason_code_id", "event_type"):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r.get(param) == value]

    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/migration-events/<event_id>/void")
def void_migration_event(event_id):
    resolve_actor(request, ["ComplianceOfficer"])
    rec = migration_event(event_id)
    body = body_of(request)
    reject_unknown(body, set())

    if rec["voided_at"] is not None:
        raise ApiError("ERR_INVALID_STATE_MACHINE_EDGE")

    rec["voided_at"] = now_iso()
    license_id = rec.get("_consumed_by_license_id")
    if license_id and license_id in DB["licenses"]:
        license_rec = DB["licenses"][license_id]
        recompute_license_window(license_rec)
        touch(license_rec)
    return ok(rec)