"""
Two defects in one request, and only one error identifier comes back. Each pair
sends a body that violates a late rung of the checking order against a row that
also violates an earlier rung, and pins which rung reports.
"""

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    assert_unit_pool,
    build_active_services,
    create_authorization,
    create_provider,
    document_visit,
    factories,
    read_authorization,
    read_service_line,
    schedule_visit,
    set_clock,
    validate_error,
    validate_paginated,
)

DOCUMENT_CLOCK = "2026-03-24T12:00:00Z"

# The same body for both attempts: five units against a two-unit session.
OVERSIZED_DOCUMENTATION = {
    "visit_status": "DELIVERED",
    "actual_units": 5,
    "actual_start": "2026-03-23T09:00:00Z",
    "actual_end": "2026-03-23T10:15:00Z",
    "session_note": "Session delivered with extended parent coaching time.",
}


def _build_one_delivered_one_scheduled(api):
    """One authorization carrying a documented session and a session still on
    the books, both of them two units long."""
    case = build_active_services(api)
    case.provider_id = create_provider(api)
    case.provider_ids.append(case.provider_id)
    case.authorization_id = create_authorization(api, case.line_id, case.provider_id)
    case.authorization_ids.append(case.authorization_id)
    for start, end in (
        ("2026-03-23T09:00:00Z", "2026-03-23T09:30:00Z"),
        ("2026-03-24T09:00:00Z", "2026-03-24T09:30:00Z"),
    ):
        case.visit_ids.append(schedule_visit(api, case.authorization_id, start, end))
    set_clock(api, DOCUMENT_CLOCK)
    case.clock = DOCUMENT_CLOCK
    document_visit(
        api,
        case.visit_ids[0],
        case.provider_id,
        visit_status="DELIVERED",
        actual_units=2,
        actual_start="2026-03-23T09:00:00Z",
        actual_end="2026-03-23T09:30:00Z",
    )
    return case


class TestStateReportsBeforeUnitCapacity:
    """One body, two target rows, two different verdicts."""

    def test_already_documented_session_reports_the_state_defect(self, api):
        """
        Re-documenting a session that has already been delivered reports the
        state precondition, even though the body's unit count is independently
        impossible.

        PRD 2.8: "The practical consequence worth internalising is that identity
        and shape come before existence, existence before ownership, ownership
        before concurrency, concurrency before state, state before regulatory
        safety, safety before referential integrity, referential integrity
        before constraints, constraints before dates, and dates before capacity
        and money."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_visit_document
        """
        case = _build_one_delivered_one_scheduled(api)

        response = api.document_visit(
            case.visit_ids[0], dict(OVERSIZED_DOCUMENTATION), case.provider_headers
        )
        validate_error(response, ApiErrorId.VISIT_NOT_SCHEDULED.value, 409)

        # The rejected attempt changed nothing on the already-delivered row.
        authorization = read_authorization(api, case.authorization_id)
        assert authorization["units_consumed"] == 2
        assert authorization["units_remaining"] == 22
        line = read_service_line(api, case.line_id)
        assert line["units_delivered"] == 2
        assert line["status"] == "IN_DELIVERY"

    def test_scheduled_session_reports_the_unit_capacity_defect(self, api):
        """
        The identical body sent against a session that is genuinely scheduled
        reports the unit-count defect, which proves the body was invalid all
        along and the state check merely reported first.

        PRD 3.7: "`actual_units` must be an integer of at least 1 and at most
        the session's `scheduled_units`, or the request is refused with
        `ERR_ACTUAL_UNITS_EXCEED_SCHEDULED`, and it must also not exceed the
        authorization's `units_remaining`, or the request is refused with
        `ERR_UNITS_EXCEED_AUTHORIZATION`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_visit_document
        """
        case = _build_one_delivered_one_scheduled(api)

        response = api.document_visit(
            case.visit_ids[1], dict(OVERSIZED_DOCUMENTATION), case.provider_headers
        )
        validate_error(response, ApiErrorId.ACTUAL_UNITS_EXCEED_SCHEDULED.value, 422)

        authorization = read_authorization(api, case.authorization_id)
        assert authorization["units_consumed"] == 2
        assert authorization["units_remaining"] == 22
        assert authorization["status"] == "ACTIVE"


# The authorization pair: an existing window that the new request touches, and a
# provider whose credential cannot cover the requested end date.
EXISTING_START = "2026-04-01"
EXISTING_END = "2026-04-30"
REQUEST_START = "2026-04-30"
REQUEST_END = "2026-05-31"
SHORT_CREDENTIAL_DATE = "2026-04-15"
LONG_CREDENTIAL_DATE = "2027-06-30"


def _build_line_with_occupied_window(api):
    """A live line already holding one authorization for the whole of April."""
    case = build_active_services(api)
    holder_id = create_provider(api, credential_expiry_date=LONG_CREDENTIAL_DATE)
    case.provider_ids.append(holder_id)
    case.provider_id = holder_id
    case.authorization_id = create_authorization(
        api,
        case.line_id,
        holder_id,
        start_date=EXISTING_START,
        end_date=EXISTING_END,
        authorized_units=24,
    )
    case.authorization_ids.append(case.authorization_id)
    return case


def _attempt_authorization(api, line_id, provider_id):
    return api.create_authorization(
        factories.authorization_payload(
            line_id,
            provider_id,
            start_date=REQUEST_START,
            end_date=REQUEST_END,
            authorized_units=12,
        ),
        ADMIN_HEADERS,
    )


class TestCredentialSafetyReportsBeforeWindowCollision:
    """The same colliding window, once with a lapsing credential."""

    def test_lapsing_credential_reports_before_the_window_collision(self, api):
        """
        A request whose window both collides with an existing authorization and
        outruns the provider's credential reports the credential, because the
        credential check is applied first.

        PRD 3.6: "The provider's `credential_expiry_date` must be on or after
        the requested `end_date`, so that no authorization can extend past the
        credential that justifies it; an over-reaching window is refused with
        `ERR_PROVIDER_CREDENTIAL_EXPIRED`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_authorization_create
        """
        case = _build_line_with_occupied_window(api)
        lapsing_provider_id = create_provider(
            api, credential_expiry_date=SHORT_CREDENTIAL_DATE
        )

        response = _attempt_authorization(api, case.line_id, lapsing_provider_id)
        validate_error(response, ApiErrorId.PROVIDER_CREDENTIAL_EXPIRED.value, 422)

        line = read_service_line(api, case.line_id)
        assert_unit_pool(
            line, units_committed=24, units_pool_remaining=72, planned_units_total=96
        )

    def test_valid_credential_exposes_the_window_collision_underneath(self, api):
        """
        With a credential that covers the window, the very same dates report the
        collision instead — the second defect was always present and simply
        ranked lower.

        PRD 3.6: "A new window conflicts with an existing one when the new
        `start_date` is on or before the existing `end_date` **and** the existing
        `start_date` is on or before the new `end_date`; a conflict is refused
        with `ERR_AUTHORIZATION_WINDOW_OVERLAP`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_authorization_create
        """
        case = _build_line_with_occupied_window(api)
        covered_provider_id = create_provider(
            api, credential_expiry_date=LONG_CREDENTIAL_DATE
        )

        response = _attempt_authorization(api, case.line_id, covered_provider_id)
        validate_error(response, ApiErrorId.AUTHORIZATION_WINDOW_OVERLAP.value, 409)

        rows, _meta = validate_paginated(
            api.list_authorizations(ADMIN_HEADERS, {"ifsp_service_id": case.line_id})
        )
        assert len(rows) == 1
        assert rows[0]["id"] == case.authorization_id

        line = read_service_line(api, case.line_id)
        assert_unit_pool(
            line, units_committed=24, units_pool_remaining=72, planned_units_total=96
        )
