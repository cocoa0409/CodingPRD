"""Published pricing: tier boundaries, channel invariance, supersede, OCC."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_pricing_schedule_payload,
    get_part,
    make_part,
    publish_price,
    validate_error,
    validate_paginated,
    validate_success,
)

PLANNER = TEST_USERS["supply_planner_headers"]
CHANNEL = TEST_USERS["channel_manager_headers"]

TIERS_3 = [
    {"min_qty": 1, "unit_price_cents": 250},
    {"min_qty": 100, "unit_price_cents": 210},
    {"min_qty": 1000, "unit_price_cents": 175},
]


def _make_tiered_part(part_number):
    part = make_part(part_number=part_number)
    publish_price(part["id"], effective_from="2026-08-01T00:00:00Z", tiers=TIERS_3)
    return part


class TestPricingQuotes:
    def test_quote_qty_at_tier_boundary_gets_tier_price(self, api):
        """PRD §3.3: "The achieved tier is the last tier whose `min_qty` is less than
        or equal to the requested quantity — the boundary is inclusive, so a quantity
        exactly equal to a tier's `min_qty` qualifies for that tier — and the quoted
        `unit_price_cents` is that tier's rate applied to the entire quantity
        (all-units pricing, never marginal)."
        PRD §3.3: "The `channel` argument is validated but must not influence the
        result, and all prices are integer cents with no rounding."

        Design: Difficulty/boundary_precision_check/quote_qty_at_tier_boundary_gets_tier_price
        """
        part = _make_tiered_part("LM358DR")

        q99 = validate_success(
            api.quote_price({"part_id": part["id"], "quantity": 99, "channel": "DIRECT_ONLINE"}, CHANNEL), 200
        )
        assert q99["unit_price_cents"] == 250 and q99["tier_min_qty"] == 1

        q100 = validate_success(
            api.quote_price({"part_id": part["id"], "quantity": 100, "channel": "DIRECT_ONLINE"}, CHANNEL), 200
        )
        assert q100["unit_price_cents"] == 210 and q100["tier_min_qty"] == 100

        q1000 = validate_success(
            api.quote_price({"part_id": part["id"], "quantity": 1000, "channel": "DISTRIBUTOR"}, CHANNEL), 200
        )
        assert q1000["unit_price_cents"] == 175 and q1000["tier_min_qty"] == 1000

        q100d = validate_success(
            api.quote_price({"part_id": part["id"], "quantity": 100, "channel": "DISTRIBUTOR"}, CHANNEL), 200
        )
        assert q100d["unit_price_cents"] == 210, "published pricing is channel-invariant"

    def test_quote_qty_at_first_tier_and_mid_tier(self, api):
        """PRD §3.3: "The `tiers` array holds entries pairing a `min_qty` with a
        `unit_price_cents`, sorted ascending by `min_qty`, and the first tier's
        `min_qty` must be exactly 1 so that every positive quantity is priced; a
        malformed array is `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.3: "The achieved tier is the last tier whose `min_qty` is less than
        or equal to the requested quantity — the boundary is inclusive, so a quantity
        exactly equal to a tier's `min_qty` qualifies for that tier — and the quoted
        `unit_price_cents` is that tier's rate applied to the entire quantity
        (all-units pricing, never marginal)."

        Design: Difficulty/boundary_precision_check/quote_qty_at_tier_boundary_gets_tier_price
        """
        part = _make_tiered_part("LM358DR2")

        q1 = validate_success(
            api.quote_price({"part_id": part["id"], "quantity": 1, "channel": "DIRECT_FIELD"}, CHANNEL), 200
        )
        assert q1["unit_price_cents"] == 250 and q1["tier_min_qty"] == 1

        q500 = validate_success(
            api.quote_price({"part_id": part["id"], "quantity": 500, "channel": "DIRECT_FIELD"}, CHANNEL), 200
        )
        assert q500["unit_price_cents"] == 210 and q500["tier_min_qty"] == 100

    def test_quote_without_published_schedule_returns_no_published_pricing(self, api):
        """PRD §3.3: "The price is read from the part's single `PUBLISHED` schedule
        whose `effective_from` is at or before the current logical-clock reading; if
        no published schedule has become effective yet, the quote is rejected with
        `ERR_NO_PUBLISHED_PRICING` (HTTP 422)."

        Design: Corner/calculations/quote_without_published_schedule_returns_no_published_pricing
        """
        part = make_part(part_number="LM386N-4")
        res = api.quote_price(
            {"part_id": part["id"], "quantity": 10, "channel": "DIRECT_ONLINE"}, CHANNEL
        )
        validate_error(res, ApiErrorId.ERR_NO_PUBLISHED_PRICING)

    def test_schedule_supersede_switches_quote_price(self, api):
        """PRD §3.3: "On success the new schedule is created with `status` `PUBLISHED`
        and `published_at` stamped from the logical clock, the part's previously
        `PUBLISHED` schedule — if any — moves to `SUPERSEDED`, and the part's `version`
        increments by one."
        PRD §3.3: "The list of a part's schedules supports a `status` filter and, as
        an explicit exception to the default ordering of §2.3, returns schedules with
        the newest `effective_from` first."

        Design: Corner/calculations/schedule_supersede_switches_quote_price
        """
        part = make_part(part_number="TL081CP")
        publish_price(part["id"], unit_price_cents=100, effective_from="2026-08-01T00:00:00Z")
        publish_price(part["id"], unit_price_cents=120, effective_from="2026-08-15T00:00:00Z")

        quote = validate_success(
            api.quote_price({"part_id": part["id"], "quantity": 10, "channel": "DIRECT_FIELD"}, CHANNEL), 200
        )
        assert quote["unit_price_cents"] == 120

        schedules, meta = validate_paginated(
            api.list_part_pricing_schedules(part["id"], CHANNEL)
        )
        assert meta["total_count"] == 2
        assert schedules[0]["status"] == "PUBLISHED"
        assert schedules[0]["tiers"][0]["unit_price_cents"] == 120
        assert schedules[1]["status"] == "SUPERSEDED"
        assert schedules[1]["tiers"][0]["unit_price_cents"] == 100

    def test_pricing_publish_stale_part_version_rejected(self, api):
        """PRD §2.7: "If the part's current `version` has advanced since that
        observation — for example because another writer has just published a schedule
        for the same part, an act which itself increments the part's `version` — the
        publish is rejected with `ERR_STALE_VERSION` (HTTP 412), and no schedule is
        created or superseded."

        Design: Corner/cross_cutting_layers/pricing_publish_stale_part_version_rejected
        """
        part = make_part(part_number="TLC272CP")
        stale_version = part["version"]
        publish_price(part["id"], unit_price_cents=100, effective_from="2026-08-01T00:00:00Z")
        after_first = get_part(part["id"])
        assert after_first["version"] == stale_version + 1

        payload = create_pricing_schedule_payload(
            part["id"],
            expected_part_version=stale_version,
            effective_from="2026-08-15T00:00:00Z",
            unit_price_cents=120,
        )
        validate_error(api.create_pricing_schedule(payload, CHANNEL), ApiErrorId.ERR_STALE_VERSION)

        schedules, meta = validate_paginated(
            api.list_part_pricing_schedules(part["id"], CHANNEL)
        )
        assert meta["total_count"] == 1
        assert schedules[0]["status"] == "PUBLISHED"
        assert schedules[0]["tiers"][0]["unit_price_cents"] == 100
        assert get_part(part["id"])["version"] == stale_version + 1
