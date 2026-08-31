"""Assessments, risk tiering and the outcome summary."""

import pytest

from test_helpers import (
    IC,
    PD,
    ApiErrorId,
    api_client,
    assert_assessment,
    create_assessment_payload,
    create_counselor,
    create_participant,
    make_counselor_headers,
    read_assessments,
    read_outreach_plan,
    read_participant,
    record_assessment,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_assessment_rows_expose_no_updated_at_or_version():
    """PRD 2.4: "There is one deliberate exception: an assessment record is an
    immutable clinical observation. Assessment rows carry only `id` and
    `created_at` — they have neither `updated_at` nor `version`, because nothing in
    the system ever modifies an assessment after it is written."
    PRD 3.2: "The server stamps `recorded_at` from the logical clock and assigns
    `sequence_index`, a one-based counter of that participant's assessments across
    all kinds in creation order — the first assessment ever recorded for a
    participant carries sequence index 1, regardless of its kind."

    Design: Corner/entities/assessment_rows_are_immutable_and_carry_no_version_field
    """
    set_clock()
    participant = create_participant(
        source_type="SELF", decedent_name="Elin Roos", date_of_death="2026-05-20",
        relationship_to_deceased="SPOUSE", loss_type="SUDDEN_DEATH",
        contact_name="Finn Roos", contact_email="finn.roos@example.org")

    first = validate_success(
        api_client.create_assessment(
            participant["id"],
            create_assessment_payload(kind="NEEDS", grief_severity=10,
                                      isolation_index=4, functional_impairment=4),
            IC), 201)
    second = validate_success(
        api_client.create_assessment(
            participant["id"],
            create_assessment_payload(kind="BASELINE", grief_severity=10,
                                      isolation_index=4, functional_impairment=4),
            IC), 201)

    assert first["sequence_index"] == 1
    assert second["sequence_index"] == 2
    assert first["raw_total"] == 18
    assert first["normalized_score"] == pytest.approx(22.50, abs=0.001)
    assert first["recorded_at"] == "2026-09-01T00:00:00.000Z"

    for row in read_assessments(participant["id"]):
        assert_assessment(row)
        assert "version" not in row, "an assessment row must not carry version"
        assert "updated_at" not in row, "an assessment row must not carry updated_at"


def test_assessment_sub_score_above_its_declared_range_is_rejected():
    """PRD 3.2: "Three sub-scores are supplied: `grief_severity`, an integer from 0
    to 40 inclusive; `isolation_index`, an integer from 0 to 20 inclusive; and
    `functional_impairment`, an integer from 0 to 20 inclusive."
    PRD 2.5: "The body conforms to the endpoint's declared input: every required
    field is present, every enum value is a declared member, every integer lies
    inside its declared range, and every array-typed field is an array."

    Design: Corner/entities/assessment_grief_severity_above_range_returns_invalid_request
    """
    set_clock()
    participant = create_participant(
        source_type="SELF", decedent_name="Elin Roos", date_of_death="2026-05-20",
        relationship_to_deceased="SPOUSE", loss_type="SUDDEN_DEATH",
        contact_name="Finn Roos", contact_email="finn.roos@example.org")

    validate_error(
        api_client.create_assessment(
            participant["id"],
            create_assessment_payload(grief_severity=41, isolation_index=4,
                                      functional_impairment=4), IC),
        ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    assert read_assessments(participant["id"]) == []
    refreshed = read_participant(participant["id"])
    assert refreshed["composite_need_index"] == 0
    assert refreshed["service_status"] == "INTAKE"


def test_composite_of_exactly_seventy_tiers_high_and_re_channels_outreach():
    """PRD 3.2: "The composite need index is a weighted blend of the three
    sub-scores, each first expressed as a fraction of its own maximum: grief
    severity out of forty carries half the weight, functional impairment out of
    twenty carries three tenths of the weight, and social isolation out of twenty
    carries the remaining two tenths. That blend is multiplied by one hundred and
    rounded half up to two decimal places to give the composite."
    PRD 3.2: "`risk_tier` then follows from the composite on inclusive lower
    bounds. A composite of 70.00 or above is `HIGH`; a composite of 40.00 or above
    but below 70.00 is `MODERATE`; anything below 40.00 is `LOW`. A composite of
    exactly 70.00 is `HIGH`, and a composite of exactly 40.00 is `MODERATE`."
    PRD 3.2: "And when the recomputed tier lands on `HIGH`, every one of that
    participant's anniversary touchpoints still sitting in `SCHEDULED` or `DUE` is
    re-channelled — its `channel` becomes `PHONE` and its `escalated` flag becomes
    true."

    Design: Corner/calculations/composite_need_index_at_exactly_seventy_lands_in_the_high_tier
    """
    set_clock()
    participant = create_participant(
        source_type="SELF", decedent_name="Elin Roos", date_of_death="2026-06-01",
        relationship_to_deceased="SPOUSE", loss_type="SUDDEN_DEATH",
        contact_name="Finn Roos", contact_email="finn.roos@example.org")

    assessment = validate_success(
        api_client.create_assessment(
            participant["id"],
            create_assessment_payload(kind="NEEDS", grief_severity=32,
                                      isolation_index=12, functional_impairment=12),
            IC), 201)
    assert assessment["raw_total"] == 56
    assert assessment["normalized_score"] == pytest.approx(70.00, abs=0.001)

    refreshed = read_participant(participant["id"])
    assert refreshed["composite_need_index"] == pytest.approx(70.00, abs=0.001)
    assert refreshed["risk_tier"] == "HIGH"
    assert refreshed["outreach_cadence_days"] == 30
    assert refreshed["service_status"] == "ASSESSED"

    plan = read_outreach_plan(participant["id"])
    assert len(plan) == 4
    for row in plan:
        assert row["channel"] == "PHONE", "a HIGH tier re-channels every live touchpoint"
        assert row["escalated"] is True


def test_composite_one_notch_below_the_high_bound_stays_moderate():
    """PRD 3.2: "`risk_tier` then follows from the composite on inclusive lower
    bounds. A composite of 70.00 or above is `HIGH`; a composite of 40.00 or above
    but below 70.00 is `MODERATE`; anything below 40.00 is `LOW`."
    PRD 3.2: "The tier immediately drives the follow-up rhythm:
    `outreach_cadence_days` becomes 90 for a `LOW` tier, 60 for a `MODERATE` tier,
    and 30 for a `HIGH` tier."

    Design: Corner/calculations/composite_need_index_one_step_below_threshold_stays_moderate
    """
    set_clock()
    participant = create_participant(
        source_type="SELF", decedent_name="Elin Roos", date_of_death="2026-06-01",
        relationship_to_deceased="SPOUSE", loss_type="SUDDEN_DEATH",
        contact_name="Finn Roos", contact_email="finn.roos@example.org")

    assessment = validate_success(
        api_client.create_assessment(
            participant["id"],
            create_assessment_payload(kind="NEEDS", grief_severity=32,
                                      isolation_index=12, functional_impairment=11),
            IC), 201)
    assert assessment["raw_total"] == 55
    assert assessment["normalized_score"] == pytest.approx(68.75, abs=0.001)

    refreshed = read_participant(participant["id"])
    assert refreshed["composite_need_index"] == pytest.approx(68.50, abs=0.001)
    assert refreshed["risk_tier"] == "MODERATE"
    assert refreshed["outreach_cadence_days"] == 60

    for row in read_outreach_plan(participant["id"]):
        assert row["channel"] == "EMAIL"
        assert row["escalated"] is False


def test_suicidality_flag_floors_the_composite_at_eighty_five():
    """PRD 3.2: "Only then — never before the rounding — does the safety floor
    apply: when the assessment's `suicidality_flag` is true, the composite is
    raised to 85.00 if it fell below that figure, and left alone if it already
    reached or exceeded it."

    Design: Corner/calculations/suicidality_flag_floors_composite_need_index_at_eighty_five
    """
    set_clock()
    participant = create_participant(
        source_type="SELF", decedent_name="Elin Roos", date_of_death="2026-06-01",
        relationship_to_deceased="SPOUSE", loss_type="SUICIDE",
        contact_name="Finn Roos", contact_email="finn.roos@example.org")

    assessment = validate_success(
        api_client.create_assessment(
            participant["id"],
            create_assessment_payload(kind="NEEDS", instrument="PG13",
                                      grief_severity=10, isolation_index=4,
                                      functional_impairment=4, suicidality_flag=True),
            IC), 201)
    assert assessment["raw_total"] == 18
    assert assessment["normalized_score"] == pytest.approx(22.50, abs=0.001), (
        "the floor lifts the participant's composite, never the assessment's own score")

    refreshed = read_participant(participant["id"])
    assert refreshed["composite_need_index"] == pytest.approx(85.00, abs=0.001)
    assert refreshed["risk_tier"] == "HIGH"
    assert refreshed["outreach_cadence_days"] == 30


def test_exit_assessment_before_any_baseline_is_out_of_sequence():
    """PRD 3.2: "recording an assessment of kind `MIDPOINT` or `EXIT` for a
    participant who has no `BASELINE` assessment on file is refused with
    `ERR_ASSESSMENT_SEQUENCE_INVALID`."
    PRD 3.2: "A `BASELINE` assessment writes its `normalized_score` to the
    participant's `baseline_score`. A `MIDPOINT` or `EXIT` assessment writes its
    `normalized_score` to the participant's `latest_score`, and an `EXIT`
    assessment additionally closes the clinical arc by moving
    `MAINTENANCE → DISCHARGED`."

    Design: Corner/validations/exit_assessment_before_any_baseline_returns_assessment_sequence_invalid
    """
    set_clock()
    participant = create_participant(
        source_type="SELF", decedent_name="Elin Roos", date_of_death="2026-05-20",
        relationship_to_deceased="SPOUSE", loss_type="SUDDEN_DEATH",
        contact_name="Finn Roos", contact_email="finn.roos@example.org")
    record_assessment(participant["id"], kind="NEEDS", grief_severity=20,
                      isolation_index=8, functional_impairment=8)

    exit_payload = create_assessment_payload(kind="EXIT", grief_severity=10,
                                             isolation_index=4,
                                             functional_impairment=4)
    validate_error(
        api_client.create_assessment(participant["id"], exit_payload, IC),
        ApiErrorId.ERR_ASSESSMENT_SEQUENCE_INVALID.value, 422)

    record_assessment(participant["id"], kind="BASELINE", grief_severity=20,
                      isolation_index=8, functional_impairment=8)
    validate_success(
        api_client.create_assessment(participant["id"], exit_payload, IC), 201)

    refreshed = read_participant(participant["id"])
    assert refreshed["baseline_score"] == pytest.approx(45.00, abs=0.001)
    assert refreshed["latest_score"] == pytest.approx(22.50, abs=0.001)
    assert refreshed["composite_need_index"] == pytest.approx(45.00, abs=0.001)
    assert len(read_assessments(participant["id"])) == 3


def test_both_intake_coordinator_and_counselor_may_record_assessments():
    """PRD 3.2: "Clinical assessments are recorded against a participant by an
    `IntakeCoordinator` or a `Counselor`, and each one is an immutable
    observation."
    PRD 3.2: "Recording an assessment answers with HTTP 201."

    Design: Corner/rbac/assessment_creation_is_shared_between_intake_coordinator_and_counselor
    """
    set_clock()
    counselor = create_counselor(full_name="Dr A Marin", license_type="LCSW",
                                 specialties=["SUDDEN_DEATH"])
    participant = create_participant(
        source_type="SELF", decedent_name="Elin Roos", date_of_death="2026-05-20",
        relationship_to_deceased="SPOUSE", loss_type="SUDDEN_DEATH",
        contact_name="Finn Roos", contact_email="finn.roos@example.org")

    first = validate_success(
        api_client.create_assessment(
            participant["id"],
            create_assessment_payload(kind="NEEDS", grief_severity=20,
                                      isolation_index=8, functional_impairment=8),
            IC), 201)
    second = validate_success(
        api_client.create_assessment(
            participant["id"],
            create_assessment_payload(kind="BASELINE", instrument="PG13",
                                      grief_severity=20, isolation_index=8,
                                      functional_impairment=8),
            make_counselor_headers(counselor["id"])), 201)

    assert first["sequence_index"] == 1
    assert second["sequence_index"] == 2
    refreshed = read_participant(participant["id"])
    assert refreshed["service_status"] == "ASSESSED"
    assert refreshed["composite_need_index"] == pytest.approx(45.00, abs=0.001)
    assert refreshed["baseline_score"] == pytest.approx(45.00, abs=0.001)
    assert len(read_assessments(participant["id"])) == 2


def _participant_with_baseline_and_exit():
    """Accepted participant who never enrolled, carrying a BASELINE normalised at
    70.00 and an EXIT normalised at 45.00, so sessions_attended_total is 0."""
    set_clock()
    participant = create_participant(
        source_type="SELF", decedent_name="Elin Roos", date_of_death="2026-05-20",
        relationship_to_deceased="SPOUSE", loss_type="SUDDEN_DEATH",
        contact_name="Finn Roos", contact_email="finn.roos@example.org")
    baseline = record_assessment(participant["id"], kind="BASELINE", instrument="PG13",
                                 grief_severity=32, isolation_index=12,
                                 functional_impairment=12)
    exit_row = record_assessment(participant["id"], kind="EXIT", instrument="PG13",
                                 grief_severity=20, isolation_index=8,
                                 functional_impairment=8)
    return participant, baseline, exit_row


def test_outcome_summary_raw_delta_is_the_plain_score_difference():
    """PRD 3.2: "First, `raw_delta` is the latest observation's normalised score
    minus the baseline observation's normalised score, rounded half up to two
    decimal places; this is the plain difference clinicians quote to families, with
    no correction and no weighting."
    PRD 3.2: "Second, `rtm_correction` accounts for regression to the mean: take
    the baseline observation's normalised score, subtract the programme mean of
    50.0, multiply the difference by 0.15, and round half up to two decimal
    places."

    Design: Difficulty/dual_variant_calc/outcome_raw_delta_vs_attendance_adjusted_delta_on_participant_scores
    """
    participant, baseline, exit_row = _participant_with_baseline_and_exit()
    assert baseline["normalized_score"] == pytest.approx(70.00, abs=0.001)
    assert exit_row["normalized_score"] == pytest.approx(45.00, abs=0.001)

    summary = validate_success(api_client.get_outcome_summary(participant["id"], IC))
    assert summary["baseline_score"] == pytest.approx(70.00, abs=0.001)
    assert summary["latest_score"] == pytest.approx(45.00, abs=0.001)
    assert summary["raw_delta"] == pytest.approx(-25.00, abs=0.001), (
        f"Expected raw_delta -25.00, got {summary['raw_delta']}")
    assert summary["rtm_correction"] == pytest.approx(3.00, abs=0.001), (
        f"Expected rtm_correction 3.00, got {summary['rtm_correction']}")


def test_outcome_summary_attendance_adjusted_delta_diverges_from_the_raw_delta():
    """PRD 3.2: "Third, the attendance weight: `attendance_ratio_capped` is the
    participant's `sessions_attended_total` divided by the eight sessions a full
    course of the programme is expected to deliver, capped so that it never exceeds
    1 — a participant who attended more than eight sessions is treated as having
    attended exactly the full course. `attendance_adjusted_delta` is then the raw
    delta minus the regression correction, multiplied by a weight of 0.6 plus 0.4
    times the capped attendance ratio, rounded half up to two decimal places."
    PRD 3.2: "The summary response carries `participant_id`, `baseline_score`,
    `latest_score`, `raw_delta`, `rtm_correction`, `attendance_ratio_capped`,
    `attendance_adjusted_delta` and `sessions_attended_total`."

    Design: Difficulty/dual_variant_calc/outcome_raw_delta_vs_attendance_adjusted_delta_on_participant_scores
    """
    participant, _, _ = _participant_with_baseline_and_exit()

    summary = validate_success(api_client.get_outcome_summary(participant["id"], IC))
    assert summary["participant_id"] == participant["id"]
    assert summary["sessions_attended_total"] == 0
    assert summary["attendance_ratio_capped"] == pytest.approx(0, abs=0.0001)
    assert summary["attendance_adjusted_delta"] == pytest.approx(-16.80, abs=0.001), (
        f"Expected attendance_adjusted_delta -16.80, got "
        f"{summary['attendance_adjusted_delta']}")
    assert summary["attendance_adjusted_delta"] != summary["raw_delta"], (
        "the two outcome variants must diverge on identical assessment rows")


def test_outcome_summary_without_a_baseline_row_is_refused():
    """PRD 3.2: "If no `BASELINE` row exists, the read is refused with
    `ERR_NO_BASELINE_ASSESSMENT`."
    PRD 3.2: "It selects a baseline and a latest observation from the participant's
    own assessments only."

    Design: Difficulty/boundary_precision_check/outcome_summary_with_empty_baseline_set_is_a_precondition_failure
    """
    set_clock()
    participant = create_participant(
        source_type="SELF", decedent_name="Jonas Peel", date_of_death="2026-07-15",
        relationship_to_deceased="SIBLING", loss_type="OVERDOSE",
        contact_name="Kara Peel", contact_email="kara.peel@example.org")
    record_assessment(participant["id"], kind="NEEDS", grief_severity=10,
                      isolation_index=4, functional_impairment=4)

    validate_error(api_client.get_outcome_summary(participant["id"], IC),
                   ApiErrorId.ERR_NO_BASELINE_ASSESSMENT.value, 422)


def test_a_needs_row_alone_leaves_baseline_and_latest_scores_null():
    """PRD 3.2: "`NEEDS` rows are excluded from both selections."
    PRD 3.2: "The baseline is the participant's earliest `BASELINE` assessment,
    ordered by `recorded_at` ascending and, where two share an instant, by
    `created_at` ascending, taking the first row."

    Design: Difficulty/boundary_precision_check/outcome_summary_with_empty_baseline_set_is_a_precondition_failure
    """
    set_clock()
    participant = create_participant(
        source_type="SELF", decedent_name="Jonas Peel", date_of_death="2026-07-15",
        relationship_to_deceased="SIBLING", loss_type="OVERDOSE",
        contact_name="Kara Peel", contact_email="kara.peel@example.org")
    record_assessment(participant["id"], kind="NEEDS", grief_severity=10,
                      isolation_index=4, functional_impairment=4)

    refreshed = read_participant(participant["id"])
    assert refreshed["baseline_score"] is None, (
        "a NEEDS row must not populate baseline_score")
    assert refreshed["latest_score"] is None
    assert refreshed["composite_need_index"] == pytest.approx(22.50, abs=0.001)
    assert refreshed["risk_tier"] == "LOW"
    validate_error(api_client.get_outcome_summary(participant["id"], IC),
                   ApiErrorId.ERR_NO_BASELINE_ASSESSMENT.value, 422)
