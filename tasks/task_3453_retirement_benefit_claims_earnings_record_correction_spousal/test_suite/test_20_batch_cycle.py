"""Monthly batch cycle: the January-only COLA with its same-January exclusion,
and idempotent replay of an already-run month."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_claim,
    create_worker_with_awi_record,
    file_claim,
    get_claim,
    list_payments,
    payment_for_month,
    run_batch,
    run_batch_at,
    set_clock,
    validate_success,
)

CS = TEST_USERS["claims_specialist_headers"]


class TestColaAdjustment:
    def test_cola_january_only_and_prior_entitlement_only(self, api):
        """PRD §3.7: "First, the **January COLA**: when the run month is a
        January, every claim in `ENTITLED` status whose `entitlement_month` is
        strictly before that January has its `monthly_benefit_cents` increased by
        two and a half percent, dime-floored once per claim. Claims entitled in
        that very January, and all `SUSPENDED` claims, receive no adjustment this
        cycle."

        Claim A (entitled 2026-06, monthly 8,750): untouched by the December run,
        then dime_floor(8,750 * 1.025) = 8,960 in the 2027-01 run. Claim B
        (entitled 2027-01 itself, monthly dime_floor(12,510 * 35/48) = 9,120) is
        excluded from that January's COLA.

        Design: Corner/calculations/cola_january_only_and_prior_entitlement_only
        """
        wa = create_worker_with_awi_record(2021, 2023, full_name="Cola A")
        claim_a = file_claim(wa["id"], "RETIREMENT", "2026-06")
        approve_claim(claim_a["id"])

        wb = create_worker_with_awi_record(2021, 2023, full_name="Cola B")
        claim_b = file_claim(wb["id"], "RETIREMENT", "2027-01")

        run_batch_at("2026-12-05T00:00:00Z", "2026-12")
        payment_dec = payment_for_month(claim_a["id"], "2026-12")
        assert payment_dec["gross_cents"] == 8_750, "no COLA in a December run"

        set_clock("2027-01-03T00:00:00Z")
        entitled_b = approve_claim(claim_b["id"])
        assert entitled_b["monthly_benefit_cents"] == 9_120

        report = run_batch("2027-01")
        assert report["cola_applied"] == 1, "only claim A is entitled before this January"

        claim_a_fresh = get_claim(claim_a["id"])
        assert claim_a_fresh["monthly_benefit_cents"] == 8_960
        assert payment_for_month(claim_a["id"], "2027-01")["gross_cents"] == 8_960
        assert payment_for_month(claim_b["id"], "2027-01")["gross_cents"] == 9_120


class TestIdempotentReplay:
    def test_batch_rerun_same_month_is_idempotent(self, api):
        """PRD §3.7: "The cycle is idempotent: re-running an already-processed
        month creates nothing and reports `already_run` as true with every count
        at zero."

        Design: Corner/endpoints/batch_rerun_same_month_is_idempotent
        """
        worker = create_worker_with_awi_record(2021, 2023, full_name="Idempotent")
        claim = file_claim(worker["id"], "RETIREMENT", "2026-06")
        set_clock("2026-10-05T00:00:00Z")
        approve_claim(claim["id"])

        first = run_batch("2026-10")
        assert first["payments_created"] == 1
        assert first["already_run"] is False

        second = run_batch("2026-10")
        assert second["already_run"] is True
        assert second["payments_created"] == 0
        assert second["corrections_expired"] == 0
        assert second["claims_auto_resumed"] == 0
        assert second["overpayments_recovered"] == 0
        assert second["cola_applied"] == 0

        payments = list_payments(claim["id"])
        assert len(payments) == 1
        assert payments[0]["month"] == "2026-10"
