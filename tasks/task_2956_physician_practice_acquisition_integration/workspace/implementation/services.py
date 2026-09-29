"""Derived fields, cascades and the shared precedence gates."""

from decimal import Decimal

import calc
import clock
import store
from errors import ApiError
from store import set_field, mark

FROZEN_CLEARANCES = ("FLAGGED", "SUSPENDED")


# ---------------------------------------------------------------------------
# Shared gates
# ---------------------------------------------------------------------------

def check_freeze(acquisition):
    """Rank 15: the compliance-clearance freeze (PRD section 2.10)."""
    if acquisition["compliance_clearance"] in FROZEN_CLEARANCES:
        raise ApiError(
            "ERR_COMPLIANCE_CLEARANCE_BLOCKED",
            "Acquisition compliance_clearance is %s; the deal is frozen for new work."
            % acquisition["compliance_clearance"],
        )


def check_occ(acquisition, expected_version):
    """Rank 13: optimistic concurrency on the Acquisition aggregate."""
    if expected_version != acquisition["version"]:
        raise ApiError(
            "ERR_STALE_ACQUISITION_VERSION",
            "expected_acquisition_version %d does not match the stored version %d."
            % (expected_version, acquisition["version"]),
        )


def scope_mismatch(message):
    return ApiError("ERR_ACQUISITION_SCOPE_MISMATCH", message)


# ---------------------------------------------------------------------------
# Derived acquisition fields
# ---------------------------------------------------------------------------

def recompute_posture(acquisition):
    tasks = store.where("readiness_tasks", acquisition_id=acquisition["id"])
    set_field(acquisition, "readiness_posture",
              calc.acquisition_readiness_posture(tasks))


def recompute_retention_pool(acquisition):
    offers = store.where("staff_transition_offers",
                         acquisition_id=acquisition["id"])
    committed = sum(o["retention_bonus_cents"] for o in offers
                    if o["status"] in ("EXTENDED", "ACCEPTED"))
    set_field(acquisition, "retention_pool_committed_cents", committed)
    set_field(acquisition, "retention_pool_available_cents",
              acquisition["retention_pool_total_cents"] - committed)


def recompute_escrow(acquisition):
    items = store.where("liability_items", acquisition_id=acquisition["id"])
    committed = sum(i["escrowed_amount_cents"] for i in items
                    if i["disposition"] == "ESCROWED")
    set_field(acquisition, "escrow_committed_cents", committed)
    set_field(acquisition, "escrow_available_cents",
              acquisition["escrow_total_cents"] - committed)


def seated_offer_count(acquisition):
    offers = store.where("staff_transition_offers",
                         acquisition_id=acquisition["id"])
    return len([o for o in offers if o["status"] in ("EXTENDED", "ACCEPTED")])


def recompute_hr_coverage(acquisition):
    coverage = calc.hr_staffing_coverage(
        seated_offer_count(acquisition),
        acquisition["required_staff_headcount"],
    )
    set_field(acquisition, "hr_staffing_coverage_pct", coverage)
    return coverage


def recompute_employment_status(physician):
    plans = store.where("compensation_plans", physician_id=physician["id"])
    status = "PROSPECTIVE"
    if any(p["status"] == "EXECUTED" for p in plans):
        status = "EMPLOYED"
    elif any(p["status"] == "APPROVED" for p in plans):
        status = "OFFERED"
    elif plans:
        newest = store.ordered(plans)[-1]
        if newest["status"] == "WITHDRAWN":
            status = "DECLINED"
    set_field(physician, "employment_status", status)


# ---------------------------------------------------------------------------
# Checklist cascades
# ---------------------------------------------------------------------------

def find_task(acquisition, task_code):
    rows = store.where("readiness_tasks", acquisition_id=acquisition["id"],
                       task_code=task_code)
    return rows[0] if rows else None


def cascade_fail_task(acquisition, task_code, failure_reason):
    """Set the named checklist line to FAILED when it is IN_PROGRESS or COMPLETE."""
    task = find_task(acquisition, task_code)
    if task is not None and task["status"] in ("IN_PROGRESS", "COMPLETE"):
        was_complete = task["status"] == "COMPLETE"
        set_field(task, "status", "FAILED")
        set_field(task, "failure_reason", failure_reason)
        if was_complete:
            set_field(task, "verified_by_user_id", None)


def cascade_complete_task(acquisition, task_code):
    """Set the named checklist line to COMPLETE when it is currently IN_PROGRESS."""
    task = find_task(acquisition, task_code)
    if task is not None and task["status"] == "IN_PROGRESS":
        set_field(task, "status", "COMPLETE")


# ---------------------------------------------------------------------------
# Compensation-plan cascades
# ---------------------------------------------------------------------------

def apply_plan_return(plan):
    """The bounded revision cycle, shared by the direct request and both cascades."""
    landing = calc.plan_return_outcome(plan["returned_count"])
    set_field(plan, "status", landing)
    set_field(plan, "returned_count", plan["returned_count"] + 1)
    if landing == "WITHDRAWN":
        physician = store.get("physicians", plan["physician_id"])
        if physician is not None:
            recompute_employment_status(physician)


def return_submitted_plans(acquisition):
    for plan in store.ordered(store.where("compensation_plans",
                                          acquisition_id=acquisition["id"])):
        if plan["status"] == "SUBMITTED":
            apply_plan_return(plan)


def flag_clearance(acquisition):
    """CLEARED -> FLAGGED, whether requested directly or arriving as a cascade."""
    set_field(acquisition, "compliance_clearance", "FLAGGED")
    return_submitted_plans(acquisition)


# ---------------------------------------------------------------------------
# Valuation and offer cascades
# ---------------------------------------------------------------------------

def supersede_open_opinions(acquisition):
    for opinion in store.ordered(store.where("valuation_opinions",
                                             acquisition_id=acquisition["id"])):
        if opinion["status"] in ("DRAFT", "SUBMITTED"):
            set_field(opinion, "status", "SUPERSEDED")


def rescind_extended_offers(acquisition):
    for offer in store.ordered(store.where("staff_transition_offers",
                                           acquisition_id=acquisition["id"])):
        if offer["status"] == "EXTENDED":
            set_field(offer, "status", "RESCINDED")
    recompute_retention_pool(acquisition)
    recompute_hr_coverage(acquisition)


def rescind_draft_offers(acquisition):
    for offer in store.ordered(store.where("staff_transition_offers",
                                           acquisition_id=acquisition["id"])):
        if offer["status"] == "DRAFT":
            set_field(offer, "status", "RESCINDED")


# ---------------------------------------------------------------------------
# Lookups used by several gates
# ---------------------------------------------------------------------------

def accepted_fmv_opinions(acquisition):
    return [o for o in store.where("valuation_opinions",
                                   acquisition_id=acquisition["id"])
            if o["opinion_type"] == "FMV" and o["status"] == "ACCEPTED"]


def pinned_fmv_opinion(acquisition):
    for opinion in accepted_fmv_opinions(acquisition):
        if opinion["is_pinned"]:
            return opinion
    return None


def accepted_reasonable_cr(acquisition):
    for opinion in store.where("valuation_opinions",
                               acquisition_id=acquisition["id"]):
        if (opinion["opinion_type"] == "COMMERCIAL_REASONABLENESS"
                and opinion["status"] == "ACCEPTED"
                and opinion["cr_conclusion"] == "REASONABLE"):
            return opinion
    return None


def plans_of(acquisition):
    return store.where("compensation_plans", acquisition_id=acquisition["id"])


def physicians_of(acquisition):
    return store.where("physicians", acquisition_id=acquisition["id"])


def expired_on(date_string):
    """True when the stored YYYY-MM-DD value is strictly before the logical date."""
    if date_string is None:
        return False
    return clock.parse_date(date_string) < clock.CLOCK.today()


# ---------------------------------------------------------------------------
# Response helpers: commit the request's version bumps, then serialise.
# ---------------------------------------------------------------------------

def respond(row, status=200):
    import envelope
    import serialize
    store.commit()
    return envelope.object_response(serialize.dump(row), status)


def respond_created(row):
    return respond(row, 201)
