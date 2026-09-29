"""
The consistency model: every derived field is already current in the very first
response after a money-moving write, and equally current after the compensating
one.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import ADJUSTER_A, ADJUSTER_B, OPERATOR


class TestImmediateDerivation:
    """No lag, no reconciliation pass, no convergence."""

    def test_the_rollup_is_current_on_the_first_read_after_the_payout_and_its_reversal(
        self, api
    ):
        """
        The approval alone moves nothing; the payout response itself already
        reports PAID with the clock instant stamped, the first balance read after
        it already shows the full 30000 subtracted, a repeated read returns the
        identical figure rather than converging toward it, and the reversal restores
        the exact pre-payout value while the append-only log grows to four rows.

        PRD §2.11: "A property's `outstanding_balance_cents` is a derived field, re-derived on every single ledger insert."

        Design: Corner/consistency_model/every_derived_field_is_current_in_the_same_response
        """
        env = fx.build_base_env(api)
        claim = fx.file_claim(api, env.subscription_id)
        fx.triage_claim(api, claim["id"], ADJUSTER_A)
        approved = fx.approve_claim(api, claim["id"], ADJUSTER_B)
        a.assert_cents(approved["approved_amount_cents"], 30000, "approved_amount_cents")

        balance_before = a.property_balance(api, env.property_id, OPERATOR)
        assert balance_before == 5588
        _before_rows, before_meta = validate_paginated(
            api.list_ledger_entries(env.subscription_id, OPERATOR)
        )
        assert before_meta["total_count"] == 2

        paid = validate_success(api.pay_claim(claim["id"], OPERATOR))
        assert paid["status"] == "PAID"
        a.assert_instant_equals(paid["paid_at"], "2026-08-05T00:00:00Z")

        balance_after_first_read = a.property_balance(api, env.property_id, OPERATOR)
        assert balance_after_first_read == -24412
        balance_after_second_read = a.property_balance(api, env.property_id, OPERATOR)
        assert balance_after_second_read == balance_after_first_read

        rows, meta = validate_paginated(
            api.list_ledger_entries(env.subscription_id, OPERATOR)
        )
        assert meta["total_count"] == 3
        a.assert_ledger_ordering(rows)
        a.assert_ledger_row(rows[-1], "CLAIM_PAYOUT", -30000, "PROPERTY_MANAGER", claim["id"])

        reversed_claim = validate_success(
            api.reverse_claim_payment(
                claim["id"], f.reverse_payment_payload("Duplicate disbursement"), OPERATOR
            )
        )
        assert reversed_claim["status"] == "PAYMENT_REVERSED"
        a.assert_cents(
            reversed_claim["approved_amount_cents"], 30000, "approved_amount_cents"
        )

        assert a.property_balance(api, env.property_id, OPERATOR) == balance_before
        reversed_rows, reversed_meta = validate_paginated(
            api.list_ledger_entries(env.subscription_id, OPERATOR)
        )
        assert reversed_meta["total_count"] == 4
        a.assert_ledger_row(
            reversed_rows[-1], "CLAIM_PAYOUT_REVERSAL", 30000, "PROPERTY_MANAGER", claim["id"]
        )
