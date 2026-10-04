"""Composite setup helpers.

Every helper builds preconditions from scratch through the public API (the
server is restarted before every test, so nothing persists). Setup calls use
the lenient get_success_data validator so a setup failure surfaces as a clear
"Setup failed" error rather than a confusing assertion failure.

Clock discipline: the logical clock starts at 2026-09-01T00:00:00Z (PRD §2.4);
universe builders pin it to 2026-10-15T00:00:00Z for SETUP work and to
election day 13:00 UTC for LIVE work. The historical 2024-11-05 rehearsal is
reachable ONLY through an explicit backward clock set inside
create_stringer_with_no_show_history — never through a silent past date.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from . import factories
from .constants import (
    SETUP_CLOCK,
    ELECTION_DAY,
    DEFAULT_WINDOW_START,
    DEFAULT_WINDOW_END,
    HISTORICAL_EVENT_DATE,
    HISTORICAL_WINDOW_START,
    HISTORICAL_WINDOW_END,
    HISTORICAL_NO_SHOW_CLOCK,
)
from .test_users import (
    TEST_USERS,
    ANALYST_NINA_ID,
    CHIEF_RAY_ID,
    make_analyst_headers,
    make_chief_headers,
    make_stringer_headers,
)

ADMIN = TEST_USERS["admin_headers"]
PLANNER = TEST_USERS["planner_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
FEED_OPERATOR = TEST_USERS["feed_operator_headers"]
CLERK = TEST_USERS["clerk_headers"]


def _setup_failed(step: str, response) -> AssertionError:
    return AssertionError(
        f"Setup failed at {step}: {response.status_code} {response.text}"
    )


def _ok(response, step: str) -> dict:
    try:
        return get_success_data(response)
    except AssertionError as exc:
        raise _setup_failed(step, response) from exc


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

def set_clock(current_utc: str) -> dict:
    """Move the logical clock to any instant (either direction). Admin only."""
    return _ok(
        api_client.set_current_utc(current_utc, ADMIN),
        f"set_clock({current_utc})",
    )


def reset_clock_to_setup() -> dict:
    """Pin the clock to the standard pre-election build date 2026-10-15."""
    return set_clock(SETUP_CLOCK)


def move_clock_to_election_day(event_date: str = ELECTION_DAY) -> dict:
    """Pin the clock inside election day (13:00 UTC) so LIVE is admissible and
    the default 08:00-20:00 assignment window contains the clock."""
    return set_clock(f"{event_date}T13:00:00Z")


# ---------------------------------------------------------------------------
# Single-resource creators
# ---------------------------------------------------------------------------

def create_event(**overrides) -> dict:
    return _ok(
        api_client.create_event(factories.create_event_payload(**overrides), ADMIN),
        "create_event",
    )


def create_county(event_id: str, payload=None, **overrides) -> dict:
    payload = payload if payload is not None else factories.create_county_payload(**overrides)
    return _ok(api_client.create_county(event_id, payload, ADMIN), "create_county")


def create_contest(event_id: str, payload=None, **overrides) -> dict:
    payload = payload if payload is not None else factories.create_contest_payload(**overrides)
    return _ok(api_client.create_contest(event_id, payload, ADMIN), "create_contest")


def patch_contest(contest_id: str, **fields) -> dict:
    return _ok(api_client.patch_contest(contest_id, fields, ADMIN), "patch_contest")


def link_county(contest_id: str, county_id: str) -> dict:
    return _ok(
        api_client.create_county_link(contest_id, county_id, ADMIN),
        "link_county",
    )


def create_candidate(contest_id: str, candidate_name="Wanda Wynn", party="DEM", **overrides) -> dict:
    return _ok(
        api_client.create_candidate(
            contest_id,
            factories.create_candidate_payload(candidate_name, party, **overrides),
            ADMIN,
        ),
        f"create_candidate({candidate_name})",
    )


def create_feed_source(event_id: str, **overrides) -> dict:
    return _ok(
        api_client.create_feed_source(
            event_id, factories.create_feed_source_payload(**overrides), ADMIN,
        ),
        "create_feed_source",
    )


def create_stringer(stringer_name="Sally Stringer", home_state="CA", **overrides) -> dict:
    return _ok(
        api_client.create_stringer(
            factories.create_stringer_payload(stringer_name, home_state, **overrides),
            COORDINATOR,
        ),
        f"create_stringer({stringer_name})",
    )


def create_assignment(
    event_id: str,
    county_id: str,
    stringer_id=None,
    window_start: str = DEFAULT_WINDOW_START,
    window_end: str = DEFAULT_WINDOW_END,
) -> dict:
    """Create an assignment. Omit stringer_id to invoke the auto-selector."""
    payload = factories.create_assignment_payload(
        county_id, window_start=window_start, window_end=window_end,
    )
    if stringer_id is not None:
        payload["stringer_id"] = stringer_id
    return _ok(
        api_client.create_assignment(event_id, payload, COORDINATOR),
        "create_assignment",
    )


def check_in_assignment(assignment_id: str, stringer_id: str) -> dict:
    """Self-service check-in: X-User-ID must equal the assignment's stringer."""
    return _ok(
        api_client.check_in_assignment(assignment_id, make_stringer_headers(stringer_id)),
        "check_in_assignment",
    )


def assignment_action(assignment_id: str, action: str) -> dict:
    """Coordinator lifecycle action: RELEASE | NO_SHOW | REDEPLOY."""
    return _ok(
        api_client.assignment_status_action(assignment_id, action, COORDINATOR),
        f"assignment_action({action})",
    )


def create_customer(customer_name="WireLite", license_tier="BASIC", licensed_states=("CA",)) -> dict:
    return _ok(
        api_client.create_media_customer(
            factories.create_customer_payload(customer_name, license_tier, licensed_states),
            ADMIN,
        ),
        f"create_customer({customer_name})",
    )


def create_wirelite_basic() -> dict:
    return create_customer("WireLite", "BASIC", ("CA",))


def create_metro_news_premium() -> dict:
    return create_customer("Metro News", "PREMIUM", ("CA",))


# ---------------------------------------------------------------------------
# Reads used by fixtures
# ---------------------------------------------------------------------------

def get_event(event_id: str, headers=None) -> dict:
    return _ok(api_client.get_event(event_id, headers or ADMIN), "get_event")


def get_contest(contest_id: str, headers=None) -> dict:
    return _ok(api_client.get_contest(contest_id, headers or ADMIN), "get_contest")


def get_contest_version(contest_id: str, headers=None) -> int:
    """Fresh contest version for OCC chaining (PRD §2.7)."""
    return get_contest(contest_id, headers)["version"]


def get_stringer(stringer_id: str, headers=None) -> dict:
    return _ok(api_client.get_stringer(stringer_id, headers or COORDINATOR), "get_stringer")


def get_tabulation(contest_id: str, headers=None) -> dict:
    return _ok(api_client.get_tabulation(contest_id, headers or CLERK), "get_tabulation")


def list_customer_deliveries(customer_id: str, headers=None, params=None):
    """Admin reads the feed by default; returns (rows, meta)."""
    return validate_paginated(
        api_client.list_customer_deliveries(customer_id, headers or ADMIN, params=params)
    )


def list_contest_deliveries(contest_id: str, headers=None, params=None):
    return validate_paginated(
        api_client.list_contest_deliveries(contest_id, headers or ADMIN, params=params)
    )


# ---------------------------------------------------------------------------
# Posture ladder (PRD §2.5)
# ---------------------------------------------------------------------------

def advance_posture(event_id: str, target_posture: str) -> dict:
    return _ok(
        api_client.transition_posture(event_id, target_posture, ADMIN),
        f"advance_posture({target_posture})",
    )


def advance_to_candidates_locked(event_id: str) -> dict:
    return advance_posture(event_id, "CANDIDATES_LOCKED")


def advance_to_live(event_id: str, event_date: str = ELECTION_DAY) -> dict:
    """Move the clock inside election day, then take CANDIDATES_LOCKED -> LIVE."""
    move_clock_to_election_day(event_date)
    return advance_posture(event_id, "LIVE")


def advance_to_tabulation(event_id: str) -> dict:
    """LIVE -> TABULATION; requires an existing report in the event."""
    return advance_posture(event_id, "TABULATION")


def advance_to_certification(event_id: str) -> dict:
    """TABULATION -> CERTIFICATION; requires every contest COMPLETE."""
    return advance_posture(event_id, "CERTIFICATION")


def advance_to_archived(event_id: str) -> dict:
    return advance_posture(event_id, "ARCHIVED")


# ---------------------------------------------------------------------------
# Vote reports (OCC-chained) and desk review
# ---------------------------------------------------------------------------

def submit_feed_report(
    contest_id: str,
    county_id: str,
    precincts_reporting: int,
    votes_by_candidate,
) -> dict:
    """Re-read the contest version, then submit a FEED report as FeedOperator."""
    version = get_contest_version(contest_id)
    payload = factories.create_vote_report_payload(
        county_id, precincts_reporting, votes_by_candidate, version, source="FEED",
    )
    return _ok(
        api_client.create_vote_report(contest_id, payload, FEED_OPERATOR),
        "submit_feed_report",
    )


def submit_stringer_report(
    contest_id: str,
    county_id: str,
    stringer_id: str,
    precincts_reporting: int,
    votes_by_candidate,
) -> dict:
    """Re-read the contest version, then submit a STRINGER report as the
    stringer themself (entity-backed headers)."""
    version = get_contest_version(contest_id)
    payload = factories.create_vote_report_payload(
        county_id, precincts_reporting, votes_by_candidate, version, source="STRINGER",
    )
    return _ok(
        api_client.create_vote_report(contest_id, payload, make_stringer_headers(stringer_id)),
        "submit_stringer_report",
    )


def accept_report(report_id: str) -> dict:
    return _ok(api_client.review_vote_report(report_id, "ACCEPT", CLERK), "accept_report")


def reject_report(report_id: str) -> dict:
    return _ok(api_client.review_vote_report(report_id, "REJECT", CLERK), "reject_report")


def void_report(report_id: str) -> dict:
    return _ok(api_client.review_vote_report(report_id, "VOID", CLERK), "void_report")


def resubmit_report(
    report_id: str,
    precincts_reporting: int,
    votes_by_candidate,
    headers,
) -> dict:
    """Resubmit a REJECTED report. headers choose the channel: the original
    stringer (make_stringer_headers(author id)) or any FeedOperator."""
    payload = factories.create_resubmit_payload(precincts_reporting, votes_by_candidate)
    return _ok(api_client.resubmit_vote_report(report_id, payload, headers), "resubmit_report")


def submit_report_sequence(contest_id: str, specs: list) -> list:
    """Run a list of report specs in order; each spec is a dict:
    {county_id, precincts_reporting, votes, source? ("FEED"), stringer_id?,
     accept? (True), review? ("ACCEPT"|"REJECT"|None)}.
    Returns the list of resulting VoteReport payloads."""
    reports = []
    for spec in specs:
        source = spec.get("source", "FEED")
        if source == "STRINGER":
            report = submit_stringer_report(
                contest_id, spec["county_id"], spec["stringer_id"],
                spec["precincts_reporting"], spec["votes"],
            )
        else:
            report = submit_feed_report(
                contest_id, spec["county_id"],
                spec["precincts_reporting"], spec["votes"],
            )
        review = spec.get("review", "ACCEPT" if spec.get("accept", True) else None)
        if review == "ACCEPT":
            report = accept_report(report["id"])
        elif review == "REJECT":
            report = reject_report(report["id"])
        reports.append(report)
    return reports


# ---------------------------------------------------------------------------
# Calls, recounts, coverage, invoices
# ---------------------------------------------------------------------------

def propose_call(contest_id: str, winner_candidate_id: str, analyst_id: str = ANALYST_NINA_ID) -> dict:
    """Re-read the contest version, then propose a call as the analyst."""
    version = get_contest_version(contest_id)
    payload = factories.create_call_payload(winner_candidate_id, version)
    return _ok(
        api_client.create_call(contest_id, payload, make_analyst_headers(analyst_id)),
        "propose_call",
    )


def publish_call(call_id: str, chief_id: str = CHIEF_RAY_ID) -> dict:
    return _ok(
        api_client.decide_call(call_id, "PUBLISH", make_chief_headers(chief_id)),
        "publish_call",
    )


def retract_call(call_id: str, reason: str, chief_id: str = CHIEF_RAY_ID) -> dict:
    return _ok(
        api_client.decide_call(call_id, "RETRACT", make_chief_headers(chief_id), reason=reason),
        "retract_call",
    )


def file_recount(contest_id: str, note=None) -> dict:
    return _ok(
        api_client.create_recount_case(contest_id, TEST_USERS["recount_officer_headers"], note=note),
        "file_recount",
    )


def activate_recount(case_id: str) -> dict:
    return _ok(
        api_client.decide_recount_case(case_id, "ACTIVATE", TEST_USERS["recount_officer_headers"]),
        "activate_recount",
    )


def dismiss_recount(case_id: str, note=None) -> dict:
    return _ok(
        api_client.decide_recount_case(case_id, "DISMISS", TEST_USERS["recount_officer_headers"], note=note),
        "dismiss_recount",
    )


def resolve_recount(case_id: str, outcome: str, note=None) -> dict:
    return _ok(
        api_client.decide_recount_case(
            case_id, "RESOLVE", TEST_USERS["recount_officer_headers"],
            outcome=outcome, note=note,
        ),
        f"resolve_recount({outcome})",
    )


def propose_coverage(
    event_id: str,
    contest_id: str,
    allocated_stringer_hours: int = 40,
    coverage_start: str = "2026-10-30",
    coverage_end: str = "2026-11-03",
    rationale=None,
) -> dict:
    payload = factories.create_coverage_decision_payload(
        contest_id, allocated_stringer_hours, coverage_start, coverage_end,
    )
    if rationale is not None:
        payload["rationale"] = rationale
    return _ok(
        api_client.create_coverage_decision(event_id, payload, PLANNER),
        "propose_coverage",
    )


def review_coverage(decision_id: str, decision: str) -> dict:
    """APPROVE | DECLINE | FUND (admin)."""
    return _ok(
        api_client.review_coverage_decision(decision_id, decision, ADMIN),
        f"review_coverage({decision})",
    )


def revise_coverage(decision_id: str, **fields) -> dict:
    return _ok(
        api_client.revise_coverage_decision(
            decision_id, factories.create_coverage_revise_payload(**fields), PLANNER,
        ),
        "revise_coverage",
    )


def generate_invoice(customer_id: str, period: str = "2026-11", headers=None) -> dict:
    """Generate the monthly invoice. Admin by default; pass
    make_customer_headers(customer_id) for the self-service path."""
    return _ok(
        api_client.create_invoice(customer_id, period, headers or ADMIN),
        f"generate_invoice({period})",
    )


# ---------------------------------------------------------------------------
# Composite universes
# ---------------------------------------------------------------------------

def setup_standard_universe(
    advance_to: str = "LIVE",
    link_alameda: bool = True,
    link_contra_costa: bool = True,
    with_contra_costa: bool = True,
    extra_counties=None,
    link_extra_counties: bool = True,
    extra_candidates=None,
    seats=None,
    contest_overrides=None,
    event_overrides=None,
    with_feed: bool = True,
    customers=(),
) -> dict:
    """The standard rehearsal universe shared by most scenarios.

    Builds: clock pinned to 2026-10-15 -> GENERAL event dated 2026-11-03
    (budget 400) -> counties Alameda (10 precincts, expected 10000, survey
    8000, hist DEM 0.60) and Contra Costa (5, 4000, no baselines) -> contest
    US Senator (CA, FEDERAL_SENATE) -> county links -> candidates Wanda Wynn
    (DEM) and Tom Traylor (REP) -> feed StateWire CA -> posture advance.

    advance_to: "SETUP" | "CANDIDATES_LOCKED" | "LIVE". TABULATION is not
    reachable here because it requires an existing report; the report-bearing
    composites advance further.

    extra_counties: list of (key, payload) registered on the event and
    optionally linked. extra_candidates: list of (key, name, party).
    customers: subset of ("basic", "premium") registered up front so the
    delivery fan-out sees them.

    Returns {"event", "contest", "feed", "counties": {key: row},
             "candidates": {key: row}, "customers": {tier: row}}.
    """
    reset_clock_to_setup()
    event = create_event(**(event_overrides or {}))

    counties = {"alameda": create_county(event["id"], factories.alameda_payload())}
    if with_contra_costa:
        counties["contra_costa"] = create_county(event["id"], factories.contra_costa_payload())
    for key, payload in (extra_counties or []):
        counties[key] = create_county(event["id"], payload)

    contest_fields = dict(contest_overrides or {})
    if seats is not None:
        contest_fields["seats"] = seats
    contest = create_contest(event["id"], **contest_fields)

    if link_alameda:
        link_county(contest["id"], counties["alameda"]["id"])
    if with_contra_costa and link_contra_costa:
        link_county(contest["id"], counties["contra_costa"]["id"])
    if link_extra_counties:
        for key, _payload in (extra_counties or []):
            link_county(contest["id"], counties[key]["id"])

    candidates = {
        "wanda": create_candidate(contest["id"], "Wanda Wynn", "DEM"),
        "tom": create_candidate(contest["id"], "Tom Traylor", "REP"),
    }
    for key, name, party in (extra_candidates or []):
        candidates[key] = create_candidate(contest["id"], name, party)

    feed = create_feed_source(event["id"]) if with_feed else None

    customer_rows = {}
    if "basic" in customers:
        customer_rows["basic"] = create_wirelite_basic()
    if "premium" in customers:
        customer_rows["premium"] = create_metro_news_premium()

    if advance_to == "CANDIDATES_LOCKED":
        advance_to_candidates_locked(event["id"])
    elif advance_to == "LIVE":
        advance_to_candidates_locked(event["id"])
        advance_to_live(event["id"], event["event_date"])
    elif advance_to != "SETUP":
        raise ValueError(f"advance_to={advance_to!r} not reachable without reports")

    return {
        "event": get_event(event["id"]),
        "contest": get_contest(contest["id"]),
        "feed": feed,
        "counties": counties,
        "candidates": candidates,
        "customers": customer_rows,
    }


def _resolve_refs(universe: dict, spec: dict) -> dict:
    """Resolve county/candidate keys in a report spec to live ids."""
    resolved = dict(spec)
    county = resolved["county"]
    if isinstance(county, str) and county in universe["counties"]:
        resolved["county_id"] = universe["counties"][county]["id"]
    else:
        resolved["county_id"] = resolved.pop("county", county)
    votes = {}
    for cand_key, n in spec["votes"].items():
        cand = universe["candidates"].get(cand_key)
        votes[cand["id"] if cand else cand_key] = n
    resolved["votes"] = votes
    return resolved


def setup_universe_with_reports(
    report_specs: list,
    advance_to=None,
    **universe_kwargs,
) -> dict:
    """Standard universe at LIVE, then the given reports submitted (and
    reviewed per spec), then an optional further posture advance
    ("TABULATION" once a report exists). Each spec names counties/candidates
    by universe key ("alameda", "wanda") or raw id.

    Returns the universe dict plus "reports": [VoteReport rows in order].
    """
    universe = setup_standard_universe(advance_to="LIVE", **universe_kwargs)
    specs = [_resolve_refs(universe, s) for s in report_specs]
    reports = submit_report_sequence(universe["contest"]["id"], specs)
    if advance_to is not None:
        advance_posture(universe["event"]["id"], advance_to)
        universe["event"] = get_event(universe["event"]["id"])
    universe["contest"] = get_contest(universe["contest"]["id"])
    universe["reports"] = reports
    return universe


def setup_complete_contest(
    alameda_votes=None,
    contra_costa_votes=None,
    alameda_precincts: int = 10,
    contra_costa_precincts: int = 5,
    advance_to: str = "TABULATION",
    **universe_kwargs,
) -> dict:
    """Universe with full-precinct ACCEPTED reports on every linked county,
    so the contest's tabulation_status is COMPLETE; posture TABULATION by
    default (recount filing and call publication both live there).

    Defaults: Alameda p10 W6000/T4000; Contra Costa p5 W2200/T1800.
    Pass link_contra_costa=False for a single-county COMPLETE contest.
    """
    link_both = universe_kwargs.get("link_contra_costa", True)
    specs = [{
        "county": "alameda",
        "precincts_reporting": alameda_precincts,
        "votes": alameda_votes or {"wanda": 6000, "tom": 4000},
    }]
    if link_both:
        specs.append({
            "county": "contra_costa",
            "precincts_reporting": contra_costa_precincts,
            "votes": contra_costa_votes or {"wanda": 2200, "tom": 1800},
        })
    return setup_universe_with_reports(specs, advance_to=advance_to, **universe_kwargs)


def setup_margin_threshold_contest(**universe_kwargs) -> dict:
    """COMPLETE contest whose margin is exactly 0.005 (Alameda p10
    W5025/T4975, Contra Costa p5 W2010/T1990) — fileable for recount."""
    return setup_complete_contest(
        alameda_votes={"wanda": 5025, "tom": 4975},
        contra_costa_votes={"wanda": 2010, "tom": 1990},
        **universe_kwargs,
    )


def setup_proposed_call(
    winner: str = "wanda",
    analyst_id: str = ANALYST_NINA_ID,
    universe=None,
    **universe_kwargs,
) -> dict:
    """COMPLETE contest at TABULATION with one PROPOSED call."""
    if universe is None:
        universe = setup_complete_contest(**universe_kwargs)
    call = propose_call(
        universe["contest"]["id"],
        universe["candidates"][winner]["id"],
        analyst_id=analyst_id,
    )
    universe["call"] = call
    universe["contest"] = get_contest(universe["contest"]["id"])
    return universe


def setup_published_call(
    winner: str = "wanda",
    analyst_id: str = ANALYST_NINA_ID,
    chief_id: str = CHIEF_RAY_ID,
    universe=None,
    **universe_kwargs,
) -> dict:
    """COMPLETE contest at TABULATION with one PUBLISHED call (certainty
    holds for the default totals)."""
    universe = setup_proposed_call(winner, analyst_id, universe, **universe_kwargs)
    universe["call"] = publish_call(universe["call"]["id"], chief_id=chief_id)
    universe["contest"] = get_contest(universe["contest"]["id"])
    return universe


def setup_active_recount_after_certification(
    chief_id: str = CHIEF_RAY_ID,
    **universe_kwargs,
) -> dict:
    """The full pre-cascade state: margin-threshold COMPLETE contest (margin
    exactly 0.005 so the recount is fileable), call published, posture
    advanced to CERTIFICATION, recount FILED then ACTIVATEd — which
    auto-reopens the event CERTIFICATION -> TABULATION and the contest
    COMPLETE -> REPORTING. The RESOLVE trigger is left to the test.
    Returns universe with "call" and "recount"."""
    universe = setup_margin_threshold_contest(**universe_kwargs)
    universe = setup_proposed_call(universe=universe)
    universe["call"] = publish_call(universe["call"]["id"], chief_id=chief_id)
    universe["contest"] = get_contest(universe["contest"]["id"])
    advance_to_certification(universe["event"]["id"])
    recount = file_recount(universe["contest"]["id"])
    recount = activate_recount(recount["id"])
    universe["recount"] = recount
    universe["event"] = get_event(universe["event"]["id"])
    universe["contest"] = get_contest(universe["contest"]["id"])
    return universe


# ---------------------------------------------------------------------------
# Stringer network composites
# ---------------------------------------------------------------------------

def create_stringer_with_no_show_history(
    stringer_name="Sally Stringer",
    home_state="CA",
) -> dict:
    """A stringer carrying one NO_SHOW from the historical 2024-11-05 event:
    career reliability dented to 75, recent-form untouched once the old event
    ages past the 365-day window.

    The past is reached only by EXPLICIT backward clock sets: build at the
    setup clock, then move the clock to 2024-11-06 (past the historical
    window) to mark the NO_SHOW. Returns {"stringer", "historical_event",
    "historical_county", "historical_assignment"}. The clock is left at
    2024-11-06; callers move it forward as needed.
    """
    reset_clock_to_setup()
    old_event = create_event(
        event_name="2024 General Election",
        event_date=HISTORICAL_EVENT_DATE,
        event_type="GENERAL",
        total_stringer_hour_budget=100,
    )
    old_county = create_county(old_event["id"], factories.autauga_al_payload())
    stringer = create_stringer(stringer_name, home_state)
    old_assignment = create_assignment(
        old_event["id"], old_county["id"],
        stringer_id=stringer["id"],
        window_start=HISTORICAL_WINDOW_START,
        window_end=HISTORICAL_WINDOW_END,
    )
    set_clock(HISTORICAL_NO_SHOW_CLOCK)
    old_assignment = assignment_action(old_assignment["id"], "NO_SHOW")
    return {
        "stringer": get_stringer(stringer["id"]),
        "historical_event": old_event,
        "historical_county": old_county,
        "historical_assignment": old_assignment,
    }


def setup_active_assignment(
    county_key: str = "alameda",
    stringer_name="Sally Stringer",
    home_state="CA",
    window_start: str = DEFAULT_WINDOW_START,
    window_end: str = DEFAULT_WINDOW_END,
    **universe_kwargs,
) -> dict:
    """Universe at LIVE with a stringer checked in (assignment ACTIVE) on the
    given county — the credential needed for STRINGER vote reports. Returns
    the universe plus "stringer" and "assignment"."""
    universe = setup_standard_universe(advance_to="SETUP", **universe_kwargs)
    stringer = create_stringer(stringer_name, home_state)
    assignment = create_assignment(
        universe["event"]["id"],
        universe["counties"][county_key]["id"],
        stringer_id=stringer["id"],
        window_start=window_start,
        window_end=window_end,
    )
    advance_to_candidates_locked(universe["event"]["id"])
    advance_to_live(universe["event"]["id"], universe["event"]["event_date"])
    assignment = check_in_assignment(assignment["id"], stringer["id"])
    universe["stringer"] = stringer
    universe["assignment"] = assignment
    universe["event"] = get_event(universe["event"]["id"])
    universe["contest"] = get_contest(universe["contest"]["id"])
    return universe
