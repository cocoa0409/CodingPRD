"""Volunteer vetting: screening claim/decide protocol, segregation of
duties, optimistic concurrency on screening intake, volunteer status
gating assignment, and assignment listing filters."""
from test_helpers import (
    ApiClient,
    ApiErrorId,
    MANAGER_1_USER_ID,
    MANAGER_2_USER_ID,
    MANAGER_3_USER_ID,
    TEST_USERS,
    assert_shift_assignment,
    assign_volunteer,
    claim_screening,
    create_center,
    create_center_with_active_agreement,
    create_cleared_volunteer,
    create_shift,
    create_volunteer,
    decide_screening,
    get_volunteer,
    make_manager_headers,
    open_screening,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

MGR = TEST_USERS["manager_headers"]


def test_screening_double_claim_rejected(api: ApiClient):
    """PRD §3.2: "Review is a two-person protocol. A `CenterManager` first claims a `SUBMITTED` screening, moving it to `IN_REVIEW` and recording the caller's `X-User-ID` in `claimed_by_user_id`; claiming a screening that is not `SUBMITTED` is a plain `ERR_INVALID_STATE`."

    Design: Corner/state_machines/screening_double_claim_rejected
    """
    set_clock()
    center = create_center(
        name="Chi Center",
        airport_code="OAK",
        occupancy_cap=25,
        required_daily_confirmed_assignments=1,
    )
    volunteer = create_volunteer(center["id"], full_name="V Claim")
    screening = open_screening(volunteer["id"], volunteer["version"])
    claim_screening(screening["id"], manager_user_id=MANAGER_1_USER_ID)

    resp = api.claim_screening(
        screening["id"], make_manager_headers(MANAGER_3_USER_ID)
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    rows, _meta = validate_paginated(api.list_screenings(volunteer["id"], MGR))
    assert len(rows) == 1
    assert rows[0]["status"] == "IN_REVIEW"
    assert rows[0]["claimed_by_user_id"] == MANAGER_1_USER_ID, (
        "a rejected second claim must not overwrite claimed_by_user_id, "
        f"got {rows[0]['claimed_by_user_id']!r}"
    )


def test_screening_decide_before_claim_rejected(api: ApiClient):
    """PRD §3.2: "A decision is then taken on the `IN_REVIEW` screening by supplying a `verdict` of `CLEARED` or `REJECTED` — but segregation of duties forbids the decider from being the claimer: when the caller's `X-User-ID` equals the screening's `claimed_by_user_id`, the decision is rejected with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §2.7: "Only then do business rules run, in this relative order: state admissibility — the target entity must be in a from-state its transition allows, covering `ERR_INVALID_STATE`, `ERR_CENTER_CLOSED`, `ERR_ALREADY_CHECKED_IN`, `ERR_SCREENING_ALREADY_OPEN`, and `ERR_RENEWAL_WINDOW_NOT_OPEN`"

    Design: Corner/state_machines/screening_decide_before_claim_rejected
    """
    set_clock()
    center = create_center(
        name="Psi Center",
        airport_code="SMF",
        occupancy_cap=25,
        required_daily_confirmed_assignments=1,
    )
    volunteer = create_volunteer(center["id"], full_name="V Early")
    screening = open_screening(volunteer["id"], volunteer["version"])
    assert screening["status"] == "SUBMITTED"

    resp = api.decide_screening(
        screening["id"],
        {"verdict": "CLEARED"},
        make_manager_headers(MANAGER_2_USER_ID),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    rows, _meta = validate_paginated(api.list_screenings(volunteer["id"], MGR))
    assert rows[0]["status"] == "SUBMITTED", (
        "a decision on a never-claimed screening must leave it SUBMITTED, "
        f"got {rows[0]['status']!r}"
    )


def test_screening_segregation_of_duties_enforced(api: ApiClient):
    """PRD §3.2: "A decision is then taken on the `IN_REVIEW` screening by supplying a `verdict` of `CLEARED` or `REJECTED` — but segregation of duties forbids the decider from being the claimer: when the caller's `X-User-ID` equals the screening's `claimed_by_user_id`, the decision is rejected with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.2: "The decider's `X-User-ID` is recorded in `decided_by_user_id`. A `CLEARED` verdict stamps `expires_at` at exactly 24 months after the decision time and moves the linked volunteer from `SCREENING` to `CLEARED`; a `REJECTED` verdict sends the volunteer back to `APPLIED`, making the apply–screen–reject loop cyclic."

    Design: Corner/rbac/screening_segregation_of_duties_enforced
    """
    set_clock()
    center = create_center(
        name="Qoph Center",
        airport_code="RNO",
        occupancy_cap=10,
        required_daily_confirmed_assignments=1,
    )
    volunteer = create_volunteer(center["id"], full_name="V Seg")
    screening = open_screening(volunteer["id"], volunteer["version"])
    claim_screening(screening["id"], manager_user_id=MANAGER_1_USER_ID)

    same_manager = api.decide_screening(
        screening["id"],
        {"verdict": "CLEARED"},
        make_manager_headers(MANAGER_1_USER_ID),
    )
    validate_error(same_manager, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    decided = decide_screening(
        screening["id"], "CLEARED", decider_user_id=MANAGER_2_USER_ID
    )
    assert decided["status"] == "CLEARED"
    assert decided["claimed_by_user_id"] == MANAGER_1_USER_ID
    assert decided["decided_by_user_id"] == MANAGER_2_USER_ID
    assert decided["expires_at"] is not None, (
        "a CLEARED verdict stamps expires_at 24 months after the decision time"
    )
    volunteer_after = get_volunteer(volunteer["id"])
    assert volunteer_after["status"] == "CLEARED", (
        f"the linked volunteer moves SCREENING -> CLEARED, got "
        f"{volunteer_after['status']!r}"
    )


def test_occ_screening_create_stale_version(api: ApiClient):
    """PRD §2.5: "Opening a background screening for a volunteer requires `expected_volunteer_version` matching that volunteer's current `version`, because a new screening legitimately supersedes the client's view of the volunteer's vetting state."
    PRD §2.7: "Fifth, optimistic concurrency: a stale expected-version field yields `ERR_STALE_VERSION`."
    PRD §3.2: "A volunteer who already has an open screening — one `SUBMITTED` or `IN_REVIEW`, which is exactly the `SCREENING` state — cannot be re-opened: the attempt fails with `ERR_SCREENING_ALREADY_OPEN`."

    Design: Corner/complexity_layers/occ_screening_create_stale_version
    """
    set_clock()
    center = create_center(
        name="Tav Center",
        airport_code="LBB",
        occupancy_cap=10,
        required_daily_confirmed_assignments=1,
    )
    volunteer = create_volunteer(center["id"], full_name="V Occ")
    open_screening(volunteer["id"], volunteer["version"])

    # Opening the screening bumped the volunteer's version, so replaying
    # the pre-open version is stale (OCC fires before the state check).
    stale = api.create_screening(
        volunteer["id"],
        {"expected_volunteer_version": volunteer["version"]},
        MGR,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    fresh = get_volunteer(volunteer["id"])
    duplicate = api.create_screening(
        volunteer["id"],
        {"expected_volunteer_version": fresh["version"]},
        MGR,
    )
    validate_error(duplicate, ApiErrorId.ERR_SCREENING_ALREADY_OPEN)


def test_volunteer_status_gates_assignment(api: ApiClient):
    """PRD §3.3: "The manager supplies a `volunteer_id`; the volunteer must be `CLEARED` or `ACTIVE` (`ERR_VOLUNTEER_NOT_ELIGIBLE` otherwise), and the new shift must not collide with the volunteer's existing commitments."

    Design: Difficulty/cross_entity_state_dependency/volunteer_status_gates_assignment
    """
    set_clock()
    center, _agreement = create_center_with_active_agreement(
        center_overrides={
            "name": "Nu Center",
            "airport_code": "STL",
            "occupancy_cap": 30,
            "required_daily_confirmed_assignments": 2,
        }
    )
    volunteer = create_volunteer(center["id"], full_name="V Gate")
    assert volunteer["status"] == "APPLIED"
    shift = create_shift(
        center["id"],
        start_at="2026-09-02T08:00:00Z",
        end_at="2026-09-02T12:00:00Z",
        role_required="DESK",
        capacity=2,
    )

    denied = api.create_assignment(
        shift["id"], {"volunteer_id": volunteer["id"]}, MGR
    )
    validate_error(denied, ApiErrorId.ERR_VOLUNTEER_NOT_ELIGIBLE)

    screening = open_screening(volunteer["id"], volunteer["version"])
    claim_screening(screening["id"])
    decide_screening(screening["id"], "CLEARED")

    accepted = api.create_assignment(
        shift["id"], {"volunteer_id": volunteer["id"]}, MGR
    )
    assignment = validate_success(accepted, 201)
    assert_shift_assignment(assignment)
    assert assignment["status"] == "ASSIGNED", (
        "the identical request succeeds once the volunteer is CLEARED, "
        f"got {assignment['status']!r}"
    )


def test_shift_assignments_filtered_by_volunteer(api: ApiClient):
    """PRD §3.3: "Assignments can be listed filtered by `shift_id` and/or `volunteer_id`; a `Volunteer` caller is scoped to its own identity, and passing any other `volunteer_id` is rejected with `ERR_FORBIDDEN`."

    Design: Corner/entities/shift_assignments_filtered_by_volunteer
    """
    set_clock()
    center, _agreement = create_center_with_active_agreement(
        center_overrides={
            "name": "Phi Center",
            "airport_code": "MCI",
            "occupancy_cap": 25,
            "required_daily_confirmed_assignments": 2,
        }
    )
    v1 = create_cleared_volunteer(center["id"], full_name="V One")
    v2 = create_cleared_volunteer(center["id"], full_name="V Two")
    shift = create_shift(
        center["id"],
        start_at="2026-09-03T08:00:00Z",
        end_at="2026-09-03T12:00:00Z",
        role_required="DESK",
        capacity=2,
    )
    a1 = assign_volunteer(shift["id"], v1["id"])
    a2 = assign_volunteer(shift["id"], v2["id"])

    rows, meta = validate_paginated(
        api.list_assignments(MGR, params={"volunteer_id": v1["id"]})
    )
    assert len(rows) == 1, (
        f"the volunteer_id filter must return exactly that volunteer's "
        f"rows, got {len(rows)}"
    )
    assert rows[0]["id"] == a1["id"]
    assert all(row["volunteer_id"] == v1["id"] for row in rows)
    assert a2["id"] not in [row["id"] for row in rows]
