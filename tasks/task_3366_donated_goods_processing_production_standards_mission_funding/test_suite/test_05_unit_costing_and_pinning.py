"""Dual unit-costing variants, standard supersession pinning, the suspension
gate on pricing, and OCC on standard creation."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    close_run,
    create_org,
    create_priced_item,
    create_production_standard_payload,
    create_run,
    create_site,
    create_sorted_items,
    create_standard,
    get_org,
    make_member_admin_headers,
    price_item,
    sell_item,
    setup_org_with_standard,
    sort_item_descriptor,
    validate_error,
    validate_paginated,
    validate_success,
)

ASSOCIATE = TEST_USERS["store_associate_headers"]
REGULATOR = TEST_USERS["brand_regulator_headers"]


def _get_item(item_id) -> dict:
    return validate_success(api_client.get_donated_item(item_id, ASSOCIATE))


def _suspend(org_id):
    return validate_success(api_client.suspend_member_org(org_id, REGULATOR))


def _reinstate(org_id):
    return validate_success(api_client.reinstate_member_org(org_id, REGULATOR))


class TestDualUnitCosting:
    def test_standard_variant_locks_configured_cost_and_margin(self, api):
        """PRD 3.3: "Under the `STANDARD` variant, the unit cost is the
        standard's `hourly_cost_cents` divided by its `target_items_per_hour`,
        rounded half-up to whole cents."
        PRD 3.5: "The sale moves the item to `SOLD`, stamps `sold_at` with the
        logical clock, and books the margin: the difference between
        `current_selling_price_cents` and the locked `unit_cost_cents` is added
        to the organization's `retail_margin_pool_cents`, which in turn
        recomputes `margin_health` per §2.8."

        Design: Difficulty/dual_variant_calc/unit_cost_standard_vs_actual_diverge
        """
        org, site, _std = setup_org_with_standard("Org S",
                                                  costing_method="STANDARD")
        item = create_priced_item(org["id"], site["id"], grade="A")
        assert item["price_cents"] == 1000
        assert item["unit_cost_cents"] == 30, "STANDARD: 1800 / 60"
        sold = sell_item(item["id"])
        assert sold["status"] == "SOLD"
        assert get_org(org["id"])["retail_margin_pool_cents"] == 970

    def test_actual_variant_derives_cost_from_closed_runs(self, api):
        """PRD 3.3: "Under the `ACTUAL` variant, it is the sum of
        `labor_cost_cents` across all of the organization's `CLOSED` processing
        runs in the item's category divided by the sum of
        `item_count_processed` across those same runs, rounded half-up to whole
        cents; if the organization has no closed runs in that category at all,
        the computation falls back to the `STANDARD` variant."
        PRD 3.3: "Identical inputs generally produce different costs under the
        two variants, and the locked value never changes afterward."

        Design: Difficulty/dual_variant_calc/unit_cost_standard_vs_actual_diverge
        """
        org, site, std = setup_org_with_standard("Org A", costing_method="ACTUAL")
        # Two CLOSED TEXTILES runs: (200 items, 6500c) and (100 items, 2700c).
        run1 = create_run(site["id"], std["id"])
        close_run(run1["id"], item_count_processed=200, unsalable_count=0,
                  labor_minutes=600, labor_cost_cents=6500)
        run2 = create_run(site["id"], std["id"])
        close_run(run2["id"], item_count_processed=100, unsalable_count=0,
                  labor_minutes=300, labor_cost_cents=2700)
        item = create_priced_item(org["id"], site["id"], grade="A")
        assert item["price_cents"] == 1000
        assert item["unit_cost_cents"] == 31, (
            "ACTUAL: round_half_up((6500+2700)/(200+100)) = round_half_up(30.67)")
        sell_item(item["id"])
        assert get_org(org["id"])["retail_margin_pool_cents"] == 969


class TestSupersedeKeepsPinnedItem:
    def test_supersede_keeps_pinned_item_price_and_cost(self, api):
        """PRD 3.3: "At most one standard per organization and category is
        `ACTIVE` at a time: creating a new standard for a pairing that already
        has an `ACTIVE` standard moves the prior one to `SUPERSEDED` and the
        new one becomes `ACTIVE`."
        PRD 3.3: "At the same moment the item pins the standard's identity in
        `priced_standard_id`, and this pin is permanent: later supersession
        never reprices the item."

        Design: Corner/cross_cutting_layers/supersede_keeps_pinned_item_price_and_cost
        """
        org, site, std1 = setup_org_with_standard("Org Pin")
        item = create_priced_item(org["id"], site["id"], grade="A")
        assert item["priced_standard_id"] == std1["id"]
        assert item["price_cents"] == 1000
        assert item["unit_cost_cents"] == 30
        std2 = create_standard(
            org["id"], target_items_per_hour=60, hourly_cost_cents=3600,
            grade_price_map={"A": 2000, "B": 1400, "C": 800},
            price_floor_cents=100, price_ceiling_cents=9000)
        assert std2["status"] == "ACTIVE"
        pinned = _get_item(item["id"])
        assert pinned["priced_standard_id"] == std1["id"]
        assert pinned["price_cents"] == 1000
        assert pinned["unit_cost_cents"] == 30
        sell_item(item["id"])
        assert get_org(org["id"])["retail_margin_pool_cents"] == 970, (
            "v2 economics must not be retro-applied to the pinned item")
        rows, _meta = validate_paginated(api_client.list_production_standards(
            org["id"], make_member_admin_headers(org["id"])))
        by_id = {r["id"]: r["status"] for r in rows}
        assert by_id[std1["id"]] == "SUPERSEDED"
        assert by_id[std2["id"]] == "ACTIVE"


class TestPriceBlockedWhenOrgSuspended:
    def test_pricing_rejected_while_org_suspended(self, api):
        """PRD 2.7: "Every org-scoped write — creating sites, standards, runs,
        lots, programs, allocations, contracts, or disposal tickets for the
        org; sorting, pricing, or selling its items; running its markdown
        events; approving, disbursing, reviewing, or attesting under it —
        requires the organization to be `ACTIVE`, and is otherwise rejected
        with `ERR_ORG_SUSPENDED` (HTTP 409)."
        PRD 3.1: "Suspension by a `BrandRegulator` takes an `ACTIVE`
        organization to `SUSPENDED` — any other starting state is rejected with
        `ERR_INVALID_STATE` — and cascades downward: every `PENDING` funding
        allocation belonging to that organization's mission programs is set to
        `CANCELLED`, while `APPROVED` allocations keep their reservation
        untouched."

        Design: Difficulty/cross_entity_state_dependency/item_price_blocked_when_org_suspended
        """
        org, site, _std = setup_org_with_standard("Org Gate")
        _donation, items = create_sorted_items(
            site["id"], [sort_item_descriptor(category="TEXTILES",
                                              condition_grade="A")])
        _suspend(org["id"])
        resp = api_client.price_item(items[0]["id"], ASSOCIATE)
        validate_error(resp, ApiErrorId.ERR_ORG_SUSPENDED)
        item = _get_item(items[0]["id"])
        assert item["status"] == "SORTED"
        assert item.get("price_cents") is None

    def test_pricing_succeeds_after_reinstatement(self, api):
        """PRD 3.1: "Reinstatement takes a `SUSPENDED` organization back to
        `ACTIVE`, re-enabling org-scoped writes without altering any financial
        field."
        PRD 3.3: "Pricing is the retail act that moves an item from `SORTED` to
        `ON_FLOOR`."

        Design: Difficulty/cross_entity_state_dependency/item_price_blocked_when_org_suspended
        """
        org, site, _std = setup_org_with_standard("Org Gate2")
        _donation, items = create_sorted_items(
            site["id"], [sort_item_descriptor(category="TEXTILES",
                                              condition_grade="A")])
        _suspend(org["id"])
        reinstated = _reinstate(org["id"])
        assert reinstated["brand_license_status"] == "ACTIVE"
        priced = price_item(items[0]["id"])
        assert priced["status"] == "ON_FLOOR"
        assert priced["price_cents"] == 1000
        assert priced["unit_cost_cents"] == 30


class TestStandardCreateOcc:
    def test_stale_org_version_rejected_on_standard_create(self, api):
        """PRD 2.11: "If the supplied value does not match the member
        organization's current `version`, the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on an
        organization state it has not observed."
        PRD 2.11: "Both creations legitimately advance the organization's
        `version` themselves — creating a standard supersedes the prior active
        standard for the same category, and creating an allocation draws
        against the margin-pool view encoded in that version — so a replayed
        request carrying the previously observed version is correctly
        recognized as stale."

        Design: Corner/validations/stale_org_version_rejected_on_standard_create
        """
        org = create_org("Org OCC")
        observed_v = org["version"]
        first = validate_success(api_client.create_production_standard(
            create_production_standard_payload(org["id"], observed_v),
            make_member_admin_headers(org["id"])), 201)
        assert get_org(org["id"])["version"] == observed_v + 1
        replay = api_client.create_production_standard(
            create_production_standard_payload(
                org["id"], observed_v, target_items_per_hour=80,
                hourly_cost_cents=2000,
                grade_price_map={"A": 1200, "B": 800, "C": 500},
                price_ceiling_cents=6000),
            make_member_admin_headers(org["id"]))
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION)
        rows, meta = validate_paginated(api_client.list_production_standards(
            org["id"], make_member_admin_headers(org["id"]),
            params={"status": "ACTIVE"}))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["id"], "failed replay superseded nothing"
