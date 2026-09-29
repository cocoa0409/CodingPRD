"""
Validation gates probed one clause at a time, at the exact value that decides them.

Each scenario drives a request to the boundary of a single rule — an instant equal
to the clock rather than after it, a counter at its ceiling rather than below it, a
status that outranks a stay — and then repeats the same request from one step away
so the refusal and the acceptance are read against each other.
"""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import (
    CASE_WORKER_HEADERS,
    INTERSTATE_LIAISON_HEADERS,
    FINANCE_OFFICER_HEADERS,
    SUPERVISING_ATTORNEY_HEADERS,
    make_employer_agent_headers,
)


# ---------------------------------------------------------------------------
# Shared scenario builders
# ---------------------------------------------------------------------------


def _paternity_action_awaiting_a_genetic_test_order() -> Dict[str, Any]:
    """
    A direct-application case at the opening clock whose `GENETIC_TEST` paternity
    action is still `PENDING`, so the appointment instant is the only variable.
    """
    scenario = fx.open_case_with_parties(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Halle Bergstrom",
            "ssn_last4": "6201",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Soren Bergstrom",
            "ssn_last4": "6202",
            "monthly_gross_income_cents": 300000,
            "supports_second_family": False,
            "has_valid_drivers_license": True,
        },
        case_type="DIRECT_APPLICATION",
        child_count=2,
        tanf_assistance=False,
        good_cause_claim=False,
    )
    return fx.open_paternity_action(scenario.case_id, "GENETIC_TEST")


# ---------------------------------------------------------------------------
# The appointment instant is strict going in and inclusive coming out
# ---------------------------------------------------------------------------


def test_01_the_appointment_must_be_after_the_clock_but_collection_may_be_at_it():
    """
    The same instant is too early to schedule and exactly late enough to collect.

    The genetic track is opened by a `SupervisingAttorney`, who supplies a `collection_appointment_at` instant that must be strictly later than the current logical clock; an appointment scheduled at or before the clock is refused with `ERR_COLLECTION_APPOINTMENT_NOT_REACHED` (HTTP 409).

    Specimen collection is recorded by a `CaseWorker` and may only happen once the clock has reached `collection_appointment_at` — at or after that instant; earlier is again `ERR_COLLECTION_APPOINTMENT_NOT_REACHED`.

    Design: Corner/validations/genetic_collection_window_and_rejection_ceiling
    """
    action = _paternity_action_awaiting_a_genetic_test_order()

    # An appointment at the clock value itself is not strictly later than it.
    response = api_client.order_genetic_test(
        action["id"],
        f.genetic_test_order_payload("2026-08-01T00:00:00Z"),
        SUPERVISING_ATTORNEY_HEADERS,
    )
    validate_error(response, ApiErrorId.COLLECTION_APPOINTMENT_NOT_REACHED.value, 409)

    ordered = fx.order_genetic_test(action["id"], "2026-08-10T00:00:00Z")
    assert ordered["status"] == "GENETIC_ORDERED"
    a.assert_instant_equals(
        ordered["collection_appointment_at"], "2026-08-10T00:00:00Z", "collection_appointment_at"
    )

    # Nine days early, so the collection clause refuses with the same error id.
    response = api_client.record_specimen_collection(
        action["id"], f.specimen_collection_payload(True), CASE_WORKER_HEADERS
    )
    validate_error(response, ApiErrorId.COLLECTION_APPOINTMENT_NOT_REACHED.value, 409)

    fx.set_clock("2026-08-10T00:00:00Z")
    collected = fx.collect_specimen(action["id"], chain_of_custody_ok=True)
    # The clock stands exactly on the appointment, and "at or after" admits it.
    assert collected["status"] == "GENETIC_COLLECTED"
    a.assert_instant_equals(
        collected["specimen_collected_at"], "2026-08-10T00:00:00Z", "specimen_collected_at"
    )


def test_02_the_ceiling_of_two_stops_the_third_rejection_and_nothing_else():
    """
    Two rejections are allowed, the third is refused, and a clean draw still lands.

    A rejected specimen may be re-drawn only while `specimen_rejection_count` is still below two; the third rejected specimen is refused with `ERR_SPECIMEN_REJECTION_LIMIT` (HTTP 409).

    A false value keeps the action in `GENETIC_ORDERED` as a self-transition, increases `specimen_rejection_count` by 1, records `chain_of_custody_ok` as false, and leaves `specimen_collected_at` absent.

    Design: Corner/validations/genetic_collection_window_and_rejection_ceiling
    """
    action = _paternity_action_awaiting_a_genetic_test_order()
    fx.order_genetic_test(action["id"], "2026-08-10T00:00:00Z")
    fx.set_clock("2026-08-10T00:00:00Z")

    first = fx.collect_specimen(action["id"], chain_of_custody_ok=False)
    assert first["status"] == "GENETIC_ORDERED"
    assert first["specimen_rejection_count"] == 1
    assert first["chain_of_custody_ok"] is False
    assert first.get("specimen_collected_at") is None

    second = fx.collect_specimen(action["id"], chain_of_custody_ok=False)
    assert second["status"] == "GENETIC_ORDERED"
    # The re-draw was legal because the count was still one, which is below two.
    assert second["specimen_rejection_count"] == 2

    response = api_client.record_specimen_collection(
        action["id"], f.specimen_collection_payload(False), CASE_WORKER_HEADERS
    )
    validate_error(response, ApiErrorId.SPECIMEN_REJECTION_LIMIT.value, 409)

    clean = fx.collect_specimen(action["id"], chain_of_custody_ok=True)
    # The ceiling guards the rejection self-loop only, never the clean transition.
    assert clean["status"] == "GENETIC_COLLECTED"
    assert clean["chain_of_custody_ok"] is True
    # The refused third rejection left the counter where the second one put it.
    assert clean["specimen_rejection_count"] == 2
    assert clean["version"] == second["version"] + 1


def _served_withholding_order_due_on_the_fifteenth() -> fx.Scenario:
    """
    An entered 75,000-cent order with one charge already payable, and a Minnesota
    withholding order served at the opening clock so its first remittance falls
    due at exactly 2026-08-15T00:00:00Z.

    The charge is due on the effective date, so the case already carries arrears
    principal and the withholding request carries the arrears add-on.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Ingrid Sollie",
            "ssn_last4": "6203",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Anders Sollie",
            "ssn_last4": "6204",
            "monthly_gross_income_cents": 300000,
            "supports_second_family": False,
            "has_valid_drivers_license": True,
        },
        case_overrides={"child_count": 2, "tanf_assistance": False, "good_cause_claim": False},
        order_overrides={
            "origin_state_code": "MN",
            "effective_date": "2026-08-01",
            "medical_support_monthly_cents": 0,
        },
    )
    scenario.charges = [
        fx.post_charge(
            scenario.order_id,
            charge_type="CURRENT_SUPPORT",
            period_start_date="2026-08-01",
            period_end_date="2026-09-01",
            due_date="2026-08-01",
        )
    ]
    scenario.employer = fx.create_employer(
        state_code="MN", legal_name="Sollie Freight", remittance_fee_cents=0
    )
    issued = fx.issue_withholding_order(
        scenario.order_id, scenario.employer_id, reported_disposable_income_cents=155000
    )
    scenario.withholding_order = fx.serve_withholding_order(issued["id"])
    return scenario


# ---------------------------------------------------------------------------
# The lapse gate is strict, and default then refuses real money
# ---------------------------------------------------------------------------


def test_03_a_lapse_at_the_due_instant_is_early_and_one_second_later_is_not():
    """
    The same lapse call is refused at 2026-08-15 and accepted one second after it.

    Declaring a lapse requires that the current logical clock is strictly past `next_remittance_due_at`; at or before it, the answer is `ERR_REMITTANCE_NOT_YET_DUE` (HTTP 409).

    A lapse increases `missed_remittance_count` by 1 and drives `remittance_status` `NOT_DUE → DELINQUENT` or `CURRENT → DELINQUENT`.

    Design: Corner/validations/lapse_before_due_then_default_locks_out_remittances
    """
    scenario = _served_withholding_order_due_on_the_fifteenth()
    iwo = scenario.withholding_order

    assert scenario.order["monthly_obligation_cents"] == 75000
    # round_half_up(75000 * 0.20) rides along because the charge is already due.
    assert iwo["arrears_recovery_cents"] == 15000
    # 90000 requested against floor(155000 * 0.60) = 93000 of cap room.
    assert iwo["withholding_amount_cents"] == 90000
    a.assert_instant_equals(iwo["served_at"], "2026-08-01T00:00:00Z", "served_at")
    a.assert_instant_equals(
        iwo["next_remittance_due_at"], "2026-08-15T00:00:00Z", "next_remittance_due_at"
    )
    # Service starts the withholding clock, not the remittance clock.
    assert iwo["remittance_status"] == "NOT_DUE"
    assert iwo["missed_remittance_count"] == 0

    fx.set_clock("2026-08-15T00:00:00Z")
    response = api_client.declare_remittance_lapse(
        iwo["id"], f.lapse_payload(), FINANCE_OFFICER_HEADERS
    )
    validate_error(response, ApiErrorId.REMITTANCE_NOT_YET_DUE.value, 409)
    assert fx.read_withholding_order(iwo["id"])["missed_remittance_count"] == 0

    fx.set_clock("2026-08-15T00:00:01Z")
    lapsed = fx.declare_lapse(iwo["id"])
    assert lapsed["remittance_status"] == "DELINQUENT"
    assert lapsed["missed_remittance_count"] == 1


def test_04_a_defaulted_remittance_dimension_refuses_the_money_the_employer_sends():
    """
    A second lapse defaults the order, and a genuine 90,000-cent remittance bounces.

    From `DELINQUENT`, a further lapse drives `DELINQUENT → DEFAULTED` once the incremented `missed_remittance_count` reaches two — two missed cycles is employer default.

    A remittance against an order whose `remittance_status` is already `DEFAULTED` is refused with `ERR_IWO_DEFAULTED` (HTTP 409).

    `DEFAULTED` is terminal on the remittance dimension.

    Design: Corner/validations/lapse_before_due_then_default_locks_out_remittances
    """
    scenario = _served_withholding_order_due_on_the_fifteenth()
    iwo_id = scenario.withholding_order["id"]

    fx.set_clock("2026-08-15T00:00:01Z")
    fx.declare_lapse(iwo_id)
    defaulted = fx.declare_lapse(iwo_id)
    assert defaulted["remittance_status"] == "DEFAULTED"
    assert defaulted["missed_remittance_count"] == 2

    response = api_client.post_remittance(
        iwo_id,
        f.remittance_payload(90000),
        make_employer_agent_headers(scenario.employer_id),
    )
    validate_error(response, ApiErrorId.IWO_DEFAULTED.value, 409)

    payments, meta = validate_paginated(
        api_client.list_payments(FINANCE_OFFICER_HEADERS, {"iwo_id": iwo_id})
    )
    # The refused remittance created no payment at all.
    assert payments == []
    assert meta["total_count"] == 0

    final = fx.read_withholding_order(iwo_id)
    assert final["remittance_status"] == "DEFAULTED"
    assert final["missed_remittance_count"] == 2
    # Nothing was applied, so the charge still stands unpaid in full.
    assert fx.read_case(scenario.case_id)["arrears_principal_cents"] == 75000


def _one_obligor_between_a_minnesota_and_a_wisconsin_payroll() -> Tuple[
    fx.Scenario, Dict[str, Any]
]:
    """
    An entered 75,000-cent order with one charge already payable, and two
    employers of the same obligor: a Minnesota one that defers to the federal
    ceiling and a Wisconsin one that carries its own fifty percent ceiling.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Fatima Larkspur",
            "ssn_last4": "6205",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Yusuf Larkspur",
            "ssn_last4": "6206",
            "monthly_gross_income_cents": 300000,
            "supports_second_family": False,
            "has_valid_drivers_license": True,
        },
        case_overrides={"child_count": 2, "tanf_assistance": False, "good_cause_claim": False},
        order_overrides={
            "origin_state_code": "MN",
            "effective_date": "2026-08-01",
            "medical_support_monthly_cents": 0,
        },
    )
    scenario.charges = [
        fx.post_charge(
            scenario.order_id,
            charge_type="CURRENT_SUPPORT",
            period_start_date="2026-08-01",
            period_end_date="2026-09-01",
            due_date="2026-08-01",
        )
    ]
    scenario.employer = fx.create_employer(
        state_code="MN", legal_name="Larkspur Grain MN", remittance_fee_cents=0
    )
    wisconsin_employer = fx.create_employer(
        state_code="WI", legal_name="Larkspur Grain WI", remittance_fee_cents=0
    )
    return scenario, wisconsin_employer


# ---------------------------------------------------------------------------
# The aggregate ceiling re-reads the whole collection at its lowest percentage
# ---------------------------------------------------------------------------


def test_05_two_orders_each_inside_its_own_cap_still_breach_the_aggregate_one():
    """
    Ninety thousand plus fifty thousand exceeds the 125,000 the strictest cap allows.

    Two of the seven recognised states place their own ceiling on wage withholding: an employer whose principal place of business is in `TX` or in `WI` carries a `statutory_cap_pct` of 0.50, a fifty percent ceiling.

    The summed `withholding_amount_cents` across those orders must not exceed that aggregate ceiling, or the request is refused with `ERR_AGGREGATE_WITHHOLDING_EXCEEDS_CAP` (HTTP 409).

    Every individual order can fit inside its own employer's state ceiling while the collection collectively breaches the strictest one, and this check is what catches that.

    Design: Corner/validations/aggregate_withholding_cap_binds_at_the_lowest_state_percentage
    """
    scenario, wisconsin_employer = _one_obligor_between_a_minnesota_and_a_wisconsin_payroll()

    assert scenario.order["monthly_obligation_cents"] == 75000
    assert scenario.employer.get("statutory_cap_pct") is None
    assert wisconsin_employer["statutory_cap_pct"] == 0.50

    minnesota = fx.issue_withholding_order(
        scenario.order_id, scenario.employer_id, reported_disposable_income_cents=150000
    )
    # 75000 + 0 + round_half_up(75000 * 0.20) requested, against floor(150000 * 0.60).
    assert minnesota["ccpa_cap_pct"] == 0.60
    assert minnesota["ccpa_cap_amount_cents"] == 90000
    # Exactly at its own cap, and the aggregate comparison is not a strict one.
    assert minnesota["withholding_amount_cents"] == 90000

    response = api_client.issue_withholding_order(
        scenario.order_id,
        f.withholding_order_payload(
            wisconsin_employer["id"],
            fx.read_order(scenario.order_id)["version"],
            reported_disposable_income_cents=100000,
        ),
        CASE_WORKER_HEADERS,
    )
    validate_error(response, ApiErrorId.AGGREGATE_WITHHOLDING_EXCEEDS_CAP.value, 409)


def test_06_terminating_the_minnesota_order_lets_the_identical_request_through():
    """
    The same Wisconsin payload passes once the summed collection is 50,000 of 50,000.

    One further ceiling operates across withholding orders rather than within one.

    Because an obligor may be withheld at two employers, the collection as a whole is checked against the most restrictive percentage in play: over all of the obligor's withholding orders whose `service_status` is not `TERMINATED`, the one being written included, the total reported disposable income is summed, the smallest `ccpa_cap_pct` among them is taken as the binding percentage, and the aggregate ceiling is that summed disposable income multiplied by the binding percentage, floored to whole cents.

    Design: Corner/validations/aggregate_withholding_cap_binds_at_the_lowest_state_percentage
    """
    scenario, wisconsin_employer = _one_obligor_between_a_minnesota_and_a_wisconsin_payroll()
    minnesota = fx.issue_withholding_order(
        scenario.order_id, scenario.employer_id, reported_disposable_income_cents=150000
    )

    terminated = fx.terminate_withholding_order(minnesota["id"], "SUPERSEDED_BY_NEW_IWO")
    assert terminated["service_status"] == "TERMINATED"

    wisconsin = fx.issue_withholding_order(
        scenario.order_id,
        wisconsin_employer["id"],
        reported_disposable_income_cents=100000,
    )
    assert wisconsin["jurisdiction_state_code"] == "WI"
    # min(federal 0.60, the Wisconsin ceiling 0.50).
    assert wisconsin["ccpa_cap_pct"] == 0.50
    assert wisconsin["ccpa_cap_amount_cents"] == 50000
    # The sum over non-terminated orders is now 50000 against a ceiling of 50000.
    assert wisconsin["withholding_amount_cents"] == 50000

    rows, meta = validate_paginated(
        api_client.list_withholding_orders(
            CASE_WORKER_HEADERS, {"order_id": scenario.order_id}
        )
    )
    # The terminated row survives as history; the refused attempt persisted nothing.
    assert meta["total_count"] == 2
    assert sorted(row["id"] for row in rows) == sorted([minnesota["id"], wisconsin["id"]])


def _case_certified_at_thirty_thousand_one_hundred_fifty(
    tanf_assistance: bool, ssn_cp: str, ssn_ncp: str
) -> fx.Scenario:
    """
    A minimum-order case carrying one 30,000-cent arrears judgment due
    2026-08-15, read at 2026-09-20 so exactly one whole month of statutory
    interest has been earned on it.

    The obligor earns the self-support reserve to the cent, so the monthly
    obligation floors at the statutory minimum and the two-month delinquency
    gate is only 10,000 cents.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Perla Nystrom",
            "ssn_last4": ssn_cp,
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Dmitri Nystrom",
            "ssn_last4": ssn_ncp,
            "monthly_gross_income_cents": 113200,
            "supports_second_family": False,
            "has_valid_drivers_license": True,
        },
        case_overrides={
            "case_type": "PA_REFERRAL" if tanf_assistance else "DIRECT_APPLICATION",
            "child_count": 2,
            "tanf_assistance": tanf_assistance,
            "good_cause_claim": False,
        },
        order_overrides={
            "origin_state_code": "MN",
            "effective_date": "2026-08-01",
            "medical_support_monthly_cents": 0,
        },
    )
    scenario.charges = [
        fx.post_charge(
            scenario.order_id,
            charge_type="ARREARS_JUDGMENT",
            period_start_date="2026-08-01",
            period_end_date="2026-09-01",
            due_date="2026-08-15",
            amount_cents=30000,
        )
    ]
    fx.set_clock("2026-09-20T00:00:00Z")
    return scenario


# ---------------------------------------------------------------------------
# One threshold row is conditional on the case, and the other gate is not
# ---------------------------------------------------------------------------


def test_07_the_same_certified_balance_clears_the_assigned_row_and_fails_the_other():
    """
    30,150 cents is enough on a TANF case and not enough without the assignment.

    `TAX_REFUND_INTERCEPT` is the one conditional row: its threshold is 15,000 cents on a case carrying `tanf_assistance`, because assigned arrears are owed to the state and the state intercepts aggressively, and 50,000 cents on a case that does not.

    `arrears_certified_snapshot_cents` is the case's `arrears_principal_cents` plus the **statutory per-charge** interest measure valued at the current logical clock date — certification always uses the statutory measure, never the ledger's aggregate measure, which is precisely why a certified balance can differ from the balance the ledger read shows for the same case at the same instant.

    Design: Corner/validations/tax_intercept_threshold_depends_on_whether_arrears_are_assigned
    """
    assigned = _case_certified_at_thirty_thousand_one_hundred_fifty(True, "6207", "6208")
    assert assigned.order["monthly_obligation_cents"] == 5000

    action = fx.propose_enforcement_action(assigned.case_id, "TAX_REFUND_INTERCEPT")
    # 30000 of principal plus round_half_up(30000 * 0.005 * 1) of statutory interest.
    assert action["arrears_certified_snapshot_cents"] == 30150
    assert action["eligibility_threshold_cents"] == 15000
    assert action["status"] == "PROPOSED"

    unassigned = _case_certified_at_thirty_thousand_one_hundred_fifty(False, "6209", "6210")
    assert unassigned.order["monthly_obligation_cents"] == 5000
    assert fx.read_case(unassigned.case_id)["arrears_principal_cents"] == 30000

    response = api_client.propose_enforcement_action(
        unassigned.case_id,
        f.enforcement_action_payload("TAX_REFUND_INTERCEPT"),
        CASE_WORKER_HEADERS,
    )
    validate_error(response, ApiErrorId.ARREARS_BELOW_ENFORCEMENT_THRESHOLD.value, 409)

    rows, meta = validate_paginated(
        api_client.list_enforcement_actions(
            CASE_WORKER_HEADERS, {"case_id": unassigned.case_id}
        )
    )
    # The refused proposal persisted nothing on the non-assigned case.
    assert rows == []
    assert meta["total_count"] == 0


def test_08_the_conditional_row_does_not_lower_any_other_remedy_s_threshold():
    """
    The same TANF case that clears 15,000 is still far below the 300,000 one.

    `eligibility_threshold_cents` is the threshold the remedy had to clear, and it is fixed per remedy: 300,000 cents for `LICENSE_SUSPENSION`, 500,000 cents for `PROPERTY_LIEN`, 1,000,000 cents for `CONTEMPT_REFERRAL`, and 100,000 cents for `CREDIT_BUREAU_REPORT`.

    Both gates compare with "at least", so a certified balance exactly equal to a threshold *is* eligible.

    Design: Corner/validations/tax_intercept_threshold_depends_on_whether_arrears_are_assigned
    """
    assigned = _case_certified_at_thirty_thousand_one_hundred_fifty(True, "6207", "6208")
    intercept = fx.propose_enforcement_action(assigned.case_id, "TAX_REFUND_INTERCEPT")
    assert intercept["eligibility_threshold_cents"] == 15000

    response = api_client.propose_enforcement_action(
        assigned.case_id,
        f.enforcement_action_payload("LICENSE_SUSPENSION"),
        CASE_WORKER_HEADERS,
    )
    validate_error(response, ApiErrorId.ARREARS_BELOW_ENFORCEMENT_THRESHOLD.value, 409)

    rows, meta = validate_paginated(
        api_client.list_enforcement_actions(
            CASE_WORKER_HEADERS, {"case_id": assigned.case_id}
        )
    )
    # Only the remedy whose conditional threshold the balance cleared exists.
    assert meta["total_count"] == 1
    assert rows[0]["action_type"] == "TAX_REFUND_INTERCEPT"


def _unlocated_case(good_cause_claim: bool, ssn_cp: str, ssn_ncp: str) -> fx.Scenario:
    """
    An open direct-application case whose obligor has never been through locate
    services, so the participant row still reads `NOT_NEEDED`.
    """
    return fx.open_case_with_parties(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Wilhelmina Northcutt",
            "ssn_last4": ssn_cp,
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Casper Northcutt",
            "ssn_last4": ssn_ncp,
            "monthly_gross_income_cents": 300000,
            "supports_second_family": False,
            "has_valid_drivers_license": True,
        },
        locate_outcome=None,
        case_type="DIRECT_APPLICATION",
        child_count=2,
        tanf_assistance=False,
        good_cause_claim=good_cause_claim,
    )


# ---------------------------------------------------------------------------
# Two flags on other rows decide whether these writes are allowed
# ---------------------------------------------------------------------------


def test_09_good_cause_bars_the_two_disclosures_and_waives_the_locate_step():
    """
    The flag that blocks the referral and the transmittal is the flag that
    lets paternity work start with an obligor nobody has found.

    Three operations disclose: referring the obligor to locate services, sending a pre-deprivation enforcement notice, and transmitting an interstate request.

    On a case whose `good_cause_claim` is true, locate is barred outright, so paternity work may begin directly from `OPENED` without the case ever passing through `LOCATE`.

    Design: Corner/validations/good_cause_and_locate_status_gate_writes_on_other_entities
    """
    scenario = _unlocated_case(True, "6211", "6212")
    assert scenario.case["good_cause_claim"] is True
    assert scenario.noncustodial_party["locate_status"] == "NOT_NEEDED"

    response = api_client.create_locate_referral(
        scenario.case_id,
        f.locate_referral_payload("STATE_DIRECTORY_OF_NEW_HIRES"),
        CASE_WORKER_HEADERS,
    )
    validate_error(response, ApiErrorId.GOOD_CAUSE_BARS_DISCLOSURE.value, 409)

    # Drafting the transmittal discloses nothing, so the draft itself is allowed.
    referral = fx.draft_interstate_referral(scenario.case_id, other_state_code="TX")
    assert referral["status"] == "DRAFT"

    # Transmittal also requires an `ENTERED` order to transmit, so the good-cause
    # refusal is read on a good-cause case that already carries one — otherwise the
    # missing order, not the confidentiality claim, would be what fails.
    transmittable = fx.case_with_entered_order(
        clock=None,
        cp_overrides={
            "full_name": "Marisol Aguirre",
            "ssn_last4": "6215",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Teodoro Aguirre",
            "ssn_last4": "6216",
            "monthly_gross_income_cents": 300000,
        },
        case_overrides={
            "case_type": "DIRECT_APPLICATION",
            "child_count": 2,
            "tanf_assistance": False,
            "good_cause_claim": True,
        },
    )
    assert transmittable.case["good_cause_claim"] is True
    guarded_referral = fx.draft_interstate_referral(
        transmittable.case_id, other_state_code="TX"
    )
    response = api_client.transmit_referral(
        guarded_referral["id"], f.transmittal_payload(), INTERSTATE_LIAISON_HEADERS
    )
    validate_error(response, ApiErrorId.GOOD_CAUSE_BARS_DISCLOSURE.value, 409)

    action = fx.open_paternity_action(scenario.case_id, "VOLUNTARY_ACKNOWLEDGMENT")
    assert action["status"] == "PENDING"
    case = fx.read_case(scenario.case_id)
    assert case["case_status"] == "PATERNITY_PENDING"
    assert case["locate_referral_count"] == 0


def test_10_without_good_cause_the_paternity_action_waits_for_a_located_obligor():
    """
    The identical request is refused at `NOT_NEEDED`, refused again at `PENDING`,
    and accepted only once the participant row reads `LOCATED`.

    Outside that bypass, an obligor who is not `LOCATED` blocks both the opening of a paternity action and the drafting of a support order with `ERR_NCP_NOT_LOCATED` (HTTP 409), and an obligor whose `locate_status` is `UNLOCATABLE` blocks every establishment step regardless of the good-cause flag.

    Each referral increases the case's `locate_referral_count` by 1 and the case's `version` by 1, sets the obligor's `locate_status` to `PENDING` and increases the obligor's `locate_attempt_count` by 1.

    Design: Corner/validations/good_cause_and_locate_status_gate_writes_on_other_entities
    """
    scenario = _unlocated_case(False, "6213", "6214")
    payload = f.paternity_action_payload("VOLUNTARY_ACKNOWLEDGMENT")

    response = api_client.create_paternity_action(
        scenario.case_id, payload, CASE_WORKER_HEADERS
    )
    validate_error(response, ApiErrorId.NCP_NOT_LOCATED.value, 409)

    referred = fx.refer_to_locate(scenario.case_id, "STATE_DIRECTORY_OF_NEW_HIRES")
    assert referred["case_status"] == "LOCATE"
    assert referred["locate_referral_count"] == 1
    assert fx.read_participant(scenario.ncp_id)["locate_status"] == "PENDING"

    # A referral in flight is not an obligor who has been found.
    response = api_client.create_paternity_action(
        scenario.case_id, payload, CASE_WORKER_HEADERS
    )
    validate_error(response, ApiErrorId.NCP_NOT_LOCATED.value, 409)

    located = fx.record_locate_outcome(
        scenario.ncp_id, "LOCATED", employer_name="Northcutt Welding"
    )
    assert located["locate_status"] == "LOCATED"

    action = fx.open_paternity_action(scenario.case_id, "VOLUNTARY_ACKNOWLEDGMENT")
    assert action["status"] == "PENDING"
    # This case reached paternity work through LOCATE rather than around it.
    assert fx.read_case(scenario.case_id)["case_status"] == "PATERNITY_PENDING"


def _entered_order_open_to_review(ssn_cp: str, ssn_ncp: str) -> fx.Scenario:
    """
    An entered 75,000-cent order effective 2026-08-01, so its statutory review
    date falls three years out and any review opened now must be exempt from it.
    """
    return fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Rosalind Thibault",
            "ssn_last4": ssn_cp,
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Emeric Thibault",
            "ssn_last4": ssn_ncp,
            "monthly_gross_income_cents": 300000,
            "supports_second_family": False,
            "has_valid_drivers_license": True,
        },
        case_overrides={"child_count": 2, "tanf_assistance": False, "good_cause_claim": False},
        order_overrides={
            "origin_state_code": "MN",
            "effective_date": "2026-08-01",
            "medical_support_monthly_cents": 0,
        },
    )


# ---------------------------------------------------------------------------
# Four review gates, each reachable only because the previous one passed
# ---------------------------------------------------------------------------


def test_11_the_periodic_cycle_waits_three_years_and_a_party_request_does_not():
    """
    The statutory review is too early on the same order a party may ask about today.

    A `PERIODIC_36_MONTH` review may not be created before `review_eligible_date`, and an early attempt answers with `ERR_REVIEW_NOT_YET_ELIGIBLE` (HTTP 409).

    `PARTY_REQUEST` and `PA_MANDATORY` reviews are exempt from that date entirely — a party may ask at any time, and the program may compel a review at any time.

    Design: Corner/validations/modification_review_gates_unlock_in_sequence
    """
    scenario = _entered_order_open_to_review("6215", "6216")
    assert scenario.order["monthly_obligation_cents"] == 75000
    assert scenario.order["review_eligible_date"] == "2029-08-01"

    response = api_client.create_modification_review(
        scenario.order_id,
        f.modification_review_payload("PERIODIC_36_MONTH"),
        CASE_WORKER_HEADERS,
    )
    validate_error(response, ApiErrorId.REVIEW_NOT_YET_ELIGIBLE.value, 409)

    review = fx.open_modification_review(scenario.order_id, "PARTY_REQUEST")
    assert review["status"] == "REQUESTED"
    # The snapshot, not the live order, is the denominator of the variance test.
    assert review["current_obligation_snapshot_cents"] == 75000
    assert review["review_eligible_date"] == "2029-08-01"
    assert review["info_request_count"] == 0


def test_12_the_information_cycle_runs_twice_and_the_third_request_strands_it():
    """
    Three screenings leave the count at three, and the fourth submission is refused.

    The cycle may run twice: an information submission is permitted while `info_request_count` is at most two, and a third information request on the same review is refused with `ERR_INFO_REQUEST_LIMIT` (HTTP 409).

    The variance test requires both parties' incomes to be verified, so if either party's `income_verification_source` is anything other than `VERIFIED_WAGE_RECORD`, screening drives `REQUESTED → INFO_PENDING` instead of computing anything: `info_request_count` increases by 1 and `info_requested_reason` is set.

    Design: Corner/validations/modification_review_gates_unlock_in_sequence
    """
    scenario = _entered_order_open_to_review("6215", "6216")
    fx.patch_income(scenario.cp_id, 250000, "SELF_REPORTED")
    review = fx.open_modification_review(scenario.order_id, "PARTY_REQUEST")

    bounced = fx.screen_modification_review(review["id"])
    assert bounced["status"] == "INFO_PENDING"
    assert bounced["info_request_count"] == 1
    # The obligor is verified, so the custodial party is the one reported.
    assert bounced["info_requested_reason"] == "CP_INCOME_UNVERIFIED"
    assert bounced.get("recalculated_guideline_cents") is None

    for expected_count in (2, 3):
        supplied = fx.supply_review_information(
            review["id"], scenario.cp_id, 250000, "SELF_REPORTED"
        )
        assert supplied["status"] == "REQUESTED"
        assert supplied["info_request_count"] == expected_count - 1
        again = fx.screen_modification_review(review["id"])
        assert again["status"] == "INFO_PENDING"
        assert again["info_request_count"] == expected_count

    response = api_client.supply_review_information(
        review["id"],
        f.review_information_payload(scenario.cp_id, 250000, "VERIFIED_WAGE_RECORD"),
        CASE_WORKER_HEADERS,
    )
    # Even a payload that finally carries verified income cannot reopen the cycle.
    validate_error(response, ApiErrorId.INFO_REQUEST_LIMIT.value, 409)

    response = api_client.create_proposed_order(
        review["id"], f.proposed_order_payload("2026-09-01"), SUPERVISING_ATTORNEY_HEADERS
    )
    validate_error(response, ApiErrorId.INVALID_REVIEW_STATUS.value, 409)
    assert fx.read_modification_review(review["id"])["status"] == "INFO_PENDING"


def test_13_the_successor_date_must_be_strictly_later_and_closes_the_review():
    """
    An equal effective date is refused, the next month is accepted, and the review
    then takes no further screening.

    The supplied `effective_date` must be **strictly later** than the reviewed order's `effective_date`; an equal or earlier date is refused with `ERR_MODIFICATION_EFFECTIVE_DATE_NOT_LATER` (HTTP 422), because a successor that takes effect on or before its predecessor would leave the obligation ambiguous for a period.

    At the first level a successor support order is created directly in `CALCULATED` — not `DRAFT` — with its `guideline_monthly_cents` set to the review's `recalculated_guideline_cents`; it is returned by no dedicated read of its own and is discoverable only through the order list filtered by case.

    Design: Corner/validations/modification_review_gates_unlock_in_sequence
    """
    scenario = _entered_order_open_to_review("6217", "6218")
    fx.patch_income(scenario.cp_id, 250000, "VERIFIED_WAGE_RECORD")
    fx.patch_income(scenario.ncp_id, 500000, "VERIFIED_WAGE_RECORD")
    review = fx.open_modification_review(scenario.order_id, "PARTY_REQUEST")

    screened = fx.screen_modification_review(review["id"])
    assert screened["status"] == "THRESHOLD_MET"
    # Combined 750000 at the second band's 0.25, shared at 0.6667.
    assert screened["recalculated_guideline_cents"] == 125006
    assert screened["variance_numerator_cents"] == 50006
    # 50006 * 10000 clears 1500 * 75000, and 50006 clears the 5000 floor.
    assert screened["substantial_change_met"] is True

    response = api_client.create_proposed_order(
        review["id"], f.proposed_order_payload("2026-08-01"), SUPERVISING_ATTORNEY_HEADERS
    )
    validate_error(response, ApiErrorId.MODIFICATION_EFFECTIVE_DATE_NOT_LATER.value, 422)

    proposed = fx.propose_successor_order(review["id"], "2026-09-01")
    assert proposed["status"] == "ORDER_PROPOSED"
    successor_id = proposed["proposed_order_id"]

    orders, _meta = validate_paginated(
        api_client.list_orders(CASE_WORKER_HEADERS, {"case_id": scenario.case_id})
    )
    successors = [order for order in orders if order["id"] == successor_id]
    assert len(successors) == 1
    successor = successors[0]
    assert successor["status"] == "CALCULATED"
    assert successor["guideline_monthly_cents"] == 125006
    assert successor["effective_date"] == "2026-09-01"
    # The predecessor waits for the successor's entry before it is superseded.
    assert fx.read_order(scenario.order_id)["status"] == "ENTERED"

    response = api_client.screen_modification_review(
        review["id"], f.screening_payload(), CASE_WORKER_HEADERS
    )
    validate_error(response, ApiErrorId.INVALID_REVIEW_STATUS.value, 409)
