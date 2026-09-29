"""Composite setup helpers.

Every helper here performs setup only: it drives the API through the same public
endpoints a client would use and returns the resulting resources so that a test
can go straight to the behaviour it is about.

The helpers are deliberately phased.  A phase never performs a hop that
invalidates the precondition an earlier phase established, so a test can stop at
any phase and build the rest itself.  For example `draft_policy_with_hull` stops
while the policy is still `DRAFT`, and binding is a separate call, because tests
about draft-only rules need the earlier state.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from . import test_users as users
from .types import (
    CoverageDecision,
    JsonDict,
    LossType,
    SalvageAction,
    SettlementBasis,
    WarrantyFinding,
)


# ----------------------------------------------------------------------
# Phase 0 — the logical clock
# ----------------------------------------------------------------------
def advance_clock(api, current_utc: str) -> JsonDict:
    """Reposition the logical clock, which also runs the policy expiry sweep."""
    return get_success_data(
        api.set_clock(f.clock_payload(current_utc), headers=users.UNDERWRITER)
    )


# ----------------------------------------------------------------------
# Phase 1 — the risk register
# ----------------------------------------------------------------------
def make_operator(api, payload: JsonDict = None, headers=None) -> JsonDict:
    return get_success_data(
        api.create_operator(
            payload if payload is not None else f.operator_payload(),
            headers=headers or users.UNDERWRITER,
        )
    )


def make_aircraft(api, payload: JsonDict = None, headers=None) -> JsonDict:
    return get_success_data(
        api.create_aircraft(
            payload if payload is not None else f.aircraft_payload(),
            headers=headers or users.UNDERWRITER,
        )
    )


def make_pilot(api, payload: JsonDict = None, headers=None) -> JsonDict:
    return get_success_data(
        api.create_pilot(
            payload if payload is not None else f.pilot_payload(),
            headers=headers or users.UNDERWRITER,
        )
    )


def verify_hours(api, pilot_id: str, **overrides) -> JsonDict:
    return get_success_data(
        api.verify_pilot_hours(
            pilot_id, f.hours_verification_payload(**overrides), headers=users.UNDERWRITER
        )
    )


def registered_book(api, clock: str = f.CLOCK_BEFORE_INCEPTION) -> JsonDict:
    """A flight school with one twin, one single and two pilots on the register."""
    advance_clock(api, clock)
    operator = make_operator(api)
    twin = make_aircraft(api)
    single = make_aircraft(api, f.single_piston_aircraft_payload())
    pilot = make_pilot(api)
    senior_pilot = make_pilot(api, f.senior_pilot_payload())
    return {
        "operator": operator,
        "operator_id": operator["id"],
        "aircraft": twin,
        "aircraft_id": twin["id"],
        "single": single,
        "single_id": single["id"],
        "pilot": pilot,
        "pilot_id": pilot["id"],
        "senior_pilot": senior_pilot,
        "senior_pilot_id": senior_pilot["id"],
    }


# ----------------------------------------------------------------------
# Phase 2 — a draft policy
# ----------------------------------------------------------------------
def make_policy(api, operator_id: str, headers=None, **overrides) -> JsonDict:
    return get_success_data(
        api.create_policy(
            f.policy_payload(operator_id, **overrides), headers=headers or users.UNDERWRITER
        )
    )


def make_schedule(
    api, policy_id: str, aircraft_id: str, named_pilot_id: str, headers=None, **overrides
) -> JsonDict:
    return get_success_data(
        api.create_schedule(
            f.schedule_payload(policy_id, aircraft_id, named_pilot_id, **overrides),
            headers=headers or users.UNDERWRITER,
        )
    )


def draft_policy_with_hull(api, clock: str = f.CLOCK_BEFORE_INCEPTION, **policy_overrides):
    """A register, a draft policy and one pending instructional hull on it.

    The policy is left in `DRAFT`, which is the state a draft-only rule needs.
    """
    book = registered_book(api, clock=clock)
    policy = make_policy(api, book["operator_id"], **policy_overrides)
    schedule = make_schedule(
        api, policy["id"], book["aircraft_id"], book["pilot_id"]
    )
    book.update(
        {
            "policy": policy,
            "policy_id": policy["id"],
            "schedule": schedule,
            "schedule_id": schedule["id"],
        }
    )
    return book


# ----------------------------------------------------------------------
# Phase 3 — binding
# ----------------------------------------------------------------------
def bind_policy(api, policy_id: str) -> JsonDict:
    return get_success_data(api.bind_policy(policy_id, headers=users.UNDERWRITER))


def set_warranty(api, schedule_id: str, finding: str, **overrides) -> JsonDict:
    return get_success_data(
        api.record_warranty_finding(
            schedule_id, f.warranty_finding_payload(finding, **overrides),
            headers=users.UNDERWRITER,
        )
    )


def bound_policy_with_hull(
    api,
    clock: str = f.CLOCK_BEFORE_INCEPTION,
    compliant_warranty: bool = False,
    **policy_overrides,
):
    """A bound policy whose single instructional hull is active.

    When `compliant_warranty` is set the hull's evidence is verified before the
    bind, so the warranty reads `COMPLIANT` rather than `PENDING_EVIDENCE`.
    """
    book = draft_policy_with_hull(api, clock=clock, **policy_overrides)
    if compliant_warranty:
        book["schedule"] = set_warranty(
            api, book["schedule_id"], WarrantyFinding.EVIDENCE_VERIFIED
        )
    book["policy"] = bind_policy(api, book["policy_id"])
    book["schedule"] = fetch_schedule(api, book["schedule_id"])
    return book


def bound_policy_mid_term(api, compliant_warranty: bool = False, **policy_overrides):
    """A bound policy with the clock parked inside its term.

    Operations that compare an instant against the clock — endorsement binding,
    damage assessment, the late flag of a declaration — need the clock to sit
    inside the window under test rather than before it.
    """
    book = bound_policy_with_hull(
        api, compliant_warranty=compliant_warranty, **policy_overrides
    )
    advance_clock(api, f.CLOCK_MID_TERM)
    book["policy"] = fetch_policy(api, book["policy_id"])
    book["schedule"] = fetch_schedule(api, book["schedule_id"])
    return book


# ----------------------------------------------------------------------
# Phase 4 — the claim file
# ----------------------------------------------------------------------
def make_claim(api, policy_id: str, schedule_id: str, headers=None, **overrides) -> JsonDict:
    return get_success_data(
        api.create_claim(
            f.claim_payload(policy_id, schedule_id, **overrides),
            headers=headers or users.CLAIMS_ADJUSTER,
        )
    )


def investigate_claim(api, claim_id: str, **overrides) -> JsonDict:
    return get_success_data(
        api.record_investigation(
            claim_id, f.investigation_payload(**overrides), headers=users.CLAIMS_ADJUSTER
        )
    )


def make_damage_assessment(api, claim_id: str, **overrides) -> JsonDict:
    return get_success_data(
        api.create_damage_assessment(
            f.damage_assessment_payload(claim_id, **overrides),
            headers=users.CLAIMS_ADJUSTER,
        )
    )


def decide_coverage(api, claim_id: str, headers=None, **overrides) -> JsonDict:
    return get_success_data(
        api.decide_coverage(
            claim_id,
            f.coverage_decision_payload(**overrides),
            headers=headers or users.CLAIMS_ADJUSTER,
        )
    )


def dispose_salvage(api, claim_id: str, salvage_action: str, **overrides) -> JsonDict:
    return get_success_data(
        api.dispose_salvage(
            claim_id,
            f.salvage_disposition_payload(salvage_action, **overrides),
            headers=users.CLAIMS_ADJUSTER,
        )
    )


def settle_claim(api, claim_id: str, settlement_basis: str, headers=None) -> JsonDict:
    """Settle a reserved claim.

    The settling user must differ from the user who decided cover, so the second
    adjuster is used by default.
    """
    return get_success_data(
        api.settle_claim(
            claim_id,
            f.settlement_payload(settlement_basis),
            headers=headers or users.SECOND_CLAIMS_ADJUSTER,
        )
    )


def investigated_claim(api, book: JsonDict, **claim_overrides) -> JsonDict:
    """A notified claim advanced to `INVESTIGATING` with the insured cooperating."""
    claim = make_claim(api, book["policy_id"], book["schedule_id"], **claim_overrides)
    claim = investigate_claim(api, claim["id"])
    book["claim"] = claim
    book["claim_id"] = claim["id"]
    return book


def reserved_claim(
    api,
    book: JsonDict,
    repair_cost_estimate_cents: int = 20000000,
    reserve_cents: int = 20000000,
    assessed_at: str = "2026-09-10T00:00:00Z",
    **claim_overrides,
) -> JsonDict:
    """A claim carrying one assessment and a confirmed reserve.

    Cover is confirmed by the first adjuster, leaving the second adjuster free to
    settle without breaching the segregation of duties.
    """
    book = investigated_claim(api, book, **claim_overrides)
    book["assessment"] = make_damage_assessment(
        api,
        book["claim_id"],
        repair_cost_estimate_cents=repair_cost_estimate_cents,
        assessed_at=assessed_at,
    )
    book["claim"] = decide_coverage(
        api,
        book["claim_id"],
        decision=CoverageDecision.COVERED,
        reserve_cents=reserve_cents,
    )
    return book


def total_loss_ready_claim(api, book: JsonDict, **kwargs) -> JsonDict:
    """A reserved claim whose assessment carries it over the total-loss threshold.

    The wreck is tendered as well, because a total-loss basis additionally
    requires a salvage disposition to have been made.
    """
    book = reserved_claim(
        api,
        book,
        repair_cost_estimate_cents=kwargs.pop("repair_cost_estimate_cents", 40000000),
        reserve_cents=kwargs.pop("reserve_cents", 45000000),
        **kwargs,
    )
    book["claim"] = dispose_salvage(api, book["claim_id"], SalvageAction.TENDER)
    return book


# ----------------------------------------------------------------------
# Phase 5 — endorsements
# ----------------------------------------------------------------------
def make_endorsement(api, payload: JsonDict, headers=None) -> JsonDict:
    return get_success_data(
        api.create_endorsement(payload, headers=headers or users.UNDERWRITER)
    )


def quote_endorsement(api, endorsement_id: str, headers=None) -> JsonDict:
    return get_success_data(
        api.quote_endorsement(endorsement_id, headers=headers or users.UNDERWRITER)
    )


def refer_endorsement(api, endorsement_id: str, **overrides) -> JsonDict:
    return get_success_data(
        api.refer_endorsement(
            endorsement_id, f.referral_payload(**overrides), headers=users.UNDERWRITER
        )
    )


def bind_endorsement(api, endorsement_id: str, headers=None) -> JsonDict:
    """Bind a quoted endorsement.

    The binding user must differ from the quoting user, so the second
    underwriter binds what the first underwriter quoted.
    """
    return get_success_data(
        api.bind_endorsement(endorsement_id, headers=headers or users.SECOND_UNDERWRITER)
    )


def void_endorsement(api, endorsement_id: str, **overrides) -> JsonDict:
    return get_success_data(
        api.void_endorsement(
            endorsement_id, f.void_payload(**overrides), headers=users.UNDERWRITER
        )
    )


def quoted_endorsement(api, payload: JsonDict) -> JsonDict:
    """An endorsement submitted and quoted, left in `QUOTED` ready to bind."""
    endorsement = make_endorsement(api, payload)
    return quote_endorsement(api, endorsement["id"])


def bound_endorsement(api, payload: JsonDict) -> JsonDict:
    """An endorsement carried all the way to `BOUND`."""
    endorsement = quoted_endorsement(api, payload)
    return bind_endorsement(api, endorsement["id"])


# ----------------------------------------------------------------------
# Phase 6 — war risk
# ----------------------------------------------------------------------
def make_war_market(api, payload: JsonDict = None, headers=None) -> JsonDict:
    return get_success_data(
        api.create_war_market(
            payload if payload is not None else f.war_market_payload(),
            headers=headers or users.UNDERWRITER,
        )
    )


def make_war_placement(
    api, policy_id: str, market_id: str, expected_policy_version: int, headers=None, **overrides
) -> JsonDict:
    return get_success_data(
        api.create_war_placement(
            f.war_placement_payload(
                policy_id, market_id, expected_policy_version, **overrides
            ),
            headers=headers or users.UNDERWRITER,
        )
    )


def cancel_war_placement(api, placement_id: str, **overrides) -> JsonDict:
    return get_success_data(
        api.cancel_war_placement(
            placement_id, f.cancellation_payload(**overrides), headers=users.UNDERWRITER
        )
    )


def placed_war_risk(api, book: JsonDict, **overrides) -> JsonDict:
    """A war risk market and a bound placement of this policy's war hull line."""
    market = make_war_market(api)
    policy = fetch_policy(api, book["policy_id"])
    placement = make_war_placement(
        api, policy["id"], market["id"], policy["version"], **overrides
    )
    book.update(
        {
            "market": market,
            "market_id": market["id"],
            "placement": placement,
            "placement_id": placement["id"],
            "policy": fetch_policy(api, book["policy_id"]),
        }
    )
    return book


# ----------------------------------------------------------------------
# Phase 7 — fleet declarations
# ----------------------------------------------------------------------
def make_fleet_declaration(api, policy_id: str, headers=None, **overrides) -> JsonDict:
    return get_success_data(
        api.create_fleet_declaration(
            f.fleet_declaration_payload(policy_id, **overrides),
            headers=headers or users.UNDERWRITER,
        )
    )


def accept_declaration(api, declaration_id: str, **overrides) -> JsonDict:
    return get_success_data(
        api.accept_fleet_declaration(
            declaration_id,
            f.declaration_acceptance_payload(**overrides),
            headers=users.UNDERWRITER,
        )
    )


# ----------------------------------------------------------------------
# Reads
# ----------------------------------------------------------------------
def fetch_operator(api, operator_id: str) -> JsonDict:
    return get_success_data(api.get_operator(operator_id, headers=users.UNDERWRITER))


def fetch_aircraft(api, aircraft_id: str) -> JsonDict:
    return get_success_data(api.get_aircraft(aircraft_id, headers=users.UNDERWRITER))


def fetch_pilot(api, pilot_id: str) -> JsonDict:
    return get_success_data(api.get_pilot(pilot_id, headers=users.UNDERWRITER))


def fetch_policy(api, policy_id: str) -> JsonDict:
    return get_success_data(api.get_policy(policy_id, headers=users.UNDERWRITER))


def fetch_schedule(api, schedule_id: str) -> JsonDict:
    return get_success_data(api.get_schedule(schedule_id, headers=users.UNDERWRITER))


def fetch_endorsement(api, endorsement_id: str) -> JsonDict:
    return get_success_data(api.get_endorsement(endorsement_id, headers=users.UNDERWRITER))


def fetch_war_market(api, market_id: str) -> JsonDict:
    return get_success_data(api.get_war_market(market_id, headers=users.UNDERWRITER))


def fetch_war_placement(api, placement_id: str) -> JsonDict:
    return get_success_data(api.get_war_placement(placement_id, headers=users.UNDERWRITER))


def fetch_claim(api, claim_id: str) -> JsonDict:
    return get_success_data(api.get_claim(claim_id, headers=users.UNDERWRITER))


def fetch_damage_assessment(api, assessment_id: str) -> JsonDict:
    return get_success_data(
        api.get_damage_assessment(assessment_id, headers=users.UNDERWRITER)
    )


def fetch_fleet_declaration(api, declaration_id: str) -> JsonDict:
    return get_success_data(
        api.get_fleet_declaration(declaration_id, headers=users.UNDERWRITER)
    )


def ledger_rows(api, policy_id: str = None, **filters) -> list:
    """Every ledger row for a policy, in created_at ascending order."""
    params = dict(filters)
    if policy_id is not None:
        params["policy_id"] = policy_id
    params.setdefault("limit", 100)
    response = api.list_premium_transactions(headers=users.UNDERWRITER, params=params)
    return get_success_data(response)


def schedules_of_policy(api, policy_id: str, **filters) -> list:
    params = dict(filters)
    params["policy_id"] = policy_id
    params.setdefault("limit", 100)
    return get_success_data(api.list_schedules(headers=users.UNDERWRITER, params=params))


def claims_of_policy(api, policy_id: str, **filters) -> list:
    params = dict(filters)
    params["policy_id"] = policy_id
    params.setdefault("limit", 100)
    return get_success_data(api.list_claims(headers=users.UNDERWRITER, params=params))


def assessments_of_claim(api, claim_id: str, **filters) -> list:
    params = dict(filters)
    params["claim_id"] = claim_id
    params.setdefault("limit", 100)
    return get_success_data(
        api.list_damage_assessments(headers=users.UNDERWRITER, params=params)
    )


__all__ = [name for name in dir() if not name.startswith("_")]
