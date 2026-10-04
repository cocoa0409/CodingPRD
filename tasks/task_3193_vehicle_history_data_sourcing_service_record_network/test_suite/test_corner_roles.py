"""Breadth tests: role-based access control denials."""

from test_helpers import (
    VIN_A,
    ApiErrorId,
    create_consumer,
    create_dealer,
    make_dealer_agent_headers,
    make_network_admin_headers,
    make_source_operator_headers,
    make_vehicle_owner_headers,
    register_source,
    setup_network,
    setup_network_with_source,
    setup_published_listing,
    submit_title,
    validate_error,
)


class TestSourceOperatorCannotAdministerSources:
    def test_source_operator_activate_denied(self, api, admin_headers):
        """PRD §2.1: "A request whose role is valid but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/roles/source_operator_cannot_administer_sources
        """
        setup_network(api)
        source = register_source(api, activate=False)
        resp = api.activate_source(source["id"], make_source_operator_headers(source["id"]))
        validate_error(resp, ApiErrorId.FORBIDDEN_FOR_ROLE)


class TestVehicleOwnerCannotFileDealerReport:
    def test_dealer_subscription_product_is_dealer_agent_only(self, api, admin_headers):
        """PRD §4: "`POST /reports` Purchase a vehicle history report — VehicleOwner, DealerAgent"
        PRD §2.1: "A request whose role is valid but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/roles/vehicle_owner_cannot_file_dealer_report
        """
        network, source = setup_network_with_source(api)
        title = submit_title(api, source["id"], VIN_A, "CA", "clean")
        consumer = create_consumer(api)
        dealer = create_dealer(api)
        resp = api.purchase_report(
            {"vehicle_id": title["vehicle_id"], "product": "DEALER_SUBSCRIPTION", "buyer_dealer_id": dealer["id"]},
            make_vehicle_owner_headers(consumer["id"]),
        )
        validate_error(resp, ApiErrorId.FORBIDDEN_FOR_ROLE)


class TestDealerAgentOwnership:
    def test_other_dealers_agent_cannot_publish_listing(self, api, admin_headers):
        """PRD §3.9: "Publication requires the dealer to be `ACTIVE` (otherwise `ERR_DEALER_SUSPENDED`), the acting agent to own the listing's dealer (otherwise `ERR_NOT_LISTING_OWNER`)"
        PRD §2.1: "When `X-User-Role` is `DealerAgent`, `X-User-ID` is the `id` of the acting `Dealer`; ownership checks on listings and dealer-scoped report purchases compare the resource's `dealer_id` to `X-User-ID`."

        Design: Corner/roles/dealer_agent_ownership_check_on_listings
        """
        network, source = setup_network_with_source(api)
        title = submit_title(api, source["id"], VIN_A, "CA", "clean")
        dealer1 = create_dealer(api, legal_name="D1")
        dealer2 = create_dealer(api, legal_name="D2")
        created = api.create_listing(
            dealer1["id"],
            {"vehicle_id": title["vehicle_id"], "asking_price_cents": 700_000},
            make_dealer_agent_headers(dealer1["id"]),
        )
        listing = created.json()["data"]
        resp = api.publish_listing(dealer1["id"], listing["id"], {}, make_dealer_agent_headers(dealer2["id"]))
        validate_error(resp, ApiErrorId.NOT_LISTING_OWNER)
