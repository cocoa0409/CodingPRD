"""Dawn-raid readiness drills on the site's half-open calendar, and the
document-creation-guideline audit that closes with a floored score.
"""
from test_helpers import (
    ADMIN, COUNSEL, ApiErrorId, assert_drill, assert_instant_equals,
    assert_site, audit_findings_payload, complete_drill, create_drill_payload,
    open_document_audit, read_document_audit, read_drill, read_site,
    register_business_unit, register_site, schedule_drill, set_clock,
    start_drill, validate_error, validate_paginated, validate_success,
)


def test_third_overlapping_drill_exceeds_the_site_aggregate_capacity(api):
    """PRD §2.10: "Concurrency is evaluated by sweeping the candidate window's
    own boundary instants together with the start instant of every occupying
    drill that falls inside the candidate window; at each such instant,
    concurrency counts the candidate itself plus every occupying drill whose
    window has begun at or before that instant and has not yet ended. The drill
    is refused when the maximum concurrency across those instants exceeds the
    site's `concurrent_drill_capacity`, which is at minimum 1 and defaults to
    1."
    PRD §3.8: "The site's aggregate capacity check runs before the drill is
    created; exceeding it is refused with `ERR_SITE_DRILL_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/site_half_open_window_allows_adjacency_but_enforces_aggregate_capacity
    """
    set_clock()
    site = register_site(name="Rotterdam Plant", country_code="NL",
                         concurrent_drill_capacity=2)
    schedule_drill(site["id"], drill_type="DAWN_RAID",
                   window_start="2026-09-01T08:00:00Z",
                   window_end="2026-09-01T12:00:00Z")
    schedule_drill(site["id"], drill_type="DOCUMENT_HOLD",
                   window_start="2026-09-01T10:00:00Z",
                   window_end="2026-09-01T14:00:00Z")

    resp = api.create_drill(create_drill_payload(
        site["id"], drill_type="INTERVIEW",
        window_start="2026-09-01T11:00:00Z",
        window_end="2026-09-01T13:00:00Z"), ADMIN)

    validate_error(resp, ApiErrorId.ERR_SITE_DRILL_CAPACITY_EXCEEDED.value)
    assert resp.status_code == 409
    _rows, meta = validate_paginated(api.list_drills(
        COUNSEL, params={"site_id": site["id"]}))
    assert meta["total_count"] == 2, "the refused drill is not created"


def test_drill_beginning_exactly_when_another_ends_is_accepted(api):
    """PRD §2.10: "A site's drill calendar is contended as a **half-open**
    interval `[window_start, window_end)` with an aggregate capacity. Adjacency
    does not conflict here: an existing drill ending at exactly some instant and
    a candidate beginning at exactly that instant may both exist."
    PRD §3.8: "A scheduled drill opens in `SCHEDULED` and occupies its window
    from that moment."
    PRD §3.8: "A site also carries a derived `readiness_score`, which starts at
    0 and is the mean `score` over that site's `COMPLETED` drills, rounded half
    up to 2 decimal places; a site with no completed drills reads 0."

    Design: Difficulty/resource_temporal_overlap/site_half_open_window_allows_adjacency_but_enforces_aggregate_capacity
    """
    set_clock()
    site = register_site(name="Rotterdam Plant", country_code="NL",
                         concurrent_drill_capacity=2)
    schedule_drill(site["id"], drill_type="DAWN_RAID",
                   window_start="2026-09-01T08:00:00Z",
                   window_end="2026-09-01T12:00:00Z")
    schedule_drill(site["id"], drill_type="DOCUMENT_HOLD",
                   window_start="2026-09-01T10:00:00Z",
                   window_end="2026-09-01T14:00:00Z")

    data = validate_success(api.create_drill(create_drill_payload(
        site["id"], drill_type="INTERVIEW",
        window_start="2026-09-01T12:00:00Z",
        window_end="2026-09-01T16:00:00Z"), ADMIN), 201)

    assert_drill(data)
    assert data["status"] == "SCHEDULED"
    assert_instant_equals(data["window_start"], "2026-09-01T12:00:00.000Z",
                          "ReadinessDrill.window_start")

    _rows, meta = validate_paginated(api.list_drills(
        COUNSEL, params={"site_id": site["id"]}))
    assert meta["total_count"] == 3
    stored_site = read_site(site["id"])
    assert_site(stored_site)
    assert stored_site["readiness_score"] == 0


def test_starting_a_drill_before_its_window_opens_is_rejected(api):
    """PRD §3.8: "Starting a drill moves `SCHEDULED → IN_PROGRESS` and is legal
    only once the logical clock has reached `window_start`; a running drill
    continues to occupy its window."
    PRD §2.4: "At startup the clock reads exactly `2026-08-01T00:00:00Z`, and
    until an administrator moves it, every time-dependent rule — training
    expiry, the agenda lead time before a meeting, attendance confirmation after
    a meeting ends, the HSR waiting period, leniency marker validity, and drill
    window boundaries — evaluates against that fixed instant."

    Design: Corner/state_machines/readiness_drill_start_before_window_start_is_rejected
    """
    set_clock("2026-08-01T00:00:00Z")
    site = register_site(name="Rotterdam Plant", country_code="NL",
                         concurrent_drill_capacity=1)
    drill = schedule_drill(site["id"], drill_type="DAWN_RAID",
                           window_start="2026-09-01T08:00:00Z",
                           window_end="2026-09-01T12:00:00Z")

    resp = api.start_drill(drill["id"], ADMIN)

    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert resp.status_code == 409
    assert read_drill(drill["id"])["status"] == "SCHEDULED"


def test_completed_drills_alone_set_the_site_readiness_score(api):
    """PRD §3.8: "Completing it moves `IN_PROGRESS → COMPLETED`, records the
    supplied `score` (an integer from 0 through 100) and `gaps_found` (a count
    that may be zero but never negative), stops the occupancy, and recomputes
    the site's `readiness_score` across all its completed drills."
    PRD §3.8: "A site also carries a derived `readiness_score`, which starts at
    0 and is the mean `score` over that site's `COMPLETED` drills, rounded half
    up to 2 decimal places; a site with no completed drills reads 0."
    PRD §3.8: "Aborting, which records a `reason` into `abort_reason`, is legal
    from both `SCHEDULED` and `IN_PROGRESS`, lands on the terminal `ABORTED`,
    and immediately frees the capacity the drill was holding."

    Design: Corner/state_machines/readiness_drill_completion_recomputes_site_readiness_score
    """
    set_clock("2026-08-01T00:00:00Z")
    site = register_site(name="Antwerp Plant", country_code="BE",
                         concurrent_drill_capacity=3)
    window = {"window_start": "2026-09-01T08:00:00Z",
              "window_end": "2026-09-01T12:00:00Z"}
    d1 = schedule_drill(site["id"], drill_type="DAWN_RAID", **window)
    d2 = schedule_drill(site["id"], drill_type="DOCUMENT_HOLD", **window)
    d3 = schedule_drill(site["id"], drill_type="INTERVIEW", **window)
    set_clock("2026-09-01T09:00:00Z")
    start_drill(d1["id"])
    start_drill(d2["id"])
    start_drill(d3["id"])

    complete_drill(d1["id"], score=80, gaps_found=3)
    assert read_site(site["id"])["readiness_score"] == 80.00

    complete_drill(d2["id"], score=91, gaps_found=1)
    assert read_site(site["id"])["readiness_score"] == 85.50

    aborted = validate_success(api.abort_drill(
        d3["id"], {"reason": "Site evacuation drill collided with the exercise"},
        COUNSEL))
    assert aborted["status"] == "ABORTED"
    assert read_site(site["id"])["readiness_score"] == 85.50, (
        "an aborted drill never enters the mean")


def test_guideline_score_floors_at_zero_rather_than_going_negative(api):
    """PRD §3.8: "First the violation ratio is the violation count multiplied by
    100 and divided by the sample size, **rounded half up to 2 decimal places at
    that point** rather than carried at full precision. Then the score is 100
    minus that rounded ratio minus 2 points for each high-risk phrase
    occurrence, rounded half up to 2 decimal places and floored at 0.00 so a
    badly failing sample bottoms out rather than going negative."
    PRD §3.8: "The audit moves `OPEN → COMPLETED`, which is terminal, and its
    `guideline_score` is computed in two pinned steps."
    PRD §3.8: "Closing the audit also recomputes the unit's
    `document_violation_count` as the sum of `violation_count` across all its
    completed audits and increments the unit's `version` by 1 — which is what
    makes those violations available to the next incident-adjusted risk
    assessment."

    Design: Corner/calculations/document_guideline_score_floors_at_zero
    """
    set_clock()
    unit = register_business_unit()
    audit = open_document_audit(unit["id"], sample_size=20)

    data = validate_success(api.record_audit_findings(
        audit["id"], audit_findings_payload(15, 20), COUNSEL))

    assert data["status"] == "COMPLETED"
    assert data["guideline_score"] == 0.00, "100 - 75.00 - 40 is clamped to 0.00"
    assert read_document_audit(audit["id"])["guideline_score"] == 0.00
    from test_helpers import read_business_unit
    assert read_business_unit(unit["id"])["document_violation_count"] == 15
