"""Station throughput summary: load score composition, peak multiplier,
over-prep penalty tiers, reason filtering, and derived par health."""

import pytest

from test_helpers import (
    validate_success,
    set_clock, create_restaurant, create_manager, create_cook,
    create_prep_item, create_menu_revision_with_recipes,
    create_station, create_station_par, create_finalized_forecast,
    create_prep_batch, create_and_prep_batch, create_locked_prep_list,
    create_service_ticket_payload, create_waste_entry_payload,
    make_kitchen_manager_headers, make_prep_cook_headers,
    make_line_cook_headers,
)


def _summary_env(api, station_type="GRILL", rack_slot_capacity=100,
                 extra_station_types=()):
    """Restaurant + manager + line cook + prep cook + published revision with
    one 4-component recipe per station type, plus one station per type."""
    set_clock("2026-09-01T00:00:00Z")
    rest = create_restaurant()
    all_types = [station_type] + [t for t in extra_station_types
                                  if t != station_type]
    mgr = create_manager(rest["id"], certified_station_types=all_types)
    mh = make_kitchen_manager_headers(mgr["id"])
    line = create_cook(rest["id"], mgr["id"], name="Leo Line",
                       certified_station_types=all_types)
    lch = make_line_cook_headers(line["id"])
    prep_cook = create_cook(rest["id"], mgr["id"], name="Paula Prep",
                            certified_station_types=all_types)
    pch = make_prep_cook_headers(prep_cook["id"])
    recipes_spec = []
    items = {}
    for st_type in all_types:
        components = []
        for i in range(1, 5):
            item = create_prep_item(name=f"P-{st_type}-{i}",
                                    station_type=st_type,
                                    shelf_life_hours=48, min_batch_size=1,
                                    batch_unit="EA")
            items[f"{st_type}-{i}"] = item
            components.append({"prep_item_id": item["id"],
                               "quantity_per_portion": 1, "unit": "EA"})
        recipes_spec.append({"name": f"R-{st_type}", "station_type": st_type,
                             "components": components})
    revision, recipes = create_menu_revision_with_recipes(
        rest["id"], recipes_spec, label="2026-Fall",
        effective_from="2026-09-15T00:00:00Z", publish=True)
    stations = {}
    for st_type in all_types:
        stations[st_type] = create_station(
            rest["id"], mgr["id"], name=f"{st_type} 1", station_type=st_type,
            rack_slot_capacity=rack_slot_capacity)
    return {
        "rest": rest, "mgr": mgr, "mh": mh, "line": line, "lch": lch,
        "prep_cook": prep_cook, "pch": pch, "items": items,
        "revision": revision, "recipes": recipes, "stations": stations,
    }


def _fire_ticket(api, env, recipe, modifications=None):
    ticket = validate_success(api.create_service_ticket(
        create_service_ticket_payload(
            env["rest"]["id"],
            [{"recipe_id": recipe["id"],
              "modifications": modifications or [],
              "allergen_flags": []}]),
        env["lch"]), 201)
    validate_success(api.fire_ticket(ticket["id"], env["lch"]))
    return ticket


class TestLoadScorePeakMultiplier:
    def _peak_setup(self, api):
        env = _summary_env(api)
        recipe = env["recipes"]["R-GRILL"]
        _fire_ticket(api, env, recipe, modifications=["no butter"])
        _fire_ticket(api, env, recipe, modifications=["extra sauce"])
        return env

    def test_load_score_at_and_below_peak_threshold(self, api):
        """PRD section 3.8: "The load score counts only tickets of the
        station's restaurant whose `fire_status` is `FIRED` or `READY` — open,
        served, and voided tickets are excluded." and "When the restaurant's
        `current_waitlist_minutes` has reached at least the forty-five-minute
        peak threshold, a peak multiplier of one and a half is applied; below
        the threshold the multiplier is one. The resulting score is capped at
        two, and reported rounded half up to four decimal places."

        Design: Difficulty/combinatorial_formula/station_load_score_peak_multiplier_mode_a
        """
        env = self._peak_setup(api)
        mh = env["mh"]
        station = env["stations"]["GRILL"]
        validate_success(api.update_waitlist(
            env["rest"]["id"], {"waitlist_minutes": 60}, mh))
        summary = validate_success(api.get_throughput_summary(station["id"], mh))
        # base = 2 tickets x 4 components x 1.25 = 10; /100 = 0.1; x1.5 = 0.15
        assert summary["load_score"] == pytest.approx(0.1500, abs=1e-9)
        validate_success(api.update_waitlist(
            env["rest"]["id"], {"waitlist_minutes": 10}, mh))
        summary2 = validate_success(
            api.get_throughput_summary(station["id"], mh))
        assert summary2["load_score"] == pytest.approx(0.1000, abs=1e-9)

    def test_idle_station_zero_metrics(self, api):
        """PRD section 3.8: "When the restaurant's `current_waitlist_minutes`
        has reached at least the forty-five-minute peak threshold, a peak
        multiplier of one and a half is applied; below the threshold the
        multiplier is one."  With no live tickets and waitlist 0 the idle
        station's load metrics are zero and `par_health` is `OK`.
        PRD section 3.6: "a station with no active pars at all reports `OK`."

        Design: Difficulty/combinatorial_formula/station_load_score_peak_multiplier_mode_a
        """
        env = _summary_env(api)
        station = env["stations"]["GRILL"]
        summary = validate_success(
            api.get_throughput_summary(station["id"], env["mh"]))
        assert summary["load_score"] == pytest.approx(0.0, abs=1e-9)
        assert summary["rack_load"] == 0
        assert summary["par_health"] == "OK"


class TestLoadScoreInputSet:
    def test_excludes_other_station_types_and_closed_tickets(self, api):
        """PRD section 3.8: "The load score counts only tickets of the
        station's restaurant whose `fire_status` is `FIRED` or `READY` —
        open, served, and voided tickets are excluded. For each included
        ticket, each item whose recipe's `station_type` differs from the
        station's own is excluded; for each remaining item, the recipe's
        complexity is the number of components in its build, and that
        complexity is multiplied by a modifier factor of one and a quarter
        whenever the item carries any modifications, or left at one when it
        does not."

        Design: Corner/calculations/load_score_excludes_other_station_types_and_closed_tickets
        """
        env = _summary_env(api, extra_station_types=["SAUTE"])
        grill = env["stations"]["GRILL"]
        recipe_g = env["recipes"]["R-GRILL"]
        recipe_s = env["recipes"]["R-SAUTE"]
        # Included: one FIRED GRILL ticket with no modifications (4 * 1.0).
        _fire_ticket(api, env, recipe_g)
        # Excluded: FIRED SAUTE ticket (wrong station type).
        _fire_ticket(api, env, recipe_s)
        # Excluded: GRILL ticket driven through to SERVED.
        done = _fire_ticket(api, env, recipe_g)
        validate_success(api.mark_ticket_ready(done["id"], env["lch"]))
        validate_success(api.serve_ticket(done["id"], env["lch"]))
        summary = validate_success(
            api.get_throughput_summary(grill["id"], env["mh"]))
        assert summary["load_score"] == pytest.approx(0.0400, abs=1e-9)


class TestOverprepPenaltyBoundary:
    def _waste_env(self, api):
        """Two GRILL stations, one PREPPED batch of 2000 on each."""
        set_clock("2026-09-01T08:00:00Z")
        env = _summary_env(api, rack_slot_capacity=5000)
        item = create_prep_item(name="P4", station_type="GRILL",
                                shelf_life_hours=48, min_batch_size=10,
                                batch_unit="OZ")
        recipe = env["recipes"]["R-GRILL"]
        forecast = create_finalized_forecast(
            env["rest"]["id"], env["mgr"]["id"],
            [{"recipe_id": recipe["id"], "expected_count": 200}],
            expected_covers=200)
        prep_list, _ = create_locked_prep_list(
            env["rest"]["id"], env["mgr"]["id"], forecast["id"])
        s4 = env["stations"]["GRILL"]
        s5 = create_station(env["rest"]["id"], env["mgr"]["id"],
                            name="Grill 5", station_type="GRILL",
                            rack_slot_capacity=5000)
        b1 = create_and_prep_batch(prep_list["id"], item["id"], s4["id"],
                                   env["prep_cook"]["id"], 2000)
        b2 = create_and_prep_batch(prep_list["id"], item["id"], s5["id"],
                                   env["prep_cook"]["id"], 2000)
        return env, s4, s5, b1, b2

    def test_ratio_exactly_at_tier_boundary_lands_in_tier(self, api):
        """PRD section 3.8: "Fourth, the penalty tier is selected on the
        unrounded ratio with lower bounds inclusive: a ratio below five
        percent earns zero points; at least five percent but below twelve
        percent earns ten points; at least twelve percent but below
        twenty-five percent earns twenty-five points; and a ratio of
        twenty-five percent or more earns fifty points."

        Design: Difficulty/boundary_precision_check/waste_ratio_exactly_at_tier_boundary
        """
        env, s4, s5, b1, b2 = self._waste_env(api)
        mh, lch, pch = env["mh"], env["lch"], env["pch"]
        # S4: 100 wasted / (100 + 1900 consumed) == exactly 0.05 -> 10 points.
        validate_success(api.record_consumption(b1["id"],
                                                {"quantity": 1900}, lch))
        validate_success(api.create_waste_entry(
            create_waste_entry_payload(s4["id"], b1["id"], quantity=100,
                                       reason="OVER_PREP"), pch), 201)
        # S5: 99 / 1999 = 0.04952... < 0.05 -> 0 points.
        validate_success(api.record_consumption(b2["id"],
                                                {"quantity": 1900}, lch))
        validate_success(api.create_waste_entry(
            create_waste_entry_payload(s5["id"], b2["id"], quantity=99,
                                       reason="OVER_PREP"), pch), 201)
        sum4 = validate_success(api.get_throughput_summary(s4["id"], mh))
        assert sum4["waste_ratio"] == pytest.approx(0.05, abs=1e-9)
        assert sum4["overprep_penalty_points"] == 10
        sum5 = validate_success(api.get_throughput_summary(s5["id"], mh))
        assert sum5["waste_ratio"] == pytest.approx(99 / 1999, abs=1e-4)
        assert sum5["overprep_penalty_points"] == 0
        b1_now = validate_success(api.get_prep_batch(b1["id"], mh))
        assert b1_now["status"] == "WASTED"

    def test_ratio_just_below_first_tier_earns_nothing(self, api):
        """PRD section 3.8: "a ratio below five percent earns zero points"
        and "Tier selection for the over-prep penalty is always made on the
        unrounded waste ratio, with rounding applied only for display." (PRD
        section 2.7)

        Design: Difficulty/boundary_precision_check/waste_ratio_exactly_at_tier_boundary
        """
        env, s4, s5, b1, b2 = self._waste_env(api)
        mh, lch, pch = env["mh"], env["lch"], env["pch"]
        validate_success(api.record_consumption(b2["id"],
                                                {"quantity": 1900}, lch))
        validate_success(api.create_waste_entry(
            create_waste_entry_payload(s5["id"], b2["id"], quantity=99,
                                       reason="OVER_PREP"), pch), 201)
        sum5 = validate_success(api.get_throughput_summary(s5["id"], mh))
        assert sum5["overprep_penalty_points"] == 0


class TestOverprepReasonFiltering:
    def test_quality_waste_excluded_from_penalty_ratio(self, api):
        """PRD section 3.8: "First, the wasted figure is the sum of waste
        entry quantities at the station whose reason is `OVER_PREP` or
        `EXPIRED`; `QUALITY` and `SPILLAGE` are excluded from the penalty
        ratio."  PRD section 3.6: "Recording waste adds the quantity to the
        batch's `wasted_quantity`, flips the batch to `WASTED` when nothing
        remains, and recomputes the station's `par_health`."

        Design: Corner/calculations/overprep_ratio_excludes_quality_and_spillage_reasons
        """
        set_clock("2026-09-01T08:00:00Z")
        env = _summary_env(api, rack_slot_capacity=5000)
        item = create_prep_item(name="P7", station_type="GRILL",
                                shelf_life_hours=48, min_batch_size=10,
                                batch_unit="OZ")
        recipe = env["recipes"]["R-GRILL"]
        forecast = create_finalized_forecast(
            env["rest"]["id"], env["mgr"]["id"],
            [{"recipe_id": recipe["id"], "expected_count": 200}],
            expected_covers=200)
        prep_list, _ = create_locked_prep_list(
            env["rest"]["id"], env["mgr"]["id"], forecast["id"])
        station = env["stations"]["GRILL"]
        batch = create_and_prep_batch(prep_list["id"], item["id"],
                                      station["id"], env["prep_cook"]["id"],
                                      2000)
        validate_success(api.record_consumption(batch["id"],
                                                {"quantity": 1900},
                                                env["lch"]))
        validate_success(api.create_waste_entry(
            create_waste_entry_payload(station["id"], batch["id"],
                                       quantity=100, reason="QUALITY"),
            env["pch"]), 201)
        summary = validate_success(
            api.get_throughput_summary(station["id"], env["mh"]))
        assert summary["waste_ratio"] == pytest.approx(0.0, abs=1e-9)
        assert summary["overprep_penalty_points"] == 0
        batch_now = validate_success(api.get_prep_batch(batch["id"], env["mh"]))
        assert batch_now["status"] == "WASTED"


class TestDerivedParHealthLifecycle:
    def _par_health_env(self, api):
        set_clock("2026-09-01T08:00:00Z")
        env = _summary_env(api, station_type="COLD", rack_slot_capacity=500)
        item = create_prep_item(name="P", station_type="COLD",
                                shelf_life_hours=48, min_batch_size=10,
                                batch_unit="EA")
        recipe = env["recipes"]["R-COLD"]
        station = env["stations"]["COLD"]
        par = create_station_par(station["id"], item["id"], env["mgr"]["id"],
                                 par_quantity=40)
        forecast = create_finalized_forecast(
            env["rest"]["id"], env["mgr"]["id"],
            [{"recipe_id": recipe["id"], "expected_count": 20}],
            expected_covers=20)
        prep_list, _ = create_locked_prep_list(
            env["rest"]["id"], env["mgr"]["id"], forecast["id"])
        batch = create_and_prep_batch(prep_list["id"], item["id"],
                                      station["id"], env["prep_cook"]["id"],
                                      40)
        return env, station, batch

    def test_par_health_tracks_consumption(self, api):
        """PRD section 3.6: "If the on-hand is below one quarter of the par's
        `par_quantity`, the candidate health is `CRITICAL`; otherwise, if
        on-hand is below the full `par_quantity`, the candidate is
        `BELOW_PAR`; otherwise the candidate is `OK`."

        Design: Corner/cross_cutting_complexity_layers/derived_par_health_reconciles_on_batch_lifecycle
        """
        env, station, batch = self._par_health_env(api)
        mh, lch = env["mh"], env["lch"]
        mid = validate_success(api.record_consumption(
            batch["id"], {"quantity": 30}, lch))
        st_mid = validate_success(api.get_station(station["id"], mh))
        assert st_mid["par_health"] == "BELOW_PAR"
        depleted = validate_success(api.record_consumption(
            batch["id"], {"quantity": 10}, lch))
        assert depleted["status"] == "DEPLETED"
        st_end = validate_success(api.get_station(station["id"], mh))
        assert st_end["par_health"] == "CRITICAL"

    def test_par_health_ok_when_on_hand_meets_par(self, api):
        """PRD section 3.6: "otherwise the candidate is `OK`."

        Design: Corner/cross_cutting_complexity_layers/derived_par_health_reconciles_on_batch_lifecycle
        """
        env, station, batch = self._par_health_env(api)
        st = validate_success(api.get_station(station["id"], env["mh"]))
        assert st["par_health"] == "OK"
