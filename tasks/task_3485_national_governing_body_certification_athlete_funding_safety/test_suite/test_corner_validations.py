"""Corner tests: validations section — single-failure rejection paths for the
score-range, window-shape, publish-lead, registration-deadline, fiscal,
consent, results-final, submission-blocker, duplicate-entry, and
agreement-overlap rules. Each scenario isolates exactly one failing check."""
from test_helpers import (
    AUDITOR_ISSUER_ID,
    ApiErrorId,
    activate_agreement,
    add_verified_results,
    answer_slot,
    create_certification_cycle,
    create_commercial_deal,
    create_funding_agreement,
    create_funding_agreement_payload,
    create_governing_body,
    create_roster,
    create_selection_procedure,
    deal_transition_payload,
    file_appeal,
    get_success_data,
    hold_trials,
    issue_findings_payload,
    make_auditor_headers,
    make_ngb_admin_headers,
    nomination_payload,
    open_cycle,
    parse_iso,
    read_funding_agreement,
    read_procedure,
    read_roster,
    set_logical_clock,
    setup_active_agreement,
    setup_certified_body,
    setup_eligible_athlete,
    setup_nominated_roster,
    setup_procedure_with_entries,
    validate_error,
    validate_success,
)


def test_score_out_of_range_rejected(api, committee_admin_headers):
    """PRD §3.1: "The auditor then issues findings by supplying the three
    component scores — `governance_score`, `athlete_rep_score`, and
    `financial_score` — each required and each within 0 to 100 inclusive, with
    out-of-range values rejected as `ERR_SCORE_OUT_OF_RANGE`."

    Design: Corner/validations/score_out_of_range_rejected
    """
    body = create_governing_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    cycle = create_certification_cycle(body["id"], api=api)
    open_cycle(cycle["id"], api=api)

    resp = api.transition_certification_cycle(
        cycle["id"],
        issue_findings_payload(101, 70, 60),
        make_auditor_headers(AUDITOR_ISSUER_ID),
    )
    validate_error(resp, ApiErrorId.ERR_SCORE_OUT_OF_RANGE)

    listed = get_success_data(
        api.list_certification_cycles(body["id"], committee_admin_headers)
    )
    after = next(c for c in listed if c["id"] == cycle["id"])
    assert after["status"] == "OPEN", "a rejected issue-findings mutates nothing"
    assert after["provisional_score"] is None


def test_cycle_window_end_not_after_start(api, committee_admin_headers):
    """PRD §3.1: "A `CommitteeAdmin` schedules a CertificationCycle for the body
    — the cycle's `governing_body_id` ties it to that body — by supplying
    `window_start` and `window_end`, which define a half-open review window:
    the end must be strictly later than the start (a reversed or empty window
    is rejected with `ERR_CYCLE_WINDOW_INVALID`), and the new window must not
    overlap any existing cycle of the same body, though windows that merely
    touch — one's start equal to a prior cycle's end — are permitted (a true
    overlap is rejected with `ERR_CYCLE_WINDOW_OVERLAP`)."

    Design: Corner/validations/cycle_window_end_not_after_start
    """
    body = create_governing_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    # window_end == window_start is an empty interval: strictly-later fails.
    resp = api.create_certification_cycle(
        body["id"],
        {
            "window_start": "2026-10-01T00:00:00Z",
            "window_end": "2026-10-01T00:00:00Z",
        },
        committee_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CYCLE_WINDOW_INVALID)


def test_publish_lead_time_short(api):
    """PRD §3.6: "Publishing — `DRAFT` to `PUBLISHED` — is gated on the body's
    standing and the calendar: the body's status must be `CERTIFIED`,
    `PROBATION`, or `INTERIM_MANAGED`; the current logical clock plus 90 days
    must fall at or before `trials_start`, so a procedure can only be published
    with at least 90 days of lead time, otherwise `ERR_PUBLISH_LEAD_TIME`; and
    the `registration_deadline` plus 14 days must fall at or before
    `trials_start`."

    Design: Corner/validations/publish_lead_time_short
    """
    body = setup_certified_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    # Startup clock 2026-09-01 + 90 days = 2026-11-30 > trials_start 2026-10-30:
    # only 59 days of lead. The 14-day registration rule is satisfied
    # (2026-10-16 + 14d == 2026-10-30), isolating the lead-time failure.
    proc = create_selection_procedure(
        body["id"],
        api=api,
        games_name="2028 Summer Olympics",
        trials_start="2026-10-30T00:00:00Z",
        trials_end="2026-11-01T00:00:00Z",
        registration_deadline="2026-10-16T00:00:00Z",
        qualifying_score=80,
        quota_slots=1,
    )
    resp = api.transition_selection_procedure(
        proc["id"], {"to_state": "PUBLISHED"}, make_ngb_admin_headers(body["id"])
    )
    validate_error(resp, ApiErrorId.ERR_PUBLISH_LEAD_TIME)

    after = read_procedure(body["id"], proc["id"], api=api)
    assert after["proc_status"] == "DRAFT", "a rejected publish mutates nothing"


def test_registration_closed_after_deadline(api):
    """PRD §3.6: "While registration is open, the body enters athletes one at a
    time by `athlete_id`; the entry is accepted only at or before the
    `registration_deadline`, with late entries rejected as
    `ERR_REGISTRATION_CLOSED` and entries against a trials dimension in any
    other state rejected as `ERR_TRIALS_NOT_OPEN`."

    Design: Corner/validations/registration_closed_after_deadline
    """
    body = setup_certified_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    athlete = setup_eligible_athlete(
        body["id"], api=api, full_name="Late Entry", date_of_birth="2000-01-01"
    )
    # Trials sit in REGISTRATION_OPEN (the state gate passes); the clock is
    # past the 2026-12-01 deadline but before trials_start 2026-12-15.
    proc = setup_procedure_with_entries(body["id"], [], api=api, quota_slots=1)
    set_logical_clock("2026-12-02T00:00:00Z", api=api)

    resp = api.create_trials_entry(
        proc["id"],
        {"athlete_id": athlete["id"]},
        make_ngb_admin_headers(body["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_CLOSED)

    after = read_procedure(body["id"], proc["id"], api=api)
    assert after["entries"] == [], "a rejected entry is not appended"


def test_funding_budget_exceeded_on_activation(api, committee_admin_headers):
    """PRD §3.5: "Activation — `OFFERED` to `ACTIVE`, by a `CommitteeAdmin` —
    carries four preconditions: the athlete's `eligibility_status` must be
    `ELIGIBLE` (otherwise `ERR_ATHLETE_NOT_ELIGIBLE`); the athlete's governing
    body must not be `DECERTIFIED`; the agreement's `tier` must not be `NONE`;
    and the fiscal gate must pass — the body's
    `committed_monthly_stipend_cents` plus the new agreement's
    `monthly_stipend_cents`, that sum multiplied by twelve, must not exceed the
    body's `funding_budget_cents`, or the activation is rejected with
    `ERR_FUNDING_BUDGET_EXCEEDED`."

    Design: Corner/validations/funding_budget_exceeded_on_activation
    """
    body = setup_certified_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=3_600_000,
        sport_science_pool_hours=100,
    )
    # Two 1st/A results each -> 2 * (40 * 1.5) = 120.00 trailing points at
    # full recency weight -> TIER_A -> 300000 cents monthly stipend.
    specs = [
        {"event_name": "Cup 1", "event_grade": "A", "placing": 1,
         "event_date": "2026-08-01T00:00:00Z"},
        {"event_name": "Cup 2", "event_grade": "A", "placing": 1,
         "event_date": "2026-08-01T00:00:00Z"},
    ]
    first = setup_eligible_athlete(
        body["id"], api=api, full_name="Fund One", date_of_birth="1998-01-01"
    )
    add_verified_results(first["id"], specs, api=api)
    second = setup_eligible_athlete(
        body["id"], api=api, full_name="Fund Two", date_of_birth="1998-01-02"
    )
    add_verified_results(second["id"], specs, api=api)

    set_logical_clock("2026-10-01T00:00:00Z", api=api)
    ag1 = create_funding_agreement(
        first["id"],
        api=api,
        coverage_start="2026-10-01T00:00:00Z",
        coverage_end="2027-04-01T00:00:00Z",
        points_method="TRAILING_365",
    )
    assert ag1["tier"] == "TIER_A"
    assert ag1["monthly_stipend_cents"] == 300000
    # (0 + 300000) * 12 == 3600000 == budget: "must not exceed" admits equality.
    activated = activate_agreement(ag1["id"], api=api)
    assert activated["status"] == "ACTIVE", (
        "the first activation lands exactly on the budget and is allowed"
    )

    ag2 = create_funding_agreement(
        second["id"],
        api=api,
        coverage_start="2026-10-01T00:00:00Z",
        coverage_end="2027-04-01T00:00:00Z",
        points_method="TRAILING_365",
    )
    # (300000 + 300000) * 12 == 7200000 > 3600000: the fiscal gate fails.
    resp = api.transition_funding_agreement(
        ag2["id"], {"to_state": "ACTIVE"}, committee_admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_FUNDING_BUDGET_EXCEEDED)

    after = read_funding_agreement(ag2["id"], api=api)
    assert after["status"] == "OFFERED", "a rejected activation mutates nothing"


def test_deal_activation_requires_consent(api, committee_admin_headers):
    """PRD §3.7: "An activation attempted straight from `PROPOSED`, skipping
    consent, is rejected with the domain-specific `ERR_DEAL_CONSENT_REQUIRED`
    rather than the generic state error."
    PRD §2.6: "Two domain-specific state rejections also live at this tier and
    take precedence over the generic ones on their endpoints: a trials entry
    attempted while the procedure's `trials_status` is not `REGISTRATION_OPEN`
    is rejected with `ERR_TRIALS_NOT_OPEN` (409), and a deal activation
    (`to_state` of `ACTIVE`) attempted from `PROPOSED` — before athlete consent
    — is rejected with `ERR_DEAL_CONSENT_REQUIRED` (409) rather than the
    generic invalid-state error."

    Design: Corner/validations/deal_activation_requires_consent
    """
    body = setup_certified_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    athlete = setup_eligible_athlete(
        body["id"], api=api, full_name="Deal Test", date_of_birth="2000-01-01"
    )
    deal = create_commercial_deal(
        athlete["id"],
        api=api,
        sponsor_name="Sponsor X",
        gross_value_cents=100000,
        basis="GROSS_BASIS",
        exclusivity_start="2027-01-01T00:00:00Z",
        exclusivity_end="2027-06-30T00:00:00Z",
    )
    assert deal["status"] == "PROPOSED"

    # The OCC version is correct; the consent gate fires instead of any
    # stale-version or generic invalid-state error.
    resp = api.transition_commercial_deal(
        deal["id"],
        deal_transition_payload("ACTIVE", deal["version"]),
        committee_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DEAL_CONSENT_REQUIRED)

    listed = get_success_data(
        api.list_commercial_deals(athlete["id"], committee_admin_headers)
    )
    after = next(d for d in listed if d["id"] == deal["id"])
    assert after["status"] == "PROPOSED"
    # Revenue shares are computed at activation (§3.7), so they stay unset.
    assert after.get("committee_share_cents") is None
    assert after.get("ngb_share_cents") is None
    assert after.get("athlete_share_cents") is None


def test_nomination_before_results_final(api):
    """PRD §3.6: "Nomination requires the procedure `LOCKED` with trials
    `RESULTS_FINALIZED` — otherwise `ERR_RESULTS_NOT_FINAL` — and the body in
    `CERTIFIED`, `PROBATION`, or `INTERIM_MANAGED`."

    Design: Corner/validations/nomination_before_results_final
    """
    body = setup_certified_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    athlete = setup_eligible_athlete(
        body["id"], api=api, full_name="Early Nom", date_of_birth="2000-01-01"
    )
    proc = setup_procedure_with_entries(
        body["id"], [athlete["id"]], api=api, quota_slots=1
    )
    proc = hold_trials(proc, body["id"], api=api)
    roster = create_roster(proc["id"], body["id"], api=api)

    # Trials are HELD, not RESULTS_FINALIZED; the OCC version is correct.
    resp = api.run_nominations(
        roster["id"],
        nomination_payload(roster["version"]),
        make_ngb_admin_headers(body["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RESULTS_NOT_FINAL)

    after = read_roster(roster["id"], api=api)
    assert after["status"] == "DRAFT"
    assert after["slots"] == []
    assert after["version"] == 1, "a rejected nomination is not a mutation"


def test_pending_appeals_block_submit(api):
    """PRD §3.6: "It is blocked while any Appeal of the roster sits in `FILED`
    or `HEARING` (rejected with `ERR_PENDING_APPEALS`), blocked while any
    `PRIMARY` slot still awaits an answer with `slot_status` of `NOMINATED` or
    `PROMOTED` (rejected with `ERR_PENDING_SLOT_DECISIONS`), and impossible
    once the body is `DECERTIFIED`."

    Design: Corner/validations/pending_appeals_block_submit
    """
    body = setup_certified_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    e1 = setup_eligible_athlete(
        body["id"], api=api, full_name="E One", date_of_birth="1998-01-01"
    )
    e2 = setup_eligible_athlete(
        body["id"], api=api, full_name="E Two", date_of_birth="1998-02-02"
    )
    # quota_slots 1: E1 (90, QUALIFIED) takes the only PRIMARY slot; E2
    # (70, UNQUALIFIED) is not a candidate but still holds an entry, which is
    # all the appeal-referential rule requires.
    proc, roster = setup_nominated_roster(
        body["id"], {e1["id"]: 90, e2["id"]: 70}, api=api, quota_slots=1
    )
    # Every PRIMARY slot is answered, isolating the appeal blocker.
    answer_slot(roster["id"], e1["id"], "ACCEPTED", api=api)
    # Filed at the 2026-12-20 nomination clock: inside the 72-hour window.
    file_appeal(roster["id"], e2["id"], api=api, grounds="SELECTION_PROCESS")

    resp = api.transition_roster(
        roster["id"], {"to_state": "SUBMITTED"}, make_ngb_admin_headers(body["id"])
    )
    validate_error(resp, ApiErrorId.ERR_PENDING_APPEALS)

    after = read_roster(roster["id"], api=api)
    assert after["status"] == "NOMINATED", "a blocked submission mutates nothing"


def test_pending_slot_decisions_block_submit(api):
    """PRD §3.6: "It is blocked while any Appeal of the roster sits in `FILED`
    or `HEARING` (rejected with `ERR_PENDING_APPEALS`), blocked while any
    `PRIMARY` slot still awaits an answer with `slot_status` of `NOMINATED` or
    `PROMOTED` (rejected with `ERR_PENDING_SLOT_DECISIONS`), and impossible
    once the body is `DECERTIFIED`."

    Design: Corner/validations/pending_slot_decisions_block_submit
    """
    body = setup_certified_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    athlete = setup_eligible_athlete(
        body["id"], api=api, full_name="No Reply", date_of_birth="2000-01-01"
    )
    # One QUALIFIED entrant, quota_slots 1 -> one unanswered PRIMARY slot;
    # no appeals exist, isolating the slot-decision blocker.
    proc, roster = setup_nominated_roster(
        body["id"], {athlete["id"]: 90}, api=api, quota_slots=1
    )

    resp = api.transition_roster(
        roster["id"], {"to_state": "SUBMITTED"}, make_ngb_admin_headers(body["id"])
    )
    validate_error(resp, ApiErrorId.ERR_PENDING_SLOT_DECISIONS)

    after = read_roster(roster["id"], api=api)
    assert after["status"] == "NOMINATED", "a blocked submission mutates nothing"


def test_duplicate_entry_rejected(api):
    """PRD §3.6: "Entry eligibility is the safety triad of §2.6: the athlete
    must be `ELIGIBLE` (else `ERR_ATHLETE_NOT_ELIGIBLE`), screening-cleared and
    unexpired (else `ERR_SCREENING_NOT_CLEARED`), and training-current within
    365 days (else `ERR_TRAINING_EXPIRED`); and an athlete already holding a
    non-`DISQUALIFIED` entry on this procedure is refused with
    `ERR_DUPLICATE_ENTRY`."

    Design: Corner/validations/duplicate_entry_rejected
    """
    body = setup_certified_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    athlete = setup_eligible_athlete(
        body["id"], api=api, full_name="Dup Entry", date_of_birth="2000-01-01"
    )
    proc = setup_procedure_with_entries(
        body["id"], [athlete["id"]], api=api, quota_slots=1
    )

    resp = api.create_trials_entry(
        proc["id"],
        {"athlete_id": athlete["id"]},
        make_ngb_admin_headers(body["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENTRY)

    after = read_procedure(body["id"], proc["id"], api=api)
    mine = [e for e in after["entries"] if e["athlete_id"] == athlete["id"]]
    assert len(after["entries"]) == 1, "the duplicate attempt appends nothing"
    assert len(mine) == 1, "the first entry is untouched"


def test_agreement_window_overlap_rejected(api, committee_admin_headers):
    """PRD §3.5: "The athlete's existing agreements constrain the window: the
    new coverage window must not overlap any of that athlete's other agreements
    in `OFFERED`, `ACTIVE`, or `SUSPENDED` status, though back-to-back
    adjacency — one window starting exactly where another ends — is allowed,
    and a true overlap is rejected with `ERR_AGREEMENT_WINDOW_OVERLAP`."

    Design: Corner/validations/agreement_window_overlap_rejected
    """
    body = setup_certified_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    athlete = setup_eligible_athlete(
        body["id"], api=api, full_name="Overlap Test", date_of_birth="2000-01-01"
    )
    # ACTIVE agreement covering the half-open window [2026-10-01, 2027-04-01).
    setup_active_agreement(
        athlete["id"],
        api=api,
        activate_at="2026-10-01T00:00:00Z",
        coverage_start="2026-10-01T00:00:00Z",
        coverage_end="2027-04-01T00:00:00Z",
        points_method="TRAILING_365",
    )

    # [2027-01-01, 2027-07-01) intersects the existing window: a true overlap.
    resp = api.create_funding_agreement(
        athlete["id"],
        create_funding_agreement_payload(
            coverage_start="2027-01-01T00:00:00Z",
            coverage_end="2027-07-01T00:00:00Z",
            points_method="TRAILING_365",
        ),
        committee_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_WINDOW_OVERLAP)

    # Starting exactly where the existing window ends is adjacency, allowed
    # under half-open semantics.
    ok_resp = api.create_funding_agreement(
        athlete["id"],
        create_funding_agreement_payload(
            coverage_start="2027-04-01T00:00:00Z",
            coverage_end="2027-10-01T00:00:00Z",
            points_method="TRAILING_365",
        ),
        committee_admin_headers,
    )
    adjacent = validate_success(ok_resp, 201)
    assert parse_iso(adjacent["coverage_start"]) == parse_iso("2027-04-01T00:00:00Z")
    assert adjacent["status"] == "OFFERED"
