"""Requests that break two gates at once, where the reported defect must be the earlier gate
in the normative evaluation order rather than the louder or later one.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import (
    ERR_TESTIMONY_SCHEDULE_CONFLICT,
    ERR_VENDOR_NOT_ACCREDITED,
    ERR_VENDOR_SUSPENDED,
)
from test_helpers.assertions import assert_fields, assert_list_meta
from test_helpers.factories import (
    court_event_payload,
    vendor_engagement_payload,
    vendor_status_payload,
)
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


def _gcms_method(api):
    return create_validated_method(
        api,
        name="GC-MS Controlled Substance Identification",
        discipline="CHEMISTRY",
        standard_hours_per_item=2.00,
        min_competency_level=3,
        max_items_per_request=10,
        is_consumptive=False,
        accreditation_scope_code="CHEM-GCMS-01",
    )


def _queued_chemistry_request_and_biology_only_vendor(api):
    """A five-item chemistry request and a vendor that is neither accredited for chemistry nor
    solvent enough for the award it would price at.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    method = _gcms_method(api)
    vendor = register_vendor(
        api,
        name="Northgate Biology Services",
        accredited_disciplines=["BIOLOGY"],
        accreditation_expires_at_utc="2027-01-01T00:00:00Z",
        concurrent_case_capacity=2,
        unit_price_cents=45000,
        rush_surcharge_pct=0.00,
        contract_ceiling_cents=1000,
    )
    case = submit_case(
        api,
        agency_case_number="D-2026-0909",
        submitting_agency="METRO PD",
        offense_category="DRUG_OFFENSE",
        suspect_in_custody=False,
    )
    item = log_evidence(
        api, case["id"], item_number="1", item_type="CHEMICAL", seal_intact=True
    )
    accept_case(api, case["id"])
    request = raise_request(api, case["id"], item["id"], method["id"], item_count=5)
    return vendor, case, request


def test_vendor_accreditation_is_reported_ahead_of_the_contract_ceiling(api):
    """The award would price at 216000 cents against a ceiling of 1000, yet the defect
    reported is the discipline the vendor is not accredited for, at 409 rather than 402.

    PRD §2.8: "Accreditation is a safety gate and deliberately outranks the fiscal ceiling at
    rule 27, so an unaccredited vendor whose award would also breach the contract ceiling
    reports the accreditation defect."

    Design: Difficulty/priority_pair_validation_conflict/vendor_accreditation_scope_outranks_contract_ceiling_breach
    """
    vendor, _case, request = _queued_chemistry_request_and_biology_only_vendor(api)

    response = api.create_vendor_engagement(
        request["id"],
        vendor_engagement_payload(
            vendor["id"],
            window_start_utc="2026-08-05T00:00:00Z",
            window_end_utc="2026-08-25T00:00:00Z",
            rush_flag=False,
        ),
        CASE_MANAGER_HEADERS,
    )
    validate_error(response, ERR_VENDOR_NOT_ACCREDITED, expected_status=409)


def test_the_refused_award_leaves_no_engagement_and_no_encumbrance(api):
    """Because the reported rule is the accreditation gate, none of the pricing side effects
    that belong to the ceiling gate below it survive: no engagement row exists, both vendor
    counters stay at zero and the request is still queued.

    PRD §2.8: "When a single request violates two rules, the earlier rule in this list
    determines the response, and no side effect belonging to any later rule is applied."

    Design: Difficulty/priority_pair_validation_conflict/vendor_accreditation_scope_outranks_contract_ceiling_breach
    """
    vendor, case, request = _queued_chemistry_request_and_biology_only_vendor(api)
    api.create_vendor_engagement(
        request["id"],
        vendor_engagement_payload(
            vendor["id"],
            window_start_utc="2026-08-05T00:00:00Z",
            window_end_utc="2026-08-25T00:00:00Z",
            rush_flag=False,
        ),
        CASE_MANAGER_HEADERS,
    )

    _rows, meta = validate_paginated(
        api.list_vendor_engagements(
            CASE_MANAGER_HEADERS, {"examination_request_id": request["id"]}
        )
    )
    assert_list_meta(meta, expected_total=0)

    reread = validate_success(api.get_vendor(vendor["id"], DIRECTOR_HEADERS))
    assert_fields(reread, encumbered_cents=0, spent_cents=0)

    assert_fields(read_request(api, request["id"]), status="QUEUED")
    assert_fields(
        validate_success(api.get_case(case["id"], CASE_MANAGER_HEADERS)),
        workflow_status="AWAITING_ASSIGNMENT",
    )


def _suspended_vendor_whose_only_slot_is_already_taken(api):
    """A single-slot chemistry vendor holding one awarded window, then suspended, plus a second
    queued request whose proposed window overlaps the first.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    method = _gcms_method(api)
    vendor = register_vendor(
        api,
        name="Cascade Reference Laboratory",
        accredited_disciplines=["CHEMISTRY"],
        accreditation_expires_at_utc="2027-01-01T00:00:00Z",
        concurrent_case_capacity=1,
        unit_price_cents=45000,
        rush_surcharge_pct=0.00,
        contract_ceiling_cents=10000000,
    )
    case = submit_case(
        api,
        agency_case_number="D-2026-1010",
        submitting_agency="METRO PD",
        offense_category="DRUG_OFFENSE",
        suspect_in_custody=False,
    )
    first_item = log_evidence(
        api, case["id"], item_number="1", item_type="CHEMICAL", seal_intact=True
    )
    second_item = log_evidence(
        api, case["id"], item_number="2", item_type="CHEMICAL", seal_intact=True
    )
    accept_case(api, case["id"])
    first_request = raise_request(
        api, case["id"], first_item["id"], method["id"], item_count=2
    )
    second_request = raise_request(
        api, case["id"], second_item["id"], method["id"], item_count=2
    )
    engagement = award_engagement(
        api,
        first_request["id"],
        vendor["id"],
        window_start_utc="2026-08-10T00:00:00Z",
        window_end_utc="2026-08-20T00:00:00Z",
        rush_flag=False,
    )
    validate_success(
        api.set_vendor_status(
            vendor["id"],
            vendor_status_payload(
                "SUSPENDED",
                suspension_reason=(
                    "Accreditation body issued an adverse audit finding."
                ),
            ),
            DIRECTOR_HEADERS,
        )
    )
    return vendor, engagement, second_request


def _award_the_overlapping_window(api, vendor_id, request_id):
    return api.create_vendor_engagement(
        request_id,
        vendor_engagement_payload(
            vendor_id,
            window_start_utc="2026-08-10T00:00:00Z",
            window_end_utc="2026-08-18T00:00:00Z",
            rush_flag=False,
        ),
        CASE_MANAGER_HEADERS,
    )


def test_vendor_suspension_is_reported_ahead_of_the_occupied_capacity_slot(api):
    """Both the availability gate and the concurrent-capacity gate answer 409, so nothing but
    the declared order can separate them: the suspension is the earlier rule and is what the
    caller is told.

    PRD §2.8: "The named vendor's `status` is `ACTIVE`, else `ERR_VENDOR_SUSPENDED` (409).
    Checked after accreditation, so a vendor that is both suspended and unaccredited reports
    the accreditation defect."

    Design: Difficulty/priority_pair_validation_conflict/vendor_suspension_outranks_aggregate_window_capacity
    """
    vendor, _engagement, second_request = _suspended_vendor_whose_only_slot_is_already_taken(
        api
    )

    response = _award_the_overlapping_window(api, vendor["id"], second_request["id"])
    validate_error(response, ERR_VENDOR_SUSPENDED, expected_status=409)


def test_the_standing_award_and_its_encumbrance_survive_the_refusal(api):
    """The refusal changes nothing that was already committed: the vendor still holds exactly
    one awarded engagement at 90000 cents, its encumbrance still matches that award, and the
    refused request stays queued.

    PRD §2.11: "The **vendor encumbrance** invariant fixes each vendor's `encumbered_cents` at
    the sum of `award_amount_cents` over that vendor's engagements whose `status` is `AWARDED`
    or `AT_VENDOR`, and their `spent_cents` at the sum of `final_invoice_cents` over that
    vendor's engagements whose `status` is `RETURNED`."

    Design: Difficulty/priority_pair_validation_conflict/vendor_suspension_outranks_aggregate_window_capacity
    """
    vendor, engagement, second_request = _suspended_vendor_whose_only_slot_is_already_taken(
        api
    )
    _award_the_overlapping_window(api, vendor["id"], second_request["id"])

    _rows, meta = validate_paginated(
        api.list_vendor_engagements(CASE_MANAGER_HEADERS, {"vendor_id": vendor["id"]})
    )
    assert_list_meta(meta, expected_total=1)

    reread_engagement = validate_success(
        api.get_vendor_engagement(engagement["id"], CASE_MANAGER_HEADERS)
    )
    assert_fields(reread_engagement, status="AWARDED", award_amount_cents=90000)

    reread_vendor = validate_success(api.get_vendor(vendor["id"], DIRECTOR_HEADERS))
    assert_fields(reread_vendor, status="SUSPENDED", encumbered_cents=90000)

    assert_fields(read_request(api, second_request["id"]), status="QUEUED")


def _examiner_with_a_scheduled_hearing_and_the_clock_moved_close_to_it(api):
    """A released report whose author already has a morning hearing on 1 September, read at an
    instant only two days before a proposed second hearing that clashes with it.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    examiner = register_analyst(
        api,
        full_name="Ada Nakamura",
        disciplines=["CHEMISTRY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    reviewer = register_analyst(
        api,
        full_name="Bo Ferreira",
        disciplines=["CHEMISTRY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    method = _gcms_method(api)
    case = submit_case(
        api,
        agency_case_number="D-2026-1111",
        submitting_agency="METRO PD",
        offense_category="DRUG_OFFENSE",
        suspect_in_custody=False,
    )
    item = log_evidence(
        api, case["id"], item_number="1", item_type="CHEMICAL", seal_intact=True
    )
    accept_case(api, case["id"])
    request = raise_request(api, case["id"], item["id"], method["id"], item_count=1)
    assign_request(
        api, request["id"], examiner["id"], expected_version=request["version"]
    )
    release_request(api, request["id"], examiner["id"], reviewer["id"], actual_hours=2.00)

    hearing = validate_success(
        api.create_court_event(
            court_event_payload(
                request["id"],
                examiner["id"],
                start_utc="2026-09-01T09:00:00Z",
                end_utc="2026-09-01T11:00:00Z",
                court_name="Superior Court Department 4",
                docket_number="CR-2026-1001",
                subpoena_received=False,
            ),
            CASE_MANAGER_HEADERS,
        ),
        201,
    )
    set_clock(api, "2026-08-30T00:00:00Z")
    return examiner, request, hearing


def _schedule_the_clashing_short_notice_hearing(api, request_id, analyst_id):
    return api.create_court_event(
        court_event_payload(
            request_id,
            analyst_id,
            start_utc="2026-09-01T11:59:00Z",
            end_utc="2026-09-01T12:59:00Z",
            court_name="Superior Court Department 6",
            docket_number="CR-2026-1002",
            subpoena_received=False,
        ),
        CASE_MANAGER_HEADERS,
    )


def test_a_calendar_clash_is_reported_ahead_of_the_short_notice(api):
    """The proposed slot starts one minute inside the travel buffer around the existing
    hearing and carries only two days' notice; the answer is the 409 calendar clash, not the
    422 notice shortfall.

    PRD §3.9: "The calendar guard treats a hearing as the half-open interval from `start_utc`
    up to but excluding `end_utc`, then extends every existing block by a 60-minute travel
    buffer at each end: the new hearing may not intersect any of that examiner's events whose
    `status` is `SCHEDULED` or `CONFIRMED` once those are so extended, else
    `ERR_TESTIMONY_SCHEDULE_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/testimony_calendar_overlap_outranks_insufficient_notice
    """
    examiner, request, _hearing = _examiner_with_a_scheduled_hearing_and_the_clock_moved_close_to_it(
        api
    )

    response = _schedule_the_clashing_short_notice_hearing(
        api, request["id"], examiner["id"]
    )
    validate_error(response, ERR_TESTIMONY_SCHEDULE_CONFLICT, expected_status=409)


def test_the_refusal_books_nothing_and_leaves_the_original_notice_untouched(api):
    """The examiner's calendar still holds exactly one block, and that block's notice figure is
    the 31 whole days measured when it was created, not anything recomputed from the moved
    clock.

    PRD §3.9: "A new event has `status` `SCHEDULED` and its `notice_days` computed once at
    creation as the whole number of complete days from the current logical instant to
    `start_utc` — the interval in seconds divided by 86400, discarding any fraction."

    Design: Difficulty/priority_pair_validation_conflict/testimony_calendar_overlap_outranks_insufficient_notice
    """
    examiner, request, hearing = _examiner_with_a_scheduled_hearing_and_the_clock_moved_close_to_it(
        api
    )
    _schedule_the_clashing_short_notice_hearing(api, request["id"], examiner["id"])

    _rows, meta = validate_paginated(
        api.list_court_events(CASE_MANAGER_HEADERS, {"analyst_id": examiner["id"]})
    )
    assert_list_meta(meta, expected_total=1)

    reread = validate_success(api.get_court_event(hearing["id"], CASE_MANAGER_HEADERS))
    assert_fields(reread, status="SCHEDULED", notice_days=31)
