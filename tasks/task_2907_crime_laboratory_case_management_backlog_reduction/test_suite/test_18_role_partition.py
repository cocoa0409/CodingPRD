"""The five roles partition the exclusive operations with no hierarchy anywhere, and the shared reads
are not uniformly shared either.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.api_errors import ERR_UNAUTHORIZED
from test_helpers.assertions import assert_fields, assert_list_meta
from test_helpers.factories import (
    administrative_review_payload,
    analyst_payload,
    case_payload,
    method_validation_payload,
    technical_review_payload,
)
from test_helpers.fixtures import (
    accept_case,
    create_method,
    create_validated_method,
    log_evidence,
    raise_request,
    read_request,
    set_clock,
    submit_case,
)
from test_helpers.test_users import (
    CASE_MANAGER_HEADERS,
    DIRECTOR_HEADERS,
    QUALITY_MANAGER_HEADERS,
    TECHNICIAN_HEADERS,
    make_analyst_headers,
)

# An identifier in the Analyst role's own header space; the role checks below are decided
# before any identity binding, so it never has to name a persisted examiner.
BENCH_CALLER_ID = "00000000-0000-4000-8000-0000000e0021"


def test_no_role_may_reach_across_the_partition_in_either_direction(api):
    """The director is refused the technical review, the quality manager the administrative release,
    the case manager method validation, the technician examiner registration and the bench examiner
    case intake — every one a 403 that leaves the draft method, the queued request and the case list
    exactly as they were. The list read is shared with four roles and refused to the bench, while the
    single-case read is shared with all five.

    PRD §2.1: "If `X-User-Role` carries a value that is not one of those five strings, or carries a
    recognised role that the requested endpoint does not authorise, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    PRD §2.1: "A `QualityManager` owns the quality system: validating and retiring methods, running
    proficiency testing, resolving technical disagreements, opening findings, deciding corrective-action
    plans, and reinstating suspended examiners — and never performs or administratively releases
    casework."

    PRD §2.1: "A `LabDirector` owns the personnel and vendor registries, sets queue-class overrides, and
    drives the logical clock; the director is deliberately not authorised for administrative review,
    technical review or corrective-action decisions, so that no single role can both create and release
    casework."

    PRD §4: "Every request must present the `X-User-ID` and `X-User-Role` headers of §2.1, and the
    Authorized Role(s) column lists the roles permitted to call that endpoint; any other role is
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/cross_role_exclusive_operations_are_unauthorized_in_both_directions
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    draft_method = create_method(
        api,
        name="Draft Scope Method",
        discipline="BIOLOGY",
        standard_hours_per_item=4.00,
        min_competency_level=2,
        accreditation_scope_code="BIO-DSC-01",
    )
    served_method = create_validated_method(
        api,
        name="Validated Scope Method",
        discipline="BIOLOGY",
        standard_hours_per_item=4.00,
        min_competency_level=2,
        max_items_per_request=6,
        accreditation_scope_code="BIO-VSC-01",
        validation_study_item_count=20,
        precision_cv_pct=2.00,
    )
    case = submit_case(
        api,
        agency_case_number="O-2026-0509",
        submitting_agency="METRO PD",
        offense_category="OTHER",
    )
    item = log_evidence(
        api,
        case["id"],
        item_number="1",
        item_description="Sealed swab",
        item_type="BIOLOGICAL",
        seal_intact=True,
    )
    accept_case(api, case["id"])
    request = raise_request(api, case["id"], item["id"], served_method["id"], item_count=1)

    bench_headers = make_analyst_headers(BENCH_CALLER_ID)
    refusals = [
        api.create_analyst(
            analyst_payload(
                full_name="Technician Created Examiner",
                disciplines=["BIOLOGY"],
                weekly_capacity_hours=40.00,
            ),
            TECHNICIAN_HEADERS,
        ),
        api.validate_method(
            draft_method["id"],
            method_validation_payload(
                validation_study_item_count=20,
                precision_cv_pct=2.00,
                expires_at_utc="2027-08-01T00:00:00Z",
            ),
            CASE_MANAGER_HEADERS,
        ),
        api.administrative_review(
            request["id"],
            administrative_review_payload(
                "APPROVE", "Quality manager releasing casework"
            ),
            QUALITY_MANAGER_HEADERS,
        ),
        api.technical_review(
            request["id"],
            technical_review_payload("AGREE", "Director reviewing casework"),
            DIRECTOR_HEADERS,
        ),
        api.create_case(
            case_payload(
                agency_case_number="O-2026-0510",
                submitting_agency="METRO PD",
                offense_category="OTHER",
            ),
            bench_headers,
        ),
    ]
    for refusal in refusals:
        validate_error(refusal, ERR_UNAUTHORIZED, 403)

    assert_fields(
        validate_success(api.get_method(draft_method["id"], QUALITY_MANAGER_HEADERS)),
        validation_status="DRAFT",
    )
    assert_fields(read_request(api, request["id"]), status="QUEUED")
    _records, record_meta = validate_paginated(
        api.list_review_records(
            CASE_MANAGER_HEADERS, {"examination_request_id": request["id"]}
        )
    )
    assert_list_meta(record_meta, expected_total=0)

    validate_error(api.list_cases(bench_headers), ERR_UNAUTHORIZED, 403)
    for headers in (
        TECHNICIAN_HEADERS,
        CASE_MANAGER_HEADERS,
        QUALITY_MANAGER_HEADERS,
        DIRECTOR_HEADERS,
    ):
        _rows, meta = validate_paginated(api.list_cases(headers))
        assert_list_meta(meta, expected_total=1)

    assert_fields(
        validate_success(api.get_case(case["id"], bench_headers)),
        agency_case_number="O-2026-0509",
    )
