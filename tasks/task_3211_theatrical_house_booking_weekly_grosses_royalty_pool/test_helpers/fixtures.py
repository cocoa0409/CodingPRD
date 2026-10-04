"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints; the runner restarts the server before every test, so each test
starts against an empty database.

Standard calendar used across fixtures (all Mondays 00:00:00Z):
  loadin 2026-09-06, run_end 2026-11-01
  week1 2026-09-07 .. 2026-09-14
  week2 2026-09-14 .. 2026-09-21
  week3 2026-09-21 .. 2026-09-28
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START, TEST_DEFAULTS
from .factories import (
    create_company_payload, create_theatre_payload, create_production_payload,
    create_booking_payload, create_license_agreement_payload,
    sign_license_agreement_payload, create_ticket_order_payload,
    create_weekly_gross_report_payload, create_crew_assignment_payload,
    create_capital_project_payload, create_royalty_participant_payload,
)
from .test_users import (
    TEST_USERS, make_company_rep_headers,
)

HM = TEST_USERS["house_manager_headers"]
BO = TEST_USERS["box_office_agent_headers"]


def reset_clock():
    get_success_data(api_client.set_clock(CLOCK_START, HM))


def create_company(name="TestCo", email="co@x.com"):
    data = get_success_data(api_client.create_company(
        create_company_payload(name=name, contact_email=email), HM))
    return data


def create_theatre(name="House", size_class="SMALL", is_landmark=False,
                   base_weekly_rent_cents=500000, capacity=500):
    return get_success_data(api_client.create_theatre(
        create_theatre_payload(name=name, capacity=capacity,
                               size_class=size_class, is_landmark=is_landmark,
                               base_weekly_rent_cents=base_weekly_rent_cents),
        HM))


def create_production(company_id, title="Show", required_size_class="SMALL",
                      required_loadin_hours=24, required_loadout_hours=24):
    return get_success_data(api_client.create_production(
        create_production_payload(
            company_id, title=title, required_size_class=required_size_class,
            required_loadin_hours=required_loadin_hours,
            required_loadout_hours=required_loadout_hours),
        make_company_rep_headers(company_id)))


def create_booking(production_id, theatre_id, company_id,
                   loadin_start=TEST_DEFAULTS["LOADIN_START"],
                   run_end=TEST_DEFAULTS["RUN_END"]):
    return get_success_data(api_client.create_booking(
        create_booking_payload(production_id, theatre_id,
                               loadin_start=loadin_start, run_end=run_end),
        make_company_rep_headers(company_id)))


def approve_booking(booking_id):
    return get_success_data(api_client.approve_booking(booking_id, HM))


def create_license(booking_id, expected_booking_version,
                   weekly_rent_cents=500000,
                   stop_clause_weekly_floor_cents=10000,
                   stop_clause_consecutive_weeks=2):
    return get_success_data(api_client.create_license_agreement(
        booking_id,
        create_license_agreement_payload(
            expected_booking_version,
            weekly_rent_cents=weekly_rent_cents,
            stop_clause_weekly_floor_cents=stop_clause_weekly_floor_cents,
            stop_clause_consecutive_weeks=stop_clause_consecutive_weeks),
        HM))


def booking_version(booking_id):
    return get_success_data(api_client.get_booking(booking_id, HM))["version"]


def sign_license(license_id, expected_booking_version, company_id):
    return get_success_data(api_client.sign_license_agreement(
        license_id, sign_license_agreement_payload(expected_booking_version),
        make_company_rep_headers(company_id)))


def create_and_sign_license(booking_id, company_id,
                            weekly_rent_cents=500000,
                            stop_clause_weekly_floor_cents=10000,
                            stop_clause_consecutive_weeks=2):
    """Create a license on the booking and sign it. Returns the SIGNED license."""
    lic = create_license(booking_id, booking_version(booking_id),
                         weekly_rent_cents=weekly_rent_cents,
                         stop_clause_weekly_floor_cents=stop_clause_weekly_floor_cents,
                         stop_clause_consecutive_weeks=stop_clause_consecutive_weeks)
    return sign_license(lic["id"], booking_version(booking_id), company_id)


def engage_crew(booking_id, crew_size=4):
    return get_success_data(api_client.create_crew_assignment(
        booking_id, create_crew_assignment_payload(crew_size=crew_size), HM))


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, HM))


def sell_order(booking_id, **overrides):
    return get_success_data(api_client.create_ticket_order(
        booking_id, create_ticket_order_payload(**overrides), BO))


def open_report(booking_id, company_id,
                week_start=TEST_DEFAULTS["WEEK1_START"]):
    return get_success_data(api_client.create_weekly_gross_report(
        booking_id, create_weekly_gross_report_payload(week_start=week_start),
        make_company_rep_headers(company_id)))


def submit_report(report_id, company_id):
    return get_success_data(api_client.submit_weekly_gross_report(
        report_id, make_company_rep_headers(company_id)))


def verify_report(report_id):
    return get_success_data(api_client.verify_weekly_gross_report(report_id, HM))


def get_booking(booking_id):
    return get_success_data(api_client.get_booking(booking_id, HM))


def get_report(report_id):
    return get_success_data(api_client.get_weekly_gross_report(report_id, HM))


def get_order(order_id):
    return get_success_data(api_client.get_ticket_order(order_id, HM))


def get_license(license_id):
    return get_success_data(api_client.get_license_agreement(license_id, HM))


def list_stop_notices(booking_id):
    data, _meta = _paginated(api_client.list_booking_stop_notices(booking_id, HM))
    return data


def list_licenses(booking_id):
    data, _meta = _paginated(
        api_client.list_booking_license_agreements(booking_id, HM))
    return data


def _paginated(resp):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(resp)


def setup_approved_booking(size_class="SMALL", is_landmark=False,
                           base_weekly_rent_cents=500000,
                           required_loadout_hours=24,
                           company_name="Co", company_email="co@x.com",
                           house_name="House", production_title="Show"):
    """Company + house + production + REQUESTED booking, then approved.

    Returns dict with company, theatre, production, booking (APPROVED), rep headers.
    """
    reset_clock()
    company = create_company(company_name, company_email)
    theatre = create_theatre(house_name, size_class=size_class,
                             is_landmark=is_landmark,
                             base_weekly_rent_cents=base_weekly_rent_cents,
                             capacity={"SMALL": 500, "MEDIUM": 1200,
                                       "LARGE": 1800}[size_class])
    production = create_production(
        company["id"], title=production_title,
        required_size_class=size_class,
        required_loadout_hours=required_loadout_hours)
    rep = make_company_rep_headers(company["id"])
    booking = create_booking(production["id"], theatre["id"], company["id"])
    approve_booking(booking["id"])
    booking = get_booking(booking["id"])
    return {"company": company, "theatre": theatre, "production": production,
            "booking": booking, "rep": rep}


def setup_active_booking(crew_size=None, size_class="SMALL",
                         weekly_rent_cents=500000,
                         stop_clause_weekly_floor_cents=10000,
                         stop_clause_consecutive_weeks=2,
                         **kwargs):
    """APPROVED booking + SIGNED license + crew engaged + clock at week1 start
    (booking flips to ACTIVE). Returns the setup dict with 'license'."""
    ctx = setup_approved_booking(size_class=size_class, **kwargs)
    if crew_size is None:
        crew_size = {"SMALL": 4, "MEDIUM": 8, "LARGE": 14}[size_class]
    lic = create_and_sign_license(
        ctx["booking"]["id"], ctx["company"]["id"],
        weekly_rent_cents=weekly_rent_cents,
        stop_clause_weekly_floor_cents=stop_clause_weekly_floor_cents,
        stop_clause_consecutive_weeks=stop_clause_consecutive_weeks)
    engage_crew(ctx["booking"]["id"], crew_size)
    set_clock(TEST_DEFAULTS["WEEK1_START"])
    ctx["license"] = lic
    ctx["booking"] = get_booking(ctx["booking"]["id"])
    return ctx


def sell_week1_order(booking_id, ticket_count=2, face_value_cents=5000,
                     performance_date="2026-09-08T19:00:00Z", **overrides):
    return sell_order(booking_id, performance_date=performance_date,
                      ticket_count=ticket_count,
                      face_value_cents=face_value_cents, **overrides)


def verified_report_for_week1(ctx, orders=None):
    """Sell the given orders (each a dict of sell_order overrides) in week 1,
    open the week-1 report, advance clock to week1 end, submit + verify.
    Returns the VERIFIED report."""
    for o in (orders or [{"ticket_count": 2, "face_value_cents": 5000}]):
        sell_week1_order(ctx["booking"]["id"], **o)
    rep = open_report(ctx["booking"]["id"], ctx["company"]["id"])
    set_clock(TEST_DEFAULTS["WEEK1_END"])
    submit_report(rep["id"], ctx["company"]["id"])
    return verify_report(rep["id"])


def add_pool_participant(production_id, company_id, name, points):
    return get_success_data(api_client.create_royalty_participant(
        production_id,
        create_royalty_participant_payload(participant_name=name,
                                           royalty_points=points,
                                           pool_eligible=True),
        make_company_rep_headers(company_id)))


def add_fixed_participant(production_id, company_id, name, points,
                          fixed_royalty_cents):
    return get_success_data(api_client.create_royalty_participant(
        production_id,
        create_royalty_participant_payload(participant_name=name,
                                           royalty_points=points,
                                           pool_eligible=False,
                                           fixed_royalty_cents=fixed_royalty_cents),
        make_company_rep_headers(company_id)))
