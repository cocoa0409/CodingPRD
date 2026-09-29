"""
Requests whose fate is decided by the state of a different entity entirely.

In each scenario the request body, the caller and the target row are all held
fixed while a neighbouring entity moves, so the refusal and the later success
differ in nothing except that neighbour's state.
"""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import validate_error

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import CASE_WORKER_HEADERS, SUPERVISING_ATTORNEY_HEADERS

#: The order request that is fired twice, unchanged, on either side of the
#: paternity result.
ORDER_REQUEST = {
    "order_type": "CURRENT_SUPPORT",
    "origin_state_code": "MN",
    "effective_date": "2026-09-01",
}


# ---------------------------------------------------------------------------
# Shared scenario builders
# ---------------------------------------------------------------------------


def _paternity_collected_but_not_yet_resulted() -> fx.Scenario:
    """
    A located obligor, a genetic-test paternity action, and a clean specimen
    collected at the appointment instant of 2026-08-05 with no result recorded.

    The obligor is referred to locate first and only then reported `LOCATED`, so
    the referral counters are observable alongside the paternity state.
    """
    scenario = fx.open_case_with_parties(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Lia Moreau",
            "ssn_last4": "2626",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Max Moreau",
            "ssn_last4": "2727",
            "monthly_gross_income_cents": 300000,
            "supports_second_family": False,
            "has_valid_drivers_license": True,
        },
        locate_outcome=None,
        child_count=2,
        tanf_assistance=False,
        good_cause_claim=False,
    )
    scenario.case = fx.refer_to_locate(scenario.case_id, "FEDERAL_PLS")
    scenario.noncustodial_party = fx.record_locate_outcome(scenario.ncp_id, "LOCATED")
    scenario.paternity_action = fx.open_paternity_action(scenario.case_id, "GENETIC_TEST")
    scenario.paternity_action = fx.order_genetic_test(
        scenario.paternity_action["id"], "2026-08-05T00:00:00Z"
    )
    fx.set_clock("2026-08-05T00:00:00Z")
    scenario.paternity_action = fx.collect_specimen(scenario.paternity_action["id"], True)
    return scenario


def _calculated_medical_order_under_a_texas_controlling_order() -> Tuple[
    fx.Scenario, Dict[str, Any]
]:
    """
    A Texas current-support order entered at 75,000 cents, a registered
    responding referral naming Texas as the child's home state, and a second
    order — Minnesota, medical support — taken as far as `CALCULATED`.

    The referral is what makes the case `RESPONDING`; nothing about the second
    order changes between its refusal and its later entry.
    """
    scenario = fx.open_case_with_parties(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Nia Okafor",
            "ssn_last4": "2828",
            "residence_state_code": "MN",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Obi Okafor",
            "ssn_last4": "2929",
            "residence_state_code": "TX",
            "monthly_gross_income_cents": 300000,
            "supports_second_family": False,
            "has_valid_drivers_license": True,
        },
        child_count=2,
        tanf_assistance=False,
        good_cause_claim=False,
    )
    scenario.paternity_action = fx.open_paternity_action(scenario.case_id, "PRESUMED_MARITAL")
    scenario.order = fx.draft_order(
        scenario.case_id,
        order_type="CURRENT_SUPPORT",
        origin_state_code="TX",
        effective_date="2026-08-01",
    )
    fx.calculate_order(scenario.order_id)
    scenario.order = fx.enter_order(scenario.order_id)
    scenario.interstate_referral = fx.register_responding_referral(
        scenario.case_id,
        other_state_code="TX",
        child_home_state_code="TX",
        transmittal_type="MODIFICATION",
    )
    medical = fx.draft_order(
        scenario.case_id,
        order_type="MEDICAL_SUPPORT",
        origin_state_code="MN",
        effective_date="2026-09-01",
        medical_support_monthly_cents=20000,
    )
    medical = fx.calculate_order(medical["id"])
    return scenario, medical


# ---------------------------------------------------------------------------
# Order drafting gated on the paternity action of the same case
# ---------------------------------------------------------------------------


def test_01_drafting_is_refused_while_the_paternity_action_is_only_collected():
    """
    Nothing on the case or in the payload is wrong; the neighbour is unresolved.

    First, when a support order is drafted on a case, the case-status check rejects only a `CLOSED` case; the requirement that the case has actually reached order establishment is owned by the paternity-settlement check, so a case that has not yet reached `ORDER_ESTABLISHMENT` answers with `ERR_PATERNITY_NOT_ESTABLISHED` and never with `ERR_INVALID_CASE_STATUS`.

    Design: Difficulty/cross_entity_state_dependency/order_creation_requires_established_paternity
    """
    scenario = _paternity_collected_but_not_yet_resulted()

    assert scenario.paternity_action["status"] == "GENETIC_COLLECTED"
    assert fx.read_case(scenario.case_id)["case_status"] == "PATERNITY_PENDING"

    response = api_client.create_order(
        scenario.case_id, f.order_payload(**ORDER_REQUEST), CASE_WORKER_HEADERS
    )
    refusal = validate_error(response, ApiErrorId.PATERNITY_NOT_ESTABLISHED.value, 409)
    assert refusal["error_id"] != ApiErrorId.INVALID_CASE_STATUS.value


def test_02_the_obligor_is_located_and_the_specimen_is_clean_so_only_the_result_is_missing():
    """
    Every other precondition of order work is already satisfied on this case.

    Each referral increases the case's `locate_referral_count` by 1 and the case's `version` by 1, sets the obligor's `locate_status` to `PENDING` and increases the obligor's `locate_attempt_count` by 1.

    A true value drives `GENETIC_ORDERED → GENETIC_COLLECTED`, stamps `specimen_collected_at` with the current clock, and records `chain_of_custody_ok` as true.

    Design: Difficulty/cross_entity_state_dependency/order_creation_requires_established_paternity
    """
    scenario = _paternity_collected_but_not_yet_resulted()

    obligor = fx.read_participant(scenario.ncp_id)
    assert obligor["locate_status"] == "LOCATED"
    assert obligor["locate_attempt_count"] == 1
    assert scenario.case["locate_referral_count"] == 1

    action = fx.read_paternity_action(scenario.paternity_action["id"])
    assert action["method"] == "GENETIC_TEST"
    assert action["chain_of_custody_ok"] is True
    a.assert_instant_equals(action["specimen_collected_at"], "2026-08-05T00:00:00Z", "specimen_collected_at")
    assert action["specimen_rejection_count"] == 0

    response = api_client.create_order(
        scenario.case_id, f.order_payload(**ORDER_REQUEST), CASE_WORKER_HEADERS
    )
    validate_error(response, ApiErrorId.PATERNITY_NOT_ESTABLISHED.value, 409)


def test_03_the_genetic_result_alone_lets_the_identical_request_through():
    """
    The same body, the same caller, the same case — and now an order in `DRAFT`.

    A probability of at least 99.0 drives `GENETIC_COLLECTED → ESTABLISHED`, stamps `established_at` with the current clock, records `established_method` as `GENETIC_TEST`, sets `genetic_cost_liable_party` to `NCP` so that the test cost becomes collectable from the obligor, and moves the case `PATERNITY_PENDING → ORDER_ESTABLISHMENT`.

    Design: Difficulty/cross_entity_state_dependency/order_creation_requires_established_paternity
    """
    scenario = _paternity_collected_but_not_yet_resulted()

    blocked = api_client.create_order(
        scenario.case_id, f.order_payload(**ORDER_REQUEST), CASE_WORKER_HEADERS
    )
    validate_error(blocked, ApiErrorId.PATERNITY_NOT_ESTABLISHED.value, 409)

    established = fx.record_genetic_result(scenario.paternity_action["id"], 99.5)
    assert established["status"] == "ESTABLISHED"
    assert established["established_method"] == "GENETIC_TEST"
    a.assert_instant_equals(established["established_at"], "2026-08-05T00:00:00Z", "established_at")
    assert fx.read_case(scenario.case_id)["case_status"] == "ORDER_ESTABLISHMENT"

    order = fx.draft_order(scenario.case_id, **ORDER_REQUEST)
    assert order["status"] == "DRAFT"
    assert order["origin_state_code"] == "MN"
    assert order["effective_date"] == "2026-09-01"


def test_04_the_result_also_assigns_the_test_cost_that_the_order_never_mentioned():
    """
    The neighbour that gated the order carries its own money consequence.

    Either way `genetic_test_ordered_at` is stamped with the current clock and `genetic_cost_cents` is stamped at 48,000 cents, which is 480 dollars; the caller never supplies that amount.

    `genetic_cost_liable_party` remains `NONE` until the result is in.

    Design: Difficulty/cross_entity_state_dependency/order_creation_requires_established_paternity
    """
    scenario = _paternity_collected_but_not_yet_resulted()

    assert scenario.paternity_action["genetic_cost_cents"] == 48000
    a.assert_instant_equals(scenario.paternity_action["genetic_test_ordered_at"], "2026-08-01T00:00:00Z", "genetic_test_ordered_at")
    assert scenario.paternity_action["genetic_cost_liable_party"] == "NONE"

    established = fx.record_genetic_result(scenario.paternity_action["id"], 99.5)

    assert established["genetic_cost_liable_party"] == "NCP"
    assert established["genetic_cost_cents"] == 48000
    # The cost survives the establishment untouched; only its owner changed.
    assert fx.draft_order(scenario.case_id, **ORDER_REQUEST)["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Order entry gated on the interstate referral of the same case
# ---------------------------------------------------------------------------


def test_05_entry_is_refused_while_a_registered_referral_names_a_foreign_controlling_order():
    """
    The order is calculated, unique in its type and still cannot be entered.

    A `controlling_order_state_code` naming this state leaves the agency free to enter and to modify orders; a foreign `controlling_order_state_code` closes the jurisdiction gate, and both order entry and the proposal of a modified order on that case are refused with `ERR_NO_CONTROLLING_ORDER_JURISDICTION` (HTTP 409) for as long as the foreign order controls.

    Design: Difficulty/cross_entity_state_dependency/order_entry_blocked_by_foreign_controlling_order
    """
    scenario, medical = _calculated_medical_order_under_a_texas_controlling_order()

    assert medical["status"] == "CALCULATED"
    assert medical["order_type"] == "MEDICAL_SUPPORT"
    # The worksheet does not care which type of order it is run for.
    assert medical["guideline_monthly_cents"] == 75000
    assert scenario.interstate_referral["controlling_order_state_code"] == "TX"

    response = api_client.enter_order(
        medical["id"], f.entry_payload(), SUPERVISING_ATTORNEY_HEADERS
    )
    validate_error(response, ApiErrorId.NO_CONTROLLING_ORDER_JURISDICTION.value, 409)

    assert fx.read_order(medical["id"])["status"] == "CALCULATED"


def test_06_registration_picked_the_texas_order_because_texas_is_the_home_state():
    """
    The blocking condition was decided by a ranking the entry request never saw.

    **If any home-state order exists**, a home-state order always outranks a foreign one, and among the home-state orders the one with the **greatest** `effective_date` prevails — the most recent home-state order controls.

    Either way registration stamps `registered_at`, determines the controlling order, sets the case's `interstate_role` to `RESPONDING` on a responding referral, and increases both the referral's and the case's `version` by 1.

    Design: Difficulty/cross_entity_state_dependency/order_entry_blocked_by_foreign_controlling_order
    """
    scenario, _medical = _calculated_medical_order_under_a_texas_controlling_order()
    referral = scenario.interstate_referral

    assert scenario.order["status"] == "ENTERED"
    assert scenario.order["monthly_obligation_cents"] == 75000
    assert referral["status"] == "REGISTERED"
    assert referral["direction"] == "RESPONDING"
    assert referral["child_home_state_code"] == "TX"
    # The only entered current-support candidate, and it originates in TX.
    assert referral["controlling_order_id"] == scenario.order_id
    assert referral["controlling_order_state_code"] == "TX"
    a.assert_instant_equals(referral["registered_at"], "2026-08-01T00:00:00Z", "registered_at")
    assert fx.read_case(scenario.case_id)["interstate_role"] == "RESPONDING"


def test_07_returning_the_referral_reopens_the_gate_for_the_identical_request():
    """
    The same entry request, unchanged, once the referral is out of the way.

    From `REGISTERED` the `returned_reason` must be `INSUFFICIENT_INFO` or `NO_JURISDICTION`, and the return additionally clears `controlling_order_id` and `controlling_order_state_code`, which reopens the jurisdiction gate on that case.

    Every return path sets the case's `interstate_role` back to `NONE` when no other live referral remains on the case, and increases both the referral's and the case's `version` by 1.

    Design: Difficulty/cross_entity_state_dependency/order_entry_blocked_by_foreign_controlling_order
    """
    scenario, medical = _calculated_medical_order_under_a_texas_controlling_order()

    blocked = api_client.enter_order(
        medical["id"], f.entry_payload(), SUPERVISING_ATTORNEY_HEADERS
    )
    validate_error(blocked, ApiErrorId.NO_CONTROLLING_ORDER_JURISDICTION.value, 409)

    returned = fx.return_referral(scenario.interstate_referral["id"], "NO_JURISDICTION")
    assert returned["status"] == "RETURNED"
    assert returned["returned_reason"] == "NO_JURISDICTION"
    assert returned.get("controlling_order_id") is None
    assert returned.get("controlling_order_state_code") is None
    assert fx.read_case(scenario.case_id)["interstate_role"] == "NONE"

    entered = fx.enter_order(medical["id"])
    assert entered["status"] == "ENTERED"
    assert entered["monthly_obligation_cents"] == 75000
    assert entered["next_accrual_due_date"] == "2026-09-01"


def test_08_the_medical_order_never_enters_the_controlling_order_ranking():
    """
    A second registration ranks the same Texas order, ignoring the new one.

    The candidate set is the `ENTERED` support orders of the case whose `order_type` is `CURRENT_SUPPORT`; medical-support orders never compete, and neither does any order in `DRAFT`, `CALCULATED`, `PENDING_DEVIATION_FINDINGS`, `SUPERSEDED` or `VACATED`.

    Interval-overlap checking, the controlling-order determination and the enforcement obligation lookup are all scoped per `order_type`, which means a case may legitimately carry one live `CURRENT_SUPPORT` order and one live `MEDICAL_SUPPORT` order at the same time without either colliding with the other.

    Design: Difficulty/cross_entity_state_dependency/order_entry_blocked_by_foreign_controlling_order
    """
    scenario, medical = _calculated_medical_order_under_a_texas_controlling_order()

    fx.return_referral(scenario.interstate_referral["id"], "NO_JURISDICTION")
    entered_medical = fx.enter_order(medical["id"])
    assert entered_medical["status"] == "ENTERED"
    # Both orders are live at once because the two types never collide.
    assert fx.read_order(scenario.order_id)["status"] == "ENTERED"

    second = fx.register_responding_referral(
        scenario.case_id,
        other_state_code="TX",
        child_home_state_code="TX",
        transmittal_type="MODIFICATION",
    )

    assert second["status"] == "REGISTERED"
    # The newly entered medical order was never a candidate.
    assert second["controlling_order_id"] == scenario.order_id
    assert second["controlling_order_id"] != medical["id"]
    assert second["controlling_order_state_code"] == "TX"
