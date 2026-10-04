"""Disqualifications: manual judicial windows (closed-interval overlap), the
auto duration/merge arithmetic, overturn, and the clock-derived lifecycle."""

from test_helpers import (
    AUDIT_AUTHORITY_HEADERS,
    DEFAULT_CLOCK_ISO,
    NON_EXISTENT_UUID,
    ApiErrorId,
    advance_clock_past,
    assert_created,
    assert_disqualification,
    assert_error,
    assert_ok,
    assert_same_instant,
    create_manual_disqualification,
    date_plus_days,
    disqualification_payload,
    expected_dq_window,
    make_jurisdiction_registrar_headers,
    post_conviction,
    read_license,
    read_record,
    read_record_disqualifications,
    reinstate_license,
    set_clock,
    setup_certified_jurisdiction,
    setup_conviction_world,
    setup_driver_record,
    setup_suspended_commercial_license,
)


def _pointer_world_with_record(api, code="AA"):
    """ACTIVE jurisdiction (POINTER_NETWORK certified) holding a driver's record."""
    ctx = setup_certified_jurisdiction(api, code=code, systems=("POINTER_NETWORK",))
    return setup_driver_record(api, ctx)


def test_manual_disqualification_closed_interval_overlap(api):
    """PRD §3.4: "Manual intervals must not overlap an existing derived-`ACTIVE`
    disqualification on the same record — under closed-interval semantics even a shared
    boundary day collides, and the attempt is rejected with
    `ERR_DISQUALIFICATION_OVERLAP`."
    PRD §2.9: "Disqualification intervals, by contrast, are closed: both `start_date`
    and `end_date` are inclusive days, so two intervals that share even a single
    boundary day collide."

    Design: Difficulty/resource_temporal_overlap/manual_disqualification_closed_interval_overlap
    """
    ctx = _pointer_world_with_record(api)
    first = create_manual_disqualification(api, ctx["record_id"], "2026-09-10", "2026-10-10")
    assert first["basis"] == "MANUAL_JUDICIAL"

    # Shared boundary day 2026-10-10 is inside both closed intervals.
    resp = api.create_disqualification(
        disqualification_payload(ctx["record_id"], "2026-10-10", "2026-11-09"),
        AUDIT_AUTHORITY_HEADERS,
    )
    assert_error(resp, ApiErrorId.ERR_DISQUALIFICATION_OVERLAP)

    # Starting one day after the inclusive end is truly disjoint.
    resp = api.create_disqualification(
        disqualification_payload(ctx["record_id"], "2026-10-11", "2026-11-09"),
        AUDIT_AUTHORITY_HEADERS,
    )
    assert_created(resp)

    disqualifications = read_record_disqualifications(api, ctx["record_id"])
    assert len(disqualifications) == 2, "only the two disjoint windows were persisted"


def test_dq_duration_points_prior_multiplier(api):
    """PRD §3.4: "First, the new point total is taken — the offense-window figure
    already including the just-posted conviction, because the points determine the tier
    and the new conviction is itself part of the points."
    PRD §3.4: "Third, the priors are counted — the existing disqualifications on the
    record whose derived status is `ACTIVE` or `COMPLETED`, with overturned ones
    excluded from the count. Fourth, the duration is the base multiplied by one plus the
    prior count, the multiplier capped at three: a first disqualification runs the base
    duration, a second runs double, and a third or later runs triple, never more."

    Design: Difficulty/combinatorial_formula/dq_duration_points_prior_multiplier
    """
    ctx = setup_conviction_world(api, code="AA")
    post_conviction(
        api, ctx["record_id"], ctx["jurisdiction_id"],
        offense_date="2026-08-10", conviction_date="2026-08-20", points=6,
    )
    post_conviction(
        api, ctx["record_id"], ctx["jurisdiction_id"],
        offense_date="2026-08-12", conviction_date="2026-08-21", points=6,
    )
    # 6 + 6 = 12 >= 12: first disqualification runs the 90-day base (prior_count 0).
    first_start, first_end = expected_dq_window(DEFAULT_CLOCK_ISO, 90)
    disqualifications = read_record_disqualifications(api, ctx["record_id"])
    assert len(disqualifications) == 1
    assert disqualifications[0]["basis"] == "AUTO_POINTS"
    assert disqualifications[0]["start_date"] == first_start == "2026-09-01"
    assert disqualifications[0]["end_date"] == first_end == "2026-11-30"

    # Advance past the first disqualification's end: it now derives COMPLETED.
    set_clock(api, "2026-12-15T00:00:00Z")
    assert read_record_disqualifications(api, ctx["record_id"])[0]["status"] == "COMPLETED"

    # The third posting recomputes points_total to 13 (all three offenses are inside
    # the trailing window at 2026-12-15); a COMPLETED prior still counts, so the second
    # disqualification doubles: 90 * min(1 + 1, 3) = 180 days, and no merge applies
    # because the completed interval is not derived-ACTIVE.
    post_conviction(
        api, ctx["record_id"], ctx["jurisdiction_id"],
        offense_date="2026-12-01", conviction_date="2026-12-10", points=1,
        clock_iso="2026-12-15T00:00:00Z",
    )
    assert read_record(api, ctx["record_id"])["points_total"] == 13
    second_start, second_end = expected_dq_window("2026-12-15T00:00:00Z", 180)
    disqualifications = read_record_disqualifications(api, ctx["record_id"])
    assert len(disqualifications) == 2, "no merge: the first interval was already COMPLETED"
    second = disqualifications[1]  # created_at ascending
    assert second["basis"] == "AUTO_POINTS"
    assert second["start_date"] == second_start == "2026-12-15"
    assert second["end_date"] == second_end == "2027-06-13"


def test_auto_disqualification_merges_into_active_window(api):
    """PRD §3.4: "if any existing derived-`ACTIVE` disqualification on the record has a
    closed interval intersecting the new one, no new entity is created; instead exactly
    one merge target — the intersecting disqualification with the earliest `start_date`,
    ties broken by earliest `created_at` — has its `end_date` extended to the later of
    its current end date and the newly computed end date."
    PRD §3.4: "the duration is the base multiplied by one plus the prior count, the
    multiplier capped at three".

    Design: Corner/calculations/auto_disqualification_merges_into_active_window
    """
    ctx = setup_conviction_world(api, code="AA")
    post_conviction(
        api, ctx["record_id"], ctx["jurisdiction_id"],
        offense_date="2026-08-10", conviction_date="2026-08-20", points=6,
    )
    post_conviction(
        api, ctx["record_id"], ctx["jurisdiction_id"],
        offense_date="2026-08-12", conviction_date="2026-08-21", points=6,
    )
    # AUTO_POINTS disqualification [2026-09-01, 2026-11-30] now exists.
    set_clock(api, "2026-10-01T00:00:00Z")
    # CMV_MAJOR fires base 365; the still-ACTIVE prior counts, so the new window is
    # 365 * 2 = 730 days from the clock date: [2026-10-01, 2028-09-30]. It intersects
    # the existing ACTIVE interval, so the merge extends that record instead of
    # creating a new one.
    post_conviction(
        api, ctx["record_id"], ctx["jurisdiction_id"],
        offense_date="2026-09-20", conviction_date="2026-09-25",
        severity="CMV_MAJOR", points=6,
        clock_iso="2026-10-01T00:00:00Z",
    )
    disqualifications = read_record_disqualifications(api, ctx["record_id"])
    assert len(disqualifications) == 1, "overlap resolves through the merge path"
    merged = disqualifications[0]
    assert merged["basis"] == "AUTO_POINTS", "the merge target keeps its basis"
    assert merged["start_date"] == "2026-09-01", "the merge target keeps its start_date"
    assert merged["end_date"] == date_plus_days("2026-10-01", 730) == "2028-09-30"
    assert read_record(api, ctx["record_id"])["points_total"] == 18


def test_disqualification_overturn_happy_path(api):
    """PRD §3.4: "The only direct mutation is the overturn, performed by an
    `AuditAuthority` and valid only while the derived status is `ACTIVE` — overturning
    anything else is `ERR_INVALID_STATE` — which stamps `overturned_at` and flips the
    derived reading to `OVERTURNED`."

    Design: Corner/state_machines/disqualification_overturn_happy_path
    """
    ctx = _pointer_world_with_record(api)
    disqualification = create_manual_disqualification(
        api, ctx["record_id"], "2026-09-10", "2026-09-20"
    )
    resp = api.overturn_disqualification(disqualification["id"], AUDIT_AUTHORITY_HEADERS)
    data = assert_ok(resp)
    assert_disqualification(data)
    assert data["status"] == "OVERTURNED"
    assert data["basis"] == "MANUAL_JUDICIAL", "the overturn does not rewrite the basis"
    assert_same_instant(data["overturned_at"], DEFAULT_CLOCK_ISO, label="overturned_at")


def test_dq_derived_completion_via_clock_blocks_overturn(api):
    """PRD §2.4: "a disqualification's `status` is not stored but derived at read time —
    `OVERTURNED` when its `overturned_at` is set, otherwise `COMPLETED` when the current
    date is strictly after its `end_date`, otherwise `ACTIVE`."
    PRD §3.4: "The only direct mutation is the overturn, performed by an
    `AuditAuthority` and valid only while the derived status is `ACTIVE` — overturning
    anything else is `ERR_INVALID_STATE`".

    Design: Corner/state_machines/dq_derived_completion_via_clock_blocks_overturn
    """
    ctx = _pointer_world_with_record(api)
    disqualification = create_manual_disqualification(
        api, ctx["record_id"], "2026-09-10", "2026-09-20"
    )
    advance_clock_past(api, "2026-09-20")  # clock now reads 2026-09-21
    rows = read_record_disqualifications(api, ctx["record_id"])
    assert rows[0]["status"] == "COMPLETED", "2026-09-21 is strictly after end_date"

    resp = api.overturn_disqualification(disqualification["id"], AUDIT_AUTHORITY_HEADERS)
    assert_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_overturn_unknown_disqualification_not_found(api):
    """PRD §2.6: "Path identifiers and body foreign keys must reference existing
    resources, validated left to right; the first missing reference yields the
    corresponding not-found error" — here `ERR_DISQUALIFICATION_NOT_FOUND` (HTTP 404).

    Design: Corner/errors/overturn_unknown_disqualification_not_found
    """
    resp = api.overturn_disqualification(NON_EXISTENT_UUID, AUDIT_AUTHORITY_HEADERS)
    assert_error(resp, ApiErrorId.ERR_DISQUALIFICATION_NOT_FOUND)


def test_reinstate_blocked_while_dq_active(api):
    """PRD §3.5: "a registrar of the license's `issuing_jurisdiction_id` reinstates a
    `SUSPENDED` license to `ACTIVE`, but only once no disqualification on the backing
    record has derived status `ACTIVE`; a live disqualification blocks the reinstatement
    with `ERR_ACTIVE_DISQUALIFICATION`".

    Design: Corner/errors/reinstate_blocked_while_dq_active
    """
    ctx = setup_suspended_commercial_license(api, code="AA")
    resp = api.reinstate_license(
        ctx["license_id"],
        make_jurisdiction_registrar_headers(ctx["jurisdiction_id"]),
    )
    assert_error(resp, ApiErrorId.ERR_ACTIVE_DISQUALIFICATION)
    assert read_license(api, ctx["license_id"])["status"] == "SUSPENDED"


def test_license_reinstate_after_dq_expiry(api):
    """PRD §2.4: "Advancing the clock therefore re-evaluates derived statuses lazily on
    the next read, with no background job mutating records."
    PRD §3.5: "Reinstatement is the registrar's lever back: a registrar of the license's
    `issuing_jurisdiction_id` reinstates a `SUSPENDED` license to `ACTIVE`, but only
    once no disqualification on the backing record has derived status `ACTIVE`".

    Design: Corner/cross_cutting_layers/license_reinstate_after_dq_expiry
    """
    ctx = setup_suspended_commercial_license(api, code="AA")
    # The AUTO_MAJOR disqualification spans [2026-09-01, 2027-09-01]; move past it.
    advance_clock_past(api, "2027-09-01")  # clock now reads 2027-09-02
    rows = read_record_disqualifications(api, ctx["record_id"])
    assert rows[0]["status"] == "COMPLETED"

    license_body = reinstate_license(api, ctx["license_id"], ctx["jurisdiction_id"])
    assert license_body["status"] == "ACTIVE", (
        "reinstate succeeds once no derived-ACTIVE disqualification remains"
    )
