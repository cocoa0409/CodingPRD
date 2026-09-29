"""Record shapes of the home-sharps mail-back program: what a creation echoes
back, which fields the server derives, which system fields it stamps, and which
two records are append-only.

Every test builds its own state from an empty database through the program's own
endpoints, and pins the logical clock so that every instant and every derived
calendar date is reproducible.
"""

from datetime import datetime

from test_helpers import (
    OMIT,
    assert_append_only_system_fields,
    assert_auto_ship_run,
    assert_calendar_date,
    assert_enrollment,
    assert_facility_counters,
    assert_kit,
    assert_ledger_entry,
    assert_patient_risk,
    assert_program_balances,
    assert_system_fields,
    auto_ship_run_payload,
    create_eligible_patient,
    create_draft_enrollment,
    create_packaging_spec,
    create_sponsor,
    create_sponsorship_program,
    create_state_rule,
    create_treatment_facility,
    funding_adjustment_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    issue_kit_for,
    kit_issuance_payload,
    make_sponsor_representative_headers,
    read_enrollment,
    read_enrollment_version,
    read_ledger_entries,
    read_program,
    set_clock,
    setup_active_enrollment,
    setup_program_foundations,
    state_rule_payload,
    validate_success,
)

CLOCK_AT_CREATION = "2026-08-01T00:00:00Z"
CLOCK_AFTER_ADVANCE = "2026-08-05T09:30:00Z"

# The sizing inputs shared by every kit-issuance test in this module: a CA
# household generator on INSULIN_PEN_NEEDLES at 20 sharps per week, enrolled on a
# 30-day cadence against a program funded at 500000 cents with a 5000-cent
# per-kit allowance.
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
# Seeding one state's household-sharps rule
# ==========================================================================
def test_01_state_rule_creation_echoes_every_declared_field(api, program_admin_headers):
    """A single POST carrying all seven declared inputs comes back as HTTP 201
    with every one of them echoed on the created rule.

    PRD 3.1: "Registration takes a `state_code` — exactly two uppercase letters, and no two state rules may share one, a duplicate being refused with `ERR_DUPLICATE_STATE_RULE` — together with the state's `household_sharps_classification`, its `mail_back_permitted` flag, a `max_container_volume_liters` figure that must be greater than zero, and a `certificate_retention_years` value that must be a whole number from 0 through 30 inclusive."
    PRD 3.1: "Two further fields are optional and carry defaults: `requires_state_manifest` defaults to false, and `notification_deadline_hours` defaults to 72 and must, when supplied, be a whole number from 1 through 720 inclusive."
    PRD 4: "Endpoints that mint a new resource return HTTP 201 with the created resource in `data`; endpoints that modify an existing resource return HTTP 200 with the updated resource in `data`, as do all read endpoints."
    Design: Corner/entities/state_rule_creation_returns_201_with_every_declared_field_echoed
    """
    set_clock(api, CLOCK_AT_CREATION)

    payload = state_rule_payload(
        state_code="CA",
        household_sharps_classification="CONDITIONALLY_EXEMPT",
        mail_back_permitted=True,
        max_container_volume_liters=30.3,
        certificate_retention_years=5,
        requires_state_manifest=True,
        notification_deadline_hours=48,
    )
    rule = validate_success(api.create_state_rule(payload, program_admin_headers), 201)

    assert rule["state_code"] == "CA"
    assert rule["household_sharps_classification"] == "CONDITIONALLY_EXEMPT"
    assert rule["mail_back_permitted"] is True
    assert rule["max_container_volume_liters"] == 30.3
    assert rule["certificate_retention_years"] == 5
    assert rule["requires_state_manifest"] is True
    assert rule["notification_deadline_hours"] == 48


def test_02_state_rule_creation_stamps_system_fields_from_the_logical_clock(
    api, program_admin_headers
):
    """The created rule carries a server-minted UUID, `version` 1 and both
    timestamps read from the logical clock rather than from wall-clock time.

    PRD 2.4: "Every persisted resource carries an `id` that is a server-minted UUID."
    PRD 2.4: "Every resource also carries a `created_at` timestamp: an ISO 8601 UTC instant with three fractional-second digits, read from the logical clock at the moment the row was minted."
    PRD 2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC instant refreshed on every mutation of that row, and `version`, an integer that begins at 1 when the row is created and increments by exactly 1 on every mutation."
    Design: Corner/entities/state_rule_creation_returns_201_with_every_declared_field_echoed
    """
    set_clock(api, CLOCK_AT_CREATION)

    payload = state_rule_payload(
        state_code="CA",
        household_sharps_classification="CONDITIONALLY_EXEMPT",
        mail_back_permitted=True,
        max_container_volume_liters=30.3,
        certificate_retention_years=5,
        requires_state_manifest=True,
        notification_deadline_hours=48,
    )
    rule = validate_success(api.create_state_rule(payload, program_admin_headers), 201)

    assert_system_fields(rule, expected_version=1)
    assert is_valid_uuid(rule["id"]), f"id must be a server-minted UUID: {rule['id']!r}"
    _assert_instant(rule["created_at"], CLOCK_AT_CREATION, "created_at")
    _assert_instant(rule["updated_at"], CLOCK_AT_CREATION, "updated_at")


# ==========================================================================
# Reading back a registered household sharps generator
# ==========================================================================
def test_03_patient_read_returns_the_registered_household_generator_fields(
    api, program_admin_headers
):
    """GET on a patient returns exactly what registration stored.

    PRD 3.3: "Registering a household sharps generator captures the patient's `full_name`, the `state_rule_id` of their residence state, their `therapy_type`, a self-reported `weekly_sharps_count` that must be a whole number from 1 through 500 inclusive, and a `contact_email` — the address that will be used if their waste is ever rejected and a customer notification becomes due."
    Design: Corner/entities/patient_retrieval_returns_stored_row_with_zeroed_risk_fields
    """
    set_clock(api, CLOCK_AT_CREATION)
    rule = create_state_rule(
        api,
        state_code="CA",
        household_sharps_classification="HOUSEHOLD_EXEMPT",
        mail_back_permitted=True,
        max_container_volume_liters=30.3,
        certificate_retention_years=3,
    )
    created = validate_success(
        api.create_patient(
            {
                "full_name": "Dana Reyes",
                "state_rule_id": rule["id"],
                "therapy_type": "INSULIN_PEN_NEEDLES",
                "weekly_sharps_count": 20,
                "contact_email": "dana@example.com",
            },
            program_admin_headers,
        ),
        201,
    )

    patient = validate_success(
        api.get_patient(
            created["id"], program_admin_headers
        )
    )
    assert patient["id"] == created["id"]
    assert patient["full_name"] == "Dana Reyes"
    assert patient["state_rule_id"] == rule["id"]
    assert patient["therapy_type"] == "INSULIN_PEN_NEEDLES"
    assert patient["weekly_sharps_count"] == 20
    assert patient["contact_email"] == "dana@example.com"


def test_04_patient_read_returns_zeroed_risk_scores_and_pending_eligibility(
    api, program_admin_headers
):
    """A patient with no non-conformance history reads back at
    `PENDING_ELIGIBILITY` with both risk scores at 0 and `suspended_at` null.

    PRD 3.3: "A new patient begins at `PENDING_ELIGIBILITY` with `screening_risk_score` at 0, `audit_risk_score` at 0 and `suspended_at` null."
    PRD 3.3: "Patients can be listed and filtered by `state_rule_id` or `status`, and retrieving one returns both risk scores."
    Design: Corner/entities/patient_retrieval_returns_stored_row_with_zeroed_risk_fields
    """
    set_clock(api, CLOCK_AT_CREATION)
    rule = create_state_rule(
        api,
        state_code="CA",
        household_sharps_classification="HOUSEHOLD_EXEMPT",
        mail_back_permitted=True,
        max_container_volume_liters=30.3,
        certificate_retention_years=3,
    )
    created = validate_success(
        api.create_patient(
            {
                "full_name": "Dana Reyes",
                "state_rule_id": rule["id"],
                "therapy_type": "INSULIN_PEN_NEEDLES",
                "weekly_sharps_count": 20,
                "contact_email": "dana@example.com",
            },
            program_admin_headers,
        ),
        201,
    )

    patient = validate_success(
        api.get_patient(
            created["id"], program_admin_headers
        )
    )
    assert_patient_risk(
        patient,
        screening_risk_score=0,
        audit_risk_score=0,
        status="PENDING_ELIGIBILITY",
        suspended_at=None,
    )
    assert_system_fields(patient, expected_version=1)


# ==========================================================================
# Omitted optional inputs fall back to the declared defaults
# ==========================================================================
def test_05_state_rule_optional_inputs_default_to_no_manifest_and_seventy_two_hours(
    api,
):
    """A state rule registered without `requires_state_manifest` or
    `notification_deadline_hours` lands on false and 72.

    PRD 3.1: "Two further fields are optional and carry defaults: `requires_state_manifest` defaults to false, and `notification_deadline_hours` defaults to 72 and must, when supplied, be a whole number from 1 through 720 inclusive."
    Design: Corner/entities/omitted_optional_inputs_fall_back_to_declared_defaults
    """
    set_clock(api, CLOCK_AT_CREATION)

    rule = create_state_rule(
        api,
        state_code="OR",
        household_sharps_classification="HOUSEHOLD_EXEMPT",
        mail_back_permitted=True,
        max_container_volume_liters=11.4,
        certificate_retention_years=3,
        requires_state_manifest=OMIT,
        notification_deadline_hours=OMIT,
    )

    assert rule["requires_state_manifest"] is False
    assert rule["notification_deadline_hours"] == 72


def test_06_packaging_spec_optional_inputs_default_to_no_absorbent_and_active(api):
    """A packaging specification registered without `requires_absorbent` or
    `status` lands on false and `ACTIVE`.

    PRD 3.1: "Whether absorbent material must be declared when the label is activated is carried by `requires_absorbent`, which defaults to false."
    PRD 3.1: "Finally `status` is `ACTIVE` or `RETIRED` and defaults to `ACTIVE`; a `RETIRED` specification remains readable and remains pinned to labels already printed against it, but may not back a new one."
    Design: Corner/entities/omitted_optional_inputs_fall_back_to_declared_defaults
    """
    set_clock(api, CLOCK_AT_CREATION)

    spec = create_packaging_spec(
        api,
        spec_code="PS-D",
        un_specification_code="UN 4G/X7.5/S/26",
        postal_service="USPS_PARCEL_SELECT_MAILBACK",
        hazard_class="UN3291_SHARPS_ONLY",
        max_gross_weight_grams=7500,
        allowed_container_sizes=["ONE_QUART", "TWO_GALLON"],
        requires_absorbent=OMIT,
        status=OMIT,
    )

    assert spec["requires_absorbent"] is False
    assert spec["status"] == "ACTIVE"


def test_07_treatment_facility_defaults_to_active_with_zeroed_counters(api):
    """A facility registered without `status` lands on `ACTIVE`, and its three
    custody and destruction counters all initialise to 0.

    PRD 3.1: "Registration also initialises three counters to 0: `pending_intake_units`, which tracks the units currently inside the facility's custody chain; `destroyed_units_total`, the lifetime units destroyed under certificates that have not been voided; and `certificates_issued_count`, the count of certificates ever minted at the facility including voided ones, which drives the certificate numbering sequence."
    PRD 3.1: "`status` is `ACTIVE` or `SUSPENDED` and defaults to `ACTIVE`."
    Design: Corner/entities/omitted_optional_inputs_fall_back_to_declared_defaults
    """
    set_clock(api, CLOCK_AT_CREATION)
    rule = create_state_rule(
        api,
        state_code="CA",
        household_sharps_classification="HOUSEHOLD_EXEMPT",
        mail_back_permitted=True,
        max_container_volume_liters=30.3,
        certificate_retention_years=3,
    )

    facility = create_treatment_facility(
        api,
        rule["id"],
        name="Valley Sharps Treatment",
        permit_number="CA-TF-0001",
        accepted_hazard_classes=["UN3291_SHARPS_ONLY"],
        daily_intake_capacity_units=1000,
        status=OMIT,
    )

    assert_facility_counters(
        facility,
        pending_intake_units=0,
        destroyed_units_total=0,
        certificates_issued_count=0,
        status="ACTIVE",
    )


def test_08_sponsor_status_defaults_to_active(api):
    """A sponsor registered without the optional `status` lands on `ACTIVE`.

    PRD 3.2: "Registration records the sponsor's `legal_name`, a `sponsor_type` of either `MANUFACTURER` or `HEALTH_PLAN`, a program `contact_email`, and an optional `status` of `ACTIVE` or `SUSPENDED` defaulting to `ACTIVE`."
    Design: Corner/entities/omitted_optional_inputs_fall_back_to_declared_defaults
    """
    set_clock(api, CLOCK_AT_CREATION)

    sponsor = create_sponsor(
        api,
        legal_name="Cascade Health Plan",
        sponsor_type="HEALTH_PLAN",
        contact_email="sharps@cascade.example",
        status=OMIT,
    )

    assert sponsor["status"] == "ACTIVE"
    assert sponsor["sponsor_type"] == "HEALTH_PLAN"


def test_09_draft_enrollment_starts_with_null_container_size_and_null_due_date(api):
    """An enrollment created without `requested_container_size` starts at `DRAFT`
    with that field null alongside the other declared initial values.

    PRD 3.3: "The payload names the `patient_id` and the `sponsorship_program_id`, sets a `cadence_days` figure that must be a whole number from 14 through 180 inclusive, sets `kits_authorized` — a whole number from 1 through 24 inclusive capping the number of non-voided kits the enrollment may ever hold — and may optionally record a `requested_container_size` drawn from `ONE_QUART`, `TWO_GALLON`, `THREE_GALLON` and `EIGHT_GALLON`, which defaults to null."
    PRD 3.3: "The new enrollment starts at `DRAFT` with `kits_issued` at 0, `next_autoship_due_date` null, `activated_at` null, `sponsor_decision_note` null and `version` at 1."
    Design: Corner/entities/omitted_optional_inputs_fall_back_to_declared_defaults
    """
    ctx = setup_program_foundations(
        api,
        clock=CLOCK_AT_CREATION,
        state_rule_overrides=STATE_RULE_OVERRIDES,
        program_overrides=PROGRAM_OVERRIDES,
    )
    patient = create_eligible_patient(api, ctx["state_rule"]["id"], **PATIENT_OVERRIDES)

    enrollment = create_draft_enrollment(
        api,
        patient["id"],
        ctx["sponsorship_program"]["id"],
        cadence_days=30,
        kits_authorized=3,
    )

    assert enrollment["requested_container_size"] is None
    assert_enrollment(
        enrollment,
        status="DRAFT",
        kits_issued=0,
        next_autoship_due_date=None,
        activated_at=None,
        sponsor_decision_note=None,
        version=1,
    )


# ==========================================================================
# Issuance derives sizing, cost and the seal deadline from four inputs
# ==========================================================================
def _issue_one_kit(api, headers):
    """Seed Dana's 20-sharps-a-week INSULIN_PEN_NEEDLES enrollment on a 30-day
    cadence and issue her first kit, whose body carries only the version echo."""
    ctx = setup_active_enrollment(
        api,
        clock=CLOCK_AT_CREATION,
        state_rule_overrides=STATE_RULE_OVERRIDES,
        program_overrides=PROGRAM_OVERRIDES,
        patient_overrides=PATIENT_OVERRIDES,
        enrollment_overrides=ENROLLMENT_OVERRIDES,
    )
    version = read_enrollment_version(api, ctx["enrollment"]["id"])
    kit = validate_success(
        api.issue_kit(
            ctx["enrollment"]["id"], kit_issuance_payload(version), headers
        ),
        201,
    )
    return ctx, kit


def test_10_issuance_sizes_the_container_from_weekly_count_factor_and_cadence(
    api, logistics_coordinator_headers
):
    """20 pen needles a week at factor 1 over a 30-day cadence needs 99 units,
    which the catalogue satisfies with the ONE_QUART row.

    PRD 3.4: "The computation multiplies the weekly count by that factor, then by the number of cadence days, then by 115, divides the product by 700, and rounds the single resulting quotient up to the next whole number."
    PRD 3.4: "The per-item factor counts how many catalogue units one discarded item consumes: an insulin pen needle counts as 1 unit, an insulin syringe as 2, an autoinjector pen as 6, an infusion set as 9, and a lancet as 1."
    PRD 3.4: "`ONE_QUART` holds 0.9 litres, 100 units, and costs 1450 cents."
    PRD 3.4: "Among the candidates the server picks the first one after ordering by capacity ascending, then by volume ascending, then by size-code name in ascending alphabetical order; no random or clock-dependent value participates in that ordering, so the selection is fully reproducible."
    Design: Corner/entities/kit_issuance_computes_sizing_cost_and_seal_deadline_fields
    """
    _ctx, kit = _issue_one_kit(api, logistics_coordinator_headers)

    assert_kit(
        kit,
        required_units=99,
        container_size="ONE_QUART",
        capacity_units=100,
        volume_liters=0.9,
    )


def test_11_issuance_prices_the_kit_at_catalogue_base_plus_estimated_transport(
    api, logistics_coordinator_headers
):
    """The ONE_QUART base of 1450 cents plus a transport estimate of 15 cents
    on 100 capacity units gives `provisional_cost_cents` 1465.

    PRD 3.4: "The transport component estimates weight from capacity rather than from any actual fill: the container's `capacity_units` is multiplied by 4 grams per unit to give an estimated gram weight, that figure is multiplied by the transport rate of 38 cents per kilogram and divided by 1000 to convert grams to kilograms, and the result is rounded half up to a whole cent."
    PRD 3.4: "`provisional_cost_cents` is the base component plus that rounded transport component."
    Design: Corner/entities/kit_issuance_computes_sizing_cost_and_seal_deadline_fields
    """
    _ctx, kit = _issue_one_kit(api, logistics_coordinator_headers)

    assert kit["provisional_cost_cents"] == 1465
    assert isinstance(kit["provisional_cost_cents"], int), (
        "money is always a whole number of cents"
    )


def test_12_the_new_kit_is_minted_issued_with_a_seal_deadline_of_cadence_plus_grace(
    api, logistics_coordinator_headers
):
    """The kit is stamped `ISSUED` at the logical-clock instant, empty, with a
    seal deadline 30 cadence days plus 14 grace days after 2026-08-01.

    PRD 3.4: "*Second*, the new kit is minted in status `ISSUED` with `enrollment_id` pointing at its enrollment, `required_units`, `container_size`, `capacity_units` and `volume_liters` from the sizing rule above, `provisional_cost_cents` from the costing rule above, `issued_at` set to the current logical-clock instant, `fill_units` at 0, `sealed_gross_weight_grams` null, `acknowledged_at` null, `void_reason` null, `auto_ship_run_id` null for an operator-driven issuance, and `supersedes_kit_id` set to the id of the kit that was just superseded — or null when there was none."
    PRD 3.4: "Its `seal_deadline_date` is the UTC calendar date of `issued_at` advanced by the enrollment's `cadence_days` plus a 14-day grace period; a kit still unsealed after that date is a late kit for audit purposes."
    Design: Corner/entities/kit_issuance_computes_sizing_cost_and_seal_deadline_fields
    """
    ctx, kit = _issue_one_kit(api, logistics_coordinator_headers)

    assert kit["enrollment_id"] == ctx["enrollment"]["id"]
    _assert_instant(kit["issued_at"], CLOCK_AT_CREATION, "issued_at")
    assert_calendar_date(kit["seal_deadline_date"], "seal_deadline_date")
    assert_kit(
        kit,
        status="ISSUED",
        seal_deadline_date="2026-09-14",
        fill_units=0,
        void_reason=None,
        supersedes_kit_id=None,
        auto_ship_run_id=None,
    )
    assert kit["sealed_gross_weight_grams"] is None
    assert kit["acknowledged_at"] is None


def test_13_issuance_advances_the_enrollment_due_date_and_reserves_the_money(
    api, logistics_coordinator_headers
):
    """Issuance recomputes `kits_issued`, pushes the due date out by the cadence,
    and reserves the provisional cost against the program.

    PRD 3.4: "*Third*, a `RESERVATION` ledger entry for the positive `provisional_cost_cents` is appended at the next `sequence_no` and the program's `reserved_cents` rises by that amount."
    PRD 3.4: "*Fifth*, the enrollment's `next_autoship_due_date` is set to the UTC calendar date of `issued_at` advanced by `cadence_days`, its `kits_issued` is recomputed, and its `version` is incremented by 1."
    Design: Corner/entities/kit_issuance_computes_sizing_cost_and_seal_deadline_fields
    """
    ctx, _kit = _issue_one_kit(api, logistics_coordinator_headers)

    enrollment = read_enrollment(api, ctx["enrollment"]["id"])
    assert_enrollment(enrollment, kits_issued=1, next_autoship_due_date="2026-08-31")

    program = read_program(api, ctx["sponsorship_program"]["id"])
    assert_program_balances(
        program, reserved_cents=1465, available_cents=498535, committed_cents=0
    )


# ==========================================================================
# System fields are server-stamped and version moves on every write
# ==========================================================================
def _program_then_funding_adjustment(api):
    """Open NW-2026 at 2026-08-01, advance the clock four days with no writes in
    between, then top the ceiling up by 10000 cents as the owning sponsor."""
    set_clock(api, CLOCK_AT_CREATION)
    sponsor = create_sponsor(
        api,
        legal_name="Northwind Devices Inc",
        sponsor_type="MANUFACTURER",
        contact_email="programs@northwind.example",
    )
    created = create_sponsorship_program(api, sponsor["id"], **PROGRAM_OVERRIDES)

    set_clock(api, CLOCK_AFTER_ADVANCE)
    adjusted = validate_success(
        api.create_funding_adjustment(
            created["id"],
            funding_adjustment_payload(10000, created["version"], memo="Q3 top-up"),
            make_sponsor_representative_headers(sponsor["id"]),
        ),
        200,
    )
    return created, adjusted


def test_14_created_at_freezes_while_updated_at_and_version_move_on_the_adjustment(
    api,
):
    """The program's `created_at` stays at the creation instant while
    `updated_at` re-reads the advanced clock and `version` goes 1 to 2.

    PRD 2.4: "Every resource also carries a `created_at` timestamp: an ISO 8601 UTC instant with three fractional-second digits, read from the logical clock at the moment the row was minted."
    PRD 2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC instant refreshed on every mutation of that row, and `version`, an integer that begins at 1 when the row is created and increments by exactly 1 on every mutation."
    Design: Corner/entities/system_fields_are_server_stamped_and_version_increments_on_every_write
    """
    created, adjusted = _program_then_funding_adjustment(api)

    assert created["version"] == 1
    assert_system_fields(adjusted, expected_version=2)
    _assert_instant(adjusted["created_at"], CLOCK_AT_CREATION, "created_at")
    _assert_instant(adjusted["updated_at"], CLOCK_AFTER_ADVANCE, "updated_at")


def test_15_the_adjustment_raises_the_ceiling_in_place_without_reminting_the_row(api):
    """The delta lands on `funding_ceiling_cents`, `available_cents` follows it,
    and the row keeps its original id rather than being replaced.

    PRD 3.2: "The delta is added to `funding_ceiling_cents`, which may rise or fall, but it may never be pushed below the sum of `reserved_cents` and `committed_cents`: a sponsor cannot claw back money that is already reserved against outstanding kits or committed against issued certificates, and an attempt to do so is refused with `ERR_FUNDING_BELOW_OBLIGATIONS` (HTTP 422)."
    PRD 2.4: "Every persisted resource carries an `id` that is a server-minted UUID."
    Design: Corner/entities/system_fields_are_server_stamped_and_version_increments_on_every_write
    """
    created, adjusted = _program_then_funding_adjustment(api)

    assert adjusted["id"] == created["id"], "an adjustment mutates the row in place"
    assert_program_balances(
        adjusted,
        funding_ceiling_cents=510000,
        available_cents=510000,
        reserved_cents=0,
        committed_cents=0,
        status="ACTIVE",
    )


def test_16_the_adjustment_appends_the_programs_first_ledger_entry(api):
    """The only ledger movement so far is the signed funding adjustment, at the
    program's opening `sequence_no`.

    PRD 3.2: "A successful adjustment appends a `FUNDING_ADJUSTMENT` ledger entry whose `amount_cents` is the submitted `delta_cents` signed exactly as submitted, whose `kit_id` is null, whose `memo` is copied from the request, and whose three after-balances are snapshotted; it then recomputes `available_cents`, flips the program between `EXHAUSTED` and `ACTIVE` if the recomputed figure crosses zero, and increments the program's `version` by 1."
    PRD 2.9: "Each entry also carries a `sequence_no`, a per-program monotonic counter starting at 1, which pins the relative order of appends made in the same request or at the same clock instant; ledger listings are returned in `sequence_no` ascending order."
    Design: Corner/entities/system_fields_are_server_stamped_and_version_increments_on_every_write
    """
    created, _adjusted = _program_then_funding_adjustment(api)

    entries = read_ledger_entries(api, created["id"])
    assert len(entries) == 1, f"expected exactly 1 ledger entry, got {len(entries)}"
    assert_ledger_entry(
        entries[0],
        entry_type="FUNDING_ADJUSTMENT",
        amount_cents=10000,
        sequence_no=1,
    )
    assert entries[0]["kit_id"] is None
    assert entries[0]["memo"] == "Q3 top-up"


# ==========================================================================
# The two append-only event records
# ==========================================================================
def _issued_kit_context(api):
    """Dana's enrollment with one ONE_QUART kit issued at 2026-08-01, which
    leaves a RESERVATION on the ledger and the due date at 2026-08-31."""
    ctx = setup_active_enrollment(
        api,
        clock=CLOCK_AT_CREATION,
        state_rule_overrides=STATE_RULE_OVERRIDES,
        program_overrides=PROGRAM_OVERRIDES,
        patient_overrides=PATIENT_OVERRIDES,
        enrollment_overrides=ENROLLMENT_OVERRIDES,
    )
    issue_kit_for(api, ctx)
    return ctx


def test_17_the_reservation_ledger_entry_carries_no_version_and_no_updated_at(api):
    """The RESERVATION row minted by issuance is read-only history: it exposes
    `id` and `created_at` and neither `updated_at` nor `version`.

    PRD 2.4: "Two resources are append-only event records and therefore carry **only** `id` and `created_at`: the sponsor ledger entry and the auto-ship run."
    PRD 2.4: "For those two, `updated_at` and `version` are absent entirely — not null, not zero, absent — because neither row is ever modified after it is written."
    PRD 3.2: "They are the audit trail of every cent the program has moved, and because they are append-only they carry neither `updated_at` nor `version`."
    Design: Corner/entities/sponsor_ledger_entry_and_autoship_run_are_append_only_with_no_version_field
    """
    ctx = _issued_kit_context(api)

    entries = read_ledger_entries(api, ctx["sponsorship_program"]["id"])
    assert len(entries) == 1, f"expected exactly 1 ledger entry, got {len(entries)}"
    assert_append_only_system_fields(entries[0])
    assert "version" not in entries[0]
    assert "updated_at" not in entries[0]


def test_18_the_reservation_entry_snapshots_the_balances_it_produced(api):
    """The entry classifies itself, carries the positive provisional cost, names
    the kit it accounts for, and snapshots the post-append balance triple.

    PRD 3.4: "*Third*, a `RESERVATION` ledger entry for the positive `provisional_cost_cents` is appended at the next `sequence_no` and the program's `reserved_cents` rises by that amount."
    PRD 2.9: "Finally, each entry snapshots the three program balances as they stood immediately after the append, in `reserved_after_cents`, `committed_after_cents` and `available_after_cents`, and records a human-readable origin in `memo` — "kit issuance", "kit void", "certificate settlement" and the like."
    Design: Corner/entities/sponsor_ledger_entry_and_autoship_run_are_append_only_with_no_version_field
    """
    ctx = _issued_kit_context(api)

    entries = read_ledger_entries(api, ctx["sponsorship_program"]["id"])
    assert_ledger_entry(
        entries[0],
        entry_type="RESERVATION",
        amount_cents=1465,
        sequence_no=1,
        kit_id=ctx["kit"]["id"],
        reserved_after_cents=1465,
        committed_after_cents=0,
        available_after_cents=498535,
    )


def test_19_the_auto_ship_run_record_carries_no_version_and_no_updated_at(
    api, program_admin_headers
):
    """The run record is the second append-only event record, so it too exposes
    only `id` and `created_at` among the system fields.

    PRD 2.4: "Two resources are append-only event records and therefore carry **only** `id` and `created_at`: the sponsor ledger entry and the auto-ship run."
    PRD 2.4: "For those two, `updated_at` and `version` are absent entirely — not null, not zero, absent — because neither row is ever modified after it is written."
    Design: Corner/entities/sponsor_ledger_entry_and_autoship_run_are_append_only_with_no_version_field
    """
    _issued_kit_context(api)

    run = validate_success(
        api.create_auto_ship_run(auto_ship_run_payload(), program_admin_headers),
        201,
    )
    assert_append_only_system_fields(run)
    assert "version" not in run
    assert "updated_at" not in run


def test_20_a_run_that_issues_nothing_still_records_its_walk(
    api, program_admin_headers
):
    """With Dana's only enrollment not yet due, the run defaults `as_of_date`
    from the clock, evaluates one enrollment and records a single not-due skip.

    PRD 3.9: "A `ProgramAdmin` runs the replacement-container checkpoint, optionally supplying an `as_of_date` against which due dates are evaluated; when omitted it defaults to the logical clock's UTC date."
    PRD 3.9: "The run records its own `run_at` as the logical-clock instant at which it executed."
    PRD 3.9: "The count of enrollments inspected is recorded as `enrollments_evaluated`."
    PRD 3.9: "First, **not due**: if the enrollment's `next_autoship_due_date` falls after the run's `as_of_date`, `kits_skipped_not_due` rises by 1."
    PRD 3.9: "A run that issues no kits at all is still a success: it returns a created run record with its counters at whatever values the walk produced."
    Design: Corner/entities/sponsor_ledger_entry_and_autoship_run_are_append_only_with_no_version_field
    """
    _issued_kit_context(api)

    run = validate_success(
        api.create_auto_ship_run(auto_ship_run_payload(), program_admin_headers),
        201,
    )
    assert_calendar_date(run["as_of_date"], "as_of_date")
    _assert_instant(run["run_at"], CLOCK_AT_CREATION, "run_at")
    assert_auto_ship_run(
        run,
        as_of_date="2026-08-01",
        enrollments_evaluated=1,
        kits_created=0,
        kits_skipped_not_due=1,
        kits_skipped_risk=0,
        kits_skipped_unfilled=0,
        kits_skipped_funding=0,
        created_kit_ids=[],
    )
