"""Party deposit/refund variants and final-bill rounding (queue A: dual_variant_calc,
combinatorial_formula; queue B: calculations deposit corner)."""
from test_helpers import (
    MANAGER,
    add_party_guests,
    complete_guest_session,
    create_customer,
    create_party,
    create_staff,
    create_store,
    make_customer_headers,
    pay_party_deposit,
    set_clock,
    setup_confirmed_party,
    validate_success,
)


class TestPartyDepositQuoteVsCancelRefund:
    def test_ultimate_quote_floor_binds_at_twelve_guests(self, api):
        """PRD §3.6: "For `ULTIMATE` parties the deposit is the greater of two values:
        the guest count times 1000 cents per guest, or a floor of 20000 cents."

        Design: Difficulty/dual_variant_calc/party_deposit_quote_floor_vs_cancel_honored_refund
        """
        store = create_store(name="Flagship", party_room_count=2)
        create_staff(store["id"], role_title="PARTY_HOST", display_name="Host Hana")
        customer = create_customer(email="c1@example.com", full_name="Casey One")
        set_clock("2026-10-01T00:00:00Z")
        party = create_party(
            customer,
            store["id"],
            party_start="2026-10-10T18:00:00Z",
            guest_count=12,
            package_tier="ULTIMATE",
            staffing_mode="STAFF_HOSTED",
        )
        assert party["deposit_amount_cents"] == 20000, (
            f"ULTIMATE quote at 12 guests: floor 20000 must dominate 12*1000=12000, "
            f"got {party['deposit_amount_cents']}"
        )

    def test_cancel_refund_uses_honored_headcount_not_quote_tier(self, api):
        """PRD §3.7: "otherwise the refund is 1000 cents multiplied by the smaller of
        the guest count booked at quote time and the honored count, where the honored
        count is the number of the reservation's guests whose status is not `NO_SHOW`
        at cancel time. The refund is recorded as a negative adjustment to
        `paid_amount_cents`."

        Design: Difficulty/dual_variant_calc/party_deposit_quote_floor_vs_cancel_honored_refund
        """
        store = create_store(name="Flagship", party_room_count=2)
        create_staff(store["id"], role_title="PARTY_HOST", display_name="Host Hana")
        customer = create_customer(email="c1@example.com", full_name="Casey One")
        set_clock("2026-10-01T00:00:00Z")
        party = create_party(
            customer,
            store["id"],
            party_start="2026-10-10T18:00:00Z",
            guest_count=12,
            package_tier="ULTIMATE",
            staffing_mode="STAFF_HOSTED",
        )
        assert party["deposit_amount_cents"] == 20000
        party = pay_party_deposit(party, customer["id"])
        add_party_guests(party["id"], customer["id"], 9, confirm=True, name_prefix="G")
        cancelled = validate_success(
            api.cancel_party(party["id"], make_customer_headers(customer["id"]))
        )
        assert cancelled["status"] == "CANCELLED"
        # honored = 9 (none NO_SHOW); refund = min(12, 9) * 1000 = 9000
        assert cancelled["paid_amount_cents"] == 20000 - 9000, (
            f"expected paid_amount_cents 11000 after 9000 refund, got "
            f"{cancelled['paid_amount_cents']}"
        )


class TestPartyFinalAmountDue:
    def test_per_line_rounding_then_summation(self, api):
        """PRD §3.7: "each billable guest — those in `CONFIRMED` or `ATTENDED` status —
        is charged the tier's per-guest price (1899 cents for `BASIC`, 4299 cents for
        `CELEBRATION`, 7999 cents for `ULTIMATE`) plus a 15 percent service charge
        rounded half up to the nearest cent on that line. The per-line amounts are
        then summed into a subtotal, and the previously collected `deposit_amount_cents`
        is subtracted to produce `final_amount_due_cents`."

        Design: Difficulty/combinatorial_formula/party_final_per_line_rounding_before_summation
        """
        env = setup_confirmed_party(
            guest_count=12,
            confirmed_guests=12,
            package_tier="CELEBRATION",
            party_start="2026-10-20T18:00:00Z",
            clock_at_booking="2026-10-10T00:00:00Z",
            store_name="Party Plaza",
            party_room_count=2,
        )
        customer = env["customer"]
        for entry in env["sessions"]:
            assert entry["session_id"], "auto-confirm must create a session per confirmed guest"
            complete_guest_session(entry["session_id"], customer["id"])
        set_clock("2026-10-20T20:00:00Z")
        finalized = validate_success(api.finalize_party(env["party"]["id"], MANAGER))
        assert finalized["status"] == "COMPLETED"
        # 12 CELEBRATION lines: 4299 + round_half_up(4299*0.15)=645 -> 4944 each;
        # subtotal 59328; minus deposit 10000.
        assert finalized["final_amount_due_cents"] == 59328 - 10000, (
            f"expected final_amount_due_cents 49328, got {finalized['final_amount_due_cents']}"
        )

    def test_per_line_rounding_diverges_from_sum_then_round(self, api):
        """PRD §2.6: "Where a percentage is applied (the party service charge and the
        consignment commission), the result is rounded half up to the nearest whole
        cent, and — critically for party billing — rounding is applied per guest line
        before any summation. The rejected alternative is summing raw amounts and
        rounding once at the end."

        Design: Difficulty/combinatorial_formula/party_final_per_line_rounding_before_summation
        """
        # 10 BASIC guests: per-line 1899 + round(1899*0.15)=285 -> 2184 each,
        # subtotal 21840; sum-then-round would give round(18990*1.15)=21839.
        env = setup_confirmed_party(
            guest_count=10,
            confirmed_guests=10,
            package_tier="BASIC",
            party_start="2026-10-20T18:00:00Z",
            clock_at_booking="2026-10-10T00:00:00Z",
            store_name="Rounding Plaza",
            party_room_count=2,
        )
        customer = env["customer"]
        for entry in env["sessions"]:
            assert entry["session_id"]
            complete_guest_session(entry["session_id"], customer["id"])
        set_clock("2026-10-20T20:00:00Z")
        finalized = validate_success(api.finalize_party(env["party"]["id"], MANAGER))
        assert finalized["status"] == "COMPLETED"
        assert finalized["final_amount_due_cents"] == 21840 - 10000, (
            f"expected final_amount_due_cents 11840 (per-line rounding), got "
            f"{finalized['final_amount_due_cents']}"
        )


class TestDepositCorner:
    def test_ultimate_deposit_floor_dominates_per_guest_product(self, api):
        """PRD §3.6: "For `ULTIMATE` parties the deposit is the greater of two values:
        the guest count times 1000 cents per guest, or a floor of 20000 cents."

        Design: Corner/calculations/ultimate_deposit_uses_floor_when_per_guest_below_floor
        """
        store = create_store(name="Floor Store", party_room_count=1)
        customer = create_customer(email="floor@example.com", full_name="Floor F")
        set_clock("2026-10-01T00:00:00Z")
        party = create_party(
            customer,
            store["id"],
            party_start="2026-10-10T18:00:00Z",
            guest_count=12,
            package_tier="ULTIMATE",
            staffing_mode="SELF_GUIDED",
        )
        assert party["deposit_amount_cents"] == 20000, (
            f"floor 20000 must dominate 12*1000=12000, got {party['deposit_amount_cents']}"
        )
