"""Lifecycle transitions: valid hops, refused hops, initial and terminal states.

Each test drives one transition of one entity from an empty database and then
re-reads every row the PRD says the hop touches, so that a transition which
silently skips a cascade, or one that fires a cascade it should have refused, is
visible in the assertions rather than inferred.
"""

from test_helpers import (
    ADMIN,
    ADMIN_ALT,
    BOARD,
    COMPLIANCE,
    ApiErrorId,
    adopt_trading_plan,
    allocate_taxes,
    api_client,
    approve_grant_by_board,
    assert_grant,
    assert_instant_equals,
    assert_preclearance_request,
    assert_reserve_conservation,
    assert_share_split_identity,
    assert_tax_allocation,
    assert_trading_plan,
    assert_trading_window,
    assert_version_incremented,
    assert_vesting_event,
    create_cycle,
    create_draft_grant,
    create_granted_grant,
    create_mobility_assignment,
    create_participant,
    create_plan,
    create_preclearance,
    create_window,
    decide_preclearance,
    drive_window,
    make_participant_headers,
    read_event,
    read_grant,
    read_plan,
    read_preclearance,
    read_trading_plan,
    read_tranche,
    read_window,
    set_clock,
    settle_event,
    submit_grant,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    vest_tranche,
)
from test_helpers.test_users import ADMIN_USER_ID, COMPLIANCE_USER_ID

TIME_TRANCHE_2026_07_01 = [
    {
        "tranche_index": 1,
        "vest_type": "TIME",
        "scheduled_vest_date": "2026-07-01",
        "target_shares": 1000,
    }
]


def _plan_participant_and_draft(plan_name, participant_name, employee_number,
                                birth_date, tranches=None, **plan_overrides):
    """An ACTIVE plan of 1000000 authorised shares, an ACTIVE recipient, and one
    DRAFT RSU grant of 1000 shares carrying a single TIME tranche."""
    plan = create_plan(
        name=plan_name, total_authorized_shares=1000000,
        common_shares_outstanding=1000000, fiscal_year_start_date="2026-01-01",
        **plan_overrides,
    )
    participant = create_participant(
        full_name=participant_name, employee_number=employee_number,
        home_country_code="US", home_state_code="CA",
        hire_date="2020-01-06", birth_date=birth_date,
    )
    grant, tranche_rows = create_draft_grant(
        plan["id"], participant["id"],
        tranches=tranches if tranches is not None else TIME_TRANCHE_2026_07_01,
        award_type="RSU", target_shares=1000,
    )
    return plan, participant, grant, tranche_rows


class TestGrantSubmission:
    def test_submit_moves_a_draft_grant_to_pending_approval(self):
        """PRD §3.4: "Submitting moves a grant from `DRAFT` — or back from `CHANGES_REQUESTED` — to `PENDING_APPROVAL` and records the acting `X-User-ID` as `submitted_by_user_id`, overwriting any previous submitter."

        PRD §3.4: "A drafted grant begins at status `DRAFT` with `changes_requested_count` at 0, `grant_date` null, `approval_path` null, `approved_under_authority_id` null, `approved_by_user_id` null, `submitted_by_user_id` null, `approved_at` null, `cancel_reason` null, and both `weighted_reserve_shares` and `outstanding_shares` at 0. Nothing is committed against the plan reserve at draft time."

        PRD §2.4: "Most entities additionally carry `updated_at` — refreshed on every mutation of that row, in the same format — and `version`, an integer that starts at 1 when the row is created and increases by exactly 1 on every mutation of that row, including mutations caused by a cascade the client did not directly request."

        Design: Corner/state_machines/grant_submit_valid_transition_draft_to_pending_approval
        """
        set_clock("2026-01-05T09:00:00Z")
        plan, participant, grant, _ = _plan_participant_and_draft(
            "Corner Plan Hotel", "Sam Submit", "E-C-70", "1986-06-06",
        )
        assert grant["status"] == "DRAFT", "the grant starts in DRAFT"
        version_before = grant["version"]

        submitted = validate_success(api_client.submit_grant(grant["id"], ADMIN))

        assert_grant(submitted)
        assert submitted["status"] == "PENDING_APPROVAL", (
            "submitting moves the grant to PENDING_APPROVAL"
        )
        assert submitted["submitted_by_user_id"] == ADMIN_USER_ID, (
            "the acting identity is recorded as submitted_by_user_id"
        )
        assert submitted["changes_requested_count"] == 0, (
            "submission does not touch the send-back counter"
        )
        assert submitted["weighted_reserve_shares"] == 0, (
            "nothing is charged against the reserve before approval"
        )
        assert submitted["grant_date"] is None, "grant_date is written only at issuance"
        assert_version_incremented(submitted["version"], version_before)

        plan_after = read_plan(plan["id"])
        assert plan_after["shares_committed_cumulative"] == 0, (
            "no share is committed against the plan at submission"
        )
        assert plan_after["available_reserve_shares"] == 1000000, (
            "the reserve is untouched at submission"
        )
        assert_reserve_conservation(plan_after)

    def test_submitting_an_already_pending_grant_is_refused(self):
        """PRD §2.6: "The state gate — the addressed row must be in a state from which the requested transition exists — yielding the entity-specific invalid-state error described in §2.7. Replaying a transition that already succeeded lands here, which is how the system refuses idempotent repeats."

        PRD §2.7: "State failures resolve the same way, each carrying HTTP 409: `ERR_PLAN_INVALID_STATE`, `ERR_AUTHORITY_INVALID_STATE`, `ERR_PARTICIPANT_INVALID_STATE`, `ERR_GRANT_INVALID_STATE`, `ERR_TRANCHE_INVALID_STATE`, `ERR_CYCLE_INVALID_STATE`, `ERR_VESTING_EVENT_INVALID_STATE`, `ERR_WINDOW_INVALID_STATE`, `ERR_PRECLEARANCE_INVALID_STATE`, `ERR_TRADING_PLAN_INVALID_STATE`, and `ERR_REPORT_INVALID_STATE`."

        PRD §3.4: "Submitting moves a grant from `DRAFT` — or back from `CHANGES_REQUESTED` — to `PENDING_APPROVAL` and records the acting `X-User-ID` as `submitted_by_user_id`, overwriting any previous submitter."

        Design: Corner/state_machines/grant_submit_twice_second_attempt_rejected
        """
        set_clock("2026-01-05T09:00:00Z")
        _, _, grant, _ = _plan_participant_and_draft(
            "Corner Plan India", "Ida Idem", "E-C-71", "1986-07-07",
        )
        first = submit_grant(grant["id"], headers=ADMIN)
        assert first["status"] == "PENDING_APPROVAL", "the first submission succeeds"

        response = api_client.submit_grant(grant["id"], ADMIN_ALT)

        assert response.status_code == 409, "a replayed transition carries HTTP 409"
        validate_error(response, ApiErrorId.ERR_GRANT_INVALID_STATE)

        reread = read_grant(grant["id"])
        assert reread["status"] == "PENDING_APPROVAL", (
            "the refused replay leaves the grant in PENDING_APPROVAL"
        )
        assert reread["submitted_by_user_id"] == ADMIN_USER_ID, (
            "the refused replay does not overwrite the recorded submitter"
        )

    def test_approving_a_draft_grant_is_refused_before_any_fiscal_check(self):
        """PRD §2.6: "The state gate — the addressed row must be in a state from which the requested transition exists — yielding the entity-specific invalid-state error described in §2.7. Replaying a transition that already succeeded lands here, which is how the system refuses idempotent repeats."

        PRD §3.4: "Both paths move the grant from `PENDING_APPROVAL` to `APPROVED`, record `approved_by_user_id` from the acting `X-User-ID`, stamp `approved_at` from the logical clock, store the chosen `approval_path`, write `weighted_reserve_shares` from the calculation above, add that figure to the plan's `shares_committed_cumulative` and to its `fiscal_year_gross_granted_shares`, and then rerun the reserve ledger and both burn-rate variants."

        Design: Corner/state_machines/grant_approve_from_draft_status_is_rejected
        """
        set_clock("2026-01-05T09:00:00Z")
        plan, _, grant, _ = _plan_participant_and_draft(
            "Corner Plan Juliett", "Drew Draft", "E-C-72", "1986-08-08",
        )

        response = api_client.approve_grant(
            grant["id"], {"approval_path": "BOARD"}, BOARD
        )

        assert response.status_code == 409, (
            "DRAFT has no outgoing approve transition, so the state gate fires"
        )
        validate_error(response, ApiErrorId.ERR_GRANT_INVALID_STATE)

        reread = read_grant(grant["id"])
        assert reread["status"] == "DRAFT", "the refused approval leaves the grant in DRAFT"
        assert reread["approved_by_user_id"] is None, "no approver is recorded"
        assert reread["weighted_reserve_shares"] == 0, "no reserve charge is written"

        plan_after = read_plan(plan["id"])
        assert plan_after["shares_committed_cumulative"] == 0, (
            "the refused approval commits nothing"
        )
        assert plan_after["available_reserve_shares"] == 1000000, (
            "the refused approval consumes no reserve"
        )
        assert plan_after["fiscal_year_gross_granted_shares"] == 0, (
            "the refused approval touches no burn-rate accumulator"
        )


class TestInitialAndTerminalStates:
    def test_a_freshly_filed_preclearance_request_starts_in_submitted(self):
        """PRD §3.9: "The new request is `SUBMITTED` with `revision_count` at 0, `valid_until` null, `executed_shares` at 0, `decided_by_user_id`, `decided_at`, `decision_note`, `executed_at`, and `price_per_share_cents` all null, and `requested_by_user_id` recorded from the acting `X-User-ID` for the four-eyes control at decision time."

        PRD §3.9: "A `Participant` acting for themselves, or a `ComplianceOfficer` acting on an insider's behalf, files a preclearance request naming the `participant_id` seeking clearance, the `window_id` the trade would settle inside, a `transaction_type` of `SELL`, `BUY`, or `GIFT`, a `requested_shares` count of at least 1, and the `intended_trade_date` on which the participant intends to trade."

        PRD §3.9: "A new window is `SCHEDULED` with `approved_shares_cumulative` at 0 and `suspension_reason` null."

        Design: Corner/state_machines/preclearance_request_initial_state_is_submitted
        """
        set_clock("2026-01-06T10:00:00Z")
        plan = create_plan(
            name="Corner Plan Kilo", total_authorized_shares=1000000,
            common_shares_outstanding=1000000, fiscal_year_start_date="2026-01-01",
        )
        participant = create_participant(
            full_name="Ina Initial", employee_number="E-C-80",
            home_country_code="US", home_state_code="NY",
            hire_date="2019-02-04", birth_date="1982-02-02",
            insider_status="DESIGNATED_INSIDER",
        )
        window = create_window(
            plan["id"], quarter_label="FY2026-Q1",
            open_at="2026-01-05T00:00:00Z", close_at="2026-03-31T00:00:00Z",
        )
        drive_window(window["id"], "OPEN")

        request = validate_success(
            api_client.create_preclearance_request(
                {
                    "participant_id": participant["id"],
                    "window_id": window["id"],
                    "transaction_type": "SELL",
                    "requested_shares": 500,
                    "intended_trade_date": "2026-01-09",
                },
                make_participant_headers(participant["id"]),
            ),
            201,
        )

        assert_preclearance_request(request)
        assert request["status"] == "SUBMITTED", "a new request is SUBMITTED"
        assert request["revision_count"] == 0, "revision_count starts at 0"
        assert request["requested_by_user_id"] == participant["id"], (
            "the filing participant's own id is recorded as requested_by_user_id"
        )
        assert request["valid_until"] is None, "valid_until is null before a decision"
        assert request["decided_at"] is None, "decided_at is null before a decision"
        assert request["decided_by_user_id"] is None, (
            "decided_by_user_id is null before a decision"
        )
        assert request["decision_note"] is None, "decision_note starts null"
        assert request["executed_at"] is None, "executed_at starts null"
        assert request["price_per_share_cents"] is None, (
            "price_per_share_cents starts null"
        )
        assert request["executed_shares"] == 0, "executed_shares starts at 0"

        window_after = read_window(window["id"])
        assert window_after["approved_shares_cumulative"] == 0, (
            "filing a request takes no reservation against the window"
        )

    def test_a_closed_trading_window_refuses_every_remaining_action(self):
        """PRD §3.9: "`CLOSED` is terminal, and an action with no outgoing transition from the window's current status — `RESUME` on an `OPEN` window, or anything at all on a `CLOSED` window — is refused with `ERR_WINDOW_INVALID_STATE`."

        PRD §3.9: "`CLOSE` is reachable from `SCHEDULED`, `OPEN`, and `SUSPENDED`, moves the window to `CLOSED`, expires every `APPROVED` request of the window and voids every request that was `SUBMITTED` or `INFO_REQUESTED`, then recomputes `approved_shares_cumulative` over the surviving requests that are `APPROVED` or `EXECUTED`; the window's `version` and the `version` of every mutated request each advance by 1."

        Design: Corner/state_machines/trading_window_close_from_closed_is_terminal_lockdown
        """
        set_clock("2026-01-06T10:00:00Z")
        plan = create_plan(
            name="Corner Plan Lima", total_authorized_shares=1000000,
            common_shares_outstanding=1000000, fiscal_year_start_date="2026-01-01",
        )
        window = create_window(
            plan["id"], quarter_label="FY2026-Q1",
            open_at="2026-01-05T00:00:00Z", close_at="2026-03-31T00:00:00Z",
        )
        drive_window(window["id"], "OPEN")
        closed = drive_window(window["id"], "CLOSE")
        assert closed["status"] == "CLOSED", "the window reaches its terminal status"

        for action in ("CLOSE", "RESUME", "OPEN"):
            response = api_client.set_trading_window_status(
                window["id"], {"action": action}, COMPLIANCE
            )
            assert response.status_code == 409, (
                f"{action} has no outgoing transition from CLOSED"
            )
            validate_error(response, ApiErrorId.ERR_WINDOW_INVALID_STATE)

        reread = read_window(window["id"])
        assert reread["status"] == "CLOSED", "the window stays CLOSED"
        assert reread["suspension_reason"] is None, (
            "the refused actions write no suspension_reason"
        )
        assert_trading_window(reread)

    def test_issuance_needs_an_eligible_window_and_takes_its_open_at_date(self):
        """PRD §3.5: "Issuance is a `PlanAdministrator` operation that advances a grant from `APPROVED` to `GRANTED`, requires the plan to be `ACTIVE`, and writes `grant_date`. Every tranche keeps its `UNVESTED` status, and `outstanding_shares` is recomputed as the sum of `shares` over the tranches that are `UNVESTED` or `VESTED`."

        PRD §3.5: "If no window satisfies that test, the system looks instead at windows of the plan whose status is `SCHEDULED` and whose `open_at` is strictly after the logical clock; among those it chooses the one with the smallest `open_at`, breaking a tie in favour of the earlier `created_at`, and sets `grant_date` to that window's `open_at` calendar date."

        PRD §3.5: "When neither an eligible open window nor a future scheduled window exists, issuance is refused with `ERR_NO_ELIGIBLE_GRANT_DATE` (HTTP 409), nothing is written, and the grant stays in `APPROVED` until compliance schedules a new window."

        PRD §3.9: "Windows already `CLOSED` are ignored, so a replacement window may reuse a retired slot."

        Design: Corner/state_machines/grant_issue_precondition_requires_eligible_window
        """
        set_clock("2026-02-10T10:00:00Z")
        plan = create_plan(
            name="Corner Plan Mike", total_authorized_shares=1000000,
            common_shares_outstanding=1000000, fiscal_year_start_date="2026-01-01",
        )
        participant = create_participant(
            full_name="Win Dow", employee_number="E-C-90",
            home_country_code="US", home_state_code="CA",
            hire_date="2020-01-06", birth_date="1985-09-09",
        )
        retired_window = create_window(
            plan["id"], quarter_label="FY2026-Q1",
            open_at="2026-01-05T00:00:00Z", close_at="2026-02-01T00:00:00Z",
        )
        drive_window(retired_window["id"], "CLOSE")
        grant, _ = create_draft_grant(
            plan["id"], participant["id"],
            tranches=[{
                "tranche_index": 1,
                "vest_type": "TIME",
                "scheduled_vest_date": "2027-02-10",
                "target_shares": 1000,
            }],
            award_type="RSU", target_shares=1000,
        )
        submit_grant(grant["id"], headers=ADMIN)
        approved = approve_grant_by_board(grant["id"], headers=BOARD)
        assert approved["status"] == "APPROVED", "the award reaches APPROVED"

        refused = api_client.issue_grant(grant["id"], ADMIN)
        assert refused.status_code == 409, (
            "with only a CLOSED window there is no eligible grant date"
        )
        validate_error(refused, ApiErrorId.ERR_NO_ELIGIBLE_GRANT_DATE)
        still_approved = read_grant(grant["id"])
        assert still_approved["status"] == "APPROVED", (
            "the refused issuance leaves the grant APPROVED"
        )
        assert still_approved["grant_date"] is None, "no grant_date is written"

        future_window = validate_success(
            api_client.create_trading_window(
                {
                    "plan_id": plan["id"],
                    "quarter_label": "FY2026-Q2",
                    "open_at": "2026-04-06T13:30:00Z",
                    "close_at": "2026-06-30T00:00:00Z",
                },
                COMPLIANCE,
            ),
            201,
        )
        assert future_window["status"] == "SCHEDULED", (
            "the replacement window is accepted alongside the retired CLOSED one"
        )

        issued = validate_success(api_client.issue_grant(grant["id"], ADMIN))
        assert issued["status"] == "GRANTED", "the award now advances to GRANTED"
        assert issued["grant_date"] == "2026-04-06", (
            "grant_date is the calendar date of the future window's open_at"
        )
        assert issued["outstanding_shares"] == 1000, (
            "outstanding_shares is the sum of shares over the UNVESTED tranches"
        )


def _settled_share_withhold_scenario(plan_name, participant_name, employee_number,
                                     birth_date, settle=True):
    """A GRANTED RSU of 1000 shares whose single TIME tranche is vested at 2000
    cents under SHARE_WITHHOLD, with one contained US-CA sourcing period."""
    set_clock("2026-01-05T09:00:00Z")
    plan = create_plan(
        name=plan_name, total_authorized_shares=1000000,
        common_shares_outstanding=1000000, fiscal_year_start_date="2026-01-01",
    )
    participant = create_participant(
        full_name=participant_name, employee_number=employee_number,
        home_country_code="US", home_state_code="CA",
        hire_date="2020-01-06", birth_date=birth_date,
    )
    window = create_window(
        plan["id"], quarter_label="FY2026-Q1",
        open_at="2026-01-05T00:00:00Z", close_at="2026-03-31T00:00:00Z",
    )
    drive_window(window["id"], "OPEN")
    grant, tranches = create_granted_grant(
        plan["id"], participant["id"], tranches=TIME_TRANCHE_2026_07_01,
        award_type="RSU", target_shares=1000,
    )
    create_mobility_assignment(
        participant["id"], jurisdiction_code="US-CA", tax_rate_bps=3000,
        start_date="2026-01-06", end_date="2026-06-30", workdays=200,
    )
    set_clock("2026-07-01T12:00:00Z")
    event = vest_tranche(
        tranches[0]["id"], fmv_per_share_cents=2000,
        withholding_method="SHARE_WITHHOLD",
    )
    if settle:
        allocate_taxes(event["id"])
        settle_event(event["id"])
    return {
        "plan": read_plan(plan["id"]),
        "participant": participant,
        "window": window,
        "grant": read_grant(grant["id"]),
        "tranche": read_tranche(tranches[0]["id"]),
        "event": read_event(event["id"]),
    }


class TestSettlementCascades:
    def test_allocation_and_settlement_advance_two_independent_dimensions(self):
        """PRD §3.7: "A settlement carries two statuses that advance independently. `tax_status` moves along `PENDING_ALLOCATION → ALLOCATED`, and `settlement_status` moves along `PENDING_TAX → SETTLED → REVERSED`. Allocating taxes moves the first dimension and leaves the second alone; settling moves the second and leaves the first alone. They are independent but ordered: shares cannot be delivered before the jurisdictional withholding is known, because the withheld share count is derived from the allocated tax total."

        PRD §3.7: "That record starts with `tax_status` at `PENDING_ALLOCATION` and `settlement_status` at `PENDING_TAX`; its `tranche_id` points back at the tranche, its `gross_shares` is a snapshot of the tranche's `shares` at that moment, its `vest_date` is the logical clock's calendar date, its `sourcing_start_date` is copied from the owning grant's `grant_date`, and its `taxable_income_cents` is `gross_shares` multiplied by `fmv_per_share_cents`."

        PRD §3.7: "Third, each group's `tax_amount_cents` is the settlement's `taxable_income_cents` multiplied by that group's `allocation_bps` multiplied by that group's rate, divided by 100000000, rounded half up to whole cents; the division is evaluated once over the exact product, with no intermediate rounding after the allocation step. Fourth, the settlement's `total_tax_cents` is the sum of those already-rounded per-jurisdiction amounts — round first, then sum. Summing the exact per-jurisdiction values and rounding once at the end is explicitly not the pinned order and can differ by a cent. Finally, `blended_rate_bps` is `total_tax_cents` multiplied by 10000, divided by `taxable_income_cents`, rounded half up to whole basis points."

        PRD §3.7: "The run materialises one immutable tax row per contributing jurisdiction, each carrying its `vesting_event_id`, its `jurisdiction_code`, the `workdays_in_period` sourced to it, its `allocation_bps`, the `tax_rate_bps` copied from the contributing assignment records, and its `tax_amount_cents`. The settlement's `total_workdays`, `total_tax_cents`, and `blended_rate_bps` are written, `tax_status` becomes `ALLOCATED`, `settlement_status` stays at `PENDING_TAX`, and the settlement's `version` advances by 1."

        PRD §3.7: "Under `SHARE_WITHHOLD`, `shares_withheld` is the total tax divided by the fair market value per share, rounded up to the next whole share; `shares_sold` is 0; `net_shares_delivered` is `gross_shares` minus `shares_withheld`; `residual_cash_cents` is `shares_withheld` multiplied by the fair market value per share, minus the total tax — the over-withholding refunded to the participant; and `cash_due_cents` is 0. No commission is charged."

        PRD §3.7: "Settling records the `withholding_method` in force, writes the five derived figures, moves `settlement_status` to `SETTLED`, and moves the owning tranche from `VESTED` to `SETTLED`, which causes the grant's `outstanding_shares` to be recomputed — a `SETTLED` tranche leaves the outstanding pool while remaining committed against the reserve. Both the settlement's `version` and the tranche's `version` advance by 1."

        Design: Corner/state_machines/vesting_event_tax_and_settlement_dimensions_advance_independently
        """
        set_clock("2026-01-05T09:00:00Z")
        plan = create_plan(
            name="Corner Plan November", total_authorized_shares=1000000,
            common_shares_outstanding=1000000, fiscal_year_start_date="2026-01-01",
        )
        participant = create_participant(
            full_name="Vera Vest", employee_number="E-C-100",
            home_country_code="US", home_state_code="CA",
            hire_date="2020-01-06", birth_date="1984-04-04",
        )
        window = create_window(
            plan["id"], quarter_label="FY2026-Q1",
            open_at="2026-01-05T00:00:00Z", close_at="2026-03-31T00:00:00Z",
        )
        drive_window(window["id"], "OPEN")
        grant, tranches = create_granted_grant(
            plan["id"], participant["id"], tranches=TIME_TRANCHE_2026_07_01,
            award_type="RSU", target_shares=1000,
        )
        assert grant["grant_date"] == "2026-01-05", (
            "the clock sits inside the OPEN window, so the grant date is the clock date"
        )
        create_mobility_assignment(
            participant["id"], jurisdiction_code="US-CA", tax_rate_bps=3000,
            start_date="2026-01-06", end_date="2026-06-30", workdays=200,
        )
        set_clock("2026-07-01T12:00:00Z")
        event = vest_tranche(
            tranches[0]["id"], fmv_per_share_cents=2000,
            withholding_method="SHARE_WITHHOLD",
        )
        assert event["tax_status"] == "PENDING_ALLOCATION", (
            "a fresh settlement starts at PENDING_ALLOCATION"
        )
        assert event["settlement_status"] == "PENDING_TAX", (
            "a fresh settlement starts at PENDING_TAX"
        )

        allocated = validate_success(
            api_client.allocate_taxes(event["id"], COMPLIANCE)
        )

        assert_vesting_event(allocated)
        assert allocated["tax_status"] == "ALLOCATED", (
            "allocating moves the tax dimension to ALLOCATED"
        )
        assert allocated["settlement_status"] == "PENDING_TAX", (
            "allocating leaves the settlement dimension alone"
        )
        assert allocated["taxable_income_cents"] == 2000000, (
            "1000 gross shares at 2000 cents is 2000000 cents of income"
        )
        assert allocated["total_workdays"] == 200, (
            "the single contained period sources 200 workdays"
        )
        assert allocated["total_tax_cents"] == 600000, (
            "2000000 cents at 10000 allocation basis points and 3000 bps is 600000 cents"
        )
        assert allocated["blended_rate_bps"] == 3000, (
            "600000 * 10000 / 2000000 is a blended rate of 3000 basis points"
        )

        rows, meta = validate_paginated(
            api_client.list_event_tax_allocations(event["id"], ADMIN)
        )
        assert meta["total_count"] == 1, "one immutable tax row per contributing jurisdiction"
        allocation = rows[0]
        assert_tax_allocation(allocation)
        assert allocation["jurisdiction_code"] == "US-CA", "the sourced jurisdiction is US-CA"
        assert allocation["allocation_bps"] == 10000, (
            "a single jurisdiction takes the whole 10000 basis points"
        )
        assert allocation["tax_rate_bps"] == 3000, (
            "the rate is copied from the contributing assignment record"
        )
        assert allocation["tax_amount_cents"] == 600000, (
            "the jurisdiction's tax amount is 600000 cents"
        )
        assert allocation["workdays_in_period"] == 200, (
            "the workdays sourced to the jurisdiction are recorded"
        )

        settled = validate_success(
            api_client.settle_vesting_event(event["id"], ADMIN)
        )

        assert settled["settlement_status"] == "SETTLED", (
            "settling moves the settlement dimension to SETTLED"
        )
        assert settled["tax_status"] == "ALLOCATED", (
            "settling leaves the tax dimension at ALLOCATED"
        )
        assert settled["shares_withheld"] == 300, (
            "600000 cents of tax over 2000 cents per share withholds 300 shares"
        )
        assert settled["shares_sold"] == 0, "SHARE_WITHHOLD sells no share"
        assert settled["net_shares_delivered"] == 700, (
            "1000 gross shares minus 300 withheld delivers 700"
        )
        assert settled["residual_cash_cents"] == 0, (
            "300 shares at 2000 cents exactly covers the 600000 cent tax"
        )
        assert settled["cash_due_cents"] == 0, "SHARE_WITHHOLD leaves no cash due"
        assert_share_split_identity(settled)

        tranche_after = read_tranche(tranches[0]["id"])
        assert tranche_after["status"] == "SETTLED", (
            "settling moves the owning tranche from VESTED to SETTLED"
        )

        plan_after = read_plan(plan["id"])
        assert plan_after["available_reserve_shares"] == 999000, (
            "the 1000 weighted shares remain committed after settlement"
        )
        assert plan_after["shares_returned_cumulative"] == 0, (
            "settlement returns nothing to the reserve"
        )
        assert_reserve_conservation(plan_after)

    def test_cancelling_a_grant_with_a_settled_tranche_is_refused(self):
        """PRD §3.4: "It is reachable from `DRAFT`, `PENDING_APPROVAL`, `CHANGES_REQUESTED`, `APPROVED`, `GRANTED`, and `PARTIALLY_FORFEITED`, requires the plan to be `ACTIVE`, and is impossible once any tranche of the grant has reached `SETTLED`."

        PRD §2.7: "State failures resolve the same way, each carrying HTTP 409: `ERR_PLAN_INVALID_STATE`, `ERR_AUTHORITY_INVALID_STATE`, `ERR_PARTICIPANT_INVALID_STATE`, `ERR_GRANT_INVALID_STATE`, `ERR_TRANCHE_INVALID_STATE`, `ERR_CYCLE_INVALID_STATE`, `ERR_VESTING_EVENT_INVALID_STATE`, `ERR_WINDOW_INVALID_STATE`, `ERR_PRECLEARANCE_INVALID_STATE`, `ERR_TRADING_PLAN_INVALID_STATE`, and `ERR_REPORT_INVALID_STATE`."

        PRD §3.1: "The `NET` variant writes `net_burn_rate_bps` and equals `fiscal_year_gross_granted_shares` minus `fiscal_year_returned_shares`, multiplied by 10000, divided by `common_shares_outstanding`, rounded half up to whole basis points, with the result floored at zero so that a fiscal year in which more shares came back than went out reports 0 rather than a negative rate."

        Design: Corner/state_machines/grant_cancel_blocked_when_a_tranche_is_settled
        """
        scenario = _settled_share_withhold_scenario(
            "Corner Plan Oscar", "Seth Settle", "E-C-110", "1984-05-05",
        )
        assert scenario["tranche"]["status"] == "SETTLED", (
            "the award's only tranche has been delivered"
        )
        assert scenario["grant"]["status"] == "GRANTED", "the award is GRANTED"

        response = api_client.cancel_grant(
            scenario["grant"]["id"],
            {"cancel_reason": "administrative rescission attempt after settlement"},
            BOARD,
        )

        assert response.status_code == 409, (
            "a settled award can never be unwound by cancellation"
        )
        validate_error_is_one_of(
            response,
            [ApiErrorId.ERR_GRANT_INVALID_STATE, ApiErrorId.ERR_TRANCHE_INVALID_STATE],
        )

        grant_after = read_grant(scenario["grant"]["id"])
        assert grant_after["status"] == "GRANTED", "the refused cancel leaves the award GRANTED"
        assert grant_after["cancel_reason"] is None, "no cancel_reason is stored"
        assert read_tranche(scenario["tranche"]["id"])["status"] == "SETTLED", (
            "the delivered tranche is untouched"
        )

        plan_after = read_plan(scenario["plan"]["id"])
        assert plan_after["shares_committed_cumulative"] == 1000, (
            "the committed weight stays committed"
        )
        assert plan_after["shares_returned_cumulative"] == 0, (
            "no reserve is credited back by a refused cancel"
        )
        assert plan_after["available_reserve_shares"] == 999000, (
            "the available reserve is unchanged"
        )
        assert plan_after["net_burn_rate_bps"] == 10, (
            "1000 net granted shares over 1000000 outstanding is 10 basis points"
        )


def _open_window_with_two_requests(plan_name, participant_name, employee_number,
                                   birth_date):
    """An OPEN capped window holding one SUBMITTED request of 400 shares and one
    APPROVED request of 600 shares filed by the same insider."""
    set_clock("2026-01-06T10:00:00Z")
    plan = create_plan(
        name=plan_name, total_authorized_shares=1000000,
        common_shares_outstanding=1000000, fiscal_year_start_date="2026-01-01",
    )
    participant = create_participant(
        full_name=participant_name, employee_number=employee_number,
        home_country_code="US", home_state_code="NY",
        hire_date="2018-03-05", birth_date=birth_date,
        insider_status="DESIGNATED_INSIDER",
    )
    window = create_window(
        plan["id"], quarter_label="FY2026-Q1",
        open_at="2026-01-05T00:00:00Z", close_at="2026-03-31T00:00:00Z",
        aggregate_share_cap=5000,
    )
    drive_window(window["id"], "OPEN")
    submitted = create_preclearance(
        participant["id"], window["id"], requested_shares=400,
        intended_trade_date="2026-01-09",
    )
    approved_request = create_preclearance(
        participant["id"], window["id"], requested_shares=600,
        intended_trade_date="2026-01-12",
    )
    approved_request = decide_preclearance(
        approved_request["id"], "APPROVE", headers=COMPLIANCE
    )
    return plan, participant, read_window(window["id"]), submitted, approved_request


class TestWindowCascades:
    def test_suspending_a_window_voids_its_open_requests(self):
        """PRD §3.9: "`SUSPEND` moves an `OPEN` window to `SUSPENDED`, stores the `suspension_reason`, and voids every preclearance request of that window whose status is `SUBMITTED`, `INFO_REQUESTED`, or `APPROVED`, after which `approved_shares_cumulative` is recomputed over the survivors; the window's `version` and the `version` of every voided request each advance by 1."

        PRD §3.9: "On success the request becomes `APPROVED`, `decided_by_user_id`, `decided_at`, and `decision_note` are stored, `valid_until` is computed as described below, the window's `approved_shares_cumulative` is increased by `requested_shares`, and both the request's `version` and the window's `version` advance by 1."

        PRD §3.9: "On approval, `valid_until` is the earlier of the `decided_at` instant advanced by 5 days and the window's own `close_at` — a clearance is good for five days or until the window closes, whichever comes first. The arithmetic is exact instant arithmetic."

        Design: Corner/state_machines/window_suspend_voids_open_requests_and_recomputes_cumulative
        """
        _, _, window, submitted, approved_request = _open_window_with_two_requests(
            "Corner Plan Papa", "Sue Spend", "E-C-120", "1981-01-01",
        )
        assert window["approved_shares_cumulative"] == 600, (
            "the approved 600-share request reserves against the window"
        )

        suspended = validate_success(
            api_client.set_trading_window_status(
                window["id"],
                {"action": "SUSPEND", "suspension_reason": "pending 8-K"},
                COMPLIANCE,
            )
        )

        assert suspended["status"] == "SUSPENDED", "SUSPEND moves the window to SUSPENDED"
        assert suspended["suspension_reason"] == "pending 8-K", (
            "the supplied suspension_reason is stored"
        )
        assert suspended["approved_shares_cumulative"] == 0, (
            "the cumulative figure is recomputed over the survivors, of which there are none"
        )

        assert read_preclearance(submitted["id"])["status"] == "VOID", (
            "the SUBMITTED request is voided by the suspension"
        )
        voided_approval = read_preclearance(approved_request["id"])
        assert voided_approval["status"] == "VOID", (
            "the APPROVED request is voided by the suspension"
        )
        assert_instant_equals(
            voided_approval["valid_until"], "2026-01-11T10:00:00.000Z",
            "valid_until",
        )
        assert voided_approval["decided_by_user_id"] == COMPLIANCE_USER_ID, (
            "the cascade voids the status without clearing the decision fields"
        )

    def test_closing_a_window_expires_approvals_and_voids_submissions(self):
        """PRD §3.9: "`CLOSE` is reachable from `SCHEDULED`, `OPEN`, and `SUSPENDED`, moves the window to `CLOSED`, expires every `APPROVED` request of the window and voids every request that was `SUBMITTED` or `INFO_REQUESTED`, then recomputes `approved_shares_cumulative` over the surviving requests that are `APPROVED` or `EXECUTED`; the window's `version` and the `version` of every mutated request each advance by 1."

        PRD §3.9: "`EXPIRED` is reached only from `APPROVED`, and only by the window-close cascade."

        PRD §3.9: "Requests are listable with optional `participant_id`, `window_id`, and `status` filters, and readable individually."

        Design: Corner/state_machines/window_close_expires_approved_and_voids_submitted
        """
        _, _, window, submitted, approved_request = _open_window_with_two_requests(
            "Corner Plan Quebec", "Cleo Close", "E-C-121", "1981-02-02",
        )

        closed = validate_success(
            api_client.set_trading_window_status(
                window["id"], {"action": "CLOSE"}, COMPLIANCE
            )
        )

        assert closed["status"] == "CLOSED", "CLOSE moves the window to CLOSED"
        assert read_preclearance(submitted["id"])["status"] == "VOID", (
            "a still-SUBMITTED request is voided by the close"
        )
        assert read_preclearance(approved_request["id"])["status"] == "EXPIRED", (
            "an APPROVED request is expired by the close"
        )

        expired_rows, expired_meta = validate_paginated(
            api_client.list_preclearance_requests(
                COMPLIANCE, params={"window_id": window["id"], "status": "EXPIRED"}
            )
        )
        assert expired_meta["total_count"] == 1, (
            "exactly one request of the window lands in EXPIRED"
        )
        assert [row["id"] for row in expired_rows] == [approved_request["id"]], (
            "the expired row is the one that had been approved"
        )

        all_rows, _ = validate_paginated(
            api_client.list_preclearance_requests(
                COMPLIANCE, params={"window_id": window["id"]}
            )
        )
        live_statuses = [
            row["status"] for row in all_rows
            if row["status"] in ("SUBMITTED", "INFO_REQUESTED", "APPROVED")
        ]
        assert live_statuses == [], (
            f"no request of a closed window stays actionable, found {live_statuses}"
        )


class TestCoolingOffAndCascadeBranches:
    def test_trading_plan_activation_at_the_exact_cooling_off_boundary(self):
        """PRD §3.9: "A successful adoption creates the plan in `PENDING_COOLING_OFF` with `modification_count` at 0, `termination_reason` and `superseded_plan_id` null, `adopted_at` stamped from the logical clock, and `insider_status_at_adoption` frozen from the participant's `insider_status` at that instant."

        PRD §3.9: "A `DESIGNATED_INSIDER` adoption has a fixed cooling-off period of 30 days."

        PRD §3.9: "`first_trade_allowed_at` is then `adopted_at` advanced by `cooling_off_days` whole days using exact instant arithmetic, so the time of day of `adopted_at` is preserved rather than being truncated to midnight."

        PRD §3.9: "Only a `ComplianceOfficer` activates a plan, and only from `PENDING_COOLING_OFF`; any other status is `ERR_TRADING_PLAN_INVALID_STATE`. The logical clock must be at or after `first_trade_allowed_at` — activating at exactly that instant is permitted, one millisecond earlier is refused with `ERR_COOLING_OFF_NOT_ELAPSED` — and the participant's employment must be `ACTIVE`. The plan becomes `EFFECTIVE` and its `version` advances by 1."

        Design: Corner/state_machines/trading_plan_activation_at_exact_cooling_off_boundary
        """
        set_clock("2026-01-06T10:00:00Z")
        create_plan(
            name="Corner Plan Romeo", total_authorized_shares=1000000,
            common_shares_outstanding=1000000, fiscal_year_start_date="2026-01-01",
            next_earnings_release_at="2026-02-10T21:00:00Z",
        )
        participant = create_participant(
            full_name="Cole Ling", employee_number="E-C-130",
            home_country_code="US", home_state_code="NY",
            hire_date="2017-06-05", birth_date="1979-03-03",
            insider_status="DESIGNATED_INSIDER",
        )

        trading_plan = adopt_trading_plan(
            participant["id"], participant["version"],
            plan_document_ref="10b5-1/2026/001",
            first_scheduled_trade_date="2026-03-02", total_shares=1200,
        )

        assert_trading_plan(trading_plan)
        assert trading_plan["status"] == "PENDING_COOLING_OFF", (
            "a freshly adopted plan waits out its cooling-off period"
        )
        assert trading_plan["insider_status_at_adoption"] == "DESIGNATED_INSIDER", (
            "the classification is frozen at adoption"
        )
        assert_instant_equals(
            trading_plan["adopted_at"], "2026-01-06T10:00:00.000Z", "adopted_at"
        )
        assert trading_plan["cooling_off_days"] == 30, (
            "a DESIGNATED_INSIDER adoption carries a fixed 30-day period"
        )
        assert_instant_equals(
            trading_plan["first_trade_allowed_at"], "2026-02-05T10:00:00.000Z",
            "first_trade_allowed_at",
        )
        assert trading_plan["modification_count"] == 0, "modification_count starts at 0"
        assert trading_plan["superseded_plan_id"] is None, (
            "superseded_plan_id starts null"
        )

        set_clock("2026-02-05T09:59:59.999Z", COMPLIANCE)
        too_early = api_client.activate_trading_plan(trading_plan["id"], COMPLIANCE)
        assert too_early.status_code == 409, (
            "one millisecond before the boundary the cooling-off period has not elapsed"
        )
        validate_error(too_early, ApiErrorId.ERR_COOLING_OFF_NOT_ELAPSED)
        assert read_trading_plan(trading_plan["id"])["status"] == "PENDING_COOLING_OFF", (
            "the refused activation leaves the plan in PENDING_COOLING_OFF"
        )

        set_clock("2026-02-05T10:00:00.000Z", COMPLIANCE)
        activated = validate_success(
            api_client.activate_trading_plan(trading_plan["id"], COMPLIANCE)
        )
        assert activated["status"] == "EFFECTIVE", (
            "activating at exactly first_trade_allowed_at is permitted"
        )

    def test_for_cause_termination_claws_back_a_vested_tranche(self):
        """PRD §3.8: "The request first sets `employment_status` to `TERMINATED`, stores `termination_date` and `termination_reason`, and freezes `age_years`, `service_years`, and `retirement_eligible` as they stand at the termination date."

        PRD §3.8: "It also writes `ptep_expiry_date`, the date on which the post-termination exercise period ends: the `termination_date` advanced by 0 days for `FOR_CAUSE`, 90 days for `VOLUNTARY`, 180 days for `INVOLUNTARY`, 1095 days for `RETIREMENT`, and 365 days for `DEATH`. A `FOR_CAUSE` termination therefore expires the exercise period on the termination date itself."

        PRD §3.8: "For each tranche already `VESTED`, the reason decides: under `FOR_CAUSE` the tranche is clawed back to `FORFEITED`, and under every other reason it is left alone. The clawback only applies while no settlement of that tranche has reached `SETTLED`; delivered shares are not retracted. When a `VESTED` tranche is clawed back, every settlement of that tranche still sitting at `PENDING_TAX` moves to `REVERSED` with `reversal_reason` set to `FOR_CAUSE_CLAWBACK`, and any tax rows of those settlements are deleted."

        PRD §3.8: "A grant whose recomputed `outstanding_shares` is greater than zero moves to `PARTIALLY_FORFEITED`; a grant whose `outstanding_shares` recomputes to exactly 0 and none of whose tranches is `SETTLED` moves to `FORFEITED` with both `outstanding_shares` and `weighted_reserve_shares` set to 0."

        PRD §3.8: "Each grant's weight decrease from hop 2 is added to the plan's `shares_returned_cumulative` and to its `fiscal_year_returned_shares`. A fully forfeited grant returns its entire prior `weighted_reserve_shares`. The reserve ledger is then rerun, rewriting `available_reserve_shares`, and the net burn rate is recomputed. The gross burn rate is not unwound."

        PRD §3.7: "When the participant's `insider_status` is `SECTION_16_OFFICER` or `DESIGNATED_INSIDER`, settling also creates one Section 16 report, described in §3.9."

        Design: Corner/state_machines/for_cause_termination_clawback_reverses_pending_vesting_event
        """
        set_clock("2026-01-05T09:00:00Z")
        plan = create_plan(
            name="Corner Plan Sierra", total_authorized_shares=1000000,
            common_shares_outstanding=1000000, fiscal_year_start_date="2026-01-01",
        )
        participant = create_participant(
            full_name="Cass Cause", employee_number="E-C-140",
            home_country_code="US", home_state_code="CA",
            hire_date="2020-01-06", birth_date="1983-03-03",
        )
        window = create_window(
            plan["id"], quarter_label="FY2026-Q1",
            open_at="2026-01-05T00:00:00Z", close_at="2026-03-31T00:00:00Z",
        )
        drive_window(window["id"], "OPEN")
        grant, tranches = create_granted_grant(
            plan["id"], participant["id"], tranches=TIME_TRANCHE_2026_07_01,
            award_type="RSU", target_shares=1000,
        )
        set_clock("2026-07-01T12:00:00Z")
        event = vest_tranche(tranches[0]["id"], fmv_per_share_cents=2000)
        assert event["settlement_status"] == "PENDING_TAX", (
            "the settlement is still awaiting tax treatment"
        )
        set_clock("2026-07-02T09:00:00Z")

        terminated = validate_success(
            api_client.terminate_participant(
                participant["id"],
                {"termination_date": "2026-07-02", "termination_reason": "FOR_CAUSE"},
                ADMIN,
            )
        )

        assert terminated["employment_status"] == "TERMINATED", (
            "the recipient's employment ends"
        )
        assert terminated["termination_reason"] == "FOR_CAUSE", (
            "the supplied reason is stored"
        )
        assert terminated["termination_date"] == "2026-07-02", (
            "the supplied termination date is stored"
        )
        assert terminated["ptep_expiry_date"] == "2026-07-02", (
            "FOR_CAUSE advances the exercise period by 0 days"
        )

        assert read_tranche(tranches[0]["id"])["status"] == "FORFEITED", (
            "FOR_CAUSE claws the VESTED tranche back to FORFEITED"
        )
        event_after = read_event(event["id"])
        assert event_after["settlement_status"] == "REVERSED", (
            "the settlement still at PENDING_TAX is reversed by the clawback"
        )
        assert event_after["tax_status"] == "PENDING_ALLOCATION", (
            "the tax dimension is driven back to PENDING_ALLOCATION"
        )

        grant_after = read_grant(grant["id"])
        assert grant_after["status"] == "FORFEITED", (
            "a grant whose outstanding shares recompute to 0 with no SETTLED tranche is FORFEITED"
        )
        assert grant_after["weighted_reserve_shares"] == 0, (
            "a fully forfeited grant carries no reserve charge"
        )
        assert grant_after["outstanding_shares"] == 0, (
            "a fully forfeited grant holds no outstanding shares"
        )

        plan_after = read_plan(plan["id"])
        assert plan_after["shares_committed_cumulative"] == 1000, (
            "the original commitment stays on the cumulative accumulator"
        )
        assert plan_after["shares_returned_cumulative"] == 1000, (
            "the fully forfeited grant returns its entire prior weight"
        )
        assert plan_after["available_reserve_shares"] == 1000000, (
            "1000000 - 1000 + 1000 restores the whole reserve"
        )
        assert plan_after["reserve_posture"] == "OPEN", "the restored reserve is OPEN"
        assert plan_after["gross_burn_rate_bps"] == 10, (
            "the gross burn rate is deliberately not unwound"
        )
        assert plan_after["net_burn_rate_bps"] == 0, (
            "1000 granted minus 1000 returned nets to a 0 basis point rate"
        )
        assert_reserve_conservation(plan_after)

        _, report_meta = validate_paginated(
            api_client.list_participant_transaction_reports(
                participant["id"], COMPLIANCE
            )
        )
        assert report_meta["total_count"] == 0, (
            "no settlement completed, so no Section 16 report exists"
        )

    def test_a_below_floor_certification_cancels_the_cycle_and_forfeits_its_tranche(self):
        """PRD §3.6: "The achievement ratio is the `actual_value` divided by the `target_value`, rounded half up to six decimal places before anything else happens."

        PRD §3.6: "That ratio is then looked up against a tier schedule whose boundaries are inclusive on the lower edge: a ratio below 0.800000 pays 0 basis points; a ratio from 0.800000 up to but not including 0.900000 pays 5000; from 0.900000 up to but not including 1.000000 pays 7500; from 1.000000 up to but not including 1.100000 pays 10000; from 1.100000 up to but not including 1.200000 pays 15000; and a ratio of 1.200000 or more pays the maximum of 20000."

        PRD §3.6: "The same operation takes a completely different shape when the achievement ratio falls below the zero-payout floor of 0.800000, which is exactly the condition that makes `payout_multiplier_bps` equal 0. In that case the cycle moves from `OPEN` to `CANCELLED` rather than to `CERTIFIED`, stores `actual_value` and a multiplier of 0, and stamps `certified_at`; every tranche bound to the cycle whose status is `UNVESTED` moves to `FORFEITED` with its `shares` set to 0. The second hop recomputes each owning grant's `outstanding_shares` and `weighted_reserve_shares` and moves the grant to `PARTIALLY_FORFEITED` or `FORFEITED` exactly as the termination cascade of §3.8 does. The third hop adds the weight decrease to `shares_returned_cumulative` and `fiscal_year_returned_shares` and recomputes `available_reserve_shares` and `reserve_posture`. The cycle's `version` and the `version` of every mutated row each advance by 1. A below-floor certification therefore forfeits rather than revalues, and the two branches of the same certification operation carry genuinely different side-effect sets."

        PRD §3.4: "First, the committed share count is the sum of `shares` over the grant's tranches whose status is `UNVESTED`, `VESTED`, or `SETTLED`; a `FORFEITED` tranche never contributes, and the sum is 0 when no tranche qualifies."

        PRD §3.4: "Separately, `outstanding_shares` is the sum of `shares` over the grant's tranches whose status is `UNVESTED` or `VESTED`, which is a narrower set than the reserve charge because a `SETTLED` tranche has left the outstanding pool while remaining committed against the reserve."

        Design: Corner/state_machines/performance_cycle_zero_payout_cancels_cycle_and_forfeits_tranches
        """
        set_clock("2026-01-05T09:00:00Z")
        plan = create_plan(
            name="Corner Plan Tango", total_authorized_shares=1000000,
            common_shares_outstanding=1000000, fiscal_year_start_date="2026-01-01",
        )
        participant = create_participant(
            full_name="Zed Zero", employee_number="E-C-150",
            home_country_code="US", home_state_code="CA",
            hire_date="2020-01-06", birth_date="1985-12-12",
        )
        cycle = create_cycle(
            plan["id"], headers=ADMIN, metric_code="TSR-2026", target_value=200,
            certification_due_date="2027-02-15",
        )
        grant, tranches = create_draft_grant(
            plan["id"], participant["id"],
            tranches=[{
                "tranche_index": 1,
                "vest_type": "PERFORMANCE",
                "scheduled_vest_date": "2027-03-01",
                "target_shares": 1000,
                "performance_cycle_id": cycle["id"],
            }],
            award_type="PSU", target_shares=1000,
        )
        submit_grant(grant["id"], headers=ADMIN)
        approved = approve_grant_by_board(grant["id"], headers=BOARD)
        assert approved["weighted_reserve_shares"] == 0, (
            "an uncertified performance tranche commits nothing against the reserve"
        )

        certified = validate_success(
            api_client.certify_performance_cycle(
                cycle["id"], {"actual_value": 100}, BOARD
            )
        )

        assert certified["status"] == "CANCELLED", (
            "a ratio of 0.500000 is below the zero-payout floor, so the cycle is CANCELLED"
        )
        assert certified["payout_multiplier_bps"] == 0, (
            "a ratio below 0.800000 pays 0 basis points"
        )
        assert certified["actual_value"] == 100, "the achieved value is stored"
        assert_instant_equals(
            certified["certified_at"], "2026-01-05T09:00:00.000Z", "certified_at"
        )

        tranche_after = read_tranche(tranches[0]["id"])
        assert tranche_after["status"] == "FORFEITED", (
            "a bound UNVESTED tranche is forfeited by the cancelled branch"
        )
        assert tranche_after["shares"] == 0, "the forfeited tranche holds 0 shares"

        grant_after = read_grant(grant["id"])
        assert grant_after["weighted_reserve_shares"] == 0, (
            "no tranche qualifies, so the committed share count is 0"
        )
        assert grant_after["outstanding_shares"] == 0, (
            "a FORFEITED tranche is not outstanding"
        )

        plan_after = read_plan(plan["id"])
        assert plan_after["shares_committed_cumulative"] == 0, (
            "nothing was ever committed for the uncertified performance award"
        )
        assert plan_after["available_reserve_shares"] == 1000000, (
            "the reserve is untouched by the below-floor certification"
        )
        assert plan_after["gross_burn_rate_bps"] == 0, (
            "no share was granted against the fiscal year"
        )
        assert_reserve_conservation(plan_after)
