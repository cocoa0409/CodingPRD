"""Vendor capacity, the hours ledger and the five-hop suspension cascade."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx

SO_RATING = {
    "crime_index": 90.0,
    "political_instability_index": 95.0,
    "medical_infrastructure_index": 20.0,
    "natural_hazard_index": 60.0,
}


def _leg_world(api, country_code=c.COUNTRY_PT, rating=None, **vendor_overrides):
    """A draft trip with one wide leg and one AVAILABLE vendor in the same country."""
    w = fx.bootstrap_world(api, country_code=country_code, rating=rating)
    dep = w.dep
    trip = fx.create_trip(api, dep, w.exec_id, w.ra_id)
    leg = fx.add_leg(
        api,
        dep,
        trip["id"],
        destination_country_code=country_code,
        arrive_at=c.TRIP_DEPART_AT,
        depart_at=c.TRIP_RETURN_AT,
    )
    w.trip_id = trip["id"]
    w.leg_id = leg["id"]
    w.vendor = fx.register_vendor(api, dep, country_code=country_code, **vendor_overrides)
    w.vendor_id = w.vendor["id"]
    return w


def _engage(api, w, starts_at, ends_at, version=None, purpose=None):
    return api.create_vendor_engagement(
        f.vendor_engagement_payload(
            w.vendor_id,
            w.leg_id,
            purpose or w.vendor["vendor_type"],
            starts_at,
            ends_at,
            fx.vendor_version(api, w.dep, w.vendor_id) if version is None else version,
        ),
        w.dep.mgr,
    )


def test_two_adjacent_engagements_both_fit_a_capacity_of_one(api):
    """A half-open window excludes its own end, so adjacency is not intersection.

    PRD §3.5: "And the vendor's aggregate capacity must not be exceeded: the count of that vendor's `ACTIVE` engagements whose half-open window from `starts_at` up to `ends_at` intersects the requested window must be strictly less than `max_concurrent_engagements`."

    Design: Difficulty/resource_temporal_overlap/vendor_capacity_counts_intersecting_engagements_and_allows_adjacent_ones
    """
    w = _leg_world(
        api,
        vendor_name="Liaison Lisboa",
        vendor_type=c.VENDOR_LOCAL_LIAISON,
        max_concurrent_engagements=1,
        sla_response_minutes=60,
        hourly_rate_cents=10_000,
        retainer_cents=50_000,
    )
    assert w.vendor["max_concurrent_engagements"] == 1
    a.assert_vendor_hours(w.vendor, 0)

    first = validate_success(
        _engage(api, w, "2026-09-10T08:00:00Z", "2026-09-10T12:00:00Z"), 201
    )
    second = validate_success(
        _engage(api, w, "2026-09-10T12:00:00Z", "2026-09-10T16:00:00Z"), 201
    )
    for row in (first, second):
        assert row["status"] == c.ENGAGEMENT_ACTIVE
        assert row["engagement_hours"] == 4
        a.assert_cents(row["engagement_cost_cents"], 90_000, "engagement_cost_cents")
        assert row["incident_id"] is None
        assert row["cancelled_reason"] is None

    a.assert_vendor_hours(fx.read_vendor(api, w.dep, w.vendor_id), 8)
    _rows, meta = validate_paginated(
        api.list_vendor_engagements(w.dep.mgr, vendor_id=w.vendor_id)
    )
    assert meta["total_count"] == 2


def test_a_candidate_straddling_the_seam_exceeds_a_capacity_of_one(api):
    """The count is an aggregate over both neighbours, and each alone was legal.

    PRD §3.5: "That is an aggregate check — each existing engagement is individually legal and only their collective count fails — and the rejection is `ERR_VENDOR_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/vendor_capacity_counts_intersecting_engagements_and_allows_adjacent_ones
    """
    w = _leg_world(
        api,
        vendor_name="Liaison Lisboa",
        vendor_type=c.VENDOR_LOCAL_LIAISON,
        max_concurrent_engagements=1,
        sla_response_minutes=60,
        hourly_rate_cents=10_000,
        retainer_cents=50_000,
    )
    fx.engage_vendor(
        api,
        w.dep,
        w.vendor_id,
        w.leg_id,
        c.VENDOR_LOCAL_LIAISON,
        "2026-09-10T08:00:00Z",
        "2026-09-10T12:00:00Z",
    )
    fx.engage_vendor(
        api,
        w.dep,
        w.vendor_id,
        w.leg_id,
        c.VENDOR_LOCAL_LIAISON,
        "2026-09-10T12:00:00Z",
        "2026-09-10T16:00:00Z",
    )
    version = fx.vendor_version(api, w.dep, w.vendor_id)

    straddling = _engage(
        api, w, "2026-09-10T11:00:00Z", "2026-09-10T13:00:00Z", version=version
    )
    validate_error(straddling, e.ERR_VENDOR_CAPACITY_EXCEEDED, 409)

    after = fx.read_vendor(api, w.dep, w.vendor_id)
    a.assert_vendor_hours(after, 8)
    assert after["version"] == version, "a rejected create advances nothing"
    _rows, meta = validate_paginated(
        api.list_vendor_engagements(w.dep.mgr, vendor_id=w.vendor_id)
    )
    assert meta["total_count"] == 2

    adjacent = validate_success(
        _engage(
            api, w, "2026-09-10T16:00:00Z", "2026-09-10T20:00:00Z", version=version
        ),
        201,
    )
    assert adjacent["status"] == c.ENGAGEMENT_ACTIVE
    assert adjacent["engagement_hours"] == 4
    a.assert_cents(adjacent["engagement_cost_cents"], 90_000, "engagement_cost_cents")
    a.assert_vendor_hours(fx.read_vendor(api, w.dep, w.vendor_id), 12)
    _rows, meta = validate_paginated(
        api.list_vendor_engagements(w.dep.mgr, vendor_id=w.vendor_id)
    )
    assert meta["total_count"] == 3


def _cascade_world(api):
    """An EXTREME SO trip driven to APPROVED/READY on a liaison engagement."""
    w = fx.bootstrap_world(api, country_code=c.COUNTRY_SO, rating=SO_RATING)
    dep = w.dep
    vendor = fx.register_vendor(
        api,
        dep,
        vendor_name="Mogadishu Liaison Group",
        vendor_type=c.VENDOR_LOCAL_LIAISON,
        country_code=c.COUNTRY_SO,
        max_concurrent_engagements=3,
        sla_response_minutes=120,
        hourly_rate_cents=20_000,
        retainer_cents=100_000,
    )
    trip = fx.create_trip(
        api,
        dep,
        w.exec_id,
        w.ra_id,
        insurance_policy_id=w.policy_id,
        primary_destination_country_code=c.COUNTRY_SO,
    )
    leg = fx.add_leg(
        api,
        dep,
        trip["id"],
        destination_country_code=c.COUNTRY_SO,
        arrive_at="2026-09-10T00:00:00Z",
        depart_at="2026-09-11T00:00:00Z",
    )
    w.assignment = fx.assign_detail(
        api,
        dep,
        leg["id"],
        dep.lead_id,
        c.DETAIL_LEAD_AGENT,
        "2026-09-10T00:00:00Z",
        "2026-09-11T00:00:00Z",
    )
    w.engagement = fx.engage_vendor(
        api,
        dep,
        vendor["id"],
        leg["id"],
        c.VENDOR_LOCAL_LIAISON,
        "2026-09-10T00:00:00Z",
        "2026-09-11T00:00:00Z",
    )
    fx.complete_required_advance_work(api, dep, leg["id"])
    # The briefing may only be acknowledged once the trip is pending a decision.
    fx.submit_trip(api, dep, trip["id"])
    fx.ack_briefing(api, w.exec_id, trip["id"])
    fx.decide_trip(api, dep, trip["id"], c.DECISION_APPROVE)
    w.trip = fx.decide_trip(
        api, dep, trip["id"], c.DECISION_APPROVE, headers=dep.officer
    )
    w.trip_id = trip["id"]
    w.leg_id = leg["id"]
    w.vendor_id = vendor["id"]
    return w


def test_suspending_a_vendor_cancels_its_engagement_and_clears_its_hours(api):
    """Hops one and two: the vendor closes and its live engagement is voided.

    PRD §3.5: "Hop one moves `activation_status` from `AVAILABLE` to `SUSPENDED`, stores the `suspension_reason` and increments the vendor's `version`."

    Design: Difficulty/transitive_cascade/vendor_suspension_cascades_five_hops_to_check_in_interval
    """
    w = _cascade_world(api)
    dep = w.dep

    a.assert_decimal_value(
        w.rating["composite_destination_score"], 83.50, "composite_destination_score"
    )
    assert w.rating["rating_band"] == c.BAND_EXTREME
    a.assert_cents(
        w.rating["insurance_required_coverage_cents"],
        500_000_000,
        "insurance_required_coverage_cents",
    )
    a.assert_trip_states(w.trip, c.APPROVAL_APPROVED, c.READINESS_READY)
    assert w.trip["required_approval_level"] == c.LEVEL_DIRECTOR_AND_COMPLIANCE
    assert w.trip["check_in_interval_hours"] == 4
    a.assert_cents(
        w.trip["provisional_security_cost_cents"],
        850_000,
        "provisional_security_cost_cents",
    )
    a.assert_vendor_hours(fx.read_vendor(api, dep, w.vendor_id), 24)
    assert fx.read_executive(api, dep, w.exec_id)["open_degraded_trip_count"] == 0

    reason = "Local licence revoked by host authorities"
    suspended = fx.suspend_vendor(api, dep, w.vendor_id, reason)
    assert suspended["activation_status"] == c.VENDOR_SUSPENDED_STATUS
    assert suspended["suspension_reason"] == reason
    a.assert_vendor_hours(suspended, 0)

    engagement = validate_success(
        api.get_vendor_engagement(w.engagement["id"], dep.mgr)
    )
    assert engagement["status"] == c.ENGAGEMENT_CANCELLED
    assert engagement["cancelled_reason"] == c.CANCELLED_REASON_VENDOR_SUSPENDED
    a.assert_cents(engagement["engagement_cost_cents"], 0, "engagement_cost_cents")


def test_the_suspension_cascade_reaches_the_check_in_cadence(api):
    """Hops three to five: the liaison item is un-recorded and the trip degrades.

    PRD §3.5: "Hop three reaches back into the itinerary: for each cancelled engagement whose `engagement_purpose` was `LOCAL_LIAISON`, `LOCAL_LIAISON` is **removed** from that leg's `completed_advance_items` and the leg's `advance_complete` is re-derived."

    Design: Difficulty/transitive_cascade/vendor_suspension_cascades_five_hops_to_check_in_interval
    """
    w = _cascade_world(api)
    dep = w.dep

    before = fx.read_leg(api, dep, w.leg_id)
    assert before["leg_risk_band"] == c.BAND_EXTREME
    assert before["required_advance_items"] == c.BAND_REQUIRED_ADVANCE_ITEMS[
        c.BAND_EXTREME
    ]
    assert before["advance_complete"] is True

    fx.suspend_vendor(api, dep, w.vendor_id, "Local licence revoked")

    leg = fx.read_leg(api, dep, w.leg_id)
    assert leg["completed_advance_items"] == [
        c.ITEM_ROUTE_SURVEY,
        c.ITEM_HOTEL_SURVEY,
        c.ITEM_HOSPITAL_SURVEY,
        c.ITEM_COMMS_TEST,
    ]
    assert leg["advance_complete"] is False
    assert leg["required_advance_items"] == c.BAND_REQUIRED_ADVANCE_ITEMS[
        c.BAND_EXTREME
    ], "the required set is derived from the band and did not move"

    trip = fx.read_trip(api, dep, w.trip_id)
    a.assert_trip_states(trip, c.APPROVAL_APPROVED, c.READINESS_DEGRADED)
    assert trip["check_in_interval_hours"] == 2
    assert fx.read_executive(api, dep, w.exec_id)["open_degraded_trip_count"] == 1

    a.assert_cents(
        trip["provisional_security_cost_cents"],
        850_000,
        "provisional_security_cost_cents",
    )
    a.assert_budget_ledger(
        fx.read_executive(api, dep, w.exec_id), committed=850_000, spent=0
    )
    assignment = validate_success(
        api.get_detail_assignment(w.assignment["id"], dep.mgr)
    )
    assert assignment["status"] == c.ASSIGNMENT_CONFIRMED
    a.assert_cents(assignment["cost_cents"], 270_000, "cost_cents")


def _hours_ledger_world(api):
    """One ACTIVE and one COMPLETED ground-security engagement on the same leg."""
    w = _leg_world(
        api,
        vendor_name="Guarda Atlantica",
        vendor_type=c.VENDOR_GROUND_SECURITY,
        max_concurrent_engagements=2,
        sla_response_minutes=45,
        hourly_rate_cents=10_000,
        retainer_cents=50_000,
    )
    dep = w.dep
    w.hours0 = w.vendor["committed_engagement_hours"]
    w.e1 = fx.engage_vendor(
        api,
        dep,
        w.vendor_id,
        w.leg_id,
        c.VENDOR_GROUND_SECURITY,
        "2026-09-10T08:00:00Z",
        "2026-09-10T12:00:00Z",
    )
    w.hours1 = fx.read_vendor(api, dep, w.vendor_id)["committed_engagement_hours"]
    w.e2 = fx.engage_vendor(
        api,
        dep,
        w.vendor_id,
        w.leg_id,
        c.VENDOR_GROUND_SECURITY,
        "2026-09-10T12:00:00Z",
        "2026-09-10T18:00:00Z",
    )
    w.hours2 = fx.read_vendor(api, dep, w.vendor_id)["committed_engagement_hours"]
    w.e2_completed = fx.complete_engagement(api, dep, w.e2["id"])
    w.hours3 = fx.read_vendor(api, dep, w.vendor_id)["committed_engagement_hours"]
    return w


def test_completing_an_engagement_releases_its_hours_but_not_its_cost(api):
    """The hours ledger walks 0, 4, 10, 4 while the completed cost stands still.

    PRD §3.5: "Completing an engagement moves it `ACTIVE → COMPLETED` and releases the vendor's capacity: `committed_engagement_hours` falls by that engagement's `engagement_hours` and the vendor's `version` increments."

    Design: Difficulty/compensating_invariant/vendor_suspension_restores_the_hours_ledger_without_touching_completed_rows
    """
    w = _hours_ledger_world(api)

    assert [w.hours0, w.hours1, w.hours2, w.hours3] == [0, 4, 10, 4]
    assert w.e1["engagement_hours"] == 4
    a.assert_cents(w.e1["engagement_cost_cents"], 90_000, "engagement_cost_cents")
    assert w.e2["engagement_hours"] == 6
    a.assert_cents(w.e2["engagement_cost_cents"], 110_000, "engagement_cost_cents")

    assert w.e2_completed["status"] == c.ENGAGEMENT_COMPLETED
    a.assert_cents(
        w.e2_completed["engagement_cost_cents"],
        110_000,
        "engagement_cost_cents after completion",
    )
    assert w.e1["status"] == c.ENGAGEMENT_ACTIVE


def test_suspension_restores_the_hours_ledger_without_touching_completed_rows(api):
    """The compensator debits only the ACTIVE row, so the ledger lands on zero.

    PRD §2.10: "For every vendor, `committed_engagement_hours` is the sum of `engagement_hours` over that vendor's engagements whose `status` is `ACTIVE`."

    Design: Difficulty/compensating_invariant/vendor_suspension_restores_the_hours_ledger_without_touching_completed_rows
    """
    w = _hours_ledger_world(api)
    dep = w.dep
    leg_before = fx.read_leg(api, dep, w.leg_id)

    reason = "licence lapsed in country"
    suspended = fx.suspend_vendor(api, dep, w.vendor_id, reason)
    assert suspended["activation_status"] == c.VENDOR_SUSPENDED_STATUS
    assert suspended["suspension_reason"] == reason
    a.assert_vendor_hours(suspended, 0)

    e1 = validate_success(api.get_vendor_engagement(w.e1["id"], dep.mgr))
    assert e1["status"] == c.ENGAGEMENT_CANCELLED
    assert e1["cancelled_reason"] == c.CANCELLED_REASON_VENDOR_SUSPENDED
    a.assert_cents(e1["engagement_cost_cents"], 0, "engagement_cost_cents")

    e2 = validate_success(api.get_vendor_engagement(w.e2["id"], dep.mgr))
    assert e2["status"] == c.ENGAGEMENT_COMPLETED
    a.assert_cents(e2["engagement_cost_cents"], 110_000, "engagement_cost_cents")
    assert e2["cancelled_reason"] is None

    leg_after = fx.read_leg(api, dep, w.leg_id)
    assert leg_after["completed_advance_items"] == leg_before["completed_advance_items"]
    assert leg_after["advance_complete"] == leg_before["advance_complete"]

    _rows, active_meta = validate_paginated(
        api.list_vendor_engagements(
            dep.mgr, vendor_id=w.vendor_id, status=c.ENGAGEMENT_ACTIVE
        )
    )
    assert active_meta["total_count"] == 0
    _rows, all_meta = validate_paginated(
        api.list_vendor_engagements(dep.mgr, vendor_id=w.vendor_id)
    )
    assert all_meta["total_count"] == 2, "the compensation cancels rows, never deletes"


def test_a_second_completion_would_drive_the_hours_ledger_negative(api):
    """The retry is refused, so the eight hours are debited exactly once.

    PRD §3.5: "Completing anything that is not `ACTIVE` is rejected with `ERR_ENGAGEMENT_INVALID_STATE`."

    Design: Corner/state_machines/complete_an_already_completed_engagement_returns_engagement_invalid_state
    """
    w = _leg_world(
        api,
        vendor_type=c.VENDOR_GROUND_SECURITY,
        max_concurrent_engagements=2,
        hourly_rate_cents=10_000,
        retainer_cents=50_000,
    )
    dep = w.dep
    engagement = fx.engage_vendor(
        api,
        dep,
        w.vendor_id,
        w.leg_id,
        c.VENDOR_GROUND_SECURITY,
        "2026-09-10T08:00:00Z",
        "2026-09-10T16:00:00Z",
    )
    completed = fx.complete_engagement(api, dep, engagement["id"])
    assert completed["status"] == c.ENGAGEMENT_COMPLETED
    assert completed["engagement_hours"] == 8
    a.assert_cents(completed["engagement_cost_cents"], 130_000, "engagement_cost_cents")

    retry = api.complete_vendor_engagement(engagement["id"], dep.mgr)
    validate_error(retry, e.ERR_ENGAGEMENT_INVALID_STATE, 409)

    a.assert_vendor_hours(fx.read_vendor(api, dep, w.vendor_id), 0)
    stored = validate_success(api.get_vendor_engagement(engagement["id"], dep.mgr))
    a.assert_cents(stored["engagement_cost_cents"], 130_000, "engagement_cost_cents")
    assert stored["version"] == completed["version"]


def test_a_second_suspension_is_refused_and_leaves_the_first_reason_standing(api):
    """Suspension is the entry point of a cascade, so it must not be re-runnable.

    PRD §3.5: "It requires a `suspension_reason` and requires that the vendor is currently `AVAILABLE`; suspending an already-suspended vendor is rejected with `ERR_VENDOR_SUSPENDED`."

    Design: Corner/endpoints/suspending_an_already_suspended_vendor_is_rejected
    """
    dep = fx.bootstrap_department(api)
    vendor = validate_success(
        api.create_vendor(
            f.vendor_payload(
                vendor_name="Lisbon Ground",
                vendor_type=c.VENDOR_GROUND_SECURITY,
                country_code=c.COUNTRY_PT,
                max_concurrent_engagements=2,
                sla_response_minutes=30,
                hourly_rate_cents=10_000,
                retainer_cents=50_000,
            ),
            dep.dir,
        ),
        201,
    )
    assert vendor["activation_status"] == c.VENDOR_AVAILABLE
    a.assert_vendor_hours(vendor, 0)
    assert vendor["suspension_reason"] is None
    assert vendor["version"] == 1

    first = validate_success(
        api.suspend_vendor(
            vendor["id"], f.vendor_suspend_payload("licence lapsed"), dep.dir
        )
    )
    assert first["activation_status"] == c.VENDOR_SUSPENDED_STATUS
    assert first["suspension_reason"] == "licence lapsed"
    assert first["version"] == 2

    second = api.suspend_vendor(
        vendor["id"], f.vendor_suspend_payload("licence lapsed again"), dep.dir
    )
    validate_error(second, e.ERR_VENDOR_SUSPENDED, 409)

    stored = fx.read_vendor(api, dep, vendor["id"])
    assert stored["suspension_reason"] == "licence lapsed"
    assert stored["version"] == 2


def test_an_engagement_needs_both_ends_to_exist_and_to_agree(api):
    """A missing endpoint is a 404 while a mismatched one is a 409 eligibility failure.

    PRD §3.5: "The `engagement_purpose` must equal the vendor's own `vendor_type`, and the vendor's `country_code` must equal the leg's `destination_country_code`; a mismatch on either is rejected with `ERR_NO_ELIGIBLE_VENDOR`."

    Design: Corner/endpoints/engagement_create_requires_a_vendor_and_leg_that_exist_and_agree
    """
    w = _leg_world(
        api,
        vendor_name="Lisbon Ground",
        vendor_type=c.VENDOR_GROUND_SECURITY,
        max_concurrent_engagements=2,
        sla_response_minutes=30,
        hourly_rate_cents=10_000,
        retainer_cents=50_000,
    )
    dep = w.dep
    good_v = w.vendor["version"]
    wrong_country = fx.register_vendor(
        api,
        dep,
        headers=dep.dir,
        vendor_name="Madrid Ground",
        vendor_type=c.VENDOR_GROUND_SECURITY,
        country_code=c.COUNTRY_ES,
        max_concurrent_engagements=2,
        sla_response_minutes=20,
        hourly_rate_cents=9_000,
        retainer_cents=40_000,
    )
    wrong_type = fx.register_vendor(
        api,
        dep,
        headers=dep.dir,
        vendor_name="Lisbon Medevac",
        vendor_type=c.VENDOR_MEDICAL_EVAC,
        country_code=c.COUNTRY_PT,
        max_concurrent_engagements=2,
        sla_response_minutes=25,
        hourly_rate_cents=20_000,
        retainer_cents=80_000,
    )

    def create(vendor_id, leg_id, version):
        return api.create_vendor_engagement(
            f.vendor_engagement_payload(
                vendor_id,
                leg_id,
                c.VENDOR_GROUND_SECURITY,
                "2026-09-10T08:00:00Z",
                "2026-09-10T16:00:00Z",
                version,
            ),
            dep.mgr,
        )

    validate_error(
        create(c.MISSING_VENDOR_ID, w.leg_id, good_v), e.ERR_VENDOR_NOT_FOUND, 404
    )
    validate_error(
        create(w.vendor_id, c.MISSING_LEG_ID, good_v), e.ERR_TRIP_LEG_NOT_FOUND, 404
    )
    validate_error(
        create(wrong_country["id"], w.leg_id, wrong_country["version"]),
        e.ERR_NO_ELIGIBLE_VENDOR,
        409,
    )
    validate_error(
        create(wrong_type["id"], w.leg_id, wrong_type["version"]),
        e.ERR_NO_ELIGIBLE_VENDOR,
        409,
    )

    accepted = validate_success(create(w.vendor_id, w.leg_id, good_v), 201)
    assert accepted["status"] == c.ENGAGEMENT_ACTIVE
    assert accepted["incident_id"] is None
    assert accepted["engagement_hours"] == 8
    a.assert_cents(accepted["engagement_cost_cents"], 130_000, "engagement_cost_cents")

    by_leg, _meta = validate_paginated(
        api.list_vendor_engagements(dep.mgr, trip_leg_id=w.leg_id)
    )
    assert [row["id"] for row in by_leg] == [accepted["id"]]
    by_vendor, _meta = validate_paginated(
        api.list_vendor_engagements(dep.mgr, vendor_id=w.vendor_id)
    )
    assert [row["id"] for row in by_vendor] == [accepted["id"]]

    good = fx.read_vendor(api, dep, w.vendor_id)
    a.assert_vendor_hours(good, 8)
    assert good["version"] == good_v + 1
    for rejected in (wrong_country, wrong_type):
        row = fx.read_vendor(api, dep, rejected["id"])
        a.assert_vendor_hours(row, 0)
        assert row["version"] == 1


def test_a_stale_vendor_version_is_refused_even_when_nothing_else_is_wrong(api):
    """Two non-intersecting engagements are legal, so only the version is at fault.

    PRD §2.8: "If that value does not equal the vendor's current `version`, the create is rejected with `ERR_STALE_VENDOR_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/a_stale_expected_vendor_version_is_rejected_after_a_prior_engagement_lands
    """
    w = _leg_world(
        api,
        vendor_name="Lisbon Ground",
        vendor_type=c.VENDOR_GROUND_SECURITY,
        max_concurrent_engagements=2,
        sla_response_minutes=30,
        hourly_rate_cents=10_000,
        retainer_cents=50_000,
    )
    dep = w.dep
    v0 = w.vendor["version"]
    assert v0 == 1

    first = validate_success(
        _engage(api, w, "2026-09-10T08:00:00Z", "2026-09-10T16:00:00Z", version=v0), 201
    )
    assert first["engagement_hours"] == 8
    a.assert_cents(first["engagement_cost_cents"], 130_000, "engagement_cost_cents")
    assert fx.vendor_version(api, dep, w.vendor_id) == 2

    stale = _engage(
        api, w, "2026-09-11T08:00:00Z", "2026-09-11T16:00:00Z", version=v0
    )
    validate_error(stale, e.ERR_STALE_VENDOR_VERSION, 412)

    after = fx.read_vendor(api, dep, w.vendor_id)
    assert after["version"] == 2
    a.assert_vendor_hours(after, 8)

    retried = validate_success(
        _engage(
            api,
            w,
            "2026-09-11T08:00:00Z",
            "2026-09-11T16:00:00Z",
            version=after["version"],
        ),
        201,
    )
    assert retried["status"] == c.ENGAGEMENT_ACTIVE
    final = fx.read_vendor(api, dep, w.vendor_id)
    assert final["version"] == 3
    a.assert_vendor_hours(final, 16)
