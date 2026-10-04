"""Employee transition tests: severance tiers and the union rule."""
from test_helpers import (
    api_client, TEST_USERS,
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    assert_employee_transition,
    setup_target_in_valuation,
    register_employee,
    make_headers,
)


def test_severance_exactly_5_years_gets_4_weeks(api):
    """PRD §3.6: "Severance is computed by service tier: at least 10 years of
    service earns 8 weeks; at least 5 years (but fewer than 10) earns 4 weeks;
    at least 1 year (but fewer than 5) earns 2 weeks; fewer than 1 year earns 1
    week. The boundaries are inclusive — exactly 5 years earns 4 weeks, exactly
    10 years earns 8, and exactly 0 years earns 1. `severance_cents` is the
    `severance_weeks` multiplied by the employee's `weekly_salary_cents`."

    Design: Difficulty/boundary_precision_check/severance_exactly_5_years_gets_4_weeks
    """
    target, _, _ = setup_target_in_valuation(state_code="OH", customer_count=10)
    emp = register_employee(target["id"], employee_ref="E5", years_of_service=5,
                            weekly_salary_cents=120000, union_covered=False)
    resp = api.respond_to_offer(emp["id"], {"response": "DECLINED"},
                                TEST_USERS["hr_headers"])
    declined = validate_success(resp, 200)
    assert declined["status"] == "DECLINED"
    assert declined["severance_weeks"] == 4
    assert declined["severance_cents"] == 480000


def test_severance_exactly_10_years_gets_8_weeks(api):
    """PRD §3.6: "The boundaries are inclusive — exactly 5 years earns 4 weeks,
    exactly 10 years earns 8, and exactly 0 years earns 1."

    Design: Difficulty/boundary_precision_check/severance_exactly_5_years_gets_4_weeks
    """
    target, _, _ = setup_target_in_valuation(state_code="OH", customer_count=10)
    emp = register_employee(target["id"], employee_ref="E10", years_of_service=10,
                            weekly_salary_cents=100000, union_covered=False)
    declined = get_success_data(api.respond_to_offer(
        emp["id"], {"response": "DECLINED"}, TEST_USERS["hr_headers"]))
    assert declined["severance_weeks"] == 8
    assert declined["severance_cents"] == 800000


def test_severance_exactly_0_years_gets_1_week(api):
    """PRD §3.6: "fewer than 1 year earns 1 week ... exactly 0 years earns 1."

    Design: Difficulty/boundary_precision_check/severance_exactly_5_years_gets_4_weeks
    """
    target, _, _ = setup_target_in_valuation(state_code="OH", customer_count=10)
    emp = register_employee(target["id"], employee_ref="E0", years_of_service=0,
                            weekly_salary_cents=50000, union_covered=False)
    declined = get_success_data(api.respond_to_offer(
        emp["id"], {"response": "DECLINED"}, TEST_USERS["hr_headers"]))
    assert declined["severance_weeks"] == 1
    assert declined["severance_cents"] == 50000


def test_union_employee_cannot_decline_must_be_assumed(api):
    """PRD §3.6: "the union rule is strict: a union-covered employee may not
    decline — declining a union-covered employee is rejected with
    `ERR_UNION_ASSUMPTION_REQUIRED` (HTTP 409) — and a non-union employee may
    not be recorded `ASSUMED`, which draws the same error."
    and "**`ASSUMED`.** Union only. The union agreement is assumed in full;
    `severance_weeks` and `severance_cents` are both zero."

    Design: Corner/validations/union_employee_cannot_decline_must_be_assumed
    """
    target, _, _ = setup_target_in_valuation(state_code="OH", customer_count=5)
    emp = register_employee(target["id"], employee_ref="U1", years_of_service=12,
                            weekly_salary_cents=200000, union_covered=True)
    resp = api.respond_to_offer(emp["id"], {"response": "DECLINED"},
                                TEST_USERS["hr_headers"])
    validate_error(resp, ApiErrorId.ERR_UNION_ASSUMPTION_REQUIRED)
    assumed = get_success_data(api.respond_to_offer(
        emp["id"], {"response": "ASSUMED"}, TEST_USERS["hr_headers"]))
    assert assumed["status"] == "ASSUMED"
    assert assumed["severance_cents"] == 0
    assert assumed["severance_weeks"] == 0
