"""Approval gates, delegation ceilings and the compliance rejection ladder.

Every test builds its own world from scratch against the deterministic logical
clock, because the harness empties the database before each one.
"""

from test_helpers import (
    ADMIN,
    BOARD,
    COMPLIANCE,
    UNKNOWN_UUID,
    api_client,
    assert_allocations_sum_to_full_bps,
    assert_approval_authority,
    assert_equity_plan,
    assert_grant,
    assert_pagination_meta,
    assert_participant,
    assert_preclearance_request,
    assert_round_then_sum_total,
    assert_share_split_identity,
    assert_tax_allocation,
    assert_trading_window,
    assert_vesting_event,
    assert_vesting_tranche,
    get_success_data,
    make_admin_headers,
    make_board_headers,
    make_officer_headers,
    make_participant_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# ---------------------------------------------------------------------------
# Local composite setup helpers. They live here rather than in the shared
# helpers because each one encodes a preamble only this module needs.
# ---------------------------------------------------------------------------
PLAN_BASE = {
    "total_authorized_shares": 1_000_000,
    "common_shares_outstanding": 1_000_000,
    "fiscal_year_start_date": "2026-01-01",
}
TIME_TRANCHE = {
    "tranche_index": 1,
    "vest_type": "TIME",
    "scheduled_vest_date": "2027-01-05",
}


def _set_clock(instant):
    return get_success_data(api_client.set_clock(instant, ADMIN))


def _register_plan(name, **overrides):
    payload = dict(PLAN_BASE)
    payload["name"] = name
    payload.update(overrides)
    return get_success_data(api_client.create_equity_plan(payload, ADMIN))


def _read_plan(plan_id):
    return get_success_data(api_client.get_equity_plan(plan_id, ADMIN))


def _enrol_participant(employee_number, full_name="Gate Recipient", **overrides):
    payload = {
        "full_name": full_name,
        "employee_number": employee_number,
        "home_country_code": "US",
        "home_state_code": "CA",
        "hire_date": "2020-01-06",
        "birth_date": "1985-05-05",
    }
    payload.update(overrides)
    return get_success_data(api_client.create_participant(payload, ADMIN))


def _read_participant(participant_id, headers=ADMIN):
    return get_success_data(api_client.get_participant(participant_id, headers))


def _delegate_to_officer(plan_id, per_grant_share_cap, aggregate_share_cap,
                         effective_from="2026-01-01", effective_to="2026-12-31",
                         delegate_user_id="officer-1"):
    payload = {
        "plan_id": plan_id,
        "authority_type": "DELEGATED_OFFICER",
        "delegate_user_id": delegate_user_id,
        "per_grant_share_cap": per_grant_share_cap,
        "aggregate_share_cap": aggregate_share_cap,
        "effective_from": effective_from,
        "effective_to": effective_to,
    }
    return get_success_data(api_client.create_approval_authority(payload, BOARD))


def _read_authority(authority_id):
    return get_success_data(api_client.get_approval_authority(authority_id, BOARD))


def _open_window(plan_id, quarter_label="FY2026-Q1",
                 open_at="2026-01-05T00:00:00Z", close_at="2026-03-31T00:00:00Z",
                 **overrides):
    payload = {
        "plan_id": plan_id,
        "quarter_label": quarter_label,
        "open_at": open_at,
        "close_at": close_at,
    }
    payload.update(overrides)
    window = get_success_data(api_client.create_trading_window(payload, COMPLIANCE))
    return get_success_data(
        api_client.set_trading_window_status(
            window["id"], {"action": "OPEN"}, COMPLIANCE
        )
    )


def _read_window(window_id):
    return get_success_data(api_client.get_trading_window(window_id, COMPLIANCE))


def _draft_with_tranches(plan_id, participant_id, award_type, target_shares,
                         tranches, exercise_price_cents=None, headers=ADMIN):
    """Draft a grant and append every tranche while it is still DRAFT."""
    payload = {
        "plan_id": plan_id,
        "participant_id": participant_id,
        "award_type": award_type,
        "target_shares": target_shares,
    }
    if exercise_price_cents is not None:
        payload["exercise_price_cents"] = exercise_price_cents
    grant = get_success_data(api_client.create_grant(payload, headers))
    rows = [
        get_success_data(api_client.create_vesting_tranche(grant["id"], spec, headers))
        for spec in tranches
    ]
    return grant, rows


def _single_time_tranche(target_shares, **overrides):
    spec = dict(TIME_TRANCHE)
    spec["target_shares"] = target_shares
    spec.update(overrides)
    return [spec]


def _submit(grant_id, headers=ADMIN):
    return get_success_data(api_client.submit_grant(grant_id, headers))


def _approve_by_board(grant_id):
    return get_success_data(
        api_client.approve_grant(grant_id, {"approval_path": "BOARD"}, BOARD)
    )


def _issue(grant_id):
    return get_success_data(api_client.issue_grant(grant_id, ADMIN))


def _read_grant(grant_id):
    return get_success_data(api_client.get_grant(grant_id, ADMIN))


def _read_tranche(tranche_id):
    return get_success_data(api_client.get_vesting_tranche(tranche_id, ADMIN))


def _pending_approval_grant(plan_id, participant_id, award_type, target_shares,
                            exercise_price_cents=None, scheduled_vest_date="2027-01-05"):
    """Take one grant as far as PENDING_APPROVAL, which is where the approval
    ladder of the PRD is exercised."""
    grant, rows = _draft_with_tranches(
        plan_id, participant_id, award_type, target_shares,
        _single_time_tranche(target_shares, scheduled_vest_date=scheduled_vest_date),
        exercise_price_cents=exercise_price_cents,
    )
    _submit(grant["id"])
    return grant, rows


# ---------------------------------------------------------------------------
# The plan-frozen gate is scoped, not a blanket lock
# ---------------------------------------------------------------------------
def test_frozen_plan_refuses_a_grant_submit_but_still_lets_a_tranche_vest():
    """PRD §2.4: "A plan that is `FROZEN` or `TERMINATED` accepts no new commitment, no new calendar entry, and no grant-lifecycle write at all: drafting a grant, appending a tranche, submitting, approving, issuing, cancelling, opening a performance cycle, certifying one, scheduling a trading window, adjusting the share reserve, and running the annual rollover are all refused with `ERR_PLAN_FROZEN` (HTTP 409). That list is exhaustive and includes the compensating actions — a frozen plan cannot even have a grant cancelled, because cancellation moves the reserve ledger."

    PRD §3.6: "Vesting sets the tranche to `VESTED`, stamps `vested_at` from the logical clock, leaves `acceleration_reason` null (a tranche that vests on schedule was not accelerated), and creates exactly one settlement record."

    Design: Corner/validations/plan_frozen_blocks_grant_submit_but_allows_vesting
    """
    _set_clock("2026-01-05T09:00:00Z")
    plan = _register_plan("Corner Plan Bravo Two")
    _open_window(plan["id"])
    participant = _enrol_participant("E-C-230", full_name="Fred Frost",
                                    birth_date="1986-05-05")
    get_success_data(
        api_client.create_mobility_assignment(
            {
                "participant_id": participant["id"],
                "jurisdiction_code": "US-CA",
                "tax_rate_bps": 1000,
                "start_date": "2025-01-01",
                "workdays": 250,
            },
            ADMIN,
        )
    )
    grant_a, tranches_a = _draft_with_tranches(
        plan["id"], participant["id"], "RSU", 1000,
        _single_time_tranche(1000, scheduled_vest_date="2026-01-05"),
    )
    _submit(grant_a["id"])
    _approve_by_board(grant_a["id"])
    _issue(grant_a["id"])
    grant_b, _tranches_b = _draft_with_tranches(
        plan["id"], participant["id"], "RSU", 500, _single_time_tranche(500)
    )
    frozen = validate_success(
        api_client.set_equity_plan_status(
            plan["id"],
            {"action": "FREEZE", "freeze_reason": "restatement under review"},
            ADMIN,
        )
    )
    assert frozen["status"] == "FROZEN", (
        f"the plan must be FROZEN before the gate can fire, got {frozen['status']}"
    )

    blocked = api_client.submit_grant(grant_b["id"], ADMIN)
    validate_error(blocked, "ERR_PLAN_FROZEN")

    still_draft = _read_grant(grant_b["id"])
    assert_grant(still_draft)
    assert still_draft["status"] == "DRAFT", (
        f"the refused submit leaves the grant in DRAFT, got {still_draft['status']}"
    )

    event = validate_success(
        api_client.vest_tranche(
            tranches_a[0]["id"], {"fmv_per_share_cents": 4000}, ADMIN
        ),
        expected_status=201,
    )
    assert_vesting_event(event)
    assert event["gross_shares"] == 1000, (
        f"gross_shares snapshots the tranche's shares, got {event['gross_shares']}"
    )
    assert event["taxable_income_cents"] == 4000000, (
        f"taxable_income_cents expected 4000000, got {event['taxable_income_cents']}"
    )

    vested = _read_tranche(tranches_a[0]["id"])
    assert_vesting_tranche(vested)
    assert vested["status"] == "VESTED", (
        "vesting is not on the exhaustive frozen-plan list, so it still runs, got "
        f"{vested['status']}"
    )
    assert _read_plan(plan["id"])["status"] == "FROZEN", (
        "the plan is still FROZEN after the successful vesting"
    )


# ---------------------------------------------------------------------------
# The acceleration price guard
# ---------------------------------------------------------------------------
def test_termination_that_would_accelerate_needs_a_price_while_a_forfeiting_one_does_not():
    """PRD §3.8: "Before any hop runs, one guard is evaluated: if the resolution below would accelerate at least one `UNVESTED` tranche and `acceleration_fmv_per_share_cents` was omitted, the entire request is refused with `ERR_ACCELERATION_FMV_REQUIRED` (HTTP 409) and nothing whatsoever is written. Rather than invent a valuation, the system declines. A termination in which every tranche forfeits does not need the field, so omitting it is fine there and supplying it anyway is harmless."

    Design: Corner/validations/acceleration_fmv_required_when_a_tranche_will_accelerate
    """
    _set_clock("2026-01-05T09:00:00Z")
    plan = _register_plan("Corner Plan Charlie Two")
    _open_window(plan["id"])
    dying = _enrol_participant("E-C-240", full_name="Dana Death",
                               birth_date="1987-07-07")
    leaving = _enrol_participant("E-C-241", full_name="Vic Voluntary",
                                 birth_date="1988-08-08")
    grants = {}
    tranches = {}
    for key, participant in (("death", dying), ("voluntary", leaving)):
        grant, rows = _draft_with_tranches(
            plan["id"], participant["id"], "RSU", 800, _single_time_tranche(800)
        )
        _submit(grant["id"])
        _approve_by_board(grant["id"])
        _issue(grant["id"])
        grants[key] = grant
        tranches[key] = rows[0]

    refused = api_client.terminate_participant(
        dying["id"],
        {"termination_date": "2026-02-10", "termination_reason": "DEATH"},
        ADMIN,
    )
    validate_error(refused, "ERR_ACCELERATION_FMV_REQUIRED")

    untouched = _read_participant(dying["id"])
    assert_participant(untouched)
    assert untouched["employment_status"] == "ACTIVE", (
        "nothing whatsoever is written by the refused termination, got "
        f"{untouched['employment_status']}"
    )
    assert _read_tranche(tranches["death"]["id"])["status"] == "UNVESTED", (
        "the tranche that would have accelerated is untouched"
    )

    accepted = validate_success(
        api_client.terminate_participant(
            leaving["id"],
            {"termination_date": "2026-02-10", "termination_reason": "VOLUNTARY"},
            ADMIN,
        )
    )
    assert accepted["employment_status"] == "TERMINATED", (
        "a termination where every tranche forfeits needs no price, got "
        f"{accepted['employment_status']}"
    )
    assert _read_tranche(tranches["voluntary"]["id"])["status"] == "FORFEITED", (
        "the unvested tranche of a voluntary leaver forfeits"
    )
    assert _read_grant(grants["voluntary"]["id"])["status"] == "FORFEITED", (
        "a grant whose only tranche forfeited is FORFEITED"
    )


# ---------------------------------------------------------------------------
# The delegated approval ladder
# ---------------------------------------------------------------------------
def test_delegated_approval_is_refused_while_the_clock_sits_before_effective_from():
    """PRD §3.5: "The cited delegation must be `ACTIVE`, must belong to the grant's own plan, must name the acting `X-User-ID` as its `delegate_user_id`, and the logical clock date at approval must fall inside `effective_from` through `effective_to` with both endpoints inclusive. A `REVOKED`, `EXHAUSTED`, or `EXPIRED` delegation, one belonging to another plan, one delegated to a different officer, or an approval dated outside the term all yield `ERR_AUTHORITY_NOT_EFFECTIVE`."

    PRD §3.2: "A new delegation is `ACTIVE` with `consumed_shares` at 0 and `remaining_shares` equal to the full `aggregate_share_cap`; `revoked_at` is null."

    Design: Corner/validations/delegated_authority_not_yet_effective_is_rejected
    """
    _set_clock("2026-01-05T09:00:00Z")
    plan = _register_plan("Corner Plan Delta Two")
    authority = _delegate_to_officer(
        plan["id"], 100000, 100000,
        effective_from="2026-06-01", effective_to="2026-12-31",
    )
    assert_approval_authority(authority)
    participant = _enrol_participant("E-C-250", full_name="Nora Notyet",
                                     birth_date="1989-09-09")
    grant, _rows = _pending_approval_grant(
        plan["id"], participant["id"], "RSU", 500
    )

    refused = api_client.approve_grant(
        grant["id"],
        {"approval_path": "DELEGATED", "authority_id": authority["id"]},
        make_officer_headers("officer-1"),
    )
    validate_error(refused, "ERR_AUTHORITY_NOT_EFFECTIVE")

    unapproved = _read_grant(grant["id"])
    assert unapproved["status"] == "PENDING_APPROVAL", (
        f"the grant is left pending, got {unapproved['status']}"
    )
    assert unapproved["approved_under_authority_id"] is None, (
        "no delegation is recorded on a refused approval, got "
        f"{unapproved['approved_under_authority_id']}"
    )

    untouched = _read_authority(authority["id"])
    assert untouched["status"] == "ACTIVE", (
        "an unusable delegation is still ACTIVE - status alone never made it "
        f"usable, got {untouched['status']}"
    )
    assert untouched["consumed_shares"] == 0, (
        f"consumed_shares expected 0, got {untouched['consumed_shares']}"
    )
    assert untouched["remaining_shares"] == 100000, (
        f"remaining_shares expected 100000, got {untouched['remaining_shares']}"
    )

    plan_row = _read_plan(plan["id"])
    assert plan_row["shares_committed_cumulative"] == 0, (
        f"no reserve was committed, got {plan_row['shares_committed_cumulative']}"
    )


def test_per_grant_cap_is_measured_against_weighted_shares_not_target_shares():
    """PRD §3.5: "**Per-grant ceiling.** The grant's `weighted_reserve_shares` may not exceed the delegation's `per_grant_share_cap`; exceeding it yields `ERR_AUTHORITY_PER_GRANT_CAP_EXCEEDED`."

    PRD §3.4: "Second, that committed count is weighted by instrument family: for the full-value types `RSU` and `PSU`, the count is multiplied by the plan's `fungible_ratio_full_value_bps` and divided by 10000, then rounded half up to whole shares; for the option types `ISO` and `NSO`, the count is charged one share for one share with no weighting at all."

    Design: Corner/validations/delegated_per_grant_cap_measured_on_weighted_shares_rejected
    """
    _set_clock("2026-01-05T09:00:00Z")
    plan = _register_plan("Corner Plan Echo Two", fungible_ratio_full_value_bps=15000)
    authority = _delegate_to_officer(plan["id"], 1000, 100000)
    participant = _enrol_participant("E-C-260", full_name="Walt Weight",
                                     birth_date="1990-10-10")
    grant, _rows = _pending_approval_grant(
        plan["id"], participant["id"], "RSU", 1000
    )

    refused = api_client.approve_grant(
        grant["id"],
        {"approval_path": "DELEGATED", "authority_id": authority["id"]},
        make_officer_headers("officer-1"),
    )
    validate_error(refused, "ERR_AUTHORITY_PER_GRANT_CAP_EXCEEDED")

    unapproved = _read_grant(grant["id"])
    assert unapproved["status"] == "PENDING_APPROVAL", (
        "1000 target shares weigh 1500 against a 1000-share cap, so the grant "
        f"stays pending, got {unapproved['status']}"
    )

    untouched = _read_authority(authority["id"])
    assert untouched["consumed_shares"] == 0, (
        f"consumed_shares expected 0, got {untouched['consumed_shares']}"
    )
    assert untouched["remaining_shares"] == 100000, (
        f"remaining_shares expected 100000, got {untouched['remaining_shares']}"
    )

    plan_row = _read_plan(plan["id"])
    assert_equity_plan(plan_row)
    assert plan_row["shares_committed_cumulative"] == 0, (
        f"no reserve was committed, got {plan_row['shares_committed_cumulative']}"
    )
    assert plan_row["available_reserve_shares"] == 1000000, (
        f"available_reserve_shares expected 1000000, got {plan_row['available_reserve_shares']}"
    )


def test_aggregate_cap_fires_on_the_second_grant_even_though_each_fits_the_per_grant_cap():
    """PRD §3.5: "**Aggregate ceiling.** The delegation's `consumed_shares` plus this grant's `weighted_reserve_shares` may not exceed its `aggregate_share_cap`. Landing exactly on the cap is allowed and drives the delegation to `EXHAUSTED` as a side effect; exceeding it by a single share is refused with `ERR_AUTHORITY_CAP_EXCEEDED` and leaves the delegation `ACTIVE`."

    PRD §3.2: "`consumed_shares` accumulates the fungible-weighted shares that grants approved under this authority have charged to it, and `remaining_shares` is always the `aggregate_share_cap` minus `consumed_shares`."

    Design: Corner/validations/authority_aggregate_cap_exceeded_across_two_grants
    """
    _set_clock("2026-01-05T09:00:00Z")
    plan = _register_plan("Corner Plan Foxtrot Two")
    authority = _delegate_to_officer(plan["id"], 5000, 5000)
    participant = _enrol_participant("E-C-270", full_name="Aggie Gate",
                                     birth_date="1991-11-11")
    first, _rows_one = _pending_approval_grant(
        plan["id"], participant["id"], "NSO", 3000, exercise_price_cents=2500
    )
    approved = validate_success(
        api_client.approve_grant(
            first["id"],
            {"approval_path": "DELEGATED", "authority_id": authority["id"]},
            make_officer_headers("officer-1"),
        )
    )
    assert approved["status"] == "APPROVED", (
        f"the first grant fits both caps, got {approved['status']}"
    )
    assert approved["approved_under_authority_id"] == authority["id"], (
        "the delegation used is recorded on the grant, got "
        f"{approved['approved_under_authority_id']}"
    )
    consumed = _read_authority(authority["id"])
    assert consumed["consumed_shares"] == 3000, (
        f"consumed_shares expected 3000, got {consumed['consumed_shares']}"
    )
    assert consumed["remaining_shares"] == 2000, (
        f"remaining_shares expected 2000, got {consumed['remaining_shares']}"
    )
    assert consumed["status"] == "ACTIVE", (
        f"2000 shares of capacity remain, so the delegation is ACTIVE, got {consumed['status']}"
    )

    second, _rows_two = _pending_approval_grant(
        plan["id"], participant["id"], "NSO", 2500, exercise_price_cents=2500
    )
    refused = api_client.approve_grant(
        second["id"],
        {"approval_path": "DELEGATED", "authority_id": authority["id"]},
        make_officer_headers("officer-1"),
    )
    validate_error(refused, "ERR_AUTHORITY_CAP_EXCEEDED")

    assert 2500 <= consumed["per_grant_share_cap"], (
        "the second grant is individually inside the per-grant cap, so it is the "
        "aggregate ceiling that fired"
    )
    still = _read_authority(authority["id"])
    assert still["consumed_shares"] == 3000, (
        f"the refusal consumes nothing, got {still['consumed_shares']}"
    )
    assert still["remaining_shares"] == 2000, (
        f"remaining_shares stays at 2000, got {still['remaining_shares']}"
    )
    assert still["status"] == "ACTIVE", (
        f"exceeding the cap leaves the delegation ACTIVE, got {still['status']}"
    )
    assert _read_grant(second["id"])["status"] == "PENDING_APPROVAL", (
        "the refused grant is left pending"
    )
    plan_row = _read_plan(plan["id"])
    assert plan_row["shares_committed_cumulative"] == 3000, (
        "only the first approval committed reserve, got "
        f"{plan_row['shares_committed_cumulative']}"
    )


# ---------------------------------------------------------------------------
# The trading window's collective share ceiling
# ---------------------------------------------------------------------------
def test_window_share_cap_is_an_aggregate_check_across_sibling_requests():
    """PRD §3.9: "And when the window carries a non-null `aggregate_share_cap`, its `approved_shares_cumulative` plus the `requested_shares` may not exceed that cap, otherwise `ERR_WINDOW_SHARE_CAP_EXCEEDED`. That last rule is an aggregate check across sibling requests: each individual request may be modest while the collective busts the ceiling. Only requests in `APPROVED` and `EXECUTED` status count toward `approved_shares_cumulative`; a `DENIED`, `EXPIRED`, or `VOID` request releases its reservation."

    Design: Corner/validations/window_aggregate_share_cap_counts_only_approved_requests
    """
    _set_clock("2026-01-05T09:00:00Z")
    plan = _register_plan("Corner Plan Golf Two")
    window = _open_window(plan["id"], aggregate_share_cap=1000)
    assert_trading_window(window)
    first_insider = _enrol_participant(
        "E-C-280", full_name="Cap One", home_state_code="NY",
        hire_date="2019-01-07", birth_date="1982-02-02",
        insider_status="DESIGNATED_INSIDER",
    )
    second_insider = _enrol_participant(
        "E-C-281", full_name="Cap Two", home_state_code="NY",
        hire_date="2019-01-07", birth_date="1983-03-03",
        insider_status="DESIGNATED_INSIDER",
    )
    first_request = get_success_data(
        api_client.create_preclearance_request(
            {
                "participant_id": first_insider["id"],
                "window_id": window["id"],
                "transaction_type": "SELL",
                "requested_shares": 600,
                "intended_trade_date": "2026-01-09",
            },
            make_participant_headers(first_insider["id"]),
        )
    )
    approved = validate_success(
        api_client.decide_preclearance_request(
            first_request["id"], {"decision": "APPROVE"}, COMPLIANCE
        )
    )
    assert_preclearance_request(approved)
    reserved = _read_window(window["id"])
    assert reserved["approved_shares_cumulative"] == 600, (
        "the approved request reserves 600 of the 1000-share cap, got "
        f"{reserved['approved_shares_cumulative']}"
    )

    refused = api_client.create_preclearance_request(
        {
            "participant_id": second_insider["id"],
            "window_id": window["id"],
            "transaction_type": "SELL",
            "requested_shares": 600,
            "intended_trade_date": "2026-01-09",
        },
        make_participant_headers(second_insider["id"]),
    )
    validate_error(refused, "ERR_WINDOW_SHARE_CAP_EXCEEDED")

    rows, meta = validate_paginated(
        api_client.list_preclearance_requests(
            COMPLIANCE, params={"participant_id": second_insider["id"]}
        )
    )
    assert rows == [], (
        f"the refused creation writes no request row, got {len(rows)} rows"
    )
    assert_pagination_meta(meta, total_count=0)

    unchanged = _read_window(window["id"])
    assert unchanged["approved_shares_cumulative"] == 600, (
        "a refused creation reserves nothing further, got "
        f"{unchanged['approved_shares_cumulative']}"
    )


# ---------------------------------------------------------------------------
# The reserve gate is evaluated on weighted shares
# ---------------------------------------------------------------------------
def test_reserve_gate_refuses_an_approval_whose_weighted_cost_exceeds_the_pool():
    """PRD §3.5: "Second the reserve gate: `available_reserve_shares` must be at least the grant's `weighted_reserve_shares`, and a shortfall is refused with `ERR_RESERVE_INSUFFICIENT`. Consuming the reserve down to exactly zero is permitted."

    PRD §3.5: "Both paths move the grant from `PENDING_APPROVAL` to `APPROVED`, record `approved_by_user_id` from the acting `X-User-ID`, stamp `approved_at` from the logical clock, store the chosen `approval_path`, write `weighted_reserve_shares` from the calculation above, add that figure to the plan's `shares_committed_cumulative` and to its `fiscal_year_gross_granted_shares`, and then rerun the reserve ledger and both burn-rate variants."

    Design: Corner/validations/reserve_insufficient_blocks_grant_approval
    """
    _set_clock("2026-01-05T09:00:00Z")
    plan = _register_plan(
        "Corner Plan Hotel Two",
        total_authorized_shares=1000,
        fungible_ratio_full_value_bps=15000,
    )
    participant = _enrol_participant("E-C-290", full_name="Rita Reserve",
                                     birth_date="1984-04-04")
    grant, _rows = _pending_approval_grant(
        plan["id"], participant["id"], "RSU", 1000
    )

    refused = api_client.approve_grant(
        grant["id"], {"approval_path": "BOARD"}, BOARD
    )
    validate_error(refused, "ERR_RESERVE_INSUFFICIENT")

    unapproved = _read_grant(grant["id"])
    assert_grant(unapproved)
    assert unapproved["status"] == "PENDING_APPROVAL", (
        f"the refused grant is left pending, got {unapproved['status']}"
    )
    assert unapproved["weighted_reserve_shares"] == 0, (
        "the weighted figure is only written by a successful approval, got "
        f"{unapproved['weighted_reserve_shares']}"
    )

    plan_row = _read_plan(plan["id"])
    assert_equity_plan(plan_row)
    assert plan_row["available_reserve_shares"] == 1000, (
        f"available_reserve_shares expected 1000, got {plan_row['available_reserve_shares']}"
    )
    assert plan_row["shares_committed_cumulative"] == 0, (
        f"shares_committed_cumulative expected 0, got {plan_row['shares_committed_cumulative']}"
    )
    assert plan_row["version"] == 1, (
        f"a refused approval never touches the plan row, got {plan_row['version']}"
    )
    assert plan_row["fiscal_year_gross_granted_shares"] == 0, (
        f"fiscal_year_gross_granted_shares expected 0, got {plan_row['fiscal_year_gross_granted_shares']}"
    )
    assert plan_row["gross_burn_rate_bps"] == 0, (
        f"gross_burn_rate_bps expected 0, got {plan_row['gross_burn_rate_bps']}"
    )


# ---------------------------------------------------------------------------
# Settlement waits for the tax allocation
# ---------------------------------------------------------------------------
def test_settlement_is_refused_until_taxes_are_allocated_then_the_same_call_passes():
    """PRD §3.7: "Settling while `tax_status` is still `PENDING_ALLOCATION` is refused with `ERR_TAX_ALLOCATION_MISSING`; settling something already `SETTLED` or `REVERSED` is refused with `ERR_VESTING_EVENT_INVALID_STATE`."

    PRD §3.7: "Under `SHARE_WITHHOLD`, `shares_withheld` is the total tax divided by the fair market value per share, rounded up to the next whole share; `shares_sold` is 0; `net_shares_delivered` is `gross_shares` minus `shares_withheld`; `residual_cash_cents` is `shares_withheld` multiplied by the fair market value per share, minus the total tax — the over-withholding refunded to the participant; and `cash_due_cents` is 0."

    PRD §3.7: "The contributing rows are then grouped by `jurisdiction_code`. Inside each group, the sourced workday figure is the sum of `workdays` across the group's rows, and the group's rate is the largest `tax_rate_bps` among them, which keeps the result deterministic when a jurisdiction appears more than once. The settlement's `total_workdays` is the sum of the group figures."

    Design: Corner/validations/tax_allocation_missing_blocks_settlement_then_passes
    """
    _set_clock("2026-01-05T09:00:00Z")
    plan = _register_plan("Corner Plan India Two")
    _open_window(plan["id"])
    participant = _enrol_participant("E-C-300", full_name="Tara Tax",
                                     birth_date="1985-05-05")
    get_success_data(
        api_client.create_mobility_assignment(
            {
                "participant_id": participant["id"],
                "jurisdiction_code": "US-CA",
                "tax_rate_bps": 1000,
                "start_date": "2026-01-05",
                "end_date": "2026-06-30",
                "workdays": 250,
            },
            ADMIN,
        )
    )
    grant, tranches = _draft_with_tranches(
        plan["id"], participant["id"], "RSU", 1000,
        _single_time_tranche(1000, scheduled_vest_date="2026-06-30"),
    )
    _submit(grant["id"])
    _approve_by_board(grant["id"])
    _issue(grant["id"])
    _set_clock("2026-06-30T09:00:00Z")
    event = validate_success(
        api_client.vest_tranche(
            tranches[0]["id"],
            {"fmv_per_share_cents": 4000, "withholding_method": "SHARE_WITHHOLD"},
            ADMIN,
        ),
        expected_status=201,
    )
    assert event["tax_status"] == "PENDING_ALLOCATION", (
        f"a fresh settlement awaits its allocation, got {event['tax_status']}"
    )

    too_early = api_client.settle_vesting_event(event["id"], ADMIN)
    validate_error(too_early, "ERR_TAX_ALLOCATION_MISSING")

    blocked = get_success_data(api_client.get_vesting_event(event["id"], ADMIN))
    assert blocked["settlement_status"] == "PENDING_TAX", (
        f"the refused settle changes nothing, got {blocked['settlement_status']}"
    )
    assert _read_tranche(tranches[0]["id"])["status"] == "VESTED", (
        "the owning tranche is still VESTED after the refusal"
    )

    allocated = validate_success(api_client.allocate_taxes(event["id"], ADMIN))
    assert_vesting_event(allocated)
    assert allocated["tax_status"] == "ALLOCATED", (
        f"tax_status expected ALLOCATED, got {allocated['tax_status']}"
    )
    assert allocated["total_workdays"] == 250, (
        f"total_workdays expected 250, got {allocated['total_workdays']}"
    )
    assert allocated["total_tax_cents"] == 400000, (
        "1000 bps of 4000000 cents of income is 400000 cents, got "
        f"{allocated['total_tax_cents']}"
    )

    rows, _meta = validate_paginated(
        api_client.list_event_tax_allocations(event["id"], ADMIN)
    )
    assert len(rows) == 1, (
        f"exactly one jurisdiction contributed, got {len(rows)}"
    )
    assert_tax_allocation(rows[0])
    assert rows[0]["jurisdiction_code"] == "US-CA", (
        f"jurisdiction_code expected US-CA, got {rows[0]['jurisdiction_code']}"
    )
    assert rows[0]["allocation_bps"] == 10000, (
        f"a single jurisdiction takes the whole 10000 bps, got {rows[0]['allocation_bps']}"
    )
    assert rows[0]["tax_amount_cents"] == 400000, (
        f"tax_amount_cents expected 400000, got {rows[0]['tax_amount_cents']}"
    )
    assert_allocations_sum_to_full_bps(rows)
    assert_round_then_sum_total(allocated, rows)

    settled = validate_success(api_client.settle_vesting_event(event["id"], ADMIN))
    assert settled["settlement_status"] == "SETTLED", (
        "the identical settle call now succeeds, got "
        f"{settled['settlement_status']}"
    )
    assert settled["shares_withheld"] == 100, (
        "400000 cents of tax at 4000 cents per share withholds 100 shares, got "
        f"{settled['shares_withheld']}"
    )
    assert settled["net_shares_delivered"] == 900, (
        f"net_shares_delivered expected 900, got {settled['net_shares_delivered']}"
    )
    assert_share_split_identity(settled)
    assert _read_tranche(tranches[0]["id"])["status"] == "SETTLED", (
        "the owning tranche follows the settlement to SETTLED"
    )


# ---------------------------------------------------------------------------
# Four eyes on a grant approval
# ---------------------------------------------------------------------------
def test_the_submitter_cannot_approve_their_own_grant_even_wearing_a_permitted_role():
    """PRD §3.5: "Both paths require the plan to be `ACTIVE`, the recipient's employment to be `ACTIVE` — otherwise `ERR_PARTICIPANT_NOT_ACTIVE` — and the acting `X-User-ID` to differ from `submitted_by_user_id`. That last control is the four-eyes rule: whoever submitted a grant may not approve it, and the refusal is `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). Role membership alone never satisfies it."

    Design: Corner/validations/segregation_of_duties_same_user_cannot_submit_and_approve
    """
    _set_clock("2026-01-05T09:00:00Z")
    plan = _register_plan("Corner Plan Juliet Two")
    participant = _enrol_participant("E-C-310", full_name="Sol Duty",
                                     birth_date="1986-06-06")
    dual_admin = make_admin_headers("dual-1")
    grant, _rows = _draft_with_tranches(
        plan["id"], participant["id"], "RSU", 400, _single_time_tranche(400),
        headers=dual_admin,
    )
    _submit(grant["id"], headers=dual_admin)

    refused = api_client.approve_grant(
        grant["id"], {"approval_path": "BOARD"}, make_board_headers("dual-1")
    )
    validate_error(refused, "ERR_SEGREGATION_OF_DUTIES")

    unapproved = _read_grant(grant["id"])
    assert unapproved["status"] == "PENDING_APPROVAL", (
        f"the refused approval leaves the grant pending, got {unapproved['status']}"
    )
    assert unapproved["approved_by_user_id"] is None, (
        f"approved_by_user_id is still null, got {unapproved['approved_by_user_id']}"
    )
    assert _read_plan(plan["id"])["shares_committed_cumulative"] == 0, (
        "nothing is committed until a second pair of eyes approves"
    )

    approved = validate_success(
        api_client.approve_grant(grant["id"], {"approval_path": "BOARD"}, BOARD)
    )
    assert approved["status"] == "APPROVED", (
        f"a different identity may approve, got {approved['status']}"
    )
    assert approved["approved_by_user_id"] == "board-1", (
        f"approved_by_user_id expected board-1, got {approved['approved_by_user_id']}"
    )
    assert _read_plan(plan["id"])["shares_committed_cumulative"] == 400, (
        "the reserve is committed only by the successful approval"
    )


# ---------------------------------------------------------------------------
# Path eligibility sits above the delegation caps
# ---------------------------------------------------------------------------
def test_a_psu_award_cannot_take_the_delegated_path_however_much_capacity_remains():
    """PRD §3.5: "**Path eligibility.** A `DELEGATED` approval is impossible for a `PSU` award, and impossible for any award to a participant whose `insider_status` is `SECTION_16_OFFICER`; both require the full board. The refusal is `ERR_DELEGATED_APPROVAL_BLOCKED`, and it is evaluated before any delegation cap so the caller learns the path itself is unavailable rather than merely exhausted."

    PRD §3.4: "A `PERFORMANCE` tranche must supply `performance_cycle_id`, and its `shares` sit at 0 until the cycle is certified — which is why an uncertified performance tranche commits nothing against the reserve."

    Design: Corner/validations/delegated_approval_blocked_for_psu_award
    """
    _set_clock("2026-01-05T09:00:00Z")
    plan = _register_plan("Corner Plan Kilo Two")
    authority = _delegate_to_officer(plan["id"], 100000, 100000)
    participant = _enrol_participant("E-C-320", full_name="Perry Psu",
                                     birth_date="1987-07-07")
    cycle = get_success_data(
        api_client.create_performance_cycle(
            {
                "plan_id": plan["id"],
                "metric_code": "TSR-2026",
                "target_value": 100,
                "certification_due_date": "2027-02-28",
            },
            ADMIN,
        )
    )
    grant, _rows = _draft_with_tranches(
        plan["id"], participant["id"], "PSU", 900,
        [{
            "tranche_index": 1,
            "vest_type": "PERFORMANCE",
            "scheduled_vest_date": "2027-03-01",
            "target_shares": 900,
            "performance_cycle_id": cycle["id"],
        }],
    )
    _submit(grant["id"])

    refused = api_client.approve_grant(
        grant["id"],
        {"approval_path": "DELEGATED", "authority_id": authority["id"]},
        make_officer_headers("officer-1"),
    )
    validate_error(refused, "ERR_DELEGATED_APPROVAL_BLOCKED")

    untouched = _read_authority(authority["id"])
    assert untouched["consumed_shares"] == 0, (
        "the path check runs before any cap is consulted, got "
        f"{untouched['consumed_shares']}"
    )
    assert untouched["remaining_shares"] == 100000, (
        f"remaining_shares expected 100000, got {untouched['remaining_shares']}"
    )

    approved = validate_success(
        api_client.approve_grant(grant["id"], {"approval_path": "BOARD"}, BOARD)
    )
    assert_grant(approved)
    assert approved["status"] == "APPROVED", (
        "the very same grant is approvable by the board, so the block attaches to "
        f"the path, got {approved['status']}"
    )
    assert approved["approved_under_authority_id"] is None, (
        "a board approval cites no delegation, got "
        f"{approved['approved_under_authority_id']}"
    )
    assert approved["approved_by_user_id"] == "board-1", (
        f"approved_by_user_id expected board-1, got {approved['approved_by_user_id']}"
    )
    assert approved["weighted_reserve_shares"] == 0, (
        "the uncertified performance tranche carries 0 shares, so nothing is "
        f"charged, got {approved['weighted_reserve_shares']}"
    )
    plan_row = _read_plan(plan["id"])
    assert plan_row["shares_committed_cumulative"] == 0, (
        "an uncertified performance tranche commits nothing against the reserve, "
        f"got {plan_row['shares_committed_cumulative']}"
    )


# ---------------------------------------------------------------------------
# A terminated recipient receives nothing new
# ---------------------------------------------------------------------------
def test_a_terminated_participant_can_no_longer_be_granted_a_new_award():
    """PRD §3.3: "That same active-employment gate guards four other creations: a terminated participant receives no new grant, no new mobility period, no new preclearance request, and no new trading plan. In each of those cases the code is `ERR_PARTICIPANT_NOT_ACTIVE` (HTTP 409). Their existing tranches, settlements, and Section 16 reports remain fully processable, so a post-termination exercise period can run to completion."

    PRD §3.8: "It also writes `ptep_expiry_date`, the date on which the post-termination exercise period ends: the `termination_date` advanced by 0 days for `FOR_CAUSE`, 90 days for `VOLUNTARY`, 180 days for `INVOLUNTARY`, 1095 days for `RETIREMENT`, and 365 days for `DEATH`."

    Design: Corner/validations/participant_not_active_blocks_new_grant
    """
    _set_clock("2026-01-05T09:00:00Z")
    plan = _register_plan("Corner Plan Lima Two")
    participant = _enrol_participant("E-C-330", full_name="Gone Guy",
                                     birth_date="1988-08-08")
    terminated = validate_success(
        api_client.terminate_participant(
            participant["id"],
            {"termination_date": "2026-02-10", "termination_reason": "VOLUNTARY"},
            ADMIN,
        )
    )
    assert terminated["employment_status"] == "TERMINATED", (
        f"employment_status expected TERMINATED, got {terminated['employment_status']}"
    )

    refused = api_client.create_grant(
        {
            "plan_id": plan["id"],
            "participant_id": participant["id"],
            "award_type": "RSU",
            "target_shares": 100,
        },
        ADMIN,
    )
    validate_error(refused, "ERR_PARTICIPANT_NOT_ACTIVE")

    grants, meta = validate_paginated(
        api_client.list_grants(ADMIN, params={"participant_id": participant["id"]})
    )
    assert grants == [], (
        f"the refused creation writes no grant row, got {len(grants)} rows"
    )
    assert_pagination_meta(meta, total_count=0)

    persisted = _read_participant(participant["id"])
    assert_participant(persisted)
    assert persisted["termination_reason"] == "VOLUNTARY", (
        f"termination_reason expected VOLUNTARY, got {persisted['termination_reason']}"
    )
    assert persisted["ptep_expiry_date"] == "2026-05-11", (
        "a VOLUNTARY termination advances the exercise period by 90 days, got "
        f"{persisted['ptep_expiry_date']}"
    )

    plan_row = _read_plan(plan["id"])
    assert plan_row["available_reserve_shares"] == 1000000, (
        f"available_reserve_shares expected 1000000, got {plan_row['available_reserve_shares']}"
    )
    assert plan_row["shares_committed_cumulative"] == 0, (
        f"shares_committed_cumulative expected 0, got {plan_row['shares_committed_cumulative']}"
    )


# ---------------------------------------------------------------------------
# Pagination bounds
# ---------------------------------------------------------------------------
def test_pagination_limit_bounds_reject_zero_and_one_hundred_and_one_but_accept_one():
    """PRD §2.2: "Every list endpoint accepts two optional query parameters, `limit` and `offset`. `limit` defaults to 10, may be no smaller than 1, and may be no larger than 100. `offset` defaults to 0 and may be no smaller than 0; it has no upper bound. A `limit` of 0, a `limit` of 101, or a negative `offset` is rejected with `ERR_INVALID_PAGINATION` (HTTP 400), while a `limit` of 1, a `limit` of 100, and an `offset` of 0 are all accepted."

    Design: Corner/validations/invalid_pagination_limit_zero_rejected
    """
    _set_clock("2026-01-05T09:00:00Z")
    _enrol_participant("E-C-340", full_name="Page One", birth_date="1989-09-09")
    _enrol_participant("E-C-341", full_name="Page Two", birth_date="1990-10-10")

    validate_error(
        api_client.list_participants(ADMIN, params={"limit": 0}),
        "ERR_INVALID_PAGINATION",
    )
    validate_error(
        api_client.list_participants(ADMIN, params={"limit": 101}),
        "ERR_INVALID_PAGINATION",
    )

    rows, meta = validate_paginated(
        api_client.list_participants(ADMIN, params={"limit": 1, "offset": 0})
    )
    assert len(rows) == 1, (
        f"a limit of 1 is accepted and returns one row, got {len(rows)}"
    )
    assert_pagination_meta(meta, limit=1, offset=0, total_count=2, has_more=True)


# ---------------------------------------------------------------------------
# The strike price survives the revision loop
# ---------------------------------------------------------------------------
def test_a_revision_may_resize_an_nso_grant_but_never_reprice_it():
    """PRD §3.4: "A revision may change the share figure and the vesting design but never the strike price, because the strike is pinned to the fair market value captured at draft time: when `exercise_price_cents` is supplied and differs from the value stored on an `ISO` or `NSO` grant, the revision is refused with `ERR_EXERCISE_PRICE_MISMATCH` (HTTP 400). The rule does not apply to `RSU` or `PSU` grants, whose strike is always 0. A revision does not touch `changes_requested_count`, which the send-back already advanced, and it leaves the grant in `CHANGES_REQUESTED` until it is submitted again."

    Design: Corner/validations/exercise_price_mismatch_on_nso_revise_rejected
    """
    _set_clock("2026-01-05T09:00:00Z")
    plan = _register_plan("Corner Plan Mike Two")
    participant = _enrol_participant("E-C-350", full_name="Nick Strike",
                                     birth_date="1991-11-11")
    grant, _rows = _pending_approval_grant(
        plan["id"], participant["id"], "NSO", 1000, exercise_price_cents=2500
    )
    sent_back = validate_success(
        api_client.request_grant_changes(
            grant["id"], {"change_note": "reduce the award size"}, BOARD
        )
    )
    assert sent_back["status"] == "CHANGES_REQUESTED", (
        f"the grant must be in the revision loop, got {sent_back['status']}"
    )
    assert sent_back["changes_requested_count"] == 1, (
        f"the send-back advanced the counter to 1, got {sent_back['changes_requested_count']}"
    )

    repricing = api_client.revise_grant(
        grant["id"], {"target_shares": 800, "exercise_price_cents": 3000}, ADMIN
    )
    validate_error(repricing, "ERR_EXERCISE_PRICE_MISMATCH")

    unchanged = _read_grant(grant["id"])
    assert unchanged["target_shares"] == 1000, (
        f"the refused revision changes no share figure, got {unchanged['target_shares']}"
    )
    assert unchanged["exercise_price_cents"] == 2500, (
        f"the stored strike survives, got {unchanged['exercise_price_cents']}"
    )
    assert unchanged["changes_requested_count"] == 1, (
        f"changes_requested_count stays at 1, got {unchanged['changes_requested_count']}"
    )

    revised = validate_success(
        api_client.revise_grant(
            grant["id"], {"target_shares": 800, "exercise_price_cents": 2500}, ADMIN
        )
    )
    assert_grant(revised)
    assert revised["target_shares"] == 800, (
        f"resending the identical strike with a new size is accepted, got {revised['target_shares']}"
    )
    assert revised["exercise_price_cents"] == 2500, (
        f"exercise_price_cents expected 2500, got {revised['exercise_price_cents']}"
    )
    assert revised["status"] == "CHANGES_REQUESTED", (
        f"a revision leaves the grant in CHANGES_REQUESTED, got {revised['status']}"
    )
    assert revised["changes_requested_count"] == 1, (
        "revise never advances the counter, got "
        f"{revised['changes_requested_count']}"
    )


# ---------------------------------------------------------------------------
# The rejection ladder leaks no existence information
# ---------------------------------------------------------------------------
def test_the_role_gate_answers_before_the_path_row_is_resolved():
    """PRD §2.6: "2. The role gate, yielding `ERR_ROLE_NOT_PERMITTED`. This runs **before** any path parameter is resolved, so a role that may not call an endpoint receives 403 even when the addressed row does not exist."

    PRD §2.6: "Path and body existence failures resolve to an entity-specific identifier rather than a single generic code: `ERR_PLAN_NOT_FOUND`, `ERR_AUTHORITY_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_TRANCHE_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_VESTING_EVENT_NOT_FOUND`, `ERR_TAX_ALLOCATION_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, `ERR_PRECLEARANCE_NOT_FOUND`, `ERR_TRADING_PLAN_NOT_FOUND`, and `ERR_REPORT_NOT_FOUND`. All of them carry HTTP 404."

    Design: Corner/validations/role_check_precedes_existence_check_returns_403
    """
    _set_clock("2026-01-05T09:00:00Z")
    _register_plan("Corner Plan November Two")

    unauthorised = api_client.approve_grant(
        UNKNOWN_UUID, {"approval_path": "BOARD"}, ADMIN
    )
    validate_error(unauthorised, "ERR_ROLE_NOT_PERMITTED")

    permitted = api_client.approve_grant(
        UNKNOWN_UUID, {"approval_path": "BOARD"}, BOARD
    )
    validate_error(permitted, "ERR_GRANT_NOT_FOUND")

    grants, meta = validate_paginated(api_client.list_grants(ADMIN))
    assert grants == [], (
        f"neither refusal created a grant row, got {len(grants)} rows"
    )
    assert_pagination_meta(meta, total_count=0)


def test_a_participant_reading_a_peer_row_is_scoped_out_rather_than_shown_a_404():
    """PRD §2.1: "A `Participant` may therefore reach their own participant record, their own grants, tranches, settlements, tax allocations, mobility assignments, preclearance requests, trading plans, and Section 16 reports, and nothing belonging to a colleague. An attempt to reach a sibling participant's row returns `ERR_PARTICIPANT_SCOPE_VIOLATION` (HTTP 403) and never a 404, so the mere existence of the other row is not disclosed."

    Design: Corner/validations/participant_scope_violation_reading_another_participant
    """
    _set_clock("2026-01-05T09:00:00Z")
    reader = _enrol_participant("E-C-360", full_name="Self Reader",
                                birth_date="1992-12-12")
    peer = _enrol_participant("E-C-361", full_name="Peer Row",
                              birth_date="1993-01-13")
    reader_headers = make_participant_headers(reader["id"])

    scoped_out = api_client.get_participant(peer["id"], reader_headers)
    validate_error(scoped_out, "ERR_PARTICIPANT_SCOPE_VIOLATION")

    own_row = validate_success(
        api_client.get_participant(reader["id"], reader_headers)
    )
    assert_participant(own_row)
    assert own_row["id"] == reader["id"], (
        f"the self read returns the acting participant, got {own_row['id']}"
    )
    assert own_row["full_name"] == "Self Reader", (
        f"full_name expected Self Reader, got {own_row['full_name']}"
    )
    assert own_row["version"] == 1, (
        f"a read mutates nothing, got version {own_row['version']}"
    )
    assert _read_participant(peer["id"])["version"] == 1, (
        "the peer row is untouched by the refused read"
    )
