"""The shelf ledger, the weighted escalation score, and the four-hop cascade a
completed stop sets off — plus the void that must undo it without drift.
"""

from test_helpers.assertions import (
    assert_account,
    assert_escalation_score,
    assert_par_unit_invariant,
    assert_site,
)
from test_helpers.fixtures import (
    ANCHOR_MONDAY,
    CATALOG_SPEC_COFFEE_CREAMER,
    CATALOG_SPEC_COFFEE_ONLY,
    CATALOG_SPEC_COFFEE_TEA,
    CATALOG_SPEC_THREE_ALLIED,
    complete_stop,
    create_asset,
    evaluate_posture,
    override_par_line,
    par_lines_by_label,
    place_asset_at_site,
    propose_adjustment,
    read_account,
    read_adjustment,
    read_route,
    read_site,
    read_visit,
    schedule_stop_with_lines,
    set_market_index,
    setup_planned_site,
    setup_second_site,
    void_visit,
)


def _flatten_par_to_twenty_eight(base, site, labels):
    """Pin the named par lines to a par of 28 units, a two-unit daily draw.

    A par of 28 over the fourteen-day cover period is exactly two units a day,
    so a week between stops models exactly fourteen units of consumption and the
    shelf arithmetic is exact rather than approximate.
    """
    rows = par_lines_by_label(site["id"], base["products"])
    for label in labels:
        override_par_line(rows[label]["id"], par_units=28, reorder_point_units=10)


def _two_escalating_break_rooms_with_an_open_proposal():
    """One customer, two rented break rooms, and one outstanding price proposal.

    Each break room takes a modest delivery on the anchor Monday and is then
    served again a fortnight later with nothing on the truck, which is exactly
    enough modelled consumption to empty both of its shelves.
    """
    base = setup_planned_site(clock=ANCHOR_MONDAY, catalog_spec=CATALOG_SPEC_COFFEE_TEA)
    site_two = setup_second_site(base)
    base["site_two"] = site_two

    for site, serial in ((base["site"], "SN-RENT-1"), (site_two, "SN-RENT-2")):
        asset = create_asset(base["model"]["id"], serial_number=serial)
        place_asset_at_site(site, asset["id"], terms_type="RENTAL", minimum_purchase_cents=0)

    set_market_index(2160000)
    base["adjustment"] = propose_adjustment(
        base["account"]["id"], effective_at="2026-09-01T00:00:00Z"
    )

    windows = {
        "a": ("09:00:00", "09:45:00"),
        "b": ("10:30:00", "11:15:00"),
    }
    for key, site in (("a", base["site"]), ("b", site_two)):
        start, end = windows[key]
        first = schedule_stop_with_lines(
            base,
            {"COFFEE": 20, "TEA": 6},
            site=site,
            window_start=f"2026-08-03T{start}Z",
            window_end=f"2026-08-03T{end}Z",
        )
        complete_stop(base, first, {"COFFEE": 20, "TEA": 6}, complete_at="2026-08-03T11:15:00Z")

    base["second_stops"] = {}
    for key, site in (("a", base["site"]), ("b", site_two)):
        start, end = windows[key]
        base["second_stops"][key] = schedule_stop_with_lines(
            base,
            {"COFFEE": 1, "TEA": 1},
            site=site,
            window_start=f"2026-08-17T{start}Z",
            window_end=f"2026-08-17T{end}Z",
        )
    return base


def test_completion_cascades_from_the_shelf_to_the_deferred_price_proposal():
    """Emptying the second break room's shelves escalates that site, carries the
    account to risk, and freezes the outstanding price negotiation — all before
    the completion response comes back.

    "**Cascade hop two — the site posture.** The site's `escalation_score` is
    recomputed from the new shelf state, and if it crosses the threshold the site
    moves `ACTIVE` → `ESCALATED`. **Hop three** recomputes the owning account's
    `escalated_site_count`, which may carry the account `ACTIVE` → `AT_RISK`.
    **Hop four** defers every `PROPOSED` price adjustment of that account. All
    four hops complete before the response is returned."

    "The **stockout count** is the number of par lines of the site whose
    `on_hand_units` is exactly 0 **and** whose `cumulative_delivered_units` is
    above 0 — a line that has never been delivered to at all is merely unstocked,
    not a stockout, which is why a freshly planned site never escalates on its
    own."

    "If the recomputed count reaches 2 or more and the account is `ACTIVE`, the
    account moves `ACTIVE` → `AT_RISK`, increments its `version` by 1, and — as
    the fourth hop of the replenishment cascade — moves every price adjustment of
    that account currently in `PROPOSED` to `DEFERRED`."

    Design: Difficulty/transitive_cascade/visit_completion_cascades_par_stockout_to_site_to_account_to_deferred_adjustment
    """
    base = _two_escalating_break_rooms_with_an_open_proposal()

    complete_stop(
        base, base["second_stops"]["a"], {"COFFEE": 0, "TEA": 0}, complete_at="2026-08-17T11:15:00Z"
    )
    triggering = complete_stop(
        base, base["second_stops"]["b"], {"COFFEE": 0, "TEA": 0}, complete_at="2026-08-17T11:15:00Z"
    )
    assert triggering["visit_status"] == "COMPLETED"
    assert triggering["shortfall_flag"] is True

    rows = par_lines_by_label(base["site_two"]["id"], base["products"])
    for label, delivered in (("COFFEE", 20), ("TEA", 6)):
        row = rows[label]
        assert_par_unit_invariant(row)
        assert row["cumulative_delivered_units"] == delivered
        assert row["cumulative_consumed_units"] == delivered
        assert row["on_hand_units"] == 0
        assert row["stock_status"] == "STOCKOUT"
        assert row["last_service_at"] == "2026-08-17T10:30:00Z"

    site_two = read_site(base["site_two"]["id"])
    assert_site(site_two)
    # Two stockout lines at 20.0 points each land exactly on the threshold.
    assert_escalation_score(site_two, stockouts=2, below_reorder=0, overdue_descales=0, missed_visits=0)
    assert float(site_two["escalation_score"]) == 40.0
    assert site_two["service_posture"] == "ESCALATED"
    assert site_two["consecutive_shortfall_visit_count"] == 1

    account = read_account(base["account"]["id"])
    assert_account(account)
    assert account["escalated_site_count"] == 2
    assert account["program_posture"] == "AT_RISK"

    adjustment = read_adjustment(base["adjustment"]["id"])
    assert adjustment["adj_status"] == "DEFERRED"
    # A deferral changes no figure on the adjustment.
    assert adjustment["adjustment_pct_bps"] == 480
    assert adjustment["movement_bps"] == 800
    assert adjustment["revision_count"] == 0


def test_one_escalated_break_room_is_not_enough_to_freeze_the_negotiation():
    """With only the first break room escalated the account stays open and the
    proposal stays live, which is what makes the second escalation the trigger.

    "Two escalated sites is the trigger in both directions, and the comparison is
    inclusive going up (two escalated sites is enough) and strict coming down (one
    escalated site restores the account)."

    "The **below-reorder count** is the number of par lines whose `on_hand_units`
    is above 0 and at or below `reorder_point_units`."

    "A site moves `ACTIVE` → `ESCALATED` when its recomputed score is at or above
    40.0 and it was `ACTIVE`; it moves `ESCALATED` → `ACTIVE` when its recomputed
    score is strictly below 40.0 and it was `ESCALATED`."

    Design: Difficulty/transitive_cascade/visit_completion_cascades_par_stockout_to_site_to_account_to_deferred_adjustment
    """
    base = _two_escalating_break_rooms_with_an_open_proposal()

    # Only the first break room is emptied.
    complete_stop(
        base, base["second_stops"]["a"], {"COFFEE": 0, "TEA": 0}, complete_at="2026-08-17T11:15:00Z"
    )

    site_one = read_site(base["site"]["id"])
    assert float(site_one["escalation_score"]) == 40.0
    assert site_one["service_posture"] == "ESCALATED"

    # The second break room has taken its delivery and is merely running low.
    site_two = read_site(base["site_two"]["id"])
    low_rows = par_lines_by_label(base["site_two"]["id"], base["products"])
    assert low_rows["COFFEE"]["stock_status"] == "LOW"
    assert low_rows["TEA"]["stock_status"] == "LOW"
    assert_escalation_score(
        site_two, stockouts=0, below_reorder=2, overdue_descales=0, missed_visits=0
    )
    assert float(site_two["escalation_score"]) == 15.0
    assert site_two["service_posture"] == "ACTIVE"

    account = read_account(base["account"]["id"])
    assert account["escalated_site_count"] == 1
    assert account["program_posture"] == "ACTIVE"

    adjustment = read_adjustment(base["adjustment"]["id"])
    assert adjustment["adj_status"] == "PROPOSED"
    assert adjustment["adjustment_pct_bps"] == 480


def _progression_site(catalog_spec, flattened_labels):
    """A planned break room whose named par lines draw two units a day."""
    base = setup_planned_site(clock=ANCHOR_MONDAY, catalog_spec=catalog_spec)
    _flatten_par_to_twenty_eight(base, base["site"], flattened_labels)
    return base


def test_escalation_score_climbs_to_exactly_forty_and_escalates_there():
    """Three stops walk the score from nothing, through a low-shelf reading, to
    exactly the threshold — where the comparison is inclusive and the break room
    escalates.

    "The raw score is the stockout count multiplied by 20.0, plus the
    below-reorder count multiplied by 7.5, plus the overdue-descale count
    multiplied by 15.0, plus the missed-visit count multiplied by 10.0."

    "The comparison against 40.0 is exact: a score of 39.5 stays `ACTIVE`, and a
    score of exactly 40.0 escalates."

    "The modelled consumption is the daily draw multiplied by the elapsed days,
    rounded down to whole units, and then clamped to the shelf quantity: the
    consumed quantity is the smaller of the current `on_hand_units` and that
    modelled figure, so the shelf can never be driven negative."

    Design: Difficulty/boundary_precision_check/escalation_score_progression_reaching_exactly_the_40_point_threshold
    """
    base = _progression_site(CATALOG_SPEC_COFFEE_CREAMER, ("COFFEE", "CREAMER"))
    site_id = base["site"]["id"]

    first = schedule_stop_with_lines(base, {"COFFEE": 20, "CREAMER": 20})
    complete_stop(base, first, {"COFFEE": 20, "CREAMER": 20}, complete_at="2026-08-03T09:30:00Z")
    stocked = read_site(site_id)
    assert float(stocked["escalation_score"]) == 0.0
    assert stocked["service_posture"] == "ACTIVE"
    rows = par_lines_by_label(site_id, base["products"])
    assert rows["COFFEE"]["stock_status"] == "IN_STOCK"
    assert rows["COFFEE"]["on_hand_units"] == 20

    # A week later with an empty truck: two units a day for seven days.
    second = schedule_stop_with_lines(
        base,
        {"COFFEE": 1, "CREAMER": 1},
        window_start="2026-08-10T09:00:00Z",
        window_end="2026-08-10T09:45:00Z",
    )
    complete_stop(base, second, {"COFFEE": 0, "CREAMER": 0}, complete_at="2026-08-10T09:30:00Z")
    low = read_site(site_id)
    rows = par_lines_by_label(site_id, base["products"])
    for label in ("COFFEE", "CREAMER"):
        assert rows[label]["cumulative_consumed_units"] == 14
        assert rows[label]["on_hand_units"] == 6
        assert rows[label]["stock_status"] == "LOW"
    assert_escalation_score(low, stockouts=0, below_reorder=2, overdue_descales=0, missed_visits=0)
    assert float(low["escalation_score"]) == 15.0
    assert low["service_posture"] == "ACTIVE"

    # A third week empties both shelves, and the modelled draw is clamped.
    third = schedule_stop_with_lines(
        base,
        {"COFFEE": 28, "CREAMER": 28},
        window_start="2026-08-17T09:00:00Z",
        window_end="2026-08-17T09:45:00Z",
    )
    complete_stop(base, third, {}, complete_at="2026-08-17T09:30:00Z")
    escalated = read_site(site_id)
    rows = par_lines_by_label(site_id, base["products"])
    for label in ("COFFEE", "CREAMER"):
        assert_par_unit_invariant(rows[label])
        # The modelled fourteen units are clamped to the six on the shelf.
        assert rows[label]["cumulative_consumed_units"] == 20
        assert rows[label]["cumulative_delivered_units"] == 20
        assert rows[label]["on_hand_units"] == 0
        assert rows[label]["stock_status"] == "STOCKOUT"
    assert_escalation_score(
        escalated, stockouts=2, below_reorder=0, overdue_descales=0, missed_visits=0
    )
    assert float(escalated["escalation_score"]) == 40.0
    assert escalated["service_posture"] == "ESCALATED"

    # One escalated break room is not two, so the customer stays where it was.
    account = read_account(base["account"]["id"])
    assert account["escalated_site_count"] == 1
    assert account["program_posture"] != "AT_RISK"


def test_a_score_of_thirty_five_stays_active_and_the_recompute_is_a_no_op():
    """One stockout beside two low shelves weighs 35.0, which is strictly below
    the threshold, and a direct recompute at that score changes nothing at all.

    "Two stockouts alone (40.0) escalate a site; one stockout plus two
    below-reorder lines (35.0) do not."

    "The **stockout count** is the number of par lines of the site whose
    `on_hand_units` is exactly 0 **and** whose `cumulative_delivered_units` is
    above 0 — a line that has never been delivered to at all is merely unstocked,
    not a stockout, which is why a freshly planned site never escalates on its
    own."

    "Doing so writes the freshly computed `escalation_score`, applies the
    `ACTIVE` ↔ `ESCALATED` transition in whichever direction the score demands,
    leaves the posture unchanged when neither direction applies (an idempotent
    no-op), recomputes the account's `escalated_site_count`, and may therefore
    move the account `ACTIVE` → `AT_RISK` — deferring its `PROPOSED` adjustments
    — or `AT_RISK` → `ACTIVE`, restoring them."

    "The site's `version` increments by 1 **only** when the service posture
    actually changed."

    Design: Difficulty/boundary_precision_check/escalation_score_progression_reaching_exactly_the_40_point_threshold
    """
    base = _progression_site(CATALOG_SPEC_THREE_ALLIED, ("COFFEE", "CREAMER", "TEA"))
    site_id = base["site"]["id"]

    first = schedule_stop_with_lines(base, {"COFFEE": 14, "CREAMER": 20, "TEA": 20})
    complete_stop(
        base, first, {"COFFEE": 14, "CREAMER": 20, "TEA": 20}, complete_at="2026-08-03T09:30:00Z"
    )
    second = schedule_stop_with_lines(
        base,
        {"COFFEE": 1, "CREAMER": 1, "TEA": 1},
        window_start="2026-08-10T09:00:00Z",
        window_end="2026-08-10T09:45:00Z",
    )
    complete_stop(
        base, second, {"COFFEE": 0, "CREAMER": 0, "TEA": 0}, complete_at="2026-08-10T09:30:00Z"
    )

    rows = par_lines_by_label(site_id, base["products"])
    # Fourteen delivered, fourteen drunk: empty, and it counts as a stockout.
    assert rows["COFFEE"]["on_hand_units"] == 0
    assert rows["COFFEE"]["cumulative_delivered_units"] == 14
    assert rows["COFFEE"]["stock_status"] == "STOCKOUT"
    for label in ("CREAMER", "TEA"):
        assert rows[label]["on_hand_units"] == 6
        assert rows[label]["stock_status"] == "LOW"
    # The pantry line was never on a stop, so it is unstocked rather than out.
    assert rows["PANTRY"]["on_hand_units"] == 0
    assert rows["PANTRY"]["cumulative_delivered_units"] == 0
    assert rows["PANTRY"]["stock_status"] == "STOCKOUT"

    site = read_site(site_id)
    assert_escalation_score(site, stockouts=1, below_reorder=2, overdue_descales=0, missed_visits=0)
    assert float(site["escalation_score"]) == 35.0
    assert site["service_posture"] == "ACTIVE"

    recomputed = evaluate_posture(site_id)
    assert float(recomputed["escalation_score"]) == 35.0
    assert recomputed["service_posture"] == "ACTIVE"
    # Neither direction applied, so the version stood still.
    assert recomputed["version"] == site["version"]
    assert read_account(base["account"]["id"])["escalated_site_count"] == 0


def _two_stops_on_a_flattened_coffee_line():
    """One break room served twice a week apart, the second stop short-delivered."""
    base = _progression_site(CATALOG_SPEC_COFFEE_ONLY, ("COFFEE",))
    first = schedule_stop_with_lines(base, {"COFFEE": 28})
    base["first"] = complete_stop(base, first, {"COFFEE": 20}, complete_at="2026-08-03T09:30:00Z")
    second = schedule_stop_with_lines(
        base,
        {"COFFEE": 28},
        window_start="2026-08-10T09:00:00Z",
        window_end="2026-08-10T09:45:00Z",
    )
    base["second"] = complete_stop(base, second, {"COFFEE": 8}, complete_at="2026-08-10T09:30:00Z")
    return base


def test_voiding_a_stop_reverses_the_ledger_and_the_route_minutes_exactly():
    """The void subtracts precisely what the completion added: both cumulative
    counters, the shelf quantity, the service stamp and the route's minutes all
    return to their pre-stop readings.

    "Every par line the visit touched has both cumulative counters **reduced** by
    that line's recorded amounts — `cumulative_delivered_units` by the line's
    delivered quantity and `cumulative_consumed_units` by the line's consumed
    quantity — and `on_hand_units` re-derived from them, so the unit invariant
    holds with no drift."

    "Each affected par line's `last_service_at` reverts to the `window_start` of
    the most recent remaining `COMPLETED` visit that touched that line, or, if none
    remains, to that par line's own `created_at`."

    "The route's `booked_minutes_total` is reduced by the visit's
    `planned_minutes`."

    "Finally the site's `consecutive_shortfall_visit_count` is recomputed over the
    remaining `COMPLETED` visits and its `escalation_score` is recomputed, which
    may move the site `ESCALATED` → `ACTIVE` and, in turn, the account `AT_RISK` →
    `ACTIVE` with its deferred adjustments restored to `PROPOSED`."

    Design: Difficulty/compensating_invariant/visit_void_restores_the_par_unit_ledger_and_route_minutes_without_drift
    """
    base = _two_stops_on_a_flattened_coffee_line()
    site_id = base["site"]["id"]
    route_id = base["route"]["id"]

    before = par_lines_by_label(site_id, base["products"])["COFFEE"]
    assert_par_unit_invariant(before)
    assert before["cumulative_delivered_units"] == 28
    assert before["cumulative_consumed_units"] == 14
    assert before["on_hand_units"] == 14
    assert before["last_service_at"] == "2026-08-10T09:00:00Z"
    assert read_route(route_id)["booked_minutes_total"] == 90
    assert read_site(site_id)["consecutive_shortfall_visit_count"] == 2

    # The stop's own line records exactly what the void has to undo.
    line = base["second"]["lines"][0]
    assert line["consumed_units"] == 14
    assert line["delivered_units"] == 8
    assert line["resulting_on_hand_units"] == 14
    assert line["effective_unit_price_micros"] == 4500000

    voided = void_visit(base["second"]["id"], "Recorded against the wrong stop")
    assert voided["visit_status"] == "VOIDED"
    assert voided["void_reason"] == "Recorded against the wrong stop"

    after = par_lines_by_label(site_id, base["products"])["COFFEE"]
    assert_par_unit_invariant(after)
    assert after["cumulative_delivered_units"] == 20
    assert after["cumulative_consumed_units"] == 0
    assert after["on_hand_units"] == 20
    assert after["stock_status"] == "IN_STOCK"
    # The only remaining completed stop is the one on the anchor Monday.
    assert after["last_service_at"] == "2026-08-03T09:00:00Z"

    assert read_route(route_id)["booked_minutes_total"] == 45
    recovered = read_site(site_id)
    # Only the first stop remains, and it was short too.
    assert recovered["consecutive_shortfall_visit_count"] == 1
    assert float(recovered["escalation_score"]) == 0.0
    assert recovered["service_posture"] == "ACTIVE"


def test_replaying_the_voided_stop_reproduces_the_identical_ledger():
    """Re-running the same window after the void lands on exactly the figures the
    voided stop had produced, which is what "no drift" means.

    "**Voiding a completed stop** is the compensating action, reserved to
    `ProgramAdmin`, and it exists precisely because the shelf ledger must never
    drift."

    "The identity that `on_hand_units` always equals
    `cumulative_delivered_units` minus `cumulative_consumed_units` is an invariant
    of this system and must hold before and after every operation, with no drift."

    "Minutes are released immediately in both directions: a visit that is
    `CANCELLED` frees its minutes, and a visit that is `VOIDED` after completion
    frees them too, so neither status ever contributes to load."

    Design: Difficulty/compensating_invariant/visit_void_restores_the_par_unit_ledger_and_route_minutes_without_drift
    """
    base = _two_stops_on_a_flattened_coffee_line()
    site_id = base["site"]["id"]
    route_id = base["route"]["id"]
    void_visit(base["second"]["id"], "Recorded against the wrong stop")

    # The freed minutes make the identical window schedulable again.
    replay = schedule_stop_with_lines(
        base,
        {"COFFEE": 28},
        window_start="2026-08-10T09:00:00Z",
        window_end="2026-08-10T09:45:00Z",
    )
    replay = complete_stop(base, replay, {"COFFEE": 8}, complete_at="2026-08-10T09:30:00Z")

    row = par_lines_by_label(site_id, base["products"])["COFFEE"]
    assert_par_unit_invariant(row)
    assert row["cumulative_delivered_units"] == 28
    assert row["cumulative_consumed_units"] == 14
    assert row["on_hand_units"] == 14
    assert row["last_service_at"] == "2026-08-10T09:00:00Z"

    line = replay["lines"][0]
    assert line["consumed_units"] == 14
    assert line["delivered_units"] == 8
    assert line["resulting_on_hand_units"] == 14

    assert read_route(route_id)["booked_minutes_total"] == 90
    assert read_site(site_id)["consecutive_shortfall_visit_count"] == 2
    # The voided stop is still on the record and still contributes nothing.
    assert read_visit(base["second"]["id"])["visit_status"] == "VOIDED"
