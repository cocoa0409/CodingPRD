"""Two requests that each violate two rules at once, in bands far apart, so the answer
proves which band the server evaluated first."""

from test_helpers import (
    ADMIN,
    LOGISTICS,
    acknowledge_kit,
    add_enrolled_patient,
    assert_empty_listing,
    assert_enrollment,
    assert_facility_counters,
    assert_kit,
    assert_program_balances,
    assert_return_label,
    create_draft_enrollment,
    create_eligible_patient,
    create_state_rule,
    issue_kit_for,
    kit_issuance_payload,
    label_activation_payload,
    print_label_for,
    read_enrollment,
    read_kit,
    read_program,
    read_return_label,
    read_treatment_facility,
    seal_kit_for,
    setup_program_foundations,
    validate_error,
)

# A ceiling of 100 cents cannot fund any catalogue size, the cheapest of which
# reserves 1465 cents.
_TINY_PROGRAM = {
    "program_code": "NPD-TINY",
    "funding_ceiling_cents": 100,
    "per_kit_allowance_cents": 6000,
}

# A 500-gram postal ceiling, which a 1400-gram parcel blows through.
_PS_C = {
    "spec_code": "PS-C",
    "un_specification_code": "UN 4G/X0.5/S/26",
    "max_gross_weight_grams": 500,
    "allowed_container_sizes": ["ONE_QUART", "TWO_GALLON"],
}


# --------------------------------------------------------------------------
# State precondition (409) versus fiscal pool (422) on kit issuance
# --------------------------------------------------------------------------
def _draft_enrollment_on_an_unaffordable_program(api):
    """An enrollment left in DRAFT — never submitted, never sponsor-approved — under a
    program that cannot afford a single kit. The patient is therefore still ELIGIBLE
    rather than ENROLLED, so the patient-state rule is violated as well."""
    ctx = setup_program_foundations(
        api, program_overrides=_TINY_PROGRAM, with_facility=False
    )
    ctx["patient"] = create_eligible_patient(api, ctx["state_rule"]["id"])
    ctx["enrollment"] = create_draft_enrollment(
        api, ctx["patient"]["id"], ctx["sponsorship_program"]["id"]
    )
    return ctx


def _attempt_issuance(api, ctx, headers):
    return api.issue_kit(
        ctx["enrollment"]["id"],
        kit_issuance_payload(ctx["enrollment"]["version"]),
        headers,
    )


def test_01_enrollment_state_beats_the_funding_pool_on_kit_issuance(api, program_admin_headers):
    """A DRAFT enrollment on a 100-cent program violates both the state precondition
    and the pool check; the state band answers first, with 409 rather than 422.

    PRD 3.4: "Before anything is written, the request must clear a fixed sequence of gates. The enrollment must be `ACTIVE`, otherwise `ERR_INVALID_ENROLLMENT_STATE`; the patient behind it must be `ENROLLED`, otherwise `ERR_INVALID_PATIENT_STATE`; and the version echo must match, otherwise `ERR_STALE_ENROLLMENT_VERSION`. Then come the sizing checks, then the authorization count, and only then the two money checks — allowance before pool."
    PRD 2.6: "The bands are, in order: header validity (`ERR_UNAUTHENTICATED`), role membership (`ERR_ROLE_NOT_PERMITTED`), request shape (`ERR_INVALID_REQUEST`), existence of referenced records (the 404 family above), resource ownership (`ERR_NOT_RESOURCE_OWNER`), state preconditions on the target record, optimistic-concurrency version echoes, and then the four business bands."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_kit_issuance_for_paused_enrollment
    """
    ctx = _draft_enrollment_on_an_unaffordable_program(api)

    response = _attempt_issuance(api, ctx, program_admin_headers)

    validate_error(response, "ERR_INVALID_ENROLLMENT_STATE", 409)


def test_02_the_losing_fiscal_diagnosis_is_never_returned(api, program_admin_headers):
    """Both rules are genuinely broken, so the refusal must name the enrollment state
    and not the exhausted pool.

    PRD 2.6: "A parcel that a state forbids from entering the mail must never be diagnosed as a budget problem, and a budget problem must never be allowed to mask a packaging-compliance defect."
    PRD 3.4: "Likewise the pool check compares the program's `available_cents`, with the superseded kit's reservation already released, against the new kit's `provisional_cost_cents`; a shortfall is refused with `ERR_PROGRAM_FUNDING_EXHAUSTED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_kit_issuance_for_paused_enrollment
    """
    ctx = _draft_enrollment_on_an_unaffordable_program(api)

    response = _attempt_issuance(api, ctx, program_admin_headers)

    assert response.json()["data"]["error_id"] != "ERR_PROGRAM_FUNDING_EXHAUSTED", (
        "the fiscal band must not answer ahead of the state-precondition band"
    )
    assert response.status_code != 422, (
        f"expected the 409 state refusal, got {response.status_code}"
    )


def test_03_the_refused_issuance_writes_nothing_at_all(api, program_admin_headers):
    """No kit, no ledger append, no movement in the program's balances and no change to
    the enrollment.

    PRD 3.4: "This figure is then measured against the program's `per_kit_allowance_cents`, and here the behaviour is a **hard gate**: if `provisional_cost_cents` is greater than the allowance, the request fails with `ERR_PER_KIT_ALLOWANCE_EXCEEDED` (HTTP 422) and no kit is created."
    PRD 2.9: "Sponsor money is never adjusted by direct assignment. Every movement is an append to an immutable ledger, and a program's balances are derived from those appends."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_kit_issuance_for_paused_enrollment
    """
    ctx = _draft_enrollment_on_an_unaffordable_program(api)

    _attempt_issuance(api, ctx, program_admin_headers)

    assert_empty_listing(
        api.list_kits(ADMIN, params={"enrollment_id": ctx["enrollment"]["id"]})
    )
    assert_empty_listing(
        api.list_ledger_entries(
            ADMIN, params={"sponsorship_program_id": ctx["sponsorship_program"]["id"]}
        )
    )
    assert_program_balances(
        read_program(api, ctx["sponsorship_program"]["id"]),
        reserved_cents=0,
        committed_cents=0,
        available_cents=100,
        status="ACTIVE",
    )
    assert_enrollment(
        read_enrollment(api, ctx["enrollment"]["id"]), status="DRAFT", kits_issued=0
    )


# --------------------------------------------------------------------------
# Safety (422) versus constraint (422) on label activation
# --------------------------------------------------------------------------
def _printed_label_for_a_prohibited_state_and_an_overweight_parcel(api):
    """The patient lives in NV, which forbids household-sharps mail-back outright, and
    the parcel is 1400 g against the pinned spec's 500 g postal ceiling. Nothing checks
    either fact at print time, so the label prints cleanly."""
    ctx = setup_program_foundations(api, packaging_spec_overrides=_PS_C)
    ctx["nevada_rule"] = create_state_rule(
        api,
        state_code="NV",
        household_sharps_classification="HOUSEHOLD_EXEMPT",
        mail_back_permitted=False,
        max_container_volume_liters=11.4,
        certificate_retention_years=5,
        requires_state_manifest=False,
        notification_deadline_hours=48,
    )
    add_enrolled_patient(
        api,
        ctx,
        state_rule_id=ctx["nevada_rule"]["id"],
        patient_overrides={"full_name": "Ray Alonzo", "contact_email": "ray@example.com"},
    )
    issue_kit_for(api, ctx)
    acknowledge_kit(api, ctx)
    seal_kit_for(api, ctx, fill_units=69, sealed_gross_weight_grams=1400)
    print_label_for(api, ctx)
    return ctx


def _attempt_activation(api, ctx):
    return api.activate_return_label(
        ctx["return_label"]["id"],
        label_activation_payload(
            ctx["treatment_facility"]["id"],
            scheduled_intake_date="2026-08-10",
            declared_gross_weight_grams=1400,
        ),
        LOGISTICS,
    )


def test_04_the_state_prohibition_outranks_the_postal_weight_ceiling(api):
    """Two violations, both carrying HTTP 422, so only the error id can tell a correct
    implementation from a wrong one: the safety band must answer.

    PRD 3.6: "Then the safety band: the patient's state must permit household-sharps mail-back at all, and if its `mail_back_permitted` is false the tender is refused outright with `ERR_STATE_MAILBACK_PROHIBITED` (HTTP 422). This outranks every packaging, routing, capacity, window and funding consideration — a parcel the state forbids must never be diagnosed as anything else."
    PRD 2.6: "The four business bands then run in this sequence, and the sequence matters diagnostically: **safety** first, then **referential and structural constraints**, then **temporal windows**, then **fiscal capacity**."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_label_activation_for_prohibited_state
    """
    ctx = _printed_label_for_a_prohibited_state_and_an_overweight_parcel(api)

    response = _attempt_activation(api, ctx)

    validate_error(response, "ERR_STATE_MAILBACK_PROHIBITED", 422)
    assert response.json()["data"]["error_id"] != "ERR_POSTAL_WEIGHT_EXCEEDED", (
        "the constraint band must not answer ahead of the safety band"
    )


def test_05_the_refused_activation_leaves_the_label_and_kit_untendered(api):
    """The label stays PRINTED and the kit stays SEALED; a refusal writes neither axis
    of the journey.

    PRD 3.6: "**What activation writes.** The label moves `PRINTED → ACTIVATED` with `activated_at` set to the current logical-clock instant and its `version` incremented by 1."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_label_activation_for_prohibited_state
    """
    ctx = _printed_label_for_a_prohibited_state_and_an_overweight_parcel(api)

    _attempt_activation(api, ctx)

    label = read_return_label(api, ctx["return_label"]["id"])
    assert_return_label(label, status="PRINTED", activated_at=None)
    assert_kit(read_kit(api, ctx["kit"]["id"]), status="SEALED")


def test_06_no_shipment_is_created_and_the_facility_books_nothing(api):
    """Activation is the only thing that mints a shipment and the only thing that books
    intake units, so a refused activation leaves both untouched.

    PRD 3.6: "A shipment is created, copying `kit_id` from the label's kit and recording `return_label_id` as the label whose activation produced it, storing the submitted `treatment_facility_id`, `scheduled_intake_date`, `declared_gross_weight_grams` and `state_manifest_number`, freezing `custody_units` to the kit's `fill_units` as of this instant — a value that never changes afterwards, whatever happens to the kit — and setting `tendered_at` to the current logical-clock instant."
    PRD 3.6: "The destination facility's `pending_intake_units` rises by the new shipment's `custody_units`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_label_activation_for_prohibited_state
    """
    ctx = _printed_label_for_a_prohibited_state_and_an_overweight_parcel(api)

    _attempt_activation(api, ctx)

    assert_empty_listing(
        api.list_shipments(
            ADMIN, params={"treatment_facility_id": ctx["treatment_facility"]["id"]}
        )
    )
    assert_facility_counters(
        read_treatment_facility(api, ctx["treatment_facility"]["id"]),
        pending_intake_units=0,
    )
