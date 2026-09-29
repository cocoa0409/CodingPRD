"""
Values sitting exactly on a declared threshold.

An index of exactly 70.00 is healthy, and a track loaded to exactly its spot
capacity is accepted; one hundredth or one railcar the other way changes the
outcome.
"""

from test_helpers import fixtures as fx
from test_helpers import get_success_data, validate_error, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_2dp, assert_3dp
from test_helpers.test_users import LOGISTICS_COORDINATOR, PROCESS_OPERATOR


def _batch_at_exactly_seventy(api):
    """FB-5001 whose three reading scores weight to exactly 70.00."""
    fx.commission_plant(
        api,
        base_grind_cap_bushels=120000,
        coverage_floor_bushels=5000,
        baseline_ci_g_per_mj=60.0,
        rin_generation_enabled=True,
    )
    fx.advance_clock(api, "2026-09-01T00:00:00Z")
    tank = fx.commission_tank(api, "T-101", "ETHANOL_200_PROOF", 1000000.00, opening_gallons=0.00)
    contract = fx.priced_contract(api, 458.0, supplier_name="Cedar Ridge Elevator")
    fx.settled_load(api, contract["id"])
    batch = fx.charge_batch(
        api,
        tank["id"],
        batch_code="FB-5001",
        corn_bushels_charged=900.00,
        charge_test_weight_lb_per_bu=54.0,
    )
    scores = []
    for hours, lactic, acetic, temperature in (
        (12, 1367, 322, 35.0),
        (24, 870, 443, 29.0),
        (36, 1262, 421, 33.0),
    ):
        reading = fx.append_health_reading(
            api, batch["id"], hours_elapsed=hours, lactic_acid_ppm=lactic,
            acetic_acid_ppm=acetic, temperature_c=temperature,
        )
        scores.append(reading["reading_score"])
    return {"batch": batch, "scores": scores}


def _track_filled_to_capacity(api):
    """TRK-A carrying 60 + 50 railcars in overlapping windows, exactly its 110 spots."""
    fx.commission_plant(
        api,
        base_grind_cap_bushels=120000,
        coverage_floor_bushels=5000,
        baseline_ci_g_per_mj=60.0,
        rin_generation_enabled=True,
    )
    fx.advance_clock(api, "2026-09-05T05:00:00Z")
    tank = fx.commission_tank(
        api, "T-301", "DENATURED_E100", 1000000.00,
        opening_gallons=900000.00, settling_buffer_minutes=120,
    )
    track = fx.commission_track(api, loading_rate_cars_per_hour=20.0, is_active=True)
    first = fx.schedule_shipment(
        api, track["id"], tank["id"], track["version"],
        shipment_code="UT-9001", destination_terminal="Chicago Rail Terminal",
        railcar_count=60, gallons_per_railcar=2659.00,
        window_start="2026-09-05T06:00:00Z", window_end="2026-09-05T12:00:00Z",
        price_cents_per_gallon=181.50,
    )
    reread = get_success_data(api.get_track(track["id"], LOGISTICS_COORDINATOR))
    second = fx.schedule_shipment(
        api, track["id"], tank["id"], reread["version"],
        shipment_code="UT-9002", destination_terminal="Kansas City Terminal",
        railcar_count=50, gallons_per_railcar=2659.00,
        window_start="2026-09-05T08:00:00Z", window_end="2026-09-05T14:00:00Z",
        price_cents_per_gallon=181.50,
    )
    return {"tank": tank, "track": track, "first": first, "second": second}


class TestHealthIndexExactlyAtSeventy:
    """Seventy on the nose is healthy, and the yield ladder still charges for it."""

    def test_an_index_of_exactly_seventy_leaves_the_batch_fermenting(self, api):
        """68.49, 71.48 and 71.57 weight to exactly 70.00, which is not health watch.

        PRD 3.4: "From `FERMENTING`, an appended reading keeping the index at or
        above 70.00 is a `FERMENTING → FERMENTING` self-transition — not a no-op,
        because the appended reading changes the three-reading window and
        therefore the yield the batch will realise — while an index strictly
        below 70.00 moves it `FERMENTING → HEALTH_WATCH`."

        Design: Difficulty/boundary_precision_check/health_index_exactly_seventy_stays_fermenting
        """
        scenario = _batch_at_exactly_seventy(api)
        assert_2dp(scenario["scores"][0], 71.57, "reading_score")
        assert_2dp(scenario["scores"][1], 71.48, "reading_score")
        assert_2dp(scenario["scores"][2], 68.49, "reading_score")

        batch = get_success_data(api.get_batch(scenario["batch"]["id"], PROCESS_OPERATOR))
        assert_2dp(batch["fermentation_health_index"], 70.00, "fermentation_health_index")
        assert batch["status"] == "FERMENTING", batch["status"]

    def test_the_boundary_index_still_costs_the_middle_health_penalty_at_distillation(self, api):
        """An index of 70.00 sits in the 60.00-to-75.00 tier, so the yield is 2.700.

        PRD 3.4: "Second, `health_penalty_gal_per_bushel` is a descending tier
        ladder on `fermentation_health_index`: 0.000 at an index of 90.00 or
        above, 0.050 at an index of at least 75.00 but below 90.00, 0.150 at an
        index of at least 60.00 but below 75.00, and 0.300 below 60.00."

        Design: Difficulty/boundary_precision_check/health_index_exactly_seventy_stays_fermenting
        """
        scenario = _batch_at_exactly_seventy(api)

        distilling = validate_success(
            api.distill_batch(scenario["batch"]["id"], PROCESS_OPERATOR), 200
        )
        assert distilling["status"] == "DISTILLING", distilling["status"]
        assert_3dp(distilling["starch_bonus_gal_per_bushel"], 0.000, "starch_bonus_gal_per_bushel")
        assert_3dp(distilling["health_penalty_gal_per_bushel"], 0.150, "health_penalty_gal_per_bushel")
        assert_3dp(
            distilling["effective_yield_gal_per_bushel"], 2.700, "effective_yield_gal_per_bushel"
        )


class TestTrackExactlyAtSpotCapacity:
    """One hundred and ten committed railcars of one hundred and ten spots."""

    def test_two_overlapping_trains_summing_to_capacity_are_both_accepted(self, api):
        """The aggregate bound is inclusive, so landing exactly on capacity stands.

        PRD 3.6: "Capacity is then judged in the aggregate rather than
        exclusively: sum the `railcar_count` of every shipment on the same track
        whose `loading_status` is `SCHEDULED`, `BLOCKED` or `LOADED` and whose
        window overlaps the candidate's, add the candidate's own `railcar_count`,
        and accept the schedule when that total is **at most** the track's
        `spot_capacity` — the bound is inclusive, so landing exactly on capacity
        is accepted."

        Design: Difficulty/boundary_precision_check/track_committed_railcars_exactly_at_spot_capacity_is_accepted
        """
        scenario = _track_filled_to_capacity(api)

        assert scenario["first"]["loading_status"] == "SCHEDULED", scenario["first"]["loading_status"]
        assert scenario["second"]["loading_status"] == "SCHEDULED", scenario["second"]["loading_status"]

        track = get_success_data(api.get_track(scenario["track"]["id"], LOGISTICS_COORDINATOR))
        assert track["committed_railcars"] == 110, track["committed_railcars"]
        assert track["spot_capacity"] == 110, track["spot_capacity"]

    def test_one_further_railcar_in_an_overlapping_window_is_refused(self, api):
        """A single extra car takes the overlap to 111 and the schedule is rejected.

        PRD 3.6: "Exceeding it is refused with `ERR_TRACK_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/track_committed_railcars_exactly_at_spot_capacity_is_accepted
        """
        scenario = _track_filled_to_capacity(api)
        before = get_success_data(api.get_track(scenario["track"]["id"], LOGISTICS_COORDINATOR))

        validate_error(
            api.create_shipment(
                {
                    "shipment_code": "UT-9003",
                    "track_id": scenario["track"]["id"],
                    "expected_track_version": before["version"],
                    "source_tank_id": scenario["tank"]["id"],
                    "destination_terminal": "Omaha Terminal",
                    "railcar_count": 1,
                    "gallons_per_railcar": 2659.00,
                    "window_start": "2026-09-05T09:00:00Z",
                    "window_end": "2026-09-05T10:00:00Z",
                    "price_cents_per_gallon": 181.50,
                },
                LOGISTICS_COORDINATOR,
            ),
            ApiErrorId.TRACK_CAPACITY_EXCEEDED,
            422,
        )

        after = get_success_data(api.get_track(scenario["track"]["id"], LOGISTICS_COORDINATOR))
        assert after["committed_railcars"] == 110, after["committed_railcars"]
        assert after["version"] == before["version"], (
            "a refused schedule must not increment the track version"
        )
