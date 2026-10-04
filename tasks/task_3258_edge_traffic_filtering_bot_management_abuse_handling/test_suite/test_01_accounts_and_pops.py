"""Accounts, points of presence, maintenance windows, and capacity planning."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, api_client, TEST_USERS,
    make_account, make_pop, maintenance_window_payload,
    assert_account, assert_meta_envelope,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["network_planner_headers"]


# ---------------------------------------------------------------------------
# Corner/entities/account_create_derives_sla_and_starts_active
# ---------------------------------------------------------------------------

def test_account_create_derives_sla_from_plan_matrix(api):
    """PRD section 3.1: "At creation the platform derives
    support_response_sla_hours from the tier per section 2.7 — 72, 24, 8, or 4
    hours — and stores it on the account; it does not change thereafter."

    Design: Corner/entities/account_create_derives_sla_and_starts_active
    """
    resp = api.create_account(
        {
            "company_name": "Biz Corp",
            "plan_tier": "BUSINESS",
            "account_email": "ops@biz.example.com",
        },
        ADMIN,
    )
    data = validate_success(resp, expected_status=201)
    assert_account(data)
    assert data["support_response_sla_hours"] == 8, (
        "BUSINESS tier derives an 8-hour first-response SLA"
    )
    assert_meta_envelope(resp.json())


def test_account_create_sla_is_derived_not_from_input(api):
    """PRD section 2.7: "First, it sets the account's first-response support
    commitment, recorded as support_response_sla_hours: 72 hours for FREE, 24
    hours for PRO, 8 hours for BUSINESS, and 4 hours for ENTERPRISE."

    Design: Corner/entities/account_create_derives_sla_and_starts_active
    """
    for tier, expected in [("FREE", 72), ("PRO", 24), ("ENTERPRISE", 4)]:
        acc = make_account(plan_tier=tier)
        assert acc["support_response_sla_hours"] == expected, (
            f"{tier} must derive SLA {expected}, got "
            f"{acc['support_response_sla_hours']}"
        )


# ---------------------------------------------------------------------------
# Corner/endpoints/capacity_plan_computed_read
# ---------------------------------------------------------------------------

def _pop_with_window():
    pop = make_pop(code="DFW", capacity_baseline_gbps=200)
    resp = api_client.add_maintenance_window(
        pop["id"],
        maintenance_window_payload(
            "2026-09-15T00:00:00Z", "2026-09-15T02:00:00Z", 40
        ),
        PLANNER,
    )
    get_success_data(resp)
    return pop


def test_capacity_read_inside_maintenance_window(api):
    """PRD section 3.2: "with one or more windows occupying it — a window
    occupies the instant when its start_utc is at or before as_of_utc and its
    end_utc is strictly after — the effective capacity is the baseline
    multiplied by the smallest headroom_pct among the occupying windows,
    divided by 100, with the floor taken once of the full product."

    Design: Corner/endpoints/capacity_plan_computed_read
    """
    pop = _pop_with_window()
    resp = api.get_pop(
        pop["id"], PLANNER,
        params={"as_of_utc": "2026-09-15T01:00:00Z", "reserved_gbps": 60},
    )
    data = validate_success(resp)
    assert data["effective_capacity_gbps"] == 80, (
        "floor(200 * 40 / 100) == 80 inside the 40-headroom window"
    )
    assert data["planned_utilization_pct"] == 75, (
        "round_half_up(100 * 60 / 80) == 75"
    )


def test_capacity_read_outside_maintenance_window(api):
    """PRD section 3.2: "with no maintenance window occupying that instant, the
    effective capacity equals capacity_baseline_gbps" and "otherwise one hundred
    times the reserved amount divided by the effective capacity, rounded half-up
    to a whole percentage."

    Design: Corner/endpoints/capacity_plan_computed_read
    """
    pop = _pop_with_window()
    resp = api.get_pop(
        pop["id"], PLANNER,
        params={"as_of_utc": "2026-09-16T01:00:00Z", "reserved_gbps": 60},
    )
    data = validate_success(resp)
    assert data["effective_capacity_gbps"] == 200
    assert data["planned_utilization_pct"] == 30


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/
# time_range_beats_overlap_on_maintenance_window
# ---------------------------------------------------------------------------

def test_inverted_window_beats_overlap_error(api):
    """PRD section 3.2: "Two temporal rules guard the append, in this order:
    first, end_utc must be strictly after start_utc, or the append fails with
    ERR_INVALID_TIME_RANGE; second, the new window must not overlap any existing
    window on the same PoP."

    Design: Difficulty/priority_pair_validation_conflict/time_range_beats_overlap_on_maintenance_window
    """
    pop = make_pop(code="AMS", capacity_baseline_gbps=100)
    resp = api.add_maintenance_window(
        pop["id"],
        maintenance_window_payload(
            "2026-09-20T01:00:00Z", "2026-09-20T03:00:00Z", 50
        ),
        PLANNER,
    )
    get_success_data(resp)
    # The new window [04:00, 02:00) is inverted AND would collide under naive
    # arithmetic; the range rule is checked first.
    resp = api.add_maintenance_window(
        pop["id"],
        maintenance_window_payload(
            "2026-09-20T04:00:00Z", "2026-09-20T02:00:00Z", 50
        ),
        PLANNER,
    )
    err = validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE)
    assert resp.status_code == 422
    assert err["error_id"] == "ERR_INVALID_TIME_RANGE"
    assert err["error_id"] != "ERR_WINDOW_OVERLAP"


def test_inverted_window_leaves_existing_windows_untouched(api):
    """PRD section 3.2: "A conflicting append is rejected with
    ERR_WINDOW_OVERLAP; a successful one appends the window and increments the
    PoP's version by 1, returning 200." A rejected append adds nothing.

    Design: Difficulty/priority_pair_validation_conflict/time_range_beats_overlap_on_maintenance_window
    """
    pop = make_pop(code="AMS", capacity_baseline_gbps=100)
    resp = api.add_maintenance_window(
        pop["id"],
        maintenance_window_payload(
            "2026-09-20T01:00:00Z", "2026-09-20T03:00:00Z", 50
        ),
        PLANNER,
    )
    get_success_data(resp)
    resp = api.add_maintenance_window(
        pop["id"],
        maintenance_window_payload(
            "2026-09-20T04:00:00Z", "2026-09-20T02:00:00Z", 50
        ),
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE)
    after = validate_success(api.get_pop(pop["id"], PLANNER))
    assert len(after["maintenance_windows"]) == 1, (
        "rejected inverted window must not be appended"
    )


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/maintenance_window_interval_overlap_semantics
# ---------------------------------------------------------------------------

def test_overlapping_window_rejected(api):
    """PRD section 3.2: "the new window conflicts with an existing one only when
    the new start falls before the existing end and the existing start falls
    before the new end."

    Design: Difficulty/resource_temporal_overlap/maintenance_window_interval_overlap_semantics
    """
    pop = make_pop(code="LAX", capacity_baseline_gbps=150)
    get_success_data(api.add_maintenance_window(
        pop["id"],
        maintenance_window_payload(
            "2026-09-12T01:00:00Z", "2026-09-12T03:00:00Z", 50
        ),
        PLANNER,
    ))
    resp = api.add_maintenance_window(
        pop["id"],
        maintenance_window_payload(
            "2026-09-12T02:30:00Z", "2026-09-12T04:00:00Z", 50
        ),
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP)
    assert resp.status_code == 409


def test_adjacent_window_at_existing_end_permitted(api):
    """PRD section 3.2: "Windows that merely touch — the new start equal to an
    existing end, or the new end equal to an existing start — do not conflict."

    Design: Difficulty/resource_temporal_overlap/maintenance_window_interval_overlap_semantics
    """
    pop = make_pop(code="LAX", capacity_baseline_gbps=150)
    get_success_data(api.add_maintenance_window(
        pop["id"],
        maintenance_window_payload(
            "2026-09-12T01:00:00Z", "2026-09-12T03:00:00Z", 50
        ),
        PLANNER,
    ))
    resp = api.add_maintenance_window(
        pop["id"],
        maintenance_window_payload(
            "2026-09-12T03:00:00Z", "2026-09-12T05:00:00Z", 50
        ),
        PLANNER,
    )
    data = validate_success(resp)
    assert len(data["maintenance_windows"]) == 2, (
        "adjacent window at exactly the existing end must be appended"
    )


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/maintenance_window_half_open_boundary
# ---------------------------------------------------------------------------

def test_touching_boundary_succeeds_one_second_earlier_fails(api):
    """PRD section 3.2: "each window occupies from its start_utc up to but not
    including its end_utc, so the new window conflicts with an existing one only
    when the new start falls before the existing end and the existing start
    falls before the new end."

    Design: Difficulty/boundary_precision_check/maintenance_window_half_open_boundary
    """
    pop = make_pop(code="SFO", capacity_baseline_gbps=200)
    get_success_data(api.add_maintenance_window(
        pop["id"],
        maintenance_window_payload(
            "2026-09-10T02:00:00Z", "2026-09-10T04:00:00Z", 40
        ),
        PLANNER,
    ))
    # touching boundary: start == existing end -> allowed
    ok = api.add_maintenance_window(
        pop["id"],
        maintenance_window_payload(
            "2026-09-10T04:00:00Z", "2026-09-10T06:00:00Z", 60
        ),
        PLANNER,
    )
    data = validate_success(ok)
    assert len(data["maintenance_windows"]) == 2
    # one second earlier -> half-open overlap
    bad = api.add_maintenance_window(
        pop["id"],
        maintenance_window_payload(
            "2026-09-10T03:59:59Z", "2026-09-10T05:00:00Z", 60
        ),
        PLANNER,
    )
    validate_error(bad, ApiErrorId.ERR_WINDOW_OVERLAP)


def test_capacity_at_window_boundary_uses_new_window_only(api):
    """PRD section 3.2: "a window occupies the instant when its start_utc is at
    or before as_of_utc and its end_utc is strictly after" — so at exactly the
    first window's end only the second window occupies the instant, and "the
    effective capacity is the baseline multiplied by the smallest headroom_pct
    among the occupying windows, divided by 100, with the floor taken once of
    the full product."

    Design: Difficulty/boundary_precision_check/maintenance_window_half_open_boundary
    """
    pop = make_pop(code="SFO", capacity_baseline_gbps=200)
    get_success_data(api.add_maintenance_window(
        pop["id"],
        maintenance_window_payload(
            "2026-09-10T02:00:00Z", "2026-09-10T04:00:00Z", 40
        ),
        PLANNER,
    ))
    get_success_data(api.add_maintenance_window(
        pop["id"],
        maintenance_window_payload(
            "2026-09-10T04:00:00Z", "2026-09-10T06:00:00Z", 60
        ),
        PLANNER,
    ))
    resp = api.get_pop(
        pop["id"], PLANNER,
        params={"as_of_utc": "2026-09-10T04:00:00Z", "reserved_gbps": 60},
    )
    data = validate_success(resp)
    assert data["effective_capacity_gbps"] == 120, (
        "floor(200 * 60 / 100): only the 60-headroom window occupies 04:00"
    )
