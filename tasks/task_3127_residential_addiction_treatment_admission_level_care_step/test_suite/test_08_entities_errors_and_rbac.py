"""Resource shape, nested resolution, error envelopes and role boundaries."""

import pytest

from test_helpers import (
    C,
    INTAKE_NURSE_HEADERS,
    NON_EXISTENT_UUID,
    PLATFORM_ADMIN_HEADERS,
    READ_HEADERS,
    UTILIZATION_REVIEWER_HEADERS,
    ApiErrorId,
    build_user_headers,
    grant_state_license,
    is_iso8601_timestamp,
    is_valid_uuid,
    open_episode,
    read_episode,
    read_facility,
    set_clock,
    setup_admitted_episode,
    setup_claimed_episode,
    setup_site,
    setup_staged_episode,
    validate_error,
    validate_paginated,
    validate_success,
)


# ------------------------------------------------------------------ creation shape

def test_a_new_facility_opens_unlicensed_and_every_declared_field_is_returned(api):
    """PRD §2.5: "A newly created `Facility` therefore begins with `licensed` false and
    `as_level_max` at `ASAM_1_0` until a state licence is recorded."
    PRD §2.2: "The `data` field contains the resource object or an array of resource objects."

    Design: Corner/entities/facility_create_returns_every_declared_field_and_opens_unlicensed
    """
    set_clock(C.CLOCK_2026_09_01)
    response = api.create_facility(
        {"name": C.FACILITY_NAME, "state_code": C.FACILITY_STATE}, PLATFORM_ADMIN_HEADERS
    )
    data = validate_success(response, 201)

    assert data["name"] == C.FACILITY_NAME
    assert data["state_code"] == C.FACILITY_STATE
    assert data["licensed"] is False
    assert data["as_level_max"] == "ASAM_1_0"
    assert data["facility_posture"] == "OPEN"
    assert data["compliance_risk_points"] == 0
    assert data["ops_epoch"] == 0
    assert data["last_ops_run_at"] is None
    assert data["version"] == 1
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])


def test_facility_derived_flags_are_computed_and_never_taken_from_the_body(api):
    """
    PRD §2.5: "A `STATE_LICENSE` row additionally carries `license_level_max`, the highest ASAM
    level that licence permits, and `credential_tier_min`, the lowest clinician credential tier
    it permits; both are null for the other two classes." PRD §2.5: "`licensed` is true once a
    `STATE_LICENSE` accreditation for the facility's own `state_code` has been `GRANTED` and has
    not reached `EXPIRED`."

    Design: Corner/entities/facility_derived_fields_are_computed_on_read_and_never_stored_from_input
    """
    set_clock(C.CLOCK_2026_09_01)
    response = api.create_facility(
        {"name": C.FACILITY_NAME, "state_code": C.FACILITY_STATE, "licensed": True},
        PLATFORM_ADMIN_HEADERS,
    )
    data = validate_success(response, 201)
    assert data["licensed"] is False, "no body value can set a derived flag"
    assert data["as_level_max"] == "ASAM_1_0"

    grant_state_license(data["id"])
    refreshed = read_facility(data["id"])
    assert refreshed["licensed"] is True
    assert refreshed["as_level_max"] == "ASAM_3_5"
    assert refreshed["state_min_credential_tier"] == "TIER_3_LICENSED"


def test_an_episode_opened_without_an_assigned_level_stays_unset(api):
    """PRD §3.1: "The new episode starts with `clinical_status` at `AWAITING_ASSESSMENT`,
    `care_level_status` at `NOT_STARTED`, `step_down_count` at 0 and `therapy_revenue_cents`
    at 0."

    Design: Corner/entities/episode_create_omitting_assigned_level_leaves_it_unset
    """
    site = setup_site()
    episode = open_episode(site)

    assert episode["clinical_status"] == "AWAITING_ASSESSMENT"
    assert episode["care_level_status"] == "NOT_STARTED"
    assert episode["step_down_count"] == 0
    assert episode["therapy_revenue_cents"] == 0


def test_a_new_episode_start_state_matches_the_declared_initial_state(api):
    """
    PRD §3.1: "The new episode starts with `clinical_status` at `AWAITING_ASSESSMENT`,
    `care_level_status` at `NOT_STARTED`, `step_down_count` at 0 and `therapy_revenue_cents` at
    0."

    Design: Corner/state_machines/episode_starts_in_awaiting_assessment_with_not_started_care_level
    """
    site = setup_site()
    episode = open_episode(site)

    stored = read_episode(episode["id"])
    assert stored["clinical_status"] == "AWAITING_ASSESSMENT"
    assert stored["care_level_status"] == "NOT_STARTED"


def test_a_sessions_server_owned_fields_ignore_client_input(api):
    """PRD §3.4: "The row starts at `SCHEDULED` with `attended` false and
    `billing_amount_cents` 0."
    PRD §3.4: "computes `billing_amount_cents` from the service level and duration"

    Design: Corner/entities/session_create_extra_field_status_is_ignored_input
    """
    site = setup_site()
    setup = setup_admitted_episode(site=site)

    response = api.create_session(
        site.id,
        setup.id,
        {
            "service_id": site.service_35["id"],
            "clinician_id": site.clinician["id"],
            "scheduled_at": "2026-09-03T09:00:00Z",
            "duration_minutes": 60,
            "status": "ATTENDED",
            "billing_amount_cents": 210,
        },
        INTAKE_NURSE_HEADERS,
    )
    data = validate_success(response, 201)

    assert data["status"] == "SCHEDULED", "status is server-owned"
    assert data["billing_amount_cents"] == 0
    assert data["attended"] is False


def test_an_out_of_enum_level_of_care_is_refused(api):
    """PRD §2.7: "An enum-typed field carrying a value outside its declared member set is
    refused with `ERR_INVALID_ENUM_VALUE`."

    Design: Corner/entities/bed_create_out_of_enum_level_of_care_returns_invalid_enum_value
    """
    site = setup_site()
    response = api.create_bed(
        site.id,
        {"unit_name": "North Wing", "bed_label": "MN-B-99",
         "level_of_care": "ASAM_4_0", "cleaning_turnaround_hours": 0},
        PLATFORM_ADMIN_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_ENUM_VALUE, 400)


# -------------------------------------------------------------------- listing

def test_the_episode_listing_paginates_and_reports_the_filtered_total(api):
    """PRD §2.3: "`limit` defaults to 10, may not be lower than 1, and may not exceed 100."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and `has_more`
    inside the `meta` object of the envelope."

    Design: Corner/entities/episodes_list_paginates_and_reports_total_count_and_has_more
    """
    site = setup_site()
    for i in range(3):
        open_episode(site, patient_ref=f"PT-81{i:02d}")

    from test_helpers import list_episodes

    first_page = list_episodes(site.id, limit=2, offset=0)
    rows, meta = first_page
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    rows2, meta2 = list_episodes(site.id, limit=2, offset=2)
    assert len(rows2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    rows3, meta3 = list_episodes(site.id)
    assert len(rows3) == 3
    assert meta3["limit"] == 10
    assert meta3["offset"] == 0


# ------------------------------------------------------------ nested resolution

def test_an_unknown_facility_id_resolves_to_its_entity_specific_not_found(api):
    """PRD §2.7: "A missing facility yields `ERR_FACILITY_NOT_FOUND`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    Design: Corner/entities/facility_get_with_unknown_id_returns_facility_not_found
    """
    response = api.get_facility(NON_EXISTENT_UUID, READ_HEADERS)
    error = validate_error(response, ApiErrorId.ERR_FACILITY_NOT_FOUND, 404)
    assert error["error_id"] == ApiErrorId.ERR_FACILITY_NOT_FOUND


def test_an_unreachable_child_id_still_names_its_own_entity(api):
    """
    PRD §2.7: "A missing terminal child yields the class-specific code:
    `ERR_ASSESSMENT_NOT_FOUND` for an assessment, `ERR_BED_NOT_FOUND` for a bed,
    `ERR_AUTHORIZATION_NOT_FOUND` for an authorization, `ERR_PLAN_NOT_FOUND` for a treatment
    plan, `ERR_CHANGE_NOT_FOUND` for a level-of-care change, `ERR_HOUSING_NOT_FOUND` for a
    recovery-housing row, `ERR_ACCREDITATION_NOT_FOUND` for an accreditation,
    `ERR_CONTACT_NOT_FOUND` for an alumni contact, and `ERR_SESSION_NOT_FOUND` for a session
    attendance." PRD §2.7: "Resolution is strict, left-to-right and short-circuiting: the server
    validates the facility identifier first, then the episode identifier, then any terminal
    child identifier, and rejects at the first identifier that does not resolve."

    Design: Corner/errors/unreachable_child_id_produces_the_entity_specific_not_found
    """
    site = setup_site()
    claim = setup_claimed_episode(site=site)

    response = api.complete_assessment(
        site.id, NON_EXISTENT_UUID, {}, site.clinician_headers
    )
    validate_error(response, ApiErrorId.ERR_ASSESSMENT_NOT_FOUND, 404)

    response = api.cancel_session(site.id, NON_EXISTENT_UUID, {}, site.clinician_headers)
    validate_error(response, ApiErrorId.ERR_SESSION_NOT_FOUND, 404)


def test_a_body_foreign_key_from_another_facility_is_an_invalid_reference(api):
    """PRD §2.7: "That includes a reference that exists but belongs to a different facility
    from the one in the path."
    PRD §2.7: "Rooms, clinicians and payers named inside a request body resolve separately
    from the path."

    Design: Corner/entities/body_foreign_keys_are_validated_left_to_right_against_the_facility
    """
    site = setup_site()
    outsider = setup_site()
    setup = setup_admitted_episode(site=site)

    response = api.create_session(
        site.id,
        setup.id,
        {
            "service_id": outsider.service_35["id"],
            "clinician_id": site.clinician["id"],
            "scheduled_at": "2026-09-03T09:00:00Z",
            "duration_minutes": 60,
        },
        INTAKE_NURSE_HEADERS,
    )
    error = validate_error(response, ApiErrorId.ERR_INVALID_REFERENCE, 404)
    assert error["error_id"] != ApiErrorId.ERR_CLINICIAN_NOT_FOUND, (
        "the first failing foreign key decides the error"
    )


# ------------------------------------------------------------------ error shape

def test_distinct_failures_share_one_envelope_shape(api):
    """
    PRD §2.2: "#### Standard Error Response Format All error API responses (4xx status codes)
    follow this standard envelope format: ```json { "meta": { "api_request_id":
    "req_RANDOMALPHANUM123456", "api_request_timestamp": "2025-05-24T10:30:00.123Z" },
    "response_type": "error", "data": { "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING", "message":
    "A human-readable explanation of the error." } } ``` - The `meta` object for error responses
    contains only `api_request_id` and `api_request_timestamp`." PRD §2.2: "The `message`
    provides a human-readable explanation of what went wrong."

    Design: Corner/errors/error_envelope_shape_is_uniform_across_distinct_failure_modes
    """
    site = setup_site()
    claim = setup_claimed_episode(site=site)

    # A malformed session: an enum outside its member set.
    malformed = api.create_session(
        site.id,
        claim.id,
        {"service_id": site.service_35["id"], "clinician_id": site.clinician["id"],
         "scheduled_at": "2026-09-03T09:00:00Z", "duration_minutes": -5},
        INTAKE_NURSE_HEADERS,
    )
    assert malformed.status_code == 400
    assert malformed.status_code < 500
    body = malformed.json()
    assert body["response_type"] == "error"
    assert set(body["data"]) >= {"error_id", "message"}

    unknown = api.get_facility(NON_EXISTENT_UUID, READ_HEADERS)
    unknown_body = unknown.json()
    assert unknown_body["response_type"] == "error"
    assert set(unknown_body["data"]) >= {"error_id", "message"}
    assert set(unknown_body["meta"]) == {"api_request_id", "api_request_timestamp"}


# ----------------------------------------------------------------------- RBAC

def test_peers_are_not_interchangeable_on_authorization_approval(api):
    """
    PRD §2.1: "`UtilizationReviewer` is the payer-facing role: it requests authorizations and
    approves, denies or re-reviews them." PRD §2.1: "A request whose role is not permitted on
    the targeted operation, or whose `X-User-ID` fails to resolve where the role demands a
    persisted identity, is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/peer_roles_are_not_interchangeable_on_authorization_approval
    """
    site = setup_site()
    claim = setup_staged_episode(site=site)
    # The setup already approved one authorization; build a second pending one.
    from test_helpers import open_episode, place_episode, request_authorization

    episode = open_episode(site, patient_ref="PT-8100")
    place_episode(site, episode["id"], scores=C.SCORES_ASAM_3_5)
    auth = request_authorization(site, episode["id"], requested_level="ASAM_3_5",
                                 bed_id=site.beds["ASAM_3_5"]["id"])

    nurse = api.approve_authorization(site.id, auth["id"], {}, INTAKE_NURSE_HEADERS)
    validate_error(nurse, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)

    clinician = api.approve_authorization(site.id, auth["id"], {}, site.clinician_headers)
    validate_error(clinician, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)

    reviewer = validate_success(
        api.approve_authorization(site.id, auth["id"], {}, UTILIZATION_REVIEWER_HEADERS), 200
    )
    assert reviewer["posture"] == "APPROVED"


def test_segregation_of_duties_keys_on_user_identity_not_on_role(api):
    """PRD §2.12: "The same `X-User-ID` may not perform a `UtilizationReviewer` step on an
    episode and then attempt a gated `ClinicalDirector` step on that same episode."
    PRD §2.12: "A violation is reported as `ERR_SEGREGATION_OF_DUTIES_VIOLATION`, and it is
    reported before the server performs any existence check on the request."

    Design: Corner/rbac/segregation_of_duties_blocks_the_same_user_on_a_gated_clinical_step
    """
    site = setup_site()
    claim = setup_claimed_episode(site=site)

    # A concurrent review authored by "cd-ray" makes that same identity ineligible to
    # cosign. PRD §2.8 only extends a live authorization, so the review is filed while
    # the grant still has days in hand, before the day bank is burnt to zero.
    api.submit_concurrent_review(
        site.id, claim.auth_id, {},
        build_user_headers("cd-ray", "UtilizationReviewer"),
    )

    from test_helpers import draft_plan

    plan = draft_plan(site, claim.id)

    blocked = api.submit_plan_for_cosign(
        site.id, plan["id"], {}, build_user_headers("cd-ray", "ClinicalDirector")
    )
    error = validate_error(blocked, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION, 403)
    assert error["error_id"] != ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, (
        "the ClinicalDirector role is permitted on this endpoint"
    )

    accepted = validate_success(
        api.submit_plan_for_cosign(
            site.id, plan["id"], {}, build_user_headers("cd-other", "ClinicalDirector")
        ),
        200,
    )
    assert accepted["status"] == "ACTIVE"
