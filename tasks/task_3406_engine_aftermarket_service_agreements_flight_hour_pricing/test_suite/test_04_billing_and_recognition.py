"""Monthly billing (PROVISIONAL vs FINAL variants, escalation + utilization
band rate math, pinned rounding order) and contract-accounting snapshots."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_operator,
    create_engine,
    create_active_agreement,
    enroll_engine,
    get_agreement,
    setup_enrolled_engine,
    setup_enrolled_engines,
    submit_report,
    verify_report,
    submit_and_verify_report,
    submit_history,
    create_visit,
    induct_visit,
    complete_visit,
    create_workscope_version,
    approve_workscope,
    workscope_item,
    issue_statement,
    settle_statement,
    issue_and_settle_statement,
    create_recognition_snapshot,
    issue_billing_statement_payload,
    make_operator_headers,
)


def test_billing_provisional_vs_final_divergence(api):
    """PRD §3.4: "For each engine it looks up that engine's flight-hour report
    for the statement period in the provisional input set — reports in either
    `SUBMITTED` or `VERIFIED` status — so unverified hours are billed at
    issuance."
    PRD §3.4: "the input set is now `VERIFIED` reports only, so hours that
    were never verified drop out of the bill."
    PRD §3.4: "The settlement sets `final_total_usd` to the recomputed total
    and `adjustment_usd` to the difference between `final_total_usd` and
    `provisional_total_usd`".

    Arithmetic (statement period 2026-09, agreement base 250.00, escalation
    3% anchored 2025-09-01): anchor + 12 months = 2026-09-01 <= 2026-09-30,
    so exactly 1 anniversary -> escalation factor 1.03. ESN-A101 has no
    VERIFIED history -> ratio defaults to 1.00 (STANDARD); ESN-A102 annualized
    310*12/1 = 3720 over assumed 3600 -> ratio 1.0333 <= 1.10 -> STANDARD.
    Effective rate for both = round4(250.00 * 1.03 * 1.00) = 257.5000.
    Provisional = (290 + 310) * 257.5000 = 154500.00; final keeps only the
    VERIFIED engine: 310 * 257.5000 = 79825.00; adjustment = -74675.00.

    Design: Difficulty/dual_variant_calc/billing_provisional_vs_final_divergence
    """
    fx = setup_enrolled_engines(
        [
            {"esn": "ESN-A101", "base_severity_tier": "MODERATE",
             "llp_remaining_cycles": 8000, "assumed_annual_hours": 3000,
             "assumed_cycles_per_month": 120},
            {"esn": "ESN-A102", "base_severity_tier": "HARSH",
             "llp_remaining_cycles": 8000, "assumed_annual_hours": 3600,
             "assumed_cycles_per_month": 140},
        ],
        credit_rating="B",
        operator_overrides={"name": "Meridian Air", "iata_code": "MA"},
        agreement_overrides={
            "contract_ref": "LTSA-A01",
            "base_rate_per_fh_usd": 250.00,
            "escalation_pct": 0.03,
            "escalation_anchor_date": "2025-09-01T00:00:00Z",
            "start_date": "2025-09-01T00:00:00Z",
            "end_date": "2030-08-31T00:00:00Z",
            "allowed_sourcing_classes": ["NEW", "REPAIRED", "USM"],
            "max_workscope_cost_usd": 2000000,
        },
    )
    e1, e2 = fx["engines"]
    submit_report(e1, fx["operator_headers"], period="2026-09",
                  flight_hours=290, cycles=120, observed_severity="MODERATE")
    r2 = submit_report(e2, fx["operator_headers"], period="2026-09",
                       flight_hours=310, cycles=140, observed_severity="HARSH")
    verify_report(r2)

    stmt = issue_statement(fx["agreement"], "2026-09")
    assert stmt["provisional_total_usd"] == pytest.approx(154500.00, abs=0.01)

    settled = settle_statement(stmt)
    assert settled["status"] == "SETTLED"
    assert settled["final_total_usd"] == pytest.approx(79825.00, abs=0.01)
    assert settled["adjustment_usd"] == pytest.approx(-74675.00, abs=0.01)


def test_recognition_projected_vs_actual_divergence(api):
    """PRD §3.9: "The snapshot's `lifetime_revenue_projection_usd` is then the
    agreement's `billed_to_date_usd` plus the remaining term in months
    multiplied by that projected monthly revenue."
    PRD §3.9: "`cost_to_date_usd` is the sum of `total_cost_usd` over all
    `APPROVED` workscopes of `COMPLETED` visits of the agreement's enrolled
    engines, plus the `lease_cost_usd` of all `RETURNED` leases on those
    visits — money demonstrably spent."
    PRD §3.9: "`recognition_pct` is the ratio of `cost_to_date_usd` to
    `lifetime_cost_projection_usd`, capped at 1" and
    "`recognized_revenue_actual_usd` is the sum of `final_total_usd` over the
    agreement's `SETTLED` statements, deflated by the fixed target margin of
    0.15 — that is, multiplied by 0.85".
    PRD §3.9: "When that margin falls strictly below the margin floor of 0.05,
    the contract is onerous and `onerous_loss_accrual_usd` is the full
    projected shortfall".

    Arithmetic (clock 2026-09-01; agreement 2026-09-01 .. 2028-08-31):
      remaining_term_months = (2028*12 + 8) - (2026*12 + 9) = 23.
      2026-09 statement: escalation 0 anniversaries (2027-09-01 > 2026-09-30);
      ratio = (200*12/1)/2400 = 1.00 STANDARD -> rate 100.0000 -> 20000.00.
      projected_monthly_revenue = (2400/12) * 100.0000 = 20000.00.
      lifetime_revenue = 20000.00 + 23 * 20000.00 = 480000.00.
      cost_to_date = 300000.00 (one APPROVED workscope of a COMPLETED visit).
      forecast_visits = ceil(23 * 100 / 8000) = 1; per-visit 1200000 * 1.00.
      lifetime_cost = 300000.00 + 1200000.00 = 1500000.00.
      recognition_pct = 300000/1500000 = 0.2 -> projected 0.2 * 480000 = 96000.
      actual = 20000 * 0.85 = 17000.00.
      margin = (480000 - 1500000)/480000 = -2.125 < 0.05 -> onerous 1020000.00.

    Design: Difficulty/dual_variant_calc/recognition_projected_vs_actual_divergence
    """
    operator = create_operator(name="Coastal Airways", iata_code="CB",
                               credit_rating="A")
    engine = create_engine(operator, esn="ESN-B200",
                           base_severity_tier="BENIGN", llp_remaining_cycles=8000)
    agreement = create_active_agreement(
        contract_ref="LTSA-B02",
        base_rate_per_fh_usd=100.00,
        escalation_pct=0.02,
        escalation_anchor_date="2026-09-01T00:00:00Z",
        start_date="2026-09-01T00:00:00Z",
        end_date="2028-08-31T00:00:00Z",
        allowed_sourcing_classes=["NEW"],
        max_workscope_cost_usd=2000000,
    )
    engine = enroll_engine(agreement, engine, assumed_annual_hours=2400,
                           assumed_cycles_per_month=100)
    op_headers = make_operator_headers(operator["id"])
    submit_and_verify_report(engine, op_headers, period="2026-09",
                             flight_hours=200, cycles=100,
                             observed_severity="BENIGN")

    visit = create_visit(engine, op_headers, "2026-09-01T00:00:00Z")
    visit = induct_visit(visit)
    workscope = create_workscope_version(
        visit["id"],
        items=[workscope_item(item_code="MO-1", estimated_cost_usd=300000,
                              restores_cycles=8000)],
    )
    approve_workscope(workscope, op_headers)
    complete_visit(visit)

    stmt = issue_and_settle_statement(agreement, "2026-09")
    assert stmt["final_total_usd"] == pytest.approx(20000.00, abs=0.01)

    snap = create_recognition_snapshot(agreement)
    assert snap["cost_to_date_usd"] == pytest.approx(300000.00, abs=0.01)
    assert snap["lifetime_revenue_projection_usd"] == pytest.approx(480000.00, abs=0.01)
    assert snap["lifetime_cost_projection_usd"] == pytest.approx(1500000.00, abs=0.01)
    assert snap["recognition_pct"] == pytest.approx(0.2, abs=0.0001)
    assert snap["recognized_revenue_projected_usd"] == pytest.approx(96000.00, abs=0.01)
    assert snap["recognized_revenue_actual_usd"] == pytest.approx(17000.00, abs=0.01)
    assert snap["onerous_loss_accrual_usd"] == pytest.approx(1020000.00, abs=0.01)


def test_escalated_rate_compounding_with_band_tiers(api):
    """PRD §2.10: "The number of compounding steps for a given statement
    period is the count of integers k, with k at least 1, such that the date
    exactly k times 12 months after `escalation_anchor_date` is on or before
    the last day of that statement period."
    PRD §2.10: "a ratio strictly above 1.10 prices at a band factor of 1.08."
    PRD §2.10: "The effective per-flight-hour rate for an engine in a period
    is the base rate multiplied by the escalation factor multiplied by the
    band factor, rounded half-up to 4 decimal places."

    Arithmetic: verified history 3 x 100 h -> annualized (300*12/3) = 1200
    over assumed 1000 -> ratio 1.20 > 1.10 -> HIGH band 1.08; escalation
    anchor 2025-09-01 + 12 months = 2026-09-01 <= 2026-09-30 -> 1 anniversary
    -> factor 1.03; rate = round4(250.00 * 1.03 * 1.08) = 278.1000; the
    still-SUBMITTED 2026-09 report (50 h) is billed provisionally:
    50 * 278.1000 = 13905.00.

    Design: Difficulty/combinatorial_formula/escalated_rate_compounding_with_band_tiers
    """
    fx = setup_enrolled_engine(
        esn="ESN-C301",
        base_severity_tier="BENIGN",
        llp_remaining_cycles=8000,
        assumed_annual_hours=1000,
        assumed_cycles_per_month=100,
        operator_overrides={"name": "Prairie Air", "iata_code": "PC"},
        agreement_overrides={
            "contract_ref": "LTSA-C03",
            "base_rate_per_fh_usd": 250.00,
            "escalation_pct": 0.03,
            "escalation_anchor_date": "2025-09-01T00:00:00Z",
            "start_date": "2025-09-01T00:00:00Z",
            "end_date": "2030-08-31T00:00:00Z",
            "allowed_sourcing_classes": ["NEW"],
            "max_workscope_cost_usd": 2000000,
        },
    )
    submit_history(
        fx["engine"],
        fx["operator_headers"],
        [
            ("2026-06", 100, 50, "BENIGN"),
            ("2026-07", 100, 50, "BENIGN"),
            ("2026-08", 100, 50, "BENIGN"),
        ],
    )
    submit_report(fx["engine"], fx["operator_headers"], period="2026-09",
                  flight_hours=50, cycles=25, observed_severity="BENIGN")

    stmt = issue_statement(fx["agreement"], "2026-09")
    assert len(stmt["line_items"]) == 1
    line = stmt["line_items"][0]
    assert line["effective_rate_per_fh_usd"] == pytest.approx(278.1000, abs=0.0001)
    assert line["line_amount_usd"] == pytest.approx(13905.00, abs=0.001)
    assert stmt["provisional_total_usd"] == pytest.approx(13905.00, abs=0.001)


def test_per_line_round_then_sum_order(api):
    """PRD §2.6: "**Billing statements pin a rounding order:** each line's
    `line_amount_usd` is rounded to 2 decimal places first, and the statement
    total is then the exact sum of those rounded lines, with no further
    rounding applied to the total."

    Arithmetic: base 99.995, no escalation, no verified history -> ratio
    defaults to 1.00 -> rate round4(99.995 * 1 * 1.00) = 99.9950. Each 3 h
    line rounds half-up: round2(3 * 99.9950 = 299.985) = 299.99. Two identical
    engines -> total 299.99 + 299.99 = 599.98 (the sum-then-round alternative
    599.97 is the wrong order).

    Design: Difficulty/combinatorial_formula/per_line_round_then_sum_order
    """
    fx = setup_enrolled_engines(
        [
            {"esn": "ESN-D401", "assumed_annual_hours": 2000,
             "assumed_cycles_per_month": 100},
            {"esn": "ESN-D402", "assumed_annual_hours": 2000,
             "assumed_cycles_per_month": 100},
        ],
        credit_rating="C",
        operator_overrides={"name": "Delta Regional", "iata_code": "DD"},
        agreement_overrides={
            "contract_ref": "LTSA-D04",
            "base_rate_per_fh_usd": 99.995,
            "escalation_pct": 0.0,
        },
    )
    for engine in fx["engines"]:
        submit_report(engine, fx["operator_headers"], period="2026-09",
                      flight_hours=3, cycles=1, observed_severity="BENIGN")

    stmt = issue_statement(fx["agreement"], "2026-09")
    assert len(stmt["line_items"]) == 2
    for line in stmt["line_items"]:
        assert line["effective_rate_per_fh_usd"] == pytest.approx(99.9950, abs=0.0001)
        assert line["line_amount_usd"] == pytest.approx(299.99, abs=0.001)
    assert stmt["provisional_total_usd"] == pytest.approx(599.98, abs=0.001)


def test_utilization_ratio_exactly_high_threshold(api):
    """PRD §2.10: "a ratio from 0.90 up to and including 1.10 prices at a band
    factor of 1.00; a ratio strictly above 1.10 prices at a band factor of
    1.08."
    PRD §3.4: "Otherwise the summed hours are annualized by multiplying by 12
    and dividing by the number of distinct periods present, and the ratio is
    that annualized figure divided by the engine's `assumed_annual_hours`."

    Arithmetic (assumed 2000 h/yr both engines):
      ESN-I101: 183+183+184 = 550 h over 3 periods -> annualized 2200 ->
                ratio exactly 1.10 -> NOT strictly above -> STANDARD 1.00 ->
                rate 100.0000.
      ESN-I102: 184+184+183 = 551 h over 3 periods -> annualized 2204 ->
                ratio 1.102 > 1.10 -> HIGH 1.08 -> rate 108.0000.
      Provisional (2026-09, 100 h each) = 10000.00 + 10800.00 = 20800.00.

    Design: Difficulty/boundary_precision_check/utilization_ratio_exactly_high_threshold
    """
    fx = setup_enrolled_engines(
        [
            {"esn": "ESN-I101", "assumed_annual_hours": 2000,
             "assumed_cycles_per_month": 100},
            {"esn": "ESN-I102", "assumed_annual_hours": 2000,
             "assumed_cycles_per_month": 100},
        ],
        operator_overrides={"name": "Island Air", "iata_code": "IA"},
        agreement_overrides={"contract_ref": "LTSA-I11"},
    )
    e_a, e_b = fx["engines"]
    submit_history(e_a, fx["operator_headers"], [
        ("2026-06", 183, 50, "BENIGN"),
        ("2026-07", 183, 50, "BENIGN"),
        ("2026-08", 184, 50, "BENIGN"),
    ])
    submit_history(e_b, fx["operator_headers"], [
        ("2026-06", 184, 50, "BENIGN"),
        ("2026-07", 184, 50, "BENIGN"),
        ("2026-08", 183, 50, "BENIGN"),
    ])
    for engine in (e_a, e_b):
        submit_report(engine, fx["operator_headers"], period="2026-09",
                      flight_hours=100, cycles=40, observed_severity="BENIGN")

    stmt = issue_statement(fx["agreement"], "2026-09")
    lines = {line["engine_id"]: line for line in stmt["line_items"]}
    assert lines[e_a["id"]]["effective_rate_per_fh_usd"] == pytest.approx(
        100.0000, abs=0.0001), "ratio exactly 1.10 must stay in the STANDARD band"
    assert lines[e_b["id"]]["effective_rate_per_fh_usd"] == pytest.approx(
        108.0000, abs=0.0001), "ratio 1.102 must cross into the HIGH band"
    assert stmt["provisional_total_usd"] == pytest.approx(20800.00, abs=0.01)


def test_statement_settle_twice_rejected(api, finance_controller_headers):
    """PRD §3.4: "A `FinanceController` settles an `ISSUED` statement —
    attempting to settle one already `SETTLED` is rejected with
    `ERR_INVALID_STATE` — which recomputes the line items under the **FINAL
    variant**: the input set is now `VERIFIED` reports only, so hours that
    were never verified drop out of the bill."

    Re-derivation note: the design recipe enrolled the engine at 2400 assumed
    h/yr, which under the PRD §3.4 ratio rule yields (100*12/1)/2400 = 0.5 ->
    LOW band 0.95 -> 9500.00, contradicting the recipe's asserted 10000.00.
    Enrolling at assumed_annual_hours=1200 makes the ratio exactly 1.00
    (STANDARD) so the recipe's asserted literal holds: rate 100.0000,
    final = 100 * 100.0000 = 10000.00.

    Design: Corner/state_machines/statement_settle_twice_rejected
    """
    fx = setup_enrolled_engine(
        esn="ESN-S201",
        assumed_annual_hours=1200,
        assumed_cycles_per_month=100,
        operator_overrides={"name": "Tarn Air", "iata_code": "TA"},
        agreement_overrides={"contract_ref": "LTSA-C501"},
    )
    submit_and_verify_report(fx["engine"], fx["operator_headers"],
                             period="2026-09", flight_hours=100, cycles=40,
                             observed_severity="BENIGN")
    stmt = issue_statement(fx["agreement"], "2026-09")
    settled = settle_statement(stmt)
    assert settled["status"] == "SETTLED"
    assert settled["final_total_usd"] == pytest.approx(10000.00, abs=0.01)

    res = api.settle_billing_statement(stmt["id"], finance_controller_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_agreement_billed_to_date_reconciles_across_settle(api):
    """PRD §3.2: "Throughout the lifecycle, `billed_to_date_usd` keeps a
    running commercial picture: it is the sum of `provisional_total_usd` over
    the agreement's `ISSUED` statements plus `final_total_usd` over its
    `SETTLED` statements, recomputed whenever a statement is issued or
    settled."
    PRD §3.4: settle "recomputes the agreement's `billed_to_date_usd`, which
    from then on counts this statement by its final rather than provisional
    total."

    Arithmetic: verified 200 h, ratio (200*12/1)/2400 = 1.00 STANDARD,
    0 anniversaries -> rate 100.0000 -> provisional = final = 20000.00; the
    settle replaces the provisional contribution rather than adding to it
    (20000.00, never 40000.00).

    Design: Corner/calculations/agreement_billed_to_date_reconciles_across_settle
    """
    fx = setup_enrolled_engine(
        esn="ESN-F301",
        assumed_annual_hours=2400,
        assumed_cycles_per_month=100,
        operator_overrides={"name": "Field Air", "iata_code": "FC"},
        agreement_overrides={"contract_ref": "LTSA-C1001"},
    )
    submit_and_verify_report(fx["engine"], fx["operator_headers"],
                             period="2026-09", flight_hours=200, cycles=80,
                             observed_severity="BENIGN")

    stmt = issue_statement(fx["agreement"], "2026-09")
    assert stmt["provisional_total_usd"] == pytest.approx(20000.00, abs=0.01)
    pre = get_agreement(fx["agreement"]["id"])
    assert pre["billed_to_date_usd"] == pytest.approx(20000.00, abs=0.01)

    settled = settle_statement(stmt)
    assert settled["final_total_usd"] == pytest.approx(20000.00, abs=0.01)
    post = get_agreement(fx["agreement"]["id"])
    assert post["billed_to_date_usd"] == pytest.approx(20000.00, abs=0.01), (
        "settlement must replace the provisional amount, not double-count it"
    )


def test_duplicate_statement_period_rejected(api, finance_controller_headers):
    """PRD §3.4: "One statement exists per agreement per period
    (`ERR_DUPLICATE_STATEMENT` on collision)".

    Design: Corner/validations/duplicate_statement_period_rejected
    """
    fx = setup_enrolled_engine(
        esn="ESN-I201",
        operator_overrides={"name": "Ice Air", "iata_code": "IB"},
        agreement_overrides={"contract_ref": "LTSA-V1801"},
    )
    issue_statement(fx["agreement"], "2026-09")
    res = api.issue_billing_statement(
        fx["agreement"]["id"],
        issue_billing_statement_payload(period="2026-09"),
        finance_controller_headers,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_STATEMENT.value)
