"""Arithmetic at its awkward edges: empty sets, caps, orderings and waterfalls.

Every scenario here is chosen so that a plausible shortcut gives a different number: an
empty denominator, a multiplier that outruns its cap, a chronology that disagrees with
insertion order, a waterfall that must skip two full lots, and a failure list whose wire
order is not its evaluation order.
"""

from test_helpers import assertions
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success

WINDOW_END = "2026-08-01T00:00:00Z"
WINDOW_START = "2026-05-03T00:00:00Z"


def test_01_an_unreferred_facility_reports_zeroes_rather_than_dividing_by_zero(api):
    """Both derived rates have an empty denominator, and both come back as 0.

    The PRD states: "`missed_treatments_per_referral_x100` is the raw in-window missed
    count multiplied by 100 and divided by the in-window referral volume, rounded half up
    to a whole number; it is reported as 0 when the referral volume is 0 rather than
    dividing by zero."

    It also states: "the rate is likewise reported as 0 when that denominator is 0."

    And it states: "The view also echoes `window_start` — the instant ninety days before
    the clock — and `window_end` — the clock itself — as ISO 8601 instants, so a caller can
    see exactly which referrals were in scope."

    The read is pure — the PRD states "It recomputes nothing and persists nothing, so two
    consecutive calls against an unchanged clock return byte-identical bodies" — so
    `last_scored_at` is still null afterwards and the facility's version has not moved.

    Design: Corner/calculations/partnership_metrics_are_zero_for_a_facility_with_no_referrals
    """
    fx.reset_clock(api)
    facility = fx.seed_facility(api)

    response = api.get_facility_partnership_metrics(facility["id"], fx.COORDINATOR)
    metrics = validate_success(response)
    assertions.assert_partnership_metrics(metrics)
    assert response.json()["response_type"] == "object"

    assert metrics["facility_id"] == facility["id"]
    assert metrics["partnership_score"] == 100
    assert metrics["partnership_tier"] == "SILVER"
    assert metrics["contract_status"] == "ACTIVE"
    assert metrics["referral_volume_window"] == 0
    assert metrics["raw_missed_count_window"] == 0
    assert metrics["grace_credit_window"] == 0
    assert metrics["adjusted_missed_count_window"] == 0
    assert metrics["same_day_honored_window"] == 0
    assert metrics["missed_treatments_per_referral_x100"] == 0
    assert metrics["same_day_honor_rate_pct"] == 0
    assert metrics["last_scored_at"] is None
    assertions.assert_instant_equals(metrics["window_end"], WINDOW_END, "window_end")
    assertions.assert_instant_equals(metrics["window_start"], WINDOW_START, "window_start")

    repeat = validate_success(
        api.get_facility_partnership_metrics(facility["id"], fx.COORDINATOR)
    )
    assert repeat == metrics

    settled = fx.read_facility(api, facility["id"])
    assert settled["last_scored_at"] is None
    assertions.assert_version_unchanged(facility, settled)


READING_A_AT = "2026-07-25T08:00:00Z"
READING_B_AT = "2026-07-26T08:00:00Z"


def _two_benign_accesses_with_three_and_four_missed_treatments(api):
    """One facility, two IN_USE accesses at a flow of 900, and two referrals over the cap.

    Every scoring component except the missed-treatment burden is deliberately zero: a
    flow of 900 is neither below 600 nor below 800, a venous pressure of 100 is under 150
    and a recirculation of 2.0 is under 10.0, so the score each referral earns is its
    missed-treatment contribution and nothing else.
    """
    facility = fx.seed_facility(api)
    patient = fx.seed_patient(api, facility["id"])
    facility_headers = fx.make_facility_coordinator_headers(facility["id"])

    access_a = fx.seed_access_in_use(
        api,
        patient["id"],
        access_type="AVG",
        laterality="LEFT",
        site="FOREARM",
        placed_on="2026-03-01",
    )
    access_b = fx.seed_access_in_use(
        api,
        patient["id"],
        access_type="AVF",
        laterality="RIGHT",
        site="UPPER_ARM",
        placed_on="2026-03-10",
    )
    for access, reading_at in ((access_a, READING_A_AT), (access_b, READING_B_AT)):
        fx.seed_reading(
            api,
            access["id"],
            facility["id"],
            reading_at,
            headers=facility_headers,
            access_flow_ml_min=900,
            venous_pressure_mmhg=100,
            recirculation_pct=2.0,
            kind="ROUTINE",
        )

    referral_a = fx.seed_referral(
        api,
        access_a["id"],
        facility["id"],
        headers=facility_headers,
        suspected_problem="STENOSIS",
        clinical_narrative="three treatments missed on this graft",
        missed_treatment_count=3,
    )
    referral_b = fx.seed_referral(
        api,
        access_b["id"],
        facility["id"],
        headers=facility_headers,
        suspected_problem="STENOSIS",
        clinical_narrative="four treatments missed on this fistula",
        missed_treatment_count=4,
    )
    return facility, referral_a, referral_b


def test_02_the_fourth_missed_treatment_earns_nothing_because_the_cap_binds(api):
    """Three misses and four misses produce the same triage score.

    The PRD states: "the missed-treatment burden contributes six points per missed
    treatment, capped at 18 points — which is to say the cap binds from the fourth missed
    treatment onward."

    It also states: "When exactly one reading qualifies, `triage_variant` is
    `ABSOLUTE_BASED`. There is no trend component at all — trend points are 0 — and the
    absolute-level component is doubled: 40 points if the latest reading's
    `access_flow_ml_min` is below 600 millilitres per minute, otherwise 20 points if it is
    below 800, otherwise none."

    Six times three is exactly the cap and six times four overshoots it, so an
    implementation that multiplied without clamping would score the second referral 24.
    Both scores band identically — the PRD states "`urgency` is then banded off the score:
    `SAME_DAY` when `triage_score` is 70 or above, otherwise `NEXT_DAY` when it is 45 or
    above, otherwise `ROUTINE`" — so the cap is visible only in `triage_score` itself.

    Design: Corner/calculations/triage_missed_treatment_component_is_capped_at_eighteen
    """
    _facility, referral_a, referral_b = (
        _two_benign_accesses_with_three_and_four_missed_treatments(api)
    )

    triaged_a = fx.triage(api, referral_a["id"])
    assert triaged_a["triage_variant"] == "ABSOLUTE_BASED"
    assert triaged_a["triage_score"] == 18
    assert triaged_a["urgency"] == "ROUTINE"
    assert triaged_a["missed_treatment_count"] == 3

    triaged_b = fx.triage(api, referral_b["id"])
    assert triaged_b["triage_variant"] == "ABSOLUTE_BASED"
    assert triaged_b["triage_score"] == 18
    assert triaged_b["urgency"] == "ROUTINE"
    assert triaged_b["missed_treatment_count"] == 4


def test_03_the_capped_burden_still_reaches_the_facility_score_uncapped(api):
    """The triage cap is local to the referral; the partnership window sums the raw counts.

    The PRD states: "`referral_volume_window` is the count of those referrals and
    `raw_missed_count_window` is the sum of their `missed_treatment_count` values."

    It also states that the grace credit is the in-window referral volume multiplied by the
    rate for the tier read in Step A — "one fifth for a `GOLD` partner, one tenth for a
    `SILVER` partner, and nothing at all for a `WATCH` partner" — and that the product is
    taken to its floor, so two referrals at the silver rate earn no credit at all.

    And it states: "The score starts at 100, loses four points for each adjusted missed
    treatment, gains three points for each honoured same-day case, and is then clamped into
    the range 0 to 100 inclusive."

    Seven raw misses therefore cost 28 points and the facility settles at 72, which keeps
    it above the `ACTIVE` floor of 70 — so no posture drop interferes with either triage.

    Design: Corner/calculations/triage_missed_treatment_component_is_capped_at_eighteen
    """
    facility, referral_a, referral_b = (
        _two_benign_accesses_with_three_and_four_missed_treatments(api)
    )

    fx.triage(api, referral_a["id"])
    fx.triage(api, referral_b["id"])

    scored = fx.read_facility(api, facility["id"])
    assert scored["referral_volume_window"] == 2
    assert scored["raw_missed_count_window"] == 7
    assert scored["grace_credit_window"] == 0
    assert scored["adjusted_missed_count_window"] == 7
    assert scored["same_day_honored_window"] == 0
    assert scored["partnership_score"] == 72
    assert scored["partnership_tier"] == "SILVER"
    assert scored["contract_status"] == "ACTIVE"
    assertions.assert_instant_equals(
        scored["last_scored_at"], fx.CLOCK_STARTUP_UTC, "last_scored_at"
    )

    metrics = validate_success(
        api.get_facility_partnership_metrics(facility["id"], fx.ADMIN)
    )
    assert metrics["raw_missed_count_window"] == 7
    assert metrics["missed_treatments_per_referral_x100"] == 350
    assert metrics["same_day_honor_rate_pct"] == 0


LATE_READING_AT = "2026-07-28T08:00:00Z"
EARLY_READING_AT = "2026-07-20T08:00:00Z"


def test_04_the_backfilled_reading_is_previous_even_though_it_was_posted_last(api):
    """Chronology beats insertion order, and the score doubles because of it.

    The PRD states: "The qualifying readings are ordered by `reading_at` ascending, with
    `created_at` ascending as the tie-break and never by `id`; the **latest** reading is the
    last element of that ordering and the **previous** reading is the one immediately before
    it."

    It also states: "Trend points are that percentage multiplied by a weight of 1.2, rounded
    half up to a whole number, floored at 0 so an improving access earns nothing, and then
    capped at 40."

    And it states: "The `kind` value has no effect on triage scoring — a `ROUTINE` reading
    and an `URGENT` one carry identical weight, and the only thing that matters for scoring
    is whether the reading falls inside the lookback window."

    The reading dated 2026-07-28 is created first and the one dated 2026-07-20 second, so an
    implementation ordering by `created_at` would read the decline backwards, floor the trend
    component at 0 and land the referral in ROUTINE on a score of 12. Ordered by
    `reading_at`, the flow falls from 1000 to 700 — a 30.0 per cent decline worth 36 points —
    and the latest flow of 700 adds the 12-point band, for 48 and NEXT_DAY.

    Design: Corner/calculations/triage_trend_uses_reading_at_order_not_creation_order
    """
    facility = fx.seed_facility(api)
    patient = fx.seed_patient(api, facility["id"])
    facility_headers = fx.make_facility_coordinator_headers(facility["id"])
    access = fx.seed_access_in_use(
        api,
        patient["id"],
        access_type="AVG",
        laterality="LEFT",
        site="FOREARM",
        placed_on="2026-03-01",
    )

    late = fx.seed_reading(
        api,
        access["id"],
        facility["id"],
        LATE_READING_AT,
        headers=facility_headers,
        access_flow_ml_min=700,
        venous_pressure_mmhg=100,
        recirculation_pct=2.0,
        kind="ROUTINE",
    )
    early = fx.seed_reading(
        api,
        access["id"],
        facility["id"],
        EARLY_READING_AT,
        headers=facility_headers,
        access_flow_ml_min=1000,
        venous_pressure_mmhg=100,
        recirculation_pct=2.0,
        kind="URGENT",
    )
    assert late["access_flow_ml_min"] == 700
    assert early["access_flow_ml_min"] == 1000

    referral = fx.seed_referral(
        api,
        access["id"],
        facility["id"],
        headers=facility_headers,
        suspected_problem="STENOSIS",
        clinical_narrative="baseline flow backfilled after the fact",
        missed_treatment_count=0,
    )
    triaged = fx.triage(api, referral["id"])

    assert triaged["triage_variant"] == "TREND_BASED"
    assert triaged["triage_score"] == 48
    assert triaged["urgency"] == "NEXT_DAY"
    assert triaged["status"] == "TRIAGED"

    readings, meta = validate_paginated(
        api.list_access_surveillance_readings(access["id"], fx.ADMIN)
    )
    assert meta["total_count"] == 2
    assert {reading["id"] for reading in readings} == {late["id"], early["id"]}


def _five_balloon_lots_and_a_thrombectomy(api):
    """A case on 2026-08-01 and five balloon lots, two of which must be skipped.

    A expires first with 2 units; B and C share an expiry and B is created first; D
    expires on the case date itself; E is quarantined after receipt. Only A, B and C are
    candidates, and together they hold ten units.
    """
    bundle = fx.seed_scheduled_case(
        api, procedure_type="THROMBECTOMY", suspected_problem="THROMBOSIS"
    )
    lot_a = fx.seed_lot(
        api, "BALLOON", received_quantity=2, unit_cost_cents=22000, expires_on="2026-09-30"
    )
    lot_b = fx.seed_lot(
        api, "BALLOON", received_quantity=3, unit_cost_cents=22000, expires_on="2026-10-31"
    )
    lot_c = fx.seed_lot(
        api, "BALLOON", received_quantity=5, unit_cost_cents=22000, expires_on="2026-10-31"
    )
    lot_d = fx.seed_lot(
        api, "BALLOON", received_quantity=10, unit_cost_cents=22000, expires_on="2026-08-01"
    )
    lot_e = fx.seed_lot(
        api, "BALLOON", received_quantity=10, unit_cost_cents=22000, expires_on="2026-12-31"
    )
    fx.quarantine_lot(api, lot_e["id"], quarantine_reason="held pending incoming inspection")
    return bundle, (lot_a, lot_b, lot_c, lot_d, lot_e)


def test_05_the_allocation_fills_each_lot_to_its_headroom_in_expiry_order(api):
    """Six units are drawn from three lots, and twenty units are deliberately not touched.

    The PRD states: "The candidate set is every lot of the requested type whose `status` is
    `AVAILABLE`, whose `expires_on` is strictly after the calendar date of the procedure's
    `scheduled_start`, and whose headroom is strictly positive; quarantined, expired and
    depleted lots are excluded even when they still hold units on hand."

    It also states: "Candidates are ordered by `expires_on` ascending with `created_at`
    ascending as the tie-break, and `id` is never read."

    And it states: "Otherwise the server walks the ordered candidates taking from each the
    lesser of the units still outstanding and that lot's headroom, creating one device usage
    per lot it draws on with `state` of `RESERVED`, incrementing that lot's
    `quantity_reserved` by the amount taken and its `version` by one, and stopping as soon as
    the request is fully covered. The created usages are returned in the same
    first-expiry-first-out order."

    The lot expiring on the case date is skipped because the PRD requires the expiry to be
    strictly after that date, and the quarantined lot is skipped despite holding ten units;
    between them they would have covered the request twice over.

    Design: Corner/calculations/device_allocation_is_fefo_with_created_at_tiebreak_and_all_or_nothing
    """
    bundle, lots = _five_balloon_lots_and_a_thrombectomy(api)
    lot_a, lot_b, lot_c, lot_d, lot_e = lots

    response = api.create_device_allocation(
        bundle["procedure_id"], {"device_type": "BALLOON", "quantity": 6}, fx.COORDINATOR
    )
    usages = validate_success(response, 201)
    assert response.json()["response_type"] == "array"
    assert [(usage["device_lot_id"], usage["quantity"]) for usage in usages] == [
        (lot_a["id"], 2),
        (lot_b["id"], 3),
        (lot_c["id"], 1),
    ]
    for usage in usages:
        assertions.assert_device_usage(usage)
        assert usage["state"] == "RESERVED"
        assert usage["procedure_id"] == bundle["procedure_id"]
        assert usage["wasted_quantity"] == 0
        assert usage["consumed_at"] is None
        assert usage["released_at"] is None

    drained_a = fx.read_lot(api, lot_a["id"])
    assert drained_a["quantity_on_hand"] == 2
    assert drained_a["quantity_reserved"] == 2
    assert drained_a["status"] == "AVAILABLE"
    assertions.assert_lot_headroom(drained_a, 0)

    drained_b = fx.read_lot(api, lot_b["id"])
    assert drained_b["quantity_on_hand"] == 3
    assert drained_b["quantity_reserved"] == 3
    assertions.assert_lot_headroom(drained_b, 0)

    partial_c = fx.read_lot(api, lot_c["id"])
    assert partial_c["quantity_on_hand"] == 5
    assert partial_c["quantity_reserved"] == 1
    assertions.assert_lot_headroom(partial_c, 4)

    untouched_d = fx.read_lot(api, lot_d["id"])
    assert untouched_d["quantity_reserved"] == 0
    assert untouched_d["status"] == "AVAILABLE"
    assertions.assert_version_unchanged(lot_d, untouched_d)

    untouched_e = fx.read_lot(api, lot_e["id"])
    assert untouched_e["quantity_reserved"] == 0
    assert untouched_e["status"] == "QUARANTINED"


def test_06_a_short_or_empty_candidate_set_reserves_nothing_at_all(api):
    """The all-or-nothing rule, proved on an empty set and on a merely insufficient one.

    The PRD states: "If the candidate set is empty the call reserves nothing and is refused
    with `ERR_NO_ELIGIBLE_LOT`. If the candidates' aggregate headroom is less than the
    requested quantity the call again reserves nothing and is refused with
    `ERR_INSUFFICIENT_DEVICE_STOCK` — the allocation is all-or-nothing, never partial."

    No stent lot has ever been received, so the stent request meets the empty set. The
    hundred-unit balloon request meets the second rule: after the first allocation the only
    candidate left with positive headroom is the partly drawn lot, holding four units, since
    the two exhausted lots have dropped out of the candidate set by the strictly-positive
    headroom rule.

    Neither refusal writes anything: the partly drawn lot's `quantity_reserved` and `version`
    are exactly what the successful allocation left, and the case still carries three
    reservations and no more.

    Design: Corner/calculations/device_allocation_is_fefo_with_created_at_tiebreak_and_all_or_nothing
    """
    bundle, lots = _five_balloon_lots_and_a_thrombectomy(api)
    _lot_a, _lot_b, lot_c, _lot_d, _lot_e = lots

    validate_success(
        api.create_device_allocation(
            bundle["procedure_id"], {"device_type": "BALLOON", "quantity": 6}, fx.COORDINATOR
        ),
        201,
    )
    after_success = fx.read_lot(api, lot_c["id"])

    no_stents = api.create_device_allocation(
        bundle["procedure_id"], {"device_type": "STENT", "quantity": 1}, fx.COORDINATOR
    )
    validate_error(no_stents, "ERR_NO_ELIGIBLE_LOT", 422)

    too_many = api.create_device_allocation(
        bundle["procedure_id"], {"device_type": "BALLOON", "quantity": 100}, fx.COORDINATOR
    )
    validate_error(too_many, "ERR_INSUFFICIENT_DEVICE_STOCK", 409)

    settled = fx.read_lot(api, lot_c["id"])
    assert settled["quantity_reserved"] == 1
    assert settled["quantity_on_hand"] == 5
    assertions.assert_version_unchanged(after_success, settled)

    usages, meta = validate_paginated(
        api.list_device_usages(fx.ADMIN, {"procedure_id": bundle["procedure_id"]})
    )
    assert meta["total_count"] == 3
    assert [usage["state"] for usage in usages] == ["RESERVED", "RESERVED", "RESERVED"]


TARGET_PLACED_ON = "2026-07-25"


def test_07_all_five_failure_tokens_come_back_in_ascii_order(api):
    """DEPTH is evaluated third and reported first.

    The PRD states: "`readiness_met` is true only when all five criteria hold, and
    `readiness_failure_reasons` holds the failure tokens of exactly the criteria that failed,
    sorted in ascending ASCII order, and is an empty list on a passing check."

    It also states: "Measurements of exactly 6.0 millimetres diameter, exactly 600 millilitres
    per minute, exactly 6.0 millimetres depth, exactly day 42 and exactly two readings all
    **pass**; 5.9, 599, 6.1, day 41 and one reading all fail."

    And it states: "Every accepted check writes `last_check_at` to the clock, copies the three
    measurements into `last_diameter_mm`, `last_flow_ml_min` and `last_depth_mm`, writes the
    computed `days_since_placement`, and increments `maturation_check_count` by one".

    This check fails all five criteria at once — a diameter of 5.9, a flow of 599, a depth of
    6.1, a target placed seven days ago and no surveillance readings at all — which is the
    only configuration in which the ordering of the token list is fully observable.

    Design: Corner/calculations/maturation_failure_reasons_are_ascii_sorted_when_several_criteria_fail
    """
    facility = fx.seed_facility(api)
    patient = fx.seed_patient(api, facility["id"])
    catheter = fx.seed_catheter_in_use(api, patient["id"], placed_on="2026-05-01")
    target = fx.seed_access(
        api,
        patient["id"],
        access_type="AVF",
        laterality="LEFT",
        site="UPPER_ARM",
        placed_on=TARGET_PLACED_ON,
        predecessor_access_id=catheter["id"],
    )
    assert target["status"] == "PLANNED"

    plan = fx.seed_active_plan(
        api,
        patient["id"],
        catheter,
        target["id"],
        target_conversion_date="2026-10-01",
    )
    assert plan["status"] == "ACTIVE"
    assert plan["readiness_failure_reasons"] == []

    checked = fx.file_maturation_check(
        api, plan["id"], diameter_mm=5.9, flow_ml_min=599, depth_mm=6.1
    )
    assert checked["readiness_met"] is False
    assert checked["readiness_failure_reasons"] == [
        "DEPTH",
        "DIAMETER",
        "FLOW",
        "MATURATION_DAYS",
        "SURVEILLANCE_COUNT",
    ]
    assertions.assert_ascii_sorted(
        checked["readiness_failure_reasons"], "readiness_failure_reasons"
    )
    assert checked["status"] == "MATURATION_HOLD"
    assert checked["maturation_check_count"] == 1
    assert checked["days_since_placement"] == 7
    assert checked["last_diameter_mm"] == 5.9
    assert checked["last_flow_ml_min"] == 599
    assert checked["last_depth_mm"] == 6.1
    assert checked["converted_at"] is None
    assertions.assert_instant_equals(
        checked["last_check_at"], fx.CLOCK_STARTUP_UTC, "last_check_at"
    )

    assert fx.read_access(api, target["id"])["status"] == "PLANNED"
    assert fx.read_access(api, catheter["id"])["status"] == "IN_USE"
