"""
The declared transition lists of the paternity action and the support order.

Every scenario here fires triggers at a row rather than reading one: the legal
ones to watch a side effect land, the illegal ones to watch the machine refuse
without moving, and the time-driven one to watch a deadline decide by itself.
"""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import (
    CASE_WORKER_HEADERS,
    FINANCE_OFFICER_HEADERS,
    INTERSTATE_LIAISON_HEADERS,
    SUPERVISING_ATTORNEY_HEADERS,
)

#: The sixty-day window opened by an acknowledgment signed at the opening clock.
RESCISSION_DEADLINE = "2026-09-30T00:00:00Z"


# ---------------------------------------------------------------------------
# Shared scenario builders
# ---------------------------------------------------------------------------


def _acknowledgment_signed_at_the_opening_clock() -> fx.Scenario:
    """
    A direct-application case whose obligor has signed the acknowledgment at
    2026-08-01, leaving the action in `AOP_SIGNED` and the case unestablished.
    """
    scenario = fx.open_case_with_parties(
        clock=CLOCK_START,
        cp_overrides={"full_name": "Dana Ruiz", "ssn_last4": "2727"},
        ncp_overrides={"full_name": "Alex Ruiz", "ssn_last4": "2828"},
        child_count=2,
        tanf_assistance=False,
        good_cause_claim=False,
    )
    scenario.paternity_action = fx.open_paternity_action(
        scenario.case_id, "VOLUNTARY_ACKNOWLEDGMENT"
    )
    scenario.paternity_action = fx.sign_acknowledgment(
        scenario.paternity_action["id"], scenario.ncp_id
    )
    scenario.reload_case()
    return scenario


def _twin_acknowledgments_one_rescinded_inside_the_window() -> Tuple[
    fx.Scenario, fx.Scenario
]:
    """
    Two identical cases whose acknowledgments were both signed at 2026-08-01.

    The second one is rescinded at 2026-09-15, inside the window; the first is
    left alone. The clock then stands at 2026-10-01, past both deadlines.
    """
    left = fx.open_case_with_parties(
        clock=CLOCK_START,
        cp_overrides={"full_name": "Dana Ruiz", "ssn_last4": "2929"},
        ncp_overrides={"full_name": "Alex Ruiz", "ssn_last4": "3030"},
        child_count=2,
        tanf_assistance=False,
        good_cause_claim=False,
    )
    right = fx.open_case_with_parties(
        clock=None,
        cp_overrides={"full_name": "Iris Poole", "ssn_last4": "3131"},
        ncp_overrides={"full_name": "Marcus Poole", "ssn_last4": "3232"},
        child_count=2,
        tanf_assistance=False,
        good_cause_claim=False,
    )
    for scenario in (left, right):
        scenario.paternity_action = fx.open_paternity_action(
            scenario.case_id, "VOLUNTARY_ACKNOWLEDGMENT"
        )
        scenario.paternity_action = fx.sign_acknowledgment(
            scenario.paternity_action["id"], scenario.ncp_id
        )
    fx.set_clock("2026-09-15T00:00:00Z")
    right.paternity_action = fx.rescind_acknowledgment(
        right.paternity_action["id"], right.ncp_id
    )
    fx.set_clock("2026-10-01T00:00:00Z")
    return left, right


def _terminal_paternity_action_and_returned_referral() -> fx.Scenario:
    """
    A case whose paternity action is `NOT_REQUIRED` and whose initiating
    referral to Wisconsin has been returned unworked for want of an
    acknowledgment.

    The order is entered because a transmittal has to have something to
    transmit, and the clock is moved past `ack_due_at` because the sister state
    is entitled to its whole ten days.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={"full_name": "Dana Ruiz", "ssn_last4": "3333"},
        ncp_overrides={"full_name": "Alex Ruiz", "ssn_last4": "3434"},
        case_overrides={
            "child_count": 2,
            "tanf_assistance": False,
            "good_cause_claim": False,
        },
        order_overrides={"origin_state_code": "MN", "effective_date": "2026-08-01"},
    )
    referral = fx.draft_interstate_referral(
        scenario.case_id,
        direction="INITIATING",
        other_state_code="WI",
        child_home_state_code="MN",
        transmittal_type="ENFORCEMENT",
    )
    scenario.interstate_referral = fx.transmit_referral(referral["id"])
    fx.set_clock("2026-08-12T00:00:00Z")
    scenario.interstate_referral = fx.return_referral(referral["id"], "NO_ACK_RECEIVED")
    return scenario


def _one_row_of_every_kind_at_creation() -> Dict[str, Any]:
    """
    One freshly created row of six kinds, each read from its creation response.

    The order is captured in `DRAFT` before the worksheet touches it; the charge
    falls due on 2026-08-15, which is after the opening clock, so the case still
    carries no arrears principal when the withholding order is issued.
    """
    unsettled = fx.open_case_with_parties(
        clock=CLOCK_START,
        cp_overrides={"full_name": "Nora Pike", "ssn_last4": "3535"},
        ncp_overrides={"full_name": "Owen Pike", "ssn_last4": "3636"},
        child_count=2,
        tanf_assistance=False,
        good_cause_claim=False,
    )
    pending_action = fx.open_paternity_action(
        unsettled.case_id, "VOLUNTARY_ACKNOWLEDGMENT"
    )

    scenario = fx.open_case_with_parties(
        clock=None,
        cp_overrides={"full_name": "Pia Quint", "ssn_last4": "3737"},
        ncp_overrides={"full_name": "Raul Quint", "ssn_last4": "3838"},
        child_count=2,
        tanf_assistance=False,
        good_cause_claim=False,
    )
    fx.open_paternity_action(scenario.case_id, "PRESUMED_MARITAL")
    draft = fx.draft_order(
        scenario.case_id,
        order_type="CURRENT_SUPPORT",
        origin_state_code="MN",
        effective_date="2026-08-01",
        medical_support_monthly_cents=0,
    )
    fx.calculate_order(draft["id"])
    scenario.order = fx.enter_order(draft["id"])
    charge = fx.post_monthly_charge(scenario.order_id, "2026-08-01", due_day=15)
    scenario.employer = fx.create_employer(
        state_code="MN", legal_name="Northline Manufacturing", remittance_fee_cents=0
    )
    withholding_order = fx.issue_withholding_order(
        scenario.order_id,
        scenario.employer_id,
        reported_disposable_income_cents=234000,
    )
    review = fx.open_modification_review(scenario.order_id, "PARTY_REQUEST")
    referral = fx.draft_interstate_referral(
        scenario.case_id,
        direction="INITIATING",
        other_state_code="WI",
        child_home_state_code="MN",
        transmittal_type="ENFORCEMENT",
    )
    return {
        "scenario": scenario,
        "unsettled_case_id": unsettled.case_id,
        "paternity_action": pending_action,
        "draft_order": draft,
        "charge": charge,
        "withholding_order": withholding_order,
        "modification_review": review,
        "referral": referral,
    }


def _settled_action_entered_order_and_one_unpaid_charge() -> fx.Scenario:
    """
    A presumed-marital case with an entered order at 75,000 cents, one charge of
    75,000 due 2026-08-15, and the clock carried to 2026-10-01 with the ledger
    brought up to date once.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={"full_name": "Sara Tate", "ssn_last4": "3939"},
        ncp_overrides={"full_name": "Theo Tate", "ssn_last4": "4040"},
        case_overrides={
            "child_count": 2,
            "tanf_assistance": False,
            "good_cause_claim": False,
        },
        order_overrides={
            "origin_state_code": "MN",
            "effective_date": "2026-08-01",
            "medical_support_monthly_cents": 0,
        },
    )
    scenario.charges = [fx.post_monthly_charge(scenario.order_id, "2026-08-01", due_day=15)]
    fx.set_clock("2026-10-01T00:00:00Z")
    scenario.case = fx.run_accrual(scenario.case_id)
    return scenario


def _entered_order_beside_a_draft_medical_order() -> Tuple[fx.Scenario, Dict[str, Any]]:
    """
    One entered current-support order at 75,000 cents and, on the same case, a
    medical-support order left in `DRAFT` — plus an employer to aim a withholding
    request at.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={"full_name": "Uli Vega", "ssn_last4": "4141"},
        ncp_overrides={"full_name": "Vito Vega", "ssn_last4": "4242"},
        case_overrides={
            "child_count": 2,
            "tanf_assistance": False,
            "good_cause_claim": False,
        },
        order_overrides={
            "origin_state_code": "MN",
            "effective_date": "2026-08-01",
            "medical_support_monthly_cents": 0,
        },
    )
    scenario.employer = fx.create_employer(
        state_code="MN", legal_name="Harbor Freight Lines", remittance_fee_cents=0
    )
    draft = fx.draft_order(
        scenario.case_id,
        order_type="MEDICAL_SUPPORT",
        origin_state_code="MN",
        effective_date="2026-09-01",
        medical_support_monthly_cents=20000,
    )
    return scenario, draft


# ---------------------------------------------------------------------------
# The acknowledgment ripens on the clock, not on an operator
# ---------------------------------------------------------------------------


def test_01_a_signed_acknowledgment_waits_out_its_window_and_the_deadline_itself():
    """
    The window opens at signature and the deadline instant is still inside it.

    This drives `PENDING → AOP_SIGNED`, stamps `aop_signed_at` with the current logical clock, computes `rescission_deadline_at` as that instant plus a sixty-day rescission window, records `notary_verified` as true, and increases the action's `version` by 1.

    The other two methods create the row in `PENDING` and move the case to `PATERNITY_PENDING`.

    This is the only establishment in the system driven by the passage of time rather than by an operator, and the comparison is strict: a clock value exactly equal to the deadline leaves the action in `AOP_SIGNED`.

    Design: Corner/state_machines/voluntary_acknowledgment_establishes_only_after_the_deadline_passes
    """
    scenario = _acknowledgment_signed_at_the_opening_clock()
    action = scenario.paternity_action

    assert action["status"] == "AOP_SIGNED"
    assert action["method"] == "VOLUNTARY_ACKNOWLEDGMENT"
    assert action["notary_verified"] is True
    a.assert_instant_equals(action["aop_signed_at"], CLOCK_START, "aop_signed_at")
    # 2026-08-01 plus sixty days.
    a.assert_instant_equals(
        action["rescission_deadline_at"], RESCISSION_DEADLINE, "rescission_deadline_at"
    )
    assert scenario.case["case_status"] == "PATERNITY_PENDING"

    fx.set_clock(RESCISSION_DEADLINE)

    on_the_deadline = fx.read_paternity_action(action["id"])
    assert on_the_deadline["status"] == "AOP_SIGNED"
    assert on_the_deadline.get("established_at") is None
    assert on_the_deadline.get("established_method") is None
    assert fx.read_case(scenario.case_id)["case_status"] == "PATERNITY_PENDING"


def test_02_one_second_past_the_deadline_the_clock_establishes_paternity():
    """
    Nobody calls an establishment endpoint; advancing the clock does the work.

    When the logical clock is advanced to a value strictly after an action's `rescission_deadline_at`, that action moves `AOP_SIGNED → ESTABLISHED`, `established_at` is stamped with the new clock value, `established_method` is recorded as `VOLUNTARY_ACKNOWLEDGMENT`, and the case moves `PATERNITY_PENDING → ORDER_ESTABLISHMENT`.

    Design: Corner/state_machines/voluntary_acknowledgment_establishes_only_after_the_deadline_passes
    """
    scenario = _acknowledgment_signed_at_the_opening_clock()
    action_id = scenario.paternity_action["id"]

    fx.set_clock("2026-10-01T00:00:00Z")

    established = fx.read_paternity_action(action_id)
    assert established["status"] == "ESTABLISHED"
    assert established["established_method"] == "VOLUNTARY_ACKNOWLEDGMENT"
    a.assert_instant_equals(
        established["established_at"], "2026-10-01T00:00:00Z", "established_at"
    )
    assert fx.read_case(scenario.case_id)["case_status"] == "ORDER_ESTABLISHMENT"

    # The establishment is a state change, not a reading artefact: it holds.
    assert fx.read_paternity_action(action_id)["status"] == "ESTABLISHED"


# ---------------------------------------------------------------------------
# The rescission cycle and the window error that outranks the status error
# ---------------------------------------------------------------------------


def test_03_a_rescission_inside_the_window_clears_both_stamps_and_stops_the_clock():
    """
    Two identical acknowledgments diverge on one call, and only one ripens.

    A `NoncustodialParty` caller drives `AOP_SIGNED → AOP_RESCINDED`, which increases `rescission_count` by 1 and clears both `aop_signed_at` and `rescission_deadline_at` back to absent.

    Design: Corner/state_machines/rescission_after_the_sixty_day_window_is_refused
    """
    left, right = _twin_acknowledgments_one_rescinded_inside_the_window()

    rescinded = fx.read_paternity_action(right.paternity_action["id"])
    assert rescinded["status"] == "AOP_RESCINDED"
    assert rescinded["rescission_count"] == 1
    assert rescinded.get("aop_signed_at") is None
    assert rescinded.get("rescission_deadline_at") is None
    # No deadline is left for the clock to pass, so nothing establishes.
    assert rescinded.get("established_at") is None
    assert fx.read_case(right.case_id)["case_status"] == "PATERNITY_PENDING"

    ripened = fx.read_paternity_action(left.paternity_action["id"])
    assert ripened["status"] == "ESTABLISHED"
    assert ripened["rescission_count"] == 0
    assert fx.read_case(left.case_id)["case_status"] == "ORDER_ESTABLISHMENT"


def test_04_rescinding_a_voluntarily_established_action_answers_with_the_window_error():
    """
    The status error is the one the general precedence rule would have picked.

    Second, when a rescission is attempted against a paternity action already in `ESTABLISHED` whose `established_method` is `VOLUNTARY_ACKNOWLEDGMENT`, the answer is `ERR_RESCISSION_WINDOW_CLOSED` rather than `ERR_INVALID_PATERNITY_STATUS`, because the elapsed sixty-day deadline is the specific reason the request fails; every other disallowed origin state on that operation — `PENDING`, `GENETIC_ORDERED`, `GENETIC_COLLECTED`, `AOP_RESCINDED`, `EXCLUDED`, `NOT_REQUIRED`, or an `ESTABLISHED` action whose `established_method` is `GENETIC_TEST` — still answers with `ERR_INVALID_PATERNITY_STATUS`.

    Design: Corner/state_machines/rescission_after_the_sixty_day_window_is_refused
    """
    left, _right = _twin_acknowledgments_one_rescinded_inside_the_window()
    action_id = left.paternity_action["id"]

    assert fx.read_paternity_action(action_id)["established_method"] == "VOLUNTARY_ACKNOWLEDGMENT"

    response = api_client.rescind_acknowledgment(
        action_id, f.rescission_payload(), left.ncp_headers
    )
    refusal = validate_error(response, ApiErrorId.RESCISSION_WINDOW_CLOSED.value, 409)
    assert refusal["error_id"] != ApiErrorId.INVALID_PATERNITY_STATUS.value

    unmoved = fx.read_paternity_action(action_id)
    assert unmoved["status"] == "ESTABLISHED"
    assert unmoved["rescission_count"] == 0


def test_05_the_rescinded_action_re_executes_into_a_completely_fresh_window():
    """
    Signing again from `AOP_RESCINDED` reopens sixty days from the new signature,
    and the cycle then closes for good.

    A rescinded acknowledgment is not a dead end. The same acknowledgment operation re-executes from `AOP_RESCINDED` back to `AOP_SIGNED` — still requiring `notary_verified` to be true — and a completely fresh sixty-day window opens from the new `aop_signed_at`.

    And `rescission_count` must still be below one, because the statute permits exactly one rescission per acknowledgment; a second attempt is refused with `ERR_RESCISSION_LIMIT` (HTTP 409).

    Design: Corner/state_machines/rescission_after_the_sixty_day_window_is_refused
    """
    _left, right = _twin_acknowledgments_one_rescinded_inside_the_window()
    action_id = right.paternity_action["id"]

    resigned = fx.sign_acknowledgment(action_id, right.ncp_id)

    assert resigned["status"] == "AOP_SIGNED"
    a.assert_instant_equals(resigned["aop_signed_at"], "2026-10-01T00:00:00Z", "aop_signed_at")
    # 2026-10-01 plus a fresh sixty days.
    a.assert_instant_equals(
        resigned["rescission_deadline_at"], "2026-11-30T00:00:00Z", "rescission_deadline_at"
    )
    assert resigned["rescission_count"] == 1

    response = api_client.rescind_acknowledgment(
        action_id, f.rescission_payload(), right.ncp_headers
    )
    validate_error(response, ApiErrorId.RESCISSION_LIMIT.value, 409)

    assert fx.read_paternity_action(action_id)["status"] == "AOP_SIGNED"


# ---------------------------------------------------------------------------
# Terminal states refuse every trigger aimed at them
# ---------------------------------------------------------------------------


def test_06_a_not_required_action_refuses_all_five_paternity_triggers():
    """
    The marital presumption lands in a terminal state, and nothing moves it.

    `ESTABLISHED`, `EXCLUDED` and `NOT_REQUIRED` are terminal: no write of any kind is accepted against a paternity action in any of them, and an attempt answers with `ERR_INVALID_PATERNITY_STATUS` (HTTP 409) — with the single exception, described in the precedence rules above, of a rescission attempted against a voluntarily-established action, which answers with the window error instead.

    A `method` of `PRESUMED_MARITAL` creates the row directly in the terminal state `NOT_REQUIRED` — it is never observable in `PENDING` — and moves the case straight from `OPENED` to `ORDER_ESTABLISHMENT`, skipping `PATERNITY_PENDING` entirely.

    Design: Corner/state_machines/terminal_paternity_and_referral_states_refuse_every_trigger
    """
    scenario = _terminal_paternity_action_and_returned_referral()
    action_id = scenario.paternity_action["id"]
    assert scenario.paternity_action["status"] == "NOT_REQUIRED"

    refusals = [
        api_client.record_acknowledgment(
            action_id, f.acknowledgment_payload(scenario.ncp_id), CASE_WORKER_HEADERS
        ),
        api_client.rescind_acknowledgment(
            action_id, f.rescission_payload(), scenario.ncp_headers
        ),
        api_client.order_genetic_test(
            action_id,
            f.genetic_test_order_payload("2026-09-01T00:00:00Z"),
            SUPERVISING_ATTORNEY_HEADERS,
        ),
        api_client.record_specimen_collection(
            action_id, f.specimen_collection_payload(True), CASE_WORKER_HEADERS
        ),
        api_client.record_genetic_result(
            action_id, f.genetic_result_payload(99.5), SUPERVISING_ATTORNEY_HEADERS
        ),
    ]
    for response in refusals:
        validate_error(response, ApiErrorId.INVALID_PATERNITY_STATUS.value, 409)

    unmoved = fx.read_paternity_action(action_id)
    assert unmoved["status"] == "NOT_REQUIRED"
    assert unmoved["method"] == "PRESUMED_MARITAL"
    assert unmoved.get("aop_signed_at") is None
    assert unmoved.get("genetic_test_ordered_at") is None
    assert unmoved["version"] == scenario.paternity_action["version"]


def test_07_a_returned_referral_refuses_transmittal_registration_and_return():
    """
    The referral came back unworked after its ten days and is now closed to all
    three of its own triggers.

    From `TRANSMITTED` the `returned_reason` may be `NO_ACK_RECEIVED`, but only when the current logical clock is **strictly past** `ack_due_at` — the sister state gets the whole ten days.

    `RETURNED` is terminal.

    Transmitting a responding referral, transmitting one that has already gone out, registering a referral that is already registered or enforcing, or returning one that is already returned all answer with `ERR_INVALID_REFERRAL_STATUS` (HTTP 409).

    Design: Corner/state_machines/terminal_paternity_and_referral_states_refuse_every_trigger
    """
    scenario = _terminal_paternity_action_and_returned_referral()
    referral = scenario.interstate_referral
    referral_id = referral["id"]

    assert referral["status"] == "RETURNED"
    assert referral["returned_reason"] == "NO_ACK_RECEIVED"
    a.assert_instant_equals(referral["transmitted_at"], CLOCK_START, "transmitted_at")
    # Transmitted at 2026-08-01, so the sister state had until 2026-08-11.
    a.assert_instant_equals(referral["ack_due_at"], "2026-08-11T00:00:00Z", "ack_due_at")

    refusals = [
        api_client.transmit_referral(
            referral_id, f.transmittal_payload(), INTERSTATE_LIAISON_HEADERS
        ),
        api_client.register_referral(
            referral_id, f.registration_payload(), INTERSTATE_LIAISON_HEADERS
        ),
        api_client.return_referral(
            referral_id,
            f.referral_return_payload("INSUFFICIENT_INFO"),
            INTERSTATE_LIAISON_HEADERS,
        ),
    ]
    for response in refusals:
        validate_error(response, ApiErrorId.INVALID_REFERRAL_STATUS.value, 409)

    unmoved = fx.read_interstate_referral(referral_id)
    assert unmoved["status"] == "RETURNED"
    assert unmoved["returned_reason"] == "NO_ACK_RECEIVED"
    assert unmoved.get("registered_at") is None
    assert unmoved["version"] == referral["version"]
    # The single live referral is gone, so the case is nobody's respondent.
    assert fx.read_case(scenario.case_id)["interstate_role"] == "NONE"


# ---------------------------------------------------------------------------
# Every kind of row starts in its declared initial state
# ---------------------------------------------------------------------------


def test_08_a_new_action_a_new_order_and_a_new_charge_land_where_they_are_declared_to():
    """
    Three creation responses read field by field against their declared defaults.

    The other two methods create the row in `PENDING` and move the case to `PATERNITY_PENDING`.

    The order is created in `DRAFT` with every guideline field absent — `guideline_monthly_cents`, `guideline_cp_income_cents`, `guideline_ncp_income_cents`, `guideline_basic_obligation_cents` and `guideline_ncp_share_ratio` all stay absent until the worksheet runs — with `multi_family_credit_cents` at zero, `imputation_applied` false, `monthly_obligation_cents` absent, `arrears_recovery_monthly_cents` at zero, `deviation_applied` false, `deviation_rejection_count` at zero, and `terminated_date`, `superseded_by_order_id`, `next_accrual_due_date`, `findings_approved_by_user_id`, `deviation_requested_cents`, `deviation_reason` and `vacate_reason` all absent.

    A new charge is created with `status` `OPEN`, `unpaid_balance_cents` equal to `amount_cents`, `paid_cents` at zero and `interest_accrued_cents` at zero.

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    rows = _one_row_of_every_kind_at_creation()

    action = rows["paternity_action"]
    assert action["status"] == "PENDING"
    assert action["method"] == "VOLUNTARY_ACKNOWLEDGMENT"
    assert fx.read_case(rows["unsettled_case_id"])["case_status"] == "PATERNITY_PENDING"

    draft = rows["draft_order"]
    assert draft["status"] == "DRAFT"
    for absent in (
        "guideline_monthly_cents",
        "guideline_cp_income_cents",
        "guideline_ncp_income_cents",
        "guideline_basic_obligation_cents",
        "guideline_ncp_share_ratio",
        "monthly_obligation_cents",
        "terminated_date",
        "superseded_by_order_id",
        "next_accrual_due_date",
        "findings_approved_by_user_id",
        "deviation_requested_cents",
        "deviation_reason",
        "vacate_reason",
    ):
        assert draft.get(absent) is None, absent
    assert draft["multi_family_credit_cents"] == 0
    assert draft["imputation_applied"] is False
    assert draft["arrears_recovery_monthly_cents"] == 0
    assert draft["deviation_applied"] is False
    assert draft["deviation_rejection_count"] == 0
    # The effective date of 2026-08-01 plus thirty-six months.
    assert draft["review_eligible_date"] == "2029-08-01"

    charge = rows["charge"]
    assert charge["status"] == "OPEN"
    assert charge["amount_cents"] == 75000
    assert charge["unpaid_balance_cents"] == charge["amount_cents"]
    assert charge["paid_cents"] == 0
    assert charge["interest_accrued_cents"] == 0


def test_09_a_new_withholding_order_review_and_referral_land_where_they_are_declared_to():
    """
    The withholding order asks for the bare obligation, because the only charge on
    the case does not fall due until the fifteenth.

    The new row starts with `service_status` `ISSUED` and `remittance_status` `NOT_DUE`, with `served_at`, `first_withholding_due_at`, `next_remittance_due_at` and `terminated_reason` all absent and `missed_remittance_count` at zero.

    `arrears_recovery_cents` is the parent order's `monthly_obligation_cents` multiplied by 0.20 — twenty percent — rounded half up to whole cents, and it is zero when the case has no outstanding arrears principal.

    The review is created with `status` `REQUESTED`, its `case_id` copied from the reviewed order, its `current_obligation_snapshot_cents` captured from that order's `monthly_obligation_cents` — this snapshot, not the live order, is the denominator of the variance test — and its `review_eligible_date` computed as the reviewed order's `effective_date` plus thirty-six months.

    The referral is created with `status` `DRAFT` and with `transmitted_at`, `ack_due_at`, `registered_at`, `controlling_order_id`, `controlling_order_state_code` and `returned_reason` all absent.

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    rows = _one_row_of_every_kind_at_creation()
    scenario = rows["scenario"]

    withholding_order = rows["withholding_order"]
    assert withholding_order["service_status"] == "ISSUED"
    assert withholding_order["remittance_status"] == "NOT_DUE"
    for absent in (
        "served_at",
        "first_withholding_due_at",
        "next_remittance_due_at",
        "terminated_reason",
    ):
        assert withholding_order.get(absent) is None, absent
    assert withholding_order["missed_remittance_count"] == 0
    assert fx.read_case(scenario.case_id)["arrears_principal_cents"] == 0
    assert withholding_order["arrears_recovery_cents"] == 0
    assert withholding_order["requested_amount_cents"] == 75000
    assert withholding_order["withholding_amount_cents"] == 75000
    assert withholding_order["jurisdiction_state_code"] == "MN"

    review = rows["modification_review"]
    assert review["status"] == "REQUESTED"
    assert review["case_id"] == scenario.case_id
    assert review["current_obligation_snapshot_cents"] == 75000
    assert review["review_eligible_date"] == "2029-08-01"
    for absent in (
        "recalculated_guideline_cents",
        "variance_numerator_cents",
        "substantial_change_met",
        "info_requested_reason",
        "screened_at",
        "proposed_order_id",
    ):
        assert review.get(absent) is None, absent
    assert review["info_request_count"] == 0

    referral = rows["referral"]
    assert referral["status"] == "DRAFT"
    for absent in (
        "transmitted_at",
        "ack_due_at",
        "registered_at",
        "controlling_order_id",
        "controlling_order_state_code",
        "returned_reason",
    ):
        assert referral.get(absent) is None, absent
    # Drafting leaves the case's interstate posture alone.
    assert fx.read_case(scenario.case_id)["interstate_role"] == "NONE"


# ---------------------------------------------------------------------------
# One-shot triggers refuse a replay; the accrual run welcomes one
# ---------------------------------------------------------------------------


def test_10_the_second_paternity_action_and_the_second_entry_are_both_refused():
    """
    Two triggers that have already fired once, replayed with valid payloads.

    A case carries at most one paternity action, ever. A `CaseWorker` opens it by naming a `method` — `VOLUNTARY_ACKNOWLEDGMENT`, `GENETIC_TEST` or `PRESUMED_MARITAL` — against a case, and a second attempt on a case that already has one is refused with `ERR_DUPLICATE_PATERNITY_ACTION` (HTTP 409).

    `SUPERSEDED` and `VACATED` are terminal for an order. Calculating a superseded order, entering a draft, requesting findings on an order that has none pending, issuing withholding against an order that is not entered, posting a charge against a vacated order, or opening a modification review on an order that is not entered all answer with `ERR_INVALID_ORDER_STATUS` (HTTP 409).

    Design: Corner/state_machines/repeating_a_completed_trigger_errors_while_accrual_runs_stay_idempotent
    """
    scenario = _settled_action_entered_order_and_one_unpaid_charge()

    for method in ("PRESUMED_MARITAL", "GENETIC_TEST"):
        response = api_client.create_paternity_action(
            scenario.case_id, f.paternity_action_payload(method), CASE_WORKER_HEADERS
        )
        validate_error(response, ApiErrorId.DUPLICATE_PATERNITY_ACTION.value, 409)

    response = api_client.enter_order(
        scenario.order_id, f.entry_payload(), SUPERVISING_ATTORNEY_HEADERS
    )
    validate_error(response, ApiErrorId.INVALID_ORDER_STATUS.value, 409)

    actions, meta = validate_paginated(
        api_client.list_paternity_actions(CASE_WORKER_HEADERS, {"case_id": scenario.case_id})
    )
    assert meta["total_count"] == 1
    assert actions[0]["id"] == scenario.paternity_action["id"]
    assert actions[0]["method"] == "PRESUMED_MARITAL"
    settled_order = fx.read_order(scenario.order_id)
    assert settled_order["status"] == "ENTERED"
    assert settled_order["monthly_obligation_cents"] == 75000


def test_11_a_second_accrual_run_at_the_same_clock_reproduces_every_figure():
    """
    The run is a recomputation, not an accumulator, so replaying it is harmless.

    The run is idempotent for a fixed clock: running it twice without advancing the clock produces identical figures, because both measures are pure functions of the charge set and the as-of date rather than accumulators.

    The run writes each `OPEN` charge's `interest_accrued_cents` from the per-charge statutory measure, recomputes the case's `interest_receivable_cents` as the aggregate month-end measure less `interest_written_off_cents` less `interest_collected_cents`, and increases the case's `version` by 1.

    Design: Corner/state_machines/repeating_a_completed_trigger_errors_while_accrual_runs_stay_idempotent
    """
    scenario = _settled_action_entered_order_and_one_unpaid_charge()
    charge_id = scenario.charges[0]["id"]

    first_case = scenario.case
    first_ledger = fx.read_ledger(scenario.case_id)
    # One whole calendar month from 2026-08-15 to 2026-10-01.
    assert first_ledger["statutory_interest_cents"] == 375
    # Two month ends fall strictly before 2026-10-01: 08-31 and 09-30.
    assert first_ledger["aggregate_interest_cents"] == 750
    assert first_ledger["interest_receivable_cents"] == 750
    assert first_case["arrears_principal_cents"] == 75000
    assert fx.read_charge(charge_id)["interest_accrued_cents"] == 375

    second_case = fx.run_accrual(scenario.case_id)
    second_ledger = fx.read_ledger(scenario.case_id)

    for field in (
        "statutory_interest_cents",
        "aggregate_interest_cents",
        "interest_written_off_cents",
        "interest_collected_cents",
        "interest_receivable_cents",
        "arrears_principal_cents",
        "assigned_arrears_cents",
        "unassigned_arrears_cents",
        "unapplied_credit_cents",
    ):
        assert second_ledger[field] == first_ledger[field], field
    for field in (
        "interest_receivable_cents",
        "interest_written_off_cents",
        "interest_collected_cents",
        "arrears_principal_cents",
        "total_charged_principal_cents",
    ):
        assert second_case[field] == first_case[field], field
    assert fx.read_charge(charge_id)["interest_accrued_cents"] == 375
    # The figures repeat; only the case version records that a run happened.
    assert second_case["version"] == first_case["version"] + 1


# ---------------------------------------------------------------------------
# Order triggers fired from outside the declared transition list
# ---------------------------------------------------------------------------


def test_12_an_entered_order_refuses_the_worksheet_a_second_entry_and_both_deviation_steps():
    """
    Four triggers, each legal from some other state, all refused from `ENTERED`.

    Only then are state preconditions evaluated: `ERR_INVALID_CASE_STATUS`, `ERR_INVALID_ORDER_STATUS`, `ERR_INVALID_PATERNITY_STATUS`, `ERR_INVALID_IWO_STATUS`, `ERR_INVALID_REVIEW_STATUS`, `ERR_INVALID_ACTION_STATUS`, `ERR_INVALID_REFERRAL_STATUS` and `ERR_INVALID_OFFER_STATUS`, each at HTTP 409.

    Running the worksheet drives `DRAFT → CALCULATED`, and re-running it is a self-transition from `CALCULATED` back to `CALCULATED` that keeps a draft in step with income updates; the self-transition is permitted only while `deviation_applied` is false.

    A caseworker who believes the guideline number is wrong requests a deviation, driving `CALCULATED → PENDING_DEVIATION_FINDINGS`.

    Design: Corner/state_machines/every_order_trigger_outside_the_transition_list_is_refused
    """
    scenario, _draft = _entered_order_beside_a_draft_medical_order()
    order_id = scenario.order_id
    version_before = fx.read_order(order_id)["version"]

    refusals = [
        api_client.run_guideline_calculation(
            order_id, f.guideline_calculation_payload(), CASE_WORKER_HEADERS
        ),
        api_client.enter_order(order_id, f.entry_payload(), SUPERVISING_ATTORNEY_HEADERS),
        api_client.request_deviation(
            order_id, f.deviation_request_payload(60000, "HARDSHIP"), CASE_WORKER_HEADERS
        ),
        api_client.decide_deviation_findings(
            order_id, f.deviation_findings_payload("APPROVE"), SUPERVISING_ATTORNEY_HEADERS
        ),
    ]
    for response in refusals:
        validate_error(response, ApiErrorId.INVALID_ORDER_STATUS.value, 409)

    unmoved = fx.read_order(order_id)
    assert unmoved["status"] == "ENTERED"
    assert unmoved["monthly_obligation_cents"] == 75000
    assert unmoved["deviation_applied"] is False
    assert unmoved["deviation_rejection_count"] == 0
    assert unmoved.get("deviation_requested_cents") is None
    assert unmoved["version"] == version_before


def test_13_a_draft_refuses_five_triggers_but_vacates_freely_and_then_refuses_a_charge():
    """
    The one legal trigger from `DRAFT` is vacatur, and it closes the row for good.

    `SUPERSEDED` and `VACATED` are terminal for an order. Calculating a superseded order, entering a draft, requesting findings on an order that has none pending, issuing withholding against an order that is not entered, posting a charge against a vacated order, or opening a modification review on an order that is not entered all answer with `ERR_INVALID_ORDER_STATUS` (HTTP 409).

    From `DRAFT` it is unconditional and consequence-free: no charge and no withholding order exists yet, so nothing cascades.

    Design: Corner/state_machines/every_order_trigger_outside_the_transition_list_is_refused
    """
    scenario, draft = _entered_order_beside_a_draft_medical_order()
    draft_id = draft["id"]
    assert draft["status"] == "DRAFT"

    refusals = [
        api_client.enter_order(draft_id, f.entry_payload(), SUPERVISING_ATTORNEY_HEADERS),
        api_client.request_deviation(
            draft_id, f.deviation_request_payload(60000, "HARDSHIP"), CASE_WORKER_HEADERS
        ),
        api_client.decide_deviation_findings(
            draft_id, f.deviation_findings_payload("REJECT"), SUPERVISING_ATTORNEY_HEADERS
        ),
        api_client.issue_withholding_order(
            draft_id,
            f.withholding_order_payload(
                scenario.employer_id,
                fx.read_order(draft_id)["version"],
                reported_disposable_income_cents=234000,
            ),
            CASE_WORKER_HEADERS,
        ),
        api_client.create_modification_review(
            draft_id, f.modification_review_payload("PARTY_REQUEST"), CASE_WORKER_HEADERS
        ),
    ]
    for response in refusals:
        validate_error(response, ApiErrorId.INVALID_ORDER_STATUS.value, 409)

    vacated = fx.vacate_order(draft_id, "CLERICAL_ERROR")
    assert vacated["status"] == "VACATED"
    assert vacated["vacate_reason"] == "CLERICAL_ERROR"
    # Nothing existed underneath a draft, so nothing was terminated with it.
    assert vacated.get("terminated_date") is None

    response = api_client.post_charge(
        draft_id,
        f.charge_payload(
            charge_type="MEDICAL_SUPPORT",
            period_start_date="2026-09-01",
            period_end_date="2026-10-01",
            due_date="2026-09-01",
            amount_cents=20000,
        ),
        FINANCE_OFFICER_HEADERS,
    )
    validate_error(response, ApiErrorId.INVALID_ORDER_STATUS.value, 409)

    # The entered order beside it is untouched by any of this.
    assert fx.read_order(scenario.order_id)["status"] == "ENTERED"
