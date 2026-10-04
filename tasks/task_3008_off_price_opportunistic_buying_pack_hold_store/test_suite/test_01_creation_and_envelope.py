"""Entity creation defaults, existence checks, and request constraint corners."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    TEST_USERS,
    assert_merchandise_season,
    evaluate_lot,
    get_lot,
    make_lot,
    make_lot_line,
    make_store,
    make_vendor,
    make_zone,
    open_season,
    set_clock,
    setup_base,
    validate_error,
    validate_success,
)

BUYER = TEST_USERS["buyer_headers"]
PLANNER = TEST_USERS["planning_lead_headers"]
ALLOCATOR = TEST_USERS["allocation_manager_headers"]
PRICING = TEST_USERS["pricing_analyst_headers"]


class TestSeasonCreationDefaults:
    def test_season_create_returns_draft_and_zero_ledger(self, api):
        """PRD §3.1: "A new season is `DRAFT`, and its four ledger figures —
        `committed_forward_cents`, `committed_packaway_cents`, `spent_forward_cents`,
        and `spent_packaway_cents` — all initialize to zero."

        Design: Corner/entities/merchandise_season_create_returns_defaults_and_computed_zeros
        """
        set_clock()
        res = api.create_season(
            {
                "season_code": "SS2027-Z",
                "start_date": TEST_DEFAULTS["SEASON_START"],
                "end_date": TEST_DEFAULTS["SEASON_END"],
                "department_otb_budget_cents": TEST_DEFAULTS["SEASON_BUDGET"],
                "packaway_reserve_ratio": TEST_DEFAULTS["SEASON_RESERVE_RATIO"],
            },
            PLANNER,
        )
        season = validate_success(res, 201)
        assert_merchandise_season(season)
        assert season["status"] == "DRAFT"
        assert season["version"] == 1
        assert season["committed_forward_cents"] == 0
        assert season["committed_packaway_cents"] == 0
        assert season["spent_forward_cents"] == 0
        assert season["spent_packaway_cents"] == 0
        assert season["created_at"] is not None
        assert season["updated_at"] is not None

    def test_season_create_common_fields_present(self, api):
        """PRD §2.4: "`version` — an integer that increments by exactly 1 on every
        mutation of the resource." A freshly created season is version 1.

        Design: Corner/entities/merchandise_season_create_returns_defaults_and_computed_zeros
        """
        set_clock()
        res = api.create_season(
            {
                "season_code": "SS2027-V",
                "start_date": TEST_DEFAULTS["SEASON_START"],
                "end_date": TEST_DEFAULTS["SEASON_END"],
                "department_otb_budget_cents": 1_000_000,
                "packaway_reserve_ratio": 0.0,
            },
            PLANNER,
        )
        season = validate_success(res, 201)
        assert season["id"] is not None
        assert season["version"] == 1
        assert season["status"] == "DRAFT"


class TestLotCreationRules:
    def test_packaway_lot_without_target_season_rejected(self, api):
        """PRD §3.2: "When the disposition is `PACKAWAY`, a `target_season_id` is
        required and must reference an existing season, still in `DRAFT`, and
        different from the buying season."

        Design: Corner/entities/lot_create_packaway_requires_target_season_and_defaults
        """
        base = setup_base()
        res = api.create_lot(
            {
                "lot_code": "PK-NOTARGET",
                "vendor_id": base["vendor"]["id"],
                "season_id": base["season"]["id"],
                "lot_type": "PACKAWAY",
                "disposition": "PACKAWAY",
                "asking_price_cents": 1_000_000,
                "unit_count": 10,
                "expected_sell_through_pct": 0.9,
                "estimated_unit_retail_cents": 5_000,
                "offer_expires_at": TEST_DEFAULTS["OFFER_EXPIRES_AT"],
            },
            BUYER,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_immediate_lot_defaults_mixed_lot_false_and_null_computed(self, api):
        """PRD §3.2: "the flag defaults to false." PRD §3.2: "Both figures are
        null until the first evaluation."

        Design: Corner/entities/lot_create_packaway_requires_target_season_and_defaults
        """
        base = setup_base()
        payload = {
            "lot_code": "IM-DEFAULT",
            "vendor_id": base["vendor"]["id"],
            "season_id": base["season"]["id"],
            "lot_type": "CLOSEOUT",
            "disposition": "IMMEDIATE",
            "asking_price_cents": 1_000_000,
            "unit_count": 10,
            "expected_sell_through_pct": 0.9,
            "estimated_unit_retail_cents": 5_000,
            "offer_expires_at": TEST_DEFAULTS["OFFER_EXPIRES_AT"],
        }
        lot = validate_success(api.create_lot(payload, BUYER), 201)
        assert lot["mixed_lot"] is False
        assert lot["status"] == "OFFERED"
        assert lot["landed_cost_cents"] is None
        assert lot["deal_quality_score"] is None


class TestNotFound:
    def test_get_vendor_unknown_id_is_not_found(self, api):
        """PRD §2.9: "Request bodies are checked for foreign-key resolution in the
        same spirit" of the path-existence rule producing `ERR_NOT_FOUND` (HTTP 404).

        Design: Corner/entities/vendor_get_with_unknown_id_returns_not_found
        """
        set_clock()
        res = api.get_vendor("00000000-0000-4000-8000-000000000000", BUYER)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)
        body = res.json()
        assert body["response_type"] == "error"
        assert "error_id" in body["data"] and "message" in body["data"]

    def test_lot_line_create_under_unknown_lot_is_not_found(self, api):
        """PRD §2.9: "Endpoints that address nested resources validate path
        identifiers strictly left-to-right: the first identifier in the path that
        does not resolve to an existing resource produces `ERR_NOT_FOUND` (HTTP 404),
        before any deeper identifier or any business rule is examined."

        Design: Corner/entities/lot_line_create_rejected_when_parent_lot_missing
        """
        set_clock()
        res = api.create_lot_line(
            "00000000-0000-4000-8000-000000000000",
            {
                "style_code": "X",
                "department": "APPAREL",
                "quantity": 1,
                "unit_cost_cents": 100,
                "compare_at_claim_cents": 200,
                "target_retail_cents": 150,
            },
            BUYER,
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)


class TestRequestConstraints:
    def test_clearance_weeks_equal_to_cadence_rejected(self, api):
        """PRD §3.1: "a `clearance_weeks` threshold — strictly greater than
        `markdown_cadence_weeks` and at most 52 — at which floor stock is forced
        to clearance."

        Design: Corner/entities/price_zone_rejects_invalid_enum_and_clearance_bound
        """
        set_clock()
        res = api.create_price_zone(
            {
                "zone_code": "NE",
                "compare_at_multiplier": 1.5,
                "markdown_cadence_weeks": 4,
                "clearance_weeks": 4,
            },
            PRICING,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_store_with_undeclared_cluster_code_rejected(self, api):
        """PRD §2.9: "request well-formedness — required fields present, types
        matching, enum values in range, unknown fields rejected — as
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/price_zone_rejects_invalid_enum_and_clearance_bound
        """
        make_zone(zone_code="MT")
        res = api.create_store(
            {
                "store_code": "S-BAD",
                "cluster_code": "DOWNTOWN_CORE",
                "zone_code": "MT",
                "storage_capacity_units": 100,
            },
            ALLOCATOR,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
