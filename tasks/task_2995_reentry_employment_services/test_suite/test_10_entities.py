"""
Entity projections, declared defaults and referential resolution.

What a create returns, what a read returns, which fields the server fills in for
itself, and which addressing mistakes are 404s rather than 422s.
"""

from test_helpers.api_errors import (
    ERR_PARTICIPANT_NOT_FOUND,
    ERR_VALIDATION,
)
from test_helpers.assertions import (
    assert_all_null,
    assert_array_equals,
    assert_common_fields,
    assert_int_field,
    assert_money_cents,
    assert_one_decimal_place,
    ids_of,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_unpaginated,
)
from test_helpers.constants import (
    ALL_GRANT_CATEGORIES,
    BONDING_NONE,
    CATEGORY_ID_FEE,
    DOC_BIRTH_CERTIFICATE,
    DOC_MEDICAID_APPLICATION,
    DOC_SSN_CARD,
    DOC_STATE_ID,
    DOC_WORK_HISTORY,
    EMPLOYMENT_OFFERED,
    FUNDING_POSTURE_OPEN,
    INDUSTRY_MANUFACTURING,
    LICENSE_RELIEF_NONE,
    PARTNERSHIP_PROSPECT,
    POSTURE_OPEN,
    RECORD_DRUG_OFFENSE,
    RECORD_DUI,
    RECORD_PROPERTY_OFFENSE,
    RELEASE_PLAN_NONE,
    REQUEST_SUBMITTED,
    SHIFT_SCHEDULED,
    STAGE_PRE_RELEASE,
    SUSPENSION_NONE,
)
from test_helpers import factories as f
from test_helpers.test_users import (
    CASE_MANAGER,
    CASE_MANAGER_ID,
    EMPLOYER_LIAISON,
    FUNDER_ANALYST,
    SUPERVISION_OFFICER,
)


def test_creating_a_participant_returns_the_whole_projection_with_its_defaults(
    api, build
):
    """
    The create response is the full participant row, with every default already
    materialised and every not-yet-known field present and null.

    PRD section 3.1: "A freshly enrolled participant is born in a fully determined
    state: `stage` is `PRE_RELEASE`, `suspension_status` is `NONE`,
    `license_relief_status` is `NONE`, `release_plan_status` is `NONE`,
    `release_plan_revision` is 0, `petition_rounds_used` is 0,
    `verified_document_types` is an empty array, `doc_completeness_pct` is 0.0, and
    `engagement_posture` is `OPEN`."

    Design: Corner/entities/create_participant_returns_every_declared_field_and_default
    """
    response = api.create_participant(f.participant_payload(), CASE_MANAGER)
    participant = validate_unpaginated(response, 201)

    assert participant["full_name"] == "Marcus Reed"
    assert participant["facility_name"] == "Northgate Correctional"
    assert participant["facility_state"] == "OH"
    assert participant["expected_release_date"] == "2026-08-10"
    assert_array_equals(participant, "record_categories", [RECORD_PROPERTY_OFFENSE])
    assert_array_equals(
        participant,
        "required_document_types",
        [
            DOC_STATE_ID,
            DOC_SSN_CARD,
            DOC_BIRTH_CERTIFICATE,
            DOC_WORK_HISTORY,
            DOC_MEDICAID_APPLICATION,
        ],
    )
    assert_array_equals(participant, "verified_document_types", [])
    assert_one_decimal_place(participant, "doc_completeness_pct", 0.0)
    assert participant["stage"] == STAGE_PRE_RELEASE
    assert participant["release_plan_status"] == RELEASE_PLAN_NONE
    assert_int_field(participant, "release_plan_revision", 0)
    assert participant["suspension_status"] == SUSPENSION_NONE
    assert participant["license_relief_status"] == LICENSE_RELIEF_NONE
    assert_int_field(participant, "petition_rounds_used", 0)
    assert participant["engagement_posture"] == POSTURE_OPEN
    assert participant["assigned_case_manager_user_id"] == CASE_MANAGER_ID
    assert_all_null(
        participant,
        [
            "actual_release_date",
            "assessment_domain_scores",
            "barrier_score",
            "barrier_tier",
            "exit_reason",
            "exit_date",
        ],
    )
    assert_common_fields(participant, 1)
    assert is_valid_uuid(participant["id"])

    body = response.json()
    assert body["response_type"] == "object"
    meta = body["meta"]
    assert meta["api_request_id"]
    assert meta["api_request_timestamp"]


def test_reading_a_grant_returns_its_ledger_columns_reconciled_at_zero(api, build):
    """
    The computed money columns are part of the grant projection from the moment it
    opens, not nulls waiting for the first request.

    PRD section 3.8: "A new grant opens with `committed_cents` and
    `disbursed_cents` of 0, `available_cents` equal to `authorized_cents`,
    `open_request_count` of 0, and `funding_posture` of `OPEN`."

    Design: Corner/entities/get_grant_returns_stored_inputs_and_computed_ledger_columns
    """
    created = build.grant(
        authorized_cents=100000, per_participant_cap_cents=60000, retention_benchmark_pct=75.0
    )

    grant = validate_unpaginated(api.get_grant(created["id"], FUNDER_ANALYST))
    assert grant["funder_name"] == "Reentry Workforce Fund"
    assert_int_field(grant, "program_year", 2026)
    assert_money_cents(grant, "authorized_cents", 100000)
    assert_money_cents(grant, "per_participant_cap_cents", 60000)
    assert_one_decimal_place(grant, "retention_benchmark_pct", 75.0)
    assert_array_equals(grant, "allowed_categories", list(ALL_GRANT_CATEGORIES))
    assert_money_cents(grant, "committed_cents", 0)
    assert_money_cents(grant, "disbursed_cents", 0)
    assert_money_cents(grant, "available_cents", 100000)
    assert grant["funding_posture"] == FUNDING_POSTURE_OPEN
    assert_int_field(grant, "open_request_count", 0)
    assert_common_fields(grant, 1)


def test_listing_participants_reports_the_whole_match_and_flips_has_more(api, build):
    """
    `total_count` counts the matching set before pagination while `data` carries
    only the page, and `has_more` is false on the last page.

    PRD section 2.3: "The `meta` object of a list response carries `limit` (the
    effective page size actually applied), `offset` (the effective offset actually
    applied), `total_count` (the number of rows matching the filters before
    pagination is applied), and `has_more` (true when rows remain beyond the current
    page, false otherwise)."

    Design: Corner/entities/list_participants_paginates_with_total_count_and_has_more
    """
    first = build.participant()
    second = build.participant(
        full_name="Dana Whitfield", record_categories=[RECORD_DRUG_OFFENSE]
    )
    third = build.participant(full_name="Alvin Peters", record_categories=[RECORD_DUI])

    page_one, meta_one = validate_paginated(
        api.list_participants(CASE_MANAGER, f.page_params(limit=2, offset=0))
    )
    assert len(page_one) == 2
    assert meta_one["total_count"] == 3
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0
    assert meta_one["has_more"] is True

    page_two, meta_two = validate_paginated(
        api.list_participants(CASE_MANAGER, f.page_params(limit=2, offset=2))
    )
    assert len(page_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["limit"] == 2
    assert meta_two["offset"] == 2
    assert meta_two["has_more"] is False

    assert set(ids_of(page_one) + ids_of(page_two)) == {
        first["id"],
        second["id"],
        third["id"],
    }


def test_a_grant_id_in_the_participant_path_is_a_participant_miss(api, build):
    """
    The addressed collection decides the not-found code, so a real grant identifier
    is still nothing at all under `/participants`.

    PRD section 2.5: "**Path existence** — an identifier embedded in the URL path
    matches no row of the collection it addresses, yielding that collection's own
    not-found code with HTTP 404: `ERR_PARTICIPANT_NOT_FOUND`,
    `ERR_SUPERVISION_CASE_NOT_FOUND`, `ERR_PARTNERSHIP_NOT_FOUND`,
    `ERR_JOB_OPENING_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`,
    `ERR_WORK_SHIFT_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`,
    `ERR_SUPPORT_REQUEST_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, or
    `ERR_ENROLLMENT_NOT_FOUND`."

    Design: Corner/entities/get_participant_with_an_unknown_id_returns_not_found
    """
    grant = build.grant()

    missed = api.get_participant(grant["id"], CASE_MANAGER)
    validate_error(missed, ERR_PARTICIPANT_NOT_FOUND, 404)
    assert missed.json()["response_type"] == "error"

    still_there = validate_unpaginated(api.get_grant(grant["id"], FUNDER_ANALYST))
    assert still_there["id"] == grant["id"]


def test_a_job_opening_without_an_hourly_wage_is_a_shape_failure(api, build):
    """
    `hourly_wage_cents` carries no default and feeds both the subsidy ladder and the
    match arithmetic, so its absence is refused rather than stored as null.

    PRD section 3.4: "The create payload names the employer as `partnership_id` and
    carries `title`, the job title; `occupation_code`, a Standard Occupational
    Classification code such as `51-4031`; `hourly_wage_cents`, the offered wage in
    cents per hour, which must be at least 725; `weekly_hours`, the scheduled hours
    per week, which must be strictly greater than 0 and at most 60; and
    `openings_count`, the total number of seats the posting can fill, an integer of
    at least 1."

    Design: Corner/entities/create_job_opening_without_hourly_wage_cents_is_rejected
    """
    partnership = build.partnership_active()

    refused = api.create_job_opening(
        f.job_opening_payload(partnership["id"], hourly_wage_cents="__omit__"),
        EMPLOYER_LIAISON,
    )
    validate_error(refused, ERR_VALIDATION, 422)

    rows, meta = validate_paginated(
        api.list_partnership_job_openings(partnership["id"], EMPLOYER_LIAISON)
    )
    assert meta["total_count"] == 0


def test_omitted_partnership_flags_take_their_declared_defaults(api, build):
    """
    The two optional eligibility inputs default to false and to an empty array, and
    the bonding fields stay unset until a bonding agreement is recorded.

    PRD section 3.4: "Two optional inputs shape eligibility later: `wotc_certified`
    declares whether the employer is enrolled for Work Opportunity Tax Credit
    paperwork and defaults to false, and `excluded_record_categories` lists
    conviction categories the employer refuses across every one of its openings,
    defaulting to an empty array."

    Design: Corner/entities/omitted_partnership_flags_take_their_declared_defaults
    """
    partnership = validate_unpaginated(
        api.create_partnership(
            f.partnership_payload(
                employer_name="Riverside Fabrication",
                industry=INDUSTRY_MANUFACTURING,
                max_concurrent_placements=3,
            ),
            EMPLOYER_LIAISON,
        ),
        201,
    )

    assert partnership["wotc_certified"] is False
    assert_array_equals(partnership, "excluded_record_categories", [])
    assert partnership["fidelity_bond_enabled"] is False
    assert_all_null(partnership, ["bond_coverage_cents", "bond_effective_date"])
    assert_int_field(partnership, "max_concurrent_placements", 3)
    assert_int_field(partnership, "active_placement_count", 0)
    assert partnership["status"] == PARTNERSHIP_PROSPECT
    assert_common_fields(partnership, 1)


def test_scheduled_hours_is_computed_from_the_stored_interval(api, build):
    """
    A 09:00-to-16:30 interval is seven and a half hours, and that decimal is what
    the subsidy tier is priced from.

    PRD section 3.7: "From the accepted interval the server computes
    `scheduled_hours` as the number of minutes from `starts_at` to `ends_at` divided
    by sixty, rounded half up to two decimal places, and the shift is stored with
    `status` of `SCHEDULED` and `conflict_reason` of null."

    Design: Corner/entities/work_shift_scheduled_hours_is_computed_from_the_interval
    """
    grant = build.grant(
        authorized_cents=30000, per_participant_cap_cents=60000, retention_benchmark_pct=75.0
    )
    participant = build.participant_released()
    build.case_authorized(participant["id"])
    partnership = build.partnership_active()
    opening = build.job_opening(partnership["id"])
    placement = build.placement_active(participant["id"], opening["id"], grant["id"])

    shift = validate_unpaginated(
        api.create_work_shift(
            placement["id"],
            f.work_shift_payload("2026-08-05T09:00:00.000Z", "2026-08-05T16:30:00.000Z"),
            CASE_MANAGER,
        ),
        201,
    )
    assert shift["scheduled_hours"] == 7.5
    assert shift["status"] == SHIFT_SCHEDULED
    assert shift["conflict_reason"] is None
    assert shift["placement_id"] == placement["id"]

    stored = validate_unpaginated(api.get_placement(placement["id"], CASE_MANAGER))
    assert_money_cents(stored, "projected_subsidy_cents", 6938)
    assert_money_cents(stored, "actual_subsidy_cents", 0)

    ledger = validate_unpaginated(api.get_grant_ledger(grant["id"], FUNDER_ANALYST))
    assert_money_cents(ledger, "committed_cents", 6938)
    assert_money_cents(ledger, "available_cents", 23062)


def test_support_request_system_fields_are_stamped_by_the_server(api, build):
    """
    The submitter comes from the caller's header and every review, settlement and
    deferral column starts null; the body cannot seed them.

    PRD section 3.8: "An accepted request is created with `status` of `SUBMITTED`,
    `info_rounds_used` of 0, `submitted_by_user_id` set from the caller's
    `X-User-ID`, and `reviewed_by_user_id`, `settled_by_user_id`, `review_note`,
    `settlement_note`, `deferred_at`, and `promoted_at` all null; the grant's
    `open_request_count` rises by one and the grant's `version` advances, while no
    money is committed yet."

    Design: Corner/entities/support_request_system_fields_are_stamped_by_the_server
    """
    grant = build.grant(
        authorized_cents=100000, per_participant_cap_cents=60000, retention_benchmark_pct=75.0
    )
    participant = build.participant_zero_barrier_draft(
        record_categories=[RECORD_DRUG_OFFENSE]
    )

    request = validate_unpaginated(
        api.create_support_request(
            f.support_request_payload(
                participant["id"],
                grant["id"],
                build.grant_version(grant["id"]),
                [f.line_item("State ID replacement fee", 8000)],
                category=CATEGORY_ID_FEE,
                justification="State ID required before employment",
            ),
            CASE_MANAGER,
        ),
        201,
    )
    assert request["status"] == REQUEST_SUBMITTED
    assert request["submitted_by_user_id"] == CASE_MANAGER_ID
    assert_all_null(
        request,
        [
            "reviewed_by_user_id",
            "settled_by_user_id",
            "review_note",
            "settlement_note",
            "deferred_at",
            "promoted_at",
        ],
    )
    assert_int_field(request, "info_rounds_used", 0)
    assert_money_cents(request, "requested_cents", 8000)
    assert_money_cents(request, "admin_fee_cents", 240)
    assert_money_cents(request, "total_charge_cents", 8240)
    assert_common_fields(request, 1)


def test_a_lowercase_facility_state_is_refused_rather_than_upcased(api, build):
    """
    Two characters are not enough: the pair must be uppercase, and the server does
    not quietly normalise them.

    PRD section 3.1: "Engagement begins inside the facility, weeks before anyone
    walks out of it. A `CaseManager` enrols a participant by supplying the person's
    legal name as `full_name`, a string of at least 1 and at most 120 characters; the
    correctional facility as `facility_name`; the facility's location as
    `facility_state`, which must be exactly two uppercase letters in the range A
    through Z, so that `CA` is accepted while `Ca`, `CAL`, and `C` are each refused
    with `ERR_VALIDATION`; and the scheduled release date as `expected_release_date`,
    an ISO 8601 calendar date with no time component."

    Design: Corner/entities/create_participant_with_a_lowercase_facility_state_is_rejected
    """
    refused = api.create_participant(
        f.participant_payload(
            facility_state="oh", required_document_types=[DOC_STATE_ID, DOC_SSN_CARD]
        ),
        CASE_MANAGER,
    )
    validate_error(refused, ERR_VALIDATION, 422)

    rows, meta = validate_paginated(api.list_participants(CASE_MANAGER))
    assert meta["total_count"] == 0


def test_a_body_foreign_key_that_matches_no_participant_is_a_not_found(api, build):
    """
    A grant identifier supplied as a body `participant_id` is resolved against the
    participants collection and reported as a 404, not as a shape failure.

    PRD section 2.5: "**Body foreign keys** — a foreign key supplied inside the
    request body matches no row, yielding the referenced collection's not-found code
    with HTTP 404."

    Design: Corner/entities/create_supervision_case_with_an_unknown_participant_id_returns_not_found
    """
    grant = build.grant()

    refused = api.create_supervision_case(
        f.supervision_case_payload(grant["id"], "officer-1"), SUPERVISION_OFFICER
    )
    validate_error(refused, ERR_PARTICIPANT_NOT_FOUND, 404)

    rows, meta = validate_paginated(api.list_supervision_cases(SUPERVISION_OFFICER))
    assert meta["total_count"] == 0


def test_a_placement_links_three_aggregates_and_is_addressable_by_each(api, build):
    """
    Two participants on one opening produce two independent junction rows, each
    reachable through the participant, the opening and the grant filter.

    PRD section 3.6: "A placement is the junction where a participant, a job opening,
    and — when the work is subsidised — a funder grant meet."

    Design: Corner/entities/placement_junction_links_participant_opening_and_grant_independently
    """
    grant = build.grant(authorized_cents=30000, per_participant_cap_cents=60000)
    partnership = build.partnership_active()
    opening = build.job_opening(partnership["id"])
    first_participant = build.participant_released()
    second_participant = build.participant_released(
        full_name="Dana Whitfield", record_categories=[RECORD_DRUG_OFFENSE]
    )
    first = build.placement_offered(first_participant["id"], opening["id"], grant["id"])

    second = validate_unpaginated(
        api.create_placement(
            f.placement_payload(
                second_participant["id"],
                opening["id"],
                build.opening_version(opening["id"]),
                grant["id"],
            ),
            CASE_MANAGER,
        ),
        201,
    )
    assert second["participant_id"] == second_participant["id"]
    assert second["job_opening_id"] == opening["id"]
    assert second["grant_id"] == grant["id"]
    assert second["employment_status"] == EMPLOYMENT_OFFERED
    assert second["bonding_status"] == BONDING_NONE

    by_opening, opening_meta = validate_paginated(
        api.list_placements(CASE_MANAGER, f.page_params(job_opening_id=opening["id"]))
    )
    assert opening_meta["total_count"] == 2
    assert set(ids_of(by_opening)) == {first["id"], second["id"]}

    by_participant, participant_meta = validate_paginated(
        api.list_placements(
            CASE_MANAGER, f.page_params(participant_id=first_participant["id"])
        )
    )
    assert participant_meta["total_count"] == 1
    assert by_participant[0]["id"] == first["id"]

    by_grant, grant_meta = validate_paginated(
        api.list_placements(CASE_MANAGER, f.page_params(grant_id=grant["id"]))
    )
    assert grant_meta["total_count"] == 2

    stored_opening = validate_unpaginated(api.get_job_opening(opening["id"], CASE_MANAGER))
    assert_int_field(stored_opening, "offered_count", 2)
    assert_int_field(stored_opening, "filled_count", 0)
    assert_int_field(stored_opening, "remaining_openings", 0)
