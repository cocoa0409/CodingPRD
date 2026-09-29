"""
The machines that reach outside their own row: locate, exclusion, voidance,
remedies, referrals and settlement plans.

Each scenario fires one trigger and then reads the neighbours it was declared to
move — a participant's locate status, a case's closure, three ledger totals, a
sister referral, a participant remedy flag — and, where a window or a counter is
involved, the instant or the cent on either side of the edge.
"""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import validate_error, validate_success

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
)

#: The instant thirty days after a notice sent at 2026-11-01.
CONTEST_DEADLINE = "2026-12-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Shared scenario builders
# ---------------------------------------------------------------------------


def _case_whose_obligor_has_never_been_located() -> fx.Scenario:
    """
    A direct-application case with no locate history at all: the obligor's
    `locate_status` is still `NOT_NEEDED` and no paternity action exists, because
    none can be opened while the obligor is unlocated.
    """
    return fx.open_case_with_parties(
        clock=CLOCK_START,
        cp_overrides={"full_name": "Dana Ruiz", "ssn_last4": "4343"},
        ncp_overrides={"full_name": "Alex Ruiz", "ssn_last4": "4444"},
        locate_outcome=None,
        child_count=2,
        tanf_assistance=False,
        good_cause_claim=False,
    )


def _specimen_collected_at_the_appointment_instant() -> fx.Scenario:
    """
    A genetic-test action ordered at 2026-08-01 for an appointment at 2026-08-20,
    with the specimen collected at exactly that instant and no result recorded.
    """
    scenario = fx.open_case_with_parties(
        clock=CLOCK_START,
        cp_overrides={"full_name": "Dana Ruiz", "ssn_last4": "4545"},
        ncp_overrides={"full_name": "Alex Ruiz", "ssn_last4": "4646"},
        child_count=2,
        tanf_assistance=False,
        good_cause_claim=False,
    )
    scenario.paternity_action = fx.open_paternity_action(scenario.case_id, "GENETIC_TEST")
    scenario.paternity_action = fx.order_genetic_test(
        scenario.paternity_action["id"], "2026-08-20T00:00:00Z"
    )
    fx.set_clock("2026-08-20T00:00:00Z")
    scenario.paternity_action = fx.collect_specimen(scenario.paternity_action["id"], True)
    return scenario


def _two_charges_with_a_part_payment_at_the_twentieth() -> fx.Scenario:
    """
    Two 75,000-cent charges due 2026-08-15 and 2026-09-15, and a direct payment of
    20,000 cents landing at 2026-09-20 on the charge whose period contains that
    date — leaving the older charge wholly unpaid and the newer one part paid.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={"full_name": "Dana Ruiz", "ssn_last4": "4747"},
        ncp_overrides={"full_name": "Alex Ruiz", "ssn_last4": "4848"},
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
    scenario.charges = fx.post_monthly_charges(
        scenario.order_id, ["2026-08-01", "2026-09-01"], due_day=15
    )
    fx.set_clock("2026-09-20T00:00:00Z")
    scenario.payments = [fx.post_payment(scenario.case_id, 20000, source="DIRECT_PAY")]
    scenario.reload_case()
    return scenario


def _delinquent_case(cp_ssn: str, ncp_ssn: str, origin_state_code: str = "MN") -> fx.Scenario:
    """
    An entered order at 75,000 cents carrying two unpaid 75,000-cent charges due
    2026-08-15 and 2026-09-15, with the clock left at 2026-11-01.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={"full_name": "Dana Ruiz", "ssn_last4": cp_ssn},
        ncp_overrides={"full_name": "Alex Ruiz", "ssn_last4": ncp_ssn},
        case_overrides={
            "child_count": 2,
            "tanf_assistance": False,
            "good_cause_claim": False,
        },
        order_overrides={
            "origin_state_code": origin_state_code,
            "effective_date": "2026-08-01",
            "medical_support_monthly_cents": 0,
        },
    )
    scenario.charges = fx.post_monthly_charges(
        scenario.order_id, ["2026-08-01", "2026-09-01"], due_day=15
    )
    fx.set_clock("2026-11-01T00:00:00Z")
    scenario.reload_case()
    return scenario


def _two_noticed_credit_bureau_actions() -> Tuple[fx.Scenario, fx.Scenario]:
    """
    Two identical delinquent cases, each carrying a `CREDIT_BUREAU_REPORT` action
    noticed at 2026-11-01, so both share a `contest_deadline_at` of 2026-12-01.
    """
    left = _delinquent_case("4949", "5050")
    right = _delinquent_case("5151", "5252")
    for scenario in (left, right):
        action = fx.propose_enforcement_action(scenario.case_id, "CREDIT_BUREAU_REPORT")
        scenario.enforcement_action = fx.send_enforcement_notice(action["id"])
    return left, right


def _registered_wisconsin_referral_and_a_noticed_remedy() -> fx.Scenario:
    """
    A Wisconsin-origin entered order, a responding Wisconsin enforcement referral
    registered at 2026-11-01, and a `CREDIT_BUREAU_REPORT` action noticed the same
    day — with the clock then carried past the contest deadline to 2026-12-02.
    """
    scenario = _delinquent_case("5353", "5454", origin_state_code="WI")
    scenario.interstate_referral = fx.register_responding_referral(
        scenario.case_id,
        other_state_code="WI",
        child_home_state_code="WI",
        transmittal_type="ENFORCEMENT",
    )
    action = fx.propose_enforcement_action(scenario.case_id, "CREDIT_BUREAU_REPORT")
    scenario.enforcement_action = fx.send_enforcement_notice(action["id"])
    fx.set_clock("2026-12-02T00:00:00Z")
    return scenario


def _accepted_three_installment_plan() -> fx.Scenario:
    """
    A three-installment settlement of the 150,000-cent arrears plus 1,875 cents of
    aggregate interest, accepted by the obligor at 2026-11-01.
    """
    scenario = _delinquent_case("5555", "5656")
    scenario.compromise_offer = fx.create_compromise_offer(
        scenario.case_id, installment_count=3
    )
    scenario.compromise_offer = fx.accept_compromise_offer(
        scenario.compromise_offer["id"], scenario.ncp_id
    )
    return scenario


# ---------------------------------------------------------------------------
# The locate self-loop and the third attempt that ends it
# ---------------------------------------------------------------------------


def test_01_each_locate_referral_applies_all_four_side_effects_and_the_third_gives_up():
    """
    Three referrals, two rows moving in step, and one status flip at the end.

    Referring the obligor to locate services drives `case_status` from `OPENED` to `LOCATE`, and a repeat referral is a self-transition from `LOCATE` back to `LOCATE`.

    Each referral increases the case's `locate_referral_count` by 1 and the case's `version` by 1, sets the obligor's `locate_status` to `PENDING` and increases the obligor's `locate_attempt_count` by 1.

    The referral whose increment brings `locate_attempt_count` up to three additionally sets that participant's `locate_status` to `UNLOCATABLE` — the agency has exhausted its statutory attempts.

    Design: Corner/state_machines/locate_referral_self_loop_exhausts_at_three_attempts
    """
    scenario = _case_whose_obligor_has_never_been_located()

    assert scenario.case["case_status"] == "OPENED"
    assert scenario.case["locate_referral_count"] == 0
    obligor = fx.read_participant(scenario.ncp_id)
    assert obligor["locate_status"] == "NOT_NEEDED"
    assert obligor["locate_attempt_count"] == 0
    version_before = scenario.case["version"]

    expected = [
        ("FEDERAL_PLS", 1, "PENDING"),
        ("STATE_DIRECTORY_OF_NEW_HIRES", 2, "PENDING"),
        ("CREDIT_BUREAU", 3, "UNLOCATABLE"),
    ]
    for locate_source, attempt, locate_status in expected:
        case = fx.refer_to_locate(scenario.case_id, locate_source)
        assert case["case_status"] == "LOCATE", locate_source
        assert case["locate_referral_count"] == attempt, locate_source
        assert case["version"] == version_before + attempt, locate_source
        obligor = fx.read_participant(scenario.ncp_id)
        assert obligor["locate_attempt_count"] == attempt, locate_source
        assert obligor["locate_status"] == locate_status, locate_source


def test_02_the_fourth_referral_is_exhausted_and_the_closed_case_refuses_a_fifth():
    """
    Being unlocatable is what lets the case close, and closing shuts every door.

    A fourth referral is refused with `ERR_LOCATE_ATTEMPTS_EXHAUSTED` (HTTP 409).

    From `LOCATE`, the case may close only when the obligor's `locate_status` is `UNLOCATABLE` and the `closed_reason` is `NO_JURISDICTION` — the agency cannot proceed against a person it cannot find.

    Finally, a `CLOSED` case rejects every write — every write directed at the case itself and every write directed at a child of the case — with `ERR_INVALID_CASE_STATUS`.

    Design: Corner/state_machines/locate_referral_self_loop_exhausts_at_three_attempts
    """
    scenario = _case_whose_obligor_has_never_been_located()
    for locate_source in ("FEDERAL_PLS", "STATE_DIRECTORY_OF_NEW_HIRES", "CREDIT_BUREAU"):
        fx.refer_to_locate(scenario.case_id, locate_source)

    response = api_client.create_locate_referral(
        scenario.case_id, f.locate_referral_payload("EMPLOYER_TIP"), CASE_WORKER_HEADERS
    )
    validate_error(response, ApiErrorId.LOCATE_ATTEMPTS_EXHAUSTED.value, 409)

    unmoved = fx.read_case(scenario.case_id)
    assert unmoved["locate_referral_count"] == 3
    assert unmoved["case_status"] == "LOCATE"
    assert fx.read_participant(scenario.ncp_id)["locate_attempt_count"] == 3

    closed = fx.close_case(scenario.case_id, "NO_JURISDICTION")
    assert closed["case_status"] == "CLOSED"
    assert closed["closed_reason"] == "NO_JURISDICTION"
    a.assert_instant_equals(closed["closed_at"], CLOCK_START, "closed_at")

    response = api_client.create_locate_referral(
        scenario.case_id, f.locate_referral_payload("FEDERAL_PLS"), CASE_WORKER_HEADERS
    )
    validate_error(response, ApiErrorId.INVALID_CASE_STATUS.value, 409)
    assert fx.read_case(scenario.case_id)["locate_referral_count"] == 3


# ---------------------------------------------------------------------------
# Exclusion moves the test cost and closes the case in one request
# ---------------------------------------------------------------------------


def test_03_a_probability_below_the_threshold_bills_the_state_and_closes_the_case():
    """
    One result recording, and the consequence runs four levels deep.

    Specimen collection is recorded by a `CaseWorker` and may only happen once the clock has reached `collection_appointment_at` — at or after that instant; earlier is again `ERR_COLLECTION_APPOINTMENT_NOT_REACHED`.

    A probability below 99.0 drives `GENETIC_COLLECTED → EXCLUDED` and sets `genetic_cost_liable_party` to `STATE`, meaning the test cost is never billed to the obligor.

    At the first level the case moves to `CLOSED` with `closed_reason` `NO_JURISDICTION` and `closed_at` stamped with the current clock — this is also the transition `PATERNITY_PENDING → CLOSED`.

    Design: Corner/state_machines/paternity_exclusion_shifts_the_genetic_cost_and_closes_the_case
    """
    scenario = _specimen_collected_at_the_appointment_instant()
    action = scenario.paternity_action

    assert action["status"] == "GENETIC_COLLECTED"
    assert action["method"] == "GENETIC_TEST"
    assert action["genetic_cost_cents"] == 48000
    # Collection at exactly the appointment instant is timely.
    a.assert_instant_equals(
        action["specimen_collected_at"], "2026-08-20T00:00:00Z", "specimen_collected_at"
    )
    assert fx.read_case(scenario.case_id)["case_status"] == "PATERNITY_PENDING"

    excluded = fx.record_genetic_result(action["id"], 98.5)

    assert excluded["status"] == "EXCLUDED"
    assert excluded["genetic_probability_pct"] == 98.5
    assert excluded["genetic_cost_liable_party"] == "STATE"
    assert excluded["genetic_cost_cents"] == 48000
    assert excluded.get("established_at") is None
    assert excluded.get("established_method") is None

    case = fx.read_case(scenario.case_id)
    assert case["case_status"] == "CLOSED"
    assert case["closed_reason"] == "NO_JURISDICTION"
    a.assert_instant_equals(case["closed_at"], "2026-08-20T00:00:00Z", "closed_at")


def test_04_the_case_closed_by_exclusion_refuses_both_a_locate_referral_and_a_new_order():
    """
    Two writes that would have been legal a moment earlier are now refused.

    Finally, a `CLOSED` case rejects every write — every write directed at the case itself and every write directed at a child of the case — with `ERR_INVALID_CASE_STATUS`.

    First, when a support order is drafted on a case, the case-status check rejects only a `CLOSED` case; the requirement that the case has actually reached order establishment is owned by the paternity-settlement check, so a case that has not yet reached `ORDER_ESTABLISHMENT` answers with `ERR_PATERNITY_NOT_ESTABLISHED` and never with `ERR_INVALID_CASE_STATUS`.

    Design: Corner/state_machines/paternity_exclusion_shifts_the_genetic_cost_and_closes_the_case
    """
    scenario = _specimen_collected_at_the_appointment_instant()
    fx.record_genetic_result(scenario.paternity_action["id"], 98.5)

    refused_referral = api_client.create_locate_referral(
        scenario.case_id, f.locate_referral_payload("FEDERAL_PLS"), CASE_WORKER_HEADERS
    )
    validate_error(refused_referral, ApiErrorId.INVALID_CASE_STATUS.value, 409)

    refused_order = api_client.create_order(
        scenario.case_id,
        f.order_payload(
            order_type="CURRENT_SUPPORT",
            origin_state_code="MN",
            effective_date="2026-09-01",
        ),
        CASE_WORKER_HEADERS,
    )
    refusal = validate_error(refused_order, ApiErrorId.INVALID_CASE_STATUS.value, 409)
    # On a closed case the status check answers, not the paternity carve-out.
    assert refusal["error_id"] != ApiErrorId.PATERNITY_NOT_ESTABLISHED.value

    assert fx.read_case(scenario.case_id)["case_status"] == "CLOSED"


# ---------------------------------------------------------------------------
# Voidance reconciles three ancestor figures and spares the part-paid charge
# ---------------------------------------------------------------------------


def test_05_the_part_paid_charge_cannot_be_withdrawn_by_hand():
    """
    The payment landed on the newer charge, which is what protects it.

    **Bucket one, current support for the current period**: the `OPEN` `CURRENT_SUPPORT` charges of the case whose period contains the payment's `received_at` date — that is, `period_start_date` less than or equal to that date and `period_end_date` strictly greater — are taken in order of `due_date` and then `created_at`, and each absorbs the smaller of the remaining balance and its own `unpaid_balance_cents`, accumulating into `applied_current_cents`.

    On the manual path a `FinanceOfficer` voids the charge, and the charge must have `paid_cents` of zero — a partly paid charge cannot be withdrawn by hand, and the attempt answers with `ERR_CHARGE_PARTIALLY_PAID` (HTTP 409).

    Design: Corner/state_machines/charge_voidance_reconciles_the_case_ledger_and_the_interest_base
    """
    scenario = _two_charges_with_a_part_payment_at_the_twentieth()
    older, newer = scenario.charges

    # 2026-09-20 falls inside the second charge's period, not the first's.
    assert scenario.payments[0]["applied_current_cents"] == 20000
    assert scenario.case["total_charged_principal_cents"] == 150000
    assert scenario.case["arrears_principal_cents"] == 130000
    # The only month end strictly before 2026-09-20 with a due balance is 08-31.
    assert scenario.case["interest_receivable_cents"] == 375

    response = api_client.void_charge(
        newer["id"], f.voidance_payload(), FINANCE_OFFICER_HEADERS
    )
    validate_error(response, ApiErrorId.CHARGE_PARTIALLY_PAID.value, 409)

    protected = fx.read_charge(newer["id"])
    assert protected["status"] == "OPEN"
    assert protected["paid_cents"] == 20000
    assert protected["unpaid_balance_cents"] == 55000
    assert fx.read_charge(older["id"])["paid_cents"] == 0


def test_06_voiding_the_unpaid_charge_moves_the_ledger_and_the_interest_base_at_once():
    """
    One void, and three computed case figures fall together.

    Voidance subtracts the charge's `amount_cents` from the case's `total_charged_principal_cents`, recomputes the case's `arrears_principal_cents`, and increases the case's `version` by 1 — the charge itself has no version to increase.

    Charges in `VOID` and charges in `SATISFIED` are excluded entirely and retroactively — once a charge is satisfied it contributes nothing to either measure, including for month-end snapshots that predate the payment that satisfied it.

    Design: Corner/state_machines/charge_voidance_reconciles_the_case_ledger_and_the_interest_base
    """
    scenario = _two_charges_with_a_part_payment_at_the_twentieth()
    older, newer = scenario.charges
    version_before = scenario.case["version"]

    voided = fx.void_charge(older["id"])
    assert voided["status"] == "VOID"

    after = fx.read_case(scenario.case_id)
    # 150000 less the voided charge's own amount.
    assert after["total_charged_principal_cents"] == 75000
    # Only the part-paid charge is still open.
    assert after["arrears_principal_cents"] == 55000
    # The 2026-08-31 snapshot loses its only due balance retroactively.
    assert after["interest_receivable_cents"] == 0
    assert after["version"] == version_before + 1

    ledger = fx.read_ledger(scenario.case_id)
    assert ledger["aggregate_interest_cents"] == 0
    assert ledger["statutory_interest_cents"] == 0

    untouched = fx.read_charge(newer["id"])
    assert untouched["status"] == "OPEN"
    assert untouched["paid_cents"] == 20000
    assert untouched["unpaid_balance_cents"] == 55000


# ---------------------------------------------------------------------------
# One deadline instant, two complementary branches out of NOTICE_SENT
# ---------------------------------------------------------------------------


def test_07_activation_at_the_deadline_instant_itself_is_premature():
    """
    The clock reaches the deadline exactly and the contest branch still owns it.

    Notice stamps `notice_sent_at` from the logical clock, computes `contest_deadline_at` as thirty days later, and increases the action's `version` by 1.

    That path requires the clock to be **strictly after** `contest_deadline_at`, because the obligor is entitled to the whole window; activating at an instant exactly equal to the deadline is premature and answers with `ERR_CONTEST_WINDOW_OPEN` (HTTP 409).

    Design: Corner/state_machines/contest_and_activation_windows_pivot_on_the_same_deadline_instant
    """
    left, _right = _two_noticed_credit_bureau_actions()
    action = left.enforcement_action

    assert action["status"] == "NOTICE_SENT"
    assert action["eligibility_threshold_cents"] == 100000
    # 150000 of principal plus 750 and 375 of per-charge statutory interest.
    assert action["arrears_certified_snapshot_cents"] == 151125
    a.assert_instant_equals(action["notice_sent_at"], "2026-11-01T00:00:00Z", "notice_sent_at")
    a.assert_instant_equals(action["contest_deadline_at"], CONTEST_DEADLINE, "contest_deadline_at")

    early = api_client.activate_enforcement_action(
        action["id"], f.activation_payload(), CASE_WORKER_HEADERS
    )
    validate_error(early, ApiErrorId.CONTEST_WINDOW_OPEN.value, 409)

    fx.set_clock(CONTEST_DEADLINE)
    on_the_instant = api_client.activate_enforcement_action(
        action["id"], f.activation_payload(), CASE_WORKER_HEADERS
    )
    validate_error(on_the_instant, ApiErrorId.CONTEST_WINDOW_OPEN.value, 409)

    assert fx.read_enforcement_action(action["id"])["status"] == "NOTICE_SENT"
    assert fx.read_enforcement_action(action["id"])["remedy_applied"] is False


def test_08_a_contest_filed_at_the_deadline_instant_is_timely():
    """
    The same instant that refused the activation admits the obligor's contest.

    The window is **inclusive**: a contest filed at an instant equal to `contest_deadline_at` is timely, and only an instant strictly after it is late, answering with `ERR_CONTEST_WINDOW_CLOSED` (HTTP 409).

    The two conditions are exact complements, so at any given instant precisely one of the two branches is open.

    Design: Corner/state_machines/contest_and_activation_windows_pivot_on_the_same_deadline_instant
    """
    left, _right = _two_noticed_credit_bureau_actions()
    action = left.enforcement_action

    fx.set_clock(CONTEST_DEADLINE)
    refused = api_client.activate_enforcement_action(
        action["id"], f.activation_payload(), CASE_WORKER_HEADERS
    )
    validate_error(refused, ApiErrorId.CONTEST_WINDOW_OPEN.value, 409)

    contested = fx.contest_enforcement_action(action["id"], left.ncp_id, "MISTAKE_OF_FACT")

    assert contested["status"] == "CONTESTED"
    assert contested["contest_grounds"] == "MISTAKE_OF_FACT"
    a.assert_instant_equals(contested["contested_at"], CONTEST_DEADLINE, "contested_at")
    assert contested["remedy_applied"] is False
    # The obligor's own flag is untouched: nothing has activated.
    assert fx.read_participant(left.ncp_id)["credit_bureau_reported"] is False


def test_09_one_day_later_the_branches_have_swapped():
    """
    At 2026-12-02 the contest is late and the untouched twin activates cleanly.

    `ACTIVE` is a genuine join point: the uncontested branch and the upheld-contest branch land there with **identical** side effects.

    `activated_at` is stamped from the logical clock, `remedy_applied` becomes true, the case's `enforcement_posture` becomes `ESCALATED`, and the participant-level flag matching the remedy is set — `LICENSE_SUSPENSION` sets `license_suspension_active` and simultaneously clears `has_valid_drivers_license`, `PROPERTY_LIEN` sets `lien_recorded`, and `CREDIT_BUREAU_REPORT` sets `credit_bureau_reported`.

    Design: Corner/state_machines/contest_and_activation_windows_pivot_on_the_same_deadline_instant
    """
    left, right = _two_noticed_credit_bureau_actions()

    fx.set_clock("2026-12-02T00:00:00Z")

    late = api_client.contest_enforcement_action(
        left.enforcement_action["id"], f.contest_payload("MISTAKE_OF_FACT"), left.ncp_headers
    )
    validate_error(late, ApiErrorId.CONTEST_WINDOW_CLOSED.value, 409)
    assert fx.read_enforcement_action(left.enforcement_action["id"])["status"] == "NOTICE_SENT"

    activated = fx.activate_enforcement_action(right.enforcement_action["id"])

    assert activated["status"] == "ACTIVE"
    a.assert_instant_equals(activated["activated_at"], "2026-12-02T00:00:00Z", "activated_at")
    assert activated["remedy_applied"] is True
    assert fx.read_participant(right.ncp_id)["credit_bureau_reported"] is True
    assert fx.read_case(right.case_id)["enforcement_posture"] == "ESCALATED"


# ---------------------------------------------------------------------------
# The referral transition that has no endpoint of its own
# ---------------------------------------------------------------------------


def test_10_activating_the_remedy_moves_the_sister_referral_to_enforcing():
    """
    Nothing was posted to the referral, and the referral changed state anyway.

    A `REGISTERED` referral moves to `ENFORCING` as a system cascade when an enforcement action on the same case reaches `ACTIVE`, and only when the referral's `transmittal_type` is `ENFORCEMENT`; an establishment or modification transmittal stays `REGISTERED` no matter what enforcement does, because active enforcement is not what it asked for.

    Activation on the uncontested branch has one further reach: a `REGISTERED` interstate referral of the enforcement transmittal type on the same case moves to `ENFORCING`, because active enforcement is exactly what the responding state was registered to do.

    Design: Corner/state_machines/an_active_remedy_drives_a_registered_referral_to_enforcing
    """
    scenario = _registered_wisconsin_referral_and_a_noticed_remedy()
    referral = scenario.interstate_referral

    assert referral["status"] == "REGISTERED"
    assert referral["transmittal_type"] == "ENFORCEMENT"
    # The sole entered current-support order, and it originates in Wisconsin.
    assert referral["controlling_order_id"] == scenario.order_id
    assert referral["controlling_order_state_code"] == "WI"
    a.assert_instant_equals(referral["registered_at"], "2026-11-01T00:00:00Z", "registered_at")
    # Noticing the remedy left the referral where it stood.
    assert fx.read_interstate_referral(referral["id"])["status"] == "REGISTERED"

    activated = fx.activate_enforcement_action(scenario.enforcement_action["id"])
    assert activated["status"] == "ACTIVE"

    assert fx.read_interstate_referral(referral["id"])["status"] == "ENFORCING"
    case = fx.read_case(scenario.case_id)
    assert case["enforcement_posture"] == "ESCALATED"
    assert case["interstate_role"] == "RESPONDING"


def test_11_releasing_the_remedy_is_what_lets_the_referral_be_returned():
    """
    The release drops the posture and the flag, and only then does the return pass.

    Release stamps `released_at`, sets `remedy_applied` back to false, and reverses the participant flag — but only when no other `ACTIVE` action of the same `action_type` still names that participant.

    The case's `enforcement_posture` returns to `NORMAL` once no `ACTIVE` action remains on it; while any remains, the posture stays `ESCALATED`.

    Every return path sets the case's `interstate_role` back to `NONE` when no other live referral remains on the case, and increases both the referral's and the case's `version` by 1.

    Design: Corner/state_machines/an_active_remedy_drives_a_registered_referral_to_enforcing
    """
    scenario = _registered_wisconsin_referral_and_a_noticed_remedy()
    referral = scenario.interstate_referral

    fx.activate_enforcement_action(scenario.enforcement_action["id"])
    assert fx.read_participant(scenario.ncp_id)["credit_bureau_reported"] is True

    released = fx.release_enforcement_action(
        scenario.enforcement_action["id"], "PLAN_COMPLIANT"
    )
    assert released["status"] == "RELEASED"
    assert released["release_reason"] == "PLAN_COMPLIANT"
    a.assert_instant_equals(released["released_at"], "2026-12-02T00:00:00Z", "released_at")
    assert released["remedy_applied"] is False
    # No other active report of this type names the obligor.
    assert fx.read_participant(scenario.ncp_id)["credit_bureau_reported"] is False
    assert fx.read_case(scenario.case_id)["enforcement_posture"] == "NORMAL"

    returned = fx.return_referral(referral["id"], "INSUFFICIENT_INFO")

    assert returned["status"] == "RETURNED"
    assert returned["returned_reason"] == "INSUFFICIENT_INFO"
    assert fx.read_case(scenario.case_id)["interstate_role"] == "NONE"


# ---------------------------------------------------------------------------
# Three installments, two different gates, and one remainder cent
# ---------------------------------------------------------------------------


def test_12_the_frozen_terms_put_the_whole_remainder_on_the_last_installment():
    """
    151,406 over three months is 50,468 twice and 50,470 once.

    `monthly_installment_cents` is `settlement_total_cents` divided by `installment_count`, floored to whole cents, and `final_installment_cents` is `settlement_total_cents` less `monthly_installment_cents` multiplied by one fewer than `installment_count`, so the whole remainder lands entirely on the last installment and the schedule sums to `settlement_total_cents` exactly.

    Acceptance stamps `accepted_at` from the logical clock, sets `next_installment_due_date` to one month after the acceptance date, adds `interest_waiver_cents` to the case's `interest_written_off_cents` — which is what removes the waived interest from `interest_receivable_cents` — and sets the case's `enforcement_posture` to `STAYED`.

    Design: Corner/state_machines/the_final_installment_completes_the_offer_and_lifts_the_stay
    """
    scenario = _accepted_three_installment_plan()
    offer = scenario.compromise_offer

    assert offer["principal_due_snapshot_cents"] == 150000
    # Month ends 08-31, 09-30 and 10-31 over balances of 75000, 150000, 150000.
    assert offer["interest_due_snapshot_cents"] == 1875
    assert offer["pre_waiver_total_cents"] == 151875
    assert offer["waiver_tier_pct"] == 0.25
    # round_half_up(1875 * 0.25) = round_half_up(468.75).
    assert offer["interest_waiver_cents"] == 469
    assert offer["settlement_total_cents"] == 151406
    assert offer["monthly_installment_cents"] == 50468
    assert offer["final_installment_cents"] == 50470
    assert 50468 * 2 + 50470 == 151406

    assert offer["status"] == "ACCEPTED"
    assert offer["compliance_payment_count"] == 0
    a.assert_instant_equals(offer["accepted_at"], "2026-11-01T00:00:00Z", "accepted_at")
    assert offer["next_installment_due_date"] == "2026-12-01"
    assert fx.read_case(scenario.case_id)["enforcement_posture"] == "STAYED"


def test_13_the_first_two_installments_walk_the_monthly_gate():
    """
    One cent short of 50,468 is refused, and the two payments that clear it advance
    the count and the due date each time.

    A `COMPROMISE_INSTALLMENT` payment must cover at least the referenced offer's `monthly_installment_cents`, or the offer's `final_installment_cents` when it is the last installment due, and a short payment is refused with `ERR_PAYMENT_BELOW_INSTALLMENT` (HTTP 422); a sufficient one advances the offer along its installment track.

    Each further installment is a self-loop `ACTIVE → ACTIVE` while `compliance_payment_count` is still below one fewer than `installment_count`, increasing the count by 1 and advancing the due date by a further month.

    Design: Corner/state_machines/the_final_installment_completes_the_offer_and_lifts_the_stay
    """
    scenario = _accepted_three_installment_plan()
    offer_id = scenario.compromise_offer["id"]

    short = api_client.post_payment(
        scenario.case_id,
        f.installment_payment_payload(50467, offer_id),
        FINANCE_OFFICER_HEADERS,
    )
    validate_error(short, ApiErrorId.PAYMENT_BELOW_INSTALLMENT.value, 422)
    assert fx.read_compromise_offer(offer_id)["status"] == "ACCEPTED"

    fx.pay_installment(scenario.case_id, offer_id, 50468)
    first = fx.read_compromise_offer(offer_id)
    assert first["status"] == "ACTIVE"
    assert first["compliance_payment_count"] == 1
    assert first["next_installment_due_date"] == "2027-01-01"

    fx.pay_installment(scenario.case_id, offer_id, 50468)
    second = fx.read_compromise_offer(offer_id)
    assert second["status"] == "ACTIVE"
    assert second["compliance_payment_count"] == 2
    assert second["next_installment_due_date"] == "2027-02-01"


def test_14_the_final_gate_is_two_cents_higher_and_completion_lifts_the_stay():
    """
    50,469 clears the monthly figure and still fails, because the last one is 50,470.

    The payment whose arrival makes `compliance_payment_count` plus one equal `installment_count` is the final one, and it must cover at least `final_installment_cents` rather than `monthly_installment_cents`; it drives `ACTIVE → COMPLETED`, stamps `completed_at`, makes the interest waiver permanent, returns the case's `enforcement_posture` to `NORMAL`, and satisfies the remaining `OPEN` charges of the case so that `arrears_principal_cents` becomes zero.

    `DEFAULTED` is terminal, and every disallowed origin state on acceptance or on a default declaration answers with `ERR_INVALID_OFFER_STATUS` (HTTP 409).

    Design: Corner/state_machines/the_final_installment_completes_the_offer_and_lifts_the_stay
    """
    scenario = _accepted_three_installment_plan()
    offer_id = scenario.compromise_offer["id"]

    fx.pay_installment(scenario.case_id, offer_id, 50468)
    fx.pay_installment(scenario.case_id, offer_id, 50468)

    short = api_client.post_payment(
        scenario.case_id,
        f.installment_payment_payload(50469, offer_id),
        FINANCE_OFFICER_HEADERS,
    )
    validate_error(short, ApiErrorId.PAYMENT_BELOW_INSTALLMENT.value, 422)
    assert fx.read_compromise_offer(offer_id)["compliance_payment_count"] == 2

    fx.pay_installment(scenario.case_id, offer_id, 50470)
    completed = fx.read_compromise_offer(offer_id)
    assert completed["status"] == "COMPLETED"
    assert completed["compliance_payment_count"] == 3
    a.assert_instant_equals(completed["completed_at"], "2026-11-01T00:00:00Z", "completed_at")

    case = fx.read_case(scenario.case_id)
    assert case["enforcement_posture"] == "NORMAL"
    assert case["arrears_principal_cents"] == 0
    # The waiver became permanent: it was never reversed out of the case.
    assert case["interest_written_off_cents"] == 469
    assert fx.read_charge(scenario.charges[0]["id"])["status"] == "SATISFIED"

    repeat = api_client.declare_compromise_default(
        offer_id, f.default_declaration_payload(), FINANCE_OFFICER_HEADERS
    )
    validate_error(repeat, ApiErrorId.INVALID_OFFER_STATUS.value, 409)
