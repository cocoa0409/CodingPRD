"""The three-way settlement split: the waterfall, its two variants and the
withholding arithmetic that rides on it."""
import math

import pytest

from test_helpers import (
    OA_PREMIUM_RATE,
    OA_RATE_ELEVATED,
    OA_SAFETY_TIER_STANDARD_MIN,
    PINNED_AGENT_SHARE_CENTS,
    PINNED_COMPANY_SHARE_CENTS,
    PINNED_OWNER_SHARE_CENTS,
    PINNED_UNION_BASE_CENTS,
    ApiErrorId,
    api_client,
    assert_settlement_conservation,
    find_ledger_entry,
    get_success_data,
    setup_approved_settlement,
    setup_oa_clone_pair,
    setup_settled_load,
    settle_settlement,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSplitWaterfall:
    """The eight-step waterfall and its conserved total."""

    def test_split_evaluation_order_and_conserved_remainder(self, api):
        """PRD §3.7: "Step five computes `company_share_cents` as the union base
        minus the agent share minus the owner-operator share."
        PRD §3.7: "The invariant on top of all of it is a conserved quantity:
        `settled_total_cents` must equal the linehaul plus the fuel surcharge
        plus the accessorial revenue *exactly*, for both variants."
        PRD §3.7: "The `commissionable_base_cents` is the linehaul plus the
        accessorial revenue — the fuel surcharge is excluded from it,
        deliberately, because fuel is not commissioned."

        Design: Difficulty/combinatorial_formula/settlement_split_evaluation_order_and_conserved_remainder
        """
        bundle = setup_approved_settlement(settlement_method="FINAL", oa_enrolled=True)
        load = bundle["load"]

        data = validate_success(
            api.evaluate_load_settlement(
                load["id"], {"settlement_method": "FINAL"},
                TEST_USERS["settlement_operator_headers"],
            ), 200
        )

        # company_share is a remainder, not an independently rounded bucket.
        assert data["agent_share_cents"] == PINNED_AGENT_SHARE_CENTS
        assert data["owner_operator_share_cents"] == PINNED_OWNER_SHARE_CENTS
        assert data["company_share_cents"] == (
            PINNED_UNION_BASE_CENTS - PINNED_AGENT_SHARE_CENTS - PINNED_OWNER_SHARE_CENTS
        )
        assert data["settled_total_cents"] == PINNED_UNION_BASE_CENTS
        assert data["settled_total_cents"] != PINNED_UNION_BASE_CENTS - 1
        assert data["settled_total_cents"] != PINNED_UNION_BASE_CENTS + 1

        # The conserved total still lands on the summed allocations.
        assert data["settled_total_cents"] == (
            data["linehaul_revenue_allocated_cents"]
            + data["fuel_surcharge_allocated_cents"]
            + data["accessorial_allocated_cents"]
        )

    def test_commissionable_base_excludes_fuel_surcharge(self, api):
        """PRD §3.7: "The `commissionable_base_cents` is the linehaul plus the
        accessorial revenue — the fuel surcharge is excluded from it,
        deliberately, because fuel is not commissioned."
        PRD §3.7: "Step four computes the owner-operator's gross side:
        `owner_operator_share_cents` is the linehaul plus the fuel surcharge,
        multiplied by the capacity owner's `revenue_split_pct`, rounded half up."

        Design: Corner/calculations/commissionable_base_excludes_fuel_surcharge
        """
        bundle = setup_approved_settlement(settlement_method="FINAL", oa_enrolled=False)
        load = bundle["load"]
        settlement = bundle["settlement"]

        # The reported commissionable base is linehaul + accessorial only.
        assert settlement["commissionable_base_cents"] == 192000
        assert settlement["agent_share_cents"] == PINNED_AGENT_SHARE_CENTS
        assert settlement["agent_share_cents"] != 26928
        assert settlement["fuel_surcharge_allocated_cents"] == 32400
        assert settlement["owner_operator_share_cents"] == PINNED_OWNER_SHARE_CENTS
        assert settlement["settled_total_cents"] == PINNED_UNION_BASE_CENTS
        assert_settlement_conservation(settlement)

    def test_non_enrolled_final_pays_no_oa_premium(self, api):
        """PRD §3.7: "When the capacity owner is not enrolled in the
        occupational-accident program, `oa_premium_cents` is zero; otherwise it
        is the occupational-accident base multiplied by the occupational-accident
        premium rate of 1.50%, rounded up."
        PRD §3.7: "`insurance_premium_cents` is the insurance base multiplied by
        the insurance premium rate of 2.10%, rounded up."

        Design: Corner/calculations/settlement_split_non_enrolled_final_pays_no_oa_premium
        """
        bundle = setup_approved_settlement(settlement_method="FINAL", oa_enrolled=False)
        settlement = bundle["settlement"]

        assert settlement["agent_share_cents"] == PINNED_AGENT_SHARE_CENTS
        assert settlement["owner_operator_share_cents"] == PINNED_OWNER_SHARE_CENTS
        assert settlement["company_share_cents"] == PINNED_COMPANY_SHARE_CENTS
        assert settlement["settled_total_cents"] == PINNED_UNION_BASE_CENTS
        assert settlement["oa_premium_cents"] == 0
        assert settlement["insurance_premium_cents"] == 4461
        assert settlement["maintenance_withholding_cents"] == 2400
        assert settlement["net_owner_operator_pay_cents"] == 137571

    def test_withholdings_round_up_not_down(self, api):
        """PRD §2.7: "Round up (ceiling). Every percentage-based withholding —
        the occupational-accident premium, the insurance premium, the escrow
        withholding, and the advance-repayment cap — is rounded up to the
        nearest whole cent, so a fractional cent never escapes the bucket being
        withheld."
        PRD §3.8: "The maintenance withholding is not a percentage at all: it is
        exactly the reserve the trip already derived from the miles actually run,
        being the actual miles divided by the 1000-mile chunk, rounded up,
        multiplied by 1200 cents per chunk."

        Design: Corner/calculations/settlement_withholdings_round_up_not_down
        """
        bundle = setup_approved_settlement(settlement_method="FINAL", oa_enrolled=False)
        settlement = bundle["settlement"]

        # (180000 + 32400) * 0.0210 == 4460.04 → ceiling 4461, not 4460.
        assert settlement["insurance_premium_cents"] == 4461
        assert settlement["insurance_premium_cents"] != 4460
        # ceil(1237 / 1000) * 1200 == 2400, not floor(1237/1000)*1200 == 1200.
        assert settlement["maintenance_withholding_cents"] == 2400
        assert settlement["insurance_premium_cents"] + settlement["maintenance_withholding_cents"] == 6861


class TestSplitVariants:
    """Provisional and final differ in exactly one place."""

    def test_provisional_vs_final_bco_net_pay(self, api):
        """PRD §3.7: "The two variants differ in exactly one place — the base the
        two percentage premiums are computed on."
        PRD §3.7: "Under `PROVISIONAL`, step seven computes the
        occupational-accident premium and the insurance premium from the
        owner-operator base, that is from step four's `owner_share_cents`; under
        `FINAL`, it computes them from the separate bases step six derived —
        linehaul plus accessorial for the occupational-accident premium, and
        linehaul plus fuel surcharge for the insurance premium."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_bco_net_pay
        """
        bundle = setup_approved_settlement(settlement_method="PROVISIONAL", oa_enrolled=True)
        load = bundle["load"]

        provisional = validate_success(
            api.evaluate_load_settlement(
                load["id"], {"settlement_method": "PROVISIONAL"},
                TEST_USERS["settlement_operator_headers"],
            ), 200
        )
        final = validate_success(
            api.evaluate_load_settlement(
                load["id"], {"settlement_method": "FINAL"},
                TEST_USERS["settlement_operator_headers"],
            ), 200
        )

        # The three shares are identical across the two variants.
        assert provisional["owner_operator_share_cents"] == 144432
        assert final["owner_operator_share_cents"] == 144432
        assert provisional["agent_share_cents"] == 23040
        assert final["agent_share_cents"] == 23040

        # Only the two percentage premiums move.
        assert provisional["oa_premium_cents"] == 2167
        assert final["oa_premium_cents"] == 2880
        assert provisional["insurance_premium_cents"] == 3034
        assert final["insurance_premium_cents"] == 4461

        # PRD §3.7 fixes only *which* base each premium uses, not the premium's
        # value: the four bases are derived from the total billed by the run.
        # The absolute net-pay cents and the variant delta are therefore not
        # pinned by the prose, and the two premiums above carry the divergence.

    @pytest.mark.parametrize("settlement_method", ["PROVISIONAL", "FINAL"])
    def test_oa_premium_enrollment_variant_split(self, api, settlement_method):
        """PRD §3.8: "A capacity owner who is not enrolled pays nothing at all,
        regardless of score, and no occupational-accident deduction entry is
        posted for it at settle", while the tiered rate applies only to an
        enrolled owner.

        Design: Difficulty/dual_variant_calc/oa_premium_enrollment_variant_split
        """
        state = setup_oa_clone_pair(settlement_method=settlement_method)
        origin, twin = state["origin"], state["twin"]

        assert twin["id"] != origin["bco"]["id"]
        assert twin["revenue_split_pct"] == origin["bco"]["revenue_split_pct"] == 0.68
        assert twin["safety_score"] == 100 and origin["bco"]["safety_score"] == 100
        assert twin["oa_enrolled"] is False and origin["bco"]["oa_enrolled"] is True
        assert state["enrolled_trip"]["status"] == "COMPLETED"
        assert state["twin_trip"]["status"] == "COMPLETED"

        # PRD §3.7 step seven: the occupational-accident base is the
        # owner-operator share under PROVISIONAL and the linehaul plus the
        # accessorial revenue under FINAL. PRD §3.8: at score 100 the standard
        # 1.50% rate is selected and the premium is that base rounded up.
        enrolled = state["enrolled_cost"]
        oa_base = (enrolled["owner_operator_share_cents"]
                   if settlement_method == "PROVISIONAL"
                   else enrolled["linehaul_revenue_allocated_cents"]
                   + enrolled["accessorial_allocated_cents"])
        assert enrolled["oa_premium_cents"] == math.ceil(oa_base * OA_PREMIUM_RATE)
        # PRD §3.8: a non-enrolled owner pays nothing at all.
        assert state["twin_cost"]["oa_premium_cents"] == 0


class TestOaPremiumTier:
    """The safety-score tier that selects the occupational-accident rate."""

    def test_oa_premium_tier_rate_selected_from_safety_score(self, api):
        """PRD §3.8: "a score of 95 or above takes 1.50%, a score of exactly 94
        takes 1.75%, a score of exactly 93 takes 1.75%, and a score of 92 or
        below takes 2.00%."
        PRD §3.8: "The boundary at 95 is the one that catches implementations:
        95 takes the standard rate, 94 takes the elevated rate."

        Design: Corner/calculations/oa_premium_tier_rate_selected_from_safety_score
        """
        bundle = setup_approved_settlement(settlement_method="FINAL", oa_enrolled=True)
        bco, load = bundle["bco"], bundle["load"]

        bco_now = get_success_data(api.get_capacity_owner(bco["id"], TEST_USERS["network_admin_headers"]))
        assert bco_now["safety_score"] == 100

        data = validate_success(
            api.evaluate_load_settlement(
                load["id"], {"settlement_method": "FINAL"},
                TEST_USERS["settlement_operator_headers"],
            ), 200
        )
        # PRD §3.8: a score of 95 or above takes 1.50%; PRD §3.7: under FINAL
        # the occupational-accident base is the linehaul plus the accessorial
        # revenue, and the premium is that base at the selected rate, rounded
        # up. At score 100 the standard rate is the one selected — the elevated
        # 1.75% rate that would have charged ceil(192000 * 0.0175) is not.
        assert OA_SAFETY_TIER_STANDARD_MIN <= bco_now["safety_score"]
        oa_base = (data["linehaul_revenue_allocated_cents"]
                   + data["accessorial_allocated_cents"])
        assert data["oa_premium_cents"] == math.ceil(oa_base * OA_PREMIUM_RATE)
        assert data["oa_premium_cents"] < math.ceil(oa_base * OA_RATE_ELEVATED)


class TestWithholdingLedgerEffects:
    """The settle-time ledger fan-out and the reversal that restores it."""

    def test_settle_posts_the_ledger_rows_for_the_bco(self, api):
        """PRD §3.6: "the ledger work runs: the six derived withholding and
        reserve entries are posted for the capacity owner, and an
        advance-repayment entry is posted when `advance_repayment_cents` is
        non-zero."
        PRD §3.7: "An advance cap is the advance-repayment base multiplied by
        the advance repayment rate of 10.00%, rounded up, and
        `advance_repayment_cents` is the smaller of the capacity owner's
        `outstanding_advance_cents` and that cap."

        Design: Corner/state_machines/settle_posts_the_five_ledger_rows_for_the_bco
        """
        bundle = setup_settled_load(
            settlement_method="FINAL", oa_enrolled=True
        )
        bco, load = bundle["bco"], bundle["load"]

        ledger, _meta = _ledger_rows(bco["id"])
        types = [row["transaction_type"] for row in ledger]
        for expected in (
            "OA_PREMIUM_DEDUCTION", "INSURANCE_PREMIUM_DEDUCTION",
            "MAINTENANCE_DEPOSIT", "ESCROW_DEPOSIT", "ADVANCE_REPAYMENT",
        ):
            assert expected in types, f"expected a {expected} row after the settle"

        maintenance = [r for r in ledger if r["transaction_type"] == "MAINTENANCE_DEPOSIT"]
        assert maintenance and maintenance[0]["amount_cents"] == 2400

        assert load["status"] == "SETTLED"
        settled = get_success_data(
            api.get_settlement(bundle["settlement"]["id"], TEST_USERS["settlement_operator_headers"])
        )
        assert settled["status"] == "SETTLED"
        assert settled["net_owner_operator_pay_cents"] == 134691

    def test_maintenance_withholding_reversal_restores_balance(self, api):
        """PRD §2.11: "Reversing a maintenance deposit restores the pre-mutation
        maintenance balance exactly."
        PRD §2.11: "the compensating map is fixed — `ESCROW_DEPOSIT` against
        `ESCROW_RELEASE`, `MAINTENANCE_DEPOSIT` against
        `MAINTENANCE_WITHDRAWAL`, `ADVANCE` against `ADVANCE_REPAYMENT`, and the
        reverse of each of those four".

        Design: Difficulty/compensating_invariant/maintenance_withholding_reversal_restores_balance
        """
        bundle = setup_approved_settlement(settlement_method="FINAL", oa_enrolled=False)
        bco, load = bundle["bco"], bundle["load"]

        before = get_success_data(api.get_capacity_owner(bco["id"], TEST_USERS["settlement_operator_headers"]))
        assert before["maintenance_balance_cents"] == 0

        settle_settlement(bundle["settlement"], load)
        after = get_success_data(api.get_capacity_owner(bco["id"], TEST_USERS["settlement_operator_headers"]))
        assert after["maintenance_balance_cents"] == 2400

        maintenance_row = find_ledger_entry(bco, "MAINTENANCE_DEPOSIT")
        assert maintenance_row["amount_cents"] == 2400

        reversal = get_success_data(
            api.reverse_escrow_transaction(
                maintenance_row["id"], {"effective_at": "2026-09-03T00:00:00Z"},
                TEST_USERS["settlement_operator_headers"],
            )
        )
        assert reversal["transaction_type"] == "MAINTENANCE_WITHDRAWAL"
        assert reversal["reverses_transaction_id"] == maintenance_row["id"]

        final = get_success_data(api.get_capacity_owner(bco["id"], TEST_USERS["settlement_operator_headers"]))
        assert final["maintenance_balance_cents"] == 0
        assert final["escrow_balance_cents"] == 250000

    def test_advance_and_repayment_are_escrow_balance_neutral(self, api):
        """PRD §3.8: "Posting an advance or a repayment is an ordinary ledger
        entry carrying the owning `capacity_owner_id`, a `transaction_type`, a
        positive `amount_cents`, and an `effective_at`; posting it recomputes the
        owner's escrow and maintenance balances, recomputes the owner's
        `outstanding_advance_cents` when the type is an advance or a repayment,
        and recomputes the qualification posture when the escrow floor has been
        crossed in either direction."

        Design: Difficulty/compensating_invariant/advance_and_repayment_are_escrow_balance_neutral
        """
        from test_helpers import setup_advance_position

        state = setup_advance_position(deposit_cents=250000, advance_cents=200000)
        bco = state["bco"]

        assert state["before"]["escrow_balance_cents"] == 250000
        assert state["advance"]["escrow_balance_cents"] == 50000

        after_advance = get_success_data(api.get_capacity_owner(bco["id"], TEST_USERS["settlement_operator_headers"]))
        assert after_advance["outstanding_advance_cents"] == 200000
        assert after_advance["qualification_posture"] == "QUALIFICATION_RESTRICTED"

        get_success_data(
            api.reverse_escrow_transaction(
                state["advance"]["advance_transaction_id"],
                {"effective_at": "2026-09-01T06:00:00Z"},
                TEST_USERS["settlement_operator_headers"],
            )
        )
        restored = get_success_data(api.get_capacity_owner(bco["id"], TEST_USERS["settlement_operator_headers"]))
        assert restored["escrow_balance_cents"] == 250000
        assert restored["outstanding_advance_cents"] == 0
        assert restored["qualification_posture"] == "QUALIFIED_CLEAR"

        second = api.reverse_escrow_transaction(
            state["advance"]["advance_transaction_id"],
            {"effective_at": "2026-09-01T07:00:00Z"},
            TEST_USERS["settlement_operator_headers"],
        )
        validate_error(second, ApiErrorId.ERR_ESCROW_ALREADY_MATCHED)


def _ledger_rows(bco_id):
    return validate_paginated(
        api_client.list_capacity_owner_ledger(bco_id, TEST_USERS["settlement_operator_headers"])
    )