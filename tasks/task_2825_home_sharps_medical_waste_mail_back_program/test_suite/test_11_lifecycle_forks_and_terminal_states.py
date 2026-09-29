"""Lifecycle forks, declared initial states and compensating transitions.

Every test in this module drives the program's own state machines: where a newly
minted row starts, which arm of a branching decision was taken, and what a
terminal or compensating transition is allowed to write.
"""

from test_helpers import (
    OMIT,
    acknowledge_kit,
    assert_certificate,
    assert_empty_listing,
    assert_enrollment,
    assert_facility_counters,
    assert_kit,
    assert_ledger_sequence,
    assert_patient_risk,
    assert_program_balances,
    assert_total_count,
    certificate_void_payload,
    certify_destruction_for,
    create_active_enrollment,
    create_california_rule,
    create_draft_enrollment,
    create_eligible_patient,
    create_patient,
    create_sponsorship_program,
    destruction_certificate_payload,
    eligibility_review_payload,
    enrollment_payload,
    get_success_data,
    issue_kit_for,
    make_destruction_officer_headers,
    make_program_admin_headers,
    make_sponsor_representative_headers,
    read_destruction_certificate,
    read_enrollment,
    read_kit,
    read_ledger_entries,
    read_patient,
    read_program,
    read_treatment_facility,
    set_clock,
    setup_certifiable_shipment,
    setup_program_foundations,
    sponsor_decision_payload,
    sponsor_payload,
    sponsorship_program_payload,
    status_action_payload,
    treatment_facility_payload,
    validate_error,
    validate_success,
)

ADMIN = make_program_admin_headers()


# --------------------------------------------------------------------------
# Shared context builders
# --------------------------------------------------------------------------
def _two_program_enrolled_patient(api):
    """One patient enrolled under two funded programs of the same sponsor, with
    an ACTIVE_FILLING kit on the first enrollment and an ISSUED kit on the
    second."""
    ctx = setup_program_foundations(
        api,
        program_overrides={
            "program_code": "NW-A",
            "funding_ceiling_cents": 500000,
            "per_kit_allowance_cents": 5000,
        },
    )
    ctx["program_b"] = create_sponsorship_program(
        api,
        ctx["sponsor"]["id"],
        program_code="NW-B",
        funding_ceiling_cents=300000,
        per_kit_allowance_cents=5000,
    )
    patient = create_eligible_patient(
        api, ctx["state_rule"]["id"], weekly_sharps_count=20
    )
    ctx["patient"] = patient
    ctx["enrollment"] = create_active_enrollment(
        api,
        patient["id"],
        ctx["sponsorship_program"]["id"],
        ctx["sponsor"]["id"],
        cadence_days=30,
        kits_authorized=3,
    )
    ctx["kit_a"] = issue_kit_for(api, ctx, enrollment=ctx["enrollment"])
    acknowledge_kit(api, ctx, kit=ctx["kit_a"], patient=patient)
    ctx["enrollment_b"] = create_active_enrollment(
        api,
        patient["id"],
        ctx["program_b"]["id"],
        ctx["sponsor"]["id"],
        cadence_days=30,
        kits_authorized=3,
    )
    ctx["kit_b"] = issue_kit_for(api, ctx, enrollment=ctx["enrollment_b"])
    return ctx


def _sponsor_with_eligible_patient(api):
    """An ACTIVE sponsor with one funded program and one ELIGIBLE patient who is
    not yet enrolled anywhere."""
    ctx = setup_program_foundations(
        api,
        program_overrides={
            "program_code": "NW-2026",
            "funding_ceiling_cents": 500000,
            "per_kit_allowance_cents": 5000,
        },
    )
    ctx["patient"] = create_eligible_patient(
        api, ctx["state_rule"]["id"], weekly_sharps_count=20
    )
    return ctx


def _settled_certificate(api):
    """A ONE_QUART kit carried through to an ISSUED destruction certificate at
    clock 2026-08-20T12:00:00Z, with the pre-certificate program balances kept on
    the context for comparison."""
    ctx = setup_certifiable_shipment(
        api,
        state_rule_overrides={"certificate_retention_years": 3},
        packaging_spec_overrides={
            "spec_code": "MB-4G-STD",
            "max_gross_weight_grams": 8000,
            "allowed_container_sizes": ["ONE_QUART", "TWO_GALLON"],
        },
        facility_overrides={
            "permit_number": "CA-TF-0001",
            "daily_intake_capacity_units": 200,
        },
        program_overrides={
            "program_code": "NW-2026",
            "funding_ceiling_cents": 500000,
            "per_kit_allowance_cents": 5000,
        },
        patient_overrides={"weekly_sharps_count": 20},
        enrollment_overrides={"cadence_days": 30, "kits_authorized": 3},
        fill_units=60,
        sealed_gross_weight_grams=1200,
        scheduled_intake_date="2026-08-05",
        declared_gross_weight_grams=1200,
        observed_gross_weight_grams=1200,
    )
    ctx["pre_certificate_program"] = read_program(api, ctx["sponsorship_program"]["id"])
    set_clock(api, "2026-08-20T12:00:00Z")
    ctx["certificate"] = certify_destruction_for(api, ctx, destroyed_units=60)
    return ctx


# --------------------------------------------------------------------------
# Declared initial states of newly created rows
# --------------------------------------------------------------------------
def test_01_sponsor_registration_and_funded_program_start_active_with_the_full_ceiling(api):
    """A sponsor registered without an explicit status defaults to ACTIVE, and the
    program opened underneath it starts with an untouched ceiling.

    PRD 3.2: "Registration records the sponsor's `legal_name`, a `sponsor_type` of either `MANUFACTURER` or `HEALTH_PLAN`, a program `contact_email`, and an optional `status` of `ACTIVE` or `SUSPENDED` defaulting to `ACTIVE`."
    PRD 3.2: "The new program starts with `reserved_cents` at 0, `committed_cents` at 0, `available_cents` equal to `funding_ceiling_cents`, and `status` `ACTIVE` — or `EXHAUSTED` in the degenerate case where the ceiling is zero, since the status is a pure function of `available_cents`."
    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    set_clock(api)
    sponsor = validate_success(
        api.create_sponsor(
            sponsor_payload(
                legal_name="Northwind Devices Inc",
                sponsor_type="MANUFACTURER",
                contact_email="programs@northwind.example",
                status=OMIT,
            ),
            ADMIN,
        ),
        expected_status=201,
    )
    assert sponsor["status"] == "ACTIVE", (
        f"An omitted status must default to ACTIVE, got {sponsor['status']!r}"
    )
    assert sponsor["version"] == 1, (
        f"A freshly registered sponsor starts at version 1, got {sponsor['version']}"
    )

    program = validate_success(
        api.create_sponsorship_program(
            sponsor["id"],
            sponsorship_program_payload(
                program_code="NW-2026",
                funding_ceiling_cents=500000,
                per_kit_allowance_cents=5000,
            ),
            ADMIN,
        ),
        expected_status=201,
    )
    assert_program_balances(
        program,
        reserved_cents=0,
        committed_cents=0,
        available_cents=500000,
        funding_ceiling_cents=500000,
        status="ACTIVE",
    )


def test_02_a_new_program_starts_with_every_reconciliation_counter_at_zero(api):
    """The four reconciliation counters are sums and counts over kits and
    certificates, so a program with neither starts every one of them at zero.

    PRD 3.2: "Beyond the reserved/committed/available triple a program maintains five derived counters that a sponsor uses to reconcile: `kits_issued_count`, the number of kits under this program's enrollments whose status is anything other than `VOIDED`; `kits_settled_count`, the number of destruction certificates in status `ISSUED` against this program's kits; `provisional_total_cents`, the sum of `provisional_cost_cents` over this program's kits that carry an `ISSUED` certificate; and `final_total_cents`, the sum of `final_kit_cost_cents` over this program's `ISSUED` certificates."
    PRD 3.2: "Ledger entries are readable individually and as a list filtered by `sponsorship_program_id`, `kit_id` or `entry_type`, always in `sequence_no` ascending order."
    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    set_clock(api)
    sponsor = get_success_data(
        api.create_sponsor(sponsor_payload(legal_name="Northwind Devices Inc"), ADMIN)
    )
    program = create_sponsorship_program(
        api,
        sponsor["id"],
        program_code="NW-2026",
        funding_ceiling_cents=500000,
        per_kit_allowance_cents=5000,
    )
    for counter in (
        "kits_issued_count",
        "kits_settled_count",
        "provisional_total_cents",
        "final_total_cents",
    ):
        assert program[counter] == 0, (
            f"A program with no kits must start {counter} at 0, got {program[counter]}"
        )
    assert_empty_listing(
        api.list_ledger_entries(ADMIN, {"sponsorship_program_id": program["id"]})
    )


def test_03_treatment_facility_registration_starts_active_with_zeroed_custody_counters(api):
    """A facility registered without an explicit status defaults to ACTIVE and
    holds nothing in custody yet.

    PRD 3.1: "`status` is `ACTIVE` or `SUSPENDED` and defaults to `ACTIVE`."
    PRD 3.1: "Registration also initialises three counters to 0: `pending_intake_units`, which tracks the units currently inside the facility's custody chain; `destroyed_units_total`, the lifetime units destroyed under certificates that have not been voided; and `certificates_issued_count`, the count of certificates ever minted at the facility including voided ones, which drives the certificate numbering sequence."
    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    set_clock(api)
    state_rule = create_california_rule(api)
    facility = validate_success(
        api.create_treatment_facility(
            treatment_facility_payload(
                state_rule["id"],
                name="Valley Sharps Treatment",
                permit_number="CA-TF-0001",
                accepted_hazard_classes=["UN3291_SHARPS_ONLY"],
                daily_intake_capacity_units=1000,
                status=OMIT,
            ),
            ADMIN,
        ),
        expected_status=201,
    )
    assert_facility_counters(
        facility,
        pending_intake_units=0,
        destroyed_units_total=0,
        certificates_issued_count=0,
        status="ACTIVE",
    )


def test_04_a_new_patient_is_pending_eligibility_and_a_new_enrollment_is_draft_at_version_one(api):
    """Registration parks the patient at PENDING_ELIGIBILITY with both risk
    scores at zero; once approved, the first enrollment opens in DRAFT.

    PRD 3.3: "A new patient begins at `PENDING_ELIGIBILITY` with `screening_risk_score` at 0, `audit_risk_score` at 0 and `suspended_at` null."
    PRD 3.3: "`APPROVE` moves the patient `PENDING_ELIGIBILITY → ELIGIBLE` and increments the patient's `version` by 1; the patient may now be enrolled."
    PRD 3.3: "The new enrollment starts at `DRAFT` with `kits_issued` at 0, `next_autoship_due_date` null, `activated_at` null, `sponsor_decision_note` null and `version` at 1."
    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    ctx = setup_program_foundations(
        api,
        program_overrides={
            "program_code": "NW-2026",
            "funding_ceiling_cents": 500000,
            "per_kit_allowance_cents": 5000,
        },
    )
    patient = create_patient(
        api, ctx["state_rule"]["id"], full_name="Dana Reyes", weekly_sharps_count=20
    )
    assert_patient_risk(
        patient,
        screening_risk_score=0,
        audit_risk_score=0,
        status="PENDING_ELIGIBILITY",
        suspended_at=None,
    )
    assert patient["version"] == 1, (
        f"A freshly registered patient starts at version 1, got {patient['version']}"
    )

    approved = get_success_data(
        api.review_patient_eligibility(
            patient["id"], eligibility_review_payload("APPROVE"), ADMIN
        )
    )
    assert_patient_risk(approved, status="ELIGIBLE")
    assert approved["version"] == 2, (
        f"Approving eligibility must increment the patient version to 2, got "
        f"{approved['version']}"
    )

    enrollment = validate_success(
        api.create_enrollment(
            enrollment_payload(
                patient["id"],
                ctx["sponsorship_program"]["id"],
                cadence_days=30,
                kits_authorized=3,
            ),
            ADMIN,
        ),
        expected_status=201,
    )
    assert_enrollment(
        enrollment,
        status="DRAFT",
        kits_issued=0,
        next_autoship_due_date=None,
        version=1,
        activated_at=None,
        sponsor_decision_note=None,
    )


# --------------------------------------------------------------------------
# The eligibility review DENY fork
# --------------------------------------------------------------------------
def test_05_denying_eligibility_forks_the_patient_into_the_terminal_ineligible_state(api):
    """DENY is the other arm of the review fork: the patient lands in INELIGIBLE
    with the version bumped once.

    PRD 3.3: "`DENY` moves the patient `PENDING_ELIGIBILITY → INELIGIBLE` and likewise increments `version` by 1, but `INELIGIBLE` is terminal and permanently forecloses enrollment: no enrollment may ever be created for that patient afterwards."
    Design: Corner/state_machines/eligibility_review_deny_forks_the_patient_into_the_ineligible_branch
    """
    set_clock(api)
    state_rule = create_california_rule(api)
    patient = create_patient(api, state_rule["id"], weekly_sharps_count=20)
    denied = validate_success(
        api.review_patient_eligibility(
            patient["id"],
            eligibility_review_payload(
                "DENY", note="no state-permitted mail-back pathway on file"
            ),
            ADMIN,
        )
    )
    assert_patient_risk(denied, status="INELIGIBLE")
    assert denied["version"] == 2, (
        f"A denial must increment the patient version to 2, got {denied['version']}"
    )


def test_06_a_denied_patient_keeps_both_risk_scores_at_zero_and_is_listable_by_status(api):
    """The DENY branch is a status fork only: nothing about the patient's risk
    posture changes, and the row remains readable through the status filter.

    PRD 3.3: "A new patient begins at `PENDING_ELIGIBILITY` with `screening_risk_score` at 0, `audit_risk_score` at 0 and `suspended_at` null."
    PRD 3.3: "`DENY` moves the patient `PENDING_ELIGIBILITY → INELIGIBLE` and likewise increments `version` by 1, but `INELIGIBLE` is terminal and permanently forecloses enrollment: no enrollment may ever be created for that patient afterwards."
    PRD 3.3: "Patients can be listed and filtered by `state_rule_id` or `status`, and retrieving one returns both risk scores."
    Design: Corner/state_machines/eligibility_review_deny_forks_the_patient_into_the_ineligible_branch
    """
    set_clock(api)
    state_rule = create_california_rule(api)
    patient = create_patient(api, state_rule["id"], weekly_sharps_count=20)
    api.review_patient_eligibility(
        patient["id"],
        eligibility_review_payload("DENY", note="no state-permitted mail-back pathway on file"),
        ADMIN,
    )

    reread = read_patient(api, patient["id"])
    assert_patient_risk(
        reread,
        screening_risk_score=0,
        audit_risk_score=0,
        status="INELIGIBLE",
        suspended_at=None,
    )
    rows, _ = assert_total_count(
        api.list_patients(ADMIN, {"status": "INELIGIBLE"}), 1
    )
    assert rows[0]["id"] == patient["id"], (
        "The INELIGIBLE listing must return the denied patient"
    )
    assert_empty_listing(api.list_patients(ADMIN, {"status": "ELIGIBLE"}))


# --------------------------------------------------------------------------
# The sponsor decision REJECT fork
# --------------------------------------------------------------------------
def test_07_sponsor_reject_moves_the_enrollment_into_the_terminal_rejected_state_with_the_note(api):
    """REJECT is the narrow sibling of APPROVE: it terminates the enrollment,
    stores the note, and leaves the activation fields null.

    PRD 3.3: "It moves the enrollment `PENDING_SPONSOR_APPROVAL → REJECTED`, which is terminal, and copies the submitted note into `sponsor_decision_note`."
    PRD 3.3: "The enrollment's `version` is incremented by 1."
    Design: Corner/state_machines/sponsor_reject_terminates_the_enrollment_without_touching_patient_or_ledger
    """
    ctx = _sponsor_with_eligible_patient(api)
    enrollment = create_draft_enrollment(
        api,
        ctx["patient"]["id"],
        ctx["sponsorship_program"]["id"],
        cadence_days=30,
        kits_authorized=3,
    )
    get_success_data(api.submit_enrollment(enrollment["id"], ADMIN))

    rejected = validate_success(
        api.record_sponsor_decision(
            enrollment["id"],
            sponsor_decision_payload(
                "REJECT", sponsor_decision_note="outside the funded therapy list"
            ),
            make_sponsor_representative_headers(ctx["sponsor"]["id"]),
        )
    )
    assert_enrollment(
        rejected,
        status="REJECTED",
        kits_issued=0,
        next_autoship_due_date=None,
        version=3,
        activated_at=None,
        sponsor_decision_note="outside the funded therapy list",
    )


def test_08_sponsor_reject_leaves_the_patient_eligible_and_appends_no_ledger_entry(api):
    """No money was ever reserved for a rejected enrollment, so the sponsor's
    ledger stays empty and the patient may still be enrolled elsewhere.

    PRD 3.3: "It leaves `next_autoship_due_date` null, leaves `activated_at` null, does not touch the patient's `status` at all — a patient rejected by one sponsor remains `ELIGIBLE` and may be enrolled elsewhere — and appends no ledger entry whatsoever, because no money was ever reserved."
    PRD 3.2: "Ledger entries are readable individually and as a list filtered by `sponsorship_program_id`, `kit_id` or `entry_type`, always in `sequence_no` ascending order."
    Design: Corner/state_machines/sponsor_reject_terminates_the_enrollment_without_touching_patient_or_ledger
    """
    ctx = _sponsor_with_eligible_patient(api)
    patient_version_before = read_patient(api, ctx["patient"]["id"])["version"]
    enrollment = create_draft_enrollment(
        api,
        ctx["patient"]["id"],
        ctx["sponsorship_program"]["id"],
        cadence_days=30,
        kits_authorized=3,
    )
    get_success_data(api.submit_enrollment(enrollment["id"], ADMIN))
    get_success_data(
        api.record_sponsor_decision(
            enrollment["id"],
            sponsor_decision_payload(
                "REJECT", sponsor_decision_note="outside the funded therapy list"
            ),
            make_sponsor_representative_headers(ctx["sponsor"]["id"]),
        )
    )

    patient = read_patient(api, ctx["patient"]["id"])
    assert_patient_risk(patient, status="ELIGIBLE")
    assert patient["version"] == patient_version_before, (
        "A rejection must not touch the patient row, so its version must not move"
    )
    assert_empty_listing(
        api.list_ledger_entries(
            ADMIN, {"sponsorship_program_id": ctx["sponsorship_program"]["id"]}
        )
    )
    program = read_program(api, ctx["sponsorship_program"]["id"])
    assert_program_balances(
        program,
        reserved_cents=0,
        committed_cents=0,
        available_cents=500000,
        funding_ceiling_cents=500000,
        status="ACTIVE",
    )


# --------------------------------------------------------------------------
# Patient withdrawal: a terminal fan-out that spares kits in the field
# --------------------------------------------------------------------------
def test_09_withdrawal_terminates_every_live_enrollment_of_the_patient(api):
    """One withdrawal reaches both of the patient's ACTIVE enrollments, across two
    different funded programs, and clears their due dates.

    PRD 3.9: "The patient moves to `WITHDRAWN`, which is terminal."
    PRD 3.9: "Every enrollment of that patient whose status is `DRAFT`, `PENDING_SPONSOR_APPROVAL`, `ACTIVE` or `PAUSED` moves to `TERMINATED`, also terminal, with `next_autoship_due_date` cleared to null."
    Design: Corner/state_machines/patient_withdrawal_voids_only_issued_kits_and_spares_the_active_filling_kit
    """
    ctx = _two_program_enrolled_patient(api)
    withdrawn = validate_success(
        api.patient_status_action(
            ctx["patient"]["id"],
            status_action_payload("WITHDRAW", reason="patient moved out of the service area"),
            ADMIN,
        )
    )
    assert_patient_risk(withdrawn, status="WITHDRAWN")

    for key in ("enrollment", "enrollment_b"):
        enrollment = read_enrollment(api, ctx[key]["id"])
        assert_enrollment(
            enrollment, status="TERMINATED", next_autoship_due_date=None
        )


def test_10_withdrawal_voids_the_issued_kit_and_spares_the_active_filling_kit(api):
    """The kit the patient has already acknowledged is out in the field, so the
    cascade stops at the untouched ISSUED kit.

    PRD 3.9: "For each of those terminated enrollments, every kit whose status is `ISSUED` moves to `VOIDED` with `void_reason` set to `ENROLLMENT_TERMINATED`, and each such void appends a `RESERVATION_RELEASE` ledger entry that lowers the program's `reserved_cents`, with `available_cents` and the program `status` recomputed afterwards."
    PRD 3.9: "Kits already in `ACTIVE_FILLING`, `SEALED`, `IN_TRANSIT`, `RECEIVED` or `RETURNED_TO_PATIENT` are physically out in the field and are left completely untouched — the program still expects them back and still owes the reservation."
    Design: Corner/state_machines/patient_withdrawal_voids_only_issued_kits_and_spares_the_active_filling_kit
    """
    ctx = _two_program_enrolled_patient(api)
    get_success_data(
        api.patient_status_action(
            ctx["patient"]["id"],
            status_action_payload("WITHDRAW", reason="patient moved out of the service area"),
            ADMIN,
        )
    )

    kit_in_the_field = read_kit(api, ctx["kit_a"]["id"])
    assert_kit(kit_in_the_field, status="ACTIVE_FILLING", void_reason=None)

    voided_kit = read_kit(api, ctx["kit_b"]["id"])
    assert_kit(voided_kit, status="VOIDED", void_reason="ENROLLMENT_TERMINATED")

    assert_enrollment(read_enrollment(api, ctx["enrollment"]["id"]), kits_issued=1)
    assert_enrollment(read_enrollment(api, ctx["enrollment_b"]["id"]), kits_issued=0)


def test_11_withdrawal_releases_the_reservation_of_the_voided_kit_only(api):
    """Only the voided kit's reservation is released: the first program still owes
    the money for the container the patient is filling.

    PRD 3.9: "For each of those terminated enrollments, every kit whose status is `ISSUED` moves to `VOIDED` with `void_reason` set to `ENROLLMENT_TERMINATED`, and each such void appends a `RESERVATION_RELEASE` ledger entry that lowers the program's `reserved_cents`, with `available_cents` and the program `status` recomputed afterwards."
    PRD 3.9: "Kits already in `ACTIVE_FILLING`, `SEALED`, `IN_TRANSIT`, `RECEIVED` or `RETURNED_TO_PATIENT` are physically out in the field and are left completely untouched — the program still expects them back and still owes the reservation."
    PRD 3.4: "`ONE_QUART` holds 0.9 litres, 100 units, and costs 1450 cents."
    PRD 3.4: "The base component is the catalogue's `unit_cost_cents` for the selected size."
    PRD 3.4: "The transport component estimates weight from capacity rather than from any actual fill: the container's `capacity_units` is multiplied by 4 grams per unit to give an estimated gram weight, that figure is multiplied by the transport rate of 38 cents per kilogram and divided by 1000 to convert grams to kilograms, and the result is rounded half up to a whole cent."
    PRD 3.4: "`provisional_cost_cents` is the base component plus that rounded transport component."
    Design: Corner/state_machines/patient_withdrawal_voids_only_issued_kits_and_spares_the_active_filling_kit
    """
    ctx = _two_program_enrolled_patient(api)
    get_success_data(
        api.patient_status_action(
            ctx["patient"]["id"],
            status_action_payload("WITHDRAW", reason="patient moved out of the service area"),
            ADMIN,
        )
    )

    program_a = read_program(api, ctx["sponsorship_program"]["id"])
    assert_program_balances(
        program_a,
        reserved_cents=1465,
        committed_cents=0,
        available_cents=498535,
        funding_ceiling_cents=500000,
        status="ACTIVE",
    )
    assert program_a["kits_issued_count"] == 1, (
        "The spared ACTIVE_FILLING kit still counts toward kits_issued_count"
    )
    assert_ledger_sequence(
        read_ledger_entries(api, ctx["sponsorship_program"]["id"]),
        [(1, "RESERVATION", 1465)],
    )

    program_b = read_program(api, ctx["program_b"]["id"])
    assert_program_balances(
        program_b,
        reserved_cents=0,
        committed_cents=0,
        available_cents=300000,
        funding_ceiling_cents=300000,
        status="ACTIVE",
    )
    assert program_b["kits_issued_count"] == 0, (
        "The voided kit must drop out of kits_issued_count"
    )
    assert_ledger_sequence(
        read_ledger_entries(api, ctx["program_b"]["id"]),
        [(1, "RESERVATION", 1465), (2, "RESERVATION_RELEASE", -1465)],
    )


# --------------------------------------------------------------------------
# Sponsor suspension gates only the two declared entry points
# --------------------------------------------------------------------------
def test_12_suspending_a_sponsor_moves_it_to_suspended_and_increments_its_version(api):
    """The sponsor status action is a two-way switch on the sponsor row itself.

    PRD 3.2: "A `ProgramAdmin` may suspend or reinstate a sponsor by supplying an `action` of `SUSPEND` or `REINSTATE` with an optional `reason`, moving it `ACTIVE → SUSPENDED` or `SUSPENDED → ACTIVE` and incrementing the sponsor's `version` by 1."
    Design: Corner/state_machines/suspended_sponsor_blocks_new_programs_and_new_enrollments_until_reinstated
    """
    ctx = _sponsor_with_eligible_patient(api)
    suspended = validate_success(
        api.sponsor_status_action(
            ctx["sponsor"]["id"],
            status_action_payload("SUSPEND", reason="funding audit in progress"),
            ADMIN,
        )
    )
    assert suspended["status"] == "SUSPENDED", (
        f"Expected sponsor status SUSPENDED, got {suspended['status']!r}"
    )
    assert suspended["version"] == 2, (
        f"Suspension must increment the sponsor version to 2, got {suspended['version']}"
    )


def test_13_a_suspended_sponsor_blocks_both_a_new_program_and_a_new_enrollment(api):
    """Both declared gate points refuse with the same error, while the existing
    program and its balances are left exactly as they were.

    PRD 3.2: "The gate is evaluated at precisely two points — opening a new program under that sponsor, and creating a new enrollment against one of its programs — and in both cases a non-`ACTIVE` sponsor produces `ERR_SPONSOR_NOT_ACTIVE` (HTTP 422)."
    PRD 3.2: "Suspension is deliberately narrow: existing programs, enrollments, kits and ledger balances are all left exactly as they were, and no in-flight work is disturbed."
    Design: Corner/state_machines/suspended_sponsor_blocks_new_programs_and_new_enrollments_until_reinstated
    """
    ctx = _sponsor_with_eligible_patient(api)
    get_success_data(
        api.sponsor_status_action(
            ctx["sponsor"]["id"],
            status_action_payload("SUSPEND", reason="funding audit in progress"),
            ADMIN,
        )
    )

    validate_error(
        api.create_sponsorship_program(
            ctx["sponsor"]["id"],
            sponsorship_program_payload(
                program_code="NW-2027",
                funding_ceiling_cents=200000,
                per_kit_allowance_cents=5000,
            ),
            ADMIN,
        ),
        "ERR_SPONSOR_NOT_ACTIVE",
        expected_status=422,
    )
    validate_error(
        api.create_enrollment(
            enrollment_payload(
                ctx["patient"]["id"],
                ctx["sponsorship_program"]["id"],
                cadence_days=30,
                kits_authorized=3,
            ),
            ADMIN,
        ),
        "ERR_SPONSOR_NOT_ACTIVE",
        expected_status=422,
    )

    assert_total_count(api.list_sponsor_programs(ctx["sponsor"]["id"], ADMIN), 1)
    assert_empty_listing(api.list_enrollments(ADMIN))
    assert_program_balances(
        read_program(api, ctx["sponsorship_program"]["id"]),
        reserved_cents=0,
        committed_cents=0,
        available_cents=500000,
        funding_ceiling_cents=500000,
        status="ACTIVE",
    )


def test_14_reinstating_the_sponsor_lets_the_identical_enrollment_payload_succeed(api):
    """The gate is a live read of the sponsor's status, so reinstatement reopens
    the enrollment path with no other change.

    PRD 3.2: "A `ProgramAdmin` may suspend or reinstate a sponsor by supplying an `action` of `SUSPEND` or `REINSTATE` with an optional `reason`, moving it `ACTIVE → SUSPENDED` or `SUSPENDED → ACTIVE` and incrementing the sponsor's `version` by 1."
    PRD 3.2: "The gate is evaluated at precisely two points — opening a new program under that sponsor, and creating a new enrollment against one of its programs — and in both cases a non-`ACTIVE` sponsor produces `ERR_SPONSOR_NOT_ACTIVE` (HTTP 422)."
    PRD 3.3: "The new enrollment starts at `DRAFT` with `kits_issued` at 0, `next_autoship_due_date` null, `activated_at` null, `sponsor_decision_note` null and `version` at 1."
    Design: Corner/state_machines/suspended_sponsor_blocks_new_programs_and_new_enrollments_until_reinstated
    """
    ctx = _sponsor_with_eligible_patient(api)
    payload = enrollment_payload(
        ctx["patient"]["id"],
        ctx["sponsorship_program"]["id"],
        cadence_days=30,
        kits_authorized=3,
    )
    get_success_data(
        api.sponsor_status_action(
            ctx["sponsor"]["id"],
            status_action_payload("SUSPEND", reason="funding audit in progress"),
            ADMIN,
        )
    )
    validate_error(
        api.create_enrollment(payload, ADMIN),
        "ERR_SPONSOR_NOT_ACTIVE",
        expected_status=422,
    )

    reinstated = validate_success(
        api.sponsor_status_action(
            ctx["sponsor"]["id"], status_action_payload("REINSTATE"), ADMIN
        )
    )
    assert reinstated["status"] == "ACTIVE", (
        f"Expected sponsor status ACTIVE after reinstatement, got {reinstated['status']!r}"
    )
    assert reinstated["version"] == 3, (
        f"A suspend then reinstate pair must leave the sponsor at version 3, got "
        f"{reinstated['version']}"
    )

    enrollment = validate_success(
        api.create_enrollment(payload, ADMIN), expected_status=201
    )
    assert_enrollment(
        enrollment,
        status="DRAFT",
        kits_issued=0,
        next_autoship_due_date=None,
        version=1,
        activated_at=None,
        sponsor_decision_note=None,
    )
    assert_total_count(api.list_enrollments(ADMIN), 1)


# --------------------------------------------------------------------------
# Certificate void: an exact compensation that never reuses the number
# --------------------------------------------------------------------------
VOID_REASON = "destroyed unit count mis-keyed at the scale"


def _voided_certificate(api):
    """The settled kit of `_settled_certificate`, with its certificate voided at
    clock 2026-08-21T09:00:00Z."""
    ctx = _settled_certificate(api)
    set_clock(api, "2026-08-21T09:00:00Z")
    ctx["voided_certificate"] = get_success_data(
        api.void_destruction_certificate(
            ctx["certificate"]["id"],
            certificate_void_payload(VOID_REASON),
            make_destruction_officer_headers(),
        )
    )
    return ctx


def test_15_voiding_the_certificate_restores_the_pre_certificate_program_triple(api):
    """The compensating pair puts the reservation back and unwinds the commitment,
    returning the program to exactly the balances it held before settlement.

    PRD 3.8: "Two ledger entries are appended, again in a pinned order: first a `COMMITMENT_REVERSAL` for the negation of `final_kit_cost_cents`, then, at the immediately following `sequence_no`, a `RESERVATION` for the positive `provisional_cost_cents` of the kit — which restores the program's reserved, committed and available triple to precisely the values it held before the certificate was issued."
    PRD 2.9: "`available_cents` is `funding_ceiling_cents` less `reserved_cents` less `committed_cents`, recomputed after every append."
    PRD 3.4: "`ONE_QUART` holds 0.9 litres, 100 units, and costs 1450 cents."
    PRD 3.4: "The base component is the catalogue's `unit_cost_cents` for the selected size."
    PRD 3.4: "The transport component estimates weight from capacity rather than from any actual fill: the container's `capacity_units` is multiplied by 4 grams per unit to give an estimated gram weight, that figure is multiplied by the transport rate of 38 cents per kilogram and divided by 1000 to convert grams to kilograms, and the result is rounded half up to a whole cent."
    PRD 3.4: "`provisional_cost_cents` is the base component plus that rounded transport component."
    Design: Corner/state_machines/certificate_void_reverses_the_settlement_exactly_and_never_reuses_the_number
    """
    ctx = _voided_certificate(api)
    program = read_program(api, ctx["sponsorship_program"]["id"])
    assert_program_balances(
        program,
        reserved_cents=1465,
        committed_cents=0,
        available_cents=498535,
        funding_ceiling_cents=500000,
        status="ACTIVE",
    )
    before = ctx["pre_certificate_program"]
    for field in ("reserved_cents", "committed_cents", "available_cents"):
        assert program[field] == before[field], (
            f"Void must restore {field} to its pre-certificate value "
            f"{before[field]}, got {program[field]}"
        )


def test_16_voiding_the_certificate_rebooks_custody_units_and_reopens_the_kit(api):
    """Custody of the units returns to the facility, the lifetime destroyed total
    is unwound, and the kit drops back to RECEIVED so a corrected certificate can
    be issued.

    PRD 3.8: "The kit moves `DESTROYED → RECEIVED` with its `version` incremented by 1, which is what re-opens the cycle and allows a corrected certificate to be issued."
    PRD 3.8: "On the facility, `pending_intake_units` rises by exactly the shipment's `custody_units`, `destroyed_units_total` falls by the certificate's `destroyed_units`, and `certificates_issued_count` is deliberately left **unchanged** so that certificate numbers are never reused."
    Design: Corner/state_machines/certificate_void_reverses_the_settlement_exactly_and_never_reuses_the_number
    """
    ctx = _voided_certificate(api)
    assert_facility_counters(
        read_treatment_facility(api, ctx["treatment_facility"]["id"]),
        pending_intake_units=60,
        destroyed_units_total=0,
        certificates_issued_count=1,
        status="ACTIVE",
    )
    assert_kit(read_kit(api, ctx["kit"]["id"]), status="RECEIVED", fill_units=60)


def test_17_the_voided_certificate_freezes_its_number_and_retention_deadline(api):
    """Voiding only changes the certificate's status and void fields; the number,
    the destruction date and the retention deadline it minted stay put.

    PRD 3.8: "The certificate moves `ISSUED → VOIDED` with `voided_at` set to the current logical-clock instant and the supplied reason stored in `void_reason`."
    PRD 3.8: "Its `certificate_number` is the literal text `CERT-`, then the facility's `permit_number`, then a hyphen, then a sequence number zero-padded to five digits, where the sequence number is the facility's `certificates_issued_count` plus one."
    PRD 3.8: "A new certificate records the `shipment_id` it certifies, copies `kit_id` and `treatment_facility_id` from that shipment, writes the acting `X-User-ID` into `issued_by_user_id`, and sets `destruction_date` to the UTC calendar date of the logical clock at issuance."
    PRD 3.8: "Take the `certificate_retention_years` of the patient's state rule, the `certificate_retention_years` of the facility's state rule, and the federal minimum of 3 years, and use the largest of the three."
    PRD 3.8: "That number of whole calendar years is then added to `destruction_date`."
    Design: Corner/state_machines/certificate_void_reverses_the_settlement_exactly_and_never_reuses_the_number
    """
    ctx = _voided_certificate(api)
    certificate = read_destruction_certificate(api, ctx["certificate"]["id"])
    assert_certificate(
        certificate,
        certificate_number="CERT-CA-TF-0001-00001",
        destroyed_units=60,
        destruction_date="2026-08-20",
        retention_until_date="2029-08-20",
        status="VOIDED",
    )
    assert certificate["void_reason"] == VOID_REASON, (
        f"Expected void_reason {VOID_REASON!r}, got {certificate['void_reason']!r}"
    )
    assert certificate["voided_at"] is not None, (
        "A voided certificate must carry the instant at which it was voided"
    )


def test_18_the_replacement_certificate_takes_a_fresh_number_and_is_not_blocked_by_the_void(api):
    """A voided certificate does not block re-issuance, and because the facility's
    minted-certificate counter was never decremented the corrected certificate
    bears the next number rather than reusing the first.

    PRD 3.8: "The shipment must carry no destruction certificate in status `ISSUED`, otherwise `ERR_CERTIFICATE_ALREADY_ISSUED` (HTTP 409); a previously voided certificate does not block re-issuance."
    PRD 3.8: "Because that counter includes voided certificates and is never decremented, a number is never reused: a corrected certificate re-issued for the same shipment always bears a fresh number."
    PRD 3.8: "Its `certificate_number` is the literal text `CERT-`, then the facility's `permit_number`, then a hyphen, then a sequence number zero-padded to five digits, where the sequence number is the facility's `certificates_issued_count` plus one."
    PRD 3.8: "A new certificate records the `shipment_id` it certifies, copies `kit_id` and `treatment_facility_id` from that shipment, writes the acting `X-User-ID` into `issued_by_user_id`, and sets `destruction_date` to the UTC calendar date of the logical clock at issuance."
    PRD 3.8: "Take the `certificate_retention_years` of the patient's state rule, the `certificate_retention_years` of the facility's state rule, and the federal minimum of 3 years, and use the largest of the three."
    PRD 3.8: "That number of whole calendar years is then added to `destruction_date`."
    PRD 3.8: "Certificates are readable individually and as a list filtered by `shipment_id`, `kit_id`, `treatment_facility_id` or `status`."
    Design: Corner/state_machines/certificate_void_reverses_the_settlement_exactly_and_never_reuses_the_number
    """
    ctx = _voided_certificate(api)
    replacement = validate_success(
        api.issue_destruction_certificate(
            ctx["shipment"]["id"],
            destruction_certificate_payload(60),
            make_destruction_officer_headers(),
        ),
        expected_status=201,
    )
    assert_certificate(
        replacement,
        certificate_number="CERT-CA-TF-0001-00002",
        destroyed_units=60,
        destruction_date="2026-08-21",
        retention_until_date="2029-08-21",
        status="ISSUED",
    )
    assert replacement["id"] != ctx["certificate"]["id"], (
        "Re-issuance must mint a new certificate row, not revive the voided one"
    )
    assert_facility_counters(
        read_treatment_facility(api, ctx["treatment_facility"]["id"]),
        pending_intake_units=0,
        destroyed_units_total=60,
        certificates_issued_count=2,
        status="ACTIVE",
    )
    assert_total_count(
        api.list_destruction_certificates(
            ADMIN, {"shipment_id": ctx["shipment"]["id"]}
        ),
        2,
    )


def test_19_the_reissued_settlement_recommits_the_final_cost_and_the_ledger_shows_both_compensation_pairs(api):
    """The whole episode leaves four compensating appends plus the original
    reservation on the ledger, and the program ends up committed for exactly one
    final cost.

    PRD 3.8: "The base component is the size catalogue's `unit_cost_cents` for the kit's `container_size` — the same base the provisional figure used."
    PRD 3.8: "The transport component takes the shipment's `observed_gross_weight_grams`, multiplies by the transport rate of 38 cents per kilogram, divides by 1000 to convert grams to kilograms, and rounds half up to a whole cent; note that this uses the weight the technician measured, not the capacity-based estimate the reservation used."
    PRD 3.8: "The destruction component multiplies the certificate's `destroyed_units` by the sponsor's per-unit destruction rate — 3 cents per unit when the sponsor's `sponsor_type` is `MANUFACTURER` and 2.5 cents per unit when it is `HEALTH_PLAN` — and rounds half up to a whole cent."
    PRD 3.8: "The surcharge component is 0 when the shipment carries no resolved remediation action or when the resolved action was `RETURN_TO_PATIENT`, 500 cents when it was `ON_SITE_REPACK`, and 900 cents when it was `DISPOSE_AS_RMW`."
    PRD 3.8: "Those four rounded components are added to give a pre-rebate amount, and the pre-rebate amount is then capped: the amount carried forward is the smaller of the program's `per_kit_allowance_cents` and the pre-rebate amount."
    PRD 3.8: "For a `MANUFACTURER` sponsor the percentage is selected from a tier table keyed on a cumulative basis figure, and that basis is the program's `committed_cents` **as it stands before this certificate's ledger appends** plus this kit's capped pre-rebate amount."
    PRD 3.8: "The tiers are: a basis from 0 through 14999 cents inclusive gives 0; a basis from 15000 through 29999 cents inclusive gives 0.03; and a basis from 30000 through 100000000 cents inclusive gives 0.06."
    PRD 3.8: "The rebate amount is the capped amount multiplied by that percentage, rounded half up to a whole cent, and `final_kit_cost_cents` is the capped amount less that rebate amount."
    PRD 3.8: "Two ledger entries are appended in a pinned order that must not be swapped: first a `RESERVATION_RELEASE` for the negation of the kit's `provisional_cost_cents`, then, at the immediately following `sequence_no`, a `COMMITMENT` for the positive `final_kit_cost_cents`."
    PRD 3.8: "Two ledger entries are appended, again in a pinned order: first a `COMMITMENT_REVERSAL` for the negation of `final_kit_cost_cents`, then, at the immediately following `sequence_no`, a `RESERVATION` for the positive `provisional_cost_cents` of the kit — which restores the program's reserved, committed and available triple to precisely the values it held before the certificate was issued."
    PRD 2.9: "Each entry also carries a `sequence_no`, a per-program monotonic counter starting at 1, which pins the relative order of appends made in the same request or at the same clock instant; ledger listings are returned in `sequence_no` ascending order."
    PRD 2.9: "On the program side, `reserved_cents` is the sum of `RESERVATION` amounts less the sum of `RESERVATION_RELEASE` amounts over that program's entries, and `committed_cents` is the sum of `COMMITMENT` amounts less the sum of `COMMITMENT_REVERSAL` amounts."
    PRD 2.9: "`available_cents` is `funding_ceiling_cents` less `reserved_cents` less `committed_cents`, recomputed after every append."
    Design: Corner/state_machines/certificate_void_reverses_the_settlement_exactly_and_never_reuses_the_number
    """
    ctx = _voided_certificate(api)
    replacement = get_success_data(
        api.issue_destruction_certificate(
            ctx["shipment"]["id"],
            destruction_certificate_payload(60),
            make_destruction_officer_headers(),
        )
    )
    assert_certificate(replacement, final_kit_cost_cents=1676, rebate_pct_applied=0)

    assert_program_balances(
        read_program(api, ctx["sponsorship_program"]["id"]),
        reserved_cents=0,
        committed_cents=1676,
        available_cents=498324,
        funding_ceiling_cents=500000,
        status="ACTIVE",
    )
    assert_ledger_sequence(
        read_ledger_entries(api, ctx["sponsorship_program"]["id"]),
        [
            (1, "RESERVATION", 1465),
            (2, "RESERVATION_RELEASE", -1465),
            (3, "COMMITMENT", 1676),
            (4, "COMMITMENT_REVERSAL", -1676),
            (5, "RESERVATION", 1465),
            (6, "RESERVATION_RELEASE", -1465),
            (7, "COMMITMENT", 1676),
        ],
    )
