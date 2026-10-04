"""Corner queue — endpoints section: the fixed success/error response
envelope, and the purely server-computed shipment freight cost and arrival
date (PRD §2.2 and §3.5).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_shipment,
    book_shipment,
    create_crush_plant,
    create_farmer_payload,
    create_truck_lane,
    setup_elevator_with_stored_bushels,
)
from conftest import parse_iso

ADMIN = TEST_USERS["platform_admin_headers"]
MERCH = TEST_USERS["origination_merchandiser_headers"]


class TestResponseEnvelope:
    def test_response_envelope_success_and_error_shapes(self, api):
        """PRD §2.2 success envelope: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`." and `response_type` is either object or array; error
        envelope: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`." with data carrying
        error_id and a message per "The `message` provides a human-readable explanation of what went wrong."

        Design: Corner/endpoints/response_envelope_success_and_error_shapes
        """
        resp = api_client.create_farmer(
            create_farmer_payload(legal_name="Env Check", county="Knox"), ADMIN
        )
        assert resp.status_code == 201
        body = resp.json()
        assert set(body.keys()) == {"meta", "response_type", "data"}
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert body["meta"]["api_request_timestamp"]
        farmer_id = body["data"]["id"]
        assert body["data"]["legal_name"] == "Env Check"

        err_resp = api_client.get_origination_contract(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", MERCH
        )
        assert err_resp.status_code == 404
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        assert set(err_body["meta"].keys()) == {
            "api_request_id", "api_request_timestamp"
        }
        assert err_body["data"]["error_id"] == "ERR_CONTRACT_NOT_FOUND"
        assert err_body["data"]["message"].strip()
        assert farmer_id  # sanity: the success path minted an id


class TestShipmentComputedFields:
    def test_shipment_freight_cost_and_arrival_computed(self, api):
        """PRD §3.5: "The booking computes `arrival_date` as the departure plus the lane's `transit_days` calendar days and `freight_cost_cents` as the `bushels` multiplied by the lane's `freight_cents_per_bushel`, rounded half up to whole cents, and the shipment is born `BOOKED`." 2000 bu at
        12 cents -> 24000; departure 2026-09-10 plus 2 days -> 2026-09-12.

        Design: Corner/endpoints/shipment_freight_cost_and_arrival_computed
        """
        base = setup_elevator_with_stored_bushels(5000)
        plant = create_crush_plant()
        lane = create_truck_lane(
            base["site"]["elevator"]["id"], plant["id"],
            freight_cents_per_bushel=12, transit_days=2,
        )
        shipment = book_shipment(lane["id"], 2000,
                                 departure_date="2026-09-10T00:00:00Z")
        assert_shipment(shipment)
        assert shipment["status"] == "BOOKED"
        assert shipment["freight_cost_cents"] == 24000
        assert parse_iso(shipment["arrival_date"]) == parse_iso(
            "2026-09-12T00:00:00Z"
        )
        drawn = sum(float(d["bushels"]) for d in shipment["draws"])
        assert drawn == pytest.approx(2000), "draws cover exactly the load"
