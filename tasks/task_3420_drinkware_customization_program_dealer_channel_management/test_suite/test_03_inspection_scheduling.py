"""Site-visit scheduling: record window gating and the inspector calendar
(PRD section 3.1)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    boot_clock,
    create_open_application,
    get_application,
    make_field_inspector_headers,
    record_inspection,
    schedule_inspection,
    schedule_inspection_payload,
    set_clock,
    validate_error,
    validate_success,
)


def test_record_inspection_before_window_end_returns_not_reached(api):
    """Recording is refused while the scheduled window is still running and
    succeeds at the exact window end.

    PRD section 3.1: "Later, once the scheduled window has ended — recording
    before the window's end is rejected with
    `ERR_INSPECTION_WINDOW_NOT_REACHED` — the assigned inspector records the
    `outcome`, moving `inspection_status` to `PASSED` or `FAILED`"

    Design: Corner/validations/record_inspection_before_window_end_returns_not_reached
    """
    boot_clock()
    pair = create_open_application()
    app = pair["application"]
    schedule_inspection(app["id"], inspector_id="fi-1",
                        window_start="2026-09-02T09:00:00Z",
                        window_end="2026-09-02T11:00:00Z")

    set_clock("2026-09-02T10:30:00Z")
    resp = api.record_inspection(
        app["id"], {"outcome": "PASSED", "brand_presentation_score": 85},
        make_field_inspector_headers("fi-1"))
    validate_error(resp, ApiErrorId.ERR_INSPECTION_WINDOW_NOT_REACHED)
    assert get_application(app["id"])["inspection_status"] == "SCHEDULED"

    set_clock("2026-09-02T11:00:00Z")
    recorded = record_inspection(app["id"], inspector_id="fi-1",
                                 outcome="PASSED", brand_presentation_score=85)
    assert recorded["inspection_status"] == "PASSED", \
        "at exactly window_end the record succeeds"


def test_inspector_closed_interval_and_travel_buffer(api):
    """Inspector windows are closed intervals (shared endpoints conflict) with
    an unconditional 60-minute travel buffer (59 minutes conflicts, exactly
    60 is allowed).

    PRD section 3.1: "An inspector's site-visit windows are closed intervals:
    both endpoints are occupied, so two windows sharing an endpoint conflict
    outright, and between consecutive windows on the same inspector a travel
    buffer of at least 60 minutes is required, meaning the next window's start
    must be at least 60 minutes after the previous window's end. Only
    applications whose `inspection_status` is `SCHEDULED` occupy the
    inspector's calendar, and a collision is rejected with
    `ERR_INSPECTOR_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/inspector_closed_interval_and_travel_buffer
    """
    boot_clock()
    apps = []
    for i in (1, 2, 3, 4):
        pair = create_open_application(
            dealer_overrides={"legal_name": f"Insp {i}"},
            storefront_sqft=1200, document_refs=[f"d{i}"])
        apps.append(pair["application"])
    a1, a2, a3, a4 = (a["id"] for a in apps)
    fi = make_field_inspector_headers("fi-9")

    def schedule(app_id, start, end):
        return api.schedule_inspection(
            app_id,
            schedule_inspection_payload(
                inspector_user_id="fi-9", window_start=start, window_end=end),
            fi)

    # [09:00, 10:00] scheduled first.
    validate_success(schedule(a1, "2026-09-03T09:00:00Z", "2026-09-03T10:00:00Z"))

    # [08:00, 09:00] shares the 09:00 endpoint: closed intervals touch-conflict.
    resp_touch = schedule(a2, "2026-09-03T08:00:00Z", "2026-09-03T09:00:00Z")
    validate_error(resp_touch, ApiErrorId.ERR_INSPECTOR_SCHEDULE_CONFLICT)

    # 59 minutes after a1's 10:00 end: below the 60-minute travel buffer.
    resp_gap59 = schedule(a3, "2026-09-03T10:59:00Z", "2026-09-03T11:30:00Z")
    validate_error(resp_gap59, ApiErrorId.ERR_INSPECTOR_SCHEDULE_CONFLICT)

    # Exactly 60 minutes after 10:00: the buffer boundary is inclusive.
    validate_success(schedule(a4, "2026-09-03T11:00:00Z", "2026-09-03T12:00:00Z"))

    assert get_application(a2)["inspection_status"] == "UNSCHEDULED"
    assert get_application(a3)["inspection_status"] == "UNSCHEDULED"
    assert get_application(a1)["inspection_status"] == "SCHEDULED"
    assert get_application(a4)["inspection_status"] == "SCHEDULED"
