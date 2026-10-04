"""Composite setup helpers.

Every test runs against a freshly restarted server with an empty database, so
each helper builds exactly the state it names through the public API. Setup
calls use the lenient success validator so a broken precondition surfaces as a
clear "Setup failed" message rather than an assertion deep inside a test.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import ApiClient
from .constants import CLOCK_EPOCH, DEFAULT_EXPIRATION_DATE, DEFAULT_LICENSE_EXPIRY
from .factories import (
    create_allocation_decision_payload,
    create_allocation_request_payload,
    create_customs_declaration_payload,
    create_distribution_report_payload,
    create_donor_payload,
    create_emergency_event_payload,
    create_license_payload,
    create_lot_payload,
    create_module_payload,
    create_shipment_payload,
    create_site_payload,
)
from .test_users import (
    ALLOCATION_OFFICER_HEADERS,
    COMPLIANCE_OFFICER_HEADERS,
    DONOR_REPORTING_OFFICER_HEADERS,
    EMERGENCY_MANAGER_HEADERS,
    LOGISTICS_COORDINATOR_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    QA_PHARMACIST_HEADERS,
    make_allocation_officer_headers,
    make_site_coordinator_headers,
)


# ── Logical clock ──────────────────────────────────────────────────────────


def set_clock(api: ApiClient, current_utc: str = CLOCK_EPOCH) -> None:
    resp = api.set_clock({"current_utc": current_utc}, PLATFORM_ADMIN_HEADERS)
    get_success_data(resp)


# ── Donors and lots ────────────────────────────────────────────────────────


def create_donor(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    resp = api.create_donor(create_donor_payload(**overrides), PLATFORM_ADMIN_HEADERS)
    return get_success_data(resp, 201)


def create_lot(api: ApiClient, donor_id: str, **overrides: Any) -> Dict[str, Any]:
    resp = api.create_lot(create_lot_payload(donor_id, **overrides), QA_PHARMACIST_HEADERS)
    return get_success_data(resp, 201)


def create_lot_batch(
    api: ApiClient, donor_id: str, count: int, **overrides: Any
) -> List[Dict[str, Any]]:
    """Intake ``count`` lots with distinct NDC codes (still QUARANTINED)."""
    lots = []
    for i in range(count):
        params = dict(overrides)
        params["ndc_code"] = f"LOT-{i:04d}"
        lots.append(create_lot(api, donor_id, **params))
    return lots


def create_and_release_lot(api: ApiClient, donor_id: str, **overrides: Any) -> Dict[str, Any]:
    lot = create_lot(api, donor_id, **overrides)
    resp = api.release_lot(lot["id"], QA_PHARMACIST_HEADERS)
    return get_success_data(resp)


# ── Sites and licenses ─────────────────────────────────────────────────────


def create_site(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    resp = api.create_site(create_site_payload(**overrides), COMPLIANCE_OFFICER_HEADERS)
    return get_success_data(resp, 201)


def create_license(api: ApiClient, site_id: str, **overrides: Any) -> Dict[str, Any]:
    resp = api.create_license(
        create_license_payload(site_id, **overrides), COMPLIANCE_OFFICER_HEADERS
    )
    return get_success_data(resp, 201)


def create_verified_license(
    api: ApiClient,
    site_id: str,
    license_type: str = "PHARMACY",
    expires_on: str = DEFAULT_LICENSE_EXPIRY,
    **overrides: Any,
) -> Dict[str, Any]:
    lic = create_license(
        api, site_id, license_type=license_type, expires_on=expires_on, **overrides
    )
    resp = api.verify_license(lic["id"], COMPLIANCE_OFFICER_HEADERS)
    return get_success_data(resp)


def setup_qualified_site(
    api: ApiClient,
    license_type: Optional[str] = None,
    **site_overrides: Any,
) -> Dict[str, Any]:
    """Create a site, verify a license, and qualify it. Returns the site.

    International sites (country_code != US) get a verified IMPORT license by
    default, since qualification requires one.
    """
    site = create_site(api, **site_overrides)
    if license_type is None:
        license_type = "IMPORT" if site.get("is_international") else "PHARMACY"
    create_verified_license(api, site["id"], license_type=license_type)
    resp = api.qualify_site(site["id"], COMPLIANCE_OFFICER_HEADERS)
    return get_success_data(resp)


def get_site(api: ApiClient, site_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_site(site_id, COMPLIANCE_OFFICER_HEADERS))


def get_lot(api: ApiClient, lot_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_lot(lot_id, QA_PHARMACIST_HEADERS))


def get_request(api: ApiClient, request_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_allocation_request(request_id, ALLOCATION_OFFICER_HEADERS))


def get_decision(api: ApiClient, decision_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_allocation_decision(decision_id, ALLOCATION_OFFICER_HEADERS))


def get_shipment(api: ApiClient, shipment_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_shipment(shipment_id, LOGISTICS_COORDINATOR_HEADERS))


def get_customs_declaration(api: ApiClient, declaration_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_customs_declaration(declaration_id, LOGISTICS_COORDINATOR_HEADERS)
    )


def get_report(api: ApiClient, report_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_distribution_report(report_id, COMPLIANCE_OFFICER_HEADERS))


def get_event(api: ApiClient, event_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_emergency_event(event_id, EMERGENCY_MANAGER_HEADERS))


def get_module(api: ApiClient, module_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_module(module_id, EMERGENCY_MANAGER_HEADERS))


def get_license(api: ApiClient, license_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_license(license_id, COMPLIANCE_OFFICER_HEADERS))


# ── Allocation request / decision pipeline ─────────────────────────────────


def create_request(
    api: ApiClient,
    site_id: str,
    quantity_requested: int = 10,
    ndc_code: str = "N1",
    emergency_event_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Submit an allocation request as the site's own coordinator."""
    payload = create_allocation_request_payload(
        site_id, ndc_code=ndc_code, quantity_requested=quantity_requested
    )
    if emergency_event_id is not None:
        payload["emergency_event_id"] = emergency_event_id
    resp = api.create_allocation_request(payload, make_site_coordinator_headers(site_id))
    return get_success_data(resp, 201)


def begin_review(api: ApiClient, request_id: str) -> Dict[str, Any]:
    return get_success_data(api.begin_review(request_id, ALLOCATION_OFFICER_HEADERS))


def create_draft_decision(
    api: ApiClient,
    request_id: str,
    lines: List[Dict[str, Any]],
    officer_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a DRAFT decision as an AllocationOfficer (same id finalizes it)."""
    headers = (
        make_allocation_officer_headers(officer_user_id)
        if officer_user_id
        else ALLOCATION_OFFICER_HEADERS
    )
    resp = api.create_allocation_decision(
        create_allocation_decision_payload(request_id, lines), headers
    )
    return get_success_data(resp, 201)


def finalize_decision(
    api: ApiClient,
    decision_id: str,
    expected_request_version: int,
    officer_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    headers = (
        make_allocation_officer_headers(officer_user_id)
        if officer_user_id
        else ALLOCATION_OFFICER_HEADERS
    )
    resp = api.finalize_decision(
        decision_id, {"expected_request_version": expected_request_version}, headers
    )
    return get_success_data(resp)


def list_lines_for_decision(api: ApiClient, decision_id: str) -> List[Dict[str, Any]]:
    resp = api.list_allocation_lines(
        ALLOCATION_OFFICER_HEADERS, params={"decision_id": decision_id}
    )
    body = resp.json()
    return body["data"]


def setup_finalized_decision(
    api: ApiClient,
    quantity_requested: int = 10,
    decision_quantities: Optional[List[int]] = None,
    lot_quantity: int = 100,
    lot_overrides: Optional[Dict[str, Any]] = None,
    site_overrides: Optional[Dict[str, Any]] = None,
    request_overrides: Optional[Dict[str, Any]] = None,
    officer_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Full pipeline: donor, released lot, qualified site, request, decision FINALIZED.

    Returns a dict with donor, lot, site, request, decision and the finalized
    decision's RESERVED lines.
    """
    lot_overrides = dict(lot_overrides or {})
    site_overrides = dict(site_overrides or {})
    request_overrides = dict(request_overrides or {})
    if decision_quantities is None:
        decision_quantities = [quantity_requested]

    donor = create_donor(api)
    ndc = lot_overrides.get("ndc_code", "N1")
    lot = create_and_release_lot(api, donor["id"], quantity_received=lot_quantity, **lot_overrides)
    site = setup_qualified_site(api, **site_overrides)
    emergency_event_id = request_overrides.pop("emergency_event_id", None)
    request = create_request(
        api,
        site["id"],
        quantity_requested=quantity_requested,
        ndc_code=ndc,
        emergency_event_id=emergency_event_id,
    )
    begin_review(api, request["id"])
    current = get_request(api, request["id"])
    lines = [{"lot_id": lot["id"], "quantity": q} for q in decision_quantities]
    decision = create_draft_decision(
        api, request["id"], lines, officer_user_id=officer_user_id
    )
    finalize_decision(
        api, decision["id"], current["version"], officer_user_id=officer_user_id
    )
    return {
        "donor": donor,
        "lot": lot,
        "site": site,
        "request": get_request(api, request["id"]),
        "decision": get_decision(api, decision["id"]),
        "lines": list_lines_for_decision(api, decision["id"]),
    }


# ── Shipments and customs ──────────────────────────────────────────────────


def create_shipment_for_decision(
    api: ApiClient, decision_id: str, packed_with_cold_shipper: bool = False
) -> Dict[str, Any]:
    resp = api.create_shipment(
        create_shipment_payload(decision_id, packed_with_cold_shipper=packed_with_cold_shipper),
        LOGISTICS_COORDINATOR_HEADERS,
    )
    return get_success_data(resp, 201)


def setup_shipped_domestic(
    api: ApiClient,
    quantity_requested: int = 10,
    lot_quantity: int = 100,
    packed_with_cold_shipper: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Full domestic pipeline through DISPATCHED: finalized decision, shipment,
    pack-complete, dispatch. Returns the pipeline dict plus shipment."""
    world = setup_finalized_decision(
        api,
        quantity_requested=quantity_requested,
        lot_quantity=lot_quantity,
        **kwargs,
    )
    shipment = create_shipment_for_decision(
        api, world["decision"]["id"], packed_with_cold_shipper=packed_with_cold_shipper
    )
    get_success_data(api.pack_complete(shipment["id"], LOGISTICS_COORDINATOR_HEADERS))
    get_success_data(api.dispatch_shipment(shipment["id"], LOGISTICS_COORDINATOR_HEADERS))
    world["shipment"] = get_shipment(api, shipment["id"])
    return world


def setup_delivered_shipment(
    api: ApiClient,
    quantity_requested: int = 10,
    lot_quantity: int = 100,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Full domestic pipeline through DELIVERED."""
    world = setup_shipped_domestic(
        api, quantity_requested=quantity_requested, lot_quantity=lot_quantity, **kwargs
    )
    site_id = world["site"]["id"]
    get_success_data(
        api.confirm_delivery(world["shipment"]["id"], make_site_coordinator_headers(site_id))
    )
    world["shipment"] = get_shipment(api, world["shipment"]["id"])
    return world


# ── Emergency events and modules ───────────────────────────────────────────


def create_event(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    resp = api.create_emergency_event(
        create_emergency_event_payload(**overrides), EMERGENCY_MANAGER_HEADERS
    )
    return get_success_data(resp, 201)


def create_active_event(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    event = create_event(api, **overrides)
    return get_success_data(api.activate_emergency_event(event["id"], EMERGENCY_MANAGER_HEADERS))


def create_module(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    resp = api.create_module(create_module_payload(**overrides), EMERGENCY_MANAGER_HEADERS)
    return get_success_data(resp, 201)


# ── Distribution reports ───────────────────────────────────────────────────


def create_report(
    api: ApiClient,
    site_id: str,
    shipment_id: str,
    reporting_period: str = "2026-09",
    units_distributed: int = 5,
    patients_reached: int = 5,
    wastage_units: int = 0,
) -> Dict[str, Any]:
    resp = api.create_distribution_report(
        create_distribution_report_payload(
            site_id,
            shipment_id,
            reporting_period=reporting_period,
            units_distributed=units_distributed,
            patients_reached=patients_reached,
            wastage_units=wastage_units,
        ),
        make_site_coordinator_headers(site_id),
    )
    return get_success_data(resp, 201)


def submit_report(api: ApiClient, report_id: str, site_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.submit_distribution_report(report_id, make_site_coordinator_headers(site_id))
    )
