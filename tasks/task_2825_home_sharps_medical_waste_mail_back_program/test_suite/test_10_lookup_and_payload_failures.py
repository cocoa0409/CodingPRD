"""Lookup and payload failures in the home-sharps mail-back program: the
per-entity 404 codes, the shape band that rejects a malformed body before any
row is touched, the not-found code a write earns for naming an unknown parent,
and the pagination metadata a filtered listing reports.

Every test builds its own state from an empty database through the program's own
endpoints, and pins the logical clock so that every derived date is reproducible.
"""

from datetime import datetime

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    OMIT,
    assert_empty_listing,
    assert_facility_counters,
    assert_program_balances,
    assert_shipment_axes,
    assert_total_count,
    create_state_rule,
    eligibility_review_payload,
    enrollment_payload,
    is_iso8601_timestamp,
    kit_issuance_payload,
    label_activation_payload,
    packaging_spec_payload,
    patient_payload,
    read_enrollment,
    read_kit,
    read_patient,
    read_program,
    read_return_label,
    read_treatment_facility,
    set_clock,
    setup_active_enrollment,
    setup_printed_label,
    sponsorship_program_payload,
    state_rule_payload,
    treatment_facility_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_AT_CREATION = "2026-08-01T00:00:00Z"

PATIENT_OVERRIDES = {
    "full_name": "Dana Reyes",
    "therapy_type": "INSULIN_PEN_NEEDLES",
    "weekly_sharps_count": 20,
    "contact_email": "dana@example.com",
}
ENROLLMENT_OVERRIDES = {"cadence_days": 30, "kits_authorized": 3}
PROGRAM_OVERRIDES = {
    "program_code": "NW-2026",
    "funding_ceiling_cents": 500000,
    "per_kit_allowance_cents": 5000,
}
STATE_RULE_OVERRIDES = {"household_sharps_classification": "HOUSEHOLD_EXEMPT"}

# One well-formed identifier per entity type, resolving to nothing in any table.
SINGLE_ROW_READS = [
    ("get_state_rule", "ERR_STATE_RULE_NOT_FOUND"),
    ("get_packaging_spec", "ERR_PACKAGING_SPEC_NOT_FOUND"),
    ("get_treatment_facility", "ERR_FACILITY_NOT_FOUND"),
    ("get_sponsor", "ERR_SPONSOR_NOT_FOUND"),
    ("get_sponsorship_program", "ERR_PROGRAM_NOT_FOUND"),
    ("get_patient", "ERR_PATIENT_NOT_FOUND"),
    ("get_enrollment", "ERR_ENROLLMENT_NOT_FOUND"),
    ("get_kit", "ERR_KIT_NOT_FOUND"),
    ("get_return_label", "ERR_LABEL_NOT_FOUND"),
    ("get_shipment", "ERR_SHIPMENT_NOT_FOUND"),
    ("get_non_conformance_event", "ERR_NONCONFORMANCE_EVENT_NOT_FOUND"),
    ("get_destruction_certificate", "ERR_CERTIFICATE_NOT_FOUND"),
    ("get_ledger_entry", "ERR_LEDGER_ENTRY_NOT_FOUND"),
    ("get_auto_ship_run", "ERR_AUTOSHIP_RUN_NOT_FOUND"),
]


# ==========================================================================
# Fourteen entity types, fourteen distinct not-found codes
# ==========================================================================
@pytest.mark.parametrize("reader,expected_error", SINGLE_ROW_READS)
def test_01_an_unknown_id_earns_that_entity_types_own_not_found_code(
    api, program_admin_headers, reader, expected_error
):
    """Each single-row read of an id that matches no row answers with the 404
    code belonging to that entity type.

    PRD 2.6: "Each entity type has its own 404 code: `ERR_STATE_RULE_NOT_FOUND`, `ERR_PACKAGING_SPEC_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_SPONSOR_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_KIT_NOT_FOUND`, `ERR_LABEL_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_NONCONFORMANCE_EVENT_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, `ERR_LEDGER_ENTRY_NOT_FOUND` and `ERR_AUTOSHIP_RUN_NOT_FOUND`, each returning HTTP 404."
    Design: Corner/entities/unknown_ids_on_all_fourteen_single_row_reads_each_return_their_own_not_found_error
    """
    set_clock(api, CLOCK_AT_CREATION)

    response = getattr(api, reader)(NON_EXISTENT_UUID, program_admin_headers)
    validate_error(response, expected_error, 404)


def test_02_the_fourteen_not_found_codes_are_pairwise_distinct(
    api, program_admin_headers
):
    """A single generic not-found code for every entity type is not enough: the
    fourteen reads must be told apart by their `error_id`.

    PRD 2.6: "Each entity type has its own 404 code: `ERR_STATE_RULE_NOT_FOUND`, `ERR_PACKAGING_SPEC_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_SPONSOR_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_KIT_NOT_FOUND`, `ERR_LABEL_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_NONCONFORMANCE_EVENT_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, `ERR_LEDGER_ENTRY_NOT_FOUND` and `ERR_AUTOSHIP_RUN_NOT_FOUND`, each returning HTTP 404."
    Design: Corner/entities/unknown_ids_on_all_fourteen_single_row_reads_each_return_their_own_not_found_error
    """
    set_clock(api, CLOCK_AT_CREATION)

    observed = []
    for reader, _expected in SINGLE_ROW_READS:
        response = getattr(api, reader)(NON_EXISTENT_UUID, program_admin_headers)
        assert response.status_code == 404, (
            f"{reader} on an unknown id must answer 404, got {response.status_code}"
        )
        observed.append(response.json()["data"]["error_id"])

    assert len(observed) == 14, f"expected fourteen reads, made {len(observed)}"
    assert len(set(observed)) == 14, (
        f"the fourteen not-found codes must be pairwise distinct, got {observed}"
    )


# ==========================================================================
# A creation missing one declared input is a shape failure
# ==========================================================================
def _foundations_without_a_facility(api):
    """The catalogue, a funded program and Dana's ACTIVE enrollment, with no
    treatment facility registered yet so that a rejected registration is
    visible as an empty facility listing."""
    return setup_active_enrollment(
        api,
        clock=CLOCK_AT_CREATION,
        with_facility=False,
        state_rule_overrides=STATE_RULE_OVERRIDES,
        program_overrides=PROGRAM_OVERRIDES,
        patient_overrides=PATIENT_OVERRIDES,
        enrollment_overrides=ENROLLMENT_OVERRIDES,
    )


def _creation_missing_one_field(api, ctx, headers, case):
    if case == "patient_without_therapy_type":
        return api.create_patient(
            patient_payload(
                ctx["state_rule"]["id"],
                full_name="Ray Okafor",
                weekly_sharps_count=12,
                contact_email="ray@example.com",
                therapy_type=OMIT,
            ),
            headers,
        )
    if case == "facility_without_daily_intake_capacity_units":
        return api.create_treatment_facility(
            treatment_facility_payload(
                ctx["state_rule"]["id"],
                name="Valley Sharps Treatment",
                permit_number="CA-TF-0001",
                accepted_hazard_classes=["UN3291_SHARPS_ONLY"],
                daily_intake_capacity_units=OMIT,
            ),
            headers,
        )
    if case == "program_without_per_kit_allowance_cents":
        return api.create_sponsorship_program(
            ctx["sponsor"]["id"],
            sponsorship_program_payload(
                program_code="NW-2027",
                funding_ceiling_cents=200000,
                per_kit_allowance_cents=OMIT,
            ),
            headers,
        )
    if case == "enrollment_without_cadence_days":
        return api.create_enrollment(
            enrollment_payload(
                ctx["patient"]["id"],
                ctx["sponsorship_program"]["id"],
                kits_authorized=3,
                cadence_days=OMIT,
            ),
            headers,
        )
    if case == "kit_without_expected_enrollment_version":
        return api.issue_kit(
            ctx["enrollment"]["id"],
            kit_issuance_payload(OMIT),
            headers,
        )
    raise AssertionError(f"unknown case {case!r}")


MISSING_FIELD_CASES = [
    "patient_without_therapy_type",
    "facility_without_daily_intake_capacity_units",
    "program_without_per_kit_allowance_cents",
    "enrollment_without_cadence_days",
    "kit_without_expected_enrollment_version",
]


@pytest.mark.parametrize("case", MISSING_FIELD_CASES)
def test_03_a_creation_omitting_one_declared_input_is_rejected_as_invalid_request(
    api, program_admin_headers, case
):
    """Each write drops exactly one input the PRD declares without a default and
    earns the shape-band refusal.

    PRD 2.6: "The bands are, in order: header validity (`ERR_UNAUTHENTICATED`), role membership (`ERR_ROLE_NOT_PERMITTED`), request shape (`ERR_INVALID_REQUEST`), existence of referenced records (the 404 family above), resource ownership (`ERR_NOT_RESOURCE_OWNER`), state preconditions on the target record, optimistic-concurrency version echoes, and then the four business bands."
    PRD 3.3: "Registering a household sharps generator captures the patient's `full_name`, the `state_rule_id` of their residence state, their `therapy_type`, a self-reported `weekly_sharps_count` that must be a whole number from 1 through 500 inclusive, and a `contact_email` — the address that will be used if their waste is ever rejected and a customer notification becomes due."
    PRD 3.1: "`accepted_hazard_classes` is a non-empty list drawn from the same two hazard classes and records what the facility's permit actually covers, and `daily_intake_capacity_units` — a whole number from 1 through 100000 inclusive — is the number of sharps units the facility may accept for a single UTC intake date."
    PRD 3.2: "Opening a funded program under a sponsor draws `sponsor_id` from the path rather than the payload; the payload carries a `program_code` of 1 to 32 characters unique across all programs, a `funding_ceiling_cents` figure and a `per_kit_allowance_cents` figure, each a whole number from 1 through 100000000 inclusive."
    PRD 3.3: "The payload names the `patient_id` and the `sponsorship_program_id`, sets a `cadence_days` figure that must be a whole number from 14 through 180 inclusive, sets `kits_authorized` — a whole number from 1 through 24 inclusive capping the number of non-voided kits the enrollment may ever hold — and may optionally record a `requested_container_size` drawn from `ONE_QUART`, `TWO_GALLON`, `THREE_GALLON` and `EIGHT_GALLON`, which defaults to null."
    PRD 2.5: "In both cases the version field is a required, non-optional element of the request body, and a mismatch is a rejection rather than a retry."
    Design: Corner/entities/creations_missing_required_input_fields_return_invalid_request
    """
    ctx = _foundations_without_a_facility(api)

    response = _creation_missing_one_field(api, ctx, program_admin_headers, case)
    validate_error(response, "ERR_INVALID_REQUEST", 400)


def test_04_the_rejected_creations_leave_no_rows_behind(
    api, program_admin_headers
):
    """After all five malformed writes the catalogues still hold exactly what the
    setup put there and no kit was minted.

    PRD 2.6: "The bands are, in order: header validity (`ERR_UNAUTHENTICATED`), role membership (`ERR_ROLE_NOT_PERMITTED`), request shape (`ERR_INVALID_REQUEST`), existence of referenced records (the 404 family above), resource ownership (`ERR_NOT_RESOURCE_OWNER`), state preconditions on the target record, optimistic-concurrency version echoes, and then the four business bands."
    Design: Corner/entities/creations_missing_required_input_fields_return_invalid_request
    """
    ctx = _foundations_without_a_facility(api)
    for case in MISSING_FIELD_CASES:
        response = _creation_missing_one_field(api, ctx, program_admin_headers, case)
        validate_error(response, "ERR_INVALID_REQUEST", 400)

    assert_total_count(api.list_patients(program_admin_headers), 1)
    assert_empty_listing(api.list_treatment_facilities(program_admin_headers))
    assert_total_count(
        api.list_sponsor_programs(ctx["sponsor"]["id"], program_admin_headers), 1
    )
    assert_empty_listing(
        api.list_kits(
            program_admin_headers, {"enrollment_id": ctx["enrollment"]["id"]}
        )
    )


def test_05_a_missing_version_echo_leaves_the_enrollment_and_the_money_untouched(
    api, program_admin_headers
):
    """The kit request that omitted `expected_enrollment_version` neither bumped
    the enrollment's own `version` nor reserved a cent.

    PRD 2.5: "In both cases the version field is a required, non-optional element of the request body, and a mismatch is a rejection rather than a retry."
    PRD 2.6: "The bands are, in order: header validity (`ERR_UNAUTHENTICATED`), role membership (`ERR_ROLE_NOT_PERMITTED`), request shape (`ERR_INVALID_REQUEST`), existence of referenced records (the 404 family above), resource ownership (`ERR_NOT_RESOURCE_OWNER`), state preconditions on the target record, optimistic-concurrency version echoes, and then the four business bands."
    Design: Corner/entities/creations_missing_required_input_fields_return_invalid_request
    """
    ctx = _foundations_without_a_facility(api)
    version_before = read_enrollment(api, ctx["enrollment"]["id"])["version"]

    response = _creation_missing_one_field(
        api, ctx, program_admin_headers, "kit_without_expected_enrollment_version"
    )
    validate_error(response, "ERR_INVALID_REQUEST", 400)

    enrollment = read_enrollment(api, ctx["enrollment"]["id"])
    assert enrollment["version"] == version_before
    assert enrollment["kits_issued"] == 0

    program = read_program(api, ctx["sponsorship_program"]["id"])
    assert_program_balances(program, reserved_cents=0, available_cents=500000)


# ==========================================================================
# Values outside a declared enum or range are shape failures too
# ==========================================================================
def _rule_and_pending_patient(api, headers):
    """The CA rule plus Dana registered and still awaiting her eligibility
    determination — the smallest state in which every shape probe below is
    meaningful."""
    set_clock(api, CLOCK_AT_CREATION)
    rule = create_state_rule(
        api,
        state_code="CA",
        household_sharps_classification="HOUSEHOLD_EXEMPT",
        mail_back_permitted=True,
        max_container_volume_liters=30.3,
        certificate_retention_years=3,
    )
    patient = validate_success(
        api.create_patient(patient_payload(rule["id"], **PATIENT_OVERRIDES), headers),
        201,
    )
    return rule, patient


def _out_of_domain_write(api, rule, patient, headers, case):
    if case == "therapy_type_outside_the_declared_set":
        return api.create_patient(
            patient_payload(
                rule["id"],
                full_name="Ray Okafor",
                therapy_type="INSULIN_PUMP",
                weekly_sharps_count=12,
                contact_email="ray@example.com",
            ),
            headers,
        )
    if case == "negative_weekly_sharps_count":
        return api.create_patient(
            patient_payload(
                rule["id"],
                full_name="Ray Okafor",
                therapy_type="LANCETS_ONLY",
                weekly_sharps_count=-5,
                contact_email="ray@example.com",
            ),
            headers,
        )
    if case == "classification_outside_the_declared_set":
        return api.create_state_rule(
            state_rule_payload(
                state_code="NV",
                household_sharps_classification="EXEMPT",
                mail_back_permitted=False,
                max_container_volume_liters=11.4,
                certificate_retention_years=4,
            ),
            headers,
        )
    if case == "empty_allowed_container_sizes":
        return api.create_packaging_spec(
            packaging_spec_payload(
                spec_code="PS-E",
                un_specification_code="UN 4G/X7.5/S/26",
                postal_service="USPS_PARCEL_SELECT_MAILBACK",
                hazard_class="UN3291_SHARPS_ONLY",
                max_gross_weight_grams=7500,
                allowed_container_sizes=[],
            ),
            headers,
        )
    if case == "eligibility_decision_outside_the_declared_set":
        return api.review_patient_eligibility(
            patient["id"], eligibility_review_payload("MAYBE"), headers
        )
    raise AssertionError(f"unknown case {case!r}")


OUT_OF_DOMAIN_CASES = [
    "therapy_type_outside_the_declared_set",
    "negative_weekly_sharps_count",
    "classification_outside_the_declared_set",
    "empty_allowed_container_sizes",
    "eligibility_decision_outside_the_declared_set",
]


@pytest.mark.parametrize("case", OUT_OF_DOMAIN_CASES)
def test_06_a_value_outside_its_declared_domain_is_rejected_as_invalid_request(
    api, program_admin_headers, case
):
    """An enum member the PRD never names, a negative count and an empty
    non-empty list are all shape failures rather than business failures.

    PRD 3.3: "The `therapy_type` is one of `INSULIN_PEN_NEEDLES`, `INSULIN_SYRINGES`, `AUTOINJECTOR_PENS`, `INFUSION_SETS` or `LANCETS_ONLY`, and it does double duty: it sets the per-item unit factor used to size containers and it applies a therapy-specific eligibility filter over the size catalogue."
    PRD 3.3: "Registering a household sharps generator captures the patient's `full_name`, the `state_rule_id` of their residence state, their `therapy_type`, a self-reported `weekly_sharps_count` that must be a whole number from 1 through 500 inclusive, and a `contact_email` — the address that will be used if their waste is ever rejected and a customer notification becomes due."
    PRD 2.10: "A state rule declares how the state classifies used household sharps through `household_sharps_classification` — `REGULATED_MEDICAL_WASTE`, `CONDITIONALLY_EXEMPT` or `HOUSEHOLD_EXEMPT` — and whether mail-back is permitted at all through `mail_back_permitted`."
    PRD 3.1: "A `max_gross_weight_grams` ceiling — a whole number from 100 through 31700 inclusive — states the heaviest parcel the carrier will accept under this specification, and `allowed_container_sizes` is a non-empty list drawn from `ONE_QUART`, `TWO_GALLON`, `THREE_GALLON` and `EIGHT_GALLON` naming the inner containers the outer box is certified to hold."
    PRD 3.3: "A `ProgramAdmin` records the determination by supplying a `decision` of `APPROVE` or `DENY` with an optional `note`, and the patient must be in `PENDING_ELIGIBILITY` for either branch to be legal — a second review attempt on an already-decided patient is refused with `ERR_INVALID_PATIENT_STATE`."
    PRD 2.6: "The bands are, in order: header validity (`ERR_UNAUTHENTICATED`), role membership (`ERR_ROLE_NOT_PERMITTED`), request shape (`ERR_INVALID_REQUEST`), existence of referenced records (the 404 family above), resource ownership (`ERR_NOT_RESOURCE_OWNER`), state preconditions on the target record, optimistic-concurrency version echoes, and then the four business bands."
    Design: Corner/entities/invalid_enum_values_and_out_of_range_integers_are_rejected_as_invalid_request
    """
    rule, patient = _rule_and_pending_patient(api, program_admin_headers)

    response = _out_of_domain_write(api, rule, patient, program_admin_headers, case)
    validate_error(response, "ERR_INVALID_REQUEST", 400)


@pytest.mark.parametrize(
    "reader,params",
    [
        ("list_state_rules", {"limit": 101}),
        ("list_patients", {"offset": -1}),
    ],
)
def test_07_pagination_arguments_outside_their_declared_range_are_refused(
    api, program_admin_headers, reader, params
):
    """A `limit` above 100 and a negative `offset` are refused outright instead
    of being quietly clamped into range.

    PRD 2.3: "`limit` controls page size: it defaults to 10 when omitted, its minimum accepted value is 1 and its maximum accepted value is 100."
    PRD 2.3: "A `limit` outside the range 1 through 100, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400) rather than being silently clamped."
    Design: Corner/entities/invalid_enum_values_and_out_of_range_integers_are_rejected_as_invalid_request
    """
    _rule_and_pending_patient(api, program_admin_headers)

    response = getattr(api, reader)(program_admin_headers, params)
    validate_error(response, "ERR_INVALID_REQUEST", 400)


def test_08_no_rejected_shape_probe_writes_a_row_or_moves_the_patient(
    api, program_admin_headers
):
    """After all seven refusals the database still holds one rule and one
    patient, holds no packaging specification, and Dana is still undecided.

    PRD 2.6: "The bands are, in order: header validity (`ERR_UNAUTHENTICATED`), role membership (`ERR_ROLE_NOT_PERMITTED`), request shape (`ERR_INVALID_REQUEST`), existence of referenced records (the 404 family above), resource ownership (`ERR_NOT_RESOURCE_OWNER`), state preconditions on the target record, optimistic-concurrency version echoes, and then the four business bands."
    PRD 3.3: "A new patient begins at `PENDING_ELIGIBILITY` with `screening_risk_score` at 0, `audit_risk_score` at 0 and `suspended_at` null."
    Design: Corner/entities/invalid_enum_values_and_out_of_range_integers_are_rejected_as_invalid_request
    """
    rule, patient = _rule_and_pending_patient(api, program_admin_headers)

    for case in OUT_OF_DOMAIN_CASES:
        response = _out_of_domain_write(api, rule, patient, program_admin_headers, case)
        validate_error(response, "ERR_INVALID_REQUEST", 400)
    validate_error(
        api.list_state_rules(program_admin_headers, {"limit": 101}),
        "ERR_INVALID_REQUEST",
        400,
    )
    validate_error(
        api.list_patients(program_admin_headers, {"offset": -1}),
        "ERR_INVALID_REQUEST",
        400,
    )

    assert_total_count(api.list_patients(program_admin_headers), 1)
    assert_total_count(api.list_state_rules(program_admin_headers), 1)
    assert_empty_listing(api.list_packaging_specs(program_admin_headers))

    stored = read_patient(api, patient["id"])
    assert stored["status"] == "PENDING_ELIGIBILITY"
    assert stored["version"] == 1


# ==========================================================================
# A write naming an unknown parent earns that parent's not-found code
# ==========================================================================
def _write_naming_an_unknown_parent(api, ctx, headers, case):
    if case == "facility_under_an_unknown_state_rule":
        return api.create_treatment_facility(
            treatment_facility_payload(
                NON_EXISTENT_UUID,
                name="Valley Sharps Treatment",
                permit_number="CA-TF-0001",
                accepted_hazard_classes=["UN3291_SHARPS_ONLY"],
                daily_intake_capacity_units=1000,
            ),
            headers,
        )
    if case == "enrollment_for_an_unknown_patient":
        return api.create_enrollment(
            enrollment_payload(
                NON_EXISTENT_UUID,
                ctx["sponsorship_program"]["id"],
                cadence_days=30,
                kits_authorized=2,
            ),
            headers,
        )
    if case == "enrollment_against_an_unknown_program":
        return api.create_enrollment(
            enrollment_payload(
                ctx["patient"]["id"],
                NON_EXISTENT_UUID,
                cadence_days=30,
                kits_authorized=2,
            ),
            headers,
        )
    if case == "kit_under_an_unknown_enrollment":
        return api.issue_kit(
            NON_EXISTENT_UUID,
            kit_issuance_payload(read_enrollment(api, ctx["enrollment"]["id"])["version"]),
            headers,
        )
    raise AssertionError(f"unknown case {case!r}")


UNKNOWN_PARENT_CASES = [
    ("facility_under_an_unknown_state_rule", "ERR_STATE_RULE_NOT_FOUND"),
    ("enrollment_for_an_unknown_patient", "ERR_PATIENT_NOT_FOUND"),
    ("enrollment_against_an_unknown_program", "ERR_PROGRAM_NOT_FOUND"),
    ("kit_under_an_unknown_enrollment", "ERR_ENROLLMENT_NOT_FOUND"),
]


@pytest.mark.parametrize("case,expected_error", UNKNOWN_PARENT_CASES)
def test_09_naming_an_unknown_parent_returns_that_parents_own_not_found_code(
    api, program_admin_headers, case, expected_error
):
    """Whether the unknown identifier sits in the path or in the body, the
    refusal names the entity type that failed to resolve.

    PRD 2.6: "Path parameters are resolved strictly left to right, and the first identifier that resolves to nothing determines the error."
    PRD 2.6: "Only after every path identifier has resolved does the server look up identifiers carried in the request body."
    PRD 2.6: "A `state_rule_id` in a body, a `packaging_spec_id`, a `treatment_facility_id`, a `sponsorship_program_id`, a `patient_id`, an `enrollment_id`, a `kit_id`, a `return_label_id`, a `shipment_id`, a `supersedes_kit_id` or an `auto_ship_run_id` that matches no row raises the corresponding code."
    PRD 3.1: "Registering a facility against a `state_rule_id` that matches nothing fails with `ERR_STATE_RULE_NOT_FOUND`."
    Design: Corner/entities/writes_naming_a_nonexistent_parent_id_are_rejected_with_that_parents_not_found_code
    """
    ctx = _foundations_without_a_facility(api)

    response = _write_naming_an_unknown_parent(api, ctx, program_admin_headers, case)
    validate_error(response, expected_error, 404)


def test_10_an_unknown_enrollment_in_the_path_outranks_the_version_echo(
    api, program_admin_headers
):
    """The kit request carries a well-formed version echo, yet the unresolved
    path identifier is diagnosed first because existence outranks concurrency.

    PRD 2.6: "The bands are, in order: header validity (`ERR_UNAUTHENTICATED`), role membership (`ERR_ROLE_NOT_PERMITTED`), request shape (`ERR_INVALID_REQUEST`), existence of referenced records (the 404 family above), resource ownership (`ERR_NOT_RESOURCE_OWNER`), state preconditions on the target record, optimistic-concurrency version echoes, and then the four business bands."
    PRD 2.6: "Path parameters are resolved strictly left to right, and the first identifier that resolves to nothing determines the error."
    Design: Corner/entities/writes_naming_a_nonexistent_parent_id_are_rejected_with_that_parents_not_found_code
    """
    ctx = _foundations_without_a_facility(api)
    version_before = read_enrollment(api, ctx["enrollment"]["id"])["version"]

    response = _write_naming_an_unknown_parent(
        api, ctx, program_admin_headers, "kit_under_an_unknown_enrollment"
    )
    validate_error(response, "ERR_ENROLLMENT_NOT_FOUND", 404)

    assert read_enrollment(api, ctx["enrollment"]["id"])["version"] == version_before


def test_11_the_rejected_parent_writes_create_nothing(api, program_admin_headers):
    """None of the four refusals leaves a facility, an extra enrollment or a kit
    behind.

    PRD 2.6: "A `state_rule_id` in a body, a `packaging_spec_id`, a `treatment_facility_id`, a `sponsorship_program_id`, a `patient_id`, an `enrollment_id`, a `kit_id`, a `return_label_id`, a `shipment_id`, a `supersedes_kit_id` or an `auto_ship_run_id` that matches no row raises the corresponding code."
    Design: Corner/entities/writes_naming_a_nonexistent_parent_id_are_rejected_with_that_parents_not_found_code
    """
    ctx = _foundations_without_a_facility(api)

    for case, expected_error in UNKNOWN_PARENT_CASES:
        response = _write_naming_an_unknown_parent(
            api, ctx, program_admin_headers, case
        )
        validate_error(response, expected_error, 404)

    assert_empty_listing(api.list_treatment_facilities(program_admin_headers))
    assert_total_count(
        api.list_enrollments(program_admin_headers, {"patient_id": ctx["patient"]["id"]}),
        1,
    )
    assert_empty_listing(
        api.list_kits(program_admin_headers, {"enrollment_id": ctx["enrollment"]["id"]})
    )


# ==========================================================================
# The state-rule catalogue listing: pagination over the filtered set
# ==========================================================================
def _three_state_rules(api):
    """Exactly three state rules — CA and TX permit mail-back, NV does not."""
    set_clock(api, CLOCK_AT_CREATION)
    create_state_rule(
        api,
        state_code="CA",
        household_sharps_classification="HOUSEHOLD_EXEMPT",
        mail_back_permitted=True,
        max_container_volume_liters=30.3,
        certificate_retention_years=3,
    )
    create_state_rule(
        api,
        state_code="NV",
        household_sharps_classification="REGULATED_MEDICAL_WASTE",
        mail_back_permitted=False,
        max_container_volume_liters=11.4,
        certificate_retention_years=4,
    )
    create_state_rule(
        api,
        state_code="TX",
        household_sharps_classification="CONDITIONALLY_EXEMPT",
        mail_back_permitted=True,
        max_container_volume_liters=7.6,
        certificate_retention_years=2,
    )


def test_12_the_first_page_reports_the_unpaginated_total_and_flags_more_to_come(
    api, logistics_coordinator_headers
):
    """A two-row page over three rules echoes the effective window, reports the
    full total and announces that records remain.

    PRD 2.3: "Four pagination fields appear in the `meta` object of every list response: `limit` and `offset` echo the effective values used to build the page, `total_count` reports the number of records matching the filters before pagination is applied, and `has_more` is true exactly when records matching the filters remain beyond the current page."
    Design: Corner/entities/state_rules_listing_paginates_and_filters_with_total_count_and_has_more
    """
    _three_state_rules(api)

    rows, meta = validate_paginated(
        api.list_state_rules(logistics_coordinator_headers, {"limit": 2, "offset": 0})
    )
    assert len(rows) == 2, f"expected a two-row page, got {len(rows)}"
    assert meta["total_count"] == 3
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["has_more"] is True


def test_13_the_last_page_holds_the_remainder_and_clears_has_more(
    api, logistics_coordinator_headers
):
    """Offsetting past the first two rules leaves a single row and nothing beyond
    it, while `total_count` still counts the whole catalogue.

    PRD 2.3: "`offset` controls the starting position: it defaults to 0 and its minimum accepted value is 0."
    PRD 2.3: "Four pagination fields appear in the `meta` object of every list response: `limit` and `offset` echo the effective values used to build the page, `total_count` reports the number of records matching the filters before pagination is applied, and `has_more` is true exactly when records matching the filters remain beyond the current page."
    Design: Corner/entities/state_rules_listing_paginates_and_filters_with_total_count_and_has_more
    """
    _three_state_rules(api)

    rows, meta = validate_paginated(
        api.list_state_rules(logistics_coordinator_headers, {"limit": 2, "offset": 2})
    )
    assert len(rows) == 1, f"expected the remainder of one row, got {len(rows)}"
    assert meta["total_count"] == 3
    assert meta["limit"] == 2
    assert meta["offset"] == 2
    assert meta["has_more"] is False


def test_14_filtering_by_state_code_narrows_the_total_count_itself(
    api, logistics_coordinator_headers
):
    """`total_count` is computed over the filtered set, so asking for Nevada
    reports one rule rather than three.

    PRD 3.1: "State rules can be listed and filtered by `state_code` or by `mail_back_permitted`."
    PRD 2.3: "Four pagination fields appear in the `meta` object of every list response: `limit` and `offset` echo the effective values used to build the page, `total_count` reports the number of records matching the filters before pagination is applied, and `has_more` is true exactly when records matching the filters remain beyond the current page."
    Design: Corner/entities/state_rules_listing_paginates_and_filters_with_total_count_and_has_more
    """
    _three_state_rules(api)

    rows, meta = validate_paginated(
        api.list_state_rules(logistics_coordinator_headers, {"state_code": "NV"})
    )
    assert len(rows) == 1
    assert rows[0]["state_code"] == "NV"
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_15_filtering_by_mail_back_permitted_returns_only_the_permitting_states(
    api, logistics_coordinator_headers
):
    """The two mail-back states come back together and Nevada is excluded.

    PRD 3.1: "State rules can be listed and filtered by `state_code` or by `mail_back_permitted`."
    Design: Corner/entities/state_rules_listing_paginates_and_filters_with_total_count_and_has_more
    """
    _three_state_rules(api)

    rows, meta = validate_paginated(
        api.list_state_rules(
            logistics_coordinator_headers, {"mail_back_permitted": "true"}
        )
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert {row["state_code"] for row in rows} == {"CA", "TX"}
    assert all(row["mail_back_permitted"] is True for row in rows)


def test_16_an_unparameterised_listing_falls_back_to_the_declared_page_defaults(
    api, logistics_coordinator_headers
):
    """With no query parameters the page is ten wide starting at zero, which
    holds all three rules at once.

    PRD 2.3: "`limit` controls page size: it defaults to 10 when omitted, its minimum accepted value is 1 and its maximum accepted value is 100."
    PRD 2.3: "`offset` controls the starting position: it defaults to 0 and its minimum accepted value is 0."
    Design: Corner/entities/state_rules_listing_paginates_and_filters_with_total_count_and_has_more
    """
    _three_state_rules(api)

    rows, meta = validate_paginated(api.list_state_rules(logistics_coordinator_headers))
    assert len(rows) == 3
    assert meta["total_count"] == 3
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["has_more"] is False


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, so that two spellings of the same instant
    compare equal regardless of how many fractional-second digits are printed."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_instant(actual, expected: str, field: str) -> None:
    assert is_iso8601_timestamp(actual), (
        f"{field} must be an ISO 8601 UTC instant, got {actual!r}"
    )
    assert _instant(actual) == _instant(expected), (
        f"Expected {field} {expected}, got {actual}"
    )


# ==========================================================================
# The shipment's three-way fan-in, read from both ends
# ==========================================================================
PACKAGING_SPEC_OVERRIDES = {
    "spec_code": "PS-A",
    "max_gross_weight_grams": 7500,
    "allowed_container_sizes": [
        "ONE_QUART",
        "TWO_GALLON",
        "THREE_GALLON",
        "EIGHT_GALLON",
    ],
    "requires_absorbent": False,
    "status": "ACTIVE",
}
FACILITY_OVERRIDES = {
    "name": "Valley Sharps Treatment",
    "permit_number": "CA-TF-0001",
    "accepted_hazard_classes": ["UN3291_SHARPS_ONLY"],
    "daily_intake_capacity_units": 1000,
    "status": "ACTIVE",
}


def _tender_dana_parcel(api, headers):
    """Dana's ONE_QUART kit sealed with 60 units at 1200 g and its label printed,
    then tendered to the postal service, which is what mints the shipment."""
    ctx = setup_printed_label(
        api,
        clock=CLOCK_AT_CREATION,
        state_rule_overrides=STATE_RULE_OVERRIDES,
        packaging_spec_overrides=PACKAGING_SPEC_OVERRIDES,
        facility_overrides=FACILITY_OVERRIDES,
        program_overrides=PROGRAM_OVERRIDES,
        patient_overrides=PATIENT_OVERRIDES,
        enrollment_overrides=ENROLLMENT_OVERRIDES,
        fill_units=60,
        sealed_gross_weight_grams=1200,
    )
    shipment = validate_success(
        api.activate_return_label(
            ctx["return_label"]["id"],
            label_activation_payload(
                ctx["treatment_facility"]["id"],
                scheduled_intake_date="2026-08-10",
                declared_gross_weight_grams=1200,
            ),
            headers,
        ),
        201,
    )
    return ctx, shipment


def test_17_activation_copies_the_three_parent_ids_onto_the_new_shipment(
    api, logistics_coordinator_headers
):
    """The shipment names the kit it carries, the label whose activation produced
    it and the facility it is routed to, and freezes the sealed unit count.

    PRD 3.6: "A shipment is created, copying `kit_id` from the label's kit and recording `return_label_id` as the label whose activation produced it, storing the submitted `treatment_facility_id`, `scheduled_intake_date`, `declared_gross_weight_grams` and `state_manifest_number`, freezing `custody_units` to the kit's `fill_units` as of this instant — a value that never changes afterwards, whatever happens to the kit — and setting `tendered_at` to the current logical-clock instant."
    Design: Corner/entities/shipment_cross_aggregate_foreign_keys_resolve_in_both_directions
    """
    ctx, shipment = _tender_dana_parcel(api, logistics_coordinator_headers)

    assert shipment["kit_id"] == ctx["kit"]["id"]
    assert shipment["return_label_id"] == ctx["return_label"]["id"]
    assert shipment["treatment_facility_id"] == ctx["treatment_facility"]["id"]
    assert shipment["custody_units"] == 60
    assert shipment["scheduled_intake_date"] == "2026-08-10"
    assert shipment["declared_gross_weight_grams"] == 1200


def test_18_the_new_shipment_starts_tendered_and_unscreened_with_nothing_observed(
    api, logistics_coordinator_headers
):
    """Both state dimensions start at their opening values and every field that
    only screening or delivery can fill is still null.

    PRD 3.6: "Its two axes start at `transport_status` `TENDERED` and `conformance_status` `UNSCREENED`, with `observed_gross_weight_grams`, `delivered_at` and `screened_by_user_id` all null."
    PRD 3.6: "A shipment is created, copying `kit_id` from the label's kit and recording `return_label_id` as the label whose activation produced it, storing the submitted `treatment_facility_id`, `scheduled_intake_date`, `declared_gross_weight_grams` and `state_manifest_number`, freezing `custody_units` to the kit's `fill_units` as of this instant — a value that never changes afterwards, whatever happens to the kit — and setting `tendered_at` to the current logical-clock instant."
    Design: Corner/entities/shipment_cross_aggregate_foreign_keys_resolve_in_both_directions
    """
    _ctx, shipment = _tender_dana_parcel(api, logistics_coordinator_headers)

    assert_shipment_axes(
        shipment,
        transport_status="TENDERED",
        conformance_status="UNSCREENED",
        custody_units=60,
        screened_by_user_id=None,
    )
    _assert_instant(shipment["tendered_at"], CLOCK_AT_CREATION, "tendered_at")
    assert shipment["delivered_at"] is None
    assert shipment["observed_gross_weight_grams"] is None


@pytest.mark.parametrize(
    "filter_key",
    ["kit_id", "return_label_id", "treatment_facility_id"],
)
def test_19_the_shipment_is_reachable_from_each_of_its_three_parents(
    api, logistics_coordinator_headers, filter_key
):
    """Filtering the shipment listing by any one of the three foreign keys
    returns exactly the parcel that was just tendered.

    PRD 3.6: "Shipments are readable individually and as a list filtered by `kit_id`, `return_label_id`, `treatment_facility_id`, `transport_status`, `conformance_status` or `scheduled_intake_date`."
    Design: Corner/entities/shipment_cross_aggregate_foreign_keys_resolve_in_both_directions
    """
    _ctx, shipment = _tender_dana_parcel(api, logistics_coordinator_headers)

    rows, meta = validate_paginated(
        api.list_shipments(
            logistics_coordinator_headers, {filter_key: shipment[filter_key]}
        )
    )
    assert meta["total_count"] == 1, (
        f"filtering shipments by {filter_key} must find exactly one parcel, "
        f"got {meta['total_count']}"
    )
    assert len(rows) == 1
    assert rows[0]["id"] == shipment["id"]


def test_20_activation_advances_the_label_and_the_facility_but_not_the_kit(
    api, logistics_coordinator_headers
):
    """The label becomes `ACTIVATED`, the facility books the 60 units, and the kit
    deliberately stays `SEALED` until the carrier's first scan.

    PRD 3.6: "The label moves `PRINTED → ACTIVATED` with `activated_at` set to the current logical-clock instant and its `version` incremented by 1."
    PRD 3.6: "The destination facility's `pending_intake_units` rises by the new shipment's `custody_units`."
    PRD 3.6: "The kit itself stays `SEALED`: it does not advance until the carrier's first scan."
    Design: Corner/entities/shipment_cross_aggregate_foreign_keys_resolve_in_both_directions
    """
    ctx, _shipment = _tender_dana_parcel(api, logistics_coordinator_headers)

    label = read_return_label(api, ctx["return_label"]["id"])
    assert label["status"] == "ACTIVATED"
    _assert_instant(label["activated_at"], CLOCK_AT_CREATION, "activated_at")

    assert read_kit(api, ctx["kit"]["id"])["status"] == "SEALED"

    facility = read_treatment_facility(api, ctx["treatment_facility"]["id"])
    assert_facility_counters(facility, pending_intake_units=60)
