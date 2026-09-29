"""Derived metric computation: intensity, valuation, diversion, baselines, attainment and rollups.

Every test in this module drives the service from an empty database through PRD-declared
endpoints only, then asserts the exact arithmetic the specification pins.
"""

import pytest

from test_helpers import (
    api_client,
    assert_baseline_period,
    assert_coaching_posture_ladder,
    assert_consignment,
    assert_corporate_rollup,
    assert_data_quality_finding,
    assert_effective_cost_selection,
    assert_gram_conservation,
    assert_reduction_target,
    assert_shift,
    assert_site,
    assert_timestamp_has_three_fractional_digits,
    assert_waste_entry,
    fixtures,
    make_corporate_lead_headers,
    make_hauler_operator_headers,
    make_kitchen_staff_headers,
    make_platform_admin_headers,
    make_shift_lead_headers,
    make_site_sustainability_manager_headers,
    validate_paginated,
    validate_success,
)


class TestShiftIntensityAndCompliance:
    """The service period's grams, intensity, pre-consumer share and station compliance."""

    def test_two_captures_sum_into_the_shift_intensity_at_full_compliance(self):
        """Two captures five minutes apart total 2500 g over 250 covers, an intensity of exactly 10.000.

        PRD Coverage: "The owning service period recomputes `shift_waste_grams`, the sum of `weight_grams` over its captures whose status is `RECORDED` or `FLAGGED`; `waste_intensity_kg_per_1k_meals`, which is `shift_waste_grams` divided by `meals_served` rounded half up to 3 decimal places — grams per meal is numerically identical to kilograms per thousand meals — and is null whenever `meals_served` is 0; `pre_consumer_share_pct`, which is the summed `weight_grams` of the `PRE_CONSUMER` members of that same set divided by `shift_waste_grams`, rounded half up to 4 decimal places, and null whenever `shift_waste_grams` is 0; and `capture_compliance_pct`, which is the number of distinct stations that reported on this period divided by the number of the site's `ACTIVE` stations, rounded half up to 4 decimal places, and fixed at 1.0000 when the site has no `ACTIVE` stations at all."
        PRD Coverage: "A newly opened period has `status` `OPEN` and a null `leaderboard_score`; `status` may only ever hold `OPEN` or `CLOSED`, and `closed_at` is null while `OPEN`."

        Design: Corner/calculations/shift_waste_intensity_sums_two_captures_and_reports_full_compliance
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        site = fixtures.create_site()
        station = fixtures.create_station(site["id"], station_code="PREP-1", station_kind="PREP")
        food_type = fixtures.create_food_type()
        shift = fixtures.open_shift(site["id"], shift_date="2026-08-01", shift_code="AM", meals_served=250)

        fixtures.capture_entry(
            station["id"], shift["id"], food_type["id"],
            weight_grams=1000, loss_reason="TRIM", captured_at="2026-08-01T10:00:00Z",
        )
        fixtures.capture_entry(
            station["id"], shift["id"], food_type["id"],
            weight_grams=1500, loss_reason="SPOILAGE", captured_at="2026-08-01T10:05:00Z",
        )

        read = validate_success(api_client.get_shift(shift["id"], make_shift_lead_headers("sl-1")), 200)
        assert_shift(read)
        assert read["shift_waste_grams"] == 2500
        assert read["waste_intensity_kg_per_1k_meals"] == pytest.approx(10.000, abs=0.0001)
        assert read["pre_consumer_share_pct"] == pytest.approx(1.0000, abs=0.0001)
        assert read["capture_compliance_pct"] == pytest.approx(1.0000, abs=0.0001)
        assert read["status"] == "OPEN"
        assert read["leaderboard_score"] is None

    def test_voiding_a_capture_removes_its_grams_from_the_intensity_input_set(self):
        """Voiding the 1500 g capture recomputes intensity from the 1000 g survivor alone.

        PRD Coverage: "In the first hop the capture's status becomes `VOIDED`, `void_reason` is stored, and the entry leaves every `RECORDED`-or-`FLAGGED` aggregation set. In the second hop, caused by that departure, the owning service period recomputes `shift_waste_grams`, `waste_intensity_kg_per_1k_meals`, `capture_compliance_pct` and `pre_consumer_share_pct` — and, when the period has already been closed, its `leaderboard_score` as well."
        PRD Coverage: "The reporting-station numerator deliberately counts distinct `station_id` values over captures of this period whose status is `RECORDED`, `FLAGGED` **or** `SUPERSEDED` — a superseded capture still proves the station reported — while `shift_waste_grams` and the pre-consumer share exclude both `VOIDED` and `SUPERSEDED` records."
        PRD Coverage: "`total_captured_weight_grams` is the sum of `weight_grams` over the site's captures whose status is either `RECORDED` or `FLAGGED`"

        Design: Corner/calculations/voided_capture_drops_out_of_the_shift_intensity_input_set
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        site = fixtures.create_site()
        station = fixtures.create_station(site["id"], station_code="PREP-1", station_kind="PREP")
        food_type = fixtures.create_food_type()
        shift = fixtures.open_shift(site["id"], shift_date="2026-08-01", shift_code="AM", meals_served=250)

        fixtures.capture_entry(
            station["id"], shift["id"], food_type["id"],
            weight_grams=1000, loss_reason="TRIM", captured_at="2026-08-01T10:00:00Z",
        )
        entry_b = fixtures.capture_entry(
            station["id"], shift["id"], food_type["id"],
            weight_grams=1500, loss_reason="SPOILAGE", captured_at="2026-08-01T10:05:00Z",
        )

        voided = validate_success(
            api_client.void_waste_entry(
                entry_b["id"], {"void_reason": "double weighed the same hotel pan"},
                make_shift_lead_headers("sl-1"),
            ),
            200,
        )
        assert voided["status"] == "VOIDED"

        read = validate_success(api_client.get_shift(shift["id"], make_shift_lead_headers("sl-1")), 200)
        assert_shift(read)
        assert read["shift_waste_grams"] == 1000
        assert read["waste_intensity_kg_per_1k_meals"] == pytest.approx(4.000, abs=0.0001)
        assert read["capture_compliance_pct"] == pytest.approx(1.0000, abs=0.0001)

        site_read = validate_success(
            api_client.get_site(site["id"], make_site_sustainability_manager_headers(site["id"])), 200
        )
        assert_site(site_read)
        assert site_read["total_captured_weight_grams"] == 1000

    def test_station_placement_decides_the_stream_and_feeds_the_pre_consumer_share(self):
        """The same EXPIRATION reason segments pre-consumer at PREP-1 and post-consumer at DISH-1.

        PRD Coverage: "Its `stream` is derived from placement and cause together: `POST_CONSUMER` when the station's `station_kind` is `DISH_RETURN` or when the `loss_reason` is `PLATE_WASTE`, and `PRE_CONSUMER` in every other case — which means a dish-return station always produces post-consumer records regardless of stated reason, and plate waste is post-consumer wherever it is weighed."
        PRD Coverage: "`EXPIRATION` and `CONTAMINATION` are accepted at any station kind."
        PRD Coverage: "`pre_consumer_share_pct`, which is the summed `weight_grams` of the `PRE_CONSUMER` members of that same set divided by `shift_waste_grams`, rounded half up to 4 decimal places, and null whenever `shift_waste_grams` is 0"

        Design: Corner/calculations/station_kind_propagates_into_the_entry_stream_and_the_pre_consumer_share
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        site = fixtures.create_site()
        prep_station = fixtures.create_station(site["id"], station_code="PREP-1", station_kind="PREP")
        dish_station = fixtures.create_station(site["id"], station_code="DISH-1", station_kind="DISH_RETURN")
        food_type = fixtures.create_food_type()
        shift = fixtures.open_shift(site["id"], shift_date="2026-08-01", shift_code="AM", meals_served=250)

        pre_entry = fixtures.capture_entry(
            prep_station["id"], shift["id"], food_type["id"],
            weight_grams=1000, loss_reason="EXPIRATION", captured_at="2026-08-01T10:00:00Z",
        )
        post_entry = fixtures.capture_entry(
            dish_station["id"], shift["id"], food_type["id"],
            weight_grams=1000, loss_reason="EXPIRATION", captured_at="2026-08-01T10:01:00Z",
        )

        pre_read = validate_success(
            api_client.get_waste_entry(pre_entry["id"], make_platform_admin_headers()), 200
        )
        post_read = validate_success(
            api_client.get_waste_entry(post_entry["id"], make_platform_admin_headers()), 200
        )
        assert_waste_entry(pre_read)
        assert_waste_entry(post_read)
        assert pre_read["stream"] == "PRE_CONSUMER"
        assert post_read["stream"] == "POST_CONSUMER"

        read = validate_success(api_client.get_shift(shift["id"], make_shift_lead_headers("sl-1")), 200)
        assert_shift(read)
        assert read["shift_waste_grams"] == 2000
        assert read["waste_intensity_kg_per_1k_meals"] == pytest.approx(8.000, abs=0.0001)
        assert read["pre_consumer_share_pct"] == pytest.approx(0.5000, abs=0.0001)
        assert read["capture_compliance_pct"] == pytest.approx(1.0000, abs=0.0001)


class TestCaptureValuation:
    """The catalog-basis provisional figure a capture is born with."""

    def test_provisional_cost_rounds_the_gram_to_cent_product_half_up(self):
        """1234 g at 640 cents per kilogram is 789.76 cents exactly, which must carry to 790.

        PRD Coverage: "Valuation at capture time uses the catalog basis only. The weight is converted to kilograms by dividing `weight_grams` by 1000, an exact decimal that is never rounded, and the cost is that kilogram figure multiplied by the chosen basis in cents per kilogram, rounded half up to a whole number of cents. `provisional_cost_cents` is that product taken against `catalog_cost_basis_cents`, ignoring recipe attribution entirely."
        PRD Coverage: "Wherever this document describes rounding, the method is **round half up**: a value exactly on the midpoint rounds away from zero to the larger magnitude."
        PRD Coverage: "`valued_waste_cost_cents` is the sum of `effective_cost_cents` over exactly that same set of captures"

        Design: Corner/calculations/provisional_valuation_rounds_the_gram_to_cent_product_half_up
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        site = fixtures.create_site()
        station = fixtures.create_station(site["id"], station_code="PREP-1", station_kind="PREP")
        food_type = fixtures.create_food_type(default_cost_per_kg_cents=640)
        shift = fixtures.open_shift(site["id"], shift_date="2026-08-01", shift_code="AM", meals_served=250)

        created = validate_success(
            api_client.create_waste_entry(
                {
                    "station_id": station["id"],
                    "shift_id": shift["id"],
                    "food_type_id": food_type["id"],
                    "weight_grams": 1234,
                    "loss_reason": "TRIM",
                    "captured_at": "2026-08-01T10:00:00Z",
                },
                make_kitchen_staff_headers("ks-1"),
            ),
            201,
        )
        assert_waste_entry(created)
        assert created["catalog_cost_basis_cents"] == 640
        assert created["provisional_cost_cents"] == 790
        assert created["effective_cost_cents"] == 790
        assert_effective_cost_selection(created)

        site_read = validate_success(
            api_client.get_site(site["id"], make_site_sustainability_manager_headers(site["id"])), 200
        )
        assert site_read["valued_waste_cost_cents"] == 790

    def test_capture_takes_the_catalog_provisional_figure_and_leaves_the_final_cost_null(self):
        """A recipe-attributed capture still values provisionally at catalog price while the period is OPEN.

        PRD Coverage: "Two valuation bases are snapshotted so that later catalog or recipe edits can never disturb the record: `catalog_cost_basis_cents` takes the food type's `default_cost_per_kg_cents`, and `recipe_cost_basis_cents` takes the recipe's `published_cost_per_kg_cents` when a `recipe_id` was supplied and is null otherwise."
        PRD Coverage: "`final_cost_cents` stays null while the owning service period is `OPEN`, and so does `valuation_delta_cents`. `effective_cost_cents` — the figure that actually feeds every site, baseline and rollup total — is `final_cost_cents` when that field is non-null and `provisional_cost_cents` otherwise, so at capture time it equals the provisional figure."
        PRD Coverage: "Rounding each line first gives 3003, 611 and 500 cents, summing to 4114 cents against a usable yield of 4.000 kilograms, which divides to 1028.5 and rounds to a `cost_per_kg_cents` of 1029."

        Design: Corner/calculations/capture_selects_the_catalog_provisional_variant_and_leaves_final_cost_null
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        site = fixtures.create_site()
        station = fixtures.create_station(site["id"], station_code="PREP-1", station_kind="PREP")
        food_type = fixtures.create_food_type(default_cost_per_kg_cents=640)
        recipe = fixtures.create_published_recipe(
            ingredients=[
                {"ingredient_name": "Chicken Breast", "quantity_kg": 2.5, "unit_cost_cents_per_kg": 1201, "trim_loss_pct": 0.20},
                {"ingredient_name": "Mirepoix", "quantity_kg": 1.5, "unit_cost_cents_per_kg": 407, "trim_loss_pct": 0.00},
                {"ingredient_name": "Demi Glace", "quantity_kg": 0.5, "unit_cost_cents_per_kg": 999, "trim_loss_pct": 0.00},
            ],
            recipe_code="BRZ-CHK",
            name="Braised Chicken",
        )
        assert recipe["published_cost_per_kg_cents"] == 1029
        shift = fixtures.open_shift(site["id"], shift_date="2026-08-01", shift_code="AM", meals_served=250)

        created = validate_success(
            api_client.create_waste_entry(
                {
                    "station_id": station["id"],
                    "shift_id": shift["id"],
                    "food_type_id": food_type["id"],
                    "weight_grams": 2450,
                    "loss_reason": "TRIM",
                    "recipe_id": recipe["id"],
                    "captured_at": "2026-08-01T10:00:00Z",
                },
                make_kitchen_staff_headers("ks-1"),
            ),
            201,
        )
        assert_waste_entry(created)
        assert created["catalog_cost_basis_cents"] == 640
        assert created["recipe_cost_basis_cents"] == 1029
        assert created["provisional_cost_cents"] == 1568
        assert created["final_cost_cents"] is None
        assert created["valuation_delta_cents"] is None
        assert created["effective_cost_cents"] == 1568
        assert_effective_cost_selection(created)

        site_read = validate_success(
            api_client.get_site(site["id"], make_site_sustainability_manager_headers(site["id"])), 200
        )
        assert site_read["valued_waste_cost_cents"] == 1568


class TestSiteDiversionLedger:
    """Routed grams and settled diverted grams are two deliberately different ledgers."""

    def test_dispatched_but_unsettled_grams_stay_out_of_the_site_diversion_rate(self):
        """400 g routed and physically collected still leave the settled diversion ledger at zero.

        PRD Coverage: "`diverted_weight_grams_settled` is the sum of `allocated_weight_grams` over the site's allocation lines whose consignment has reached `SETTLED` on the settlement dimension and has not been `CANCELLED` on the logistics dimension; `diversion_rate_pct` is the settled diverted grams divided by the total captured grams, multiplied by 100 and rounded half up to 2 decimal places, and is null whenever `total_captured_weight_grams` is 0"
        PRD Coverage: "For the affected capture, `routed_weight_grams` becomes the sum of `allocated_weight_grams` over all its lines whose consignment's `logistics_status` is anything other than `CANCELLED`, and `unrouted_weight_grams` becomes its `weight_grams` minus that routed figure."
        PRD Coverage: "On success `dispatched_at` is stamped with the current logical clock, the consignment becomes ticket-eligible on the settlement dimension, and `version` is incremented by 1."

        Design: Corner/calculations/site_diversion_rate_counts_only_settled_consignments
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        site = fixtures.create_site()
        station = fixtures.create_station(site["id"], station_code="PREP-1", station_kind="PREP")
        food_type = fixtures.create_food_type()
        shift = fixtures.open_shift(site["id"], shift_date="2026-08-01", shift_code="AM", meals_served=250)
        entry = fixtures.capture_entry(
            station["id"], shift["id"], food_type["id"],
            weight_grams=1000, loss_reason="TRIM", captured_at="2026-08-01T10:00:00Z",
        )
        hauler = fixtures.create_approved_hauler(
            name="Green Haul", channels=["COMPOST"], rate_cents_per_tonne=52000,
            stop_fee_cents=1800, capacity_kg_per_pickup=500,
        )
        consignment = fixtures.open_consignment(
            site["id"], hauler["id"], channel="COMPOST",
            pickup_window_start="2026-08-02T09:00:00Z", pickup_window_end="2026-08-02T11:00:00Z",
        )
        fixtures.add_line(site["id"], consignment["id"], entry["id"], 400)
        fixtures.stage_consignment(site["id"], consignment["id"])
        validate_success(
            api_client.dispatch_consignment(consignment["id"], make_hauler_operator_headers(hauler["id"])), 200
        )

        site_read = validate_success(
            api_client.get_site(site["id"], make_site_sustainability_manager_headers(site["id"])), 200
        )
        assert_site(site_read)
        assert site_read["total_captured_weight_grams"] == 1000
        assert site_read["diverted_weight_grams_settled"] == 0
        assert site_read["diversion_rate_pct"] == pytest.approx(0.00, abs=0.01)

        entry_read = validate_success(
            api_client.get_waste_entry(entry["id"], make_platform_admin_headers()), 200
        )
        assert entry_read["routed_weight_grams"] == 400
        assert entry_read["unrouted_weight_grams"] == 600
        assert_gram_conservation(entry_read)

        consignment_read = validate_success(
            api_client.get_consignment(consignment["id"], make_site_sustainability_manager_headers(site["id"])), 200
        )
        assert_consignment(consignment_read)
        assert consignment_read["logistics_status"] == "DISPATCHED"
        assert consignment_read["settlement_status"] == "UNBILLED"


class TestCoachingThresholds:
    """The single-drop overproduction constant and the intensity ceiling are both inclusive."""

    def test_a_4999_gram_overproduction_drop_raises_no_alert(self):
        """One gram below the five-kilogram constant, with an intensity of 4.999, leaves the site silent.

        PRD Coverage: "The second rule watches single-drop overproduction: when the capture's `loss_reason` is `OVERPRODUCTION` and its `weight_grams` has reached five kilograms — 5000 grams, inclusive — and no alert for this service period with `alert_type` `OVERPRODUCTION_SPIKE` is currently `OPEN` or `ACKNOWLEDGED`, one alert is created with that `alert_type`, a `severity` of `MEDIUM` always, and a null `observed_intensity`."
        PRD Coverage: "When the period's recomputed `waste_intensity_kg_per_1k_meals` is not null and has reached 12.000 kilograms per thousand meals or more — the comparison is inclusive and is made against the already-3-decimal-rounded value, so exactly 12.000 fires it — and no coaching alert for this service period with `alert_type` `INTENSITY_BREACH` is currently in status `OPEN` or `ACKNOWLEDGED`, one alert is created with that `alert_type`."
        PRD Coverage: "`coaching_posture` is derived purely from that count — `MONITORING` when the count is exactly 0, `ESCALATED` when the count is 3 or more, and `INTERVENTION` for every count in between."

        Design: Corner/calculations/overproduction_spike_stays_silent_one_gram_below_the_five_kilogram_constant
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        site = fixtures.create_site()
        station = fixtures.create_station(site["id"], station_code="PREP-1", station_kind="PREP")
        food_type = fixtures.create_food_type()
        shift = fixtures.open_shift(site["id"], shift_date="2026-08-01", shift_code="AM", meals_served=1000)

        created = validate_success(
            api_client.create_waste_entry(
                {
                    "station_id": station["id"],
                    "shift_id": shift["id"],
                    "food_type_id": food_type["id"],
                    "weight_grams": 4999,
                    "loss_reason": "OVERPRODUCTION",
                    "captured_at": "2026-08-01T10:00:00Z",
                },
                make_kitchen_staff_headers("ks-1"),
            ),
            201,
        )
        assert_waste_entry(created)

        shift_read = validate_success(api_client.get_shift(shift["id"], make_shift_lead_headers("sl-1")), 200)
        assert shift_read["waste_intensity_kg_per_1k_meals"] == pytest.approx(4.999, abs=0.0001)

        alerts, meta = validate_paginated(api_client.list_alerts(make_shift_lead_headers("sl-1"), shift_id=shift["id"]))
        assert meta["total_count"] == 0
        assert alerts == []

        site_read = validate_success(
            api_client.get_site(site["id"], make_site_sustainability_manager_headers(site["id"])), 200
        )
        assert site_read["open_alert_count"] == 0
        assert site_read["coaching_posture"] == "MONITORING"
        assert_coaching_posture_ladder(site_read)


class TestDataQualityScanning:
    """Findings are materialised in a type-pinned order and re-scanning respects live rows."""

    def test_the_scan_emits_the_missed_capture_before_the_weight_outlier(self):
        """The silent DISH-1 station's missed capture is created before the 25000 g outlier.

        PRD Coverage: "Three rules run, and their creation order is pinned: every `MISSED_CAPTURE` finding first, then every `DUPLICATE_ENTRY`, then every `WEIGHT_OUTLIER`. The row `id` is never used for ordering."
        PRD Coverage: "The `MISSED_CAPTURE` rule walks every pairing of an in-scope station with an in-scope shift, ordered by the station's `station_code` ascending and then by the shift's `shift_code` in the order `AM`, `PM`, `NIGHT`, and emits one finding for a pairing when no capture exists carrying that `station_id` and that `shift_id` with `status` `RECORDED`, `FLAGGED` or `SUPERSEDED` — a superseded capture still proves the station was used, so a corrected station is not also a missed one. The finding's `waste_entry_id` is null, because the defect is the absence of a row."
        PRD Coverage: "The `WEIGHT_OUTLIER` rule considers the captures of those shifts whose `status` is `RECORDED` or `FLAGGED` and whose `weight_grams` has reached 25000 grams or more, that boundary also inclusive, sorted by `captured_at` ascending and then `created_at` ascending."
        PRD Coverage: "A finding records the scanned `site_id`, the `station_id` and `shift_id` it is about, the offending `waste_entry_id` where one exists, the `finding_type` it came from, a human-readable `detail` explaining the detection, and a `detected_at` stamped with the logical clock instant of the scan."

        Design: Corner/calculations/data_quality_scan_emits_missed_capture_before_weight_outlier
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        site = fixtures.create_site()
        dish_station = fixtures.create_station(site["id"], station_code="DISH-1", station_kind="DISH_RETURN")
        prep_station = fixtures.create_station(site["id"], station_code="PREP-1", station_kind="PREP")
        food_type = fixtures.create_food_type()
        shift = fixtures.open_shift(site["id"], shift_date="2026-08-01", shift_code="AM", meals_served=1000)
        entry = fixtures.capture_entry(
            prep_station["id"], shift["id"], food_type["id"],
            weight_grams=25000, loss_reason="TRIM", captured_at="2026-08-01T10:00:00Z",
        )

        findings = validate_success(
            api_client.create_data_quality_scan(
                {"site_id": site["id"], "scan_date": "2026-08-01"},
                make_site_sustainability_manager_headers(site["id"]),
            ),
            200,
        )
        assert len(findings) == 2
        for finding in findings:
            assert_data_quality_finding(finding)
            assert finding["site_id"] == site["id"]
            assert finding["status"] == "OPEN"
            assert finding["detected_at"].startswith("2026-08-01T12:00:00")
            assert_timestamp_has_three_fractional_digits(finding["detected_at"])

        assert findings[0]["finding_type"] == "MISSED_CAPTURE"
        assert findings[0]["station_id"] == dish_station["id"]
        assert findings[0]["shift_id"] == shift["id"]
        assert findings[0]["waste_entry_id"] is None

        assert findings[1]["finding_type"] == "WEIGHT_OUTLIER"
        assert findings[1]["waste_entry_id"] == entry["id"]
        assert findings[1]["station_id"] == prep_station["id"]

    def test_a_second_scan_creates_nothing_while_the_same_findings_are_still_open(self):
        """The suppression tuple already holds two OPEN rows, so the re-scan returns an empty array.

        PRD Coverage: "Re-running a scan is idempotent, but only against live findings. A candidate is skipped when a finding already exists with `status` `OPEN` and an identical combination of `finding_type`, `site_id`, `station_id`, `shift_id` and `waste_entry_id`."
        PRD Coverage: "The scan answers with an array of exactly the findings it created, in creation order; a scan of a site that has no `ACTIVE` station and no shift on that date is still a success carrying an empty array, not an error."

        Design: Corner/calculations/rescanning_creates_nothing_while_the_same_findings_are_still_open
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        site = fixtures.create_site()
        fixtures.create_station(site["id"], station_code="DISH-1", station_kind="DISH_RETURN")
        prep_station = fixtures.create_station(site["id"], station_code="PREP-1", station_kind="PREP")
        food_type = fixtures.create_food_type()
        shift = fixtures.open_shift(site["id"], shift_date="2026-08-01", shift_code="AM", meals_served=1000)
        fixtures.capture_entry(
            prep_station["id"], shift["id"], food_type["id"],
            weight_grams=25000, loss_reason="TRIM", captured_at="2026-08-01T10:00:00Z",
        )
        first_pass = fixtures.run_scan(site["id"], "2026-08-01")
        assert len(first_pass) == 2

        second_pass = validate_success(
            api_client.create_data_quality_scan(
                {"site_id": site["id"], "scan_date": "2026-08-01"},
                make_site_sustainability_manager_headers(site["id"]),
            ),
            200,
        )
        assert second_pass == []

        stored, meta = validate_paginated(
            api_client.list_findings(make_site_sustainability_manager_headers(site["id"]), site_id=site["id"])
        )
        assert meta["total_count"] == 2
        assert len(stored) == 2


class TestAllocationWaterfall:
    """Each allocation line is checked against the capture's current unrouted remainder."""

    def test_the_second_consignment_takes_exactly_the_grams_the_first_left_behind(self):
        """400 g then 600 g out of one 1000 g capture drives the unrouted remainder to zero.

        PRD Coverage: "Finally `allocated_weight_grams` must be at least 1 and no greater than the capture's current `unrouted_weight_grams`; over-allocation is refused with `ERR_ALLOCATION_EXCEEDS_UNROUTED`."
        PRD Coverage: "Every line insertion and deletion re-derives four figures from the surviving source rows. For the affected capture, `routed_weight_grams` becomes the sum of `allocated_weight_grams` over all its lines whose consignment's `logistics_status` is anything other than `CANCELLED`, and `unrouted_weight_grams` becomes its `weight_grams` minus that routed figure. For the consignment, `staged_weight_grams` becomes the sum of `allocated_weight_grams` over its lines and `line_count` becomes the number of lines attached."
        PRD Coverage: "A line names its `consignment_id`, the `waste_entry_id` whose weight is being routed, and the `allocated_weight_grams` being routed, which may be a partial slice of the capture — the same capture can be split across several consignments and channels."

        Design: Corner/calculations/allocation_fills_the_first_consignment_before_the_second
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        site = fixtures.create_site()
        station = fixtures.create_station(site["id"], station_code="PREP-1", station_kind="PREP")
        food_type = fixtures.create_food_type()
        shift = fixtures.open_shift(site["id"], shift_date="2026-08-01", shift_code="AM", meals_served=250)
        entry = fixtures.capture_entry(
            station["id"], shift["id"], food_type["id"],
            weight_grams=1000, loss_reason="TRIM", captured_at="2026-08-01T10:00:00Z",
        )
        hauler = fixtures.create_approved_hauler(
            name="Green Haul", channels=["COMPOST"], rate_cents_per_tonne=52000,
            stop_fee_cents=1800, capacity_kg_per_pickup=500,
        )
        consignment_a = fixtures.open_consignment(
            site["id"], hauler["id"], channel="COMPOST",
            pickup_window_start="2026-08-02T09:00:00Z", pickup_window_end="2026-08-02T11:00:00Z",
        )
        consignment_b = fixtures.open_consignment(
            site["id"], hauler["id"], channel="COMPOST",
            pickup_window_start="2026-08-02T13:00:00Z", pickup_window_end="2026-08-02T15:00:00Z",
        )

        validate_success(
            api_client.create_consignment_line(
                {"consignment_id": consignment_a["id"], "waste_entry_id": entry["id"], "allocated_weight_grams": 400},
                make_site_sustainability_manager_headers(site["id"]),
            ),
            201,
        )
        after_first = validate_success(
            api_client.get_waste_entry(entry["id"], make_platform_admin_headers()), 200
        )
        assert after_first["routed_weight_grams"] == 400
        assert after_first["unrouted_weight_grams"] == 600
        assert_gram_conservation(after_first)

        validate_success(
            api_client.create_consignment_line(
                {"consignment_id": consignment_b["id"], "waste_entry_id": entry["id"], "allocated_weight_grams": 600},
                make_site_sustainability_manager_headers(site["id"]),
            ),
            201,
        )
        after_second = validate_success(
            api_client.get_waste_entry(entry["id"], make_platform_admin_headers()), 200
        )
        assert after_second["routed_weight_grams"] == 1000
        assert after_second["unrouted_weight_grams"] == 0
        assert_gram_conservation(after_second)

        read_a = validate_success(
            api_client.get_consignment(consignment_a["id"], make_site_sustainability_manager_headers(site["id"])), 200
        )
        read_b = validate_success(
            api_client.get_consignment(consignment_b["id"], make_site_sustainability_manager_headers(site["id"])), 200
        )
        assert read_a["staged_weight_grams"] == 400
        assert read_a["line_count"] == 1
        assert read_b["staged_weight_grams"] == 600
        assert read_b["line_count"] == 1


class TestBaselineMetrics:
    """The frozen baseline reads waste from every shift and meals only from closed ones."""

    def test_baseline_waste_includes_the_open_period_while_meals_come_only_from_the_closed_one(self):
        """1500 g over two periods but only the closed AM period's 250 covers, an intensity of 6.000.

        PRD Coverage: "Over the qualifying capture set, `baseline_entry_count` is the number of captures, `baseline_waste_grams` is the sum of their `weight_grams`, `baseline_waste_kg` is those grams divided by 1000 and rounded half up to 3 decimal places, and `baseline_cost_cents` is the sum of their `effective_cost_cents`. Over a *different* set — the site's service periods whose status is `CLOSED` and whose `shift_date` falls inside the same inclusive window — `baseline_meals_served` is the sum of `meals_served`. Only closed periods contribute meals; an `OPEN` period is excluded from the meals total even when its captures fall squarely inside the window, and those captures still count toward the waste total. Finally `baseline_intensity_kg_per_1k_meals` is `baseline_waste_grams` divided by `baseline_meals_served`, rounded half up to 3 decimal places, and is null when `baseline_meals_served` is 0. Submission stamps `submitted_at` with the current logical clock and increments `version` by 1."
        PRD Coverage: "Submission freezes the numbers. It advances `OPEN → SUBMITTED`, is refused with `ERR_INVALID_BASELINE_STATE` from any other status, and requires at least one capture with status `RECORDED` or `FLAGGED` whose `captured_at` date falls inside the inclusive window at this site — a window with no data is refused with `ERR_BASELINE_NO_DATA`."

        Design: Corner/calculations/baseline_metrics_take_waste_from_every_shift_but_meals_only_from_closed_ones
        """
        fixtures.set_clock("2026-08-01T20:00:00Z")
        site = fixtures.create_site()
        station = fixtures.create_station(site["id"], station_code="PREP-1", station_kind="PREP")
        food_type = fixtures.create_food_type(default_cost_per_kg_cents=640)
        am_shift = fixtures.open_shift(site["id"], shift_date="2026-08-01", shift_code="AM", meals_served=250)
        pm_shift = fixtures.open_shift(site["id"], shift_date="2026-08-01", shift_code="PM", meals_served=200)

        fixtures.capture_entry(
            station["id"], am_shift["id"], food_type["id"],
            weight_grams=1000, loss_reason="TRIM", captured_at="2026-08-01T10:00:00Z",
        )
        fixtures.capture_entry(
            station["id"], pm_shift["id"], food_type["id"],
            weight_grams=500, loss_reason="TRIM", captured_at="2026-08-01T18:00:00Z",
        )
        fixtures.close_shift(am_shift["id"])
        baseline = fixtures.open_baseline(site["id"], start_date="2026-08-01", end_date="2026-08-01")

        submitted = validate_success(
            api_client.submit_baseline_period(
                baseline["id"], make_site_sustainability_manager_headers(site["id"])
            ),
            200,
        )
        assert_baseline_period(submitted)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_at"].startswith("2026-08-01T20:00:00")
        assert_timestamp_has_three_fractional_digits(submitted["submitted_at"])
        assert submitted["baseline_entry_count"] == 2
        assert submitted["baseline_waste_grams"] == 1500
        assert submitted["baseline_waste_kg"] == pytest.approx(1.500, abs=0.0001)
        assert submitted["baseline_meals_served"] == 250
        assert submitted["baseline_intensity_kg_per_1k_meals"] == pytest.approx(6.000, abs=0.0001)
        assert submitted["baseline_cost_cents"] == 960

        still_open = validate_success(api_client.get_shift(pm_shift["id"], make_shift_lead_headers("sl-1")), 200)
        assert still_open["status"] == "OPEN"


class TestReductionAttainment:
    """The comparison against the configured reduction percentage is inclusive at equality."""

    def test_a_reduction_of_exactly_the_target_percentage_counts_as_achieved_pending(self):
        """900 g against a frozen 1000 g baseline is exactly 10.00 percent, which attains at equality.

        PRD Coverage: "`absolute_reduction_pct` is the baseline grams minus the performance grams, divided by the baseline grams, multiplied by 100 and rounded half up to 2 decimal places; it is null when the frozen `baseline_waste_grams` is 0. `intensity_reduction_pct` is the frozen baseline intensity minus the performance intensity, divided by the frozen baseline intensity, multiplied by 100 and rounded half up to 2 decimal places; it is null whenever either intensity is null. `effective_reduction_pct` is the absolute figure when `basis` is `ABSOLUTE` and the intensity figure when `basis` is `INTENSITY`."
        PRD Coverage: "`attainment_state` then holds `ACHIEVED_PENDING` when three conditions all hold — `effective_reduction_pct` is not null, it has reached `target_reduction_pct` or more with the comparison inclusive, and the diversion floor is satisfied — and `BEHIND` in every other case. The diversion floor reads the site's live `diversion_rate_pct`, with a null value read as 0.00, and is satisfied when that value has reached `min_diversion_rate_pct` or more."
        PRD Coverage: "Over captures at the target's site with status `RECORDED` or `FLAGGED` whose `captured_at` date falls inside the inclusive performance window, `performance_waste_grams` is the sum of `weight_grams`. Over the site's `CLOSED` service periods whose `shift_date` falls inside that same inclusive window, `performance_meals_served` is the sum of `meals_served`. `performance_intensity_kg_per_1k_meals` is the performance grams divided by the performance meals, rounded half up to 3 decimal places, and is null when the meals figure is 0."

        Design: Corner/calculations/attainment_at_exactly_the_target_percentage_counts_as_achieved_pending
        """
        fixtures.set_clock("2026-08-01T20:00:00Z")
        site = fixtures.create_site()
        station = fixtures.create_station(site["id"], station_code="PREP-1", station_kind="PREP")
        food_type = fixtures.create_food_type(default_cost_per_kg_cents=640)
        base_shift = fixtures.open_shift(site["id"], shift_date="2026-08-01", shift_code="AM", meals_served=250)
        fixtures.capture_entry(
            station["id"], base_shift["id"], food_type["id"],
            weight_grams=1000, loss_reason="TRIM", captured_at="2026-08-01T10:00:00Z",
        )
        fixtures.close_shift(base_shift["id"])
        baseline = fixtures.open_baseline(site["id"], start_date="2026-08-01", end_date="2026-08-01")
        fixtures.submit_baseline(site["id"], baseline["id"])
        fixtures.certify_baseline(baseline["id"])

        site_snapshot = validate_success(
            api_client.get_site(site["id"], make_corporate_lead_headers("csl-1")), 200
        )
        target = fixtures.propose_target(
            site["id"], baseline["id"], site_snapshot["version"],
            basis="ABSOLUTE", target_reduction_pct=10.00,
            window_start="2026-08-02", window_end="2026-08-31",
        )
        fixtures.activate_target(target["id"])

        fixtures.set_clock("2026-08-02T20:00:00Z")
        perf_shift = fixtures.open_shift(site["id"], shift_date="2026-08-02", shift_code="AM", meals_served=250)
        fixtures.capture_entry(
            station["id"], perf_shift["id"], food_type["id"],
            weight_grams=900, loss_reason="TRIM", captured_at="2026-08-02T10:00:00Z",
        )
        fixtures.close_shift(perf_shift["id"])

        attainment = validate_success(
            api_client.get_target_attainment(target["id"], make_corporate_lead_headers("csl-1")), 200
        )
        assert attainment["target_id"] == target["id"]
        assert attainment["basis"] == "ABSOLUTE"
        assert attainment["baseline_waste_grams"] == 1000
        assert attainment["baseline_intensity_kg_per_1k_meals"] == pytest.approx(4.000, abs=0.0001)
        assert attainment["performance_waste_grams"] == 900
        assert attainment["performance_meals_served"] == 250
        assert attainment["performance_intensity_kg_per_1k_meals"] == pytest.approx(3.600, abs=0.0001)
        assert attainment["absolute_reduction_pct"] == pytest.approx(10.00, abs=0.01)
        assert attainment["intensity_reduction_pct"] == pytest.approx(10.00, abs=0.01)
        assert attainment["effective_reduction_pct"] == pytest.approx(10.00, abs=0.01)
        assert attainment["target_reduction_pct"] == pytest.approx(10.00, abs=0.01)
        assert attainment["min_diversion_rate_pct"] == pytest.approx(0.00, abs=0.01)
        assert attainment["site_diversion_rate_pct"] == pytest.approx(0.00, abs=0.01)
        assert attainment["attainment_state"] == "ACHIEVED_PENDING"

        target_read = validate_success(
            api_client.get_reduction_target(target["id"], make_corporate_lead_headers("csl-1")), 200
        )
        assert_reduction_target(target_read)
        assert target_read["status"] == "ACTIVE"
        assert target_read["attainment_state"] == "ACHIEVED_PENDING"


class TestCorporateRollupMetrics:
    """Preparation computes every rollup figure over exactly the listed sites and dated period."""

    def test_a_single_site_draft_rollup_computes_all_seven_figures(self):
        """One 1000 g capture worth 640 cents, no diversion and no live target: NONE_ON_TRACK.

        PRD Coverage: "`in_scope_site_count` is the length of `site_ids`. The capture set for the period is every capture belonging to an in-scope site whose `status` is `RECORDED` or `FLAGGED` and whose `captured_at` falls on a calendar date within the inclusive period; `total_captured_weight_grams` is the sum of `weight_grams` over that set and `total_valued_cost_cents` is the sum of `effective_cost_cents` over that same set, so the cost figure automatically reflects whichever shifts have closed and re-valued and whichever have not."
        PRD Coverage: "`diversion_rate_pct` is `total_diverted_weight_grams` divided by `total_captured_weight_grams`, multiplied by 100 and rounded half up to 2 decimal places, and is null when the captured denominator is 0."
        PRD Coverage: "`sites_on_track_count` is the number of in-scope sites holding at least one reduction target whose `status` is `ACTIVE` **and** whose `attainment_state` is `ACHIEVED_PENDING`."
        PRD Coverage: "From that count, `goal_attainment_state` is `ALL_ON_TRACK` when `sites_on_track_count` equals `in_scope_site_count`, `NONE_ON_TRACK` when `sites_on_track_count` is 0, and `PARTIAL` in every other case."
        PRD Coverage: "The rollup's `status` begins at `DRAFT`, which may only ever hold `DRAFT` or `PUBLISHED`, `prepared_by_user_id` is stamped with the acting `X-User-ID` — the value that segregation of duties will later be measured against — and `published_by_user_id`, `published_at` and `published_metrics` are all null."

        Design: Corner/calculations/corporate_rollup_computes_its_draft_metrics_over_one_site
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        site = fixtures.create_site()
        station = fixtures.create_station(site["id"], station_code="PREP-1", station_kind="PREP")
        food_type = fixtures.create_food_type(default_cost_per_kg_cents=640)
        shift = fixtures.open_shift(site["id"], shift_date="2026-08-01", shift_code="AM", meals_served=250)
        fixtures.capture_entry(
            station["id"], shift["id"], food_type["id"],
            weight_grams=1000, loss_reason="TRIM", captured_at="2026-08-01T10:00:00Z",
        )

        rollup = validate_success(
            api_client.create_rollup(
                {"period_start": "2026-08-01", "period_end": "2026-08-01", "site_ids": [site["id"]]},
                make_corporate_lead_headers("csl-1"),
            ),
            201,
        )
        assert_corporate_rollup(rollup)
        assert rollup["status"] == "DRAFT"
        assert rollup["prepared_by_user_id"] == "csl-1"
        assert rollup["published_by_user_id"] is None
        assert rollup["published_at"] is None
        assert rollup["published_metrics"] is None
        assert rollup["in_scope_site_count"] == 1
        assert rollup["total_captured_weight_grams"] == 1000
        assert rollup["total_valued_cost_cents"] == 640
        assert rollup["total_diverted_weight_grams"] == 0
        assert rollup["diversion_rate_pct"] == pytest.approx(0.00, abs=0.01)
        assert rollup["sites_on_track_count"] == 0
        assert rollup["goal_attainment_state"] == "NONE_ON_TRACK"

    def test_a_capture_on_the_following_day_falls_outside_the_rollup_period(self):
        """A single-day period of 2026-08-01 counts the 1000 g capture and ignores the 2000 g one.

        PRD Coverage: "The capture set for the period is every capture belonging to an in-scope site whose `status` is `RECORDED` or `FLAGGED` and whose `captured_at` falls on a calendar date within the inclusive period; `total_captured_weight_grams` is the sum of `weight_grams` over that set and `total_valued_cost_cents` is the sum of `effective_cost_cents` over that same set, so the cost figure automatically reflects whichever shifts have closed and re-valued and whichever have not."
        PRD Coverage: "Note the deliberate asymmetry in how the two sides are dated: captures are dated by when the food was weighed, and diversions by when the pickup window opened, so a haul settled long after the period still counts in the period whose window it belonged to."
        PRD Coverage: "`total_captured_weight_grams` is the sum of `weight_grams` over the site's captures whose status is either `RECORDED` or `FLAGGED`"

        Design: Corner/calculations/rollup_period_bounds_exclude_a_capture_from_the_following_day
        """
        fixtures.set_clock("2026-08-01T12:00:00Z")
        site = fixtures.create_site()
        station = fixtures.create_station(site["id"], station_code="PREP-1", station_kind="PREP")
        food_type = fixtures.create_food_type(default_cost_per_kg_cents=640)
        day1_shift = fixtures.open_shift(site["id"], shift_date="2026-08-01", shift_code="AM", meals_served=250)
        fixtures.capture_entry(
            station["id"], day1_shift["id"], food_type["id"],
            weight_grams=1000, loss_reason="TRIM", captured_at="2026-08-01T10:00:00Z",
        )

        fixtures.set_clock("2026-08-02T12:00:00Z")
        day2_shift = fixtures.open_shift(site["id"], shift_date="2026-08-02", shift_code="AM", meals_served=250)
        fixtures.capture_entry(
            station["id"], day2_shift["id"], food_type["id"],
            weight_grams=2000, loss_reason="TRIM", captured_at="2026-08-02T10:00:00Z",
        )

        rollup = validate_success(
            api_client.create_rollup(
                {"period_start": "2026-08-01", "period_end": "2026-08-01", "site_ids": [site["id"]]},
                make_corporate_lead_headers("csl-1"),
            ),
            201,
        )
        assert_corporate_rollup(rollup)
        assert rollup["total_captured_weight_grams"] == 1000
        assert rollup["total_valued_cost_cents"] == 640

        site_read = validate_success(
            api_client.get_site(site["id"], make_site_sustainability_manager_headers(site["id"])), 200
        )
        assert site_read["total_captured_weight_grams"] == 3000

        entries, meta = validate_paginated(
            api_client.list_waste_entries(make_platform_admin_headers(), site_id=site["id"])
        )
        assert meta["total_count"] == 2
        assert len(entries) == 2
