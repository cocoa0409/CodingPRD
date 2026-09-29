"""Rule-ladder precedence between co-violated rules, and the exact decision edges of four metrics.

Every test in this module builds its own world from an empty database with the logical clock at
its process-start value, using only the endpoints the specification declares.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_coaching_alert,
    assert_coaching_posture_ladder,
    assert_consignment,
    assert_hauler_ticket,
    assert_settlement_breakdown,
    assert_waste_entry,
    factories,
    fixtures,
    get_success_data,
    make_hauler_operator_headers,
    make_kitchen_staff_headers,
    make_shift_lead_headers,
    make_site_sustainability_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CALIBRATION_DUE_AT = "2027-01-01T00:00:00Z"
CLOCK_INSTANT = "2026-08-01T00:00:00.000Z"


def _assert_instant(actual, expected):
    """Compare two UTC instants, tolerating the fractional-digit spelling of either side."""

    def canonical(value):
        assert isinstance(value, str) and value.endswith("Z"), f"not a UTC instant: {value!r}"
        body = value[:-1]
        if "." not in body:
            body += ".000"
        head, fraction = body.split(".")
        return f"{head}.{(fraction + '000')[:3]}Z"

    assert canonical(actual) == canonical(expected), f"instant {actual!r} is not {expected!r}"


def _prepared_food_type(**overrides):
    """The catalog entry every world below discards: 640 cents per kilogram, donation eligible."""
    payload = {
        "name": "Braised Chicken Portion",
        "category": "PREPARED",
        "default_cost_per_kg_cents": 640,
        "donation_eligible": True,
        "animal_feed_eligible": True,
        "compostable": True,
        "donation_shelf_life_hours": 24,
    }
    payload.update(overrides)
    return fixtures.create_food_type(**payload)


class TestCaptureTimingOutranksLossReasonPlacement:
    """A capture that is both misdated and misplaced reports the dating defect."""

    @staticmethod
    def _world():
        site = fixtures.create_site()
        station = fixtures.create_station(
            site["id"],
            station_code="PREP-1",
            station_kind="PREP",
            calibration_due_at=CALIBRATION_DUE_AT,
            capture_lock_seconds=30,
        )
        food_type = _prepared_food_type()
        shift = fixtures.open_shift(
            site["id"], shift_date="2026-06-10", shift_code="AM", meals_served=1000
        )
        return site, station, food_type, shift

    def test_a_capture_dated_before_its_shift_reports_the_dating_defect(self):
        """Plate waste weighed at a prep bench on the wrong calendar day reports the date error.

        PRD Coverage: "When a single request violates several rules at once, exactly one error is returned — the one belonging to the earliest check in the following fixed evaluation order." "This ordering is normative; reporting a later error in place of an earlier one is a defect even when both conditions genuinely hold." "17. Capture timing — `ERR_CAPTURE_IN_FUTURE`, then `ERR_CAPTURE_OUTSIDE_SHIFT_DATE`." "28. Loss reason compatible with station placement — `ERR_LOSS_REASON_STATION_MISMATCH`." "The `captured_at` instant must not be later than the current logical clock — a strictly future instant is refused with `ERR_CAPTURE_IN_FUTURE` — and the calendar date of `captured_at` must equal the period's `shift_date`, with any other date refused as `ERR_CAPTURE_OUTSIDE_SHIFT_DATE`."

        Design: Difficulty/priority_pair_validation_conflict/capture_date_outside_shift_outranks_loss_reason_station_mismatch
        """
        _site, station, food_type, shift = self._world()

        response = api_client.create_waste_entry(
            factories.create_waste_entry_payload(
                station["id"],
                shift["id"],
                food_type["id"],
                weight_grams=900,
                loss_reason="PLATE_WASTE",
                captured_at="2026-06-09T10:00:00Z",
            ),
            make_kitchen_staff_headers("ks-1"),
        )
        validate_error(response, ApiErrorId.CAPTURE_OUTSIDE_SHIFT_DATE.value)

    def test_repairing_only_the_capture_date_surfaces_the_placement_defect(self):
        """With the date moved onto the shift day, the surviving defect is the station pairing.

        PRD Coverage: "`PLATE_WASTE` is accepted only at a `DISH_RETURN` station, because plate scrapings by definition arrive at the dish return." "Every other pairing — plate waste weighed at the prep bench, trim weighed at the dish return — is refused with `ERR_LOSS_REASON_STATION_MISMATCH`." "28. Loss reason compatible with station placement — `ERR_LOSS_REASON_STATION_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/capture_date_outside_shift_outranks_loss_reason_station_mismatch
        """
        _site, station, food_type, shift = self._world()

        misdated = api_client.create_waste_entry(
            factories.create_waste_entry_payload(
                station["id"],
                shift["id"],
                food_type["id"],
                weight_grams=900,
                loss_reason="PLATE_WASTE",
                captured_at="2026-06-09T10:00:00Z",
            ),
            make_kitchen_staff_headers("ks-1"),
        )
        validate_error(misdated, ApiErrorId.CAPTURE_OUTSIDE_SHIFT_DATE.value)

        repaired = api_client.create_waste_entry(
            factories.create_waste_entry_payload(
                station["id"],
                shift["id"],
                food_type["id"],
                weight_grams=900,
                loss_reason="PLATE_WASTE",
                captured_at="2026-06-10T10:00:00Z",
            ),
            make_kitchen_staff_headers("ks-1"),
        )
        validate_error(repaired, ApiErrorId.LOSS_REASON_STATION_MISMATCH.value)

    def test_neither_refused_capture_leaves_a_row_or_moves_the_shift_totals(self):
        """Both refusals are total: no capture row exists and the period stays empty.

        PRD Coverage: "The owning service period recomputes `shift_waste_grams`, the sum of `weight_grams` over its captures whose status is `RECORDED` or `FLAGGED`; `waste_intensity_kg_per_1k_meals`, which is `shift_waste_grams` divided by `meals_served` rounded half up to 3 decimal places" "When a single request violates several rules at once, exactly one error is returned — the one belonging to the earliest check in the following fixed evaluation order."

        Design: Difficulty/priority_pair_validation_conflict/capture_date_outside_shift_outranks_loss_reason_station_mismatch
        """
        _site, station, food_type, shift = self._world()

        for captured_at in ("2026-06-09T10:00:00Z", "2026-06-10T10:00:00Z"):
            refused = api_client.create_waste_entry(
                factories.create_waste_entry_payload(
                    station["id"],
                    shift["id"],
                    food_type["id"],
                    weight_grams=900,
                    loss_reason="PLATE_WASTE",
                    captured_at=captured_at,
                ),
                make_kitchen_staff_headers("ks-1"),
            )
            assert refused.status_code == 422

        rows, meta = validate_paginated(
            api_client.list_waste_entries(make_kitchen_staff_headers("ks-1"), shift_id=shift["id"])
        )
        assert meta["total_count"] == 0
        assert rows == []

        stored_shift = fixtures.read_shift(shift["id"])
        assert stored_shift["shift_waste_grams"] == 0
        assert stored_shift["waste_intensity_kg_per_1k_meals"] == pytest.approx(0.000, abs=0.01)


class TestDonationEligibilityOutranksShelfLife:
    """When the food may not be donated at all, its expiry is not the complaint."""

    @staticmethod
    def _world():
        site = fixtures.create_site()
        station = fixtures.create_station(
            site["id"],
            station_code="PREP-1",
            station_kind="PREP",
            calibration_due_at=CALIBRATION_DUE_AT,
            capture_lock_seconds=30,
        )
        spoil_type = fixtures.create_food_type(
            name="Mixed Produce Trim",
            category="PRODUCE",
            default_cost_per_kg_cents=210,
            donation_eligible=False,
            animal_feed_eligible=True,
            compostable=True,
            donation_shelf_life_hours=12,
        )
        prep_type = _prepared_food_type()
        hauler = fixtures.create_hauler(
            name="City Food Rescue",
            channels=["DONATION", "COMPOST"],
            rate_cents_per_tonne=52000,
            stop_fee_cents=1800,
            capacity_kg_per_pickup=500,
            max_concurrent_pickups=1,
        )
        shift = fixtures.open_shift(
            site["id"], shift_date="2026-06-10", shift_code="AM", meals_served=1000
        )
        spoil_entry = fixtures.capture_entry(
            station["id"],
            shift["id"],
            spoil_type["id"],
            weight_grams=800,
            loss_reason="SPOILAGE",
            captured_at="2026-06-10T10:00:00Z",
        )
        prep_entry = fixtures.capture_entry(
            station["id"],
            shift["id"],
            prep_type["id"],
            weight_grams=1000,
            loss_reason="TRIM",
            captured_at="2026-06-10T10:05:00Z",
        )
        consignment = fixtures.open_consignment(
            site["id"],
            hauler["id"],
            channel="DONATION",
            pickup_window_start="2026-06-20T08:00:00Z",
            pickup_window_end="2026-06-20T10:00:00Z",
            container_tare_grams=0,
        )
        return site, consignment, spoil_entry, prep_entry

    def test_food_that_may_not_be_donated_reports_the_eligibility_refusal(self):
        """The produce trim is barred from donation outright, and stale by more than a week besides.

        PRD Coverage: "The food must be eligible for the consignment's `channel`: a `DONATION` line requires the food type's `donation_eligible` flag to be true **and** the capture's `stream` to be `PRE_CONSUMER`, because post-consumer material can never be given to people however wholesome its food type" "A violation is refused with `ERR_CHANNEL_INELIGIBLE_FOOD`." "14. Channel eligibility of the routed food — `ERR_CHANNEL_INELIGIBLE_FOOD`." "18. Donation shelf life — `ERR_DONATION_WINDOW_EXPIRED`." "This ordering is normative; reporting a later error in place of an earlier one is a defect even when both conditions genuinely hold."

        Design: Difficulty/priority_pair_validation_conflict/channel_ineligible_food_outranks_expired_donation_window
        """
        site, consignment, spoil_entry, _prep_entry = self._world()

        response = api_client.create_consignment_line(
            factories.create_consignment_line_payload(consignment["id"], spoil_entry["id"], 800),
            make_site_sustainability_manager_headers(site["id"]),
        )
        validate_error(response, ApiErrorId.CHANNEL_INELIGIBLE_FOOD.value)

        assert spoil_entry["stream"] == "PRE_CONSUMER", (
            "a spoilage loss weighed at the prep bench must be pre-consumer, so the eligibility "
            "refusal cannot be a stream rejection in disguise"
        )

    def test_switching_to_donatable_food_leaves_only_the_expired_pickup(self):
        """The prepared portion is donatable, so the surviving objection is the stale pickup.

        PRD Coverage: "On a `DONATION` consignment the food must additionally still be inside its shelf life: the consignment's `pickup_window_start` must be no later than the capture's `captured_at` advanced by the food type's `donation_shelf_life_hours`, with that endpoint inclusive, and a later pickup start is refused with `ERR_DONATION_WINDOW_EXPIRED`." "18. Donation shelf life — `ERR_DONATION_WINDOW_EXPIRED`."

        Design: Difficulty/priority_pair_validation_conflict/channel_ineligible_food_outranks_expired_donation_window
        """
        site, consignment, spoil_entry, prep_entry = self._world()

        ineligible = api_client.create_consignment_line(
            factories.create_consignment_line_payload(consignment["id"], spoil_entry["id"], 800),
            make_site_sustainability_manager_headers(site["id"]),
        )
        validate_error(ineligible, ApiErrorId.CHANNEL_INELIGIBLE_FOOD.value)

        expired = api_client.create_consignment_line(
            factories.create_consignment_line_payload(consignment["id"], prep_entry["id"], 1000),
            make_site_sustainability_manager_headers(site["id"]),
        )
        validate_error(expired, ApiErrorId.DONATION_WINDOW_EXPIRED.value)

    def test_neither_refused_allocation_routes_a_single_gram(self):
        """Both refusals leave the consignment empty and both captures fully unrouted.

        PRD Coverage: "For the affected capture, `routed_weight_grams` becomes the sum of `allocated_weight_grams` over all its lines whose consignment's `logistics_status` is anything other than `CANCELLED`, and `unrouted_weight_grams` becomes its `weight_grams` minus that routed figure." "For the consignment, `staged_weight_grams` becomes the sum of `allocated_weight_grams` over its lines and `line_count` becomes the number of lines attached."

        Design: Difficulty/priority_pair_validation_conflict/channel_ineligible_food_outranks_expired_donation_window
        """
        site, consignment, spoil_entry, prep_entry = self._world()
        headers = make_site_sustainability_manager_headers(site["id"])

        for entry_id, grams in ((spoil_entry["id"], 800), (prep_entry["id"], 1000)):
            refused = api_client.create_consignment_line(
                factories.create_consignment_line_payload(consignment["id"], entry_id, grams),
                headers,
            )
            assert refused.status_code == 422

        lines, meta = validate_paginated(
            api_client.list_consignment_lines(headers, consignment_id=consignment["id"])
        )
        assert meta["total_count"] == 0
        assert lines == []

        stored_consignment = fixtures.read_consignment(consignment["id"])
        assert_consignment(stored_consignment)
        assert stored_consignment["line_count"] == 0
        assert stored_consignment["staged_weight_grams"] == 0

        stored_spoil = fixtures.read_entry(spoil_entry["id"])
        assert stored_spoil["routed_weight_grams"] == 0
        assert stored_spoil["unrouted_weight_grams"] == 800
        assert_waste_entry(stored_spoil)


class TestWrongSiteOutranksOverAllocation:
    """Grams from another kitchen are rejected as foreign before they are counted."""

    @staticmethod
    def _world():
        site_a = fixtures.create_site(name="Harbor Kitchen", site_code="HK-01", region_code="NE")
        site_b = fixtures.create_site(name="Westside Dining", site_code="WD-02", region_code="NE")
        station_a = fixtures.create_station(
            site_a["id"],
            station_code="PREP-1",
            station_kind="PREP",
            calibration_due_at=CALIBRATION_DUE_AT,
            capture_lock_seconds=30,
        )
        station_b = fixtures.create_station(
            site_b["id"],
            station_code="PREP-9",
            station_kind="PREP",
            calibration_due_at=CALIBRATION_DUE_AT,
            capture_lock_seconds=30,
        )
        food_type = _prepared_food_type()
        hauler = fixtures.create_hauler(
            name="Green Loop Compost",
            channels=["COMPOST"],
            rate_cents_per_tonne=52000,
            stop_fee_cents=1800,
            capacity_kg_per_pickup=500,
            max_concurrent_pickups=1,
        )
        shift_a = fixtures.open_shift(
            site_a["id"], shift_date="2026-06-10", shift_code="AM", meals_served=1000
        )
        shift_b = fixtures.open_shift(
            site_b["id"], shift_date="2026-06-10", shift_code="AM", meals_served=1000
        )
        entry_a = fixtures.capture_entry(
            station_a["id"],
            shift_a["id"],
            food_type["id"],
            weight_grams=1000,
            loss_reason="TRIM",
            captured_at="2026-06-10T10:00:00Z",
        )
        entry_b = fixtures.capture_entry(
            station_b["id"],
            shift_b["id"],
            food_type["id"],
            weight_grams=2000,
            loss_reason="TRIM",
            captured_at="2026-06-10T10:00:00Z",
        )
        consignment = fixtures.open_consignment(
            site_a["id"],
            hauler["id"],
            channel="COMPOST",
            pickup_window_start="2026-06-11T08:00:00Z",
            pickup_window_end="2026-06-11T10:00:00Z",
            container_tare_grams=0,
        )
        return consignment, entry_a, entry_b

    def test_routing_another_kitchens_capture_reports_the_aggregate_mismatch(self):
        """A neighbouring kitchen's tray, over-asked as well, is refused as the wrong kitchen's.

        PRD Coverage: "The capture's `site_id` must equal the consignment's `site_id`, refused otherwise with `ERR_ENTRY_SITE_MISMATCH`." "16. Same-aggregate referential consistency — `ERR_ENTRY_SITE_MISMATCH`, `ERR_TICKET_HAULER_MISMATCH`, or `ERR_DUPLICATE_SITE_IN_SCOPE`." "21. Allocation against remaining unrouted grams — `ERR_ALLOCATION_EXCEEDS_UNROUTED`." "When a single request violates several rules at once, exactly one error is returned — the one belonging to the earliest check in the following fixed evaluation order."

        Design: Difficulty/priority_pair_validation_conflict/entry_site_mismatch_outranks_allocation_exceeds_unrouted
        """
        consignment, _entry_a, entry_b = self._world()

        response = api_client.create_consignment_line(
            factories.create_consignment_line_payload(consignment["id"], entry_b["id"], 5000),
            make_shift_lead_headers("sl-1"),
        )
        validate_error(response, ApiErrorId.ENTRY_SITE_MISMATCH.value)
        assert response.status_code == 409

    def test_repairing_only_the_kitchen_surfaces_the_over_allocation(self):
        """With a home-kitchen tray, asking for more grams than it holds is the surviving fault.

        PRD Coverage: "Finally `allocated_weight_grams` must be at least 1 and no greater than the capture's current `unrouted_weight_grams`; over-allocation is refused with `ERR_ALLOCATION_EXCEEDS_UNROUTED`." "21. Allocation against remaining unrouted grams — `ERR_ALLOCATION_EXCEEDS_UNROUTED`."

        Design: Difficulty/priority_pair_validation_conflict/entry_site_mismatch_outranks_allocation_exceeds_unrouted
        """
        consignment, entry_a, entry_b = self._world()

        foreign = api_client.create_consignment_line(
            factories.create_consignment_line_payload(consignment["id"], entry_b["id"], 5000),
            make_shift_lead_headers("sl-1"),
        )
        validate_error(foreign, ApiErrorId.ENTRY_SITE_MISMATCH.value)

        over_allocated = api_client.create_consignment_line(
            factories.create_consignment_line_payload(consignment["id"], entry_a["id"], 1500),
            make_shift_lead_headers("sl-1"),
        )
        validate_error(over_allocated, ApiErrorId.ALLOCATION_EXCEEDS_UNROUTED.value)
        assert over_allocated.status_code == 422

    def test_both_captures_keep_every_gram_unrouted(self):
        """Neither refusal routes grams, at either kitchen, and the consignment stays empty.

        PRD Coverage: "Two conservation identities hold at all times and are the platform's primary integrity checks. First, for every capture, its `weight_grams` always equals `routed_weight_grams` plus `unrouted_weight_grams`." "For the consignment, `staged_weight_grams` becomes the sum of `allocated_weight_grams` over its lines and `line_count` becomes the number of lines attached."

        Design: Difficulty/priority_pair_validation_conflict/entry_site_mismatch_outranks_allocation_exceeds_unrouted
        """
        consignment, entry_a, entry_b = self._world()

        for entry_id, grams in ((entry_b["id"], 5000), (entry_a["id"], 1500)):
            refused = api_client.create_consignment_line(
                factories.create_consignment_line_payload(consignment["id"], entry_id, grams),
                make_shift_lead_headers("sl-1"),
            )
            assert refused.status_code in (409, 422)

        stored_a = fixtures.read_entry(entry_a["id"])
        assert stored_a["routed_weight_grams"] == 0
        assert stored_a["unrouted_weight_grams"] == 1000

        stored_b = fixtures.read_entry(entry_b["id"])
        assert stored_b["routed_weight_grams"] == 0
        assert stored_b["unrouted_weight_grams"] == 2000

        stored_consignment = fixtures.read_consignment(consignment["id"])
        assert stored_consignment["line_count"] == 0
        assert stored_consignment["staged_weight_grams"] == 0


class TestIntensityThresholdIsInclusiveAtTwelve:
    """One gram separates a quiet service period from a coached one."""

    @staticmethod
    def _world():
        site = fixtures.create_site(target_intensity_kg_per_1k_meals=10.000)
        station = fixtures.create_station(
            site["id"],
            station_code="PREP-1",
            station_kind="PREP",
            calibration_due_at=CALIBRATION_DUE_AT,
            capture_lock_seconds=30,
        )
        food_type = _prepared_food_type()
        shift = fixtures.open_shift(
            site["id"], shift_date="2026-06-10", shift_code="AM", meals_served=250
        )
        fixtures.capture_entry(
            station["id"],
            shift["id"],
            food_type["id"],
            weight_grams=1200,
            loss_reason="TRIM",
            captured_at="2026-06-10T10:00:00Z",
        )
        fixtures.capture_entry(
            station["id"],
            shift["id"],
            food_type["id"],
            weight_grams=1000,
            loss_reason="TRIM",
            captured_at="2026-06-10T10:05:00Z",
        )
        return site, station, food_type, shift

    def test_one_thousandth_below_the_ceiling_coaches_nobody(self):
        """2999 grams over 250 covers reads 11.996 and leaves the terminal silent.

        PRD Coverage: "`waste_intensity_kg_per_1k_meals`, which is `shift_waste_grams` divided by `meals_served` rounded half up to 3 decimal places" "When the period's recomputed `waste_intensity_kg_per_1k_meals` is not null and has reached 12.000 kilograms per thousand meals or more — the comparison is inclusive and is made against the already-3-decimal-rounded value, so exactly 12.000 fires it — and no coaching alert for this service period with `alert_type` `INTENSITY_BREACH` is currently in status `OPEN` or `ACKNOWLEDGED`, one alert is created with that `alert_type`." "`MONITORING` when the count is exactly 0"

        Design: Difficulty/boundary_precision_check/intensity_at_exactly_twelve_point_zero_zero_zero_fires_the_coaching_alert
        """
        site, station, food_type, shift = self._world()

        below = api_client.create_waste_entry(
            factories.create_waste_entry_payload(
                station["id"],
                shift["id"],
                food_type["id"],
                weight_grams=799,
                loss_reason="SPOILAGE",
                captured_at="2026-06-10T10:10:00Z",
            ),
            make_kitchen_staff_headers("ks-1"),
        )
        validate_success(below, 201)

        stored_shift = fixtures.read_shift(shift["id"])
        assert stored_shift["shift_waste_grams"] == 2999
        assert stored_shift["waste_intensity_kg_per_1k_meals"] == pytest.approx(11.996, abs=0.01)

        alerts, meta = validate_paginated(
            api_client.list_alerts(make_kitchen_staff_headers("ks-1"), shift_id=shift["id"])
        )
        assert meta["total_count"] == 0
        assert alerts == []

        stored_site = fixtures.read_site(site["id"])
        assert stored_site["open_alert_count"] == 0
        assert stored_site["coaching_posture"] == "MONITORING"
        assert_coaching_posture_ladder(stored_site)

    def test_a_single_gram_more_lands_exactly_on_twelve_and_raises_the_alert(self):
        """3000 grams over 250 covers is exactly 12.000, and the inclusive ceiling fires.

        PRD Coverage: "When the period's recomputed `waste_intensity_kg_per_1k_meals` is not null and has reached 12.000 kilograms per thousand meals or more — the comparison is inclusive and is made against the already-3-decimal-rounded value, so exactly 12.000 fires it — and no coaching alert for this service period with `alert_type` `INTENSITY_BREACH` is currently in status `OPEN` or `ACKNOWLEDGED`, one alert is created with that `alert_type`." "Its `observed_intensity` records the intensity value at the instant it was raised, to 3 decimal places, and its `severity` is `HIGH` when that observed intensity has reached 18.000 or more and `MEDIUM` otherwise." "Creating one increments the site's `open_alert_count` by 1 and recomputes `coaching_posture` from the new count." "`INTERVENTION` for every count in between"

        Design: Difficulty/boundary_precision_check/intensity_at_exactly_twelve_point_zero_zero_zero_fires_the_coaching_alert
        """
        site, station, food_type, shift = self._world()

        fixtures.capture_entry(
            station["id"],
            shift["id"],
            food_type["id"],
            weight_grams=799,
            loss_reason="SPOILAGE",
            captured_at="2026-06-10T10:10:00Z",
        )
        edge = api_client.create_waste_entry(
            factories.create_waste_entry_payload(
                station["id"],
                shift["id"],
                food_type["id"],
                weight_grams=1,
                loss_reason="SPOILAGE",
                captured_at="2026-06-10T10:15:00Z",
            ),
            make_kitchen_staff_headers("ks-1"),
        )
        edge_entry = get_success_data(edge, 201)

        stored_shift = fixtures.read_shift(shift["id"])
        assert stored_shift["shift_waste_grams"] == 3000
        assert stored_shift["waste_intensity_kg_per_1k_meals"] == pytest.approx(12.000, abs=0.01)

        alerts, meta = validate_paginated(
            api_client.list_alerts(make_kitchen_staff_headers("ks-1"), shift_id=shift["id"])
        )
        assert meta["total_count"] == 1
        alert = alerts[0]
        assert_coaching_alert(alert)
        assert alert["alert_type"] == "INTENSITY_BREACH"
        assert alert["status"] == "OPEN"
        assert alert["severity"] == "MEDIUM"
        assert alert["observed_intensity"] == pytest.approx(12.000, abs=0.01)
        assert alert["waste_entry_id"] == edge_entry["id"]

        stored_site = fixtures.read_site(site["id"])
        assert stored_site["open_alert_count"] == 1
        assert stored_site["coaching_posture"] == "INTERVENTION"
        assert_coaching_posture_ladder(stored_site)

    def test_a_further_breach_while_the_alert_is_open_raises_nothing_new(self):
        """The suppression is per period and per alert type, so the count stays at one.

        PRD Coverage: "The suppression condition in each rule is per service period and per alert type, so a second breach on the same period while the first alert is still open or merely acknowledged creates nothing."

        Design: Difficulty/boundary_precision_check/intensity_at_exactly_twelve_point_zero_zero_zero_fires_the_coaching_alert
        """
        site, station, food_type, shift = self._world()

        for weight, captured_at in ((799, "2026-06-10T10:10:00Z"), (1, "2026-06-10T10:15:00Z")):
            fixtures.capture_entry(
                station["id"],
                shift["id"],
                food_type["id"],
                weight_grams=weight,
                loss_reason="SPOILAGE",
                captured_at=captured_at,
            )
        fixtures.capture_entry(
            station["id"],
            shift["id"],
            food_type["id"],
            weight_grams=500,
            loss_reason="SPOILAGE",
            captured_at="2026-06-10T10:20:00Z",
        )

        _alerts, meta = validate_paginated(
            api_client.list_alerts(make_kitchen_staff_headers("ks-1"), shift_id=shift["id"])
        )
        assert meta["total_count"] == 1

        stored_site = fixtures.read_site(site["id"])
        assert stored_site["open_alert_count"] == 1
        assert stored_site["coaching_posture"] == "INTERVENTION"


class TestVarianceToleranceIsExclusiveAtFivePercent:
    """A scale disagreement of exactly five percent is tolerated; a hair more is credited."""

    @staticmethod
    def _dispatched_world():
        site = fixtures.create_site()
        station = fixtures.create_station(
            site["id"],
            station_code="PREP-1",
            station_kind="PREP",
            calibration_due_at=CALIBRATION_DUE_AT,
            capture_lock_seconds=30,
        )
        food_type = _prepared_food_type()
        hauler = fixtures.create_approved_hauler(
            name="Green Loop Compost",
            channels=["COMPOST"],
            rate_cents_per_tonne=52000,
            stop_fee_cents=1800,
            capacity_kg_per_pickup=500,
            max_concurrent_pickups=1,
        )
        shift = fixtures.open_shift(
            site["id"], shift_date="2026-06-10", shift_code="AM", meals_served=5000
        )
        entry_a = fixtures.capture_entry(
            station["id"],
            shift["id"],
            food_type["id"],
            weight_grams=120000,
            loss_reason="SPOILAGE",
            captured_at="2026-06-10T10:00:00Z",
        )
        entry_b = fixtures.capture_entry(
            station["id"],
            shift["id"],
            food_type["id"],
            weight_grams=120000,
            loss_reason="SPOILAGE",
            captured_at="2026-06-10T10:05:00Z",
        )
        consignment = fixtures.open_consignment(
            site["id"],
            hauler["id"],
            channel="COMPOST",
            pickup_window_start="2026-06-11T08:00:00Z",
            pickup_window_end="2026-06-11T10:00:00Z",
            container_tare_grams=2000,
        )
        fixtures.add_line(site["id"], consignment["id"], entry_a["id"], 120000)
        fixtures.add_line(site["id"], consignment["id"], entry_b["id"], 120000)
        staged = fixtures.stage_consignment(site["id"], consignment["id"])
        assert staged["staged_weight_grams"] == 240000
        fixtures.dispatch_consignment(site["id"], consignment["id"])
        return site, hauler, consignment

    def test_a_variance_of_exactly_five_percent_earns_no_credit(self):
        """A 252 kilogram net against a 240 kilogram load is 5.00 percent and is billed in full.

        PRD Coverage: "**Step one**: `net_weight_grams` is the submitted `gross_weight_grams` minus the consignment's `container_tare_grams`. **Step two**: `billable_tonnes` is those net grams divided by one million — the number of grams in a metric tonne — rounded half up to 4 decimal places. **Step three**: `base_haul_fee_cents` is `billable_tonnes` multiplied by the hauler's `rate_cents_per_tonne`, rounded half up to a whole number of cents, and then increased by the hauler's flat `stop_fee_cents`." "**Step six** measures the scale disagreement: `variance_pct` is the absolute difference between `net_weight_grams` and the consignment's frozen `staged_weight_grams`, divided by that `staged_weight_grams`, multiplied by 100 and rounded half up to 2 decimal places; `variance_credit_cents` is 10 percent of `settlement_subtotal_cents`, rounded half up to a whole number of cents, when `variance_pct` is **strictly greater** than a 5.00 percent tolerance, and 0 otherwise — a variance of exactly 5.00 percent earns no credit." "**Step seven**: `settlement_total_cents` is `settlement_subtotal_cents` minus `variance_credit_cents`."

        Design: Difficulty/boundary_precision_check/ticket_variance_at_exactly_five_percent_earns_no_credit_but_five_point_four_two_does
        """
        _site, hauler, consignment = self._dispatched_world()

        response = api_client.create_hauler_ticket(
            factories.create_hauler_ticket_payload(
                consignment["id"],
                254000,
                ticket_number="GLC-EDGE-1",
                ticket_date="2026-06-11",
            ),
            make_hauler_operator_headers(hauler["id"]),
        )
        ticket = get_success_data(response, 201)
        assert_hauler_ticket(ticket)
        assert_settlement_breakdown(
            ticket,
            net_weight_grams=252000,
            billable_tonnes=0.2520,
            base_haul_fee_cents=14904,
            fuel_surcharge_pct=0.06,
            fuel_surcharge_cents=894,
            settlement_subtotal_cents=15798,
            variance_pct=5.00,
            variance_credit_cents=0,
            settlement_total_cents=15798,
        )

    def test_a_variance_of_five_point_four_two_percent_earns_the_ten_percent_credit(self):
        """One extra kilogram on the hauler's scale pushes the disagreement past tolerance.

        PRD Coverage: "**Step six** measures the scale disagreement: `variance_pct` is the absolute difference between `net_weight_grams` and the consignment's frozen `staged_weight_grams`, divided by that `staged_weight_grams`, multiplied by 100 and rounded half up to 2 decimal places; `variance_credit_cents` is 10 percent of `settlement_subtotal_cents`, rounded half up to a whole number of cents, when `variance_pct` is **strictly greater** than a 5.00 percent tolerance, and 0 otherwise — a variance of exactly 5.00 percent earns no credit." "**Step four** selects the fuel surcharge tier **from `base_haul_fee_cents` alone**: `fuel_surcharge_pct` is 0.00 when the base fee is below 5000 cents, 0.06 when the base fee is at least 5000 cents and below 15000 cents, and 0.09 when the base fee has reached 15000 cents or more" "**Step seven**: `settlement_total_cents` is `settlement_subtotal_cents` minus `variance_credit_cents`."

        Design: Difficulty/boundary_precision_check/ticket_variance_at_exactly_five_percent_earns_no_credit_but_five_point_four_two_does
        """
        site, hauler, consignment = self._dispatched_world()

        edge_ticket = fixtures.submit_ticket(
            hauler["id"], consignment["id"], 254000, ticket_number="GLC-EDGE-1", ticket_date="2026-06-11"
        )
        fixtures.dispute_ticket(
            site["id"], edge_ticket["id"], dispute_note="reweigh requested by the site"
        )

        response = api_client.create_hauler_ticket(
            factories.create_hauler_ticket_payload(
                consignment["id"],
                255000,
                ticket_number="GLC-EDGE-2",
                ticket_date="2026-06-11",
            ),
            make_hauler_operator_headers(hauler["id"]),
        )
        replacement = get_success_data(response, 201)
        assert_hauler_ticket(replacement)
        assert_settlement_breakdown(
            replacement,
            net_weight_grams=253000,
            billable_tonnes=0.2530,
            base_haul_fee_cents=14956,
            fuel_surcharge_pct=0.06,
            fuel_surcharge_cents=897,
            settlement_subtotal_cents=15853,
            variance_pct=5.42,
            variance_credit_cents=1585,
            settlement_total_cents=14268,
        )

    def test_the_disputed_ticket_keeps_its_frozen_money_after_the_replacement(self):
        """The rejected ticket is never repriced when its successor is filed.

        PRD Coverage: "The disputed ticket itself stays `DISPUTED` forever; it is never reopened. Instead the hauler files a **replacement** ticket with a fresh `ticket_number` against the same consignment, which is permitted precisely because `settlement_status` is `DISPUTED`, and which returns the settlement dimension to `TICKET_SUBMITTED`."

        Design: Difficulty/boundary_precision_check/ticket_variance_at_exactly_five_percent_earns_no_credit_but_five_point_four_two_does
        """
        site, hauler, consignment = self._dispatched_world()

        edge_ticket = fixtures.submit_ticket(
            hauler["id"], consignment["id"], 254000, ticket_number="GLC-EDGE-1", ticket_date="2026-06-11"
        )
        fixtures.dispute_ticket(
            site["id"], edge_ticket["id"], dispute_note="reweigh requested by the site"
        )
        fixtures.submit_ticket(
            hauler["id"], consignment["id"], 255000, ticket_number="GLC-EDGE-2", ticket_date="2026-06-11"
        )

        stored = fixtures.read_ticket(edge_ticket["id"])
        assert stored["status"] == "DISPUTED"
        assert stored["settlement_total_cents"] == 15798
        assert stored["variance_credit_cents"] == 0
        assert stored["variance_pct"] == pytest.approx(5.00, abs=0.01)

        stored_consignment = fixtures.read_consignment(consignment["id"])
        assert stored_consignment["settlement_status"] == "TICKET_SUBMITTED"
        assert stored_consignment["logistics_status"] == "DISPATCHED"


class TestBaselineWindowEndpointsAndTheEmptySetGuard:
    """An empty measuring window is refused outright; a populated one stops at its last day."""

    @staticmethod
    def _world():
        site = fixtures.create_site()
        station = fixtures.create_station(
            site["id"],
            station_code="PREP-1",
            station_kind="PREP",
            calibration_due_at=CALIBRATION_DUE_AT,
            capture_lock_seconds=30,
        )
        food_type = _prepared_food_type()

        june_shift = fixtures.open_shift(
            site["id"], shift_date="2026-06-30", shift_code="AM", meals_served=100
        )
        fixtures.capture_entry(
            station["id"],
            june_shift["id"],
            food_type["id"],
            weight_grams=500,
            loss_reason="TRIM",
            captured_at="2026-06-30T23:30:00Z",
        )
        fixtures.close_shift(june_shift["id"])

        july_shift = fixtures.open_shift(
            site["id"], shift_date="2026-07-01", shift_code="AM", meals_served=100
        )
        fixtures.capture_entry(
            station["id"],
            july_shift["id"],
            food_type["id"],
            weight_grams=700,
            loss_reason="TRIM",
            captured_at="2026-07-01T00:30:00Z",
        )
        fixtures.close_shift(july_shift["id"])

        may_period = fixtures.open_baseline(
            site["id"], start_date="2026-05-01", end_date="2026-05-31"
        )
        june_period = fixtures.open_baseline(
            site["id"], start_date="2026-06-01", end_date="2026-06-30"
        )
        return site, may_period, june_period

    def test_a_window_with_no_captures_is_refused_rather_than_frozen_as_zeros(self):
        """A May window over a kitchen that only served in June cannot be measured.

        PRD Coverage: "requires at least one capture with status `RECORDED` or `FLAGGED` whose `captured_at` date falls inside the inclusive window at this site — a window with no data is refused with `ERR_BASELINE_NO_DATA`." "27. Empty-set guards — `ERR_BASELINE_NO_DATA` and `ERR_CONSIGNMENT_EMPTY`."

        Design: Difficulty/boundary_precision_check/baseline_empty_window_is_an_error_while_the_inclusive_end_date_captures_the_last_day
        """
        site, may_period, _june_period = self._world()

        response = api_client.submit_baseline_period(
            may_period["id"], make_site_sustainability_manager_headers(site["id"])
        )
        validate_error(response, ApiErrorId.BASELINE_NO_DATA.value)

        stored = fixtures.read_baseline(may_period["id"])
        assert stored["status"] == "OPEN"
        assert stored["baseline_entry_count"] == 0
        assert stored["baseline_waste_grams"] == 0
        assert stored["submitted_at"] is None

    def test_the_inclusive_end_date_captures_the_last_service_day(self):
        """A capture at half past eleven on the closing day is inside the June window.

        PRD Coverage: "The window is inclusive on both ends." "Over the qualifying capture set, `baseline_entry_count` is the number of captures, `baseline_waste_grams` is the sum of their `weight_grams`, `baseline_waste_kg` is those grams divided by 1000 and rounded half up to 3 decimal places, and `baseline_cost_cents` is the sum of their `effective_cost_cents`." "Submission stamps `submitted_at` with the current logical clock and increments `version` by 1."

        Design: Difficulty/boundary_precision_check/baseline_empty_window_is_an_error_while_the_inclusive_end_date_captures_the_last_day
        """
        site, _may_period, june_period = self._world()

        response = api_client.submit_baseline_period(
            june_period["id"], make_site_sustainability_manager_headers(site["id"])
        )
        submitted = get_success_data(response, 200)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["baseline_entry_count"] == 1
        assert submitted["baseline_waste_grams"] == 500
        assert submitted["baseline_waste_kg"] == pytest.approx(0.500, abs=0.01)
        assert submitted["baseline_cost_cents"] == 320
        _assert_instant(submitted["submitted_at"], CLOCK_INSTANT)

    def test_the_next_calendar_day_contributes_neither_grams_nor_covers(self):
        """The first of July is one day outside the window and stays outside it entirely.

        PRD Coverage: "Over a *different* set — the site's service periods whose status is `CLOSED` and whose `shift_date` falls inside the same inclusive window — `baseline_meals_served` is the sum of `meals_served`." "Finally `baseline_intensity_kg_per_1k_meals` is `baseline_waste_grams` divided by `baseline_meals_served`, rounded half up to 3 decimal places, and is null when `baseline_meals_served` is 0."

        Design: Difficulty/boundary_precision_check/baseline_empty_window_is_an_error_while_the_inclusive_end_date_captures_the_last_day
        """
        site, _may_period, june_period = self._world()

        submitted = fixtures.submit_baseline(site["id"], june_period["id"])
        assert submitted["baseline_meals_served"] == 100
        assert submitted["baseline_intensity_kg_per_1k_meals"] == pytest.approx(5.000, abs=0.01)
        assert submitted["baseline_waste_grams"] == 500, (
            "pulling the 2026-07-01 capture in would freeze 1200 grams"
        )
        assert submitted["baseline_entry_count"] == 1


class TestDonationShelfLifeIsInclusiveToTheSecond:
    """A donation pickup may begin at the last legal instant, but not one second later."""

    @staticmethod
    def _world():
        site = fixtures.create_site()
        station = fixtures.create_station(
            site["id"],
            station_code="PREP-1",
            station_kind="PREP",
            calibration_due_at=CALIBRATION_DUE_AT,
            capture_lock_seconds=30,
        )
        food_type = _prepared_food_type()
        hauler = fixtures.create_hauler(
            name="City Food Rescue",
            channels=["DONATION"],
            rate_cents_per_tonne=52000,
            stop_fee_cents=1800,
            capacity_kg_per_pickup=500,
            max_concurrent_pickups=3,
        )
        shift = fixtures.open_shift(
            site["id"], shift_date="2026-06-10", shift_code="AM", meals_served=1000
        )
        entry = fixtures.capture_entry(
            station["id"],
            shift["id"],
            food_type["id"],
            weight_grams=1000,
            loss_reason="OVERPRODUCTION",
            captured_at="2026-06-10T10:00:00Z",
        )
        edge_consignment = fixtures.open_consignment(
            site["id"],
            hauler["id"],
            channel="DONATION",
            pickup_window_start="2026-06-11T10:00:00Z",
            pickup_window_end="2026-06-11T12:00:00Z",
            container_tare_grams=0,
        )
        late_consignment = fixtures.open_consignment(
            site["id"],
            hauler["id"],
            channel="DONATION",
            pickup_window_start="2026-06-11T10:00:01Z",
            pickup_window_end="2026-06-11T12:00:00Z",
            container_tare_grams=0,
        )
        return site, shift, entry, edge_consignment, late_consignment

    def test_a_pickup_beginning_at_the_shelf_life_instant_is_accepted(self):
        """Twenty-four hours to the second after the weighing, the food may still be collected.

        PRD Coverage: "On a `DONATION` consignment the food must additionally still be inside its shelf life: the consignment's `pickup_window_start` must be no later than the capture's `captured_at` advanced by the food type's `donation_shelf_life_hours`, with that endpoint inclusive, and a later pickup start is refused with `ERR_DONATION_WINDOW_EXPIRED`." "For the affected capture, `routed_weight_grams` becomes the sum of `allocated_weight_grams` over all its lines whose consignment's `logistics_status` is anything other than `CANCELLED`, and `unrouted_weight_grams` becomes its `weight_grams` minus that routed figure."

        Design: Difficulty/boundary_precision_check/donation_shelf_life_endpoint_is_inclusive_to_the_second
        """
        site, _shift, entry, edge_consignment, _late_consignment = self._world()

        response = api_client.create_consignment_line(
            factories.create_consignment_line_payload(edge_consignment["id"], entry["id"], 400),
            make_site_sustainability_manager_headers(site["id"]),
        )
        line = get_success_data(response, 201)
        assert line["allocated_weight_grams"] == 400

        stored_entry = fixtures.read_entry(entry["id"])
        assert stored_entry["routed_weight_grams"] == 400
        assert stored_entry["unrouted_weight_grams"] == 600
        assert_waste_entry(stored_entry)

        stored_consignment = fixtures.read_consignment(edge_consignment["id"])
        assert stored_consignment["line_count"] == 1
        assert stored_consignment["staged_weight_grams"] == 400

    def test_a_pickup_one_second_later_is_refused_as_expired(self):
        """The same tray, the same grams, one second past its shelf life, is out of reach.

        PRD Coverage: "On a `DONATION` consignment the food must additionally still be inside its shelf life: the consignment's `pickup_window_start` must be no later than the capture's `captured_at` advanced by the food type's `donation_shelf_life_hours`, with that endpoint inclusive, and a later pickup start is refused with `ERR_DONATION_WINDOW_EXPIRED`." "Finally `allocated_weight_grams` must be at least 1 and no greater than the capture's current `unrouted_weight_grams`; over-allocation is refused with `ERR_ALLOCATION_EXCEEDS_UNROUTED`."

        Design: Difficulty/boundary_precision_check/donation_shelf_life_endpoint_is_inclusive_to_the_second
        """
        site, _shift, entry, edge_consignment, late_consignment = self._world()
        headers = make_site_sustainability_manager_headers(site["id"])

        fixtures.add_line(site["id"], edge_consignment["id"], entry["id"], 400)

        response = api_client.create_consignment_line(
            factories.create_consignment_line_payload(late_consignment["id"], entry["id"], 400),
            headers,
        )
        validate_error(response, ApiErrorId.DONATION_WINDOW_EXPIRED.value)

        stored_entry = fixtures.read_entry(entry["id"])
        assert stored_entry["routed_weight_grams"] == 400
        assert stored_entry["unrouted_weight_grams"] == 600

        stored_late = fixtures.read_consignment(late_consignment["id"])
        assert stored_late["line_count"] == 0
        assert stored_late["staged_weight_grams"] == 0

    def test_the_split_capture_stays_conserved_and_raises_no_coaching_alert(self):
        """Only the pickup start differs between the two calls, and the tray stays balanced.

        PRD Coverage: "A line names its `consignment_id`, the `waste_entry_id` whose weight is being routed, and the `allocated_weight_grams` being routed, which may be a partial slice of the capture — the same capture can be split across several consignments and channels." "The second rule watches single-drop overproduction: when the capture's `loss_reason` is `OVERPRODUCTION` and its `weight_grams` has reached five kilograms — 5000 grams, inclusive — and no alert for this service period with `alert_type` `OVERPRODUCTION_SPIKE` is currently `OPEN` or `ACKNOWLEDGED`, one alert is created with that `alert_type`, a `severity` of `MEDIUM` always, and a null `observed_intensity`."

        Design: Difficulty/boundary_precision_check/donation_shelf_life_endpoint_is_inclusive_to_the_second
        """
        site, shift, entry, edge_consignment, late_consignment = self._world()
        headers = make_site_sustainability_manager_headers(site["id"])

        fixtures.add_line(site["id"], edge_consignment["id"], entry["id"], 400)
        refused = api_client.create_consignment_line(
            factories.create_consignment_line_payload(late_consignment["id"], entry["id"], 400),
            headers,
        )
        validate_error(refused, ApiErrorId.DONATION_WINDOW_EXPIRED.value)

        stored_entry = fixtures.read_entry(entry["id"])
        assert_waste_entry(stored_entry)
        assert stored_entry["weight_grams"] == 400 + stored_entry["unrouted_weight_grams"]

        _alerts, meta = validate_paginated(
            api_client.list_alerts(make_shift_lead_headers("sl-1"), shift_id=shift["id"])
        )
        assert meta["total_count"] == 0
