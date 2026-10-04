"""Corner queue — rbac section: entity-backed ownership checks, role gates on
exclusive endpoints, and hedge segregation of duties (PRD §2.1/§2.5/§3.2/
§3.4/§3.7/§3.8).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    confirm_board_position,
    create_cash_contract,
    create_buyer,
    create_deferred_contract,
    create_farmer,
    elect_price,
    enter_board_position,
    make_commercial_buyer_headers,
    make_farmer_headers,
    make_plant_scheduler_headers,
    make_risk_manager_headers,
    post_bean_quote,
    post_crush_quote_set,
    set_clock_payload,
    setup_origination_site,
    setup_sales_scenario,
    validate_error,
    validate_success,
)

MERCH = TEST_USERS["origination_merchandiser_headers"]
PRODUCT_MERCH = TEST_USERS["product_merchandiser_headers"]


class TestFarmerOwnership:
    def test_farmer_cannot_read_others_contract(self, api):
        """PRD §3.2: "A `Farmer` caller sees only its own contracts: reads and elections on a contract whose `farmer_id` does not match the caller's `X-User-ID` are `ERR_FORBIDDEN`."

        Design: Corner/rbac/farmer_cannot_read_others_contract
        """
        site = setup_origination_site()
        neighbor = create_farmer(legal_name="B. Neighbor", county="Knox")
        contract = create_cash_contract(
            site["farmer"]["id"], site["elevator"]["id"], quantity_bushels=100
        )
        resp = api_client.get_origination_contract(
            contract["id"], make_farmer_headers(neighbor["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_farmer_can_price_own_contract(self, api):
        """PRD §3.4: "Either the `OriginationMerchandiser` or the owning `Farmer` may elect, supplying `bushels` and the optimistic-concurrency token `expected_contract_version" and "The unit price of an election is the as-of bean futures price — plus the locked `basis_cents_per_bushel` for a `BASIS` contract". The owning farmer's 200-bu election on a 500-bu
        DEFERRED contract lands at the as-of quote.

        Design: Corner/rbac/farmer_can_price_own_contract
        """
        site = setup_origination_site()
        post_bean_quote("2026-12", 1100, "2026-09-01T00:00:00Z")
        contract = create_deferred_contract(
            site["farmer"]["id"], site["elevator"]["id"],
            quantity_bushels=500, futures_month="2026-12",
            pricing_deadline="2026-12-15T00:00:00Z",
            storage_rate_cents_per_bushel_day=1,
        )
        farmer_headers = make_farmer_headers(site["farmer"]["id"])
        updated = elect_price(contract["id"], 200, headers=farmer_headers)
        assert updated["pricing_status"] == "PARTIALLY_PRICED"
        assert float(updated["priced_bushels"]) == pytest.approx(200)
        assert updated["elections"][-1]["unit_price_cents"] == 1100
        assert updated["elections"][-1]["origin"] == "CLIENT"


class TestBuyerOwnership:
    def test_buyer_cannot_read_others_sales_contract(self, api):
        """PRD §3.8: "a `CommercialBuyer` caller sees only its own contracts — any other access is `ERR_FORBIDDEN`."

        Design: Corner/rbac/buyer_cannot_read_others_sales_contract
        """
        base = setup_sales_scenario(product="SOY_OIL")
        rival = create_buyer(company_name="Rival Feeds Inc")
        resp = api_client.get_product_sales_contract(
            base["contract"]["id"], make_commercial_buyer_headers(rival["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestExclusiveEndpoints:
    def test_scheduler_cannot_confirm_hedge(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)"; PRD §4 permits
        only RiskManager on the confirm endpoint. A PlantScheduler caller is
        denied regardless of user id and the position stays ENTERED.

        Design: Corner/rbac/scheduler_cannot_confirm_hedge
        """
        post_crush_quote_set("2026-11")
        position = enter_board_position(trader_user_id="trader-77")
        resp = api_client.confirm_board_crush_position(
            position["id"], make_plant_scheduler_headers("sched-1")
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = validate_success(
            api_client.get_board_crush_position(
                position["id"], TEST_USERS["crush_trader_headers"]
            )
        )
        assert after["status"] == "ENTERED"

    def test_merchandiser_cannot_set_clock(self, api):
        """PRD §2.5: "Only a `PlatformAdmin` may advance it" — the logical clock
        endpoint denies every other role with ERR_FORBIDDEN.

        Design: Corner/rbac/merchandiser_cannot_set_clock
        """
        resp = api_client.set_clock(
            set_clock_payload("2026-12-01T00:00:00Z"), MERCH
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestSegregationOfDuties:
    def test_sod_same_user_cannot_confirm_own_entry(self, api):
        """PRD §3.7: "the confirming user's `X-User-ID` must differ from
        `entered_by_user_id`, and a match is rejected `ERR_SEGREGATION_OF_DUTIES`."
        and "A clean confirm records the confirmer as `confirmed_by_user_id`,
        moves the position to `CONFIRMED`, and increments its `version`."
        trader-77's self-confirm fails 403; rm-9's confirm succeeds.

        Design: Corner/rbac/sod_same_user_cannot_confirm_own_entry
        """
        post_crush_quote_set("2026-11")
        position = enter_board_position(trader_user_id="trader-77")
        resp = api_client.confirm_board_crush_position(
            position["id"], make_risk_manager_headers("trader-77")
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        confirmed = confirm_board_position(position["id"], "rm-9")
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["confirmed_by_user_id"] == "rm-9"
        assert confirmed["entered_by_user_id"] == "trader-77"
