"""Funding cycles and selection runs (PRD 3.1, 3.4; OCC per 2.9)."""
from flask import Blueprint, request

from db import STORES, new_record, get_clock
from helpers import (
    body, require_roles, ok_obj, list_response, get_or_404, req_str, req_int,
    opt_enum, raise_err, now_iso,
)
from errors import (
    E_INVALID_REQUEST, E_INVALID_STATE, E_CYCLE_NOT_FOUND, E_RUN_NOT_FOUND,
    E_STALE_VERSION, E_CYCLE_NOT_SELECTION_OPEN,
)
from logic import (
    bump, cycle_ledger, latest_scoped_assessment, envelope_for, get_cycle,
)
from serializers import ser_cycle, ser_run

bp = Blueprint("cycles", __name__)

CYCLE_STATUSES = ("OPEN", "SELECTION_OPEN", "SEALED", "CLOSED")
RUN_STATUSES = ("COMPUTED", "APPLIED", "SUPERSEDED", "DISCARDED")


@bp.post("/rebuild/funding-cycles")
def create_cycle():
    require_roles("PlatformAdmin")
    b = body()
    name = req_str(b, "name")
    fiscal_year = req_int(b, "fiscal_year")
    budget = req_int(b, "total_budget_cents", lo=0)
    mode = opt_enum(b, "priority_mode", ("STANDARD", "HAZARD_PRIORITY"),
                    default="STANDARD")
    rec = new_record("funding_cycles", {
        "name": name,
        "fiscal_year": fiscal_year,
        "total_budget_cents": budget,
        "priority_mode": mode,
        "status": "OPEN",
    }, now_iso)
    return ok_obj(ser_cycle(rec), 201)


@bp.get("/rebuild/funding-cycles/<cycleId>")
def get_cycle_route(cycleId):
    require_roles("Any")
    rec = get_or_404("funding_cycles", cycleId, E_CYCLE_NOT_FOUND)
    return ok_obj(ser_cycle(rec))


@bp.patch("/rebuild/funding-cycles/<cycleId>")
def patch_cycle(cycleId):
    require_roles("PlatformAdmin")
    rec = get_or_404("funding_cycles", cycleId, E_CYCLE_NOT_FOUND)
    b = body()
    if "status" not in b:
        raise_err(E_INVALID_REQUEST, 400, "status is required")
    target = b["status"]
    if not isinstance(target, str) or target not in CYCLE_STATUSES:
        raise_err(E_INVALID_REQUEST, 400,
                  "status must be one of " + ", ".join(CYCLE_STATUSES))
    if target == "SELECTION_OPEN":
        if rec["status"] != "OPEN":
            raise_err(E_INVALID_STATE, 409,
                      "cycle must be OPEN to open selection")
        rec["status"] = "SELECTION_OPEN"
        bump(rec)
    elif target == "SEALED":
        if rec["status"] != "SELECTION_OPEN":
            raise_err(E_INVALID_STATE, 409,
                      "cycle must be SELECTION_OPEN to seal")
        # Atomic seal: discard COMPUTED runs, defer unselected CANDIDATEs.
        for run in STORES["selection_runs"].values():
            if (run["funding_cycle_id"] == rec["id"]
                    and run["status"] == "COMPUTED"):
                run["status"] = "DISCARDED"
                bump(run)
        for app in STORES["applications"].values():
            if (app["funding_cycle_id"] == rec["id"]
                    and app["status"] == "CANDIDATE"):
                app["status"] = "DEFERRED"
                app["decision_reason"] = "CYCLE_SEALED"
                bump(app)
        rec["status"] = "SEALED"
        bump(rec)
    elif target == "CLOSED":
        if rec["status"] != "SEALED":
            raise_err(E_INVALID_STATE, 409,
                      "cycle must be SEALED to close")
        stragglers = [p for p in STORES["projects"].values()
                      if p["funding_cycle_id"] == rec["id"]
                      and p["status"] not in ("CLOSED", "CANCELLED")]
        if stragglers:
            raise_err(E_INVALID_STATE, 409,
                      "every project of the cycle must be CLOSED or CANCELLED")
        rec["status"] = "CLOSED"
        bump(rec)
    else:  # OPEN is not a drivable target
        raise_err(E_INVALID_STATE, 409, "no transition to %s" % target)
    return ok_obj(ser_cycle(rec))


@bp.post("/rebuild/funding-cycles/<cycleId>/selection-runs")
def create_selection_run(cycleId):
    require_roles("AffiliateStaff", "PlatformAdmin")
    cycle = get_or_404("funding_cycles", cycleId, E_CYCLE_NOT_FOUND)
    b = body()
    # OCC (tier 5): expected_funding_cycle_version is non-optional.
    if ("expected_funding_cycle_version" not in b
            or b["expected_funding_cycle_version"] is None):
        raise_err(E_INVALID_REQUEST, 400,
                  "expected_funding_cycle_version is required")
    expected = b["expected_funding_cycle_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(E_INVALID_REQUEST, 400,
                  "expected_funding_cycle_version must be an integer")
    if expected != cycle["version"]:
        raise_err(E_STALE_VERSION, 412,
                  "expected_funding_cycle_version does not match the cycle "
                  "version")
    # State (tier 6).
    if cycle["status"] != "SELECTION_OPEN":
        raise_err(E_CYCLE_NOT_SELECTION_OPEN, 409,
                  "selection runs require the cycle in SELECTION_OPEN")
    ranked = sorted(
        (a for a in STORES["applications"].values()
         if a["funding_cycle_id"] == cycleId and a["status"] == "CANDIDATE"),
        key=lambda a: (-(a["priority_score"] or 0), a["created_at"], a["_seq"]))
    # Supersede any previous COMPUTED run of the cycle.
    for run in STORES["selection_runs"].values():
        if (run["funding_cycle_id"] == cycleId
                and run["status"] == "COMPUTED"):
            run["status"] = "SUPERSEDED"
            bump(run)
    rec = new_record("selection_runs", {
        "funding_cycle_id": cycleId,
        "status": "COMPUTED",
        "priority_mode_snapshot": cycle["priority_mode"],
        "ranked_application_ids": [a["id"] for a in ranked],
        "selected_application_ids": [],
        "applied_at": None,
    }, now_iso)
    bump(cycle)
    return ok_obj(ser_run(rec), 201)


@bp.get("/rebuild/selection-runs")
def list_runs():
    require_roles("Any")
    recs = list(STORES["selection_runs"].values())
    fc = request.args.get("funding_cycle_id")
    if fc is not None:
        recs = [r for r in recs if r["funding_cycle_id"] == fc]
    return list_response(recs, ser_run)


@bp.get("/rebuild/selection-runs/<runId>")
def get_run(runId):
    require_roles("Any")
    rec = get_or_404("selection_runs", runId, E_RUN_NOT_FOUND)
    return ok_obj(ser_run(rec))


@bp.post("/rebuild/selection-runs/<runId>/apply")
def apply_run(runId):
    require_roles("AffiliateStaff")
    run = get_or_404("selection_runs", runId, E_RUN_NOT_FOUND)
    cycle = get_cycle(run["funding_cycle_id"])
    # Cycle gate first, then run state (PRD 3.4 ordering).
    if cycle["status"] != "SELECTION_OPEN":
        raise_err(E_CYCLE_NOT_SELECTION_OPEN, 409,
                  "apply requires the cycle in SELECTION_OPEN")
    if run["status"] != "COMPUTED":
        raise_err(E_INVALID_STATE, 409, "run must be COMPUTED to apply")
    remaining = cycle_ledger(cycle)["available_cents"]
    project_ids = []
    deferred_ids = []
    selected_ids = []
    created_envelopes = []
    for aid in run["ranked_application_ids"]:
        app = STORES["applications"].get(aid)
        if app is None or app["status"] != "CANDIDATE":
            deferred_ids.append(aid)
            continue
        assessment = latest_scoped_assessment(aid)
        items = []
        if assessment is not None:
            items = [i for i in STORES["scope_items"].values()
                     if i["assessment_id"] == assessment["id"]
                     and i["status"] == "INCLUDED"]
        est = sum(i["midpoint_cents"] for i in items)
        envelope = envelope_for(est)
        if envelope <= remaining:
            # Greedy first-fit: select, spawn the project in PLANNING.
            app["status"] = "SELECTED"
            bump(app)
            proj = new_record("projects", {
                "application_id": aid,
                "funding_cycle_id": cycle["id"],
                "_assessment_id": assessment["id"] if assessment else None,
                "status": "PLANNING",
                "cancellation_reason": None,
                "provisional_estimate_cents": est,
                "envelope_cents": envelope,
                "reserved_balance_cents": envelope,
                "priority_score_snapshot": app["priority_score"],
                "completed_on": None,
                "follow_up_completed_on": None,
                "warranty_valid_until": None,
            }, now_iso)
            remaining -= envelope
            project_ids.append(proj["id"])
            selected_ids.append(aid)
            created_envelopes.append(envelope)
        else:
            # Does not fit: skip and continue down the ranking.
            deferred_ids.append(aid)
    # Sponsor waterfall: base budget first, then RECEIVED commitments in
    # received_at ASC order (ties: created_at ASC).
    need = sum(created_envelopes)
    remaining_need = need - min(cycle["total_budget_cents"], need)
    commitments = sorted(
        (c for c in STORES["commitments"].values()
         if c["funding_cycle_id"] == cycle["id"] and c["status"] == "RECEIVED"),
        key=lambda c: (c["received_at"] or "", c["created_at"], c["_seq"]))
    for c in commitments:
        if remaining_need <= 0:
            break
        alloc = min(c["amount_cents"], remaining_need)
        if alloc > 0:
            c["status"] = "ALLOCATED"
            c["allocated_amount_cents"] = alloc
            bump(c)
            remaining_need -= alloc
    run["selected_application_ids"] = selected_ids
    run["status"] = "APPLIED"
    run["applied_at"] = get_clock()
    bump(run)
    bump(cycle)
    return ok_obj({
        "applied_count": len(project_ids),
        "project_ids": project_ids,
        "deferred_application_ids": deferred_ids,
    })
