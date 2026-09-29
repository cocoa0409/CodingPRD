"""
Status dimensions that advance on their own, and one that closes a bounded cycle.

A support case carries three orthogonal dimensions and a withholding order carries
two, and no trigger moves more than the dimension it owns. A paternity action, by
contrast, runs a genuine cycle whose loop counter is bounded at one.
"""

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import make_noncustodial_party_headers
from prd_bench_local_runner.testing import validate_error


# ---------------------------------------------------------------------------
# Shared scenario builders
# ---------------------------------------------------------------------------


def _enforcement_case_with_registered_responding_referral() -> fx.Scenario:
    """
    An enforcement-stage case with three unpaid charges, one accrual run at
    2026-11-01, and one `RESPONDING` enforcement transmittal registered against
    the sister state's order.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Rosa Vance",
            "ssn_last4": "7171",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Seth Vance",
            "ssn_last4": "7272",
            "monthly_gross_income_cents": 300000,
        },
        case_overrides={"child_count": 2, "tanf_assistance": False, "good_cause_claim": False},
        # The order being registered here is the sister state's own order, which
        # is what the responding registration path requires.
        order_overrides={"origin_state_code": "TX", "effective_date": "2026-08-01"},
    )
    scenario.charges = fx.post_monthly_charges(
        scenario.order_id,
        ["2026-08-01", "2026-09-01", "2026-10-01"],
        due_day=15,
    )
    fx.set_clock("2026-11-01T00:00:00Z")
    fx.run_accrual(scenario.case_id)
    scenario.interstate_referral = fx.draft_interstate_referral(
        scenario.case_id,
        direction="RESPONDING",
        other_state_code="TX",
        child_home_state_code="MN",
        transmittal_type="ENFORCEMENT",
    )
    scenario.reload_case()
    return scenario


def _signed_then_rescinded_then_signed_again() -> fx.Scenario:
    """
    A voluntary acknowledgment taken back once and then executed again, with the
    clock held at 2026-08-01 so the re-derived window is still open.
    """
    scenario = fx.open_case_with_parties(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Tara Lund",
            "ssn_last4": "8181",
            "monthly_gross_income_cents": 180000,
        },
        ncp_overrides={
            "full_name": "Uri Lund",
            "ssn_last4": "8282",
            "monthly_gross_income_cents": 240000,
        },
        child_count=1,
        tanf_assistance=False,
        good_cause_claim=False,
    )
    scenario.paternity_action = fx.open_paternity_action(
        scenario.case_id, "VOLUNTARY_ACKNOWLEDGMENT"
    )
    return scenario


def _served_withholding_order_paid_once() -> fx.Scenario:
    """
    A served withholding order on an MN employer that has remitted 99,000 cents
    at 2026-08-15, leaving the second of six charges part paid.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Vera Nolan",
            "ssn_last4": "9191",
            "monthly_gross_income_cents": 150000,
        },
        ncp_overrides={
            "full_name": "Wes Nolan",
            "ssn_last4": "9292",
            "monthly_gross_income_cents": 330000,
            "supports_second_family": False,
        },
        case_overrides={"child_count": 2, "tanf_assistance": False, "good_cause_claim": False},
        order_overrides={
            "origin_state_code": "MN",
            "effective_date": "2026-08-01",
            "medical_support_monthly_cents": 0,
        },
    )
    scenario.charges = fx.post_monthly_charges(
        scenario.order_id,
        [
            "2026-08-01",
            "2026-09-01",
            "2026-10-01",
            "2026-11-01",
            "2026-12-01",
            "2027-01-01",
        ],
        due_day=15,
    )
    scenario.employer = fx.create_employer(
        state_code="MN", legal_name="Bemidji Millworks", remittance_fee_cents=0
    )
    scenario.withholding_order = fx.issue_withholding_order(
        scenario.order_id,
        scenario.employer_id,
        reported_disposable_income_cents=155000,
    )
    scenario.withholding_order = fx.serve_withholding_order(scenario.iwo_id)
    fx.set_clock("2026-08-15T00:00:00Z")
    scenario.payments = [fx.post_remittance(scenario.iwo_id, scenario.employer_id, 99000)]
    return scenario


# ---------------------------------------------------------------------------
# The three case dimensions
# ---------------------------------------------------------------------------


def test_01_registration_moves_the_interstate_role_and_nothing_else():
    """
    Registering a responding transmittal touches one dimension of three.

    Either way registration stamps `registered_at`, determines the controlling order, sets the case's `interstate_role` to `RESPONDING` on a responding referral, and increases both the referral's and the case's `version` by 1.

    Design: Difficulty/non_linear_state_machine/case_parallel_dimensions_evolve_independently
    """
    scenario = _enforcement_case_with_registered_responding_referral()

    assert scenario.interstate_referral["status"] == "DRAFT"
    assert scenario.case["case_status"] == "ENFORCEMENT"
    assert scenario.case["enforcement_posture"] == "NORMAL"
    assert scenario.case["interstate_role"] == "NONE"

    registered = fx.register_referral(scenario.interstate_referral["id"])

    assert registered["status"] == "REGISTERED"
    assert registered["controlling_order_id"] == scenario.order_id
    assert registered["controlling_order_state_code"] == "TX"

    case = fx.read_case(scenario.case_id)
    # Registration did not move the establishment dimension.
    assert case["case_status"] == "ENFORCEMENT"
    # Registration did not move the escalation dimension.
    assert case["enforcement_posture"] == "NORMAL"
    assert case["interstate_role"] == "RESPONDING"


def test_02_activation_escalates_the_posture_while_the_other_two_dimensions_hold():
    """
    Activating an uncontested remedy escalates and cascades, but only sideways.

    Activation on the uncontested branch has one further reach: a `REGISTERED` interstate referral of the enforcement transmittal type on the same case moves to `ENFORCING`, because active enforcement is exactly what the responding state was registered to do.

    Design: Difficulty/non_linear_state_machine/case_parallel_dimensions_evolve_independently
    """
    scenario = _enforcement_case_with_registered_responding_referral()
    fx.register_referral(scenario.interstate_referral["id"])

    action = fx.propose_enforcement_action(scenario.case_id, "CREDIT_BUREAU_REPORT")
    # 225000 principal plus 1125 of per-charge statutory interest at 2026-11-01.
    assert action["arrears_certified_snapshot_cents"] == 226125
    assert action["eligibility_threshold_cents"] == 100000

    noticed = fx.send_enforcement_notice(action["id"])
    a.assert_instant_equals(noticed["contest_deadline_at"], "2026-12-01T00:00:00Z", "contest_deadline_at")

    fx.set_clock("2026-12-02T00:00:00Z")
    activated = fx.activate_enforcement_action(action["id"])

    assert activated["status"] == "ACTIVE"
    assert activated["remedy_applied"] is True
    a.assert_instant_equals(activated["activated_at"], "2026-12-02T00:00:00Z", "activated_at")

    case = fx.read_case(scenario.case_id)
    # Activation did not move the establishment dimension either.
    assert case["case_status"] == "ENFORCEMENT"
    assert case["enforcement_posture"] == "ESCALATED"
    # Activation did not move the interstate dimension.
    assert case["interstate_role"] == "RESPONDING"

    referral = fx.read_interstate_referral(scenario.interstate_referral["id"])
    assert referral["status"] == "ENFORCING"

    obligor = fx.read_participant(scenario.ncp_id)
    assert obligor["credit_bureau_reported"] is True
    # Only the flag matching this remedy is set.
    assert obligor["license_suspension_active"] is False
    assert obligor["lien_recorded"] is False


# ---------------------------------------------------------------------------
# The bounded acknowledgment cycle
# ---------------------------------------------------------------------------


def test_03_rescinded_acknowledgment_can_be_re_executed_with_a_fresh_window():
    """
    The cycle closes back on `AOP_SIGNED` and re-derives its own deadline.

    A rescinded acknowledgment is not a dead end. The same acknowledgment operation re-executes from `AOP_RESCINDED` back to `AOP_SIGNED` — still requiring `notary_verified` to be true — and a completely fresh sixty-day window opens from the new `aop_signed_at`.

    Design: Difficulty/non_linear_state_machine/paternity_aop_rescission_cycle_returns_to_aop_signed
    """
    scenario = _signed_then_rescinded_then_signed_again()

    assert scenario.case["case_status"] == "OPENED"
    assert scenario.paternity_action["status"] == "PENDING"

    signed = fx.sign_acknowledgment(scenario.paternity_action["id"], scenario.ncp_id)
    assert signed["status"] == "AOP_SIGNED"
    a.assert_instant_equals(signed["aop_signed_at"], "2026-08-01T00:00:00Z", "aop_signed_at")
    # The sixty-day rescission window from the signature instant.
    a.assert_instant_equals(signed["rescission_deadline_at"], "2026-09-30T00:00:00Z", "rescission_deadline_at")

    rescinded = fx.rescind_acknowledgment(scenario.paternity_action["id"], scenario.ncp_id)
    assert rescinded["status"] == "AOP_RESCINDED"
    assert rescinded["rescission_count"] == 1
    assert rescinded.get("aop_signed_at") is None
    assert rescinded.get("rescission_deadline_at") is None

    resigned = fx.sign_acknowledgment(scenario.paternity_action["id"], scenario.ncp_id)
    assert resigned["status"] == "AOP_SIGNED"
    a.assert_instant_equals(resigned["aop_signed_at"], "2026-08-01T00:00:00Z", "aop_signed_at")
    # Re-derived from the new signature, not inherited from the first one.
    a.assert_instant_equals(resigned["rescission_deadline_at"], "2026-09-30T00:00:00Z", "rescission_deadline_at")
    # Re-signing does not reset the loop counter.
    assert resigned["rescission_count"] == 1


def test_04_second_rescission_is_refused_although_the_window_is_still_open():
    """
    The loop is bounded at one rescission per acknowledgment.

    And `rescission_count` must still be below one, because the statute permits exactly one rescission per acknowledgment; a second attempt is refused with `ERR_RESCISSION_LIMIT` (HTTP 409).

    Design: Difficulty/non_linear_state_machine/paternity_aop_rescission_cycle_returns_to_aop_signed
    """
    scenario = _signed_then_rescinded_then_signed_again()
    paternity_action_id = scenario.paternity_action["id"]

    fx.sign_acknowledgment(paternity_action_id, scenario.ncp_id)
    fx.rescind_acknowledgment(paternity_action_id, scenario.ncp_id)
    resigned = fx.sign_acknowledgment(paternity_action_id, scenario.ncp_id)
    # The clock has never moved, so the window is open on its own terms.
    a.assert_instant_equals(resigned["rescission_deadline_at"], "2026-09-30T00:00:00Z", "rescission_deadline_at")

    response = api_client.rescind_acknowledgment(
        paternity_action_id,
        f.rescission_payload(),
        make_noncustodial_party_headers(scenario.ncp_id),
    )
    validate_error(response, ApiErrorId.RESCISSION_LIMIT.value, 409)

    unchanged = fx.read_paternity_action(paternity_action_id)
    assert unchanged["status"] == "AOP_SIGNED"
    assert unchanged["rescission_count"] == 1


# ---------------------------------------------------------------------------
# The two withholding-order dimensions
# ---------------------------------------------------------------------------


def test_05_first_remittance_moves_the_remittance_dimension_and_allocates_a_payment():
    """
    The employer's money lands as a payment and starts the remittance dimension.

    The remittance creates a payment on the case with `source` `INCOME_WITHHOLDING` and its `iwo_id` set to this order, which is then allocated and split exactly as described in the ledger section below; both the withholding order's `version` and the case's `version` increase by 1.

    Design: Difficulty/non_linear_state_machine/iwo_service_and_remittance_dimensions_are_independent
    """
    scenario = _served_withholding_order_paid_once()
    payment = scenario.payments[0]

    assert payment["source"] == "INCOME_WITHHOLDING"
    assert payment["iwo_id"] == scenario.iwo_id
    # Bucket one: the only charge whose period contains 2026-08-15.
    assert payment["applied_current_cents"] == 82500
    assert payment["applied_medical_cents"] == 0
    # Bucket three: the oldest remaining open charge takes the rest.
    assert payment["applied_arrears_cents"] == 16500
    assert payment["applied_interest_cents"] == 0
    assert payment["unapplied_credit_cents"] == 0
    # A non-assistance case disburses current, medical and arrears to the family.
    assert payment["disbursed_to_cp_cents"] == 99000
    assert payment["retained_by_state_cents"] == 0

    iwo = fx.read_withholding_order(scenario.iwo_id)
    assert iwo["service_status"] == "SERVED"
    assert iwo["remittance_status"] == "CURRENT"
    assert iwo["missed_remittance_count"] == 0


def test_06_amendment_advances_the_service_dimension_and_leaves_the_remittance_dimension_alone():
    """
    One row, two dimensions, one of them untouched by this write.

    A transition on one dimension never implies a transition on another unless this document says it does — amending a withholding order, for instance, leaves `remittance_status` completely untouched.

    Design: Difficulty/non_linear_state_machine/iwo_service_and_remittance_dimensions_are_independent
    """
    scenario = _served_withholding_order_paid_once()

    assert scenario.withholding_order["service_status"] == "SERVED"
    a.assert_instant_equals(scenario.withholding_order["first_withholding_due_at"], "2026-08-15T00:00:00Z", "first_withholding_due_at")

    fx.set_clock("2027-02-01T00:00:00Z")
    amended = fx.amend_withholding_order(scenario.iwo_id, 140000)

    # The service dimension advanced.
    assert amended["service_status"] == "AMENDED"
    # The remittance dimension did not move.
    assert amended["remittance_status"] == "CURRENT"
    assert amended["missed_remittance_count"] == 0
    assert amended["reported_disposable_income_cents"] == 140000


def test_07_amendment_recomputes_the_ceiling_from_the_ledger_the_remittance_left_behind():
    """
    The recomputation reads the current arrears, not the arrears at issuance.

    It recomputes `ccpa_cap_pct`, `ccpa_cap_amount_cents`, `withholding_amount_cents` and `employer_fee_cents` through the same four movements, re-checks the aggregate ceiling, and increases the order's `version` by 1.

    Design: Difficulty/non_linear_state_machine/iwo_service_and_remittance_dimensions_are_independent
    """
    scenario = _served_withholding_order_paid_once()

    first_charge = fx.read_charge(scenario.charges[0]["id"])
    second_charge = fx.read_charge(scenario.charges[1]["id"])
    assert first_charge["status"] == "SATISFIED"
    assert first_charge["unpaid_balance_cents"] == 0
    assert second_charge["status"] == "OPEN"
    assert second_charge["unpaid_balance_cents"] == 66000

    fx.set_clock("2027-02-01T00:00:00Z")
    case = fx.read_case(scenario.case_id)
    assert case["arrears_principal_cents"] == 396000
    assert case["total_collected_principal_cents"] == 99000

    amended = fx.amend_withholding_order(scenario.iwo_id, 140000)

    # 396000 of arrears is at least three times the 82500 obligation.
    assert amended["federal_cap_pct"] == 0.65
    # An MN employer has no ceiling of its own and defers to the federal one.
    assert amended["ccpa_cap_pct"] == 0.65
    # floor(140000 * 0.65).
    assert amended["ccpa_cap_amount_cents"] == 91000
    assert amended["requested_amount_cents"] == 99000
    # min(99000, 91000 - 0) — the recomputed ceiling now binds.
    assert amended["withholding_amount_cents"] == 91000
    assert amended["employer_fee_cents"] == 0
