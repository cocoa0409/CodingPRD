"""Corner queue — window lifecycle under the logical clock.

Initial state, single-mutation sweeps, terminal-state lockdowns, OCC version
discipline and sweep idempotency (PRD §2.4, §3.3).
"""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    CLOCK_DEFAULT,
    CLOCK_REGISTRATION_CLOSED,
    CLOCK_REGISTRATION_OPEN,
    CLOCK_SCORING,
    CLOCK_TESTING_STARTS,
    FEE_EARLY_CENTS,
    REGISTRAR,
    create_exam_registration_payload,
    get_success_data,
    get_window,
    make_active_exam,
    make_candidate,
    make_candidate_headers,
    make_window,
    register,
    set_clock,
    setup_open_window,
    setup_published_window,
    validate_error,
)


def _utc(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def test_window_initial_state_scheduled(api):
    """PRD §3.3: "Once scheduled, a window's lifecycle is driven entirely by
    the logical clock sweep described in §2.4. A `SCHEDULED` window becomes
    `REGISTRATION_OPEN` once the clock reaches `registration_opens_at`."

    Design: Corner/state_machines/window_initial_state_scheduled
    """
    _, exam = make_active_exam(api)
    # registration_opens_at equals the default clock reading, but no sweep has
    # run: sweeps happen only on clock-set calls.
    window = make_window(api, exam["id"], window_code="P-2026-10",
                         registration_opens_at=CLOCK_DEFAULT)
    assert window["status"] == "SCHEDULED"


def test_window_full_sweep_single_mutation(api):
    """PRD §2.4: "Every examination window whose thresholds have passed
    advances directly to its furthest due status — passing through all
    intermediate states whose thresholds have passed — and its `version`
    increments once per window per sweep, not once per state crossed."
    PRD §2.4: "A window reaching `SCORING` in a sweep marks each of its
    `REGISTERED` registrations as `SAT` in the same sweep."

    Design: Corner/state_machines/window_full_sweep_single_mutation
    """
    ctx = setup_open_window(api)
    candidate = make_candidate(api)
    registration = register(api, ctx["window"]["id"], candidate)
    before = get_window(api, ctx["window"]["id"])
    assert before["status"] == "REGISTRATION_OPEN"

    sweep = set_clock(api, CLOCK_SCORING)
    assert sweep["windows_advanced"] == 1
    assert sweep["registrations_marked_sat"] == 1

    after = get_window(api, ctx["window"]["id"])
    # REGISTRATION_OPEN -> SCORING in one mutation: exactly one version bump.
    assert after["status"] == "SCORING"
    assert after["version"] == before["version"] + 1

    rows = get_success_data(api.list_candidate_registrations(candidate["id"], REGISTRAR))
    assert rows[0]["id"] == registration["id"]
    assert rows[0]["logistics_status"] == "SAT"
    assert _utc(rows[0]["sat_at"]) == _utc(CLOCK_SCORING)


def test_registration_after_publish_rejected(api):
    """PRD §3.3: "The window must be `REGISTRATION_OPEN` — a registration
    against a window in any other status, including the exact-deadline
    boundary above, is rejected with `ERR_WINDOW_NOT_OPEN`."
    PRD §3.3: "A window ends in one of two terminal states:
    `RESULTS_PUBLISHED`, reached when the committee publishes the ratified
    pass mark, or `CANCELLED`."

    Design: Corner/state_machines/registration_after_publish_rejected
    """
    ctx = setup_published_window(api)
    assert ctx["window"]["status"] == "RESULTS_PUBLISHED"
    newcomer = make_candidate(api)
    resp = api.create_exam_registration(
        create_exam_registration_payload(ctx["window"]["id"]),
        make_candidate_headers(newcomer["id"]))
    validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_OPEN)


def test_registration_cancel_after_release_rejected(api):
    """PRD §3.3: "A registration can be cancelled by the owning candidate or
    by a `Registrar`, but only while its `logistics_status` is `REGISTERED` or
    `WAITLISTED`, its `grading_status` is still `PENDING`, and its window is
    `REGISTRATION_OPEN` or `REGISTRATION_CLOSED`; any other combination is
    rejected with `ERR_REGISTRATION_NOT_CANCELLABLE`."

    Design: Corner/state_machines/registration_cancel_after_release_rejected
    """
    ctx = setup_published_window(api)
    candidate = ctx["candidates"][0]
    registration = ctx["registrations"][0]
    resp = api.cancel_exam_registration(
        registration["id"], make_candidate_headers(candidate["id"]))
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_NOT_CANCELLABLE)

    rows = get_success_data(api.list_candidate_registrations(candidate["id"], REGISTRAR))
    assert rows[0]["logistics_status"] == "SAT"
    assert rows[0]["grading_status"] == "RELEASED"
    assert rows[0]["result"] == "PASS"


def test_immediate_consistency_read_after_write(api):
    """PRD §3.3: "`seats_held` is the count of its registrations whose
    `logistics_status` is `REGISTERED` and is kept equal to that count at all
    times."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/consistency_model/immediate_consistency_read_after_write
    """
    ctx = setup_open_window(api)
    candidate = make_candidate(api)
    registration = register(api, ctx["window"]["id"], candidate)
    # The creation response itself already carries the computed fee.
    assert registration["fee_charged_cents"] == FEE_EARLY_CENTS
    window = get_window(api, ctx["window"]["id"])
    assert window["seats_held"] == 1
    assert window["waitlist_count"] == 0


def test_occ_version_increments_once_per_mutation(api):
    """PRD §2.4: "its `version` increments once per window per sweep, not once
    per state crossed."
    PRD §2.5: "`version` (integer): a system-managed integer that increments
    with every modification to the resource, including modifications performed
    by automatic cascades, sweeps, and bubble-up reconciliations."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_once_per_mutation
    """
    _, exam = make_active_exam(api)
    window = make_window(api, exam["id"], window_code="P-2026-10")
    version = window["version"]
    for clock, expected_status in (
        (CLOCK_REGISTRATION_OPEN, "REGISTRATION_OPEN"),
        (CLOCK_REGISTRATION_CLOSED, "REGISTRATION_CLOSED"),
        (CLOCK_TESTING_STARTS, "TESTING"),
        (CLOCK_SCORING, "SCORING"),
    ):
        set_clock(api, clock)
        window = get_window(api, window["id"])
        assert window["status"] == expected_status
        assert window["version"] == version + 1
        version = window["version"]


def test_ops_run_sweep_idempotent_same_timestamp(api):
    """PRD §2.4: "A set call that changes nothing performs no mutations at
    all: no `version` changes and all four counters report zero."
    PRD §2.4: "The clock-set response reports the new `current_utc` together
    with the counters `windows_advanced`, `registrations_marked_sat`,
    `sessions_held`, and `suspensions_lifted`."

    Design: Corner/cross_cutting_complexity_layers/ops_run_sweep_idempotent_same_timestamp
    """
    ctx = setup_open_window(api)
    candidate = make_candidate(api)
    register(api, ctx["window"]["id"], candidate)
    set_clock(api, CLOCK_SCORING)
    before = get_window(api, ctx["window"]["id"])

    sweep = set_clock(api, CLOCK_SCORING)
    assert _utc(sweep["current_utc"]) == _utc(CLOCK_SCORING)
    assert sweep["windows_advanced"] == 0
    assert sweep["registrations_marked_sat"] == 0
    assert sweep["sessions_held"] == 0
    assert sweep["suspensions_lifted"] == 0

    after = get_window(api, ctx["window"]["id"])
    assert after["version"] == before["version"]
    assert after["status"] == before["status"]
