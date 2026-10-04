"""Linehaul lifecycle: daily-capacity gate, arrival state ordering, and the
miss cascade (promised-date recompute + rebind)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    set_clock,
    create_hub,
    create_linehaul,
    setup_routed_network_order,
    api_client,
    TEST_USERS,
    SETUP_CLOCK,
)

ADMIN = TEST_USERS["network_admin_headers"]
HUB_OP = TEST_USERS["hub_operator_headers"]


class TestLinehaulMissRecascadesPromisedDates:
    def _setup(self, api):
        """Routed OWNED_FINAL_MILE order bound to L1 (arrival 2026-09-10)
        with two replacement PLANNED linehauls L2 (2026-09-12) and
        L3 (2026-09-14); L1 departed."""
        refs = setup_routed_network_order()
        lh2 = create_linehaul(
            refs["hub"]["id"], planned_arrival_date="2026-09-12",
            origin_ship_date="2026-09-09", capacity=10,
        )
        lh3 = create_linehaul(
            refs["hub"]["id"], planned_arrival_date="2026-09-14",
            origin_ship_date="2026-09-11", capacity=10,
        )
        get = api_client.depart_linehaul(refs["linehaul"]["id"], ADMIN)
        validate_success(get, 200)
        refs["lh2"] = lh2
        refs["lh3"] = lh3
        return refs

    def test_miss_recomputes_promised_date_and_rebinds(self, api):
        """PRD §3.5: "When a `HubOperator` marks a departed linehaul missed,
        the network compensates automatically. For every shipment bound to
        that linehaul whose state is neither `DELIVERED` nor `EXCEPTION`: the
        shipment's `linehaul_misses` counter increments by one, its
        `promised_date` is recomputed — the promised date slips by exactly 2
        days per recorded miss, reflecting one day of rebooked linehaul slip
        and one day of additional hub dwell — and the shipment re-binds to
        the earliest-`planned_arrival_date` `PLANNED` linehaul into the same
        hub with free capacity, ties broken by `created_at` ascending."

        Design: Difficulty/transitive_cascade/linehaul_miss_recascades_promised_dates
        """
        refs = self._setup(api)
        validate_success(
            api.mark_linehaul_missed(refs["linehaul"]["id"], HUB_OP), 200
        )
        shipment = validate_success(
            api.get_shipment(refs["shipment"]["id"], ADMIN)
        )
        assert shipment["linehaul_misses"] == 1
        # base promised 2026-09-11 (+2 handling +3 transit +1 dwell) + 2
        assert shipment["promised_date"] == "2026-09-13"
        assert shipment["linehaul_id"] == refs["lh2"]["id"], (
            "shipment re-binds to the earliest PLANNED replacement linehaul"
        )

    def test_second_miss_slips_two_more_days_and_migrates_slot(self, api):
        """PRD §3.5: "the promised date slips by exactly 2 days per recorded
        miss, reflecting one day of rebooked linehaul slip and one day of
        additional hub dwell"
        PRD §3.5: "The rebinding decrements the old linehaul's
        `committed_count` by one and increments the new one by one."

        Design: Difficulty/transitive_cascade/linehaul_miss_recascades_promised_dates
        """
        refs = self._setup(api)
        validate_success(
            api.mark_linehaul_missed(refs["linehaul"]["id"], HUB_OP), 200
        )
        missed_first = validate_success(
            api.get_linehaul(refs["linehaul"]["id"], ADMIN)
        )
        lh2_after_first = validate_success(
            api.get_linehaul(refs["lh2"]["id"], ADMIN)
        )
        assert missed_first["status"] == "MISSED"
        assert missed_first["committed_count"] == 0
        assert lh2_after_first["committed_count"] == 1

        validate_success(api.depart_linehaul(refs["lh2"]["id"], ADMIN), 200)
        validate_success(
            api.mark_linehaul_missed(refs["lh2"]["id"], HUB_OP), 200
        )
        shipment = validate_success(
            api.get_shipment(refs["shipment"]["id"], ADMIN)
        )
        assert shipment["linehaul_misses"] == 2
        assert shipment["promised_date"] == "2026-09-15"
        assert shipment["linehaul_id"] == refs["lh3"]["id"]


class TestStateBeatsSafetyOnLinehaulArrive:
    def test_arrive_on_planned_linehaul_at_full_hub_returns_invalid_state(self, api):
        """PRD §3.2: "A `NetworkAdmin` marks a linehaul departed, moving it
        from `PLANNED` to `DEPARTED`; any other source state is rejected with
        `ERR_INVALID_STATE`."
        PRD §2.7: "Every incoming request passes through a fixed validation
        pipeline, and the order matters because the first failing check
        determines the error returned."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_linehaul_arrive
        """
        set_clock(SETUP_CLOCK)
        hub = create_hub(
            hub_code="HUB-C", name="Capacity Hub", serves_zones=["ZONE_NE"],
            white_glove_capable=False, daily_capacity=1,
        )
        lh_full = create_linehaul(
            hub["id"], planned_arrival_date="2026-09-05",
            origin_ship_date="2026-09-03", capacity=5,
        )
        validate_success(api.depart_linehaul(lh_full["id"], ADMIN), 200)
        validate_success(api.arrive_linehaul(lh_full["id"], HUB_OP), 200)
        lh3 = create_linehaul(
            hub["id"], planned_arrival_date="2026-09-05",
            origin_ship_date="2026-09-03", capacity=5,
        )
        # Hub daily capacity is exhausted for the date AND lh3 is still
        # PLANNED; the state check must fire first.
        resp = api.arrive_linehaul(lh3["id"], HUB_OP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        still = validate_success(api.get_linehaul(lh3["id"], ADMIN))
        assert still["status"] == "PLANNED"

    def test_state_error_takes_priority_over_capacity_error(self, api):
        """PRD §2.7: "Only after these five general gates pass do the
        endpoint-specific business rules run"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_linehaul_arrive
        """
        set_clock(SETUP_CLOCK)
        hub = create_hub(
            hub_code="HUB-C", name="Capacity Hub", serves_zones=["ZONE_NE"],
            white_glove_capable=False, daily_capacity=1,
        )
        lh_full = create_linehaul(
            hub["id"], planned_arrival_date="2026-09-05",
            origin_ship_date="2026-09-03", capacity=5,
        )
        validate_success(api.depart_linehaul(lh_full["id"], ADMIN), 200)
        validate_success(api.arrive_linehaul(lh_full["id"], HUB_OP), 200)
        lh3 = create_linehaul(
            hub["id"], planned_arrival_date="2026-09-05",
            origin_ship_date="2026-09-03", capacity=5,
        )
        resp = api.arrive_linehaul(lh3["id"], HUB_OP)
        assert resp.status_code == 409
        error_id = resp.json()["data"]["error_id"]
        assert error_id == ApiErrorId.ERR_INVALID_STATE
        assert error_id != ApiErrorId.ERR_HUB_DAILY_CAPACITY_EXCEEDED


class TestHubDailyCapacityWholeDateOverlap:
    def test_second_arrival_same_date_rejected(self, api):
        """PRD §3.2: "Arrival moves the linehaul from `DEPARTED` to `ARRIVED`
        and is gated by the hub's daily capacity: if the number of linehauls
        already `ARRIVED` at the same hub with the same `planned_arrival_date`
        has reached the hub's `daily_capacity`, the arrival is rejected with
        `ERR_HUB_DAILY_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/hub_daily_capacity_whole_date_overlap
        """
        set_clock(SETUP_CLOCK)
        hub = create_hub(
            hub_code="HUB-C2", name="Cap Hub 2", serves_zones=["ZONE_NE"],
            white_glove_capable=False, daily_capacity=1,
        )
        la = create_linehaul(
            hub["id"], planned_arrival_date="2026-09-05",
            origin_ship_date="2026-09-03", capacity=5,
        )
        validate_success(api.depart_linehaul(la["id"], ADMIN), 200)
        validate_success(api.arrive_linehaul(la["id"], HUB_OP), 200)
        lb = create_linehaul(
            hub["id"], planned_arrival_date="2026-09-05",
            origin_ship_date="2026-09-03", capacity=5,
        )
        validate_success(api.depart_linehaul(lb["id"], ADMIN), 200)
        resp = api.arrive_linehaul(lb["id"], HUB_OP)
        validate_error(resp, ApiErrorId.ERR_HUB_DAILY_CAPACITY_EXCEEDED)

    def test_arrival_on_disjoint_date_succeeds(self, api):
        """PRD §3.2: "a `daily_capacity` expressing the maximum number of
        linehauls that may reach `ARRIVED` status at the hub on any single
        calendar date, counted as a whole-date aggregate."

        Design: Difficulty/resource_temporal_overlap/hub_daily_capacity_whole_date_overlap
        """
        set_clock(SETUP_CLOCK)
        hub = create_hub(
            hub_code="HUB-C2", name="Cap Hub 2", serves_zones=["ZONE_NE"],
            white_glove_capable=False, daily_capacity=1,
        )
        la = create_linehaul(
            hub["id"], planned_arrival_date="2026-09-05",
            origin_ship_date="2026-09-03", capacity=5,
        )
        validate_success(api.depart_linehaul(la["id"], ADMIN), 200)
        validate_success(api.arrive_linehaul(la["id"], HUB_OP), 200)
        lc = create_linehaul(
            hub["id"], planned_arrival_date="2026-09-06",
            origin_ship_date="2026-09-04", capacity=5,
        )
        validate_success(api.depart_linehaul(lc["id"], ADMIN), 200)
        arrived = validate_success(api.arrive_linehaul(lc["id"], HUB_OP), 200)
        assert arrived["status"] == "ARRIVED"
