"""Corner queue — endpoint surface (PRD §2.2, §2.3, §3.1, §3.6, §3.7).

Pagination envelope, filter isolation, the success/error envelope shape,
and the pinned per-pathway special conditions on issued permits.
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    SPECIAL_CONDITIONS_GENERAL,
    SPECIAL_CONDITIONS_INDIVIDUAL,
    assert_permit,
    assert_permit_conditions_for_pathway,
    create_applicant,
    create_application,
    create_plan,
    create_site,
    impact_line,
    parse_iso8601,
    setup_aa_accepted,
    setup_issued_general_permit,
    setup_issued_permit,
    setup_site_with_issued_jd,
    validate_error,
    validate_paginated,
    validate_success,
    walk_application_to_alternatives_review,
)


def test_corner_list_pagination_envelope(api, reviewer_headers):
    """PRD §2.3: "Every list endpoint accepts two optional query parameters:
    `limit`, which defaults to 10 and must be at least 1 and at most 100, and
    `offset`, which defaults to 0. The `meta` object of a list response
    carries `limit`, `offset`, `total_count`, and `has_more`. Unless an
    endpoint's description pins a different key, list results are sorted by
    `created_at` ascending."

    limit=2 over 3 sites: page 1 has 2 rows with has_more true; offset=2
    returns the remaining row with has_more false; the concatenation is
    created_at non-decreasing.

    Design: Corner/endpoints/corner_list_pagination_envelope
    """
    applicant = create_applicant()
    site_ids = set()
    for i, name in enumerate(("Tract A", "Tract B", "Tract C")):
        site = create_site(
            applicant, site_name=name, watershed_code=f"1802010{i + 1}",
            total_acres=10.0 + i, resource_types_present=["STREAM"],
        )
        site_ids.add(site["id"])

    page1, meta1 = validate_paginated(
        api.list_sites(reviewer_headers, params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2 and meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api.list_sites(reviewer_headers, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert meta2["offset"] == 2

    rows = page1 + page2
    assert {r["id"] for r in rows} == site_ids, "the pages partition the roster"
    stamps = [parse_iso8601(r["created_at"]) for r in rows]
    assert stamps == sorted(stamps), "rows are sorted by created_at ascending"


def test_corner_filtered_list_isolation(api, reviewer_headers):
    """PRD §3.6: "Transactions can be listed with optional `bank_id`,
    `plan_id`, `resource_type`, and `status` filters; plans with optional
    `application_id`, `mechanism`, and `status` filters."

    The application_id filter isolates one application's plan; the sibling
    application's plan never appears.

    Design: Corner/endpoints/corner_filtered_list_isolation
    """
    applicant, site, jd = setup_site_with_issued_jd()

    app_a = create_application(
        site, jd, applicant, impacts=[impact_line("FORESTED_WETLAND", 1.0)],
        project_purpose="Project A", estimated_cost_dollars=300000.0,
    )
    app_a = walk_application_to_alternatives_review(app_a, applicant)
    ctx_a = setup_aa_accepted({"applicant": applicant, "site": site, "jd": jd, "app": app_a})
    plan_a = create_plan(ctx_a["app"], applicant, mechanism="BANK_CREDITS")

    app_b = create_application(
        site, jd, applicant, impacts=[impact_line("STREAM", 1.0)],
        project_purpose="Project B", estimated_cost_dollars=200000.0,
    )
    app_b = walk_application_to_alternatives_review(app_b, applicant)
    ctx_b = setup_aa_accepted({"applicant": applicant, "site": site, "jd": jd, "app": app_b})
    plan_b = create_plan(ctx_b["app"], applicant, mechanism="IN_LIEU_FEE")

    data, meta = validate_paginated(
        api.list_mitigation_plans(
            reviewer_headers, params={"application_id": ctx_a["app"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["id"] == plan_a["id"]
    assert plan_b["id"] not in {row["id"] for row in data}


def test_corner_success_and_error_envelope_shape(api, system_admin_headers):
    """PRD §2.2: "The `api_request_id` is a server-generated unique
    identifier for the request that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource
    or "array" for a list of resources."
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `message` provides a human-readable explanation of what
    went wrong."

    Design: Corner/endpoints/corner_success_and_error_envelope_shape
    """
    applicant = create_applicant()

    resp = api.get_applicant(applicant["id"], system_admin_headers)
    data = validate_success(resp)
    body = resp.json()
    assert body["response_type"] == "object"
    request_id = body["meta"]["api_request_id"]
    assert isinstance(request_id, str) and request_id.startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert data["id"] == applicant["id"]

    resp = api.get_applicant(NON_EXISTENT_UUID, system_admin_headers)
    err = validate_error(resp, ApiErrorId.ERR_APPLICANT_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(err["message"], str) and err["message"], (
        "error responses carry a non-empty human-readable message"
    )
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}


def test_corner_permit_conditions_by_pathway(api):
    """PRD §3.7: "Its `special_conditions` are pinned by pathway and never
    vary: general-pathway permits carry exactly "SC-GP-01: Erosion and
    sediment controls must be maintained for the duration of the authorized
    work" and "SC-GP-02: Work must be completed within the general permit
    activity limits", while individual-pathway permits carry exactly
    "SC-IP-01: Five years of mitigation monitoring reports are required",
    "SC-IP-02: Long-term stewardship must be maintained by the designated
    stewardship entity", and "SC-IP-03: Compensatory mitigation must remain
    secured for the life of the project"."
    PRD §3.7: "is stamped with a `permit_number` formed as `WP-` followed by
    a four-digit zero-padded sequential count of issued permits starting at
    1 — the first permit is `WP-0001`, and the number is count-based, never
    derived from any identifier".

    The GENERAL permit issued first is WP-0001 with the two SC-GP strings;
    the INDIVIDUAL permit issued second is WP-0002 with the three SC-IP
    strings.

    Design: Corner/endpoints/corner_permit_conditions_by_pathway
    """
    ctx_gen = setup_issued_general_permit()
    permit_gen = ctx_gen["permit"]
    assert_permit(permit_gen)
    assert permit_gen["permit_number"] == "WP-0001"
    assert permit_gen["special_conditions"] == SPECIAL_CONDITIONS_GENERAL

    ctx_ind = setup_issued_permit()
    permit_ind = ctx_ind["permit"]
    assert_permit(permit_ind)
    assert permit_ind["permit_number"] == "WP-0002"
    assert permit_ind["special_conditions"] == SPECIAL_CONDITIONS_INDIVIDUAL
    assert_permit_conditions_for_pathway(permit_ind, "INDIVIDUAL")
