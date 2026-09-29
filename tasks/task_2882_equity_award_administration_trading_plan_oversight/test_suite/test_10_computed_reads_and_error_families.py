"""Computed reads, conditional endpoint actions and the API's error families.

Every test builds the world it needs from scratch through the public endpoints,
because the harness restarts the server and empties the database before each one.
"""

import pytest

from test_helpers import (
    ADMIN,
    AUDITOR,
    BOARD,
    COMPLIANCE,
    OFFICER,
    UNKNOWN_UUID,
    api_client,
    approve_grant_by_board,
    approve_grant_by_delegate,
    assert_burn_rate_summary,
    assert_instant_equals,
    assert_preclearance_request,
    assert_reserve_conservation,
    assert_trading_plan,
    assert_transaction_report,
    assert_vesting_tranche,
    certify_cycle,
    create_authority,
    create_cycle,
    create_draft_grant,
    create_mobility_assignment,
    create_open_window,
    create_participant,
    create_plan,
    create_preclearance,
    decide_preclearance,
    execute_preclearance,
    issue_grant,
    make_headers,
    make_participant_headers,
    read_authority,
    read_cycle,
    read_event,
    read_grant,
    read_participant,
    read_plan,
    read_preclearance,
    read_report,
    read_tranche,
    read_trading_plan,
    read_window,
    reclassify_participant,
    set_clock,
    submit_grant,
    validate_error,
    validate_paginated,
    validate_success,
)

# ---------------------------------------------------------------------------
# Computed reads and conditional actions
# ---------------------------------------------------------------------------


def test_burn_rate_summary_mirrors_the_plan_and_mutates_nothing():
    """PRD §3.1: "A computed read exposes both variants side by side for a plan, together with `plan_id`, `fiscal_year_gross_granted_shares`, `fiscal_year_returned_shares`, `burn_rate_limit_bps`, `available_reserve_shares`, `reserve_posture`, and a `headroom_shares` figure."

    PRD §3.1: "`headroom_shares` is the `burn_rate_limit_bps` multiplied by `common_shares_outstanding`, divided by 10000 and rounded **down** to a whole number of shares, minus `fiscal_year_gross_granted_shares`, and the result is floored at 0 so that an over-budget plan reports zero headroom rather than a negative one."

    Design: Corner/endpoints/burn_rate_summary_computed_read_matches_plan_fields
    """
    set_clock("2026-01-05T09:00:00Z")
    plan = create_plan(
        name="Corner Burn Summary Plan",
        total_authorized_shares=1_000_000,
        common_shares_outstanding=1_000_000,
        fiscal_year_start_date="2026-01-01",
        burn_rate_limit_bps=500,
    )
    participant = create_participant(
        full_name="Bea Burnrate",
        employee_number="E-C-370",
        hire_date="2020-01-06",
        birth_date="1985-02-02",
    )
    grant, _ = create_draft_grant(
        plan["id"],
        participant["id"],
        award_type="NSO",
        target_shares=30000,
        exercise_price_cents=2500,
        tranches=[
            {
                "tranche_index": 1,
                "vest_type": "TIME",
                "scheduled_vest_date": "2027-01-05",
                "target_shares": 30000,
            }
        ],
    )
    submit_grant(grant["id"])
    approve_grant_by_board(grant["id"])

    summary = validate_success(api_client.get_burn_rate_summary(plan["id"], AUDITOR), 200)

    assert summary["plan_id"] == plan["id"], "the summary reports the addressed plan"
    assert summary["gross_burn_rate_bps"] == 300, (
        "30000 option shares against 1000000 outstanding is 300 bps gross, got "
        f"{summary['gross_burn_rate_bps']}"
    )
    assert summary["net_burn_rate_bps"] == 300, (
        "with no returned shares the net variant equals the gross variant, got "
        f"{summary['net_burn_rate_bps']}"
    )
    assert summary["fiscal_year_gross_granted_shares"] == 30000
    assert summary["fiscal_year_returned_shares"] == 0
    assert summary["burn_rate_limit_bps"] == 500
    assert summary["headroom_shares"] == 20000, (
        "headroom is floor(500 * 1000000 / 10000) - 30000 = 20000, got "
        f"{summary['headroom_shares']}"
    )
    assert summary["available_reserve_shares"] == 970000
    assert summary["reserve_posture"] == "OPEN"

    refreshed = read_plan(plan["id"])
    assert_burn_rate_summary(summary, refreshed)
    assert_reserve_conservation(refreshed)
    assert refreshed["version"] == 2, (
        "a computed read writes nothing, so the plan version still reflects only the "
        f"approval, got {refreshed['version']}"
    )


def test_clock_move_echoes_the_instant_backwards_and_mutates_no_row():
    """PRD §2.5: "An administration or compliance operator moves it by supplying a `current_utc` instant; the response echoes that instant back. Moving the clock mutates no entity, and moving it backwards is permitted and does not retroactively re-evaluate any stored state."

    PRD §2.5: "Nothing in this system reads the wall clock."

    Design: Corner/endpoints/clock_set_endpoint_returns_the_new_instant
    """
    set_clock("2026-05-01T12:00:00Z")
    plan = create_plan(
        name="Corner Clock Plan",
        total_authorized_shares=500_000,
        common_shares_outstanding=1_000_000,
        fiscal_year_start_date="2026-01-01",
    )
    assert_instant_equals(
        plan["created_at"], "2026-05-01T12:00:00.000Z", "EquityPlan.created_at"
    )

    echoed = validate_success(
        api_client.set_clock("2026-01-05T09:00:00Z", COMPLIANCE), 200
    )
    assert_instant_equals(
        echoed["current_utc"], "2026-01-05T09:00:00.000Z", "echoed current_utc"
    )

    refreshed = read_plan(plan["id"])
    assert_instant_equals(
        refreshed["created_at"],
        "2026-05-01T12:00:00.000Z",
        "EquityPlan.created_at after the clock moved backwards",
    )
    assert refreshed["version"] == 1, (
        "moving the clock mutates no entity, so the plan version stays 1, got "
        f"{refreshed['version']}"
    )
    assert refreshed["status"] == "ACTIVE"


def _delegation_with_one_approved_and_one_pending_grant():
    """A plan carrying an active delegation that has already approved one grant, plus a
    second grant still waiting for approval under the same delegation."""
    set_clock("2026-01-05T09:00:00Z")
    plan = create_plan(
        name="Corner Revocation Plan",
        total_authorized_shares=200_000,
        common_shares_outstanding=1_000_000,
        fiscal_year_start_date="2026-01-01",
    )
    authority = create_authority(
        plan["id"],
        delegate_user_id="officer-1",
        per_grant_share_cap=5000,
        aggregate_share_cap=10000,
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )
    participant = create_participant(
        full_name="Rex Revocation",
        employee_number="E-C-380",
        hire_date="2020-01-06",
        birth_date="1984-03-03",
    )

    def _option_grant(shares):
        grant, _ = create_draft_grant(
            plan["id"],
            participant["id"],
            award_type="NSO",
            target_shares=shares,
            exercise_price_cents=2500,
            tranches=[
                {
                    "tranche_index": 1,
                    "vest_type": "TIME",
                    "scheduled_vest_date": "2027-01-05",
                    "target_shares": shares,
                }
            ],
        )
        submit_grant(grant["id"])
        return grant

    approved = _option_grant(3000)
    approve_grant_by_delegate(approved["id"], authority["id"], "officer-1")
    pending = _option_grant(1000)
    return plan, authority, approved, pending


def test_revoking_a_delegation_freezes_consumption_and_spares_prior_approvals():
    """PRD §3.2: "Revocation accepts an optional `revocation_reason`. It moves an `ACTIVE` or `EXHAUSTED` delegation to `REVOKED` and stamps `revoked_at` from the logical clock; `consumed_shares` and `remaining_shares` are frozen at whatever they were, and grants already approved under the delegation are entirely unaffected. Revoking a delegation that is already `REVOKED` or already `EXPIRED` is refused with `ERR_AUTHORITY_INVALID_STATE`."

    Design: Corner/endpoints/approval_authority_revoke_is_conditional_action
    """
    plan, authority, approved, _pending = _delegation_with_one_approved_and_one_pending_grant()

    revoked = validate_success(
        api_client.revoke_approval_authority(
            authority["id"], {"revocation_reason": "Officer reassigned."}, BOARD
        ),
        200,
    )
    assert revoked["status"] == "REVOKED", (
        f"an ACTIVE delegation moves to REVOKED, got {revoked['status']}"
    )
    assert_instant_equals(
        revoked["revoked_at"],
        "2026-01-05T09:00:00.000Z",
        "ApprovalAuthority.revoked_at",
    )
    assert revoked["consumed_shares"] == 3000, (
        "consumption is frozen at the 3000 shares already approved, got "
        f"{revoked['consumed_shares']}"
    )
    assert revoked["remaining_shares"] == 7000, (
        f"remaining_shares is frozen at 7000, got {revoked['remaining_shares']}"
    )

    untouched = read_grant(approved["id"])
    assert untouched["status"] == "APPROVED", (
        "a grant already approved under the delegation is entirely unaffected, got "
        f"{untouched['status']}"
    )
    assert untouched["approved_under_authority_id"] == authority["id"]
    assert untouched["approval_path"] == "DELEGATED"

    refreshed_plan = read_plan(plan["id"])
    assert refreshed_plan["shares_committed_cumulative"] == 3000, (
        "revocation returns nothing to the reserve, got "
        f"{refreshed_plan['shares_committed_cumulative']}"
    )


def test_revoked_delegation_can_no_longer_approve_and_cannot_be_revoked_twice():
    """PRD §3.4: "A `REVOKED`, `EXHAUSTED`, or `EXPIRED` delegation, one belonging to another plan, one delegated to a different officer, or an approval dated outside the term all yield `ERR_AUTHORITY_NOT_EFFECTIVE`."

    PRD §3.2: "Revoking a delegation that is already `REVOKED` or already `EXPIRED` is refused with `ERR_AUTHORITY_INVALID_STATE`."

    Design: Corner/endpoints/approval_authority_revoke_is_conditional_action
    """
    _plan, authority, _approved, pending = _delegation_with_one_approved_and_one_pending_grant()
    validate_success(
        api_client.revoke_approval_authority(
            authority["id"], {"revocation_reason": "Officer reassigned."}, BOARD
        ),
        200,
    )

    validate_error(
        api_client.approve_grant(
            pending["id"],
            {"approval_path": "DELEGATED", "authority_id": authority["id"]},
            OFFICER,
        ),
        "ERR_AUTHORITY_NOT_EFFECTIVE",
    )
    still_pending = read_grant(pending["id"])
    assert still_pending["status"] == "PENDING_APPROVAL", (
        "the refused approval leaves the grant awaiting approval, got "
        f"{still_pending['status']}"
    )
    assert still_pending["approved_at"] is None

    validate_error(
        api_client.revoke_approval_authority(
            authority["id"], {"revocation_reason": "Duplicate revocation."}, BOARD
        ),
        "ERR_AUTHORITY_INVALID_STATE",
    )
    unchanged = read_authority(authority["id"])
    assert unchanged["status"] == "REVOKED"
    assert unchanged["consumed_shares"] == 3000


def test_grant_list_filters_narrow_by_authority_and_by_status():
    """PRD §3.4: "Grants are listable with optional `plan_id`, `participant_id`, `approved_under_authority_id`, and `status` filters, and readable individually."

    PRD §2.3: "`total_count` is the number of rows matching the filters before the page window is applied, and `has_more` is true when rows remain beyond the current window."

    Design: Corner/endpoints/grant_list_filtered_by_authority_and_status
    """
    set_clock("2026-01-05T09:00:00Z")
    plan = create_plan(
        name="Corner Grant Filter Plan",
        total_authorized_shares=200_000,
        common_shares_outstanding=1_000_000,
        fiscal_year_start_date="2026-01-01",
    )
    authority = create_authority(
        plan["id"],
        delegate_user_id="officer-1",
        per_grant_share_cap=5000,
        aggregate_share_cap=10000,
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )
    participant = create_participant(
        full_name="Fay Filter",
        employee_number="E-C-390",
        hire_date="2020-01-06",
        birth_date="1986-04-04",
    )

    def _submitted_option_grant(shares):
        grant, _ = create_draft_grant(
            plan["id"],
            participant["id"],
            award_type="NSO",
            target_shares=shares,
            exercise_price_cents=2500,
            tranches=[
                {
                    "tranche_index": 1,
                    "vest_type": "TIME",
                    "scheduled_vest_date": "2027-01-05",
                    "target_shares": shares,
                }
            ],
        )
        submit_grant(grant["id"])
        return grant

    delegated = _submitted_option_grant(2000)
    approve_grant_by_delegate(delegated["id"], authority["id"], "officer-1")
    board = _submitted_option_grant(1000)
    approve_grant_by_board(board["id"])
    pending = _submitted_option_grant(500)

    rows, meta = validate_paginated(
        api_client.list_grants(
            ADMIN,
            params={"plan_id": plan["id"], "approved_under_authority_id": authority["id"]},
        )
    )
    assert meta["total_count"] == 1, (
        f"only the delegated approval cites the delegation, got {meta['total_count']}"
    )
    assert [row["id"] for row in rows] == [delegated["id"]]
    assert rows[0]["approval_path"] == "DELEGATED"

    rows, meta = validate_paginated(
        api_client.list_grants(ADMIN, params={"plan_id": plan["id"], "status": "APPROVED"})
    )
    assert meta["total_count"] == 2, (
        f"both approved grants match the status filter, got {meta['total_count']}"
    )
    assert {row["id"] for row in rows} == {delegated["id"], board["id"]}
    assert {row["approval_path"] for row in rows} == {"DELEGATED", "BOARD"}

    rows, meta = validate_paginated(
        api_client.list_grants(
            ADMIN,
            params={"participant_id": participant["id"], "status": "PENDING_APPROVAL"},
        )
    )
    assert meta["total_count"] == 1, (
        f"the filters combine, leaving only the unapproved grant, got {meta['total_count']}"
    )
    assert [row["id"] for row in rows] == [pending["id"]]
    assert rows[0]["approved_under_authority_id"] is None


def test_plan_freeze_and_unfreeze_round_trip_leaves_children_untouched():
    """PRD §3.1: "Freezing moves an `ACTIVE` plan to `FROZEN` and stores the supplied `freeze_reason`; no child row is mutated at all, because the freeze acts purely as the precondition gate described in §2.10. Unfreezing moves a `FROZEN` plan back to `ACTIVE` and clears `freeze_reason` to null."

    PRD §3.1: "`TERMINATED` is terminal: no plan action has an outgoing transition from it, and attempting `UNFREEZE` on an `ACTIVE` plan or any action on a `TERMINATED` plan yields `ERR_PLAN_INVALID_STATE`."

    Design: Corner/endpoints/equity_plan_freeze_unfreeze_round_trip
    """
    set_clock("2026-01-05T09:00:00Z")
    plan = create_plan(
        name="Corner Freeze Plan",
        total_authorized_shares=100_000,
        common_shares_outstanding=1_000_000,
        fiscal_year_start_date="2026-01-01",
    )
    participant = create_participant(
        full_name="Gil Gate",
        employee_number="E-C-400",
        hire_date="2020-01-06",
        birth_date="1987-05-05",
    )
    grant, tranches = create_draft_grant(
        plan["id"],
        participant["id"],
        award_type="RSU",
        target_shares=1000,
        tranches=[
            {
                "tranche_index": 1,
                "vest_type": "TIME",
                "scheduled_vest_date": "2027-01-05",
                "target_shares": 1000,
            }
        ],
    )

    frozen = validate_success(
        api_client.set_equity_plan_status(
            plan["id"], {"action": "FREEZE", "freeze_reason": "Audit in progress."}, BOARD
        ),
        200,
    )
    assert frozen["status"] == "FROZEN", f"FREEZE moves ACTIVE to FROZEN, got {frozen['status']}"
    assert frozen["freeze_reason"] == "Audit in progress.", (
        f"the supplied freeze_reason is stored, got {frozen['freeze_reason']!r}"
    )
    assert frozen["version"] == 2, f"the plan version advances to 2, got {frozen['version']}"

    child_grant = read_grant(grant["id"])
    assert child_grant["version"] == grant["version"], (
        "no child row is mutated by a freeze, so the grant version is unchanged"
    )
    assert child_grant["status"] == "DRAFT"
    child_tranche = read_tranche(tranches[0]["id"])
    assert child_tranche["version"] == tranches[0]["version"], (
        "no child row is mutated by a freeze, so the tranche version is unchanged"
    )

    thawed = validate_success(
        api_client.set_equity_plan_status(plan["id"], {"action": "UNFREEZE"}, ADMIN), 200
    )
    assert thawed["status"] == "ACTIVE", f"UNFREEZE returns the plan to ACTIVE, got {thawed['status']}"
    assert thawed["freeze_reason"] is None, (
        f"unfreezing clears freeze_reason to null, got {thawed['freeze_reason']!r}"
    )
    assert thawed["version"] == 3, f"the plan version advances to 3, got {thawed['version']}"

    validate_error(
        api_client.set_equity_plan_status(plan["id"], {"action": "UNFREEZE"}, ADMIN),
        "ERR_PLAN_INVALID_STATE",
    )
    unchanged = read_plan(plan["id"])
    assert unchanged["status"] == "ACTIVE"
    assert unchanged["version"] == 3, (
        f"the refused action writes nothing, got version {unchanged['version']}"
    )


def test_performance_tranche_is_reachable_through_its_cycle_cross_reference():
    """PRD §3.4: "A `TIME` tranche must omit `performance_cycle_id` and has its effective `shares` set equal to `target_shares` immediately. A `PERFORMANCE` tranche must supply `performance_cycle_id`, and its `shares` sit at 0 until the cycle is certified — which is why an uncertified performance tranche commits nothing against the reserve."

    PRD §3.4: "Tranches are listable with optional `grant_id`, `performance_cycle_id`, and `status` filters, and readable individually."

    Design: Corner/endpoints/tranche_to_performance_cycle_cross_reference_link
    """
    set_clock("2026-01-05T09:00:00Z")
    plan = create_plan(
        name="Corner Cross Reference Plan",
        total_authorized_shares=100_000,
        common_shares_outstanding=1_000_000,
        fiscal_year_start_date="2026-01-01",
    )
    cycle = create_cycle(
        plan["id"],
        metric_code="TSR-2026",
        target_value=100,
        certification_due_date="2027-02-15",
    )
    participant = create_participant(
        full_name="Cam Cycle",
        employee_number="E-C-410",
        hire_date="2020-01-06",
        birth_date="1988-06-06",
    )
    grant, tranches = create_draft_grant(
        plan["id"],
        participant["id"],
        award_type="PSU",
        target_shares=1000,
        tranches=[
            {
                "tranche_index": 1,
                "vest_type": "PERFORMANCE",
                "scheduled_vest_date": "2027-03-01",
                "target_shares": 600,
                "performance_cycle_id": cycle["id"],
            },
            {
                "tranche_index": 2,
                "vest_type": "TIME",
                "scheduled_vest_date": "2027-03-01",
                "target_shares": 400,
            },
        ],
    )

    rows, meta = validate_paginated(
        api_client.list_vesting_tranches(ADMIN, params={"performance_cycle_id": cycle["id"]})
    )
    assert meta["total_count"] == 1, (
        f"only the performance tranche cites the cycle, got {meta['total_count']}"
    )
    performance = rows[0]
    assert_vesting_tranche(performance)
    assert performance["vest_type"] == "PERFORMANCE"
    assert performance["performance_cycle_id"] == cycle["id"]
    assert performance["target_shares"] == 600
    assert performance["shares"] == 0, (
        "a performance tranche's shares sit at 0 until the cycle is certified, got "
        f"{performance['shares']}"
    )
    assert performance["status"] == "UNVESTED"

    rows, meta = validate_paginated(
        api_client.list_vesting_tranches(ADMIN, params={"grant_id": grant["id"]})
    )
    assert meta["total_count"] == 2, (
        f"the grant carries both tranches, got {meta['total_count']}"
    )
    by_index = {row["tranche_index"]: row for row in rows}
    assert by_index[2]["vest_type"] == "TIME"
    assert by_index[2]["performance_cycle_id"] is None, (
        "a TIME tranche must omit performance_cycle_id"
    )
    assert by_index[2]["shares"] == 400, (
        "a TIME tranche's shares equal target_shares immediately, got "
        f"{by_index[2]['shares']}"
    )

    uncommitted = read_grant(grant["id"])
    assert uncommitted["weighted_reserve_shares"] == 0, (
        "an unapproved grant has charged nothing to the reserve, got "
        f"{uncommitted['weighted_reserve_shares']}"
    )
    assert len(tranches) == 2


# ---------------------------------------------------------------------------
# Error families
# ---------------------------------------------------------------------------

_BAD_IDENTITY_HEADERS = [
    ("absent_user_id", make_headers(None, "PlanAdministrator")),
    ("empty_user_id", make_headers("", "PlanAdministrator")),
    ("whitespace_user_id", make_headers("   ", "PlanAdministrator")),
    ("absent_role", make_headers("admin-1", None)),
    ("unrecognised_role", make_headers("admin-1", "SuperAdmin")),
    ("wrong_case_role", make_headers("admin-1", "planadministrator")),
]


@pytest.mark.parametrize(
    "headers",
    [variant[1] for variant in _BAD_IDENTITY_HEADERS],
    ids=[variant[0] for variant in _BAD_IDENTITY_HEADERS],
)
def test_broken_identity_headers_are_unauthenticated(headers):
    """PRD §2.1: "A request whose `X-User-ID` header is absent, empty, or consists only of whitespace is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role header is absent, or whose value is not one of those six exact strings, is likewise rejected with `ERR_UNAUTHENTICATED` and not with a permission error — no identity can be established, so the failure is authentication rather than authorisation."

    Design: Corner/errors/error_unauthenticated_missing_x_user_id_header
    """
    plan = create_plan(
        name="Corner Identity Plan",
        total_authorized_shares=100_000,
        common_shares_outstanding=1_000_000,
        fiscal_year_start_date="2026-01-01",
    )

    validate_error(api_client.get_equity_plan(plan["id"], headers), "ERR_UNAUTHENTICATED")


def test_authentication_is_decided_before_existence_and_before_permission():
    """PRD §2.6: "Presence of a non-empty `X-User-ID`, then presence of a recognised role — both yielding `ERR_UNAUTHENTICATED`."

    PRD §2.1: "A request whose role header is absent, or whose value is not one of those six exact strings, is likewise rejected with `ERR_UNAUTHENTICATED` and not with a permission error — no identity can be established, so the failure is authentication rather than authorisation."

    Design: Corner/errors/error_unauthenticated_missing_x_user_id_header
    """
    blank_identity = make_headers("", "PlanAdministrator")
    validate_error(
        api_client.get_equity_plan(UNKNOWN_UUID, blank_identity), "ERR_UNAUTHENTICATED"
    )

    unknown_role = make_headers("admin-1", "SuperAdmin")
    validate_error(
        api_client.create_equity_plan(
            {
                "name": "Corner Unauthenticated Plan",
                "total_authorized_shares": 100_000,
                "common_shares_outstanding": 1_000_000,
                "fiscal_year_start_date": "2026-01-01",
            },
            unknown_role,
        ),
        "ERR_UNAUTHENTICATED",
    )

    rows, meta = validate_paginated(api_client.list_equity_plans(ADMIN))
    assert meta["total_count"] == 0, (
        f"neither rejected request wrote a plan row, got {meta['total_count']}"
    )
    assert rows == []


_ENTITY_NOT_FOUND_READS = [
    ("ERR_PLAN_NOT_FOUND", lambda: api_client.get_equity_plan(UNKNOWN_UUID, ADMIN)),
    (
        "ERR_AUTHORITY_NOT_FOUND",
        lambda: api_client.get_approval_authority(UNKNOWN_UUID, ADMIN),
    ),
    (
        "ERR_ASSIGNMENT_NOT_FOUND",
        lambda: api_client.get_mobility_assignment(UNKNOWN_UUID, ADMIN),
    ),
    ("ERR_TRANCHE_NOT_FOUND", lambda: api_client.get_vesting_tranche(UNKNOWN_UUID, ADMIN)),
    (
        "ERR_VESTING_EVENT_NOT_FOUND",
        lambda: api_client.get_vesting_event(UNKNOWN_UUID, ADMIN),
    ),
    (
        "ERR_TAX_ALLOCATION_NOT_FOUND",
        lambda: api_client.get_tax_allocation(UNKNOWN_UUID, ADMIN),
    ),
    ("ERR_WINDOW_NOT_FOUND", lambda: api_client.get_trading_window(UNKNOWN_UUID, ADMIN)),
    (
        "ERR_PRECLEARANCE_NOT_FOUND",
        lambda: api_client.get_preclearance_request(UNKNOWN_UUID, ADMIN),
    ),
    (
        "ERR_TRADING_PLAN_NOT_FOUND",
        lambda: api_client.get_trading_plan(UNKNOWN_UUID, ADMIN),
    ),
    (
        "ERR_REPORT_NOT_FOUND",
        lambda: api_client.get_transaction_report(UNKNOWN_UUID, ADMIN),
    ),
]


@pytest.mark.parametrize(
    "expected_error_id, call",
    _ENTITY_NOT_FOUND_READS,
    ids=[row[0] for row in _ENTITY_NOT_FOUND_READS],
)
def test_not_found_identifiers_are_entity_specific(expected_error_id, call):
    """PRD §2.7: "Path and body existence failures resolve to an entity-specific identifier rather than a single generic code: `ERR_PLAN_NOT_FOUND`, `ERR_AUTHORITY_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_TRANCHE_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_VESTING_EVENT_NOT_FOUND`, `ERR_TAX_ALLOCATION_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, `ERR_PRECLEARANCE_NOT_FOUND`, `ERR_TRADING_PLAN_NOT_FOUND`, and `ERR_REPORT_NOT_FOUND`. All of them carry HTTP 404."

    Design: Corner/errors/error_not_found_codes_are_entity_specific
    """
    validate_error(call(), expected_error_id)


def test_repeated_vest_and_repeated_allocation_report_the_owning_entity():
    """PRD §3.7: "A tranche that is already `VESTED`, `SETTLED`, or `FORFEITED` is refused with `ERR_TRANCHE_INVALID_STATE`."

    PRD §3.7: "The settlement must have `tax_status` `PENDING_ALLOCATION` and `settlement_status` `PENDING_TAX`; an allocation attempted on an already-`ALLOCATED` settlement is refused with `ERR_VESTING_EVENT_INVALID_STATE`."

    Design: Corner/errors/error_tranche_and_event_invalid_state_on_repeated_triggers
    """
    set_clock("2026-01-05T09:00:00Z")
    plan = create_plan(
        name="Corner Replay Plan",
        total_authorized_shares=100_000,
        common_shares_outstanding=1_000_000,
        fiscal_year_start_date="2026-01-01",
    )
    create_open_window(plan["id"], open_at="2026-01-05T00:00:00Z", close_at="2026-03-31T00:00:00Z")
    participant = create_participant(
        full_name="Vic Vest",
        employee_number="E-C-420",
        hire_date="2020-01-06",
        birth_date="1985-07-07",
    )
    create_mobility_assignment(
        participant["id"],
        jurisdiction_code="US-CA",
        tax_rate_bps=1000,
        start_date="2026-01-05",
        end_date="2026-06-30",
        workdays=200,
    )
    grant, tranches = create_draft_grant(
        plan["id"],
        participant["id"],
        award_type="RSU",
        target_shares=500,
        tranches=[
            {
                "tranche_index": 1,
                "vest_type": "TIME",
                "scheduled_vest_date": "2026-06-30",
                "target_shares": 500,
            }
        ],
    )
    submit_grant(grant["id"])
    approve_grant_by_board(grant["id"])
    issue_grant(grant["id"])
    tranche_id = tranches[0]["id"]

    set_clock("2026-06-30T09:00:00Z")
    event = validate_success(
        api_client.vest_tranche(
            tranche_id,
            {"fmv_per_share_cents": 2000, "withholding_method": "SHARE_WITHHOLD"},
            ADMIN,
        ),
        201,
    )
    validate_success(api_client.allocate_taxes(event["id"], ADMIN), 200)

    validate_error(
        api_client.vest_tranche(
            tranche_id,
            {"fmv_per_share_cents": 2000, "withholding_method": "SHARE_WITHHOLD"},
            ADMIN,
        ),
        "ERR_TRANCHE_INVALID_STATE",
    )
    validate_error(
        api_client.allocate_taxes(event["id"], ADMIN), "ERR_VESTING_EVENT_INVALID_STATE"
    )

    events, meta = validate_paginated(
        api_client.list_vesting_events(ADMIN, params={"tranche_id": tranche_id})
    )
    assert meta["total_count"] == 1, (
        f"the replayed vest created no second settlement, got {meta['total_count']}"
    )
    assert events[0]["id"] == event["id"]

    allocations, alloc_meta = validate_paginated(
        api_client.list_event_tax_allocations(event["id"], ADMIN)
    )
    assert alloc_meta["total_count"] == 1, (
        f"the replayed allocation created no second tax row, got {alloc_meta['total_count']}"
    )
    assert allocations[0]["tax_amount_cents"] == 100000, (
        "1000000 cents of income at 10000 bps of a 1000 bps rate is 100000 cents, got "
        f"{allocations[0]['tax_amount_cents']}"
    )

    settlement = read_event(event["id"])
    assert settlement["tax_status"] == "ALLOCATED"
    assert settlement["total_tax_cents"] == 100000
    assert read_tranche(tranche_id)["status"] == "VESTED"


def test_second_termination_and_second_certification_are_entity_specific():
    """PRD §3.8: "The participant's `employment_status` must be `ACTIVE` — terminating someone already `TERMINATED` is refused with `ERR_PARTICIPANT_INVALID_STATE` — and the `termination_date` may not precede their `hire_date`."

    PRD §3.6: "The plan must be `ACTIVE`, and a cycle already `CERTIFIED` or `CANCELLED` cannot be certified again — that attempt yields `ERR_CYCLE_INVALID_STATE`."

    Design: Corner/errors/error_participant_and_cycle_invalid_state_on_second_attempt
    """
    set_clock("2026-01-05T09:00:00Z")
    plan = create_plan(
        name="Corner Second Attempt Plan",
        total_authorized_shares=100_000,
        common_shares_outstanding=1_000_000,
        fiscal_year_start_date="2026-01-01",
    )
    participant = create_participant(
        full_name="Tess Twice",
        employee_number="E-C-430",
        hire_date="2020-01-06",
        birth_date="1983-08-08",
    )
    cycle = create_cycle(
        plan["id"],
        metric_code="TSR-2026",
        target_value=100,
        certification_due_date="2027-02-15",
    )
    certified = certify_cycle(cycle["id"], 100)
    assert certified["status"] == "CERTIFIED"
    assert certified["payout_multiplier_bps"] == 10000, (
        f"a ratio of exactly 1.000000 pays 10000 bps, got {certified['payout_multiplier_bps']}"
    )

    terminated = validate_success(
        api_client.terminate_participant(
            participant["id"],
            {"termination_date": "2026-02-10", "termination_reason": "VOLUNTARY"},
            ADMIN,
        ),
        200,
    )
    assert terminated["employment_status"] == "TERMINATED"
    assert terminated["ptep_expiry_date"] == "2026-05-11", (
        "a VOLUNTARY termination on 2026-02-10 expires the exercise period 90 days "
        f"later on 2026-05-11, got {terminated['ptep_expiry_date']}"
    )

    validate_error(
        api_client.terminate_participant(
            participant["id"],
            {"termination_date": "2026-03-10", "termination_reason": "FOR_CAUSE"},
            ADMIN,
        ),
        "ERR_PARTICIPANT_INVALID_STATE",
    )
    unchanged_participant = read_participant(participant["id"])
    assert unchanged_participant["termination_reason"] == "VOLUNTARY", (
        "the refused second termination overwrites nothing, got "
        f"{unchanged_participant['termination_reason']}"
    )
    assert unchanged_participant["termination_date"] == "2026-02-10"
    assert unchanged_participant["ptep_expiry_date"] == "2026-05-11"

    validate_error(
        api_client.certify_performance_cycle(cycle["id"], {"actual_value": 40}, BOARD),
        "ERR_CYCLE_INVALID_STATE",
    )
    unchanged_cycle = read_cycle(cycle["id"])
    assert unchanged_cycle["status"] == "CERTIFIED"
    assert unchanged_cycle["actual_value"] == 100, (
        f"the refused recertification overwrites nothing, got {unchanged_cycle['actual_value']}"
    )
    assert unchanged_cycle["payout_multiplier_bps"] == 10000


def _executed_preclearance_report(executed_at, requested_shares, executed_shares):
    """A Section 16 officer with one executed clearance and the report it created."""
    set_clock("2026-01-05T09:00:00Z")
    plan = create_plan(
        name="Corner Section Sixteen Plan",
        total_authorized_shares=100_000,
        common_shares_outstanding=1_000_000,
        fiscal_year_start_date="2026-01-01",
    )
    window = create_open_window(
        plan["id"], open_at="2026-01-05T00:00:00Z", close_at="2026-03-31T00:00:00Z"
    )
    participant = create_participant(
        full_name="Iris Insider",
        employee_number="E-C-440",
        hire_date="2019-02-01",
        birth_date="1980-09-09",
    )
    reclassify_participant(participant["id"], "SECTION_16_OFFICER")
    request = create_preclearance(
        participant["id"],
        window["id"],
        transaction_type="SELL",
        requested_shares=requested_shares,
        intended_trade_date="2026-01-09",
    )
    decide_preclearance(request["id"], "APPROVE")

    set_clock(executed_at)
    executed = execute_preclearance(
        request["id"],
        executed_shares,
        4500,
        headers=make_participant_headers(participant["id"]),
    )
    assert executed["status"] == "EXECUTED"

    rows, meta = validate_paginated(
        api_client.list_participant_transaction_reports(participant["id"], COMPLIANCE)
    )
    assert meta["total_count"] == 1, (
        f"the execution created exactly one Section 16 report, got {meta['total_count']}"
    )
    return plan, window, participant, request, rows[0]


def test_filing_a_report_a_second_time_is_refused():
    """PRD §3.9: "Only a `ComplianceOfficer` files, and only a report that is `PENDING`; a second filing attempt on a report already `FILED` or `LATE_FILED` is refused with `ERR_REPORT_INVALID_STATE`."

    PRD §3.9: "`due_at` is the end of the second business day after `transaction_at`."

    Design: Corner/errors/error_report_invalid_state_filing_twice
    """
    _plan, _window, participant, request, report = _executed_preclearance_report(
        "2026-01-08T14:00:00Z", 300, 300
    )
    assert_transaction_report(report)
    assert report["participant_id"] == participant["id"]
    assert report["form_type"] == "FORM_4", (
        f"a SECTION_16_OFFICER files on FORM_4, got {report['form_type']}"
    )
    assert report["source_type"] == "PRECLEARANCE_EXECUTION"
    assert report["source_id"] == request["id"]
    assert report["shares"] == 300, f"shares equal executed_shares, got {report['shares']}"
    assert report["status"] == "PENDING"
    assert report["filed_at"] is None
    assert_instant_equals(
        report["transaction_at"], "2026-01-08T14:00:00.000Z", "TransactionReport.transaction_at"
    )
    assert_instant_equals(
        report["due_at"],
        "2026-01-12T23:59:59.999Z",
        "a Thursday transaction is due at the end of the following Monday",
    )

    set_clock("2026-01-09T10:00:00Z")
    filed = validate_success(api_client.file_transaction_report(report["id"], COMPLIANCE), 200)
    assert filed["status"] == "FILED", (
        f"filing at or before due_at is timely, got {filed['status']}"
    )
    assert_instant_equals(
        filed["filed_at"], "2026-01-09T10:00:00.000Z", "TransactionReport.filed_at"
    )
    assert filed["version"] == 2, f"the report version advances to 2, got {filed['version']}"

    set_clock("2026-01-15T10:00:00Z")
    validate_error(
        api_client.file_transaction_report(report["id"], COMPLIANCE),
        "ERR_REPORT_INVALID_STATE",
    )
    unchanged = read_report(report["id"])
    assert unchanged["status"] == "FILED", (
        f"the refused second filing does not relabel the report, got {unchanged['status']}"
    )
    assert_instant_equals(
        unchanged["filed_at"],
        "2026-01-09T10:00:00.000Z",
        "filed_at is not restamped by the refused filing",
    )
    assert unchanged["version"] == 2


def test_expired_clearance_and_undecided_clearance_fail_differently_on_execute():
    """PRD §3.9: "The logical clock must be at or before `valid_until`; executing at exactly `valid_until` succeeds, one millisecond later is refused with `ERR_PRECLEARANCE_EXPIRED` and the request is left in `APPROVED` so an operator can see the miss."

    PRD §2.6: "The state gate — the addressed row must be in a state from which the requested transition exists — yielding the entity-specific invalid-state error described in §2.7."

    Design: Corner/errors/error_preclearance_expired_and_invalid_state_on_execute
    """
    set_clock("2026-01-06T10:00:00Z")
    plan = create_plan(
        name="Corner Expiry Plan",
        total_authorized_shares=100_000,
        common_shares_outstanding=1_000_000,
        fiscal_year_start_date="2026-01-01",
    )
    window = create_open_window(
        plan["id"], open_at="2026-01-05T00:00:00Z", close_at="2026-03-31T00:00:00Z"
    )
    first = create_participant(
        full_name="Ada Approved",
        employee_number="E-C-450",
        hire_date="2019-03-01",
        birth_date="1981-10-10",
    )
    second = create_participant(
        full_name="Sam Submitted",
        employee_number="E-C-451",
        hire_date="2019-04-01",
        birth_date="1982-11-11",
    )
    for participant in (first, second):
        reclassify_participant(participant["id"], "DESIGNATED_INSIDER")

    approved = create_preclearance(
        first["id"],
        window["id"],
        transaction_type="SELL",
        requested_shares=200,
        intended_trade_date="2026-01-09",
    )
    decided = decide_preclearance(approved["id"], "APPROVE")
    assert_instant_equals(
        decided["valid_until"],
        "2026-01-11T10:00:00.000Z",
        "valid_until is decided_at advanced by five days",
    )
    submitted = create_preclearance(
        second["id"],
        window["id"],
        transaction_type="SELL",
        requested_shares=150,
        intended_trade_date="2026-01-09",
    )

    set_clock("2026-01-12T09:00:00Z")
    validate_error(
        api_client.execute_preclearance_request(
            approved["id"],
            {"executed_shares": 200, "price_per_share_cents": 4500},
            make_participant_headers(first["id"]),
        ),
        "ERR_PRECLEARANCE_EXPIRED",
    )
    stale = read_preclearance(approved["id"])
    assert_preclearance_request(stale)
    assert stale["status"] == "APPROVED", (
        f"the missed clearance is left in APPROVED, got {stale['status']}"
    )
    assert stale["executed_shares"] == 0
    assert stale["executed_at"] is None

    validate_error(
        api_client.execute_preclearance_request(
            submitted["id"],
            {"executed_shares": 150, "price_per_share_cents": 4500},
            make_participant_headers(second["id"]),
        ),
        "ERR_PRECLEARANCE_INVALID_STATE",
    )
    undecided = read_preclearance(submitted["id"])
    assert undecided["status"] == "SUBMITTED", (
        f"an undecided clearance cannot be executed, got {undecided['status']}"
    )
    assert undecided["executed_shares"] == 0

    refreshed_window = read_window(window["id"])
    assert refreshed_window["approved_shares_cumulative"] == 200, (
        "only the approved request reserved shares, got "
        f"{refreshed_window['approved_shares_cumulative']}"
    )

    for participant in (first, second):
        _rows, meta = validate_paginated(
            api_client.list_participant_transaction_reports(participant["id"], COMPLIANCE)
        )
        assert meta["total_count"] == 0, (
            "no execution succeeded, so no Section 16 report exists, got "
            f"{meta['total_count']}"
        )


def test_employee_number_is_issuer_wide_while_metric_code_is_per_plan():
    """PRD §3.3: "If another participant already carries the same `employee_number` — compared exactly and case-sensitively — the enrolment is refused with `ERR_DUPLICATE_EMPLOYEE_NUMBER`."

    PRD §3.6: "The `metric_code` must be unique among the plan's cycles that are not `CANCELLED`; a collision is refused with `ERR_DUPLICATE_METRIC_CODE`."

    Design: Corner/errors/error_duplicate_employee_number_and_metric_code
    """
    set_clock("2026-01-05T09:00:00Z")
    first_plan = create_plan(
        name="Corner Duplicate Plan One",
        total_authorized_shares=100_000,
        common_shares_outstanding=1_000_000,
        fiscal_year_start_date="2026-01-01",
    )
    second_plan = create_plan(
        name="Corner Duplicate Plan Two",
        total_authorized_shares=100_000,
        common_shares_outstanding=1_000_000,
        fiscal_year_start_date="2026-01-01",
    )
    create_participant(
        full_name="Dee Duplicate",
        employee_number="E-C-460",
        hire_date="2020-01-06",
        birth_date="1984-12-12",
    )

    validate_error(
        api_client.create_participant(
            {
                "full_name": "Other Person",
                "employee_number": "E-C-460",
                "home_country_code": "US",
                "home_state_code": "NY",
                "hire_date": "2021-02-01",
                "birth_date": "1990-01-01",
            },
            ADMIN,
        ),
        "ERR_DUPLICATE_EMPLOYEE_NUMBER",
    )
    _rows, meta = validate_paginated(api_client.list_participants(ADMIN))
    assert meta["total_count"] == 1, (
        f"the refused enrolment wrote no participant row, got {meta['total_count']}"
    )

    validate_success(
        api_client.create_performance_cycle(
            {
                "plan_id": first_plan["id"],
                "metric_code": "TSR-2026",
                "target_value": 100,
                "certification_due_date": "2027-02-15",
            },
            ADMIN,
        ),
        201,
    )
    validate_error(
        api_client.create_performance_cycle(
            {
                "plan_id": first_plan["id"],
                "metric_code": "TSR-2026",
                "target_value": 120,
                "certification_due_date": "2027-02-15",
            },
            ADMIN,
        ),
        "ERR_DUPLICATE_METRIC_CODE",
    )
    validate_success(
        api_client.create_performance_cycle(
            {
                "plan_id": second_plan["id"],
                "metric_code": "TSR-2026",
                "target_value": 100,
                "certification_due_date": "2027-02-15",
            },
            ADMIN,
        ),
        201,
    )

    _cycles, first_meta = validate_paginated(
        api_client.list_plan_performance_cycles(first_plan["id"], ADMIN)
    )
    assert first_meta["total_count"] == 1, (
        "uniqueness is scoped to the plan's own cycles, got "
        f"{first_meta['total_count']} on the first plan"
    )
    _cycles, second_meta = validate_paginated(
        api_client.list_plan_performance_cycles(second_plan["id"], ADMIN)
    )
    assert second_meta["total_count"] == 1, (
        "the same code is free on a second plan, got "
        f"{second_meta['total_count']} on the second plan"
    )


def test_second_adoption_during_cooling_off_is_a_trading_plan_conflict():
    """PRD §3.9: "The participant must not already hold a plan in `PENDING_COOLING_OFF` status — one plan may be waiting out its cooling-off period at a time — and a second concurrent adoption is refused with `ERR_TRADING_PLAN_CONFLICT`."

    PRD §3.9: "`first_trade_allowed_at` is then `adopted_at` advanced by `cooling_off_days` whole days using exact instant arithmetic, so the time of day of `adopted_at` is preserved rather than being truncated to midnight."

    Design: Corner/errors/error_trading_plan_conflict_on_second_pending_adoption
    """
    set_clock("2026-01-05T09:00:00Z")
    create_plan(
        name="Corner Conflict Plan",
        total_authorized_shares=100_000,
        common_shares_outstanding=1_000_000,
        fiscal_year_start_date="2026-01-01",
    )
    participant = create_participant(
        full_name="Cody Conflict",
        employee_number="E-C-470",
        hire_date="2019-05-01",
        birth_date="1982-01-15",
        insider_status="DESIGNATED_INSIDER",
    )
    assert participant["version"] == 1

    headers = make_participant_headers(participant["id"])
    adopted = validate_success(
        api_client.create_trading_plan(
            {
                "participant_id": participant["id"],
                "plan_document_ref": "10b5-1/2026/008",
                "first_scheduled_trade_date": "2026-06-01",
                "total_shares": 1200,
                "expected_participant_version": 1,
            },
            headers,
        ),
        201,
    )
    assert_trading_plan(adopted)
    assert adopted["status"] == "PENDING_COOLING_OFF"
    assert adopted["cooling_off_days"] == 30, (
        f"a DESIGNATED_INSIDER adoption has a fixed 30-day period, got {adopted['cooling_off_days']}"
    )
    assert_instant_equals(
        adopted["first_trade_allowed_at"],
        "2026-02-04T09:00:00.000Z",
        "first_trade_allowed_at preserves the time of day of adopted_at",
    )
    assert read_participant(participant["id"])["version"] == 2, (
        "the adoption advanced the participant version to 2"
    )

    validate_error(
        api_client.create_trading_plan(
            {
                "participant_id": participant["id"],
                "plan_document_ref": "10b5-1/2026/009",
                "first_scheduled_trade_date": "2026-07-01",
                "total_shares": 400,
                "expected_participant_version": 2,
            },
            headers,
        ),
        "ERR_TRADING_PLAN_CONFLICT",
    )

    rows, meta = validate_paginated(
        api_client.list_trading_plans(COMPLIANCE, params={"participant_id": participant["id"]})
    )
    assert meta["total_count"] == 1, (
        f"the refused adoption wrote no second plan row, got {meta['total_count']}"
    )
    assert rows[0]["id"] == adopted["id"]
    assert read_participant(participant["id"])["version"] == 2, (
        "the refused adoption did not touch the participant version"
    )


def test_third_modification_of_a_trading_plan_is_refused():
    """PRD §3.9: "`modification_count` is compared against 2 before the loop is opened, so the first and second modifications are allowed and the third is refused with `ERR_MAX_MODIFICATIONS_EXCEEDED`."

    PRD §3.9: "A `Participant` acting for themselves, or a `ComplianceOfficer`, may modify a plan that is `EFFECTIVE`, supplying a fresh `first_scheduled_trade_date` and `total_shares`."

    Design: Corner/errors/error_max_modifications_exceeded_on_third_trading_plan_modify
    """
    set_clock("2026-01-05T09:00:00Z")
    create_plan(
        name="Corner Modification Plan",
        total_authorized_shares=100_000,
        common_shares_outstanding=1_000_000,
        fiscal_year_start_date="2026-01-01",
    )
    participant = create_participant(
        full_name="Mo Modify",
        employee_number="E-C-480",
        hire_date="2019-06-01",
        birth_date="1983-02-16",
        insider_status="NON_INSIDER",
    )
    headers = make_participant_headers(participant["id"])

    adopted = validate_success(
        api_client.create_trading_plan(
            {
                "participant_id": participant["id"],
                "plan_document_ref": "10b5-1/2026/010",
                "first_scheduled_trade_date": "2026-03-02",
                "total_shares": 600,
                "expected_participant_version": 1,
            },
            headers,
        ),
        201,
    )
    assert adopted["cooling_off_days"] == 0, (
        f"a NON_INSIDER adoption may be activated immediately, got {adopted['cooling_off_days']}"
    )
    plan_id = adopted["id"]

    effective = validate_success(api_client.activate_trading_plan(plan_id, COMPLIANCE), 200)
    assert effective["status"] == "EFFECTIVE"

    first_modification = validate_success(
        api_client.modify_trading_plan(
            plan_id, {"first_scheduled_trade_date": "2026-03-09", "total_shares": 800}, headers
        ),
        200,
    )
    assert first_modification["status"] == "PENDING_COOLING_OFF", (
        "a modification returns the plan to PENDING_COOLING_OFF, got "
        f"{first_modification['status']}"
    )
    assert first_modification["modification_count"] == 1

    validate_error(
        api_client.modify_trading_plan(
            plan_id, {"first_scheduled_trade_date": "2026-03-10", "total_shares": 900}, headers
        ),
        "ERR_TRADING_PLAN_INVALID_STATE",
    )
    assert read_trading_plan(plan_id)["modification_count"] == 1, (
        "the refused modification did not advance the counter"
    )

    validate_success(api_client.activate_trading_plan(plan_id, COMPLIANCE), 200)
    second_modification = validate_success(
        api_client.modify_trading_plan(
            plan_id, {"first_scheduled_trade_date": "2026-03-16", "total_shares": 1000}, headers
        ),
        200,
    )
    assert second_modification["modification_count"] == 2, (
        f"the second modification is allowed, got {second_modification['modification_count']}"
    )

    validate_success(api_client.activate_trading_plan(plan_id, COMPLIANCE), 200)
    validate_error(
        api_client.modify_trading_plan(
            plan_id, {"first_scheduled_trade_date": "2026-03-23", "total_shares": 1100}, headers
        ),
        "ERR_MAX_MODIFICATIONS_EXCEEDED",
    )

    final = read_trading_plan(plan_id)
    assert final["modification_count"] == 2, (
        f"the third modification wrote nothing, got {final['modification_count']}"
    )
    assert final["total_shares"] == 1000, (
        f"total_shares still reflects the second modification, got {final['total_shares']}"
    )
    assert final["first_scheduled_trade_date"] == "2026-03-16", (
        "first_scheduled_trade_date still reflects the second modification, got "
        f"{final['first_scheduled_trade_date']}"
    )
    assert final["status"] == "EFFECTIVE"
    assert read_participant(participant["id"])["version"] == 2, (
        "only the adoption touched the participant version"
    )
