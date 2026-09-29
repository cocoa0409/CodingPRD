"""Entity shape: declared fields, declared defaults, server-minted system fields.

These tests hold the registries of PRD 3.1-3.5 to their declared representation:
every input echoed back on creation (PRD 2.2 envelope), every omitted optional
input resolved to the default PRD 3.1 names, `id`/`created_at`/`updated_at`/
`version` minted by the server (PRD 2.4), computed fields such as a shift's
`scheduled_minutes` derived rather than accepted, request-shape failures reported
as `ERR_INVALID_REQUEST` (PRD 2.8 check 7), and unknown identifiers - in a path
or in a request body - reported with the entity-specific 404 of PRD 2.7.
"""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_INVALID_REQUEST,
    ERR_PATIENT_NOT_FOUND,
    ERR_PAYER_MISMATCH,
    ERR_PAYER_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_millisecond_instants,
    assert_numbers_not_strings,
    assert_ratio,
    assert_shift_axes,
    assert_unversioned_entity,
    assert_versioned_entity,
    validate_unpaginated,
)
from test_helpers.test_users import (
    AGENCY_ADMIN,
    CASE_MANAGER,
    CLINICAL_SUPERVISOR,
    SCHEDULER,
    SUPERVISOR_USER_ID,
)
from test_helpers.types import (
    BillingEditRuleset,
    CompetencyStatus,
    EscalationTier,
    EvvStatus,
    LicenseType,
    NurseStatus,
    PatientStatus,
    PlanType,
    ShiftCancelReason,
    Skill,
    StaffingStatus,
    SupervisoryStatus,
    VisitOutcome,
)

SHIFT_START = "2026-08-05T08:00:00Z"
SHIFT_END = "2026-08-05T16:00:00Z"


def test_payer_creation_echoes_every_declared_field(api):
    """PRD 3.1 gives the payer seven inputs - `name`, `plan_type`,
    `weekly_hour_cap`, `evv_required`, `billing_edit_ruleset`,
    `appeal_window_days` and `reduction_notice_days` - and PRD 4 answers a
    registration with 201 Created. A call carrying all seven must return each of
    them unchanged inside the PRD 2.2 success envelope, with `version` at 1 as
    PRD 2.4 requires of a freshly created row.

    Design: Corner/entities/payer_creation_echoes_every_declared_field
    """
    fx.set_clock(api, C.WEEK32_START)

    response = api.create_payer(
        f.payer_payload(
            name="Sunrise MCO",
            plan_type=PlanType.MEDICAID_MCO.value,
            weekly_hour_cap=84,
            evv_required=True,
            billing_edit_ruleset=BillingEditRuleset.STRICT_15MIN.value,
            appeal_window_days=45,
            reduction_notice_days=20,
        ),
        AGENCY_ADMIN,
    )
    payer = validate_success(response, 201)

    body = response.json()
    assert body["response_type"] == "object", body
    assert body["meta"]["api_request_id"].startswith("req_"), body["meta"]
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"]), body["meta"]

    assert payer["name"] == "Sunrise MCO", payer
    assert payer["plan_type"] == PlanType.MEDICAID_MCO.value, payer
    assert payer["weekly_hour_cap"] == 84, payer
    assert payer["evv_required"] is True, payer
    assert payer["billing_edit_ruleset"] == BillingEditRuleset.STRICT_15MIN.value, payer
    assert payer["appeal_window_days"] == 45, payer
    assert payer["reduction_notice_days"] == 20, payer
    assert_numbers_not_strings(
        payer, ["weekly_hour_cap", "appeal_window_days", "reduction_notice_days"]
    )
    assert_versioned_entity(payer)
    assert payer["version"] == 1, payer


def test_omitted_payer_optionals_fall_back_to_the_declared_defaults(api):
    """PRD 3.1 declares four optional payer attributes with defaults:
    `evv_required` true, `billing_edit_ruleset` `STANDARD_15MIN`,
    `appeal_window_days` 30 and `reduction_notice_days` 10. A registration that
    supplies only the three mandatory fields must therefore answer with those
    defaults materialised, never with nulls.

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_declared_defaults
    """
    fx.set_clock(api, C.WEEK32_START)

    payer = validate_success(
        api.create_payer(
            f.payer_payload(
                name="Lakeside Waiver",
                plan_type=PlanType.MEDICAID_WAIVER.value,
                weekly_hour_cap=70,
                evv_required=...,
                billing_edit_ruleset=...,
                appeal_window_days=...,
                reduction_notice_days=...,
            ),
            AGENCY_ADMIN,
        ),
        201,
    )

    assert payer["evv_required"] is True, payer
    assert payer["billing_edit_ruleset"] == BillingEditRuleset.STANDARD_15MIN.value, payer
    assert payer["appeal_window_days"] == 30, payer
    assert payer["reduction_notice_days"] == 10, payer
    assert payer["weekly_hour_cap"] == 70, payer


def test_omitted_nurse_and_patient_optionals_fall_back_to_the_declared_defaults(api):
    """PRD 3.1 defaults a nurse's `max_weekly_hours` to 40 and starts `status` at
    `ACTIVE`; the same section defaults all four patient acuity flags -
    `requires_trach`, `requires_vent`, `requires_feeding_tube` and
    `parent_backup_available` - to false and starts a patient's `status` at
    `ACTIVE`. A nurse with no attested competency has an empty `verified_skills`,
    since that list holds only skills with a `VALID` competency.

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_declared_defaults
    """
    fx.set_clock(api, C.WEEK32_START)
    payer = fx.create_payer(api, name="Lakeside Waiver", weekly_hour_cap=70)

    nurse = validate_success(
        api.create_nurse(
            f.nurse_payload(
                full_name="Ivy Lane",
                license_type=LicenseType.LPN.value,
                license_number="LPN-200001",
                license_expires_on="2027-06-30",
                max_weekly_hours=...,
            ),
            AGENCY_ADMIN,
        ),
        201,
    )
    patient = validate_success(
        api.create_patient(
            f.patient_payload(
                payer["id"],
                full_name="Eli Ford",
                date_of_birth="2021-02-02",
                primary_diagnosis="Spinal muscular atrophy",
                requires_trach=...,
                requires_vent=...,
                requires_feeding_tube=...,
                parent_backup_available=...,
            ),
            CASE_MANAGER,
        ),
        201,
    )

    assert nurse["max_weekly_hours"] == 40, nurse
    assert nurse["status"] == NurseStatus.ACTIVE.value, nurse
    assert patient["requires_trach"] is False, patient
    assert patient["requires_vent"] is False, patient
    assert patient["requires_feeding_tube"] is False, patient
    assert patient["parent_backup_available"] is False, patient
    assert patient["status"] == PatientStatus.ACTIVE.value, patient

    reread = validate_success(api.get_nurse(nurse["id"], AGENCY_ADMIN))
    assert reread["verified_skills"] == [], reread


def test_nurse_get_by_id_returns_the_stored_row_with_its_derived_skills(api):
    """PRD 3.1 says a nurse read exposes the persisted row plus two derived
    quantities: `scheduled_minutes_this_week` and `verified_skills`, the skills
    whose competency is `VALID` with an `expires_on` after the clock date. With
    one TRACH competency attested and no assignment yet, the read must carry
    `verified_skills == ["TRACH"]` and `scheduled_minutes_this_week == 0`
    alongside every stored attribute - not a partial projection.

    Design: Corner/entities/nurse_get_by_id_returns_the_stored_row
    """
    fx.set_clock(api, C.WEEK32_START)
    nurse = fx.register_nurse(api)
    competency = fx.attest_competency(api, nurse["id"], Skill.TRACH.value)

    response = api.get_nurse(nurse["id"], SCHEDULER)
    stored = validate_success(response)

    assert response.json()["response_type"] == "object", response.json()
    assert stored["id"] == nurse["id"], stored
    assert stored["full_name"] == C.NURSE_FULL_NAME, stored
    assert stored["license_type"] == LicenseType.RN.value, stored
    assert stored["license_number"] == C.NURSE_LICENSE_NUMBER, stored
    assert stored["license_expires_on"] == C.NURSE_LICENSE_EXPIRES_ON, stored
    assert stored["max_weekly_hours"] == 48, stored
    assert stored["status"] == NurseStatus.ACTIVE.value, stored
    assert stored["verified_skills"] == [Skill.TRACH.value], stored
    assert stored["scheduled_minutes_this_week"] == 0, stored
    assert_versioned_entity(stored)

    assert competency["validated_by_user_id"] == SUPERVISOR_USER_ID, competency
    assert competency["status"] == CompetencyStatus.VALID.value, competency
    assert competency["skill"] == Skill.TRACH.value, competency


def _three_nurses_one_suspended(api):
    """Three nurses created in order; the third moved to SUSPENDED."""
    fx.set_clock(api, C.WEEK32_START)
    first = fx.register_nurse(api)
    second = fx.register_nurse(api, full_name="Dana Ross", license_number="RN-100002")
    third = fx.register_nurse(
        api,
        full_name="Ivy Lane",
        license_type=LicenseType.LPN.value,
        license_number="LPN-200001",
        max_weekly_hours=...,
    )
    validate_success(
        api.set_nurse_status(
            third["id"], f.nurse_status_payload(NurseStatus.SUSPENDED.value), AGENCY_ADMIN
        )
    )
    return first, second, third


def test_nurse_listing_paginates_with_total_count_and_has_more(api):
    """PRD 2.3 puts `limit`, `offset`, `total_count` and `has_more` in `meta` and
    sorts a list by `created_at` ascending by default. With three nurses on the
    roster, `limit=2&offset=0` must answer two rows with `total_count` 3 and
    `has_more` true, and `limit=2&offset=2` the remaining row with `has_more`
    false - each nurse appearing exactly once across the two pages.

    Design: Corner/entities/nurse_listing_paginates_with_total_count_and_has_more
    """
    first_nurse, second_nurse, third_nurse = _three_nurses_one_suspended(api)

    first_page = api.list_nurses(SCHEDULER, f.pagination(2, 0))
    page_one, meta_one = validate_paginated(first_page)
    assert first_page.json()["response_type"] == "array", first_page.json()
    assert [row["id"] for row in page_one] == [first_nurse["id"], second_nurse["id"]], page_one
    assert meta_one["limit"] == 2, meta_one
    assert meta_one["offset"] == 0, meta_one
    assert meta_one["total_count"] == 3, meta_one
    assert meta_one["has_more"] is True, meta_one

    second_page = api.list_nurses(SCHEDULER, f.pagination(2, 2))
    page_two, meta_two = validate_paginated(second_page)
    assert [row["id"] for row in page_two] == [third_nurse["id"]], page_two
    assert meta_two["total_count"] == 3, meta_two
    assert meta_two["has_more"] is False, meta_two

    seen = [row["id"] for row in page_one] + [row["id"] for row in page_two]
    assert sorted(seen) == sorted(
        [first_nurse["id"], second_nurse["id"], third_nurse["id"]]
    ), seen
    assert len(set(seen)) == 3, seen


def test_a_nurse_status_filter_counts_the_filtered_population_only(api):
    """PRD 3.1 allows `GET /pdn/nurses` to be filtered by `status`, and PRD 2.3
    defines `total_count` as the number of rows matching the request. With one of
    three nurses SUSPENDED, the filtered read must return that single row and a
    `total_count` of 1 - the filter is applied before the count, not after the
    page is cut.

    Design: Corner/entities/nurse_listing_paginates_with_total_count_and_has_more
    """
    _first, _second, third_nurse = _three_nurses_one_suspended(api)

    response = api.list_nurses(
        SCHEDULER, f.pagination(10, 0, status=NurseStatus.SUSPENDED.value)
    )
    rows, meta = validate_paginated(response)

    assert [row["id"] for row in rows] == [third_nurse["id"]], rows
    assert rows[0]["status"] == NurseStatus.SUSPENDED.value, rows[0]
    assert meta["total_count"] == 1, meta
    assert meta["has_more"] is False, meta


def test_patient_get_with_an_unknown_id_returns_patient_not_found(api):
    """PRD 2.7 requires an unresolvable path identifier to answer with the
    entity-specific 404, and PRD 5 fixes `ERR_PATIENT_NOT_FOUND` at 404 for the
    patient. A well-formed UUID that names no row must therefore produce that
    `error_id` in the PRD 2.2 error envelope - with `response_type` `error`, a
    non-empty `message` and `meta.api_request_id` present exactly as on a success.

    Design: Corner/entities/patient_get_with_an_unknown_id_returns_patient_not_found
    """
    fx.set_clock(api, C.WEEK32_START)

    response = api.get_patient(C.UNKNOWN_UUID, CASE_MANAGER)
    validate_error(response, ERR_PATIENT_NOT_FOUND, 404)

    body = response.json()
    assert body["response_type"] == "error", body
    assert isinstance(body["data"]["message"], str), body["data"]
    assert body["data"]["message"].strip() != "", body["data"]
    assert body["meta"]["api_request_id"].startswith("req_"), body["meta"]
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"]), body["meta"]


def test_plan_of_care_without_a_ten_digit_ordering_physician_npi_is_rejected(api):
    """PRD 3.3 requires `ordering_physician_npi` as exactly ten digits and gives
    it no default, so both an omitted value and a nine-digit value fail the
    request-shape check that PRD 2.8 runs at priority 7 as `ERR_INVALID_REQUEST`
    with HTTP 400. Neither rejected call may leave a plan of care behind, so the
    `patient_id`-filtered list must report `total_count` 0.

    Design: Corner/entities/plan_of_care_without_the_ordering_physician_npi_is_rejected
    """
    fx.set_clock(api, C.WEEK32_START)
    payer = fx.create_payer(api)
    patient = fx.create_patient(api, payer["id"])

    omitted = api.create_plan_of_care(
        f.plan_of_care_payload(patient["id"], ordering_physician_npi=...), CASE_MANAGER
    )
    validate_error(omitted, ERR_INVALID_REQUEST, 400)

    nine_digits = api.create_plan_of_care(
        f.plan_of_care_payload(patient["id"], ordering_physician_npi="123456789"),
        CASE_MANAGER,
    )
    validate_error(nine_digits, ERR_INVALID_REQUEST, 400)

    listing = api.list_plans_of_care(
        CASE_MANAGER, f.pagination(10, 0, patient_id=patient["id"])
    )
    rows, meta = validate_paginated(listing)
    assert rows == [], rows
    assert meta["total_count"] == 0, meta


def test_shift_scheduled_minutes_is_derived_from_the_published_window(api):
    """PRD 3.5 says the server derives `scheduled_minutes` as the whole minutes
    between `start_at` and `end_at`, so a 08:00-16:00 window is 480 minutes, and a
    new shift starts with `staffing_status` `OPEN`, `evv_status` `NOT_STARTED`,
    `escalation_tier` `NONE`, `escalated_at` null and `cancel_reason` `NONE`. The
    same paragraph re-derives the case's `unfilled_shift_count` and `fill_rate`
    immediately: one unstaffed shift inside the grant gives 1 and 0.0000.

    Design: Corner/entities/shift_scheduled_minutes_is_derived_from_the_window
    """
    base = fx.setup_baseline(api, with_nurse=False)

    response = api.create_shift(
        f.shift_payload(base.case_id, SHIFT_START, SHIFT_END, [Skill.TRACH.value, Skill.VENT.value]),
        SCHEDULER,
    )
    shift = validate_success(response, 201)

    assert shift["scheduled_minutes"] == 480, shift
    assert isinstance(shift["scheduled_minutes"], int), shift
    assert_shift_axes(shift, StaffingStatus.OPEN.value, EvvStatus.NOT_STARTED.value)
    assert shift["escalation_tier"] == EscalationTier.NONE.value, shift
    assert shift["escalated_at"] is None, shift
    assert shift["cancel_reason"] == ShiftCancelReason.NONE.value, shift
    assert shift["required_skills"] == [Skill.TRACH.value, Skill.VENT.value], shift
    assert_versioned_entity(shift)
    assert shift["version"] == 1, shift

    case = fx.refresh_case(api, base.case_id)
    assert case["unfilled_shift_count"] == 1, case
    assert_ratio(case, "fill_rate", 0.0000)


def test_payer_system_fields_are_server_minted_and_stable_across_a_reread(api):
    """PRD 2.4 mints `id` as a bare UUID with no type prefix, starts `version` at
    1, and stamps `created_at` and `updated_at` as ISO-8601 UTC instants with
    exactly three fractional digits; on a row that has never been mutated the two
    instants are equal. Those minted values belong to the row, so the PRD 2.2
    read of the same payer must return the very same `id`, `created_at` and
    `version`.

    Design: Corner/entities/payer_system_fields_are_server_minted
    """
    fx.set_clock(api, C.WEEK32_START)

    created_response = api.create_payer(
        f.payer_payload(
            evv_required=...,
            billing_edit_ruleset=...,
            appeal_window_days=...,
            reduction_notice_days=...,
        ),
        AGENCY_ADMIN,
    )
    created = validate_success(created_response, 201)

    assert is_valid_uuid(created["id"]), created
    assert "_" not in created["id"], created
    assert ":" not in created["id"], created
    assert created["version"] == 1, created
    assert_millisecond_instants(created_response, ["created_at", "updated_at"])
    assert created["created_at"] == created["updated_at"], created

    reread = validate_success(api.get_payer(created["id"], CASE_MANAGER))
    assert reread["id"] == created["id"], reread
    assert reread["created_at"] == created["created_at"], reread
    assert reread["version"] == created["version"], reread


def test_enum_members_outside_the_declared_sets_are_rejected(api):
    """PRD 3.1 declares `plan_type` over `MEDICAID_MCO`, `MEDICAID_WAIVER` and
    `COMMERCIAL`, and `license_type` over `RN` and `LPN` only. PRD 2.8 catches an
    unknown enum member at priority 7 with `ERR_INVALID_REQUEST` and HTTP 400, so
    a `MEDICARE` payer and an `APRN` nurse are both refused and neither row is
    persisted - the roster read still reports `total_count` 0.

    Design: Corner/entities/illegal_enum_values_and_inverted_windows_are_rejected
    """
    fx.set_clock(api, C.WEEK32_START)

    bad_plan_type = api.create_payer(
        f.payer_payload(name="Medicare Direct", plan_type="MEDICARE"), AGENCY_ADMIN
    )
    validate_error(bad_plan_type, ERR_INVALID_REQUEST, 400)

    bad_license_type = api.create_nurse(
        f.nurse_payload(
            full_name="Ada Poole",
            license_type="APRN",
            license_number="APRN-1",
            max_weekly_hours=...,
        ),
        AGENCY_ADMIN,
    )
    validate_error(bad_license_type, ERR_INVALID_REQUEST, 400)

    listing = api.list_nurses(SCHEDULER, f.pagination(10, 0))
    rows, meta = validate_paginated(listing)
    assert rows == [], rows
    assert meta["total_count"] == 0, meta


def test_a_plan_of_care_window_whose_end_precedes_its_start_is_rejected(api):
    """PRD 3.3 requires a plan of care's `end_date` to be strictly after its
    `start_date`. PRD 2.8 classifies an inverted window as a request-shape failure
    at priority 7, so a plan running from 2026-11-01 to 2026-08-03 answers
    `ERR_INVALID_REQUEST` with HTTP 400 rather than any business-rule error.

    Design: Corner/entities/illegal_enum_values_and_inverted_windows_are_rejected
    """
    fx.set_clock(api, C.WEEK32_START)
    payer = fx.create_payer(api)
    patient = fx.create_patient(api, payer["id"])

    response = api.create_plan_of_care(
        f.plan_of_care_payload(
            patient["id"], start_date="2026-11-01", end_date="2026-08-03"
        ),
        CASE_MANAGER,
    )
    validate_error(response, ERR_INVALID_REQUEST, 400)

    listing = api.list_plans_of_care(
        CASE_MANAGER, f.pagination(10, 0, patient_id=patient["id"])
    )
    _rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 0, meta


def test_supervisory_visit_is_immutable_with_no_version_field(api):
    """PRD 2.4 names `SupervisoryVisit` as the one entity that carries only `id`
    and `created_at`: it has no `updated_at` and no `version`, so no
    `expected_version` handshake can exist for it. PRD 3.4 makes the visit log an
    append-only record, so the read of the case's visits returns the row just
    created, unchanged.

    Design: Corner/entities/supervisory_visit_is_immutable_with_no_version_field
    """
    base = fx.setup_baseline(api, with_nurse=False)

    response = api.create_supervisory_visit(
        base.case_id,
        f.supervisory_visit_payload(
            C.CLOCK_WEEK32_MONDAY_06,
            VisitOutcome.PASS.value,
            notes="home vent settings verified against the plan of care",
        ),
        CLINICAL_SUPERVISOR,
    )
    visit = validate_success(response, 201)

    assert_unversioned_entity(visit)
    assert "version" not in visit, visit
    assert "updated_at" not in visit, visit
    assert visit["case_id"] == base.case_id, visit
    assert visit["outcome"] == VisitOutcome.PASS.value, visit

    rows, meta = validate_unpaginated(
        api.list_supervisory_visits(base.case_id, CLINICAL_SUPERVISOR)
    )
    assert meta["total_count"] == 1, meta
    assert [row["id"] for row in rows] == [visit["id"]], rows
    assert rows[0]["visit_at"] == "2026-08-03T06:00:00.000Z", rows[0]
    assert "version" not in rows[0], rows[0]


def test_a_vent_patient_visit_applies_the_fourteen_day_cadence(api):
    """PRD 3.4 sets the supervisory cadence at 14 days when the patient is
    vent-dependent, and records the figure used on the visit as
    `cadence_days_applied`. A `PASS` visit at 2026-08-03T06:00:00Z therefore moves
    the case's `next_supervisory_visit_due_at` to 2026-08-17T06:00:00.000Z and
    leaves `supervisory_status` `CURRENT`, the clock being well before that date.

    Design: Corner/entities/supervisory_visit_is_immutable_with_no_version_field
    """
    base = fx.setup_baseline(api, with_nurse=False)

    visit = validate_success(
        api.create_supervisory_visit(
            base.case_id,
            f.supervisory_visit_payload(C.CLOCK_WEEK32_MONDAY_06, VisitOutcome.PASS.value),
            CLINICAL_SUPERVISOR,
        ),
        201,
    )

    assert visit["visit_at"] == "2026-08-03T06:00:00.000Z", visit
    assert visit["cadence_days_applied"] == C.CADENCE_DAYS_VENT, visit

    case = fx.refresh_case(api, base.case_id)
    assert case["next_supervisory_visit_due_at"] == "2026-08-17T06:00:00.000Z", case
    assert case["supervisory_status"] == SupervisoryStatus.CURRENT.value, case


def test_patient_creation_with_an_unknown_payer_id_is_a_body_foreign_key_404(api):
    """PRD 2.7 resolves every identifier carried in a request body before any
    shape or business rule runs, answering an unresolvable one with that entity's
    404. A patient whose `payer_id` names no payer is therefore
    `ERR_PAYER_NOT_FOUND` with HTTP 404 - not a 400 and not a dangling row, so the
    patient list still reports `total_count` 0.

    Design: Corner/entities/patient_creation_with_an_unknown_payer_id_is_a_body_fk_404
    """
    fx.set_clock(api, C.WEEK32_START)

    response = api.create_patient(
        f.patient_payload(
            C.UNKNOWN_UUID,
            requires_trach=...,
            requires_vent=...,
            requires_feeding_tube=...,
            parent_backup_available=...,
        ),
        CASE_MANAGER,
    )
    validate_error(response, ERR_PAYER_NOT_FOUND, 404)

    listing = api.list_patients(CASE_MANAGER, f.pagination(10, 0))
    rows, meta = validate_paginated(listing)
    assert rows == [], rows
    assert meta["total_count"] == 0, meta


def test_case_linking_a_patient_and_authorization_of_different_payers_is_rejected(api):
    """PRD 3.4 requires a case's patient and authorization to belong to the same
    payer, and PRD 2.8 places that cross-reference check at priority 14 as
    `ERR_PAYER_MISMATCH` with HTTP 422 - after the priority-11 staffable-status
    check, which an `ACTIVE` grant passes. A child enrolled under payer A cannot
    be opened against payer B's grant, and no case row survives the refusal.

    Design: Corner/entities/case_linking_a_patient_and_authorization_of_different_payers_is_rejected
    """
    fx.set_clock(api)
    payer_a = fx.create_payer(api)
    payer_b = fx.create_payer(
        api,
        name="Lakeside Waiver",
        plan_type=PlanType.MEDICAID_WAIVER.value,
        weekly_hour_cap=70,
    )
    patient = fx.create_patient(api, payer_a["id"])
    plan = fx.create_submitted_plan_of_care(api, patient["id"])
    authorization = fx.create_authorization(
        api, plan["id"], payer_b["id"], plan["version"]
    )
    authorization = fx.activate_authorization(api, authorization["id"], payer_b["id"])
    assert authorization["payer_id"] == payer_b["id"], authorization

    response = api.create_case(
        f.case_payload(patient["id"], authorization["id"], SUPERVISOR_USER_ID),
        CASE_MANAGER,
    )
    validate_error(response, ERR_PAYER_MISMATCH, 422)

    listing = api.list_cases(
        CASE_MANAGER, f.pagination(10, 0, authorization_id=authorization["id"])
    )
    rows, meta = validate_paginated(listing)
    assert rows == [], rows
    assert meta["total_count"] == 0, meta
