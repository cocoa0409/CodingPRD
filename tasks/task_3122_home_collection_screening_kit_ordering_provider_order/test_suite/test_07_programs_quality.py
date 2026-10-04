"""Programs, cohorts, outreach, exclusion, opt-out cascade, and quality
measure attribution/reporting."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_outreach_event,
    create_kit_for,
    create_order_payload,
    create_outreach_payload,
    create_patient,
    create_program,
    enroll_cohort,
    get_cohort,
    get_kit,
    get_order,
    get_program,
    get_specimen,
    get_success_data,
    make_provider_headers,
    result_cohort_order,
    set_clock,
    setup_program_order_in_lab,
    setup_program_with_cohort,
    validate_error,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["program_admin_headers"]
FA = TEST_USERS["fulfillment_agent_headers"]
LT = TEST_USERS["lab_technician_headers"]


# ---------------------------------------------------------------------------
# Outreach gating (queue A cross-entity dep + queue B validations)
# ---------------------------------------------------------------------------

def test_outreach_on_self_serve_program_rejected(api):
    """PRD §3.1: "Three conditions must hold, in this order: the cohort must
    currently be in `ELIGIBLE` status, else the request fails with
    `ERR_COHORT_INVALID_STATE`; the program's `is_active` must be true, else
    `ERR_PROGRAM_INACTIVE`; and the program's `outreach_mode` must be `PUSH`,
    else `ERR_PROGRAM_MODE_VIOLATION`."

    Design: Difficulty/cross_entity_state_dependency/outreach_requires_program_active_push
    """
    ctx = setup_program_with_cohort(program_overrides={
        "program_code": "G-SS", "outreach_mode": "SELF_SERVE",
    })
    resp = api.dispatch_outreach(
        ctx["program"]["id"], ctx["cohort"]["id"],
        create_outreach_payload(channel="MAIL", template_code="T1"), PA,
    )
    validate_error(resp, ApiErrorId.ERR_PROGRAM_MODE_VIOLATION)
    assert get_cohort(ctx["cohort"]["id"])["status"] == "ELIGIBLE"


def test_outreach_success_advances_cohort_and_records_event(api):
    """PRD §3.1: "On success the server creates an `OutreachEvent` recording
    the `cohort_id`, the `channel`, the `template_code`, and a `sent_at`
    timestamp from the logical clock, and the cohort's status advances
    `ELIGIBLE → OUTREACH_SENT`."

    Design: Difficulty/cross_entity_state_dependency/outreach_requires_program_active_push
    """
    ctx = setup_program_with_cohort()
    event = validate_success(
        api.dispatch_outreach(
            ctx["program"]["id"], ctx["cohort"]["id"],
            create_outreach_payload(channel="SMS", template_code="T2"), PA,
        ),
        expected_status=201,
    )
    assert_outreach_event(event)
    assert event["cohort_id"] == ctx["cohort"]["id"]
    assert event["channel"] == "SMS"
    assert event["template_code"] == "T2"
    assert event["sent_at"]
    assert get_cohort(ctx["cohort"]["id"])["status"] == "OUTREACH_SENT"


def test_outreach_on_inactive_program_rejected(api):
    """PRD §3.1: "Three conditions must hold, in this order: the cohort must
    currently be in `ELIGIBLE` status, else the request fails with
    `ERR_COHORT_INVALID_STATE`; the program's `is_active` must be true, else
    `ERR_PROGRAM_INACTIVE`; and the program's `outreach_mode` must be `PUSH`,
    else `ERR_PROGRAM_MODE_VIOLATION`."

    Design: Corner/validations/outreach_on_inactive_program_rejected
    """
    ctx = setup_program_with_cohort(program_overrides={
        "program_code": "G-OFF", "is_active": False,
    })
    resp = api.dispatch_outreach(
        ctx["program"]["id"], ctx["cohort"]["id"],
        create_outreach_payload(channel="MAIL", template_code="T3"), PA,
    )
    validate_error(resp, ApiErrorId.ERR_PROGRAM_INACTIVE)


def test_outreach_event_immutable_lightweight_row(api):
    """PRD §2.4: "An `OutreachEvent` carries only `id` and `created_at` —
    both `updated_at` and `version` are absent, because an outreach dispatch
    is an immutable fact."

    Design: Corner/entities/outreach_event_immutable_no_update_endpoint
    """
    ctx = setup_program_with_cohort()
    validate_success(
        api.dispatch_outreach(
            ctx["program"]["id"], ctx["cohort"]["id"],
            create_outreach_payload(channel="SMS", template_code="T2"), PA,
        ),
        expected_status=201,
    )
    events, _ = validate_paginated(
        api.list_cohort_outreach_events(ctx["program"]["id"], ctx["cohort"]["id"], PA)
    )
    assert len(events) == 1
    event = events[0]
    assert event["channel"] == "SMS"
    assert event["id"]
    assert event["created_at"]
    assert "version" not in event
    assert "updated_at" not in event


# ---------------------------------------------------------------------------
# Exclusion denominator conservation (queue A compensating_invariant)
# ---------------------------------------------------------------------------

def test_exclusion_drops_member_from_denominator(api):
    """PRD §3.1: "Exclusion sets the cohort's `attributed` flag to false and
    moves the cohort to the terminal `EXCLUDED` status, then recomputes the
    program's counters."
    PRD §3.8: "A program's `attributed_count` is the number of its
    `MemberCohort` rows whose `attributed` flag is true and whose status is
    not `EXCLUDED`".

    Design: Difficulty/compensating_invariant/exclusion_conserves_measure_denominator
    """
    ctx = setup_program_with_cohort()
    create_patient_b = create_patient()
    create_patient_c = create_patient()
    enroll_cohort(ctx["program"], create_patient_b)
    cohort_c = enroll_cohort(ctx["program"], create_patient_c)

    excluded = validate_success(api.exclude_cohort(ctx["program"]["id"], cohort_c["id"], PA))
    assert excluded["status"] == "EXCLUDED"
    assert excluded["attributed"] is False

    program = get_program(ctx["program"]["id"])
    assert program["attributed_count"] == 2
    assert program["adherent_count"] == 0


def test_exclusion_recomputes_attributed_count(api):
    """PRD §3.8: "Note that a cohort that was excluded — whether directly or
    through patient opt-out — drops out of the denominator entirely."
    PRD §3.1: "Exclusion sets the cohort's `attributed` flag to false and
    moves the cohort to the terminal `EXCLUDED` status, then recomputes the
    program's counters."

    Design: Difficulty/compensating_invariant/exclusion_conserves_measure_denominator
    """
    ctx = setup_program_with_cohort()
    patient_b = create_patient()
    cohort_b = enroll_cohort(ctx["program"], patient_b)
    assert get_program(ctx["program"]["id"])["attributed_count"] == 2

    validate_success(api.exclude_cohort(ctx["program"]["id"], cohort_b["id"], PA))
    program = get_program(ctx["program"]["id"])
    assert program["attributed_count"] == 1
    cohort_after = get_cohort(cohort_b["id"])
    assert cohort_after["attributed"] is False
    assert cohort_after["status"] == "EXCLUDED"


# ---------------------------------------------------------------------------
# Result cascade depth 3 (queue A transitive_cascade)
# ---------------------------------------------------------------------------

def test_result_delivery_cascades_order_cohort_program(api):
    """PRD §3.8: "These counters are recomputed whenever a contributing event
    occurs, including when an order carrying the cohort results (which also
    cascades the cohort `ORDERED → SCREENED`)."
    PRD §3.8: "its `adherent_count` is the number of those attributed cohorts
    linked to a `ScreeningOrder` whose `quality_outcome` is
    `ADHERENT_NEGATIVE` or `ADHERENT_POSITIVE_NAVIGATED`."

    Design: Difficulty/transitive_cascade/result_delivery_cascade_depth3
    """
    ctx = setup_program_order_in_lab()
    result_cohort_order(ctx, "NEGATIVE")

    order = get_order(ctx["order"]["id"])
    assert order["status"] == "RESULTED"
    assert order["quality_outcome"] == "ADHERENT_NEGATIVE"
    assert get_cohort(ctx["cohort"]["id"])["status"] == "SCREENED"
    program = get_program(ctx["program"]["id"])
    assert program["adherent_count"] == 1
    assert program["attributed_count"] == 1


def test_result_delivery_kit_consumed_and_active_kit_cleared(api):
    """PRD §3.6: "On success, a cascade runs: the specimen moves `PROCESSING
    → RESULTED`; the kit moves to `CONSUMED` and the order's `active_kit_id`
    is cleared; a `ScreeningResult` is created recording the `order_id`, the
    producing `specimen_id`, the `outcome`, a `resulted_at` timestamp, and a
    `delivered_to_provider_at` timestamp — both stamped from the logical
    clock, since finalization and delivery to the ordering provider happen in
    the same instant; and the order transitions `IN_LAB → RESULTED` with a
    `version` increment."

    Design: Difficulty/transitive_cascade/result_delivery_cascade_depth3
    """
    ctx = setup_program_order_in_lab()
    result = result_cohort_order(ctx, "NEGATIVE")

    assert get_specimen(ctx["specimen"]["id"])["status"] == "RESULTED"
    assert get_kit(ctx["kit"]["id"])["status"] == "CONSUMED"
    order = get_order(ctx["order"]["id"])
    assert order["status"] == "RESULTED"
    assert order.get("active_kit_id") is None
    assert result["order_id"] == order["id"]
    assert result["specimen_id"] == ctx["specimen"]["id"]
    assert result["outcome"] == "NEGATIVE"


# ---------------------------------------------------------------------------
# Quality measure report: combinatorial rate + zero denominator
# ---------------------------------------------------------------------------

def test_quality_measure_rate_with_lapsed_positive(api):
    """PRD §3.8: "The snapshot copies the program's `measure_year`, records
    `numerator` as the program's `adherent_count` at snapshot time and
    `denominator` as its `attributed_count` at snapshot time, computes
    `adherence_rate` as the numerator divided by the denominator rounded to
    four decimal places round-half-up — exactly 0.0000 when the denominator
    is zero".
    PRD §3.8: "A `POSITIVE` result whose navigation is still `PENDING` or
    `SCHEDULED` leaves the order `POSITIVE_NAVIGATION_PENDING`; once
    navigation lapses, the order becomes `POSITIVE_NAVIGATION_LAPSED`."

    Design: Difficulty/combinatorial_formula/quality_measure_rate_threshold_inputs
    """
    set_clock()
    # Member 1: NEGATIVE result (adherent).
    ctx1 = setup_program_order_in_lab(
        program_overrides={"program_code": "G-COMB"},
    )
    result_cohort_order(ctx1, "NEGATIVE")

    # Member 2: POSITIVE result, navigation lapses past the 90-day window.
    patient2 = create_patient()
    cohort2 = enroll_cohort(ctx1["program"], patient2)
    provider = ctx1["provider"]
    order2 = get_success_data(api_client.create_order(
        create_order_payload(patient2["id"], provider["id"],
                             program_id=ctx1["program"]["id"], cohort_id=cohort2["id"]),
        make_provider_headers(provider["id"]),
    ))
    order2 = get_success_data(api_client.confirm_eligibility(order2["id"], PA))
    kit2 = create_kit_for(order2)
    get_success_data(api_client.ship_kit(kit2["id"], FA))
    get_success_data(api_client.return_kit(kit2["id"], FA))
    specimen2 = get_success_data(api_client.accession_specimen(order2["id"], LT))
    get_success_data(api_client.process_specimen(specimen2["id"], LT))
    get_success_data(api_client.record_adequacy(specimen2["id"], {"adequacy": "ADEQUATE"}, LT))
    get_success_data(api_client.result_specimen(specimen2["id"], {"outcome": "POSITIVE"}, LT))

    set_clock("2026-12-15T00:00:00Z")  # past the 2026-11-30 navigation due date
    report = validate_success(api.create_quality_measure_report(ctx1["program"]["id"], PA),
                              expected_status=201)
    assert report["denominator"] == 2
    assert report["numerator"] == 1
    assert float(report["adherence_rate"]) == 0.5
    assert get_order(order2["id"])["quality_outcome"] == "POSITIVE_NAVIGATION_LAPSED"


def test_quality_measure_pending_positive_not_in_numerator(api):
    """PRD §3.8: "its `adherent_count` is the number of those attributed
    cohorts linked to a `ScreeningOrder` whose `quality_outcome` is
    `ADHERENT_NEGATIVE` or `ADHERENT_POSITIVE_NAVIGATED`."
    PRD §3.8: "A `POSITIVE` result whose navigation is still `PENDING` or
    `SCHEDULED` leaves the order `POSITIVE_NAVIGATION_PENDING`".

    Design: Difficulty/combinatorial_formula/quality_measure_rate_threshold_inputs
    """
    set_clock()
    ctx = setup_program_order_in_lab()
    result_cohort_order(ctx, "POSITIVE")

    assert get_order(ctx["order"]["id"])["quality_outcome"] == "POSITIVE_NAVIGATION_PENDING"
    program = get_program(ctx["program"]["id"])
    assert program["attributed_count"] == 1
    assert program["adherent_count"] == 0


def test_adherence_rate_zero_denominator(api):
    """PRD §3.8: "computes `adherence_rate` as the numerator divided by the
    denominator rounded to four decimal places round-half-up — exactly 0.0000
    when the denominator is zero".
    PRD §3.8: "Note that a cohort that was excluded — whether directly or
    through patient opt-out — drops out of the denominator entirely."

    Design: Corner/calculations/adherence_rate_zero_denominator
    """
    ctx = setup_program_with_cohort(program_overrides={"program_code": "G-ZERO"})
    validate_success(api.exclude_cohort(ctx["program"]["id"], ctx["cohort"]["id"], PA))

    report = validate_success(api.create_quality_measure_report(ctx["program"]["id"], PA),
                              expected_status=201)
    assert report["denominator"] == 0
    assert report["numerator"] == 0
    assert float(report["adherence_rate"]) == 0.0


# ---------------------------------------------------------------------------
# Patient opt-out cascade (queue B cross_cutting)
# ---------------------------------------------------------------------------

def test_opt_out_cascades_cohort_exclusion(api):
    """PRD §3.1: "A patient-level opt-out is broader: when a `ProgramAdmin`
    marks a patient `OPTED_OUT`, every cohort row for that patient currently
    in `ELIGIBLE` or `OUTREACH_SENT` is moved to `EXCLUDED` and the affected
    program counters are recomputed."

    Design: Corner/cross_cutting_layers/opt_out_cascades_cohort_exclusion
    """
    g1 = create_program(program_code="G-OO1")
    g2 = create_program(program_code="G-OO2")
    patient = create_patient(external_ref="p-oo")
    c1 = enroll_cohort(g1, patient)
    c2 = enroll_cohort(g2, patient)
    validate_success(
        api.dispatch_outreach(g2["id"], c2["id"],
                              create_outreach_payload(channel="PHONE", template_code="T4"), PA),
        expected_status=201,
    )

    updated = validate_success(api.opt_out_patient(patient["id"], PA))
    assert updated["status"] == "OPTED_OUT"

    for cohort in (c1, c2):
        after = get_cohort(cohort["id"])
        assert after["status"] == "EXCLUDED"
        assert after["attributed"] is False
    assert get_program(g1["id"])["attributed_count"] == 0
    assert get_program(g2["id"])["attributed_count"] == 0
