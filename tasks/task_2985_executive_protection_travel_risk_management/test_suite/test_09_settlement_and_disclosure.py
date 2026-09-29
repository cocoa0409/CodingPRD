"""Closing a trip: the final basis, the pinned perquisite order and the disclosure."""

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


def _approved_trip(
    api, w, method, depart_at, return_at, lines, leg_arrive=None, leg_depart=None
):
    """Build, staff, submit and approve one trip; its details stay CONFIRMED."""
    dep = w.dep
    trip = fx.create_trip(
        api,
        dep,
        w.exec_id,
        w.ra_id,
        insurance_policy_id=w.policy_id,
        cost_allocation_method=method,
        depart_at=depart_at,
        return_at=return_at,
    )
    leg = fx.add_leg(
        api,
        dep,
        trip["id"],
        arrive_at=leg_arrive or depart_at,
        depart_at=leg_depart or return_at,
    )
    rows = [
        fx.assign_detail(api, dep, leg["id"], staff_id, role, starts_at, ends_at)
        for staff_id, role, starts_at, ends_at in lines
    ]
    fx.record_advance(api, dep, leg["id"], c.ITEM_ROUTE_SURVEY)
    submitted = fx.submit_trip(api, dep, trip["id"])
    fx.ack_briefing(api, w.exec_id, trip["id"])
    approved = fx.decide_trip(api, dep, trip["id"], c.DECISION_APPROVE)
    return fx.Ctx(
        trip_id=trip["id"],
        leg_id=leg["id"],
        rows=rows,
        lines=lines,
        submitted=submitted,
        approved=approved,
    )


def _release_all(api, dep, built):
    """Settle every detail of one trip at its own planned end instant."""
    return [
        fx.release_assignment(api, dep, row["id"], line[3])
        for row, line in zip(built.rows, built.lines)
    ]


def _two_close_world(api):
    """One protectee, two trips, closed in a pinned order at 4,000,000 then 30,000,000."""
    w = fx.bootstrap_world(api)
    dep = w.dep
    w.pricey_id = fx.register_staff(
        api, "Pia Principal", c.STAFF_ROLE_ANALYST, 100_000
    )["id"]
    w.first = _approved_trip(
        api,
        w,
        c.ALLOCATION_EXEC_PERQUISITE,
        "2026-09-10T00:00:00Z",
        "2026-09-12T00:00:00Z",
        [
            (
                w.pricey_id,
                c.DETAIL_LEAD_AGENT,
                "2026-09-10T00:00:00Z",
                "2026-09-11T08:00:00Z",
            )
        ],
        leg_arrive="2026-09-10T00:00:00Z",
        leg_depart="2026-09-11T08:00:00Z",
    )
    w.second = _approved_trip(
        api,
        w,
        c.ALLOCATION_PRORATA,
        "2026-09-21T00:00:00Z",
        "2026-10-01T00:00:00Z",
        [
            (
                w.pricey_id,
                c.DETAIL_LEAD_AGENT,
                "2026-09-21T00:00:00Z",
                "2026-10-01T00:00:00Z",
            )
        ],
    )
    fx.set_clock(api, "2026-09-12T00:00:00Z")
    _release_all(api, dep, w.first)
    w.closed_a = fx.close_trip(api, dep, w.first.trip_id)
    fx.set_clock(api, "2026-10-01T00:00:00Z")
    _release_all(api, dep, w.second)
    w.closed_b = fx.close_trip(api, dep, w.second.trip_id)
    return w


def test_the_second_close_reads_the_tier_from_the_disclosure_before_its_own_rollup(api):
    """The 30,000,000 trip is taxed at 0.10 because the prior figure was 4,000,000.

    PRD §3.9: "**Step two:** select the tier rate from the prior disclosure alone, never from the post-trip total. A prior disclosure below 5,000,000 cents (fifty thousand dollars) selects a rate of 0.10; a prior disclosure of at least 5,000,000 cents but below 20,000,000 cents (two hundred thousand dollars) selects 0.25; a prior disclosure of 20,000,000 cents or more selects 0.40."

    Design: Difficulty/combinatorial_formula/perquisite_tier_read_before_rollup_across_two_closes
    """
    w = _two_close_world(api)

    a.assert_cents(
        w.closed_a["total_security_cost_cents"], 4_000_000, "trip A total"
    )
    a.assert_decimal_value(
        w.closed_a["perquisite_rate_applied"], 1.00, "trip A perquisite_rate_applied"
    )
    a.assert_cents(
        w.closed_a["perquisite_taxable_cents"], 4_000_000, "trip A taxable"
    )
    a.assert_cents(w.closed_a["business_borne_cents"], 0, "trip A business_borne_cents")

    a.assert_cents(
        w.closed_b["total_security_cost_cents"], 30_000_000, "trip B total"
    )
    a.assert_decimal_value(
        w.closed_b["perquisite_rate_applied"], 0.10, "trip B perquisite_rate_applied"
    )
    a.assert_cents(w.closed_b["perquisite_taxable_cents"], 3_000_000, "trip B taxable")
    assert w.closed_b["perquisite_taxable_cents"] != 12_000_000, (
        "reading the tier after the rollup would have seen 34,000,000 and applied 0.40"
    )
    a.assert_cents(
        w.closed_b["business_borne_cents"], 27_000_000, "trip B business_borne_cents"
    )
    a.assert_trip_states(w.closed_b, c.APPROVAL_APPROVED, c.READINESS_CLOSED)


def test_the_rollup_lands_last_and_the_disclosure_read_agrees_with_both_closes(api):
    """Two closes accumulate into one disclosure position and one budget ledger.

    PRD §3.9: "**Step five, pinned last:** roll up — the protectee's `annual_disclosed_perquisite_cents` rises by `perquisite_taxable_cents` and their `business_borne_security_cents` rises by `business_borne_cents`."

    Design: Difficulty/combinatorial_formula/perquisite_tier_read_before_rollup_across_two_closes
    """
    w = _two_close_world(api)
    dep = w.dep

    executive = fx.read_executive(api, dep, w.exec_id)
    a.assert_cents(
        executive["annual_disclosed_perquisite_cents"],
        7_000_000,
        "annual_disclosed_perquisite_cents",
    )
    a.assert_cents(
        executive["business_borne_security_cents"],
        27_000_000,
        "business_borne_security_cents",
    )
    a.assert_budget_ledger(
        executive, committed=0, spent=34_000_000, remaining=66_000_000
    )

    disclosure = validate_success(
        api.get_perquisite_disclosure(w.exec_id, dep.officer)
    )
    assert disclosure["executive_id"] == w.exec_id
    assert disclosure["closed_trip_count"] == 2
    a.assert_cents(
        disclosure["annual_disclosed_perquisite_cents"],
        7_000_000,
        "disclosed annual_disclosed_perquisite_cents",
    )
    a.assert_cents(
        disclosure["business_borne_security_cents"],
        27_000_000,
        "disclosed business_borne_security_cents",
    )
    a.assert_cents(
        disclosure["total_security_cost_cents"],
        34_000_000,
        "disclosed total_security_cost_cents",
    )
    a.assert_decimal_value(
        disclosure["latest_perquisite_rate_applied"],
        0.10,
        "latest_perquisite_rate_applied",
    )


def _tier_edge_world(api):
    """Three closes whose priors land at 0, at 4,999,999 and at exactly 5,000,000."""
    w = fx.bootstrap_world(api)
    dep = w.dep
    w.rich_id = fx.register_staff(api, "Rex Rich", c.STAFF_ROLE_ANALYST, 999_999)["id"]
    w.penny_id = fx.register_staff(api, "Penny Cent", c.STAFF_ROLE_ANALYST, 1)["id"]
    w.mite_id = fx.register_staff(api, "Mona Mite", c.STAFF_ROLE_ANALYST, 1)["id"]
    w.plain_id = fx.register_staff(api, "Paul Plain", c.STAFF_ROLE_ANALYST, 9_000)["id"]
    w.first = _approved_trip(
        api,
        w,
        c.ALLOCATION_EXEC_PERQUISITE,
        "2026-09-01T00:00:00Z",
        "2026-09-01T04:00:00Z",
        [
            (
                w.rich_id,
                c.DETAIL_LEAD_AGENT,
                "2026-09-01T00:00:00Z",
                "2026-09-01T04:00:00Z",
            ),
            (
                w.penny_id,
                c.DETAIL_AGENT,
                "2026-09-01T00:00:00Z",
                "2026-09-01T04:00:00Z",
            ),
        ],
    )
    w.second = _approved_trip(
        api,
        w,
        c.ALLOCATION_PRORATA,
        "2026-09-03T00:00:00Z",
        "2026-09-03T04:00:00Z",
        [
            (
                w.mite_id,
                c.DETAIL_LEAD_AGENT,
                "2026-09-03T00:00:00Z",
                "2026-09-03T04:00:00Z",
            )
        ],
    )
    w.third = _approved_trip(
        api,
        w,
        c.ALLOCATION_PRORATA,
        "2026-09-05T08:00:00Z",
        "2026-09-05T18:00:00Z",
        [
            (
                w.plain_id,
                c.DETAIL_LEAD_AGENT,
                "2026-09-05T08:00:00Z",
                "2026-09-05T18:00:00Z",
            )
        ],
    )
    fx.set_clock(api, "2026-09-06T00:00:00Z")
    for built in (w.first, w.second, w.third):
        built.released = _release_all(api, dep, built)
    w.closed_a = fx.close_trip(api, dep, w.first.trip_id)
    w.closed_b = fx.close_trip(api, dep, w.second.trip_id)
    w.closed_c = fx.close_trip(api, dep, w.third.trip_id)
    return w


def test_a_prior_disclosure_of_exactly_five_million_selects_the_middle_tier(api):
    """4,999,999 cents of prior disclosure buys 0.10; the very next cent buys 0.25.

    PRD §3.9: "The boundaries are inclusive at the lower edge, so a prior disclosure of exactly 5,000,000 cents selects 0.25 while 4,999,999 cents selects 0.10."

    Design: Difficulty/boundary_precision_check/perquisite_tier_boundary_inclusive_at_exactly_five_million_prior
    """
    w = _tier_edge_world(api)

    a.assert_decimal_value(
        w.closed_a["perquisite_rate_applied"], 1.00, "trip A perquisite_rate_applied"
    )
    a.assert_cents(
        w.closed_a["perquisite_taxable_cents"], 4_999_999, "trip A taxable"
    )

    a.assert_decimal_value(
        w.closed_b["perquisite_rate_applied"],
        0.10,
        "the prior disclosure was 4,999,999, one cent below the tier edge",
    )

    a.assert_decimal_value(
        w.closed_c["perquisite_rate_applied"],
        0.25,
        "the prior disclosure was exactly 5,000,000, which is inside the tier",
    )
    a.assert_cents(
        w.closed_c["total_security_cost_cents"], 112_500, "trip C total"
    )
    a.assert_cents(w.closed_c["perquisite_taxable_cents"], 28_125, "trip C taxable")
    assert w.closed_c["perquisite_taxable_cents"] != 11_250, (
        "an exclusive lower edge would have kept trip C on the 0.10 tier"
    )
    a.assert_cents(w.closed_c["business_borne_cents"], 84_375, "trip C business_borne_cents")


def test_a_half_cent_perquisite_share_rounds_up_and_the_ledger_follows(api):
    """Ten cents of a five-cent trip is half a cent, and half-up makes it one.

    PRD §3.9: "**Step four:** `perquisite_taxable_cents` is `total_security_cost_cents` multiplied by that rate, rounded half-up to a whole cent; `business_borne_cents` is `total_security_cost_cents` less `perquisite_taxable_cents`; and `perquisite_rate_applied` records the rate actually used, pinned for audit, and is therefore always exactly one of 0.00, 0.10, 0.25, 0.40 or 1.00."

    Design: Difficulty/boundary_precision_check/perquisite_tier_boundary_inclusive_at_exactly_five_million_prior
    """
    w = _tier_edge_world(api)

    a.assert_cents(w.first.released[0]["cost_cents"], 4_999_995, "trip A lead line")
    a.assert_cents(w.first.released[1]["cost_cents"], 4, "trip A agent line")
    a.assert_cents(w.second.released[0]["cost_cents"], 5, "trip B lead line")
    a.assert_cents(w.third.released[0]["cost_cents"], 112_500, "trip C lead line")
    for built in (w.first, w.second, w.third):
        for row in built.released:
            assert row["status"] == c.ASSIGNMENT_RELEASED
            assert row["cost_basis"] == c.COST_BASIS_FINAL

    a.assert_cents(
        w.closed_a["total_security_cost_cents"], 4_999_999, "trip A total"
    )
    a.assert_cents(w.closed_b["total_security_cost_cents"], 5, "trip B total")
    a.assert_cents(
        w.closed_b["perquisite_taxable_cents"],
        1,
        "five cents at 0.10 is half a cent, which rounds up",
    )
    assert w.closed_b["perquisite_taxable_cents"] != 0, "half-up never truncates"
    a.assert_cents(w.closed_b["business_borne_cents"], 4, "trip B business_borne_cents")

    executive = fx.read_executive(api, w.dep, w.exec_id)
    a.assert_cents(
        executive["annual_disclosed_perquisite_cents"],
        5_028_125,
        "annual_disclosed_perquisite_cents",
    )
    a.assert_cents(
        executive["business_borne_security_cents"],
        84_379,
        "business_borne_security_cents",
    )
    a.assert_budget_ledger(
        executive, committed=0, spent=5_112_504, remaining=94_887_496
    )

    disclosure = validate_success(
        api.get_perquisite_disclosure(w.exec_id, w.dep.dir)
    )
    assert disclosure["closed_trip_count"] == 3
    a.assert_cents(
        disclosure["total_security_cost_cents"],
        5_112_504,
        "disclosed total_security_cost_cents",
    )
    a.assert_decimal_value(
        disclosure["latest_perquisite_rate_applied"],
        0.25,
        "latest_perquisite_rate_applied",
    )


def test_the_disclosure_read_reconciles_with_the_single_closed_trip(api):
    """One closed trip, and every figure in the disclosure traces back to it.

    PRD §3.9: "The disclosure position is available as a computed read, aggregated over that protectee's closed trips only."

    Design: Corner/endpoints/perquisite_disclosure_read_matches_the_closed_trip_totals
    """
    w = fx.approved_trip_world(api)
    dep = w.dep
    fx.release_assignment(api, dep, w.lead_assignment["id"], c.LEG_DEPART_AT)
    fx.set_clock(api, c.TRIP_RETURN_AT)

    closed = fx.close_trip(api, dep, w.trip_id)
    a.assert_trip_states(closed, c.APPROVAL_APPROVED, c.READINESS_CLOSED)
    assert closed["closed_at"] == "2026-09-12T00:00:00.000Z"
    assert closed["next_check_in_due_at"] is None
    a.assert_cents(
        closed["total_security_cost_cents"], 112_500, "total_security_cost_cents"
    )
    a.assert_decimal_value(
        closed["perquisite_rate_applied"], 0.10, "perquisite_rate_applied"
    )
    a.assert_cents(closed["perquisite_taxable_cents"], 11_250, "perquisite_taxable_cents")
    a.assert_cents(closed["business_borne_cents"], 101_250, "business_borne_cents")

    own_read = validate_success(
        api.get_perquisite_disclosure(w.exec_id, w.exec_headers)
    )
    assert own_read["executive_id"] == w.exec_id
    assert own_read["closed_trip_count"] == 1
    a.assert_cents(
        own_read["annual_disclosed_perquisite_cents"],
        11_250,
        "annual_disclosed_perquisite_cents",
    )
    a.assert_cents(
        own_read["business_borne_security_cents"],
        101_250,
        "business_borne_security_cents",
    )
    a.assert_cents(
        own_read["total_security_cost_cents"],
        112_500,
        "total_security_cost_cents",
    )
    assert (
        own_read["annual_disclosed_perquisite_cents"]
        + own_read["business_borne_security_cents"]
        == own_read["total_security_cost_cents"]
    ), "the two shares of one closed trip must add back to its total"
    a.assert_decimal_value(
        own_read["latest_perquisite_rate_applied"],
        0.10,
        "latest_perquisite_rate_applied",
    )

    officer_read = validate_success(
        api.get_perquisite_disclosure(w.exec_id, dep.officer)
    )
    assert officer_read == own_read, "a ComplianceOfficer sees the same position"

    executive = fx.read_executive(api, dep, w.exec_id)
    a.assert_budget_ledger(
        executive, committed=0, spent=112_500, remaining=99_887_500
    )
    assert executive["open_degraded_trip_count"] == 0


def _only_incident(api, dep, trip_id):
    """Incidents have no single-resource read, so re-observe one through the list."""
    rows, meta = validate_paginated(api.list_incidents(trip_id, dep.mgr))
    assert meta["total_count"] == 1
    return rows[0]


def test_the_close_ladder_reports_the_most_serious_defect_it_can_see(api):
    """Not-ended outranks the open incident, which outranks the unsettled detail.

    PRD §3.9: "Every incident of the trip must have `status` of `CLOSED`, or the close is rejected with `ERR_OPEN_INCIDENTS_BLOCK_CLOSE` — an open incident would otherwise be silently omitted from the final cost, which is precisely why the gate exists."

    Design: Corner/errors/close_rejects_an_unended_trip_then_an_open_incident_then_an_unsettled_detail
    """
    w = fx.approved_trip_world(api)
    dep = w.dep
    evac = fx.register_vendor(
        api,
        dep,
        vendor_name="Lisboa Air Ambulance",
        vendor_type=c.VENDOR_MEDICAL_EVAC,
        country_code=c.COUNTRY_PT,
        max_concurrent_engagements=1,
        sla_response_minutes=30,
        hourly_rate_cents=20_000,
        retainer_cents=80_000,
    )
    a.assert_trip_states(w.trip, c.APPROVAL_APPROVED, c.READINESS_READY)
    assert w.lead_assignment["status"] == c.ASSIGNMENT_CONFIRMED

    validate_error(
        api.close_trip(w.trip_id, dep.mgr), e.ERR_TRIP_NOT_ENDED, 409
    )

    fx.set_clock(api, "2026-09-11T00:00:00Z")
    reported = fx.report_incident(
        api,
        dep,
        w.trip_id,
        incident_type=c.INCIDENT_MEDICAL,
        severity=3,
        narrative="principal collapsed in the hotel lobby",
    )
    assert reported["status"] == c.INCIDENT_REPORTED
    assert reported["response_track"] is None
    a.assert_cents(reported["response_cost_cents"], 0, "response_cost_cents")
    a.assert_trip_states(
        fx.read_trip(api, dep, w.trip_id),
        c.APPROVAL_APPROVED,
        c.READINESS_DEGRADED,
    )
    assert fx.read_executive(api, dep, w.exec_id)["open_degraded_trip_count"] == 1

    fx.set_clock(api, c.TRIP_RETURN_AT)
    validate_error(
        api.close_trip(w.trip_id, dep.mgr), e.ERR_OPEN_INCIDENTS_BLOCK_CLOSE, 409
    )
    assert _only_incident(api, dep, w.trip_id)["status"] == c.INCIDENT_REPORTED

    validate_error(
        api.triage_incident(
            reported["id"], f.triage_payload(c.TRACK_SHELTER_IN_PLACE), dep.mgr
        ),
        e.ERR_INCIDENT_TRACK_INCOMPATIBLE,
        422,
    )
    untouched = _only_incident(api, dep, w.trip_id)
    assert untouched["status"] == c.INCIDENT_REPORTED
    assert untouched["response_track"] is None
    assert untouched["version"] == reported["version"]

    triaged = fx.triage_incident(api, dep, reported["id"], c.TRACK_MEDEVAC)
    assert triaged["status"] == c.INCIDENT_MEDEVAC_ACTIVE
    assert triaged["response_track"] == c.TRACK_MEDEVAC
    engagements, meta = validate_paginated(
        api.list_vendor_engagements(dep.mgr, incident_id=reported["id"])
    )
    assert meta["total_count"] == 1
    engagement = engagements[0]
    assert engagement["vendor_id"] == evac["id"]
    assert engagement["starts_at"] == "2026-09-12T00:00:00.000Z"
    assert engagement["ends_at"] == "2026-09-13T00:00:00.000Z"
    assert engagement["engagement_hours"] == 24
    a.assert_cents(
        engagement["engagement_cost_cents"], 560_000, "engagement_cost_cents"
    )
    a.assert_vendor_hours(fx.read_vendor(api, dep, evac["id"]), 24)

    fx.complete_engagement(api, dep, engagement["id"])
    a.assert_vendor_hours(fx.read_vendor(api, dep, evac["id"]), 0)
    resolved = fx.resolve_incident(
        api,
        dep,
        reported["id"],
        resolution_note="principal evacuated and stable in Lisbon",
    )
    assert resolved["status"] == c.INCIDENT_RESOLVED
    closed_incident = fx.close_incident(api, dep, reported["id"])
    assert closed_incident["status"] == c.INCIDENT_CLOSED
    a.assert_cents(
        closed_incident["response_cost_cents"],
        3_060_000,
        "the completed engagement plus the MEDEVAC surcharge",
    )
    assert (
        closed_incident["response_cost_cents"] == 560_000 + c.MEDEVAC_SURCHARGE_CENTS
    )

    validate_error(
        api.close_trip(w.trip_id, dep.mgr), e.ERR_ASSIGNMENTS_NOT_SETTLED, 409
    )
    fx.release_assignment(api, dep, w.lead_assignment["id"], c.LEG_DEPART_AT)

    closed = fx.close_trip(api, dep, w.trip_id)
    a.assert_trip_states(closed, c.APPROVAL_APPROVED, c.READINESS_CLOSED)
    a.assert_cents(
        closed["total_security_cost_cents"],
        3_172_500,
        "the released detail plus the closed incident's frozen response cost",
    )
    a.assert_decimal_value(
        closed["perquisite_rate_applied"], 0.10, "perquisite_rate_applied"
    )
    a.assert_cents(
        closed["perquisite_taxable_cents"], 317_250, "perquisite_taxable_cents"
    )
    a.assert_cents(closed["business_borne_cents"], 2_855_250, "business_borne_cents")

    executive = fx.read_executive(api, dep, w.exec_id)
    a.assert_budget_ledger(
        executive, committed=0, spent=3_172_500, remaining=96_827_500
    )
    assert executive["open_degraded_trip_count"] == 0
