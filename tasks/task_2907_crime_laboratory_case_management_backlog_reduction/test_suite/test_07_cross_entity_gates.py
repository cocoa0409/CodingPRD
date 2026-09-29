"""Gates that live on a neighbouring row: a lapsed method validation that stops bench work, and
a request's release state that decides whether a hearing may be booked at all.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import (
    ERR_EXAM_REQUEST_INVALID_STATE,
    ERR_METHOD_VALIDATION_EXPIRED,
)
from test_helpers.assertions import (
    assert_fields,
    assert_instant_equals,
    assert_list_meta,
    assert_two_decimal_value,
)
from test_helpers.factories import court_event_payload
from test_helpers.fixtures import (
    accept_case,
    administrative_review,
    assign_request,
    carry_to_tech_review,
    create_validated_method,
    log_evidence,
    raise_request,
    read_request,
    register_analyst,
    set_clock,
    start_analysis,
    submit_case,
    technical_review,
)
from test_helpers.test_users import (
    CASE_MANAGER_HEADERS,
    QUALITY_MANAGER_HEADERS,
    TECHNICIAN_HEADERS,
    make_analyst_headers,
)


def _assigned_biology_request_whose_method_expires_on_the_first_of_september(api):
    """A biology request held by a qualified examiner, its exhibit still sealed in the vault, and
    a method whose validation lapses at exactly 2026-09-01T00:00:00Z.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    examiner = register_analyst(
        api,
        full_name="Ines Okafor",
        disciplines=["BIOLOGY"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    method = create_validated_method(
        api,
        name="STR Autosomal Typing",
        discipline="BIOLOGY",
        standard_hours_per_item=4.00,
        min_competency_level=3,
        max_items_per_request=6,
        is_consumptive=True,
        accreditation_scope_code="BIO-STR-01",
        precision_cv_pct=2.00,
        expires_at_utc="2026-09-01T00:00:00Z",
    )
    case = submit_case(
        api,
        agency_case_number="A-2026-1414",
        submitting_agency="COUNTY SO",
        offense_category="AGG_ASSAULT",
        suspect_in_custody=False,
    )
    item = log_evidence(
        api, case["id"], item_number="1", item_type="BIOLOGICAL", seal_intact=True
    )
    accept_case(api, case["id"])
    request = raise_request(api, case["id"], item["id"], method["id"], item_count=2)
    assignment = assign_request(
        api, request["id"], examiner["id"], expected_version=request["version"]
    )
    return examiner, method, item, request, assignment


def test_bench_work_is_refused_when_the_clock_reaches_the_validation_expiry(api):
    """Nothing about the request, the examiner or the exhibit has changed, yet at exactly the
    expiry instant the method no longer supports work, and the refusal leaves the exhibit sealed
    in the vault with no checkout recorded.

    PRD §3.5: "So is the method: its `validation_status` must be `VALIDATED`, else
    `ERR_METHOD_NOT_VALIDATED`, and its `validation_expires_at_utc` must either be null or lie
    strictly after the logical clock, else `ERR_METHOD_VALIDATION_EXPIRED`."

    Design: Difficulty/cross_entity_state_dependency/start_analysis_blocked_by_lapsed_method_validation_on_a_third_entity
    """
    examiner, method, item, request, assignment = (
        _assigned_biology_request_whose_method_expires_on_the_first_of_september(api)
    )
    set_clock(api, "2026-09-01T00:00:00Z")

    response = api.start_analysis(request["id"], make_analyst_headers(examiner["id"]))
    validate_error(response, ERR_METHOD_VALIDATION_EXPIRED, expected_status=409)

    assert_fields(read_request(api, request["id"]), status="ASSIGNED")
    assert_fields(
        validate_success(api.get_evidence_item(item["id"], TECHNICIAN_HEADERS)),
        custody_status="IN_VAULT",
        checkout_count=0,
    )
    assert_fields(
        validate_success(api.get_assignment(assignment["id"], CASE_MANAGER_HEADERS)),
        status="ACTIVE",
    )
    assert_fields(
        validate_success(api.get_method(method["id"], QUALITY_MANAGER_HEADERS)),
        validation_status="VALIDATED",
    )


def test_one_second_before_the_expiry_the_exhibit_leaves_the_vault(api):
    """The comparison is strictly after, so with the clock a single second short of the expiry the
    same call is admitted: the request opens on the bench and the exhibit records its first
    checkout.

    PRD §3.5: "Starting analysis checks the property out of the vault. The item moves `IN_VAULT`
    → `IN_ANALYSIS` and its `checkout_count` increases by 1 — that counter records how many times
    the item has been checked out over its whole life, which is exactly once per revision round of
    the work performed on it."

    Design: Difficulty/cross_entity_state_dependency/start_analysis_blocked_by_lapsed_method_validation_on_a_third_entity
    """
    examiner, _method, item, request, _assignment = (
        _assigned_biology_request_whose_method_expires_on_the_first_of_september(api)
    )
    set_clock(api, "2026-08-31T23:59:59Z")

    start_analysis(api, request["id"], examiner["id"])

    assert_fields(read_request(api, request["id"]), status="IN_ANALYSIS")
    assert_fields(
        validate_success(api.get_evidence_item(item["id"], TECHNICIAN_HEADERS)),
        custody_status="IN_ANALYSIS",
        checkout_count=1,
    )
    reread = validate_success(api.get_analyst(examiner["id"], QUALITY_MANAGER_HEADERS))
    assert_two_decimal_value(
        reread["assigned_casework_hours"], 8.00, "assigned_casework_hours"
    )


def _latent_print_request_resting_in_technical_review(api):
    """A friction-ridge comparison finished at the bench and waiting on a peer signature, with the
    clock still at the pinned instant.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    examiner = register_analyst(
        api,
        full_name="Priya Raman",
        disciplines=["LATENT_PRINTS"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    reviewer = register_analyst(
        api,
        full_name="Owen Baptiste",
        disciplines=["LATENT_PRINTS"],
        competency_level=4,
        weekly_capacity_hours=40.00,
        training_hours_per_week=8.00,
    )
    method = create_validated_method(
        api,
        name="ACE-V Friction Ridge Comparison",
        discipline="LATENT_PRINTS",
        standard_hours_per_item=3.00,
        min_competency_level=3,
        max_items_per_request=6,
        is_consumptive=False,
        accreditation_scope_code="LP-ACEV-01",
        precision_cv_pct=1.50,
    )
    case = submit_case(
        api,
        agency_case_number="R-2026-1515",
        submitting_agency="METRO PD",
        offense_category="ROBBERY",
        suspect_in_custody=False,
    )
    item = log_evidence(
        api, case["id"], item_number="1", item_type="LATENT_LIFT", seal_intact=True
    )
    accept_case(api, case["id"])
    request = raise_request(api, case["id"], item["id"], method["id"], item_count=2)
    assign_request(
        api, request["id"], examiner["id"], expected_version=request["version"]
    )
    carry_to_tech_review(api, request["id"], examiner["id"], actual_hours=5.00)
    return examiner, reviewer, request


def _book_the_september_hearing(api, request_id, analyst_id):
    return api.create_court_event(
        court_event_payload(
            request_id,
            analyst_id,
            start_utc="2026-09-10T09:00:00Z",
            end_utc="2026-09-10T11:00:00Z",
            court_name="Superior Court Division 4",
            docket_number="CR-2026-2001",
        ),
        CASE_MANAGER_HEADERS,
    )


def test_no_hearing_may_be_booked_against_a_report_still_in_review(api):
    """The examiner and the hearing details are all admissible; what refuses the booking is the
    state of the request being testified to, and the refusal leaves the examiner's calendar empty.

    PRD §3.9: "The named request must be `RELEASED` — only released findings are testified to —
    and the named examiner must be that request's assigned analyst, else `ERR_REFERENTIAL_MISMATCH`;
    a colleague cannot be put on the stand for work they did not perform."

    Design: Difficulty/cross_entity_state_dependency/court_event_creation_gated_on_examination_request_release_state
    """
    examiner, _reviewer, request = _latent_print_request_resting_in_technical_review(api)

    response = _book_the_september_hearing(api, request["id"], examiner["id"])
    validate_error(response, ERR_EXAM_REQUEST_INVALID_STATE, expected_status=409)

    _rows, meta = validate_paginated(
        api.list_court_events(CASE_MANAGER_HEADERS, {"analyst_id": examiner["id"]})
    )
    assert_list_meta(meta, expected_total=0)


def test_once_the_two_reviews_release_the_report_the_same_booking_is_accepted(api):
    """Approval at administrative review is what releases the report, and with the request released
    the identical payload books a hearing forty whole days out from the unmoved clock.

    PRD §3.6: "Approval writes the administrative record, advances the request `ADMIN_REVIEW` →
    `RELEASED`, stamps `released_at_utc` from the logical clock and runs the case rollup, which is
    what moves `open_examination_request_count` down and `released_examination_request_count` up."

    Design: Difficulty/cross_entity_state_dependency/court_event_creation_gated_on_examination_request_release_state
    """
    examiner, reviewer, request = _latent_print_request_resting_in_technical_review(api)
    _book_the_september_hearing(api, request["id"], examiner["id"])

    technical_review(api, request["id"], reviewer["id"], "AGREE")
    administrative_review(api, request["id"], "APPROVE")

    released = read_request(api, request["id"])
    assert_fields(released, status="RELEASED")
    assert_instant_equals(
        released["released_at_utc"], "2026-08-01T00:00:00Z", "released_at_utc"
    )

    hearing = validate_success(
        _book_the_september_hearing(api, request["id"], examiner["id"]), 201
    )
    assert_fields(
        hearing,
        status="SCHEDULED",
        notice_days=40,
        subpoena_received=False,
        analyst_id=examiner["id"],
    )

    _rows, meta = validate_paginated(
        api.list_court_events(CASE_MANAGER_HEADERS, {"analyst_id": examiner["id"]})
    )
    assert_list_meta(meta, expected_total=1)
