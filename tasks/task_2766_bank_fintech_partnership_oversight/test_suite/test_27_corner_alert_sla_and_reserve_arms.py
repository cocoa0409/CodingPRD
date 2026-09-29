"""Corner cases of the alert hour constants, the three reserve arms, the
contractual clamp and the fee/reserve variant selection."""
from test_helpers import (
    PO,
    api_client,
    assert_same_instant,
    clear_variance,
    create_batch,
    create_partner,
    fund_batch,
    post_ledger_entry,
    raise_alert,
    read_custody_account,
    read_batch,
    read_partner,
    reconcile_batch,
    seed_reserve_balance,
    setup_contracted_partner,
    setup_live_partner,
    validate_paginated,
    validate_success,
)

NOTE = "the monitoring rule fired on this partner's inbound flow overnight"


class TestAlertDeadlineHours:
    def test_all_four_alert_types_add_wall_clock_hours_with_no_weekend_adjustment(self):
        """The response deadline runs on wall-clock hours from `triggered_at`, with no calendar or
        business-day adjustment — alert SLAs do not stop for weekends. A `SANCTIONS_HIT` allows 24
        hours, `STRUCTURING` allows 72 hours (three days), `VELOCITY` allows 120 hours (five days),
        and `ACH_RETURN_RATE` allows 168 hours (a full week).

        Design: Corner/calculations/alert_sla_due_at_applies_the_per_type_hour_constant_with_no_weekend_adjustment
        """
        partner = create_partner(legal_name="Saltmarsh Pay Inc")
        saturday = "2026-08-01T00:00:00Z"
        expected = {
            "ACH_RETURN_RATE": "2026-08-08T00:00:00Z",
            "VELOCITY": "2026-08-06T00:00:00Z",
            "STRUCTURING": "2026-08-04T00:00:00Z",
            "SANCTIONS_HIT": "2026-08-02T00:00:00Z",
        }
        for alert_type, due in expected.items():
            alert = raise_alert(
                partner["id"],
                alert_type=alert_type,
                triggered_at=saturday,
                transaction_volume_cents=750_000,
                detection_note=NOTE,
            )
            assert alert["alert_type"] == alert_type
            assert alert["sla_breach_count"] == 0
            assert_same_instant(alert["sla_due_at"], due, f"{alert_type} sla_due_at")
        assert expected["SANCTIONS_HIT"] != expected["ACH_RETURN_RATE"], (
            "the four hour constants are genuinely different"
        )


class TestTrailingVolumeArm:
    def test_the_trailing_volume_arm_ignores_out_of_window_and_unreconciled_batches(self):
        """The second is the partner's trailing settlement volume multiplied by 150 basis points,
        divided by 10000 and floored to whole cents, where trailing settlement volume is the sum of
        `gross_settlement_cents` over the partner's settlement batches whose `reconciliation_status`
        is `MATCHED` or `VARIANCE_CLEARED` and whose `window_end` is strictly later than the logical
        clock less ninety days and no later than the logical clock.

        Design: Corner/calculations/required_reserve_selects_the_trailing_volume_arm_and_ignores_out_of_window_or_unreconciled_batches
        """
        ctx = setup_contracted_partner(
            partner_overrides={"legal_name": "Cindermill Pay Inc"},
            agreement_overrides={"reserve_requirement_bps": 500},
        )
        partner_id = ctx["partner"]["id"]
        seed_reserve_balance(partner_id, ctx["reserve"], 312_500)
        assert read_partner(partner_id)["reserve_shortfall_cents"] == 0

        def _window(start, end):
            return create_batch(
                partner_id,
                window_start=start,
                window_end=end,
                gross_settlement_cents=100_000_000,
                interchange_cents=0,
                returns_cents=0,
                partner_reported_net_cents=100_000_000,
            )

        stale = _window("2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")
        qualifying = _window("2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")
        ahead = _window("2026-08-01T00:00:00Z", "2026-08-15T00:00:00Z")

        assert reconcile_batch(qualifying["id"], 100_000_000)["reconciliation_status"] == "MATCHED"
        # A one-cent movement is what makes the reserve pass run and publish the arm.
        validate_success(
            post_ledger_entry(partner_id, ctx["fbo"], "VARIANCE_ADJUSTMENT", 1), 201
        )
        first = read_partner(partner_id)
        assert first["required_reserve_cents"] == 1_500_000, (
            "only the batch whose window_end sits exactly at the clock qualifies, and 150 bps "
            f"of its 100000000 gross beats both the balance arm and the 250000 floor, got "
            f"{first['required_reserve_cents']}"
        )
        assert first["reserve_shortfall_cents"] == 1_187_500
        assert first["oversight_posture"] == "HEIGHTENED"

        assert reconcile_batch(ahead["id"], 100_000_000)["reconciliation_status"] == "MATCHED"
        validate_success(
            post_ledger_entry(partner_id, ctx["fbo"], "VARIANCE_ADJUSTMENT", 1), 201
        )
        second = read_partner(partner_id)
        assert second["required_reserve_cents"] == 1_875_000, (
            "the same single qualifying batch gives a base of 1500000, now scaled by the "
            f"HEIGHTENED multiplier of 1.25, got {second['required_reserve_cents']}"
        )
        assert second["required_reserve_cents"] != 3_750_000, (
            "counting the batch whose window_end is past the clock would double the arm"
        )
        assert second["required_reserve_cents"] != 5_625_000, (
            "counting the UNRECONCILED batch as well would triple it"
        )
        assert second["reserve_shortfall_cents"] == 1_562_500
        assert read_batch(stale["id"])["reconciliation_status"] == "UNRECONCILED"


class TestContractualCeilingClamp:
    def test_the_ceiling_is_applied_after_the_posture_multiplier(self):
        """`required_reserve_cents` is the smaller of that scaled figure and the agreement's
        `max_end_user_balance_cents` — the contractual ceiling wins. Nothing is rounded after that
        minimum is taken.

        Design: Corner/calculations/required_reserve_is_clamped_by_the_agreements_max_end_user_balance_ceiling
        """
        ctx = setup_contracted_partner(
            partner_overrides={"legal_name": "Foundry Wallet Inc"},
            agreement_overrides={
                "max_end_user_balance_cents": 300_000,
                "reserve_requirement_bps": 500,
            },
        )
        partner_id = ctx["partner"]["id"]
        at_exec = read_partner(partner_id)
        assert at_exec["required_reserve_cents"] == 250_000, (
            "the absolute floor is already below the 300000 ceiling"
        )
        assert at_exec["reserve_shortfall_cents"] == 250_000
        assert at_exec["oversight_posture"] == "HEIGHTENED"

        # A variance adjustment is not an end-user credit, so the balance cap does not guard it.
        validate_success(
            post_ledger_entry(partner_id, ctx["fbo"], "VARIANCE_ADJUSTMENT", 8_100_000), 201
        )
        assert read_custody_account(ctx["fbo"]["id"])["balance_cents"] == 8_100_000

        clamped = read_partner(partner_id)
        assert clamped["required_reserve_cents"] == 300_000, (
            "the balance arm gives 405000, the HEIGHTENED multiplier scales it to 506250, and "
            f"the 300000 ceiling then wins, got {clamped['required_reserve_cents']}"
        )
        assert clamped["required_reserve_cents"] != 506_250, "the clamp is applied after scaling"
        assert clamped["required_reserve_cents"] != 405_000, "the clamp is applied after scaling"
        assert clamped["reserve_shortfall_cents"] == 300_000
        assert clamped["oversight_posture"] == "HEIGHTENED"


def _live_book():
    return setup_live_partner(
        partner_overrides={
            "legal_name": "Windrow Cards Inc",
            "business_model": "CARD_ISSUING",
            "end_user_account_count": 9_000,
        },
        agreement_overrides={"reserve_requirement_bps": 500},
        fbo_balance_cents=20_000_000,
        reserve_balance_cents=1_250_000,
    )


class TestFlatFeeTierOnGross:
    def test_one_extra_cent_of_gross_crosses_the_tier_and_lowers_the_fee(self):
        """First, the sponsor-bank fee tier is selected **on gross volume, before any deduction**,
        and the selected rate is flat across the whole gross rather than marginal. From 10,000,000
        cents up to but not including 100,000,000 cents (one million dollars) the rate is 32 basis
        points.

        Design: Corner/calculations/the_bank_fee_tier_is_flat_on_gross_so_a_larger_batch_can_carry_a_smaller_fee
        """
        ctx = _live_book()
        partner_id = ctx["partner"]["id"]

        def _batch(start, end, gross):
            batch = create_batch(
                partner_id,
                window_start=start,
                window_end=end,
                gross_settlement_cents=gross,
                interchange_cents=0,
                returns_cents=0,
                partner_reported_net_cents=gross,
            )
            reconcile_batch(batch["id"], gross)
            return batch

        under = _batch("2026-07-01T00:00:00Z", "2026-07-15T00:00:00Z", 9_999_999)
        at_floor = _batch("2026-07-15T00:00:00Z", "2026-07-29T00:00:00Z", 10_000_000)

        t1 = fund_batch(under["id"], funding_reference="WIRE-T1")
        assert t1["bank_fee_bps_applied"] == 45
        assert t1["bank_fee_cents"] == 69_999, (
            "floor(9999999*45/10000) is 44999 and the 25000 base fee is added after, got "
            f"{t1['bank_fee_cents']}"
        )
        assert t1["settlement_base_cents"] == 9_999_999
        assert t1["reserve_funding_cents"] == 499_999
        assert t1["net_to_partner_cents"] == 9_430_001
        assert t1["shortfall_carry_cents"] == 0

        t2 = fund_batch(at_floor["id"], funding_reference="WIRE-T2")
        assert t2["bank_fee_bps_applied"] == 32, "gross exactly at the tier floor takes 32 bps"
        assert t2["bank_fee_cents"] == 57_000
        assert t2["settlement_base_cents"] == 10_000_000
        assert t2["reserve_funding_cents"] == 500_000
        assert t2["net_to_partner_cents"] == 9_443_000
        assert t2["bank_fee_cents"] < t1["bank_fee_cents"], (
            "one cent more gross carries 12999 cents less fee because the rate is flat"
        )

        partner = read_partner(partner_id)
        assert partner["cumulative_paid_out_cents"] == 18_873_001
        assert partner["cumulative_bank_fee_cents"] == 126_999


class TestReserveBasisVariant:
    def test_a_cleared_variance_routes_reserve_off_the_corrected_base(self):
        """For a batch that is `VARIANCE_CLEARED`, the basis is `settlement_base_cents` instead,
        multiplied by the same `reserve_requirement_bps`, divided by 10000 and floored to whole
        cents. If the batch is still `UNFUNDED`, nothing further happens to the ledger — the
        corrected base will simply be used when the batch is eventually funded.

        Design: Corner/calculations/the_reserve_basis_variant_diverges_between_a_matched_and_a_variance_cleared_batch
        """
        ctx = _live_book()
        partner_id = ctx["partner"]["id"]

        def _batch(start, end):
            return create_batch(
                partner_id,
                window_start=start,
                window_end=end,
                gross_settlement_cents=8_000_000,
                interchange_cents=200_000,
                returns_cents=100_000,
                partner_reported_net_cents=8_100_000,
            )

        matched = _batch("2026-07-01T00:00:00Z", "2026-07-15T00:00:00Z")
        varied = _batch("2026-07-15T00:00:00Z", "2026-07-29T00:00:00Z")

        m_recon = reconcile_batch(matched["id"], 8_100_000)
        assert m_recon["reconciliation_status"] == "MATCHED"
        assert m_recon["variance_cents"] == 0

        v_recon = reconcile_batch(varied["id"], 8_150_000)
        assert v_recon["reconciliation_status"] == "VARIANCE_OPEN"
        assert v_recon["variance_cents"] == 50_000
        assert read_partner(partner_id)["unreconciled_variance_cents"] == 50_000

        v_cleared = clear_variance(
            varied["id"], 50_000, root_cause_note="a late interchange file landed after cut-off"
        )
        assert v_cleared["reconciliation_status"] == "VARIANCE_CLEARED"
        assert v_cleared["settlement_base_cents"] == 8_150_000
        assert read_partner(partner_id)["unreconciled_variance_cents"] == 0

        entries, _meta = validate_paginated(
            api_client.list_ledger_entries(PO, {"settlement_batch_id": varied["id"]})
        )
        assert entries == [], (
            "clearing an UNFUNDED batch books no compensating entry because no money has moved"
        )

        m_funded = fund_batch(matched["id"], funding_reference="WIRE-M")
        v_funded = fund_batch(varied["id"], funding_reference="WIRE-V")

        assert m_funded["bank_fee_cents"] == 61_000
        assert v_funded["bank_fee_cents"] == 61_000, "the fee reads gross alone, which is identical"
        assert m_funded["settlement_base_cents"] == 8_100_000
        assert m_funded["reserve_funding_cents"] == 400_000
        assert m_funded["net_to_partner_cents"] == 7_639_000
        assert v_funded["settlement_base_cents"] == 8_150_000
        assert v_funded["reserve_funding_cents"] == 407_500, (
            f"500 bps of the corrected base of 8150000, got {v_funded['reserve_funding_cents']}"
        )
        assert v_funded["net_to_partner_cents"] == 7_681_500
        assert v_funded["net_to_partner_cents"] - m_funded["net_to_partner_cents"] == 42_500
        assert v_funded["reserve_funding_cents"] - m_funded["reserve_funding_cents"] == 7_500
