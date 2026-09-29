"""Cancelling a confirmed exchange, the day-count branch and reinstatement."""

from test_helpers import (
    ApiErrorId,
    assert_confirmation,
    assert_getaway_offer,
    assert_instant_equals,
    cancel_confirmation,
    list_confirmations,
    list_getaway_offers,
    list_ledger_entries,
    make_member_headers,
    read_confirmation,
    read_deposit,
    read_exchange_request,
    read_getaway_offer,
    read_member,
    set_clock,
    setup_confirmed_exchange,
    validate_error,
    validate_success,
)

CANONICAL_WINDOW = {
    "window_start_date": "2027-06-01",
    "window_end_date": "2027-06-30",
    "member_count": 2,
}


def _cancel_at(clock):
    """The canonical confirmed exchange, cancelled by M2 at the given instant."""
    scenario = setup_confirmed_exchange(**CANONICAL_WINDOW)
    assert scenario["dep_m1"]["awarded_power"] == 82
    assert scenario["dep_m2"]["awarded_power"] == 107
    assert scenario["request"]["quoted_charge_cents"] == 23060
    assert scenario["confirmation"]["power_debited"] == 82
    assert read_member(scenario["m2"]["id"])["trading_power_balance"] == 25
    assert read_member(scenario["m2"]["id"])["wallet_credit_cents"] == 57040

    set_clock(clock)
    scenario["cancelled"] = cancel_confirmation(
        scenario["confirmation"]["id"], scenario["m2"]["id"]
    )
    return scenario


class TestLateCancellationCascade:
    def test_the_prorated_branch_restores_the_power_and_adds_the_late_surcharge(
        self, api
    ):
        """Cancelling 29 days out restores 82 points and costs 16400 cents.

        PRD §3.6: "When that count is under 30 days — including a count of zero
        or a negative one, for a cancellation on or after the arrival date — the
        cancellation is prorated: `restoration_variant` is recorded as
        `PRORATED_RESTORE`, the cancelling member is still credited
        `restored_power` equal to `power_debited` through an
        `EXCHANGE_RESTORATION` entry ... and the levied `cancellation_fee_cents`
        is the tier's `cancellation_fee_cents` plus a late-cancellation surcharge
        of 7500 cents."

        Design: Difficulty/transitive_cascade/late_cancel_prorated_restore_getaway_forfeit_chain
        """
        scenario = _cancel_at("2027-05-17T00:00:00Z")
        cancelled = scenario["cancelled"]
        assert_confirmation(cancelled)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["restoration_variant"] == "PRORATED_RESTORE", (
            "29 whole days to the awarded check-in is under the 30-day threshold"
        )
        assert cancelled["restored_power"] == 82
        assert cancelled["cancellation_fee_cents"] == 16400, (
            "8900 tier cancellation fee plus the 7500 late surcharge"
        )
        assert_instant_equals(
            cancelled["cancelled_at"], "2027-05-17T00:00:00Z", "cancelled_at"
        )

        m2 = read_member(scenario["m2"]["id"])
        assert m2["trading_power_balance"] == 107, "25 left after the debit, plus 82 back"
        assert m2["wallet_credit_cents"] == 40640, "57040 less the 16400 levy"

    def test_the_returned_week_takes_the_haircut_and_lands_on_the_getaway_market(
        self, api
    ):
        """Hops 2 and 3: BANKED again with a 21-point haircut, then LISTED_GETAWAY.

        PRD §3.6: "the depositing owner is debited a haircut equal to the week's
        `awarded_power` multiplied by 25 percent and rounded *up* to a whole
        point, posted as a `RESTORATION_HAIRCUT` ledger entry; the week's
        `restoration_haircut_power` rises by that haircut and its
        `remaining_power` is recomputed as `awarded_power` minus the accumulated
        haircut; its `expires_at` is still unchanged; its `rental_status` moves
        `NOT_LISTED` → `LISTED_GETAWAY` and a getaway offer is created for it,
        priced as in §3.7 with no `created_by_run_id` because no run listed it"

        Design: Difficulty/transitive_cascade/late_cancel_prorated_restore_getaway_forfeit_chain
        """
        scenario = _cancel_at("2027-05-17T00:00:00Z")

        week = read_deposit(scenario["dep_m1"]["id"])
        assert week["deposit_status"] == "BANKED", "USED unwinds back to BANKED"
        assert week["restoration_haircut_power"] == 21, "ceil(82 * 25 / 100) = ceil(20.5)"
        assert week["remaining_power"] == 61
        assert week["awarded_power"] == 82, "the frozen award is never rewritten"
        assert_instant_equals(
            week["expires_at"], "2029-06-14T00:00:00Z", "expires_at"
        )
        assert week["rental_status"] == "LISTED_GETAWAY"

        offers, meta = list_getaway_offers(deposit_id=scenario["dep_m1"]["id"])
        assert meta["total_count"] == 1
        assert offers[0]["status"] == "LISTED"
        assert offers[0]["created_by_run_id"] is None, (
            "the cancellation listed this week, not a run"
        )

        offer = read_getaway_offer(offers[0]["id"])
        assert_getaway_offer(offer)
        assert offer["urgency_discount_pct"] == 35, (
            "29 days to check-in falls below the 30-day band"
        )
        assert offer["list_price_cents"] == 50369, (
            "82 * 900 = 73800, demand premium 5 percent -> 77490.0, "
            "less 35 percent -> 50368.5, rounded half up once -> 50369"
        )

    def test_the_listing_forfeit_zeroes_the_depositing_owner(self, api):
        """Hop 4: the 61 points surviving the haircut are forfeited to the listing.

        PRD §3.6: "because that move to `LISTED_GETAWAY` is the same edge a
        run-driven listing takes, it carries the same consequence, so whatever
        `remaining_power` survives the haircut is forfeited from the depositing
        owner through a `GETAWAY_LISTING_FORFEIT` ledger entry"

        Design: Difficulty/transitive_cascade/late_cancel_prorated_restore_getaway_forfeit_chain
        """
        scenario = _cancel_at("2027-05-17T00:00:00Z")

        m1 = read_member(scenario["m1"]["id"])
        assert m1["trading_power_balance"] == 0, "82 credited, 21 haircut, 61 forfeit"

        rows, meta = list_ledger_entries(member_id=scenario["m1"]["id"])
        assert meta["total_count"] == 4
        assert [row["entry_type"] for row in rows] == [
            "DUES_PAYMENT",
            "DEPOSIT_CREDIT",
            "RESTORATION_HAIRCUT",
            "GETAWAY_LISTING_FORFEIT",
        ], "the ledger collection is ordered by created_at ascending"
        assert rows[1]["power_delta"] == 82
        assert rows[2]["power_delta"] == -21
        assert rows[3]["power_delta"] == -61

        request = read_exchange_request(scenario["request"]["id"])
        assert request["status"] == "CONFIRMED"
        assert request["charge_refunded_cents"] == 0, (
            "a confirmed exchange never refunds its charge"
        )


class TestFullRestoreThresholdIsInclusive:
    def test_exactly_thirty_days_out_restores_everything(self, api):
        """At a day count of exactly 30 the week is left entirely untouched.

        PRD §3.6: "The threshold is inclusive on the full-restore side: a
        cancellation exactly 30 days before the awarded arrival date is
        `FULL_RESTORE`, and one day later is `PRORATED_RESTORE`."

        Design: Difficulty/boundary_precision_check/full_restore_at_exactly_thirty_days_before_check_in
        """
        scenario = _cancel_at("2027-05-16T00:00:00Z")
        cancelled = scenario["cancelled"]
        assert cancelled["restoration_variant"] == "FULL_RESTORE"
        assert cancelled["restored_power"] == 82
        assert cancelled["cancellation_fee_cents"] == 8900, "no late surcharge at 30 days"
        assert cancelled["status"] == "CANCELLED"

        m2 = read_member(scenario["m2"]["id"])
        assert m2["trading_power_balance"] == 107
        assert m2["wallet_credit_cents"] == 48140, "57040 less the 8900 tier fee"

        week = read_deposit(scenario["dep_m1"]["id"])
        assert week["deposit_status"] == "BANKED"
        assert week["restoration_haircut_power"] == 0
        assert week["remaining_power"] == 82
        assert week["rental_status"] == "NOT_LISTED"

        assert read_member(scenario["m1"]["id"])["trading_power_balance"] == 82, (
            "the depositing owner is untouched by a full restoration"
        )
        _, offers = list_getaway_offers(deposit_id=scenario["dep_m1"]["id"])
        assert offers["total_count"] == 0, "no getaway offer is created"
        rows, meta = list_ledger_entries(member_id=scenario["m1"]["id"])
        assert meta["total_count"] == 2
        assert [row["entry_type"] for row in rows] == ["DUES_PAYMENT", "DEPOSIT_CREDIT"], (
            "no RESTORATION_HAIRCUT row is written on the full-restore side"
        )

    def test_one_day_later_flips_six_figures_at_once(self, api):
        """At 29 days the identical call takes the haircut, the surcharge and the listing.

        PRD §3.6: "Take the number of whole days from the calendar date of the
        current logical clock instant to the confirmation's
        `awarded_check_in_date`. When that count is at least 30 days, the
        cancellation is a full restoration"

        Design: Difficulty/boundary_precision_check/full_restore_at_exactly_thirty_days_before_check_in
        """
        scenario = _cancel_at("2027-05-17T00:00:00Z")
        cancelled = scenario["cancelled"]
        assert cancelled["restoration_variant"] == "PRORATED_RESTORE"
        assert cancelled["cancellation_fee_cents"] == 16400

        week = read_deposit(scenario["dep_m1"]["id"])
        assert week["restoration_haircut_power"] == 21
        assert week["remaining_power"] == 61

        _, offers = list_getaway_offers(deposit_id=scenario["dep_m1"]["id"])
        assert offers["total_count"] == 1
        assert read_member(scenario["m1"]["id"])["trading_power_balance"] == 0


class TestReinstatementWindow:
    def test_fifteen_days_after_the_cancellation_is_refused(self, api):
        """The window is measured from the cancelled row's own cancelled_at.

        PRD §2.10: "A reinstatement happens while the current logical clock
        instant is no later than 14 days after the predecessor's `cancelled_at`
        — otherwise `ERR_REINSTATEMENT_WINDOW_CLOSED` (409), on confirmation
        reinstatement."

        Design: Corner/validations/reinstatement_after_the_fourteen_day_window_is_rejected
        """
        scenario = _cancel_at("2027-05-16T00:00:00Z")
        cancelled = scenario["cancelled"]
        assert cancelled["restoration_variant"] == "FULL_RESTORE"
        assert cancelled["restored_power"] == 82
        assert_instant_equals(
            cancelled["cancelled_at"], "2027-05-16T00:00:00Z", "cancelled_at"
        )
        available = read_deposit(scenario["dep_m1"]["id"])
        assert available["deposit_status"] == "BANKED"
        assert available["rental_status"] == "NOT_LISTED", (
            "the week is available, so ERR_DEPOSIT_NOT_AVAILABLE cannot explain a refusal"
        )

        set_clock("2027-05-31T00:00:00Z")
        response = api.reinstate_confirmation(
            cancelled["id"], make_member_headers(scenario["m2"]["id"])
        )
        validate_error(
            response, ApiErrorId.ERR_REINSTATEMENT_WINDOW_CLOSED.value, 409
        )

    def test_the_refused_reinstatement_levies_nothing(self, api):
        """No successor row and no fee once the window has closed.

        PRD §3.6: "The successor's `reinstatement_fee_cents` is the member's tier
        `reinstatement_fee_cents` and is levied from the wallet as a
        `REINSTATEMENT_FEE` ledger entry."

        Design: Corner/validations/reinstatement_after_the_fourteen_day_window_is_rejected
        """
        scenario = _cancel_at("2027-05-16T00:00:00Z")
        set_clock("2027-05-31T00:00:00Z")
        validate_error(
            api.reinstate_confirmation(
                scenario["cancelled"]["id"],
                make_member_headers(scenario["m2"]["id"]),
            ),
            ApiErrorId.ERR_REINSTATEMENT_WINDOW_CLOSED.value,
            409,
        )

        predecessor = read_confirmation(scenario["cancelled"]["id"])
        assert predecessor["status"] == "CANCELLED", "not advanced to REINSTATED"
        assert predecessor["reinstatement_fee_cents"] == 0
        _, successors = list_confirmations(
            reinstated_from_confirmation_id=scenario["cancelled"]["id"]
        )
        assert successors["total_count"] == 0
        assert read_member(scenario["m2"]["id"])["wallet_credit_cents"] == 48140, (
            "no reinstatement fee was levied"
        )

    def test_exactly_fourteen_days_after_the_cancellation_still_succeeds(self, api):
        """One day earlier the same call creates the successor confirmation.

        PRD §3.6: "A cancelled confirmation may be reinstated by its member
        within 14 days: the current logical clock instant must be no later than
        14 days after `cancelled_at`, or the attempt is refused with
        `ERR_REINSTATEMENT_WINDOW_CLOSED`."

        Design: Corner/validations/reinstatement_after_the_fourteen_day_window_is_rejected
        """
        scenario = _cancel_at("2027-05-16T00:00:00Z")
        set_clock("2027-05-30T00:00:00Z")

        successor = validate_success(
            api.reinstate_confirmation(
                scenario["cancelled"]["id"],
                make_member_headers(scenario["m2"]["id"]),
            ),
            201,
        )
        assert successor["reinstatement_fee_cents"] == 10900
        assert successor["status"] == "CONFIRMED"
        assert successor["reinstated_from_confirmation_id"] == scenario["cancelled"]["id"]
        assert read_confirmation(scenario["cancelled"]["id"])["status"] == "REINSTATED"
