"""Scenario builders.

The harness restarts the server before every test, so each test starts against
an empty database and must build every precondition through the API itself.
These builders do that in composable layers, so a test can stop at exactly the
state it wants to probe:

    charter → adopt bylaws → teams → memberships → lane pairs → schedule
            → sanction (the four-hop cascade) → lineups → open → scores
            → certify → dues → close season → draft/approve/disburse

Setup calls use ``get_success_data``, which is lenient about the exact success
status; a test's own assertions use ``validate_success`` so a wrong status is
still caught where it matters.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pytest
from prd_bench_local_runner.testing.validators import get_success_data

from test_helpers import factories as f
from test_helpers.api_client import ApiClient
from test_helpers.constants import (
    BASE_BYLAWS,
    LANE_CERTIFIED_THROUGH,
    LATE_PENALTY_CENTS,
    LOCAL_ASSOCIATION_FEE_CENTS,
    NATIONAL_FEE_ADULT_CENTS,
    NATIONAL_FEE_YOUTH_CENTS,
    ORG_MEETING_INSTANT,
    WEEK1_ENDS_AT,
    WEEK1_STARTS_AT,
    WEEK2_ENDS_AT,
    WEEK2_STARTS_AT,
)
from test_helpers.test_users import (
    make_association_officer_headers,
    make_bowler_headers,
    make_league_secretary_headers,
    make_league_treasurer_headers,
    make_team_captain_headers,
)
from test_helpers.types import MemberClass, RosterRole


@dataclass
class RosterSpec:
    """One bowler to enrol: who they are and what they bring with them."""

    full_name: str
    member_class: MemberClass = MemberClass.ADULT
    prior_season_average: Optional[int] = None
    prior_season_games: int = 0
    team_index: Optional[int] = 0
    roster_role: RosterRole = RosterRole.REGULAR


# The shared roster: four adults across two teams, each carrying a prior-season
# record of 30 games, which is past the 21-game carryover threshold.
DEFAULT_ROSTER: Tuple[RosterSpec, ...] = (
    RosterSpec("Cara Captain", MemberClass.ADULT, 180, 30, 0),
    RosterSpec("Dan Bowler", MemberClass.ADULT, 195, 30, 0),
    RosterSpec("Eve Captain", MemberClass.ADULT, 170, 30, 1),
    RosterSpec("Fay Bowler", MemberClass.ADULT, 160, 30, 1),
)

DEFAULT_TEAM_NAMES: Tuple[str, ...] = ("Alley Cats", "Pin Pals")


@dataclass
class Scenario:
    """Everything a test needs to reach into the world it just built."""

    api: ApiClient
    officer: Dict[str, str]
    secretary_member_id: str
    treasurer_member_id: str
    league_id: str
    bylaws: Dict[str, Any]
    member_ids: List[str] = field(default_factory=list)
    member_classes: List[MemberClass] = field(default_factory=list)
    team_ids: List[str] = field(default_factory=list)
    membership_ids: List[str] = field(default_factory=list)
    membership_teams: List[Optional[int]] = field(default_factory=list)
    lane_pair_ids: List[str] = field(default_factory=list)
    match_ids: List[str] = field(default_factory=list)
    total_weeks: int = 0

    # ─── identities ─────────────────────────────────────
    @property
    def secretary(self) -> Dict[str, str]:
        return make_league_secretary_headers(self.secretary_member_id)

    @property
    def treasurer(self) -> Dict[str, str]:
        return make_league_treasurer_headers(self.treasurer_member_id)

    def bowler(self, index: int) -> Dict[str, str]:
        """Act as the ``index``-th enrolled bowler, in the plain role."""
        return make_bowler_headers(self.member_ids[index])

    def captain(self, index: int) -> Dict[str, str]:
        """Act as the ``index``-th enrolled bowler, asserting a captaincy."""
        return make_team_captain_headers(self.member_ids[index])

    # ─── fresh reads ────────────────────────────────────
    def league(self) -> Dict[str, Any]:
        return get_success_data(self.api.get_league(self.league_id, self.secretary))

    def league_version(self) -> int:
        return self.league()["version"]

    def membership(self, index: int) -> Dict[str, Any]:
        return get_success_data(
            self.api.get_membership(self.membership_ids[index], self.secretary)
        )

    def team(self, index: int) -> Dict[str, Any]:
        return get_success_data(self.api.get_team(self.team_ids[index], self.secretary))

    def match(self, index: int = 0) -> Dict[str, Any]:
        return get_success_data(self.api.get_match(self.match_ids[index], self.secretary))

    def match_version(self, index: int = 0) -> int:
        return self.match(index)["version"]

    def prize_fund(self) -> Dict[str, Any]:
        """The fund created silently at chartering, found through the listing."""
        rows = get_success_data(
            self.api.list_prize_funds(self.secretary, params={"league_id": self.league_id})
        )
        assert rows, "chartering must have created exactly one prize fund"
        return rows[0]

    def prize_fund_id(self) -> str:
        return self.prize_fund()["id"]

    def series_entries(self, match_index: int = 0, team_index: Optional[int] = None):
        """The lineup-slot listing is the only discovery channel for slots."""
        params: Dict[str, Any] = {"match_id": self.match_ids[match_index], "limit": 100}
        if team_index is not None:
            params["team_id"] = self.team_ids[team_index]
        return get_success_data(self.api.list_series_entries(self.secretary, params=params))


# ─── the logical clock ─────────────────────────────────

def set_clock(api: ApiClient, instant: str) -> None:
    """Move the logical clock; every later stamp and comparison uses it."""
    get_success_data(api.set_clock(instant, make_association_officer_headers()))


# ─── layer 1: members, charter, bylaws ─────────────────

def register_member(
    api: ApiClient,
    full_name: str = "Dana Kegler",
    member_class: MemberClass = MemberClass.ADULT,
    **overrides: Any,
) -> str:
    data = get_success_data(
        api.register_member(
            f.member_payload(full_name, member_class, **overrides),
            make_association_officer_headers(),
        )
    )
    return data["id"]


def charter_league(
    api: ApiClient,
    *,
    declared_team_count: int = 2,
    organizational_meeting_at: str = ORG_MEETING_INSTANT,
    secretary_member_id: Optional[str] = None,
    treasurer_member_id: Optional[str] = None,
    **overrides: Any,
) -> Scenario:
    """Register the two officers (unless supplied) and charter the league.

    The league is left at ``FORMING`` with every bylaw null — chartering accepts
    no bylaw field at all.
    """
    secretary_id = secretary_member_id or register_member(
        api, "Ann Secretary", MemberClass.ADULT
    )
    treasurer_id = treasurer_member_id or register_member(
        api, "Bob Treasurer", MemberClass.ADULT
    )
    data = get_success_data(
        api.charter_league(
            f.league_payload(
                secretary_id,
                treasurer_id,
                declared_team_count=declared_team_count,
                organizational_meeting_at=organizational_meeting_at,
                **overrides,
            ),
            make_league_secretary_headers(secretary_id),
        )
    )
    return Scenario(
        api=api,
        officer=make_association_officer_headers(),
        secretary_member_id=secretary_id,
        treasurer_member_id=treasurer_id,
        league_id=data["id"],
        bylaws={},
    )


def adopt_bylaws(scn: Scenario, **overrides: Any) -> Dict[str, Any]:
    """Adopt (or amend) the bylaws, echoing the league's current version."""
    payload = f.bylaws_payload(scn.league_version(), **overrides)
    data = get_success_data(
        scn.api.adopt_bylaws(scn.league_id, payload, scn.secretary)
    )
    scn.bylaws = {key: payload[key] for key in BASE_BYLAWS}
    return data


def add_team(scn: Scenario, name: str) -> str:
    data = get_success_data(
        scn.api.create_team(f.team_payload(scn.league_id, name), scn.secretary)
    )
    scn.team_ids.append(data["id"])
    return data["id"]


def enrol(scn: Scenario, spec: RosterSpec) -> str:
    """Register the person nationally and enrol them in the league."""
    member_id = register_member(scn.api, spec.full_name, spec.member_class)
    team_id = (
        scn.team_ids[spec.team_index] if spec.team_index is not None else None
    )
    data = get_success_data(
        scn.api.create_membership(
            f.membership_payload(
                scn.league_id,
                member_id,
                team_id=team_id,
                roster_role=spec.roster_role,
                prior_season_average=spec.prior_season_average,
                prior_season_games=spec.prior_season_games,
            ),
            scn.secretary,
        )
    )
    scn.member_ids.append(member_id)
    scn.member_classes.append(spec.member_class)
    scn.membership_ids.append(data["id"])
    scn.membership_teams.append(spec.team_index)
    return data["id"]


def register_lane_pair(
    scn: Scenario,
    pair_number: int = 1,
    certified_through: str = LANE_CERTIFIED_THROUGH,
) -> str:
    """Lane certification is an association act, never the secretary's."""
    data = get_success_data(
        scn.api.register_lane_pair(
            f.lane_pair_payload(scn.league_id, pair_number, certified_through),
            scn.officer,
        )
    )
    scn.lane_pair_ids.append(data["id"])
    return data["id"]


def default_matches(scn: Scenario) -> List[Dict[str, Any]]:
    """Two weeks, the two teams swapping home and away, on one lane pair."""
    return [
        f.schedule_match(
            1, scn.team_ids[0], scn.team_ids[1], scn.lane_pair_ids[0],
            WEEK1_STARTS_AT, WEEK1_ENDS_AT,
        ),
        f.schedule_match(
            2, scn.team_ids[1], scn.team_ids[0], scn.lane_pair_ids[0],
            WEEK2_STARTS_AT, WEEK2_ENDS_AT,
        ),
    ]


def adopt_schedule(
    scn: Scenario,
    matches: Optional[List[Dict[str, Any]]] = None,
    total_weeks: int = 2,
) -> List[str]:
    """Adopt the season schedule; the response carries the created matches."""
    body = matches if matches is not None else default_matches(scn)
    rows = get_success_data(
        scn.api.adopt_schedule(
            scn.league_id, f.schedule_payload(total_weeks, body), scn.secretary
        )
    )
    if not isinstance(rows, list):
        # Fall back to the listing so that setup never depends on the response
        # shape of this one endpoint; tests that care assert the shape directly.
        rows = get_success_data(
            scn.api.list_matches(scn.secretary, params={"league_id": scn.league_id, "limit": 100})
        )
    scn.match_ids = [row["id"] for row in rows]
    scn.total_weeks = total_weeks
    return scn.match_ids


# ─── layer 2: sanctioning and the four-hop cascade ─────

def expected_remittance_cents(
    scn: Scenario, membership_ids: Sequence[str], penalty_per_member: int = 0
) -> int:
    """Price a remittance exactly as §3.3 does: the member's national fee tier,
    plus the flat local fee, plus the per-member penalty."""
    total = 0
    for membership_id in membership_ids:
        index = scn.membership_ids.index(membership_id)
        national = (
            NATIONAL_FEE_YOUTH_CENTS
            if scn.member_classes[index] == MemberClass.YOUTH
            else NATIONAL_FEE_ADULT_CENTS
        )
        total += national + LOCAL_ASSOCIATION_FEE_CENTS
    return total + penalty_per_member * len(membership_ids)


def open_remittance(
    scn: Scenario,
    membership_ids: Optional[Sequence[str]] = None,
    declared_amount_cents: Optional[int] = None,
    penalty_per_member: int = 0,
) -> str:
    """Open a draft remittance, priced correctly unless a test overrides it."""
    ids = list(membership_ids if membership_ids is not None else scn.membership_ids)
    declared = (
        declared_amount_cents
        if declared_amount_cents is not None
        else expected_remittance_cents(scn, ids, penalty_per_member)
    )
    data = get_success_data(
        scn.api.create_fee_remittance(
            f.fee_remittance_payload(scn.league_id, ids, declared), scn.treasurer
        )
    )
    return data["id"]


def submit_remittance(
    scn: Scenario, remittance_id: str, declared_amount_cents: Optional[int] = None
) -> Dict[str, Any]:
    return get_success_data(
        scn.api.submit_fee_remittance(
            remittance_id, f.remittance_submit_payload(declared_amount_cents), scn.treasurer
        )
    )


def accept_remittance(scn: Scenario, remittance_id: str, receipt: str = "NR-2913-0001"):
    """The national acceptance — head of the four-hop sanction cascade."""
    return get_success_data(
        scn.api.record_national_decision(
            remittance_id, f.national_accept_payload(receipt), scn.officer
        )
    )


def reject_remittance(scn: Scenario, remittance_id: str, reason: str = "Roster mismatch."):
    return get_success_data(
        scn.api.record_national_decision(
            remittance_id, f.national_reject_payload(reason), scn.officer
        )
    )


def sanction(
    scn: Scenario,
    membership_ids: Optional[Sequence[str]] = None,
    penalty_per_member: int = 0,
) -> str:
    """Open, submit and have the association accept one remittance."""
    remittance_id = open_remittance(
        scn, membership_ids, penalty_per_member=penalty_per_member
    )
    submit_remittance(scn, remittance_id)
    accept_remittance(scn, remittance_id)
    return remittance_id


# ─── layer 3: match night ──────────────────────────────

def regular_slots(scn: Scenario, membership_indexes: Sequence[int]) -> List[Dict[str, Any]]:
    return [
        f.slot(position, membership_id=scn.membership_ids[index])
        for position, index in enumerate(membership_indexes, start=1)
    ]


def submit_lineup(
    scn: Scenario,
    team_index: int,
    slots: List[Dict[str, Any]],
    match_index: int = 0,
    actor: Optional[Dict[str, str]] = None,
    expected_match_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Submit one side's lineup, re-reading the match's version first.

    Each successful submission increments that version, so the echo has to be
    read immediately before the call rather than cached across the pair.
    """
    version = (
        expected_match_version
        if expected_match_version is not None
        else scn.match_version(match_index)
    )
    return get_success_data(
        scn.api.submit_lineup(
            scn.match_ids[match_index],
            f.lineup_payload(version, scn.team_ids[team_index], slots),
            actor if actor is not None else scn.secretary,
        )
    )


def submit_both_lineups(
    scn: Scenario,
    match_index: int = 0,
    home_membership_indexes: Sequence[int] = (0, 1),
    away_membership_indexes: Sequence[int] = (2, 3),
) -> None:
    """Fill both sides of a match, which advances it to LINEUPS_SUBMITTED."""
    match = scn.match(match_index)
    home_index = scn.team_ids.index(match["home_team_id"])
    away_index = scn.team_ids.index(match["away_team_id"])
    submit_lineup(
        scn, home_index, regular_slots(scn, home_membership_indexes), match_index
    )
    submit_lineup(
        scn, away_index, regular_slots(scn, away_membership_indexes), match_index
    )


def open_match(scn: Scenario, match_index: int = 0) -> Dict[str, Any]:
    return get_success_data(
        scn.api.open_match(scn.match_ids[match_index], {}, scn.secretary)
    )


def enter_scores(
    scn: Scenario, entries: List[Dict[str, Any]], match_index: int = 0
) -> Dict[str, Any]:
    return get_success_data(
        scn.api.record_scores(
            scn.match_ids[match_index], f.scores_payload(entries), scn.secretary
        )
    )


def certify_match(scn: Scenario, match_index: int = 0) -> Dict[str, Any]:
    """The only way games become certified games."""
    return get_success_data(
        scn.api.certify_match(scn.match_ids[match_index], {}, scn.secretary)
    )


# The shared score set, keyed by roster index.  Certifying one match with these
# pins is what moves the four bowlers from their entering handicaps to their
# blended current ones.
DEFAULT_GAME_PINS: Dict[int, Tuple[int, int, int]] = {
    0: (170, 180, 190),
    1: (230, 240, 250),
    2: (150, 160, 170),
    3: (140, 150, 160),
}


def slot_by_membership(scn: Scenario, match_index: int = 0) -> Dict[str, Dict[str, Any]]:
    """Index this match's slots by the membership id they name."""
    return {
        row["membership_id"]: row
        for row in scn.series_entries(match_index)
        if row.get("membership_id")
    }


def score_entries_for(
    scn: Scenario,
    match_index: int = 0,
    pins: Optional[Dict[int, Tuple[int, int, int]]] = None,
) -> List[Dict[str, Any]]:
    """Build one score entry per bowling slot of the match, from roster pins."""
    chosen = pins if pins is not None else DEFAULT_GAME_PINS
    by_membership = slot_by_membership(scn, match_index)
    entries: List[Dict[str, Any]] = []
    for index, membership_id in enumerate(scn.membership_ids):
        row = by_membership.get(membership_id)
        if row is None or index not in chosen:
            continue
        game1, game2, game3 = chosen[index]
        entries.append(f.score_entry(row["id"], game1, game2, game3))
    return entries


# ─── layer 4: dues, season close, prize distribution ───

def pay_dues(
    scn: Scenario,
    membership_index: int,
    week_number: int,
    amount_cents: Optional[int] = None,
    actor: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Record one week's dues; the tender must equal ``weekly_dues_cents``."""
    amount = (
        amount_cents
        if amount_cents is not None
        else scn.bylaws.get("weekly_dues_cents", BASE_BYLAWS["weekly_dues_cents"])
    )
    return get_success_data(
        scn.api.record_dues_payment(
            scn.membership_ids[membership_index],
            f.dues_payload(week_number, amount),
            actor if actor is not None else scn.treasurer,
        )
    )


def pay_dues_for_all(scn: Scenario, week_number: int) -> None:
    for index in range(len(scn.membership_ids)):
        pay_dues(scn, index, week_number)


def close_season(scn: Scenario) -> Dict[str, Any]:
    return get_success_data(
        scn.api.close_season(scn.league_id, {}, scn.secretary)
    )


def draft_plan(
    scn: Scenario,
    basis_variant: Any,
    place_count: Optional[int] = None,
    expected_version: Optional[int] = None,
) -> Dict[str, Any]:
    fund = scn.prize_fund()
    weights = scn.bylaws.get("prize_place_weights", BASE_BYLAWS["prize_place_weights"])
    return get_success_data(
        scn.api.draft_distribution_plan(
            fund["id"],
            f.distribution_plan_payload(
                expected_version if expected_version is not None else fund["version"],
                basis_variant,
                place_count if place_count is not None else len(weights),
            ),
            scn.treasurer,
        )
    )


def approve_plan(scn: Scenario) -> Dict[str, Any]:
    """Approval belongs to the secretary, never the treasurer."""
    return get_success_data(
        scn.api.approve_plan(scn.prize_fund_id(), {}, scn.secretary)
    )


def disburse(scn: Scenario, actor: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Disbursement belongs to the treasurer, whose id must differ from the
    approver's — hence the default actor is the treasurer, not the secretary."""
    return get_success_data(
        scn.api.disburse(
            scn.prize_fund_id(), {}, actor if actor is not None else scn.treasurer
        )
    )


def awards_of_fund(scn: Scenario) -> List[Dict[str, Any]]:
    """Awards are discoverable only through the listing, ordered by place."""
    return get_success_data(
        scn.api.list_prize_awards(
            scn.secretary, params={"prize_fund_id": scn.prize_fund_id(), "limit": 100}
        )
    )


# ─── composites ────────────────────────────────────────

def build_league(
    api: ApiClient,
    *,
    clock: str = ORG_MEETING_INSTANT,
    bylaws: Optional[Dict[str, Any]] = None,
    team_names: Sequence[str] = DEFAULT_TEAM_NAMES,
    roster: Sequence[RosterSpec] = DEFAULT_ROSTER,
    declared_team_count: int = 2,
    lane_pairs: Sequence[Tuple[int, str]] = ((1, LANE_CERTIFIED_THROUGH),),
    with_schedule: bool = True,
    total_weeks: int = 2,
    matches: Optional[List[Dict[str, Any]]] = None,
    **charter_overrides: Any,
) -> Scenario:
    """Everything the organizational meeting produces, up to the schedule.

    The league lands at ``BYLAWS_ADOPTED`` with its teams ``PROVISIONAL``, its
    memberships ``UNSANCTIONED``/``UNPAID`` and its matches in ``DRAFT``.
    """
    set_clock(api, clock)
    scn = charter_league(
        api, declared_team_count=declared_team_count, **charter_overrides
    )
    adopt_bylaws(scn, **(bylaws or {}))
    for name in team_names:
        add_team(scn, name)
    for spec in roster:
        enrol(scn, spec)
    for pair_number, certified_through in lane_pairs:
        register_lane_pair(scn, pair_number, certified_through)
    if with_schedule:
        adopt_schedule(scn, matches, total_weeks)
    return scn


def build_sanctioned_league(api: ApiClient, **kwargs: Any) -> Scenario:
    """A league whose whole roster has been sanctioned by the association.

    With the shared configuration this drives both teams to ``CONFIRMED``, the
    league to ``SANCTIONED`` and every match from ``DRAFT`` to ``SCHEDULED``.
    """
    scn = build_league(api, **kwargs)
    sanction(scn)
    return scn


def build_open_match(
    api: ApiClient, *, match_clock: str = WEEK1_STARTS_AT, **kwargs: Any
) -> Scenario:
    """A sanctioned league with week one's lineups in and the match open.

    Opening the league's first match is also what moves the league itself from
    ``SANCTIONED`` to ``IN_SEASON``, which is the point weekly dues unlock.
    """
    scn = build_sanctioned_league(api, **kwargs)
    submit_both_lineups(scn, 0)
    set_clock(api, match_clock)
    open_match(scn, 0)
    return scn


def build_certified_match(
    api: ApiClient,
    *,
    pins: Optional[Dict[int, Tuple[int, int, int]]] = None,
    **kwargs: Any,
) -> Scenario:
    """Week one bowled and certified — the only source of certified games."""
    scn = build_open_match(api, **kwargs)
    enter_scores(scn, score_entries_for(scn, 0, pins), 0)
    certify_match(scn, 0)
    return scn


def build_closed_season(
    api: ApiClient,
    *,
    dues_weeks: Sequence[int] = (1,),
    forfeit_week_two: bool = True,
    **kwargs: Any,
) -> Scenario:
    """A league whose every match is settled and whose season is closed.

    Week one is certified; week two is forfeited by default, because closing the
    season requires *every* match to have reached ``CERTIFIED``, ``FORFEITED`` or
    ``VOID`` and a forfeit is the cheapest way to settle the remaining week.
    """
    scn = build_certified_match(api, **kwargs)
    for week in dues_weeks:
        pay_dues_for_all(scn, week)
    if forfeit_week_two and len(scn.match_ids) > 1:
        get_success_data(
            scn.api.forfeit_match(
                scn.match_ids[1], f.forfeit_payload(scn.team_ids[1]), scn.secretary
            )
        )
    close_season(scn)
    return scn


def build_disbursed_fund(
    api: ApiClient, *, basis_variant: str = "CERTIFIED_TO_DATE", **kwargs: Any
) -> Scenario:
    """A closed season whose plan has been drafted, approved and paid."""
    scn = build_closed_season(api, **kwargs)
    draft_plan(scn, basis_variant)
    approve_plan(scn)
    disburse(scn)
    return scn


# ─── pytest fixtures ───────────────────────────────────

@pytest.fixture
def api() -> ApiClient:
    """The HTTP client; the runner supplies the base URL in the environment."""
    return ApiClient()


@pytest.fixture
def officer() -> Dict[str, str]:
    """Association-officer headers — the one role with an opaque principal."""
    return make_association_officer_headers()


@pytest.fixture
def forming_league(api: ApiClient) -> Scenario:
    """A chartered league at FORMING, with no bylaws adopted yet."""
    set_clock(api, ORG_MEETING_INSTANT)
    return charter_league(api)


@pytest.fixture
def league(api: ApiClient) -> Scenario:
    """A league at BYLAWS_ADOPTED with teams, roster, lane pair and schedule."""
    return build_league(api)


@pytest.fixture
def sanctioned_league(api: ApiClient) -> Scenario:
    """A league at SANCTIONED with both teams CONFIRMED."""
    return build_sanctioned_league(api)


@pytest.fixture
def opened_match(api: ApiClient) -> Scenario:
    """A league IN_SEASON with week one open for bowling.

    Named ``opened_match`` rather than ``open_match`` so it cannot shadow the
    ``open_match`` helper this module itself calls.
    """
    return build_open_match(api)


@pytest.fixture
def certified_match(api: ApiClient) -> Scenario:
    """A league IN_SEASON with week one certified."""
    return build_certified_match(api)


@pytest.fixture
def closed_season(api: ApiClient) -> Scenario:
    """A league at SEASON_CLOSED with one week of dues collected."""
    return build_closed_season(api)
