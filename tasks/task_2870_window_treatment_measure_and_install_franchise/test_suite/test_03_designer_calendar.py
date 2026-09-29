"""One designer's calendar: half-open windows and a buffer that depends on the pair."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import ERR_DESIGNER_CALENDAR_CONFLICT
from test_helpers.assertions import assert_page_meta
from test_helpers.fixtures import (
    book_consultation,
    charter_territory,
    hire_designer,
    intake_lead,
    read_territory,
)
from test_helpers.test_users import designer_headers, franchisee_headers


def _one_booked_hour(api):
    """A designer holding 14:00–15:00 in postal code 30301, with two leads waiting.

    The territory covers 30301 and 30302, so the second and third homeowners live in
    a different postal code from the booked appointment and travel is required.
    """
    territory = charter_territory(api, postal_codes=["30301", "30302"],
                                 royalty_rate_pct=0.055,
                                 lead_capacity_per_week=5,
                                 credit_limit_cents=2000000,
                                 liability_window="ROLLING_180D")
    designer = hire_designer(api, territory)
    near = intake_lead(api, territory, customer_name="Ana Ruiz",
                       postal_code="30301", source="WEB_FORM",
                       requested_at="2026-08-01T08:00:00.000Z",
                       child_occupied_dwelling=False)
    across = intake_lead(api, territory, customer_name="Bo Chen",
                         postal_code="30302", source="REFERRAL",
                         requested_at="2026-08-01T09:00:00.000Z",
                         child_occupied_dwelling=False)
    third = intake_lead(api, territory, customer_name="Cy Doyle",
                        postal_code="30302", source="WALK_IN",
                        requested_at="2026-08-01T10:00:00.000Z",
                        child_occupied_dwelling=False)
    booked = book_consultation(
        api, designer, near,
        scheduled_start_at="2026-08-05T14:00:00.000Z",
        scheduled_end_at="2026-08-05T15:00:00.000Z",
        service_postal_code="30301",
    )
    return territory, designer, booked, across, third


def _attempt(api, designer, lead, start, end, postal_code):
    """Try to book one more appointment on the same designer's calendar."""
    return api.create_consultation(
        f.consultation_payload(lead["id"], designer["id"],
                               scheduled_start_at=start, scheduled_end_at=end,
                               service_postal_code=postal_code),
        designer_headers(designer["id"]),
    )


def test_a_cross_postal_code_booking_needs_exactly_forty_five_minutes(api):
    """Zero and 44:59.999 are refused across postal codes; 45:00.000 is admitted.

    "The buffer applied to a pair of appointments is zero minutes when the existing
    appointment's `service_postal_code` equals the candidate's, and forty-five
    minutes otherwise."

    "Across different postal codes a gap of exactly forty-five minutes is admissible
    while a gap of forty-four minutes and 59.999 seconds is not."

    Design: Difficulty/resource_temporal_overlap/designer_calendar_is_half_open_with_a_conditional_travel_buffer
    """
    territory, designer, _booked, across, _third = _one_booked_hour(api)

    validate_error(
        _attempt(api, designer, across, "2026-08-05T15:00:00.000Z",
                 "2026-08-05T16:00:00.000Z", "30302"),
        ERR_DESIGNER_CALENDAR_CONFLICT, 409)

    validate_error(
        _attempt(api, designer, across, "2026-08-05T15:44:59.999Z",
                 "2026-08-05T16:44:59.999Z", "30302"),
        ERR_DESIGNER_CALENDAR_CONFLICT, 409)

    admitted = validate_success(
        _attempt(api, designer, across, "2026-08-05T15:45:00.000Z",
                 "2026-08-05T16:45:00.000Z", "30302"), 201)
    assert admitted["status"] == "SCHEDULED"

    # The two refusals wrote nothing and consumed no weekly capacity.
    rows, meta = validate_paginated(api.list_consultations(
        designer_headers(designer["id"]), designer_id=designer["id"]))
    assert_page_meta(meta, total_count=2, has_more=False)
    assert len(rows) == 2
    assert read_territory(api, territory)["open_leads_count"] == 3


def test_touching_appointments_in_one_postal_code_do_not_collide(api):
    """A candidate starting at the instant a same-postal-code appointment ends is legal.

    "Occupation intervals are half-open — the start instant belongs to the appointment
    and the end instant does not — so two appointments that touch exactly, where the
    candidate starts at the very instant an existing one ends, do not collide
    **provided they are in the same postal code**."

    Design: Difficulty/resource_temporal_overlap/designer_calendar_is_half_open_with_a_conditional_travel_buffer
    """
    _territory, designer, _booked, across, third = _one_booked_hour(api)

    middle = validate_success(
        _attempt(api, designer, across, "2026-08-05T15:45:00.000Z",
                 "2026-08-05T16:45:00.000Z", "30302"), 201)
    assert middle["status"] == "SCHEDULED"

    # 16:45 is back-to-back with the 30302 appointment and 105 minutes clear of the
    # 30301 one, so it is legal against both neighbours at once.
    abutting = validate_success(
        _attempt(api, designer, third, "2026-08-05T16:45:00.000Z",
                 "2026-08-05T17:45:00.000Z", "30302"), 201)
    assert abutting["status"] == "SCHEDULED"
    assert abutting["scheduled_start_at"] == middle["scheduled_end_at"]

    _rows, meta = validate_paginated(api.list_consultations(
        designer_headers(designer["id"]), designer_id=designer["id"]))
    assert_page_meta(meta, total_count=3, has_more=False)


def test_a_refused_booking_leaves_the_lead_untouched(api):
    """The lead behind a rejected booking keeps its routing and gains no appointment.

    "A booking is admissible only when it collides with no member of that designer's
    occupied set; otherwise it is rejected with `ERR_DESIGNER_CALENDAR_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/designer_calendar_is_half_open_with_a_conditional_travel_buffer
    """
    territory, designer, _booked, across, _third = _one_booked_hour(api)
    owner = franchisee_headers(territory["id"])

    validate_error(
        _attempt(api, designer, across, "2026-08-05T15:00:00.000Z",
                 "2026-08-05T16:00:00.000Z", "30302"),
        ERR_DESIGNER_CALENDAR_CONFLICT, 409)

    unchanged = validate_success(api.get_lead(across["id"], owner))
    assert unchanged["status"] == "ROUTED"
    assert unchanged["territory_id"] == territory["id"]

    _rows, meta = validate_paginated(api.list_consultations(
        designer_headers(designer["id"]), lead_id=across["id"]))
    assert_page_meta(meta, total_count=0, has_more=False)

    accepted = validate_success(
        _attempt(api, designer, across, "2026-08-05T15:45:00.000Z",
                 "2026-08-05T16:45:00.000Z", "30302"), 201)
    _rows, meta = validate_paginated(api.list_consultations(
        designer_headers(designer["id"]), lead_id=across["id"]))
    assert_page_meta(meta, total_count=1, has_more=False)
    assert accepted["lead_id"] == across["id"]
