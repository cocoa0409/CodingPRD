"""List pagination, FK-filtered lists, the 404 catalogue, the error envelope,
and immediate read-after-write visibility."""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_instant,
    factories,
    fixtures,
)
from test_helpers.test_users import PROGRAM_OFFICE_HEADERS, TRANSITION_COUNSELOR_HEADERS


def test_pagination_limit_offset_total(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to
    return. If not provided, it defaults to 10, with a minimum of 1 and a maximum
    of 100. The `offset` parameter specifies the number of items to skip and
    defaults to 0."
    PRD §2.3: "Paginated and non-paginated list-based responses include the
    following fields in the `meta` object of the response envelope: `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/pagination_limit_offset_total
    """
    w = fixtures.setup_members_with_approved_applications(api, 2)
    app_ids = {w.applications[0]["id"], w.applications[1]["id"]}

    page1, meta1 = validate_paginated(api.list_applications(PROGRAM_OFFICE_HEADERS, params={"limit": 1, "offset": 0}))
    assert len(page1) == 1
    assert meta1["total_count"] == 2 and meta1["has_more"] is True

    page2, meta2 = validate_paginated(api.list_applications(PROGRAM_OFFICE_HEADERS, params={"limit": 1, "offset": 1}))
    assert len(page2) == 1
    assert meta2["total_count"] == 2 and meta2["has_more"] is False

    assert {page1[0]["id"], page2[0]["id"]} == app_ids, "the two pages partition the collection"


def test_filtered_list_returns_only_matching(api):
    """PRD §2.3: "The service-member list filters by `home_installation_id` and
    `service_status`; the application list filters by `service_member_id`,
    `installation_id`, and `status`; the opening list filters by `employer_id` and
    `status`; the match list filters by `internship_application_id`,
    `employer_opening_id`, `service_member_id`, `employer_id`, `installation_id`,
    and `match_status`."

    Design: Corner/endpoints/filtered_list_returns_only_matching
    """
    w = fixtures.setup_member_with_application(api)
    employer_a = fixtures.create_authorized_employer(api)
    employer_b = fixtures.create_authorized_employer(api, legal_name="Beacon Retail Group", industry_code="RET")
    opening_a = fixtures.create_opening(api, employer_a["id"])
    opening_b = fixtures.create_opening(api, employer_b["id"], title="Store Ops Intern")
    match = fixtures.propose_match(api, w.application["id"], opening_a["id"])

    mine, meta_mine = validate_paginated(
        api.list_matches(PROGRAM_OFFICE_HEADERS, params={"employer_opening_id": opening_a["id"]})
    )
    assert [m["id"] for m in mine] == [match["id"]] and meta_mine["total_count"] == 1

    other, meta_other = validate_paginated(
        api.list_matches(PROGRAM_OFFICE_HEADERS, params={"employer_opening_id": opening_b["id"]})
    )
    assert other == [] and meta_other["total_count"] == 0


def _assert_error_envelope(resp, error_id):
    body = resp.json()
    assert body.get("response_type") == "error"
    assert isinstance(body["meta"].get("api_request_id"), str)
    return validate_error(resp, error_id)


def test_not_found_catalog(api):
    """PRD §2.7: "Resource ids in the URL path exist, validated strictly left to
    right; the first missing id yields its resource-specific 404:
    `ERR_INSTALLATION_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_EMPLOYER_NOT_FOUND`, `ERR_OPENING_NOT_FOUND`,
    `ERR_MATCH_NOT_FOUND`, or `ERR_AUDIT_NOT_FOUND`."
    PRD §2.7: "Ids supplied in the request body exist, validated in the body's
    declared input order — on a match proposal, `internship_application_id` first,
    then `employer_opening_id` — with the same resource-specific 404 family."

    Design: Corner/endpoints/not_found_catalog
    """
    fixtures.create_employer(api, legal_name="Sentinel Corp", industry_code="DEF")

    cases = [
        (api.get_service_member(NON_EXISTENT_UUID, PROGRAM_OFFICE_HEADERS), ApiErrorId.ERR_MEMBER_NOT_FOUND),
        (api.get_application(NON_EXISTENT_UUID, PROGRAM_OFFICE_HEADERS), ApiErrorId.ERR_APPLICATION_NOT_FOUND),
        (api.get_employer(NON_EXISTENT_UUID, PROGRAM_OFFICE_HEADERS), ApiErrorId.ERR_EMPLOYER_NOT_FOUND),
        (api.get_opening(NON_EXISTENT_UUID, PROGRAM_OFFICE_HEADERS), ApiErrorId.ERR_OPENING_NOT_FOUND),
        (api.get_match(NON_EXISTENT_UUID, PROGRAM_OFFICE_HEADERS), ApiErrorId.ERR_MATCH_NOT_FOUND),
        (api.close_audit(NON_EXISTENT_UUID, {}, PROGRAM_OFFICE_HEADERS), ApiErrorId.ERR_AUDIT_NOT_FOUND),
    ]
    for resp, error_id in cases:
        _assert_error_envelope(resp, error_id)

    ghost_home = api.create_service_member(
        factories.create_service_member_payload(
            full_name="Ghost Post", home_installation_id=NON_EXISTENT_UUID
        ),
        TRANSITION_COUNSELOR_HEADERS,
    )
    _assert_error_envelope(ghost_home, ApiErrorId.ERR_INSTALLATION_NOT_FOUND)


def test_immediate_visibility_after_mutations(api):
    """PRD §2.10: "State changes propagate along three cascade chains, and every
    mutation plus all of its cascades commits atomically within the triggering
    request or clock-set call."
    PRD §3.2: "Either decision stamps `decided_by_user_id` with the commander's
    `X-User-ID`, `decided_at` with the logical clock, and `decision_reason` with
    the supplied reason, and increments the application's `version` by 1."

    Design: Corner/consistency_model/immediate_visibility_after_mutations
    """
    w = fixtures.setup_member_with_application(api, approve=False)
    eo = fixtures.setup_employer_with_opening(api)

    fresh = fixtures.get_application(api, w.application["id"])
    assert fresh["status"] == "SUBMITTED"

    fixtures.approve_application(api, w.application["id"], commander_id="cmd-1")
    decided = fixtures.get_application(api, w.application["id"])
    assert decided["status"] == "APPROVED"
    assert decided["decided_by_user_id"] == "cmd-1"
    assert_instant(decided["decided_at"], "2026-09-01T00:00:00Z", "decided_at")

    match = fixtures.propose_match(api, w.application["id"], eo.opening["id"])
    listed, meta = validate_paginated(
        api.list_matches(PROGRAM_OFFICE_HEADERS, params={"employer_opening_id": eo.opening["id"]})
    )
    assert [m["id"] for m in listed] == [match["id"]] and meta["total_count"] == 1
