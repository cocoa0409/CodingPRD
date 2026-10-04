"""ImportEntry lifecycle and SampleAnalysis (PRD sections 3.4, 3.5, 3.6).

ImportEntry has two parallel state dimensions: review_status
(PENDING_SCREENING -> SCREENED) and disposition_status (PENDING -> DETAINED ->
RELEASED | REFUSED | EXPORTED | RECONDITIONED). SampleAnalysis: SCHEDULED ->
RESULT_RECORDED. Every resolution preserves the entry-units conservation
invariant (services.detain_entry / release_* / refuse_entry).
"""
from flask import Blueprint, request

import db
import serialize
import services
from auth import require_roles, ALL_ROLES
from envelope import ok, ok_list, json_body
from errors import ApiError
from pagination import page_params, paginate

bp = Blueprint("entries", __name__)


def _get_entry_or_404(entry_id):
    e = db.entries.get(entry_id)
    if e is None:
        raise ApiError("ERR_ENTRY_NOT_FOUND")
    return e


def _entry_samples(entry_id):
    return sorted(
        (s for s in db.samples.values() if s["entry_id"] == entry_id),
        key=db.sort_key,
    )


@bp.post("/registry/entries")
@require_roles("Importer")
def create_entry(caller_id, caller_role):
    body = json_body()
    prior_notice_id = body.get("prior_notice_id")
    # Tier 4: the referenced prior notice must resolve.
    p = db.prior_notices.get(prior_notice_id) if isinstance(prior_notice_id, str) else None
    if prior_notice_id is not None and p is None:
        raise ApiError("ERR_PRIOR_NOTICE_NOT_FOUND")
    # Tier 3: ownership — the caller owns entries through the notice importer.
    if p is not None and p["importer_id"] != caller_id:
        raise ApiError("ERR_OWNERSHIP_VIOLATION")
    # Tier 5: notice CONFIRMED (exactly one entry may consume a notice);
    # importer standing gate.
    if p is not None and p["status"] != "CONFIRMED":
        raise ApiError("ERR_PN_NOT_CONFIRMED")
    importer = db.importers.get(p["importer_id"]) if p is not None else None
    if importer is not None and importer["standing"] == "REVOKED":
        raise ApiError("ERR_IMPORTER_REVOKED")
    # Tier 6: registration gate, then the CLASS_I recall safety gate.
    facility = db.facilities.get(p["facility_id"]) if p is not None else None
    if facility is not None and facility["registration_status"] != "REGISTERED":
        raise ApiError("ERR_REGISTRATION_NOT_ACTIVE")
    if p is not None and services.recall_gate_blocks(p["facility_id"], p["product_code"]):
        raise ApiError("ERR_ACTIVE_RECALL_BLOCKS_ENTRY")
    # Tier 12: prior_notice_id is required.
    if p is None:
        raise ApiError("ERR_INVALID_REQUEST", "prior_notice_id is required and must resolve")

    now = db.now()
    e = db.new_common()
    e.update(
        {
            "prior_notice_id": p["id"],
            "importer_id": p["importer_id"],
            "facility_id": p["facility_id"],
            "product_code": p["product_code"],
            "product_risk_class": p["product_risk_class"],
            "declared_units": p["declared_units"],
            "unit_value_cents": p["unit_value_cents"],
            "is_amendment_pn": p["is_amendment"],
            "review_status": "PENDING_SCREENING",
            "disposition_status": "PENDING",
            "screening_decision": "NONE",
            "screening_score": None,
            "scoring_variant_applied": None,
            "probation_adjustment_applied": 0,
            "detained_at": None,
            "response_deadline_at": None,
            "detained_under_alert_id": None,
            "units_held": 0,
            "units_released": 0,
            "units_refused": 0,
            "units_exported": 0,
            "units_destroyed": 0,
            "bond_amount_cents": None,
            "disposition_completed_at": None,
        }
    )
    db.entries[e["id"]] = e
    p["status"] = "CONSUMED"
    db.touch(p, now)
    return ok(serialize.entry(e), 201)


@bp.get("/registry/entries/<eid>")
@require_roles(*ALL_ROLES)
def get_entry(eid, caller_id, caller_role):
    return ok(serialize.entry(_get_entry_or_404(eid)))


@bp.get("/registry/entries")
@require_roles(*ALL_ROLES)
def list_entries(caller_id, caller_role):
    limit, offset = page_params()
    items = list(db.entries.values())
    for field in (
        "facility_id",
        "importer_id",
        "prior_notice_id",
        "detained_under_alert_id",
        "disposition_status",
        "review_status",
    ):
        value = request.args.get(field)
        if value is not None:
            items = [e for e in items if e[field] == value]
    items.sort(key=db.sort_key)
    total, page = paginate(items, limit, offset)
    return ok_list([serialize.entry(e) for e in page], total, limit, offset)


@bp.post("/registry/entries/<eid>/screen")
@require_roles("EntryReviewer")
def screen_entry(eid, caller_id, caller_role):
    e = _get_entry_or_404(eid)
    # Tier 5: screening only while PENDING_SCREENING.
    if e["review_status"] != "PENDING_SCREENING":
        raise ApiError("ERR_ENTRY_INVALID_STATE")
    now = db.now()
    score, variant, probation, alert = services.screen_score(e)
    e["screening_score"] = score
    e["scoring_variant_applied"] = variant
    e["probation_adjustment_applied"] = probation
    e["review_status"] = "SCREENED"
    if alert is not None:
        # Detention without physical examination under the earliest-created
        # matching ACTIVE alert; the score is stored regardless.
        e["screening_decision"] = "DETAIN"
        # §3.6: an entry already DETAINED (e.g. by an alert-placement or
        # inspection-refusal cascade while still PENDING_SCREENING) is never
        # re-detained — its detained_at/deadline/attribution stand.
        if e["disposition_status"] == "PENDING":
            services.detain_entry(e, alert["id"], now)
        else:
            db.touch(e, now)
    elif score >= services.SAMPLE_THRESHOLD:
        e["screening_decision"] = "SAMPLE"
        db.touch(e, now)
    else:
        e["screening_decision"] = "RELEASE"
        # The RELEASE self-execution is a disposition-dimension effect and
        # fires only from PENDING: on an already-DETAINED entry the review
        # decision is stored but the detention stands (release from DETAINED
        # is reserved to a ComplianceOfficer, §3.6), and on an already-
        # terminal entry the terminal outcome must not be applied twice.
        if e["disposition_status"] == "PENDING":
            e["disposition_status"] = "RELEASED"
            e["units_released"] = e["declared_units"]
            e["disposition_completed_at"] = now
            services.apply_terminal_outcome(db.importers[e["importer_id"]], refused=False)
        db.touch(e, now)
    return ok(serialize.entry(e))


@bp.post("/registry/entries/<eid>/record-sample")
@require_roles("EntryReviewer")
def record_sample(eid, caller_id, caller_role):
    e = _get_entry_or_404(eid)
    body = json_body()
    lab_code = body.get("lab_code")
    lab = None
    if isinstance(lab_code, str):
        for candidate in db.laboratories.values():
            if candidate["lab_code"] == lab_code:
                lab = candidate
                break
    # Tier 4: the body-referenced laboratory must exist.
    if lab_code is not None and lab is None:
        raise ApiError("ERR_LAB_NOT_FOUND")
    # Tier 5: entry must be SCREENED / SAMPLE / PENDING.
    if not (
        e["review_status"] == "SCREENED"
        and e["screening_decision"] == "SAMPLE"
        and e["disposition_status"] == "PENDING"
    ):
        raise ApiError("ERR_ENTRY_INVALID_STATE")
    # Tier 7: analysis_date must not precede the current logical date.
    analysis_date = db.parse_date(body.get("analysis_date"))
    if analysis_date is not None and analysis_date < db.now().date():
        raise ApiError("ERR_SAMPLE_DATE_PAST")
    # Tier 9: aggregate lab-day capacity.
    sample_units = body.get("sample_units")
    if lab is not None and analysis_date is not None and services.is_int(sample_units) and sample_units > 0:
        scheduled = sum(
            s["sample_units"]
            for s in db.samples.values()
            if s["lab_code"] == lab["lab_code"] and s["analysis_date"] == body["analysis_date"]
        )
        if scheduled + sample_units > lab["daily_sample_capacity"]:
            raise ApiError("ERR_LAB_CAPACITY_EXCEEDED")
    # Tier 12: request shape.
    if not isinstance(lab_code, str) or not lab_code:
        raise ApiError("ERR_INVALID_REQUEST", "lab_code is required")
    if not services.is_int(sample_units) or sample_units <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "sample_units must be an integer greater than 0")
    if analysis_date is None:
        raise ApiError("ERR_INVALID_REQUEST", "analysis_date must be a YYYY-MM-DD date")

    s = db.new_common()
    s.update(
        {
            "entry_id": e["id"],
            "lab_code": lab_code,
            "sample_units": sample_units,
            "analysis_date": body["analysis_date"],
            "status": "SCHEDULED",
            "result": "PENDING",
        }
    )
    db.samples[s["id"]] = s
    return ok(serialize.sample(s), 201)


@bp.get("/registry/entries/<eid>/samples")
@require_roles(*ALL_ROLES)
def list_entry_samples(eid, caller_id, caller_role):
    _get_entry_or_404(eid)
    limit, offset = page_params()
    items = _entry_samples(eid)
    total, page = paginate(items, limit, offset)
    return ok_list([serialize.sample(s) for s in page], total, limit, offset)


@bp.post("/registry/samples/<sid>/record-result")
@require_roles("EntryReviewer")
def record_result(sid, caller_id, caller_role):
    s = db.samples.get(sid)
    if s is None:
        raise ApiError("ERR_SAMPLE_NOT_FOUND")
    # Tier 5: only a SCHEDULED sample accepts a result.
    if s["status"] != "SCHEDULED":
        raise ApiError("ERR_ENTRY_INVALID_STATE")
    # Tier 12: result must be exactly COMPLIANT or VIOLATIVE.
    result = json_body().get("result")
    if result not in ("COMPLIANT", "VIOLATIVE"):
        raise ApiError("ERR_INVALID_REQUEST", "result must be COMPLIANT or VIOLATIVE")
    now = db.now()
    s["status"] = "RESULT_RECORDED"
    s["result"] = result
    db.touch(s, now)
    if result == "VIOLATIVE":
        # For-cause detention of the owning entry, only while still PENDING.
        e = db.entries.get(s["entry_id"])
        if e is not None and e["disposition_status"] == "PENDING":
            services.detain_entry(e, None, now)
    return ok(serialize.sample(s))


@bp.post("/registry/entries/<eid>/release")
@require_roles("EntryReviewer", "ComplianceOfficer")
def release_entry(eid, caller_id, caller_role):
    e = _get_entry_or_404(eid)
    now = db.now()
    if e["disposition_status"] == "DETAINED":
        # Releasing from detention is reserved to ComplianceOfficer.
        if caller_role != "ComplianceOfficer":
            raise ApiError(
                "ERR_FORBIDDEN",
                "A DETAINED entry may be released only by a ComplianceOfficer",
            )
        services.release_detained(e, now)
        return ok(serialize.entry(e))
    if e["disposition_status"] == "PENDING":
        # SAMPLE-decision entries need a COMPLIANT result and no unreconciled
        # pending or VIOLATIVE analyses.
        linked = _entry_samples(eid)
        releasable = (
            e["screening_decision"] == "SAMPLE"
            and any(s["result"] == "COMPLIANT" for s in linked)
            and not any(s["status"] == "SCHEDULED" for s in linked)
            and not any(s["result"] == "VIOLATIVE" for s in linked)
        )
        if not releasable:
            raise ApiError("ERR_ENTRY_INVALID_STATE")
        services.release_pending(e, now)
        return ok(serialize.entry(e))
    # Terminal (or otherwise non-releasable) dispositions.
    raise ApiError("ERR_ENTRY_INVALID_STATE")


@bp.post("/registry/entries/<eid>/request-reconditioning")
@require_roles("Importer")
def request_reconditioning(eid, caller_id, caller_role):
    e = _get_entry_or_404(eid)
    # Tier 3: ownership.
    if e["importer_id"] != caller_id:
        raise ApiError("ERR_OWNERSHIP_VIOLATION")
    # Tier 5: only a DETAINED entry may be reconditioned.
    if e["disposition_status"] != "DETAINED":
        raise ApiError("ERR_ENTRY_INVALID_STATE")
    # Tier 7: the response deadline is inclusive.
    now = db.now()
    if now > e["response_deadline_at"]:
        raise ApiError("ERR_DETENTION_RESPONSE_DEADLINE_PASSED")
    # Tier 12: lots non-empty, positive quantities, non-negative values.
    body = json_body()
    lots = body.get("lots")
    if not isinstance(lots, list) or len(lots) == 0:
        raise ApiError("ERR_INVALID_REQUEST", "lots must be a non-empty array")
    for lot in lots:
        if not isinstance(lot, dict):
            raise ApiError("ERR_INVALID_REQUEST", "each lot must be an object")
        if not services.is_int(lot.get("quantity")) or lot["quantity"] <= 0:
            raise ApiError("ERR_INVALID_REQUEST", "each lot quantity must be an integer > 0")
        if not services.is_int(lot.get("unit_value_cents")) or lot["unit_value_cents"] < 0:
            raise ApiError("ERR_INVALID_REQUEST", "each lot unit_value_cents must be an integer >= 0")
    e["bond_amount_cents"] = services.compute_bond(lots, e, now)
    db.touch(e, now)
    return ok(serialize.entry(e))


@bp.post("/registry/entries/<eid>/record-reconditioning-outcome")
@require_roles("ComplianceOfficer")
def record_reconditioning_outcome(eid, caller_id, caller_role):
    e = _get_entry_or_404(eid)
    # Tier 5: DETAINED with a bond on file.
    if e["disposition_status"] != "DETAINED" or e["bond_amount_cents"] is None:
        raise ApiError("ERR_ENTRY_INVALID_STATE")
    body = json_body()
    units_passed = body.get("units_passed")
    units_failed = body.get("units_failed")
    # Tier 9: unit accounting (non-negative and summing exactly to held).
    if services.is_int(units_passed) and services.is_int(units_failed):
        if units_passed < 0 or units_failed < 0 or units_passed + units_failed != e["units_held"]:
            raise ApiError("ERR_UNITS_ACCOUNTING_MISMATCH")
    # Tier 12: both fields required as integers.
    if not services.is_int(units_passed) or not services.is_int(units_failed):
        raise ApiError("ERR_INVALID_REQUEST", "units_passed and units_failed must be integers")

    now = db.now()
    facility = db.facilities[e["facility_id"]]
    e["units_released"] += units_passed
    e["units_destroyed"] += units_failed
    e["units_held"] = 0
    facility["open_detention_count"] -= 1
    importer = db.importers[e["importer_id"]]
    if units_failed == 0:
        e["disposition_status"] = "RECONDITIONED"
        e["disposition_completed_at"] = now
        db.touch(facility, now)
        db.touch(e, now)
        services.apply_terminal_outcome(importer, refused=False)
    else:
        # Any failed unit makes the whole entry count as a refusal.
        e["disposition_status"] = "REFUSED"
        e["disposition_completed_at"] = now
        facility["violation_count"] += 1
        db.touch(facility, now)
        db.touch(e, now)
        services.apply_terminal_outcome(importer, refused=True)
    return ok(serialize.entry(e))


@bp.post("/registry/entries/<eid>/export")
@require_roles("Importer")
def export_entry(eid, caller_id, caller_role):
    e = _get_entry_or_404(eid)
    # Tier 3: ownership.
    if e["importer_id"] != caller_id:
        raise ApiError("ERR_OWNERSHIP_VIOLATION")
    # Tier 5: only a DETAINED entry may be exported.
    if e["disposition_status"] != "DETAINED":
        raise ApiError("ERR_ENTRY_INVALID_STATE")
    # Tier 7: the response deadline is inclusive.
    now = db.now()
    if now > e["response_deadline_at"]:
        raise ApiError("ERR_DETENTION_RESPONSE_DEADLINE_PASSED")
    facility = db.facilities[e["facility_id"]]
    e["units_exported"] += e["units_held"]
    e["units_held"] = 0
    facility["open_detention_count"] -= 1
    db.touch(facility, now)
    e["disposition_status"] = "EXPORTED"
    e["disposition_completed_at"] = now
    db.touch(e, now)
    # EXPORTED is terminal but is not a refusal.
    services.apply_terminal_outcome(db.importers[e["importer_id"]], refused=False)
    return ok(serialize.entry(e))


@bp.post("/registry/entries/<eid>/refuse")
@require_roles("ComplianceOfficer")
def refuse_entry_endpoint(eid, caller_id, caller_role):
    e = _get_entry_or_404(eid)
    # Tier 5: only a DETAINED entry may be refused.
    if e["disposition_status"] != "DETAINED":
        raise ApiError("ERR_ENTRY_INVALID_STATE")
    services.refuse_entry(e, db.now())
    return ok(serialize.entry(e))
