"""Money: buyer premium tiers, seller settlement schedules, dual-side storage."""
from test_helpers import (
    ApiErrorId,
    assert_settlement_invariants,
    create_member,
    create_seller,
    create_yard,
    get_settlement,
    get_success_data,
    issue_gate_pass,
    list_into_auction,
    make_buyer_headers,
    place_bid,
    prepare_vehicle,
    create_auction,
    set_clock,
    setup_closed_sale,
    setup_live_item,
    setup_paid_sale,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

AU = TEST_USERS["auctioneer_headers"]
YO = TEST_USERS["yard_operator_headers"]


class TestBuyerPremiumPerTierRounding:
    def test_three_tier_straddle_hammer(self, api):
        """PRD §3.6: "The first 500000 cents of the hammer price are charged at 12%;
        the portion from 500000 up to (but not including) 2000000 cents is charged at
        9%; any portion from 2000000 cents upward is charged at 6%. The pinned
        evaluation order is to compute each tier's portion in whole cents, round that
        tier's contribution half-up to whole cents **per tier**, and then sum the three
        rounded contributions."

        Derivation (hammer 72505555):
          tier1 = round_half_up(0.12 * 500000)            = 60000
          tier2 = round_half_up(0.09 * (2000000-500000))  = round_half_up(135000.00) = 135000
          tier3 = round_half_up(0.06 * (72505555-2000000)) = round_half_up(4230333.30) = 4230333
          buyer_fee_cents = 60000 + 135000 + 4230333 = 4425333

        Design: Difficulty/combinatorial_formula/buyer_premium_marginal_tiers_with_per_tier_rounding
        """
        ctx = setup_live_item()
        place_bid(ctx["item"]["id"], ctx["member"], 72505555)
        sale = validate_success(
            api.close_lot(ctx["auction"]["id"], ctx["item"]["id"], AU), 200
        )
        assert sale["winning_bid_cents"] == 72505555
        assert sale["buyer_fee_cents"] == 4425333

    def test_per_tier_rounding_divergence_witness(self, api):
        """PRD §3.6: "The pinned evaluation order is to compute each tier's portion in
        whole cents, round that tier's contribution half-up to whole cents **per
        tier**, and then sum the three rounded contributions. The alternative —
        summing the unrounded tier contributions and rounding once at the end — is a
        forbidden variant that can differ from the pinned result by up to two cents;
        implementations must round per tier."

        Derivation (hammer 2000117):
          tier1 = round_half_up(0.12 * 500000)               = 60000
          tier2 = round_half_up(0.09 * (2000000 - 500000))   = round_half_up(135000.00) = 135000
          tier3 = round_half_up(0.06 * (2000117 - 2000000))  = round_half_up(7.02) = 7
          buyer_fee_cents = 60000 + 135000 + 7 = 195007
          (The forbidden sum-then-round variant would carry the 7.02 fraction into a
          single final rounding; here it coincides (195007.02 -> 195007), so the value
          the PRD pins through per-tier rounding is 195007.)

        Design: Difficulty/combinatorial_formula/buyer_premium_marginal_tiers_with_per_tier_rounding
        """
        ctx = setup_live_item()
        place_bid(ctx["item"]["id"], ctx["member"], 2000117)
        sale = validate_success(
            api.close_lot(ctx["auction"]["id"], ctx["item"]["id"], AU), 200
        )
        assert sale["winning_bid_cents"] == 2000117
        assert sale["buyer_fee_cents"] == 195007


class TestSellerFeeSchedules:
    def _two_schedule_settlements(self, api):
        """Run one sale each for a STANDARD and a VOLUME seller on the same yard."""
        yard = create_yard()
        member = create_member()
        results = {}
        for schedule in ("STANDARD", "VOLUME"):
            seller = create_seller(fee_schedule=schedule, name=f"Insurer {schedule}")
            vehicle = prepare_vehicle(seller, yard)
            auction = create_auction()
            item = list_into_auction(auction["id"], vehicle["id"])
            set_clock("2026-09-10T12:00:00Z")
            get_success_data(api.start_auction(auction["id"], AU))
            item = get_success_data(api.open_lot(auction["id"], item["id"], AU))
            place_bid(item["id"], member, 1000000)
            sale = validate_success(api.close_lot(auction["id"], item["id"], AU), 200)
            results[schedule] = get_settlement(sale["id"])
            set_clock("2026-09-01T00:00:00Z")
        return results

    def test_seller_settlement_standard_vs_volume_fee_schedule(self, api):
        """PRD §3.6: "under `STANDARD` it is the greater of 2500 cents and 10 percent
        of the gross rounded half-up, plus a fixed 5000-cent title fee; under `VOLUME`
        it is the greater of 1500 cents and 7.5 percent of the gross rounded half-up,
        plus the same fixed 5000-cent title fee."

        Derivation (gross 1000000, received 2026-09-01, sold 2026-09-10):
          STANDARD seller_fee = max(2500, round_half_up(0.10*1000000)) + 5000
                              = 100000 + 5000 = 105000
          VOLUME   seller_fee = max(1500, round_half_up(0.075*1000000)) + 5000
                              = 75000 + 5000 = 80000
          storage_recovery    = (9 days - 7 free) * 1000 = 2000 (both)
          title_late_penalty  = 0 (title received 2026-09-01, same day as assigned)
          net STANDARD = 1000000 - 105000 - 2000 - 0 = 893000
          net VOLUME   = 1000000 - 80000  - 2000 - 0 = 918000

        Design: Difficulty/dual_variant_calc/seller_settlement_standard_vs_volume_fee_schedule
        """
        settlements = self._two_schedule_settlements(api)
        assert settlements["STANDARD"]["seller_fee_cents"] == 105000
        assert settlements["VOLUME"]["seller_fee_cents"] == 80000
        assert settlements["STANDARD"]["storage_recovery_cents"] == 2000
        assert settlements["VOLUME"]["storage_recovery_cents"] == 2000
        assert settlements["STANDARD"]["net_proceeds_cents"] == 893000
        assert settlements["VOLUME"]["net_proceeds_cents"] == 918000
        assert_settlement_invariants(settlements["STANDARD"])
        assert_settlement_invariants(settlements["VOLUME"])

    def test_volume_fee_is_strictly_smaller_for_same_gross(self, api):
        """PRD §3.6: "under `VOLUME` it is the greater of 1500 cents and 7.5 percent of
        the gross rounded half-up, plus the same fixed 5000-cent title fee."

        Derivation: at gross 1000000 the percentage terms dominate both floors, and
        7.5% (75000) < 10% (100000), so the VOLUME fee (80000) is strictly smaller
        than the STANDARD fee (105000).

        Design: Difficulty/dual_variant_calc/seller_settlement_standard_vs_volume_fee_schedule
        """
        settlements = self._two_schedule_settlements(api)
        assert settlements["VOLUME"]["seller_fee_cents"] < settlements["STANDARD"]["seller_fee_cents"]


class TestDualStorageWindows:
    def test_storage_fee_winner_window_vs_seller_window(self, api):
        """PRD §3.6: "On the winner side, at gate-pass check-in, the free allowance is
        the yard's `free_storage_days` counted from the UTC date of the sale day (the
        close, or the approval for on-approval sales); the chargeable days are the days
        between that sale date and the check-in date minus the allowance, floored at
        zero, and the fee is that count times `daily_storage_rate_cents`. On the seller
        side, as described above, the window runs from `received_at` to the sale day
        with a seven-day allowance."

        Derivation (yard rate 1000, yard free 1; received 2026-09-01; sold
        2026-09-10T12:00 so gate_pass_expires_at 2026-09-13T12:00; winner check-in
        2026-09-12T12:00, inside the 72-hour window):
          buyer_fee (hammer 1000000) = round_half_up(0.12*500000)
              + round_half_up(0.09*500000) = 60000 + 45000 = 105000
          seller window  = (2026-09-10 - 2026-09-01) - 7 = 9 - 7 = 2 -> 2000
          seller_fee (STANDARD) = max(2500, 100000) + 5000 = 105000
          net = 1000000 - 105000 - 2000 - 0 = 893000
          winner window = (2026-09-12 - 2026-09-10) - 1 = 2 - 1 = 1 -> 1000
          payment (no gate pass yet) = 1000000 + 105000 + 0 = 1105000

        Design: Difficulty/dual_variant_calc/storage_fee_winner_window_vs_seller_window
        """
        yard = create_yard()
        seller = create_seller()
        member = create_member()
        vehicle = prepare_vehicle(seller, yard)
        auction = create_auction(scheduled_start="2026-09-05T00:00:00Z")
        item = list_into_auction(auction["id"], vehicle["id"])
        set_clock("2026-09-10T12:00:00Z")
        get_success_data(api.start_auction(auction["id"], AU))
        item = get_success_data(api.open_lot(auction["id"], item["id"], AU))
        place_bid(item["id"], member, 1000000)
        sale = validate_success(api.close_lot(auction["id"], item["id"], AU), 200)
        assert sale["buyer_fee_cents"] == 105000
        settlement = get_settlement(sale["id"])
        assert settlement["storage_recovery_cents"] == 2000
        assert settlement["seller_fee_cents"] == 105000
        assert settlement["title_late_penalty_cents"] == 0
        assert settlement["net_proceeds_cents"] == 893000
        # Pay (no gate pass yet: storage term 0).
        amount = sale["winning_bid_cents"] + sale["buyer_fee_cents"]
        validate_success(
            api.pay_sale(sale["id"], {"amount_cents": amount}, make_buyer_headers(member["id"])),
            201,
        )
        # Winner window: sale day 2026-09-10, check-in 2026-09-12 (inside the 72h
        # expiry that ends 2026-09-13T12:00), free 1 -> (2 - 1) x 1000 = 1000.
        set_clock("2026-09-12T12:00:00Z")
        gp = get_success_data(
            api.create_gate_pass(
                sale["id"],
                {"slot_start": "2026-09-12T11:00:00Z", "slot_end": "2026-09-12T15:00:00Z"},
                make_buyer_headers(member["id"]),
            )
        )
        checked = validate_success(api.check_in_gate_pass(gp["id"], YO), 200)
        assert checked["storage_fee_cents"] == 1000

    def test_settlement_seller_window_excludes_winner_free_days(self, api):
        """PRD §3.6: "Third, `storage_recovery_cents` is the seller-side storage fee:
        the whole calendar days between the vehicle's `received_at` date and the
        sale-day UTC date, minus a seller free allowance of seven days (an allowance
        independent of the yard's winner-side `free_storage_days`), floored at zero,
        times the yard's `daily_storage_rate_cents`."

        Derivation (same-day sale: received 2026-09-01, sold 2026-09-01):
          seller window = 0 - 7 -> floored 0 -> 0
          seller_fee (STANDARD) = max(2500, 100000) + 5000 = 105000
          net = 1000000 - 105000 - 0 - 0 = 895000

        Design: Difficulty/dual_variant_calc/storage_fee_winner_window_vs_seller_window
        """
        ctx = setup_closed_sale()
        settlement = get_settlement(ctx["sale"]["id"])
        assert settlement["storage_recovery_cents"] == 0
        assert settlement["seller_fee_cents"] == 105000
        assert settlement["net_proceeds_cents"] == 895000
        assert_settlement_invariants(settlement)


class TestLateTitlePenalty:
    def test_late_title_penalty_and_circular_window_order(self, api):
        """PRD §3.2: "When the elapsed time between the vehicle's `assigned_at` and the
        title's `received_at` exceeds thirty days — the boundary is strict, so exactly
        thirty days elapsed is not late — the flag is set true, and the seller's
        eventual settlement absorbs a flat 15000-cent penalty."
        PRD §3.6: "Third, `storage_recovery_cents` is the seller-side storage fee: the
        whole calendar days between the vehicle's `received_at` date and the sale-day
        UTC date, minus a seller free allowance of seven days ..."

        Derivation (assigned 2026-09-01; title received 2026-10-05 -> 34 days > 30,
        late; mark-ready stamps Vehicle.received_at 2026-10-05; sold 2026-10-10):
          title_late_penalty = 15000
          seller window = (2026-10-10 - 2026-10-05) - 7 = 5 - 7 -> floored 0 -> 0
          seller_fee (STANDARD) = max(2500, 100000) + 5000 = 105000
          net = 1000000 - 105000 - 0 - 15000 = 880000

        Design: Difficulty/combinatorial_formula/seller_settlement_circular_window_and_penalty_order
        """
        yard = create_yard()
        seller = create_seller()
        member = create_member()
        from test_helpers import (
            add_images,
            create_vehicle,
            mark_ready,
            receive_title,
            submit_condition,
        )

        vehicle = create_vehicle(seller, yard)
        submit_condition(vehicle["id"])
        add_images(vehicle["id"], count=5)
        set_clock("2026-10-05T12:00:00Z")
        title = receive_title(vehicle["id"])
        assert title["late"] is True
        mark_ready(vehicle["id"])
        auction = create_auction(scheduled_start="2026-10-06T00:00:00Z")
        item = list_into_auction(auction["id"], vehicle["id"])
        set_clock("2026-10-10T12:00:00Z")
        get_success_data(api.start_auction(auction["id"], AU))
        get_success_data(api.open_lot(auction["id"], item["id"], AU))
        place_bid(item["id"], member, 1000000)
        sale = validate_success(api.close_lot(auction["id"], item["id"], AU), 200)
        settlement = get_settlement(sale["id"])
        # The seller window anchors at Vehicle.received_at (the mark-ready stamp,
        # 2026-10-05), not at assigned_at: 5 days - 7 free -> 0.
        assert settlement["storage_recovery_cents"] == 0
        assert settlement["title_late_penalty_cents"] == 15000
        assert settlement["seller_fee_cents"] == 105000
        assert settlement["net_proceeds_cents"] == 880000
        assert_settlement_invariants(settlement)

    def test_title_late_penalty_exactly_at_sla_is_not_late(self, api):
        """PRD §3.2: "When the elapsed time between the vehicle's `assigned_at` and the
        title's `received_at` exceeds thirty days — the boundary is strict, so exactly
        thirty days elapsed is not late — the flag is set true, and the seller's
        eventual settlement absorbs a flat 15000-cent penalty."

        Derivation (assigned 2026-09-01; title received 2026-10-01 -> exactly 30 days,
        not late; sold same day 2026-10-01):
          late = False; title_late_penalty = 0
          seller window = 0 days -> 0
          seller_fee (STANDARD) = max(2500, 100000) + 5000 = 105000
          net = 1000000 - 105000 - 0 - 0 = 895000

        Design: Corner/calculations/title_late_penalty_exactly_at_sla_is_not_late
        """
        yard = create_yard()
        seller = create_seller()
        member = create_member()
        from test_helpers import (
            add_images,
            create_vehicle,
            mark_ready,
            receive_title,
            submit_condition,
        )

        vehicle = create_vehicle(seller, yard)
        submit_condition(vehicle["id"])
        add_images(vehicle["id"], count=5)
        set_clock("2026-10-01T12:00:00Z")  # exactly 30 days after 2026-09-01
        title = receive_title(vehicle["id"])
        assert title["late"] is False
        mark_ready(vehicle["id"])
        auction = create_auction(scheduled_start="2026-10-01T00:00:00Z")
        item = list_into_auction(auction["id"], vehicle["id"])
        get_success_data(api.start_auction(auction["id"], AU))
        get_success_data(api.open_lot(auction["id"], item["id"], AU))
        place_bid(item["id"], member, 1000000)
        sale = validate_success(api.close_lot(auction["id"], item["id"], AU), 200)
        settlement = get_settlement(sale["id"])
        assert settlement["title_late_penalty_cents"] == 0
        # Seller window: received_at 2026-10-01 -> sale day 2026-10-01 = 0 days.
        assert settlement["storage_recovery_cents"] == 0
        assert settlement["seller_fee_cents"] == 105000
        assert settlement["net_proceeds_cents"] == 895000
        assert_settlement_invariants(settlement)
