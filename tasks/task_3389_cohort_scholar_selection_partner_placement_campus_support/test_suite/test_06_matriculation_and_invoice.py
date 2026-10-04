"""Matriculation, the training gate, and the program-fee invoice (PRD §3.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    EXPECTED_INVOICE_TWO_SCHOLARS,
    TEST_USERS,
    api_client,
    assert_cohort,
    get_cohort,
    get_scholar,
    setup_cohort_foundation,
    setup_locked_cohort,
    setup_matriculated_cohort,
    validate_error,
    validate_paginated,
    validate_success,
)

_ADMIN = TEST_USERS["program_admin_headers"]


class TestMatriculatePrecondition:
    def test_matriculate_forming_cohort_rejected(self, api):
        """PRD §3.6: "The cohort must be `LOCKED`; matriculating a cohort in
        any other status is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/matriculate_forming_cohort_rejected
        """
        ctx = setup_cohort_foundation(cohort_size=3)  # FORMING, no offers at all
        resp = api.matriculate_cohort(ctx["cohort"]["id"], _ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["status"] == "FORMING"
        assert cohort["invoice_total_cents"] is None


class TestInvoiceZeroWhenNobodyMatriculates:
    def test_invoice_zero_when_nobody_matriculates(self, api):
        """PRD §3.6: "If zero scholars matriculated in the call,
        `invoice_total_cents` is 0."
        PRD §3.6: "A scholar with any shortfall — fewer than 8 completed
        modules — is instead moved to `WITHDRAWN`, their accepted offer becomes
        `REVOKED`, and `seats_committed` falls by one."

        Design: Corner/calculations/invoice_zero_when_nobody_matriculates
        """
        ctx = setup_matriculated_cohort(trained_count=0)
        cohort = ctx["cohort_after"]
        assert cohort["status"] == "MATRICULATED", (
            "the cohort still matriculates even with an empty input set"
        )
        assert cohort["invoice_total_cents"] == 0, "the empty sum is 0 — not null"
        assert cohort["seats_committed"] == 0, (
            "all three accepted offers were revoked by the training gate"
        )
        withdrawn, meta = validate_paginated(
            api.list_scholars(
                _ADMIN,
                params={"cohort_id": ctx["cohort"]["id"], "enrollment_status": "WITHDRAWN"},
            )
        )
        assert meta["total_count"] == 3


class TestProgramFeeInvoiceRounding:
    def _setup_two_of_three_trained(self):
        """LOCKED cohort (tuition 6123460); s1 and s2 fully trained, s3 not;
        then matriculated."""
        return setup_matriculated_cohort(trained_count=2, tuition_annual_cents=6123460)

    def test_invoice_uses_per_scholar_rounding_before_sum(self, api):
        """PRD §3.6: "The rounding order is pinned: each per-scholar fee is
        rounded half-up to whole cents before the sum is taken. Summing the raw
        fractional components first and rounding once at the end is forbidden,
        because it produces a different total. For concreteness: with a
        `tuition_annual_cents` of 6123460 and two scholars matriculating, the
        pinned per-line rounding yields an invoice of 653086 cents, whereas
        sum-then-round would yield 653087 cents."

        Design: Difficulty/combinatorial_formula/program_fee_invoice_per_scholar_rounding
        """
        ctx = self._setup_two_of_three_trained()
        cohort = ctx["cohort_after"]
        assert cohort["status"] == "MATRICULATED"
        assert cohort["invoice_total_cents"] == EXPECTED_INVOICE_TWO_SCHOLARS, (
            "2 x (250000 + round_half_up(6123460 * 125 / 10000)) = 2 x 326543 = 653086"
        )
        assert_cohort(cohort)

    def test_training_gate_withdraws_untrained_scholar(self, api):
        """PRD §3.6: "A scholar whose `training_completed_count` is exactly 8
        matriculates: `enrollment_status` becomes `MATRICULATED`,
        `ever_matriculated` latches to true, and that scholar's accepted offer
        becomes `FULFILLED`. A scholar with any shortfall — fewer than 8
        completed modules — is instead moved to `WITHDRAWN`, their accepted
        offer becomes `REVOKED`, and `seats_committed` falls by one."

        Design: Difficulty/combinatorial_formula/program_fee_invoice_per_scholar_rounding
        """
        ctx = self._setup_two_of_three_trained()
        cohort = ctx["cohort_after"]
        assert cohort["seats_committed"] == 2, "s3's accepted offer was revoked"

        s1, s2, s3 = (get_scholar(s["id"]) for s in ctx["scholars"])
        assert s1["enrollment_status"] == "MATRICULATED"
        assert s1["ever_matriculated"] is True
        assert s2["enrollment_status"] == "MATRICULATED"
        assert s3["enrollment_status"] == "WITHDRAWN", "training gate 0 < 8"
        assert s3["ever_matriculated"] is False
