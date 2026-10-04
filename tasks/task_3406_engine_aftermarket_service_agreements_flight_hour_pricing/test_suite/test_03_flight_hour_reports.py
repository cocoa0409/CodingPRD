"""Flight-hour reporting: submission gates, verification terminality, and the
verification cascade through forecast recompute to lease auto-cancellation."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    create_operator,
    create_engine,
    create_spare_engine,
    setup_enrolled_engine,
    setup_inducted_visit,
    submit_report,
    verify_report,
    create_visit,
    create_lease,
    create_flight_hour_report_payload,
    TEST_USERS,
    make_operator_headers,
)


def test_verify_report_to_lease_cancel_chain(api, shop_planner_headers):
    """PRD §3.3: "Life-limited-part consumption is debited:
    `llp_remaining_cycles` is reduced by the report's `cycles`, floored at
    zero so it can never go negative."
    PRD §3.3: "Every `SCHEDULED` shop visit of the engine has its
    `forecast_induction_date` recomputed. If the new forecast falls
    **earlier** than the visit's `planned_induction_date`, the planned date is
    auto-advanced to the forecast date, and every `RESERVED` spare-engine
    lease of that visit whose half-open window does not contain the new
    planned induction date is automatically cancelled — the lease transitions
    from `RESERVED` to `CANCELLED` and its `version` increments by 1."
    PRD §3.5: "it takes the engine's `llp_remaining_cycles`, divides by the
    `assumed_cycles_per_month` captured at enrollment, converts months to days
    at 30 days per month with any fractional day discarded down to a whole
    day, and adds that many days to the current logical clock."

    Forecast arithmetic (logical clock 2026-09-01, PRD §2.4):
      at creation:  floor(500/100 * 30) = 150 days -> 2026-09-01 + 150d
                    = 2027-01-29 (cycle-based; calendar is created_at + 72
                    months = 2032-09-01, so min() picks cycle-based);
      after verify: llp 500 - 300 = 200 -> floor(200/100 * 30) = 60 days
                    -> 2026-09-01 + 60d = 2026-10-31, earlier than planned
                    2027-06-01, so planned auto-advances; the lease window
                    [2027-05-20, 2027-06-20) does not contain 2026-10-31.

    Design: Difficulty/transitive_cascade/verify_report_to_lease_cancel_chain
    """
    fx = setup_enrolled_engine(
        esn="ESN-G701",
        base_severity_tier="MODERATE",
        llp_remaining_cycles=500,
        assumed_annual_hours=2000,
        assumed_cycles_per_month=100,
        agreement_overrides={"contract_ref": "LTSA-G07"},
    )
    visit = create_visit(fx["engine"], fx["operator_headers"],
                         "2027-06-01T00:00:00Z")
    assert visit["forecast_induction_date"].startswith("2027-01-29")
    assert visit["forecast_method"] == "CYCLE_BASED"

    spare = create_spare_engine(spare_serial="SP-G1", daily_lease_rate_usd=5000)
    create_lease(spare, visit, fx["operator_headers"],
                 "2027-05-20T00:00:00Z", "2027-06-20T00:00:00Z")

    report = submit_report(fx["engine"], fx["operator_headers"],
                           period="2026-09", flight_hours=100, cycles=300,
                           observed_severity="MODERATE")
    verify_report(report)

    engine_after = validate_success(
        api.get_engine(fx["engine"]["id"], shop_planner_headers), 200)
    assert engine_after["llp_remaining_cycles"] == 200

    visit_after = validate_success(
        api.get_shop_visit(visit["id"], shop_planner_headers), 200)
    assert visit_after["planned_induction_date"].startswith("2026-10-31")
    assert visit_after["forecast_induction_date"].startswith("2026-10-31")

    leases, _ = validate_paginated(
        api.list_spare_engine_leases(spare["id"], shop_planner_headers))
    assert leases[0]["status"] == "CANCELLED"


def test_report_initial_state_and_double_verify(api, finance_controller_headers):
    """PRD §3.3: "A new report is created `SUBMITTED` with `verified_at`
    unset." and "A `FinanceController` verifies a `SUBMITTED` report, moving
    it to `VERIFIED` — a terminal state; verifying an already-`VERIFIED`
    report is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/report_initial_state_and_double_verify
    """
    fx = setup_enrolled_engine(
        esn="ESN-S101", agreement_overrides={"contract_ref": "LTSA-C401"}
    )
    report = submit_report(fx["engine"], fx["operator_headers"],
                           period="2026-09", flight_hours=150, cycles=60,
                           observed_severity="BENIGN")
    assert report["status"] == "SUBMITTED"
    assert report["verified_at"] is None

    verified = verify_report(report)
    assert verified["status"] == "VERIFIED"

    res = api.verify_flight_hour_report(report["id"], finance_controller_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_duplicate_report_period_rejected(api):
    """PRD §3.3: "One report exists per engine per period — a second
    submission for the same `(engine_id, period)` pair is rejected with
    `ERR_DUPLICATE_REPORT`".

    Design: Corner/validations/duplicate_report_period_rejected
    """
    fx = setup_enrolled_engine(
        esn="ESN-H201", agreement_overrides={"contract_ref": "LTSA-V1701"}
    )
    submit_report(fx["engine"], fx["operator_headers"], period="2026-09",
                  flight_hours=100, cycles=40, observed_severity="BENIGN")
    res = api.submit_flight_hour_report(
        fx["engine"]["id"],
        create_flight_hour_report_payload(period="2026-09", flight_hours=120,
                                          cycles=45, observed_severity="BENIGN"),
        fx["operator_headers"],
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_REPORT.value)


def test_future_report_period_rejected(api):
    """PRD §2.4: "A report or statement whose `period` is after the current
    logical-clock month is rejected with `ERR_FUTURE_PERIOD`."
    Logical clock is 2026-09-01 (PRD §2.4), so 2026-10 is a future month.

    Design: Corner/validations/future_report_period_rejected
    """
    fx = setup_enrolled_engine(
        esn="ESN-I301", agreement_overrides={"contract_ref": "LTSA-V1901"}
    )
    res = api.submit_flight_hour_report(
        fx["engine"]["id"],
        create_flight_hour_report_payload(period="2026-10", flight_hours=100,
                                          cycles=40, observed_severity="BENIGN"),
        fx["operator_headers"],
    )
    validate_error(res, ApiErrorId.ERR_FUTURE_PERIOD.value)


def test_report_requires_enrollment(api):
    """PRD §3.3: "Submission is only meaningful for an engine under contract
    and on wing: reporting for an engine with no `agreement_id` is rejected
    with `ERR_ENGINE_NOT_ENROLLED`".

    Design: Corner/validations/report_requires_enrollment
    """
    operator = create_operator(name="Nova Air", iata_code="NA", credit_rating="B")
    engine = create_engine(operator, esn="ESN-N101")
    res = api.submit_flight_hour_report(
        engine["id"],
        create_flight_hour_report_payload(period="2026-09", flight_hours=100,
                                          cycles=40, observed_severity="BENIGN"),
        make_operator_headers(operator["id"]),
    )
    validate_error(res, ApiErrorId.ERR_ENGINE_NOT_ENROLLED.value)


def test_report_blocked_while_engine_in_shop(api):
    """PRD §3.3: "reporting while the engine is `IN_SHOP` is rejected with
    `ERR_ENGINE_IN_SHOP`."

    Design: Corner/validations/report_blocked_while_engine_in_shop
    """
    fx = setup_enrolled_engine(
        esn="ESN-N201", agreement_overrides={"contract_ref": "LTSA-V2501"}
    )
    fx = setup_inducted_visit(fx)
    engine = validate_success(
        api.get_engine(fx["engine"]["id"], TEST_USERS["shop_planner_headers"]),
        200,
    )
    assert engine["status"] == "IN_SHOP"
    res = api.submit_flight_hour_report(
        fx["engine"]["id"],
        create_flight_hour_report_payload(period="2026-09", flight_hours=100,
                                          cycles=40, observed_severity="BENIGN"),
        fx["operator_headers"],
    )
    validate_error(res, ApiErrorId.ERR_ENGINE_IN_SHOP.value)
