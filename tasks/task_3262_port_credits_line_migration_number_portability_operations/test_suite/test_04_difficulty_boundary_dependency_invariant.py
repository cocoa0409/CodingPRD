"""Boundary precision, cross-entity state dependencies and compensating invariants."""
from test_helpers import (
    ADMIN,
    TEST_USERS,
    advance_clock,
    api_client,
    assert_account_ledger_invariant,
    assert_number_reservation,
    assert_subscriber_line,
    check_migration_eligibility,
    commit_reservation,
    create_account,
    create_active_protection_case,
    create_activated_line,
    create_bare_line,
    create_line_addition,
    create_migration_request,
    create_promo_schedule,
    create_rejection_code,
    create_reservation,
    get_account,
    get_device_plan,
    get_line,
    get_promo_schedule,
    get_port_request,
    record_rejection,
    resubmit_port_request,
    review_line_addition,
    setup_account_with_active_lines,
    setup_line_with_existing_schedule,
    setup_line_with_plan_and_schedule,
    submit_port_request,
    create_draft_port_request,
)

CARE = TEST_USERS["customer_service_headers"]


class TestPromoWindowBufferBoundary:
    """The buffer boundary is inclusive at window_end plus the configured buffer."""

    def test_window_starting_one_day_early_is_refused(self, api):
        """PRD §3.4: "The requested `window_start` must be at or after every existing
        `PromoCreditSchedule`'s `window_end` on the same subscriber line **plus** the
        system's `promo_window_buffer_days` setting, and this test only considers
        existing schedules whose `schedule_state` is `PROVISIONAL` or `ACTIVE`"

        Design: Difficulty/boundary_precision_check/promo_window_buffer_boundary_day
        """
        account, line, _existing = setup_line_with_existing_schedule(
            "4155551101", window_start="2026-09-02T00:00:00Z",
            installment_months=1, retention_requirement_cycles=1,
        )
        assert advance_clock("2026-09-02T00:00:00Z")

        response = api_client.create_promo_schedule(
            {
                "subscriber_line_id": line["id"],
                "promo_code": "SWITCH20",
                "monthly_credit_cents": 1000,
                "installment_months": 12,
                "retention_requirement_cycles": 12,
                "window_start": "2026-10-31T00:00:00Z",
                "expected_subscriber_line_version": get_line(line["id"])["version"],
            },
            CARE,
        )

        assert response.json()["data"]["error_id"] == "ERR_PROMO_WINDOW_OVERLAP"

    def test_window_starting_exactly_at_window_end_plus_buffer_succeeds(self, api):
        """PRD §3.4: "The requested `window_start` must be at or after every existing
        `PromoCreditSchedule`'s `window_end` on the same subscriber line **plus** the
        system's `promo_window_buffer_days` setting"
        PRD §3.4: "The buffer defaults to 30 days."

        Design: Difficulty/boundary_precision_check/promo_window_buffer_boundary_day
        """
        account, line, _existing = setup_line_with_existing_schedule(
            "4155551102", window_start="2026-09-02T00:00:00Z",
            installment_months=1, retention_requirement_cycles=1,
        )

        created = create_promo_schedule(
            line,
            window_start="2026-11-01T00:00:00Z",
            installment_months=12,
            retention_requirement_cycles=12,
        )

        assert created["schedule_state"] == "PROVISIONAL"
        assert created["provisional_total_cents"] == 32000

    def test_the_refused_window_leaves_the_line_with_only_its_existing_schedule(self, api):
        """PRD §3.4: "The requested `window_start` must be at or after every existing
        `PromoCreditSchedule`'s `window_end` on the same subscriber line **plus** the
        system's `promo_window_buffer_days` setting"

        Design: Difficulty/boundary_precision_check/promo_window_buffer_boundary_day
        """
        account, line, existing = setup_line_with_existing_schedule(
            "4155551103", window_start="2026-09-02T00:00:00Z",
            installment_months=1, retention_requirement_cycles=1,
        )
        api_client.create_promo_schedule(
            {
                "subscriber_line_id": line["id"],
                "promo_code": "SWITCH20",
                "monthly_credit_cents": 1000,
                "installment_months": 12,
                "retention_requirement_cycles": 12,
                "window_start": "2026-10-15T00:00:00Z",
                "expected_subscriber_line_version": get_line(line["id"])["version"],
            },
            CARE,
        )

        refreshed_account = get_account(account["id"])
        assert refreshed_account["promo_credited_cents"] == existing[
            "provisional_total_cents"
        ]


class TestLineLimitCeilingBoundary:
    """The ceiling is inclusive at exactly ten active lines."""

    def test_ten_lines_onto_an_empty_account_is_approved(self, api):
        """PRD §3.6: "The count of the account's `ACTIVE` lines plus the request's
        `line_count` must be at or below 10, or the approval fails with
        `ERR_LINE_LIMIT_EXCEEDED` (409)"

        Design: Difficulty/boundary_precision_check/line_limit_exact_ceiling_boundary
        """
        account = create_account(payment_history_score=900, existing_deposit_cents=50000)
        request = create_line_addition(account["id"], 10)

        decided = review_line_addition(request["id"], decision="APPROVE")

        assert decided["request_state"] == "APPROVED"
        assert decided["determined_credit_class"] == "CLASS_C"

    def test_eleven_lines_on_the_account_is_refused(self, api):
        """PRD §3.6: "The count of the account's `ACTIVE` lines plus the request's
        `line_count` must be at or below 10, or the approval fails with
        `ERR_LINE_LIMIT_EXCEEDED` (409)"

        Design: Difficulty/boundary_precision_check/line_limit_exact_ceiling_boundary
        """
        account, _line = setup_account_with_active_lines(
            1, mdn_offset=400, billing_mode="POSTPAID",
            account_overrides={"payment_history_score": 900,
                               "existing_deposit_cents": 50000},
        )
        request = create_line_addition(account["id"], 10)

        response = api_client.review_line_addition_request(
            request["id"], {"decision": "APPROVE"}, TEST_USERS["credit_analyst_headers"]
        )

        assert response.json()["data"]["error_id"] == "ERR_LINE_LIMIT_EXCEEDED"

    def test_the_over_limit_request_stays_submitted(self, api):
        """PRD §3.6: "Only then is the deposit compared: the account's
        `existing_deposit_cents` — the deposit already on file, which defaults to 0 at
        account creation — must be at or above the request's computed
        `required_deposit_cents`"

        Design: Difficulty/boundary_precision_check/line_limit_exact_ceiling_boundary
        """
        account, _line = setup_account_with_active_lines(
            1, mdn_offset=410, billing_mode="POSTPAID",
            account_overrides={"payment_history_score": 900,
                               "existing_deposit_cents": 50000},
        )
        request = create_line_addition(account["id"], 10)
        api_client.review_line_addition_request(
            request["id"], {"decision": "APPROVE"}, TEST_USERS["credit_analyst_headers"]
        )

        listed = api_client.list_account_line_addition_requests(
            account["id"], TEST_USERS["credit_analyst_headers"]
        )
        assert listed.json()["data"][0]["request_state"] == "SUBMITTED"


class TestMigrationEligibilityDependsOnProtectionCase:
    """The migration can only leave ELIGIBILITY_CHECK once no protection case is ACTIVE."""

    def test_active_protection_case_blocks_the_migration(self, api):
        """PRD §3.3: "If the attached line's `port_protection_status` is `PROTECTED`, or
        if any `PortRequest` on the attached line is sitting in `PENDING` or
        `RESUBMITTED`, the request goes to `BLOCKED`"

        Design: Difficulty/cross_entity_state_dependency/migration_eligibility_depends_on_protection_case_state
        """
        account = create_account(payment_history_score=720, existing_deposit_cents=50000)
        line = create_activated_line(account["id"], "4155551501", billing_mode="PREPAID")
        migration = create_migration_request(
            line, prepaid_balance_cents=0, requested_cutover_at="2026-10-01T00:00:00Z"
        )
        create_active_protection_case(line)

        result = check_migration_eligibility(migration["id"])

        assert result["migration_state"] == "BLOCKED"

    def test_the_blocked_migration_releases_the_number(self, api):
        """PRD §3.3: "in that branch the attached line's `number_status` is set to
        `UNASSIGNED`, and when the reason is protection specifically, the attached line's
        account also has `account_status` set to `SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/migration_eligibility_depends_on_protection_case_state
        """
        account = create_account(payment_history_score=720, existing_deposit_cents=50000)
        line = create_activated_line(account["id"], "4155551501", billing_mode="PREPAID")
        migration = create_migration_request(
            line, prepaid_balance_cents=0, requested_cutover_at="2026-10-01T00:00:00Z"
        )
        create_active_protection_case(line)

        check_migration_eligibility(migration["id"])

        refreshed_line = get_line(line["id"])
        assert refreshed_line["number_status"] == "UNASSIGNED"
        assert refreshed_line["port_protection_status"] == "PROTECTED"

    def test_the_suspension_reaches_the_owning_account(self, api):
        """PRD §3.3: "when the reason is protection specifically, the attached line's
        account also has `account_status` set to `SUSPENDED`."
        PRD §3.3: "When the request is blocked because of an open port request rather than
        protection, the account is left untouched."

        Design: Difficulty/cross_entity_state_dependency/migration_eligibility_depends_on_protection_case_state
        """
        account = create_account(payment_history_score=720, existing_deposit_cents=50000)
        line = create_activated_line(account["id"], "4155551501", billing_mode="PREPAID")
        migration = create_migration_request(
            line, prepaid_balance_cents=0, requested_cutover_at="2026-10-01T00:00:00Z"
        )
        create_active_protection_case(line)

        check_migration_eligibility(migration["id"])

        assert get_account(account["id"])["account_status"] == "SUSPENDED"


class TestMigrationEligibilityDependsOnOpenPortRequest:
    """With no protection case, an open port request still holds the migration."""

    def test_resubmitted_port_request_blocks_the_migration(self, api):
        """PRD §3.3: "or if any `PortRequest` on the attached line is sitting in
        `PENDING` or `RESUBMITTED`, the request goes to `BLOCKED`"

        Design: Difficulty/cross_entity_state_dependency/migration_eligibility_depends_on_open_port_request_state
        """
        create_rejection_code("ACCT_LOCKED", resubmission_allowed=True,
                              retry_after_hours=0)
        account = create_account(payment_history_score=720, existing_deposit_cents=50000)
        line = create_bare_line(account["id"], "4155551601", billing_mode="PREPAID")
        advance_clock("2026-09-02T00:00:00Z")
        request = create_draft_port_request(
            line, transfer_pin="1616", account_number_at_losing_carrier="ACC16",
            requested_cutover_at="2026-09-20T00:00:00Z",
        )
        submit_port_request(request, account_number_at_losing_carrier="ACC16")
        record_rejection(request["id"], "ACCT_LOCKED")
        resubmit_port_request(request)
        migration = create_migration_request(
            line, prepaid_balance_cents=0, requested_cutover_at="2026-10-01T00:00:00Z"
        )

        result = check_migration_eligibility(migration["id"])

        assert result["migration_state"] == "BLOCKED"

    def test_the_port_request_keeps_its_resubmitted_state(self, api):
        """PRD §3.2: "A successful resubmission sets `request_state` to `RESUBMITTED` and
        `submitted_at` to the current logical clock instant, and it re-reserves the
        attached line's number by setting `number_status` to `RESERVED`."

        Design: Difficulty/cross_entity_state_dependency/migration_eligibility_depends_on_open_port_request_state
        """
        create_rejection_code("ACCT_LOCKED", resubmission_allowed=True,
                              retry_after_hours=0)
        account = create_account(payment_history_score=720, existing_deposit_cents=50000)
        line = create_bare_line(account["id"], "4155551601", billing_mode="PREPAID")
        advance_clock("2026-09-02T00:00:00Z")
        request = create_draft_port_request(
            line, transfer_pin="1616", account_number_at_losing_carrier="ACC16",
            requested_cutover_at="2026-09-20T00:00:00Z",
        )
        submit_port_request(request, account_number_at_losing_carrier="ACC16")
        record_rejection(request["id"], "ACCT_LOCKED")
        resubmit_port_request(request)
        migration = create_migration_request(
            line, prepaid_balance_cents=0, requested_cutover_at="2026-10-01T00:00:00Z"
        )
        check_migration_eligibility(migration["id"])

        assert get_port_request(request["id"])["request_state"] == "RESUBMITTED"

    def test_the_blocked_migration_releases_the_number_without_suspending(self, api):
        """PRD §3.3: "When the request is blocked because of an open port request rather
        than protection, the account is left untouched."

        Design: Difficulty/cross_entity_state_dependency/migration_eligibility_depends_on_open_port_request_state
        """
        create_rejection_code("ACCT_LOCKED", resubmission_allowed=True,
                              retry_after_hours=0)
        account = create_account(payment_history_score=720, existing_deposit_cents=50000)
        line = create_bare_line(account["id"], "4155551601", billing_mode="PREPAID")
        advance_clock("2026-09-02T00:00:00Z")
        request = create_draft_port_request(
            line, transfer_pin="1616", account_number_at_losing_carrier="ACC16",
            requested_cutover_at="2026-09-20T00:00:00Z",
        )
        submit_port_request(request, account_number_at_losing_carrier="ACC16")
        record_rejection(request["id"], "ACCT_LOCKED")
        resubmit_port_request(request)
        migration = create_migration_request(
            line, prepaid_balance_cents=0, requested_cutover_at="2026-10-01T00:00:00Z"
        )
        check_migration_eligibility(migration["id"])

        assert get_line(line["id"])["number_status"] == "UNASSIGNED"
        assert get_account(account["id"])["account_status"] == "OPEN"


class TestReservationHalfOpenAdjacency:
    """Adjacency is permitted; nesting is not."""

    def test_a_hold_starting_at_the_prior_upper_bound_is_accepted(self, api):
        """PRD §3.9: "The hold interval is half-open: `reserved_at` is inside it and
        `reserved_until` is outside it."

        Design: Difficulty/resource_temporal_overlap/reservation_half_open_adjacency_allowed_overlap_rejected
        """
        account = create_account()
        create_reservation(
            account["id"], "4155551701",
            reserved_at="2026-09-02T00:00:00Z", reserved_until="2026-09-17T00:00:00Z",
        )

        adjacent = create_reservation(
            account["id"], "4155551702",
            reserved_at="2026-09-17T00:00:00Z", reserved_until="2026-10-02T00:00:00Z",
        )

        assert adjacent["reservation_state"] == "HELD"
        assert_number_reservation(adjacent)

    def test_a_hold_contained_by_the_existing_window_is_refused(self, api):
        """PRD §3.9: "The requested interval must not overlap an existing
        `NumberReservation` on the same `pool_code` whose `reservation_state` is `HELD`
        and whose `reserved_at` is strictly earlier than the new reservation's
        `reserved_at`; when it would, the creation fails with
        `ERR_RESERVATION_WINDOW_OVERLAP` (409)."

        Design: Difficulty/resource_temporal_overlap/reservation_half_open_adjacency_allowed_overlap_rejected
        """
        account = create_account()
        create_reservation(
            account["id"], "4155551701",
            reserved_at="2026-09-02T00:00:00Z", reserved_until="2026-09-17T00:00:00Z",
        )

        response = api_client.create_number_reservation(
            {
                "account_id": account["id"],
                "mdn": "4155551703",
                "pool_code": "POOL-A",
                "reserved_at": "2026-09-05T00:00:00Z",
                "reserved_until": "2026-09-20T00:00:00Z",
            },
            ADMIN,
        )

        assert response.json()["data"]["error_id"] == "ERR_RESERVATION_WINDOW_OVERLAP"
        assert get_account(account["id"])["reserved_mdn_count"] == 1

    def test_the_overlapping_hold_is_counted_only_once(self, api):
        """PRD §3.9: "A reservation is created in `reservation_state` `HELD`, with a null
        `committed_line_id`, and creation recomputes the owning account's
        `reserved_mdn_count`, which counts the account's reservations whose
        `reservation_state` is `HELD`."

        Design: Difficulty/resource_temporal_overlap/reservation_half_open_adjacency_allowed_overlap_rejected
        """
        account = create_account()
        create_reservation(
            account["id"], "4155551701",
            reserved_at="2026-09-02T00:00:00Z", reserved_until="2026-09-17T00:00:00Z",
        )
        create_reservation(
            account["id"], "4155551702",
            reserved_at="2026-09-17T00:00:00Z", reserved_until="2026-10-02T00:00:00Z",
        )

        assert get_account(account["id"])["reserved_mdn_count"] == 2


class TestPromoWindowBufferedAdjacency:
    """The promotional window uses buffered-closed arithmetic, not half-open."""

    def test_a_window_starting_where_the_prior_ended_is_refused(self, api):
        """PRD §3.4: "New promotions cannot be stacked end to end arbitrarily."
        PRD §3.4: "A window that starts inside another schedule's window plus the buffer
        is refused with `ERR_PROMO_WINDOW_OVERLAP` (409)."

        Design: Difficulty/resource_temporal_overlap/promo_window_buffered_adjacency_rejected
        """
        account, line, existing = setup_line_with_existing_schedule(
            "4155551801", window_start="2026-09-02T00:00:00Z",
            installment_months=1, retention_requirement_cycles=1,
        )

        response = api_client.create_promo_schedule(
            {
                "subscriber_line_id": line["id"],
                "promo_code": "SWITCH20",
                "monthly_credit_cents": 1000,
                "installment_months": 12,
                "retention_requirement_cycles": 12,
                "window_start": "2026-10-02T00:00:00Z",
                "expected_subscriber_line_version": get_line(line["id"])["version"],
            },
            CARE,
        )

        assert response.json()["data"]["error_id"] == "ERR_PROMO_WINDOW_OVERLAP"

    def test_a_different_line_accepts_a_window_past_the_buffer(self, api):
        """PRD §3.4: "this test only considers existing schedules whose `schedule_state`
        is `PROVISIONAL` or `ACTIVE` — a schedule that has already `VESTED` or been
        `CLAWED_BACK` imposes no buffer."

        Design: Difficulty/resource_temporal_overlap/promo_window_buffered_adjacency_rejected
        """
        account, first_line, existing = setup_line_with_existing_schedule(
            "4155551801", window_start="2026-09-02T00:00:00Z",
            installment_months=1, retention_requirement_cycles=1,
        )
        second_line = create_activated_line(
            account["id"], "4155551802", billing_mode="PREPAID"
        )

        created = create_promo_schedule(
            second_line,
            window_start="2026-11-01T00:00:00Z",
            installment_months=12,
            retention_requirement_cycles=12,
        )

        assert created["schedule_state"] == "PROVISIONAL"
        assert get_promo_schedule(existing["id"])["schedule_state"] == "ACTIVE"

    def test_the_existing_schedule_survives_the_refused_replacement(self, api):
        """PRD §3.4: "Starting to apply the credit moves the schedule from `PROVISIONAL`
        to `ACTIVE`, and it is permitted only while the schedule is `PROVISIONAL` and the
        current logical clock instant is at or after `window_start`"

        Design: Difficulty/resource_temporal_overlap/promo_window_buffered_adjacency_rejected
        """
        account, line, existing = setup_line_with_existing_schedule(
            "4155551803", window_start="2026-09-02T00:00:00Z",
            installment_months=1, retention_requirement_cycles=1,
        )
        api_client.create_promo_schedule(
            {
                "subscriber_line_id": line["id"],
                "promo_code": "SWITCH20",
                "monthly_credit_cents": 1000,
                "installment_months": 12,
                "retention_requirement_cycles": 12,
                "window_start": "2026-10-02T00:00:00Z",
                "expected_subscriber_line_version": get_line(line["id"])["version"],
            },
            CARE,
        )

        assert get_promo_schedule(existing["id"])["schedule_state"] == "ACTIVE"


class TestPromoCreditLedgerCompensatingInvariant:
    """The account ledger returns to zero after a claw-back."""

    def test_credited_and_clawed_back_totals_cancel(self, api):
        """PRD §3.4: "The reversal amount is exactly the schedule's own
        `provisional_total_cents` and nothing else. The rule reads only the schedule's own
        projected total and never the account's running totals, so a schedule that was
        created and then clawed back nets the account to zero: the credited increment and
        the clawed-back increment cancel."

        Design: Difficulty/compensating_invariant/promo_credit_ledger_returns_to_zero_after_clawback
        """
        account, line, plan, schedule = setup_line_with_plan_and_schedule(
            "4155551901", plan_price_cents=40000, installment_months=20,
            activate_schedule=True,
        )
        api_client.claw_back_promo_schedule(schedule["id"], {}, ADMIN)

        refreshed = get_account(account["id"])
        assert refreshed["promo_credited_cents"] == 32000
        assert refreshed["promo_clawed_back_cents"] == 32000
        assert refreshed["net_promo_credit_cents"] == 0
        assert_account_ledger_invariant(refreshed)

    def test_the_schedule_and_plan_move_by_the_same_reversed_amount(self, api):
        """PRD §3.4: "First, the schedule's `schedule_state` becomes `CLAWED_BACK` and its
        `vested_total_cents` is set to 0, and the attached line's
        `promo_eligibility_state` becomes `CLAWED_BACK`."
        PRD §3.4: "A device plan that is present receives the whole
        `provisional_total_cents` added to its `remaining_balance_cents` regardless of how
        much of the credit had actually vested"

        Design: Difficulty/compensating_invariant/promo_credit_ledger_returns_to_zero_after_clawback
        """
        account, line, plan, schedule = setup_line_with_plan_and_schedule(
            "4155551902", plan_price_cents=40000, installment_months=20,
            activate_schedule=True,
        )
        api_client.claw_back_promo_schedule(schedule["id"], {}, ADMIN)

        reverted = get_promo_schedule(schedule["id"])
        assert reverted["schedule_state"] == "CLAWED_BACK"
        assert reverted["vested_total_cents"] == 0
        assert get_line(line["id"])["promo_eligibility_state"] == "CLAWED_BACK"
        assert get_device_plan(plan["id"])["remaining_balance_cents"] == 72000


class TestReservedNumberInventoryBalancedByCommit:
    """The held-number count returns to zero when the hold is committed."""

    def test_commit_clears_the_hold_from_the_account_count(self, api):
        """PRD §3.9: "A successful commit sets the reservation's `committed_line_id` to
        the supplied `subscriber_line_id`, moves the reservation to the terminal
        `COMMITTED` state, sets that line's `number_status` to `ASSIGNED` and its `mdn` to
        the reservation's `mdn`"

        Design: Difficulty/compensating_invariant/reserved_number_inventory_balanced_by_commit
        """
        account = create_account(payment_history_score=720, existing_deposit_cents=50000)
        line = create_bare_line(account["id"], "4155552001", billing_mode="POSTPAID")
        reservation = create_reservation(
            account["id"], "4155552002",
            reserved_at="2026-09-01T00:00:00Z", reserved_until="2026-09-16T00:00:00Z",
        )
        assert get_account(account["id"])["reserved_mdn_count"] == 1

        committed = commit_reservation(reservation["id"], line["id"])

        assert committed["reservation_state"] == "COMMITTED"
        assert committed["committed_line_id"] == line["id"]

    def test_the_account_count_and_line_number_reflect_the_commit(self, api):
        """PRD §3.9: "The owning account's `reserved_mdn_count` and `active_line_count`
        are both recomputed."

        Design: Difficulty/compensating_invariant/reserved_number_inventory_balanced_by_commit
        """
        account = create_account(payment_history_score=720, existing_deposit_cents=50000)
        line = create_bare_line(account["id"], "4155552002", billing_mode="POSTPAID")
        reservation = create_reservation(
            account["id"], "4155552003",
            reserved_at="2026-09-01T00:00:00Z", reserved_until="2026-09-16T00:00:00Z",
        )

        commit_reservation(reservation["id"], line["id"])

        assert get_account(account["id"])["reserved_mdn_count"] == 0
        refreshed_line = get_line(line["id"])
        assert refreshed_line["number_status"] == "ASSIGNED"
        assert refreshed_line["mdn"] == "4155552003"
        assert_subscriber_line(refreshed_line)