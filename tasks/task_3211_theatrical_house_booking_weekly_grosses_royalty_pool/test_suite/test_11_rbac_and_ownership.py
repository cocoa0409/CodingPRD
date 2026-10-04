"""RBAC and ownership claims."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId,
    TEST_USERS, make_company_rep_headers,
    create_company, create_theatre, create_production, create_booking,
    setup_active_booking, sell_week1_order, open_report, set_clock,
    submit_report, get_booking, create_discount_code_payload,
    TEST_DEFAULTS,
)

HM = TEST_USERS["house_manager_headers"]
BO = TEST_USERS["box_office_agent_headers"]


def test_box_office_agent_cannot_approve_booking(api):
    """PRD §2.1: "A `BoxOfficeAgent` operates the box office: sells and
    refunds ticket orders and otherwise only reads."
    PRD §2.1: "Missing headers, an unrecognized role, a role not authorized
    for the endpoint, or a `CompanyRep` crossing company ownership are all
    rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/box_office_agent_cannot_approve_booking
    """
    from test_helpers import reset_clock, approve_booking  # noqa: F401
    reset_clock()
    comp = create_company("RbacCo", "rb@x.com")
    house = create_theatre("BijouRb")
    prod = create_production(comp["id"], title="Show Rb")
    bk = create_booking(prod["id"], house["id"], comp["id"])
    resp = api_client.approve_booking(bk["id"], BO)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_company_rep_cannot_verify_own_gross_report(api):
    """PRD §2.1: "Segregation of duties applies: the representative who owns a
    production cannot verify that production's grosses — verification is
    strictly a `HouseManager` duty."

    Design: Corner/rbac/company_rep_cannot_verify_own_gross_report
    """
    ctx = setup_active_booking(company_name="SodCo", company_email="so@x.com")
    sell_week1_order(ctx["booking"]["id"])
    rep = open_report(ctx["booking"]["id"], ctx["company"]["id"])
    set_clock(TEST_DEFAULTS["WEEK1_END"])
    submit_report(rep["id"], ctx["company"]["id"])
    resp = api_client.verify_weekly_gross_report(rep["id"], ctx["rep"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_foreign_company_rep_cannot_withdraw_booking(api):
    """PRD §2.1: "When `X-User-Role` is `CompanyRep`, `X-User-ID` is the `id`
    of the acting `ProductionCompany`; ownership checks on any resource that
    references a `ProductionCompany` compare the resource's foreign-key field
    (for a `Production`, its `company_id`; for anything downstream of a
    production, the owning company's id resolved through the production) to
    `X-User-ID`. A `CompanyRep` acting on a resource owned by another company
    is rejected."

    Design: Corner/validations/foreign_company_rep_cannot_withdraw_booking
    """
    from test_helpers import reset_clock
    reset_clock()
    comp_a = create_company("OwnCo", "ow@x.com")
    comp_b = create_company("OtherCo", "ot@x.com")
    house = create_theatre("BijouO")
    prod = create_production(comp_a["id"], title="Show O")
    bk = create_booking(prod["id"], house["id"], comp_a["id"])
    resp = api_client.withdraw_booking(bk["id"], make_company_rep_headers(comp_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_booking(bk["id"])["status"] == "REQUESTED"


def test_discount_code_wrong_production_rejected(api):
    """PRD §3.5: "An order that applies a code belonging to a different
    production, an inactive code, or a code whose `percent_off` is out of
    range is rejected with `ERR_DISCOUNT_CODE_INVALID` (HTTP 422)."

    Design: Corner/errors/discount_code_wrong_production_rejected
    """
    from test_helpers import reset_clock, approve_booking, create_and_sign_license
    reset_clock()
    comp_a = create_company("DACo", "da@x.com")
    comp_b = create_company("DBCo", "db@x.com")
    house_a = create_theatre("HA")
    house_b = create_theatre("HB")
    prod_a = create_production(comp_a["id"], title="Show DA")
    prod_b = create_production(comp_b["id"], title="Show DB")
    bk_b = create_booking(prod_b["id"], house_b["id"], comp_b["id"])
    approve_booking(bk_b["id"])
    create_and_sign_license(bk_b["id"], comp_b["id"])
    from test_helpers import engage_crew
    engage_crew(bk_b["id"], 4)
    set_clock(TEST_DEFAULTS["WEEK1_START"])
    code_a = validate_success(api_client.create_discount_code(
        prod_a["id"], create_discount_code_payload(code="ACODE", percent_off=10),
        make_company_rep_headers(comp_a["id"])), expected_status=201)
    resp = api_client.create_ticket_order(
        bk_b["id"],
        {"performance_date": "2026-09-08T19:00:00Z", "ticket_count": 2,
         "is_group_sale": False, "face_value_cents": 5000,
         "discount_code_id": code_a["id"]},
        BO)
    validate_error(resp, ApiErrorId.ERR_DISCOUNT_CODE_INVALID)
