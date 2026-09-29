"""Stale-version proofs on the two guarded parent aggregates and the immediacy of every derived field.

Both version guards are plain stale-version comparisons against a parent's current
`version` integer, so every test here drives its calls strictly in sequence. Each
test builds its own world from an empty database through the public API only,
because the harness restarts the service before each test with the logical clock
back at its process-start value.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_coaching_posture_ladder,
    assert_reduction_target,
    assert_shift,
    assert_site,
    assert_site_cost_ledger,
    assert_version_bumped_by,
    assert_waste_entry,
    factories,
    fixtures,
    make_shift_lead_headers,
    make_site_sustainability_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

WORKING_CLOCK = "2026-08-01T12:00:00Z"
MORNING_CAPTURE_AT = "2026-08-01T10:00:00Z"
MID_MORNING_CAPTURE_AT = "2026-08-01T10:10:00Z"
LATE_MORNING_CAPTURE_AT = "2026-08-01T10:30:00Z"
NEAR_NOON_CAPTURE_AT = "2026-08-01T11:00:00Z"


def _kitchen_with_open_am_shift():
    """Harbor Kitchen with one ACTIVE PREP station, one catalog food type and an OPEN AM period."""
    fixtures.set_clock(WORKING_CLOCK)
    return fixtures.site_with_open_shift()


def _kitchen_with_a_superseded_capture():
    """A 1000 g capture by a cook, superseded by an accepted 800 g correction."""
    world = _kitchen_with_open_am_shift()
    world["entry_a"] = fixtures.capture_entry(
        world["station"]["id"],
        world["shift"]["id"],
        world["food_type"]["id"],
        weight_grams=1000,
        loss_reason="TRIM",
        captured_at=MORNING_CAPTURE_AT,
    )
    world["entry_b"] = fixtures.correct_entry(
        world["entry_a"]["id"],
        world["entry_a"]["version"],
        weight_grams=800,
        correction_note="scale reweighed to 800 g",
    )
    return world


class TestCorrectionUnderEntryVersionGuard:
    """A corrector must prove it has seen the version of the capture it is superseding."""

    def test_a_corrector_quoting_the_pre_correction_version_is_refused_with_stale_entry_version(self, api):
        """A second lead still holding the capture's pre-correction version is refused at 412.

        PRD Coverage: "Creating a correcting waste entry against an existing capture requires the request to carry `expected_entry_version`, holding the client's last observed `version` of the `WasteEntry` being corrected. If that value does not equal the entry's current `version`, the request is rejected with `ERR_STALE_ENTRY_VERSION` and HTTP status 412. The field is not optional." "Because the optimistic-concurrency check sits at step 10, a correction request carrying a stale `expected_entry_version` against an already-superseded entry reports the stale-version error, not the invalid-state error."

        Design: Corner/complexity_layers/a_correction_quoting_a_superseded_entrys_old_version_is_rejected_with_four_twelve
        """
        world = _kitchen_with_a_superseded_capture()
        pre_correction_version = world["entry_a"]["version"]
        assert pre_correction_version == 1

        response = api.correct_waste_entry(
            world["entry_a"]["id"],
            factories.correction_payload(
                pre_correction_version,
                correction_note="second corrector, unrefreshed",
                weight_grams=700,
            ),
            make_shift_lead_headers("sl-2"),
        )

        validate_error(response, ApiErrorId.STALE_ENTRY_VERSION.value)

    def test_the_same_corrector_refreshed_to_the_current_version_is_refused_as_invalid_entry_state(self, api):
        """Once the version token is current, the SUPERSEDED row's own state is what refuses the call.

        PRD Coverage: "Preconditions are, in order: the target capture must be `RECORDED` or `FLAGGED`, refused otherwise with `ERR_INVALID_ENTRY_STATE`; `expected_entry_version` must equal the capture's current `version`, refused otherwise with `ERR_STALE_ENTRY_VERSION`". "This ordering is normative; reporting a later error in place of an earlier one is a defect even when both conditions genuinely hold." "Because the optimistic-concurrency check sits at step 10, a correction request carrying a stale `expected_entry_version` against an already-superseded entry reports the stale-version error, not the invalid-state error."

        Design: Corner/complexity_layers/a_correction_quoting_a_superseded_entrys_old_version_is_rejected_with_four_twelve
        """
        world = _kitchen_with_a_superseded_capture()
        refreshed = fixtures.read_entry(world["entry_a"]["id"])
        assert refreshed["version"] == world["entry_a"]["version"] + 1

        response = api.correct_waste_entry(
            world["entry_a"]["id"],
            factories.correction_payload(
                refreshed["version"],
                correction_note="second corrector, refreshed",
                weight_grams=700,
            ),
            make_shift_lead_headers("sl-2"),
        )

        validate_error(response, ApiErrorId.INVALID_ENTRY_STATE.value)

    def test_neither_refused_correction_disturbs_the_supersession_or_the_period_total(self, api):
        """Both refusals leave one SUPERSEDED predecessor, one successor and an 800 g period total.

        PRD Coverage: "On success the original capture's status becomes `SUPERSEDED`, which removes it from every `RECORDED`-or-`FLAGGED` aggregation set while leaving it visible to the compliance numerator, and its `version` is incremented by 1." "The owning service period recomputes `shift_waste_grams`, the sum of `weight_grams` over its captures whose status is `RECORDED` or `FLAGGED`; `waste_intensity_kg_per_1k_meals`, which is `shift_waste_grams` divided by `meals_served` rounded half up to 3 decimal places — grams per meal is numerically identical to kilograms per thousand meals — and is null whenever `meals_served` is 0; `pre_consumer_share_pct`, which is the summed `weight_grams` of the `PRE_CONSUMER` members of that same set divided by `shift_waste_grams`, rounded half up to 4 decimal places, and null whenever `shift_waste_grams` is 0; and `capture_compliance_pct`, which is the number of distinct stations that reported on this period divided by the number of the site's `ACTIVE` stations, rounded half up to 4 decimal places, and fixed at 1.0000 when the site has no `ACTIVE` stations at all."

        Design: Corner/complexity_layers/a_correction_quoting_a_superseded_entrys_old_version_is_rejected_with_four_twelve
        """
        world = _kitchen_with_a_superseded_capture()
        entry_a_id = world["entry_a"]["id"]
        current_version = fixtures.read_entry(entry_a_id)["version"]

        validate_error(
            api.correct_waste_entry(
                entry_a_id,
                factories.correction_payload(1, correction_note="unrefreshed", weight_grams=700),
                make_shift_lead_headers("sl-2"),
            ),
            ApiErrorId.STALE_ENTRY_VERSION.value,
        )
        validate_error(
            api.correct_waste_entry(
                entry_a_id,
                factories.correction_payload(current_version, correction_note="refreshed", weight_grams=700),
                make_shift_lead_headers("sl-2"),
            ),
            ApiErrorId.INVALID_ENTRY_STATE.value,
        )

        predecessor = fixtures.read_entry(entry_a_id)
        assert_waste_entry(predecessor)
        assert predecessor["status"] == "SUPERSEDED"
        assert predecessor["version"] == current_version
        assert predecessor["version"] == world["entry_a"]["version"] + 1

        rows, meta = validate_paginated(
            api.list_waste_entries(make_shift_lead_headers("sl-1"), shift_id=world["shift"]["id"])
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2

        shift = fixtures.read_shift(world["shift"]["id"])
        assert_shift(shift)
        assert shift["shift_waste_grams"] == 800


def _site_with_certified_baseline_and_an_intervening_capture():
    """A certified 2026-08-01 baseline, the site version the corporate lead read, then a PM capture."""
    world = _kitchen_with_open_am_shift()
    fixtures.capture_entry(
        world["station"]["id"],
        world["shift"]["id"],
        world["food_type"]["id"],
        weight_grams=1000,
        loss_reason="TRIM",
        captured_at=MORNING_CAPTURE_AT,
    )
    world["shift"] = fixtures.close_shift(world["shift"]["id"])
    baseline = fixtures.open_baseline(world["site"]["id"])
    baseline = fixtures.submit_baseline(world["site"]["id"], baseline["id"])
    world["baseline"] = fixtures.certify_baseline(baseline["id"])
    world["site_observed"] = fixtures.read_site(world["site"]["id"])
    world["pm_shift"] = fixtures.open_shift(world["site"]["id"], shift_code="PM", meals_served=200)
    fixtures.capture_entry(
        world["station"]["id"],
        world["pm_shift"]["id"],
        world["food_type"]["id"],
        weight_grams=600,
        loss_reason="SPOILAGE",
        captured_at=NEAR_NOON_CAPTURE_AT,
    )
    world["site_current"] = fixtures.read_site(world["site"]["id"])
    return world


class TestReductionTargetUnderSiteVersionGuard:
    """A target must be sized against a site snapshot that is still current."""

    def test_a_target_quoting_the_site_version_from_before_the_last_capture_is_refused_at_412(
        self, api, corporate_lead_headers
    ):
        """The sizing token went stale the moment a cook posted another loss, and nothing is created.

        PRD Coverage: "Creating a reduction target requires the request to carry `expected_site_version`, holding the client's last observed `version` of the `Site` the target is being written for. If that value does not equal the site's current `version`, the request is rejected with `ERR_STALE_SITE_VERSION` and HTTP status 412. The field is not optional." "Every capture, void, service-period close and settlement bumps `Site.version`, so a stale `expected_site_version` is direct evidence that the sizing inputs have moved."

        Design: Corner/complexity_layers/a_target_quoting_a_site_version_from_before_the_last_capture_is_rejected_with_four_twelve
        """
        world = _site_with_certified_baseline_and_an_intervening_capture()
        stale_payload = factories.create_reduction_target_payload(
            world["site"]["id"],
            world["baseline"]["id"],
            world["site_observed"]["version"],
            basis="INTENSITY",
        )

        response = api.create_reduction_target(stale_payload, corporate_lead_headers)

        validate_error(response, ApiErrorId.STALE_SITE_VERSION.value)
        rows, meta = validate_paginated(
            api.list_reduction_targets(corporate_lead_headers, site_id=world["site"]["id"])
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_refreshing_the_site_version_by_one_capture_lets_the_same_target_be_proposed(
        self, api, corporate_lead_headers
    ):
        """The intervening capture moved the site by exactly one, and the refreshed token is accepted.

        PRD Coverage: "Every capture, void, service-period close and settlement bumps `Site.version`, so a stale `expected_site_version` is direct evidence that the sizing inputs have moved." "The new target itself opens in status `PROPOSED` with `activated_at` and `resolved_at` null, `performance_waste_grams` and `performance_meals_served` at 0, and `attainment_state` at `BEHIND`."

        Design: Corner/complexity_layers/a_target_quoting_a_site_version_from_before_the_last_capture_is_rejected_with_four_twelve
        """
        world = _site_with_certified_baseline_and_an_intervening_capture()
        assert_version_bumped_by(world["site_observed"], world["site_current"], 1)
        fresh_payload = factories.create_reduction_target_payload(
            world["site"]["id"],
            world["baseline"]["id"],
            world["site_current"]["version"],
            basis="INTENSITY",
        )

        response = api.create_reduction_target(fresh_payload, corporate_lead_headers)

        target = validate_success(response, 201)
        assert_reduction_target(target)
        assert target["status"] == "PROPOSED"
        assert target["site_id"] == world["site"]["id"]
        assert target["baseline_period_id"] == world["baseline"]["id"]
        assert target["activated_at"] is None
        assert target["resolved_at"] is None
        assert target["performance_waste_grams"] == 0
        assert target["performance_meals_served"] == 0
        assert target["attainment_state"] == "BEHIND"
        rows, meta = validate_paginated(
            api.list_reduction_targets(corporate_lead_headers, site_id=world["site"]["id"])
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == target["id"]


class TestSiteVersionIsAWriteCounterOnTheAggregate:
    """The site's version counts the writes that recompute its scoreboard, and nothing else."""

    def test_two_captures_and_a_close_walk_the_site_version_from_one_to_four(
        self, api, kitchen_staff_headers, shift_lead_headers
    ):
        """Three writes aimed at three different rows each bump the site exactly once.

        PRD Coverage: "Every capture, void, service-period close and settlement bumps `Site.version`, so a stale `expected_site_version` is direct evidence that the sizing inputs have moved." "Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increases by exactly 1 each time the row is mutated." "The site then recomputes `total_captured_weight_grams`, `valued_waste_cost_cents` and `diversion_rate_pct`."

        Design: Corner/complexity_layers/site_version_advances_once_per_capture_void_and_shift_close
        """
        world = _kitchen_with_open_am_shift()
        site_id = world["site"]["id"]
        assert fixtures.read_site(site_id)["version"] == 1

        validate_success(
            api.create_waste_entry(
                factories.create_waste_entry_payload(
                    world["station"]["id"],
                    world["shift"]["id"],
                    world["food_type"]["id"],
                    weight_grams=1000,
                    loss_reason="TRIM",
                    captured_at=MORNING_CAPTURE_AT,
                ),
                kitchen_staff_headers,
            ),
            201,
        )
        assert fixtures.read_site(site_id)["version"] == 2

        validate_success(
            api.create_waste_entry(
                factories.create_waste_entry_payload(
                    world["station"]["id"],
                    world["shift"]["id"],
                    world["food_type"]["id"],
                    weight_grams=400,
                    loss_reason="SPOILAGE",
                    captured_at=MID_MORNING_CAPTURE_AT,
                ),
                kitchen_staff_headers,
            ),
            201,
        )
        assert fixtures.read_site(site_id)["version"] == 3

        validate_success(api.close_shift(world["shift"]["id"], shift_lead_headers), 200)

        site = fixtures.read_site(site_id)
        assert_site(site)
        assert site["version"] == 4
        assert site["total_captured_weight_grams"] == 1400

    def test_installing_a_station_and_opening_a_period_leave_the_site_version_untouched(self, api):
        """Neither catalog write touches the site scoreboard, so the counter only moves on the capture.

        PRD Coverage: "Every capture, void, service-period close and settlement bumps `Site.version`, so a stale `expected_site_version` is direct evidence that the sizing inputs have moved." "Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increases by exactly 1 each time the row is mutated."

        Design: Corner/complexity_layers/site_version_advances_once_per_capture_void_and_shift_close
        """
        fixtures.set_clock(WORKING_CLOCK)
        site = fixtures.create_site()
        assert site["version"] == 1

        station = fixtures.create_station(site["id"], station_code="PREP-1", station_kind="PREP")
        after_station = fixtures.read_site(site["id"])
        assert after_station["version"] == 1

        food_type = fixtures.create_food_type()
        shift = fixtures.open_shift(site["id"])
        after_shift = fixtures.read_site(site["id"])
        assert after_shift["version"] == 1
        assert after_shift["total_captured_weight_grams"] == 0

        fixtures.capture_entry(
            station["id"],
            shift["id"],
            food_type["id"],
            weight_grams=1000,
            loss_reason="TRIM",
            captured_at=MORNING_CAPTURE_AT,
        )

        after_capture = fixtures.read_site(site["id"])
        assert_version_bumped_by(after_shift, after_capture, 1)
        assert after_capture["version"] == 2
        assert after_capture["total_captured_weight_grams"] == 1000


def _closed_am_shift_with_two_captures():
    """One PREP station, an AM period of 250 covers carrying 1000 g and 2000 g, then closed."""
    world = _kitchen_with_open_am_shift()
    world["entry_small"] = fixtures.capture_entry(
        world["station"]["id"],
        world["shift"]["id"],
        world["food_type"]["id"],
        weight_grams=1000,
        loss_reason="TRIM",
        captured_at=MORNING_CAPTURE_AT,
    )
    world["entry_big"] = fixtures.capture_entry(
        world["station"]["id"],
        world["shift"]["id"],
        world["food_type"]["id"],
        weight_grams=2000,
        loss_reason="SPOILAGE",
        captured_at=MID_MORNING_CAPTURE_AT,
    )
    world["shift"] = fixtures.close_shift(world["shift"]["id"])
    return world


class TestVoidingAfterClosureRescoresTheLeaderboard:
    """A retraction that lands after the accounting event re-derives the stored score."""

    def test_closing_the_period_scores_ninety_five_from_the_intensity_penalty_and_the_bonus(self, api):
        """3000 g over 250 covers is exactly 12.000, so the period loses 8.0 and gains the flat bonus.

        PRD Coverage: "The **intensity excess** is the amount by which the period's `waste_intensity_kg_per_1k_meals` exceeds the site's `target_intensity_kg_per_1k_meals`, floored at zero so a period that beat its target scores no excess; a null intensity, which happens when `meals_served` is 0, is treated as zero excess." "The **intensity penalty** is that excess multiplied by 4.0 points per kilogram per thousand meals, then capped so it can never exceed 60.0 points however far the period overshot." "The **compliance penalty** is the shortfall in station reporting — one minus `capture_compliance_pct` — multiplied by a weight of 25.0 points, so a period where every active station reported loses nothing and a period where none did loses the full 25.0." "The **pre-consumer bonus** is a flat 3.0 points, awarded when `pre_consumer_share_pct` is not null and has reached 0.60 or more, and zero otherwise; catching waste before it reaches a plate is what the bonus rewards." "The raw score is 100 minus the intensity penalty, minus the compliance penalty, plus the bonus."

        Design: Corner/complexity_layers/voiding_a_capture_after_the_shift_closed_rescores_the_leaderboard_and_hits_the_clamp
        """
        world = _closed_am_shift_with_two_captures()

        shift = fixtures.read_shift(world["shift"]["id"])

        assert_shift(shift)
        assert shift["status"] == "CLOSED"
        assert shift["shift_waste_grams"] == 3000
        assert shift["waste_intensity_kg_per_1k_meals"] == pytest.approx(12.000, abs=0.01)
        assert shift["capture_compliance_pct"] == pytest.approx(1.0000, abs=0.01)
        assert shift["pre_consumer_share_pct"] == pytest.approx(1.0000, abs=0.01)
        assert shift["leaderboard_score"] == pytest.approx(95.0, abs=0.01)

    def test_voiding_the_larger_capture_rescores_the_closed_period_up_to_the_clamp(self, api):
        """The raw figure climbs to 103 and must be reported as exactly 100.0.

        PRD Coverage: "In the second hop, caused by that departure, the owning service period recomputes `shift_waste_grams`, `waste_intensity_kg_per_1k_meals`, `capture_compliance_pct` and `pre_consumer_share_pct` — and, when the period has already been closed, its `leaderboard_score` as well." "That raw figure is then clamped into the range from 0 to 100 inclusive — first floored at 0, then capped at 100 — and rounded half up to 1 decimal place to become `leaderboard_score`."

        Design: Corner/complexity_layers/voiding_a_capture_after_the_shift_closed_rescores_the_leaderboard_and_hits_the_clamp
        """
        world = _closed_am_shift_with_two_captures()

        response = api.void_waste_entry(
            world["entry_big"]["id"],
            factories.void_payload(void_reason="tray was weighed twice"),
            make_shift_lead_headers("sl-2"),
        )

        voided = validate_success(response, 200)
        assert voided["status"] == "VOIDED"
        shift = fixtures.read_shift(world["shift"]["id"])
        assert_shift(shift)
        assert shift["status"] == "CLOSED"
        assert shift["shift_waste_grams"] == 1000
        assert shift["waste_intensity_kg_per_1k_meals"] == pytest.approx(4.000, abs=0.01)
        assert shift["leaderboard_score"] == pytest.approx(100.0, abs=0.01)

    def test_the_surviving_capture_keeps_the_single_station_covered_and_the_site_posture_calm(self, api):
        """Compliance holds at 1.0000 and the site scoreboard falls back to the one surviving capture.

        PRD Coverage: "The reporting-station numerator deliberately counts distinct `station_id` values over captures of this period whose status is `RECORDED`, `FLAGGED` **or** `SUPERSEDED` — a superseded capture still proves the station reported — while `shift_waste_grams` and the pre-consumer share exclude both `VOIDED` and `SUPERSEDED` records." "`total_captured_weight_grams` is the sum of `weight_grams` over the site's captures whose status is either `RECORDED` or `FLAGGED`; `valued_waste_cost_cents` is the sum of `effective_cost_cents` over exactly that same set of captures; `diverted_weight_grams_settled` is the sum of `allocated_weight_grams` over the site's allocation lines whose consignment has reached `SETTLED` on the settlement dimension and has not been `CANCELLED` on the logistics dimension; `diversion_rate_pct` is the settled diverted grams divided by the total captured grams, multiplied by 100 and rounded half up to 2 decimal places, and is null whenever `total_captured_weight_grams` is 0; `open_alert_count` is the number of coaching alerts at the site whose status is `OPEN` or `ACKNOWLEDGED`; and `coaching_posture` is derived purely from that count — `MONITORING` when the count is exactly 0, `ESCALATED` when the count is 3 or more, and `INTERVENTION` for every count in between."

        Design: Corner/complexity_layers/voiding_a_capture_after_the_shift_closed_rescores_the_leaderboard_and_hits_the_clamp
        """
        world = _closed_am_shift_with_two_captures()
        fixtures.void_entry(world["entry_big"]["id"], user_id="sl-2", void_reason="tray was weighed twice")

        shift = fixtures.read_shift(world["shift"]["id"])
        site = fixtures.read_site(world["site"]["id"])
        surviving = fixtures.read_entry(world["entry_small"]["id"])
        retracted = fixtures.read_entry(world["entry_big"]["id"])

        assert shift["capture_compliance_pct"] == pytest.approx(1.0000, abs=0.01)
        assert surviving["status"] == "RECORDED"
        assert retracted["status"] == "VOIDED"
        assert_site(site)
        assert site["total_captured_weight_grams"] == 1000
        assert site["open_alert_count"] == 0
        assert site["coaching_posture"] == "MONITORING"
        assert_coaching_posture_ladder(site)
        assert_site_cost_ledger(site, [surviving, retracted])


class TestDerivedFieldsAreReadableInTheNextRequest:
    """Every recompute happens inside the writing request, so the following read is already current."""

    def test_the_capture_response_and_the_next_period_read_already_carry_the_new_totals(
        self, api, kitchen_staff_headers, shift_lead_headers
    ):
        """2500 g at 640 cents per kilogram values at 1600 cents and lifts the period to 10.000 at once.

        PRD Coverage: "The weight is converted to kilograms by dividing `weight_grams` by 1000, an exact decimal that is never rounded, and the cost is that kilogram figure multiplied by the chosen basis in cents per kilogram, rounded half up to a whole number of cents." "`provisional_cost_cents` is that product taken against `catalog_cost_basis_cents`, ignoring recipe attribution entirely." "`effective_cost_cents` — the figure that actually feeds every site, baseline and rollup total — is `final_cost_cents` when that field is non-null and `provisional_cost_cents` otherwise, so at capture time it equals the provisional figure." "A large fraction of every entity's payload is derived. Derived fields are never maintained by incremental delta arithmetic; each recompute reads the qualifying source rows and recalculates the value from scratch."

        Design: Corner/consistency_model/derived_site_and_shift_fields_are_readable_in_the_next_request
        """
        world = _kitchen_with_open_am_shift()

        created = validate_success(
            api.create_waste_entry(
                factories.create_waste_entry_payload(
                    world["station"]["id"],
                    world["shift"]["id"],
                    world["food_type"]["id"],
                    weight_grams=2500,
                    loss_reason="TRIM",
                    captured_at=MORNING_CAPTURE_AT,
                ),
                kitchen_staff_headers,
            ),
            201,
        )
        shift = validate_success(api.get_shift(world["shift"]["id"], shift_lead_headers), 200)

        assert_waste_entry(created)
        assert created["catalog_cost_basis_cents"] == 640
        assert created["provisional_cost_cents"] == 1600
        assert created["effective_cost_cents"] == 1600
        assert_shift(shift)
        assert shift["shift_waste_grams"] == 2500
        assert shift["waste_intensity_kg_per_1k_meals"] == pytest.approx(10.000, abs=0.01)

    def test_the_site_scoreboard_and_its_version_are_current_on_the_very_next_read(
        self, api, kitchen_staff_headers
    ):
        """The read that immediately follows the capture already shows 2500 g, 1600 cents and version 2.

        PRD Coverage: "The site then recomputes `total_captured_weight_grams`, `valued_waste_cost_cents` and `diversion_rate_pct`." "Both the service period's `version` and the site's `version` are incremented by 1." "Cascades run to completion inside the request that triggers them, and every row a cascade touches has its `updated_at` refreshed and its `version` incremented."

        Design: Corner/consistency_model/derived_site_and_shift_fields_are_readable_in_the_next_request
        """
        world = _kitchen_with_open_am_shift()
        site_id = world["site"]["id"]

        validate_success(
            api.create_waste_entry(
                factories.create_waste_entry_payload(
                    world["station"]["id"],
                    world["shift"]["id"],
                    world["food_type"]["id"],
                    weight_grams=2500,
                    loss_reason="TRIM",
                    captured_at=MORNING_CAPTURE_AT,
                ),
                kitchen_staff_headers,
            ),
            201,
        )
        site = validate_success(
            api.get_site(site_id, make_site_sustainability_manager_headers(site_id)), 200
        )

        assert_site(site)
        assert site["total_captured_weight_grams"] == 2500
        assert site["valued_waste_cost_cents"] == 1600
        assert site["version"] == 2

    def test_repeating_both_reads_returns_the_identical_resource_bodies(
        self, api, kitchen_staff_headers, shift_lead_headers
    ):
        """Nothing settles late: a second pass over the same two reads returns the same resources.

        PRD Coverage: "A large fraction of every entity's payload is derived. Derived fields are never maintained by incremental delta arithmetic; each recompute reads the qualifying source rows and recalculates the value from scratch." "Cascades run to completion inside the request that triggers them, and every row a cascade touches has its `updated_at` refreshed and its `version` incremented."

        Design: Corner/consistency_model/derived_site_and_shift_fields_are_readable_in_the_next_request
        """
        world = _kitchen_with_open_am_shift()
        site_id = world["site"]["id"]
        manager_headers = make_site_sustainability_manager_headers(site_id)
        fixtures.capture_entry(
            world["station"]["id"],
            world["shift"]["id"],
            world["food_type"]["id"],
            weight_grams=2500,
            loss_reason="TRIM",
            captured_at=MORNING_CAPTURE_AT,
        )

        first_shift = validate_success(api.get_shift(world["shift"]["id"], shift_lead_headers), 200)
        first_site = validate_success(api.get_site(site_id, manager_headers), 200)
        second_shift = validate_success(api.get_shift(world["shift"]["id"], shift_lead_headers), 200)
        second_site = validate_success(api.get_site(site_id, manager_headers), 200)

        assert second_shift == first_shift
        assert second_site == first_site
        assert first_shift["shift_waste_grams"] == 2500
        assert first_site["valued_waste_cost_cents"] == 1600


class TestARejectedCaptureLeavesNoPartiallyAppliedState:
    """A refusal from the far end of the validation ladder must write nothing at all."""

    def test_plate_waste_weighed_at_the_prep_bench_is_refused_and_the_period_total_holds(
        self, api, kitchen_staff_headers
    ):
        """The mismatched pairing is refused and the period still reads only the accepted 1000 g.

        PRD Coverage: "`PLATE_WASTE` is accepted only at a `DISH_RETURN` station, because plate scrapings by definition arrive at the dish return." "Every other pairing — plate waste weighed at the prep bench, trim weighed at the dish return — is refused with `ERR_LOSS_REASON_STATION_MISMATCH`." "Once the guards pass, the capture is written in status `RECORDED` and a substantial amount of derivation follows."

        Design: Corner/consistency_model/a_rejected_capture_leaves_no_partially_applied_state
        """
        world = _kitchen_with_open_am_shift()
        fixtures.capture_entry(
            world["station"]["id"],
            world["shift"]["id"],
            world["food_type"]["id"],
            weight_grams=1000,
            loss_reason="TRIM",
            captured_at=MORNING_CAPTURE_AT,
        )

        response = api.create_waste_entry(
            factories.create_waste_entry_payload(
                world["station"]["id"],
                world["shift"]["id"],
                world["food_type"]["id"],
                weight_grams=3000,
                loss_reason="PLATE_WASTE",
                captured_at=LATE_MORNING_CAPTURE_AT,
            ),
            kitchen_staff_headers,
        )

        validate_error(response, ApiErrorId.LOSS_REASON_STATION_MISMATCH.value)
        shift = fixtures.read_shift(world["shift"]["id"])
        assert_shift(shift)
        assert shift["shift_waste_grams"] == 1000
        assert shift["waste_intensity_kg_per_1k_meals"] == pytest.approx(4.000, abs=0.01)
        rows, meta = validate_paginated(
            api.list_waste_entries(kitchen_staff_headers, shift_id=world["shift"]["id"])
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1

    def test_the_refused_capture_neither_moves_the_site_scoreboard_nor_its_version(
        self, api, kitchen_staff_headers
    ):
        """A partially applied aggregate would show up as a version bump with no row behind it.

        PRD Coverage: "Once the guards pass, the capture is written in status `RECORDED` and a substantial amount of derivation follows." "Every capture, void, service-period close and settlement bumps `Site.version`, so a stale `expected_site_version` is direct evidence that the sizing inputs have moved." "`total_captured_weight_grams` is the sum of `weight_grams` over the site's captures whose status is either `RECORDED` or `FLAGGED`; `valued_waste_cost_cents` is the sum of `effective_cost_cents` over exactly that same set of captures; `diverted_weight_grams_settled` is the sum of `allocated_weight_grams` over the site's allocation lines whose consignment has reached `SETTLED` on the settlement dimension and has not been `CANCELLED` on the logistics dimension; `diversion_rate_pct` is the settled diverted grams divided by the total captured grams, multiplied by 100 and rounded half up to 2 decimal places, and is null whenever `total_captured_weight_grams` is 0; `open_alert_count` is the number of coaching alerts at the site whose status is `OPEN` or `ACKNOWLEDGED`; and `coaching_posture` is derived purely from that count — `MONITORING` when the count is exactly 0, `ESCALATED` when the count is 3 or more, and `INTERVENTION` for every count in between."

        Design: Corner/consistency_model/a_rejected_capture_leaves_no_partially_applied_state
        """
        world = _kitchen_with_open_am_shift()
        accepted = fixtures.capture_entry(
            world["station"]["id"],
            world["shift"]["id"],
            world["food_type"]["id"],
            weight_grams=1000,
            loss_reason="TRIM",
            captured_at=MORNING_CAPTURE_AT,
        )
        site_before = fixtures.read_site(world["site"]["id"])

        validate_error(
            api.create_waste_entry(
                factories.create_waste_entry_payload(
                    world["station"]["id"],
                    world["shift"]["id"],
                    world["food_type"]["id"],
                    weight_grams=3000,
                    loss_reason="PLATE_WASTE",
                    captured_at=LATE_MORNING_CAPTURE_AT,
                ),
                kitchen_staff_headers,
            ),
            ApiErrorId.LOSS_REASON_STATION_MISMATCH.value,
        )

        site_after = fixtures.read_site(world["site"]["id"])
        assert_site(site_after)
        assert site_after["version"] == site_before["version"]
        assert site_after["total_captured_weight_grams"] == 1000
        assert site_after["valued_waste_cost_cents"] == 640
        assert_site_cost_ledger(site_after, [fixtures.read_entry(accepted["id"])])
