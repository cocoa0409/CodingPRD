"""The operations run: the matching pass, held weeks, declines and the clock."""

from test_helpers import (
    OPERATOR_HEADERS,
    assert_instant_absent,
    assert_instant_equals,
    assert_matching_run,
    bank_deposit,
    create_active_member,
    create_tier,
    decline_match,
    factories,
    file_exchange_request,
    is_iso8601_timestamp,
    list_ledger_entries,
    list_matching_runs,
    read_deposit,
    read_exchange_request,
    read_member,
    run_matching,
    set_clock,
    setup_affiliated_resort,
    validate_success,
    withdraw_deposit,
)

RUN_COUNTERS = (
    "lapsed_member_count",
    "expired_deposit_count",
    "probation_resort_count",
    "expired_request_count",
    "denied_request_count",
    "matched_count",
    "waitlisted_count",
    "completed_confirmation_count",
    "getaway_listed_count",
)


def _two_member_market():
    """Resort A with two ONE_BR weeks from M1 and a funded ONE_BR request from M2."""
    tier = create_tier()
    resort = setup_affiliated_resort()
    owner = create_active_member(tier["id"])
    seeker = create_active_member(
        tier["id"], email="m2@example.com", full_name="Priya Ravindran"
    )
    week_p = bank_deposit(owner["id"], resort["id"], check_in_date="2027-06-15")
    week_q = bank_deposit(owner["id"], resort["id"], check_in_date="2027-06-20")
    assert week_p["awarded_power"] == 82 and week_q["awarded_power"] == 82
    funding = bank_deposit(
        seeker["id"], resort["id"], unit_size="THREE_BR", check_in_date="2027-05-10"
    )
    assert funding["awarded_power"] == 139
    request = file_exchange_request(
        seeker["id"], resort["id"], deposit_id=funding["id"]
    )
    assert request["power_budget"] == 152, "floor(139 * 110 / 100)"
    assert request["required_power_estimate"] == 82
    assert request["quoted_charge_cents"] == 23060
    return {
        "resort": resort,
        "owner": owner,
        "seeker": seeker,
        "week_p": week_p,
        "week_q": week_q,
        "request": request,
    }


class TestMatchDeclineRematchCycle:
    def test_the_decline_unwinds_the_match_and_costs_five_points(self, api):
        """Leaving MATCHED for WAITLISTED releases the week and books a penalty.

        PRD §3.6: "Declining moves the request `MATCHED` → `WAITLISTED`, releases
        the held week from `RESERVED` back to `BANKED`, clears
        `matched_deposit_id` and `matched_hold_expires_at`, stamps `waitlisted_at`
        with the current logical clock instant, and raises `decline_count` by 1 —
        which lowers `priority_score` by 5 points at every subsequent run."

        Design: Difficulty/non_linear_state_machine/exchange_request_match_decline_rematch_cycle
        """
        market = _two_member_market()

        first_run = run_matching("first pass")
        assert first_run["matched_count"] == 1
        assert first_run["waitlisted_count"] == 0

        matched = read_exchange_request(market["request"]["id"])
        assert matched["status"] == "MATCHED"
        assert matched["matched_deposit_id"] == market["week_p"]["id"], (
            "the ranking breaks the 82-point tie on check_in_date ascending"
        )
        assert matched["priority_score"] == 35, "20 for PLUS plus 15 for deposit-first"
        assert matched["decline_count"] == 0
        assert read_deposit(market["week_p"]["id"])["deposit_status"] == "RESERVED"

        declined = decline_match(market["request"]["id"], market["seeker"]["id"])
        assert declined["status"] == "WAITLISTED"
        assert declined["matched_deposit_id"] is None
        assert_instant_absent(declined["matched_hold_expires_at"], "matched_hold_expires_at")
        assert declined["decline_count"] == 1

        released = read_deposit(market["week_p"]["id"])
        assert released["deposit_status"] == "BANKED"
        assert released["settlement_power"] == 82, (
            "the settlement valuation frozen by the run survives the decline"
        )

    def test_re_entering_matched_lands_on_another_week_at_a_lower_score(self, api):
        """The second entry into MATCHED differs from the first in week and score.

        PRD §3.6: "The loop `MATCHED` → `WAITLISTED` → `MATCHED` may run
        repeatedly, and re-entry into `MATCHED` is not equivalent to the first
        entry: the request now carries a higher `decline_count`, ranks lower, and
        may well be offered a different week. Declining does not refund any part
        of the exchange charge, because the request is still live."

        Design: Difficulty/non_linear_state_machine/exchange_request_match_decline_rematch_cycle
        """
        market = _two_member_market()
        run_matching("first pass")
        decline_match(market["request"]["id"], market["seeker"]["id"])
        withdraw_deposit(market["week_p"]["id"], market["owner"]["id"])
        assert read_member(market["owner"]["id"])["trading_power_balance"] == 82, (
            "164 credited for two weeks, 82 reversed by the withdrawal"
        )

        second_run = run_matching("second pass after the decline")
        assert second_run["matched_count"] == 1
        assert second_run["waitlisted_count"] == 0

        rematched = read_exchange_request(market["request"]["id"])
        assert rematched["status"] == "MATCHED"
        assert rematched["matched_deposit_id"] == market["week_q"]["id"], (
            "the first week left the pool, so a different week wins"
        )
        assert rematched["priority_score"] == 30, (
            "20 tier plus 15 deposit-first minus 5 for one decline"
        )
        assert rematched["decline_count"] == 1
        assert rematched["quoted_charge_cents"] == 23060
        assert rematched["charge_refunded_cents"] == 0, "a decline refunds nothing"

        held = read_deposit(market["week_q"]["id"])
        assert held["deposit_status"] == "RESERVED"
        assert held["settlement_power"] == 82


class TestDeclineSideEffects:
    def test_one_call_unwinds_the_request_the_week_and_the_score(self, api):
        """The compensation edge touches three rows in a single call.

        PRD §3.6: "Declining moves the request `MATCHED` → `WAITLISTED`, releases
        the held week from `RESERVED` back to `BANKED`, clears
        `matched_deposit_id` and `matched_hold_expires_at`, stamps `waitlisted_at`
        with the current logical clock instant, and raises `decline_count` by 1."

        Design: Corner/state_machines/declined_match_returns_the_deposit_to_banked
        """
        tier = create_tier()
        resort = setup_affiliated_resort()
        owner = create_active_member(tier["id"])
        seeker = create_active_member(
            tier["id"], email="m2@example.com", full_name="Priya Ravindran"
        )
        week = bank_deposit(owner["id"], resort["id"], check_in_date="2027-06-15")
        funding = bank_deposit(
            seeker["id"], resort["id"], unit_size="TWO_BR", check_in_date="2027-05-10"
        )
        assert funding["awarded_power"] == 107
        request = file_exchange_request(
            seeker["id"], resort["id"], deposit_id=funding["id"]
        )
        assert request["power_budget"] == 117, "floor(107 * 110 / 100)"
        run_matching()

        before = read_exchange_request(request["id"])
        assert before["status"] == "MATCHED"
        assert before["matched_deposit_id"] == week["id"]
        assert_instant_equals(
            before["matched_hold_expires_at"],
            "2026-08-03T00:00:00Z",
            "matched_hold_expires_at",
        )
        assert before["priority_score"] == 35
        assert before["decline_count"] == 0

        declined = decline_match(request["id"], seeker["id"])
        assert declined["status"] == "WAITLISTED"
        assert declined["matched_deposit_id"] is None
        assert declined["matched_hold_expires_at"] is None
        assert declined["decline_count"] == 1
        assert_instant_equals(
            declined["waitlisted_at"], "2026-08-01T00:00:00Z", "waitlisted_at"
        )

        released = read_deposit(week["id"])
        assert released["deposit_status"] == "BANKED"
        assert released["rental_status"] == "NOT_LISTED"
        assert released["settlement_power"] == 82

    def test_the_decline_moves_neither_power_nor_cash(self, api):
        """A decline leaves both ledgers exactly where the match left them.

        PRD §3.6: "Declining does not refund any part of the exchange charge,
        because the request is still live."

        Design: Corner/state_machines/declined_match_returns_the_deposit_to_banked
        """
        tier = create_tier()
        resort = setup_affiliated_resort()
        owner = create_active_member(tier["id"])
        seeker = create_active_member(
            tier["id"], email="m2@example.com", full_name="Priya Ravindran"
        )
        bank_deposit(owner["id"], resort["id"], check_in_date="2027-06-15")
        funding = bank_deposit(
            seeker["id"], resort["id"], unit_size="TWO_BR", check_in_date="2027-05-10"
        )
        request = file_exchange_request(
            seeker["id"], resort["id"], deposit_id=funding["id"]
        )
        run_matching()

        decline_match(request["id"], seeker["id"])

        assert read_member(owner["id"])["trading_power_balance"] == 82, (
            "the depositing owner is untouched by a decline"
        )
        after_seeker = read_member(seeker["id"])
        assert after_seeker["active_request_count"] == 1, "the request is still live"
        assert after_seeker["wallet_credit_cents"] == 57040
        _, refunds = list_ledger_entries(
            member_id=seeker["id"], entry_type="EXCHANGE_CHARGE_REFUND"
        )
        assert refunds["total_count"] == 0


class TestMatchingRunCompletesSynchronously:
    def test_the_creating_call_already_returns_a_completed_run(self, api):
        """A run is never observable in PENDING; the 201 already reports COMPLETED.

        PRD §3.5: "The run opens as `PENDING` and moves `PENDING` → `COMPLETED` at
        the end of the pinned step sequence, at which point all eleven counter
        fields are frozen at their post-sweep values and the completed run is
        returned to the caller."

        Design: Corner/state_machines/matching_run_reaches_completed_within_the_creating_request
        """
        response = api.create_matching_run(
            factories.matching_run_payload("cold start"), OPERATOR_HEADERS
        )
        data = validate_success(response, 201)
        assert data["status"] == "COMPLETED", "never PENDING"
        assert data["run_sequence"] == 1
        assert data["note"] == "cold start"
        assert_instant_equals(data["as_of_utc"], "2026-08-01T00:00:00Z", "as_of_utc")
        assert_matching_run(data)

        fetched = validate_success(api.get_matching_run(data["id"], OPERATOR_HEADERS))
        assert fetched["status"] == "COMPLETED", "the terminal state is reached in-band"

    def test_every_counter_on_an_empty_network_is_zero(self, api):
        """The counters are computed, so a run over nothing reports nine zeroes.

        PRD §3.5: "Runs are read back individually or listed in `run_sequence`
        ascending order, and their counters are the operator's record of what the
        checkpoint did."
        PRD §3.5: "The run is stamped with a `run_sequence` equal to one more than
        the highest sequence already recorded, or 1 when no run exists yet."

        Design: Corner/state_machines/matching_run_reaches_completed_within_the_creating_request
        """
        first = run_matching("cold start")
        for counter in RUN_COUNTERS:
            assert first[counter] == 0, f"{counter} must be 0, not null, on an empty network"

        second = run_matching("second sweep")
        assert second["run_sequence"] == 2, "the sequence is per-network and monotonic"
        rows, meta = list_matching_runs()
        assert meta["total_count"] == 2
        assert [row["run_sequence"] for row in rows] == [1, 2], (
            "runs are listed in run_sequence ascending order"
        )


class TestLogicalClockEndpoint:
    def test_the_endpoint_reports_the_instant_it_replaced(self, api):
        """The first call reports the mandatory default as previous_utc.

        PRD §2.5: "The server holds a logical clock whose default value is
        `2026-08-01T00:00:00Z` ... An operator-only test-driving capability moves
        the clock to a supplied `to_iso8601` instant and reports the resulting
        `current_utc` alongside the `previous_utc` it replaced."

        Design: Corner/endpoints/clock_endpoint_reports_previous_and_current_instants
        """
        response = api.set_clock(
            factories.clock_payload("2027-03-01T12:34:56Z"), OPERATOR_HEADERS
        )
        first = validate_success(response)
        assert sorted(first.keys()) == ["current_utc", "previous_utc"]
        assert_instant_equals(first["previous_utc"], "2026-08-01T00:00:00Z", "previous_utc")
        assert_instant_equals(first["current_utc"], "2027-03-01T12:34:56Z", "current_utc")

        body = response.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])

        second = set_clock("2027-04-01T00:00:00Z")
        assert_instant_equals(
            second["previous_utc"], "2027-03-01T12:34:56Z", "previous_utc"
        )
        assert_instant_equals(
            second["current_utc"], "2027-04-01T00:00:00Z", "current_utc"
        )

    def test_setting_the_clock_is_inert_but_later_writes_observe_it(self, api):
        """No run and no ledger row follow a clock move, yet the next run adopts it.

        PRD §2.5: "Moving the clock has no consequences of its own: no deposit
        expires, no request is swept, no confirmation completes and no resort
        changes its affiliation state merely because the clock advanced past a
        threshold."

        Design: Corner/endpoints/clock_endpoint_reports_previous_and_current_instants
        """
        set_clock("2027-03-01T12:34:56Z")
        set_clock("2027-04-01T00:00:00Z")

        _, runs = list_matching_runs()
        assert runs["total_count"] == 0, "setting the clock triggers no run"
        _, entries = list_ledger_entries()
        assert entries["total_count"] == 0

        run = run_matching("after the clock move")
        assert_instant_equals(run["as_of_utc"], "2027-04-01T00:00:00Z", "as_of_utc")


class TestHoldExpiryFeedsTheSamePass:
    def _three_member_contest(self):
        """One ONE_BR week, two identical requests: M2 wins, M3 waits."""
        tier = create_tier()
        resort = setup_affiliated_resort()
        owner = create_active_member(tier["id"])
        first_seeker = create_active_member(
            tier["id"], email="m2@example.com", full_name="Priya Ravindran"
        )
        second_seeker = create_active_member(
            tier["id"], email="m3@example.com", full_name="Owen Mbeki"
        )
        week = bank_deposit(owner["id"], resort["id"], check_in_date="2027-06-15")

        requests = {}
        for label, seeker, check_in in (
            ("first", first_seeker, "2027-05-10"),
            ("second", second_seeker, "2027-05-20"),
        ):
            funding = bank_deposit(
                seeker["id"], resort["id"], unit_size="TWO_BR", check_in_date=check_in
            )
            assert funding["awarded_power"] == 107
            request = file_exchange_request(
                seeker["id"],
                resort["id"],
                window_start_date="2027-06-15",
                window_end_date="2027-06-15",
                deposit_id=funding["id"],
            )
            assert request["power_budget"] == 117
            assert request["quoted_charge_cents"] == 23060
            requests[label] = request
        return {
            "week": week,
            "first_seeker": first_seeker,
            "second_seeker": second_seeker,
            "first_request": requests["first"],
            "second_request": requests["second"],
        }

    def test_created_at_breaks_the_tie_and_leaves_the_loser_waitlisted(self, api):
        """Equal scores are ordered by created_at ascending, so the earlier wins.

        PRD §3.5: "the surviving requests are then processed in `priority_score`
        descending order, ties broken by `created_at` ascending. A request's `id`
        is never a tie-break input."

        Design: Corner/cross_cutting_complexity_layers/hold_expiry_in_step_two_frees_the_deposit_for_step_three
        """
        contest = self._three_member_contest()

        first_run = run_matching("first pass")
        assert first_run["matched_count"] == 1
        assert first_run["waitlisted_count"] == 1

        winner = read_exchange_request(contest["first_request"]["id"])
        assert winner["status"] == "MATCHED"
        assert winner["matched_deposit_id"] == contest["week"]["id"]
        assert_instant_equals(
            winner["matched_hold_expires_at"],
            "2026-08-03T00:00:00Z",
            "matched_hold_expires_at",
        )
        loser = read_exchange_request(contest["second_request"]["id"])
        assert loser["status"] == "WAITLISTED"
        assert loser["matched_deposit_id"] is None
        assert read_deposit(contest["week"]["id"])["deposit_status"] == "RESERVED"

    def test_one_run_expires_the_stale_hold_and_rematches_the_same_week(self, api):
        """Step 2 releases the week and step 3 hands it to the waitlisted request.

        PRD §3.5: "The seven steps run in exactly the order given, and each step
        reads the state its predecessors left behind."
        PRD §3.5: "First, a `MATCHED` request whose `matched_hold_expires_at` is
        not later than `as_of_utc` moves `MATCHED` → `EXPIRED` and releases its
        held week from `RESERVED` back to `BANKED`, clearing `matched_deposit_id`
        and `matched_hold_expires_at`."

        Design: Corner/cross_cutting_complexity_layers/hold_expiry_in_step_two_frees_the_deposit_for_step_three
        """
        contest = self._three_member_contest()
        run_matching("first pass")
        set_clock("2026-08-04T00:00:00Z")

        second_run = run_matching("sweep and rematch")
        assert second_run["expired_request_count"] == 1
        assert second_run["matched_count"] == 1, "one POST produced both effects"
        for counter in (
            "lapsed_member_count",
            "expired_deposit_count",
            "denied_request_count",
            "completed_confirmation_count",
            "getaway_listed_count",
            "probation_resort_count",
        ):
            assert second_run[counter] == 0, f"only steps 2 and 3 did work, yet {counter} moved"

        swept = read_exchange_request(contest["first_request"]["id"])
        assert swept["status"] == "EXPIRED"
        assert swept["matched_deposit_id"] is None
        assert swept["matched_hold_expires_at"] is None
        assert swept["charge_refunded_cents"] == 23060
        refunded = read_member(contest["first_seeker"]["id"])
        assert refunded["wallet_credit_cents"] == 80100
        assert refunded["active_request_count"] == 0

        promoted = read_exchange_request(contest["second_request"]["id"])
        assert promoted["status"] == "MATCHED"
        assert promoted["matched_deposit_id"] == contest["week"]["id"]
        assert_instant_equals(
            promoted["matched_hold_expires_at"],
            "2026-08-06T00:00:00Z",
            "matched_hold_expires_at",
        )
        assert read_deposit(contest["week"]["id"])["deposit_status"] == "RESERVED", (
            "held for the second seeker now, never left BANKED for a caller to see"
        )
        still_charged = read_member(contest["second_seeker"]["id"])
        assert still_charged["wallet_credit_cents"] == 57040, "a rematch charges nothing"
        assert still_charged["active_request_count"] == 1
