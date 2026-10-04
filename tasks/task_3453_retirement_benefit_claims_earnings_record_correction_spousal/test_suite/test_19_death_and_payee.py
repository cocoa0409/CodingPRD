"""Death reporting cascades and representative-payee determinations: capacity-1
exclusivity, payment routing, and segregation of duties."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_claim,
    create_overpayment_case,
    create_payee_case,
    create_worker_with_awi_record,
    decide_payee_case,
    file_claim,
    get_claim,
    get_worker,
    list_payments,
    make_senior_adjudicator_headers,
    payment_for_month,
    run_batch,
    run_batch_at,
    set_clock,
    setup_entitled_retirement,
    validate_error,
    validate_success,
)

CS = TEST_USERS["claims_specialist_headers"]


def _setup_claim_with_active_payee(api):
    """Worker (five AWI years, monthly 14,610 at 62), RETIREMENT entitled
    2026-06, and an ACTIVE payee case created by spec-2 and approved by sen-3."""
    worker, entitled = setup_entitled_retirement(2019, 2023, "2026-06")
    assert entitled["monthly_benefit_cents"] == 14_610
    payee = create_payee_case(
        entitled["id"], creator_id="spec-2", payee_name="Pat Payee",
        determination_basis="physician letter: cannot manage funds",
    )
    active = decide_payee_case(payee["id"], "APPROVED", adjudicator_id="sen-3")
    assert active["status"] == "ACTIVE"
    return worker, entitled, active


class TestDeathCascade:
    def test_death_terminates_claim_and_ends_payee(self, api):
        """PRD §3.9: "The worker becomes `DECEASED` with `death_date` stored, and
        the cascade runs: every claim of this worker in `ENTITLED` or `SUSPENDED`
        status moves to `TERMINATED` with `monthly_benefit_cents` zeroed; every
        `ACTIVE` payee case on those claims moves to `ENDED` with
        `has_active_payee` cleared; suspended claims stop accruing delayed
        credits; and the worker's `version` increments."

        Design: Difficulty/transitive_cascade/worker_death_termination_chain
        """
        worker, entitled, payee = _setup_claim_with_active_payee(api)
        run_batch_at("2026-06-20T00:00:00Z", "2026-06")

        set_clock("2026-07-16T00:00:00Z")
        deceased = validate_success(api.report_death(worker["id"], "2026-07-15", CS))
        assert deceased["status"] == "DECEASED"
        assert deceased["death_date"] == "2026-07-15"

        claim = get_claim(entitled["id"])
        assert claim["status"] == "TERMINATED"
        assert claim["monthly_benefit_cents"] == 0
        assert claim["has_active_payee"] is False

        payees = validate_success(api.list_claim_payee_cases(entitled["id"], CS))
        assert payees[0]["id"] == payee["id"]
        assert payees[0]["status"] == "ENDED"

    def test_terminated_claim_generates_no_payments(self, api):
        """PRD §3.7: "Third, **payment generation**: one payment is created per
        `ENTITLED` claim whose `entitlement_month` is on or before the run
        month."
        PRD §3.7: "Routing is recorded in `paid_to`: `REPRESENTATIVE_PAYEE`
        while the claim has an `ACTIVE` payee case, `BENEFICIARY` otherwise."

        The pre-death 2026-06 payment routed to the representative payee; the
        2026-08 batch after termination creates nothing.

        Design: Difficulty/transitive_cascade/worker_death_termination_chain
        """
        worker, entitled, payee = _setup_claim_with_active_payee(api)
        run_batch_at("2026-06-20T00:00:00Z", "2026-06")

        payment = payment_for_month(entitled["id"], "2026-06")
        assert payment["paid_to"] == "REPRESENTATIVE_PAYEE"
        assert payment["net_paid_cents"] == 14_610

        set_clock("2026-07-16T00:00:00Z")
        validate_success(api.report_death(worker["id"], "2026-07-15", CS))

        report = run_batch_at("2026-08-01T00:00:00Z", "2026-08")
        assert report["payments_created"] == 0
        assert payment_for_month(entitled["id"], "2026-08") is None


class TestPayeeCapacityAndSegregation:
    def test_first_payee_approval_sets_active_flag(self, api):
        """PRD §3.9: "On approval the case becomes `ACTIVE`, the claim's
        `has_active_payee` becomes true, `decided_by` is stamped, and future
        payments route to the payee (`paid_to` `REPRESENTATIVE_PAYEE`, §3.7)."

        Design: Difficulty/resource_temporal_overlap/payee_capacity_one_exclusivity
        """
        worker, entitled = setup_entitled_retirement(2019, 2023, "2026-06")
        payee = create_payee_case(entitled["id"], creator_id="spec-5",
                                  payee_name="Payee One",
                                  determination_basis="court order")
        active = decide_payee_case(payee["id"], "APPROVED", adjudicator_id="sen-1")
        assert active["status"] == "ACTIVE"
        assert active["decided_by"] == "sen-1"

        claim = get_claim(entitled["id"])
        assert claim["has_active_payee"] is True

    def test_second_active_payee_rejected(self, api):
        """PRD §3.9: "and capacity-one exclusivity: no other `ACTIVE` payee case
        may exist for the claim, else `ERR_ACTIVE_PAYEE_EXISTS` (409)."

        Design: Difficulty/resource_temporal_overlap/payee_capacity_one_exclusivity
        """
        worker, entitled = setup_entitled_retirement(2019, 2023, "2026-06")
        payee1 = create_payee_case(entitled["id"], creator_id="spec-5",
                                   payee_name="Payee One",
                                   determination_basis="court order")
        decide_payee_case(payee1["id"], "APPROVED", adjudicator_id="sen-1")
        payee2 = create_payee_case(entitled["id"], creator_id="spec-5",
                                   payee_name="Payee Two",
                                   determination_basis="family request")

        resp = api.decide_payee_case(
            payee2["id"], "APPROVED", TEST_USERS["senior_adjudicator_headers"]
        )
        # default adjudicator header id differs from creator spec-5; the
        # capacity rule is the one that rejects.
        validate_error(resp, ApiErrorId.ERR_ACTIVE_PAYEE_EXISTS, 409)

        payees = validate_success(api.list_claim_payee_cases(entitled["id"], CS))
        by_id = {p["id"]: p for p in payees}
        assert by_id[payee1["id"]]["status"] == "ACTIVE"
        assert by_id[payee2["id"]]["status"] == "INVESTIGATING"
        assert get_claim(entitled["id"])["has_active_payee"] is True

    def test_payee_decision_by_case_creator_rejected(self, api):
        """PRD §3.9: "A `SeniorAdjudicator` decides with an `outcome` of
        `APPROVED` or `DENIED`, never the case's creator (`ERR_SAME_ADJUDICATOR`,
        409). An approval additionally requires the claim still `ENTITLED` — else
        `ERR_INVALID_STATE` (409) — and capacity-one exclusivity: no other
        `ACTIVE` payee case may exist for the claim, else
        `ERR_ACTIVE_PAYEE_EXISTS` (409). On approval the case becomes `ACTIVE`,
        the claim's `has_active_payee` becomes true, `decided_by` is stamped, and
        future payments route to the payee (`paid_to` `REPRESENTATIVE_PAYEE`,
        §3.7). A denial ends the case as `DENIED`, which is terminal."

        The creator 'spec-6' may not decide even with the adjudicator role; a
        different adjudicator's DENIED terminates the case.

        Design: Corner/validations/payee_decision_by_case_creator_rejected
        """
        worker, entitled = setup_entitled_retirement(2021, 2023, "2026-06")
        payee = create_payee_case(entitled["id"], creator_id="spec-6",
                                  payee_name="Case Worker",
                                  determination_basis="medical evidence")

        resp = api.decide_payee_case(
            payee["id"], "APPROVED", make_senior_adjudicator_headers("spec-6")
        )
        validate_error(resp, ApiErrorId.ERR_SAME_ADJUDICATOR, 409)

        denied = decide_payee_case(payee["id"], "DENIED", adjudicator_id="sen-4")
        assert denied["status"] == "DENIED"
        assert denied["decided_by"] == "sen-4"
        assert get_claim(entitled["id"])["has_active_payee"] is False
