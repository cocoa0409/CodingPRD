"""Freight lifecycle: windows, dry-run costing, customs duty dual variant,
rebook cycle, and role exclusivity."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    book_freight,
    create_freight_shipment_payload,
    get_campaign,
    set_clock,
    setup_campaign_in_production,
    ship_freight_fully,
    transition_freight,
    validate_error,
    validate_paginated,
    validate_success,
)

FREIGHT = TEST_USERS["freight_broker_headers"]
CUSTOMS = TEST_USERS["customs_agent_headers"]
FULFILL = TEST_USERS["fulfillment_operator_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


class TestFreightWindows:
    def test_freight_window_half_open_overlap(self, api):
        """PRD §3.5: "Two windows on the same run may touch but may not
        overlap; the half-open convention makes adjacency legal and overlap
        illegal."
        PRD §3.5: "no other shipment on the same run hold an overlapping
        window in `IN_TRANSIT`, `CUSTOMS_HOLD`, `DUTY_ASSESSED`, or `CLEARED`
        (otherwise `ERR_FREIGHT_WINDOW_OVERLAP`; adjacency is allowed)".

        Existing shipment IN_TRANSIT [09-07, 09-20); adjacent [09-20, 10-05)
        books fine; overlapping [09-19, 10-01) is rejected.

        Design: Difficulty/resource_temporal_overlap/freight_window_half_open_overlap
        """
        bundle = setup_campaign_in_production()
        run = bundle["run"]
        s1 = book_freight(
            run["id"],
            departs_at="2026-09-07T00:00:00Z",
            arrives_at="2026-09-20T00:00:00Z",
        )
        set_clock("2026-09-08T00:00:00Z")
        transition_freight(s1["id"], "depart")

        # Adjacent booking succeeds (existing.end == new.start).
        resp = api.create_freight_shipment(
            create_freight_shipment_payload(
                run["id"],
                region_code="EU",
                departs_at="2026-09-20T00:00:00Z",
                arrives_at="2026-10-05T00:00:00Z",
            ),
            FREIGHT,
        )
        validate_success(resp, expected_status=201)

        # Properly overlapping booking is rejected.
        resp = api.create_freight_shipment(
            create_freight_shipment_payload(
                run["id"],
                region_code="APAC",
                departs_at="2026-09-19T00:00:00Z",
                arrives_at="2026-10-01T00:00:00Z",
            ),
            FREIGHT,
        )
        validate_error(resp, ApiErrorId.ERR_FREIGHT_WINDOW_OVERLAP)

    def test_freight_rebook_cyclic_reentry(self, api):
        """PRD §3.5: "rebook moves `CUSTOMS_HOLD → BOOKED` with new
        `departs_at` and `arrives_at` values, replacing the window".

        Design: Corner/state_machines/freight_rebook_cyclic_reentry
        """
        bundle = setup_campaign_in_production()
        run = bundle["run"]
        s1 = book_freight(run["id"])
        set_clock("2026-09-08T00:00:00Z")
        transition_freight(s1["id"], "depart")
        set_clock("2026-09-11T00:00:00Z")
        transition_freight(s1["id"], "arrive")

        resp = api.transition_freight_shipment(
            s1["id"],
            {
                "action": "rebook",
                "departs_at": "2026-09-15T00:00:00Z",
                "arrives_at": "2026-09-25T00:00:00Z",
            },
            FREIGHT,
        )
        data = validate_success(resp)
        assert data["status"] == "BOOKED"
        assert data["departs_at"].startswith("2026-09-15")


class TestFreightDryRun:
    def test_freight_dry_run_returns_cost_without_persisting(self, api):
        """PRD §3.5: "when `dry_run` is true — accompanied by
        `total_weight_kg` and `total_volume_m3` — no shipment is persisted,
        and the response carries a `cost_cents` preview".
        PRD §3.5: "The base charge is `container_count` times the
        per-container rate for the destination region: 350,000 cents for
        `NA`, 420,000 for `EU`, 280,000 for `APAC`, and 510,000 for `ROW`."

        1 container NA, weight 10000 kg, volume 50 m3: dimensional weight
        max(10000, 12500) = 12500 < 22000 → no surcharges → 350,000c.

        Design: Corner/endpoints/freight_dry_run_returns_cost_without_persisting
        """
        bundle = setup_campaign_in_production()
        run = bundle["run"]
        resp = api.create_freight_shipment(
            create_freight_shipment_payload(
                run["id"],
                dry_run=True,
                total_weight_kg=10_000,
                total_volume_m3=50,
            ),
            FREIGHT,
        )
        data = validate_success(resp, expected_status=201)
        assert data["cost_cents"] == 350_000

        resp = api.list_freight_shipments(
            ADMIN, params={"production_run_id": run["id"]}
        )
        rows, meta = validate_paginated(resp)
        assert len(rows) == 0

    def test_freight_consolidation_nested_min_max(self, api):
        """PRD §3.5: "The dimensional weight is the greater of
        `total_weight_kg` and `total_volume_m3` multiplied by 250."
        PRD §3.5: "A weight surcharge adds 8 cents for every kilogram of
        dimensional weight above 22,000, floored at zero. A volume surcharge
        adds 4,000 cents per cubic meter of `total_volume_m3` above 67, or
        zero at or below."

        2 containers EU, weight 25000, volume 80: dim = max(25000, 20000) =
        25000; weight surcharge = 3000*8 = 24000; volume surcharge =
        13*4000 = 52000; total = 2*420000 + 24000 + 52000 = 916000.

        Design: Difficulty/combinatorial_formula/freight_consolidation_nested_min_max
        """
        bundle = setup_campaign_in_production()
        run = bundle["run"]
        resp = api.create_freight_shipment(
            create_freight_shipment_payload(
                run["id"],
                region_code="EU",
                container_count=2,
                declared_value_cents=1,
                departs_at="2026-10-05T00:00:00Z",
                arrives_at="2026-10-20T00:00:00Z",
                dry_run=True,
                total_weight_kg=25_000,
                total_volume_m3=80,
            ),
            FREIGHT,
        )
        data = validate_success(resp, expected_status=201)
        assert data["cost_cents"] == 916_000

    def test_freight_consolidation_volume_drives_dimensional_weight(self, api):
        """PRD §3.5: "The dimensional weight is the greater of
        `total_weight_kg` and `total_volume_m3` multiplied by 250."
        PRD §3.5: "A weight surcharge adds 8 cents for every kilogram of
        dimensional weight above 22,000, floored at zero. A volume surcharge
        adds 4,000 cents per cubic meter of `total_volume_m3` above 67, or
        zero at or below."

        1 container APAC (280,000c), weight 1000 kg, volume 100 m3: volume
        branch wins (100*250 = 25,000 kg); weight surcharge (25,000-22,000)*8
        = 24,000c; volume surcharge (100-67)*4,000 = 132,000c; total
        436,000c.

        Design: Difficulty/combinatorial_formula/freight_consolidation_nested_min_max
        """
        bundle = setup_campaign_in_production()
        run = bundle["run"]
        resp = api.create_freight_shipment(
            create_freight_shipment_payload(
                run["id"],
                region_code="APAC",
                container_count=1,
                departs_at="2026-10-05T00:00:00Z",
                arrives_at="2026-10-20T00:00:00Z",
                dry_run=True,
                total_weight_kg=1_000,
                total_volume_m3=100,
            ),
            FREIGHT,
        )
        data = validate_success(resp, expected_status=201)
        assert data["cost_cents"] == 436_000


class TestCustomsDuty:
    def test_customs_duty_lower_of_two_variants_pinned(self, api):
        """PRD §3.5: "computes the duty under two candidate variants and
        keeps the cheaper."
        PRD §3.5: "Under the `DECLARED_VALUE` variant the dutiable amount is
        the shipment's `declared_value_cents`. Under the `TRANSACTION_VALUE`
        variant the dutiable amount is the production run's `planned_units`
        multiplied by the finalized quote's `final_unit_price_cents`, then
        pro-rated by the shipment's share of the run's total containers."
        PRD §3.5: "The lower result becomes `customs_duty_cents`, and
        `duty_variant_used` records which variant won; on an exact tie,
        `DECLARED_VALUE` wins."

        planned_units=1, final_unit_price=20000c, 1/1 containers →
        transaction dutiable 20000c; NA rate 0.040 → 800c. Declared 100000c
        → 4000c. Cheaper is 800 with variant TRANSACTION_VALUE.

        Design: Difficulty/dual_variant_calc/customs_duty_lower_of_two_variants_pinned
        """
        bundle = setup_campaign_in_production(
            tier_breaks=[{"min_units": 1, "unit_price_cents": 20_000}]
        )
        run = bundle["run"]
        shipment = book_freight(
            run["id"],
            declared_value_cents=100_000,
            departs_at="2026-09-07T00:00:00Z",
            arrives_at="2026-09-20T00:00:00Z",
        )
        set_clock("2026-09-08T00:00:00Z")
        transition_freight(shipment["id"], "depart")
        set_clock("2026-09-21T00:00:00Z")
        transition_freight(shipment["id"], "arrive")
        resp = api.transition_freight_shipment(
            shipment["id"], {"action": "assess-duty"}, CUSTOMS
        )
        data = validate_success(resp)
        assert data["customs_duty_cents"] == 800
        assert data["duty_variant_used"] == "TRANSACTION_VALUE"

    def test_pay_duty_updates_campaign_customs_total(self, api):
        """PRD §3.5: "Paying the duty — `DUTY_ASSESSED → CLEARED` — adds the
        assessed amount to the campaign's `customs_duty_paid_cents`,
        recomputes the net payable, and increments the campaign's `version`."

        Design: Difficulty/dual_variant_calc/customs_duty_lower_of_two_variants_pinned
        """
        bundle = setup_campaign_in_production(
            tier_breaks=[{"min_units": 1, "unit_price_cents": 20_000}]
        )
        run = bundle["run"]
        shipment = book_freight(
            run["id"],
            declared_value_cents=100_000,
            departs_at="2026-09-07T00:00:00Z",
            arrives_at="2026-09-20T00:00:00Z",
        )
        set_clock("2026-09-08T00:00:00Z")
        transition_freight(shipment["id"], "depart")
        set_clock("2026-09-21T00:00:00Z")
        transition_freight(shipment["id"], "arrive")
        assessed = transition_freight(shipment["id"], "assess-duty", headers=CUSTOMS)
        version_before = get_campaign(bundle["campaign"]["id"])["version"]
        resp = api.transition_freight_shipment(
            shipment["id"], {"action": "pay-duty"}, CUSTOMS
        )
        validate_success(resp)
        campaign = get_campaign(bundle["campaign"]["id"])
        assert campaign["customs_duty_paid_cents"] == assessed["customs_duty_cents"]
        assert campaign["version"] == version_before + 1


class TestFreightRoles:
    def test_customs_agent_cannot_book_freight(self, api):
        """PRD §2.1: "A request whose role is not in the endpoint's authorized
        role list is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        The PRD §4 routing table restricts POST /freight-shipments to
        FreightBroker only.

        Design: Corner/roles/customs_agent_cannot_book_freight
        """
        bundle = setup_campaign_in_production()
        resp = api.create_freight_shipment(
            create_freight_shipment_payload(bundle["run"]["id"]), CUSTOMS
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
