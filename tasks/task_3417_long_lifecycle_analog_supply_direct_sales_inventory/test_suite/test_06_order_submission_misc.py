"""Order submission corners: second submit, NRND orderability, credit boundary."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    get_customer,
    get_inventory_position,
    make_customer,
    make_customer_headers,
    make_order,
    make_stocked_priced_part,
    submit_order,
    validate_error,
    validate_success,
)

PLANNER = TEST_USERS["supply_planner_headers"]


class TestOrderSubmissionMisc:
    def test_order_second_submit_returns_invalid_state(self, api):
        """PRD §3.4: "Submission is the pivotal act and is permitted only from
        `DRAFT`; a second submission is `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/order_second_submit_returns_invalid_state
        """
        part, _ = make_stocked_priced_part(
            "SN7404N", on_hand=100, unit_price_cents=100,
            site_name="DFAB", process_technology="CMOS_180NM",
        )
        cust = make_customer(name="Idem Co", credit_limit_cents=1_000_000)
        order = make_order(cust["id"], [{"part_id": part["id"], "quantity": 5}])
        submit_order(order["id"], cust["id"])

        res = api.submit_order(order["id"], make_customer_headers(cust["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

        after = validate_success(api.get_order(order["id"], PLANNER), 200)
        assert after["status"] == "ALLOCATED"
        assert after["total_cents"] == 500
        assert get_inventory_position(part["id"])["reserved_units"] == 5

    def test_nrnd_part_remains_orderable(self, api):
        """PRD §3.4: "Every line's part must be orderable — `lifecycle_status`
        `ACTIVE`, `NRND`, or `EOL_ANNOUNCED`; a line on a `LAST_TIME_BUY` or
        `DISCONTINUED` part is rejected with `ERR_PART_NOT_ORDERABLE` (HTTP 422)."
        PRD §3.1: "The planner may later update `demand_rate_units_per_week` and
        `buffer_multiple`, and may toggle the lifecycle between `ACTIVE` and `NRND`
        ("not recommended for new designs") — `ACTIVE` to `NRND`, or `NRND` back to
        `ACTIVE`."

        Design: Corner/endpoints/nrnd_part_remains_orderable
        """
        part, _ = make_stocked_priced_part(
            "LM741H", on_hand=100, unit_price_cents=100
        )
        patched = validate_success(
            api.patch_part(part["id"], {"lifecycle_status": "NRND"}, PLANNER), 200
        )
        assert patched["lifecycle_status"] == "NRND"

        cust = make_customer(name="Legacy Buyer", credit_limit_cents=1_000_000)
        order = make_order(cust["id"], [{"part_id": part["id"], "quantity": 5}])
        submitted = submit_order(order["id"], cust["id"])
        assert submitted["status"] == "ALLOCATED"
        assert submitted["total_cents"] == 500
        assert get_inventory_position(part["id"])["reserved_units"] == 5

    def test_credit_limit_equality_passes_then_overflow_rejected(self, api):
        """PRD §3.2: "The boundary is inclusive — landing exactly on the credit limit
        passes — and a breach is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`
        (HTTP 422)."
        PRD §3.4: "`service_fee_cents` is 500 cents — the small-order fee — when the
        customer's tier is `SMALL` and the order's channel is `DIRECT_ONLINE` and
        `subtotal_cents` is strictly below 10000 cents; in every other case, including
        a subtotal of exactly 10000 cents, the fee is 0."

        Design: Corner/validations/credit_limit_equality_passes_then_overflow_rejected
        """
        part, _ = make_stocked_priced_part(
            "MCP6004-I/P", on_hand=100, unit_price_cents=210,
            site_name="DFAB", process_technology="CMOS_180NM",
        )
        cust = make_customer(
            name="Exact Credit", tier="SMALL", channel="DIRECT_ONLINE",
            credit_limit_cents=8900,
        )
        o1 = make_order(cust["id"], [{"part_id": part["id"], "quantity": 40}])
        s1 = submit_order(o1["id"], cust["id"])
        assert s1["status"] == "ALLOCATED"
        assert s1["total_cents"] == 8900  # 8400 subtotal + 500 fee == limit exactly

        o2 = make_order(cust["id"], [{"part_id": part["id"], "quantity": 1}])
        res = api.submit_order(o2["id"], make_customer_headers(cust["id"]))
        validate_error(res, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        assert get_customer(cust["id"])["open_exposure_cents"] == 8900
