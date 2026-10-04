"""Overpayment waiver workflow: request window, waiver decisions, segregation of
duties, and the begin-recovery claim-state gate."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_claim,
    create_overpayment_case,
    create_worker,
    create_worker_with_awi_record,
    file_claim,
    get_claim,
    get_overpayment_case,
    make_claimant_headers,
    make_senior_adjudicator_headers,
    payment_for_month,
    run_batch_at,
    set_clock,
    setup_entitled_retirement,
    validate_error,
    validate_success,
)

CS = TEST_USERS["claims_specialist_headers"]


class TestWaiverWindow:
    def test_waiver_request_after_30_days_rejected(self, api):
        """PRD §3.8: "A claimant who disputes the debt may **request a waiver**
        within thirty days of the notice date; a later request is rejected with
        `ERR_WAIVER_WINDOW_CLOSED` (422)."

        Notice at the default clock 2026-09-01; the request at 2026-10-02 is day
        31. The OCC version is fresh, isolating the temporal rule.

        Design: Corner/validations/waiver_request_after_30_days_rejected
        """
        worker = create_worker(full_name="Late Waiver")
        claim = file_claim(worker["id"], "RETIREMENT", "2026-06")
        case = create_overpayment_case(claim["id"], 8_000, "2026-06", "2026-06",
                                       reason="FRAUD")

        set_clock("2026-10-02T00:00:00Z")
        resp = api.request_waiver(
            case["id"], case["version"], "without fault",
            make_claimant_headers(worker["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WAIVER_WINDOW_CLOSED, 422)

        unchanged = get_overpayment_case(case["id"], claim["id"])
        assert unchanged["status"] == "NOTIFIED"

    def test_begin_recovery_inside_waiver_window_rejected(self, api):
        """PRD §3.8: "Recovery may also be **started directly** by a
        `ClaimsSpecialist`, but only after the thirty-day waiver window has
        lapsed — an earlier attempt is rejected with `ERR_WAIVER_WINDOW_OPEN`
        (422)".

        Case noticed at the default clock; recovery attempted five days later.

        Design: Corner/validations/begin_recovery_inside_waiver_window_rejected
        """
        worker, entitled = setup_entitled_retirement(2021, 2023, "2026-06")
        case = create_overpayment_case(entitled["id"], 8_000, "2026-06", "2026-06",
                                       reason="SYSTEM_ERROR")

        set_clock("2026-09-06T00:00:00Z")
        resp = api.begin_recovery(case["id"], "FULL", CS)
        validate_error(resp, ApiErrorId.ERR_WAIVER_WINDOW_OPEN, 422)

        unchanged = get_overpayment_case(case["id"], entitled["id"])
        assert unchanged["status"] == "NOTIFIED"


class TestWaiverDecisions:
    def test_waiver_decision_by_case_creator_rejected(self, api):
        """PRD §2.9: "Four second-instance decisions — reopening a denied claim,
        reopening a denied correction, deciding a waiver, and deciding a payee
        determination — require the acting operator's `X-User-ID` to differ from
        the operator recorded on the contested first-instance determination
        (`decided_by` on the claim or correction, `created_by` on the
        overpayment or payee case). An attempt by the same operator is rejected
        with `ERR_SAME_ADJUDICATOR` (409)."

        Design: Corner/validations/waiver_decision_by_case_creator_rejected
        """
        worker = create_worker(full_name="Seg Duty")
        claim = file_claim(worker["id"], "RETIREMENT", "2026-06")
        case = create_overpayment_case(claim["id"], 8_000, "2026-06", "2026-06",
                                       reason="FRAUD", creator_id="spec-7")
        validate_success(
            api.request_waiver(case["id"], case["version"], "against equity",
                               make_claimant_headers(worker["id"]))
        )

        resp = api.decide_waiver(case["id"], "GRANTED",
                                 make_senior_adjudicator_headers("spec-7"))
        validate_error(resp, ApiErrorId.ERR_SAME_ADJUDICATOR, 409)

        unchanged = get_overpayment_case(case["id"], claim["id"])
        assert unchanged["status"] == "WAIVER_REVIEW"

    def test_waiver_granted_forgives_debt_no_withholding(self, api):
        """PRD §3.8: "Granting moves the case to `WAIVED` (terminal): the debt is
        forgiven, `remaining_cents` becomes zero by definition, and the case
        leaves the withholding set. Denying moves it to `RECOVERY_ACTIVE`, with
        withholding beginning on the next batch cycle. Either decision stamps
        `waiver_decided_by`."

        Case A (7,000) GRANTED leaves the withholding set entirely; case B
        (6,000) DENIED withholds 6,000 in the next cycle and closes RECOVERED.

        Design: Corner/state_machines/waiver_granted_forgives_debt_no_withholding
        """
        worker = create_worker_with_awi_record(2021, 2023, full_name="Waiver Worker")
        claim = file_claim(worker["id"], "RETIREMENT", "2031-06")
        set_clock("2031-06-10T00:00:00Z")
        entitled = approve_claim(claim["id"])
        assert entitled["monthly_benefit_cents"] == 12_510

        case_a = create_overpayment_case(entitled["id"], 7_000, "2031-06", "2031-06",
                                         reason="REPORTING_ERROR", creator_id="spec-4")
        case_b = create_overpayment_case(entitled["id"], 6_000, "2031-06", "2031-06",
                                         reason="SYSTEM_ERROR", creator_id="spec-4")
        validate_success(
            api.request_waiver(case_a["id"], case_a["version"],
                               "without fault and against equity",
                               make_claimant_headers(worker["id"]))
        )
        validate_success(
            api.request_waiver(case_b["id"], case_b["version"], "administrative burden",
                               make_claimant_headers(worker["id"]))
        )

        granted = validate_success(
            api.decide_waiver(case_a["id"], "GRANTED", make_senior_adjudicator_headers("sen-8"))
        )
        assert granted["status"] == "WAIVED"
        assert granted["waiver_decided_by"] == "sen-8"
        denied = validate_success(
            api.decide_waiver(case_b["id"], "DENIED", make_senior_adjudicator_headers("sen-8"))
        )
        assert denied["status"] == "RECOVERY_ACTIVE"

        run_batch_at("2031-08-01T00:00:00Z", "2031-08")
        payment = payment_for_month(entitled["id"], "2031-08")
        assert payment["withheld_cents"] == 6_000, "only case B withholds"
        assert payment["net_paid_cents"] == 6_510

        case_b_fresh = get_overpayment_case(case_b["id"], entitled["id"])
        assert case_b_fresh["recovered_cents"] == 6_000
        assert case_b_fresh["status"] == "RECOVERED"
        case_a_fresh = get_overpayment_case(case_a["id"], entitled["id"])
        assert case_a_fresh["status"] == "WAIVED"


class TestBeginRecoveryClaimGate:
    def test_begin_recovery_against_filed_claim_rejected(self, api):
        """PRD §3.8: "and only against a claim in `ENTITLED` status, because
        recovery works by withholding from future benefits of an active claim;
        anything else is `ERR_INVALID_STATE` (409)."

        The claim is FILED; even with the call otherwise well-formed the state
        gate rejects.

        Design: Difficulty/cross_entity_state_dependency/begin_recovery_gated_on_claim_entitled
        """
        worker = create_worker_with_awi_record(2019, 2023, full_name="Overpaid Worker")
        claim = file_claim(worker["id"], "RETIREMENT", "2026-06")
        case = create_overpayment_case(claim["id"], 12_000, "2026-06", "2026-07",
                                       reason="REPORTING_ERROR")

        resp = api.begin_recovery(case["id"], "FULL", CS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

        unchanged = get_overpayment_case(case["id"], claim["id"])
        assert unchanged["status"] == "NOTIFIED"

    def test_begin_recovery_succeeds_once_claim_entitled(self, api):
        """PRD §3.8: "The same call elects the claim-level withholding policy:
        the claim's `recovery_mode` becomes the elected mode — `FULL` (the
        default), `PARTIAL` with a `monthly_rate_cents`, or `PROPORTIONAL` — and
        the most recent election governs."

        After approval and after the 30-day waiver window lapses (notice
        2026-09-01, clock 2026-10-05), the identical begin-recovery succeeds.

        Design: Difficulty/cross_entity_state_dependency/begin_recovery_gated_on_claim_entitled
        """
        worker = create_worker_with_awi_record(2019, 2023, full_name="Overpaid Worker")
        claim = file_claim(worker["id"], "RETIREMENT", "2026-06")
        case = create_overpayment_case(claim["id"], 12_000, "2026-06", "2026-07",
                                       reason="REPORTING_ERROR")

        approve_claim(claim["id"])
        set_clock("2026-10-05T00:00:00Z")
        active = validate_success(api.begin_recovery(case["id"], "FULL", CS))
        assert active["status"] == "RECOVERY_ACTIVE"

        claim_fresh = get_claim(claim["id"])
        assert claim_fresh["recovery_mode"] == "FULL"
