"""ServiceScan and ResidentFine endpoints (PRD s3.5 scans, s3.6 tags and fines)."""

from flask import Blueprint

import shape
from authz import (
    admit,
    get_fine,
    get_resident,
    get_route,
    get_scan,
    night_of_route,
    own,
    property_of_night,
    property_of_route,
    require_property_owner,
)
from calc import (
    auto_fine_applies,
    compute_fine_amount,
    compute_offense_ordinal,
    fines_of_scan,
    has_escalated_jam,
    recompute_night_counters,
    remaining_fine_cap_cents,
    scans_of_route,
)
from envelope import array_response, object_response
from errors import ApiError
from rollups import apply_resident_ledger
from serializers import fine_out, scan_out
from shape import pagination, paginate, q
from store import MAX_DISPUTE_ROUNDS, db, now_iso, sort_rows, stamp_new, touch

bp = Blueprint("scan", __name__)

SCAN_RESULTS = ("SERVICED", "NO_SET_OUT", "TAGGED_NOT_SERVICED")
CONTAINER_TYPES = ("TRASH_BIN", "RECYCLING_BIN", "LOOSE_BAG")
NON_COMPLIANCE_TYPES = ("EARLY_SET_OUT", "IMPROPER_CONTAINER", "RECYCLING_CONTAMINATION")
OUTSTANDING_FINE_STATUSES = ("ASSESSED", "DISPUTED", "UPHELD")
TERMINAL_FINE = ("WAIVED", "VOIDED")


# ---------------------------------------------------------------------------
# Fine creation, shared by the AUTO cascade and the MANUAL assessment
# ---------------------------------------------------------------------------
def _create_fine(scan, night, resident, origin, assessed_by_user_id):
    amounts = compute_fine_amount(scan, night, resident)
    row = {
        "scan_id": scan["id"],
        "resident_id": resident["id"],
        "tag_type": scan["non_compliance_type"],
        "offense_ordinal": scan["offense_ordinal"],
        "base_cents": amounts["base_cents"],
        "escalation_multiplier": amounts["escalation_multiplier"],
        "seasonal_uplift_applied": amounts["seasonal_uplift_applied"],
        "amount_cents": amounts["amount_cents"],
        "uncapped_amount_cents": amounts["uncapped_amount_cents"],
        "origin": origin,
        "status": "ASSESSED",
        "dispute_round": 0,
        "assessed_by_user_id": assessed_by_user_id,
        "adjudicated_by_user_id": None,
        "dispute_reason": None,
    }
    stamp_new(row)
    db.fines[row["id"]] = row
    return row


# ---------------------------------------------------------------------------
# ServiceScan
# ---------------------------------------------------------------------------
@bp.route("/valet/route-assignments/<route_id>/scans", methods=["POST"])
def create_scan(route_id):
    actor = admit(("Valet",))
    route = get_route(route_id)
    own(actor.user_id == route["contractor_id"])
    body = shape.body()
    resident_id = shape.req_str(body, "resident_id", min_len=1, non_blank=True)
    scan_result = shape.req_enum(body, "scan_result", SCAN_RESULTS)
    container_type = shape.req_enum(body, "container_type", CONTAINER_TYPES)
    non_compliance_type = shape.opt_enum(body, "non_compliance_type", NON_COMPLIANCE_TYPES)

    # rung 6
    resident = get_resident(resident_id)

    night = night_of_route(route)
    prop = property_of_night(night) if night is not None else None

    # rung 7
    if prop is None or resident["property_id"] != prop["id"]:
        raise ApiError("ERR_CROSS_PROPERTY_REFERENCE")

    # rung 8
    if route["status"] in ("COMPLETED", "ABANDONED", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if route["status"] not in ("ACCEPTED", "IN_PROGRESS"):
        raise ApiError("ERR_INVALID_STATE")

    # rung 9
    if prop["status"] in ("SUSPENDED", "TERMINATED"):
        raise ApiError("ERR_PROPERTY_SUSPENDED")

    # rung 12
    if has_escalated_jam(prop["id"]):
        raise ApiError("ERR_COMPACTOR_BLOCKED")

    # rung 22
    if resident["unit_number"] < route["unit_from"] or resident["unit_number"] > route["unit_to"]:
        raise ApiError("ERR_UNIT_NOT_IN_ROUTE")

    # rung 23
    for other in scans_of_route(route["id"]):
        if other["resident_id"] == resident["id"]:
            raise ApiError("ERR_DUPLICATE_SCAN")

    ordinal = compute_offense_ordinal(resident["id"], non_compliance_type)
    row = {
        "route_assignment_id": route["id"],
        "service_night_id": route["service_night_id"],
        "resident_id": resident["id"],
        "scan_result": scan_result,
        "container_type": container_type,
        "non_compliance_type": non_compliance_type,
        "tag_status": "OPEN" if non_compliance_type else "NONE",
        "offense_ordinal": ordinal,
        "scanned_at": now_iso(),
        "void_reason": None,
    }
    stamp_new(row)
    db.scans[row["id"]] = row

    # route rollup
    route["scan_count"] = route["scan_count"] + 1
    if route["status"] == "ACCEPTED":
        route["status"] = "IN_PROGRESS"
    touch(route)

    # night rollups
    if night["verification_status"] == "SCHEDULED":
        night["verification_status"] = "IN_PROGRESS"
    recompute_night_counters(night)
    touch(night)

    # AUTO fine cascade -- silently skipped when the resident cannot be billed
    if auto_fine_applies(row):
        if resident["fee_passthrough_enabled"] and remaining_fine_cap_cents(resident["id"]) > 0:
            _create_fine(row, night, resident, "AUTO", "system")
            row["tag_status"] = "FINED"
            apply_resident_ledger(resident)

    return object_response(scan_out(row), 201)


@bp.route("/valet/service-scans/<scan_id>", methods=["GET"])
def read_scan(scan_id):
    admit((
        "PlatformAdmin",
        "ValetOpsManager",
        "PropertyManager",
        "ComplianceOfficer",
        "Valet",
        "Resident",
    ))
    row = get_scan(scan_id)
    return object_response(scan_out(row))


@bp.route("/valet/service-scans", methods=["GET"])
def list_scans():
    admit((
        "PlatformAdmin",
        "ValetOpsManager",
        "PropertyManager",
        "ComplianceOfficer",
        "Valet",
        "Resident",
    ))
    limit, offset = pagination()
    f_route = q("route_assignment_id")
    f_night = q("service_night_id")
    f_resident = q("resident_id")
    f_result = q("scan_result")
    f_tag = q("tag_status")
    f_type = q("non_compliance_type")
    rows = sort_rows(list(db.scans.values()))
    if f_route is not None:
        rows = [r for r in rows if r["route_assignment_id"] == f_route]
    if f_night is not None:
        rows = [r for r in rows if r["service_night_id"] == f_night]
    if f_resident is not None:
        rows = [r for r in rows if r["resident_id"] == f_resident]
    if f_result is not None:
        rows = [r for r in rows if r["scan_result"] == f_result]
    if f_tag is not None:
        rows = [r for r in rows if r["tag_status"] == f_tag]
    if f_type is not None:
        rows = [r for r in rows if r["non_compliance_type"] == f_type]
    page, total, has_more = paginate(rows, limit, offset)
    return array_response([scan_out(r) for r in page], limit, offset, total, has_more)


@bp.route("/valet/service-scans/<scan_id>/fine", methods=["POST"])
def assess_fine(scan_id):
    actor = admit(("PropertyManager",))
    scan = get_scan(scan_id)
    resident = db.residents.get(scan["resident_id"])
    require_property_owner(actor, resident["property_id"] if resident else None)
    body = shape.body()
    shape.opt_str(body, "note", max_len=500)

    # rung 8 -- the ERR_TAG_NOT_FINEABLE specialisation
    if scan["tag_status"] != "OPEN":
        raise ApiError("ERR_TAG_NOT_FINEABLE")

    # rung 27
    if not resident["fee_passthrough_enabled"]:
        raise ApiError("ERR_PASSTHROUGH_DISABLED")

    # rung 28
    if remaining_fine_cap_cents(resident["id"]) <= 0:
        raise ApiError("ERR_FINE_CAP_EXHAUSTED")

    night = db.nights.get(scan["service_night_id"])
    fine = _create_fine(scan, night, resident, "MANUAL", actor.user_id)
    scan["tag_status"] = "FINED"
    touch(scan)
    apply_resident_ledger(resident)
    return object_response(fine_out(fine), 201)


@bp.route("/valet/service-scans/<scan_id>/void-tag", methods=["POST"])
def void_tag(scan_id):
    actor = admit(("PropertyManager",))
    scan = get_scan(scan_id)
    resident = db.residents.get(scan["resident_id"])
    require_property_owner(actor, resident["property_id"] if resident else None)
    body = shape.body()
    reason = shape.req_str(body, "reason", min_len=1, max_len=500, non_blank=True)

    # rung 8
    if scan["tag_status"] == "VOIDED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if scan["tag_status"] not in ("OPEN", "FINED"):
        raise ApiError("ERR_INVALID_STATE")

    scan["tag_status"] = "VOIDED"
    scan["void_reason"] = reason
    touch(scan)

    voided_any = False
    for fine in fines_of_scan(scan["id"]):
        if fine["status"] in OUTSTANDING_FINE_STATUSES:
            fine["status"] = "VOIDED"
            touch(fine)
            voided_any = True
    if voided_any and resident is not None:
        apply_resident_ledger(resident)
    return object_response(scan_out(scan))


# ---------------------------------------------------------------------------
# ResidentFine
# ---------------------------------------------------------------------------
@bp.route("/valet/resident-fines/<fine_id>", methods=["GET"])
def read_fine(fine_id):
    admit((
        "PlatformAdmin",
        "PropertyManager",
        "BillingAnalyst",
        "ComplianceOfficer",
        "Resident",
    ))
    row = get_fine(fine_id)
    return object_response(fine_out(row))


@bp.route("/valet/resident-fines", methods=["GET"])
def list_fines():
    admit((
        "PlatformAdmin",
        "PropertyManager",
        "BillingAnalyst",
        "ComplianceOfficer",
        "Resident",
    ))
    limit, offset = pagination()
    f_resident = q("resident_id")
    f_scan = q("scan_id")
    f_status = q("status")
    f_origin = q("origin")
    rows = sort_rows(list(db.fines.values()))
    if f_resident is not None:
        rows = [r for r in rows if r["resident_id"] == f_resident]
    if f_scan is not None:
        rows = [r for r in rows if r["scan_id"] == f_scan]
    if f_status is not None:
        rows = [r for r in rows if r["status"] == f_status]
    if f_origin is not None:
        rows = [r for r in rows if r["origin"] == f_origin]
    page, total, has_more = paginate(rows, limit, offset)
    return array_response([fine_out(r) for r in page], limit, offset, total, has_more)


@bp.route("/valet/resident-fines/<fine_id>/dispute", methods=["POST"])
def dispute_fine(fine_id):
    actor = admit(("Resident",))
    fine = get_fine(fine_id)
    own(actor.user_id == fine["resident_id"])
    body = shape.body()
    reason = shape.req_str(body, "reason", min_len=1, max_len=500, non_blank=True)

    # rung 8
    if fine["status"] in TERMINAL_FINE:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if fine["status"] not in ("ASSESSED", "UPHELD"):
        raise ApiError("ERR_INVALID_STATE")

    # rung 24
    if fine["dispute_round"] >= MAX_DISPUTE_ROUNDS:
        raise ApiError("ERR_DISPUTE_ROUNDS_EXHAUSTED")

    fine["status"] = "DISPUTED"
    fine["dispute_round"] = fine["dispute_round"] + 1
    fine["dispute_reason"] = reason
    touch(fine)
    return object_response(fine_out(fine))


@bp.route("/valet/resident-fines/<fine_id>/adjudicate", methods=["POST"])
def adjudicate_fine(fine_id):
    actor = admit(("PropertyManager",))
    fine = get_fine(fine_id)
    resident = db.residents.get(fine["resident_id"])
    require_property_owner(actor, resident["property_id"] if resident else None)
    body = shape.body()
    outcome = shape.req_enum(body, "outcome", ("UPHELD", "WAIVED"))
    shape.opt_str(body, "note", max_len=500)

    # rung 8
    if fine["status"] in TERMINAL_FINE:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if fine["status"] != "DISPUTED":
        raise ApiError("ERR_INVALID_STATE")

    fine["status"] = outcome
    fine["adjudicated_by_user_id"] = actor.user_id
    touch(fine)

    if outcome == "WAIVED" and resident is not None:
        apply_resident_ledger(resident)
    return object_response(fine_out(fine))
