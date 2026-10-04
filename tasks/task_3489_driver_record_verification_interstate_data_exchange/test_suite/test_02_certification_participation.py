"""System participation enrollment, certification windows, grants, and the
suspend/restore certification cycle."""

from test_helpers import (
    ASSOCIATION_ADMIN_HEADERS,
    CERTIFICATION_ENGINEER_HEADERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    activate_jurisdiction,
    assert_certification,
    assert_created,
    assert_error,
    certification_completion_payload,
    certification_payload,
    certify_participation,
    complete_certification,
    create_jurisdiction,
    enroll_participation,
    grant_certification,
    list_certifications,
    make_jurisdiction_registrar_headers,
    read_certification,
    read_jurisdiction,
    read_participations,
    schedule_certification,
    setup_certified_jurisdiction,
    suspend_jurisdiction,
)


def test_grant_without_passed_certification_rejected(api):
    """PRD §3.2: "The grant succeeds only when the participation's most recent completed
    certification — the one with the maximum `window_start` among those `PASSED` or
    `FAILED`, ties broken by latest `created_at` — is a `PASSED` one, else
    `ERR_GRANT_REQUIRES_PASSED_CERTIFICATION`"

    Design: Corner/state_machines/grant_without_passed_certification_rejected
    """
    jurisdiction = create_jurisdiction(api, code="AA", name="State A")
    participation = enroll_participation(api, jurisdiction["id"], "POINTER_NETWORK")
    certification = schedule_certification(api, participation["id"])
    complete_certification(api, certification["id"], result="FAILED", score=41)

    resp = api.grant_certification(participation["id"], ASSOCIATION_ADMIN_HEADERS)
    assert_error(resp, ApiErrorId.ERR_GRANT_REQUIRES_PASSED_CERTIFICATION)
    rows, _ = read_participations(api, jurisdiction["id"])
    assert rows[0]["status"] == "TESTING", "a failed grant leaves the machine in place"


def test_certification_complete_outside_window_rejected(api):
    """PRD §3.2: "Completing a certification is only valid while the logical clock sits
    inside the window; an attempt outside it — before `window_start`, or at or after
    `window_end` — is rejected with `ERR_OUTSIDE_TEST_WINDOW`."
    PRD §3.2: "While a certification remains `SCHEDULED`, its `score` and
    `completed_at` stay null."

    Design: Corner/state_machines/certification_complete_outside_window_rejected
    """
    jurisdiction = create_jurisdiction(api, code="AA", name="State A")
    participation = enroll_participation(api, jurisdiction["id"], "POINTER_NETWORK")
    certification = schedule_certification(
        api,
        participation["id"],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-15T00:00:00Z",
    )
    resp = api.complete_certification(
        certification["id"],
        certification_completion_payload("PASSED", 97),
        CERTIFICATION_ENGINEER_HEADERS,
    )
    assert_error(resp, ApiErrorId.ERR_OUTSIDE_TEST_WINDOW)
    current = read_certification(api, certification["id"])
    assert_certification(current)
    assert current["status"] == "SCHEDULED"
    assert current["score"] is None and current["completed_at"] is None


def test_certification_window_end_exact_is_outside(api):
    """PRD §2.9: "Certification test windows are half-open: the lower bound
    `window_start` is inclusive, the upper bound `window_end` is exclusive, so a
    completion attempted at exactly `window_start` is inside the window while one
    attempted at exactly `window_end` is outside it."

    Design: Corner/state_machines/certification_window_end_exact_is_outside
    """
    jurisdiction = create_jurisdiction(api, code="AA", name="State A")
    participation = enroll_participation(api, jurisdiction["id"], "POINTER_NETWORK")
    # The startup clock reads exactly 2026-09-01T00:00:00Z — the window_end below.
    certification = schedule_certification(
        api,
        participation["id"],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-09-01T00:00:00Z",
    )
    resp = api.complete_certification(
        certification["id"],
        certification_completion_payload("PASSED", 97),
        CERTIFICATION_ENGINEER_HEADERS,
    )
    assert_error(resp, ApiErrorId.ERR_OUTSIDE_TEST_WINDOW)


def test_certification_invalid_window_rejected(api):
    """PRD §3.2: "Scheduling a certification takes a `participation_id`, a
    `window_start`, and a `window_end`; the window end must lie strictly after the
    window start, else `ERR_INVALID_WINDOW`."

    Design: Corner/state_machines/certification_invalid_window_rejected
    """
    jurisdiction = create_jurisdiction(api, code="AA", name="State A")
    participation = enroll_participation(api, jurisdiction["id"], "POINTER_NETWORK")
    resp = api.create_certification(
        certification_payload(
            participation["id"],
            "2026-10-01T00:00:00Z",
            "2026-10-01T00:00:00Z",
        ),
        CERTIFICATION_ENGINEER_HEADERS,
    )
    assert_error(resp, ApiErrorId.ERR_INVALID_WINDOW)


def test_certified_systems_count_tracks_grants(api):
    """PRD §3.2: "A successful grant moves the participation `TESTING` → `CERTIFIED`,
    stamps `granted_at` (which remains null until this first grant, just as
    `suspended_at` remains null until a first suspension), and recomputes the
    jurisdiction's `certified_systems_count`."
    PRD §3.2: "The full set of certifications is listable, optionally filtered by
    `participation_id`."

    Design: Corner/calculations/certified_systems_count_tracks_grants
    """
    jurisdiction = create_jurisdiction(api, code="AA", name="State A")
    pointer = enroll_participation(api, jurisdiction["id"], "POINTER_NETWORK")
    certify_participation(api, pointer["id"], score=97)
    title = enroll_participation(api, jurisdiction["id"], "TITLE_NETWORK")
    certify_participation(api, title["id"], score=93)

    current = read_jurisdiction(api, jurisdiction["id"])
    assert current["membership_status"] == "APPLIED", (
        "the count tracks CERTIFIED participations, not membership state"
    )
    assert current["certified_systems_count"] == 2

    rows, meta = list_certifications(api, params={"participation_id": pointer["id"]})
    assert meta["total_count"] == 1 and len(rows) == 1
    assert rows[0]["status"] == "PASSED"


def test_participation_certify_suspend_restore_cycle(api):
    """PRD §2.8: "Link one: every system participation of that jurisdiction currently
    `CERTIFIED` transitions to `SUSPENDED`, its `suspended_at` timestamp is set, and the
    jurisdiction's `certified_systems_count` is recomputed."
    PRD §2.8: "Re-activation runs the recovery in reverse: when the jurisdiction returns
    from `SUSPENDED` to `ACTIVE`, every participation of that jurisdiction sitting in
    `SUSPENDED` that has at least one `PASSED` connection certification transitions back
    to `CERTIFIED`, its `granted_at` refreshed and the certified count recomputed once
    more."

    Design: Difficulty/non_linear_state_machine/participation_certify_suspend_restore_cycle
    """
    ctx = setup_certified_jurisdiction(api, code="AA", systems=("POINTER_NETWORK",))
    jurisdiction_id = ctx["jurisdiction_id"]

    suspend_jurisdiction(api, jurisdiction_id)
    rows, _ = read_participations(api, jurisdiction_id)
    assert rows[0]["status"] == "SUSPENDED", "cascade link 1 drops CERTIFIED participations"

    restored = activate_jurisdiction(api, jurisdiction_id)
    assert restored["certified_systems_count"] == 1, (
        "certified_systems_count went 1 -> 0 -> 1 across the cycle"
    )
    rows, _ = read_participations(api, jurisdiction_id)
    assert rows[0]["status"] == "CERTIFIED", (
        "a PASSED certification exists, so restoration fires on re-activation"
    )


def test_certification_window_half_open_adjacency(api):
    """PRD §2.9: "Two scheduled windows of the same participation may touch — a new
    window starting exactly where an existing one ends is legal adjacency — but any
    positive intersection is rejected."
    PRD §3.2: "Among a participation's `SCHEDULED` certifications, the half-open windows
    of §2.9 must not intersect — adjacency is allowed, and any positive overlap is
    rejected with `ERR_CERT_WINDOW_OVERLAP`."
    PRD §3.2: "the very first scheduling against a participation moves that participation
    from `ENROLLING` to `TESTING`."

    Design: Difficulty/resource_temporal_overlap/certification_window_half_open_adjacency
    """
    jurisdiction = create_jurisdiction(api, code="AA", name="State A")
    participation = enroll_participation(api, jurisdiction["id"], "POINTER_NETWORK")

    resp1 = api.create_certification(
        certification_payload(
            participation["id"], "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z"
        ),
        CERTIFICATION_ENGINEER_HEADERS,
    )
    assert_created(resp1)
    resp2 = api.create_certification(
        certification_payload(
            participation["id"], "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z"
        ),
        CERTIFICATION_ENGINEER_HEADERS,
    )
    assert_created(resp2)
    resp3 = api.create_certification(
        certification_payload(
            participation["id"], "2026-09-30T00:00:00Z", "2026-10-15T00:00:00Z"
        ),
        CERTIFICATION_ENGINEER_HEADERS,
    )
    assert_error(resp3, ApiErrorId.ERR_CERT_WINDOW_OVERLAP)

    rows, _ = read_participations(api, jurisdiction["id"])
    assert rows[0]["status"] == "TESTING", "the first scheduling moved ENROLLING -> TESTING"
    certs, meta = list_certifications(api, params={"participation_id": participation["id"]})
    assert meta["total_count"] == 2 and len(certs) == 2


def test_duplicate_participation_rejected(api):
    """PRD §3.2: "One jurisdiction holds at most one participation per system: a
    duplicate pairing is rejected with `ERR_PARTICIPATION_ALREADY_EXISTS`."

    Design: Corner/errors/duplicate_participation_rejected
    """
    jurisdiction = create_jurisdiction(api, code="AA", name="State A")
    enroll_participation(api, jurisdiction["id"], "POINTER_NETWORK")
    registrar = make_jurisdiction_registrar_headers(jurisdiction["id"])
    resp = api.create_participation(
        {"jurisdiction_id": jurisdiction["id"], "system": "POINTER_NETWORK"},
        registrar,
    )
    assert_error(resp, ApiErrorId.ERR_PARTICIPATION_ALREADY_EXISTS)


def test_grant_unknown_participation_not_found(api):
    """PRD §2.6: "Path identifiers and body foreign keys must reference existing
    resources, validated left to right; the first missing reference yields the
    corresponding not-found error" — here `ERR_PARTICIPATION_NOT_FOUND` (HTTP 404).

    Design: Corner/errors/grant_unknown_participation_not_found
    """
    resp = api.grant_certification(NON_EXISTENT_UUID, ASSOCIATION_ADMIN_HEADERS)
    assert_error(resp, ApiErrorId.ERR_PARTICIPATION_NOT_FOUND)


def test_complete_unknown_certification_not_found(api):
    """PRD §2.6: "Path identifiers and body foreign keys must reference existing
    resources, validated left to right; the first missing reference yields the
    corresponding not-found error" — here `ERR_CERTIFICATION_NOT_FOUND` (HTTP 404).

    Design: Corner/errors/complete_unknown_certification_not_found
    """
    resp = api.complete_certification(
        NON_EXISTENT_UUID,
        certification_completion_payload("PASSED", 90),
        CERTIFICATION_ENGINEER_HEADERS,
    )
    assert_error(resp, ApiErrorId.ERR_CERTIFICATION_NOT_FOUND)


def test_certification_engineer_cannot_grant_certification(api):
    """PRD §2.1: "`CertificationEngineer` runs the connection test suites used during
    onboarding and, by segregation of duties, may never grant certification — the grant
    belongs exclusively to an `AssociationAdmin`."
    PRD §2.1: "a role outside that set is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/certification_engineer_cannot_grant_certification
    """
    jurisdiction = create_jurisdiction(api, code="AA", name="State A")
    participation = enroll_participation(api, jurisdiction["id"], "POINTER_NETWORK")
    certification = schedule_certification(api, participation["id"])
    complete_certification(api, certification["id"], result="PASSED", score=97)

    resp = api.grant_certification(participation["id"], CERTIFICATION_ENGINEER_HEADERS)
    assert_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    rows, _ = read_participations(api, jurisdiction["id"])
    assert rows[0]["status"] == "TESTING"
