"""Composite setup helpers. Each fixture builds its preconditions from scratch
using only PRD-declared endpoints: the harness restarts the server before every
test, so nothing carries over. Setup calls use get_success_data (lenient 2xx)
so a broken precondition surfaces as a clear setup error."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .factories import (
    close_run_payload,
    create_disposal_ticket_payload,
    create_donation_payload,
    create_donation_site_payload,
    create_funding_allocation_payload,
    create_member_org_payload,
    create_mission_program_payload,
    create_processing_run_payload,
    create_production_standard_payload,
    create_salvage_lot_payload,
    create_sort_payload,
    create_territory_payload,
    create_workforce_contract_payload,
    milestone_payload,
    sort_item_descriptor,
)
from .test_users import (
    TEST_USERS,
    make_compliance_officer_headers,
    make_contract_manager_headers,
    make_donation_attendant_headers,
    make_member_admin_headers,
    make_member_cfo_headers,
    make_production_lead_headers,
    make_program_director_headers,
    make_store_associate_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
REGULATOR = TEST_USERS["brand_regulator_headers"]
ASSOCIATE = TEST_USERS["store_associate_headers"]
LEAD = TEST_USERS["production_lead_headers"]


# ---------------------------------------------------------------------------
# Tier 0: primitives
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_org(name="Org", reserve_floor_cents=0, diversion_floor_bps=7500,
               costing_method=None) -> dict:
    payload = create_member_org_payload(
        name=name, reserve_floor_cents=reserve_floor_cents,
        diversion_floor_bps=diversion_floor_bps)
    if costing_method is not None:
        payload["costing_method"] = costing_method
    return get_success_data(api_client.create_member_org(payload, ADMIN))


def get_org(org_id) -> dict:
    return get_success_data(api_client.get_member_org(org_id, ADMIN))


def current_org_version(org_id) -> int:
    return get_org(org_id)["version"]


def create_site(org_id, name="Site", site_type="ADC") -> dict:
    return get_success_data(api_client.create_donation_site(
        create_donation_site_payload(org_id, name=name, site_type=site_type),
        make_member_admin_headers(org_id)))


def create_standard(org_id, **overrides) -> dict:
    """Create a production standard; reads the live org version for OCC."""
    payload = create_production_standard_payload(
        org_id, current_org_version(org_id), **overrides)
    return get_success_data(api_client.create_production_standard(
        payload, make_member_admin_headers(org_id)))


def create_donation(site_id, donor_name="Donor", item_count=1, **overrides) -> dict:
    payload = create_donation_payload(
        site_id, donor_name=donor_name, item_count_declared=item_count, **overrides)
    return get_success_data(api_client.create_donation(
        payload, make_donation_attendant_headers(site_id)))


def sort_donation(site_id, donation_id, items) -> dict:
    return get_success_data(api_client.sort_donation(
        donation_id, create_sort_payload(items),
        make_donation_attendant_headers(site_id)))


def list_items(params=None, headers=None) -> list:
    data, _meta = validate_paginated(
        api_client.list_donated_items(headers or ADMIN, params=params))
    return data


def create_sorted_items(site_id, items, donor_name="Donor"):
    """Donation declared len(items) + sort + fetch materialized items.
    Returns (donation, items_list)."""
    donation = create_donation(site_id, donor_name=donor_name, item_count=len(items))
    donation = sort_donation(site_id, donation["id"], items)
    return donation, list_items({"donation_id": donation["id"], "limit": 100})


def price_item(item_id) -> dict:
    return get_success_data(api_client.price_item(item_id, ASSOCIATE))


def sell_item(item_id) -> dict:
    return get_success_data(api_client.sell_item(item_id, ASSOCIATE))


# ---------------------------------------------------------------------------
# Tier 1/2: org + site + standard hierarchies
# ---------------------------------------------------------------------------

def setup_org_with_standard(name="Org", reserve_floor_cents=0,
                            diversion_floor_bps=7500, costing_method=None,
                            site_type="ADC", **std_overrides):
    """Org + one site + one standard (default shared TEXTILES fixture).
    Returns (org, site, standard)."""
    org = create_org(name, reserve_floor_cents=reserve_floor_cents,
                     diversion_floor_bps=diversion_floor_bps,
                     costing_method=costing_method)
    site = create_site(org["id"], name=f"{name} Site", site_type=site_type)
    standard = create_standard(org["id"], **std_overrides)
    return org, site, standard


def create_priced_item(org_id, site_id, category="TEXTILES", grade="A",
                       estimated_value_cents=100, weight_lbs=5.0,
                       donor_name="Donor") -> dict:
    """Donation + sort + price. Requires an ACTIVE standard for the category."""
    _donation, items = create_sorted_items(
        site_id,
        [sort_item_descriptor(category=category, condition_grade=grade,
                              estimated_value_cents=estimated_value_cents,
                              weight_lbs=weight_lbs)],
        donor_name=donor_name)
    return price_item(items[0]["id"])


def create_sold_item(org_id, site_id, **item_kwargs) -> dict:
    """Donation + sort + price + sell. Returns the SOLD item."""
    item = create_priced_item(org_id, site_id, **item_kwargs)
    return sell_item(item["id"])


def create_salvaged_item(site_id, weight_lbs, category="TEXTILES",
                         donor_name="Donor") -> dict:
    """An UNSALABLE-grade item, born SALVAGED at sort (never priced)."""
    _donation, items = create_sorted_items(
        site_id,
        [sort_item_descriptor(category=category, condition_grade="UNSALABLE",
                              estimated_value_cents=0, weight_lbs=weight_lbs)],
        donor_name=donor_name)
    return items[0]


# ---------------------------------------------------------------------------
# Tier 2/3: retail margin accumulation
# ---------------------------------------------------------------------------

def setup_org_with_pool(name="Org Pool", sales=1, reserve_floor_cents=0):
    """Org + site + standard, then `sales` grade-A items priced and sold.
    Under the shared fixture each sale accrues 1000 - 30 = 970 margin.
    Returns (org_refetched, site, standard)."""
    org, site, standard = setup_org_with_standard(
        name, reserve_floor_cents=reserve_floor_cents)
    for i in range(sales):
        create_sold_item(org["id"], site["id"], donor_name=f"Donor {i}")
    return get_org(org["id"]), site, standard


# ---------------------------------------------------------------------------
# Salvage / disposal
# ---------------------------------------------------------------------------

def create_lot(org_id, channel, item_ids) -> dict:
    return get_success_data(api_client.create_salvage_lot(
        create_salvage_lot_payload(org_id, channel, item_ids),
        make_member_admin_headers(org_id)))


def sell_lot(org_id, lot_id) -> dict:
    return get_success_data(api_client.sell_salvage_lot(
        lot_id, make_member_admin_headers(org_id)))


def create_sold_bale_lot(org_id, site_id, weight_lbs, donor_name="Donor") -> dict:
    """One UNSALABLE TEXTILES item of `weight_lbs` -> TEXTILE_BALE lot -> SOLD.
    Diverts `weight_lbs` and accrues bale revenue into the margin pool."""
    item = create_salvaged_item(site_id, weight_lbs, category="TEXTILES",
                                donor_name=donor_name)
    lot = create_lot(org_id, "TEXTILE_BALE", [item["id"]])
    return sell_lot(org_id, lot["id"])


def create_disposal_ticket(org_id, material, weight_lbs) -> dict:
    return get_success_data(api_client.create_disposal_ticket(
        create_disposal_ticket_payload(org_id, material, weight_lbs),
        make_member_admin_headers(org_id)))


# ---------------------------------------------------------------------------
# Mission funding
# ---------------------------------------------------------------------------

def create_program(org_id, name="Prog", program_type="JOB_TRAINING",
                   director_id="pd-1", **overrides) -> dict:
    return get_success_data(api_client.create_mission_program(
        create_mission_program_payload(
            org_id, name=name, program_type=program_type, **overrides),
        make_program_director_headers(director_id)))


def create_allocation(org_id, program_id, amount_cents, creator_id="pd-1") -> dict:
    """Create a PENDING allocation; reads the live org version for OCC."""
    payload = create_funding_allocation_payload(
        program_id, amount_cents, current_org_version(org_id))
    return get_success_data(api_client.create_funding_allocation(
        payload, make_program_director_headers(creator_id)))


def approve_allocation(allocation_id, cfo_id="cfo-1") -> dict:
    return get_success_data(api_client.approve_allocation(
        allocation_id, make_member_cfo_headers(cfo_id)))


def cancel_allocation(allocation_id, role_headers) -> dict:
    return get_success_data(api_client.cancel_allocation(allocation_id, role_headers))


def disburse_allocation(allocation_id, cfo_id="cfo-1") -> dict:
    return get_success_data(api_client.disburse_allocation(
        allocation_id, make_member_cfo_headers(cfo_id)))


def get_allocation(allocation_id) -> dict:
    return get_success_data(api_client.get_funding_allocation(allocation_id, ADMIN))


def list_allocations(params=None) -> list:
    data, _meta = validate_paginated(
        api_client.list_funding_allocations(ADMIN, params=params))
    return data


def setup_pending_allocation(name="Org Alloc", amount_cents=500,
                             reserve_floor_cents=0, sales=1,
                             program_overrides=None, creator_id="pd-1"):
    """Org with `sales` grade-A sales of pool, one program inside its window,
    and one PENDING allocation. Returns (org, site, standard, program, alloc)."""
    org, site, standard = setup_org_with_pool(
        name, sales=sales, reserve_floor_cents=reserve_floor_cents)
    program = create_program(org["id"], **(program_overrides or {}))
    alloc = create_allocation(org["id"], program["id"], amount_cents,
                              creator_id=creator_id)
    return get_org(org["id"]), site, standard, program, alloc


# ---------------------------------------------------------------------------
# Workforce contracts
# ---------------------------------------------------------------------------

def create_contract(org_id, milestones, creator_id="cm-1", **overrides) -> dict:
    return get_success_data(api_client.create_workforce_contract(
        create_workforce_contract_payload(org_id, milestones, **overrides),
        make_contract_manager_headers(creator_id)))


def list_contract_milestones(contract_id) -> list:
    data, _meta = validate_paginated(
        api_client.list_milestones(ADMIN, params={"contract_id": contract_id}))
    return data


def review_action(contract_id, action, officer_id="co-1") -> dict:
    return get_success_data(api_client.create_review(
        contract_id, action, make_compliance_officer_headers(officer_id)))


def attest_milestone(milestone_id, officer_id="co-2") -> dict:
    return get_success_data(api_client.attest_milestone(
        milestone_id, make_compliance_officer_headers(officer_id)))


def get_milestone(milestone_id) -> dict:
    return get_success_data(api_client.get_milestone(milestone_id, ADMIN))


# ---------------------------------------------------------------------------
# Processing runs
# ---------------------------------------------------------------------------

def create_run(site_id, standard_id) -> dict:
    return get_success_data(api_client.create_processing_run(
        create_processing_run_payload(site_id, standard_id), LEAD))


def close_run(run_id, **overrides) -> dict:
    return get_success_data(api_client.close_processing_run(
        run_id, close_run_payload(**overrides), LEAD))


def get_run(run_id) -> dict:
    return get_success_data(api_client.get_processing_run(run_id, ADMIN))


# ---------------------------------------------------------------------------
# Territories
# ---------------------------------------------------------------------------

def create_territory(org_id, region_code, effective_from, effective_to=None) -> dict:
    payload = create_territory_payload(
        org_id, region_code=region_code, effective_from=effective_from)
    if effective_to is not None:
        payload["effective_to"] = effective_to
    return get_success_data(api_client.create_territory(payload, REGULATOR))


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

def run_markdown_event(org_id) -> dict:
    return get_success_data(api_client.create_markdown_event(
        org_id, make_member_admin_headers(org_id)))
