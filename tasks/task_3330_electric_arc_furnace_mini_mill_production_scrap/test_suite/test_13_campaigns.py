"""Campaign lifecycle: empty commit, cancel side effects, window violation,
roll-change budget boundary (PRD §3.8, §2.8)."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, validate_success, validate_error,
    validate_paginated, set_clock, make_mill, make_grade, make_campaign,
    setup_supply_pool, setup_cast_heat, commit_campaign, get_heat, get_mill,
)

SCH = TEST_USERS["scheduler_headers"]


def test_campaign_commit_empty_returns_campaign_empty():
    """PRD §3.8: "it must have at least one line, else `ERR_CAMPAIGN_EMPTY`
    (HTTP 409)"

    Design: Corner/state_machines/campaign_commit_empty_returns_campaign_empty
    """
    mill = make_mill(name="Hertford Bar Mill", division="CONSTRUCTION")
    camp = make_campaign(
        mill["id"], name="Camp-Empty", planned_start="2026-09-15T08:00:00Z",
        planned_end="2026-09-15T12:00:00Z", roll_change_budget=1)
    resp = api_client.commit_campaign(
        mill["id"], camp["id"], {"expected_campaign_version": camp["version"]}, SCH)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_EMPTY, 409)
    current = validate_success(api_client.get_campaign(mill["id"], camp["id"], SCH), 200)
    assert current["status"] == "OPEN"


def test_campaign_cancel_deletes_lines_but_heats_untouched():
    """PRD §3.8: "Cancelling is available only while `OPEN` and deletes the
    campaign's junction lines outright — the heats themselves are unaffected."

    Design: Corner/state_machines/campaign_cancel_deletes_lines_but_heats_untouched
    """
    mill = make_mill(name="Hertford Bar Mill", division="CONSTRUCTION")
    contract, lots = setup_supply_pool(
        mill["id"], price=39000, committed=100,
        lots=[{"received_on": "2026-09-03", "tons_received": 60, "moisture_pct": 0.0}],
    )
    grade = make_grade(mill["id"], grade_code="GA-40", grade_group="GROUP_A")
    heat = setup_cast_heat(mill["id"], grade["id"], lots[0]["id"], 8,
                           tap_at="2026-09-15T09:00:00Z")
    camp = make_campaign(mill["id"], name="Camp-Cancel",
                         planned_start="2026-09-15T08:00:00Z",
                         planned_end="2026-09-15T10:00:00Z", roll_change_budget=1)
    validate_success(api_client.add_campaign_line(
        mill["id"], camp["id"], {"heat_id": heat["id"]}, SCH), 201)

    cancelled = validate_success(api_client.cancel_campaign(mill["id"], camp["id"], SCH), 200)
    assert cancelled["status"] == "CANCELLED"
    _rows, meta = validate_paginated(
        api_client.list_campaign_lines(mill["id"], camp["id"], SCH))
    assert meta["total_count"] == 0
    assert get_heat(mill["id"], heat["id"])["status"] == "CAST"


def test_campaign_window_violation_heat_outside_window():
    """PRD §3.8: "every line heat's `planned_tap_at` must fall inside the inclusive
    window from `planned_start` to `planned_end`, else
    `ERR_CAMPAIGN_WINDOW_VIOLATION` (HTTP 409)"

    Design: Corner/errors/campaign_window_violation_heat_outside_window
    """
    mill = make_mill(name="Hertford Bar Mill", division="CONSTRUCTION")
    contract, lots = setup_supply_pool(
        mill["id"], price=39000, committed=100,
        lots=[{"received_on": "2026-09-03", "tons_received": 60, "moisture_pct": 0.0}],
    )
    grade = make_grade(mill["id"], grade_code="GA-40", grade_group="GROUP_A")
    heat = setup_cast_heat(mill["id"], grade["id"], lots[0]["id"], 8,
                           tap_at="2026-09-20T09:00:00Z")
    camp = make_campaign(mill["id"], name="Camp-Mismatch",
                         planned_start="2026-09-15T08:00:00Z",
                         planned_end="2026-09-15T10:00:00Z", roll_change_budget=1)
    validate_success(api_client.add_campaign_line(
        mill["id"], camp["id"], {"heat_id": heat["id"]}, SCH), 201)
    current = validate_success(api_client.get_campaign(mill["id"], camp["id"], SCH), 200)

    resp = api_client.commit_campaign(
        mill["id"], camp["id"], {"expected_campaign_version": current["version"]}, SCH)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_WINDOW_VIOLATION, 409)
    after = validate_success(api_client.get_campaign(mill["id"], camp["id"], SCH), 200)
    assert after["status"] == "OPEN"


def _four_cast_heats_mill():
    """Mill with GROUP_A/GROUP_B grades and four CAST heats on distinct days."""
    set_clock("2026-09-10T00:00:00Z")
    mill = make_mill(name="Hertford Bar Mill", division="CONSTRUCTION")
    contract, lots = setup_supply_pool(
        mill["id"], price=39000, committed=100,
        lots=[{"received_on": "2026-09-03", "tons_received": 60, "moisture_pct": 0.0}],
    )
    grade_a = make_grade(mill["id"], grade_code="GA-40", grade_group="GROUP_A")
    grade_b = make_grade(mill["id"], grade_code="GB-60", grade_group="GROUP_B")
    heats = {}
    for key, grade, tap_at in (
        ("a1", grade_a, "2026-09-15T08:00:00Z"),
        ("b1", grade_b, "2026-09-16T10:00:00Z"),
        ("a2", grade_a, "2026-09-17T12:00:00Z"),
        ("b2", grade_b, "2026-09-18T14:00:00Z"),
    ):
        heats[key] = setup_cast_heat(mill["id"], grade["id"], lots[0]["id"], 8,
                                     tap_at=tap_at)
    return mill, heats


def test_campaign_roll_change_budget_at_exact_limit_commits():
    """PRD §3.8: "the recomputed `roll_changes_used` must not exceed
    `roll_change_budget`, else `ERR_ROLL_CHANGE_BUDGET_EXCEEDED` (HTTP 422)"
    PRD §3.8: "A successful commit freezes `roll_changes_used` from the committed
    line sequence, moves the campaign to `COMMITTED`, and bumps its `version`."

    Design: Difficulty/boundary_precision_check/campaign_roll_change_budget_at_exact_limit
    """
    mill, heats = _four_cast_heats_mill()
    camp = make_campaign(mill["id"], name="Camp-OK", grade_group="GROUP_A",
                         planned_start="2026-09-15T07:00:00Z",
                         planned_end="2026-09-15T11:00:00Z", roll_change_budget=0)
    validate_success(api_client.add_campaign_line(
        mill["id"], camp["id"], {"heat_id": heats["a1"]["id"]}, SCH), 201)

    committed = commit_campaign(mill["id"], camp["id"])
    # Single line: 0 changes == budget 0 — the boundary is inclusive.
    assert committed["status"] == "COMMITTED"
    assert committed["roll_changes_used"] == 0


def test_campaign_roll_change_budget_over_limit_rejects():
    """PRD §3.8: "the recomputed `roll_changes_used` must not exceed
    `roll_change_budget`, else `ERR_ROLL_CHANGE_BUDGET_EXCEEDED` (HTTP 422)"
    PRD §3.8: "each line's effective group is its heat's grade's `grade_group`
    (resolved through the line's heat to that heat's grade), and `roll_changes_used`
    counts the adjacent pairs whose groups differ"

    Design: Difficulty/boundary_precision_check/campaign_roll_change_budget_at_exact_limit
    """
    mill, heats = _four_cast_heats_mill()
    camp = make_campaign(mill["id"], name="Camp-Over", grade_group="GROUP_A",
                         planned_start="2026-09-16T07:00:00Z",
                         planned_end="2026-09-19T18:00:00Z", roll_change_budget=1)
    for key in ("b1", "a2", "b2"):
        validate_success(api_client.add_campaign_line(
            mill["id"], camp["id"], {"heat_id": heats[key]["id"]}, SCH), 201)
    current = validate_success(api_client.get_campaign(mill["id"], camp["id"], SCH), 200)

    # Tap-ordered sequence B(16th) -> A(17th) -> B(18th) = 2 changes > budget 1.
    resp = api_client.commit_campaign(
        mill["id"], camp["id"], {"expected_campaign_version": current["version"]}, SCH)
    validate_error(resp, ApiErrorId.ERR_ROLL_CHANGE_BUDGET_EXCEEDED, 422)
    after = validate_success(api_client.get_campaign(mill["id"], camp["id"], SCH), 200)
    assert after["status"] == "OPEN"


def _three_campaign_mill():
    """Mill with two CAST heats and committed C1 [08:00, 10:00) REBAR."""
    set_clock("2026-09-10T00:00:00Z")
    mill = make_mill(name="Hertford Bar Mill", division="CONSTRUCTION")
    contract, lots = setup_supply_pool(
        mill["id"], price=39000, committed=100,
        lots=[{"received_on": "2026-09-03", "tons_received": 60, "moisture_pct": 0.0}],
    )
    grade = make_grade(mill["id"], grade_code="GA-40", grade_group="GROUP_A")
    h1 = setup_cast_heat(mill["id"], grade["id"], lots[0]["id"], 8,
                         tap_at="2026-09-15T09:00:00Z")
    h2 = setup_cast_heat(mill["id"], grade["id"], lots[0]["id"], 8,
                         tap_at="2026-09-15T11:00:00Z")
    c1 = make_campaign(mill["id"], name="C1",
                       planned_start="2026-09-15T08:00:00Z",
                       planned_end="2026-09-15T10:00:00Z", roll_change_budget=1)
    validate_success(api_client.add_campaign_line(
        mill["id"], c1["id"], {"heat_id": h1["id"]}, SCH), 201)
    commit_campaign(mill["id"], c1["id"])
    return mill, h1, h2


def test_campaign_touching_endpoint_commits_half_open():
    """PRD §3.8: "Overlap uses half-open semantics: two campaigns overlap when each
    one's start is strictly before the other's end, so touching endpoints — one
    campaign ending exactly when another starts — are allowed."

    Design: Difficulty/resource_temporal_overlap/campaign_window_half_open_overlap
    """
    mill, h1, h2 = _three_campaign_mill()
    c2 = make_campaign(mill["id"], name="C2",
                       planned_start="2026-09-15T10:00:00Z",
                       planned_end="2026-09-15T12:00:00Z", roll_change_budget=1)
    validate_success(api_client.add_campaign_line(
        mill["id"], c2["id"], {"heat_id": h2["id"]}, SCH), 201)
    committed = commit_campaign(mill["id"], c2["id"])
    assert committed["status"] == "COMMITTED"


def test_campaign_genuine_overlap_rejected():
    """PRD §3.8: "the campaign's window must not overlap any other `COMMITTED`
    campaign of the same mill and same `product_family`, else `ERR_CAMPAIGN_OVERLAP`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/campaign_window_half_open_overlap
    """
    mill, h1, h2 = _three_campaign_mill()
    c3 = make_campaign(mill["id"], name="C3",
                       planned_start="2026-09-15T09:30:00Z",
                       planned_end="2026-09-15T11:00:00Z", roll_change_budget=1)
    validate_success(api_client.add_campaign_line(
        mill["id"], c3["id"], {"heat_id": h2["id"]}, SCH), 201)
    current = validate_success(api_client.get_campaign(mill["id"], c3["id"], SCH), 200)

    resp = api_client.commit_campaign(
        mill["id"], c3["id"], {"expected_campaign_version": current["version"]}, SCH)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_OVERLAP, 409)
    after = validate_success(api_client.get_campaign(mill["id"], c3["id"], SCH), 200)
    assert after["status"] == "OPEN"
