"""Retention policies and purge workflows (PRD §3.9)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_institution,
    make_instructor_headers,
    process,
    reset_clock,
    setup_basic_scenario,
    submit,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INST_ADMIN = TEST_USERS["institutional_admin_headers"]


def test_retention_policy_window_overlap_adjacency_allowed(api):
    """PRD §3.9: "Windows also may not collide: a new policy is rejected with
    `ERR_RETENTION_WINDOW_OVERLAP` (HTTP 409) if its half-open interval overlaps
    any existing `ACTIVE` policy of the same institution whose `applies_to`
    collides — `BOTH` collides with everything, including itself — where
    adjacency does not count as overlap (one window ending exactly where another
    begins is allowed)."

    Design: Difficulty/resource_temporal_overlap/retention_policy_window_overlap_adjacency_allowed
    """
    inst = create_institution(name="Overlap U", residency_region="US")
    # Windows must lie in the future relative to the logical clock (which starts
    # at 2026-09-01T00:00:00Z, PRD §2.4) so both policies are ACTIVE — the
    # overlap rule only applies against ACTIVE policies (PRD §3.9).
    validate_success(
        api.create_retention_policy(
            inst["id"],
            {"region": "US", "applies_to": "SUBMISSIONS",
             "retention_start": "2027-01-01T00:00:00Z", "retention_end": "2027-06-01T00:00:00Z"},
            ADMIN,
        ),
        expected_status=201,
    )
    overlap = api.create_retention_policy(
        inst["id"],
        {"region": "US", "applies_to": "SUBMISSIONS",
         "retention_start": "2027-03-01T00:00:00Z", "retention_end": "2027-09-01T00:00:00Z"},
        ADMIN,
    )
    validate_error(overlap, ApiErrorId.ERR_RETENTION_WINDOW_OVERLAP, expected_status=409)

    adjacent = api.create_retention_policy(
        inst["id"],
        {"region": "US", "applies_to": "SUBMISSIONS",
         "retention_start": "2027-06-01T00:00:00Z", "retention_end": "2027-12-01T00:00:00Z"},
        ADMIN,
    )
    validate_success(adjacent, expected_status=201)

    data, meta = validate_paginated(api.list_retention_policies(inst["id"], ADMIN))
    assert len(data) == 2
    assert all(p["policy_state"] == "ACTIVE" for p in data)


def test_retention_policy_overlap_detected_reverse_order(api):
    """PRD §3.9: "a new policy is rejected with `ERR_RETENTION_WINDOW_OVERLAP`
    (HTTP 409) if its half-open interval overlaps any existing `ACTIVE` policy
    of the same institution whose `applies_to` collides"

    Design: Difficulty/resource_temporal_overlap/retention_policy_window_overlap_adjacency_allowed
    """
    inst = create_institution(name="Overlap2 U", residency_region="US")
    # Future windows so the existing policy is ACTIVE at creation time (the
    # logical clock starts at 2026-09-01T00:00:00Z, PRD §2.4).
    validate_success(
        api.create_retention_policy(
            inst["id"],
            {"region": "US", "applies_to": "REPORTS",
             "retention_start": "2027-01-01T00:00:00Z", "retention_end": "2027-06-01T00:00:00Z"},
            ADMIN,
        ),
        expected_status=201,
    )
    # BOTH collides with everything, including an existing REPORTS policy.
    both = api.create_retention_policy(
        inst["id"],
        {"region": "US", "applies_to": "BOTH",
         "retention_start": "2027-05-01T00:00:00Z", "retention_end": "2027-07-01T00:00:00Z"},
        ADMIN,
    )
    validate_error(both, ApiErrorId.ERR_RETENTION_WINDOW_OVERLAP, expected_status=409)


def test_retention_policy_lazy_expiry(api):
    """PRD §3.9: "it starts `ACTIVE` and transitions to `EXPIRED` lazily, on
    read or at purge time, once the logical clock reaches `retention_end`,
    incrementing its `version`." PRD §3.9: "running a purge on an `EXPIRED`
    policy is `ERR_POLICY_EXPIRED` (HTTP 409)"

    Design: Corner/state_machines/retention_policy_lazy_expiry
    """
    reset_clock("2026-09-01T00:00:00Z")
    inst = create_institution(name="Exp U", residency_region="US")
    policy = validate_success(
        api.create_retention_policy(
            inst["id"],
            {"region": "US", "applies_to": "SUBMISSIONS",
             "retention_start": "2026-01-01T00:00:00Z", "retention_end": "2026-02-01T00:00:00Z"},
            ADMIN,
        ),
        expected_status=201,
    )
    reset_clock("2026-03-01T00:00:00Z")  # past retention_end

    resp = api.run_purge(policy["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_POLICY_EXPIRED, expected_status=409)

    data, _ = validate_paginated(api.list_retention_policies(inst["id"], ADMIN))
    assert data[0]["policy_state"] == "EXPIRED", "lazy transition applied on read"


def test_invalid_retention_window_rejected(api):
    """PRD §3.9: "The window must be non-empty — `retention_start` strictly
    before `retention_end` — and the policy's `region` must equal the
    institution's `residency_region`; violations are
    `ERR_INVALID_RETENTION_WINDOW` (HTTP 422)."

    Design: Corner/validations/invalid_retention_window_rejected
    """
    inst = create_institution(name="Win U", residency_region="US")
    bad_order = api.create_retention_policy(
        inst["id"],
        {"region": "US", "applies_to": "BOTH",
         "retention_start": "2026-06-01T00:00:00Z", "retention_end": "2026-01-01T00:00:00Z"},
        ADMIN,
    )
    validate_error(bad_order, ApiErrorId.ERR_INVALID_RETENTION_WINDOW, expected_status=422)

    bad_region = api.create_retention_policy(
        inst["id"],
        {"region": "EU", "applies_to": "BOTH",
         "retention_start": "2026-01-01T00:00:00Z", "retention_end": "2026-06-01T00:00:00Z"},
        ADMIN,
    )
    validate_error(bad_region, ApiErrorId.ERR_INVALID_RETENTION_WINDOW, expected_status=422)

    data, _ = validate_paginated(api.list_retention_policies(inst["id"], ADMIN))
    assert data == []


def test_retention_window_end_exclusive_boundary(api):
    """PRD §3.9: "The candidate set is then the institution's submissions whose
    `submitted_at` falls inside the half-open window and whose `pipeline_state`
    is not `SUPERSEDED`" PRD §3.9: "The boundary asymmetry is intentional: a
    submission timestamped exactly at `retention_end` is not a candidate (the
    window is half-open)"

    Design: Difficulty/boundary_precision_check/retention_window_end_exclusive_boundary
    """
    reset_clock("2026-09-01T00:00:00Z")
    inst, integ, instr, student, asg = setup_basic_scenario(
        "US", assignment_overrides={"max_submissions_per_student": 5, "due_at": "2027-06-01T00:00:00Z"}
    )
    reset_clock("2026-09-05T00:00:00Z")
    sub_old = submit(asg["id"], student["id"], "old inside window")
    reset_clock("2026-10-01T00:00:00Z")
    sub_edge = submit(asg["id"], student["id"], "edge at window end")
    # Policy created while the clock is before retention_end so it is ACTIVE;
    # the purge then runs before expiry (EXPIRED at clock >= retention_end).
    reset_clock("2026-09-30T00:00:00Z")

    policy = validate_success(
        api.create_retention_policy(
            inst["id"],
            {"region": "US", "applies_to": "SUBMISSIONS",
             "retention_start": "2026-09-01T00:00:00Z", "retention_end": "2026-10-01T00:00:00Z"},
            ADMIN,
        ),
        expected_status=201,
    )
    result = validate_success(api.run_purge(policy["id"], ADMIN))
    assert result["purged_count"] == 1, "only the 2026-09-05 submission is inside [09-01, 10-01)"

    edge = validate_success(api.get_submission(sub_edge["id"], make_instructor_headers(instr["id"])))
    assert edge["pipeline_state"] == "RECEIVED", "submitted_at == retention_end exactly survives"

    gone = api.get_submission(sub_old["id"], make_instructor_headers(instr["id"]))
    validate_error(gone, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_purge_grace_closed_interval_conflict(api):
    """PRD §3.9: "Before anything is deleted, one aggregate safety check runs
    over the whole candidate set: if any candidate owns a deposit in
    `deposit_state` `STORED` whose `stored_at` lies inside the closed grace
    interval beginning seven days before `retention_start` and ending at
    `retention_end` — both endpoints included — the entire run is rejected with
    `ERR_PURGE_GRACE_CONFLICT` (HTTP 409) and nothing is purged." PRD §3.9:
    "transitions to `EXPIRED` lazily, on read or at purge time, once the
    logical clock reaches `retention_end`"

    The candidate's deposit is STORED with `stored_at` inside the closed grace
    interval [retention_start - 7 days, retention_end], and the purge runs
    while the policy is still ACTIVE (clock < retention_end).

    Design: Difficulty/resource_temporal_overlap/purge_grace_closed_interval_conflict
    """
    reset_clock("2026-09-01T00:00:00Z")
    inst, integ, instr, student, asg = setup_basic_scenario(
        "US",
        inst_overrides={"repository_participation": "GLOBAL_SHARED"},
        assignment_overrides={"repository_option": "STORE_AND_COMPARE",
                              "due_at": "2027-06-01T00:00:00Z"},
    )
    # Policy created while ACTIVE; closed grace interval is [2026-08-25, 2026-11-01].
    policy = validate_success(
        api.create_retention_policy(
            inst["id"],
            {"region": "US", "applies_to": "SUBMISSIONS",
             "retention_start": "2026-09-01T00:00:00Z", "retention_end": "2026-11-01T00:00:00Z"},
            ADMIN,
        ),
        expected_status=201,
    )
    reset_clock("2026-09-05T00:00:00Z")
    sub = submit(asg["id"], student["id"], "grace body text")
    process(sub["id"], instr["id"])  # deposit stored_at 2026-09-05, inside grace interval
    # Advance within the window but before retention_end: policy still ACTIVE.
    reset_clock("2026-10-01T00:00:00Z")
    resp = api.run_purge(policy["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PURGE_GRACE_CONFLICT, expected_status=409)

    alive = validate_success(api.get_submission(sub["id"], make_instructor_headers(instr["id"])))
    assert alive["pipeline_state"] == "REPORT_READY", "nothing purged on grace conflict"
    count = validate_success(api.get_institution(inst["id"], ADMIN))["comparable_submission_count"]
    assert count == 1, "no withdrawal happened"


def test_purge_withdraws_deposits_and_cascades(api):
    """PRD §3.9: "When no conflict exists, the purge deletes every candidate
    submission together with its match fragments and similarity reports" PRD
    §3.4: "Either way, the assignment's `submission_count` is recomputed after
    intake; that counter always equals the number of the assignment's
    submissions whose `pipeline_state` is not `SUPERSEDED`"

    Design: Corner/cross_cutting_layers/purge_withdraws_deposits_and_cascades
    """
    reset_clock("2026-09-01T00:00:00Z")
    # COMPARE_ONLY (default): no deposit exists, so the grace check is vacuous.
    inst, integ, instr, student, asg = setup_basic_scenario(
        "US", assignment_overrides={"max_submissions_per_student": 5, "due_at": "2027-06-01T00:00:00Z"}
    )
    # sub_out sits before the window start; the clock only advances, so the
    # window must begin after 2026-09-05.
    reset_clock("2026-09-05T00:00:00Z")
    sub_out = submit(asg["id"], student["id"], "keep me")
    reset_clock("2026-10-05T00:00:00Z")
    sub_in = submit(asg["id"], student["id"], "purge me")
    # The policy expires once the logical clock reaches retention_end
    # (PRD §3.9), so the purge runs while the clock is still before it.
    reset_clock("2026-10-20T00:00:00Z")

    policy = validate_success(
        api.create_retention_policy(
            inst["id"],
            {"region": "US", "applies_to": "SUBMISSIONS",
             "retention_start": "2026-10-01T00:00:00Z", "retention_end": "2026-11-01T00:00:00Z"},
            ADMIN,
        ),
        expected_status=201,
    )
    result = validate_success(api.run_purge(policy["id"], ADMIN))
    assert result["purged_count"] == 1
    assert result["purged_submission_ids"] == [sub_in["id"]]

    gone = api.get_submission(sub_in["id"], make_instructor_headers(instr["id"]))
    validate_error(gone, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
    kept = validate_success(api.get_submission(sub_out["id"], make_instructor_headers(instr["id"])))
    assert kept["pipeline_state"] == "RECEIVED"

    asg_after = validate_success(api.get_assignment(asg["id"], make_instructor_headers(instr["id"])))
    assert asg_after["submission_count"] == 1, "derived field reconciles after destructive purge"


def test_retention_window_start_inclusive_boundary(api):
    """PRD §3.9: "a half-open window running from `retention_start` (inclusive)
    to `retention_end` (exclusive)" PRD §3.9: "The candidate set is then the
    institution's submissions whose `submitted_at` falls inside the half-open
    window"

    Design: Difficulty/boundary_precision_check/retention_window_end_exclusive_boundary
    """
    reset_clock("2026-09-01T00:00:00Z")
    inst, integ, instr, student, asg = setup_basic_scenario(
        "US", assignment_overrides={"max_submissions_per_student": 5, "due_at": "2027-06-01T00:00:00Z"}
    )
    # Submission timestamped exactly at retention_start IS a candidate.
    sub_start = submit(asg["id"], student["id"], "at window start")
    # Purge before the clock reaches retention_end so the policy stays ACTIVE
    # (PRD §3.9: EXPIRED once the logical clock reaches retention_end).
    reset_clock("2026-09-05T00:00:00Z")
    policy = validate_success(
        api.create_retention_policy(
            inst["id"],
            {"region": "US", "applies_to": "SUBMISSIONS",
             "retention_start": "2026-09-01T00:00:00Z", "retention_end": "2026-09-10T00:00:00Z"},
            ADMIN,
        ),
        expected_status=201,
    )
    result = validate_success(api.run_purge(policy["id"], ADMIN))
    assert result["purged_count"] == 1, "retention_start is inclusive"
    gone = api.get_submission(sub_start["id"], make_instructor_headers(instr["id"]))
    validate_error(gone, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_purge_grace_conflict_nothing_purged_aggregate(api):
    """PRD §3.9: "if any candidate owns a deposit in `deposit_state` `STORED`
    whose `stored_at` lies inside the closed grace interval beginning seven days
    before `retention_start` and ending at `retention_end` — both endpoints
    included — the entire run is rejected with `ERR_PURGE_GRACE_CONFLICT`
    (HTTP 409) and nothing is purged."

    Design: Difficulty/resource_temporal_overlap/purge_grace_closed_interval_conflict
    """
    reset_clock("2026-09-01T00:00:00Z")
    inst, integ, instr, student, asg = setup_basic_scenario(
        "US",
        inst_overrides={"repository_participation": "GLOBAL_SHARED"},
        assignment_overrides={"repository_option": "STORE_AND_COMPARE",
                              "due_at": "2027-06-01T00:00:00Z",
                              "max_submissions_per_student": 5},
    )
    reset_clock("2026-09-03T00:00:00Z")
    sub = submit(asg["id"], student["id"], "grace candidate one")
    reset_clock("2026-09-09T00:00:00Z")
    process(sub["id"], instr["id"])  # stored_at 09-09 inside grace [08-25, 09-10]
    policy = validate_success(
        api.create_retention_policy(
            inst["id"],
            {"region": "US", "applies_to": "SUBMISSIONS",
             "retention_start": "2026-09-01T00:00:00Z", "retention_end": "2026-09-10T00:00:00Z"},
            ADMIN,
        ),
        expected_status=201,
    )
    # Purge while the policy is still ACTIVE (clock 09-09 < retention_end
    # 09-10; PRD §3.9: EXPIRED once the logical clock reaches retention_end).
    resp = api.run_purge(policy["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PURGE_GRACE_CONFLICT, expected_status=409)
    # aggregate rejection: the whole run is rejected and nothing is purged
    alive = validate_success(api.get_submission(sub["id"], make_instructor_headers(instr["id"])))
    assert alive["pipeline_state"] == "REPORT_READY"
