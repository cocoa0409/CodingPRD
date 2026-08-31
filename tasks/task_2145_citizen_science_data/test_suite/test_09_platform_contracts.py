"""Cross-cutting platform contracts: the admission ladder, RBAC and the sweep."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    NO_AUTH_HEADERS,
    build_world,
    certify,
    create_protocol_payload,
    create_site,
    create_volunteer,
    make_headers,
    make_research_partner_headers,
    make_volunteer_headers,
    open_campaign,
    read_certification,
    register_partner,
    set_clock,
    STAGE_ACTORS,
    STAGE_CAMPAIGN,
    STAGE_OPEN,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-05T09:00:00Z"


def test_every_missing_path_or_body_reference_names_its_own_error(api):
    """PRD 2.7: "**Priority 4 — path resource existence (every operation with a
    templated path segment).** Each templated segment is resolved strictly left to
    right, and the first one that names no row terminates the request with that
    entity's not-found error at HTTP 404: `ERR_PROTOCOL_NOT_FOUND`,
    `ERR_VOLUNTEER_NOT_FOUND`, `ERR_EXPERT_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`,
    `ERR_CAMPAIGN_NOT_FOUND`, `ERR_OBSERVATION_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`,
    `ERR_LOAN_NOT_FOUND`, `ERR_PUBLICATION_NOT_FOUND`, `ERR_PARTNER_NOT_FOUND`,
    `ERR_GRANT_NOT_FOUND`, or `ERR_AWARD_NOT_FOUND`."
    PRD 2.7: "**Priority 7 — body foreign-key existence (all body-carrying
    operations that reference other rows).** Every foreign key supplied in the body
    must resolve to an existing row, otherwise the corresponding 404:
    `ERR_PROTOCOL_NOT_FOUND`, `ERR_VOLUNTEER_NOT_FOUND`, `ERR_EXPERT_NOT_FOUND`,
    `ERR_CAMPAIGN_NOT_FOUND`, `ERR_SITE_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`,
    `ERR_LOAN_NOT_FOUND`, `ERR_PUBLICATION_NOT_FOUND`, or `ERR_PARTNER_NOT_FOUND`."

    Design: Corner/errors/every_path_and_body_reference_not_found_returns_its_own_error_id
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)

    cases = [
        (api.get_protocol("00000000-0000-4000-8000-000000000001", ADMIN),
         ApiErrorId.ERR_PROTOCOL_NOT_FOUND),
        (api.get_volunteer("00000000-0000-4000-8000-000000000002", ADMIN),
         ApiErrorId.ERR_VOLUNTEER_NOT_FOUND),
        (api.get_expert("00000000-0000-4000-8000-000000000003", ADMIN),
         ApiErrorId.ERR_EXPERT_NOT_FOUND),
        (api.get_certification("00000000-0000-4000-8000-000000000004", ADMIN),
         ApiErrorId.ERR_CERTIFICATION_NOT_FOUND),
        (api.get_equipment("00000000-0000-4000-8000-000000000005", ADMIN),
         ApiErrorId.ERR_EQUIPMENT_NOT_FOUND),
        (api.get_loan("00000000-0000-4000-8000-000000000006", ADMIN),
         ApiErrorId.ERR_LOAN_NOT_FOUND),
        (api.get_publication("00000000-0000-4000-8000-000000000007", ADMIN),
         ApiErrorId.ERR_PUBLICATION_NOT_FOUND),
        (api.get_partner("00000000-0000-4000-8000-000000000008", ADMIN),
         ApiErrorId.ERR_PARTNER_NOT_FOUND),
        (api.get_access_grant("00000000-0000-4000-8000-000000000009", ADMIN),
         ApiErrorId.ERR_GRANT_NOT_FOUND),
    ]
    for response, expected in cases:
        validate_error(response, expected.value, 404)

    body_fk = api.create_observation({
        "campaign_id": world["cam1"],
        "site_id": "00000000-0000-4000-8000-00000000000a",
        "volunteer_id": world["v1"], "observed_at": "2026-08-05T06:00:00Z",
        "latitude": 44.0, "longitude": -70.0, "species_code": "BAEA",
        "count_value": 1}, world["vol_headers"])
    validate_error(body_fk, ApiErrorId.ERR_SITE_NOT_FOUND.value, 404)

    _rows, meta = validate_paginated(api.list_observations(
        ADMIN, {"campaign_id": world["cam1"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 0


def test_an_entity_backed_actor_id_that_names_no_row_is_an_actor_not_found(api):
    """PRD 2.7: "**Priority 5 — actor existence (every operation called as
    `Volunteer`, `Expert`, or `ResearchPartner`).** `X-User-ID` must resolve to a live
    row of the backing entity, otherwise `ERR_ACTOR_NOT_FOUND` (404)."
    PRD 2.1: "For all three entity-backed roles, if `X-User-ID` does not resolve to
    a live row of the backing entity, the request fails with `ERR_ACTOR_NOT_FOUND`
    (HTTP 404)."

    Design: Corner/errors/volunteer_actor_id_not_found_returns_actor_not_found
    """
    create_volunteer(full_name="Real Volunteer", email="real@example.org",
                     home_region_code="NE-01")

    response = api.list_observations(
        make_volunteer_headers("00000000-0000-4000-8000-0000000000cc"),
        {"limit": 10, "offset": 0})
    validate_error(response, ApiErrorId.ERR_ACTOR_NOT_FOUND.value, 404)


def test_a_volunteer_may_not_draft_a_protocol(api):
    """PRD 2.7: "**Priority 3 — role authorisation (all operations).** The acting
    role must appear in the operation's permitted-role list in §4, otherwise
    `ERR_ROLE_NOT_PERMITTED` (403)."
    PRD 2.1: "Only a `ProgramAdmin` creates and activates protocols; registers
    volunteers, experts, equipment, and research partners; enrols and grants
    certifications; creates, opens, and closes campaigns and adds survey sites;
    issues and takes back equipment loans, clears quarantine, and completes
    calibration; retracts accepted observations; creates, releases, and withdraws
    publications; approves partners and approves or revokes access grants; reinstates
    volunteers on probation or suspension; and runs maintenance sweeps or sets the
    logical clock."

    Design: Corner/rbac/volunteer_cannot_create_protocol
    """
    set_clock(CLOCK)
    volunteer = create_volunteer()

    response = api.create_protocol(create_protocol_payload(
        code="SNEAKY-1", title="Volunteer Authored Protocol",
        max_submission_lag_hours=48), make_volunteer_headers(volunteer["id"]))
    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    _rows, meta = validate_paginated(api.list_protocols(ADMIN, {"limit": 10, "offset": 0}))
    assert meta["total_count"] == 0


def test_a_volunteer_may_not_file_an_observation_for_someone_else(api):
    """PRD 2.7: "**Priority 8 — resource ownership.** Guards exactly six
    operations: `POST /citizen-science/observations`, `POST
    /citizen-science/observations/{id}/photos`, `POST
    /citizen-science/observations/{id}/resubmit`, `POST
    /citizen-science/certifications/{id}/complete-training`, `POST
    /citizen-science/equipment-loans`, and `POST /citizen-science/access-grants`. A
    `Volunteer` actor's `X-User-ID` must equal the observation's or loan's
    `volunteer_id`; an `Expert` actor's `X-User-ID` must equal the certification's
    `trainer_expert_id`; a `ResearchPartner` actor's `X-User-ID` must equal the
    grant's `partner_id`. Otherwise `ERR_NOT_RESOURCE_OWNER` (403)."

    Design: Corner/rbac/volunteer_cannot_submit_observation_for_another_volunteer
    """
    world = build_world(stage=STAGE_CAMPAIGN, clock=CLOCK)
    site = create_site(world["cam1"], site_code="S-HI", priority_weight=1.5)
    other = create_volunteer(full_name="Nina Nuthatch", email="nina@example.org",
                             home_region_code="NE-02")
    certify(other["id"], world["p1"], world["et"], level="ADVANCED", exam_score=91)
    open_campaign(world["cam1"])

    response = api.create_observation({
        "campaign_id": world["cam1"], "site_id": site["id"],
        "volunteer_id": other["id"], "observed_at": "2026-08-05T06:00:00Z",
        "latitude": 44.0, "longitude": -70.0, "species_code": "BAEA",
        "count_value": 1}, world["vol_headers"])
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    _rows, meta = validate_paginated(api.list_observations(
        ADMIN, {"volunteer_id": other["id"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 0


def test_a_research_partner_may_not_list_volunteers_but_may_list_publications(api):
    """PRD 2.1: "A `ResearchPartner` may read protocols, campaigns, sites,
    observations, publications, partner records, and access grants."
    PRD 2.1: "The authoritative per-operation role list is the table in §4; any role
    absent from an operation's list receives `ERR_ROLE_NOT_PERMITTED`."

    Design: Corner/rbac/research_partner_cannot_list_volunteers
    """
    partner = register_partner(approved=True, org_name="Boreal Institute",
                               contact_email="data@boreal.example",
                               trust_tier="STANDARD")
    partner_headers = make_research_partner_headers(partner["id"])

    denied = api.list_volunteers(partner_headers, {"limit": 10, "offset": 0})
    validate_error(denied, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    allowed = api.list_publications(partner_headers, {"limit": 10, "offset": 0})
    _rows, meta = validate_paginated(allowed)
    assert meta["total_count"] == 0


def test_a_request_without_authentication_headers_is_refused(api):
    """PRD 2.7: "**Priority 1 — authentication (all operations).** Both
    `X-User-Role` and `X-User-ID` must be present and non-empty, otherwise
    `ERR_UNAUTHENTICATED` (401)."
    PRD 2.1: "If either header is absent or empty, the request fails with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/request_missing_auth_headers_returns_unauthenticated
    """
    response = api.raw_post("/citizen-science/protocols", create_protocol_payload(
        code="NOAUTH-1", title="No Auth Protocol", max_submission_lag_hours=48),
        NO_AUTH_HEADERS)
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    _rows, meta = validate_paginated(api.list_protocols(ADMIN, {"limit": 10, "offset": 0}))
    assert meta["total_count"] == 0


def test_a_request_carrying_an_undeclared_role_is_refused(api):
    """PRD 2.7: "**Priority 2 — role recognition (all operations).** `X-User-Role`
    must be one of `ProgramAdmin`, `Volunteer`, `Expert`, or `ResearchPartner`,
    otherwise `ERR_UNKNOWN_ROLE` (401)."
    PRD 2.1: "If `X-User-Role` carries any value outside the four recognised roles,
    the request fails with `ERR_UNKNOWN_ROLE` (HTTP 401)."

    Design: Corner/rbac/request_with_unknown_role_returns_unknown_role
    """
    response = api.list_protocols(make_headers("steward-1", "DataSteward"),
                                  {"limit": 10, "offset": 0})
    error = validate_error(response, ApiErrorId.ERR_UNKNOWN_ROLE.value, 401)
    assert error["error_id"] != ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, (
        "An unrecognised role is a 401, not a 403")


def test_a_quiet_maintenance_sweep_reports_every_counter_as_zero(api):
    """PRD 3.9: "The sweep reports what it did, returning
    `expired_certification_count`, `overdue_loan_count`, `released_publication_count`,
    `expired_grant_count`, `archived_campaign_count`, and `exhausted_revision_count`.
    A sweep that finds nothing to do is not an error; it simply reports zeros."

    Design: Corner/endpoints/maintenance_run_reports_all_counters_on_a_quiet_system
    """
    world = build_world(stage=STAGE_ACTORS, clock=CLOCK)
    certification = certify(world["v1"], world["p1"], world["et"], level="BASIC")

    sweep = validate_success(api.run_maintenance(ADMIN))

    assert sweep["expired_certification_count"] == 0
    assert sweep["overdue_loan_count"] == 0
    assert sweep["released_publication_count"] == 0
    assert sweep["expired_grant_count"] == 0
    assert sweep["archived_campaign_count"] == 0
    assert sweep["exhausted_revision_count"] == 0
    assert read_certification(certification["id"])["status"] == "CERTIFIED"
