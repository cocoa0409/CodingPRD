"""Composite setup helpers.

Every function here drives the API through real requests — there is no direct
database access — and unwraps each setup call with `get_success_data`, which
already returns the inner `data` payload of the envelope. Nothing here indexes
`["data"]` a second time.

The helpers are ordinary functions rather than pytest fixtures so that a test can
compose them in whatever order its scenario needs; `conftest.py` exposes only the
client and the per-test clock reset.
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import (
    ACTIVITY_WORKSHOP,
    BODY_COMMISSION,
    BODY_COUNCIL,
    CLOCK_STARTUP,
    DECISION_APPROVE,
    DOC_EIR,
    ELEMENT_HOUSING,
    GROUP_GENERAL,
    GROUP_LOW_INCOME,
    GROUP_RENTER,
    INVENTORY_DEMOGRAPHIC,
    INVENTORY_EMPLOYMENT,
    INVENTORY_HOUSING,
    INVENTORY_LAND_USE,
    METHOD_TREND,
    OUTCOME_ADOPT,
    OUTCOME_RECOMMEND,
    STATE_REVIEW_CERTIFIED,
    STATUTORY_ELEMENT_TYPES,
    TIER_ORDER,
)
from .test_users import CLERK, CONSULTANT, DIRECTOR, STAFF, STATE

# ---------------------------------------------------------------- reference clock
# The startup clock is 2026-08-01T00:00:00Z; instants below are placed relative to it.
T_CIRCULATION = "2026-08-01T00:00:00.000Z"
T_COMMENT_END_EIR = "2026-09-15T00:00:00.000Z"
# The reference workshop sits *before* the startup clock, so it can be closed
# without moving the clock at all.
T_ACTIVITY_START = "2026-07-10T18:00:00.000Z"
T_ACTIVITY_END = "2026-07-10T20:00:00.000Z"
# A second, later window on the same reference day, for two-activity setups.
T_ACTIVITY_2_START = "2026-07-11T18:00:00.000Z"
T_ACTIVITY_2_END = "2026-07-11T20:00:00.000Z"
# Notice is published on the EIR comment-window close, ten clear days ahead of the
# commission slot, which is the minimum the notice rule accepts.
T_COMMISSION_NOTICE = "2026-09-15T00:00:00.000Z"
T_COMMISSION_START = "2026-09-25T18:00:00.000Z"
T_COMMISSION_END = "2026-09-25T21:00:00.000Z"
T_COUNCIL_NOTICE = "2026-09-15T00:00:00.000Z"
T_COUNCIL_START = "2026-10-09T18:00:00.000Z"
T_COUNCIL_END = "2026-10-09T21:00:00.000Z"
# adopted_at + 365 days
T_ACTION_DUE = "2027-10-09T18:00:00.000Z"

# A ten-record workshop roster: four underrepresented respondents out of ten
# records under STANDARD weighting gives exactly 40.0 percent.
ROSTER_EQUITY_40 = [
    {"respondent_ref": "r-01", "demographic_group": GROUP_LOW_INCOME},
    {"respondent_ref": "r-02", "demographic_group": GROUP_LOW_INCOME},
    {"respondent_ref": "r-03", "demographic_group": GROUP_RENTER},
    {"respondent_ref": "r-04", "demographic_group": GROUP_RENTER},
    {"respondent_ref": "r-05", "demographic_group": GROUP_GENERAL},
    {"respondent_ref": "r-06", "demographic_group": GROUP_GENERAL},
    {"respondent_ref": "r-07", "demographic_group": GROUP_GENERAL},
    {"respondent_ref": "r-08", "demographic_group": GROUP_GENERAL},
    {"respondent_ref": "r-09", "demographic_group": GROUP_GENERAL},
    {"respondent_ref": "r-10", "demographic_group": GROUP_GENERAL},
]

# The reference allocation set: 3600 assigned units against an 11700-unit pool,
# so every tier is fully accommodated and housing_shortfall_total is zero.
ASSIGNED_NO_SHORTFALL = {
    "VERY_LOW": 900,
    "LOW": 700,
    "MODERATE": 800,
    "ABOVE_MODERATE": 1200,
}


# ------------------------------------------------------------------ tier 1: plans
def create_plan(api, headers=DIRECTOR, **overrides) -> Dict[str, Any]:
    """Open a plan cycle. A fresh plan is DRAFTING / NOT_SUBMITTED / CAPACITY_HOLD."""
    return get_success_data(
        api.create_plan_update(f.plan_update_payload(**overrides), headers), 201
    )


def read_plan(api, plan_id, headers=DIRECTOR) -> Dict[str, Any]:
    return get_success_data(api.get_plan_update(plan_id, headers))


def read_summary(api, plan_id, headers=DIRECTOR) -> Dict[str, Any]:
    return get_success_data(api.get_compliance_summary(plan_id, headers))


def set_clock(api, instant: str, headers=DIRECTOR) -> Dict[str, Any]:
    return get_success_data(api.set_clock(instant, headers))


# ------------------------------------------------------- tier 1: inventory record
def create_tabular_inventory(
    api, plan_id, inventory_type=INVENTORY_DEMOGRAPHIC, headers=STAFF, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_inventory_dataset(
            f.tabular_inventory_payload(plan_id, inventory_type, **overrides), headers
        ),
        201,
    )


def create_land_use_inventory(api, plan_id, headers=STAFF, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_inventory_dataset(
            f.land_use_inventory_payload(plan_id, **overrides), headers
        ),
        201,
    )


def certify_inventory(api, inventory_id, headers=DIRECTOR) -> Dict[str, Any]:
    """The certifier must differ from the author, so the default staff/director
    split satisfies the segregation-of-duties comparison."""
    return get_success_data(api.certify_inventory_dataset(inventory_id, {}, headers))


def certified_inventory_set(api, plan_id, land_use=None) -> Dict[str, Dict[str, Any]]:
    """Certify one dataset of each of the four inventory types.

    "the plan must hold a CERTIFIED dataset for each of DEMOGRAPHIC, HOUSING,
    EMPLOYMENT and LAND_USE".  Returns the certified rows keyed by inventory_type.
    """
    land_use = land_use or {}
    out: Dict[str, Dict[str, Any]] = {}
    for inv_type in (INVENTORY_DEMOGRAPHIC, INVENTORY_HOUSING, INVENTORY_EMPLOYMENT):
        row = create_tabular_inventory(api, plan_id, inv_type)
        out[inv_type] = certify_inventory(api, row["id"])
    row = create_land_use_inventory(api, plan_id, **land_use)
    out[INVENTORY_LAND_USE] = certify_inventory(api, row["id"])
    return out


# -------------------------------------------------------- tier 1: growth scenarios
def create_scenario(
    api, plan_id, land_use_id, method=METHOD_TREND, headers=STAFF, **overrides
) -> Dict[str, Any]:
    """Re-reads the pinned dataset so `expected_inventory_version` is always current.

    "a second scenario pinned to the same dataset must re-read it first."
    """
    inventory = get_success_data(api.get_inventory_dataset(land_use_id, headers))
    payload = f.growth_scenario_payload(
        plan_id, land_use_id, inventory["version"], method=method, **overrides
    )
    return get_success_data(api.create_growth_scenario(payload, headers), 201)


def adopt_scenario(api, scenario_id, headers=DIRECTOR) -> Dict[str, Any]:
    return get_success_data(api.adopt_growth_scenario(scenario_id, {}, headers))


def plan_with_adopted_scenario(
    api, method=METHOD_TREND, land_use=None, **plan_overrides
) -> Dict[str, Any]:
    """Plan → four certified inventories → one adopted scenario.

    With the reference acreage a TREND scenario adopts an 11700-unit GROSS_CAPACITY
    pool and a POLICY scenario a 7115-unit NET_CAPACITY pool.
    """
    plan = create_plan(api, **plan_overrides)
    inventories = certified_inventory_set(api, plan["id"], land_use=land_use)
    scenario = create_scenario(
        api, plan["id"], inventories[INVENTORY_LAND_USE]["id"], method=method
    )
    scenario = adopt_scenario(api, scenario["id"])
    return {
        "plan": plan,
        "plan_id": plan["id"],
        "inventories": inventories,
        "land_use_inventory_id": inventories[INVENTORY_LAND_USE]["id"],
        "scenario": scenario,
        "scenario_id": scenario["id"],
    }


# ---------------------------------------------------- tier 1: housing allocations
def create_allocation(api, plan_id, income_tier, assigned_units, headers=STATE, **kw):
    return get_success_data(
        api.create_housing_allocation(
            f.housing_allocation_payload(plan_id, income_tier, assigned_units, **kw),
            headers,
        ),
        201,
    )


def create_all_allocations(
    api, plan_id, assigned: Optional[Dict[str, int]] = None
) -> Dict[str, Dict[str, Any]]:
    """One allocation row per income tier, created in statutory tier order."""
    assigned = assigned or ASSIGNED_NO_SHORTFALL
    return {
        tier: create_allocation(api, plan_id, tier, assigned[tier])
        for tier in TIER_ORDER
        if tier in assigned
    }


# ------------------------------------------------------ tier 2: element hierarchy
def create_element(api, plan_id, element_type, headers=STAFF, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_plan_element(
            f.plan_element_payload(plan_id, element_type, **overrides), headers
        ),
        201,
    )


def read_element(api, element_id, headers=STAFF) -> Dict[str, Any]:
    return get_success_data(api.get_plan_element(element_id, headers))


def submit_element(api, element_id, headers=STAFF) -> Dict[str, Any]:
    return get_success_data(api.submit_element_review(element_id, {}, headers))


def approve_element(api, element_id, headers=DIRECTOR, note=None) -> Dict[str, Any]:
    """Approve an element in IN_REVIEW. The default director identifier differs from
    the default staff author, so the duties comparison passes."""
    return get_success_data(
        api.record_review_decision(
            element_id, f.review_decision_payload(DECISION_APPROVE, note), headers
        )
    )


def approved_element(api, plan_id, element_type, headers=STAFF, **overrides):
    """DRAFT → IN_REVIEW → APPROVED in one call, for elements a test does not
    otherwise care about."""
    element = create_element(api, plan_id, element_type, headers, **overrides)
    submit_element(api, element["id"], headers)
    return approve_element(api, element["id"])


def five_approved_elements(api, plan_id) -> Dict[str, Dict[str, Any]]:
    """One APPROVED element of each statutory type — the state's rung-1 requirement,
    "required_elements_complete_count must be 5".

    HOUSING is approved last on purpose: its approval requires the plan to already
    hold an adopted projection.
    """
    out: Dict[str, Dict[str, Any]] = {}
    ordered = [t for t in STATUTORY_ELEMENT_TYPES if t != ELEMENT_HOUSING]
    ordered.append(ELEMENT_HOUSING)
    for element_type in ordered:
        out[element_type] = approved_element(api, plan_id, element_type)
    return out


def five_draft_elements(api, plan_id) -> Dict[str, Dict[str, Any]]:
    return {
        element_type: create_element(api, plan_id, element_type)
        for element_type in STATUTORY_ELEMENT_TYPES
    }


# ------------------------------------------------------- tier 2: consistency graph
def create_link(api, source_id, target_id, headers=STAFF, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_consistency_link(
            f.consistency_link_payload(source_id, target_id, **overrides), headers
        ),
        201,
    )


def reconcile_link(api, link_id, headers=DIRECTOR, note=None) -> Dict[str, Any]:
    return get_success_data(
        api.reconcile_consistency_link(
            link_id, f.reconcile_payload(note) if note else f.reconcile_payload(), headers
        )
    )


# ---------------------------------------------------------- tier 2: engagement
def create_venue(api, headers=STAFF, **overrides) -> Dict[str, Any]:
    return get_success_data(api.create_venue(f.venue_payload(**overrides), headers), 201)


def create_equity_venue(api, headers=STAFF, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_venue(f.equity_eligible_venue_payload(**overrides), headers), 201
    )


def create_activity(api, plan_id, headers=STAFF, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_engagement_activity(
            f.engagement_activity_payload(plan_id, **overrides), headers
        ),
        201,
    )


def add_participation(api, activity_id, headers=STAFF, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_participation_record(
            f.participation_record_payload(activity_id, **overrides), headers
        ),
        201,
    )


def add_roster(api, activity_id, roster: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [add_participation(api, activity_id, **entry) for entry in roster]


def complete_activity(api, activity_id, headers=STAFF) -> Dict[str, Any]:
    return get_success_data(api.complete_engagement_activity(activity_id, {}, headers))


def cancel_activity(api, activity_id, headers=STAFF, reason=None) -> Dict[str, Any]:
    payload = {"cancellation_reason": reason} if reason is not None else {}
    return get_success_data(api.cancel_engagement_activity(activity_id, payload, headers))


def completed_workshop(
    api,
    plan_id,
    roster: Optional[Sequence[Dict[str, Any]]] = None,
    venue_id: Optional[str] = None,
    start_at: str = T_ACTIVITY_START,
    end_at: str = T_ACTIVITY_END,
    restore_clock_to: Optional[str] = None,
) -> Dict[str, Any]:
    """Schedule a workshop, capture a roster, advance the clock to `end_at` and close it.

    "the logical clock must have reached the activity's end_at — an activity cannot
    be closed before it has happened".  The default roster lands the plan at exactly
    40.0 percent, which is the inclusive threshold the posture ladder passes.
    """
    roster = roster if roster is not None else ROSTER_EQUITY_40
    if venue_id is None:
        venue_id = create_venue(api)["id"]
    activity = create_activity(
        api,
        plan_id,
        activity_type=ACTIVITY_WORKSHOP,
        venue_id=venue_id,
        start_at=start_at,
        end_at=end_at,
    )
    add_roster(api, activity["id"], roster)
    if end_at > CLOCK_STARTUP:
        set_clock(api, end_at)
    completed = complete_activity(api, activity["id"])
    if restore_clock_to:
        set_clock(api, restore_clock_to)
    return completed


# --------------------------------------------------- tier 3: environmental review
def create_review(api, plan_id, document_type=DOC_EIR, headers=CONSULTANT, **overrides):
    return get_success_data(
        api.create_environmental_review(
            f.environmental_review_payload(plan_id, document_type, **overrides), headers
        ),
        201,
    )


def add_alternative(api, review_id, headers=CONSULTANT, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_plan_alternative(
            f.plan_alternative_payload(review_id, **overrides), headers
        ),
        201,
    )


def circulate_review(api, review_id, headers=CONSULTANT) -> Dict[str, Any]:
    return get_success_data(api.circulate_environmental_review(review_id, {}, headers))


def select_preferred(api, review_id, headers=CONSULTANT) -> Dict[str, Any]:
    """Returns the winning PlanAlternative — the selector is server-side and the
    client supplies no alternative id."""
    return get_success_data(api.select_preferred_alternative(review_id, {}, headers))


def certify_review(api, review_id, headers=DIRECTOR) -> Dict[str, Any]:
    return get_success_data(api.certify_environmental_review(review_id, {}, headers))


DEFAULT_ALTERNATIVES = [
    {"label": "Alternative A", "traffic_vmt_index": 40, "ghg_index": 40,
     "habitat_index": 40, "water_index": 40},
    {"label": "Alternative B", "traffic_vmt_index": 60, "ghg_index": 60,
     "habitat_index": 60, "water_index": 60},
]


def circulated_review(
    api,
    plan_id,
    document_type=DOC_EIR,
    alternatives: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Open a review, score two alternatives and release it for public comment.

    Circulation must happen while the clock still sits at its startup value for the
    comment window to end at the reference instant 2026-09-15T00:00:00.000Z.
    """
    alternatives = alternatives if alternatives is not None else DEFAULT_ALTERNATIVES
    review = create_review(api, plan_id, document_type)
    alts = [add_alternative(api, review["id"], **spec) for spec in alternatives]
    circulated = circulate_review(api, review["id"])
    return {"review": circulated, "review_id": review["id"], "alternatives": alts}


# ------------------------------------------------- tier 3: full lifecycle shortcut
def state_certified_plan(
    api,
    method=METHOD_TREND,
    land_use=None,
    assigned: Optional[Dict[str, int]] = None,
    roster: Optional[Sequence[Dict[str, Any]]] = None,
    document_type=DOC_EIR,
    alternatives: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Drive a plan all the way to STATE_CERTIFIED with a CLEAR posture.

    Every rung of the state-mandate checklist of PRD section 3.8 is satisfied in
    turn: five APPROVED elements, all four allocation tiers, no open consistency
    link, a CERTIFIED environmental review, zero housing shortfall and an equity
    share of exactly 40.0 percent.

    The clock is walked forward only where a gate demands it — circulation happens
    at the startup instant so the EIR comment window closes at
    2026-09-15T00:00:00.000Z, and the clock is left there.
    """
    ctx = plan_with_adopted_scenario(api, method=method, land_use=land_use)
    plan_id = ctx["plan_id"]
    ctx["allocations"] = create_all_allocations(api, plan_id, assigned)
    ctx["elements"] = five_approved_elements(api, plan_id)

    # Circulate before the clock moves so the comment window is the reference one.
    review_ctx = circulated_review(api, plan_id, document_type, alternatives)
    ctx["review_id"] = review_ctx["review_id"]
    ctx["alternatives"] = review_ctx["alternatives"]
    ctx["preferred"] = select_preferred(api, review_ctx["review_id"])

    ctx["activity"] = completed_workshop(api, plan_id, roster=roster)

    set_clock(api, T_COMMENT_END_EIR)
    ctx["review"] = certify_review(api, review_ctx["review_id"])

    ctx["submitted_plan"] = get_success_data(
        api.submit_plan_to_state(plan_id, {"submission_note": "First filing."}, DIRECTOR)
    )
    ctx["plan"] = get_success_data(
        api.record_state_determination(
            plan_id,
            f.state_determination_payload(
                STATE_REVIEW_CERTIFIED, "Mandate satisfied in full."
            ),
            STATE,
        )
    )
    return ctx


# ------------------------------------------------------------------ tier 3: hearings
def create_hearing(api, plan_id, headers=CLERK, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_hearing(f.hearing_payload(plan_id, **overrides), headers), 201
    )


def open_hearing(api, hearing_id, headers=CLERK) -> Dict[str, Any]:
    return get_success_data(api.open_hearing(hearing_id, {}, headers))


def record_outcome(api, hearing_id, outcome, headers=CLERK, note=None) -> Dict[str, Any]:
    return get_success_data(
        api.record_hearing_outcome(hearing_id, f.outcome_payload(outcome, note), headers)
    )


def scheduled_commission_hearing(api, plan_id, **overrides) -> Dict[str, Any]:
    """A COMMISSION hearing on the reference calendar: notice 15 days ahead of a
    2026-10-05T18:00:00.000Z start, comfortably clear of the ten-day lead rule."""
    params = {
        "body_type": BODY_COMMISSION,
        "scheduled_start": T_COMMISSION_START,
        "scheduled_end": T_COMMISSION_END,
        "notice_published_at": T_COMMISSION_NOTICE,
    }
    params.update(overrides)
    return create_hearing(api, plan_id, **params)


def scheduled_council_hearing(api, plan_id, **overrides) -> Dict[str, Any]:
    params = {
        "body_type": BODY_COUNCIL,
        "scheduled_start": T_COUNCIL_START,
        "scheduled_end": T_COUNCIL_END,
        "notice_published_at": T_COUNCIL_NOTICE,
    }
    params.update(overrides)
    return create_hearing(api, plan_id, **params)


def open_commission_hearing(api, plan_id, **overrides) -> Dict[str, Any]:
    """Schedule a commission hearing, advance the clock to its scheduled start and
    gavel it in. "the logical clock must have reached scheduled_start"."""
    hearing = scheduled_commission_hearing(api, plan_id, **overrides)
    set_clock(api, overrides.get("scheduled_start", T_COMMISSION_START))
    return open_hearing(api, hearing["id"])


def recommended_plan(api, **kwargs) -> Dict[str, Any]:
    """STATE_CERTIFIED → COMMISSION_RECOMMENDED via a RECOMMEND outcome on an open
    commission hearing."""
    ctx = state_certified_plan(api, **kwargs)
    hearing = open_commission_hearing(api, ctx["plan_id"])
    ctx["commission_hearing"] = record_outcome(api, hearing["id"], OUTCOME_RECOMMEND)
    ctx["plan"] = read_plan(api, ctx["plan_id"])
    return ctx


def adopted_plan(api, **kwargs) -> Dict[str, Any]:
    """COMMISSION_RECOMMENDED → ADOPTED via an ADOPT outcome on an open council
    hearing. `ADOPTED` is terminal for the plan and locks its whole aggregate."""
    ctx = recommended_plan(api, **kwargs)
    council = scheduled_council_hearing(api, ctx["plan_id"])
    set_clock(api, T_COUNCIL_START)
    open_hearing(api, council["id"])
    ctx["council_hearing"] = record_outcome(api, council["id"], OUTCOME_ADOPT)
    ctx["plan"] = read_plan(api, ctx["plan_id"])
    return ctx


# --------------------------------------------------------- tier 3: amendments
def propose_amendment(api, hearing_id, element_id, headers=CLERK, **overrides):
    """Re-reads the target element so `expected_element_version` is current.

    "An element's version advances on every prior amendment docketing ... so a clerk
    who has been away from the record must re-read the element before moving again."
    """
    element = read_element(api, element_id)
    payload = f.amendment_payload(hearing_id, element_id, element["version"], **overrides)
    return get_success_data(api.create_amendment(payload, headers), 201)


def adopt_amendment(api, amendment_id, headers=None) -> Dict[str, Any]:
    """Adopted by a second clerk: "The clerk adopting must not be the clerk who
    moved it"."""
    from .test_users import CLERK_2

    return get_success_data(
        api.adopt_amendment(amendment_id, {}, headers or CLERK_2)
    )


def withdraw_amendment(api, amendment_id, headers=CLERK, reason=None) -> Dict[str, Any]:
    payload = {"withdrawal_reason": reason} if reason is not None else {}
    return get_success_data(api.withdraw_amendment(amendment_id, payload, headers))


def rescind_amendment(api, amendment_id, headers=CLERK, reason="Motion reversed."):
    return get_success_data(
        api.rescind_amendment(amendment_id, {"rescission_reason": reason}, headers)
    )


# ------------------------------------------------ tier 4: implementation program
def create_action(api, plan_id, source_element_id, headers=STAFF, **overrides):
    return get_success_data(
        api.create_implementation_action(
            f.implementation_action_payload(plan_id, source_element_id, **overrides),
            headers,
        ),
        201,
    )


def record_reading(api, action_id, reading_value, headers=STAFF) -> Dict[str, Any]:
    return get_success_data(
        api.record_indicator_reading(action_id, {"reading_value": reading_value}, headers)
    )


def complete_action(api, action_id, headers=STAFF) -> Dict[str, Any]:
    return get_success_data(api.complete_implementation_action(action_id, {}, headers))


# --------------------------------------------------------------------- utilities
def rows_of(response) -> List[Dict[str, Any]]:
    """List-endpoint rows, for setup steps that only need the collection."""
    return get_success_data(response)
