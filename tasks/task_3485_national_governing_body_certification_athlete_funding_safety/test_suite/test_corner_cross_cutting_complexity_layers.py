"""Corner tests: cross_cutting_complexity_layers section — OCC stale-version
replay on roster nominations and deal transitions, the cumulative complaint
posture threshold cascade, verify-time recomputation of agreement derived
fields, and declined-athlete exclusion across an appeal-driven re-run."""
import pytest

from test_helpers import (
    AUDITOR_CLOSER_ID,
    AUDITOR_ISSUER_ID,
    ApiErrorId,
    add_verified_result,
    answer_slot,
    consent_deal,
    create_commercial_deal,
    create_funding_agreement,
    create_roster,
    deal_transition_payload,
    decide_appeal,
    file_appeal,
    file_complaint,
    investigate_complaint,
    make_ngb_admin_headers,
    move_appeal_to_hearing,
    nomination_payload,
    read_funding_agreement,
    read_governing_body,
    read_roster,
    resolve_complaint,
    run_nominations,
    set_logical_clock,
    setup_certified_body,
    setup_eligible_athlete,
    setup_finalized_procedure,
    setup_nominated_roster,
    submit_result,
    triage_complaint,
    validate_error,
    validate_success,
    verify_result,
)


def test_occ_nomination_stale_roster_version(api):
    """PRD §2.7: "A nomination request against a Roster must carry
    `expected_roster_version`, a non-optional field holding the roster
    `version` the client last observed. If the roster's current `version` has
    advanced past that value — for example because a previous nomination, a
    round of slot decisions, or an appeal-driven revert has already
    legitimately rewritten the slot list since the client read it — the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412), so the selector
    never overwrites a roster state the caller has not observed."
    PRD §3.6: "A selector re-run — `NOMINATED` to `NOMINATED` under the same
    OCC guard and the same procedure and body preconditions — legitimately
    rewrites the slot list, for example after an entry disqualification,
    recomputing the bonus and the ranking while athletes in
    `declined_athlete_ids` stay excluded; `nominated_at` survives the re-run
    untouched."
    PRD §2.4: "`version` (integer):** starts at 1 on creation and increments
    by exactly 1 on every mutation, including mutations caused by system
    cascades rather than direct client writes."

    Design: Corner/cross_cutting_complexity_layers/occ_nomination_stale_roster_version
    """
    body = setup_certified_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    athlete = setup_eligible_athlete(
        body["id"], api=api, full_name="Occ Nom", date_of_birth="2000-01-01"
    )
    proc = setup_finalized_procedure(
        body["id"], {athlete["id"]: 90}, api=api, quota_slots=1
    )
    roster = create_roster(proc["id"], body["id"], api=api)
    stale_version = roster["version"]
    assert stale_version == 1
    set_logical_clock("2026-12-20T00:00:00Z", api=api)

    # First run with the observed version: DRAFT -> NOMINATED, version 1 -> 2.
    first = run_nominations(roster, body["id"], api=api)
    assert first["status"] == "NOMINATED"
    assert first["version"] == stale_version + 1

    # Replay carrying the pre-first-run version: the roster has advanced.
    resp = api.run_nominations(
        roster["id"],
        nomination_payload(stale_version),
        make_ngb_admin_headers(body["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    # The same re-run with the fresh version is a legal NOMINATED self-loop.
    second = validate_success(
        api.run_nominations(
            roster["id"],
            nomination_payload(first["version"]),
            make_ngb_admin_headers(body["id"]),
        ),
        200,
    )
    assert second["status"] == "NOMINATED"
    assert second["version"] == first["version"] + 1


def test_occ_deal_transition_stale_version(api, committee_admin_headers):
    """PRD §2.7: "Every transition request against a CommercialDeal must carry
    `expected_deal_version`, a non-optional field holding the deal `version`
    the client last observed. If the deal's current `version` has advanced —
    for example an athlete consent has just legitimately moved the deal forward
    and a committee activation carrying the pre-consent version is stale — the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.7: "Termination — from `PROPOSED`, `CONSENT_GRANTED`, or `ACTIVE` —
    is available to a `CommitteeAdmin` carrying `expected_deal_version`, and
    arrives by cascade when the athlete's governing body is decertified or the
    athlete retires; the cascade paths carry no version expectation."

    Design: Corner/cross_cutting_complexity_layers/occ_deal_transition_stale_version
    """
    body = setup_certified_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    athlete = setup_eligible_athlete(
        body["id"], api=api, full_name="Occ Deal", date_of_birth="2000-01-01"
    )
    deal = create_commercial_deal(
        athlete["id"],
        api=api,
        sponsor_name="Sponsor Y",
        gross_value_cents=250000,
        basis="GROSS_BASIS",
        exclusivity_start="2027-01-01T00:00:00Z",
        exclusivity_end="2027-06-30T00:00:00Z",
    )
    pre_consent_version = deal["version"]

    # Athlete consent is a legitimate mutation that advances the deal version.
    consented = consent_deal(deal, athlete["id"], api=api)
    assert consented["status"] == "CONSENT_GRANTED"
    assert consented["version"] == pre_consent_version + 1

    # Committee termination carrying the pre-consent version is stale.
    resp = api.transition_commercial_deal(
        deal["id"],
        deal_transition_payload("TERMINATED", pre_consent_version),
        committee_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    # The same termination with the post-consent version succeeds.
    terminated = validate_success(
        api.transition_commercial_deal(
            deal["id"],
            deal_transition_payload("TERMINATED", consented["version"]),
            committee_admin_headers,
        ),
        200,
    )
    assert terminated["status"] == "TERMINATED"


def test_complaint_posture_threshold_trigger(api):
    """PRD §3.2: "The `substantiated_complaint_count` is the number of this
    body's complaints in `SUBSTANTIATED` status whose `resolved_at` falls
    within the trailing 365 days of the current logical clock, the window
    boundary inclusive. When that count reaches 3 the body's
    `complaint_posture` becomes `ELEVATED`; below 3 it is `NORMAL`. The
    threshold is cumulative — the third qualifying complaint flips the posture
    while the second does not — and because the window slides, the count is
    re-evaluated every time the logical clock is set. When the posture crosses
    from `NORMAL` to `ELEVATED` while the body is `CERTIFIED`, the body
    cascades to `PROBATION`."

    Design: Corner/cross_cutting_complexity_layers/complaint_posture_threshold_trigger
    """
    body = setup_certified_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    c1 = file_complaint(
        body["id"], api=api, category="FINANCIAL", severity="MAJOR",
        description="Complaint one",
    )
    c2 = file_complaint(
        body["id"], api=api, category="SELECTION", severity="MAJOR",
        description="Complaint two",
    )
    c3 = file_complaint(
        body["id"], api=api, category="GOVERNANCE", severity="MAJOR",
        description="Complaint three",
    )

    # Segregated triager/resolver; each resolution stamps resolved_at with the
    # logical clock, and all three fall inside the trailing 365-day window.
    triage_complaint(c1["id"], auditor_id=AUDITOR_ISSUER_ID, api=api)
    investigate_complaint(c1["id"], auditor_id=AUDITOR_ISSUER_ID, api=api)
    set_logical_clock("2026-09-10T00:00:00Z", api=api)
    resolve_complaint(c1["id"], "SUBSTANTIATED", auditor_id=AUDITOR_CLOSER_ID, api=api)

    triage_complaint(c2["id"], auditor_id=AUDITOR_ISSUER_ID, api=api)
    investigate_complaint(c2["id"], auditor_id=AUDITOR_ISSUER_ID, api=api)
    set_logical_clock("2026-09-20T00:00:00Z", api=api)
    resolve_complaint(c2["id"], "SUBSTANTIATED", auditor_id=AUDITOR_CLOSER_ID, api=api)

    # Two substantiations: below the threshold, posture stays NORMAL.
    mid = read_governing_body(body["id"], api=api)
    assert mid["substantiated_complaint_count"] == 2
    assert mid["complaint_posture"] == "NORMAL"
    assert mid["status"] == "CERTIFIED", "the cascade only fires at the threshold"

    triage_complaint(c3["id"], auditor_id=AUDITOR_ISSUER_ID, api=api)
    investigate_complaint(c3["id"], auditor_id=AUDITOR_ISSUER_ID, api=api)
    set_logical_clock("2026-09-30T00:00:00Z", api=api)
    resolve_complaint(c3["id"], "SUBSTANTIATED", auditor_id=AUDITOR_CLOSER_ID, api=api)

    # The third qualifying substantiation flips posture and cascades the body.
    final = read_governing_body(body["id"], api=api)
    assert final["substantiated_complaint_count"] == 3
    assert final["complaint_posture"] == "ELEVATED"
    assert final["status"] == "PROBATION"


def test_derived_points_recomputed_on_verify(api, committee_admin_headers):
    """PRD §3.4: "Both values live on the agreement as `trailing_points` and
    `season_points` and are recomputed — from the athlete's verified results as
    of the current logical clock — when a result is verified, when an agreement
    is created, and when an agreement is reassessed."
    PRD §3.4: "`TRAILING_365` anchors on the current logical clock and includes
    each verified result whose age — clock minus `event_date` — is at least 0
    days and at most 365 days. A recency weight applies per result: full weight
    for results aged at most 180 days, and half weight — a multiplier of 0.5 —
    for results aged 181 through 365 days. The method's points are the sum of
    each included result's `base_points` times its recency weight, rounded half
    up to two decimal places."
    PRD §3.4: "The agreement's operative value is its `trailing_points` when
    `points_method` is `TRAILING_365` and its `season_points` when
    `points_method` is `CALENDAR_SEASON`, and the operative value fixes the
    funding `tier` against inclusive thresholds: `TIER_A` at 100 points or
    more, `TIER_B` at 60 or more, `TIER_C` at 30 or more, and `NONE` below 30 —
    a value exactly on a threshold qualifies for that tier. The tier fixes
    `monthly_stipend_cents`: 300000 cents monthly for `TIER_A`, 200000 for
    `TIER_B`, 100000 for `TIER_C`, and 0 for `NONE`."

    Design: Corner/cross_cutting_complexity_layers/derived_points_recomputed_on_verify
    """
    body = setup_certified_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    athlete = setup_eligible_athlete(
        body["id"], api=api, full_name="Derived Test", date_of_birth="2000-01-01"
    )
    # No verified results at creation: zero points, tier NONE, stipend 0.
    set_logical_clock("2026-10-01T00:00:00Z", api=api)
    created = create_funding_agreement(
        athlete["id"],
        api=api,
        coverage_start="2026-10-01T00:00:00Z",
        coverage_end="2027-04-01T00:00:00Z",
        points_method="TRAILING_365",
    )
    assert created["trailing_points"] == pytest.approx(0.0, abs=1e-9)
    assert created["tier"] == "NONE"
    assert created["monthly_stipend_cents"] == 0

    # The verify cascade recomputes the agreement in place — no reassess call.
    # 1st/A on 2026-08-01 is 61 days old at the 2026-10-01 clock: full weight,
    # 40 * 1.5 = 60.00 points -> TIER_B -> 200000 cents.
    result = submit_result(
        athlete["id"],
        api=api,
        event_name="August Cup",
        event_grade="A",
        placing=1,
        event_date="2026-08-01T00:00:00Z",
    )
    verify_result(result["id"], api=api)

    after = read_funding_agreement(created["id"], api=api)
    assert after["trailing_points"] == pytest.approx(60.0, abs=1e-9)
    assert after["tier"] == "TIER_B"
    assert after["monthly_stipend_cents"] == 200000


def test_selector_excludes_declined_on_retry(api):
    """PRD §3.6: "The candidate pool is then filtered: an entrant must be
    `QUALIFIED`, `ELIGIBLE`, screening-cleared and unexpired as of now,
    training-current within 365 days, and absent from the roster's
    `declined_athlete_ids`, a list that persists across re-runs and appeal
    reverts."
    PRD §3.6: "Each candidate's `composite_score` is a weighted blend of 0.7
    times their `trials_score` — the entry's recorded `score` — and 0.3 times
    their season points, rounded half up to two decimal places. Ranking orders
    candidates by `composite_score` descending; ties break by `trials_score`
    descending, then by the earlier entry `result_recorded_at`, then by the
    earlier athlete `created_at`. The first `quota_effective` candidates fill
    `PRIMARY` slots ranked 1 through N, and the next 2 candidates fill
    `ALTERNATE` slots."
    PRD §3.6: "An upheld appeal cascades the roster from `NOMINATED` back to
    `DRAFT`: the `slots` list is cleared entirely, the selector must be re-run
    to rebuild it, and `declined_athlete_ids` is preserved rather than cleared
    so athletes who declined stay excluded from the re-run."

    Design: Corner/cross_cutting_complexity_layers/selector_excludes_declined_on_retry
    """
    body = setup_certified_body(
        api=api,
        name="US Track",
        sport_code="ATHL",
        funding_budget_cents=8_000_000,
        sport_science_pool_hours=100,
    )
    # Each entrant: one VERIFIED 1st/C on 2026-06-01 -> 40.00 season points
    # (CALENDAR_SEASON for the trials_end year, no decay). With trials scores
    # 95/90/85 the composites are 78.5 / 75.0 / 71.5.
    entrants = {}
    for name, dob in (
        ("A One", "1998-01-01"),
        ("A Two", "1998-01-02"),
        ("B One", "1998-01-03"),
    ):
        athlete = setup_eligible_athlete(
            body["id"], api=api, full_name=name, date_of_birth=dob
        )
        add_verified_result(
            athlete["id"],
            event_grade="C",
            placing=1,
            event_date="2026-06-01T00:00:00Z",
            event_name="June Meet",
            api=api,
        )
        entrants[name] = athlete["id"]
    a1, a2, b1 = entrants["A One"], entrants["A Two"], entrants["B One"]

    # quota_slots 2; season sum 40+40+40 = 120 < 250 -> no bonus slot.
    # First run: PRIMARY rank1 A1 (78.5), rank2 A2 (75.0); ALTERNATE B1 (71.5).
    proc, roster = setup_nominated_roster(
        body["id"], {a1: 95, a2: 90, b1: 85}, api=api, quota_slots=2
    )

    # A1 declines (B1 is promoted); A2's appeal is then UPHELD, reverting the
    # roster to DRAFT with slots cleared and declined_athlete_ids preserved.
    answer_slot(roster["id"], a1, "DECLINED", api=api)
    appeal = file_appeal(roster["id"], a2, api=api, grounds="SELECTION_PROCESS")
    move_appeal_to_hearing(appeal["id"], api=api)
    decide_appeal(
        appeal["id"], "UPHELD", decision_rationale="procedure ambiguity", api=api
    )

    mid = read_roster(roster["id"], api=api)
    assert mid["status"] == "DRAFT", "an upheld appeal reverts the roster"
    assert mid["slots"] == [], "the revert clears the slot list entirely"

    rerun = run_nominations(mid, body["id"], api=api)
    assert rerun["status"] == "NOMINATED"
    assert rerun["declined_athlete_ids"] == [a1], (
        "the decline marker survives the appeal revert into the re-run"
    )

    slots = {s["rank"]: s for s in rerun["slots"]}
    assert set(slots) == {1, 2}, (
        f"only A2 and B1 remain candidates, filling the two PRIMARY seats: "
        f"{rerun['slots']}"
    )
    assert slots[1]["athlete_id"] == a2
    assert slots[1]["slot_type"] == "PRIMARY"
    assert slots[1]["composite_score"] == pytest.approx(75.0, abs=1e-9)
    assert slots[2]["athlete_id"] == b1
    assert slots[2]["slot_type"] == "PRIMARY"
    assert slots[2]["composite_score"] == pytest.approx(71.5, abs=1e-9)
    assert all(s["athlete_id"] != a1 for s in rerun["slots"]), (
        "a declined athlete is excluded from the candidate set on the re-run"
    )
