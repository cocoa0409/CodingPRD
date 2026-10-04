"""Appointments: scheduling-responsibility split, provider ownership on
completion, terminal completion, half-open slot collision arithmetic, the
half-open episode window, validation-pipeline precedence, and the timeliness
anchor variants."""
from test_helpers import (
    TEST_USERS, api_client, validate_error, validate_paginated,
    authorize_referral, create_appointment_payload, create_station, create_tpa,
    get_appointment, list_appointments, make_provider_rep_headers,
    make_tpa_admin_headers, onboard_provider, schedule_appointment, set_clock,
    setup_episode, setup_episode_with_completed_appointments,
)

COORD = TEST_USERS["care_coordinator_headers"]


def test_scheduler_role_must_match_scheduling_responsibility():
    """PRD §3.5: "When it is `TPA`, only a `TPAAdministrator` who owns the
    authorization's `tpa_id` may schedule; when it is `VAMC`, only a
    `CareCoordinator` may."
    PRD §3.5: "A caller whose role or network does not match that
    responsibility is rejected with `ERR_OWNERSHIP_MISMATCH`."

    Design: Corner/validations/scheduler_role_must_match_scheduling_responsibility
    """
    station = create_station()
    tpa = create_tpa()
    env_t = setup_episode(station=station, tpa=tpa, scheduling="TPA")
    env_v = setup_episode(station=station, tpa=tpa, scheduling="VAMC")
    auth_t = env_t["authorization"]
    auth_v = env_v["authorization"]

    # CareCoordinator on a TPA-responsible episode.
    resp_t = api_client.create_appointment(
        auth_t["id"], create_appointment_payload(), COORD
    )
    validate_error(resp_t, "ERR_OWNERSHIP_MISMATCH")

    # TPAAdministrator (even the owning network) on a VAMC-responsible episode.
    resp_v = api_client.create_appointment(
        auth_v["id"], create_appointment_payload(),
        make_tpa_admin_headers(auth_v["tpa_id"]),
    )
    validate_error(resp_v, "ERR_OWNERSHIP_MISMATCH")

    # CareCoordinator on the VAMC-responsible episode succeeds.
    appt = schedule_appointment(auth_v)
    assert appt["status"] == "SCHEDULED"


def test_provider_cannot_complete_others_appointment():
    """PRD §3.5: "A `ProviderRep` completes one of their own appointments — the
    caller's identity must equal the appointment's `provider_id`, else
    `ERR_OWNERSHIP_MISMATCH`, and only a `SCHEDULED` appointment can complete,
    else `ERR_INVALID_STATE`."

    Design: Corner/validations/provider_cannot_complete_others_appointment
    """
    env = setup_episode()
    auth = env["authorization"]
    other = onboard_provider(env["tpa"], name="Prov Two",
                             latitude=40.2, longitude=-75.2)
    appt = schedule_appointment(auth)

    resp = api_client.complete_appointment(
        appt["id"], make_provider_rep_headers(other["id"])
    )
    validate_error(resp, "ERR_OWNERSHIP_MISMATCH")
    assert get_appointment(appt["id"])["status"] == "SCHEDULED"


def test_appointment_complete_twice_returns_invalid_state():
    """PRD §3.5: "A `ProviderRep` completes one of their own appointments — the
    caller's identity must equal the appointment's `provider_id`, else
    `ERR_OWNERSHIP_MISMATCH`, and only a `SCHEDULED` appointment can complete,
    else `ERR_INVALID_STATE`."
    PRD §3.6: "Every completed appointment creates exactly one **medical
    documentation** record, born `AWAITED` with its
    `referral_authorization_id` copied from the appointment as a read cache and
    its `deadline_at` set to the completion timestamp plus 30 days."

    Design: Corner/state_machines/appointment_complete_twice_returns_invalid_state
    """
    env = setup_episode_with_completed_appointments(num_appointments=1,
                                                    authorized_visits=2)
    appt = env["appointments"][0]

    resp = api_client.complete_appointment(
        appt["id"], make_provider_rep_headers(env["provider"]["id"])
    )
    validate_error(resp, "ERR_INVALID_STATE")

    docs, meta = validate_paginated(
        api_client.get_documentation(appt["id"], COORD)
    )
    assert meta["total_count"] == 1 and len(docs) == 1


def test_provider_slot_half_open_adjacency_allowed_overlap_rejected():
    """PRD §3.5: "And the provider's diary must be free: each appointment
    occupies the half-open slot from its `scheduled_start` through the
    following 60 minutes, so a booking that overlaps any of the provider's
    other `SCHEDULED` appointments' 60-minute slots is rejected with
    `ERR_APPOINTMENT_SLOT_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/provider_slot_half_open_adjacency_allowed_overlap_rejected
    """
    env = setup_episode(authorized_visits=3, duration_days=60)
    auth = env["authorization"]

    ap1 = schedule_appointment(auth, scheduled_start="2026-09-06T10:00:00Z")
    ap2 = schedule_appointment(auth, scheduled_start="2026-09-06T11:00:00Z")
    assert ap1["status"] == "SCHEDULED" and ap2["status"] == "SCHEDULED"

    # [10:00, 11:00) and [11:00, 12:00) touch without overlapping; 10:30
    # collides with the first slot.
    resp = api_client.create_appointment(
        auth["id"],
        create_appointment_payload(scheduled_start="2026-09-06T10:30:00Z"),
        make_tpa_admin_headers(auth["tpa_id"]),
    )
    validate_error(resp, "ERR_APPOINTMENT_SLOT_CONFLICT")

    _items, meta = list_appointments(auth["id"])
    assert meta["total_count"] == 2


def test_episode_end_day_is_excluded_half_open():
    """PRD §2.7: "Calendar arithmetic (episode windows, filing windows,
    timeliness lags) operates on whole calendar dates, and every window in this
    contract is half-open: the start date is included, the end date is
    excluded."
    PRD §2.8: "an appointment's scheduled date must lie inside the episode
    window (else `ERR_AUTH_WINDOW_VIOLATION`)"

    Design: Corner/calculations/episode_end_day_is_excluded_half_open
    """
    env = setup_episode(authorized_visits=2, duration_days=30)
    auth = env["authorization"]  # window [2026-09-05, 2026-10-05)

    ok = schedule_appointment(auth, scheduled_start="2026-10-04T10:00:00Z")
    assert ok["status"] == "SCHEDULED"

    resp = api_client.create_appointment(
        auth["id"],
        create_appointment_payload(scheduled_start="2026-10-05T10:00:00Z"),
        make_tpa_admin_headers(auth["tpa_id"]),
    )
    validate_error(resp, "ERR_AUTH_WINDOW_VIOLATION")


def test_appointment_window_error_beats_no_visits_remaining():
    """PRD §2.8: "Stages are evaluated in the order below, and the first
    failing stage produces the response — an earlier failure masks all later
    checks, so the error a caller receives always identifies the earliest
    unmet obligation:"
    PRD §2.8: "an appointment's scheduled date must lie inside the episode
    window (else `ERR_AUTH_WINDOW_VIOLATION`)"
    PRD §2.8: "scheduling with no visits remaining is rejected with
    `ERR_NO_VISITS_REMAINING`"

    Design: Difficulty/priority_pair_validation_conflict/appointment_window_error_beats_no_visits_remaining
    """
    env = setup_episode(authorized_visits=1, duration_days=30)
    auth = env["authorization"]
    schedule_appointment(auth)  # remaining_visits now 0

    # Both temporal (outside [2026-09-05, 2026-10-05)) and constraint
    # (remaining_visits == 0) fail; the earlier temporal stage wins.
    resp = api_client.create_appointment(
        auth["id"],
        create_appointment_payload(scheduled_start="2026-10-06T10:00:00Z"),
        make_tpa_admin_headers(auth["tpa_id"]),
    )
    validate_error(resp, "ERR_AUTH_WINDOW_VIOLATION")

    _items, meta = list_appointments(auth["id"])
    assert meta["total_count"] == 1


def test_appointment_timeliness_anchor_differs_by_scheduling_responsibility():
    """PRD §3.5: "Timeliness is measured against an anchor that follows the
    scheduling split: `timeliness_anchor` is `AUTHORIZED_AT` when the
    administrator schedules and `REQUESTED_DATE` when the health system
    schedules, and `within_standard` is true exactly when the number of
    calendar days from the anchor date (the date part of `authorized_at`, or
    the `requested_date`) to the date of `scheduled_start` is at most 5 days —
    the comparison is inclusive, and a negative lag counts as within standard."

    Design: Corner/calculations/appointment_timeliness_anchor_differs_by_scheduling_responsibility
    """
    station = create_station()
    tpa = create_tpa()
    env_t = setup_episode(station=station, tpa=tpa, scheduling="TPA",
                          authorize=False)
    env_v = setup_episode(station=station, tpa=tpa, scheduling="VAMC",
                          authorize=False)

    # Both episodes are authorized at the same known clock instant.
    set_clock("2026-09-05T00:00:00Z")
    auth_t = authorize_referral(env_t["authorization"])
    auth_v = authorize_referral(env_v["authorization"])

    # Identical scheduled_start and requested_date on both episodes.
    ap_t = schedule_appointment(auth_t, scheduled_start="2026-09-09T10:00:00Z",
                                requested_date="2026-09-01")
    ap_v = schedule_appointment(auth_v, scheduled_start="2026-09-09T10:00:00Z",
                                requested_date="2026-09-01")

    # TPA side: anchored at authorized_at 2026-09-05, lag 4 <= 5.
    assert ap_t["timeliness_anchor"] == "AUTHORIZED_AT"
    assert ap_t["within_standard"] is True
    # VAMC side: anchored at requested_date 2026-09-01, lag 8 > 5.
    assert ap_v["timeliness_anchor"] == "REQUESTED_DATE"
    assert ap_v["within_standard"] is False
