"""Risk-score age decay and the scope of the auto-ship checkpoint (PRD 3.9).

Every test builds its own program, patients and custody history from scratch and
drives the logical clock explicitly, because the screening decay bands and the
enrollment walk are both defined against the clock instant of the read.
"""

from test_helpers import (
    add_enrolled_patient,
    assert_auto_ship_run,
    assert_enrollment,
    assert_kit,
    assert_ledger_sequence,
    assert_ledger_sequence_numbers_start_at_one,
    assert_non_conformance_event,
    assert_patient_risk,
    assert_program_balances,
    assert_total_count,
    auto_ship_run_payload,
    create_draft_enrollment,
    create_eligible_patient,
    funding_adjustment_payload,
    make_sponsor_representative_headers,
    read_enrollment,
    read_kit,
    read_ledger_entries,
    read_patient,
    read_program,
    set_clock,
    setup_program_foundations,
    setup_screened_shipment,
    sponsor_decision_payload,
    status_action_payload,
    validate_success,
)


def _normalise_instant(value):
    """Compare ISO 8601 instants without depending on the fractional-second
    width the implementation chooses to serialise."""
    assert isinstance(value, str) and value.endswith("Z"), value
    return value[:-1].split(".")[0] + "Z"


def _loose_sharps_history(api):
    """One patient whose single returned parcel was screened NON_CONFORMING for
    LOOSE_SHARPS_IN_BOX at the 2026-08-01T00:00:00Z baseline instant.

    That event weighs 45 and is the only entry in the patient's history, so the
    patient's two risk readings isolate the age-decay bands exactly.
    """
    return setup_screened_shipment(
        api,
        outcome="NON_CONFORMING",
        reason_code="LOOSE_SHARPS_IN_BOX",
        technician_user_id="tech-77",
        fill_units=60,
        sealed_gross_weight_grams=1200,
        declared_gross_weight_grams=1200,
        observed_gross_weight_grams=1200,
        scheduled_intake_date="2026-08-05",
        state_rule_overrides={"household_sharps_classification": "HOUSEHOLD_EXEMPT"},
        packaging_spec_overrides={
            "spec_code": "MB-4G-STD",
            "max_gross_weight_grams": 8000,
            "allowed_container_sizes": ["ONE_QUART", "TWO_GALLON"],
        },
        facility_overrides={
            "daily_intake_capacity_units": 200,
            "accepted_hazard_classes": ["UN3291_SHARPS_ONLY"],
        },
        program_overrides={"per_kit_allowance_cents": 5000},
        patient_overrides={"weekly_sharps_count": 20},
        enrollment_overrides={"cadence_days": 30, "kits_authorized": 3},
    )


def _checkpoint_at(api, headers, clock, as_of_date="2026-08-01"):
    """Move the clock, then take a checkpoint whose `as_of_date` is pinned to the
    baseline so that the only thing changing between tests is event age."""
    set_clock(api, clock)
    return validate_success(
        api.create_auto_ship_run(auto_ship_run_payload(as_of_date=as_of_date), headers),
        expected_status=201,
    )


def test_01_event_aged_exactly_ninety_days_keeps_its_full_screening_weight(
    api, program_admin_headers
):
    """At 90 whole days of age the LOOSE_SHARPS_IN_BOX event is still inside the
    full-weight band, so the refreshed `screening_risk_score` reads its raw 45.

PRD 3.9: "An event's age in days is the elapsed time between its `created_at` and the current logical-clock instant, expressed in whole days by discarding any remainder — that is, the number of complete 86400-second periods that have passed."
PRD 3.9: "Each event contributes a weight determined by its `reason_code`: `LOOSE_SHARPS_IN_BOX` weighs 45, `UNAPPROVED_WASTE_TYPE` weighs 40, `UNSEALED_CONTAINER` weighs 30, `OVERFILLED_CONTAINER` weighs 25, `WEIGHT_EXCEEDS_SPEC` weighs 20 and `MISSING_ABSORBENT` weighs 15."
PRD 3.9: "An event aged at most 90 days contributes its full weight; an event aged from 91 through 180 days inclusive contributes half its weight; an event aged more than 180 days contributes nothing."
PRD 3.9: "Both readings — `screening_risk_score` and `audit_risk_score` — are recomputed and stored for every patient who holds at least one enrollment whose status is not `REJECTED` and not `TERMINATED`."

    Design: Corner/calculations/risk_decay_bands_switch_at_ninety_and_one_hundred_eighty_days_of_event_age
    """
    ctx = _loose_sharps_history(api)
    patient = ctx["patient"]
    program = ctx["sponsorship_program"]

    # 2026-08-01T00:00:00Z to 2026-10-30T00:00:00Z is exactly 90 complete days.
    run = _checkpoint_at(api, program_admin_headers, "2026-10-30T00:00:00Z")

    assert_auto_ship_run(
        run,
        enrollments_evaluated=1,
        kits_created=0,
        kits_skipped_not_due=1,
        kits_skipped_risk=0,
        kits_skipped_unfilled=0,
        kits_skipped_funding=0,
        as_of_date="2026-08-01",
        created_kit_ids=[],
    )
    assert_patient_risk(
        read_patient(api, patient["id"]),
        screening_risk_score=45,
        audit_risk_score=45,
        status="ENROLLED",
    )
    assert_program_balances(
        read_program(api, program["id"]),
        reserved_cents=1465,
        committed_cents=0,
        available_cents=498535,
        funding_ceiling_cents=500000,
        status="ACTIVE",
    )
    assert_total_count(
        api.list_kits(program_admin_headers, {"enrollment_id": ctx["enrollment"]["id"]}),
        1,
    )
    events, _ = assert_total_count(
        api.list_non_conformance_events(
            program_admin_headers, {"shipment_id": ctx["shipment"]["id"]}
        ),
        1,
    )
    assert_non_conformance_event(
        events[0], status="OPEN", reason_code="LOOSE_SHARPS_IN_BOX"
    )


def test_02_event_aged_ninety_one_days_is_halved_and_rounded_once(
    api, program_admin_headers
):
    """One day past the full-weight band the same event contributes 22.5, and the
    single trailing round-half-up over that exact sum reads 23.

PRD 3.9: "An event aged at most 90 days contributes its full weight; an event aged from 91 through 180 days inclusive contributes half its weight; an event aged more than 180 days contributes nothing."
PRD 3.9: "The discounted contributions are summed **exactly**, keeping halves intact, and the single total is then rounded half up to a whole number; the result is capped at 100."

    Design: Corner/calculations/risk_decay_bands_switch_at_ninety_and_one_hundred_eighty_days_of_event_age
    """
    ctx = _loose_sharps_history(api)

    # 2026-08-01T00:00:00Z to 2026-10-31T00:00:00Z is exactly 91 complete days.
    run = _checkpoint_at(api, program_admin_headers, "2026-10-31T00:00:00Z")

    assert_auto_ship_run(run, enrollments_evaluated=1, kits_created=0, created_kit_ids=[])
    assert_patient_risk(
        read_patient(api, ctx["patient"]["id"]),
        screening_risk_score=23,
        audit_risk_score=45,
        status="ENROLLED",
    )


def test_03_event_aged_exactly_one_hundred_eighty_days_is_still_halved(
    api, program_admin_headers
):
    """180 days is the inclusive top of the half-weight band, so the reading has
    not yet dropped to zero and still reads 23.

PRD 3.9: "An event aged at most 90 days contributes its full weight; an event aged from 91 through 180 days inclusive contributes half its weight; an event aged more than 180 days contributes nothing."
PRD 3.9: "The discounted contributions are summed **exactly**, keeping halves intact, and the single total is then rounded half up to a whole number; the result is capped at 100."

    Design: Corner/calculations/risk_decay_bands_switch_at_ninety_and_one_hundred_eighty_days_of_event_age
    """
    ctx = _loose_sharps_history(api)

    # 2026-08-01T00:00:00Z to 2027-01-28T00:00:00Z is exactly 180 complete days.
    run = _checkpoint_at(api, program_admin_headers, "2027-01-28T00:00:00Z")

    assert_auto_ship_run(run, enrollments_evaluated=1, kits_created=0, created_kit_ids=[])
    assert_patient_risk(
        read_patient(api, ctx["patient"]["id"]),
        screening_risk_score=23,
        audit_risk_score=45,
        status="ENROLLED",
    )


def test_04_event_aged_one_hundred_eighty_one_days_contributes_nothing(
    api, program_admin_headers
):
    """One day beyond the half-weight band the event stops contributing entirely,
    so `screening_risk_score` falls to 0 while `audit_risk_score` still reads its
    undiscounted 45 — the returned kit is not late, so no lateness penalty joins it.

PRD 3.9: "An event aged at most 90 days contributes its full weight; an event aged from 91 through 180 days inclusive contributes half its weight; an event aged more than 180 days contributes nothing."
PRD 3.9: "Every event contributes its full weight with no age discount at all."
PRD 3.9: "Added to that sum is a penalty of 10 points for each **late kit**, where a late kit is one of the patient's kits still in `ISSUED` or `ACTIVE_FILLING` whose `seal_deadline_date` falls strictly before the current logical-clock UTC date."

    Design: Corner/calculations/risk_decay_bands_switch_at_ninety_and_one_hundred_eighty_days_of_event_age
    """
    ctx = _loose_sharps_history(api)

    # 2026-08-01T00:00:00Z to 2027-01-29T00:00:00Z is exactly 181 complete days.
    run = _checkpoint_at(api, program_admin_headers, "2027-01-29T00:00:00Z")

    assert_auto_ship_run(
        run,
        enrollments_evaluated=1,
        kits_created=0,
        kits_skipped_not_due=1,
        kits_skipped_risk=0,
        kits_skipped_unfilled=0,
        kits_skipped_funding=0,
        created_kit_ids=[],
    )
    assert_patient_risk(
        read_patient(api, ctx["patient"]["id"]),
        screening_risk_score=0,
        audit_risk_score=45,
        status="ENROLLED",
    )
    assert_program_balances(
        read_program(api, ctx["sponsorship_program"]["id"]),
        reserved_cents=1465,
        committed_cents=0,
        available_cents=498535,
        funding_ceiling_cents=500000,
        status="ACTIVE",
    )


def _five_status_program(api, admin_headers):
    """One funded program carrying one enrollment in each of the five statuses.

    Ada stays in DRAFT, Ben waits in PENDING_SPONSOR_APPROVAL, Cleo is REJECTED by
    the sponsor, Dana is ACTIVE and due, and Eli's enrollment is PAUSED because
    the patient was suspended by an administrator.
    """
    ctx = setup_program_foundations(
        api,
        state_rule_overrides={"household_sharps_classification": "HOUSEHOLD_EXEMPT"},
        packaging_spec_overrides={
            "spec_code": "MB-4G-STD",
            "max_gross_weight_grams": 8000,
            "allowed_container_sizes": ["ONE_QUART", "TWO_GALLON"],
        },
        facility_overrides={
            "daily_intake_capacity_units": 200,
            "accepted_hazard_classes": ["UN3291_SHARPS_ONLY"],
        },
        program_overrides={"per_kit_allowance_cents": 5000},
    )
    rule_id = ctx["state_rule"]["id"]
    program_id = ctx["sponsorship_program"]["id"]
    sponsor_headers = make_sponsor_representative_headers(ctx["sponsor"]["id"])
    terms = {"cadence_days": 30, "kits_authorized": 3}

    def eligible(name, email):
        return create_eligible_patient(
            api, rule_id, full_name=name, weekly_sharps_count=20, contact_email=email
        )

    ctx["patient_ada"] = eligible("Ada Whitfield", "ada@example.com")
    ctx["enrollment_ada"] = create_draft_enrollment(
        api, ctx["patient_ada"]["id"], program_id, **terms
    )

    ctx["patient_ben"] = eligible("Ben Ortiz", "ben@example.com")
    ben_enrollment = create_draft_enrollment(
        api, ctx["patient_ben"]["id"], program_id, **terms
    )
    ctx["enrollment_ben"] = validate_success(
        api.submit_enrollment(ben_enrollment["id"], admin_headers)
    )

    ctx["patient_cleo"] = eligible("Cleo Marchetti", "cleo@example.com")
    cleo_enrollment = create_draft_enrollment(
        api, ctx["patient_cleo"]["id"], program_id, **terms
    )
    validate_success(api.submit_enrollment(cleo_enrollment["id"], admin_headers))
    ctx["enrollment_cleo"] = validate_success(
        api.record_sponsor_decision(
            cleo_enrollment["id"],
            sponsor_decision_payload(
                "REJECT", sponsor_decision_note="outside the funded therapy list"
            ),
            sponsor_headers,
        )
    )

    dana = add_enrolled_patient(
        api,
        ctx,
        patient_overrides={
            "full_name": "Dana Reyes",
            "weekly_sharps_count": 20,
            "contact_email": "dana@example.com",
        },
        enrollment_overrides=terms,
        key="dana",
    )

    eli = add_enrolled_patient(
        api,
        ctx,
        patient_overrides={
            "full_name": "Eli Ferrante",
            "weekly_sharps_count": 20,
            "contact_email": "eli@example.com",
        },
        enrollment_overrides=terms,
        key="eli",
    )
    ctx["patient_eli"] = validate_success(
        api.patient_status_action(
            eli["patient"]["id"],
            status_action_payload("SUSPEND", reason="unresolved intake complaint"),
            admin_headers,
        )
    )
    ctx["enrollment_dana"] = dana["enrollment"]
    return ctx


def test_05_the_checkpoint_walks_only_the_active_enrollment(api, program_admin_headers):
    """Of five enrollments only the ACTIVE one is inspected: `enrollments_evaluated`
    reads 1, one kit is created for it, and no skip counter fires at all.

PRD 3.9: "The run then walks the enrollments whose status is `ACTIVE`, and only those — `DRAFT`, `PENDING_SPONSOR_APPROVAL`, `PAUSED`, `REJECTED` and `TERMINATED` enrollments are out of scope entirely — in ascending order of enrollment creation time."
PRD 3.9: "The count of enrollments inspected is recorded as `enrollments_evaluated`."
PRD 3.9: "A `ProgramAdmin` runs the replacement-container checkpoint, optionally supplying an `as_of_date` against which due dates are evaluated; when omitted it defaults to the logical clock's UTC date."
PRD 3.9: "The run records its own `run_at` as the logical-clock instant at which it executed."
PRD 3.3: "The new enrollment starts at `DRAFT` with `kits_issued` at 0, `next_autoship_due_date` null, `activated_at` null, `sponsor_decision_note` null and `version` at 1."
PRD 3.3: "It moves the enrollment `DRAFT → PENDING_SPONSOR_APPROVAL` and increments the enrollment's `version` by 1, and it requires three things at once: the enrollment must be in `DRAFT`, otherwise `ERR_INVALID_ENROLLMENT_STATE`; the patient must be in `ELIGIBLE` or `ENROLLED`, otherwise `ERR_INVALID_PATIENT_STATE`; and the funding sponsor must be `ACTIVE`, otherwise `ERR_SPONSOR_NOT_ACTIVE`."
PRD 3.3: "It moves the enrollment `PENDING_SPONSOR_APPROVAL → REJECTED`, which is terminal, and copies the submitted note into `sponsor_decision_note`. It leaves `next_autoship_due_date` null, leaves `activated_at` null, does not touch the patient's `status` at all — a patient rejected by one sponsor remains `ELIGIBLE` and may be enrolled elsewhere — and appends no ledger entry whatsoever, because no money was ever reserved."
PRD 3.9: "The second hop moves every enrollment of that patient whose status is `ACTIVE` to `PAUSED`."

    Design: Corner/calculations/autoship_scope_admits_only_active_enrollments_and_ignores_the_other_four_statuses
    """
    ctx = _five_status_program(api, program_admin_headers)

    run = validate_success(
        api.create_auto_ship_run(auto_ship_run_payload(), program_admin_headers),
        expected_status=201,
    )

    assert_auto_ship_run(
        run,
        enrollments_evaluated=1,
        kits_created=1,
        kits_skipped_not_due=0,
        kits_skipped_risk=0,
        kits_skipped_unfilled=0,
        kits_skipped_funding=0,
        as_of_date="2026-08-01",
    )
    assert _normalise_instant(run["run_at"]) == "2026-08-01T00:00:00Z", run["run_at"]

    dana_kits, _ = assert_total_count(
        api.list_kits(
            program_admin_headers, {"enrollment_id": ctx["enrollment_dana"]["id"]}
        ),
        1,
    )
    assert run["created_kit_ids"] == [dana_kits[0]["id"]], run["created_kit_ids"]

    assert_enrollment(
        read_enrollment(api, ctx["enrollment_ada"]["id"]),
        status="DRAFT",
        kits_issued=0,
        next_autoship_due_date=None,
    )
    assert_enrollment(
        read_enrollment(api, ctx["enrollment_ben"]["id"]),
        status="PENDING_SPONSOR_APPROVAL",
        kits_issued=0,
    )
    assert_enrollment(
        read_enrollment(api, ctx["enrollment_cleo"]["id"]),
        status="REJECTED",
        kits_issued=0,
        next_autoship_due_date=None,
    )
    assert_enrollment(
        read_enrollment(api, ctx["enrollment_eli"]["id"]),
        status="PAUSED",
        kits_issued=0,
    )
    assert_total_count(
        api.list_kits(
            program_admin_headers, {"enrollment_id": ctx["enrollment_eli"]["id"]}
        ),
        0,
    )


def test_06_the_run_stamps_its_kit_and_advances_the_active_enrollment(
    api, program_admin_headers
):
    """The kit the run mints records the run that produced it, carries a null
    `supersedes_kit_id` because the enrollment held none, and pushes the
    enrollment's next due date to the run's `as_of_date` plus the cadence.

PRD 3.9: "The new kit's `supersedes_kit_id` is set to the enrollment's most recent prior kit by creation time, or null when the enrollment has none, and its `auto_ship_run_id` is set to this run."
PRD 3.9: "After the kit is minted, the enrollment's `next_autoship_due_date` is set to the run's `as_of_date` advanced by the enrollment's `cadence_days`, `kits_created` rises by 1, and the new kit's id is appended to `created_kit_ids`, which therefore lists ids in processing order."
PRD 3.4: "The computation multiplies the weekly count by that factor, then by the number of cadence days, then by 115, divides the product by 700, and rounds the single resulting quotient up to the next whole number."
PRD 3.4: "The transport component estimates weight from capacity rather than from any actual fill: the container's `capacity_units` is multiplied by 4 grams per unit to give an estimated gram weight, that figure is multiplied by the transport rate of 38 cents per kilogram and divided by 1000 to convert grams to kilograms, and the result is rounded half up to a whole cent. `provisional_cost_cents` is the base component plus that rounded transport component."
PRD 3.4: "*Third*, a `RESERVATION` ledger entry for the positive `provisional_cost_cents` is appended at the next `sequence_no` and the program's `reserved_cents` rises by that amount."
PRD 2.9: "`available_cents` is `funding_ceiling_cents` less `reserved_cents` less `committed_cents`, recomputed after every append."

    Design: Corner/calculations/autoship_scope_admits_only_active_enrollments_and_ignores_the_other_four_statuses
    """
    ctx = _five_status_program(api, program_admin_headers)
    program_id = ctx["sponsorship_program"]["id"]

    run = validate_success(
        api.create_auto_ship_run(auto_ship_run_payload(), program_admin_headers),
        expected_status=201,
    )

    kit = read_kit(api, run["created_kit_ids"][0])
    assert_kit(
        kit,
        status="ISSUED",
        container_size="ONE_QUART",
        required_units=99,
        capacity_units=100,
        volume_liters=0.9,
        provisional_cost_cents=1465,
        supersedes_kit_id=None,
        auto_ship_run_id=run["id"],
    )
    assert_enrollment(
        read_enrollment(api, ctx["enrollment_dana"]["id"]),
        status="ACTIVE",
        kits_issued=1,
        next_autoship_due_date="2026-08-31",
    )
    program = read_program(api, program_id)
    assert_program_balances(
        program,
        reserved_cents=1465,
        committed_cents=0,
        available_cents=498535,
        funding_ceiling_cents=500000,
        status="ACTIVE",
    )
    assert program["kits_issued_count"] == 1, program["kits_issued_count"]
    entries = read_ledger_entries(api, program_id)
    assert_ledger_sequence(entries, [(1, "RESERVATION", 1465)])


def test_07_the_risk_refresh_reaches_out_of_scope_patients_without_writing_status(
    api, program_admin_headers
):
    """The refresh covers every patient holding a non-rejected, non-terminated
    enrollment, yet it writes no `status`: the suspended patient stays SUSPENDED
    with a PAUSED enrollment and no kit of their own.

PRD 3.9: "Both readings — `screening_risk_score` and `audit_risk_score` — are recomputed and stored for every patient who holds at least one enrollment whose status is not `REJECTED` and not `TERMINATED`."
PRD 3.9: "This step never writes a patient's `status`, so no suspension can originate inside a run even if a refreshed `screening_risk_score` lands above the threshold."
PRD 3.9: "The first hop moves the patient `ENROLLED → SUSPENDED` and sets `suspended_at` to the current logical-clock instant."
PRD 3.9: "The third hop applies to each of those newly paused enrollments: its `next_autoship_due_date` is cleared to null, and every kit of that enrollment whose status is `ISSUED` moves to `VOIDED` with `void_reason` set to `ENROLLMENT_PAUSED` — kits already in `ACTIVE_FILLING` are physically in the patient's hands and are pointedly **not** voided."

    Design: Corner/calculations/autoship_scope_admits_only_active_enrollments_and_ignores_the_other_four_statuses
    """
    ctx = _five_status_program(api, program_admin_headers)

    validate_success(
        api.create_auto_ship_run(auto_ship_run_payload(), program_admin_headers),
        expected_status=201,
    )

    assert_patient_risk(
        read_patient(api, ctx["patient_ada"]["id"]),
        screening_risk_score=0,
        audit_risk_score=0,
    )
    assert_patient_risk(
        read_patient(api, ctx["patient_eli"]["id"]),
        screening_risk_score=0,
        audit_risk_score=0,
        status="SUSPENDED",
    )
    assert_enrollment(
        read_enrollment(api, ctx["enrollment_eli"]["id"]),
        status="PAUSED",
        kits_issued=0,
        next_autoship_due_date=None,
    )
    assert_total_count(
        api.list_kits(
            program_admin_headers, {"enrollment_id": ctx["enrollment_eli"]["id"]}
        ),
        0,
    )


def _two_enrollments_on_a_tight_program(api):
    """Two ACTIVE enrollments on one program whose ceiling funds a single kit.

    Ada's enrollment is created an hour before Ben's, so `created_at` ascending is
    unambiguous, and both are immediately due at the 2026-08-01 baseline date.
    """
    ctx = setup_program_foundations(
        api,
        state_rule_overrides={"household_sharps_classification": "HOUSEHOLD_EXEMPT"},
        packaging_spec_overrides={
            "spec_code": "MB-4G-STD",
            "max_gross_weight_grams": 8000,
            "allowed_container_sizes": ["ONE_QUART", "TWO_GALLON"],
        },
        facility_overrides={
            "daily_intake_capacity_units": 200,
            "accepted_hazard_classes": ["UN3291_SHARPS_ONLY"],
        },
        program_overrides={
            "program_code": "NW-TIGHT",
            "funding_ceiling_cents": 2000,
            "per_kit_allowance_cents": 5000,
        },
    )
    terms = {"cadence_days": 30, "kits_authorized": 3}
    add_enrolled_patient(
        api,
        ctx,
        patient_overrides={
            "full_name": "Ada Whitfield",
            "weekly_sharps_count": 20,
            "contact_email": "ada@example.com",
        },
        enrollment_overrides=terms,
        key="a",
    )
    set_clock(api, "2026-08-01T01:00:00Z")
    add_enrolled_patient(
        api,
        ctx,
        patient_overrides={
            "full_name": "Ben Ortiz",
            "weekly_sharps_count": 20,
            "contact_email": "ben@example.com",
        },
        enrollment_overrides=terms,
        key="b",
    )
    return ctx


def test_08_the_earlier_enrollment_takes_the_last_of_the_funding(
    api, program_admin_headers
):
    """With 2000 cents on the ceiling and a 1465-cent kit each, the enrollment
    created first is processed first and consumes the pool, leaving the later one
    counted under `kits_skipped_funding` against the running balance.

PRD 3.9: "The run then walks the enrollments whose status is `ACTIVE`, and only those — `DRAFT`, `PENDING_SPONSOR_APPROVAL`, `PAUSED`, `REJECTED` and `TERMINATED` enrollments are out of scope entirely — in ascending order of enrollment creation time."
PRD 3.9: "That ordering is the sole sanctioned one; no other field, and in particular never the enrollment's `id`, participates in it."
PRD 3.9: "Fourth, **funding**: if the program's `available_cents` is below the `provisional_cost_cents` of the kit that would be issued, `kits_skipped_funding` rises by 1."
PRD 3.9: "Because the funding comparison uses the balance as it stands after every kit issued earlier in the same run, an enrollment processed early can legitimately starve one processed later."
PRD 3.9: "After the kit is minted, the enrollment's `next_autoship_due_date` is set to the run's `as_of_date` advanced by the enrollment's `cadence_days`, `kits_created` rises by 1, and the new kit's id is appended to `created_kit_ids`, which therefore lists ids in processing order."

    Design: Corner/calculations/autoship_processes_enrollments_in_created_at_order_so_the_earlier_one_takes_the_last_funding
    """
    ctx = _two_enrollments_on_a_tight_program(api)

    run = validate_success(
        api.create_auto_ship_run(
            auto_ship_run_payload(as_of_date="2026-08-01"), program_admin_headers
        ),
        expected_status=201,
    )

    assert_auto_ship_run(
        run,
        enrollments_evaluated=2,
        kits_created=1,
        kits_skipped_not_due=0,
        kits_skipped_risk=0,
        kits_skipped_unfilled=0,
        kits_skipped_funding=1,
        as_of_date="2026-08-01",
    )
    ada_kits, _ = assert_total_count(
        api.list_kits(program_admin_headers, {"enrollment_id": ctx["enrollment_a"]["id"]}),
        1,
    )
    assert run["created_kit_ids"] == [ada_kits[0]["id"]], run["created_kit_ids"]
    assert_kit(
        ada_kits[0],
        status="ISSUED",
        container_size="ONE_QUART",
        provisional_cost_cents=1465,
        auto_ship_run_id=run["id"],
    )
    assert_program_balances(
        read_program(api, ctx["sponsorship_program"]["id"]),
        reserved_cents=1465,
        committed_cents=0,
        available_cents=535,
        funding_ceiling_cents=2000,
        status="ACTIVE",
    )
    assert_enrollment(
        read_enrollment(api, ctx["enrollment_a"]["id"]),
        status="ACTIVE",
        kits_issued=1,
        next_autoship_due_date="2026-08-31",
    )
    assert_enrollment(
        read_enrollment(api, ctx["enrollment_b"]["id"]),
        status="ACTIVE",
        kits_issued=0,
        next_autoship_due_date="2026-08-01",
    )
    assert_total_count(
        api.list_kits(program_admin_headers, {"enrollment_id": ctx["enrollment_b"]["id"]}),
        0,
    )


def _starve_then_top_up_and_reship(api, headers):
    """Run the tight checkpoint, top the ceiling up by 1000 cents, then run again
    a cadence later. Returns the context and the two run records."""
    ctx = _two_enrollments_on_a_tight_program(api)
    program_id = ctx["sponsorship_program"]["id"]
    run_one = validate_success(
        api.create_auto_ship_run(
            auto_ship_run_payload(as_of_date="2026-08-01"), headers
        ),
        expected_status=201,
    )
    before = read_program(api, program_id)
    validate_success(
        api.create_funding_adjustment(
            program_id,
            funding_adjustment_payload(
                1000,
                before["version"],
                memo="top-up so the starved enrollment can ship",
            ),
            headers,
        )
    )
    ctx["version_before_top_up"] = before["version"]
    run_two = validate_success(
        api.create_auto_ship_run(
            auto_ship_run_payload(as_of_date="2026-08-31"), headers
        ),
        expected_status=201,
    )
    return ctx, run_one, run_two


def test_09_after_a_top_up_the_starved_enrollment_ships_and_the_earlier_one_is_unfilled(
    api, program_admin_headers
):
    """The 1000-cent top-up lifts the ceiling to 3000 and the balance to 1535, and
    the next checkpoint issues for the previously starved enrollment while the
    earlier one is stopped at the unfilled check, which precedes the funding check.

PRD 3.2: "A successful adjustment appends a `FUNDING_ADJUSTMENT` ledger entry whose `amount_cents` is the submitted `delta_cents` signed exactly as submitted, whose `kit_id` is null, whose `memo` is copied from the request, and whose three after-balances are snapshotted; it then recomputes `available_cents`, flips the program between `EXHAUSTED` and `ACTIVE` if the recomputed figure crosses zero, and increments the program's `version` by 1."
PRD 2.9: "`available_cents` is `funding_ceiling_cents` less `reserved_cents` less `committed_cents`, recomputed after every append."
PRD 3.9: "For each enrollment in scope the run evaluates four skip reasons in a pinned order and stops at the first one that fires."
PRD 3.9: "Third, **unfilled**: if the enrollment's most recent kit by creation time is still in `ISSUED` or `ACTIVE_FILLING`, `kits_skipped_unfilled` rises by 1 — the household has not yet returned what it already has."
PRD 3.9: "After the kit is minted, the enrollment's `next_autoship_due_date` is set to the run's `as_of_date` advanced by the enrollment's `cadence_days`, `kits_created` rises by 1, and the new kit's id is appended to `created_kit_ids`, which therefore lists ids in processing order."
PRD 3.2: "Beyond the reserved/committed/available triple a program maintains five derived counters that a sponsor uses to reconcile: `kits_issued_count`, the number of kits under this program's enrollments whose status is anything other than `VOIDED`; `kits_settled_count`, the number of destruction certificates in status `ISSUED` against this program's kits; `provisional_total_cents`, the sum of `provisional_cost_cents` over this program's kits that carry an `ISSUED` certificate; and `final_total_cents`, the sum of `final_kit_cost_cents` over this program's `ISSUED` certificates."

    Design: Corner/calculations/autoship_processes_enrollments_in_created_at_order_so_the_earlier_one_takes_the_last_funding
    """
    ctx, _run_one, run_two = _starve_then_top_up_and_reship(api, program_admin_headers)
    program_id = ctx["sponsorship_program"]["id"]

    assert_auto_ship_run(
        run_two,
        enrollments_evaluated=2,
        kits_created=1,
        kits_skipped_not_due=0,
        kits_skipped_risk=0,
        kits_skipped_unfilled=1,
        kits_skipped_funding=0,
        as_of_date="2026-08-31",
    )
    ben_kits, _ = assert_total_count(
        api.list_kits(program_admin_headers, {"enrollment_id": ctx["enrollment_b"]["id"]}),
        1,
    )
    assert run_two["created_kit_ids"] == [ben_kits[0]["id"]], run_two["created_kit_ids"]

    program = read_program(api, program_id)
    assert_program_balances(
        program,
        reserved_cents=2930,
        committed_cents=0,
        available_cents=70,
        funding_ceiling_cents=3000,
        status="ACTIVE",
    )
    assert program["kits_issued_count"] == 2, program["kits_issued_count"]
    assert program["version"] == ctx["version_before_top_up"] + 1, program["version"]
    assert_enrollment(
        read_enrollment(api, ctx["enrollment_b"]["id"]),
        status="ACTIVE",
        kits_issued=1,
        next_autoship_due_date="2026-09-30",
    )


def test_10_the_ledger_records_the_two_reservations_around_the_top_up(
    api, program_admin_headers
):
    """The three appends land in `sequence_no` order — the first run's reservation,
    the funding adjustment with a null `kit_id`, then the second run's reservation.

PRD 2.9: "Each entry also carries a `sequence_no`, a per-program monotonic counter starting at 1, which pins the relative order of appends made in the same request or at the same clock instant; ledger listings are returned in `sequence_no` ascending order."
PRD 3.2: "A successful adjustment appends a `FUNDING_ADJUSTMENT` ledger entry whose `amount_cents` is the submitted `delta_cents` signed exactly as submitted, whose `kit_id` is null, whose `memo` is copied from the request, and whose three after-balances are snapshotted; it then recomputes `available_cents`, flips the program between `EXHAUSTED` and `ACTIVE` if the recomputed figure crosses zero, and increments the program's `version` by 1."
PRD 3.4: "*Third*, a `RESERVATION` ledger entry for the positive `provisional_cost_cents` is appended at the next `sequence_no` and the program's `reserved_cents` rises by that amount."
PRD 3.2: "Ledger entries are readable individually and as a list filtered by `sponsorship_program_id`, `kit_id` or `entry_type`, always in `sequence_no` ascending order."

    Design: Corner/calculations/autoship_processes_enrollments_in_created_at_order_so_the_earlier_one_takes_the_last_funding
    """
    ctx, run_one, run_two = _starve_then_top_up_and_reship(api, program_admin_headers)

    entries = read_ledger_entries(api, ctx["sponsorship_program"]["id"])

    assert_ledger_sequence_numbers_start_at_one(entries)
    assert_ledger_sequence(
        entries,
        [
            (1, "RESERVATION", 1465),
            (2, "FUNDING_ADJUSTMENT", 1000),
            (3, "RESERVATION", 1465),
        ],
    )
    assert entries[0]["kit_id"] == run_one["created_kit_ids"][0], entries[0]["kit_id"]
    assert entries[1]["kit_id"] is None, entries[1]["kit_id"]
    assert entries[2]["kit_id"] == run_two["created_kit_ids"][0], entries[2]["kit_id"]
