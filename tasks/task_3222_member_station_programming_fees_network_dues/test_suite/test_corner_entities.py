"""Entity surface: required inputs, derived fields, row shape and listing defaults.

Queue B, corner index section `entities`.
"""
from test_helpers import (
    ADMIN,
    AUDITOR,
    ApiErrorId,
    api_client,
    assert_schedule,
    assert_station_derived_fields_match_inputs,
    create_schedule,
    create_station,
    get_success_data,
    set_clock,
    validate_error,
    validate_paginated,
)

STATION_FIXTURE = dict(
    call_sign="WBUR", licensee_name="Boston Licensee", state_code="MA",
    dma_market_rank=8, dma_households=2400000, coverage_population=100,
    full_time_staff_count=12, newsroom_staff_count=4,
    annual_local_revenue_cents=4800000, board_seat_region="REGION_NORTHEAST",
)


def test_station_creation_without_the_revenue_input_is_refused():
    """PRD §2.9: "A request whose required input field is absent, whose enum-valued
    field carries an undeclared member, or whose numeric field violates a declared
    range fails with `ERR_INVALID_REQUEST` (400)."

    The registration contract names the station's reported local revenue among the
    recorded inputs, so its absence is a shape failure rather than a state one.

    Design: Corner/entities/station_creation_without_revenue_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    payload = dict(STATION_FIXTURE)
    payload.pop("annual_local_revenue_cents")

    resp = api_client.create_station(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_station_creation_with_the_revenue_input_succeeds():
    """PRD §3.1: "Registration is a platform-administration act that records the
    station's legal and operational identity".

    Design: Corner/entities/station_creation_without_revenue_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    station = create_station(**STATION_FIXTURE)

    assert station["call_sign"] == "WBUR"
    assert station["annual_local_revenue_cents"] == 4800000


def test_registration_rejects_a_market_rank_above_the_declared_range():
    """PRD §2.9: the ranges in force include "a `dma_market_rank` between 1 and 210
    inclusive".

    Design: Corner/entities/station_creation_without_revenue_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api_client.create_station(dict(STATION_FIXTURE, dma_market_rank=211), ADMIN)

    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_station_derived_fields_ignore_anything_the_caller_supplies():
    """PRD §2.10: "`operations_score`, `membership_class`, `is_cleared`, `crowded`,
    `disclosure_test_passed`, `collection_ratio_bps`, `compensation_credit_cents`,
    `drive_deduction_cents`, `provisional_fee_cents`, `final_fee_cents`,
    `allocated_dues_cents`, `carriage_exception_liability_cents`,
    `dues_vote_eligible`, `recorded_weight` and the tallies on a dues proposal are
    all derived. A caller may send a value for such a field and the server will
    ignore it".

    Design: Corner/entities/station_derived_fields_are_recomputed
    """
    set_clock("2026-09-01T00:00:00Z")
    payload = dict(STATION_FIXTURE, coverage_population=1000000,
                   full_time_staff_count=6, newsroom_staff_count=9,
                   operations_score=0.0, membership_class="CLASS_D")
    resp = api_client.create_station(payload, ADMIN)
    data = get_success_data(resp, 201)

    assert_station_derived_fields_match_inputs(data)
    assert data["operations_score"] != 0.0, "the server's score must replace the sent one"


def test_new_station_begins_as_an_applicant_with_zeroed_counters():
    """PRD §3.1: "A newly registered station begins with `eligibility_status` set to
    `APPLICANT`, `dues_arrears_cents` at zero, `contribution_credit_cents` at
    zero, `applied_relief_cents` at zero, `dues_vote_eligible` false, and both
    `eligible_from` and `last_review_at` unset."

    Design: Corner/entities/station_derived_fields_are_recomputed
    """
    set_clock("2026-09-01T00:00:00Z")
    overridden = {"coverage_population", "full_time_staff_count", "newsroom_staff_count"}
    station = create_station(**{k: v for k, v in STATION_FIXTURE.items()
                                if k not in overridden},
                             coverage_population=1000000, full_time_staff_count=6,
                             newsroom_staff_count=9)

    assert station["eligibility_status"] == "APPLICANT"
    assert station["dues_arrears_cents"] == 0
    assert station["contribution_credit_cents"] == 0
    assert station["applied_relief_cents"] == 0
    assert station["dues_vote_eligible"] is False
    assert station["membership_class"] == "CLASS_B", (
        f"score 69.00 with a household index of 100 should read CLASS_B, "
        f"got {station['membership_class']}"
    )


def test_reading_an_unregistered_station_returns_not_found():
    """PRD §2.7: "a request naming a station, schedule, agreement, window, feed,
    slot, program, contribution, drive, report, election, candidacy, seat,
    proposal or vote that does not exist fails with `ERR_RESOURCE_NOT_FOUND`
    (HTTP 404)".

    Design: Corner/entities/station_not_found_and_schedule_row_shape
    """
    from test_helpers import AUDITOR, NON_EXISTENT_UUID

    set_clock("2026-09-01T00:00:00Z")
    resp = api_client.get_station(NON_EXISTENT_UUID, AUDITOR)

    validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND)


def test_schedule_row_carries_no_version_and_no_updated_at():
    """PRD §2.4: "`ProgrammingFeeSchedule` has no `updated_at` and no `version`; its
    pricing terms are rewritten wholesale when a dues structure is enacted, and a
    schedule is never the parent of an optimistic concurrency check."

    Design: Corner/entities/station_not_found_and_schedule_row_shape
    """
    set_clock("2026-09-01T00:00:00Z")
    schedule = create_schedule(schedule_code="FY2026Q")
    data = get_success_data(api_client.get_schedule(schedule["id"], AUDITOR))

    assert_schedule(data)
    assert data["schedule_code"] == "FY2026Q"
    assert data["fiscal_year"] == 2026


def test_station_listing_applies_the_default_page_size():
    """PRD §2.3: "The `limit` parameter defaults to 10 and must be an integer
    between 1 and 100 inclusive".
    PRD §2.3: "The `offset` parameter defaults to 0".

    Design: Corner/entities/station_listing_pagination_defaults
    """
    set_clock("2026-09-01T00:00:00Z")
    create_station(call_sign="WAAA", licensee_name="Pilot Licensee One")
    create_station(call_sign="WBBB", licensee_name="Pilot Licensee Two")

    resp = api_client.list_stations(ADMIN)
    data, meta = validate_paginated(resp)

    assert meta["limit"] == 10, f"the default page size is 10, got {meta['limit']}"
    assert meta["offset"] == 0
    assert meta["total_count"] == 2


def test_station_listing_reports_the_page_window_it_served():
    """PRD §2.3: "`total_count` is the size of the filtered result set before
    pagination and `has_more` is true exactly when further records remain beyond
    the returned page".
    PRD §2.3: "Records are ordered by `created_at` ascending".

    Design: Corner/entities/station_listing_pagination_defaults
    """
    set_clock("2026-09-01T00:00:00Z")
    first = create_station(call_sign="WAAA", licensee_name="Pilot Licensee One")
    second = create_station(call_sign="WBBB", licensee_name="Pilot Licensee Two")

    resp = api_client.list_stations(ADMIN, {"limit": 1, "offset": 1})
    data, meta = validate_paginated(resp)

    assert meta["limit"] == 1 and meta["offset"] == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(data) == 1
    assert data[0]["id"] == second["id"], (
        "the second page should carry the later-created station"
    )
    assert first["id"] != data[0]["id"]