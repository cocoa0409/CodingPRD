"""
Two shared resources with opposite interval conventions: authorization windows on
a service line are closed date intervals where touching endpoints collide, while
sessions on a provider's calendar are half-open datetime intervals where touching
endpoints are legal until a change of setting widens them by a travel buffer.
"""

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    assert_authorization_units,
    assert_unit_pool,
    build_active_services,
    create_authorization,
    create_provider,
    factories,
    read_authorization,
    read_service_line,
    schedule_visit,
    validate_error,
    validate_paginated,
    validate_success,
)

PROVIDER = {
    "agency_name": "Riverbend Pediatric Therapies",
    "qualified_service_types": ["SPEECH_THERAPY"],
    "credential_expiry_date": "2027-06-30",
}

# ─── Closed date intervals on a service line ──────────────────────────

APRIL_START = "2026-04-01"
APRIL_END = "2026-04-30"
TOUCHING_START = "2026-04-30"
CLEAR_START = "2026-05-01"
MAY_END = "2026-05-31"


def _build_line_with_april_authorization(api):
    """A live line whose pool has 24 of its 96 units committed to April."""
    case = build_active_services(api)
    case.provider_id = create_provider(api, **PROVIDER)
    case.provider_ids.append(case.provider_id)
    case.authorization_id = create_authorization(
        api,
        case.line_id,
        case.provider_id,
        start_date=APRIL_START,
        end_date=APRIL_END,
        authorized_units=24,
    )
    case.authorization_ids.append(case.authorization_id)
    return case


def _request_window(api, line_id, provider_id, start_date):
    return api.create_authorization(
        factories.authorization_payload(
            line_id,
            provider_id,
            start_date=start_date,
            end_date=MAY_END,
            authorized_units=12,
        ),
        ADMIN_HEADERS,
    )


class TestAuthorizationWindowsAreClosedIntervals:
    """A window starting on the day another ends is a collision."""

    def test_window_starting_on_the_existing_end_date_collides(self, api):
        """
        A second window whose first day is the existing window's last day is
        refused, and the line's pool is left exactly where it was.

        PRD 3.6: "The practical consequence is that windows may not even touch: a
        new window starting exactly on an existing window's end date conflicts,
        while one starting a single day later does not."

        Design: Difficulty/resource_temporal_overlap/authorization_window_closed_interval_touching_endpoints_collide
        """
        case = _build_line_with_april_authorization(api)

        response = _request_window(
            api, case.line_id, case.provider_id, TOUCHING_START
        )
        validate_error(response, ApiErrorId.AUTHORIZATION_WINDOW_OVERLAP.value, 409)

        line = read_service_line(api, case.line_id)
        assert_unit_pool(
            line, units_committed=24, units_pool_remaining=72, planned_units_total=96
        )

    def test_window_starting_one_day_later_is_admitted_and_commits_units(self, api):
        """
        Moving the same request's start one day clear admits it, and the second
        window's units come out of the line's remaining pool.

        PRD 2.10: "A line's `units_committed` plus its `units_pool_remaining`
        always equals its `planned_units_total`, and `units_pool_remaining` is
        always between 0 and `planned_units_total` inclusive."

        Design: Difficulty/resource_temporal_overlap/authorization_window_closed_interval_touching_endpoints_collide
        """
        case = _build_line_with_april_authorization(api)

        second = validate_success(
            _request_window(api, case.line_id, case.provider_id, CLEAR_START), 201
        )
        assert second["start_date"] == CLEAR_START
        assert second["end_date"] == MAY_END
        assert second["status"] == "ACTIVE"
        assert_authorization_units(second, units_consumed=0, units_remaining=12)

        line = read_service_line(api, case.line_id)
        assert_unit_pool(
            line, units_committed=36, units_pool_remaining=60, planned_units_total=96
        )

        # The April window is untouched by the May one.
        first = read_authorization(api, case.authorization_id)
        assert first["status"] == "ACTIVE"
        assert_authorization_units(first, units_remaining=24)


# ─── Half-open datetime intervals on a provider's calendar ────────────

VISIT_DAY = "2026-03-23"
FIRST_SESSION = (f"{VISIT_DAY}T09:00:00Z", f"{VISIT_DAY}T09:30:00Z")
ADJACENT_SESSION = (f"{VISIT_DAY}T09:30:00Z", f"{VISIT_DAY}T10:00:00Z")
BUFFER_VIOLATING_SESSION = (f"{VISIT_DAY}T10:00:00Z", f"{VISIT_DAY}T10:30:00Z")
# One full 30-minute travel buffer clear of the adjacent home session's 10:00Z end.
BUFFER_CLEAR_SESSION = (f"{VISIT_DAY}T10:30:00Z", f"{VISIT_DAY}T11:00:00Z")


def _build_provider_with_one_session(api):
    """One provider holding a single half-hour home session on the calendar."""
    case = build_active_services(api)
    case.provider_id = create_provider(api, **PROVIDER)
    case.provider_ids.append(case.provider_id)
    case.authorization_id = create_authorization(
        api,
        case.line_id,
        case.provider_id,
        start_date="2026-03-21",
        end_date="2026-04-30",
        authorized_units=24,
    )
    case.authorization_ids.append(case.authorization_id)
    case.visit_id = schedule_visit(
        api, case.authorization_id, *FIRST_SESSION, setting_code="HOME"
    )
    case.visit_ids.append(case.visit_id)
    return case


def _request_session(api, authorization_id, window, setting_code):
    start, end = window
    return api.create_visit(
        factories.visit_payload(
            authorization_id, start, end, setting_code=setting_code
        ),
        ADMIN_HEADERS,
    )


class TestProviderCalendarIsHalfOpenWithATravelBuffer:
    """Touching is legal in the same setting and illegal across settings."""

    def test_same_setting_session_may_start_when_the_previous_one_ends(self, api):
        """
        A home session beginning at the instant the previous home session ends is
        accepted, because the interval excludes its own end.

        PRD 3.7: "When the two sessions share the same `setting_code`, no buffer
        is applied and the comparison is the plain half-open one, so two
        same-setting sessions may touch exactly: 09:00–09:30 followed by
        09:30–10:00 is legal."

        Design: Difficulty/resource_temporal_overlap/provider_visit_half_open_adjacency_allowed_but_cross_setting_buffer_conflicts
        """
        case = _build_provider_with_one_session(api)

        adjacent = validate_success(
            _request_session(api, case.authorization_id, ADJACENT_SESSION, "HOME"), 201
        )
        assert adjacent["visit_status"] == "SCHEDULED"
        assert adjacent["billing_status"] == "PENDING"
        assert adjacent["scheduled_units"] == 2

        # Scheduling never draws on the authorization.
        assert_authorization_units(
            read_authorization(api, case.authorization_id),
            units_consumed=0,
            units_remaining=24,
        )
        line = read_service_line(api, case.line_id)
        assert_unit_pool(
            line, units_committed=24, units_pool_remaining=72, planned_units_total=96
        )
        assert line["units_delivered"] == 0

    def test_cross_setting_session_needs_a_full_buffer_of_clearance(self, api):
        """
        A clinic session beginning at the instant a home session ends is refused
        for want of travel time, while one starting a full buffer later fits.

        PRD 3.7: "When the two sessions have different `setting_code` values, a
        travel buffer of 30 minutes is applied, and the sessions conflict when the
        new start falls before the existing end extended by the buffer **and** the
        existing start falls before the new end extended by the buffer."

        Design: Difficulty/resource_temporal_overlap/provider_visit_half_open_adjacency_allowed_but_cross_setting_buffer_conflicts
        """
        case = _build_provider_with_one_session(api)
        adjacent = validate_success(
            _request_session(api, case.authorization_id, ADJACENT_SESSION, "HOME"), 201
        )

        blocked = _request_session(
            api, case.authorization_id, BUFFER_VIOLATING_SESSION, "CLINIC"
        )
        validate_error(blocked, ApiErrorId.PROVIDER_SCHEDULE_CONFLICT.value, 409)

        clear = validate_success(
            _request_session(
                api, case.authorization_id, BUFFER_CLEAR_SESSION, "CLINIC"
            ),
            201,
        )
        assert clear["setting_code"] == "CLINIC"
        assert clear["scheduled_units"] == 2

        rows, _meta = validate_paginated(
            api.list_visits(
                ADMIN_HEADERS,
                {"provider_authorization_id": case.authorization_id},
            )
        )
        assert len(rows) == 3
        assert {row["id"] for row in rows} == {
            case.visit_id,
            adjacent["id"],
            clear["id"],
        }
