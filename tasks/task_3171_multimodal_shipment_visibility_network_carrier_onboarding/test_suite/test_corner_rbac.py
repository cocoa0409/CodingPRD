"""Corner probes over the role model: entity-backed ownership and the
data-share grant layer."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import ApiErrorId, fixtures
from test_helpers import factories as f
from test_helpers.test_users import (
    CUSTOMER_SERVICE_HEADERS,
    NETWORK_OPS_HEADERS,
    make_carrier_rep_headers,
    make_consignee_rep_headers,
    make_shipper_rep_headers,
)


def test_carrier_rep_cannot_submit_credentials_for_other_carrier(api):
    """The ownership check compares the connection's carrier to the caller.

    PRD: "When `X-User-Role` is `CarrierRep`, `X-User-ID` is the `id` of the
    acting `Carrier`; ownership checks on any resource that references a
    carrier (connections, shipments, appointments) compare the resource's
    carrier foreign-key field to `X-User-ID`."
    PRD: "The acting representative's `X-User-ID` must equal the connection's
    `carrier_id`, and the connection must currently be `DRAFT`; a state
    mismatch is rejected with `ERR_CONNECTION_INVALID_STATE` (HTTP 409)."
    Design: Corner/rbac/carrier_rep_cannot_submit_credentials_for_other_carrier
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier_a = fixtures.create_carrier(api, carrier_name="CarA", scac_code="CAAA")
    carrier_b = fixtures.create_carrier(api, carrier_name="CarB", scac_code="CBBB")
    connection_b = fixtures.create_connection(api, carrier_b, channel="TMS")

    response = api.submit_credentials(
        connection_b["id"],
        f.credentials_payload("vault://stolen"),
        make_carrier_rep_headers(carrier_a["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    assert fixtures.read_connection(api, connection_b["id"])["status"] == "DRAFT"


def test_shipper_rep_cannot_cancel_other_shippers_shipment(api):
    """ShipperRep ownership is checked against the shipment's shipper.

    PRD: "When `X-User-Role` is `ShipperRep`, `X-User-ID` is the `id` of the
    acting `Shipper`; ownership checks on any resource that references a
    shipper (consignees, purchase orders, shipments, data-share grants,
    identity-link decisions) compare the resource's shipper foreign-key field
    to `X-User-ID`."
    PRD: "A request whose role is not authorized for the endpoint — or whose
    entity-backed ownership check fails — is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    Design: Corner/rbac/shipper_rep_cannot_cancel_other_shippers_shipment
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_testing_connection(api, carrier, channel="TMS")
    shipper_a = fixtures.create_shipper(api, company_name="ShipA")
    shipper_b = fixtures.create_shipper(api, company_name="ShipB")
    shipment = fixtures.create_shipment(api, shipper_b, carrier, connection)

    response = api.cancel_shipment(shipment["id"], make_shipper_rep_headers(shipper_a["id"]))
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    assert fixtures.read_shipment(api, shipment["id"])["tracking_status"] == "BOOKED"


def test_consignee_rep_reads_shared_shipment_with_active_grant(api):
    """Grants open reads; the ETA_ONLY scope bars the event stream specifically.

    PRD: "When `X-User-Role` is `ConsigneeRep`, `X-User-ID` is the `id` of the
    acting `Consignee`; the role is read-only, and every read it performs of
    another shipper's shipment data must be covered by an active data-share
    grant naming that consignee as grantee."
    PRD: "An `ETA_ONLY` scope bars the tracking-event list specifically — a
    grantee limited to `ETA_ONLY` may read the shipment (and its ETA fields)
    and its alerts, but not its event stream."
    Design: Corner/rbac/consignee_rep_reads_shared_shipment_with_active_grant
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_testing_connection(api, carrier, channel="TMS")
    shipper = fixtures.create_shipper(api)
    shipper_headers = make_shipper_rep_headers(shipper["id"])
    consignee_full = fixtures.create_consignee(api, shipper, company_name="ConsFull")
    consignee_eta = fixtures.create_consignee(api, shipper, company_name="ConsEta")
    shipment = fixtures.create_shipment(api, shipper, carrier, connection)

    get_success_data(
        api.create_data_share_grant(
            shipper["id"],
            f.data_share_grant_payload("CONSIGNEE", consignee_full["id"], scope="FULL_TRACE"),
            shipper_headers,
        )
    )
    get_success_data(
        api.create_data_share_grant(
            shipper["id"],
            f.data_share_grant_payload("CONSIGNEE", consignee_eta["id"], scope="ETA_ONLY"),
            shipper_headers,
        )
    )

    full_read = validate_success(
        api.get_shipment(shipment["id"], make_consignee_rep_headers(consignee_full["id"]))
    )
    assert full_read["id"] == shipment["id"]

    eta_read = validate_success(
        api.get_shipment(shipment["id"], make_consignee_rep_headers(consignee_eta["id"]))
    )
    assert eta_read["id"] == shipment["id"]

    events = api.list_events(
        shipment["id"], make_consignee_rep_headers(consignee_eta["id"])
    )
    validate_error(events, ApiErrorId.ERR_DATA_SHARE_FORBIDDEN)


def test_customer_service_cannot_create_carriers(api):
    """Peer roles are separated: customer service cannot onboard carriers.

    PRD: "A request whose role is not authorized for the endpoint — or whose
    entity-backed ownership check fails — is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    Design: Corner/rbac/customer_service_cannot_create_carriers
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)

    response = api.create_carrier(
        f.carrier_payload(carrier_name="Sneaky", scac_code="SNKC"), CUSTOMER_SERVICE_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
