"""Two contended resources with deliberately opposite interval conventions: a testimony calendar
compared half-open with a travel buffer, and a vendor custody window closed at both ends.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import (
    ERR_TESTIMONY_SCHEDULE_CONFLICT,
    ERR_VENDOR_CAPACITY_EXCEEDED,
)
from test_helpers.assertions import (
    assert_fields,
    assert_instant_equals,
    assert_list_meta,
)
from test_helpers.factories import court_event_payload, vendor_engagement_payload
from test_helpers.fixtures import (
    accept_case,
    assign_request,
    award_engagement,
    create_validated_method,
    log_evidence,
    raise_request,
    read_request,
    register_analyst,
    register_vendor,
    release_request,
    set_clock,
    submit_case,
)
from test_helpers.test_users import CASE_MANAGER_HEADERS, DIRECTOR_HEADERS


def _digital_examiner_with_a_morning_hearing_on_the_first_of_september(api):
    """A released mobile-device extraction whose author already sits in court from 09:00 to 11:00,
    a block that occupies 08:00 to 12:00 once the travel buffer is added.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    examiner = register_analyst(
        api,
        full_name="Talia Mensah",
        disciplines=["DIGITAL"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    reviewer = register_analyst(
        api,
        full_name="Rui Alcantara",
        disciplines=["DIGITAL"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    method = create_validated_method(
        api,
        name="Mobile Device Logical Extraction",
        discipline="DIGITAL",
        standard_hours_per_item=6.00,
        min_competency_level=3,
        max_items_per_request=4,
        is_consumptive=False,
        accreditation_scope_code="DIG-MOB-01",
        validation_study_item_count=22,
        precision_cv_pct=1.00,
    )
    case = submit_case(
        api,
        agency_case_number="B-2026-1616",
        submitting_agency="METRO PD",
        offense_category="BURGLARY",
        suspect_in_custody=False,
    )
    item = log_evidence(
        api, case["id"], item_number="1", item_type="DIGITAL_DEVICE", seal_intact=True
    )
    accept_case(api, case["id"])
    request = raise_request(api, case["id"], item["id"], method["id"], item_count=1)
    assign_request(
        api, request["id"], examiner["id"], expected_version=request["version"]
    )
    release_request(api, request["id"], examiner["id"], reviewer["id"], actual_hours=6.00)

    hearing = validate_success(
        api.create_court_event(
            court_event_payload(
                request["id"],
                examiner["id"],
                start_utc="2026-09-01T09:00:00Z",
                end_utc="2026-09-01T11:00:00Z",
                court_name="Superior Court Division 1",
                docket_number="CR-2026-3001",
            ),
            CASE_MANAGER_HEADERS,
        ),
        201,
    )
    return examiner, request, hearing


def _book_hearing(api, request_id, analyst_id, docket_number, start_utc, end_utc, court_name):
    return api.create_court_event(
        court_event_payload(
            request_id,
            analyst_id,
            start_utc=start_utc,
            end_utc=end_utc,
            court_name=court_name,
            docket_number=docket_number,
        ),
        CASE_MANAGER_HEADERS,
    )


def test_a_hearing_starting_one_minute_inside_the_travel_buffer_is_refused(api):
    """The existing block runs to 11:00 but occupies until 12:00 once padded, so a hearing
    starting at 11:59 intersects it and is refused, leaving no row on that docket.

    PRD §3.9: "The calendar guard treats a hearing as the half-open interval from `start_utc` up
    to but excluding `end_utc`, then extends every existing block by a 60-minute travel buffer at
    each end: the new hearing may not intersect any of that examiner's events whose `status` is
    `SCHEDULED` or `CONFIRMED` once those are so extended, else `ERR_TESTIMONY_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/testimony_travel_buffer_admits_a_gap_of_exactly_sixty_minutes
    """
    examiner, request, hearing = _digital_examiner_with_a_morning_hearing_on_the_first_of_september(
        api
    )
    assert_fields(hearing, status="SCHEDULED", notice_days=31)

    response = _book_hearing(
        api,
        request["id"],
        examiner["id"],
        "CR-2026-3002",
        "2026-09-01T11:59:00Z",
        "2026-09-01T12:59:00Z",
        "Superior Court Division 2",
    )
    validate_error(response, ERR_TESTIMONY_SCHEDULE_CONFLICT, expected_status=409)

    rows, meta = validate_paginated(
        api.list_court_events(CASE_MANAGER_HEADERS, {"analyst_id": examiner["id"]})
    )
    assert_list_meta(meta, expected_total=1)
    assert all(row["docket_number"] != "CR-2026-3002" for row in rows), (
        "The refused docket must not have been written"
    )


def test_a_hearing_starting_exactly_sixty_minutes_after_the_last_one_ends_is_admitted(api):
    """One minute later the seam is clear: a hearing beginning at 12:00, a full hour after the
    earlier block ended, is booked and the examiner now holds two scheduled blocks.

    PRD §3.9: "An examiner cannot be in two courthouses at once, and cannot be in the second one
    without an hour to get there, so a hearing beginning exactly 60 minutes after an earlier one
    ends is admissible while one beginning a single second earlier is refused."

    Design: Difficulty/resource_temporal_overlap/testimony_travel_buffer_admits_a_gap_of_exactly_sixty_minutes
    """
    examiner, request, _hearing = _digital_examiner_with_a_morning_hearing_on_the_first_of_september(
        api
    )
    _book_hearing(
        api,
        request["id"],
        examiner["id"],
        "CR-2026-3002",
        "2026-09-01T11:59:00Z",
        "2026-09-01T12:59:00Z",
        "Superior Court Division 2",
    )

    admitted = validate_success(
        _book_hearing(
            api,
            request["id"],
            examiner["id"],
            "CR-2026-3003",
            "2026-09-01T12:00:00Z",
            "2026-09-01T13:00:00Z",
            "Superior Court Division 3",
        ),
        201,
    )
    assert_fields(admitted, status="SCHEDULED", notice_days=31)
    assert_instant_equals(admitted["start_utc"], "2026-09-01T12:00:00Z", "start_utc")

    _rows, meta = validate_paginated(
        api.list_court_events(
            CASE_MANAGER_HEADERS,
            {"analyst_id": examiner["id"], "status": "SCHEDULED"},
        )
    )
    assert_list_meta(meta, expected_total=2)


def _single_slot_vendor_holding_the_tenth_to_twentieth_of_august(api):
    """A chemistry vendor with one custody slot, already committed to the window from the tenth to
    the twentieth of August, and two further queued requests waiting for a slot.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    vendor = register_vendor(
        api,
        name="Keystone Analytical Services",
        accredited_disciplines=["CHEMISTRY"],
        accreditation_expires_at_utc="2027-01-01T00:00:00Z",
        concurrent_case_capacity=1,
        unit_price_cents=45000,
        rush_surcharge_pct=0.00,
        contract_ceiling_cents=10000000,
    )
    method = create_validated_method(
        api,
        name="GC-MS Controlled Substance Identification",
        discipline="CHEMISTRY",
        standard_hours_per_item=2.00,
        min_competency_level=3,
        max_items_per_request=10,
        is_consumptive=False,
        accreditation_scope_code="CHEM-GCMS-01",
    )
    case = submit_case(
        api,
        agency_case_number="D-2026-1717",
        submitting_agency="STATE PATROL",
        offense_category="DRUG_OFFENSE",
        suspect_in_custody=False,
    )
    items = [
        log_evidence(
            api,
            case["id"],
            item_number=str(number),
            item_type="CHEMICAL",
            seal_intact=True,
        )
        for number in (1, 2, 3)
    ]
    accept_case(api, case["id"])
    requests_raised = [
        raise_request(api, case["id"], item["id"], method["id"], item_count=2)
        for item in items
    ]
    incumbent = award_engagement(
        api,
        requests_raised[0]["id"],
        vendor["id"],
        window_start_utc="2026-08-10T00:00:00Z",
        window_end_utc="2026-08-20T00:00:00Z",
        rush_flag=False,
    )
    return vendor, incumbent, requests_raised


def test_a_window_starting_on_the_incumbents_end_instant_is_refused(api):
    """Custody windows are closed at both ends, so a window opening at the exact instant the
    incumbent's closes still shares that instant and exceeds a capacity of one; the vendor's
    encumbrance is left exactly as the first award set it.

    PRD §3.7: "Custody windows are **closed at both ends** for this arithmetic, so a new window
    whose `window_start_utc` falls exactly on an existing window's `window_end_utc` does intersect
    it and is refused, while a window starting one second later is admitted."

    Design: Difficulty/resource_temporal_overlap/vendor_closed_window_capacity_refuses_a_touching_endpoint
    """
    vendor, incumbent, requests_raised = _single_slot_vendor_holding_the_tenth_to_twentieth_of_august(
        api
    )
    assert_fields(incumbent, status="AWARDED", award_amount_cents=90000)
    assert_fields(read_request(api, requests_raised[0]["id"]), status="OUTSOURCED")
    assert_fields(
        validate_success(api.get_vendor(vendor["id"], DIRECTOR_HEADERS)),
        encumbered_cents=90000,
    )

    response = api.create_vendor_engagement(
        requests_raised[1]["id"],
        vendor_engagement_payload(
            vendor["id"],
            window_start_utc="2026-08-20T00:00:00Z",
            window_end_utc="2026-08-30T00:00:00Z",
            rush_flag=False,
        ),
        CASE_MANAGER_HEADERS,
    )
    validate_error(response, ERR_VENDOR_CAPACITY_EXCEEDED, expected_status=409)

    assert_fields(read_request(api, requests_raised[1]["id"]), status="QUEUED")
    assert_fields(
        validate_success(api.get_vendor(vendor["id"], DIRECTOR_HEADERS)),
        encumbered_cents=90000,
    )
    _rows, meta = validate_paginated(
        api.list_vendor_engagements(
            CASE_MANAGER_HEADERS,
            {"examination_request_id": requests_raised[1]["id"]},
        )
    )
    assert_list_meta(meta, expected_total=0)


def test_a_window_starting_one_second_later_is_awarded_and_priced_without_a_discount(api):
    """Shifting the start by a single second clears the incumbent window, and the second award
    prices at the bare base of 90000 cents — below the first volume tier — bringing the vendor's
    encumbrance to 180000 with nothing yet spent.

    PRD §3.7: "**Step four:** `volume_discount_pct` is 0.12 when `tier_basis_cents` is at least
    500000 cents, otherwise 0.08 when it is at least 250000 cents, otherwise 0.04 when it is at
    least 100000 cents, otherwise 0.00."

    PRD §3.7: "The award then increments the vendor's `encumbered_cents` by
    `award_amount_cents`."

    Design: Difficulty/resource_temporal_overlap/vendor_closed_window_capacity_refuses_a_touching_endpoint
    """
    vendor, _incumbent, requests_raised = _single_slot_vendor_holding_the_tenth_to_twentieth_of_august(
        api
    )
    api.create_vendor_engagement(
        requests_raised[1]["id"],
        vendor_engagement_payload(
            vendor["id"],
            window_start_utc="2026-08-20T00:00:00Z",
            window_end_utc="2026-08-30T00:00:00Z",
            rush_flag=False,
        ),
        CASE_MANAGER_HEADERS,
    )

    admitted = validate_success(
        api.create_vendor_engagement(
            requests_raised[2]["id"],
            vendor_engagement_payload(
                vendor["id"],
                window_start_utc="2026-08-20T00:00:01Z",
                window_end_utc="2026-08-30T00:00:00Z",
                rush_flag=False,
            ),
            CASE_MANAGER_HEADERS,
        ),
        201,
    )
    assert_fields(
        admitted,
        status="AWARDED",
        award_amount_cents=90000,
        volume_discount_pct=0.00,
    )
    assert_fields(read_request(api, requests_raised[2]["id"]), status="OUTSOURCED")
    assert_fields(
        validate_success(api.get_vendor(vendor["id"], DIRECTOR_HEADERS)),
        encumbered_cents=180000,
        spent_cents=0,
    )
