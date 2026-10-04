"""Breadth tests: grant reporting aggregates, periods, and tier selection."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data,
    set_clock, create_affiliate, create_affiliate_payload, create_fee_tier,
    create_catalog_entry, create_provider, create_license,
    create_patient, create_assessment, create_encounter,
    setup_tx_clinic, setup_patient_with_assessment, setup_assessed_encounter,
    TEST_USERS, FPL_INCOME_H4_PCT_48, FPL_INCOME_H4_PCT_153,
    FPL_INCOME_H1_PCT_265,
)

ADMIN = TEST_USERS["grant_admin_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]
CLINICIAN = TEST_USERS["clinician_headers"]


def _complete_encounter(enc_id):
    get_success_data(api_client.start_encounter(enc_id, CLINICIAN))
    get_success_data(api_client.complete_encounter(enc_id, CLINICIAN))


def test_grant_quota_exact_equality_counts_as_met(api):
    """PRD §3.10: "`low_income_quota_met` is `true` when
    `low_income_encounter_count` multiplied by 100 is greater than or equal
    to `encounter_count` multiplied by the affiliate's
    `low_income_priority_quota`; exact equality counts as met".

    Two low-income encounters of five against quota 40 gives
    200 >= 200 -> quota met.

    Design: Corner/calculations/grant_quota_exact_equality_counts_as_met
    """
    set_clock("2026-09-01T00:00:00Z")
    clinic = setup_tx_clinic(quota=40, full_fee_cents=20000)
    aff = clinic["affiliate"]

    slots = [
        ("Q-1", FPL_INCOME_H4_PCT_48, "2026-09-10T09:00:00Z", "2026-09-10T09:30:00Z"),
        ("Q-2", FPL_INCOME_H4_PCT_48, "2026-09-10T09:30:00Z", "2026-09-10T10:00:00Z"),
        ("Q-3", FPL_INCOME_H4_PCT_153, "2026-09-10T10:00:00Z", "2026-09-10T10:30:00Z"),
        ("Q-4", FPL_INCOME_H4_PCT_153, "2026-09-10T10:30:00Z", "2026-09-10T11:00:00Z"),
        ("Q-5", FPL_INCOME_H4_PCT_153, "2026-09-10T11:00:00Z", "2026-09-10T11:30:00Z"),
    ]
    enc_ids = []
    for ext_ref, income, start, end in slots:
        patient, _asm = setup_patient_with_assessment(
            clinic, income_cents=income, household_size=4,
            external_ref=ext_ref,
        )
        enc = create_encounter(patient["id"], clinic["provider"]["id"],
                               scheduled_start=start, scheduled_end=end)
        enc_ids.append(enc["id"])
    set_clock("2026-09-10T12:00:00Z")
    for enc_id in enc_ids:
        _complete_encounter(enc_id)
    set_clock("2026-10-02T00:00:00Z")

    report = validate_success(
        api_client.create_grant_report(
            aff["id"],
            {"period_start": "2026-09-01T00:00:00Z",
             "period_end": "2026-10-01T00:00:00Z",
             "valuation_variant": "FIFO",
             "expected_affiliate_version": aff["version"]},
            ADMIN,
        ),
        201,
    )
    assert report["encounter_count"] == 5
    assert report["low_income_encounter_count"] == 2
    assert report["low_income_quota_met"] is True, (
        "200 >= 5 x 40 = 200 — exact equality counts as met"
    )


def test_grant_quota_below_threshold_reports_not_met(api):
    """PRD §3.10: "`low_income_encounter_count` is the count of those
    encounters whose pinned assessment has `fpl_pct` strictly less than 100 —
    a patient at exactly 100% FPL does **not** count toward the quota."
    PRD §3.10: "`low_income_quota_met` is `true` when
    `low_income_encounter_count` multiplied by 100 is greater than or equal
    to `encounter_count` multiplied by the affiliate's
    `low_income_priority_quota`".

    Zero low-income encounters of one against quota 41 gives
    0 >= 41 -> false: the comparison uses the encounter-owning affiliate's
    quota, never a global constant.

    Design: Corner/calculations/grant_quota_exact_equality_counts_as_met
    """
    set_clock("2026-09-01T00:00:00Z")
    clinic = setup_tx_clinic(quota=41, full_fee_cents=20000)
    aff = clinic["affiliate"]
    patient, _asm = setup_patient_with_assessment(
        clinic, income_cents=FPL_INCOME_H1_PCT_265, household_size=1,
        external_ref="QB-1",
    )
    enc = create_encounter(patient["id"], clinic["provider"]["id"],
                           scheduled_start="2026-09-10T09:00:00Z",
                           scheduled_end="2026-09-10T09:30:00Z")
    set_clock("2026-09-10T12:00:00Z")
    _complete_encounter(enc["id"])
    set_clock("2026-10-02T00:00:00Z")

    report = validate_success(
        api_client.create_grant_report(
            aff["id"],
            {"period_start": "2026-09-01T00:00:00Z",
             "period_end": "2026-10-01T00:00:00Z",
             "valuation_variant": "FIFO",
             "expected_affiliate_version": aff["version"]},
            ADMIN,
        ),
        201,
    )
    assert report["encounter_count"] == 1
    assert report["low_income_encounter_count"] == 0
    assert report["low_income_quota_met"] is False, (
        "0 >= 1 x 41 = 41 is false — strictly below the quota"
    )


def test_report_period_half_open_excludes_boundary_encounter(api):
    """PRD §3.10: "a `period_end` (exclusive — the reporting window is
    half-open)".
    PRD §3.10: "`encounter_count` is the count of `COMPLETED` encounters of
    the affiliate whose `scheduled_start` falls in `[period_start,
    period_end)`."

    An encounter starting exactly at period_end (2026-10-01T00:00:00Z) is
    excluded from the September report and included in the October report.

    Design: Corner/calculations/report_period_half_open_excludes_boundary_encounter
    """
    set_clock("2026-09-01T00:00:00Z")
    clinic = setup_tx_clinic(quota=40, full_fee_cents=20000)
    aff = clinic["affiliate"]
    patient, _asm = setup_patient_with_assessment(
        clinic, income_cents=FPL_INCOME_H1_PCT_265, household_size=1,
    )
    sep_enc = create_encounter(patient["id"], clinic["provider"]["id"],
                               scheduled_start="2026-09-30T23:00:00Z",
                               scheduled_end="2026-09-30T23:30:00Z")
    oct_enc = create_encounter(patient["id"], clinic["provider"]["id"],
                               scheduled_start="2026-10-01T00:00:00Z",
                               scheduled_end="2026-10-01T00:30:00Z")

    set_clock("2026-09-30T23:00:00Z")
    _complete_encounter(sep_enc["id"])
    set_clock("2026-10-01T00:00:00Z")
    _complete_encounter(oct_enc["id"])
    set_clock("2026-11-02T00:00:00Z")

    sep_report = validate_success(
        api_client.create_grant_report(
            aff["id"],
            {"period_start": "2026-09-01T00:00:00Z",
             "period_end": "2026-10-01T00:00:00Z",
             "valuation_variant": "FIFO",
             "expected_affiliate_version": aff["version"]},
            ADMIN,
        ),
        201,
    )
    assert sep_report["encounter_count"] == 1, (
        "the 2026-10-01T00:00 encounter is outside the half-open September "
        f"period, got count {sep_report['encounter_count']}"
    )

    aff_now = validate_success(api_client.get_affiliate(aff["id"], ADMIN))
    oct_report = validate_success(
        api_client.create_grant_report(
            aff["id"],
            {"period_start": "2026-10-01T00:00:00Z",
             "period_end": "2026-11-01T00:00:00Z",
             "valuation_variant": "FIFO",
             "expected_affiliate_version": aff_now["version"]},
            ADMIN,
        ),
        201,
    )
    assert oct_report["encounter_count"] == 1, (
        "the boundary encounter lands in October, not in both reports"
    )


def test_overlapping_fee_tiers_resolved_by_highest_discount_deterministically(api):
    """PRD §3.3: "If multiple candidates remain (overlapping
    misconfiguration), the server deterministically selects the one with the
    highest `discount_pct`, breaking ties first by the lowest
    `fpl_pct_min_inclusive` and then by the tier's `created_at` ascending."

    Overlapping tiers A [0,100) disc 100 (doc-only) and B [0,150) disc 80
    both match fpl 48; the documented patient deterministically receives
    tier A.

    Design: Corner/calculations/overlapping_fee_tiers_resolved_by_highest_discount_deterministically
    """
    set_clock("2026-09-01T00:00:00Z")
    aff = create_affiliate()
    create_fee_tier(aff["id"], tier_code="A", fpl_pct_min_inclusive=0,
                    fpl_pct_max_exclusive=100, discount_pct=100,
                    nominal_copay_cents=500, requires_documentation=True)
    create_fee_tier(aff["id"], tier_code="B", fpl_pct_min_inclusive=0,
                    fpl_pct_max_exclusive=150, discount_pct=80,
                    nominal_copay_cents=500, requires_documentation=False)
    patient = create_patient(aff["id"], external_ref="OV-1",
                             date_of_birth="1990-01-01")
    asm = create_assessment(patient, household_size=4,
                            annual_income_cents=FPL_INCOME_H4_PCT_48,
                            income_basis="DOCUMENTED")
    assert asm["fpl_pct"] == 48
    assert asm["assigned_tier_code"] == "A", (
        "the highest discount wins the overlap deterministically"
    )


def test_no_eligible_tier_returns_domain_error(api):
    """PRD §3.3: "If the filtered eligible set is empty, the assessment
    creation fails with `ERR_NO_ELIGIBLE_TIER` (HTTP 422)."

    A SELF_DECLARED patient whose fpl only matches a requires_documentation
    tier gets 422 ERR_NO_ELIGIBLE_TIER, and no assessment is persisted.

    Design: Corner/calculations/no_eligible_tier_returns_domain_error
    """
    set_clock("2026-09-01T00:00:00Z")
    aff = create_affiliate()
    create_fee_tier(aff["id"], tier_code="A", fpl_pct_min_inclusive=0,
                    fpl_pct_max_exclusive=100, discount_pct=100,
                    nominal_copay_cents=500, requires_documentation=True)
    patient = create_patient(aff["id"], external_ref="NE-1",
                             date_of_birth="1990-01-01")
    res = api_client.create_assessment(
        patient["id"],
        {"household_size": 4,
         "annual_income_cents": FPL_INCOME_H4_PCT_48,
         "income_basis": "SELF_DECLARED",
         "expected_patient_version": patient["version"]},
        FRONT_DESK,
    )
    validate_error(res, "ERR_NO_ELIGIBLE_TIER", expected_status=422)

    rows, meta = validate_paginated(
        api_client.list_assessments(patient["id"], FRONT_DESK)
    )
    assert len(rows) == 0

    patient_after = validate_success(
        api_client.get_patient(patient["id"], FRONT_DESK)
    )
    assert patient_after["version"] == patient["version"], (
        "the rejected assessment does not bump the patient version"
    )
