"""Counterfeit cases (report/resolve with the confirm cascade) and safety
bulletins (window-overlap rule, supersession, severity cascades)."""
from flask import Blueprint, request

import db
from constants import (
    API_PREFIX,
    BULLETIN_SEVERITIES,
    CASE_VERDICTS,
    COUNTERFEIT_CONFIRM_THRESHOLD,
    DETECTION_METHODS,
    ROLES,
)
from errors import fail
from helpers import (
    authorize,
    body,
    check_enum,
    check_int,
    ok_list,
    ok_object,
    pagination,
    page_window,
    parse_dt,
    present,
    req_field,
    req_str,
)
from services import (
    INF,
    bulletin_cascade,
    bump,
    counterfeit_confirm_cascade,
    make_entity,
)
from views import view_bulletin, view_case

bp = Blueprint("safety", __name__)


@bp.route(f"{API_PREFIX}/counterfeit-cases", methods=["POST"])
def create_case():
    user_id, _ = authorize(["ChannelManager", "AccountManager"])
    data = body()
    battery_pack_id = req_field(data, "battery_pack_id")
    if db.STORE["packs"].get(battery_pack_id) is None:
        fail("ERR_NOT_FOUND", "battery_pack_id does not reference an existing pack")
    reported_serial = req_str(data, "reported_serial")
    detection_method = check_enum(
        req_field(data, "detection_method"), "detection_method", DETECTION_METHODS
    )
    case = make_entity(
        {
            "battery_pack_id": battery_pack_id,
            "reported_serial": reported_serial,
            "detection_method": detection_method,
            "status": "REPORTED",
            "evidence_score": None,
            "created_by_user_id": user_id,
            "resolved_by_user_id": None,
        }
    )
    db.STORE["cases"][case["id"]] = case
    return ok_object(view_case(case), 201)


@bp.route(f"{API_PREFIX}/counterfeit-cases/<case_id>/resolve", methods=["POST"])
def resolve_case(case_id):
    user_id, _ = authorize(["ComplianceEngineer"])
    case = db.STORE["cases"].get(case_id)
    if case is None:
        fail("ERR_NOT_FOUND", "Counterfeit case not found")
    data = body()
    verdict = check_enum(req_field(data, "verdict"), "verdict", CASE_VERDICTS)
    evidence_score = check_int(req_field(data, "evidence_score"), "evidence_score")
    if not (0 <= evidence_score <= 100):
        fail("ERR_VALIDATION", "evidence_score must be within 0..100")
    # Priority 6: valid from-state
    if case["status"] != "REPORTED":
        fail("ERR_INVALID_STATE", "Counterfeit case is not REPORTED")
    # Priority 7: segregation of duties
    if user_id == case["created_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "Resolver must differ from the reporter")
    # Priority 9: evidence threshold for CONFIRMED
    if verdict == "CONFIRMED" and evidence_score < COUNTERFEIT_CONFIRM_THRESHOLD:
        fail("ERR_EVIDENCE_INSUFFICIENT", "evidence_score below the confirm threshold")
    case["status"] = verdict
    case["evidence_score"] = evidence_score
    case["resolved_by_user_id"] = user_id
    bump(case)
    if verdict == "CONFIRMED":
        counterfeit_confirm_cascade(db.STORE["packs"][case["battery_pack_id"]])
    return ok_object(view_case(case))


def _windows_overlap(a_from, a_to, b_from, b_to):
    """Half-open [from, to) intersection; absent end means unbounded."""
    a_end = a_to if a_to is not None else INF
    b_end = b_to if b_to is not None else INF
    return a_from < b_end and b_from < a_end


@bp.route(f"{API_PREFIX}/safety-bulletins", methods=["POST"])
def create_bulletin():
    authorize(["ComplianceEngineer"])
    data = body()
    # Priority 4: FK existence (platform, pack ids members, supersedes target)
    platform_id = req_field(data, "platform_id")
    if db.STORE["platforms"].get(platform_id) is None:
        fail("ERR_NOT_FOUND", "platform_id does not reference an existing platform")
    pack_ids = []
    if present(data, "battery_pack_ids"):
        if not isinstance(data["battery_pack_ids"], list):
            fail("ERR_VALIDATION", "battery_pack_ids must be an array")
        for pid in data["battery_pack_ids"]:
            if db.STORE["packs"].get(pid) is None:
                fail("ERR_NOT_FOUND", "battery_pack_ids references a missing pack")
            pack_ids.append(pid)
    supersedes = None
    supersedes_id = None
    if present(data, "supersedes_bulletin_id"):
        supersedes_id = data["supersedes_bulletin_id"]
        supersedes = db.STORE["bulletins"].get(supersedes_id)
        if supersedes is None:
            fail("ERR_NOT_FOUND", "supersedes_bulletin_id does not reference an "
                                   "existing bulletin")
    # Priority 5: shape
    severity = check_enum(req_field(data, "severity"), "severity", BULLETIN_SEVERITIES)
    title = req_str(data, "title")
    effective_from = parse_dt(req_field(data, "effective_from"), "effective_from")
    effective_to = None
    if present(data, "effective_to"):
        effective_to = parse_dt(data["effective_to"], "effective_to")
    if supersedes is not None and (
        supersedes["platform_id"] != platform_id or supersedes["status"] != "ISSUED"
    ):
        fail("ERR_VALIDATION", "supersedes_bulletin_id must name an ISSUED bulletin "
                               "of the same platform")
    # Priority 15: half-open window overlap on the same platform
    for b in db.STORE["bulletins"].values():
        if b["platform_id"] != platform_id or b["status"] != "ISSUED":
            continue
        if supersedes_id is not None and b["id"] == supersedes_id:
            continue  # the superseded bulletin is excused from the overlap rule
        if _windows_overlap(effective_from, effective_to,
                            b["effective_from"], b.get("effective_to")):
            fail("ERR_BULLETIN_WINDOW_OVERLAP",
                 "Window intersects an ISSUED bulletin on this platform")
    bulletin = make_entity(
        {
            "platform_id": platform_id,
            "battery_pack_ids": pack_ids,
            "severity": severity,
            "title": title,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "supersedes_bulletin_id": supersedes_id,
            "status": "ISSUED",
        }
    )
    db.STORE["bulletins"][bulletin["id"]] = bulletin
    if supersedes is not None:
        supersedes["status"] = "SUPERSEDED"
        bump(supersedes)
    bulletin_cascade(bulletin)
    return ok_object(view_bulletin(bulletin), 201)


@bp.route(f"{API_PREFIX}/safety-bulletins/<bulletin_id>", methods=["GET"])
def get_bulletin(bulletin_id):
    authorize(ROLES)
    b = db.STORE["bulletins"].get(bulletin_id)
    if b is None:
        fail("ERR_NOT_FOUND", "Safety bulletin not found")
    return ok_object(view_bulletin(b))


@bp.route(f"{API_PREFIX}/safety-bulletins", methods=["GET"])
def list_bulletins():
    authorize(ROLES)
    limit, offset = pagination()
    items = list(db.STORE["bulletins"].values())
    platform_id = request.args.get("platform_id")
    if platform_id is not None:
        items = [b for b in items if b["platform_id"] == platform_id]
    supersedes = request.args.get("supersedes_bulletin_id")
    if supersedes is not None:
        items = [b for b in items if b.get("supersedes_bulletin_id") == supersedes]
    page, total = page_window(items, limit, offset)
    return ok_list([view_bulletin(b) for b in page], total, limit, offset)
