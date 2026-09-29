"""The two taxonomies that must not collapse: one not-found code per entity family, and the split
between an unauthenticated caller and an unauthorised one — both decided before the addressed row is
ever looked up.
"""

from typing import Any

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import (
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_COURT_EVENT_NOT_FOUND,
    ERR_EXAM_REQUEST_NOT_FOUND,
    ERR_NONCONFORMANCE_NOT_FOUND,
    ERR_PROFICIENCY_TEST_NOT_FOUND,
    ERR_REVIEW_RECORD_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    ERR_VENDOR_ENGAGEMENT_NOT_FOUND,
    ERR_VENDOR_NOT_FOUND,
)
from test_helpers.factories import method_retirement_payload
from test_helpers.fixtures import set_clock
from test_helpers.test_users import (
    CASE_MANAGER_HEADERS,
    DIRECTOR_HEADERS,
    QUALITY_MANAGER_HEADERS,
    ROLE_ANALYST,
    TECHNICIAN_HEADERS,
    headers_with_empty_user_id,
    headers_without_role,
    make_unrecognised_role_headers,
)

# Well-formed identifiers that name no persisted row, one per entity family under test.
MISSING_EXAM_REQUEST_ID = "00000000-0000-4000-8000-0000000e0001"
MISSING_ASSIGNMENT_ID = "00000000-0000-4000-8000-0000000e0002"
MISSING_REVIEW_RECORD_ID = "00000000-0000-4000-8000-0000000e0003"
MISSING_PROFICIENCY_TEST_ID = "00000000-0000-4000-8000-0000000e0004"
MISSING_VENDOR_ID = "00000000-0000-4000-8000-0000000e0005"
MISSING_VENDOR_ENGAGEMENT_ID = "00000000-0000-4000-8000-0000000e0006"
MISSING_NONCONFORMANCE_ID = "00000000-0000-4000-8000-0000000e0007"
MISSING_COURT_EVENT_ID = "00000000-0000-4000-8000-0000000e0008"
MISSING_METHOD_ID = "00000000-0000-4000-8000-0000000e0012"


def _reported_error_id(response: Any) -> str:
    """The machine-readable code an error envelope carries in its data block."""
    return response.json()["data"]["error_id"]


def test_each_entity_family_answers_an_unknown_identifier_with_its_own_code(api):
    """Eight reads of eight absent rows produce eight different codes, all at 404 — no family
    borrows another's code and none of them reports a bad request instead.

    PRD §2.9: "Each entity has its own not-found code: `ERR_ANALYST_NOT_FOUND`,
    `ERR_METHOD_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_EVIDENCE_ITEM_NOT_FOUND`,
    `ERR_EXAM_REQUEST_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_REVIEW_RECORD_NOT_FOUND`,
    `ERR_PROFICIENCY_TEST_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_VENDOR_ENGAGEMENT_NOT_FOUND`,
    `ERR_NONCONFORMANCE_NOT_FOUND` and `ERR_COURT_EVENT_NOT_FOUND`. Each is returned with HTTP 404,
    and each covers both a path segment and a body reference naming that entity — so an `analyst_id`
    supplied in a request body that resolves to nothing is also `ERR_ANALYST_NOT_FOUND`."

    Design: Corner/errors/unknown_ids_return_the_not_found_code_of_each_entity_family
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    probes = [
        (
            api.get_examination_request(MISSING_EXAM_REQUEST_ID, DIRECTOR_HEADERS),
            ERR_EXAM_REQUEST_NOT_FOUND,
        ),
        (
            api.get_assignment(MISSING_ASSIGNMENT_ID, DIRECTOR_HEADERS),
            ERR_ASSIGNMENT_NOT_FOUND,
        ),
        (
            api.get_review_record(MISSING_REVIEW_RECORD_ID, DIRECTOR_HEADERS),
            ERR_REVIEW_RECORD_NOT_FOUND,
        ),
        (
            api.get_proficiency_test(
                MISSING_PROFICIENCY_TEST_ID, QUALITY_MANAGER_HEADERS
            ),
            ERR_PROFICIENCY_TEST_NOT_FOUND,
        ),
        (api.get_vendor(MISSING_VENDOR_ID, DIRECTOR_HEADERS), ERR_VENDOR_NOT_FOUND),
        (
            api.get_vendor_engagement(
                MISSING_VENDOR_ENGAGEMENT_ID, CASE_MANAGER_HEADERS
            ),
            ERR_VENDOR_ENGAGEMENT_NOT_FOUND,
        ),
        (
            api.get_nonconformance(MISSING_NONCONFORMANCE_ID, QUALITY_MANAGER_HEADERS),
            ERR_NONCONFORMANCE_NOT_FOUND,
        ),
        (
            api.get_court_event(MISSING_COURT_EVENT_ID, CASE_MANAGER_HEADERS),
            ERR_COURT_EVENT_NOT_FOUND,
        ),
    ]

    observed = []
    for response, expected_code in probes:
        validate_error(response, expected_code, 404)
        observed.append(_reported_error_id(response))

    assert len(set(observed)) == len(observed), (
        f"Each entity family must own a distinct not-found code, got {observed}"
    )


def test_a_missing_credential_and_an_unusable_role_are_separated_by_cause(api):
    """An absent role header and an empty identity header are both authentication failures, while an
    unrecognised role and a role the endpoint does not authorise are both authorisation failures —
    and the two write attempts address rows that do not exist, yet still report the auth code.

    PRD §2.1: "If either header is absent, or is supplied as an empty string, the request is rejected
    with `ERR_UNAUTHENTICATED` (HTTP 401). A header consisting only of an empty value counts as
    absent for this purpose."

    PRD §2.1: "If `X-User-Role` carries a value that is not one of those five strings, or carries a
    recognised role that the requested endpoint does not authorise, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403). Authorisation outranks payload validity, so an unrecognised role
    never produces a 400 — it produces the 403."

    PRD §2.8: "**Path identifiers.** Every identifier segment in the URL resolves to an existing row
    of its declared entity, checked left to right, else the entity's own not-found code (404)."

    Design: Corner/errors/absent_headers_and_unlisted_roles_are_rejected_before_any_state_check
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    validate_error(api.list_cases(headers_without_role()), ERR_UNAUTHENTICATED, 401)
    validate_error(
        api.start_analysis(
            MISSING_EXAM_REQUEST_ID, headers_with_empty_user_id(ROLE_ANALYST)
        ),
        ERR_UNAUTHENTICATED,
        401,
    )
    validate_error(
        api.list_cases(make_unrecognised_role_headers()), ERR_UNAUTHORIZED, 403
    )
    validate_error(
        api.retire_method(
            MISSING_METHOD_ID,
            method_retirement_payload("Role not on this endpoint"),
            TECHNICIAN_HEADERS,
        ),
        ERR_UNAUTHORIZED,
        403,
    )
