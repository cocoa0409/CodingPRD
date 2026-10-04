"""Difficulty tests: priority_pair_validation_conflict — one request violates
two validation tiers at once; the earlier tier's error must surface (state
before safety, temporal before referential).
"""
from test_helpers import (
    ApiErrorId,
    create_athlete,
    create_selection_procedure,
    lock_procedure,
    make_athlete_headers,
    make_ngb_admin_headers,
    publish_procedure,
    read_procedure,
    set_logical_clock,
    setup_certified_body,
    setup_eligible_athlete,
    setup_nominated_roster,
    validate_error,
    validate_paginated,
)


def test_state_before_safety_on_trials_entry(api, committee_admin_headers):
    """PRD validation-pipeline section: "Every request walks a fixed
    precedence ladder of validation tiers, and the **first** failing tier
    determines the error returned — a request that would fail two checks
    surfaces the earlier tier's error, never the later one."
    PRD validation-pipeline section, tier 4 (state legality): "a trials entry
    attempted while the procedure's `trials_status` is not `REGISTRATION_OPEN`
    is rejected with `ERR_TRIALS_NOT_OPEN` (409)".
    PRD validation-pipeline section, tier 5 (safety gates): "Trials entries
    and roster-nomination eligibility require the athlete's screening cleared
    and unexpired, else `ERR_SCREENING_NOT_CLEARED` (422)".

    Design: Difficulty/priority_pair_validation_conflict/state_before_safety_on_trials_entry
    """
    body = setup_certified_body(
        api=api,
        name="US Diving",
        sport_code="DIVE",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    # Athlete whose screening was never cleared (SCREENING_PENDING) — the
    # tier-5 safety gate would fail if reached.
    athlete = create_athlete(
        body["id"], api=api, full_name="Noa Spring", date_of_birth="2001-04-04"
    )
    assert athlete["screening_status"] == "SCREENING_PENDING"

    # Procedure PUBLISHED then LOCKED, but the trials dimension never opens.
    proc = create_selection_procedure(body["id"], api=api)
    publish_procedure(proc["id"], body["id"], api=api)
    proc = lock_procedure(proc["id"], body["id"], api=api)
    assert proc["trials_status"] == "TRIALS_NOT_OPEN"

    # One request violating both tier 4 and tier 5: the state error wins.
    resp = api.create_trials_entry(
        proc["id"],
        {"athlete_id": athlete["id"]},
        make_ngb_admin_headers(body["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TRIALS_NOT_OPEN)

    # No entry is appended to the procedure.
    proc_after = read_procedure(body["id"], proc["id"], api=api)
    assert proc_after["entries"] == [], (
        f"no entry may be appended on a rejected entry call, got {proc_after['entries']!r}"
    )


def test_temporal_before_referential_on_appeal(api, committee_admin_headers):
    """PRD validation-pipeline section: "Every request walks a fixed
    precedence ladder of validation tiers, and the **first** failing tier
    determines the error returned — a request that would fail two checks
    surfaces the earlier tier's error, never the later one."
    PRD validation-pipeline section, tier 6 (temporal and window rules):
    "appeals close 72 hours after first nomination (`ERR_APPEAL_WINDOW_EXPIRED`,
    422)".
    PRD validation-pipeline section, tier 8 (referential): "The appellant must
    be an `Athlete` holding an entry on the appealed roster's procedure;
    otherwise `ERR_UNAUTHORIZED` (403)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_before_referential_on_appeal
    """
    body = setup_certified_body(
        api=api,
        name="US Rowing",
        sport_code="ROWI",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    entrant = setup_eligible_athlete(
        body["id"], api=api, full_name="A One", date_of_birth="1998-01-01"
    )
    # Outsider: registered with the same body but never entered in the trials,
    # so the tier-8 referential rule would fail if reached.
    outsider = create_athlete(
        body["id"], api=api, full_name="O Out", date_of_birth="1998-02-02"
    )

    _proc, roster = setup_nominated_roster(
        body["id"],
        {entrant["id"]: 90},
        api=api,
        quota_slots=1,
        qualifying_score=80,
        nominate_at="2026-12-20T00:00:00Z",
    )
    assert roster["status"] == "NOMINATED"

    # 120 hours after the 2026-12-20 nomination: past the 72-hour window.
    set_logical_clock("2026-12-25T00:00:00Z", api=api)
    resp = api.create_appeal(
        roster["id"],
        {"grounds": "SELECTION_PROCESS"},
        make_athlete_headers(outsider["id"]),
    )
    # Both tier 6 (late filing) and tier 8 (no entry) fail; temporal wins.
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED)

    # No Appeal row is created.
    appeals, meta = validate_paginated(
        api.list_roster_appeals(roster["id"], committee_admin_headers)
    )
    assert meta["total_count"] == 0
    assert appeals == []
