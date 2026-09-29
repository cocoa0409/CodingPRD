"""Optimistic concurrency on parent records (PRD 2.5) and the replacement
container checkpoint (PRD 3.9).

Two write operations echo a parent version: kit issuance echoes the enrollment's
and a funding adjustment echoes the program's. The checkpoint is the other
cross-cutting layer exercised here: it refreshes both risk readings of every
patient it touches and skips on the audit reading without ever writing a
patient's status.
"""

import pytest

from test_helpers import (
    acknowledge_kit,
    activate_label_for,
    assert_auto_ship_run,
    assert_enrollment,
    assert_kit,
    assert_ledger_sequence,
    assert_patient_risk,
    assert_program_balances,
    assert_total_count,
    auto_ship_run_payload,
    create_active_enrollment,
    create_eligible_patient,
    create_sponsorship_program,
    deliver_shipment,
    funding_adjustment_payload,
    issue_kit_for,
    kit_issuance_payload,
    make_patient_headers,
    make_program_admin_headers,
    print_label_for,
    read_enrollment,
    read_kit,
    read_ledger_entries,
    read_patient,
    read_program,
    screen_shipment,
    seal_kit_for,
    seal_payload,
    set_clock,
    setup_active_enrollment,
    setup_program_foundations,
    validate_error,
    validate_success,
)

# The clock's startup value (PRD 2.4).
CLOCK_START = "2026-08-01T00:00:00Z"

# A syntactically valid identifier that no enrollment carries.
UNKNOWN_ENROLLMENT_ID = "00000000-0000-4000-8000-00000000ffff"

# The instant the checkpoint runs at: 121 days after the non-conformance event
# and well past both open kits' seal deadlines.
RUN_CLOCK = "2026-11-30T00:00:00Z"
RUN_DATE = "2026-11-30"


def _assert_same_instant(actual: str, expected: str) -> None:
    """Compare two ISO 8601 UTC instants ignoring the fractional-second width."""
    assert actual is not None, "expected an ISO 8601 instant, got None"
    assert actual[:19] == expected[:19], (
        f"Expected the instant {expected}, got {actual}"
    )


def _occ_world(api) -> dict:
    """Northwind's program NW-2026 funded 500000 / 5000, with Dana's enrollment
    ACTIVE, five kits authorized and no kit issued yet."""
    ctx = setup_active_enrollment(
        api,
        clock=CLOCK_START,
        state_rule_overrides={"household_sharps_classification": "HOUSEHOLD_EXEMPT"},
        sponsor_overrides={
            "legal_name": "Northwind Devices Inc",
            "sponsor_type": "MANUFACTURER",
            "contact_email": "programs@northwind.example",
        },
        program_overrides={
            "program_code": "NW-2026",
            "funding_ceiling_cents": 500000,
            "per_kit_allowance_cents": 5000,
        },
        patient_overrides={
            "full_name": "Dana Reyes",
            "weekly_sharps_count": 20,
            "contact_email": "dana@example.com",
        },
        enrollment_overrides={"cadence_days": 30, "kits_authorized": 5},
        with_facility=False,
    )
    program = read_program(api, ctx["sponsorship_program"]["id"])
    enrollment = read_enrollment(api, ctx["enrollment"]["id"])
    return {
        "ctx": ctx,
        "patient": ctx["patient"],
        "program": program,
        "program_version": program["version"],
        "enrollment": enrollment,
        "enrollment_version": enrollment["version"],
    }


# ---------------------------------------------------------------------------
# Rule 1: kit issuance echoes the enrollment's version (PRD 2.5)
# ---------------------------------------------------------------------------
def test_01_a_stale_enrollment_echo_refuses_the_issuance_and_writes_nothing(api):
    """An issuance computed against the version before the current one is refused,
    and neither the kit nor its reservation appears anywhere.

    PRD 2.5: "Issuing a kit under an enrollment requires `expected_enrollment_version` carrying the client's last observed `version` of the target `Enrollment`."
    PRD 2.5: "If that value does not equal the enrollment's current `version`, the request is rejected with `ERR_STALE_ENROLLMENT_VERSION` (HTTP 412) and nothing is written."

    Design: Corner/cross_cutting_complexity_layers/both_occ_rules_reject_stale_parent_versions_and_bump_on_every_write
    """
    world = _occ_world(api)
    enrollment = world["enrollment"]
    program = world["program"]
    admin = make_program_admin_headers()

    response = api.issue_kit(
        enrollment["id"],
        kit_issuance_payload(world["enrollment_version"] - 1),
        admin,
    )

    validate_error(response, "ERR_STALE_ENROLLMENT_VERSION", expected_status=412)
    assert_total_count(api.list_kits(admin, {"enrollment_id": enrollment["id"]}), 0)
    assert_enrollment(
        read_enrollment(api, enrollment["id"]), version=world["enrollment_version"]
    )
    assert_total_count(
        api.list_ledger_entries(admin, {"sponsorship_program_id": program["id"]}), 0
    )
    assert_program_balances(read_program(api, program["id"]), reserved_cents=0)


def test_02_the_fresh_echo_succeeds_and_the_write_bumps_the_enrollment_version(api):
    """The version the enrollment currently carries issues the kit, and replaying
    that very payload is now itself stale — which is only possible if the write
    incremented the enrollment's version.

    PRD 2.5: "If that value does not equal the enrollment's current `version`, the request is rejected with `ERR_STALE_ENROLLMENT_VERSION` (HTTP 412) and nothing is written."
    PRD 2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC instant refreshed on every mutation of that row, and `version`, an integer that begins at 1 when the row is created and increments by exactly 1 on every mutation."
    PRD 3.4: "`provisional_cost_cents` is the base component plus that rounded transport component."

    Design: Corner/cross_cutting_complexity_layers/both_occ_rules_reject_stale_parent_versions_and_bump_on_every_write
    """
    world = _occ_world(api)
    enrollment = world["enrollment"]
    version_1 = world["enrollment_version"]
    admin = make_program_admin_headers()

    accepted = api.issue_kit(
        enrollment["id"], kit_issuance_payload(version_1), admin
    )
    kit = validate_success(accepted, expected_status=201)
    assert_kit(kit, status="ISSUED", provisional_cost_cents=1465)
    assert_enrollment(read_enrollment(api, enrollment["id"]), version=version_1 + 1)

    replayed = api.issue_kit(
        enrollment["id"], kit_issuance_payload(version_1), admin
    )
    validate_error(replayed, "ERR_STALE_ENROLLMENT_VERSION", expected_status=412)


def test_03_the_next_echo_issues_a_replacement_that_supersedes_the_open_kit(api):
    """Echoing the bumped version issues a second kit, which supersede-voids the
    first one and leaves the reservation ledger at three appends in sequence order.

    PRD 3.4: "If the enrollment already holds a kit in `ISSUED` or `ACTIVE_FILLING`, the most recent such kit by creation time is moved to `VOIDED` with `void_reason` set to `SUPERSEDED_BY_REPLACEMENT`, a `RESERVATION_RELEASE` ledger entry for the negation of that prior kit's `provisional_cost_cents` is appended at the next `sequence_no`, and the program's `reserved_cents` falls by that amount."
    PRD 2.9: "Each entry also carries a `sequence_no`, a per-program monotonic counter starting at 1, which pins the relative order of appends made in the same request or at the same clock instant; ledger listings are returned in `sequence_no` ascending order."

    Design: Corner/cross_cutting_complexity_layers/both_occ_rules_reject_stale_parent_versions_and_bump_on_every_write
    """
    world = _occ_world(api)
    enrollment = world["enrollment"]
    program = world["program"]
    version_1 = world["enrollment_version"]
    admin = make_program_admin_headers()

    first = validate_success(
        api.issue_kit(enrollment["id"], kit_issuance_payload(version_1), admin),
        expected_status=201,
    )
    second = validate_success(
        api.issue_kit(enrollment["id"], kit_issuance_payload(version_1 + 1), admin),
        expected_status=201,
    )

    assert_kit(read_kit(api, first["id"]), status="VOIDED")
    assert_kit(second, status="ISSUED", provisional_cost_cents=1465)
    assert_ledger_sequence(
        read_ledger_entries(api, program["id"]),
        [
            (1, "RESERVATION", 1465),
            (2, "RESERVATION_RELEASE", -1465),
            (3, "RESERVATION", 1465),
        ],
    )
    assert_program_balances(read_program(api, program["id"]), reserved_cents=1465)


def test_04_an_unknown_enrollment_outranks_the_stale_version_echo(api):
    """The same stale payload aimed at an identifier that matches no enrollment is
    a 404, because existence is settled before the version echo is consulted.

    PRD 2.6: "Each entity type has its own 404 code: `ERR_STATE_RULE_NOT_FOUND`, `ERR_PACKAGING_SPEC_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_SPONSOR_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_KIT_NOT_FOUND`, `ERR_LABEL_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_NONCONFORMANCE_EVENT_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, `ERR_LEDGER_ENTRY_NOT_FOUND` and `ERR_AUTOSHIP_RUN_NOT_FOUND`, each returning HTTP 404."
    PRD 2.6: "The bands are, in order: header validity (`ERR_UNAUTHENTICATED`), role membership (`ERR_ROLE_NOT_PERMITTED`), request shape (`ERR_INVALID_REQUEST`), existence of referenced records (the 404 family above), resource ownership (`ERR_NOT_RESOURCE_OWNER`), state preconditions on the target record, optimistic-concurrency version echoes, and then the four business bands."

    Design: Corner/cross_cutting_complexity_layers/both_occ_rules_reject_stale_parent_versions_and_bump_on_every_write
    """
    world = _occ_world(api)

    response = api.issue_kit(
        UNKNOWN_ENROLLMENT_ID,
        kit_issuance_payload(world["enrollment_version"] - 1),
        make_program_admin_headers(),
    )

    validate_error(response, "ERR_ENROLLMENT_NOT_FOUND", expected_status=404)


# ---------------------------------------------------------------------------
# Rule 2: funding adjustments echo the program's version (PRD 2.5)
# ---------------------------------------------------------------------------
def test_05_a_stale_program_echo_refuses_the_funding_adjustment(api):
    """An adjustment computed against a superseded program version is refused, and
    neither the ceiling nor the ledger moves.

    PRD 2.5: "Adjusting a program's funding ceiling requires `expected_program_version` carrying the client's last observed `version` of the target `SponsorshipProgram`."
    PRD 2.5: "A mismatch with the program's current `version` is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/both_occ_rules_reject_stale_parent_versions_and_bump_on_every_write
    """
    world = _occ_world(api)
    program = world["program"]
    admin = make_program_admin_headers()

    response = api.create_funding_adjustment(
        program["id"],
        funding_adjustment_payload(1000, world["program_version"] - 1, memo="top-up"),
        admin,
    )

    validate_error(response, "ERR_STALE_PROGRAM_VERSION", expected_status=412)
    assert_program_balances(
        read_program(api, program["id"]), funding_ceiling_cents=500000
    )
    assert_ledger_sequence(read_ledger_entries(api, program["id"]), [])


def test_06_the_fresh_program_echo_moves_the_ceiling_and_burns_that_version(api):
    """The adjustment lands on the current version, and the identical replay is
    stale because the successful write incremented the program's version by one.

    PRD 3.2: "A successful adjustment appends a `FUNDING_ADJUSTMENT` ledger entry whose `amount_cents` is the submitted `delta_cents` signed exactly as submitted, whose `kit_id` is null, whose `memo` is copied from the request, and whose three after-balances are snapshotted; it then recomputes `available_cents`, flips the program between `EXHAUSTED` and `ACTIVE` if the recomputed figure crosses zero, and increments the program's `version` by 1."
    PRD 2.5: "A mismatch with the program's current `version` is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/both_occ_rules_reject_stale_parent_versions_and_bump_on_every_write
    """
    world = _occ_world(api)
    program = world["program"]
    version_1 = world["program_version"]
    admin = make_program_admin_headers()
    payload = funding_adjustment_payload(1000, version_1, memo="top-up")

    accepted = api.create_funding_adjustment(program["id"], payload, admin)
    updated = validate_success(accepted, expected_status=200)
    assert_program_balances(updated, funding_ceiling_cents=501000)
    assert updated["version"] == version_1 + 1, (
        f"Expected program version {version_1 + 1}, got {updated['version']}"
    )
    assert_ledger_sequence(
        read_ledger_entries(api, program["id"]), [(1, "FUNDING_ADJUSTMENT", 1000)]
    )

    replayed = api.create_funding_adjustment(program["id"], payload, admin)
    validate_error(replayed, "ERR_STALE_PROGRAM_VERSION", expected_status=412)
    assert_program_balances(
        read_program(api, program["id"]), funding_ceiling_cents=501000
    )
    assert_ledger_sequence(
        read_ledger_entries(api, program["id"]), [(1, "FUNDING_ADJUSTMENT", 1000)]
    )


def test_07_an_unguarded_write_does_not_honour_a_version_echo(api):
    """Sealing is not one of the two guarded writes, so a version element smuggled
    into its payload is neither required nor consulted: the seal lands normally.

    PRD 2.5: "No other endpoint accepts a version field."
    PRD 2.5: "Endpoints not named in this subsection must not require, and must not honour, an `expected_..._version` element."
    PRD 3.5: "On success the kit moves `ACTIVE_FILLING → SEALED`, both declared values are stored on the kit, and the kit's `version` is incremented by 1."

    Design: Corner/cross_cutting_complexity_layers/both_occ_rules_reject_stale_parent_versions_and_bump_on_every_write
    """
    world = _occ_world(api)
    ctx = world["ctx"]
    admin = make_program_admin_headers()
    kit = validate_success(
        api.issue_kit(
            world["enrollment"]["id"],
            kit_issuance_payload(world["enrollment_version"]),
            admin,
        ),
        expected_status=201,
    )
    ctx["kit"] = kit
    acknowledge_kit(api, ctx)

    response = api.seal_kit(
        kit["id"],
        seal_payload(69, 1400, expected_kit_version=999),
        make_patient_headers(world["patient"]["id"]),
    )

    sealed = validate_success(response, expected_status=200)
    assert_kit(sealed, status="SEALED", fill_units=69)


def test_08_a_guarded_write_still_requires_its_version_echo(api):
    """The version element is mandatory on the two guarded writes: an issuance that
    omits `expected_enrollment_version` is a malformed request, not a default.

    PRD 2.5: "In both cases the version field is a required, non-optional element of the request body, and a mismatch is a rejection rather than a retry."
    PRD 2.6: "The bands are, in order: header validity (`ERR_UNAUTHENTICATED`), role membership (`ERR_ROLE_NOT_PERMITTED`), request shape (`ERR_INVALID_REQUEST`), existence of referenced records (the 404 family above), resource ownership (`ERR_NOT_RESOURCE_OWNER`), state preconditions on the target record, optimistic-concurrency version echoes, and then the four business bands."

    Design: Corner/cross_cutting_complexity_layers/both_occ_rules_reject_stale_parent_versions_and_bump_on_every_write
    """
    world = _occ_world(api)
    admin = make_program_admin_headers()

    issuance = api.issue_kit(world["enrollment"]["id"], {}, admin)
    validate_error(issuance, "ERR_INVALID_REQUEST", expected_status=400)

    adjustment = api.create_funding_adjustment(
        world["program"]["id"], {"delta_cents": 1000}, admin
    )
    validate_error(adjustment, "ERR_INVALID_REQUEST", expected_status=400)

    assert_total_count(
        api.list_kits(admin, {"enrollment_id": world["enrollment"]["id"]}), 0
    )
    assert_program_balances(
        read_program(api, world["program"]["id"]), funding_ceiling_cents=500000
    )


# ---------------------------------------------------------------------------
# The replacement-container checkpoint: both risk readings, one skip rung
# ---------------------------------------------------------------------------
def _autoship_risk_world(api) -> dict:
    """Dana holds two ACTIVE enrollments under the same sponsor, one open
    non-conformance event 121 days old, and two kits still unsealed past their
    seal deadline. At the closing clock instant her decayed screening reading has
    fallen well under the threshold while her undecayed audit reading, inflated by
    the two late kits, stands above it.

    Programs NW-A and NW-B are each funded 500000 with a 5000-cent per-kit
    allowance. Enrollment A is created first, on 2026-08-01; enrollment B follows
    on 2026-08-02, which is legal because the duplicate-enrollment rule keys on
    the (patient, program) pair.
    """
    ctx = setup_program_foundations(
        api,
        clock=CLOCK_START,
        state_rule_overrides={"household_sharps_classification": "HOUSEHOLD_EXEMPT"},
        packaging_spec_overrides={
            "spec_code": "MB-USPS",
            "max_gross_weight_grams": 8000,
            "allowed_container_sizes": ["ONE_QUART", "TWO_GALLON"],
        },
        facility_overrides={"daily_intake_capacity_units": 200},
        sponsor_overrides={
            "legal_name": "Northwind Devices Inc",
            "sponsor_type": "MANUFACTURER",
            "contact_email": "programs@northwind.example",
        },
        program_overrides={
            "program_code": "NW-A",
            "funding_ceiling_cents": 500000,
            "per_kit_allowance_cents": 5000,
        },
    )
    program_a = ctx["sponsorship_program"]
    program_b = create_sponsorship_program(
        api,
        ctx["sponsor"]["id"],
        program_code="NW-B",
        funding_ceiling_cents=500000,
        per_kit_allowance_cents=5000,
    )
    patient = create_eligible_patient(
        api,
        ctx["state_rule"]["id"],
        full_name="Dana Reyes",
        weekly_sharps_count=20,
        contact_email="dana@example.com",
    )
    ctx["patient"] = patient

    enrollment_a = create_active_enrollment(
        api,
        patient["id"],
        program_a["id"],
        ctx["sponsor"]["id"],
        cadence_days=30,
        kits_authorized=5,
    )
    ctx["enrollment"] = enrollment_a

    # Kit A1 runs the whole route on 2026-08-01 and is rejected at intake, which
    # opens one non-conformance event weighing 45 at that instant.
    kit_a1 = issue_kit_for(api, ctx, enrollment=enrollment_a)
    acknowledge_kit(api, ctx)
    seal_kit_for(api, ctx, fill_units=60, sealed_gross_weight_grams=1200)
    print_label_for(api, ctx)
    activate_label_for(
        api,
        ctx,
        scheduled_intake_date="2026-08-05",
        declared_gross_weight_grams=1200,
    )
    deliver_shipment(api, ctx)
    screen_shipment(
        api,
        ctx,
        outcome="NON_CONFORMING",
        observed_gross_weight_grams=1200,
        reason_code="LOOSE_SHARPS_IN_BOX",
        technician_user_id="tech-77",
    )

    # A day later two fresh kits go out and are simply never sealed.
    set_clock(api, "2026-08-02T00:00:00Z")
    kit_a2 = issue_kit_for(api, ctx, enrollment=enrollment_a)
    enrollment_b = create_active_enrollment(
        api,
        patient["id"],
        program_b["id"],
        ctx["sponsor"]["id"],
        cadence_days=30,
        kits_authorized=5,
    )
    kit_b1 = issue_kit_for(api, ctx, enrollment=enrollment_b)

    set_clock(api, RUN_CLOCK)
    return {
        "patient": patient,
        "program_a": program_a,
        "program_b": program_b,
        "enrollment_a": enrollment_a,
        "enrollment_b": enrollment_b,
        "kit_a1": kit_a1,
        "kit_a2": kit_a2,
        "kit_b1": kit_b1,
    }


def test_09_the_run_skips_both_enrollments_at_the_risk_rung(api):
    """Risk is the second rung of the skip order, so it claims both enrollments
    before the unfilled rung ever looks at their two open kits, and the run mints
    nothing at all while still recording itself as a success.

    PRD 3.9: "A `ProgramAdmin` runs the replacement-container checkpoint, optionally supplying an `as_of_date` against which due dates are evaluated; when omitted it defaults to the logical clock's UTC date."
    PRD 3.9: "The run records its own `run_at` as the logical-clock instant at which it executed."
    PRD 3.9: "The count of enrollments inspected is recorded as `enrollments_evaluated`."
    PRD 3.9: "Second, **risk**: if the patient's refreshed `audit_risk_score` is at least 60, `kits_skipped_risk` rises by 1."
    PRD 3.9: "A run that issues no kits at all is still a success: it returns a created run record with its counters at whatever values the walk produced."

    Design: Corner/cross_cutting_complexity_layers/ops_run_refreshes_both_risk_variants_and_skips_on_audit_without_ever_suspending
    """
    _autoship_risk_world(api)
    admin = make_program_admin_headers()

    response = api.create_auto_ship_run(auto_ship_run_payload(), admin)

    run = validate_success(response, expected_status=201)
    _assert_same_instant(run["run_at"], RUN_CLOCK)
    assert_auto_ship_run(
        run,
        as_of_date=RUN_DATE,
        enrollments_evaluated=2,
        kits_created=0,
        created_kit_ids=[],
        kits_skipped_risk=2,
    )
    assert run["kits_skipped_not_due"] == 0, (
        f"Both due dates are behind {RUN_DATE}, so nothing may skip as not due; "
        f"got {run['kits_skipped_not_due']}"
    )
    assert run["kits_skipped_unfilled"] == 0, (
        "Risk fires ahead of the unfilled rung, so the unfilled counter must stay "
        f"at 0; got {run['kits_skipped_unfilled']}"
    )
    assert run["kits_skipped_funding"] == 0, (
        "Risk fires ahead of the funding rung, so the funding counter must stay "
        f"at 0; got {run['kits_skipped_funding']}"
    )

    rows, _ = assert_total_count(api.list_auto_ship_runs(admin), 1)
    assert_auto_ship_run(rows[0], kits_skipped_risk=2)


def test_10_the_run_rewrites_both_risk_readings_without_touching_patient_status(api):
    """The same event history yields two different integers — the decayed screening
    reading and the undecayed audit reading inflated by two late kits — and the
    audit reading sitting above the threshold still writes nothing to the patient.

    PRD 3.9: "Both readings — `screening_risk_score` and `audit_risk_score` — are recomputed and stored for every patient who holds at least one enrollment whose status is not `REJECTED` and not `TERMINATED`."
    PRD 3.9: "An event aged at most 90 days contributes its full weight; an event aged from 91 through 180 days inclusive contributes half its weight; an event aged more than 180 days contributes nothing."
    PRD 3.9: "The discounted contributions are summed **exactly**, keeping halves intact, and the single total is then rounded half up to a whole number; the result is capped at 100."
    PRD 3.9: "Added to that sum is a penalty of 10 points for each **late kit**, where a late kit is one of the patient's kits still in `ISSUED` or `ACTIVE_FILLING` whose `seal_deadline_date` falls strictly before the current logical-clock UTC date."
    PRD 3.9: "This step never writes a patient's `status`, so no suspension can originate inside a run even if a refreshed `screening_risk_score` lands above the threshold."
    PRD 3.3: "A new patient begins at `PENDING_ELIGIBILITY` with `screening_risk_score` at 0, `audit_risk_score` at 0 and `suspended_at` null."

    Design: Corner/cross_cutting_complexity_layers/ops_run_refreshes_both_risk_variants_and_skips_on_audit_without_ever_suspending
    """
    world = _autoship_risk_world(api)
    admin = make_program_admin_headers()

    validate_success(
        api.create_auto_ship_run(auto_ship_run_payload(), admin), expected_status=201
    )

    assert_patient_risk(
        read_patient(api, world["patient"]["id"]),
        screening_risk_score=23,
        audit_risk_score=65,
        status="ENROLLED",
        suspended_at=None,
    )


@pytest.mark.parametrize("enrollment_key,kit_key", [("enrollment_a", "kit_a2"), ("enrollment_b", "kit_b1")])
def test_11_a_skipped_enrollment_keeps_its_due_date_and_its_open_kit(api, enrollment_key, kit_key):
    """A skipped enrollment is left exactly as the walk found it: still `ACTIVE`,
    its due date not advanced, and its unsealed kit not voided — the run never ran
    the suspension cascade that would have paused it.

    PRD 3.9: "After the kit is minted, the enrollment's `next_autoship_due_date` is set to the run's `as_of_date` advanced by the enrollment's `cadence_days`, `kits_created` rises by 1, and the new kit's id is appended to `created_kit_ids`, which therefore lists ids in processing order."
    PRD 3.9: "When an auto-ship run finds `audit_risk_score` at 60 or above, the run merely skips that enrollment and never writes the patient's `status` at all."
    PRD 3.9: "The third hop applies to each of those newly paused enrollments: its `next_autoship_due_date` is cleared to null, and every kit of that enrollment whose status is `ISSUED` moves to `VOIDED` with `void_reason` set to `ENROLLMENT_PAUSED` — kits already in `ACTIVE_FILLING` are physically in the patient's hands and are pointedly **not** voided."

    Design: Corner/cross_cutting_complexity_layers/ops_run_refreshes_both_risk_variants_and_skips_on_audit_without_ever_suspending
    """
    world = _autoship_risk_world(api)
    admin = make_program_admin_headers()

    validate_success(
        api.create_auto_ship_run(auto_ship_run_payload(), admin), expected_status=201
    )

    assert_enrollment(
        read_enrollment(api, world[enrollment_key]["id"]),
        status="ACTIVE",
        next_autoship_due_date="2026-09-01",
    )
    assert_kit(read_kit(api, world[kit_key]["id"]), status="ISSUED", void_reason=None)


def test_12_no_reservation_is_released_by_a_run_that_issued_nothing(api):
    """The money is untouched on both programs: two reservations stand against
    NW-A and one against NW-B, and the kit already back at the facility is still
    `RECEIVED`.

    PRD 3.9: "A run that issues no kits at all is still a success: it returns a created run record with its counters at whatever values the walk produced."
    PRD 3.4: "*Third*, a `RESERVATION` ledger entry for the positive `provisional_cost_cents` is appended at the next `sequence_no` and the program's `reserved_cents` rises by that amount."
    PRD 3.9: "The fourth hop applies to each kit just voided: a `RESERVATION_RELEASE` ledger entry for the negation of that kit's `provisional_cost_cents` is appended and the program's `reserved_cents` falls by that amount."

    Design: Corner/cross_cutting_complexity_layers/ops_run_refreshes_both_risk_variants_and_skips_on_audit_without_ever_suspending
    """
    world = _autoship_risk_world(api)
    admin = make_program_admin_headers()

    validate_success(
        api.create_auto_ship_run(auto_ship_run_payload(), admin), expected_status=201
    )

    assert_program_balances(
        read_program(api, world["program_a"]["id"]), reserved_cents=2930
    )
    assert_ledger_sequence(
        read_ledger_entries(api, world["program_a"]["id"]),
        [(1, "RESERVATION", 1465), (2, "RESERVATION", 1465)],
    )
    assert_program_balances(
        read_program(api, world["program_b"]["id"]), reserved_cents=1465
    )
    assert_ledger_sequence(
        read_ledger_entries(api, world["program_b"]["id"]),
        [(1, "RESERVATION", 1465)],
    )
    assert_kit(read_kit(api, world["kit_a1"]["id"]), status="RECEIVED")
