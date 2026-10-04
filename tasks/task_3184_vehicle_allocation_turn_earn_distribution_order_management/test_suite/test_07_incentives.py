"""Incentive programs and the marginal-tier accrual ledger (PRD §3.12)."""
from test_helpers import (
    TEST_USERS,
    create_carrier,
    create_shipment_payload,
    create_volume_bonus_program,
    get_accrual,
    get_success_data,
    seed_built_order,
    setup_dealer_run,
    validate_success,
)

ALLOC = TEST_USERS["allocator_headers"]
LOGIS = TEST_USERS["logistics_headers"]


def _deliver_seeded(api, seeded_order, pickup_week, carrier=None):
    carrier = carrier or create_carrier()
    shipment = get_success_data(api.create_shipment(
        create_shipment_payload(seeded_order["id"], carrier["id"], pickup_week=pickup_week), LOGIS
    ))
    get_success_data(api.pickup_shipment(shipment["id"], LOGIS))
    get_success_data(api.deliver_shipment(shipment["id"], LOGIS))


class TestVolumeBonusFreeze:
    def test_close_freezes_final_accrual(self, api):
        """PRD §3.12: "The final variant runs at program close and freezes the per-dealer ledger." and "closing transitions the program to `CLOSED`, freezes the final accrual per dealer as a single `amount_cents` figure".
        PRD §3.12: "Sales from `tier1_threshold + 1` up to and including `tier2_threshold` pay `tier1_bonus_cents` per unit."

        Design: Difficulty/dual_variant_calc/incentive_accrual_provisional_vs_final_freeze
        """
        fx = setup_dealer_run(num_dealers=1, base_units=20)
        dealer = fx["dealers"][0]
        line = fx["model_line"]
        run = fx["run"]
        prog = create_volume_bonus_program(line["id"], tier1_threshold=3, tier1_bonus_cents=500,
                                           tier2_threshold=5, tier2_bonus_cents=900)
        get_success_data(api.set_clock("2026-10-01T00:00:00Z", ALLOC))
        carrier = create_carrier(weekly_capacity=10)
        for _ in range(4):
            seeded = seed_built_order(dealer["id"], line["id"], run["id"], scheduled_week="2026-W40")
            _deliver_seeded(api, seeded, "2026-W40", carrier=carrier)
        closed = validate_success(api.close_incentive_program(prog["id"], ALLOC), 200)
        assert closed["status"] == "CLOSED"
        accrual = get_accrual(prog["id"], dealer["id"])
        # S = 4 deliveries: (min(4,5) - 3) * 500 = 500 cents, frozen at close.
        assert accrual["amount_cents"] == 500
        assert accrual["variant"] == "final"

    def test_delivery_after_close_does_not_change_frozen_figure(self, api):
        """PRD §3.12: "closing transitions the program to `CLOSED`, freezes the final accrual per dealer as a single `amount_cents` figure, and rejects any further accrual mutation with `ERR_PROGRAM_CLOSED`."

        Design: Difficulty/dual_variant_calc/incentive_accrual_provisional_vs_final_freeze
        """
        fx = setup_dealer_run(num_dealers=1, base_units=20)
        dealer = fx["dealers"][0]
        line = fx["model_line"]
        run = fx["run"]
        prog = create_volume_bonus_program(line["id"], tier1_threshold=3, tier1_bonus_cents=500,
                                           tier2_threshold=5, tier2_bonus_cents=900)
        get_success_data(api.set_clock("2026-10-01T00:00:00Z", ALLOC))
        carrier = create_carrier(weekly_capacity=10)
        for _ in range(4):
            seeded = seed_built_order(dealer["id"], line["id"], run["id"], scheduled_week="2026-W40")
            _deliver_seeded(api, seeded, "2026-W40", carrier=carrier)
        validate_success(api.close_incentive_program(prog["id"], ALLOC), 200)
        frozen = get_accrual(prog["id"], dealer["id"])["amount_cents"]
        # A 5th in-window delivery lands after close; the frozen figure must not move.
        seeded = seed_built_order(dealer["id"], line["id"], run["id"], scheduled_week="2026-W40")
        _deliver_seeded(api, seeded, "2026-W40", carrier=carrier)
        assert get_accrual(prog["id"], dealer["id"])["amount_cents"] == frozen


class TestMarginalTierStraddle:
    def test_volume_bonus_marginal_tiers(self, api):
        """PRD §3.12: "Sales up to and including `tier1_threshold` pay nothing — the first tier pays only on volume strictly above the threshold. Sales from `tier1_threshold + 1` up to and including `tier2_threshold` pay `tier1_bonus_cents` per unit. Sales beyond `tier2_threshold` pay `tier2_bonus_cents` per unit."

        Design: Corner/calculations/incentive_marginal_tier_straddle
        """
        fx = setup_dealer_run(num_dealers=1, base_units=20)
        dealer = fx["dealers"][0]
        line = fx["model_line"]
        run = fx["run"]
        prog = create_volume_bonus_program(line["id"], tier1_threshold=3, tier1_bonus_cents=500,
                                           tier2_threshold=5, tier2_bonus_cents=900)
        get_success_data(api.set_clock("2026-10-01T00:00:00Z", ALLOC))
        carrier = create_carrier(weekly_capacity=10)
        for _ in range(6):
            seeded = seed_built_order(dealer["id"], line["id"], run["id"], scheduled_week="2026-W40")
            _deliver_seeded(api, seeded, "2026-W40", carrier=carrier)
        accrual = get_accrual(prog["id"], dealer["id"])
        # S = 6: (5-3)*500 + (6-5)*900 = 1000 + 900 = 1900 (marginal straddle).
        assert accrual["amount_cents"] == 1900
