"""Refusals on the write paths that seed the catalogues, mint a container and
put it in the mail.

Every test builds its own world from scratch through the PRD's own endpoints;
the harness restarts the server with an empty database before each one. Each
refusal is asserted together with the state it must NOT have written.
"""

from test_helpers import (
    TEST_USERS,
    acknowledge_kit,
    add_enrolled_patient,
    assert_facility_counters,
    assert_kit,
    assert_enrollment,
    assert_program_balances,
    assert_return_label,
    assert_shipment_axes,
    assert_total_count,
    create_draft_enrollment,
    create_eligible_patient,
    create_packaging_spec,
    create_state_rule,
    enrollment_payload,
    get_success_data,
    issue_kit_for,
    kit_issuance_payload,
    label_activation_payload,
    make_patient_headers,
    make_sponsor_representative_headers,
    packaging_spec_payload,
    read_enrollment,
    read_enrollment_version,
    read_kit,
    read_program,
    read_treatment_facility,
    return_label_payload,
    seal_kit_for,
    seal_payload,
    sponsor_decision_payload,
    state_rule_payload,
    setup_program_foundations,
    treatment_facility_payload,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
LOGISTICS = TEST_USERS["logistics_coordinator_headers"]

_EXEMPT_CA_RULE = {
    "state_code": "CA",
    "household_sharps_classification": "HOUSEHOLD_EXEMPT",
    "mail_back_permitted": True,
    "max_container_volume_liters": 30.3,
    "certificate_retention_years": 3,
}
_MAILBACK_SPEC = {
    "spec_code": "MB-USPS",
    "un_specification_code": "UN 4G/X7.5/S/26",
    "postal_service": "USPS_PARCEL_SELECT_MAILBACK",
    "hazard_class": "UN3291_SHARPS_ONLY",
    "max_gross_weight_grams": 8000,
    "allowed_container_sizes": ["ONE_QUART", "TWO_GALLON"],
}
_SHARPS_ONLY_FACILITY = {
    "name": "Bay Area Sharps Treatment",
    "permit_number": "CA-TF-0001",
    "accepted_hazard_classes": ["UN3291_SHARPS_ONLY"],
    "daily_intake_capacity_units": 200,
}
_MANUFACTURER = {"sponsor_type": "MANUFACTURER"}
_PROGRAM = {"program_code": "NW-2026", "funding_ceiling_cents": 500000, "per_kit_allowance_cents": 5000}
_DANA = {"full_name": "Dana Reyes", "weekly_sharps_count": 20, "contact_email": "dana@example.com"}


# ==========================================================================
# The four uniqueness scopes (PRD 3.1, 3.3)
# ==========================================================================
def _one_of_each_configuration_row(api):
    """One state rule, one packaging spec and one facility exist, and Dana holds
    a single DRAFT enrollment against the funded program."""
    ctx = setup_program_foundations(
        api,
        state_rule_overrides=dict(_EXEMPT_CA_RULE),
        packaging_spec_overrides=dict(_MAILBACK_SPEC),
        facility_overrides=dict(_SHARPS_ONLY_FACILITY),
        sponsor_overrides=dict(_MANUFACTURER),
        program_overrides=dict(_PROGRAM),
    )
    ctx["patient"] = create_eligible_patient(api, ctx["state_rule"]["id"], **_DANA)
    ctx["enrollment"] = create_draft_enrollment(
        api,
        ctx["patient"]["id"],
        ctx["sponsorship_program"]["id"],
        cadence_days=30,
        kits_authorized=3,
    )
    return ctx


def test_01_a_second_rule_for_the_same_state_code_is_refused(api):
    """The state rule's uniqueness scope is the two-letter `state_code`, and a
    refused registration must not overwrite the row already on file.

    PRD 3.1: "Registration takes a `state_code` — exactly two uppercase letters, and no two state rules may share one, a duplicate being refused with `ERR_DUPLICATE_STATE_RULE` — together with the state's `household_sharps_classification`, its `mail_back_permitted` flag, a `max_container_volume_liters` figure that must be greater than zero, and a `certificate_retention_years` value that must be a whole number from 0 through 30 inclusive."
    PRD 3.1: "State rules can be listed and filtered by `state_code` or by `mail_back_permitted`."
    Design: Corner/errors/the_four_uniqueness_errors_each_fire_on_their_own_endpoint
    """
    ctx = _one_of_each_configuration_row(api)

    response = api.create_state_rule(
        state_rule_payload(
            state_code="CA",
            household_sharps_classification="CONDITIONALLY_EXEMPT",
            mail_back_permitted=False,
            max_container_volume_liters=7.6,
            certificate_retention_years=7,
        ),
        ADMIN,
    )
    validate_error(response, "ERR_DUPLICATE_STATE_RULE", 409)

    rows, _ = assert_total_count(api.list_state_rules(ADMIN, {"state_code": "CA"}), 1)
    assert rows[0]["max_container_volume_liters"] == 30.3, (
        f"the refused write must not have changed the stored cap, got "
        f"{rows[0]['max_container_volume_liters']}"
    )
    assert rows[0]["mail_back_permitted"] is True
    assert rows[0]["id"] == ctx["state_rule"]["id"]


def test_02_a_second_specification_with_the_same_spec_code_is_refused(api):
    """The packaging specification's uniqueness scope is `spec_code`, and it is
    independent of every other field on the row.

    PRD 3.1: "Each specification carries a `spec_code` of 1 to 32 characters that must be unique across all specifications — a collision yields `ERR_DUPLICATE_SPEC_CODE` — and the `un_specification_code` marking printed on the box, such as `UN 4G/X7.5/S/26`."
    PRD 3.1: "Specifications can be listed and filtered by `postal_service`, `hazard_class` or `status`."
    Design: Corner/errors/the_four_uniqueness_errors_each_fire_on_their_own_endpoint
    """
    ctx = _one_of_each_configuration_row(api)

    response = api.create_packaging_spec(
        packaging_spec_payload(
            spec_code=ctx["packaging_spec"]["spec_code"],
            un_specification_code="UN 4G/Y10/S/26",
            postal_service="UPS_GROUND_MEDICAL",
            hazard_class="UN3291_REGULATED_MEDICAL_WASTE",
            max_gross_weight_grams=12000,
            allowed_container_sizes=["THREE_GALLON"],
        ),
        ADMIN,
    )
    validate_error(response, "ERR_DUPLICATE_SPEC_CODE", 409)

    rows, _ = assert_total_count(api.list_packaging_specs(ADMIN, {"status": "ACTIVE"}), 1)
    assert rows[0]["id"] == ctx["packaging_spec"]["id"]
    assert rows[0]["postal_service"] == "USPS_PARCEL_SELECT_MAILBACK"


def test_03_a_second_facility_with_the_same_permit_number_is_refused(api):
    """The facility's uniqueness scope is `permit_number`, which has to hold
    globally because that number becomes the certificate-number prefix.

    PRD 3.1: "The third catalogue registers a permitted medical-waste treatment facility: its `name`, the `state_rule_id` of the state whose law governs its intake and its retention obligation, and a `permit_number` of 1 to 32 characters that must be unique across all facilities, with `ERR_DUPLICATE_PERMIT_NUMBER` on collision."
    PRD 3.1: "Facilities can be listed and filtered by `state_rule_id` or `status`, and retrieving one returns its live counters."
    Design: Corner/errors/the_four_uniqueness_errors_each_fire_on_their_own_endpoint
    """
    ctx = _one_of_each_configuration_row(api)

    response = api.create_treatment_facility(
        treatment_facility_payload(
            ctx["state_rule"]["id"],
            name="Second Site",
            permit_number=ctx["treatment_facility"]["permit_number"],
            accepted_hazard_classes=["UN3291_SHARPS_ONLY"],
            daily_intake_capacity_units=50,
        ),
        ADMIN,
    )
    validate_error(response, "ERR_DUPLICATE_PERMIT_NUMBER", 409)

    rows, _ = assert_total_count(
        api.list_treatment_facilities(ADMIN, {"state_rule_id": ctx["state_rule"]["id"]}), 1
    )
    assert rows[0]["id"] == ctx["treatment_facility"]["id"]
    assert rows[0]["daily_intake_capacity_units"] == 200


def test_04_a_second_enrollment_is_refused_while_the_first_is_still_draft(api):
    """The enrollment's uniqueness scope is the (patient, program) pair, and the
    blocking set includes `DRAFT` — the first enrollment has not even been
    submitted yet, and it already blocks a second one.

    PRD 3.3: "A patient may not hold two live enrollments in the same program: if an enrollment in `DRAFT`, `PENDING_SPONSOR_APPROVAL`, `ACTIVE` or `PAUSED` already exists for that patient against that same `sponsorship_program_id`, creation is refused with `ERR_DUPLICATE_ACTIVE_ENROLLMENT` (HTTP 409)."
    PRD 3.3: "Enrollments can be listed and filtered by `patient_id`, `sponsorship_program_id` or `status`."
    Design: Corner/errors/the_four_uniqueness_errors_each_fire_on_their_own_endpoint
    """
    ctx = _one_of_each_configuration_row(api)
    assert_enrollment(ctx["enrollment"], status="DRAFT")

    response = api.create_enrollment(
        enrollment_payload(
            ctx["patient"]["id"],
            ctx["sponsorship_program"]["id"],
            cadence_days=60,
            kits_authorized=1,
        ),
        ADMIN,
    )
    validate_error(response, "ERR_DUPLICATE_ACTIVE_ENROLLMENT", 409)

    rows, _ = assert_total_count(
        api.list_enrollments(ADMIN, {"patient_id": ctx["patient"]["id"]}), 1
    )
    assert rows[0]["id"] == ctx["enrollment"]["id"]
    assert rows[0]["cadence_days"] == 30, (
        f"the refused write must not have touched the live enrollment, got "
        f"cadence_days {rows[0]['cadence_days']}"
    )


def test_05_a_rejected_enrollment_frees_the_patient_program_pair_again(api):
    """The pair is not a plain unique index: once the sponsor rejects the first
    enrollment the identical payload is accepted, because `REJECTED` is terminal
    and sits outside the blocking set.

    PRD 3.3: "A `REJECTED` or `TERMINATED` prior enrollment does not block a fresh one."
    PRD 3.3: "It moves the enrollment `PENDING_SPONSOR_APPROVAL → REJECTED`, which is terminal, and copies the submitted note into `sponsor_decision_note`."
    PRD 3.3: "The new enrollment starts at `DRAFT` with `kits_issued` at 0, `next_autoship_due_date` null, `activated_at` null, `sponsor_decision_note` null and `version` at 1."
    Design: Corner/errors/the_four_uniqueness_errors_each_fire_on_their_own_endpoint
    """
    ctx = _one_of_each_configuration_row(api)
    first_id = ctx["enrollment"]["id"]
    repeat_payload = enrollment_payload(
        ctx["patient"]["id"],
        ctx["sponsorship_program"]["id"],
        cadence_days=60,
        kits_authorized=1,
    )
    validate_error(
        api.create_enrollment(repeat_payload, ADMIN), "ERR_DUPLICATE_ACTIVE_ENROLLMENT", 409
    )

    get_success_data(api.submit_enrollment(first_id, ADMIN))
    rejected = validate_success(
        api.record_sponsor_decision(
            first_id,
            sponsor_decision_payload("REJECT"),
            make_sponsor_representative_headers(ctx["sponsor"]["id"]),
        ),
        200,
    )
    assert_enrollment(rejected, status="REJECTED")

    fresh = validate_success(api.create_enrollment(repeat_payload, ADMIN), 201)
    assert_enrollment(
        fresh,
        status="DRAFT",
        kits_issued=0,
        next_autoship_due_date=None,
        activated_at=None,
        sponsor_decision_note=None,
        version=1,
    )
    assert fresh["id"] != first_id

    assert_total_count(api.list_enrollments(ADMIN, {"patient_id": ctx["patient"]["id"]}), 2)


# ==========================================================================
# Sizing, allowance and overfill refusals (PRD 3.4, 3.5)
# ==========================================================================
_TIGHT_CA_RULE = dict(_EXEMPT_CA_RULE, max_container_volume_liters=7.6)
_TIGHT_PROGRAM = {
    "program_code": "NW-TIGHT",
    "funding_ceiling_cents": 500000,
    "per_kit_allowance_cents": 2000,
}
_TOM = {"full_name": "Tom Alvarez", "weekly_sharps_count": 20, "contact_email": "tom@example.com"}


def _tight_allowance_world(api):
    """Dana lives under a 7.6-litre state cap and needs 99 units, so exactly two
    catalogue rows are candidates for her. Tom is identical except that his state
    caps containers at 0.5 litres, below the smallest catalogue row. Their shared
    program allows only 2000 cents per kit."""
    ctx = setup_program_foundations(
        api,
        state_rule_overrides=dict(_TIGHT_CA_RULE),
        packaging_spec_overrides=dict(_MAILBACK_SPEC),
        facility_overrides=dict(_SHARPS_ONLY_FACILITY),
        sponsor_overrides=dict(_MANUFACTURER),
        program_overrides=dict(_TIGHT_PROGRAM),
    )
    ctx["texas_rule"] = create_state_rule(
        api,
        state_code="TX",
        household_sharps_classification="HOUSEHOLD_EXEMPT",
        mail_back_permitted=True,
        max_container_volume_liters=0.5,
        certificate_retention_years=3,
    )
    add_enrolled_patient(
        api,
        ctx,
        patient_overrides=dict(_DANA),
        enrollment_overrides={"cadence_days": 30, "kits_authorized": 3},
    )
    add_enrolled_patient(
        api,
        ctx,
        patient_overrides=dict(_TOM),
        enrollment_overrides={"cadence_days": 30, "kits_authorized": 3},
        state_rule_id=ctx["texas_rule"]["id"],
        key="tom",
    )
    return ctx


def test_06_a_requested_size_outside_the_candidate_set_is_refused(api):
    """THREE_GALLON holds 11.4 litres, above Dana's 7.6-litre state cap, so it
    never enters her candidate set and the explicit request cannot override the
    eligibility filter.

    PRD 3.4: "A catalogue row is a **candidate** for this kit when four conditions all hold: its volume is at most the patient's state cap `max_container_volume_liters`, inclusively; its capacity is at least `required_units`, inclusively; if the patient's therapy is `INFUSION_SETS`, its volume is at least 7.6 litres; and if the patient's therapy is `LANCETS_ONLY`, its volume is at most 11.4 litres."
    PRD 3.4: "Either way, if the requested size is not itself a member of the candidate set, the request fails with `ERR_CONTAINER_SIZE_NOT_PERMITTED` (HTTP 422) and no kit is created."
    PRD 3.4: "`THREE_GALLON` holds 11.4 litres, 1300 units, and costs 3400 cents."
    Design: Corner/errors/issuance_and_seal_refusals_cover_sizing_allowance_and_overfill
    """
    ctx = _tight_allowance_world(api)
    enrollment_id = ctx["enrollment"]["id"]
    version_before = read_enrollment_version(api, enrollment_id)

    response = api.issue_kit(
        enrollment_id,
        kit_issuance_payload(version_before, container_size="THREE_GALLON"),
        ADMIN,
    )
    validate_error(response, "ERR_CONTAINER_SIZE_NOT_PERMITTED", 422)

    assert_enrollment(read_enrollment(api, enrollment_id), version=version_before, kits_issued=0)
    assert_total_count(api.list_kits(ADMIN, {"enrollment_id": enrollment_id}), 0)


def test_07_an_affordable_looking_but_over_allowance_size_is_refused(api):
    """TWO_GALLON clears the sizing filter and is refused one band later, at the
    per-kit allowance: 2600 cents of base plus a 122-cent estimated transport
    component is 2722, above the program's 2000-cent allowance.

    PRD 3.4: "`TWO_GALLON` holds 7.6 litres, 800 units, and costs 2600 cents."
    PRD 3.4: "The transport component estimates weight from capacity rather than from any actual fill: the container's `capacity_units` is multiplied by 4 grams per unit to give an estimated gram weight, that figure is multiplied by the transport rate of 38 cents per kilogram and divided by 1000 to convert grams to kilograms, and the result is rounded half up to a whole cent."
    PRD 3.4: "This figure is then measured against the program's `per_kit_allowance_cents`, and here the behaviour is a **hard gate**: if `provisional_cost_cents` is greater than the allowance, the request fails with `ERR_PER_KIT_ALLOWANCE_EXCEEDED` (HTTP 422) and no kit is created."
    PRD 3.4: "Then come the sizing checks, then the authorization count, and only then the two money checks — allowance before pool."
    Design: Corner/errors/issuance_and_seal_refusals_cover_sizing_allowance_and_overfill
    """
    ctx = _tight_allowance_world(api)
    enrollment_id = ctx["enrollment"]["id"]
    program_id = ctx["sponsorship_program"]["id"]
    version_before = read_enrollment_version(api, enrollment_id)

    response = api.issue_kit(
        enrollment_id,
        kit_issuance_payload(version_before, container_size="TWO_GALLON"),
        ADMIN,
    )
    validate_error(response, "ERR_PER_KIT_ALLOWANCE_EXCEEDED", 422)

    assert_enrollment(read_enrollment(api, enrollment_id), version=version_before, kits_issued=0)
    assert_total_count(api.list_kits(ADMIN, {"enrollment_id": enrollment_id}), 0)
    assert_program_balances(
        read_program(api, program_id), reserved_cents=0, committed_cents=0
    )
    assert_total_count(
        api.list_ledger_entries(ADMIN, {"sponsorship_program_id": program_id}), 0
    )


def test_08_an_empty_candidate_set_is_refused_before_any_money_check(api):
    """Tom's state caps containers at 0.5 litres and the smallest catalogue row is
    0.9 litres, so nothing survives the filter and he is told that no container
    fits rather than anything about the sponsor's budget.

    PRD 3.4: "`ONE_QUART` holds 0.9 litres, 100 units, and costs 1450 cents."
    PRD 3.4: "If the candidate set is empty — no catalogue row survives the state cap, the demand figure and the therapy filter together — the request fails with `ERR_NO_ELIGIBLE_CONTAINER_SIZE` (HTTP 422), and that emptiness check is evaluated before the requested-size membership check."
    Design: Corner/errors/issuance_and_seal_refusals_cover_sizing_allowance_and_overfill
    """
    ctx = _tight_allowance_world(api)
    enrollment_id = ctx["enrollment_tom"]["id"]
    version_before = read_enrollment_version(api, enrollment_id)

    response = api.issue_kit(enrollment_id, kit_issuance_payload(version_before), ADMIN)
    validate_error(response, "ERR_NO_ELIGIBLE_CONTAINER_SIZE", 422)

    assert_enrollment(read_enrollment(api, enrollment_id), version=version_before, kits_issued=0)
    assert_total_count(api.list_kits(ADMIN, {"enrollment_id": enrollment_id}), 0)


def test_09_a_fill_one_unit_past_capacity_is_refused_and_the_ceiling_is_inclusive(api):
    """Dana's ranked pick is the 100-unit ONE_QUART, whose provisional cost of
    1465 the same 2000-cent allowance permits. Declaring 101 units is a
    needlestick hazard and is refused; declaring exactly 100 is accepted.

    PRD 3.4: "The computation multiplies the weekly count by that factor, then by the number of cadence days, then by 115, divides the product by 700, and rounds the single resulting quotient up to the next whole number."
    PRD 3.4: "Among the candidates the server picks the first one after ordering by capacity ascending, then by volume ascending, then by size-code name in ascending alphabetical order; no random or clock-dependent value participates in that ordering, so the selection is fully reproducible."
    PRD 3.5: "Finally `fill_units` must not exceed the kit's `capacity_units`; an overfilled sharps container is a needlestick hazard for everyone who handles the parcel downstream, so this check lives in the safety band and its refusal is `ERR_CONTAINER_OVERFILLED` (HTTP 422)."
    PRD 3.5: "On success the kit moves `ACTIVE_FILLING → SEALED`, both declared values are stored on the kit, and the kit's `version` is incremented by 1."
    Design: Corner/errors/issuance_and_seal_refusals_cover_sizing_allowance_and_overfill
    """
    ctx = _tight_allowance_world(api)
    kit = issue_kit_for(api, ctx)
    assert_kit(
        kit,
        status="ISSUED",
        container_size="ONE_QUART",
        required_units=99,
        capacity_units=100,
        volume_liters=0.9,
        provisional_cost_cents=1465,
    )
    acknowledge_kit(api, ctx, kit=kit)
    assert_kit(read_kit(api, kit["id"]), status="ACTIVE_FILLING")

    response = api.seal_kit(
        kit["id"],
        seal_payload(fill_units=101, sealed_gross_weight_grams=1900),
        make_patient_headers(ctx["patient"]["id"]),
    )
    validate_error(response, "ERR_CONTAINER_OVERFILLED", 422)
    assert_kit(read_kit(api, kit["id"]), status="ACTIVE_FILLING")

    sealed = seal_kit_for(
        api, ctx, kit=kit, fill_units=100, sealed_gross_weight_grams=1900
    )
    assert_kit(sealed, status="SEALED", fill_units=100)


def test_10_none_of_the_three_refused_issuances_touches_the_money(api):
    """Two sizing refusals and one allowance refusal precede the one accepted
    issuance, and the program's books show a single reservation afterwards.

    PRD 3.4: "*Third*, a `RESERVATION` ledger entry for the positive `provisional_cost_cents` is appended at the next `sequence_no` and the program's `reserved_cents` rises by that amount."
    PRD 3.2: "Beyond the reserved/committed/available triple a program maintains five derived counters that a sponsor uses to reconcile: `kits_issued_count`, the number of kits under this program's enrollments whose status is anything other than `VOIDED`; `kits_settled_count`, the number of destruction certificates in status `ISSUED` against this program's kits; `provisional_total_cents`, the sum of `provisional_cost_cents` over this program's kits that carry an `ISSUED` certificate; and `final_total_cents`, the sum of `final_kit_cost_cents` over this program's `ISSUED` certificates."
    Design: Corner/errors/issuance_and_seal_refusals_cover_sizing_allowance_and_overfill
    """
    ctx = _tight_allowance_world(api)
    dana_enrollment = ctx["enrollment"]["id"]
    tom_enrollment = ctx["enrollment_tom"]["id"]
    program_id = ctx["sponsorship_program"]["id"]
    dana_version = read_enrollment_version(api, dana_enrollment)
    tom_version = read_enrollment_version(api, tom_enrollment)

    validate_error(
        api.issue_kit(
            dana_enrollment,
            kit_issuance_payload(dana_version, container_size="THREE_GALLON"),
            ADMIN,
        ),
        "ERR_CONTAINER_SIZE_NOT_PERMITTED",
        422,
    )
    validate_error(
        api.issue_kit(
            dana_enrollment,
            kit_issuance_payload(dana_version, container_size="TWO_GALLON"),
            ADMIN,
        ),
        "ERR_PER_KIT_ALLOWANCE_EXCEEDED",
        422,
    )
    validate_error(
        api.issue_kit(tom_enrollment, kit_issuance_payload(tom_version), ADMIN),
        "ERR_NO_ELIGIBLE_CONTAINER_SIZE",
        422,
    )

    kit = issue_kit_for(api, ctx)
    assert_kit(kit, container_size="ONE_QUART", provisional_cost_cents=1465)

    program = read_program(api, program_id)
    assert_program_balances(
        program, reserved_cents=1465, committed_cents=0, available_cents=498535
    )
    assert program["kits_issued_count"] == 1, (
        f"Expected kits_issued_count 1, got {program['kits_issued_count']}"
    )
    assert_total_count(
        api.list_ledger_entries(ADMIN, {"sponsorship_program_id": program_id}), 1
    )


# ==========================================================================
# Label printing and postal acceptance refusals (PRD 3.6)
# ==========================================================================
_SPEC_BIG = {
    "spec_code": "SPEC-BIG",
    "un_specification_code": "UN 4G/Y10/S/26",
    "postal_service": "USPS_PARCEL_SELECT_MAILBACK",
    "hazard_class": "UN3291_SHARPS_ONLY",
    "max_gross_weight_grams": 8000,
    "allowed_container_sizes": ["TWO_GALLON"],
}
_ELI = {"full_name": "Eli Barnes", "weekly_sharps_count": 20, "contact_email": "eli@example.com"}


def _two_sealed_kits_and_four_specs(api):
    """Four specifications share the same California route and differ in exactly
    one dimension each; Dana and Eli each hold a ONE_QUART kit sealed at 60 units
    and 1200 grams. The receiving facility's permit covers sharps only."""
    ctx = setup_program_foundations(
        api,
        state_rule_overrides=dict(_EXEMPT_CA_RULE, requires_state_manifest=False),
        packaging_spec_overrides=dict(_SPEC_BIG),
        facility_overrides=dict(_SHARPS_ONLY_FACILITY),
        sponsor_overrides=dict(_MANUFACTURER),
        program_overrides=dict(_PROGRAM),
    )
    ctx["spec_big"] = ctx["packaging_spec"]
    ctx["spec_old"] = create_packaging_spec(
        api,
        spec_code="SPEC-OLD",
        un_specification_code="UN 4G/X7.5/S/21",
        postal_service="USPS_PARCEL_SELECT_MAILBACK",
        hazard_class="UN3291_SHARPS_ONLY",
        max_gross_weight_grams=8000,
        allowed_container_sizes=["ONE_QUART"],
        status="RETIRED",
    )
    ctx["spec_light"] = create_packaging_spec(
        api,
        spec_code="SPEC-LIGHT",
        un_specification_code="UN 4G/X1.0/S/26",
        postal_service="USPS_PARCEL_SELECT_MAILBACK",
        hazard_class="UN3291_SHARPS_ONLY",
        max_gross_weight_grams=1000,
        allowed_container_sizes=["ONE_QUART"],
    )
    ctx["spec_rmw"] = create_packaging_spec(
        api,
        spec_code="SPEC-RMW",
        un_specification_code="UN 4G/X7.5/S/26",
        postal_service="UPS_GROUND_MEDICAL",
        hazard_class="UN3291_REGULATED_MEDICAL_WASTE",
        max_gross_weight_grams=8000,
        allowed_container_sizes=["ONE_QUART"],
    )
    for overrides, key in ((dict(_DANA), None), (dict(_ELI), "eli")):
        pair = add_enrolled_patient(
            api,
            ctx,
            patient_overrides=overrides,
            enrollment_overrides={"cadence_days": 30, "kits_authorized": 3},
            key=key,
        )
        kit = issue_kit_for(api, ctx, enrollment=pair["enrollment"])
        acknowledge_kit(api, ctx, kit=kit, patient=pair["patient"])
        seal_kit_for(
            api,
            ctx,
            kit=kit,
            patient=pair["patient"],
            fill_units=60,
            sealed_gross_weight_grams=1200,
        )
        ctx["kit_eli" if key else "kit_dana"] = read_kit(api, kit["id"])
    return ctx


def test_11_printing_against_a_specification_that_omits_the_kits_size_is_refused(api):
    """SPEC-BIG is certified for TWO_GALLON boxes only, so it cannot back a label
    for a ONE_QUART kit — and the refusal must leave no label row at all, or the
    occupancy window rule would later see a phantom claim on the kit.

    PRD 3.6: "The kit's `container_size` must appear in the specification's `allowed_container_sizes`, otherwise `ERR_PACKAGING_SPEC_MISMATCH` (HTTP 422)."
    PRD 3.6: "Labels are readable individually and as a list filtered by `kit_id`, `packaging_spec_id` or `status`."
    Design: Corner/errors/label_print_and_activation_refusals_cover_spec_and_facility_permits
    """
    ctx = _two_sealed_kits_and_four_specs(api)
    kit_id = ctx["kit_dana"]["id"]
    assert_kit(ctx["kit_dana"], status="SEALED", container_size="ONE_QUART")

    response = api.print_return_label(
        kit_id, return_label_payload(ctx["spec_big"]["id"]), LOGISTICS
    )
    validate_error(response, "ERR_PACKAGING_SPEC_MISMATCH", 422)

    assert_total_count(api.list_return_labels(ADMIN, {"kit_id": kit_id}), 0)


def test_12_printing_against_a_retired_specification_is_refused(api):
    """SPEC-OLD does list ONE_QUART, so the size gate passes and only the status
    gate can be firing; a retired specification may not back a new label.

    PRD 3.6: "The specification's `status` must be `ACTIVE`; a `RETIRED` specification may not back a new label and the refusal is `ERR_PACKAGING_SPEC_RETIRED` (HTTP 422)."
    PRD 3.1: "Finally `status` is `ACTIVE` or `RETIRED` and defaults to `ACTIVE`; a `RETIRED` specification remains readable and remains pinned to labels already printed against it, but may not back a new one."
    Design: Corner/errors/label_print_and_activation_refusals_cover_spec_and_facility_permits
    """
    ctx = _two_sealed_kits_and_four_specs(api)
    kit_id = ctx["kit_dana"]["id"]
    assert ctx["spec_old"]["allowed_container_sizes"] == ["ONE_QUART"]
    assert ctx["spec_old"]["status"] == "RETIRED"

    response = api.print_return_label(
        kit_id, return_label_payload(ctx["spec_old"]["id"]), LOGISTICS
    )
    validate_error(response, "ERR_PACKAGING_SPEC_RETIRED", 422)

    assert_total_count(api.list_return_labels(ADMIN, {"kit_id": kit_id}), 0)


def test_13_a_declared_weight_over_the_pinned_postal_ceiling_is_refused(api):
    """SPEC-LIGHT prints cleanly — printing never looks at weight — and the
    parcel is stopped at tender instead: 1200 grams exceeds the specification's
    1000-gram ceiling. The refusal books no units and creates no shipment, and a
    re-tender at exactly the ceiling is accepted.

    PRD 3.6: "Its `tracking_number` is deterministic and contains no random component: it is the carrier prefix, then a hyphen, then a sequence number zero-padded to eight digits."
    PRD 3.6: "The prefix is `USPSMB` when the pinned `postal_service` is `USPS_PARCEL_SELECT_MAILBACK` and `UPSGM` when it is `UPS_GROUND_MEDICAL`."
    PRD 3.6: "The sequence number is the total count of return labels that exist across the entire program — voided ones included — plus one; voided rows consume their number permanently and it is never reissued."
    PRD 3.6: "Then the constraint band, in sequence: `declared_gross_weight_grams` must not exceed the pinned specification's `max_gross_weight_grams`, otherwise `ERR_POSTAL_WEIGHT_EXCEEDED` (HTTP 422); if the pinned specification's `requires_absorbent` is true then `absorbent_declared` must be present and true, and if it is absent or false the answer is `ERR_ABSORBENT_MATERIAL_REQUIRED` (HTTP 422); if the patient's state rule has `requires_state_manifest` true then `state_manifest_number` must be present and non-empty, failing which `ERR_STATE_MANIFEST_REQUIRED` (HTTP 422); the destination facility's `accepted_hazard_classes` must include the pinned specification's `hazard_class`, otherwise `ERR_FACILITY_NOT_PERMITTED` (HTTP 422); the destination facility's `status` must be `ACTIVE`, otherwise `ERR_INVALID_FACILITY_STATE` (HTTP 409); and the facility's intake booking for that date must accommodate the parcel, failing which `ERR_FACILITY_INTAKE_CAPACITY_EXCEEDED` (HTTP 409)."
    PRD 3.6: "Its two axes start at `transport_status` `TENDERED` and `conformance_status` `UNSCREENED`, with `observed_gross_weight_grams`, `delivered_at` and `screened_by_user_id` all null."
    PRD 3.6: "The destination facility's `pending_intake_units` rises by the new shipment's `custody_units`."
    Design: Corner/errors/label_print_and_activation_refusals_cover_spec_and_facility_permits
    """
    ctx = _two_sealed_kits_and_four_specs(api)
    kit_id = ctx["kit_dana"]["id"]
    facility_id = ctx["treatment_facility"]["id"]

    label = validate_success(
        api.print_return_label(
            kit_id, return_label_payload(ctx["spec_light"]["id"]), LOGISTICS
        ),
        201,
    )
    assert_return_label(
        label,
        status="PRINTED",
        tracking_number="USPSMB-00000001",
        postal_service="USPS_PARCEL_SELECT_MAILBACK",
        activated_at=None,
        voided_at=None,
    )

    refused = api.activate_return_label(
        label["id"],
        label_activation_payload(
            facility_id,
            scheduled_intake_date="2026-08-05",
            declared_gross_weight_grams=1200,
        ),
        LOGISTICS,
    )
    validate_error(refused, "ERR_POSTAL_WEIGHT_EXCEEDED", 422)

    assert_return_label(
        get_success_data(api.get_return_label(label["id"], ADMIN)),
        status="PRINTED",
        activated_at=None,
    )
    assert_total_count(api.list_shipments(ADMIN, {"kit_id": kit_id}), 0)
    assert_facility_counters(
        read_treatment_facility(api, facility_id), pending_intake_units=0
    )

    shipment = validate_success(
        api.activate_return_label(
            label["id"],
            label_activation_payload(
                facility_id,
                scheduled_intake_date="2026-08-05",
                declared_gross_weight_grams=1000,
            ),
            LOGISTICS,
        ),
        201,
    )
    assert_shipment_axes(
        shipment,
        transport_status="TENDERED",
        conformance_status="UNSCREENED",
        custody_units=60,
        screened_by_user_id=None,
    )
    assert_facility_counters(
        read_treatment_facility(api, facility_id), pending_intake_units=60
    )


def test_14_activating_into_a_facility_whose_permit_omits_the_hazard_class_is_refused(api):
    """Printing never consults the facility, so Eli's regulated-medical-waste
    label prints and takes the next tracking number in the global sequence; the
    facility's sharps-only permit stops it at activation, leaving Dana's booked
    units as the only occupancy at the facility.

    PRD 3.6: "The prefix is `USPSMB` when the pinned `postal_service` is `USPS_PARCEL_SELECT_MAILBACK` and `UPSGM` when it is `UPS_GROUND_MEDICAL`."
    PRD 3.6: "The sequence number is the total count of return labels that exist across the entire program — voided ones included — plus one; voided rows consume their number permanently and it is never reissued."
    PRD 3.6: "Then the constraint band, in sequence: `declared_gross_weight_grams` must not exceed the pinned specification's `max_gross_weight_grams`, otherwise `ERR_POSTAL_WEIGHT_EXCEEDED` (HTTP 422); if the pinned specification's `requires_absorbent` is true then `absorbent_declared` must be present and true, and if it is absent or false the answer is `ERR_ABSORBENT_MATERIAL_REQUIRED` (HTTP 422); if the patient's state rule has `requires_state_manifest` true then `state_manifest_number` must be present and non-empty, failing which `ERR_STATE_MANIFEST_REQUIRED` (HTTP 422); the destination facility's `accepted_hazard_classes` must include the pinned specification's `hazard_class`, otherwise `ERR_FACILITY_NOT_PERMITTED` (HTTP 422); the destination facility's `status` must be `ACTIVE`, otherwise `ERR_INVALID_FACILITY_STATE` (HTTP 409); and the facility's intake booking for that date must accommodate the parcel, failing which `ERR_FACILITY_INTAKE_CAPACITY_EXCEEDED` (HTTP 409)."
    PRD 3.6: "Shipments are readable individually and as a list filtered by `kit_id`, `return_label_id`, `treatment_facility_id`, `transport_status`, `conformance_status` or `scheduled_intake_date`."
    Design: Corner/errors/label_print_and_activation_refusals_cover_spec_and_facility_permits
    """
    ctx = _two_sealed_kits_and_four_specs(api)
    facility_id = ctx["treatment_facility"]["id"]
    dana_label = validate_success(
        api.print_return_label(
            ctx["kit_dana"]["id"], return_label_payload(ctx["spec_light"]["id"]), LOGISTICS
        ),
        201,
    )
    validate_success(
        api.activate_return_label(
            dana_label["id"],
            label_activation_payload(
                facility_id,
                scheduled_intake_date="2026-08-05",
                declared_gross_weight_grams=1000,
            ),
            LOGISTICS,
        ),
        201,
    )

    eli_kit_id = ctx["kit_eli"]["id"]
    eli_label = validate_success(
        api.print_return_label(
            eli_kit_id, return_label_payload(ctx["spec_rmw"]["id"]), LOGISTICS
        ),
        201,
    )
    assert_return_label(
        eli_label,
        status="PRINTED",
        tracking_number="UPSGM-00000002",
        postal_service="UPS_GROUND_MEDICAL",
    )

    refused = api.activate_return_label(
        eli_label["id"],
        label_activation_payload(
            facility_id,
            scheduled_intake_date="2026-08-05",
            declared_gross_weight_grams=1200,
        ),
        LOGISTICS,
    )
    validate_error(refused, "ERR_FACILITY_NOT_PERMITTED", 422)

    assert_return_label(
        get_success_data(api.get_return_label(eli_label["id"], ADMIN)),
        status="PRINTED",
        activated_at=None,
    )
    assert_total_count(api.list_shipments(ADMIN, {"kit_id": eli_kit_id}), 0)
    assert_facility_counters(
        read_treatment_facility(api, facility_id), pending_intake_units=60
    )
