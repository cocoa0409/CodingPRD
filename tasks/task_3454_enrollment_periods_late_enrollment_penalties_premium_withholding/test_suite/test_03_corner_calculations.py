"""Corner coverage: calculation rules not owned by the difficulty index."""

from test_helpers import (
    PART_B,
    create_determination,
    create_employer_coverage,
    end_employer_coverage,
    enroll,
    list_enrollment_periods,
    list_payer_coordination,
    list_penalties,
    publish_default_rate_schedules,
    register_beneficiary,
    set_clock,
    setup_verified_employer_coverage,
    submit_tax_record,
    verify_employer_coverage,
)


def test_sep_anchor_uses_earlier_of_employment_and_coverage_end(client):
    """PRD section 3.3: "The SEP anchors on whichever ended FIRST — the
    earlier of `employment_end_month` and `coverage_end_month` — and runs for
    eight months: from the month after the anchor through the eighth month
    after it, inclusive." PRD section 3.3: "When employment ends in 2026-07
    while coverage runs through 2026-10, the anchor is 2026-07 and the SEP
    spans 2026-08 through 2027-03."

    Design: Corner/calculations/sep_anchor_uses_earlier_of_employment_and_coverage_end
    """
    beneficiary, record = setup_verified_employer_coverage(
        client, employer_size=30
    )
    set_clock(client, "2026-11-01T00:00:00Z")
    ended = end_employer_coverage(client, record["id"], "2026-10", "2026-07")
    assert ended["record_status"] == "ENDED"
    assert ended["coverage_end_month"] == "2026-10"
    assert ended["employment_end_month"] == "2026-07"

    periods = list_enrollment_periods(client, beneficiary)
    assert periods[0]["window_type"] == "IEP", "created_at ascending: IEP first"
    sep = periods[1]
    assert sep["window_type"] == "SEP"
    assert sep["window_start_month"] == "2026-08"
    assert sep["window_end_month"] == "2027-03"
    assert sep["source_coverage_ref"] == record["id"]


def test_payer_role_employer_size_twenty_boundary(client):
    """PRD section 3.3: "If any active record has an `employer_size` of at
    least 20 — exactly 20 counts as large, while 19 does not — Medicare is
    the secondary payer". PRD section 3.3: "Verification is retroactive:
    verifying a large-employer record opens the `MEDICARE_SECONDARY` interval
    starting at the record's `coverage_start_month`, not at the verification
    date." PRD section 3.3: "Otherwise, if any active record exists, Medicare
    remains primary with `basis` `SMALL_EMPLOYER`".

    Design: Corner/calculations/payer_role_employer_size_twenty_boundary
    """
    set_clock(client, "2026-01-05T00:00:00Z")
    beneficiary_x = register_beneficiary(
        client, date_of_birth="1961-03-10", full_name="Size Twenty"
    )
    beneficiary_y = register_beneficiary(
        client, date_of_birth="1961-03-10", full_name="Size Nineteen"
    )
    record_x = create_employer_coverage(
        client,
        beneficiary_x,
        employer_name="BIGCO",
        employer_size=20,
        coverage_start_month="2024-01",
    )
    record_y = create_employer_coverage(
        client,
        beneficiary_y,
        employer_name="SMALLCO",
        employer_size=19,
        coverage_start_month="2024-01",
    )
    verify_employer_coverage(client, record_x["id"])
    verify_employer_coverage(client, record_y["id"])

    rows_x = list_payer_coordination(client, beneficiary_x)
    assert len(rows_x) == 1, "the degenerate opening row is replaced"
    assert rows_x[0]["role"] == "MEDICARE_SECONDARY"
    assert rows_x[0]["basis"] == "LARGE_EMPLOYER"
    assert rows_x[0]["effective_start_month"] == "2024-01"
    assert rows_x[0]["effective_end_month"] is None

    rows_y = list_payer_coordination(client, beneficiary_y)
    assert len(rows_y) == 1
    assert rows_y[0]["role"] == "MEDICARE_PRIMARY"
    assert rows_y[0]["basis"] == "SMALL_EMPLOYER"


def test_creditable_months_reduce_part_b_gap_below_threshold(client):
    """PRD section 3.4: "Months of that span are credited — excluded from the
    gap — when covered by either of two things: a prior same-part
    CoverageEnrollment's half-open interval, or a month of a `VERIFIED`
    EmployerCoverageRecord's closed interval". PRD section 3.2: "Under the SEP
    or the GEP, coverage takes effect in the month after the enrollment
    month."

    Design: Corner/calculations/creditable_months_reduce_part_b_gap_below_threshold
    """
    beneficiary, record = setup_verified_employer_coverage(
        client, employer_size=30, date_of_birth="1960-06-10"
    )
    set_clock(client, "2026-10-05T00:00:00Z")
    end_employer_coverage(client, record["id"], "2026-09", "2026-09")

    set_clock(client, "2026-11-10T00:00:00Z")
    enrollment = enroll(client, beneficiary, part=PART_B)
    assert enrollment["enrolled_via_window"] == "SEP"
    assert enrollment["effective_month"] == "2026-12"

    # Span [2025-10 .. 2026-11] = 14 months; the VERIFIED record's closed
    # interval covers 2025-10..2026-09 (12 of them), leaving a gap of 2, and
    # floor(2/12) == 0: no penalty assessment is created.
    penalties = list_penalties(client, beneficiary)
    assert penalties == [], "gap of 2 months is below the twelve-month threshold"


def test_part_b_lep_amount_floats_with_coverage_year_standard(client):
    """PRD section 3.4: "A beneficiary with a ten percent penalty facing a
    standard premium of 18500 cents in one year owes 1850 cents per month;
    when the standard premium rises to 19000 cents the next year, the same
    ten percent yields 1900 cents."

    Design: Corner/calculations/part_b_lep_amount_floats_with_coverage_year_standard
    """
    publish_default_rate_schedules(client)
    set_clock(client, "2026-03-10T00:00:00Z")
    beneficiary = register_beneficiary(client, date_of_birth="1959-11-20")
    enrollment = enroll(client, beneficiary, part=PART_B)
    assert enrollment["enrolled_via_window"] == "GEP"
    assert enrollment["effective_month"] == "2026-04"
    # Gap [2025-03 .. 2026-03] = 13 months -> one full period -> 10 percent.
    submit_tax_record(client, beneficiary["id"], 2024, 5000000)
    submit_tax_record(client, beneficiary["id"], 2025, 5000000)

    penalties = list_penalties(client, beneficiary)
    assert len(penalties) == 1
    assert penalties[0]["penalty_pct"] == 10
    assert penalties[0]["gap_months"] == 13

    det_2026 = create_determination(client, beneficiary, 2026, part=PART_B)
    assert det_2026["lep_cents"] == 1850
    assert det_2026["irmaa_surcharge_cents"] == 0
    assert det_2026["total_premium_cents"] == 20350

    det_2027 = create_determination(client, beneficiary, 2027, part=PART_B)
    assert det_2027["lep_cents"] == 1900
    assert det_2027["irmaa_surcharge_cents"] == 0
    assert det_2027["total_premium_cents"] == 20900
