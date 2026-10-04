"""Prep batches: rack capacity boundary, shelf-life expiry boundary, the
expire cascade, FIFO draw-down, and waste-entry attribution."""

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    set_clock, create_restaurant, create_manager, create_cook,
    create_prep_item, create_menu_revision_with_recipes,
    create_station, create_station_par, create_finalized_forecast,
    create_prep_list_payload, create_prep_batch, create_and_prep_batch,
    create_locked_prep_list, create_service_ticket_payload,
    create_waste_entry_payload,
    make_kitchen_manager_headers, make_prep_cook_headers,
    make_line_cook_headers, menu_admin_headers,
)
from datetime import datetime, timezone


def _iso_instant(s):
    """Parse an ISO-8601 UTC timestamp string into a datetime so that
    comparisons are format-agnostic (PRD pins the instant value, not the
    fractional-digit rendering of produced_at/expires_at)."""
    v = s.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    return datetime.fromisoformat(v).astimezone(timezone.utc)


def _locked_list_env(api, station_type="SAUTE", shelf_life_hours=48,
                     min_batch_size=10, batch_unit="OZ",
                     rack_slot_capacity=500, quantity_per_portion=3,
                     expected_count=100, with_line_cook=False):
    """Restaurant + manager + prep cook + prep item + published recipe +
    FINALIZED forecast + GENERATED-then-LOCKED prep list + station."""
    rest = create_restaurant()
    mgr = create_manager(rest["id"], certified_station_types=[station_type])
    mh = make_kitchen_manager_headers(mgr["id"])
    prep_cook = create_cook(rest["id"], mgr["id"], name="Paula Prep",
                            certified_station_types=[station_type])
    pch = make_prep_cook_headers(prep_cook["id"])
    line_cook = None
    lch = None
    if with_line_cook:
        line_cook = create_cook(rest["id"], mgr["id"], name="Leo Line",
                                certified_station_types=[station_type])
        lch = make_line_cook_headers(line_cook["id"])
    item = create_prep_item(name="P", station_type=station_type,
                            shelf_life_hours=shelf_life_hours,
                            min_batch_size=min_batch_size, batch_unit=batch_unit)
    revision, recipes = create_menu_revision_with_recipes(
        rest["id"],
        [{"name": "R", "station_type": station_type,
          "components": [{"prep_item_id": item["id"],
                          "quantity_per_portion": quantity_per_portion,
                          "unit": batch_unit}]}],
        label="V1", effective_from="2026-09-01T00:00:00Z", publish=True)
    station = create_station(rest["id"], mgr["id"], station_type=station_type,
                             rack_slot_capacity=rack_slot_capacity)
    forecast = create_finalized_forecast(
        rest["id"], mgr["id"],
        [{"recipe_id": recipes["R"]["id"], "expected_count": expected_count}],
        expected_covers=max(expected_count, 1))
    prep_list, _ = create_locked_prep_list(rest["id"], mgr["id"],
                                           forecast["id"])
    return {
        "rest": rest, "mgr": mgr, "mh": mh, "prep_cook": prep_cook,
        "pch": pch, "line_cook": line_cook, "lch": lch, "item": item,
        "recipe": recipes["R"], "station": station, "prep_list": prep_list,
    }


class TestRackCapacityBoundary:
    def test_equality_allowed_and_over_capacity_rejected(self, api):
        """PRD section 2.9: "Planning a new batch is rejected with
        `ERR_RACK_CAPACITY_EXCEEDED` whenever the existing rack load plus the
        new batch's `quantity` would exceed the station's
        `rack_slot_capacity`; a station filled exactly to capacity is valid,
        since equality is allowed."

        Design: Difficulty/resource_temporal_overlap/station_rack_aggregate_capacity_equality_allowed
        """
        set_clock("2026-09-01T08:00:00Z")
        env = _locked_list_env(api, rack_slot_capacity=100, min_batch_size=1,
                               quantity_per_portion=1, expected_count=100)
        mh, pch = env["mh"], env["pch"]
        pl, item, st = env["prep_list"], env["item"], env["station"]
        b1 = validate_success(api.create_prep_batch(
            {"prep_list_id": pl["id"], "prep_item_id": item["id"],
             "station_id": st["id"], "quantity": 60}, pch), 201)
        b2 = validate_success(api.create_prep_batch(
            {"prep_list_id": pl["id"], "prep_item_id": item["id"],
             "station_id": st["id"], "quantity": 40}, pch), 201)
        resp = api.create_prep_batch(
            {"prep_list_id": pl["id"], "prep_item_id": item["id"],
             "station_id": st["id"], "quantity": 1}, pch)
        validate_error(resp, ApiErrorId.ERR_RACK_CAPACITY_EXCEEDED, 422)
        summary = validate_success(api.get_throughput_summary(st["id"], mh))
        assert summary["rack_load"] == 100

    def test_rack_load_sums_remaining_across_live_batches(self, api):
        """PRD section 2.9: "The station's current rack load is the sum, over
        all of its prep batches in `PLANNED` or `PREPPED` status and across
        all prep items, of each batch's remaining quantity — that is, its
        `quantity` minus its `consumed_quantity` minus its
        `wasted_quantity`."

        Design: Difficulty/resource_temporal_overlap/station_rack_aggregate_capacity_equality_allowed
        """
        set_clock("2026-09-01T08:00:00Z")
        env = _locked_list_env(api, rack_slot_capacity=100, min_batch_size=1,
                               quantity_per_portion=1, expected_count=100)
        mh, pch = env["mh"], env["pch"]
        pl, item, st = env["prep_list"], env["item"], env["station"]
        validate_success(api.create_prep_batch(
            {"prep_list_id": pl["id"], "prep_item_id": item["id"],
             "station_id": st["id"], "quantity": 70}, pch), 201)
        # 70 live; 30 more fits exactly.
        validate_success(api.create_prep_batch(
            {"prep_list_id": pl["id"], "prep_item_id": item["id"],
             "station_id": st["id"], "quantity": 30}, pch), 201)
        summary = validate_success(api.get_throughput_summary(st["id"], mh))
        assert summary["rack_load"] == 100


class TestBatchInitialState:
    def test_new_batch_is_planned_with_null_expiry(self, api):
        """PRD section 3.6: "A new batch occupies rack load immediately,
        starts in `PLANNED` with `consumed_quantity` and `wasted_quantity` at
        zero and `produced_at` and `expires_at` still null, and its creation
        recomputes the station's `par_health`."

        Design: Corner/state_machines/prep_batch_starts_planned_with_null_expiry
        """
        set_clock("2026-09-01T08:00:00Z")
        env = _locked_list_env(api, station_type="COLD", shelf_life_hours=6,
                               min_batch_size=10, batch_unit="EA",
                               rack_slot_capacity=500, quantity_per_portion=2,
                               expected_count=10)
        batch = validate_success(api.create_prep_batch(
            {"prep_list_id": env["prep_list"]["id"],
             "prep_item_id": env["item"]["id"],
             "station_id": env["station"]["id"], "quantity": 20},
            env["pch"]), 201)
        assert batch["status"] == "PLANNED"
        assert batch["produced_at"] is None
        assert batch["expires_at"] is None
        assert batch["consumed_quantity"] == 0
        assert batch["wasted_quantity"] == 0


class TestBatchCreateGatedOnLockedList:
    def test_batch_on_generated_not_locked_list_rejected(self, api):
        """PRD section 3.6: "Planning against a list that is neither `LOCKED`
        nor `IN_PROGRESS` is rejected with `ERR_PREP_LIST_NOT_LOCKED`."

        Design: Corner/validations/batch_create_on_unlocked_prep_list_rejected
        """
        set_clock("2026-09-01T08:00:00Z")
        rest = create_restaurant()
        mgr = create_manager(rest["id"], certified_station_types=["SAUTE"])
        mh = make_kitchen_manager_headers(mgr["id"])
        prep_cook = create_cook(rest["id"], mgr["id"], name="Paula Prep",
                                certified_station_types=["SAUTE"])
        pch = make_prep_cook_headers(prep_cook["id"])
        item = create_prep_item(name="P", station_type="SAUTE")
        revision, recipes = create_menu_revision_with_recipes(
            rest["id"],
            [{"name": "R", "station_type": "SAUTE",
              "components": [{"prep_item_id": item["id"],
                              "quantity_per_portion": 2, "unit": "OZ"}]}],
            label="V1", effective_from="2026-09-01T00:00:00Z", publish=True)
        station = create_station(rest["id"], mgr["id"],
                                 rack_slot_capacity=500)
        forecast = create_finalized_forecast(
            rest["id"], mgr["id"],
            [{"recipe_id": recipes["R"]["id"], "expected_count": 10}],
            expected_covers=10)
        prep_list = validate_success(api.create_prep_list(
            create_prep_list_payload(rest["id"], forecast["id"]), mh), 201)
        validate_success(api.generate_prep_list(
            prep_list["id"], {"generation_variant": "OPTIMISTIC"}, mh))
        resp = api.create_prep_batch(
            {"prep_list_id": prep_list["id"], "prep_item_id": item["id"],
             "station_id": station["id"], "quantity": 20}, pch)
        validate_error(resp, ApiErrorId.ERR_PREP_LIST_NOT_LOCKED, 409)
        data, meta = validate_paginated(api.list_prep_batches(
            mh, params={"prep_list_id": prep_list["id"]}))
        assert data == []


class TestConsumptionAtExactExpiry:
    def _prepped_batch_env(self, api):
        set_clock("2026-09-01T08:00:00Z")
        env = _locked_list_env(api, station_type="COLD", shelf_life_hours=4,
                               min_batch_size=10, batch_unit="EA",
                               rack_slot_capacity=500, quantity_per_portion=2,
                               expected_count=5, with_line_cook=True)
        batch = create_and_prep_batch(
            env["prep_list"]["id"], env["item"]["id"], env["station"]["id"],
            env["prep_cook"]["id"], 10)
        return env, batch

    def test_consumption_at_expiry_instant_rejected_and_expires(self, api):
        """PRD section 3.6: "The expiry check runs on every consumption: if
        the logical clock has reached or passed the batch's `expires_at` —
        equality counts as expired — the batch transitions to `EXPIRED` and
        the call fails with `ERR_BATCH_EXPIRED`; consumption is only
        permitted while the clock is still strictly before `expires_at`."

        Design: Difficulty/boundary_precision_check/consumption_at_exact_expiry_instant_rejected
        """
        env, batch = self._prepped_batch_env(api)
        set_clock("2026-09-01T12:00:00Z")  # exactly expires_at
        resp = api.record_consumption(batch["id"], {"quantity": 1},
                                      env["lch"])
        validate_error(resp, ApiErrorId.ERR_BATCH_EXPIRED, 409)
        batch_now = validate_success(api.get_prep_batch(batch["id"], env["mh"]))
        assert batch_now["status"] == "EXPIRED"
        assert _iso_instant(batch_now["expires_at"]) == _iso_instant(
            "2026-09-01T12:00:00Z")
        entries, meta = validate_paginated(api.list_waste_entries(
            env["mh"], params={"prep_batch_id": batch["id"]}))
        assert len(entries) == 1
        assert entries[0]["reason"] == "EXPIRED"
        assert entries[0]["quantity"] == 10

    def test_consumption_just_before_expiry_allowed(self, api):
        """PRD section 3.6: "consumption is only permitted while the clock is
        still strictly before `expires_at`."

        Design: Difficulty/boundary_precision_check/consumption_at_exact_expiry_instant_rejected
        """
        env, batch = self._prepped_batch_env(api)
        set_clock("2026-09-01T11:59:59Z")  # one second before expires_at
        consumed = validate_success(api.record_consumption(
            batch["id"], {"quantity": 1}, env["lch"]))
        assert consumed["status"] == "PREPPED"
        assert consumed["consumed_quantity"] == 1


class TestExpireCascadeDepth2:
    def _expire_env(self, api):
        set_clock("2026-09-01T08:00:00Z")
        env = _locked_list_env(api, station_type="COLD", shelf_life_hours=4,
                               min_batch_size=10, batch_unit="EA",
                               rack_slot_capacity=500, quantity_per_portion=2,
                               expected_count=20)
        par = create_station_par(env["station"]["id"], env["item"]["id"],
                                 env["mgr"]["id"], par_quantity=40)
        batch = create_and_prep_batch(
            env["prep_list"]["id"], env["item"]["id"], env["station"]["id"],
            env["prep_cook"]["id"], 40)
        return env, par, batch

    def test_expire_auto_waste_entry_and_par_health_flip(self, api):
        """PRD section 3.6: "Expiring a batch auto-creates a waste entry
        against it with reason `EXPIRED` for the entire remaining quantity,
        an entry that lands immediately in `ATTRIBUTED` since its parent
        batch has reached a terminal state in the same breath. The expiry
        reduces the station's on-hand, which flips the station's `par_health`
        per the derivation below — a cascade two links deep — and, as with
        depletion, completes the parent list when all siblings are terminal."

        Design: Difficulty/transitive_cascade/batch_expire_cascade_depth2
        """
        env, par, batch = self._expire_env(api)
        mh = env["mh"]
        set_clock("2026-09-01T12:01:00Z")  # past expires_at 12:00
        expired = validate_success(api.expire_batch(batch["id"], mh))
        assert expired["status"] == "EXPIRED"
        entries, meta = validate_paginated(api.list_waste_entries(
            mh, params={"prep_batch_id": batch["id"]}))
        assert len(entries) == 1
        assert entries[0]["reason"] == "EXPIRED"
        assert entries[0]["quantity"] == 40
        assert entries[0]["status"] == "ATTRIBUTED"
        station = validate_success(api.get_station(env["station"]["id"], mh))
        assert station["par_health"] == "CRITICAL"
        summary = validate_success(
            api.get_throughput_summary(env["station"]["id"], mh))
        assert summary["rack_load"] == 0

    def test_par_health_ok_before_expiry(self, api):
        """PRD section 3.6: "If the on-hand is below one quarter of the par's
        `par_quantity`, the candidate health is `CRITICAL`; otherwise, if
        on-hand is below the full `par_quantity`, the candidate is
        `BELOW_PAR`; otherwise the candidate is `OK`."

        Design: Difficulty/transitive_cascade/batch_expire_cascade_depth2
        """
        env, par, batch = self._expire_env(api)
        station = validate_success(
            api.get_station(env["station"]["id"], env["mh"]))
        assert station["par_health"] == "OK"


class TestMarkReadyFifoDrawDown:
    def test_earlier_expiring_batch_drawn_first(self, api):
        """PRD section 3.8: "For each ticket item, the system consumes the
        component quantities of the item's recipe from `PREPPED` batches at
        the station whose `station_type` matches the recipe's producing
        station, drawing from batches in order of earliest `expires_at`
        first, with ties broken by earliest `created_at`."

        Design: Corner/state_machines/mark_ready_draws_down_fifo_by_expiry
        """
        set_clock("2026-09-01T08:00:00Z")
        env = _locked_list_env(api, station_type="GRILL", shelf_life_hours=4,
                               min_batch_size=1, batch_unit="EA",
                               rack_slot_capacity=500, quantity_per_portion=1,
                               expected_count=20, with_line_cook=True)
        pl, item, st = env["prep_list"], env["item"], env["station"]
        pch, lch = env["pch"], env["lch"]
        batch_a = create_and_prep_batch(pl["id"], item["id"], st["id"],
                                        env["prep_cook"]["id"], 10)
        set_clock("2026-09-01T08:30:00Z")
        batch_b = create_and_prep_batch(pl["id"], item["id"], st["id"],
                                        env["prep_cook"]["id"], 10)
        ticket = validate_success(api.create_service_ticket(
            create_service_ticket_payload(
                env["rest"]["id"],
                [{"recipe_id": env["recipe"]["id"], "modifications": [],
                  "allergen_flags": []}]), lch), 201)
        validate_success(api.fire_ticket(ticket["id"], lch))
        ready = validate_success(api.mark_ticket_ready(ticket["id"], lch))
        assert ready["fire_status"] == "READY"
        a_now = validate_success(api.get_prep_batch(batch_a["id"], env["mh"]))
        b_now = validate_success(api.get_prep_batch(batch_b["id"], env["mh"]))
        assert a_now["consumed_quantity"] == 1
        assert b_now["consumed_quantity"] == 0


class TestWasteEntryAttribution:
    def test_recorded_by_comes_from_header(self, api):
        """PRD section 3.6: "The entry's `recorded_by_cook_id` is taken from
        the recorder's `X-User-ID` header, never from the request body."

        Design: Corner/entities/waste_entry_recorded_by_comes_from_header_not_payload
        """
        set_clock("2026-09-01T08:00:00Z")
        env = _locked_list_env(api, station_type="GRILL", min_batch_size=10,
                               rack_slot_capacity=100, quantity_per_portion=5,
                               expected_count=10)
        batch = create_and_prep_batch(
            env["prep_list"]["id"], env["item"]["id"], env["station"]["id"],
            env["prep_cook"]["id"], 50)
        entry = validate_success(api.create_waste_entry(
            create_waste_entry_payload(
                env["station"]["id"], batch["id"], quantity=5,
                reason="SPILLAGE"),
            env["pch"]), 201)
        assert entry["recorded_by_cook_id"] == env["prep_cook"]["id"]
        assert entry["status"] == "RECORDED"


class TestPrepListAutoInProgress:
    def test_first_prepped_batch_advances_parent_list(self, api):
        """PRD section 3.4: "Once a batch under a locked list is first marked
        prepped, the list advances on its own from `LOCKED` to `IN_PROGRESS`;
        once every child batch has reached a terminal state — `DEPLETED`,
        `EXPIRED`, `WASTED`, or `CANCELLED` — the list completes itself,
        moving from `IN_PROGRESS` to `COMPLETED`."
        PRD section 3.6: "Marking prepped stamps `produced_at` with the
        logical clock's current instant and computes `expires_at` as
        `produced_at` plus the item's `shelf_life_hours`."

        Design: Corner/state_machines/prep_list_auto_in_progress_on_first_prepped_batch
        """
        set_clock("2026-09-01T08:00:00Z")
        env = _locked_list_env(api, quantity_per_portion=2, expected_count=10)
        batch = create_prep_batch(
            env["prep_list"]["id"], env["item"]["id"], env["station"]["id"],
            env["prep_cook"]["id"], 20)
        prepped = validate_success(api.mark_prepped(batch["id"], env["pch"]))
        assert prepped["status"] == "PREPPED"
        assert _iso_instant(prepped["produced_at"]) == _iso_instant(
            "2026-09-01T08:00:00Z")
        pl_now = validate_success(
            api.get_prep_list(env["prep_list"]["id"], env["mh"]))
        assert pl_now["status"] == "IN_PROGRESS"
