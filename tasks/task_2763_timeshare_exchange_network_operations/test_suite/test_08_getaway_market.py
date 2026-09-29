"""The getaway salvage market: the sweep, the price, the rental and the pull-back."""

from test_helpers import (
    ApiErrorId,
    OPERATOR_HEADERS,
    assert_getaway_offer,
    assert_instant_equals,
    bank_deposit,
    factories,
    list_getaway_offers,
    list_ledger_entries,
    make_member_headers,
    read_deposit,
    read_getaway_offer,
    read_member,
    run_matching,
    set_clock,
    setup_banked_week,
    setup_market,
    setup_prorated_cancellation,
    validate_error,
    validate_success,
    withdraw_getaway,
)

CANONICAL_WINDOW = {
    "window_start_date": "2027-06-01",
    "window_end_date": "2027-06-30",
}


def _swept_week():
    """One never-requested ONE_BR week pushed onto the cash market by a run."""
    market = setup_banked_week(check_in_date="2027-06-15")
    assert market["deposit"]["awarded_power"] == 82
    assert_instant_equals(
        market["deposit"]["expires_at"], "2029-06-14T00:00:00Z", "expires_at"
    )
    set_clock("2029-05-15T00:00:00Z")
    market["run"] = run = run_matching("sweep the ageing inventory")
    offers, meta = list_getaway_offers(deposit_id=market["deposit"]["id"])
    assert meta["total_count"] == 1
    market["offer"] = offers[0]
    market["run_id"] = run["id"]
    return market


def _listed_after_prorated_cancellation():
    """The canonical chain cancelled 29 days out, so the week is on the market."""
    scenario = setup_prorated_cancellation(member_count=3, **CANONICAL_WINDOW)
    assert scenario["cancelled_confirmation"]["restoration_variant"] == "PRORATED_RESTORE"
    week = read_deposit(scenario["dep_m1"]["id"])
    assert week["restoration_haircut_power"] == 21
    assert week["rental_status"] == "LISTED_GETAWAY"
    scenario["m3"] = scenario["members"][2]
    assert scenario["offer"] is not None
    assert scenario["offer"]["list_price_cents"] == 50369
    assert scenario["offer"]["urgency_discount_pct"] == 35
    return scenario


class TestDepositDimensionsAdvanceIndependently:
    def test_the_sweep_lists_the_week_without_touching_deposit_status(self, api):
        """rental_status leaves NOT_LISTED while deposit_status stays BANKED.

        PRD §3.5: "Every deposit whose `deposit_status` is `BANKED`, whose
        `rental_status` is `NOT_LISTED`, and whose expiry is close — the number of
        whole days from the calendar date of `as_of_utc` to the calendar date of
        its `expires_at` being at most 45 days — freezes its `settlement_power` if
        that is still null, moves `NOT_LISTED` → `LISTED_GETAWAY`, forfeits its
        `remaining_power` from its owner through a `GETAWAY_LISTING_FORFEIT`
        ledger entry, and gains a getaway offer with `status` `LISTED`"

        Design: Difficulty/non_linear_state_machine/deposit_status_and_rental_status_advance_independently
        """
        market = _swept_week()
        run = market["run"]
        assert run["getaway_listed_count"] == 1
        assert run["expired_deposit_count"] == 0, "expiry is still 30 days away"
        assert run["matched_count"] == 0

        week = read_deposit(market["deposit"]["id"])
        assert week["deposit_status"] == "BANKED", (
            "the exchange dimension is untouched by the getaway sweep"
        )
        assert week["rental_status"] == "LISTED_GETAWAY"
        assert week["settlement_power"] == 58, (
            "45 * 1.25 * 1.10 = 61.875 -> 62, plus 6 is 68, "
            "lead -700 gives factor 0.85, 57.8 -> 58"
        )
        assert read_member(market["member"]["id"])["trading_power_balance"] == 0, (
            "82 credited at banking, 82 forfeited on listing"
        )

        offer = read_getaway_offer(market["offer"]["id"])
        assert_getaway_offer(offer)
        assert offer["status"] == "LISTED"
        assert offer["list_price_cents"] == 35627, (
            "58 * 900 = 52200, demand premium 5 percent -> 54810.0, "
            "less 35 percent -> 35626.5, rounded once -> 35627"
        )
        assert offer["urgency_discount_pct"] == 35
        assert offer["created_by_run_id"] == market["run_id"]

    def test_withdrawing_the_offer_walks_only_the_rental_dimension_back(self, api):
        """The pull-back restores NOT_LISTED and the power without moving the other axis.

        PRD §3.7: "Withdrawal returns the week's `rental_status` from
        `LISTED_GETAWAY` to `NOT_LISTED` and re-credits the week's
        `remaining_power` to the depositing owner through a `DEPOSIT_CREDIT`
        ledger entry, so a week pulled back becomes exchangeable again and its
        owner is made whole for the listing forfeit."

        Design: Difficulty/non_linear_state_machine/deposit_status_and_rental_status_advance_independently
        """
        market = _swept_week()
        withdrawn = withdraw_getaway(market["offer"]["id"])
        assert withdrawn["status"] == "WITHDRAWN"

        week = read_deposit(market["deposit"]["id"])
        assert week["rental_status"] == "NOT_LISTED"
        assert week["deposit_status"] == "BANKED", (
            "the second dimension moved back without the first ever changing"
        )
        assert read_member(market["member"]["id"])["trading_power_balance"] == 82, (
            "the listing forfeit is re-credited in full"
        )

        rows, meta = list_ledger_entries(member_id=market["member"]["id"])
        assert meta["total_count"] == 4
        assert [row["entry_type"] for row in rows] == [
            "DUES_PAYMENT",
            "DEPOSIT_CREDIT",
            "GETAWAY_LISTING_FORFEIT",
            "DEPOSIT_CREDIT",
        ]
        assert [row["power_delta"] for row in rows] == [0, 82, -82, 82]


class TestGetawayBooking:
    def test_booking_advances_the_offer_and_only_the_rental_dimension(self, api):
        """The rental terminal is reached while deposit_status stays BANKED.

        PRD §3.7: "On success the offer moves `LISTED` → `BOOKED`, which is
        terminal, stamping `booked_by_member_id` with the renter and `booked_at`
        with the current logical clock instant; the week's `rental_status` moves
        `LISTED_GETAWAY` → `RENTED`, also terminal"

        Design: Corner/state_machines/getaway_booking_transfers_cash_and_locks_the_deposit
        """
        scenario = _listed_after_prorated_cancellation()

        booked = validate_success(
            api.book_getaway_offer(
                scenario["offer"]["id"],
                factories.getaway_booking_payload(scenario["m3"]["id"]),
                make_member_headers(scenario["m3"]["id"]),
            )
        )
        assert booked["status"] == "BOOKED"
        assert booked["booked_by_member_id"] == scenario["m3"]["id"]
        assert_instant_equals(
            booked["booked_at"], "2027-05-17T00:00:00Z", "booked_at"
        )

        week = read_deposit(scenario["dep_m1"]["id"])
        assert week["rental_status"] == "RENTED"
        assert week["deposit_status"] == "BANKED", (
            "the two dimensions advanced independently"
        )
        assert week["remaining_power"] == 61, "unchanged by the rental"
        assert week["restoration_haircut_power"] == 21

    def test_the_booking_moves_cash_but_never_power(self, api):
        """The renter pays the frozen list price and no trading power changes hands.

        PRD §3.7: "and `list_price_cents` is debited from the renter through a
        `GETAWAY_BOOKING_PAYMENT` ledger entry raised against the `GETAWAY_OFFER`
        family. No trading power changes hands in a getaway rental — the week's
        power was already forfeited when it was listed."

        Design: Corner/state_machines/getaway_booking_transfers_cash_and_locks_the_deposit
        """
        scenario = _listed_after_prorated_cancellation()
        validate_success(
            api.book_getaway_offer(
                scenario["offer"]["id"],
                factories.getaway_booking_payload(scenario["m3"]["id"]),
                make_member_headers(scenario["m3"]["id"]),
            )
        )

        renter = read_member(scenario["m3"]["id"])
        assert renter["wallet_credit_cents"] == 29731, "80100 less the 50369 price"
        assert renter["trading_power_balance"] == 0, "renting buys nights, not power"
        assert read_member(scenario["m1"]["id"])["trading_power_balance"] == 0, (
            "the listing forfeit is not reversed by a booking"
        )

        rows, meta = list_ledger_entries(
            member_id=scenario["m3"]["id"], entry_type="GETAWAY_BOOKING_PAYMENT"
        )
        assert meta["total_count"] == 1
        assert rows[0]["cash_delta_cents"] == -50369
        assert rows[0]["power_delta"] == 0
        assert rows[0]["related_entity_type"] == "GETAWAY_OFFER"
        assert rows[0]["related_entity_id"] == scenario["offer"]["id"]


class TestBookingAfterWithdrawal:
    def test_the_pull_back_re_credits_the_forfeited_remaining_power(self, api):
        """WITHDRAWN clears the booking fields and makes the owner whole again.

        PRD §3.7: "An operator may pull a listing back off the market while it is
        still `LISTED`, moving the offer `LISTED` → `WITHDRAWN`, which is
        terminal."

        Design: Corner/state_machines/getaway_offer_booking_after_withdrawal_is_rejected
        """
        scenario = _listed_after_prorated_cancellation()

        withdrawn = validate_success(
            api.withdraw_getaway_offer(scenario["offer"]["id"], OPERATOR_HEADERS)
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["booked_by_member_id"] is None
        assert withdrawn["booked_at"] is None

        week = read_deposit(scenario["dep_m1"]["id"])
        assert week["rental_status"] == "NOT_LISTED"
        assert week["remaining_power"] == 61
        assert read_member(scenario["m1"]["id"])["trading_power_balance"] == 61, (
            "the forfeited remaining_power was re-credited"
        )

    def test_booking_a_withdrawn_offer_is_a_state_transition_error(self, api):
        """WITHDRAWN is terminal, so the late renter is refused and nothing moves.

        PRD §3.7: "Only a `LISTED` offer can be booked; anything else yields
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/getaway_offer_booking_after_withdrawal_is_rejected
        """
        scenario = _listed_after_prorated_cancellation()
        withdraw_getaway(scenario["offer"]["id"])

        response = api.book_getaway_offer(
            scenario["offer"]["id"],
            factories.getaway_booking_payload(scenario["m3"]["id"]),
            make_member_headers(scenario["m3"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

        assert read_getaway_offer(scenario["offer"]["id"])["status"] == "WITHDRAWN"
        assert read_member(scenario["m3"]["id"])["wallet_credit_cents"] == 80100, (
            "the rejected booking moved no cash"
        )
        assert read_member(scenario["m1"]["id"])["trading_power_balance"] == 61, (
            "not re-debited by the failed booking"
        )


class TestListPriceFloorClamp:
    def test_a_price_below_the_corridor_is_lifted_to_the_floor(self, api):
        """The clamp is applied after the discount, not as an input guard.

        PRD §3.7: "Finally clamp: apply the floor of 29900 cents first and then
        the ceiling of 249900 cents, so a computed price below the floor becomes
        exactly 29900 and one above the ceiling becomes exactly 249900, and store
        the result as `list_price_cents`."

        Design: Corner/calculations/getaway_list_price_clamped_up_to_the_floor
        """
        market = setup_market(
            member_count=1,
            resort_overrides=dict(factories.RESORT_C),
            band_code="SILVER",
            band_start_month_day="01-01",
            band_end_month_day="12-31",
        )
        member = market["members"][0]
        deposit = bank_deposit(
            member["id"], market["resort"]["id"], unit_size="STUDIO",
            check_in_date="2026-11-01",
        )
        assert deposit["awarded_power"] == 27, (
            "30 * 1.00 * 0.90 = 27, no bonus at STANDARD, lead 92 gives factor 1.00"
        )
        assert_instant_equals(
            deposit["expires_at"], "2028-10-31T00:00:00Z", "expires_at"
        )

        set_clock("2028-10-01T00:00:00Z")
        run = run_matching("sweep the studio close to expiry")
        assert run["expired_deposit_count"] == 0, "expiry is still thirty days away"
        assert run["getaway_listed_count"] == 1

        week = read_deposit(deposit["id"])
        assert week["settlement_power"] == 23, (
            "27 after the first two steps, lead -700 gives factor 0.85, 22.95 -> 23"
        )
        assert week["rental_status"] == "LISTED_GETAWAY"
        assert week["deposit_status"] == "BANKED"

        offers, meta = list_getaway_offers(deposit_id=deposit["id"])
        assert meta["total_count"] == 1
        offer = read_getaway_offer(offers[0]["id"])
        assert offer["list_price_cents"] == 29900, (
            "23 * 900 = 20700, demand premium -5 percent -> 19665.0, "
            "less 35 percent -> 12782.25 -> 12782, lifted by the 29900 floor"
        )
        assert offer["urgency_discount_pct"] == 35, (
            "the clamp does not rewrite the discount that produced the raw price"
        )
        assert offer["created_by_run_id"] == run["id"]

        assert read_member(member["id"])["trading_power_balance"] == 0
        rows, forfeits = list_ledger_entries(
            member_id=member["id"], entry_type="GETAWAY_LISTING_FORFEIT"
        )
        assert forfeits["total_count"] == 1
        assert rows[0]["power_delta"] == -27, "the listing forfeits remaining_power"


class TestSelfBooking:
    def test_the_depositing_owner_cannot_rent_its_own_week_back(self, api):
        """The buyer is compared against the owner two hops away through the deposit.

        PRD §2.10: "The member booking a getaway offer is not the owner of the
        underlying deposit — otherwise `ERR_GETAWAY_SELF_BOOKING` (409), on
        getaway booking."

        Design: Corner/validations/getaway_booking_by_the_deposit_owner_is_rejected
        """
        scenario = _listed_after_prorated_cancellation()
        owner = read_member(scenario["m1"]["id"])
        assert owner["wallet_credit_cents"] == 80100, (
            "the owner's wallet comfortably covers the 50369 price"
        )

        response = api.book_getaway_offer(
            scenario["offer"]["id"],
            factories.getaway_booking_payload(scenario["m1"]["id"]),
            make_member_headers(scenario["m1"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_GETAWAY_SELF_BOOKING.value, 409)

        offer = read_getaway_offer(scenario["offer"]["id"])
        assert offer["status"] == "LISTED"
        assert offer["booked_by_member_id"] is None
        assert offer["booked_at"] is None

        after = read_member(scenario["m1"]["id"])
        assert after["wallet_credit_cents"] == 80100
        assert after["trading_power_balance"] == 0
        assert read_deposit(scenario["dep_m1"]["id"])["rental_status"] == "LISTED_GETAWAY"
