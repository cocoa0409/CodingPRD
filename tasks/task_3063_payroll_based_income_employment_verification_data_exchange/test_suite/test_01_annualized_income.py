"""Annualized income: the per-record rounding order and the terminated-span variant."""
from test_helpers import (
    setup_employer_worker_record,
    set_clock,
    get_record,
    get_batch,
    validate_batch,
)


def test_terminated_span_uses_blended_final_period_reading(api):
    """PRD §3.4: "When the span's `employment_status` is `TERMINATED`, its
    `separation_date` is present, and its `final_pay_period_income_cents` is greater
    than zero, the annual figure is not the standing rate. Instead the standing
    normalized rate is pro-rated to the pay periods actually worked by multiplying it
    by one less than the number of periods per year and dividing by the number of
    periods per year, and the final partial period's income is then added to that
    prorated amount".
    PRD §3.4: "a monthly contributor whose standing normalized rate is 5200000 cents
    and whose final period income is 180000 cents annualizes to 4946667 cents rather
    than 5200000".

    Design: Difficulty/dual_variant_calc/annualized_income_terminated_blended_vs_standing_rate
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_employer_worker_record(
        record_overrides={
            "employment_status": "TERMINATED",
            "hire_date": "2023-01-15T00:00:00Z",
            "separation_date": "2026-05-15T00:00:00Z",
            "pay_rate_cents": 520000,
            "pay_rate_basis": "MONTHLY",
            "standard_hours_per_week": 40,
            "final_pay_period_income_cents": 180000,
        },
    )
    record = get_record(ctx["record"]["id"])
    assert record["annualized_income_cents"] == 5900000, (
        f"expected the blended final-period reading 5900000, got "
        f"{record['annualized_income_cents']}"
    )


def test_terminated_span_rejects_the_standing_rate_reading(api):
    """PRD §3.4: "A `TERMINATED` span with a zero final-period income, or an open
    span, takes the standing-rate branch unchanged."
    PRD §3.4: "That normalized figure is rounded half up to the nearest whole cent and
    stored as `annualized_income_cents`."

    Design: Difficulty/dual_variant_calc/annualized_income_terminated_blended_vs_standing_rate
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_employer_worker_record(
        record_overrides={
            "employment_status": "TERMINATED",
            "hire_date": "2023-01-15T00:00:00Z",
            "separation_date": "2026-05-15T00:00:00Z",
            "pay_rate_cents": 520000,
            "pay_rate_basis": "MONTHLY",
            "standard_hours_per_week": 40,
            "final_pay_period_income_cents": 180000,
        },
    )
    record = get_record(ctx["record"]["id"])
    # 520000 * 12 = 6240000 would be the standing-rate reading; the pinned variant
    # for a terminated span with a non-zero final period is the blended one.
    assert record["annualized_income_cents"] != 6240000
    assert record["annualized_income_cents"] == 5900000
    assert record["record_state"] == "VERIFIED"
    assert record["currency_state"] == "CURRENT"


def test_hourly_batch_rounds_each_record_before_aggregating(api):
    """PRD §3.4: "for an hourly basis it is the rate multiplied by the effective
    weekly hours and then multiplied by 52 weeks".
    PRD §2.4: "The per-record annualization rule rounds each record individually
    before any batch-level aggregation, so batch totals are plain sums of
    already-rounded figures rather than a single rounding of a summed total."

    Design: Difficulty/combinatorial_formula/annualized_income_nested_rounding_per_record_before_batch_sum
    """
    employer = None
    from test_helpers import (
        onboard_employer,
        register_worker,
        create_verified_layout,
        create_batch,
        attach_record,
    )
    employer = onboard_employer(
        fein="223456789", frequency="WEEKLY", legal_name="Cedar Grove Staffing",
        employer_type="STAFFING_AGENCY",
    )
    worker_a = register_worker(full_name="Rosa Aguilar", ssn_last4="9911", date_of_birth="1979-11-02")
    worker_b = register_worker(full_name="Ivan Petrov", ssn_last4="2288", date_of_birth="1990-07-21")
    layout = create_verified_layout(employer["id"])
    batch = create_batch(
        employer["id"], layout["id"], pay_period_end_date="2026-06-06T00:00:00Z", record_count=2
    )
    record_a = attach_record(
        employer["id"], worker_a["id"], batch["id"],
        employment_status="ACTIVE", hire_date="2024-02-01T00:00:00Z", separation_date=None,
        pay_rate_cents=2531, pay_rate_basis="HOURLY", standard_hours_per_week=37.1,
        final_pay_period_income_cents=0,
    )
    record_b = attach_record(
        employer["id"], worker_b["id"], batch["id"],
        employment_status="ACTIVE", hire_date="2024-02-01T00:00:00Z", separation_date=None,
        pay_rate_cents=2749, pay_rate_basis="HOURLY", standard_hours_per_week=32.3,
        final_pay_period_income_cents=0,
    )
    validate_batch(employer["id"], batch["id"])

    got_a = get_record(record_a["id"])["annualized_income_cents"]
    got_b = get_record(record_b["id"])["annualized_income_cents"]
    assert got_a == 4882805, f"expected round_half_up(2531 * 37.1 * 52) == 4882805, got {got_a}"
    assert got_b == 4617220, f"expected round_half_up(2749 * 32.3 * 52) == 4617220, got {got_b}"

    batch_after = get_batch(batch["id"], employer["id"])
    assert batch_after["gross_amount_cents"] == 9500025, (
        "gross_amount_cents must be the plain sum of the already-rounded per-record values"
    )


def test_batch_gross_amount_is_the_sum_of_stored_per_record_values(api):
    """PRD §2.4: "batch totals are plain sums of already-rounded figures rather than a
    single rounding of a summed total".

    Design: Difficulty/combinatorial_formula/annualized_income_nested_rounding_per_record_before_batch_sum
    """
    from test_helpers import (
        onboard_employer,
        register_worker,
        create_verified_layout,
        create_batch,
        attach_record,
    )
    employer = onboard_employer(
        fein="223456789", frequency="WEEKLY", legal_name="Cedar Grove Staffing",
        employer_type="STAFFING_AGENCY",
    )
    worker_a = register_worker(full_name="Rosa Aguilar", ssn_last4="9911", date_of_birth="1979-11-02")
    worker_b = register_worker(full_name="Ivan Petrov", ssn_last4="2288", date_of_birth="1990-07-21")
    layout = create_verified_layout(employer["id"])
    batch = create_batch(
        employer["id"], layout["id"], pay_period_end_date="2026-06-06T00:00:00Z", record_count=2
    )
    record_a = attach_record(
        employer["id"], worker_a["id"], batch["id"],
        employment_status="ACTIVE", hire_date="2024-02-01T00:00:00Z", separation_date=None,
        pay_rate_cents=2531, pay_rate_basis="HOURLY", standard_hours_per_week=37.1,
        final_pay_period_income_cents=0,
    )
    record_b = attach_record(
        employer["id"], worker_b["id"], batch["id"],
        employment_status="ACTIVE", hire_date="2024-02-01T00:00:00Z", separation_date=None,
        pay_rate_cents=2749, pay_rate_basis="HOURLY", standard_hours_per_week=32.3,
        final_pay_period_income_cents=0,
    )
    validate_batch(employer["id"], batch["id"])

    stored_a = get_record(record_a["id"])["annualized_income_cents"]
    stored_b = get_record(record_b["id"])["annualized_income_cents"]
    gross = get_batch(batch["id"], employer["id"])["gross_amount_cents"]
    assert gross == stored_a + stored_b
    # Summing the unrounded products first would give 9500026.
    assert gross != 9500026


def test_employment_record_carries_two_independent_state_dimensions(api):
    """PRD §2.8: "An `EmploymentRecord` carries two independent dimensions that never
    share a transition: `record_state` runs through `PENDING_VERIFICATION`,
    `VERIFIED`, `DISPUTED`, `CORRECTED` and `IMMUTABLE`, and `currency_state` runs
    through `CURRENT`, `STALE` and `FROZEN`."
    PRD §3.4: "Each write appends the span's `annualized_income_cents` and
    `tenure_months`."
    PRD §3.4: "`tenure_months` counts completed whole months from `hire_date` to
    `separation_date`, or from `hire_date` to the current clock date while the span
    has no separation."

    Design: Corner/entities/employment_record_carries_two_independent_state_dimensions
    """
    from test_helpers import (
        onboard_employer,
        register_worker,
        create_verified_layout,
        create_batch,
        attach_record,
    )
    employer = onboard_employer()
    worker = register_worker()
    layout = create_verified_layout(employer["id"])
    batch = create_batch(
        employer["id"], layout["id"], pay_period_end_date="2026-08-31T00:00:00Z", record_count=900
    )
    record = attach_record(employer["id"], worker["id"], batch["id"])

    before = get_record(record["id"])
    assert before["record_state"] == "PENDING_VERIFICATION"
    assert before["currency_state"] == "CURRENT"

    validate_batch(employer["id"], batch["id"])

    after = get_record(record["id"])
    assert after["record_state"] == "VERIFIED"
    assert after["currency_state"] == "CURRENT"
    assert after["annualized_income_cents"] == 6240000
    assert after["tenure_months"] == 43