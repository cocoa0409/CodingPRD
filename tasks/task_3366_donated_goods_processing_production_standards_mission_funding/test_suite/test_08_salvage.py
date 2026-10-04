"""Salvage channels: bale weight floor, per-item e-waste fees, tiered outlet
pricing, lot membership rules, and terminal-state lockdown."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_lot,
    create_org,
    create_salvaged_item,
    create_site,
    get_org,
    list_items,
    make_member_admin_headers,
    sell_lot,
    sort_item_descriptor,
    create_sorted_items,
    validate_error,
    validate_paginated,
    validate_success,
)

ASSOCIATE = TEST_USERS["store_associate_headers"]


def _get_item(item_id) -> dict:
    return validate_success(api_client.get_donated_item(item_id, ASSOCIATE))


def _list_lots(org_id, params=None):
    rows, meta = validate_paginated(api_client.list_salvage_lots(
        org_id, make_member_admin_headers(org_id), params=params))
    return rows, meta


def _get_lot(org_id, lot_id) -> dict:
    rows, _meta = _list_lots(org_id)
    match = [r for r in rows if r["id"] == lot_id]
    assert match, f"lot {lot_id} not found in org listing"
    return match[0]


def _unsalable_items(site_id, specs, donor_name="Donor"):
    """Sort one donation of UNSALABLE items per (category, weight) spec."""
    items = [sort_item_descriptor(category=cat, condition_grade="UNSALABLE",
                                  estimated_value_cents=0, weight_lbs=w)
             for cat, w in specs]
    _donation, rows = create_sorted_items(site_id, items, donor_name=donor_name)
    return rows


class TestSalvageChannelPricing:
    def test_textile_bale_minimum_weight_boundary(self, api):
        """PRD 3.6: "A `TEXTILE_BALE` sale first requires the
        `total_weight_lbs` to be at least 50 pounds, the boundary inclusive; a
        lighter bale is rejected with `ERR_BALE_UNDERWEIGHT`."
        PRD 3.6: "Bale revenue is then the weight multiplied by 12 cents per
        pound, rounded half-up to whole cents — a 300-pound bale yields 3600
        cents."

        Design: Corner/calculations/textile_bale_minimum_weight_boundary
        """
        org = create_org("Org BW")
        site = create_site(org["id"], name="Site BW")
        under = _unsalable_items(site["id"], [("TEXTILES", 25.0),
                                              ("TEXTILES", 24.0)], "DBW1")
        exact = _unsalable_items(site["id"], [("TEXTILES", 25.0),
                                              ("TEXTILES", 25.0)], "DBW2")
        lot_u = create_lot(org["id"], "TEXTILE_BALE", [i["id"] for i in under])
        lot_v = create_lot(org["id"], "TEXTILE_BALE", [i["id"] for i in exact])
        assert lot_u["total_weight_lbs"] == 49.0
        assert lot_v["total_weight_lbs"] == 50.0

        resp = api_client.sell_salvage_lot(
            lot_u["id"], make_member_admin_headers(org["id"]))
        validate_error(resp, ApiErrorId.ERR_BALE_UNDERWEIGHT)
        assert _get_lot(org["id"], lot_u["id"])["status"] == "OPEN"

        sold = sell_lot(org["id"], lot_v["id"])
        assert sold["status"] == "SOLD"
        assert sold["sale_revenue_cents"] == 600, "50 lbs * 12 cents"

    def test_ewaste_lot_prices_per_item_not_per_pound(self, api):
        """PRD 3.6: "An `EWASTE` lot earns a flat 150 cents per member item, so
        seven items yield 1050 cents."
        PRD 3.6: "The computed amount lands in `sale_revenue_cents`, the lot
        moves to `SOLD` with `sold_at` stamped, and two cascades fire at once:
        the lot's `total_weight_lbs` is added to the organization's
        `total_diverted_lbs`, forcing `diversion_rate_bps` and
        `diversion_compliant` to recompute per §2.9, and the revenue is added
        to `retail_margin_pool_cents`, forcing `margin_health` to recompute per
        §2.8."

        Design: Corner/calculations/ewaste_lot_prices_per_item_not_per_pound
        """
        org = create_org("Org EW")
        site = create_site(org["id"], name="Site EW")
        items = _unsalable_items(site["id"], [("EWASTE", 0.5)] * 7, "DEW")
        lot = create_lot(org["id"], "EWASTE", [i["id"] for i in items])
        sold = sell_lot(org["id"], lot["id"])
        assert sold["item_count"] == 7
        assert sold["sale_revenue_cents"] == 1050, "7 * 150"
        org_after = get_org(org["id"])
        assert org_after["total_diverted_lbs"] == 3.5, (
            "weight still counts toward diversion even when revenue is per-item")
        assert org_after["retail_margin_pool_cents"] == 1050

    def test_outlet_bin_tiered_pricing_on_sale(self, api):
        """PRD 3.6: "An `OUTLET_BIN` lot is tiered by the pound: the first 100
        pounds price at 45 cents each and every pound beyond 100 at 30 cents,
        with the total rounded half-up — a 150-pound bin yields 100 pounds at
        45 plus 50 at 30, or 6000 cents."
        PRD 3.6: "A created lot is `OPEN`, its member items have their
        `salvage_lot_id` set, and the lot's `total_weight_lbs` and `item_count`
        are computed from the membership."

        Design: Difficulty/combinatorial_formula/outlet_sale_tiered_minmax_pricing
        """
        org = create_org("Org Outlet")
        site = create_site(org["id"], name="Site O")
        items = _unsalable_items(site["id"], [("TEXTILES", 75.0),
                                              ("TEXTILES", 75.0)], "Donor O")
        lot = create_lot(org["id"], "OUTLET_BIN", [i["id"] for i in items])
        assert lot["total_weight_lbs"] == 150.0
        assert lot["item_count"] == 2
        for i in items:
            assert _get_item(i["id"])["salvage_lot_id"] == lot["id"]
        sold = sell_lot(org["id"], lot["id"])
        assert sold["status"] == "SOLD"
        assert sold["sale_revenue_cents"] == 6000, (
            "tiered: 100*45 + 50*30, not a flat 150*45 = 6750")
        assert sold.get("sold_at")

    def test_outlet_bin_sale_cascades_to_org_ledgers(self, api):
        """PRD 3.6: "The computed amount lands in `sale_revenue_cents`, the lot
        moves to `SOLD` with `sold_at` stamped, and two cascades fire at once:
        the lot's `total_weight_lbs` is added to the organization's
        `total_diverted_lbs`, forcing `diversion_rate_bps` and
        `diversion_compliant` to recompute per §2.9, and the revenue is added
        to `retail_margin_pool_cents`, forcing `margin_health` to recompute per
        §2.8."

        Design: Difficulty/combinatorial_formula/outlet_sale_tiered_minmax_pricing
        """
        org = create_org("Org Outlet2")
        site = create_site(org["id"], name="Site O2")
        items = _unsalable_items(site["id"], [("TEXTILES", 75.0),
                                              ("TEXTILES", 75.0)], "Donor O2")
        lot = create_lot(org["id"], "OUTLET_BIN", [i["id"] for i in items])
        sell_lot(org["id"], lot["id"])
        org_after = get_org(org["id"])
        assert org_after["total_diverted_lbs"] == 150.0
        assert org_after["retail_margin_pool_cents"] == 6000
        assert org_after["diversion_rate_bps"] == 10000
        assert org_after["diversion_compliant"] is True


class TestSalvageLotTerminalState:
    def test_add_items_to_sold_lot_returns_invalid_state(self, api):
        """PRD 3.6: "Further loads into an `OPEN` lot through the add-items
        capability repeat the same membership and channel checks and recompute
        both totals."
        PRD 2.10: "State-machine preconditions for the requested transition:
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/add_items_to_sold_lot_returns_invalid_state
        """
        org = create_org("Org SL")
        site = create_site(org["id"], name="Site SL")
        first = create_salvaged_item(site["id"], 25.0, donor_name="DSL1")
        second = create_salvaged_item(site["id"], 30.0, donor_name="DSL2")
        lot = create_lot(org["id"], "OUTLET_BIN", [first["id"]])
        sell_lot(org["id"], lot["id"])
        resp = api_client.add_items_to_lot(
            lot["id"], {"item_ids": [second["id"]]},
            make_member_admin_headers(org["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        frozen = _get_lot(org["id"], lot["id"])
        assert frozen["status"] == "SOLD"
        assert frozen["item_count"] == 1
        assert frozen["total_weight_lbs"] == 25.0
        assert _get_item(second["id"]).get("salvage_lot_id") is None

    def test_lot_sell_twice_returns_invalid_state(self, api):
        """PRD 3.6: "Selling a lot — a `MemberAdmin` act requiring the lot
        `OPEN` and the organization `ACTIVE` — prices it by channel."
        PRD 3.6: "An `OUTLET_BIN` lot is tiered by the pound: the first 100
        pounds price at 45 cents each and every pound beyond 100 at 30 cents,
        with the total rounded half-up — a 150-pound bin yields 100 pounds at
        45 plus 50 at 30, or 6000 cents."

        Design: Corner/state_machines/lot_sell_twice_returns_invalid_state
        """
        org = create_org("Org LS")
        site = create_site(org["id"], name="Site LS")
        item = create_salvaged_item(site["id"], 10.0, donor_name="DL")
        lot = create_lot(org["id"], "OUTLET_BIN", [item["id"]])
        sold = sell_lot(org["id"], lot["id"])
        assert sold["sale_revenue_cents"] == 450, "10 lbs * 45, single tier"
        resp = api_client.sell_salvage_lot(
            lot["id"], make_member_admin_headers(org["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        org_after = get_org(org["id"])
        assert org_after["total_diverted_lbs"] == 10.0
        assert org_after["retail_margin_pool_cents"] == 450, "credited once"


class TestSalvageLotMembership:
    def test_channel_incompatible_item_rejected_from_lot(self, api):
        """PRD 3.6: "Second, every named item must be eligible: it must be in
        `SALVAGED` status with no `salvage_lot_id` yet — otherwise
        `ERR_ITEM_ALREADY_IN_LOT` — it must belong to the same organization as
        the lot, and its category must suit the channel: `TEXTILE_BALE` accepts
        `TEXTILES`, `EWASTE` accepts `EWASTE`, and `OUTLET_BIN` accepts
        `TEXTILES`, `HOUSEWARES`, and `MEDIA`, with any other pairing rejected
        as `ERR_ITEM_CHANNEL_MISMATCH`."

        Design: Corner/validations/channel_incompatible_item_rejected_from_lot
        """
        org = create_org("Org CM")
        site = create_site(org["id"], name="Site CM")
        ewaste = create_salvaged_item(site["id"], 4.0, category="EWASTE",
                                      donor_name="DCM")
        resp = api_client.create_salvage_lot(
            {"member_org_id": org["id"], "channel": "TEXTILE_BALE",
             "item_ids": [ewaste["id"]]},
            make_member_admin_headers(org["id"]))
        validate_error(resp, ApiErrorId.ERR_ITEM_CHANNEL_MISMATCH)
        assert _get_item(ewaste["id"]).get("salvage_lot_id") is None
        _rows, meta = _list_lots(org["id"])
        assert meta["total_count"] == 0, "rejected lot must not persist"

    def test_item_already_in_lot_rejected_from_second_lot(self, api):
        """PRD 3.6: "Second, every named item must be eligible: it must be in
        `SALVAGED` status with no `salvage_lot_id` yet — otherwise
        `ERR_ITEM_ALREADY_IN_LOT` — it must belong to the same organization as
        the lot, and its category must suit the channel: `TEXTILE_BALE` accepts
        `TEXTILES`, `EWASTE` accepts `EWASTE`, and `OUTLET_BIN` accepts
        `TEXTILES`, `HOUSEWARES`, and `MEDIA`, with any other pairing rejected
        as `ERR_ITEM_CHANNEL_MISMATCH`."

        Design: Corner/validations/item_already_in_lot_rejected_from_second_lot
        """
        org = create_org("Org AL")
        site = create_site(org["id"], name="Site AL")
        item = create_salvaged_item(site["id"], 12.0, donor_name="DAL")
        lot1 = create_lot(org["id"], "OUTLET_BIN", [item["id"]])
        resp = api_client.create_salvage_lot(
            {"member_org_id": org["id"], "channel": "OUTLET_BIN",
             "item_ids": [item["id"]]},
            make_member_admin_headers(org["id"]))
        validate_error(resp, ApiErrorId.ERR_ITEM_ALREADY_IN_LOT)
        rows, meta = _list_lots(org["id"])
        assert meta["total_count"] == 1
        assert rows[0]["id"] == lot1["id"]
        assert rows[0]["item_count"] == 1
