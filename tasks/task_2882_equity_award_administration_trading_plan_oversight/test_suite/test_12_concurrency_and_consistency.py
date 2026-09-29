"""Optimistic concurrency, the independent termination fan-out, and the immediate
consistency of derived fields.

Every test builds the world it needs from scratch through the public endpoints,
because the harness restarts the server and empties the database before each one.
"""

from test_helpers import (
    ADMIN,
    BOARD,
    COMPLIANCE,
    api_client,
    approve_grant_by_board,
    assert_burn_rate_summary,
    assert_instant_equals,
    assert_reserve_conservation,
    assert_reserve_posture,
    assert_trading_plan,
    create_open_window,
    create_draft_grant,
    create_participant,
    create_plan,
    create_preclearance,
    decide_preclearance,
    make_participant_headers,
    read_participant,
    read_plan,
    read_preclearance,
    read_trading_plan,
    read_window,
    set_clock,
    submit_grant,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Optimistic concurrency against the Participant
# ---------------------------------------------------------------------------

def _participant_with_an_effective_plan():
    set_clock("2026-01-05T09:00:00Z")
    create_plan(
        name="Corner Adoption Concurrency Plan",
        total_authorized_shares=100_000,
        common_shares_outstanding=1_000_000,
        fiscal_year_start_date="2026-01-01",
    )
    participant = create_participant(
        full_name="Ola Occ",
        employee_number="E-C-540",
        hire_date="2019-07-01",
        birth_date="1984-06-06",
        insider_status="NON_INSIDER",
    )
    assert participant["version"] == 1, "a new participant is ACTIVE at version 1"
    headers = make_participant_headers(participant["id"])

    first = validate_success(
        api_client.create_trading_plan(
            {
                "participant_id": participant["id"],
                "plan_document_ref": "10b5-1/2026/011",
                "first_scheduled_trade_date": "2026-06-01",
                "total_shares": 1200,
                "expected_participant_version": 1,
            },
            headers,
        ),
        201,
    )
    assert_trading_plan(first)
    assert first["status"] == "PENDING_COOLING_OFF"
    assert first["cooling_off_days"] == 0, (
        f"a NON_INSIDER adoption may be activated immediately, got {first['cooling_off_days']}"
    )
    assert first["superseded_plan_id"] is None
    activated = validate_success(
        api_client.activate_trading_plan(first["id"], COMPLIANCE), 200
    )
    assert activated["status"] == "EFFECTIVE"
    assert read_participant(participant["id"])["version"] == 2, (
        "the adoption advanced the participant version to 2"
    )
    return participant, headers, first


def test_a_stale_participant_version_is_refused_with_412_and_writes_nothing():
    """PRD §2.9: "Adopting a trading plan — `POST /trading-plans` — requires a non-optional `expected_participant_version` field carrying the client's last observed `version` of the `Participant` named by `participant_id`. If that value does not equal the participant's current `version`, the adoption is rejected with `ERR_STALE_PARTICIPANT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_participant_version_rejects_trading_plan_adoption
    """
    participant, headers, first = _participant_with_an_effective_plan()

    response = api_client.create_trading_plan(
        {
            "participant_id": participant["id"],
            "plan_document_ref": "10b5-1/2026/012",
            "first_scheduled_trade_date": "2026-07-01",
            "total_shares": 400,
            "expected_participant_version": 1,
        },
        headers,
    )
    assert response.status_code == 412, (
        f"a stale participant version carries HTTP 412, got {response.status_code}"
    )
    validate_error(response, "ERR_STALE_PARTICIPANT_VERSION")

    rows, meta = validate_paginated(
        api_client.list_trading_plans(COMPLIANCE, params={"participant_id": participant["id"]})
    )
    assert meta["total_count"] == 1, (
        f"the rejected adoption wrote no plan row, got {meta['total_count']}"
    )
    assert rows[0]["id"] == first["id"]

    untouched = read_trading_plan(first["id"])
    assert untouched["status"] == "EFFECTIVE", (
        f"the existing plan is untouched, got {untouched['status']}"
    )
    assert untouched["version"] == 2
    assert untouched["superseded_plan_id"] is None
    assert read_participant(participant["id"])["version"] == 2, (
        "the rejected adoption did not advance the participant version"
    )


def test_re_reading_the_participant_version_lets_the_adoption_supersede_the_old_plan():
    """PRD §2.9: "If that value does not equal the participant's current `version`, the adoption is rejected with `ERR_STALE_PARTICIPANT_VERSION` (HTTP 412)."

    PRD §3.9: "When a replacement plan is adopted while the participant already holds an `EFFECTIVE` plan, the prior plan moves to `EXPIRED` with a `termination_reason` of `SUPERSEDED_BY_NEW_ADOPTION`, its `version` advances by 1, and its id is written onto the new row as `superseded_plan_id`, preserving the chain of successive adoptions."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_participant_version_rejects_trading_plan_adoption
    """
    participant, headers, first = _participant_with_an_effective_plan()
    validate_error(
        api_client.create_trading_plan(
            {
                "participant_id": participant["id"],
                "plan_document_ref": "10b5-1/2026/012",
                "first_scheduled_trade_date": "2026-07-01",
                "total_shares": 400,
                "expected_participant_version": 1,
            },
            headers,
        ),
        "ERR_STALE_PARTICIPANT_VERSION",
    )

    observed = read_participant(participant["id"])
    assert observed["version"] == 2

    second = validate_success(
        api_client.create_trading_plan(
            {
                "participant_id": participant["id"],
                "plan_document_ref": "10b5-1/2026/012",
                "first_scheduled_trade_date": "2026-07-01",
                "total_shares": 400,
                "expected_participant_version": observed["version"],
            },
            headers,
        ),
        201,
    )
    assert second["status"] == "PENDING_COOLING_OFF"
    assert second["cooling_off_days"] == 0
    assert second["superseded_plan_id"] == first["id"], (
        "the superseded plan's id is written onto the new row, got "
        f"{second['superseded_plan_id']}"
    )

    superseded = read_trading_plan(first["id"])
    assert superseded["status"] == "EXPIRED", (
        f"the prior effective plan moves to EXPIRED, got {superseded['status']}"
    )
    assert superseded["termination_reason"] == "SUPERSEDED_BY_NEW_ADOPTION", (
        f"the reason records the supersede, got {superseded['termination_reason']}"
    )
    assert superseded["version"] == 3, (
        f"the superseded plan's version advances to 3, got {superseded['version']}"
    )
    assert read_participant(participant["id"])["version"] == 3, (
        "the successful adoption advanced the participant version to 3"
    )


# ---------------------------------------------------------------------------
# Optimistic concurrency against the EquityPlan
# ---------------------------------------------------------------------------

def test_a_stale_plan_version_is_refused_with_412_and_the_retry_applies_cleanly():
    """PRD §2.9: "Posting a share-reserve adjustment — `POST /equity-plans/{id}/share-reserve-adjustments` — requires a non-optional `expected_plan_version` field carrying the client's last observed `version` of the addressed `EquityPlan`. If that value does not equal the plan's current `version`, the adjustment is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412)."

    PRD §3.1: "The adjustment adds `delta_shares` to `total_authorized_shares`, reruns the reserve ledger so that `available_reserve_shares` and `reserve_posture` are rewritten, and increments the plan's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_plan_version_rejects_share_reserve_adjustment
    """
    set_clock("2026-01-05T09:00:00Z")
    plan = create_plan(
        name="Corner Reserve Concurrency Plan",
        total_authorized_shares=1_000_000,
        common_shares_outstanding=1_000_000,
        fiscal_year_start_date="2026-01-01",
    )
    assert plan["version"] == 1

    increased = validate_success(
        api_client.adjust_share_reserve(
            plan["id"], {"delta_shares": 5000, "expected_plan_version": 1}, ADMIN
        ),
        200,
    )
    assert increased["total_authorized_shares"] == 1_005_000, (
        f"the delta is added to the authorised pool, got {increased['total_authorized_shares']}"
    )
    assert increased["available_reserve_shares"] == 1_005_000, (
        f"the reserve ledger is rerun, got {increased['available_reserve_shares']}"
    )
    assert increased["version"] == 2, f"the plan version advances to 2, got {increased['version']}"
    assert_reserve_conservation(increased)
    assert_reserve_posture(increased)

    response = api_client.adjust_share_reserve(
        plan["id"], {"delta_shares": -1000, "expected_plan_version": 1}, ADMIN
    )
    assert response.status_code == 412, (
        f"a stale plan version carries HTTP 412, got {response.status_code}"
    )
    validate_error(response, "ERR_STALE_PLAN_VERSION")

    unchanged = read_plan(plan["id"])
    assert unchanged["total_authorized_shares"] == 1_005_000, (
        "the rejected adjustment applied no part of its delta, got "
        f"{unchanged['total_authorized_shares']}"
    )
    assert unchanged["available_reserve_shares"] == 1_005_000
    assert unchanged["version"] == 2, (
        f"the rejected adjustment did not advance the version, got {unchanged['version']}"
    )

    reduced = validate_success(
        api_client.adjust_share_reserve(
            plan["id"],
            {"delta_shares": -1000, "expected_plan_version": unchanged["version"]},
            ADMIN,
        ),
        200,
    )
    assert reduced["total_authorized_shares"] == 1_004_000, (
        f"the retry applies the reduction once, got {reduced['total_authorized_shares']}"
    )
    assert reduced["available_reserve_shares"] == 1_004_000
    assert reduced["version"] == 3, f"the plan version advances to 3, got {reduced['version']}"
    assert_reserve_conservation(reduced)


# ---------------------------------------------------------------------------
# The independent termination fan-out
# ---------------------------------------------------------------------------

def test_termination_voids_a_clearance_and_terminates_a_trading_plan_with_no_grants():
    """PRD §3.8: "Separately from those four hops, and not part of the chain, termination sweeps the participant's trading activity: every trading plan of theirs whose status is `PENDING_COOLING_OFF` or `EFFECTIVE` moves to `TERMINATED` with its `termination_reason` recorded as `EMPLOYMENT_TERMINATED`, and every preclearance request of theirs whose status is `SUBMITTED`, `INFO_REQUESTED`, or `APPROVED` moves to `VOID`."

    PRD §3.8: "It also writes `ptep_expiry_date`, the date on which the post-termination exercise period ends: the `termination_date` advanced by 0 days for `FOR_CAUSE`, 90 days for `VOLUNTARY`, 180 days for `INVOLUNTARY`, 1095 days for `RETIREMENT`, and 365 days for `DEATH`."

    PRD §3.9: "a request voided that way has its `version` advanced by 1 and causes the window's `approved_shares_cumulative` to be recomputed."

    Design: Corner/cross_cutting_complexity_layers/termination_fanout_voids_preclearance_and_terminates_trading_plan
    """
    set_clock("2026-01-05T09:00:00Z")
    plan = create_plan(
        name="Corner Fan Out Plan",
        total_authorized_shares=100_000,
        common_shares_outstanding=1_000_000,
        fiscal_year_start_date="2026-01-01",
    )
    window = create_open_window(
        plan["id"], open_at="2026-01-05T00:00:00Z", close_at="2026-03-31T00:00:00Z"
    )
    participant = create_participant(
        full_name="Finn Fanout",
        employee_number="E-C-550",
        hire_date="2019-08-01",
        birth_date="1983-09-09",
        insider_status="NON_INSIDER",
    )
    participant_headers = make_participant_headers(participant["id"])

    request = create_preclearance(
        participant["id"],
        window["id"],
        transaction_type="SELL",
        requested_shares=300,
        intended_trade_date="2026-02-16",
    )
    approved = decide_preclearance(request["id"], "APPROVE")
    assert approved["status"] == "APPROVED"
    assert read_window(window["id"])["approved_shares_cumulative"] == 300, (
        "the approval reserved the requested shares against the window"
    )

    trading_plan = validate_success(
        api_client.create_trading_plan(
            {
                "participant_id": participant["id"],
                "plan_document_ref": "10b5-1/2026/013",
                "first_scheduled_trade_date": "2026-03-02",
                "total_shares": 500,
                "expected_participant_version": 1,
            },
            participant_headers,
        ),
        201,
    )
    validate_success(api_client.activate_trading_plan(trading_plan["id"], COMPLIANCE), 200)

    set_clock("2026-02-10T09:00:00Z")
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
    assert terminated["version"] == 3, (
        "one increment for the adoption and one for the termination, got "
        f"{terminated['version']}"
    )

    voided = read_preclearance(request["id"])
    assert voided["status"] == "VOID", (
        f"the approved clearance is swept to VOID, got {voided['status']}"
    )
    assert voided["version"] == 3, (
        f"approval and then the fan-out each advanced the version, got {voided['version']}"
    )

    swept_plan = read_trading_plan(trading_plan["id"])
    assert swept_plan["status"] == "TERMINATED", (
        f"the effective trading plan is swept to TERMINATED, got {swept_plan['status']}"
    )
    assert swept_plan["termination_reason"] == "EMPLOYMENT_TERMINATED", (
        f"the fan-out records its own reason, got {swept_plan['termination_reason']}"
    )

    refreshed_window = read_window(window["id"])
    assert refreshed_window["approved_shares_cumulative"] == 0, (
        "voiding the only approved request releases its reservation, got "
        f"{refreshed_window['approved_shares_cumulative']}"
    )

    refreshed_plan = read_plan(plan["id"])
    assert refreshed_plan["shares_committed_cumulative"] == 0, (
        "the participant held no grant, so the reserve accumulators stay at 0, got "
        f"{refreshed_plan['shares_committed_cumulative']}"
    )
    assert refreshed_plan["shares_returned_cumulative"] == 0
    assert refreshed_plan["available_reserve_shares"] == 100_000
    assert_reserve_conservation(refreshed_plan)


# ---------------------------------------------------------------------------
# Immediate consistency of derived fields
# ---------------------------------------------------------------------------

def test_the_approval_response_already_carries_every_derived_figure():
    """PRD §3.4: "Both paths move the grant from `PENDING_APPROVAL` to `APPROVED`, record `approved_by_user_id` from the acting `X-User-ID`, stamp `approved_at` from the logical clock, store the chosen `approval_path`, write `weighted_reserve_shares` from the calculation above, add that figure to the plan's `shares_committed_cumulative` and to its `fiscal_year_gross_granted_shares`, and then rerun the reserve ledger and both burn-rate variants."

    PRD §3.4: "Second, that committed count is weighted by instrument family: for the full-value types `RSU` and `PSU`, the count is multiplied by the plan's `fungible_ratio_full_value_bps` and divided by 10000, then rounded half up to whole shares; for the option types `ISO` and `NSO`, the count is charged one share for one share with no weighting at all."

    Design: Corner/consistency_model/immediate_consistency_derived_fields_visible_in_same_response
    """
    set_clock("2026-01-05T09:00:00Z")
    plan = create_plan(
        name="Corner Immediate Consistency Plan",
        total_authorized_shares=1_000_000,
        common_shares_outstanding=1_000_000,
        fiscal_year_start_date="2026-01-01",
        fungible_ratio_full_value_bps=15000,
    )
    participant = create_participant(
        full_name="Ida Immediate",
        employee_number="E-C-560",
        hire_date="2020-01-06",
        birth_date="1986-10-10",
    )
    grant, _rows = create_draft_grant(
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
    submit_grant(grant["id"])

    approved = validate_success(
        api_client.approve_grant(grant["id"], {"approval_path": "BOARD"}, BOARD), 200
    )
    assert approved["status"] == "APPROVED"
    assert approved["approval_path"] == "BOARD"
    assert approved["approved_by_user_id"] == "board-1"
    assert_instant_equals(
        approved["approved_at"], "2026-01-05T09:00:00.000Z", "Grant.approved_at"
    )
    assert approved["weighted_reserve_shares"] == 1500, (
        "1000 full-value shares at 15000 bps weigh 1500 shares, got "
        f"{approved['weighted_reserve_shares']}"
    )

    refreshed_plan = read_plan(plan["id"])
    assert refreshed_plan["shares_committed_cumulative"] == 1500
    assert refreshed_plan["available_reserve_shares"] == 998500, (
        f"the reserve ledger is rerun immediately, got {refreshed_plan['available_reserve_shares']}"
    )
    assert refreshed_plan["fiscal_year_gross_granted_shares"] == 1500
    assert refreshed_plan["fiscal_year_returned_shares"] == 0
    assert refreshed_plan["gross_burn_rate_bps"] == 15, (
        f"1500 weighted shares against 1000000 outstanding is 15 bps, got {refreshed_plan['gross_burn_rate_bps']}"
    )
    assert refreshed_plan["net_burn_rate_bps"] == 15
    assert refreshed_plan["version"] == 2, (
        f"the plan version advanced once with the approval, got {refreshed_plan['version']}"
    )
    assert_reserve_conservation(refreshed_plan)
    assert_reserve_posture(refreshed_plan)

    summary = validate_success(api_client.get_burn_rate_summary(plan["id"], ADMIN), 200)
    assert_burn_rate_summary(summary, refreshed_plan)
    assert summary["headroom_shares"] == 998500, (
        f"headroom is floor(10000 * 1000000 / 10000) - 1500, got {summary['headroom_shares']}"
    )


def test_a_refused_approval_leaves_no_partial_state_behind():
    """PRD §3.4: "Second the reserve gate: `available_reserve_shares` must be at least the grant's `weighted_reserve_shares`, and a shortfall is refused with `ERR_RESERVE_INSUFFICIENT`."

    PRD §2.11: "Several operations in this system mutate rows the client did not name. When they do, every touched row has its `updated_at` refreshed and its `version` incremented by 1, and the whole cascade either commits or is refused as a unit — a request that fails a precondition writes nothing, not even the part of the cascade that would have succeeded."

    Design: Corner/consistency_model/immediate_consistency_rejected_write_leaves_no_partial_state
    """
    set_clock("2026-01-05T09:00:00Z")
    plan = create_plan(
        name="Corner No Partial State Plan",
        total_authorized_shares=2000,
        common_shares_outstanding=1_000_000,
        fiscal_year_start_date="2026-01-01",
        fungible_ratio_full_value_bps=15000,
    )
    participant = create_participant(
        full_name="Pat Partial",
        employee_number="E-C-570",
        hire_date="2020-01-06",
        birth_date="1987-11-11",
    )

    def _draft(shares):
        grant, _rows = create_draft_grant(
            plan["id"],
            participant["id"],
            award_type="RSU",
            target_shares=shares,
            tranches=[
                {
                    "tranche_index": 1,
                    "vest_type": "TIME",
                    "scheduled_vest_date": "2027-01-05",
                    "target_shares": shares,
                }
            ],
        )
        return submit_grant(grant["id"])

    first = _draft(1000)
    approve_grant_by_board(first["id"])
    second = _draft(1000)
    assert second["status"] == "PENDING_APPROVAL"

    response = api_client.approve_grant(second["id"], {"approval_path": "BOARD"}, BOARD)
    assert response.status_code == 409, (
        f"an insufficient reserve carries HTTP 409, got {response.status_code}"
    )
    validate_error(response, "ERR_RESERVE_INSUFFICIENT")

    unchanged_grant = validate_success(api_client.get_grant(second["id"], ADMIN), 200)
    assert unchanged_grant["status"] == "PENDING_APPROVAL", (
        f"the refused approval left the grant pending, got {unchanged_grant['status']}"
    )
    assert unchanged_grant["weighted_reserve_shares"] == 0, (
        "no part of the weighting was written, got "
        f"{unchanged_grant['weighted_reserve_shares']}"
    )
    assert unchanged_grant["approved_at"] is None
    assert unchanged_grant["approved_by_user_id"] is None
    assert unchanged_grant["approval_path"] is None
    assert unchanged_grant["version"] == second["version"], (
        "the refused approval did not advance the grant version"
    )

    refreshed_plan = read_plan(plan["id"])
    assert refreshed_plan["shares_committed_cumulative"] == 1500, (
        "only the first approval charged the reserve, got "
        f"{refreshed_plan['shares_committed_cumulative']}"
    )
    assert refreshed_plan["available_reserve_shares"] == 500, (
        f"the reserve still shows the surviving headroom, got {refreshed_plan['available_reserve_shares']}"
    )
    assert refreshed_plan["fiscal_year_gross_granted_shares"] == 1500
    assert refreshed_plan["gross_burn_rate_bps"] == 15
    assert refreshed_plan["net_burn_rate_bps"] == 15
    assert refreshed_plan["version"] == 2, (
        f"the plan version reflects only the first approval, got {refreshed_plan['version']}"
    )
    assert_reserve_conservation(refreshed_plan)
    assert_reserve_posture(refreshed_plan)
