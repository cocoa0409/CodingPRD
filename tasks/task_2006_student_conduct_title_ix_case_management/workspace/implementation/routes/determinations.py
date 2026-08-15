"""Determination and Sanction endpoints (PRD 3.5): draft, issue with the
pinned severity/restitution evaluation order, sanction lifecycle."""
from datetime import timedelta
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE_TRANSITION, ERR_STANDARD_OF_EVIDENCE_MISMATCH,
    ERR_SANCTION_OUTSIDE_MATRIX, ERR_NOT_HEARING_DECISION_MAKER,
    ERR_RESTITUTION_ITEMS_REQUIRED, ERR_STALE_CASE_VERSION, ERR_INVALID_REQUEST,
)
from middleware import authorized, check_case_read_access, STAFF_READ_ROLES
from response import success_list, success_object
from services.core import (
    new_record, touch, public, bump_case, append_event, auto_notice, get_case,
    check_case_not_terminal, get_pagination, sort_items, apply_filters,
    FINDINGS, STANDARDS, SANCTION_TYPES,
)
from services.calculations import (
    matrix_score, tier_of, restitution_applied_cents, restitution_points,
    TIER_MATRIX, DURATION_TYPES, DURATION_LESS_TYPES,
)
from util import clock_dt, fmt_datetime
from validate import (
    get_body, req_str, req_enum, opt_int, require_path, as_int, as_enum, as_list,
)

bp = Blueprint("determinations", __name__)

READ_ROLES = STAFF_READ_ROLES + ["Party"]


def _case_hearing_for_determination(case):
    """The hearing whose decision-maker owns drafting/issuing: the live
    DELIBERATION hearing, else the most recent COMPLETED one (remand lineage)."""
    hearings = [h for h in db["hearings"].values()
                if h["case_id"] == case["id"] and h["status"] in ("DELIBERATION", "COMPLETED")]
    if not hearings:
        return None
    return max(hearings, key=lambda h: h["_seq"])


@bp.post("/cases/<cid>/determinations")
def create_determination(cid):
    caller = authorized(["DecisionMaker"])
    case = get_case(cid)
    check_case_not_terminal(case)
    body = get_body()
    # Tier 4: drafting requires DELIBERATION (or REMANDED, continuing a lineage).
    if case["status"] not in ("DELIBERATION", "REMANDED"):
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"case is {case['status']}; drafting requires DELIBERATION")
    # Tier 8: only the hearing's decision-maker may draft.
    hearing = _case_hearing_for_determination(case)
    if hearing is not None and caller.user_id != hearing["decision_maker_id"]:
        raise_error(ERR_NOT_HEARING_DECISION_MAKER,
                    "only the hearing's decision-maker may draft the determination")
    # Tier 10: OCC on the case version.
    expected = as_int(body, "expected_case_version")
    if expected is not None and expected != case["version"]:
        raise_error(ERR_STALE_CASE_VERSION,
                    "expected_case_version does not match the case's current version")
    # Tier 11: schema.
    responsibility_finding = req_enum(body, "responsibility_finding", FINDINGS)
    standard_of_evidence = req_enum(body, "standard_of_evidence", STANDARDS)
    rationale = req_str(body, "rationale")
    aggravating = opt_int(body, "aggravating_factor_count", 0, non_negative=True)
    mitigating = opt_int(body, "mitigating_factor_count", 0, non_negative=True)
    priors = opt_int(body, "prior_responsible_findings", 0, non_negative=True)
    if not isinstance(body.get("expected_case_version"), int) \
            or isinstance(body.get("expected_case_version"), bool):
        raise_error(ERR_INVALID_REQUEST, "missing or invalid field: expected_case_version")

    det_fields = {
        "case_id": cid,
        "issued_by_id": None,
        "responsibility_finding": responsibility_finding,
        "standard_of_evidence": standard_of_evidence,
        "rationale": rationale,
        "aggravating_factor_count": aggravating,
        "mitigating_factor_count": mitigating,
        "prior_responsible_findings": priors,
        "final_severity_score": None,
        "final_tier": None,
        "status": "DRAFT",
        "issued_at": None,
        "appeal_deadline": None,
    }
    det_fields["provisional_severity_score"] = matrix_score(case, det_fields, "PROVISIONAL")
    rec = new_record("determinations", det_fields)
    # A new DRAFT supersedes any existing DRAFT on the case.
    for d in db["determinations"].values():
        if d["case_id"] == cid and d["status"] == "DRAFT" and d["id"] != rec["id"]:
            d["status"] = "SUPERSEDED"
            touch(d)
    bump_case(case)
    append_event(cid, "DETERMINATION_DRAFTED", caller,
                 {"determination_id": rec["id"],
                  "provisional_severity_score": rec["provisional_severity_score"]})
    return success_object(public(rec), 201)


def _valid_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


@bp.post("/determinations/<did>/issue")
def issue_determination(did):
    caller = authorized(["DecisionMaker"])
    det = require_path("determinations", did)
    case = get_case(det["case_id"])
    body = get_body()
    # Tier 4: determination DRAFT; case DELIBERATION.
    if det["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"determination is {det['status']}, not DRAFT")
    if case["status"] != "DELIBERATION":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"case is {case['status']}, not DELIBERATION")
    # Tier 5: the standard of evidence is pinned at intake.
    soe = as_enum(body, "standard_of_evidence", STANDARDS) or det["standard_of_evidence"]
    if soe != case["standard_of_evidence"]:
        raise_error(ERR_STANDARD_OF_EVIDENCE_MISMATCH,
                    "issued standard_of_evidence differs from the case's pinned standard")

    selections = as_list(body, "sanction_selections")
    finding = det["responsibility_finding"]

    # Pinned computation (PRD 2.9): FINAL matrix score first.
    final_score = matrix_score(case, det, "FINAL")
    cap_tier = tier_of(final_score)

    # Tier 7a: selections non-empty iff finding == RESPONSIBLE.
    if selections is not None:
        if finding == "RESPONSIBLE" and len(selections) == 0:
            raise_error(ERR_SANCTION_OUTSIDE_MATRIX,
                        "a RESPONSIBLE finding requires a non-empty sanction selection")
        if finding != "RESPONSIBLE" and len(selections) > 0:
            raise_error(ERR_SANCTION_OUTSIDE_MATRIX,
                        "sanction selections must be empty for a non-RESPONSIBLE finding")

    # Steps 2-6: restitution cents (per-item rounding first), cap, points, total.
    applied_cents_map = {}
    total_points = final_score
    if selections:
        for idx, sel in enumerate(selections):
            if not isinstance(sel, dict):
                continue
            if sel.get("sanction_type") == "RESTITUTION":
                # Step 4: cap tier TIER_1/TIER_2 rejects rather than clamps.
                if cap_tier in ("TIER_1", "TIER_2"):
                    raise_error(ERR_SANCTION_OUTSIDE_MATRIX,
                                "RESTITUTION requires a cap tier of TIER_3 or TIER_4")
                items = sel.get("restitution_items")
                valid_items = [
                    it for it in items if isinstance(it, dict)
                    and _valid_num(it.get("amount_dollars")) and it.get("amount_dollars") > 0
                    and isinstance(it.get("description"), str) and it.get("description").strip() != ""
                ] if isinstance(items, list) else []
                cents = restitution_applied_cents(valid_items, cap_tier)
                applied_cents_map[idx] = cents
                total_points += restitution_points(cents)
    final_tier = tier_of(total_points)

    # Tier 7b: every selection's type and duration within the final-tier matrix.
    if selections:
        for sel in selections:
            if not isinstance(sel, dict):
                continue
            st = sel.get("sanction_type")
            if not isinstance(st, str) or st not in SANCTION_TYPES:
                continue  # schema tier handles
            if st not in TIER_MATRIX[final_tier]:
                raise_error(ERR_SANCTION_OUTSIDE_MATRIX,
                            f"{st} is not offered by {final_tier}")
            if st in DURATION_TYPES:
                dur = sel.get("duration_days")
                if isinstance(dur, int) and not isinstance(dur, bool):
                    lo, hi = TIER_MATRIX[final_tier][st]
                    if not (lo <= dur <= hi):
                        raise_error(ERR_SANCTION_OUTSIDE_MATRIX,
                                    f"duration_days {dur} outside {final_tier} bounds for {st}")

    # Tier 8: only the completed hearing's decision-maker may issue.
    hearing = _case_hearing_for_determination(case)
    if hearing is not None and caller.user_id != hearing["decision_maker_id"]:
        raise_error(ERR_NOT_HEARING_DECISION_MAKER,
                    "only the hearing's decision-maker may issue the determination")

    # Tier 9: restitution item presence and positivity.
    if selections:
        for sel in selections:
            if isinstance(sel, dict) and sel.get("sanction_type") == "RESTITUTION":
                items = sel.get("restitution_items")
                if not isinstance(items, list) or len(items) == 0:
                    raise_error(ERR_RESTITUTION_ITEMS_REQUIRED,
                                "RESTITUTION requires a non-empty restitution_items array")
                for it in items:
                    if not isinstance(it, dict) \
                            or not isinstance(it.get("description"), str) \
                            or it.get("description", "").strip() == "" \
                            or not _valid_num(it.get("amount_dollars")) \
                            or it.get("amount_dollars") <= 0:
                        raise_error(ERR_RESTITUTION_ITEMS_REQUIRED,
                                    "every restitution item needs a description and amount_dollars > 0")

    # Tier 11: schema for the selections payload.
    if selections is None:
        raise_error(ERR_INVALID_REQUEST, "missing or invalid field: sanction_selections")
    for sel in selections:
        if not isinstance(sel, dict):
            raise_error(ERR_INVALID_REQUEST, "each sanction selection must be an object")
        st = req_enum(sel, "sanction_type", SANCTION_TYPES)
        if st in DURATION_TYPES:
            dur = sel.get("duration_days")
            if not isinstance(dur, int) or isinstance(dur, bool) or dur <= 0:
                raise_error(ERR_INVALID_REQUEST,
                            f"duration_days is required and must be a positive integer for {st}")
        else:
            if sel.get("duration_days") is not None:
                raise_error(ERR_INVALID_REQUEST,
                            f"duration_days is forbidden for {st}")
        if st != "RESTITUTION" and sel.get("restitution_items") is not None:
            raise_error(ERR_INVALID_REQUEST,
                        f"restitution_items is forbidden for {st}")
        if st == "RESTITUTION":
            for it in sel.get("restitution_items", []):
                if not isinstance(it, dict) or not isinstance(it.get("description"), str) \
                        or not _valid_num(it.get("amount_dollars")):
                    raise_error(ERR_INVALID_REQUEST,
                                "restitution items need description and amount_dollars")

    # ---- Commit: issue the determination and create sanctions ----
    now = clock_dt()
    issued_at = fmt_datetime(now)
    appeal_deadline = fmt_datetime(now + timedelta(days=5))
    det["final_severity_score"] = final_score
    det["final_tier"] = final_tier
    det["status"] = "ISSUED"
    det["issued_at"] = issued_at
    det["appeal_deadline"] = appeal_deadline
    det["issued_by_id"] = hearing["decision_maker_id"] if hearing else caller.user_id
    touch(det)

    for idx, sel in enumerate(selections):
        st = sel["sanction_type"]
        new_record("sanctions", {
            "determination_id": did,
            "sanction_type": st,
            "duration_days": sel.get("duration_days") if st in DURATION_TYPES else None,
            "restitution_items": sel.get("restitution_items") if st == "RESTITUTION" else None,
            "applied_restitution_cents": applied_cents_map.get(idx, 0),
            "effective_from": issued_at,
            "status": "ACTIVE",
        })

    if hearing is not None and hearing["status"] == "DELIBERATION":
        hearing["status"] = "COMPLETED"
        touch(hearing)
    case["status"] = "DETERMINATION_ISSUED"
    bump_case(case)
    append_event(case["id"], "DETERMINATION_ISSUED", caller,
                 {"determination_id": did, "final_severity_score": final_score,
                  "final_tier": final_tier})
    auto_notice(case["id"], "DETERMINATION", "BOTH",
                "A determination has been issued on this case.")
    append_event(case["id"], "NOTICE_SENT", caller,
                 {"notice_type": "DETERMINATION", "recipient_side": "BOTH"})
    return success_object(public(det))


@bp.get("/determinations/<did>")
def get_determination(did):
    caller = authorized(READ_ROLES)
    det = require_path("determinations", did)
    case = get_case(det["case_id"])
    check_case_read_access(caller, case)
    return success_object(public(det))


@bp.get("/cases/<cid>/determinations")
def list_determinations(cid):
    caller = authorized(READ_ROLES)
    case = get_case(cid)
    check_case_read_access(caller, case)
    items = [d for d in db["determinations"].values() if d["case_id"] == cid]
    items = apply_filters(items, {"status": request.args.get("status")})
    items = sort_items(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


@bp.get("/determinations")
def list_determinations_filtered():
    authorized(["TitleIXCoordinator", "CaseAdministrator"])
    items = list(db["determinations"].values())
    items = apply_filters(items, {
        "issued_by_id": request.args.get("issued_by_id"),
        "status": request.args.get("status"),
    })
    items = sort_items(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Sanction
# ---------------------------------------------------------------------------

def _sanction_case(sanction):
    det = db["determinations"].get(sanction["determination_id"])
    return get_case(det["case_id"]) if det else None


@bp.get("/determinations/<did>/sanctions")
def list_sanctions(did):
    caller = authorized(READ_ROLES)
    det = require_path("determinations", did)
    case = get_case(det["case_id"])
    check_case_read_access(caller, case)
    items = [s for s in db["sanctions"].values() if s["determination_id"] == did]
    items = apply_filters(items, {
        "status": request.args.get("status"),
        "sanction_type": request.args.get("sanction_type"),
    })
    items = sort_items(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


@bp.get("/sanctions/<sid>")
def get_sanction(sid):
    caller = authorized(READ_ROLES)
    sanction = require_path("sanctions", sid)
    case = _sanction_case(sanction)
    check_case_read_access(caller, case)
    return success_object(public(sanction))


@bp.post("/sanctions/<sid>/mark-complete")
def mark_sanction_complete(sid):
    caller = authorized(["TitleIXCoordinator"])
    sanction = require_path("sanctions", sid)
    if sanction["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"sanction is {sanction['status']}, not ACTIVE")
    if sanction["sanction_type"] not in DURATION_LESS_TYPES:
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    "only duration-less sanction types (WARNING, EXPULSION, RESTITUTION) "
                    "complete via mark-complete")
    case = _sanction_case(sanction)
    sanction["status"] = "COMPLETED"
    touch(sanction)
    bump_case(case)
    append_event(case["id"], "SANCTION_COMPLETED", caller,
                 {"sanction_id": sid, "status": "COMPLETED"})
    return success_object(public(sanction))
