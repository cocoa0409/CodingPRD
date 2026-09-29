"""Program reconciliation reads, transactional auto-ship aborts, and the
remediation-legality fork.

Every test builds its own world from scratch through the PRD's own endpoints;
the harness restarts the server with an empty database before each one.
"""

from test_helpers import (
    TEST_USERS,
    acknowledge_kit,
    add_enrolled_patient,
    assert_auto_ship_run,
    assert_certificate,
    assert_enrollment,
    assert_facility_counters,
    assert_kit,
    assert_ledger_entry,
    assert_ledger_sequence,
    assert_ledger_sequence_numbers_start_at_one,
    assert_non_conformance_event,
    assert_program_balances,
    assert_shipment_axes,
    assert_total_count,
    auto_ship_run_payload,
    destruction_certificate_payload,
    get_success_data,
    issue_kit_for,
    kit_void_payload,
    make_destruction_officer_headers,
    make_intake_technician_headers,
    make_sponsor_representative_headers,
    read_enrollment,
    read_kit,
    read_ledger_entries,
    read_non_conformance_event,
    read_program,
    read_shipment,
    read_treatment_facility,
    remediation_payload,
    seal_kit_for,
    set_clock,
    setup_issued_certificate,
    setup_notified_non_conformance,
    setup_program_foundations,
    status_action_payload,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
LOGISTICS = TEST_USERS["logistics_coordinator_headers"]

TECH_ID = "tech-77"
OFFICER_ID = "officer-12"

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
_PROGRAM = {"funding_ceiling_cents": 500000, "per_kit_allowance_cents": 5000}
_DANA = {"full_name": "Dana Reyes", "weekly_sharps_count": 20, "contact_email": "dana@example.com"}
_CADENCE_30 = {"cadence_days": 30, "kits_authorized": 3}


def _settled_then_voided_kit(api):
    """One kit driven all the way to a settled destruction certificate, plus a
    second kit issued and then administratively voided."""
    ctx = setup_issued_certificate(
        api,
        destroyed_units=60,
        officer_user_id=OFFICER_ID,
        technician_user_id=TECH_ID,
        observed_gross_weight_grams=1200,
        fill_units=60,
        sealed_gross_weight_grams=1200,
        declared_gross_weight_grams=1200,
        scheduled_intake_date="2026-08-05",
        state_rule_overrides=dict(_EXEMPT_CA_RULE),
        packaging_spec_overrides=dict(_MAILBACK_SPEC),
        facility_overrides=dict(_SHARPS_ONLY_FACILITY),
        sponsor_overrides=dict(_MANUFACTURER),
        program_overrides=dict(_PROGRAM),
        patient_overrides=dict(_DANA),
        enrollment_overrides=dict(_CADENCE_30),
    )
    second_kit = issue_kit_for(api, ctx)
    get_success_data(
        api.void_kit(
            second_kit["id"],
            kit_void_payload("wrong shipping address on the outer box"),
            LOGISTICS,
        )
    )
    return ctx, ctx["kits"][0], second_kit


def test_01_program_read_reports_every_derived_counter(api):
    """After one settled kit and one voided kit the program read must show the
    balance triple and all four derived counters at once, each independently
    derived: the voided kit drops out of `kits_issued_count` while the destroyed
    kit is counted, and the provisional and final totals differ by design.

    PRD 3.2: "Beyond the reserved/committed/available triple a program maintains five derived counters that a sponsor uses to reconcile: `kits_issued_count`, the number of kits under this program's enrollments whose status is anything other than `VOIDED`; `kits_settled_count`, the number of destruction certificates in status `ISSUED` against this program's kits; `provisional_total_cents`, the sum of `provisional_cost_cents` over this program's kits that carry an `ISSUED` certificate; and `final_total_cents`, the sum of `final_kit_cost_cents` over this program's `ISSUED` certificates."
    PRD 2.9: "`available_cents` is `funding_ceiling_cents` less `reserved_cents` less `committed_cents`, recomputed after every append."
    Design: Corner/endpoints/program_read_reconciles_every_derived_counter_against_the_ledger
    """
    ctx, first_kit, second_kit = _settled_then_voided_kit(api)

    response = api.get_sponsorship_program(
        ctx["sponsorship_program"]["id"],
        make_sponsor_representative_headers(ctx["sponsor"]["id"]),
    )
    program = validate_success(response, 200)

    assert_program_balances(
        program,
        reserved_cents=0,
        committed_cents=1676,
        available_cents=498324,
        funding_ceiling_cents=500000,
        status="ACTIVE",
    )
    assert program["kits_issued_count"] == 1, (
        f"the VOIDED kit must drop out of kits_issued_count, got "
        f"{program['kits_issued_count']}"
    )
    assert program["kits_settled_count"] == 1, (
        f"Expected kits_settled_count 1, got {program['kits_settled_count']}"
    )
    assert program["provisional_total_cents"] == 1465, (
        f"Expected provisional_total_cents 1465, got {program['provisional_total_cents']}"
    )
    assert program["final_total_cents"] == 1676, (
        f"Expected final_total_cents 1676, got {program['final_total_cents']}"
    )

    assert_certificate(ctx["destruction_certificate"], final_kit_cost_cents=1676, status="ISSUED")
    assert_kit(read_kit(api, first_kit["id"]), status="DESTROYED", provisional_cost_cents=1465)
    assert_kit(read_kit(api, second_kit["id"]), status="VOIDED", provisional_cost_cents=1465)
    assert_enrollment(read_enrollment(api, ctx["enrollment"]["id"]), kits_issued=1)


def test_02_ledger_appends_reconcile_with_the_program_read(api):
    """The same world read through the ledger: five appends in `sequence_no`
    ascending order, and the last entry's three after-balances must equal the
    figures the program read reports.

    PRD 2.9: "Each entry also carries a `sequence_no`, a per-program monotonic counter starting at 1, which pins the relative order of appends made in the same request or at the same clock instant; ledger listings are returned in `sequence_no` ascending order."
    PRD 2.9: "Finally, each entry snapshots the three program balances as they stood immediately after the append, in `reserved_after_cents`, `committed_after_cents` and `available_after_cents`, and records a human-readable origin in `memo` — "kit issuance", "kit void", "certificate settlement" and the like."
    PRD 2.9: "On the program side, `reserved_cents` is the sum of `RESERVATION` amounts less the sum of `RESERVATION_RELEASE` amounts over that program's entries, and `committed_cents` is the sum of `COMMITMENT` amounts less the sum of `COMMITMENT_REVERSAL` amounts."
    Design: Corner/endpoints/program_read_reconciles_every_derived_counter_against_the_ledger
    """
    ctx, first_kit, second_kit = _settled_then_voided_kit(api)
    program_id = ctx["sponsorship_program"]["id"]

    entries = read_ledger_entries(api, program_id)
    assert_ledger_sequence(
        entries,
        [
            (1, "RESERVATION", 1465),
            (2, "RESERVATION_RELEASE", -1465),
            (3, "COMMITMENT", 1676),
            (4, "RESERVATION", 1465),
            (5, "RESERVATION_RELEASE", -1465),
        ],
    )
    assert_ledger_sequence_numbers_start_at_one(entries)
    for entry in entries[:3]:
        assert entry["kit_id"] == first_kit["id"], (
            f"the first three appends account for the settled kit, got kit_id "
            f"{entry['kit_id']!r}"
        )
    for entry in entries[3:]:
        assert entry["kit_id"] == second_kit["id"], (
            f"the last two appends account for the voided kit, got kit_id "
            f"{entry['kit_id']!r}"
        )
    for entry in entries:
        assert entry["sponsorship_program_id"] == program_id

    assert_ledger_entry(
        entries[4],
        entry_type="RESERVATION_RELEASE",
        amount_cents=-1465,
        sequence_no=5,
        reserved_after_cents=0,
        committed_after_cents=1676,
        available_after_cents=498324,
        kit_id=second_kit["id"],
    )

    program = read_program(api, program_id)
    assert program["reserved_cents"] == entries[4]["reserved_after_cents"]
    assert program["committed_cents"] == entries[4]["committed_after_cents"]
    assert program["available_cents"] == entries[4]["available_after_cents"]


def _two_enrollment_checkpoint_world(api):
    """Bianca's enrollment is created first and holds no kit; Aaron's is created
    an hour later, holds one SEALED kit, and authorizes only that one kit. At
        2026-08-31 both enrollments are due."""
    ctx = setup_program_foundations(
        api,
        state_rule_overrides=dict(_EXEMPT_CA_RULE),
        packaging_spec_overrides=dict(_MAILBACK_SPEC),
        facility_overrides=dict(_SHARPS_ONLY_FACILITY),
        sponsor_overrides=dict(_MANUFACTURER),
        program_overrides=dict(_PROGRAM),
    )
    add_enrolled_patient(
        api,
        ctx,
        patient_overrides={
            "full_name": "Bianca Ortiz",
            "weekly_sharps_count": 20,
            "contact_email": "bianca@example.com",
        },
        enrollment_overrides={"cadence_days": 30, "kits_authorized": 2},
        key="bianca",
    )
    set_clock(api, "2026-08-01T01:00:00Z")
    add_enrolled_patient(
        api,
        ctx,
        patient_overrides={
            "full_name": "Aaron Vance",
            "weekly_sharps_count": 20,
            "contact_email": "aaron@example.com",
        },
        enrollment_overrides={"cadence_days": 30, "kits_authorized": 1},
        key="aaron",
    )
    aaron_kit = issue_kit_for(api, ctx, enrollment=ctx["enrollment_aaron"])
    acknowledge_kit(api, ctx, kit=aaron_kit, patient=ctx["patient_aaron"])
    seal_kit_for(
        api,
        ctx,
        kit=aaron_kit,
        patient=ctx["patient_aaron"],
        fill_units=55,
        sealed_gross_weight_grams=1150,
    )
    set_clock(api, "2026-08-31T00:00:00Z")
    return ctx, aaron_kit


def test_03_checkpoint_abort_rolls_back_the_kit_it_had_already_minted(api):
    """The checkpoint mints the first due enrollment's kit and only then reaches a
    second due enrollment that has exhausted its authorizations. Because the
    authorization cap aborts the run rather than skipping the enrollment, no run
    record, no kit and no reservation may survive.

    PRD 3.9: "But four conditions abort a run **entirely**, leaving no run record and no kits behind, rather than skipping the offending enrollment."
    PRD 3.9: "If a due, unskipped enrollment has already reached its `kits_authorized` limit, the run raises `ERR_KIT_AUTHORIZATION_EXHAUSTED` (HTTP 409) — the authorization cap is enforced but is emphatically not a skip reason."
    PRD 2.9: "On the program side, `reserved_cents` is the sum of `RESERVATION` amounts less the sum of `RESERVATION_RELEASE` amounts over that program's entries, and `committed_cents` is the sum of `COMMITMENT` amounts less the sum of `COMMITMENT_REVERSAL` amounts."
    Design: Corner/endpoints/auto_ship_run_aborts_all_or_nothing_when_a_later_enrollment_is_out_of_authorizations
    """
    ctx, aaron_kit = _two_enrollment_checkpoint_world(api)
    program_id = ctx["sponsorship_program"]["id"]

    response = api.create_auto_ship_run(auto_ship_run_payload(), ADMIN)
    validate_error(response, "ERR_KIT_AUTHORIZATION_EXHAUSTED", 409)

    assert_total_count(api.list_auto_ship_runs(ADMIN), 0)
    assert_total_count(
        api.list_kits(ADMIN, {"enrollment_id": ctx["enrollment_bianca"]["id"]}), 0
    )
    assert_total_count(
        api.list_kits(ADMIN, {"enrollment_id": ctx["enrollment_aaron"]["id"]}), 1
    )

    assert_program_balances(
        read_program(api, program_id),
        reserved_cents=1465,
        committed_cents=0,
        available_cents=498535,
        status="ACTIVE",
    )
    assert_total_count(
        api.list_ledger_entries(ADMIN, {"sponsorship_program_id": program_id}), 1
    )
    assert_enrollment(
        read_enrollment(api, ctx["enrollment_bianca"]["id"]),
        status="ACTIVE",
        kits_issued=0,
        next_autoship_due_date="2026-08-01",
    )
    assert_kit(read_kit(api, aaron_kit["id"]), status="SEALED")


def test_04_checkpoint_succeeds_once_the_faulting_enrollment_leaves_scope(api):
    """Withdrawing Aaron terminates his enrollment but leaves his SEALED kit and
    its reservation untouched, which takes the faulting enrollment out of the
    checkpoint's scope. The re-run then evaluates only Bianca's enrollment and
    mints her replacement container.

    PRD 3.9: "Kits already in `ACTIVE_FILLING`, `SEALED`, `IN_TRANSIT`, `RECEIVED` or `RETURNED_TO_PATIENT` are physically out in the field and are left completely untouched — the program still expects them back and still owes the reservation."
    PRD 3.9: "The run then walks the enrollments whose status is `ACTIVE`, and only those — `DRAFT`, `PENDING_SPONSOR_APPROVAL`, `PAUSED`, `REJECTED` and `TERMINATED` enrollments are out of scope entirely — in ascending order of enrollment creation time."
    PRD 3.9: "The new kit's `supersedes_kit_id` is set to the enrollment's most recent prior kit by creation time, or null when the enrollment has none, and its `auto_ship_run_id` is set to this run."
    PRD 3.9: "After the kit is minted, the enrollment's `next_autoship_due_date` is set to the run's `as_of_date` advanced by the enrollment's `cadence_days`, `kits_created` rises by 1, and the new kit's id is appended to `created_kit_ids`, which therefore lists ids in processing order."
    Design: Corner/endpoints/auto_ship_run_aborts_all_or_nothing_when_a_later_enrollment_is_out_of_authorizations
    """
    ctx, aaron_kit = _two_enrollment_checkpoint_world(api)
    program_id = ctx["sponsorship_program"]["id"]
    validate_error(
        api.create_auto_ship_run(auto_ship_run_payload(), ADMIN),
        "ERR_KIT_AUTHORIZATION_EXHAUSTED",
        409,
    )

    get_success_data(
        api.patient_status_action(
            ctx["patient_aaron"]["id"], status_action_payload("WITHDRAW"), ADMIN
        )
    )
    assert_enrollment(read_enrollment(api, ctx["enrollment_aaron"]["id"]), status="TERMINATED")
    assert_kit(read_kit(api, aaron_kit["id"]), status="SEALED")
    assert_program_balances(read_program(api, program_id), reserved_cents=1465)

    run = validate_success(api.create_auto_ship_run(auto_ship_run_payload(), ADMIN), 201)
    assert_auto_ship_run(
        run,
        enrollments_evaluated=1,
        kits_created=1,
        kits_skipped_not_due=0,
        kits_skipped_risk=0,
        kits_skipped_unfilled=0,
        kits_skipped_funding=0,
        as_of_date="2026-08-31",
    )
    assert len(run["created_kit_ids"]) == 1, (
        f"Expected exactly one created kit id, got {run['created_kit_ids']}"
    )

    new_kit = read_kit(api, run["created_kit_ids"][0])
    assert_kit(
        new_kit,
        status="ISSUED",
        container_size="ONE_QUART",
        provisional_cost_cents=1465,
        supersedes_kit_id=None,
        auto_ship_run_id=run["id"],
    )
    assert new_kit["enrollment_id"] == ctx["enrollment_bianca"]["id"]

    assert_program_balances(read_program(api, program_id), reserved_cents=1465 * 2)
    assert_enrollment(
        read_enrollment(api, ctx["enrollment_bianca"]["id"]),
        kits_issued=1,
        next_autoship_due_date="2026-09-30",
    )


_REGULATED_NY_RULE = {
    "state_code": "NY",
    "household_sharps_classification": "REGULATED_MEDICAL_WASTE",
    "mail_back_permitted": True,
    "max_container_volume_liters": 30.3,
    "requires_state_manifest": False,
    "certificate_retention_years": 3,
    "notification_deadline_hours": 72,
}
_NY_SHARPS_ONLY_FACILITY = {
    "name": "Hudson Valley Sharps Treatment",
    "permit_number": "NY-TF-0007",
    "accepted_hazard_classes": ["UN3291_SHARPS_ONLY"],
    "daily_intake_capacity_units": 200,
}
_NORA = {"full_name": "Nora Keil", "weekly_sharps_count": 20, "contact_email": "nora@example.com"}


def _ny_notified_non_conformance(api):
    """A New York patient's ONE_QUART kit, rejected at intake for an overfilled
    container and the customer notified, awaiting a remediation decision. The
    receiving facility's permit covers sharps only."""
    return setup_notified_non_conformance(
        api,
        reason_code="OVERFILLED_CONTAINER",
        notification_channel="EMAIL",
        observed_gross_weight_grams=1200,
        technician_user_id=TECH_ID,
        fill_units=60,
        sealed_gross_weight_grams=1200,
        declared_gross_weight_grams=1200,
        scheduled_intake_date="2026-08-05",
        state_rule_overrides=dict(_REGULATED_NY_RULE),
        packaging_spec_overrides=dict(_MAILBACK_SPEC),
        facility_overrides=dict(_NY_SHARPS_ONLY_FACILITY),
        sponsor_overrides=dict(_MANUFACTURER),
        program_overrides=dict(_PROGRAM),
        patient_overrides=dict(_NORA),
        enrollment_overrides=dict(_CADENCE_30),
    )


def test_05_return_to_patient_is_barred_by_the_patients_state_classification(api):
    """The first of the two legality gates: New York classifies household sharps
    as regulated medical waste, so mailing the parcel back to the household is
    not an available disposition, and the refusal leaves every record untouched.

    PRD 3.7: "Then the safety band tests whether the chosen action is legal here at all: `RETURN_TO_PATIENT` is forbidden when the patient's state rule classifies household sharps as `REGULATED_MEDICAL_WASTE`, since mailing regulated waste back to a household is not a disposal option that state recognises; and `DISPOSE_AS_RMW` is forbidden when the receiving facility's `accepted_hazard_classes` does not include `UN3291_REGULATED_MEDICAL_WASTE`, since the facility's permit would not cover the disposal."
    PRD 3.7: "Either violation is refused with `ERR_REMEDIATION_NOT_ALLOWED_FOR_STATE` (HTTP 422)."
    Design: Corner/endpoints/remediation_action_legality_depends_on_patient_state_law_and_facility_hazard_permit
    """
    ctx = _ny_notified_non_conformance(api)
    event = ctx["non_conformance_event"]

    response = api.remediate_non_conformance(
        event["id"],
        remediation_payload("RETURN_TO_PATIENT"),
        make_intake_technician_headers(TECH_ID),
    )
    validate_error(response, "ERR_REMEDIATION_NOT_ALLOWED_FOR_STATE", 422)

    assert_non_conformance_event(
        read_non_conformance_event(api, event["id"]),
        status="CUSTOMER_NOTIFIED",
        reason_code="OVERFILLED_CONTAINER",
        remediation_action=None,
    )
    assert_shipment_axes(
        read_shipment(api, ctx["shipment"]["id"]),
        transport_status="DELIVERED",
        conformance_status="NON_CONFORMING",
    )
    assert_kit(read_kit(api, ctx["kit"]["id"]), status="RECEIVED")
    assert_facility_counters(
        read_treatment_facility(api, ctx["treatment_facility"]["id"]),
        pending_intake_units=60,
    )


def test_06_dispose_as_rmw_is_barred_by_the_receiving_facilitys_permit(api):
    """The second legality gate answers with the very same error code, but for a
    completely different reason: this facility's permit covers sharps only, so it
    may not dispose of the parcel as regulated medical waste.

    PRD 3.7: "Then the safety band tests whether the chosen action is legal here at all: `RETURN_TO_PATIENT` is forbidden when the patient's state rule classifies household sharps as `REGULATED_MEDICAL_WASTE`, since mailing regulated waste back to a household is not a disposal option that state recognises; and `DISPOSE_AS_RMW` is forbidden when the receiving facility's `accepted_hazard_classes` does not include `UN3291_REGULATED_MEDICAL_WASTE`, since the facility's permit would not cover the disposal."
    PRD 3.7: "Either violation is refused with `ERR_REMEDIATION_NOT_ALLOWED_FOR_STATE` (HTTP 422)."
    Design: Corner/endpoints/remediation_action_legality_depends_on_patient_state_law_and_facility_hazard_permit
    """
    ctx = _ny_notified_non_conformance(api)
    event = ctx["non_conformance_event"]
    tech = make_intake_technician_headers(TECH_ID)

    validate_error(
        api.remediate_non_conformance(
            event["id"], remediation_payload("RETURN_TO_PATIENT"), tech
        ),
        "ERR_REMEDIATION_NOT_ALLOWED_FOR_STATE",
        422,
    )
    validate_error(
        api.remediate_non_conformance(
            event["id"], remediation_payload("DISPOSE_AS_RMW"), tech
        ),
        "ERR_REMEDIATION_NOT_ALLOWED_FOR_STATE",
        422,
    )

    assert_non_conformance_event(
        read_non_conformance_event(api, event["id"]),
        status="CUSTOMER_NOTIFIED",
        remediation_action=None,
    )
    assert_shipment_axes(
        read_shipment(api, ctx["shipment"]["id"]), conformance_status="NON_CONFORMING"
    )


def test_07_on_site_repack_resolves_the_event_and_surcharges_the_settlement(api):
    """The one always-legal action is accepted after both illegal ones were
    refused, keeps the waste at the facility, and pushes a 500-cent repacking
    surcharge all the way into the certificate's final settlement.

    PRD 3.7: "`ON_SITE_REPACK` is always legal."
    PRD 3.7: "Whichever action is chosen, the event moves `CUSTOMER_NOTIFIED → RESOLVED` with the chosen `remediation_action` stored, the shipment's conformance axis moves `NON_CONFORMING → REMEDIATED` while `transport_status` stays `DELIVERED`, and both records have their `version` incremented by 1."
    PRD 3.7: "`ON_SITE_REPACK` keeps the waste at the facility: the kit stays `RECEIVED` and remains certifiable, the facility's `pending_intake_units` is unchanged, and a repacking surcharge of 500 cents enters the kit's final settlement."
    PRD 3.8: "The surcharge component is 0 when the shipment carries no resolved remediation action or when the resolved action was `RETURN_TO_PATIENT`, 500 cents when it was `ON_SITE_REPACK`, and 900 cents when it was `DISPOSE_AS_RMW`."
    PRD 3.8: "Its `certificate_number` is the literal text `CERT-`, then the facility's `permit_number`, then a hyphen, then a sequence number zero-padded to five digits, where the sequence number is the facility's `certificates_issued_count` plus one."
    PRD 3.8: "Take the `certificate_retention_years` of the patient's state rule, the `certificate_retention_years` of the facility's state rule, and the federal minimum of 3 years, and use the largest of the three."
    PRD 3.8: "Two ledger entries are appended in a pinned order that must not be swapped: first a `RESERVATION_RELEASE` for the negation of the kit's `provisional_cost_cents`, then, at the immediately following `sequence_no`, a `COMMITMENT` for the positive `final_kit_cost_cents`."
    PRD 3.8: "On the facility, `certificates_issued_count` rises by 1, `pending_intake_units` falls by exactly the shipment's `custody_units`, and `destroyed_units_total` rises by the certificate's `destroyed_units`."
    Design: Corner/endpoints/remediation_action_legality_depends_on_patient_state_law_and_facility_hazard_permit
    """
    ctx = _ny_notified_non_conformance(api)
    event = ctx["non_conformance_event"]
    shipment_id = ctx["shipment"]["id"]
    facility_id = ctx["treatment_facility"]["id"]
    program_id = ctx["sponsorship_program"]["id"]
    tech = make_intake_technician_headers(TECH_ID)

    for illegal_action in ("RETURN_TO_PATIENT", "DISPOSE_AS_RMW"):
        validate_error(
            api.remediate_non_conformance(
                event["id"], remediation_payload(illegal_action), tech
            ),
            "ERR_REMEDIATION_NOT_ALLOWED_FOR_STATE",
            422,
        )

    resolved = validate_success(
        api.remediate_non_conformance(
            event["id"], remediation_payload("ON_SITE_REPACK"), tech
        ),
        200,
    )
    assert_non_conformance_event(
        resolved, status="RESOLVED", remediation_action="ON_SITE_REPACK"
    )
    assert_shipment_axes(
        read_shipment(api, shipment_id),
        transport_status="DELIVERED",
        conformance_status="REMEDIATED",
        custody_units=60,
    )
    assert_kit(read_kit(api, ctx["kit"]["id"]), status="RECEIVED")
    assert_facility_counters(
        read_treatment_facility(api, facility_id), pending_intake_units=60
    )

    certificate = validate_success(
        api.issue_destruction_certificate(
            shipment_id,
            destruction_certificate_payload(60),
            make_destruction_officer_headers(OFFICER_ID),
        ),
        201,
    )
    assert_certificate(
        certificate,
        certificate_number="CERT-NY-TF-0007-00001",
        destroyed_units=60,
        destruction_date="2026-08-01",
        retention_until_date="2029-08-01",
        final_kit_cost_cents=2176,
        rebate_pct_applied=0.00,
        issued_by_user_id=OFFICER_ID,
        status="ISSUED",
    )

    assert_ledger_sequence(
        read_ledger_entries(api, program_id),
        [
            (1, "RESERVATION", 1465),
            (2, "RESERVATION_RELEASE", -1465),
            (3, "COMMITMENT", 2176),
        ],
    )
    assert_program_balances(
        read_program(api, program_id),
        reserved_cents=0,
        committed_cents=2176,
        available_cents=497824,
        status="ACTIVE",
    )
    assert_facility_counters(
        read_treatment_facility(api, facility_id),
        pending_intake_units=0,
        destroyed_units_total=60,
        certificates_issued_count=1,
    )
