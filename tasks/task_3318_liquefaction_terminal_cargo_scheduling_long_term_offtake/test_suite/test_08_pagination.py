"""Listing envelope and pagination defaults."""
from test_helpers import (
    CM,
    ApiErrorId,
    create_customer,
    create_spa_payload,
    get_success_data,
    validate_paginated,
)


class TestListPagination:
    def test_list_pagination_envelope_defaults(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items
        to return; it defaults to 10, with a minimum of 1 and a maximum of 100.
        The `offset` parameter specifies the number of items to skip and defaults
        to 0." PRD §2.3: "Paginated list responses include `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope." PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."

        Design: Corner/endpoints/list_pagination_envelope_defaults
        """
        customer = create_customer(legal_name="Tsadi Energy")
        get_success_data(
            api.create_spa(create_spa_payload(customer["id"]), CM)
        )
        get_success_data(
            api.create_spa(
                create_spa_payload(
                    customer["id"],
                    contract_year_start=2028,
                    term_years=3,
                    annual_contract_quantity_mmbtu=18000000,
                    fixed_liquefaction_fee_usd_per_mmbtu=3.60,
                    destination_flexibility="DES",
                    title_transfer_point="DISCHARGE_PORT",
                    cancellation_notice_days=45,
                    tolerance_pct=0.03,
                    estimated_index_price_usd_per_mmbtu=2.90,
                ),
                CM,
            )
        )
        resp = api.list_customer_spas(customer["id"], CM)
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"].get("api_request_id", "").startswith("req_"), (
            "envelope must carry meta.api_request_id starting with req_"
        )
        assert body["meta"].get("api_request_timestamp"), (
            "envelope must carry meta.api_request_timestamp"
        )
        assert body["response_type"] == "array"
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 10, f"default limit must be 10, got {meta['limit']}"
        assert meta["offset"] == 0, f"default offset must be 0, got {meta['offset']}"
        assert meta["total_count"] == 2, (
            f"two SPAs registered, got total_count {meta['total_count']}"
        )
        assert meta["has_more"] is False
        assert len(data) == 2
