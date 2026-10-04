"""EquitableReliefCase: file (collision guard), list, adjudicate
(GRANTED runs the four-stage calc_relief_repricing cascade)."""
from __future__ import annotations

from authn import (ROLE_BENEFICIARY, ROLE_FIELD_OFFICER, authenticate,
                   authorize, body_beneficiary_ownership, check_ownership)
from clock import (clock_month, month_diff, month_str, parse_month)
from db import find, find_one, get, make_entity, public, sort_entities, touch
from domain import (activate_enrollment, active_lep_cents,
                    rate_schedule_for_year, reprice_beneficiary_part_invoices,
                    sync_penalty)
from envelope import success_list, success_object
from errors import fail
from validate import (body_json, opt_month_str, pagination_args, paginate,
                      req_enum, req_month_str, req_str)

RELIEF_TYPES = ("RETROACTIVE_ENROLLMENT", "PENALTY_WAIVER", "BOTH")
RELIEF_PARTS = ("PART_B", "PART_D")
MISINFORM_SOURCES = ("FEDERAL_AGENCY", "PLAN_REPRESENTATIVE", "EMPLOYER")
_FAR_FUTURE = (9999, 12)


def _live_same_part_enrollment(bid, part):
    return find_one("enrollments",
                    lambda e: e["beneficiary_id"] == bid
                    and e["part"] == part
                    and e["enrollment_status"] in ("PENDING", "ACTIVE"))


def file_relief_case():
    role, uid = authenticate()
    authorize(role, [ROLE_BENEFICIARY, ROLE_FIELD_OFFICER])
    body = body_json()
    body_beneficiary_ownership(role, uid, body)
    bid = req_str(body, "beneficiary_id")
    relief_type = req_enum(body, "relief_type", RELIEF_TYPES)
    part = req_enum(body, "part", RELIEF_PARTS)
    source = req_enum(body, "claimed_misinform_source", MISINFORM_SOURCES)
    description = req_str(body, "description")
    if relief_type in ("RETROACTIVE_ENROLLMENT", "BOTH"):
        requested = req_month_str(body, "requested_effective_month")
    else:
        requested = opt_month_str(body, "requested_effective_month")
    if not get("beneficiaries", bid):
        fail("ERR_BENEFICIARY_NOT_FOUND", "No beneficiary with that id")
    # Filing-time collision guard: create-path ONLY (no live same-part
    # enrollment), retro interval [requested, clock) vs TERMINATED/CANCELLED
    # same-part intervals [eff, end); half-open adjacency allowed.
    if requested is not None and not _live_same_part_enrollment(bid, part):
        req_ym = parse_month(requested)
        cm = clock_month()
        for e in find("enrollments",
                      lambda x: x["beneficiary_id"] == bid
                      and x["part"] == part
                      and x["enrollment_status"] in ("TERMINATED",
                                                     "CANCELLED")):
            s = parse_month(e["effective_month"])
            en = parse_month(e["end_month"]) if e["end_month"] else _FAR_FUTURE
            if month_diff(req_ym, en) < 0 and month_diff(s, cm) < 0:
                fail("ERR_RELIEF_PERIOD_OVERLAP",
                     "Retro interval collides with an existing enrollment")
    case = make_entity("relief_cases", {
        "beneficiary_id": bid,
        "relief_type": relief_type,
        "part": part,
        "requested_effective_month": requested,
        "claimed_misinform_source": source,
        "description": description,
        "status": "UNDER_INVESTIGATION",
    })
    return success_object(public(case), 201)


def adjudicate_relief_case(case_id):
    role, uid = authenticate()
    authorize(role, [ROLE_FIELD_OFFICER])
    body = body_json()
    decision = req_enum(body, "decision", ("GRANTED", "DENIED"))
    case = get("relief_cases", case_id)
    if not case:
        fail("ERR_RELIEF_CASE_NOT_FOUND",
             "No equitable relief case with that id")
    if case["status"] != "UNDER_INVESTIGATION":
        fail("ERR_INVALID_STATE", "Relief case is not UNDER_INVESTIGATION")
    if decision == "DENIED":
        case["status"] = "DENIED"
        touch(case)
        return success_object(public(case))
    # GRANTED: calc_relief_repricing, four stages
    bid = case["beneficiary_id"]
    part = case["part"]
    cm = clock_month()
    new_eff_ym = None
    # Stage 1 — retroactive enrollment
    if case["relief_type"] in ("RETROACTIVE_ENROLLMENT", "BOTH"):
        new_eff_ym = parse_month(case["requested_effective_month"])
        ent = _live_same_part_enrollment(bid, part)
        if ent:
            if month_diff(new_eff_ym, parse_month(ent["effective_month"])) >= 0:
                fail("ERR_EFFECTIVE_DATE_INVALID",
                     "requested_effective_month must be strictly earlier "
                     "than the existing enrollment's effective_month")
            ent["effective_month"] = month_str(new_eff_ym)
            touch(ent)
        else:
            ent = make_entity("enrollments", {
                "beneficiary_id": bid,
                "part": part,
                "enrollment_status": "PENDING",
                "collection_status": "PENDING_SETUP",
                "effective_month": month_str(new_eff_ym),
                "end_month": None,
                "enrolled_via_window": "RELIEF",
            })
            if month_diff(new_eff_ym, cm) <= 0:
                activate_enrollment(ent)
        # Penalty recompute: below threshold -> VOIDED; still positive ->
        # update in place (ACTIVE); creates one if none and gap non-zero
        sync_penalty(bid, part, new_eff_ym, exclude_enrollment_id=ent["id"])
    # Stage 2 — waiver
    if case["relief_type"] in ("PENALTY_WAIVER", "BOTH"):
        for a in find("penalties",
                      lambda p: p["beneficiary_id"] == bid
                      and p["part"] == part and p["status"] == "ACTIVE"):
            a["status"] = "WAIVED"
            touch(a)
    # Stage 3 — determinations: supersede + FINAL replacement per live row
    for det in sort_entities(find(
            "determinations",
            lambda d: d["beneficiary_id"] == bid
            and d["part"] == part and d["status"] != "SUPERSEDED")):
        det["status"] = "SUPERSEDED"
        touch(det)
        schedule = rate_schedule_for_year(det["coverage_year"])
        lep = active_lep_cents(bid, part, schedule) if schedule else 0
        make_entity("determinations", {
            "beneficiary_id": bid,
            "coverage_year": det["coverage_year"],
            "part": part,
            "status": "FINAL",
            "tax_year_used": det["tax_year_used"],
            "irmaa_tier": det["irmaa_tier"],
            "base_premium_cents": det["base_premium_cents"],
            "irmaa_surcharge_cents": det["irmaa_surcharge_cents"],
            "lep_cents": lep,
            "total_premium_cents": (det["base_premium_cents"]
                                    + det["irmaa_surcharge_cents"] + lep),
            "created_by_user_id": uid,
        })
    # Stage 4 — invoices: service months >= the new effective month
    # (a pure waiver reprices every service month of the part)
    reprice_beneficiary_part_invoices(bid, part, cutoff_ym=new_eff_ym)
    case["status"] = "GRANTED"
    touch(case)
    return success_object(public(case))


def list_relief_cases(beneficiary_id):
    role, uid = authenticate()
    authorize(role, [ROLE_BENEFICIARY, ROLE_FIELD_OFFICER])
    check_ownership(role, uid, beneficiary_id)
    if not get("beneficiaries", beneficiary_id):
        fail("ERR_BENEFICIARY_NOT_FOUND", "No beneficiary with that id")
    limit, offset = pagination_args()
    rows = sort_entities(find("relief_cases",
                              lambda e: e["beneficiary_id"] == beneficiary_id))
    page, total = paginate(rows, limit, offset)
    return success_list([public(e) for e in page], limit, offset, total)


def register(app):
    app.add_url_rule("/medicare/equitable-relief-cases", "file_relief_case",
                     file_relief_case, methods=["POST"])
    app.add_url_rule(
        "/medicare/beneficiaries/<beneficiary_id>/equitable-relief-cases",
        "list_relief_cases", list_relief_cases, methods=["GET"])
    app.add_url_rule("/medicare/equitable-relief-cases/<case_id>/adjudicate",
                     "adjudicate_relief_case", adjudicate_relief_case,
                     methods=["POST"])
