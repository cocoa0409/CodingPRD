"""Routes: allocation requests, allocation decisions, allocation lines."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from common import (
    ApiError, DONORS, LOTS, SITES, REQUESTS, DECISIONS, LINES, EVENTS, LOCK,
    require_roles, auth_context, body, ok, ok_list,
    req_str, opt_str, req_int, req_list,
    stamp_new, bump, sorted_items, get_or_404,
    request_json, decision_json, line_json, decision_lines,
    lot_available, finalized_decision_for, clock,
    release_line,
)

REQ_ROLES = ("SiteCoordinator", "AllocationOfficer", "ComplianceOfficer", "PlatformAdmin")
DEC_GET_ONE_ROLES = ("AllocationOfficer", "ComplianceOfficer", "PlatformAdmin", "SiteCoordinator")
DEC_LIST_ROLES = ("AllocationOfficer", "ComplianceOfficer", "PlatformAdmin")
LINE_LIST_ROLES = ("AllocationOfficer", "ComplianceOfficer", "LogisticsCoordinator",
                   "PlatformAdmin", "SiteCoordinator")
LINE_GET_ROLES = ("AllocationOfficer", "ComplianceOfficer", "LogisticsCoordinator", "PlatformAdmin")

RESERVATION_TTL_HOURS = 72
EMERGENCY_RESERVATION_TTL_HOURS = 24


def compute_need_score(site, event, lines):
    base = Decimal("100") * Decimal(str(site["underserved_index"]))
    volume_factor = min(Decimal(str(site["monthly_patient_volume"])) / Decimal("1000"),
                        Decimal("2.0"))
    volume_points = Decimal("25") * volume_factor
    emergency_boost = Decimal(0)
    if event is not None and event["status"] == "ACTIVE":
        emergency_boost = Decimal("10") * Decimal(event["severity"])
    storage_adjust = Decimal(0)
    any_cold = any(LOTS[l["lot_id"]]["product_class"] == "COLD_CHAIN" for l in lines)
    if any_cold and site["cold_storage_capacity_l"] == 0:
        storage_adjust = Decimal("-50")
    total = base + volume_points + emergency_boost + storage_adjust
    return float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def validate_decision_lines(lines_in):
    """Parse + structurally validate the lines array; returns list of dicts."""
    lines = req_list_of_lines(lines_in)
    return lines


def req_list_of_lines(lines_in):
    if not isinstance(lines_in, list):
        raise ApiError("ERR_INVALID_REQUEST", 400, "lines must be an array")
    out = []
    for ln in lines_in:
        if not isinstance(ln, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400, "each line must be an object")
        lot_id = ln.get("lot_id")
        qty = ln.get("quantity")
        if not isinstance(lot_id, str) or not lot_id.strip():
            raise ApiError("ERR_INVALID_REQUEST", 400, "line.lot_id must be a non-empty string")
        if isinstance(qty, bool) or not isinstance(qty, int):
            raise ApiError("ERR_INVALID_REQUEST", 400, "line.quantity must be an integer")
        out.append({"lot_id": lot_id.strip(), "quantity": qty})
    return out


def check_line_business(req, parsed_lines, *, finalization):
    """Shared business checks for decision create + finalize.

    PRD §3.5: at draft creation the enforced guards are lot releasability,
    the line-sum-vs-quantity_requested bound, and per-lot availability. At
    finalization the PRD fixes an explicit order: releasability ->
    cold-chain adequacy -> controlled-site authorization -> line-sum bound ->
    availability. The controlled-site and cold-chain checks are
    finalization-only per PRD §3.2 ("at decision finalization").
    """
    site = SITES[req["site_id"]]
    lots = []
    for ln in parsed_lines:
        lot = LOTS.get(ln["lot_id"])
        if lot is None:
            raise ApiError("ERR_NOT_FOUND", 404, f"ProductLot not found: {ln['lot_id']}")
        lots.append((ln, lot))
    # releasability (draft creation and finalization)
    for ln, lot in lots:
        if lot["lot_posture"] != "RELEASABLE":
            raise ApiError("ERR_LOT_NOT_RELEASABLE", 409,
                           f"Lot {lot['id']} is not RELEASABLE")
    if finalization:
        # cold-chain adequacy, then controlled-site authorization
        for ln, lot in lots:
            if lot["product_class"] == "COLD_CHAIN" and site["cold_storage_capacity_l"] <= 0:
                raise ApiError("ERR_COLD_CHAIN_INADEQUATE", 422,
                               "Cold-chain allocation to a site with zero cold storage capacity")
        for ln, lot in lots:
            if lot["product_class"] == "CONTROLLED" and not site["has_dea_registration"]:
                raise ApiError("ERR_CONTROLLED_SITE_NOT_AUTHORIZED", 422,
                               "Controlled lot allocated to a site without DEA registration")
    # quantity bounds
    for ln, lot in lots:
        if ln["quantity"] <= 0:
            raise ApiError("ERR_QUANTITY_INVALID", 422, "Line quantity must be positive")
    total = sum(ln["quantity"] for ln, _ in lots)
    if total <= 0 or total > req["quantity_requested"]:
        raise ApiError("ERR_QUANTITY_INVALID", 422,
                       "Decision line sum must be > 0 and <= quantity_requested")
    # per-lot availability — a commit-time invariant; drafts carry no
    # reservation, so this is enforced at finalization ("after the commit").
    if finalization:
        per_lot = {}
        for ln, lot in lots:
            per_lot[lot["id"]] = per_lot.get(lot["id"], 0) + ln["quantity"]
        for lot_id, qty in per_lot.items():
            if lot_available(LOTS[lot_id]) - qty < 0:
                raise ApiError("ERR_INSUFFICIENT_AVAILABLE", 409,
                               "Decision would drive a lot's quantity_available negative")
    return lots


def register(app):

    # ---------------------------------------------------- allocation requests
    @app.post("/medicine-relief/allocation-requests")
    def create_request():
        uid, _ = require_roles("SiteCoordinator")
        b = body()
        site_id = req_str(b, "site_id")
        ndc_code = req_str(b, "ndc_code")
        qty = req_int(b, "quantity_requested")
        justification = req_str(b, "justification_text")
        event_id = opt_str(b, "emergency_event_id")
        if qty <= 0:
            raise ApiError("ERR_QUANTITY_INVALID", 422, "quantity_requested must be a positive integer")
        with LOCK:
            get_or_404(SITES, site_id, "RecipientSite")
            if event_id is not None:
                ev = EVENTS.get(event_id)
                if ev is None:
                    raise ApiError("ERR_NOT_FOUND", 404, f"EmergencyEvent not found: {event_id}")
                if ev["status"] != "ACTIVE":
                    raise ApiError("ERR_EMERGENCY_NOT_ACTIVE", 409,
                                   "Referenced EmergencyEvent is not ACTIVE")
            req_obj = {
                "site_id": site_id,
                "requested_by_user_id": uid,
                "ndc_code": ndc_code,
                "quantity_requested": qty,
                "justification_text": justification,
                "emergency_event_id": event_id,
                "status": "SUBMITTED",
                "need_score": None,
                "quantity_approved": 0,
            }
            stamp_new(req_obj)
            REQUESTS[req_obj["id"]] = req_obj
            return ok(request_json(req_obj), 201)

    @app.get("/medicine-relief/allocation-requests/<request_id>")
    def get_request(request_id):
        require_roles(*REQ_ROLES)
        with LOCK:
            return ok(request_json(get_or_404(REQUESTS, request_id, "AllocationRequest")))

    @app.get("/medicine-relief/allocation-requests")
    def list_requests():
        require_roles(*REQ_ROLES)
        site_id = request.args.get("site_id")
        status = request.args.get("status")
        ndc = request.args.get("ndc_code")
        ev = request.args.get("emergency_event_id")
        with LOCK:
            items = [r for r in sorted_items(REQUESTS)
                     if (site_id is None or r["site_id"] == site_id)
                     and (status is None or r["status"] == status)
                     and (ndc is None or r["ndc_code"] == ndc)
                     and (ev is None or r["emergency_event_id"] == ev)]
            return ok_list([request_json(r) for r in items])

    @app.post("/medicine-relief/allocation-requests/<request_id>/begin-review")
    def begin_review(request_id):
        require_roles("AllocationOfficer")
        with LOCK:
            req_obj = get_or_404(REQUESTS, request_id, "AllocationRequest")
            if req_obj["status"] not in ("SUBMITTED", "APPROVED", "PARTIALLY_APPROVED"):
                raise ApiError("ERR_INVALID_STATE", 409,
                               "Request cannot enter review from its current status")
            site = SITES.get(req_obj["site_id"])
            if site is None or site["qualification_status"] != "QUALIFIED":
                raise ApiError("ERR_SITE_NOT_QUALIFIED", 409, "Site is not QUALIFIED")
            if req_obj["status"] in ("APPROVED", "PARTIALLY_APPROVED"):
                dec = finalized_decision_for(req_obj["id"])
                if dec is None or any(
                        l["status"] != "RESERVED" for l in decision_lines(dec["id"])):
                    raise ApiError("ERR_INVALID_STATE", 409,
                                   "Existing finalized decision's lines are no longer all RESERVED")
            req_obj["status"] = "UNDER_REVIEW"
            bump(req_obj)
            return ok(request_json(req_obj))

    @app.post("/medicine-relief/allocation-requests/<request_id>/reject")
    def reject_request(request_id):
        require_roles("AllocationOfficer")
        b = body()
        opt_str(b, "rationale")
        with LOCK:
            req_obj = get_or_404(REQUESTS, request_id, "AllocationRequest")
            if req_obj["status"] != "UNDER_REVIEW":
                raise ApiError("ERR_INVALID_STATE", 409, "Request is not UNDER_REVIEW")
            if finalized_decision_for(req_obj["id"]) is not None:
                raise ApiError("ERR_INVALID_STATE", 409,
                               "A FINALIZED decision exists for this request")
            req_obj["status"] = "REJECTED"
            bump(req_obj)
            return ok(request_json(req_obj))

    @app.post("/medicine-relief/allocation-requests/<request_id>/cancel")
    def cancel_request(request_id):
        uid, _ = require_roles("SiteCoordinator")
        with LOCK:
            req_obj = get_or_404(REQUESTS, request_id, "AllocationRequest")
            if req_obj["requested_by_user_id"] != uid:
                raise ApiError("ERR_FORBIDDEN_OWNERSHIP", 403,
                               "Only the requesting coordinator may cancel this request")
            if req_obj["status"] not in ("SUBMITTED", "UNDER_REVIEW"):
                raise ApiError("ERR_INVALID_STATE", 409,
                               "Request cannot be cancelled from its current status")
            if finalized_decision_for(req_obj["id"]) is not None:
                raise ApiError("ERR_INVALID_STATE", 409,
                               "A FINALIZED decision exists for this request")
            req_obj["status"] = "CANCELLED"
            bump(req_obj)
            return ok(request_json(req_obj))

    # --------------------------------------------------- allocation decisions
    @app.post("/medicine-relief/allocation-decisions")
    def create_decision():
        uid, _ = require_roles("AllocationOfficer")
        b = body()
        request_id = req_str(b, "request_id")
        rationale = req_str(b, "rationale")
        parsed = req_list_of_lines(b.get("lines", []))
        with LOCK:
            req_obj = get_or_404(REQUESTS, request_id, "AllocationRequest")
            site = SITES.get(req_obj["site_id"])
            if site is None or site["qualification_status"] != "QUALIFIED":
                raise ApiError("ERR_SITE_NOT_QUALIFIED", 409, "Site is not QUALIFIED")
            check_line_business(req_obj, parsed, finalization=False)
            dec = {
                "request_id": request_id,
                "reviewer_user_id": uid,
                "decided_at": None,
                "rationale": rationale,
                "status": "DRAFT",
            }
            stamp_new(dec)
            DECISIONS[dec["id"]] = dec
            for ln in parsed:
                line = {
                    "decision_id": dec["id"],
                    "lot_id": ln["lot_id"],
                    "quantity": ln["quantity"],
                    "status": "DRAFT",
                    "reservation_expires_at": None,
                }
                stamp_new(line)
                LINES[line["id"]] = line
            return ok(decision_json(dec), 201)

    @app.get("/medicine-relief/allocation-decisions/<decision_id>")
    def get_decision(decision_id):
        require_roles(*DEC_GET_ONE_ROLES)
        with LOCK:
            return ok(decision_json(get_or_404(DECISIONS, decision_id, "AllocationDecision")))

    @app.get("/medicine-relief/allocation-decisions")
    def list_decisions():
        require_roles(*DEC_LIST_ROLES)
        rid = request.args.get("request_id")
        status = request.args.get("status")
        with LOCK:
            items = [d for d in sorted_items(DECISIONS)
                     if (rid is None or d["request_id"] == rid)
                     and (status is None or d["status"] == status)]
            return ok_list([decision_json(d) for d in items])

    @app.post("/medicine-relief/allocation-decisions/<decision_id>/finalize")
    def finalize_decision(decision_id):
        uid, _ = require_roles("AllocationOfficer")
        b = body()
        with LOCK:
            dec = get_or_404(DECISIONS, decision_id, "AllocationDecision")
            if dec["status"] != "DRAFT":
                raise ApiError("ERR_INVALID_STATE", 409, "Decision is not DRAFT")
            if dec["reviewer_user_id"] != uid:
                raise ApiError("ERR_FORBIDDEN_OWNERSHIP", 403,
                               "Only the drafting reviewer may finalize this decision")
            req_obj = REQUESTS.get(dec["request_id"])
            if req_obj is None:
                raise ApiError("ERR_NOT_FOUND", 404, "AllocationRequest not found")
            site = SITES.get(req_obj["site_id"])
            if site is None or site["qualification_status"] != "QUALIFIED":
                raise ApiError("ERR_SITE_NOT_QUALIFIED", 409, "Site is not QUALIFIED")
            lines = decision_lines(dec["id"])
            if not lines:
                raise ApiError("ERR_QUANTITY_INVALID", 422, "Decision has no lines")
            parsed = [{"lot_id": l["lot_id"], "quantity": l["quantity"]} for l in lines]
            check_line_business(req_obj, parsed, finalization=True)
            # OCC check — last in the PRD §3.5 ordered guard list
            expected = b.get("expected_request_version")
            if expected is None or expected != req_obj["version"]:
                raise ApiError("ERR_STALE_VERSION", 412,
                               "expected_request_version does not match the request's current version")

            # Supersede prior FINALIZED decision (revision loop)
            prior = finalized_decision_for(req_obj["id"])
            if prior is not None and prior["id"] != dec["id"]:
                for line in decision_lines(prior["id"]):
                    if line["status"] != "RESERVED":
                        raise ApiError("ERR_INVALID_STATE", 409,
                                       "Prior finalized decision's lines are no longer all RESERVED")
                for line in decision_lines(prior["id"]):
                    release_line(line)
                prior["status"] = "SUPERSEDED"
                bump(prior)

            decided_at = clock()
            event = EVENTS.get(req_obj["emergency_event_id"]) if req_obj["emergency_event_id"] else None
            ttl = EMERGENCY_RESERVATION_TTL_HOURS if (event is not None and event["status"] == "ACTIVE") \
                else RESERVATION_TTL_HOURS
            expires = decided_at + timedelta(hours=ttl)

            for line in lines:
                lot = LOTS[line["lot_id"]]
                lot["quantity_committed"] += line["quantity"]
                bump(lot)
                line["status"] = "RESERVED"
                line["reservation_expires_at"] = expires
                bump(line)

            dec["status"] = "FINALIZED"
            dec["decided_at"] = decided_at
            bump(dec)

            total = sum(l["quantity"] for l in lines)
            req_obj["need_score"] = compute_need_score(site, event, lines)
            req_obj["quantity_approved"] = total
            req_obj["status"] = "APPROVED" if total == req_obj["quantity_requested"] else "PARTIALLY_APPROVED"
            bump(req_obj)
            return ok(decision_json(dec))

    @app.post("/medicine-relief/allocation-decisions/<decision_id>/void")
    def void_decision(decision_id):
        require_roles("AllocationOfficer")
        with LOCK:
            dec = get_or_404(DECISIONS, decision_id, "AllocationDecision")
            if dec["status"] != "DRAFT":
                raise ApiError("ERR_INVALID_STATE", 409, "Decision is not DRAFT")
            dec["status"] = "VOID"
            bump(dec)
            return ok(decision_json(dec))

    # ------------------------------------------------------- allocation lines
    @app.get("/medicine-relief/allocation-lines")
    def list_lines():
        require_roles(*LINE_LIST_ROLES)
        did = request.args.get("decision_id")
        lid = request.args.get("lot_id")
        status = request.args.get("status")
        with LOCK:
            items = [l for l in sorted_items(LINES)
                     if (did is None or l["decision_id"] == did)
                     and (lid is None or l["lot_id"] == lid)
                     and (status is None or l["status"] == status)]
            return ok_list([line_json(l) for l in items])

    @app.get("/medicine-relief/allocation-lines/<line_id>")
    def get_line(line_id):
        require_roles(*LINE_GET_ROLES)
        with LOCK:
            return ok(line_json(get_or_404(LINES, line_id, "AllocationLine")))
