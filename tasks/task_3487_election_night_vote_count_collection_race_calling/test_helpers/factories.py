"""Payload factories — one per creatable resource, input fields only.

Optional fields that default server-side (stringer_selection_mode, seats,
is_incumbent, priority_tier, survey_turnout_estimate, historical_dem_share,
stringer_id, rationale, note, reason, outcome) are included in the payload
ONLY when explicitly supplied, so tests can exercise the PRD's defaults.
"""
from .constants import (
    ELECTION_DAY,
    DEFAULT_WINDOW_START,
    DEFAULT_WINDOW_END,
)


# ---------------------------------------------------------------------------
# Events / counties / contests / candidates / feeds
# ---------------------------------------------------------------------------

def create_event_payload(**overrides) -> dict:
    """Election event. stringer_selection_mode is omitted unless given, so the
    PRD's CAREER default is exercised by default."""
    payload = {
        "event_name": "2026 General Election",
        "event_date": ELECTION_DAY,
        "event_type": "GENERAL",
        "total_stringer_hour_budget": 400,
    }
    payload.update(overrides)
    return payload


def create_county_payload(**overrides) -> dict:
    """County registration. survey_turnout_estimate / historical_dem_share are
    included only when explicitly supplied (they are nullable baselines)."""
    payload = {
        "county_fips": "06001",
        "county_name": "Alameda",
        "state_code": "CA",
        "expected_precincts": 10,
        "expected_vote_total": 10000,
    }
    payload.update(overrides)
    return payload


def alameda_payload(**overrides) -> dict:
    """Alameda CA: 10 precincts, expected 10000, survey 8000, hist DEM 0.60."""
    payload = create_county_payload(
        survey_turnout_estimate=8000, historical_dem_share=0.60,
    )
    payload.update(overrides)
    return payload


def contra_costa_payload(**overrides) -> dict:
    """Contra Costa CA: 5 precincts, expected 4000, no survey, no hist share."""
    payload = create_county_payload(
        county_fips="06013", county_name="Contra Costa",
        expected_precincts=5, expected_vote_total=4000,
    )
    payload.update(overrides)
    return payload


def solano_payload(**overrides) -> dict:
    payload = create_county_payload(
        county_fips="06095", county_name="Solano",
        expected_precincts=3, expected_vote_total=3000,
    )
    payload.update(overrides)
    return payload


def marin_payload(**overrides) -> dict:
    payload = create_county_payload(
        county_fips="06041", county_name="Marin",
        expected_precincts=3, expected_vote_total=3000,
    )
    payload.update(overrides)
    return payload


def washoe_nv_payload(**overrides) -> dict:
    payload = create_county_payload(
        county_fips="32031", county_name="Washoe", state_code="NV",
        expected_precincts=4, expected_vote_total=3000,
    )
    payload.update(overrides)
    return payload


def sierra_payload(**overrides) -> dict:
    payload = create_county_payload(
        county_fips="06999", county_name="Sierra",
        expected_precincts=2, expected_vote_total=1500,
    )
    payload.update(overrides)
    return payload


def autauga_al_payload(**overrides) -> dict:
    """County for the historical 2024 rehearsal event."""
    payload = create_county_payload(
        county_fips="01001", county_name="Autauga", state_code="AL",
        expected_precincts=4, expected_vote_total=2000,
    )
    payload.update(overrides)
    return payload


def big_county_payload(**overrides) -> dict:
    """200000-vote county for margin-at-threshold recount scenarios."""
    payload = create_county_payload(
        county_fips="06037", county_name="Big County",
        expected_precincts=4, expected_vote_total=200000,
    )
    payload.update(overrides)
    return payload


def exactshire_payload(**overrides) -> dict:
    """20000-vote county for the over-threshold recount scenario."""
    payload = create_county_payload(
        county_fips="06099", county_name="Exactshire",
        expected_precincts=2, expected_vote_total=20000,
    )
    payload.update(overrides)
    return payload


def create_contest_payload(**overrides) -> dict:
    """Contest. seats is omitted unless given (PRD default is 1)."""
    payload = {
        "office_name": "US Senator",
        "state_code": "CA",
        "contest_type": "FEDERAL_SENATE",
    }
    payload.update(overrides)
    return payload


def create_candidate_payload(candidate_name="Wanda Wynn", party="DEM", **overrides) -> dict:
    """Candidate. is_incumbent is omitted unless given (PRD default false)."""
    payload = {"candidate_name": candidate_name, "party": party}
    payload.update(overrides)
    return payload


def create_feed_source_payload(**overrides) -> dict:
    """Feed source. priority_tier is omitted unless given (default SECONDARY)."""
    payload = {"feed_name": "StateWire CA", "state_codes": ["CA"]}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Stringers and assignments
# ---------------------------------------------------------------------------

def create_stringer_payload(stringer_name="Sally Stringer", home_state="CA", **overrides) -> dict:
    payload = {"stringer_name": stringer_name, "home_state": home_state}
    payload.update(overrides)
    return payload


def create_assignment_payload(county_id, **overrides) -> dict:
    """Assignment. stringer_id is omitted unless given (omission invokes the
    auto-selector). Default window: election day 08:00-20:00 UTC, half-open."""
    payload = {
        "county_id": county_id,
        "window_start": DEFAULT_WINDOW_START,
        "window_end": DEFAULT_WINDOW_END,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Vote reports
# ---------------------------------------------------------------------------

def build_candidate_votes(votes_by_candidate) -> list:
    """Accepts {candidate_id: votes} or a list of (candidate_id, votes) pairs
    and returns the PRD's candidate_votes array shape."""
    if isinstance(votes_by_candidate, dict):
        items = votes_by_candidate.items()
    else:
        items = votes_by_candidate
    return [{"candidate_id": cid, "votes": v} for cid, v in items]


def create_vote_report_payload(
    county_id,
    precincts_reporting,
    votes_by_candidate,
    expected_contest_version,
    source="FEED",
    **overrides,
) -> dict:
    payload = {
        "county_id": county_id,
        "source": source,
        "precincts_reporting": precincts_reporting,
        "candidate_votes": build_candidate_votes(votes_by_candidate),
        "expected_contest_version": expected_contest_version,
    }
    payload.update(overrides)
    return payload


def create_resubmit_payload(precincts_reporting, votes_by_candidate, **overrides) -> dict:
    payload = {
        "precincts_reporting": precincts_reporting,
        "candidate_votes": build_candidate_votes(votes_by_candidate),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Race calls / recounts
# ---------------------------------------------------------------------------

def create_call_payload(winner_candidate_id, expected_contest_version, **overrides) -> dict:
    payload = {
        "winner_candidate_id": winner_candidate_id,
        "expected_contest_version": expected_contest_version,
    }
    payload.update(overrides)
    return payload


def create_recount_case_payload(note=None, **overrides) -> dict:
    payload = {}
    if note is not None:
        payload["note"] = note
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Coverage decisions
# ---------------------------------------------------------------------------

def create_coverage_decision_payload(
    contest_id,
    allocated_stringer_hours=40,
    coverage_start="2026-10-30",
    coverage_end="2026-11-03",
    **overrides,
) -> dict:
    """Coverage decision. rationale is included only when supplied."""
    payload = {
        "contest_id": contest_id,
        "allocated_stringer_hours": allocated_stringer_hours,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
    }
    payload.update(overrides)
    return payload


def create_coverage_revise_payload(**overrides) -> dict:
    """Revise payload: any of allocated_stringer_hours / coverage_start /
    coverage_end; all optional."""
    return dict(overrides)


# ---------------------------------------------------------------------------
# Media customers / invoices
# ---------------------------------------------------------------------------

def create_customer_payload(
    customer_name="WireLite",
    license_tier="BASIC",
    licensed_states=("CA",),
    **overrides,
) -> dict:
    payload = {
        "customer_name": customer_name,
        "license_tier": license_tier,
        "licensed_states": list(licensed_states),
    }
    payload.update(overrides)
    return payload


def wirelite_basic_payload(**overrides) -> dict:
    payload = create_customer_payload("WireLite", "BASIC", ["CA"])
    payload.update(overrides)
    return payload


def metro_news_premium_payload(**overrides) -> dict:
    payload = create_customer_payload("Metro News", "PREMIUM", ["CA"])
    payload.update(overrides)
    return payload
