"""Overpayment recovery: the FULL/PROPORTIONAL withholding variants, case
closure, WITHHELD_FULL payments, and the PARTIAL rate floor."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_claim,
    create_overpayment_case,
    create_worker_with_awi_record,
    file_claim,
    get_claim,
    get_overpayment_case,
    make_claimant_headers,
    payment_for_month,
    run_batch_at,
    set_clock,
    setup_entitled_retirement,
    validate_error,
    validate_success,
)

CS = TEST_USERS["claims_specialist_headers"]


def _setup_claim_with_two_cases(api, mode_a, mode_b):
    """Worker with three AWI years 2021-2023, RETIREMENT entitled 2031-06 at FRA
    (monthly 12,510), carrying case A 30,000 (created first) and case B 20,000,
    both put into recovery under the given modes after the waiver window."""
    worker = create_worker_with_awi_record(2021, 2023)
    claim = file_claim(worker["id"], "RETIREMENT", "2031-06")
    set_clock("2031-06-10T00:00:00Z")
    entitled = approve_claim(claim["id"])
    assert entitled["monthly_benefit_cents"] == 12_510

    case_a = create_overpayment_case(entitled["id"], 30_000, "2031-06", "2031-06",
                                     reason="REPORTING_ERROR")
    case_b = create_overpayment_case(entitled["id"], 20_000, "2031-06", "2031-06",
                                     reason="SYSTEM_ERROR")
    set_clock("2031-07-15T00:00:00Z")
    validate_success(api.begin_recovery(case_a["id"], mode_a, CS))
    validate_success(api.begin_recovery(case_b["id"], mode_b, CS))
    return worker, entitled, case_a, case_b


class TestWithholdingVariants:
    def test_full_mode_drains_oldest_case_first(self, api):
        """PRD §3.8: "In `FULL` or `PARTIAL` mode the cases are processed
        chronologically, oldest first: `FULL` withholds the lesser of the case's
        `remaining_cents` and the capacity left; `PARTIAL` withholds the lesser
        of the case's elected `monthly_rate_cents`, its `remaining_cents`, and
        the capacity left; each withholding shrinks the remaining capacity."

        Capacity 12,510 against case A 30,000 then case B 20,000: A takes the
        full 12,510, B takes nothing; the payment's net is 0 with positive
        withholding.

        Design: Difficulty/dual_variant_calc/chronological_vs_proportional_withholding
        """
        worker, entitled, case_a, case_b = _setup_claim_with_two_cases(api, "FULL", "FULL")

        run_batch_at("2031-08-01T00:00:00Z", "2031-08")

        payment = payment_for_month(entitled["id"], "2031-08")
        assert payment["gross_cents"] == 12_510
        assert payment["withheld_cents"] == 12_510
        assert payment["net_paid_cents"] == 0
        assert payment["status"] == "WITHHELD_FULL"

        a = get_overpayment_case(case_a["id"], entitled["id"])
        b = get_overpayment_case(case_b["id"], entitled["id"])
        assert a["recovered_cents"] == 12_510
        assert b["recovered_cents"] == 0

    def test_proportional_mode_splits_pro_rata_with_dime_residual(self, api):
        """PRD §3.8: "In `PROPORTIONAL` mode with active cases, the month's
        capacity is split pro-rata to remaining balances: each case is withheld
        the lesser of its own `remaining_cents` and the dime floor of the
        capacity multiplied by that case's share of the total remaining balance;
        any residual dimes left unallocated while debts remain go one dime at a
        time to cases in `created_at` ascending order, always respecting each
        case's remaining balance."

        Identical debts and capacity as the FULL leg: A dime_floor(12,510 *
        30,000/50,000) = 7,500 plus the 10-cent residual as earliest created_at
        = 7,510; B dime_floor(12,510 * 20,000/50,000) = 5,000.

        Design: Difficulty/dual_variant_calc/chronological_vs_proportional_withholding
        """
        worker, entitled, case_a, case_b = _setup_claim_with_two_cases(
            api, "PROPORTIONAL", "PROPORTIONAL"
        )

        run_batch_at("2031-08-01T00:00:00Z", "2031-08")

        payment = payment_for_month(entitled["id"], "2031-08")
        assert payment["withheld_cents"] == 12_510
        assert payment["net_paid_cents"] == 0

        a = get_overpayment_case(case_a["id"], entitled["id"])
        b = get_overpayment_case(case_b["id"], entitled["id"])
        assert a["recovered_cents"] == 7_510
        assert b["recovered_cents"] == 5_000


class TestCaseClosureAndPaymentStatus:
    def test_overpayment_fully_withheld_then_recovered_terminal(self, api):
        """PRD §3.8: "When a case's `recovered_cents` reaches its `amount_cents`,
        the case closes — `RECOVERY_ACTIVE → RECOVERED` — during that batch.
        `WAIVED` and `RECOVERED` are terminal."
        PRD §2.9: "**State-machine legality**: the target entity is in a
        from-state of the invoked transition, and terminal entities reject all
        further actions — otherwise `ERR_INVALID_STATE` (409), or
        `ERR_CLAIM_ALREADY_TERMINAL` (409) when the target claim is
        `WITHDRAWN` or `TERMINATED`."

        A 5,000-cent case against a 12,510 monthly benefit recovers fully in one
        cycle; a later waiver request is a state error (the terminal-state layer
        precedes OCC).

        Design: Corner/state_machines/overpayment_fully_withheld_then_recovered_terminal
        """
        worker = create_worker_with_awi_record(2021, 2023, full_name="Recovered Worker")
        claim = file_claim(worker["id"], "RETIREMENT", "2031-06")
        set_clock("2031-06-10T00:00:00Z")
        entitled = approve_claim(claim["id"])
        case = create_overpayment_case(entitled["id"], 5_000, "2031-06", "2031-06",
                                       reason="SYSTEM_ERROR")
        set_clock("2031-07-15T00:00:00Z")
        validate_success(api.begin_recovery(case["id"], "FULL", CS))

        run_batch_at("2031-08-01T00:00:00Z", "2031-08")

        payment = payment_for_month(entitled["id"], "2031-08")
        assert payment["withheld_cents"] == 5_000
        assert payment["net_paid_cents"] == 7_510

        closed = get_overpayment_case(case["id"], entitled["id"])
        assert closed["recovered_cents"] == 5_000
        assert closed["remaining_cents"] == 0
        assert closed["status"] == "RECOVERED"

        resp = api.request_waiver(case["id"], case["version"], "too late",
                                  make_claimant_headers(worker["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_payment_withheld_full_status_when_recovery_consumes_gross(self, api):
        """PRD §3.7: "The payment's status is `WITHHELD_FULL` when withholding
        consumed the entire gross — net zero with positive withholding — and
        `PAID` otherwise. Routing is recorded in `paid_to`:
        `REPRESENTATIVE_PAYEE` while the claim has an `ACTIVE` payee case,
        `BENEFICIARY` otherwise."

        A 20,000-cent case in FULL recovery against an 8,750 monthly benefit
        consumes the whole gross.

        Design: Corner/state_machines/payment_withheld_full_status_when_recovery_consumes_gross
        """
        worker, entitled = setup_entitled_retirement(2021, 2023, "2026-06")
        assert entitled["monthly_benefit_cents"] == 8_750
        case = create_overpayment_case(entitled["id"], 20_000, "2026-06", "2026-07",
                                       reason="REPORTING_ERROR")
        set_clock("2026-10-05T00:00:00Z")
        validate_success(api.begin_recovery(case["id"], "FULL", CS))

        run_batch_at("2026-10-05T00:00:00Z", "2026-10")

        payment = payment_for_month(entitled["id"], "2026-10")
        assert payment["gross_cents"] == 8_750
        assert payment["withheld_cents"] == 8_750
        assert payment["net_paid_cents"] == 0
        assert payment["status"] == "WITHHELD_FULL"
        assert payment["paid_to"] == "BENEFICIARY"

        fresh = get_overpayment_case(case["id"], entitled["id"])
        assert fresh["recovered_cents"] == 8_750
        assert fresh["remaining_cents"] == 11_250
        assert fresh["status"] == "RECOVERY_ACTIVE"


class TestPartialRecovery:
    def test_partial_recovery_withholds_flat_rate(self, api):
        """PRD §3.8: "`PARTIAL` withholds the lesser of the case's elected
        `monthly_rate_cents`, its `remaining_cents`, and the capacity left".
        PRD §3.8: "A `PARTIAL` election must withhold at least ten percent of the
        claim's `monthly_benefit_cents` each month, else
        `ERR_RECOVERY_RATE_TOO_LOW` (422)."

        Rate 2,000 >= 1,251 (10% of 12,510): the cycle withholds exactly 2,000
        regardless of the 9,000 balance above it.

        Design: Corner/calculations/partial_recovery_withholds_flat_rate
        """
        worker = create_worker_with_awi_record(2021, 2023, full_name="Partial Rate")
        claim = file_claim(worker["id"], "RETIREMENT", "2031-06")
        set_clock("2031-06-10T00:00:00Z")
        entitled = approve_claim(claim["id"])
        case = create_overpayment_case(entitled["id"], 9_000, "2031-06", "2031-06",
                                       reason="REPORTING_ERROR")
        set_clock("2031-07-15T00:00:00Z")
        validate_success(api.begin_recovery(case["id"], "PARTIAL", CS,
                                            monthly_rate_cents=2_000))

        run_batch_at("2031-08-01T00:00:00Z", "2031-08")

        payment = payment_for_month(entitled["id"], "2031-08")
        assert payment["gross_cents"] == 12_510
        assert payment["withheld_cents"] == 2_000
        assert payment["net_paid_cents"] == 10_510
        assert payment["status"] == "PAID"

        fresh = get_overpayment_case(case["id"], entitled["id"])
        assert fresh["recovered_cents"] == 2_000
        assert fresh["remaining_cents"] == 7_000
        assert fresh["status"] == "RECOVERY_ACTIVE"

        claim_fresh = get_claim(entitled["id"])
        assert claim_fresh["recovery_mode"] == "PARTIAL"

    def test_partial_recovery_below_ten_percent_rejected(self, api):
        """PRD §3.8: "A `PARTIAL` election must withhold at least ten percent of
        the claim's `monthly_benefit_cents` each month, else
        `ERR_RECOVERY_RATE_TOO_LOW` (422)."

        500 < 1,251 (10% of 12,510).

        Design: Corner/validations/partial_recovery_below_ten_percent_rejected
        """
        worker = create_worker_with_awi_record(2021, 2023, full_name="Low Rate")
        claim = file_claim(worker["id"], "RETIREMENT", "2031-06")
        set_clock("2031-06-10T00:00:00Z")
        entitled = approve_claim(claim["id"])
        case = create_overpayment_case(entitled["id"], 9_000, "2031-06", "2031-06",
                                       reason="REPORTING_ERROR")

        set_clock("2031-07-15T00:00:00Z")
        resp = api.begin_recovery(case["id"], "PARTIAL", CS, monthly_rate_cents=500)
        validate_error(resp, ApiErrorId.ERR_RECOVERY_RATE_TOO_LOW, 422)

        unchanged = get_overpayment_case(case["id"], entitled["id"])
        assert unchanged["status"] == "NOTIFIED"
        claim_fresh = get_claim(entitled["id"])
        assert claim_fresh["recovery_mode"] == "FULL"
