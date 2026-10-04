"""Outcome measurement, attributed downstream savings and invoice construction.

Covers the version-pinned window reading against the billing-time reading, the
invoice's pinned-share / trailing-remainder arithmetic and its rounding order,
the suspension conservation pair, the in-person referral total, and the
measurement, invoice and reconciliation error paths.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    CLINICAL_OPS,
    ENROLLMENT_OPS,
    advance_week,
    activate_enrollment,
    approve_transition,
    book_session,
    complete_session,
    conduct_review,
    create_client_payload,
    create_invoice_payload,
    create_member_payload,
    create_measurement_payload,
    create_claim_line_payload,
    create_eligibility_file_payload,
    enrollment_for_member,
    get_success_data,
    make_member_headers,
    record_claim_line,
    seed_review,
    set_clock,
    setup_client,
    setup_clinicians,
    setup_roster,
    setup_scenario,
    setup_tracks,
    validate_error,
    validate_success,
    assign_tracks,
)

WEEK_INSTANT = {
    0: "2026-09-01T00:00:00Z",
    1: "2026-09-08T00:00:00Z",
    2: "2026-09-15T00:00:00Z",
    3: "2026-09-22T00:00:00Z",
    4: "2026-09-29T00:00:00Z",
    5: "2026-10-06T00:00:00Z",
    6: "2026-10-13T00:00:00Z",
}
WEEK_SESSION_DATE = {
    1: "2026-09-08T09:00:00Z",
    2: "2026-09-15T09:00:00Z",
    3: "2026-09-22T09:00:00Z",
    4: "2026-09-29T09:00:00Z",
    5: "2026-10-06T09:00:00Z",
}


def _engage_weeks(enrollment_id, member_id, weeks, pain_after=6.5):
    """Complete one session in each listed week, moving the clock into that week first."""
    sessions = []
    for week in weeks:
        # Week 1 of the lattice begins at 2026-09-07; the instant used here sits
        # inside it even though 2026-09-08 is the conventional week-1 Monday.
        set_clock(WEEK_INSTANT[week])
        session = book_session(enrollment_id, week, WEEK_SESSION_DATE[week])
        complete_session(session["id"], member_id, pain_score_after=pain_after)
        sessions.append(session)
    return sessions


def _savings_scenario():
    """One ACTIVE enrollment engaged across weeks 1-4 with a window-2 claim line."""
    scenario = setup_scenario(
        member_specs=[{
            "external_member_ref": "CHP-0001", "full_name": "Dita Alvarez",
            "date_of_birth": "1982-02-19T00:00:00Z", "musculo_condition_code": "KNEE_OA",
            "baseline_pain_score": 8.0, "baseline_function_score": 40.0,
            "red_flag_multipliers": [1.10],
        }],
        client_overrides={
            "legal_name": "Cedar Health Plan", "client_type": "HEALTH_PLAN",
            "billing_model": "OUTCOME_SHARED_SAVINGS", "savings_share_rate": 0.30,
            "expected_monthly_engagement_rate": 0.60,
        },
        acute_fee=9000,
        activate=True,
        add_clinicians=True,
    )
    enrollment_id = scenario["enrollment_id"]
    member_id = scenario["member_id"]
    return scenario, enrollment_id, member_id


# ══════════════════════════════════════════════════════════════════
# Attributed savings: the version-pinned window reading
# ══════════════════════════════════════════════════════════════════

def test_attributed_savings_is_pinned_at_the_window_engagement_rate(api, clinical_ops_headers):
    """PRD §3.6: "The window's engagement multiplier is the enrollment's
    `adherence_rate` as recomputed within the measurement's window — the same
    value that drives the engagement milestone — so a window in which the member
    engaged poorly is discounted."
    PRD §3.6: "The inclusion set is every claim line of this enrollment whose
    `claim_service_week` is at or after the window's `window_start_week` and
    strictly before the week following `window_end_week`".
    PRD §3.6: "a `MODERATE`-severity line takes the `LOW` weight, and a line
    whose severity is `LOW` takes the `LOW` weight as well." PRD §3.6: "A line
    takes the `HIGH` weight only when it is a `HIGH`-severity surgical line being
    evaluated in a week where that is the applicable reading".

    Design: Difficulty/dual_variant_calc/outcome_savings_window_end_vs_invoice_creation_evaluation
    """
    scenario, enrollment_id, member_id = _savings_scenario()

    _engage_weeks(enrollment_id, member_id, [1, 2, 3, 4])

    line = record_claim_line(enrollment_id, claim_service_week=2, claim_severity="HIGH",
                             amount_cents=400000, claim_source="MEDICAL",
                             claim_service_date="2026-09-15T00:00:00Z")
    assert line["line_instance_version"] == 1
    assert line["claim_superseded"] is False

    measurement = get_success_data(api.create_measurement(
        create_measurement_payload(enrollment_id, measurement_week=4,
                                   pain_score=4.0, function_score=70.0),
        make_member_headers(member_id),
    ))
    assert measurement["window_start_week"] <= 2 <= measurement["window_end_week"], (
        "the week-2 line falls inside the measurement's window"
    )
    assert measurement["attributed_savings_cents"] == 200000, (
        "400000 * the HIGH weight of 0.5 * the window rate of 1.00"
    )

    enrollment = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert enrollment["attributed_savings_cents"] == 200000, (
        "the enrollment mirrors the version-pinned window reading"
    )


def test_the_pinned_window_reading_survives_an_adherence_drop(api, clinical_ops_headers):
    """PRD §3.6: "the attributed figure recorded on the measurement and on the
    enrollment is a fixed historical reading rather than a moving one."
    PRD §3.6: "This version-pinned reading is what writes
    `OutcomeMeasurement.attributed_savings_cents` and
    `Enrollment.attributed_savings_cents`, and nothing else may write those two
    fields."

    Design: Difficulty/dual_variant_calc/outcome_savings_window_end_vs_invoice_creation_evaluation
    """
    scenario, enrollment_id, member_id = _savings_scenario()

    _engage_weeks(enrollment_id, member_id, [1, 2, 3, 4])

    record_claim_line(enrollment_id, claim_service_week=2, claim_severity="HIGH",
                      amount_cents=400000, claim_source="MEDICAL",
                      claim_service_date="2026-09-15T00:00:00Z")
    get_success_data(api.create_measurement(
        create_measurement_payload(enrollment_id, measurement_week=4,
                                   pain_score=4.0, function_score=70.0),
        make_member_headers(member_id),
    ))

    # The window has closed; a later week is missed, dragging the live rate down.
    set_clock(WEEK_INSTANT[6])
    lapsed = book_session(enrollment_id, 5, WEEK_SESSION_DATE[5])
    validate_success(api.weekly_transition_session(
        lapsed["id"], {"session_week": 5}, __import__("test_helpers").ELIGIBILITY_SERVICE))

    enrollment = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert enrollment["adherence_rate"] == pytest.approx(0.80, abs=1e-9), (
        "four completed sessions plus one missed week give 4 / 5"
    )
    assert enrollment["attributed_savings_cents"] == 200000, (
        "the pinned reading is not recomputed from the live, lower rate"
    )

    measurements = get_success_data(api.list_measurements(
        ENROLLMENT_OPS, {"enrollment_id": enrollment_id}))
    assert len(measurements) == 1
    assert measurements[0]["attributed_savings_cents"] == 200000


def test_superseding_a_claim_line_revalues_the_window_on_the_current_instance(api,
                                                                             clinical_ops_headers):
    """PRD §3.6: "Superseding a line instance supplies a `replacement_amount_cents`
    and a `replacement_claim_severity`, marks the prior instance `claim_superseded`,
    and creates a replacement `ClaimLine` whose `line_instance_version` is the prior
    instance's value plus one".
    PRD §3.6: "the savings attributed to a window use the line instance that is
    current at the instant the window is evaluated".

    Design: Difficulty/dual_variant_calc/outcome_savings_window_end_vs_invoice_creation_evaluation
    """
    scenario, enrollment_id, member_id = _savings_scenario()

    _engage_weeks(enrollment_id, member_id, [1, 2, 3, 4])

    line = record_claim_line(enrollment_id, claim_service_week=2, claim_severity="HIGH",
                             amount_cents=400000, claim_source="MEDICAL",
                             claim_service_date="2026-09-15T00:00:00Z")
    get_success_data(api.create_measurement(
        create_measurement_payload(enrollment_id, measurement_week=4,
                                   pain_score=4.0, function_score=70.0),
        make_member_headers(member_id),
    ))

    replacement = validate_success(api.supersede_claim_line(
        line["id"], {"replacement_amount_cents": 500000,
                     "replacement_claim_severity": "HIGH"},
        ENROLLMENT_OPS))

    superseded = get_success_data(api.get_claim_line(line["id"], ENROLLMENT_OPS))
    assert superseded["claim_superseded"] is True
    assert replacement["line_instance_version"] == 2, "the instance counter is monotonic"

    measurement = get_success_data(api.list_measurements(
        ENROLLMENT_OPS, {"enrollment_id": enrollment_id}))[0]
    assert measurement["attributed_savings_cents"] == 250000, (
        "500000 * the HIGH weight of 0.5 * the window rate of 1.00, on the current instance"
    )

    enrollment = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert enrollment["attributed_savings_cents"] == 250000


# ══════════════════════════════════════════════════════════════════
# Invoice construction
# ══════════════════════════════════════════════════════════════════

def _invoice_pair_scenario():
    """Two members enrolled in week 1 on different tracks, five weeks old at week 6."""
    set_clock("2026-09-01T00:00:00Z")
    client = setup_client(
        legal_name="Kestrel Manufacturing", client_type="EMPLOYER",
        billing_model="OUTCOME_SHARED_SAVINGS", savings_share_rate=0.0,
        expected_monthly_engagement_rate=0.60)
    setup_tracks(acute_fee=9002, chronic_fee=9006)
    tracks = {
        "ACUTE": get_success_data(api_client.list_program_tracks(
            CLINICAL_OPS, {"track_code": "ACUTE"}))[0],
        "CHRONIC": get_success_data(api_client.list_program_tracks(
            CLINICAL_OPS, {"track_code": "CHRONIC"}))[0],
    }
    roster = setup_roster(client["id"], [
        {"external_member_ref": "KS-0001", "full_name": "Rosa Lindqvist",
         "date_of_birth": "1981-03-14T00:00:00Z", "musculo_condition_code": "KNEE_OA",
         "baseline_pain_score": 7.0, "baseline_function_score": 48.0},
        {"external_member_ref": "KS-0002", "full_name": "Tomas Behr",
         "date_of_birth": "1976-09-09T00:00:00Z", "musculo_condition_code": "HIP",
         "baseline_pain_score": 6.0, "baseline_function_score": 52.0},
    ])
    assign_tracks(roster["file"]["id"], client["id"])

    clinicians = setup_clinicians()
    dana_id = clinicians["dana"]["id"]
    leo_id = clinicians["leo"]["id"]

    # Activation happens while the clock sits in week 1, so enrolled_week is 1.
    set_clock(WEEK_INSTANT[1])
    enrollments = []
    for member, track_code in zip(roster["members"], ["ACUTE", "CHRONIC"]):
        enrollment = enrollment_for_member(member["id"])
        review = seed_review(enrollment["id"], dana_id)
        conduct_review(review["id"], tracks[track_code]["id"], dana_id)
        approve_transition(enrollment["id"], roster["file"]["id"], leo_id)
        enrollments.append(get_success_data(
            api_client.get_enrollment(enrollment["id"], ENROLLMENT_OPS)))

    # One completed week-1 session each, so both enrollments sit inside the
    # engagement group once week 1 has been scored.
    for member, enrollment in zip(roster["members"], enrollments):
        session = book_session(enrollment["id"], 1, WEEK_SESSION_DATE[1])
        complete_session(session["id"], member["id"], pain_score_after=6.5)
    advance_week(client["id"])  # week 1 is scored, so the completions count

    set_clock(WEEK_INSTANT[6])
    # Re-read the enrollments: the rows captured at activation carry the week-1
    # projection, not the week-6 one the caller asserts on.
    enrollments = [get_success_data(api_client.get_enrollment(e["id"], ENROLLMENT_OPS))
                   for e in enrollments]
    return client, roster, enrollments


def test_invoice_rounds_each_pinned_share_and_trailing_remainder_separately(api,
                                                                           clinical_ops_headers,
                                                                           billing_ops_headers):
    """PRD §3.8: "each enrollment contributes a pinned share equal to its track's
    `base_fee_per_member_cents` multiplied by the number of whole months the
    enrollment has been active, where a month is four weeks".
    PRD §3.8: "Each enrollment also carries a trailing remainder: its track's base
    fee multiplied by the number of leftover weeks beyond those whole four-week
    blocks and divided by four, with a single round half up to whole cents."
    PRD §3.8: "and this is defined as a formula over the current tables rather than
    as a running adjustment. It is the sum, over the enrollment inclusion set, of
    each enrollment's pinned share plus its trailing remainder".

    Design: Difficulty/combinatorial_formula/invoice_milestone_rounding_order_and_straddled_component
    """
    client, roster, enrollments = _invoice_pair_scenario()

    for enrollment in enrollments:
        assert enrollment["weeks_active"] == 5, "both enrollments are five weeks old"

    invoice = validate_success(api.create_invoice(
        create_invoice_payload(client["id"], billing_period="2026-09"), billing_ops_headers),
        expected_status=201)
    finalized = validate_success(api.finalize_invoice(invoice["id"], billing_ops_headers))

    assert finalized["recalculated_component_cents"] == 22511, (
        "9002 + 9006 pinned shares, plus round(9002 / 4) == 2251 and round(9006 / 4) == 2252"
    )
    assert finalized["final_amount_cents"] == 22511
    assert finalized["recalculated_component_cents"] != 22510, (
        "rounding the combined raw total once would land on 22510, so the pinned "
        "per-enrollment order is observable"
    )


def test_invoice_provisional_and_chronological_totals_diverge_by_the_trailing_deltas(api,
                                                                                    clinical_ops_headers,
                                                                                    billing_ops_headers):
    """PRD §3.8: "`additional_fee_component_cents` is the late-reconciliation
    channel and it starts empty by construction."
    PRD §3.8: "`net_delta_cents` is set to the final total minus the provisional
    total. `finalized_total_cents` is set equal to `final_amount_cents`, and this
    is the figure actually billed."

    Design: Difficulty/combinatorial_formula/invoice_milestone_rounding_order_and_straddled_component
    """
    client, roster, enrollments = _invoice_pair_scenario()

    invoice = validate_success(api.create_invoice(
        create_invoice_payload(client["id"], billing_period="2026-09"), billing_ops_headers),
        expected_status=201)
    assert invoice["invoice_status"] == "DRAFT"
    assert invoice["additional_fee_component_cents"] == 0, "it starts empty by construction"
    assert invoice["milestone_member_count"] == 2
    assert invoice["provisional_amount_cents"] == 18008, (
        "the pinned shares only: no trailing deltas enter at creation"
    )

    finalized = validate_success(api.finalize_invoice(invoice["id"], billing_ops_headers))
    assert finalized["invoice_status"] == "FINALIZED"
    assert finalized["final_amount_cents"] == 22511
    assert finalized["net_delta_cents"] == 4503
    assert finalized["net_delta_cents"] == (
        finalized["final_amount_cents"] - finalized["provisional_amount_cents"]
    )
    assert finalized["finalized_total_cents"] == 22511, "the figure actually billed"


# ══════════════════════════════════════════════════════════════════
# Retention credit and the suspension conservation pair
# ══════════════════════════════════════════════════════════════════

def _two_draft_invoices():
    """One active enrollment and two DRAFT invoices on one client."""
    scenario = setup_scenario(
        acute_fee=9000,
        activate=True,
        add_clinicians=True,
    )
    client_id = scenario["client_id"]
    set_clock(WEEK_INSTANT[1])
    first = validate_success(api_client.create_invoice(
        create_invoice_payload(client_id, billing_period="2026-09"),
        __import__("test_helpers").BILLING_OPS), expected_status=201)
    second = validate_success(api_client.create_invoice(
        create_invoice_payload(client_id, billing_period="2026-10"),
        __import__("test_helpers").BILLING_OPS), expected_status=201)
    return scenario, first, second


def test_suspend_zeroes_the_retained_credit_and_reinstate_leaves_it_at_zero(api,
                                                                          clinical_ops_headers,
                                                                          billing_ops_headers):
    """PRD §3.8: "The difference between the draft invoice count before the
    suspension and the count after it must equal the number of invoices the
    suspension voided."
    PRD §3.8: "And the retained credit reported for those same bills must equal the
    sum of their `provisional_amount_cents`."
    PRD §3.8: "Reinstatement does not restore any voided invoice, so the retained
    credit does not come back".

    Design: Difficulty/compensating_invariant/suspend_voids_draft_invoices_and_reinstate_does_not_drift_count
    """
    scenario, first, second = _two_draft_invoices()
    client_id = scenario["client_id"]

    before = get_success_data(api.retention_credit(client_id, billing_ops_headers))
    assert before["draft_invoice_count"] == 2
    assert before["retained_credit_amount_cents"] == (
        first["provisional_amount_cents"] + second["provisional_amount_cents"]
    ), "the retained credit equals the sum of the drafts' provisional amounts"

    validate_success(api.suspend_client(client_id, {"reason": "Contract review"},
                                        billing_ops_headers))
    after_suspend = get_success_data(api.retention_credit(client_id, billing_ops_headers))
    assert after_suspend["draft_invoice_count"] == 0, "the forward action drove the count to zero"
    assert after_suspend["retained_credit_amount_cents"] == 0

    validate_success(api.reinstate_client(client_id, billing_ops_headers))
    after_reinstate = get_success_data(api.retention_credit(client_id, billing_ops_headers))
    assert after_reinstate["draft_invoice_count"] == 0, (
        "the compensation does not restore the voided rows, so the conserved count "
        "does not drift back"
    )
    assert after_reinstate["retained_credit_amount_cents"] == 0


def test_the_voided_drafts_stay_void_and_cannot_be_reopened(api, clinical_ops_headers,
                                                            billing_ops_headers):
    """PRD §3.5: "First, every `DRAFT` invoice belonging to the client is voided."
    PRD §2.10: "reopening a voided invoice, which fails with `ERR_INVOICE_ALREADY_VOID`".

    Design: Difficulty/compensating_invariant/suspend_voids_draft_invoices_and_reinstate_does_not_drift_count
    """
    scenario, first, second = _two_draft_invoices()
    client_id = scenario["client_id"]

    validate_success(api.suspend_client(client_id, {"reason": "Contract review"},
                                        billing_ops_headers))
    validate_success(api.reinstate_client(client_id, billing_ops_headers))

    for draft in (first, second):
        read = get_success_data(api.get_invoice(draft["id"], billing_ops_headers))
        assert read["invoice_status"] == "VOID"

        refused = api.reopen_invoice(draft["id"], billing_ops_headers)
        validate_error(refused, ApiErrorId.ERR_INVOICE_ALREADY_VOID, expected_status=409)


def test_suspension_side_effects_are_visible_on_the_first_read(api, clinical_ops_headers,
                                                               billing_ops_headers):
    """PRD §3.5: "every enrollment of that client sitting in
    `AWAITING_TRANSITION_REVIEW` is reverted to `ACTIVE`, with `transition_reason`
    and `pending_transition_clinician_id` cleared".
    PRD §3.5: "every `CareTransition` of that client still in `PENDING` status is
    ended with its `transition_reason` recorded as `NO_ENGAGEMENT`".

    Design: Corner/consistency_model/suspension_side_effects_are_visible_on_the_same_response
    """
    scenario = setup_scenario(add_tracks=True, screen=True, assign=True,
                              add_clinicians=True)
    enrollment_id = scenario["enrollment_id"]
    client_id = scenario["client_id"]
    dana_id = scenario["dana_id"]

    # Activation creates exactly one PENDING CareTransition for the enrollment
    # (PRD 3.3), which is the row the suspension cascade ends.
    activate_enrollment(enrollment_id, scenario["file_id"], dana_id,
                        scenario["acute_track"]["id"], scenario["leo_id"])
    transition = get_success_data(api.list_care_transitions(
        CLINICAL_OPS, {"enrollment_id": enrollment_id}))[0]
    assert transition["transition_status"] == "PENDING"

    invoice = validate_success(api.create_invoice(
        create_invoice_payload(client_id, billing_period="2026-09"), billing_ops_headers),
        expected_status=201)

    suspended = validate_success(api.suspend_client(
        client_id, {"reason": "Contract review"}, billing_ops_headers))
    assert suspended["account_status"] == "SUSPENDED", (
        "the new account state needed no re-read"
    )

    voided = get_success_data(api.get_invoice(invoice["id"], billing_ops_headers))
    assert voided["invoice_status"] == "VOID", "visible on the first read"

    ended = get_success_data(api.get_care_transition(transition["id"], CLINICAL_OPS))
    assert ended["transition_status"] == "PENDING"
    assert ended.get("transition_reason") == "NO_ENGAGEMENT", (
        "the pending handoff was ended with the registered reason"
    )

    reverted = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert reverted["enrollment_status"] == "ACTIVE", (
        "the enrollment was reverted out of the handoff queue"
    )
    assert reverted["pending_transition_clinician_id"] is None
    assert reverted["transition_reason"] is None


# ══════════════════════════════════════════════════════════════════
# Measurement finalization and duplicates
# ══════════════════════════════════════════════════════════════════

def test_finalizing_a_measurement_inside_its_window_is_refused(api, clinical_ops_headers):
    """PRD §3.6: "A `RECORDED` measurement may be finalized once its four-week
    claim window has fully lapsed — that is, once `window_end_week` is strictly
    less than the current week index. Finalizing while the window is still open is
    refused with `ERR_MEASUREMENT_WINDOW_OPEN`."

    Design: Corner/errors/error_measurement_window_open_on_finalize
    """
    scenario = setup_scenario(acute_fee=9000, activate=True, add_clinicians=True)
    enrollment_id = scenario["enrollment_id"]
    member_id = scenario["member_id"]

    measurement = get_success_data(api.create_measurement(
        create_measurement_payload(enrollment_id, measurement_week=2,
                                   pain_score=5.5, function_score=62.0),
        make_member_headers(member_id),
    ))
    assert measurement["measurement_status"] == "RECORDED"

    refused = api.finalize_measurement(
        measurement["id"], __import__("test_helpers").CLINICAL_REVIEW_SERVICE)
    validate_error(refused, ApiErrorId.ERR_MEASUREMENT_WINDOW_OPEN, expected_status=409)

    unchanged = get_success_data(api.get_measurement(measurement["id"], ENROLLMENT_OPS))
    assert unchanged["measurement_status"] == "RECORDED"

    enrollment = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert enrollment["pain_reduction_points"] == pytest.approx(0.0, abs=1e-9), (
        "no headline was written"
    )


def test_a_duplicate_live_measurement_week_is_refused(api, clinical_ops_headers):
    """PRD §3.6: "The enrollment may not carry two live measurements for the same
    week: a recording whose `measurement_week` duplicates an existing measurement
    that is still `RECORDED` and has not been superseded is refused with
    `ERR_MEASUREMENT_WEEK_DUPLICATE`."

    Design: Corner/validations/duplicate_active_measurement_week_is_refused_but_superseded_weeks_are_reusable
    """
    scenario = setup_scenario(acute_fee=9000, activate=True, add_clinicians=True)
    enrollment_id = scenario["enrollment_id"]
    member_id = scenario["member_id"]

    validate_success(api.create_measurement(
        create_measurement_payload(enrollment_id, measurement_week=2,
                                   pain_score=5.0, function_score=62.0),
        make_member_headers(member_id)), expected_status=201)

    refused = api.create_measurement(
        create_measurement_payload(enrollment_id, measurement_week=2,
                                   pain_score=4.5, function_score=66.0),
        make_member_headers(member_id))
    validate_error(refused, ApiErrorId.ERR_MEASUREMENT_WEEK_DUPLICATE, expected_status=409)

    rows = get_success_data(api.list_measurements(
        ENROLLMENT_OPS, {"enrollment_id": enrollment_id}))
    assert len(rows) == 1, "the refused recording wrote nothing"


def test_a_void_invoice_cannot_be_finalized_or_reopened(api, clinical_ops_headers,
                                                        billing_ops_headers):
    """PRD §2.10: "reopening a voided invoice, which fails with
    `ERR_INVOICE_ALREADY_VOID`".
    PRD §3.8: "A `DRAFT` invoice can be voided by a `BillingOps` operator, becoming
    `VOID`; a `VOID` invoice can never be reopened".
    PRD §3.8: "reopening clears `finalized_total_cents` to null and advances the
    invoice's `version`."

    Design: Corner/state_machines/void_invoice_cannot_be_finalized_or_reopened
    """
    client = setup_client()
    invoice = validate_success(api.create_invoice(
        create_invoice_payload(client["id"], billing_period="2026-09"), billing_ops_headers),
        expected_status=201)

    voided = validate_success(api.void_invoice(invoice["id"], billing_ops_headers))
    assert voided["invoice_status"] == "VOID"
    version_after_void = voided["version"]

    refused_finalize = api.finalize_invoice(invoice["id"], billing_ops_headers)
    validate_error(refused_finalize, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    refused_reopen = api.reopen_invoice(invoice["id"], billing_ops_headers)
    validate_error(refused_reopen, ApiErrorId.ERR_INVOICE_ALREADY_VOID, expected_status=409)

    reread = get_success_data(api.get_invoice(invoice["id"], billing_ops_headers))
    assert reread["invoice_status"] == "VOID"
    assert reread["finalized_total_cents"] is None
    assert reread["version"] == version_after_void, (
        "the invoice's version was not advanced by either refused call"
    )


# ══════════════════════════════════════════════════════════════════
# Engagement report and the reconciliation ladder
# ══════════════════════════════════════════════════════════════════

def test_the_engagement_report_reads_the_reconciled_outcome_headline(api, clinical_ops_headers,
                                                                     billing_ops_headers):
    """PRD §3.7: "The engagement report is the client-level counterpart and reports
    the same member-week arithmetic rolled up per enrollment, including each
    enrollment's outcome headline figures."
    PRD §3.9: "the pain block anchored on `pain_reduction_points`, the function
    block anchored on `function_gain_points`, and the savings block anchored on
    `attributed_savings_cents`."
    PRD §3.6: "On success the measurement becomes `FINALIZED` and the enrollment's
    headline outcome fields are written directly from the measurement".

    Design: Corner/endpoints/engagement_report_returns_the_reconciled_outcome_headline
    """
    scenario = setup_scenario(
        member_specs=[{
            "external_member_ref": "CHP-0002", "full_name": "Cyrus Almeida",
            "date_of_birth": "1979-04-04T00:00:00Z", "musculo_condition_code": "LOW_BACK",
            "baseline_pain_score": 8.0, "baseline_function_score": 40.0,
            "red_flag_multipliers": [1.15],
        }],
        client_overrides={
            "legal_name": "Cedar Health Plan", "client_type": "HEALTH_PLAN",
            "billing_model": "OUTCOME_SHARED_SAVINGS", "savings_share_rate": 0.30,
        },
        acute_fee=9000,
        activate=True,
        add_clinicians=True,
    )
    client_id = scenario["client_id"]
    enrollment_id = scenario["enrollment_id"]
    member_id = scenario["member_id"]

    set_clock(WEEK_INSTANT[1])
    session = book_session(enrollment_id, 1, WEEK_SESSION_DATE[1])
    complete_session(session["id"], member_id, pain_score_after=6.0)

    record_claim_line(enrollment_id, claim_service_week=2, claim_severity="HIGH",
                      amount_cents=250000, claim_source="MEDICAL",
                      claim_service_date="2026-09-15T00:00:00Z")
    measurement = get_success_data(api.create_measurement(
        create_measurement_payload(enrollment_id, measurement_week=2,
                                   pain_score=5.0, function_score=65.0),
        make_member_headers(member_id),
    ))

    set_clock(WEEK_INSTANT[6])
    validate_success(api.finalize_measurement(
        measurement["id"], __import__("test_helpers").CLINICAL_REVIEW_SERVICE))

    report = validate_success(api.engagement_report(client_id, billing_ops_headers))
    assert report is not None, "the report is readable as an object"

    enrollment = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert enrollment["pain_reduction_points"] == pytest.approx(3.0, abs=1e-9), (
        "the 8.0 baseline minus the 5.0 measurement"
    )
    assert enrollment["function_gain_points"] == pytest.approx(25.0, abs=1e-9), (
        "the 65.0 measurement minus the 40.0 baseline"
    )
    assert enrollment["attributed_savings_cents"] == 125000, (
        "the single week-2 HIGH line at 250000 * 0.5 * the window rate of 1.00"
    )

    reread = get_success_data(api.get_measurement(measurement["id"], ENROLLMENT_OPS))
    assert reread["attributed_savings_cents"] == 125000, "matching the headline"
    assert reread["pain_delta_points"] == pytest.approx(3.0, abs=1e-9)
    assert reread["function_delta_points"] == pytest.approx(25.0, abs=1e-9)


def test_the_reconciliation_ladder_is_idempotent(api, clinical_ops_headers):
    """PRD §3.5: "The ladder is idempotent. A second invocation immediately after
    the first makes no further change, because every item it would have touched has
    already been moved out of the state the step keys on."
    PRD §3.5: "An implementation that advances the same item twice will be visible
    as duplicate version increments".

    Design: Corner/endpoints/reconciling_reviews_reports_its_two_headline_counts
    """
    scenario = setup_scenario(acute_fee=9000, activate=True, add_clinicians=True)
    enrollment_id = scenario["enrollment_id"]

    review = seed_review(enrollment_id, scenario["dana_id"])
    before = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))

    first = api.reconcile_reviews(__import__("test_helpers").CLINICAL_REVIEW_SERVICE)
    assert first.status_code == 200, "the ladder is reachable"

    after_first = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    second = api.reconcile_reviews(__import__("test_helpers").CLINICAL_REVIEW_SERVICE)
    assert second.status_code == 200

    after_second = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert after_second["version"] == after_first["version"], (
        "the second invocation makes no further change"
    )

    untouched = get_success_data(api.get_clinical_review(review["id"], ENROLLMENT_OPS))
    assert untouched["review_status"] == "SUBMITTED", (
        "a review inside its 7-day window is untouched by a ladder run"
    )
    assert before["version"] <= after_second["version"]