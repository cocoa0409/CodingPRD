"""Disaster relief operations and deployment candidate ranking."""
from test_helpers import (
    ApiErrorId,
    create_operation,
    create_region,
    create_shelter_site,
    create_volunteer,
    inspect_site,
    refresh_credentials,
    validate_error,
    validate_paginated,
    validate_success,
)


def _ranking_scenario(api):
    """Two regions, one operation, and three differently-placed volunteers."""
    region_gl = create_region()
    region_nw = create_region(code="NW", name="Northwest", state_codes=["WA", "OR"],
                              coordinator_user_id="rc_nw", volunteer_pool_target=25,
                              authorized_agency_codes=["FEMA"])
    operation = create_operation(region_gl["id"])

    qualified_home = refresh_credentials(create_volunteer(
        region_gl["id"], qualified_role_codes=["REGISTRATION", "SHELTER_MANAGER"])["id"])
    qualified_away = refresh_credentials(create_volunteer(
        region_nw["id"], full_name="Eli Nakamura",
        qualified_role_codes=["REGISTRATION"])["id"])
    unqualified_home = refresh_credentials(create_volunteer(
        region_gl["id"], full_name="Priya Shah",
        qualified_role_codes=["FEEDING"])["id"])

    return operation, qualified_home, qualified_away, unqualified_home


def _candidate_headers():
    from test_helpers import TEST_USERS
    return TEST_USERS["regional_coordinator_headers"]


def test_candidates_are_ranked_by_the_weighted_score(api):
    """PRD §3.5: "Eligible volunteers receive a score built from a base of 100 points, adjusted
    by four terms ... The role match bonus adds 20 points when the requested `role_code` appears
    in the volunteer's `qualified_role_codes`."

    PRD §3.5: "Candidates are returned highest score first, and ties are broken by the earlier
    `credential_refreshed_at`, then by the earlier `created_at`."

    Design: Difficulty/combinatorial_formula/deployment_candidate_weighted_ranking
    """
    operation, home, away, unqualified = _ranking_scenario(api)

    resp = api.list_deployment_candidates(
        operation["id"], _candidate_headers(), params={"role_code": "REGISTRATION"})
    data, _meta = validate_paginated(resp)

    ids = [row["id"] for row in data]
    assert ids == [home["id"], away["id"], unqualified["id"]], (
        "role match beats the cross-region distance penalty, which beats no role match")


def test_candidate_list_holds_exactly_the_eligible_pool(api):
    """PRD §3.5: "A volunteer is eligible only if their `credential_status` is `ACTIVE` and their
    `deployment_availability` is `AVAILABLE`; anyone else is excluded from the pool entirely
    rather than ranked low."

    Design: Difficulty/combinatorial_formula/deployment_candidate_weighted_ranking
    """
    operation, home, away, unqualified = _ranking_scenario(api)

    resp = api.list_deployment_candidates(
        operation["id"], _candidate_headers(), params={"role_code": "REGISTRATION"})
    data, meta = validate_paginated(resp)

    assert len(data) == 3
    assert meta["total_count"] == 3
    assert set(row["id"] for row in data) == {home["id"], away["id"], unqualified["id"]}
    assert data[0]["full_name"] == "Dana Ruiz"


def test_candidate_pool_with_no_eligible_volunteer_is_an_error(api):
    """PRD §3.5: "If no volunteer is eligible at all, the request is refused with
    `ERR_NO_ELIGIBLE_VOLUNTEER` at HTTP status 409."

    Design: Difficulty/boundary_precision_check/deployment_candidate_empty_pool_zero_count
    """
    region = create_region()
    operation = create_operation(region["id"])
    create_volunteer(region["id"], qualified_role_codes=["REGISTRATION"])

    resp = api.list_deployment_candidates(
        operation["id"], _candidate_headers(), params={"role_code": "REGISTRATION"})
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_VOLUNTEER)


def test_pending_volunteer_is_excluded_from_the_candidate_pool(api):
    """PRD §2.5: "A newly registered volunteer starts `PENDING` and is not deployable."

    PRD §3.5: "A volunteer is eligible only if their `credential_status` is `ACTIVE`."

    Design: Difficulty/boundary_precision_check/deployment_candidate_empty_pool_zero_count
    """
    region = create_region()
    operation = create_operation(region["id"])
    volunteer = create_volunteer(region["id"], qualified_role_codes=["REGISTRATION"])

    coord = _candidate_headers()
    read = validate_success(api.get_volunteer(volunteer["id"], coord))
    assert read["credential_status"] == "PENDING"

    resp = api.list_deployment_candidates(
        operation["id"], coord, params={"role_code": "REGISTRATION"})
    assert resp.status_code == 409, "an empty pool is an error, not a 200 with an empty array"


def test_duplicate_incident_code_is_refused(api):
    """PRD §3.5: "A duplicate `incident_code` is refused with `ERR_DUPLICATE_INCIDENT_CODE` at
    HTTP status 409."

    Design: Corner/errors/duplicate_incident_code_rejected
    """
    region = create_region()
    create_operation(region["id"], incident_code="DR-9101", incident_type="FLOOD")

    resp = api.create_operation(
        {"incident_code": "DR-9101", "incident_type": "WILDFIRE",
         "declared_at": "2026-09-05T00:00:00Z", "region_id": region["id"]},
        _candidate_headers())
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_INCIDENT_CODE)

    other = validate_success(api.create_operation(
        {"incident_code": "DR-9102", "incident_type": "WILDFIRE",
         "declared_at": "2026-09-05T00:00:00Z", "region_id": region["id"]},
        _candidate_headers()), 201)
    assert other["phase"] == "MOBILIZATION"


def test_shelter_activation_across_regions_is_refused(api):
    """PRD §3.1: "The activation is refused with `ERR_REGION_MISMATCH` at HTTP status 409 if the
    site's region is not the same region as the disaster relief operation it is being activated
    for — a region does not shelter another region's disaster."

    Design: Corner/errors/shelter_creation_region_mismatch_rejected
    """
    region_gl = create_region()
    region_nw = create_region(code="NW", name="Northwest", state_codes=["WA", "OR"],
                              coordinator_user_id="rc_nw", volunteer_pool_target=25,
                              authorized_agency_codes=["FEMA"])
    operation = create_operation(region_nw["id"], incident_code="DR-9101")
    site = create_shelter_site(region_gl["id"])
    inspect_site(site["id"], site["version"])

    resp = api.create_shelter_operation(
        {"shelter_site_id": site["id"], "disaster_relief_operation_id": operation["id"]},
        _candidate_headers())
    validate_error(resp, ApiErrorId.ERR_REGION_MISMATCH)
