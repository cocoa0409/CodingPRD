"""Corner — endpoints: action-endpoint response shape and list filters.

Design: Corner/endpoints
"""
from test_helpers import (
    TEST_USERS, create_offer_payload, get_success_data, setup_film,
    setup_film_with_offer, setup_territory, validate_paginated,
    validate_success,
)

ACQ = TEST_USERS["acq_exec_headers"]


class TestCounterOfferActionEndpoint:
    def test_counter_offer_action_endpoint_returns_new_offer(self, api):
        """PRD §3.2: "The original offer transitions `OPEN → COUNTERED`, and a
        fresh offer is minted on the same film in `OPEN` status with
        `round_number` equal to the prior round plus one."
        PRD §4: "Operations that create a new stand-alone resource return
        `201 Created`" — the counter mints a new offer, so it returns 201 with
        the new offer body.

        Design: Corner/endpoints/counter_offer_action_endpoint_returns_new_offer
        """
        film, o1 = setup_film_with_offer()

        resp = api.counter_offer(
            film["id"], o1["id"],
            create_offer_payload(buyer_code="NEON", upfront_price_cents=2_000_000,
                                 backend_participation_pct=0.12,
                                 prints_advertising_commit_cents=1_500_000),
            ACQ,
        )
        o2 = validate_success(resp, expected_status=201)
        assert o2["id"] != o1["id"]
        assert o2["round_number"] == 2
        assert o2["status"] == "OPEN"
        assert o2["buyer_code"] == "NEON"

        o1_after = get_success_data(api.get_offer(film["id"], o1["id"], ACQ))
        assert o1_after["status"] == "COUNTERED"


class TestListEndpointFilters:
    def test_list_endpoints_support_filter_query_params(self, api):
        """PRD §3.3: "For each pair in the Cartesian product of the offer's
        `requested_territory_codes` and `requested_windows`, a `RightsGrant`
        is created on the deal in `GRANTED` status."
        PRD §4: `GET /deals/{deal_id}/rights-grants` — "List rights grants on
        a deal, optional `territory_code`, `window`, `status`".

        Design: Corner/endpoints/list_endpoints_support_filter_query_params
        """
        setup_territory(code="US")
        setup_territory(code="FR", name="France")
        film = setup_film()
        offer = get_success_data(api.create_offer(
            film["id"],
            create_offer_payload(
                requested_territory_codes=["US", "FR"],
                requested_windows=["THEATRICAL", "HOME_ENT"],
            ),
            TEST_USERS["acq_exec_2_headers"],
        ))
        film_now = get_success_data(api.get_film(film["id"], ACQ))
        deal = validate_success(api.accept_offer(
            film["id"], offer["id"],
            {"expected_film_version": film_now["version"]}, ACQ,
        ), expected_status=201)

        us_rows, us_meta = validate_paginated(
            api.list_deal_rights_grants(
                deal["id"], ACQ, params={"territory_code": "US"},
            )
        )
        assert len(us_rows) == 2
        assert {g["window"] for g in us_rows} == {"THEATRICAL", "HOME_ENT"}

        he_rows, he_meta = validate_paginated(
            api.list_deal_rights_grants(
                deal["id"], ACQ, params={"window": "HOME_ENT"},
            )
        )
        assert len(he_rows) == 2
        assert {g["territory_code"] for g in he_rows} == {"US", "FR"}

        all_rows, all_meta = validate_paginated(
            api.list_deal_rights_grants(deal["id"], ACQ)
        )
        assert len(all_rows) == 4
        assert all_meta["total_count"] == 4
