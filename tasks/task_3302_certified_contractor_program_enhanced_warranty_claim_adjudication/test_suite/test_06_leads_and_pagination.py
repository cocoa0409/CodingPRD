"""Lead assignment rules: pool exhaustion, tier requirements, pagination."""
from test_helpers import (
    ApiErrorId,
    assign_lead,
    create_distributor_payload,
    create_lead_assignment_payload,
    create_training_course_payload,
    get_success_data,
    make_certified_contractor,
    make_distributor_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_lead_pool_exhausted_returns_pool_empty(api, program_admin_headers):
    """PRD §3.8: "Finally, the pool itself must not be empty: assigning when
    `lead_pool_available` is 0 is refused with `ERR_LEAD_POOL_EMPTY` (HTTP 422)."

    Design: Corner/validations/lead_pool_exhausted_returns_pool_empty
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = make_certified_contractor(tier="BRONZE", territory_codes=["T1", "T2"])
    contractor = ctx["contractor"]
    dist = get_success_data(api.create_distributor(
        create_distributor_payload(name="Dist X", territory_codes=["T1", "T2"], lead_pool_total=1),
        program_admin_headers))
    assign_lead(dist["id"], contractor["id"], territory_code="T1")
    resp = api.create_lead_assignment(
        create_lead_assignment_payload(
            distributor_id=dist["id"],
            contractor_id=contractor["id"],
            territory_code="T2",
            start_date="2027-01-01",
            end_date="2027-02-01",
        ),
        make_distributor_headers(dist["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LEAD_POOL_EMPTY)


def test_tier_requirement_not_met_for_lead_rejected(api, program_admin_headers):
    """PRD §3.8: "The assignment is refused with `ERR_TIER_REQUIREMENT_NOT_MET`
    (HTTP 422) unless all of the following hold: the contractor is `ACTIVE`... the
    `territory_code` appears in both the distributor's and the contractor's
    `territory_codes`, and the contractor holds an `ACTIVE` certification whose tier
    ranks at or above the `required_tier`."

    Design: Corner/validations/tier_requirement_not_met_for_lead_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = make_certified_contractor(tier="BRONZE")
    contractor = ctx["contractor"]
    dist = get_success_data(api.create_distributor(
        create_distributor_payload(name="Dist T2", territory_codes=["T1"], lead_pool_total=1),
        program_admin_headers))
    resp = api.create_lead_assignment(
        create_lead_assignment_payload(
            distributor_id=dist["id"],
            contractor_id=contractor["id"],
            required_tier="SILVER",
        ),
        make_distributor_headers(dist["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TIER_REQUIREMENT_NOT_MET)


def test_enrollment_list_pagination_defaults_and_offset(api, program_admin_headers):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; when
    omitted it defaults to 10, and any supplied value must fall between 1 and 100
    inclusive. The `offset` parameter specifies how many items to skip and defaults
    to 0. ... The `meta` object of a list response carries the pagination fields
    `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/enrollment_list_pagination_defaults_and_offset
    """
    from test_helpers import create_contractor_payload

    contractor = get_success_data(api.create_contractor(
        create_contractor_payload(legal_name="Page Co", license_number="LIC-PG"), program_admin_headers))
    course = get_success_data(api.create_training_course(
        create_training_course_payload(title="Basics", credits=4, validity_months=36), program_admin_headers))
    for _ in range(12):
        get_success_data(api.create_training_enrollment(
            {"contractor_id": contractor["id"], "course_id": course["id"]}, program_admin_headers))

    items1, meta1 = validate_paginated(api.list_training_enrollments(program_admin_headers))
    assert len(items1) == 10
    assert meta1["total_count"] == 12
    assert meta1["has_more"] is True
    assert meta1["limit"] == 10
    assert meta1["offset"] == 0

    items2, meta2 = validate_paginated(api.list_training_enrollments(program_admin_headers, params={"offset": 10}))
    assert len(items2) == 2
    assert meta2["total_count"] == 12
    assert meta2["has_more"] is False
