"""Composite setup helpers.

Every fixture builds its preconditions from scratch via PRD-declared endpoints
(the server restarts before each test). Fixtures use get_success_data so setup
failures surface as clear errors, and thread entity-backed identities through
make_*_headers.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_account_payload, create_rate_card_payload, create_tool_model_payload,
    create_agreement_payload, create_jobsite_payload, create_loaner_unit_payload,
    create_consumable_product_payload,
)
from .test_users import (
    TEST_USERS, make_contractor_manager_headers, make_jobsite_supervisor_headers,
    make_fleet_admin_headers, make_claims_adjuster_headers,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
COORD = TEST_USERS["service_coordinator_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_account(credit_limit_cents=100_000_000, tax_id=None, company_name=None):
    payload = create_account_payload(
        credit_limit_cents=credit_limit_cents,
        **({} if tax_id is None else {"tax_id": tax_id}),
        **({} if company_name is None else {"company_name": company_name}),
    )
    return get_success_data(api_client.create_account(payload, ADMIN))


def create_rate_card(**overrides):
    return get_success_data(api_client.create_rate_card(
        create_rate_card_payload(**overrides), ADMIN))


def create_tool_model(**overrides):
    return get_success_data(api_client.create_tool_model(
        create_tool_model_payload(**overrides), ADMIN))


def list_agreement_assets(agreement_id):
    data, _meta = _list_assets(params={"agreement_id": agreement_id, "limit": 100})
    return data


def _list_assets(params=None):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(api_client.list_assets(ADMIN, params=params))


def setup_agreement_with_assets(
        n_assets=1, credit_limit_cents=100_000_000, clock=None,
        category="DRILL", weight_class="LIGHT", replacement_value_cents=80000,
        rate_card_overrides=None, term_months=12,
        start_date="2026-09-01T00:00:00Z", end_of_term_option="RETURN",
        activate=True):
    """Account + rate card + tool model + agreement + N REGISTERED assets.

    Returns a dict with account, headers (cm/js), tool_model, agreement,
    asset_ids. When activate=True the agreement is ACTIVE on return.
    """
    if clock is not None:
        set_clock(clock)
    account = create_account(credit_limit_cents=credit_limit_cents)
    acct = account["id"]
    cm = make_contractor_manager_headers(acct)
    js = make_jobsite_supervisor_headers(acct)
    create_rate_card(**({"tool_category": category} if rate_card_overrides is None
                        else dict(rate_card_overrides)))
    tm = create_tool_model(category=category, weight_class=weight_class,
                           replacement_value_cents=replacement_value_cents)
    ag = get_success_data(api_client.create_agreement(
        acct, create_agreement_payload(term_months=term_months,
                                       start_date=start_date,
                                       end_of_term_option=end_of_term_option), ADMIN))
    ag_id = ag["id"]
    ver = ag["version"]
    if n_assets:
        ag = get_success_data(api_client.adjust_fleet(
            acct, ag_id,
            {"expected_agreement_version": ver,
             "add_tool_model_ids": [tm["id"]] * n_assets,
             "return_asset_ids": []}, cm))
        ver = ag["version"]
    asset_ids = [a["id"] for a in list_agreement_assets(ag_id)]
    if activate:
        ag = get_success_data(api_client.activate_agreement(acct, ag_id, ADMIN))
        ver = ag["version"]
    return {
        "account": account, "account_id": acct, "cm": cm, "js": js,
        "tool_model": tm, "agreement": ag, "agreement_id": ag_id,
        "agreement_version": ver, "asset_ids": asset_ids,
    }


def create_jobsite(account_id, capacity_assets=10, name=None, cm=None):
    headers = cm or make_contractor_manager_headers(account_id)
    payload = create_jobsite_payload(capacity_assets=capacity_assets,
                                     **({} if name is None else {"name": name}))
    return get_success_data(api_client.create_jobsite(account_id, payload, headers))


def deploy_asset(asset_id, jobsite_id, js_headers):
    return get_success_data(api_client.deploy_asset(asset_id, jobsite_id, js_headers))


def setup_deployed_asset(clock=None, jobsite_capacity=10, **kwargs):
    """setup_agreement_with_assets + jobsite + first asset DEPLOYED."""
    env = setup_agreement_with_assets(clock=clock, **kwargs)
    site = create_jobsite(env["account_id"], capacity_assets=jobsite_capacity,
                          cm=env["cm"])
    asset = deploy_asset(env["asset_ids"][0], site["id"], env["js"])
    env["jobsite"] = site
    env["asset"] = asset
    return env


def open_ticket(asset_id, loaner_requested, js_headers):
    return get_success_data(api_client.create_repair_ticket(
        asset_id, loaner_requested, js_headers))


def drive_ticket_to_in_shop(ticket_id):
    """Advance a ticket to IN_SHOP.

    OPENED requires schedule-pickup then receive; a REOPENED leg is received
    directly (PRD endpoint table: "Receive a PICKUP_SCHEDULED or REOPENED unit
    into IN_SHOP").
    """
    ticket = get_success_data(api_client.get_repair_ticket(ticket_id, ADMIN))
    if ticket["status"] == "OPENED":
        get_success_data(api_client.schedule_pickup(ticket_id, COORD))
    return get_success_data(api_client.receive_ticket(ticket_id, COORD))


def drive_ticket_to_quality_check(ticket_id):
    drive_ticket_to_in_shop(ticket_id)
    return get_success_data(api_client.complete_repair(ticket_id, COORD))


def drive_ticket_to_closed(ticket_id):
    drive_ticket_to_quality_check(ticket_id)
    return get_success_data(api_client.close_ticket(ticket_id, COORD))


def report_claim(asset_id, js_headers):
    return get_success_data(api_client.create_theft_claim(asset_id, js_headers))


def verify_claim(claim_id, police_report_number, police_report_filed_at,
                 verifier_user_id):
    admin = make_fleet_admin_headers(verifier_user_id)
    return get_success_data(api_client.verify_police_report(
        claim_id,
        {"police_report_number": police_report_number,
         "police_report_filed_at": police_report_filed_at}, admin))


def approve_claim(claim_id, adjuster_user_id):
    adj = make_claims_adjuster_headers(adjuster_user_id)
    return get_success_data(api_client.decide_theft_claim(claim_id, "APPROVE", adj))


def setup_police_verified_claim(clock="2026-09-01T00:00:00Z", verifier="admin-ver-1",
                                filed_at="2026-09-01T12:00:00Z", **kwargs):
    """Deployed asset + REPORTED -> POLICE_VERIFIED claim."""
    env = setup_deployed_asset(clock=clock, **kwargs)
    claim = report_claim(env["asset"]["id"], env["js"])
    verify_claim(claim["id"], "PR-1", filed_at, verifier)
    env["claim"] = claim
    env["verifier"] = verifier
    return env


def get_agreement(agreement_id):
    return get_success_data(api_client.get_agreement(agreement_id, ADMIN))


def get_account(account_id):
    return get_success_data(api_client.get_account(account_id, ADMIN))


def get_jobsite(jobsite_id):
    return get_success_data(api_client.get_jobsite(jobsite_id, ADMIN))


def get_asset(asset_id):
    return get_success_data(api_client.get_asset(asset_id, ADMIN))


def get_settlement_rows(agreement_id):
    from prd_bench_local_runner.testing import validate_paginated
    data, _meta = validate_paginated(api_client.get_settlement(agreement_id, ADMIN))
    return data


def get_ticket(ticket_id):
    return get_success_data(api_client.get_repair_ticket(ticket_id, ADMIN))


def get_loaner(loaner_id):
    return get_success_data(api_client.get_loaner_unit(loaner_id, ADMIN))


def create_loaner(tool_model_id, serial_number=None):
    payload = create_loaner_unit_payload(
        tool_model_id, **({} if serial_number is None else {"serial_number": serial_number}))
    return get_success_data(api_client.create_loaner_unit(payload, ADMIN))


def create_consumable_product(**overrides):
    return get_success_data(api_client.create_consumable_product(
        create_consumable_product_payload(**overrides), ADMIN))
