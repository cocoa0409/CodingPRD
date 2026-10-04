"""ElectionDefinition endpoints (PRD 3.5): lifecycle, OCC-guarded layout PUT,
fleet readiness and print estimate computed reads.

Layout storage is DRAFT-only and OCC-guarded on the definition version.
LOCKED checks, in pipeline order: freeze window (P18), then procurement
ACCEPTED and pinned certificate ACTIVE (P19).
"""
from datetime import time

from flask import Blueprint, request

from auth import auth_context, require_acting_official, require_role
from constants import (
    BATTERY_CYCLE_MAX,
    ELECTION_FREEZE_DAYS,
    ELECTION_MIN_LEAD_DAYS,
    PAPER_THICKNESS_MAX_MICRONS,
    PAPER_THICKNESS_MIN_MICRONS,
    PAPER_WEIGHT_MAX_GSM,
    PAPER_WEIGHT_MIN_GSM,
    REAM_SHEETS,
    TIER1_MAX_REAMS,
    TIER1_PRICE_CENTS,
    TIER2_MAX_REAMS,
    TIER2_PRICE_CENTS,
    TIER3_PRICE_CENTS,
)
from envelope import apply_filters, list_page, ok_object
from errors import err_invalid_request, err_invalid_state, err_not_found, raise_err
from store import db
from util import parse_iso_date, stamp_new, today, touch
from validation import body_json, no_extra, opt_str, req_enum, req_int, req_obj, req_str

bp = Blueprint("definitions", __name__)

ED_STATES = {"DRAFT", "PROGRAMMED", "LA_PASSED", "LOCKED", "CANVASSING", "CLOSED", "CANCELLED"}
ED_FROM = {
    "PROGRAMMED": {"DRAFT"},
    "LA_PASSED": {"PROGRAMMED"},
    "DRAFT": {"PROGRAMMED", "LA_PASSED"},
    "LOCKED": {"LA_PASSED"},
    "CANVASSING": {"LOCKED"},
    "CLOSED": {"CANVASSING"},
    "CANCELLED": {"DRAFT", "PROGRAMMED"},
}
PAPER_COATINGS = {"UNCOATED", "COATED"}
TERMINAL_AUDIT_STATES = {"CLOSED_CONFIRMED", "CLOSED_ESCALATED"}


@bp.post("/evote/election-definitions")
def create_definition():
    uid, role = auth_context()
    require_role(role, {"ElectionOfficial"})
    body = body_json()
    no_extra(body, {"jurisdiction_id", "procurement_id", "name", "election_date", "precinct_count"})
    jurisdiction_id = req_str(body, "jurisdiction_id")
    procurement_id = req_str(body, "procurement_id")
    name = req_str(body, "name")
    election_date_raw = req_str(body, "election_date")
    election_date = parse_iso_date(election_date_raw)
    if election_date is None:
        err_invalid_request("election_date must be YYYY-MM-DD")
    precinct_count = req_int(body, "precinct_count", minv=1)
    if db.jurisdictions.get(jurisdiction_id) is None:
        raise_err("ERR_JURISDICTION_NOT_FOUND", 404, "jurisdiction_id does not resolve")
    proc = db.procurements.get(procurement_id)
    if proc is None:
        raise_err("ERR_PROCUREMENT_NOT_FOUND", 404, "procurement_id does not resolve")
    require_acting_official(uid, jurisdiction_id)
    if (election_date - today()).days < ELECTION_MIN_LEAD_DAYS:
        raise_err("ERR_ELECTION_DATE_INVALID", 422, "election_date must be at least 30 days out")
    if proc["status"] not in {"ACCEPTANCE_TESTING", "ACCEPTED"}:
        raise_err("ERR_PROCUREMENT_NOT_ACCEPTED", 422, "procurement must be ACCEPTANCE_TESTING or ACCEPTED")
    rec = stamp_new({})
    rec.update({
        "jurisdiction_id": jurisdiction_id,
        "procurement_id": procurement_id,
        "name": name,
        "election_date": election_date_raw,
        "precinct_count": precinct_count,
        "ballot_layout": None,
        "layout_revision": 0,
        "paper_weight_gsm": None,
        "paper_thickness_microns": None,
        "paper_coating": None,
        "status": "DRAFT",
        "status_reason": None,
    })
    db.election_definitions[rec["id"]] = rec
    return ok_object(rec, 201)


@bp.get("/evote/election-definitions")
def list_definitions():
    auth_context()
    items = apply_filters(
        list(db.election_definitions.values()),
        {"jurisdiction_id", "procurement_id", "status"},
    )
    return list_page(items)


def get_definition_or_404(definition_id):
    definition = db.election_definitions.get(definition_id)
    if definition is None:
        err_not_found("election definition not found")
    return definition


@bp.get("/evote/election-definitions/<definition_id>")
def get_definition(definition_id):
    auth_context()
    return ok_object(get_definition_or_404(definition_id), 200)


def _definition_system(definition):
    proc = db.procurements.get(definition["procurement_id"])
    if proc is None:
        return None
    return db.voting_systems.get(proc["voting_system_id"])


@bp.put("/evote/election-definitions/<definition_id>/layout")
def put_layout(definition_id):
    uid, role = auth_context()
    require_role(role, {"ElectionOfficial"})
    definition = get_definition_or_404(definition_id)
    body = body_json()
    no_extra(body, {
        "ballot_layout", "paper_weight_gsm", "paper_thickness_microns",
        "paper_coating", "expected_election_definition_version",
    })
    layout = req_obj(body, "ballot_layout")
    weight = req_int(body, "paper_weight_gsm")
    thickness = req_int(body, "paper_thickness_microns")
    coating = req_enum(body, "paper_coating", PAPER_COATINGS)
    expected = req_int(body, "expected_election_definition_version")
    require_acting_official(uid, definition["jurisdiction_id"])
    if definition["status"] != "DRAFT":
        err_invalid_state("layout may only be stored while DRAFT")
    if expected != definition["version"]:
        raise_err("ERR_STALE_VERSION", 412, "expected_election_definition_version does not match")
    if not (PAPER_WEIGHT_MIN_GSM <= weight <= PAPER_WEIGHT_MAX_GSM):
        raise_err("ERR_PAPER_INCOMPATIBLE", 422, "paper weight outside [80,120] gsm")
    if not (PAPER_THICKNESS_MIN_MICRONS <= thickness <= PAPER_THICKNESS_MAX_MICRONS):
        raise_err("ERR_PAPER_INCOMPATIBLE", 422, "paper thickness outside [60,250] microns")
    system = _definition_system(definition)
    if system is not None and system["hardware_class"] == "OPTICAL_SCANNER" and coating != "UNCOATED":
        raise_err("ERR_PAPER_INCOMPATIBLE", 422, "OPTICAL_SCANNER systems require UNCOATED paper")
    definition["ballot_layout"] = layout
    definition["paper_weight_gsm"] = weight
    definition["paper_thickness_microns"] = thickness
    definition["paper_coating"] = coating
    definition["layout_revision"] += 1
    touch(definition)
    return ok_object(definition, 200)


@bp.post("/evote/election-definitions/<definition_id>/transitions")
def definition_transition(definition_id):
    uid, role = auth_context()
    require_role(role, {"ElectionOfficial"})
    definition = get_definition_or_404(definition_id)
    body = body_json()
    no_extra(body, {"to_state", "reason"})
    to_state = req_enum(body, "to_state", ED_STATES)
    reason = opt_str(body, "reason")
    if to_state == "DRAFT" and not reason:
        err_invalid_request("reason is required for a revert to DRAFT")
    require_acting_official(uid, definition["jurisdiction_id"])
    if definition["status"] not in ED_FROM[to_state]:
        err_invalid_state("definition cannot transition from %s to %s" % (definition["status"], to_state))
    election_date = parse_iso_date(definition["election_date"])
    if to_state == "LOCKED":
        if (election_date - today()).days < ELECTION_FREEZE_DAYS:
            raise_err("ERR_ELECTION_FREEZE_WINDOW", 422, "inside the 14-day freeze window")
    if to_state == "CANVASSING" and today() < election_date:
        raise_err("ERR_ELECTION_NOT_HELD", 422, "election day has not been reached")
    if to_state == "PROGRAMMED":
        if (
            definition["ballot_layout"] is None
            or definition["paper_weight_gsm"] is None
            or definition["paper_thickness_microns"] is None
            or definition["paper_coating"] is None
        ):
            raise_err("ERR_LAYOUT_REQUIRED", 422, "layout and paper fields must be stored first")
    if to_state == "LA_PASSED":
        certified_pass = any(
            t["election_definition_id"] == definition_id
            and t["status"] == "CERTIFIED"
            and t["result"] == "PASS"
            for t in db.logic_accuracy_tests.values()
        )
        if not certified_pass:
            raise_err("ERR_LA_TEST_NOT_CERTIFIED", 422, "no CERTIFIED PASS L&A test exists")
    if to_state == "CLOSED":
        for audit in db.post_election_audits.values():
            if audit["election_definition_id"] == definition_id and audit["status"] not in TERMINAL_AUDIT_STATES:
                raise_err("ERR_AUDIT_OPEN", 422, "a post-election audit is not terminal")
    if to_state == "LOCKED":
        proc = db.procurements.get(definition["procurement_id"])
        if proc is None or proc["status"] != "ACCEPTED":
            raise_err("ERR_PROCUREMENT_NOT_ACCEPTED", 422, "procurement must be ACCEPTED to lock")
        cert = db.certificates.get(proc["certificate_id"])
        if cert is None or cert["status"] != "ACTIVE":
            raise_err("ERR_CERTIFICATE_NOT_ACTIVE", 422, "pinned certificate is not ACTIVE")
    if to_state in {"DRAFT", "CANCELLED"}:
        definition["status_reason"] = reason
    definition["status"] = to_state
    touch(definition)
    return ok_object(definition, 200)


@bp.get("/evote/election-definitions/<definition_id>/readiness")
def fleet_readiness(definition_id):
    auth_context()
    definition = get_definition_or_404(definition_id)
    proc = db.procurements.get(definition["procurement_id"])
    system_id = proc["voting_system_id"] if proc is not None else None
    election_date = parse_iso_date(definition["election_date"])
    election_end_of_day = None
    if election_date is not None:
        from datetime import datetime, timezone
        election_end_of_day = datetime.combine(election_date, time.max, tzinfo=timezone.utc)
    units = [
        u for u in db.equipment_units.values()
        if u["jurisdiction_id"] == definition["jurisdiction_id"]
        and u["voting_system_id"] == system_id
    ]
    optimistic = 0
    conservative = 0
    for unit in units:
        op = unit["operational_status"]
        if op in {"IN_SERVICE", "IN_STORAGE"}:
            optimistic += 1
        elif op == "IN_MAINTENANCE":
            finishing = any(
                wo["equipment_unit_id"] == unit["id"]
                and wo["status"] in {"SCHEDULED", "IN_PROGRESS"}
                and election_end_of_day is not None
                and wo["scheduled_end"] <= election_end_of_day
                for wo in db.maintenance_work_orders.values()
            )
            if finishing:
                optimistic += 1
        if (
            op == "IN_SERVICE"
            and unit["custody_status"] == "SECURED"
            and unit["battery_cycles"] < BATTERY_CYCLE_MAX
            and unit["storage_excursion_count"] == 0
        ):
            conservative += 1
    return ok_object({
        "jurisdiction_id": definition["jurisdiction_id"],
        "voting_system_id": system_id,
        "unit_count": len(units),
        "optimistic_ready_count": optimistic,
        "conservative_ready_count": conservative,
    }, 200)


@bp.get("/evote/election-definitions/<definition_id>/print-estimate")
def print_estimate(definition_id):
    auth_context()
    definition = get_definition_or_404(definition_id)
    raw = request.args.get("ballots_per_precinct")
    try:
        ballots_per_precinct = int(raw)
    except (TypeError, ValueError):
        err_invalid_request("ballots_per_precinct must be an integer")
    if ballots_per_precinct < 1:
        err_invalid_request("ballots_per_precinct must be at least 1")
    precinct_count = definition["precinct_count"]
    reams_per_precinct = -(-ballots_per_precinct // REAM_SHEETS)  # ceil per precinct
    total_reams = reams_per_precinct * precinct_count
    if total_reams <= TIER1_MAX_REAMS:
        tier_price = TIER1_PRICE_CENTS
    elif total_reams <= TIER2_MAX_REAMS:
        tier_price = TIER2_PRICE_CENTS
    else:
        tier_price = TIER3_PRICE_CENTS
    return ok_object({
        "precinct_count": precinct_count,
        "ballots_per_precinct": ballots_per_precinct,
        "reams_per_precinct": reams_per_precinct,
        "total_reams": total_reams,
        "tier_price_cents": tier_price,
        "total_cost_cents": total_reams * tier_price,
    }, 200)
