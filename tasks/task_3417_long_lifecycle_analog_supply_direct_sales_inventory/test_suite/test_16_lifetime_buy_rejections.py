"""Lifetime-buy referential and inventory rejections."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_lifetime_buy_payload,
    get_part,
    make_customer,
    make_customer_headers,
    make_eol_notice,
    make_ltb_ready_part,
    make_part,
    publish_price,
    validate_error,
    validate_success,
)

PLANNER = TEST_USERS["supply_planner_headers"]


class TestLifetimeBuyRejections:
    def test_ltb_against_rescinded_notice_rejected(self, api):
        """PRD §3.7: "The referenced notice must be `ANNOUNCED`, else
        `ERR_EOL_NOTICE_NOT_ACTIVE` (HTTP 422), and the notice's part must be the
        requested `part_id`, else `ERR_NOTICE_PART_MISMATCH` (HTTP 422)."

        Design: Corner/validations/ltb_against_rescinded_notice_rejected
        """
        part = make_part(part_number="LM393P", demand_rate_units_per_week=40)
        # Publish pricing so the §2.8 row-9 pricing check (evaluated first in
        # the row's written order) passes and the notice-status check is the
        # unique highest-priority failure.
        publish_price(part["id"])
        notice = make_eol_notice(part["id"], reason="Issued in error")
        rescinded = validate_success(api.rescind_eol_notice(notice["id"], PLANNER), 200)
        assert rescinded["status"] == "RESCINDED"
        assert get_part(part["id"])["lifecycle_status"] == "ACTIVE"

        cust = make_customer(name="Confused Buyer", tier="STRATEGIC",
                             channel="DIRECT_FIELD", credit_limit_cents=10_000_000)
        res = api.create_lifetime_buy(
            create_lifetime_buy_payload(notice["id"], part["id"], cust["id"], 2080),
            make_customer_headers(cust["id"]),
        )
        validate_error(res, ApiErrorId.ERR_EOL_NOTICE_NOT_ACTIVE)

    def test_ltb_notice_part_mismatch_rejected(self, api):
        """PRD §3.7: "The referenced notice must be `ANNOUNCED`, else
        `ERR_EOL_NOTICE_NOT_ACTIVE` (HTTP 422), and the notice's part must be the
        requested `part_id`, else `ERR_NOTICE_PART_MISMATCH` (HTTP 422)."

        Design: Corner/validations/ltb_notice_part_mismatch_rejected
        """
        part_a = make_part(part_number="LM358AN", demand_rate_units_per_week=40)
        part_b = make_part(part_number="LM358BN", demand_rate_units_per_week=40)
        # Publish pricing for the requested part (part_b) so the §2.8 row-9
        # pricing check (evaluated first in the row's written order) passes and
        # the part-match check is the unique highest-priority failure.
        publish_price(part_b["id"])
        notice = make_eol_notice(part_a["id"], reason="EOL A")

        cust = make_customer(name="Mismatch Buyer", tier="STRATEGIC",
                             channel="DIRECT_FIELD", credit_limit_cents=10_000_000)
        res = api.create_lifetime_buy(
            create_lifetime_buy_payload(notice["id"], part_b["id"], cust["id"], 2080),
            make_customer_headers(cust["id"]),
        )
        validate_error(res, ApiErrorId.ERR_NOTICE_PART_MISMATCH)

    def test_ltb_insufficient_inventory_rejected(self, api):
        """PRD §3.7: "Available stock must cover the reservation — `on_hand_units`
        minus `reserved_units` at least `quantity` — else
        `ERR_INSUFFICIENT_INVENTORY` (HTTP 422)."

        Design: Corner/validations/ltb_insufficient_inventory_rejected
        """
        part, _, notice = make_ltb_ready_part(
            "TL072ACN", demand_rate=40, on_hand=100, unit_price_cents=150
        )
        cust = make_customer(name="Greedy Buyer", tier="STRATEGIC",
                             channel="DIRECT_FIELD", credit_limit_cents=10_000_000)

        res = api.create_lifetime_buy(
            create_lifetime_buy_payload(notice["id"], part["id"], cust["id"], 2080),
            make_customer_headers(cust["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_INVENTORY)
        assert get_part(part["id"])["reserved_units"] == 0
