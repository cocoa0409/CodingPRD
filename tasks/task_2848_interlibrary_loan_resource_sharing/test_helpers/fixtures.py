"""Pytest fixtures and composite setup chains.

The harness restarts the API server before every individual test, so each test
begins against an empty database and every precondition below is built from
scratch through the documented endpoints.
"""

from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories as F
from .api_client import IllApiClient
from .test_users import (
    make_accountant_headers,
    make_acquisitions_headers,
    make_admin_headers,
    make_ill_staff_headers,
    make_partner_agent_headers,
    make_patron_headers,
)
from .types import MaterialType, ShipmentCondition


# --- Pytest fixtures ---------------------------------------------------------
@pytest.fixture
def client() -> IllApiClient:
    return IllApiClient()


@pytest.fixture
def admin_headers() -> Dict[str, str]:
    return make_admin_headers()


@pytest.fixture
def staff_headers() -> Dict[str, str]:
    return make_ill_staff_headers()


@pytest.fixture
def acq_headers() -> Dict[str, str]:
    return make_acquisitions_headers()


@pytest.fixture
def accountant_headers() -> Dict[str, str]:
    return make_accountant_headers()


# --- Clock -------------------------------------------------------------------
def set_clock(client: IllApiClient, to_iso8601: str) -> str:
    """Move the logical clock forward and return the new `current_utc`."""
    data = get_success_data(
        client.set_clock(to_iso8601, headers=make_admin_headers())
    )
    return data["current_utc"]


# --- Patrons -----------------------------------------------------------------
def create_patron(client: IllApiClient, **kwargs: Any) -> Dict[str, Any]:
    payload = F.patron_payload(**kwargs)
    return get_success_data(client.create_patron(payload, headers=make_admin_headers()))


def update_patron(
    client: IllApiClient, patron_id: str, **kwargs: Any
) -> Dict[str, Any]:
    payload = F.patron_update_payload(**kwargs)
    return get_success_data(
        client.update_patron(patron_id, payload, headers=make_admin_headers())
    )


def load_infraction(
    client: IllApiClient, patron_id: str, kind: str, **kwargs: Any
) -> Dict[str, Any]:
    """Load one migrated infraction row; the response is the updated patron."""
    payload = F.infraction_payload(kind, **kwargs)
    return get_success_data(
        client.create_infraction_record(patron_id, payload, headers=make_admin_headers())
    )


def read_patron(client: IllApiClient, patron_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.get_patron(patron_id, headers=make_ill_staff_headers())
    )


# --- Partners ----------------------------------------------------------------
def create_partner(client: IllApiClient, **kwargs: Any) -> Dict[str, Any]:
    payload = F.partner_payload(**kwargs)
    return get_success_data(client.create_partner(payload, headers=make_admin_headers()))


def update_partner(
    client: IllApiClient, partner_id: str, **kwargs: Any
) -> Dict[str, Any]:
    payload = F.partner_update_payload(**kwargs)
    return get_success_data(
        client.update_partner(partner_id, payload, headers=make_admin_headers())
    )


def read_partner(client: IllApiClient, partner_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.get_partner(partner_id, headers=make_ill_staff_headers())
    )


def partner_version(client: IllApiClient, partner_id: str) -> int:
    return read_partner(client, partner_id)["version"]


# --- Reciprocity agreements --------------------------------------------------
def create_agreement(
    client: IllApiClient,
    partner_id: str,
    expected_partner_version: Optional[int] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Create an agreement, declaring the partner version currently on record."""
    if expected_partner_version is None:
        expected_partner_version = partner_version(client, partner_id)
    payload = F.agreement_payload(
        partner_id=partner_id,
        expected_partner_version=expected_partner_version,
        **kwargs,
    )
    return get_success_data(
        client.create_agreement(payload, headers=make_admin_headers())
    )


# --- Rotas -------------------------------------------------------------------
def create_rota(client: IllApiClient, **kwargs: Any) -> Dict[str, Any]:
    payload = F.rota_payload(**kwargs)
    return get_success_data(client.create_rota(payload, headers=make_admin_headers()))


def read_rota(client: IllApiClient, rota_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_rota(rota_id, headers=make_ill_staff_headers()))


def rota_version(client: IllApiClient, rota_id: str) -> int:
    return read_rota(client, rota_id)["version"]


def add_rota_entry(
    client: IllApiClient,
    rota_id: str,
    partner_id: str,
    expected_rota_version: Optional[int] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Add or re-quote a partner on a rota, refreshing the declared rota version."""
    if expected_rota_version is None:
        expected_rota_version = rota_version(client, rota_id)
    payload = F.rota_entry_payload(
        rota_id=rota_id,
        partner_id=partner_id,
        expected_rota_version=expected_rota_version,
        **kwargs,
    )
    return get_success_data(
        client.create_rota_entry(payload, headers=make_admin_headers())
    )


# --- Bibliographic records ---------------------------------------------------
def create_bib_item(client: IllApiClient, **kwargs: Any) -> Dict[str, Any]:
    payload = F.bib_item_payload(**kwargs)
    return get_success_data(client.create_bib_item(payload, headers=make_admin_headers()))


def create_article_bib_item(client: IllApiClient, **kwargs: Any) -> Dict[str, Any]:
    payload = F.article_bib_item_payload(**kwargs)
    return get_success_data(client.create_bib_item(payload, headers=make_admin_headers()))


def update_bib_item(
    client: IllApiClient, bib_item_id: str, **kwargs: Any
) -> Dict[str, Any]:
    payload = F.bib_item_update_payload(**kwargs)
    return get_success_data(
        client.update_bib_item(bib_item_id, payload, headers=make_admin_headers())
    )


# --- Requests ----------------------------------------------------------------
def intake_request(
    client: IllApiClient,
    patron_id: str,
    bib_item_id: str,
    rota_id: str,
    headers: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    payload = F.request_payload(patron_id, bib_item_id, rota_id, **kwargs)
    return get_success_data(
        client.create_request(payload, headers=headers or make_ill_staff_headers())
    )


def intake_copy_request(
    client: IllApiClient,
    patron_id: str,
    bib_item_id: str,
    rota_id: str,
    headers: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    payload = F.copy_request_payload(patron_id, bib_item_id, rota_id, **kwargs)
    return get_success_data(
        client.create_request(payload, headers=headers or make_ill_staff_headers())
    )


def read_request(client: IllApiClient, request_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.get_request(request_id, headers=make_ill_staff_headers())
    )


def run_rota_round(
    client: IllApiClient,
    request_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Run one rota round; the response is the new supply offer."""
    return get_success_data(
        client.source_request(request_id, headers=headers or make_ill_staff_headers())
    )


def accept_offer(
    client: IllApiClient,
    offer_id: str,
    partner_id: str,
) -> Dict[str, Any]:
    """The selected lender accepts, acting as the `Partner` row it owns."""
    return get_success_data(
        client.accept_offer(offer_id, headers=make_partner_agent_headers(partner_id))
    )


def decline_offer(
    client: IllApiClient,
    offer_id: str,
    partner_id: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    payload = F.decline_payload(**kwargs)
    return get_success_data(
        client.decline_offer(
            offer_id, payload, headers=make_partner_agent_headers(partner_id)
        )
    )


def ship_item(
    client: IllApiClient,
    offer_id: str,
    partner_id: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    payload = F.shipment_payload(**kwargs)
    return get_success_data(
        client.create_shipment(
            offer_id, payload, headers=make_partner_agent_headers(partner_id)
        )
    )


def receive_shipment(client: IllApiClient, shipment_id: str) -> Dict[str, Any]:
    """Receive the inbound parcel; the response is the newly created loan."""
    return get_success_data(
        client.receive_shipment(shipment_id, headers=make_ill_staff_headers())
    )


def pickup_loan(client: IllApiClient, loan_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.pickup_loan(loan_id, headers=make_ill_staff_headers())
    )


def read_loan(client: IllApiClient, loan_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_loan(loan_id, headers=make_ill_staff_headers()))


def return_loan(client: IllApiClient, loan_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.return_loan(loan_id, headers=make_ill_staff_headers())
    )


def recall_loan(
    client: IllApiClient, loan_id: str, partner_id: str, **kwargs: Any
) -> Dict[str, Any]:
    payload = F.recall_payload(**kwargs)
    return get_success_data(
        client.recall_loan(
            loan_id, payload, headers=make_partner_agent_headers(partner_id)
        )
    )


def declare_lost(client: IllApiClient, loan_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.declare_loan_lost(loan_id, headers=make_ill_staff_headers())
    )


def lender_confirm(
    client: IllApiClient,
    shipment_id: str,
    partner_id: str,
    condition: str = ShipmentCondition.OK,
    **kwargs: Any,
) -> Dict[str, Any]:
    payload = F.lender_confirm_payload(condition=condition, **kwargs)
    return get_success_data(
        client.lender_confirm_shipment(
            shipment_id, payload, headers=make_partner_agent_headers(partner_id)
        )
    )


def list_request_shipments(
    client: IllApiClient, request_id: str, params: Optional[Dict] = None
) -> List[Dict[str, Any]]:
    return get_success_data(
        client.list_request_shipments(
            request_id, headers=make_ill_staff_headers(), params=params
        )
    )


def list_request_loans(
    client: IllApiClient, request_id: str, params: Optional[Dict] = None
) -> List[Dict[str, Any]]:
    return get_success_data(
        client.list_request_loans(
            request_id, headers=make_ill_staff_headers(), params=params
        )
    )


def list_clearances(
    client: IllApiClient, request_id: str, params: Optional[Dict] = None
) -> List[Dict[str, Any]]:
    return get_success_data(
        client.list_copyright_clearances(
            request_id, headers=make_ill_staff_headers(), params=params
        )
    )


def list_notifications(
    client: IllApiClient, request_id: str, params: Optional[Dict] = None
) -> List[Dict[str, Any]]:
    return get_success_data(
        client.list_notifications(
            request_id, headers=make_ill_staff_headers(), params=params
        )
    )


def list_pod_orders(
    client: IllApiClient, request_id: str, params: Optional[Dict] = None
) -> List[Dict[str, Any]]:
    return get_success_data(
        client.list_pod_orders(
            request_id, headers=make_ill_staff_headers(), params=params
        )
    )


# --- Electronic delivery -----------------------------------------------------
def deliver_electronically(
    client: IllApiClient,
    request_id: str,
    partner_id: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    payload = F.electronic_delivery_payload(**kwargs)
    return get_success_data(
        client.create_electronic_delivery(
            request_id, payload, headers=make_partner_agent_headers(partner_id)
        )
    )


def download_delivery(
    client: IllApiClient, delivery_id: str, patron_id: str
) -> Dict[str, Any]:
    return get_success_data(
        client.create_download(delivery_id, headers=make_patron_headers(patron_id))
    )


# --- Purchase on demand ------------------------------------------------------
def escalate_request(
    client: IllApiClient,
    request_id: str,
    headers: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    payload = F.escalate_payload(**kwargs)
    return get_success_data(
        client.escalate_request(
            request_id, payload, headers=headers or make_ill_staff_headers()
        )
    )


def decide_pod_order(
    client: IllApiClient,
    order_id: str,
    headers: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    payload = F.pod_decision_payload(**kwargs)
    return get_success_data(
        client.decide_pod_order(
            order_id, payload, headers=headers or make_acquisitions_headers()
        )
    )


def receive_pod_order(client: IllApiClient, order_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.receive_pod_order(order_id, headers=make_acquisitions_headers())
    )


# --- Settlement --------------------------------------------------------------
def create_lending_charge(
    client: IllApiClient, partner_id: str, **kwargs: Any
) -> Dict[str, Any]:
    payload = F.lending_charge_payload(partner_id, **kwargs)
    return get_success_data(
        client.create_lending_charge(payload, headers=make_accountant_headers())
    )


def draft_invoice(
    client: IllApiClient,
    partner_id: str,
    period_month: str,
    expected_partner_version: Optional[int] = None,
) -> Dict[str, Any]:
    if expected_partner_version is None:
        expected_partner_version = partner_version(client, partner_id)
    payload = F.invoice_payload(period_month, expected_partner_version)
    return get_success_data(
        client.create_invoice(partner_id, payload, headers=make_accountant_headers())
    )


def issue_invoice(client: IllApiClient, invoice_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.issue_invoice(invoice_id, headers=make_accountant_headers())
    )


def settle_loan_charge(
    client: IllApiClient, loan_id: str, payload: Dict[str, Any]
) -> Dict[str, Any]:
    return get_success_data(
        client.create_charge_settlement(
            loan_id, payload, headers=make_accountant_headers()
        )
    )


def run_ops(client: IllApiClient) -> Dict[str, Any]:
    """Run the operational sweep; the response is its counter summary."""
    return get_success_data(client.create_ops_run(headers=make_ill_staff_headers()))


# --- Composite chains --------------------------------------------------------
def build_loan_world(
    client: IllApiClient,
    partner_kwargs: Optional[Dict[str, Any]] = None,
    rota_kwargs: Optional[Dict[str, Any]] = None,
    entry_kwargs: Optional[Dict[str, Any]] = None,
    bib_kwargs: Optional[Dict[str, Any]] = None,
    patron_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """One patron, one partner, a `LOAN` rota with a single entry, and one work."""
    patron = create_patron(client, **(patron_kwargs or {}))
    partner = create_partner(client, **(partner_kwargs or {}))
    rota = create_rota(
        client, **{"material_type": MaterialType.LOAN, **(rota_kwargs or {})}
    )
    entry = add_rota_entry(client, rota["id"], partner["id"], **(entry_kwargs or {}))
    bib_item = create_bib_item(client, **(bib_kwargs or {}))
    return {
        "patron": patron,
        "partner": partner,
        "rota": rota,
        "entry": entry,
        "bib_item": bib_item,
    }


def build_copy_world(
    client: IllApiClient,
    partner_kwargs: Optional[Dict[str, Any]] = None,
    rota_kwargs: Optional[Dict[str, Any]] = None,
    entry_kwargs: Optional[Dict[str, Any]] = None,
    bib_kwargs: Optional[Dict[str, Any]] = None,
    patron_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """The same shape as `build_loan_world` but for a `COPY` rota and an article."""
    patron = create_patron(client, **(patron_kwargs or {}))
    partner = create_partner(client, **(partner_kwargs or {}))
    rota = create_rota(
        client, **{"material_type": MaterialType.COPY, **(rota_kwargs or {})}
    )
    entry = add_rota_entry(client, rota["id"], partner["id"], **(entry_kwargs or {}))
    bib_item = create_article_bib_item(client, **(bib_kwargs or {}))
    return {
        "patron": patron,
        "partner": partner,
        "rota": rota,
        "entry": entry,
        "bib_item": bib_item,
    }


def commit_request(
    client: IllApiClient,
    world: Dict[str, Any],
    request_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Take a `LOAN` request in, run one rota round and have the lender accept."""
    request = intake_request(
        client,
        world["patron"]["id"],
        world["bib_item"]["id"],
        world["rota"]["id"],
        **(request_kwargs or {}),
    )
    offer = run_rota_round(client, request["id"])
    accepted = accept_offer(client, offer["id"], world["partner"]["id"])
    return {"request": request, "offer": offer, "accepted_offer": accepted}


def commit_copy_request(
    client: IllApiClient,
    world: Dict[str, Any],
    request_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """The `COPY` equivalent of `commit_request`."""
    request = intake_copy_request(
        client,
        world["patron"]["id"],
        world["bib_item"]["id"],
        world["rota"]["id"],
        **(request_kwargs or {}),
    )
    offer = run_rota_round(client, request["id"])
    accepted = accept_offer(client, offer["id"], world["partner"]["id"])
    return {"request": request, "offer": offer, "accepted_offer": accepted}


def build_loan_on_shelf(
    client: IllApiClient,
    world: Optional[Dict[str, Any]] = None,
    request_kwargs: Optional[Dict[str, Any]] = None,
    shipment_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Carry a `LOAN` request all the way to a loan awaiting pickup."""
    world = world or build_loan_world(client)
    committed = commit_request(client, world, request_kwargs)
    shipment = ship_item(
        client,
        committed["offer"]["id"],
        world["partner"]["id"],
        **(shipment_kwargs or {}),
    )
    loan = receive_shipment(client, shipment["id"])
    return {**world, **committed, "shipment": shipment, "loan": loan}


def build_loan_with_patron(
    client: IllApiClient,
    world: Optional[Dict[str, Any]] = None,
    request_kwargs: Optional[Dict[str, Any]] = None,
    shipment_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Carry a `LOAN` request to a loan in the patron's hands."""
    built = build_loan_on_shelf(client, world, request_kwargs, shipment_kwargs)
    loan = pickup_loan(client, built["loan"]["id"])
    return {**built, "loan": loan}


def build_delivered_copy(
    client: IllApiClient,
    world: Optional[Dict[str, Any]] = None,
    request_kwargs: Optional[Dict[str, Any]] = None,
    delivery_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Carry a `COPY` request to a live electronic delivery window."""
    world = world or build_copy_world(client)
    committed = commit_copy_request(client, world, request_kwargs)
    delivery = deliver_electronically(
        client,
        committed["request"]["id"],
        world["partner"]["id"],
        **(delivery_kwargs or {}),
    )
    return {**world, **committed, "delivery": delivery}


def return_and_confirm(
    client: IllApiClient,
    built: Dict[str, Any],
    condition: str = ShipmentCondition.OK,
    **confirm_kwargs: Any,
) -> Dict[str, Any]:
    """Return the item, find the `RETURN` parcel and have the lender confirm it."""
    returned_loan = return_loan(client, built["loan"]["id"])
    parcels = list_request_shipments(
        client, built["request"]["id"], params={"direction": "RETURN"}
    )
    return_parcel = parcels[0]
    confirmed = lender_confirm(
        client,
        return_parcel["id"],
        built["partner"]["id"],
        condition=condition,
        **confirm_kwargs,
    )
    return {
        "returned_loan": returned_loan,
        "return_parcel": return_parcel,
        "confirmed_parcel": confirmed,
    }
