"""Composite setup helpers.

Every test starts against an empty database, so each helper builds its own
preconditions using nothing but the endpoints the PRD declares. Setup steps go
through the lenient success validator so a broken precondition surfaces as a
setup failure rather than as a confusing assertion.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .test_users import TEST_USERS, make_customer_contact_headers

ADMIN = TEST_USERS["platform_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
COORDINATOR = TEST_USERS["permit_coordinator_headers"]
PLANNER = TEST_USERS["dispatch_planner_headers"]
DRIVER = TEST_USERS["driver_operator_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
SECOND_OFFICER = TEST_USERS["second_compliance_officer_headers"]


# ─── Logical clock ────────────────────────────────────────────────────────

def reposition_clock(to_iso8601: str, headers: Dict[str, str] = None) -> dict:
    """Reposition the logical clock and return the sweep report."""
    return get_success_data(
        api_client.set_clock(to_iso8601, headers or ADMIN)
    )


# ─── Reference data ───────────────────────────────────────────────────────

def open_account(legal_name: str = "Test Rentals LLC", **overrides) -> dict:
    return get_success_data(
        api_client.create_rental_account(
            f.rental_account_payload(legal_name=legal_name, **overrides), ADMIN
        ),
        201,
    )


def register_site(account_id: str, site_label: str = "Test Placement Site", **overrides):
    return get_success_data(
        api_client.create_service_site(
            f.service_site_payload(account_id, site_label=site_label, **overrides),
            SALES,
        ),
        201,
    )


def file_permit(site_id: str, authority_ref: str = "PL-0001", **overrides) -> dict:
    return get_success_data(
        api_client.create_placement_permit(
            f.placement_permit_payload(site_id, authority_ref=authority_ref, **overrides),
            COORDINATOR,
        ),
        201,
    )


def submit_permit(permit_id: str, submission_note: Optional[str] = None) -> dict:
    payload = {} if submission_note is None else {"submission_note": submission_note}
    return get_success_data(
        api_client.submit_placement_permit(permit_id, COORDINATOR, payload)
    )


def approve_permit(
    permit_id: str, authority_decision_ref: str = "AD-0001",
    headers: Dict[str, str] = None,
) -> dict:
    return get_success_data(
        api_client.approve_placement_permit(
            permit_id, f.permit_approval_payload(authority_decision_ref),
            headers or OFFICER,
        )
    )


def reject_permit(
    permit_id: str,
    authority_decision_ref: str = "AD-0001",
    rejection_reason: str = "insufficient traffic control plan",
) -> dict:
    return get_success_data(
        api_client.reject_placement_permit(
            permit_id,
            f.permit_rejection_payload(authority_decision_ref, rejection_reason),
            OFFICER,
        )
    )


def approve_permit_for_site(
    site_id: str,
    authority_ref: str = "PL-0001",
    authority_decision_ref: str = "AD-0001",
    permit_kind: str = "PLACEMENT",
    **permit_overrides,
) -> dict:
    """File, submit and approve one permit filing of a kind on the site."""
    permit = file_permit(
        site_id, authority_ref=authority_ref, permit_kind=permit_kind,
        **permit_overrides,
    )
    submit_permit(permit["id"])
    return approve_permit(permit["id"], authority_decision_ref)


def add_asset_unit(asset_tag: str = "SP-0001", **overrides) -> dict:
    return get_success_data(
        api_client.create_asset_unit(
            f.asset_unit_payload(asset_tag=asset_tag, **overrides), ADMIN
        ),
        201,
    )


def register_disposal_site(site_code: str = "DS-0001", **overrides) -> dict:
    return get_success_data(
        api_client.create_disposal_site(
            f.disposal_site_payload(site_code=site_code, **overrides), ADMIN
        ),
        201,
    )


def create_route(route_code: str = "RT-MON-1", **overrides) -> dict:
    return get_success_data(
        api_client.create_route(
            f.route_payload(route_code=route_code, **overrides), PLANNER
        ),
        201,
    )


# ─── Contracts ────────────────────────────────────────────────────────────

def raise_contract(
    account_id: str, site_id: str, headers: Dict[str, str] = None, **overrides
) -> dict:
    return get_success_data(
        api_client.create_rental_contract(
            f.rental_contract_payload(account_id, site_id, **overrides),
            headers or SALES,
        ),
        201,
    )


def raise_thirteen_unit_contract(account_id: str, site_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_rental_contract(
            f.thirteen_unit_contract_payload(account_id, site_id, **overrides), SALES
        ),
        201,
    )


def raise_event_contract(account_id: str, site_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_rental_contract(
            f.event_contract_payload(account_id, site_id, **overrides), SALES
        ),
        201,
    )


def run_quote(
    contract_id: str, expected_contract_version: int, quote_note: Any = f.OMIT
) -> dict:
    return get_success_data(
        api_client.quote_rental_contract(
            contract_id, f.quote_payload(expected_contract_version, quote_note), SALES
        )
    )


def quote_contract(contract: dict, quote_note: Any = f.OMIT) -> dict:
    """Quote a freshly raised contract using its current version."""
    return run_quote(contract["id"], contract["version"], quote_note)


def mobilize_contract(contract_id: str) -> dict:
    return get_success_data(api_client.activate_rental_contract(contract_id, SALES))


def demobilize_contract(contract_id: str, demobilization_note: Any = f.OMIT) -> dict:
    return get_success_data(
        api_client.demobilize_rental_contract(
            contract_id, PLANNER, f.demobilization_payload(demobilization_note)
        )
    )


def invoice_contract(contract_id: str) -> dict:
    return get_success_data(api_client.invoice_rental_contract(contract_id, SALES))


def settle_contract(contract_id: str, payment_reference: Any = f.OMIT) -> dict:
    return get_success_data(
        api_client.settle_rental_contract_invoice(
            contract_id, ADMIN, f.settlement_payload(payment_reference)
        )
    )


# ─── Field commitments, routing and execution ─────────────────────────────

def commit_deployment(
    contract_id: str, asset_unit_id: str,
    deploy_from: str = "2026-08-03", deploy_to: str = "2026-09-30",
) -> dict:
    return get_success_data(
        api_client.create_unit_deployment(
            f.unit_deployment_payload(
                contract_id, asset_unit_id,
                deploy_from=deploy_from, deploy_to=deploy_to,
            ),
            PLANNER,
        ),
        201,
    )


def relocate_deployment(
    deployment_id: str,
    destination_site_id: str,
    effective_date: str,
    relocation_reason: Any = f.OMIT,
    headers: Dict[str, str] = None,
) -> dict:
    return get_success_data(
        api_client.relocate_unit_deployment(
            deployment_id,
            f.relocation_payload(destination_site_id, effective_date, relocation_reason),
            headers or PLANNER,
        )
    )


def attach_schedule(
    contract_id: str, route_id: str, service_day: str = "MON",
    window_start_minute: int = 480, window_end_minute: int = 600,
) -> dict:
    return get_success_data(
        api_client.create_service_schedule(
            f.service_schedule_payload(
                contract_id, route_id, service_day=service_day,
                window_start_minute=window_start_minute,
                window_end_minute=window_end_minute,
            ),
            PLANNER,
        ),
        201,
    )


def suspend_schedule(schedule_id: str, suspension_reason: Any = f.OMIT) -> dict:
    return get_success_data(
        api_client.suspend_service_schedule(
            schedule_id, PLANNER, f.schedule_suspension_payload(suspension_reason)
        )
    )


def plan_visit(
    schedule_id: str,
    scheduled_date: str = "2026-08-10",
    window_start_minute: int = 480,
    window_end_minute: int = 540,
    visit_kind: str = "SERVICE",
) -> dict:
    return get_success_data(
        api_client.create_service_visit(
            f.service_visit_payload(
                schedule_id, visit_kind=visit_kind, scheduled_date=scheduled_date,
                window_start_minute=window_start_minute,
                window_end_minute=window_end_minute,
            ),
            PLANNER,
        ),
        201,
    )


def dispatch_visit(visit_id: str) -> dict:
    return get_success_data(api_client.dispatch_service_visit(visit_id, DRIVER))


def complete_visit(visit_id: str, gallons_pumped: int) -> dict:
    return get_success_data(
        api_client.complete_service_visit(
            visit_id, f.visit_completion_payload(gallons_pumped), DRIVER
        )
    )


def service_visit_fully(visit_id: str, gallons_pumped: int) -> dict:
    """Dispatch then complete one visit."""
    dispatch_visit(visit_id)
    return complete_visit(visit_id, gallons_pumped)


def mark_visit_missed(
    visit_id: str, missed_reason: str = "truck breakdown",
    headers: Dict[str, str] = None,
) -> dict:
    return get_success_data(
        api_client.mark_service_visit_missed(
            visit_id, f.missed_visit_payload(missed_reason), headers or PLANNER
        )
    )


def book_rerun(
    visit_id: str, rerun_date: str,
    window_start_minute: int = 480, window_end_minute: int = 540,
) -> dict:
    return get_success_data(
        api_client.schedule_service_visit_rerun(
            visit_id,
            f.rerun_payload(rerun_date, window_start_minute, window_end_minute),
            PLANNER,
        ),
        201,
    )


def open_manifest(
    route_id: str, disposal_site_id: str,
    manifest_date: str = "2026-08-10", waste_class: str = "BLACKWATER",
) -> dict:
    return get_success_data(
        api_client.create_waste_manifest(
            f.waste_manifest_payload(
                route_id, disposal_site_id,
                manifest_date=manifest_date, waste_class=waste_class,
            ),
            DRIVER,
        ),
        201,
    )


def seal_manifest(
    manifest_id: str, expected_route_version: int, seal_note: Any = f.OMIT
) -> dict:
    return get_success_data(
        api_client.seal_waste_manifest(
            manifest_id, f.manifest_seal_payload(expected_route_version, seal_note),
            DRIVER,
        )
    )


def accept_manifest(manifest_id: str, acceptance_note: Any = f.OMIT) -> dict:
    return get_success_data(
        api_client.accept_waste_manifest(
            manifest_id, OFFICER, f.manifest_acceptance_payload(acceptance_note)
        )
    )


# ─── Charges ──────────────────────────────────────────────────────────────

def assess_damage_charge(
    contract_id: str, asset_unit_id: str, severity: str = "MODERATE",
    headers: Dict[str, str] = None,
) -> dict:
    return get_success_data(
        api_client.create_charge_event(
            f.damage_charge_payload(contract_id, asset_unit_id, severity),
            headers or OFFICER,
        ),
        201,
    )


def assess_tip_over_charge(
    contract_id: str, asset_unit_id: str, headers: Dict[str, str] = None
) -> dict:
    return get_success_data(
        api_client.create_charge_event(
            f.tip_over_charge_payload(contract_id, asset_unit_id), headers or OFFICER
        ),
        201,
    )


def dispute_charge(
    charge_id: str, account_id: str,
    dispute_reason: str = "the unit was already damaged on delivery",
) -> dict:
    return get_success_data(
        api_client.dispute_charge_event(
            charge_id, f.dispute_payload(dispute_reason),
            make_customer_contact_headers(account_id),
        )
    )


def uphold_charge(
    charge_id: str, headers: Dict[str, str] = None, resolution_note: Any = f.OMIT
) -> dict:
    return get_success_data(
        api_client.uphold_charge_event(
            charge_id, headers or SECOND_OFFICER, f.resolution_payload(resolution_note)
        )
    )


def waive_charge(
    charge_id: str, headers: Dict[str, str] = None, resolution_note: Any = f.OMIT
) -> dict:
    return get_success_data(
        api_client.waive_charge_event(
            charge_id, headers or SECOND_OFFICER, f.resolution_payload(resolution_note)
        )
    )


# ─── Reads ────────────────────────────────────────────────────────────────

def read_account(account_id: str, headers: Dict[str, str] = None) -> dict:
    return get_success_data(
        api_client.get_rental_account(account_id, headers or ADMIN)
    )


def read_site(site_id: str, headers: Dict[str, str] = None) -> dict:
    return get_success_data(api_client.get_service_site(site_id, headers or SALES))


def read_permit(permit_id: str, headers: Dict[str, str] = None) -> dict:
    return get_success_data(
        api_client.get_placement_permit(permit_id, headers or COORDINATOR)
    )


def read_asset_unit(asset_unit_id: str, headers: Dict[str, str] = None) -> dict:
    return get_success_data(
        api_client.get_asset_unit(asset_unit_id, headers or PLANNER)
    )


def read_disposal_site(disposal_site_id: str, headers: Dict[str, str] = None) -> dict:
    return get_success_data(
        api_client.get_disposal_site(disposal_site_id, headers or DRIVER)
    )


def read_route(route_id: str, headers: Dict[str, str] = None) -> dict:
    return get_success_data(api_client.get_route(route_id, headers or PLANNER))


def read_contract(contract_id: str, headers: Dict[str, str] = None) -> dict:
    return get_success_data(
        api_client.get_rental_contract(contract_id, headers or SALES)
    )


def read_deployment(deployment_id: str, headers: Dict[str, str] = None) -> dict:
    return get_success_data(
        api_client.get_unit_deployment(deployment_id, headers or PLANNER)
    )


def read_schedule(schedule_id: str, headers: Dict[str, str] = None) -> dict:
    return get_success_data(
        api_client.get_service_schedule(schedule_id, headers or PLANNER)
    )


def read_visit(visit_id: str, headers: Dict[str, str] = None) -> dict:
    return get_success_data(api_client.get_service_visit(visit_id, headers or PLANNER))


def read_manifest(manifest_id: str, headers: Dict[str, str] = None) -> dict:
    return get_success_data(
        api_client.get_waste_manifest(manifest_id, headers or DRIVER)
    )


def read_charge(charge_id: str, headers: Dict[str, str] = None) -> dict:
    return get_success_data(api_client.get_charge_event(charge_id, headers or OFFICER))


def live_quote_lines(contract_id: str) -> List[dict]:
    """Quote lines of the contract that have not been superseded."""
    return get_success_data(
        api_client.list_quote_lines(contract_id, SALES, {"is_superseded": False})
    )


def superseded_quote_lines(contract_id: str) -> List[dict]:
    return get_success_data(
        api_client.list_quote_lines(contract_id, SALES, {"is_superseded": True})
    )


def all_quote_lines(contract_id: str, **params) -> List[dict]:
    return get_success_data(api_client.list_quote_lines(contract_id, SALES, params or None))


def charges_for_contract(contract_id: str, **params) -> List[dict]:
    query = {"contract_id": contract_id}
    query.update(params)
    return get_success_data(api_client.list_charge_events(OFFICER, query))


def missed_service_credit_for_contract(contract_id: str) -> dict:
    """The single missed-service credit on a contract."""
    credits = charges_for_contract(
        contract_id, charge_kind="MISSED_SERVICE_CREDIT"
    )
    assert len(credits) == 1, (
        f"expected exactly one missed-service credit on the contract, got {len(credits)}"
    )
    return credits[0]


# ─── Composite scenarios ──────────────────────────────────────────────────

SEVEN_UNIT = "seven_unit"
THIRTEEN_UNIT = "thirteen_unit"
EVENT_SHAPE = "event"

FIRST_MONDAY_MORNING = "2026-08-03T08:00:00Z"
SECOND_MONDAY_EARLY = "2026-08-10T06:00:00Z"


def _raise_shaped_contract(shape: str, account_id: str, site_id: str, **overrides):
    if shape == THIRTEEN_UNIT:
        return raise_thirteen_unit_contract(account_id, site_id, **overrides)
    if shape == EVENT_SHAPE:
        return raise_event_contract(account_id, site_id, **overrides)
    return raise_contract(account_id, site_id, **overrides)


def setup_placeable_site(
    legal_name: str = "Test Rentals LLC",
    site_label: str = "Test Placement Site",
    authority_ref: str = "PL-0001",
    authority_decision_ref: str = "AD-0001",
    clock: Optional[str] = FIRST_MONDAY_MORNING,
    account_overrides: Optional[Dict[str, Any]] = None,
    site_overrides: Optional[Dict[str, Any]] = None,
    permit_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Account plus a site whose PLACEMENT filing is approved: posture OPEN.

    Returns ``{"account", "site", "permit"}`` where ``site`` is re-read after
    the approval so its roll-up fields are the post-approval ones.
    """
    if clock:
        reposition_clock(clock)
    account = open_account(legal_name, **(account_overrides or {}))
    site = register_site(account["id"], site_label, **(site_overrides or {}))
    permit = approve_permit_for_site(
        site["id"], authority_ref=authority_ref,
        authority_decision_ref=authority_decision_ref,
        **(permit_overrides or {}),
    )
    return {
        "account": account,
        "site": read_site(site["id"]),
        "permit": permit,
    }


def setup_quoted_contract(
    shape: str = SEVEN_UNIT,
    contract_overrides: Optional[Dict[str, Any]] = None,
    **site_kwargs,
) -> Dict[str, Any]:
    """A placeable site carrying one contract already advanced to QUOTED."""
    env = setup_placeable_site(**site_kwargs)
    contract = _raise_shaped_contract(
        shape, env["account"]["id"], env["site"]["id"], **(contract_overrides or {})
    )
    env["contract_at_draft"] = contract
    env["contract"] = quote_contract(contract)
    return env


def setup_active_contract_with_deployment(
    shape: str = SEVEN_UNIT,
    asset_tag: str = "SP-0001",
    unit_class: str = "STANDARD_PORTABLE",
    yard_code: str = "YD-1",
    tare_length_ft: int = 8,
    deploy_from: str = "2026-08-03",
    deploy_to: str = "2026-09-30",
    contract_overrides: Optional[Dict[str, Any]] = None,
    **site_kwargs,
) -> Dict[str, Any]:
    """A mobilized contract with one unit in the field.

    Returns the quoted-then-activated contract, the asset unit and the
    deployment, each re-read after mobilization.
    """
    env = setup_quoted_contract(
        shape=shape, contract_overrides=contract_overrides, **site_kwargs
    )
    asset = add_asset_unit(
        asset_tag, unit_class=unit_class, yard_code=yard_code,
        tare_length_ft=tare_length_ft,
    )
    deployment = commit_deployment(
        env["contract"]["id"], asset["id"], deploy_from, deploy_to
    )
    env["contract"] = mobilize_contract(env["contract"]["id"])
    env["asset"] = read_asset_unit(asset["id"])
    env["deployment"] = read_deployment(deployment["id"])
    env["site"] = read_site(env["site"]["id"])
    return env


def setup_scheduled_contract(
    shape: str = THIRTEEN_UNIT,
    route_code: str = "RT-MON-1",
    truck_capacity_units: int = 20,
    waste_capacity_gallons: int = 3000,
    route_overrides: Optional[Dict[str, Any]] = None,
    window_start_minute: int = 480,
    window_end_minute: int = 600,
    contract_overrides: Optional[Dict[str, Any]] = None,
    **site_kwargs,
) -> Dict[str, Any]:
    """A quoted contract attached to a Monday route through one schedule."""
    env = setup_quoted_contract(
        shape=shape, contract_overrides=contract_overrides, **site_kwargs
    )
    route = create_route(
        route_code, service_day="MON", truck_capacity_units=truck_capacity_units,
        waste_capacity_gallons=waste_capacity_gallons, **(route_overrides or {}),
    )
    env["schedule"] = attach_schedule(
        env["contract"]["id"], route["id"], "MON",
        window_start_minute, window_end_minute,
    )
    env["route"] = read_route(route["id"])
    return env


def setup_serviced_visit_with_manifest(
    gallons_pumped: int = 380,
    disposal_site_code: str = "DS-0001",
    daily_gallon_cap: int = 5000,
    accepted_waste_classes: Optional[List[str]] = None,
    disposal_status: str = "ACCEPTING",
    waste_class: str = "BLACKWATER",
    manifest_date: str = "2026-08-10",
    shape: str = SEVEN_UNIT,
    route_code: str = "RT-MON-1",
    truck_capacity_units: int = 20,
    **site_kwargs,
) -> Dict[str, Any]:
    """One serviced visit on a Monday route with an OPEN manifest over it.

    The logical clock sits at the visit's own Monday so the facility's
    committed volume is read against that calendar date.
    """
    site_kwargs.setdefault("clock", SECOND_MONDAY_EARLY)
    env = setup_scheduled_contract(
        shape=shape, route_code=route_code,
        truck_capacity_units=truck_capacity_units, **site_kwargs
    )
    env["disposal_site"] = register_disposal_site(
        disposal_site_code,
        daily_gallon_cap=daily_gallon_cap,
        accepted_waste_classes=list(accepted_waste_classes or ["BLACKWATER"]),
        status=disposal_status,
    )
    visit = plan_visit(env["schedule"]["id"], manifest_date, 480, 540)
    env["visit"] = service_visit_fully(visit["id"], gallons_pumped)
    env["manifest"] = open_manifest(
        env["route"]["id"], env["disposal_site"]["id"], manifest_date, waste_class
    )
    env["route"] = read_route(env["route"]["id"])
    env["route_version_before_seal"] = env["route"]["version"]
    return env


def setup_missed_visit_credit(
    invoice_first: bool = False,
    shape: str = THIRTEEN_UNIT,
    truck_capacity_units: int = 20,
    scheduled_date: str = "2026-08-10",
    missed_reason: str = "driver rerouted to a spill response",
    **site_kwargs,
) -> Dict[str, Any]:
    """One planned visit declared missed, with its credit cascade run.

    ``invoice_first`` mobilizes and invoices the contract before the visit is
    missed, so the cascade lands on an already-issued invoice.
    """
    env = setup_scheduled_contract(
        shape=shape, truck_capacity_units=truck_capacity_units, **site_kwargs
    )
    if invoice_first:
        mobilize_contract(env["contract"]["id"])
        env["contract_at_invoice"] = invoice_contract(env["contract"]["id"])
    visit = plan_visit(env["schedule"]["id"], scheduled_date, 480, 540)
    env["visit"] = mark_visit_missed(visit["id"], missed_reason)
    env["credit"] = missed_service_credit_for_contract(env["contract"]["id"])
    env["contract"] = read_contract(env["contract"]["id"])
    env["account"] = read_account(env["account"]["id"])
    env["route"] = read_route(env["route"]["id"])
    return env
