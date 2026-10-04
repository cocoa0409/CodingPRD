"""Creation semantics: initial states, server-managed fields, intake
uniqueness, and enum validation for the registry surface."""
import pytest

from test_helpers import (
    api_client,
    fixtures,
    factories,
    TEST_USERS,
    make_applicant_headers,
    validate_success,
    validate_error,
    is_valid_uuid,
    is_iso8601_timestamp,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_funding_opportunity,
    assert_application,
    assert_reviewer,
)

_PO = TEST_USERS["program_officer_headers"]
_SRO = TEST_USERS["sro_headers"]


def test_foa_create_returns_open_with_server_fields():
    """PRD §3.1: "A new announcement starts `OPEN`."
    PRD §4: "Operations that create a new resource — announcements, institutes, institutions, applicants, applications, study sections, reviewers, assignments, council reviews, awards, progress reports, modifications, and transfer requests — return a `201 Created` status code."
    PRD §2.5: "a `version`, an integer that increments by one on every mutation of the resource — including automatic transitions the server performs on it, such as quorum-driven flips, score release outcomes, funding decisions, and expiry cascades."
    Note: the PRD pins the increment-by-one semantics of `version` but never
    pins its value at creation, so this test asserts only a positive integer
    version rather than a literal starting number.

    Design: Corner/entities/foa_create_returns_open_with_server_fields
    """
    payload = factories.create_funding_opportunity_payload(
        pa_number="PA-26-201",
        title="R01 Base FOA",
        activity_code="R01",
        research_strategy_page_limit=12,
        min_direct_cents_per_year=1_000_000,
        max_direct_cents_per_year=25_000_000,
        max_years=5,
        open_date="2026-08-01T00:00:00Z",
        receipt_deadline="2026-12-01T00:00:00Z",
    )
    resp = api_client.create_funding_opportunity(payload, _PO)
    data = validate_success(resp, 201)
    assert_funding_opportunity(data)
    assert data["status"] == "OPEN", f"new announcement must start OPEN, got {data['status']}"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert data["activity_code"] == "R01"
    assert data["research_strategy_page_limit"] == 12
    assert data["pa_number"] == "PA-26-201"
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])


def test_application_create_body_applicant_id_input_ignored():
    """PRD §3.1: "The drafting applicant's identity comes from the request context: `applicant_id` is taken from `X-User-ID`, never from the request body."
    PRD §3.1: "Two boolean flags, `human_subjects_involved` and `vertebrate_animals_involved`, default to false and drive both certification gates and later just-in-time requirements."
    PRD §3.1: "The applicant may also express referral preferences through `requested_study_section_id` and `requested_institute_id` (both optional and advisory), and may name reviewers to avoid in `excluded_reviewer_ids` (defaulting to an empty list, with no existence check at creation)."
    PRD §3.1: "A draft starts in `DRAFT` status with `study_section_id` and `institute_id` unset, `live_assignment_count` at zero, and `impact_score`, `approach_mean`, `significance_mean`, `innovation_mean`, `percentile_raw`, and `percentile_normalized` all null until scoring."

    Design: Corner/entities/application_create_body_applicant_id_input_ignored
    """
    ctx = fixtures.make_review_context()
    pi_a = fixtures.make_applicant()
    payload = factories.create_application_payload(
        ctx["foa"]["id"], ctx["institution"]["id"],
        title="Defaults app",
        applicant_id=NON_EXISTENT_UUID,  # body value must be ignored
    )
    resp = api_client.create_application(payload, make_applicant_headers(pi_a["id"]))
    data = validate_success(resp, 201)
    assert_application(data)
    assert data["applicant_id"] == pi_a["id"], (
        f"applicant_id must come from X-User-ID, got {data['applicant_id']!r}"
    )
    assert data["human_subjects_involved"] is False
    assert data["vertebrate_animals_involved"] is False
    assert data["excluded_reviewer_ids"] == []
    assert data["status"] == "DRAFT"
    assert data["live_assignment_count"] == 0


def test_application_computed_score_fields_input_ignored():
    """PRD §3.1: "A draft starts in `DRAFT` status with `study_section_id` and `institute_id` unset, `live_assignment_count` at zero, and `impact_score`, `approach_mean`, `significance_mean`, `innovation_mean`, `percentile_raw`, and `percentile_normalized` all null until scoring."

    Design: Corner/entities/application_computed_score_fields_input_ignored
    """
    ctx = fixtures.make_review_context()
    pi_a = fixtures.make_applicant()
    payload = factories.create_application_payload(
        ctx["foa"]["id"], ctx["institution"]["id"],
        title="Computed app",
        impact_score=10,      # client-supplied computed fields must not stick
        percentile_raw=1.0,
    )
    resp = api_client.create_application(payload, make_applicant_headers(pi_a["id"]))
    data = validate_success(resp, 201)
    assert data["impact_score"] is None, "client-supplied impact_score must be ignored"
    assert data["percentile_raw"] is None
    assert data["percentile_normalized"] is None


def test_get_application_unknown_id_returns_404():
    """PRD §2.7: "Every resource id in the URL path must exist, validated in left-to-right order; the request is rejected with the not-found error (HTTP 404) of the *first* missing id, and a nested path under a missing parent never evaluates the child."
    PRD §2.7: "The not-found family is: `ERR_FOA_NOT_FOUND`, `ERR_INSTITUTE_NOT_FOUND`, `ERR_INSTITUTION_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_STUDY_SECTION_NOT_FOUND`, `ERR_REVIEWER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_JIT_REQUEST_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`, `ERR_PROGRESS_REPORT_NOT_FOUND`, `ERR_MODIFICATION_NOT_FOUND`, `ERR_TRANSFER_REQUEST_NOT_FOUND`."

    Design: Corner/entities/get_application_unknown_id_returns_404
    """
    resp = api_client.get_application(NON_EXISTENT_UUID, _PO)
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_FOUND)


def test_duplicate_pa_number_rejected():
    """PRD §3.1: "The announcement carries a `pa_number` that must be unique across all funding opportunities — a duplicate is rejected with `ERR_DUPLICATE_PA_NUMBER`"

    Design: Corner/entities/duplicate_pa_number_rejected
    """
    first = factories.create_funding_opportunity_payload(pa_number="PA-26-204", title="First")
    api_client.create_funding_opportunity(first, _PO)
    second = factories.create_funding_opportunity_payload(
        pa_number="PA-26-204", title="Second", activity_code="R21",
        research_strategy_page_limit=6, min_direct_cents_per_year=500_000,
        max_direct_cents_per_year=10_000_000, max_years=2,
    )
    resp = api_client.create_funding_opportunity(second, _PO)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PA_NUMBER)


def test_duplicate_application_per_foa_rejected():
    """PRD §3.1: "An applicant may hold only one non-terminal application per announcement: a second draft against the same `foa_id` while an earlier application of the same applicant is not yet `AWARDED`, `NOT_FUNDED`, `UNSCORED`, or `WITHDRAWN` is rejected with `ERR_DUPLICATE_APPLICATION`."

    Design: Corner/entities/duplicate_application_per_foa_rejected
    """
    ctx = fixtures.make_review_context()
    pi_a = fixtures.make_applicant()
    pi_b = fixtures.make_applicant()
    fixtures.make_draft_application(ctx["foa"]["id"], ctx["institution"]["id"], pi_a["id"],
                                    title="First")
    resp_dup = api_client.create_application(
        factories.create_application_payload(ctx["foa"]["id"], ctx["institution"]["id"],
                                             title="Second"),
        make_applicant_headers(pi_a["id"]))
    validate_error(resp_dup, ApiErrorId.ERR_DUPLICATE_APPLICATION)
    resp_other = api_client.create_application(
        factories.create_application_payload(ctx["foa"]["id"], ctx["institution"]["id"],
                                             title="Other applicant"),
        make_applicant_headers(pi_b["id"]))
    data = validate_success(resp_other, 201)
    assert data["status"] == "DRAFT"


def test_invalid_activity_code_rejected():
    """PRD §3.1: "an `activity_code` naming the grant mechanism (`R01`, `R21`, or `R03`)"
    PRD §2.7: "Separately from this pipeline, malformed payloads — a missing required field, a wrong type, an enum value outside its declared set, a criterion score outside 1 through 9, a `budget_cut_pct` outside zero to 0.30, a `new_end_date` that is not after the award's current `end_date`, or a `start_date`/`effective_date` earlier than the logical clock — are rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/invalid_activity_code_rejected
    """
    payload = factories.create_funding_opportunity_payload(
        pa_number="PA-26-206", title="Bad enum", activity_code="R99")
    resp = api_client.create_funding_opportunity(payload, _PO)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_reviewer_created_invited_initial_state():
    """PRD §3.4: "the reviewer starts `INVITED` with an empty `declared_conflicts` list and an `active_assignment_count` of zero."

    Design: Corner/entities/reviewer_created_invited_initial_state
    """
    inst = fixtures.make_institution(name="Other College")
    resp = api_client.create_reviewer(
        factories.create_reviewer_payload(inst["id"], full_name="Rev X",
                                          expertise_keywords=["neuro"]),
        _SRO)
    data = validate_success(resp, 201)
    assert_reviewer(data)
    assert data["status"] == "INVITED"
    assert data["active_assignment_count"] == 0
    assert data["declared_conflicts"] == []
