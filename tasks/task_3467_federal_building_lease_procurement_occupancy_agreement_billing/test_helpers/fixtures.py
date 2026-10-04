"""Composite setup helpers.

Most claims require the portfolio to be in a specific state that takes 5-15
API calls to reach (agency -> building -> clock -> requirement -> submit ->
validate -> market survey -> offer -> evaluate -> select -> commence -> OA ->
activate -> ...). These helpers encapsulate those chains so tests focus on
assertions. All setup calls use the lenient get_success_data validator so a
setup failure surfaces as a clear setup error, not an assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import SETUP_CLOCK_ISO
from .factories import (
    commence_lease_payload, create_agency_payload, create_alteration_payload,
    create_leased_oa_payload, create_offer_payload, create_owned_building_payload,
    create_owned_oa_payload, create_building_payload, create_requirement_payload,
    create_service_ticket_payload, create_survey_payload,
    create_tax_statement_payload, estimate_alteration_payload,
    select_option_payload,
)
from .test_users import TEST_USERS, make_agency_manager_headers

ADMIN = TEST_USERS["gsa_admin_headers"]
OFFICER = TEST_USERS["gsa_leasing_officer_headers"]
PM = TEST_USERS["gsa_property_manager_headers"]
LESSOR = TEST_USERS["lessor_rep_headers"]


# --- Tier 0: single-resource creation ----------------------------------------

def set_clock(to_iso8601):
    """Advance the logical clock; returns the sweep report."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_agency(name="Forest Service", **overrides):
    return get_success_data(api_client.create_agency(
        create_agency_payload(name=name, **overrides), ADMIN))


def create_leased_building(**overrides):
    return get_success_data(api_client.create_building(
        create_building_payload(**overrides), ADMIN))


def create_owned_building(**overrides):
    return get_success_data(api_client.create_building(
        create_owned_building_payload(**overrides), ADMIN))


def create_requirement(agency, **overrides):
    return get_success_data(api_client.create_space_requirement(
        create_requirement_payload(agency["id"], **overrides),
        make_agency_manager_headers(agency["id"])))


def submit_requirement(req, agency):
    return get_success_data(api_client.submit_requirement(
        req["id"], make_agency_manager_headers(agency["id"])))


# --- Tier 1: requirement lifecycle --------------------------------------------

def walk_requirement_to_soliciting(agency, **req_overrides):
    """Create -> submit -> validate -> complete-market-survey. Returns the
    SOLICITING requirement."""
    req = create_requirement(agency, **req_overrides)
    submit_requirement(req, agency)
    get_success_data(api_client.validate_requirement(req["id"], OFFICER))
    return get_success_data(api_client.complete_market_survey(
        req["id"], {"survey_summary": "Five buildings toured"}, OFFICER))


# --- Tier 2: procurement through award ----------------------------------------

def award_lease(agency, building, req, **offer_overrides):
    """Offer -> evaluate -> select. Returns (offer, created Lease)."""
    offer = get_success_data(api_client.create_offer(
        req["id"], create_offer_payload(building["id"], **offer_overrides), LESSOR))
    get_success_data(api_client.evaluate_offer(offer["id"], OFFICER))
    lease = get_success_data(api_client.select_offer(offer["id"], OFFICER))
    return offer, lease


def setup_awarded_lease(escalation_method="BASE_YEAR_STOP",
                        offer_overrides=None, req_overrides=None,
                        clock=SETUP_CLOCK_ISO):
    """Full procurement chain through lease award. Returns a bundle dict with
    agency / building / req / offer / lease (lease still AWARDED)."""
    agency = create_agency()
    building = create_leased_building()
    if clock is not None:
        set_clock(clock)
    req = walk_requirement_to_soliciting(agency, **(req_overrides or {}))
    offer_kw = dict(offer_overrides or {})
    offer_kw["escalation_method"] = escalation_method
    offer, lease = award_lease(agency, building, req, **offer_kw)
    return {"agency": agency, "building": building, "req": req,
            "offer": offer, "lease": lease}


# --- Tier 3: commencement and occupancy ---------------------------------------

def commence_lease(lease, **overrides):
    return get_success_data(api_client.commence_lease(
        lease["id"], commence_lease_payload(**overrides), OFFICER))


def setup_commenced_lease(escalation_method="BASE_YEAR_STOP",
                          cpi_base_index=None, commencement_date="2027-01-01",
                          ti_amort_method="ANNUITY", **kwargs):
    """Awarded lease then commenced. Bundle includes the COMMENCED lease."""
    bundle = setup_awarded_lease(escalation_method=escalation_method, **kwargs)
    kw = {"commencement_date": commencement_date, "ti_amort_method": ti_amort_method}
    if cpi_base_index is not None:
        kw["cpi_base_index"] = cpi_base_index
    bundle["lease"] = commence_lease(bundle["lease"], **kw)
    return bundle


def create_leased_oa(lease, agency, **overrides):
    return get_success_data(api_client.create_oa(
        create_leased_oa_payload(lease["id"], agency["id"], **overrides), OFFICER))


def create_owned_oa(building, agency, **overrides):
    return get_success_data(api_client.create_oa(
        create_owned_oa_payload(building["id"], agency["id"], **overrides), OFFICER))


def activate_oa(oa, agency):
    return get_success_data(api_client.activate_oa(
        oa["id"], make_agency_manager_headers(agency["id"])))


def add_tax_statement(lease, tax_year, actual_tax_per_sf_yr_cents, cpi_index=None):
    payload = create_tax_statement_payload(tax_year, actual_tax_per_sf_yr_cents)
    if cpi_index is not None:
        payload["cpi_index"] = cpi_index
    return get_success_data(api_client.create_tax_statement(
        lease["id"], payload, OFFICER))


def setup_active_leased_oa(tax_year=2027, actual_tax=460, cpi_index=None, **kwargs):
    """Canonical leased fixture: commenced lease (2027-01-01, 120 months),
    OA over the full 68,300 sf ACTIVated, optional tax statement recorded.
    Bundle keys: agency, building, req, offer, lease, oa."""
    bundle = setup_commenced_lease(**kwargs)
    oa = create_leased_oa(bundle["lease"], bundle["agency"])
    bundle["oa"] = activate_oa(oa, bundle["agency"])
    if tax_year is not None:
        add_tax_statement(bundle["lease"], tax_year, actual_tax, cpi_index)
    return bundle


def setup_active_owned_oa(assigned_sf=20000, clock=SETUP_CLOCK_ISO, **oa_overrides):
    """Owned-building fixture: FEDERALLY_OWNED building (50,000 sf) with one
    ACTIVE OA. Bundle keys: agency, building, oa."""
    agency = create_agency(name="Park Service")
    building = create_owned_building()
    if clock is not None:
        set_clock(clock)
    oa = create_owned_oa(building, agency, assigned_sf=assigned_sf, **oa_overrides)
    oa = activate_oa(oa, agency)
    return {"agency": agency, "building": building, "oa": oa}


# --- Tier 4: billing ----------------------------------------------------------

def generate_bill(oa, billing_month):
    return get_success_data(api_client.generate_bill(
        oa["id"], {"billing_month": billing_month}, PM))


def pay_bill(bill, agency, amount_cents):
    return get_success_data(api_client.pay_bill(
        bill["id"], {"amount_cents": amount_cents},
        make_agency_manager_headers(agency["id"])))


# --- Tier 4: alterations -------------------------------------------------------

def create_alteration(oa, agency, **overrides):
    return get_success_data(api_client.create_alteration(
        oa["id"], create_alteration_payload(**overrides),
        make_agency_manager_headers(agency["id"])))


def estimate_alteration(alt, **overrides):
    return get_success_data(api_client.estimate_alteration(
        alt["id"], estimate_alteration_payload(**overrides), PM))


def approve_alteration(alt, agency, funding_method="LUMP_SUM"):
    return get_success_data(api_client.approve_alteration(
        alt["id"], {"funding_method": funding_method},
        make_agency_manager_headers(agency["id"])))


def complete_alteration(alt, completion_date):
    return get_success_data(api_client.complete_alteration(
        alt["id"], {"completion_date": completion_date}, PM))


# --- Tier 4: service tickets ---------------------------------------------------

def create_ticket(building, oa, agency=None, **overrides):
    """Report a ticket. As the owning AgencyManager when agency is given,
    else as the GSA property manager."""
    headers = make_agency_manager_headers(agency["id"]) if agency else PM
    return get_success_data(api_client.create_service_ticket(
        building["id"], create_service_ticket_payload(oa["id"], **overrides),
        headers))


# --- Tier 4: utilization -------------------------------------------------------

def create_survey(oa, **overrides):
    return get_success_data(api_client.create_survey(
        oa["id"], create_survey_payload(**overrides), PM))


def finalize_survey(survey):
    return get_success_data(api_client.finalize_survey(survey["id"], PM))


def list_reduction_actions(oa, params=None):
    return get_success_data(api_client.list_reduction_actions(oa["id"], ADMIN,
                                                              params=params))


# --- Tier 5: expiration planning ------------------------------------------------

def create_plan(lease):
    return get_success_data(api_client.create_expiration_plan(lease["id"], OFFICER))


def select_plan_option(plan, **overrides):
    return get_success_data(api_client.select_plan_option(
        plan["id"], select_option_payload(**overrides), OFFICER))


def setup_expiring_lease_with_plan(option="SUCCEEDING_LEASE", **select_overrides):
    """Commenced lease swept to EXPIRING (clock 2035-07-01), one plan opened
    and the given option selected. Bundle keys: agency, building, req, offer,
    lease, plan."""
    bundle = setup_commenced_lease()
    set_clock("2035-07-01T00:00:00Z")
    plan = create_plan(bundle["lease"])
    bundle["plan"] = select_plan_option(plan, option=option, **select_overrides)
    return bundle
