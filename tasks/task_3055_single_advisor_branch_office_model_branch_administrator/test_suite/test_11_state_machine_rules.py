"""State machine rules: invalid transitions, lockdown, timing, preconditions."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, validate_paginated,
    get_success_data, api_client, ApiErrorId,
    create_advisor, create_territory, create_branch, create_period,
    create_validated_advisor, create_site_approved_branch,
    create_open_branch, setup_retiring_advisor_with_transfer,
    create_administrator, set_clock, make_advisor_headers,
)

ADMIN = TEST_USERS["home_office_admin_headers"]


def test_candidate_cannot_declare_retirement():
    """PRD §3.7: "A practicing advisor declares retirement through their own
    session — the acting advisor must own the advisor record — moving the
    advisor `PRACTICING → RETIRING` and flipping the branch's staffing to
    `SUCCESSION_PENDING`."

    Design: Corner/state_machines/advisor_invalid_transition_declare_retirement_from_candidate
    """
    advisor = create_advisor()
    validate_error(
        api_client.declare_retirement(
            advisor["id"], make_advisor_headers(advisor["id"])
        ),
        ApiErrorId.ERR_INVALID_STATE,
    )
    assert get_success_data(
        api_client.get_advisor(advisor["id"], ADMIN)
    )["status"] == "CANDIDATE"


def test_closed_branch_rejects_reinstate():
    """PRD §3.3: "Closing is terminal and available only from `SUSPENDED`: it
    requires every financial period of the branch to be `FINALIZED` — none may
    remain `OPEN` or `CLOSED` — and no goodwill transfer on the branch may be
    in `OFFERED`, `NEGOTIATING`, or `ACCEPTED` status, otherwise the close is
    rejected with `ERR_TRANSFER_ACTIVE`."

    Design: Corner/state_machines/branch_terminal_close_lockdown
    """
    branch, territory, advisor, boa = create_open_branch()

    # Finalize the auto-created first period so the close precondition holds.
    periods, meta = validate_paginated(
        api_client.list_branch_financial_periods(branch["id"], ADMIN)
    )
    assert len(periods) == 1
    first_period = periods[0]
    set_clock("2026-10-02T00:00:00Z")
    validate_success(api_client.close_period(first_period["id"], ADMIN))
    validate_success(api_client.finalize_period(first_period["id"], ADMIN))

    validate_success(api_client.suspend_branch(branch["id"], ADMIN))
    closed = validate_success(api_client.close_branch(branch["id"], ADMIN))
    assert closed["operating_status"] == "CLOSED"

    validate_error(
        api_client.reinstate_branch(branch["id"], ADMIN),
        ApiErrorId.ERR_INVALID_STATE,
    )
    validate_error(
        api_client.suspend_branch(branch["id"], ADMIN),
        ApiErrorId.ERR_INVALID_STATE,
    )
    assert get_success_data(
        api_client.get_branch(branch["id"], ADMIN)
    )["operating_status"] == "CLOSED"


def test_period_close_before_period_end_rejected():
    """PRD §3.5: "Closing a period requires the logical clock to have reached
    `period_end`; closing earlier is rejected with
    `ERR_PERIOD_NOT_CLOSABLE`."

    Design: Corner/state_machines/period_close_before_period_end_rejected
    """
    territory = create_territory()
    branch, _ = create_branch(territory["id"])
    period = create_period(branch["id"])
    set_clock("2026-09-15T00:00:00Z")

    validate_error(
        api_client.close_period(period["id"], ADMIN),
        ApiErrorId.ERR_PERIOD_NOT_CLOSABLE,
    )
    assert get_success_data(
        api_client.get_financial_period(period["id"], ADMIN)
    )["status"] == "OPEN"


def test_reopen_rejected_when_later_period_exists():
    """PRD §3.5: "A closed period may be reopened — but only if no later
    period exists for the same branch in any status; reopening any period that
    is not the branch's latest is rejected with `ERR_PERIOD_NOT_LATEST`."

    Design: Corner/state_machines/period_reopen_not_latest_rejected
    """
    territory = create_territory()
    branch, _ = create_branch(territory["id"])
    p1 = create_period(branch["id"], "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z")
    create_period(branch["id"], "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z")

    set_clock("2026-10-02T00:00:00Z")
    validate_success(api_client.close_period(p1["id"], ADMIN))

    validate_error(
        api_client.reopen_period(p1["id"], ADMIN),
        ApiErrorId.ERR_PERIOD_NOT_LATEST,
    )
    assert get_success_data(
        api_client.get_financial_period(p1["id"], ADMIN)
    )["status"] == "CLOSED"


def test_branch_open_requires_fully_staffed():
    """PRD §3.3: "Only a `FULLY_STAFFED` branch may open: the open action
    moves a `SITE_APPROVED` branch to `OPEN` and, as a side effect, creates
    the branch's first `OPEN` financial period covering the current calendar
    month."
    PRD §2.9: "Opening or reinstating a branch requires `FULLY_STAFFED`; a
    request made in any other staffing state is rejected with
    `ERR_BRANCH_NOT_FULLY_STAFFED`."

    Design: Corner/state_machines/branch_open_requires_fully_staffed
    """
    branch, territory = create_site_approved_branch()
    advisor = create_validated_advisor()
    validate_success(
        api_client.assign_branch(advisor["id"], {"branch_id": branch["id"]}, ADMIN)
    )

    # Advisor assigned but no ACTIVE administrator: not fully staffed.
    validate_error(
        api_client.open_branch(branch["id"], ADMIN),
        ApiErrorId.ERR_BRANCH_NOT_FULLY_STAFFED,
    )
    assert get_success_data(
        api_client.get_branch(branch["id"], ADMIN)
    )["operating_status"] == "SITE_APPROVED"


def test_assign_branch_requires_validated_advisor():
    """PRD §3.3: "A validated advisor is assigned to a branch in the
    `SITE_APPROVED` or `OPEN` operating state, provided three conditions hold
    — the advisor is `VALIDATED` (otherwise `ERR_ADVISOR_NOT_VALIDATED`), the
    branch has no other advisor whose status is neither `RETIRED` nor
    `TERMINATED` (otherwise `ERR_BRANCH_OCCUPIED`), and the branch's territory
    is either `OPEN` or already assigned to this advisor."

    Design: Corner/state_machines/assign_branch_requires_validated_advisor
    """
    advisor = create_advisor()
    program = get_success_data(api_client.enroll_training(
        advisor["id"],
        {"goal_cents": 100, "start_date": "2026-01-05T00:00:00Z"},
        ADMIN,
    ), expected_status=201)
    branch, territory = create_site_approved_branch()

    validate_error(
        api_client.assign_branch(advisor["id"], {"branch_id": branch["id"]}, ADMIN),
        ApiErrorId.ERR_ADVISOR_NOT_VALIDATED,
    )
    assert get_success_data(
        api_client.get_advisor(advisor["id"], ADMIN)
    )["status"] == "TRAINEE"


def test_offered_transfer_expires_via_clock():
    """PRD §3.7: "Offers age out: when the logical clock reaches thirty days
    past the transfer's `created_at` without acceptance, a transfer still
    `OFFERED` or `NEGOTIATING` expires — the clock-set sweep performs this —
    refunding the escrow and moving it to `EXPIRED`."

    Design: Corner/state_machines/transfer_expiry_via_clock
    """
    transfer, retiring, successor, branch = setup_retiring_advisor_with_transfer(
        clock="2026-09-05T00:00:00Z",
    )
    assert transfer["status"] == "OFFERED"

    set_clock("2026-10-06T00:00:00Z")
    fresh = get_success_data(api_client.get_goodwill_transfer(transfer["id"], ADMIN))
    assert fresh["status"] == "EXPIRED"


def test_finalize_creates_deficit_carryover_charge():
    """PRD §3.5: "Second, when the final net is negative, it creates a
    `DEFICIT_CARRYOVER` charge on the branch's next `OPEN` period for the
    carryforward amount, or holds the carryforward if no open period exists."
    PRD §3.6: "Given a period's `net_profit_cents`: when the net is zero or
    negative, the share is zero."

    Design: Corner/state_machines/deficit_carryover_charge_created_on_finalize
    """
    branch, territory, advisor, boa = create_open_branch()
    # Opening the branch auto-creates the first OPEN period covering the
    # current calendar month (the clock starts at 2026-09-01, so September);
    # an overlapping creation would be rejected, so fetch it via the listing.
    periods, _meta = validate_paginated(
        api_client.list_branch_financial_periods(branch["id"], ADMIN)
    )
    p1 = [p for p in periods
          if p["period_start"].startswith("2026-09-01T00:00:00")
          and p["period_end"].startswith("2026-10-01T00:00:00")][0]
    p2 = create_period(branch["id"], "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z")

    from test_helpers import post_production, post_charge
    post_production(advisor["id"], 300000, "2026-09-10T00:00:00Z")
    post_charge(p1["id"], branch["id"], 400000, "LEASE_RENT")

    set_clock("2026-10-02T00:00:00Z")
    validate_success(api_client.close_period(p1["id"], ADMIN))
    finalized = validate_success(api_client.finalize_period(p1["id"], ADMIN))
    assert finalized["advisor_share_cents"] == 0
    assert finalized["deficit_carryforward_cents"] == 100000

    charges, meta = validate_paginated(
        api_client.list_period_charges(p2["id"], ADMIN)
    )
    carryovers = [c for c in charges if c["charge_type"] == "DEFICIT_CARRYOVER"]
    assert len(carryovers) == 1
    assert carryovers[0]["amount_cents"] == 100000
