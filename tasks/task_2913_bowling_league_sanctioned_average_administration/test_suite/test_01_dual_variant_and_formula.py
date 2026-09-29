"""Dual-variant calculations and the composed arithmetic formulas.

Two families of behaviour are exercised here.  The first is the pair of
genuine *variants* the bylaws can select between: the handicap basis
(``ENTERING`` versus ``CURRENT``) read over one untouched set of certified
pins, and the prize basis (``PROJECTED_SEASON_END`` versus
``CERTIFIED_TO_DATE``) drafted over one unchanged dues ledger.  The second is
the set of formulas whose branches and pinned rounding order compose in a
single request: the per-bowler handicap with its class branch, its zero floor
and its ceiling; the team handicap that floors per bowler *before* it sums;
and the prize waterfall whose reserve tier, half-up administrative fee and
per-place flooring leave a remainder cent that must land on place 1.
"""
from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing.validators import (
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_cents,
    assert_fields,
    assert_points,
    assert_prize_money_invariant,
)
from test_helpers.fixtures import RosterSpec, Scenario
from test_helpers.types import (
    AverageStatus,
    BasisVariant,
    FeeRemittanceStatus,
    HandicapAverageBasis,
    LeagueStatus,
    MemberClass,
    PrizeAwardStatus,
    PrizeFundStatus,
    SanctionStatus,
    TeamStatus,
)

# ─── Rosters that pin the formula branches ────────────────────────────────
# The shared configuration's own roster (priors 180, 195, 170 and 160 over 30
# games each) already exercises the handicap-basis variants, so the two
# rosters below exist only for the branch and rounding-order cases.

# Adult 180 -> a plain product; adult 130 -> a product of 81 clipped by the
# 60-cent ceiling; YOUTH 150 -> the youth percentage 0.80; adult 230 -> the
# max(0, base - basis) guard rather than a negative handicap.
_CLASS_BRANCH_ROSTER: Tuple[RosterSpec, ...] = (
    RosterSpec("Cara Captain", MemberClass.ADULT, 180, 30, 0),
    RosterSpec("Dan Bowler", MemberClass.ADULT, 130, 30, 0),
    RosterSpec("Eve Captain", MemberClass.YOUTH, 150, 30, 1),
    RosterSpec("Fay Bowler", MemberClass.ADULT, 230, 30, 1),
)

# The rounding-order roster: 178, 183, 191 and 205 floor to 37, 33, 26 and 13,
# which sum to 109; deferring the flooring to the end would give 110.
_FLOOR_ORDER_ROSTER: Tuple[RosterSpec, ...] = (
    RosterSpec("H1 Bowler", MemberClass.ADULT, 178, 30, 0),
    RosterSpec("H2 Bowler", MemberClass.ADULT, 183, 30, 0),
    RosterSpec("H3 Bowler", MemberClass.ADULT, 191, 30, 0),
    RosterSpec("H4 Bowler", MemberClass.ADULT, 205, 30, 0),
    RosterSpec("A1 Bowler", MemberClass.ADULT, 150, 30, 1),
    RosterSpec("A2 Bowler", MemberClass.ADULT, 160, 30, 1),
    RosterSpec("A3 Bowler", MemberClass.ADULT, 170, 30, 1),
    RosterSpec("A4 Bowler", MemberClass.ADULT, 180, 30, 1),
)

# Four positions per side with three of them enough for legality, so that all
# four roster candidates are retained by the roster-depth ranking.
_DEEP_LINEUP_BYLAWS: Dict[str, Any] = {
    "lineup_positions": 4,
    "legal_lineup_minimum": 3,
}

_DEEP_TEAM_NAMES = ("Strike Force", "Split Decision")


# ─── Private helpers (this module only) ───────────────────────────────────

def _amend_bylaws(scn: Scenario, **overrides: Any) -> Dict[str, Any]:
    """Re-adopt the whole bylaw set, echoing the league's current version.

    Amendment is a mutation of an existing league, so it answers 200.
    """
    payload = f.bylaws_payload(scn.league_version(), **overrides)
    return validate_success(
        scn.api.adopt_bylaws(scn.league_id, payload, scn.secretary), 200
    )


def _sanction_with_accept(scn: Scenario) -> Dict[str, Any]:
    """Draft, submit and have the national body accept one remittance.

    The acceptance is the head of the four-hop sanction cascade, and it
    transitions an existing remittance, so it answers 200.
    """
    remittance_id = fx.open_remittance(scn)
    fx.submit_remittance(scn, remittance_id)
    return validate_success(
        scn.api.record_national_decision(
            remittance_id, f.national_accept_payload("NR-2913-0002"), scn.officer
        ),
        200,
    )


def _draft_plan(scn: Scenario, basis_variant: Any, place_count: int = 2) -> Dict[str, Any]:
    """Draft a distribution plan on the named basis, echoing the fund version.

    Drafting creates no award rows at all — it only rewrites the fund's plan
    figures — so it answers 200.
    """
    fund = scn.prize_fund()
    payload = f.distribution_plan_payload(fund["version"], basis_variant, place_count)
    return validate_success(
        scn.api.draft_distribution_plan(fund["id"], payload, scn.treasurer), 200
    )


def _fund_of(scn: Scenario) -> Dict[str, Any]:
    """Read the league's single prize fund through its own endpoint."""
    return validate_success(scn.api.get_prize_fund(scn.prize_fund_id(), scn.secretary), 200)


def _membership(scn: Scenario, index: int) -> Dict[str, Any]:
    return validate_success(
        scn.api.get_membership(scn.membership_ids[index], scn.secretary), 200
    )


def _team(scn: Scenario, index: int) -> Dict[str, Any]:
    return validate_success(scn.api.get_team(scn.team_ids[index], scn.secretary), 200)


def _match(scn: Scenario, index: int = 0) -> Dict[str, Any]:
    return validate_success(scn.api.get_match(scn.match_ids[index], scn.secretary), 200)


def _league(scn: Scenario) -> Dict[str, Any]:
    return validate_success(scn.api.get_league(scn.league_id, scn.secretary), 200)


# ══════════════════════════════════════════════════════════════════════════
# The handicap basis: ENTERING versus CURRENT over identical certified pins
# ══════════════════════════════════════════════════════════════════════════

def test_current_basis_handicap_reads_the_blended_current_average(api: ApiClient):
    """Under a CURRENT basis the handicap follows the live average.

    Three certified games against a 30-game prior record and a minimum of
    nine games for an established average leave the bowler PROVISIONAL, so
    the BLENDED policy blends 195 over 30 prior games with the 720 certified
    pins into a current average of 199.  The handicap is then the floor of
    0.90 times (220 - 199), which is 18.

    Design: Difficulty/dual_variant_calc/handicap_basis_entering_vs_current_on_identical_certified_pins
    """
    scn = fx.build_certified_match(api)

    membership = _membership(scn, 1)
    assert_fields(
        membership,
        entering_average=195,
        certified_games=3,
        certified_pins=720,
        average_status=AverageStatus.PROVISIONAL.value,
        current_average=199,
        handicap_per_game=18,
    )
    league = _league(scn)
    assert_fields(
        league,
        handicap_average_basis=HandicapAverageBasis.CURRENT.value,
        status=LeagueStatus.IN_SEASON.value,
    )


def test_current_basis_handicaps_feed_every_roster_team_handicap(api: ApiClient):
    """Every membership's handicap, and both team handicaps, follow the basis.

    On the CURRENT basis the four blended averages are 180, 199, 169 and 159,
    which floor to handicaps of 36, 18, 45 and 54.  A team handicap sums the
    already-floored integers of its sanctioned roster, so the first team
    reports 36 plus 18 and the second 45 plus 54.

    Design: Difficulty/dual_variant_calc/handicap_basis_entering_vs_current_on_identical_certified_pins
    """
    scn = fx.build_certified_match(api)

    assert_fields(_membership(scn, 0), current_average=180, handicap_per_game=36)
    assert_fields(_membership(scn, 2), current_average=169, handicap_per_game=45)
    assert_fields(_membership(scn, 3), current_average=159, handicap_per_game=54)
    assert_fields(_team(scn, 0), team_handicap_per_game=54)
    assert_fields(_team(scn, 1), team_handicap_per_game=99)


def test_amendment_to_entering_basis_moves_the_handicap_and_no_pin(api: ApiClient):
    """Flipping the basis to ENTERING re-derives handicaps from frozen averages.

    The amendment adds and removes no certified pin: the same 720 pins and
    the same current average of 199 stand afterwards.  Only the basis moves,
    so the handicap becomes the floor of 0.90 times (220 - 195), which is 22
    rather than 18 — a delta of four from identical scoring data.

    Design: Difficulty/dual_variant_calc/handicap_basis_entering_vs_current_on_identical_certified_pins
    """
    scn = fx.build_certified_match(api)
    before = _league(scn)
    assert_fields(_membership(scn, 1), handicap_per_game=18)

    amended = _amend_bylaws(scn, handicap_average_basis=HandicapAverageBasis.ENTERING)
    assert_fields(
        amended,
        handicap_average_basis=HandicapAverageBasis.ENTERING.value,
        version=before["version"] + 1,
        status=LeagueStatus.IN_SEASON.value,
    )

    membership = _membership(scn, 1)
    assert_fields(
        membership,
        handicap_per_game=22,
        entering_average=195,
        current_average=199,
        certified_games=3,
        certified_pins=720,
        average_status=AverageStatus.PROVISIONAL.value,
    )


def test_amendment_recomputes_roster_handicaps_but_not_frozen_match_figures(api: ApiClient):
    """A basis amendment re-derives team handicaps and leaves matches alone.

    With the basis on ENTERING the first team's roster handicap becomes 36
    plus 22, which is 58, while the second team's two bowlers are unmoved at
    45 plus 54.  The per-side handicaps frozen onto the match at lineup
    submission — 58 for the home side and 99 for the away side, both computed
    before any game was certified — stay exactly where they were.

    Design: Difficulty/dual_variant_calc/handicap_basis_entering_vs_current_on_identical_certified_pins
    """
    scn = fx.build_certified_match(api)
    _amend_bylaws(scn, handicap_average_basis=HandicapAverageBasis.ENTERING)

    assert_fields(_team(scn, 0), team_handicap_per_game=58)
    assert_fields(_team(scn, 1), team_handicap_per_game=99)
    assert_fields(
        _match(scn, 0),
        home_team_handicap_per_game=58,
        away_team_handicap_per_game=99,
    )


# ══════════════════════════════════════════════════════════════════════════
# The prize basis: PROJECTED_SEASON_END versus CERTIFIED_TO_DATE
# ══════════════════════════════════════════════════════════════════════════

def _league_with_one_week_of_dues(api: ApiClient) -> Scenario:
    """Week one certified and every bowler's week-one dues collected.

    Weekly dues of 1200 cents less a 500-cent expense share leave a 700-cent
    prize share per bowler, so four bowlers put 2800 cents into the fund.
    """
    scn = fx.build_certified_match(api)
    fx.pay_dues_for_all(scn, 1)
    return scn


def test_settled_figures_that_both_prize_bases_start_from(api: ApiClient):
    """Both bases begin from the same settled dues and the same week count.

    Week one is certified while week two is still scheduled, so the high-water
    mark of fully settled weeks is 1 out of a two-week season.  All four
    memberships are sanctioned, and the fund has accumulated the four
    700-cent prize shares without yet drafting anything.

    Design: Difficulty/dual_variant_calc/prize_basis_projected_vs_certified_on_identical_dues_ledger
    """
    scn = _league_with_one_week_of_dues(api)

    assert_fields(
        _league(scn),
        certified_week_high_water=1,
        total_weeks=2,
        sanctioned_member_count=4,
        status=LeagueStatus.IN_SEASON.value,
    )
    fund = _fund_of(scn)
    assert_cents(fund["collected_prize_cents"], 2800, "collected_prize_cents")
    assert_cents(fund["undistributed_balance_cents"], 2800, "undistributed_balance_cents")
    assert_fields(fund, status=PrizeFundStatus.ACCUMULATING.value, place_count=0)


def test_projected_basis_adds_the_remaining_week_to_the_settled_amount(api: ApiClient):
    """PROJECTED_SEASON_END projects the one remaining week over the roster.

    The settled amount is 2800 cents; one week remains of the two, four
    members are sanctioned and the weekly prize share is 700 cents, so the
    basis is 2800 plus 1 times 4 times 700, which is 5600.  Below the
    100000-cent tier the reserve is five percent — 280 cents — the
    administrative fee is three percent of the remaining 5320 rounded half up
    to 160, and 5160 cents are left to distribute.

    Design: Difficulty/dual_variant_calc/prize_basis_projected_vs_certified_on_identical_dues_ledger
    """
    scn = _league_with_one_week_of_dues(api)
    version_before = scn.prize_fund()["version"]

    drafted = _draft_plan(scn, BasisVariant.PROJECTED_SEASON_END)

    assert_cents(drafted["plan_basis_cents"], 5600, "plan_basis_cents")
    assert_cents(drafted["reserve_cents"], 280, "reserve_cents")
    assert_cents(drafted["admin_fee_cents"], 160, "admin_fee_cents")
    assert_cents(drafted["net_distributable_cents"], 5160, "net_distributable_cents")
    assert_fields(
        drafted,
        basis_variant=BasisVariant.PROJECTED_SEASON_END.value,
        place_count=2,
        status=PrizeFundStatus.PLAN_DRAFTED.value,
        version=version_before + 1,
    )


def test_certified_basis_redraft_ignores_the_remaining_schedule(api: ApiClient):
    """CERTIFIED_TO_DATE keeps only the settled money, over the same ledger.

    A fresh draft supersedes the projected one outright.  The basis falls to
    the settled 2800 cents, the five-percent reserve to 140, the half-up
    administrative fee on the remaining 2660 to 80, and the distributable
    figure to 2580 — every number different from the projected draft although
    not one dues payment changed.

    Design: Difficulty/dual_variant_calc/prize_basis_projected_vs_certified_on_identical_dues_ledger
    """
    scn = _league_with_one_week_of_dues(api)
    version_before = scn.prize_fund()["version"]

    projected = _draft_plan(scn, BasisVariant.PROJECTED_SEASON_END)
    redrafted = _draft_plan(scn, BasisVariant.CERTIFIED_TO_DATE)

    assert_cents(redrafted["plan_basis_cents"], 2800, "plan_basis_cents")
    assert_cents(redrafted["reserve_cents"], 140, "reserve_cents")
    assert_cents(redrafted["admin_fee_cents"], 80, "admin_fee_cents")
    assert_cents(redrafted["net_distributable_cents"], 2580, "net_distributable_cents")
    assert_fields(
        redrafted,
        basis_variant=BasisVariant.CERTIFIED_TO_DATE.value,
        place_count=2,
        status=PrizeFundStatus.PLAN_DRAFTED.value,
        version=version_before + 2,
    )
    assert projected["plan_basis_cents"] > redrafted["plan_basis_cents"], (
        "the projected basis must exceed the certified basis while a week remains"
    )


def test_drafting_either_basis_moves_no_money(api: ApiClient):
    """Neither draft touches the fund's money triple.

    The collected total stays at the 2800 cents the dues ledger actually
    holds, nothing has been paid out, and the undistributed balance is
    untouched — the reserve and the administrative fee remain inside it.

    Design: Difficulty/dual_variant_calc/prize_basis_projected_vs_certified_on_identical_dues_ledger
    """
    scn = _league_with_one_week_of_dues(api)

    _draft_plan(scn, BasisVariant.PROJECTED_SEASON_END)
    after_projected = _fund_of(scn)
    assert_cents(after_projected["collected_prize_cents"], 2800, "collected_prize_cents")
    assert_cents(after_projected["paid_award_total_cents"], 0, "paid_award_total_cents")
    assert_cents(
        after_projected["undistributed_balance_cents"], 2800, "undistributed_balance_cents"
    )
    assert_prize_money_invariant(after_projected)

    _draft_plan(scn, BasisVariant.CERTIFIED_TO_DATE)
    after_certified = _fund_of(scn)
    assert_cents(after_certified["collected_prize_cents"], 2800, "collected_prize_cents")
    assert_cents(after_certified["paid_award_total_cents"], 0, "paid_award_total_cents")
    assert_cents(
        after_certified["undistributed_balance_cents"], 2800, "undistributed_balance_cents"
    )
    assert_prize_money_invariant(after_certified)


# ══════════════════════════════════════════════════════════════════════════
# One sanction cascade, four branches of the per-bowler handicap formula
# ══════════════════════════════════════════════════════════════════════════

def test_sanctioning_grants_the_plain_product_and_the_zero_floor_together(api: ApiClient):
    """The same formula yields a plain product and a floored zero at once.

    A bowler entering at 180 in a league measuring from 220 at ninety percent
    takes the plain product: the floor of 0.90 times 40, which is 36.  A
    bowler entering at 230 is above the scratch score altogether, so the
    negative difference is replaced by zero and the handicap is 0 rather than
    a negative number.  Both are granted by the one acceptance that moved
    every membership to SANCTIONED.

    Design: Difficulty/combinatorial_formula/bowler_handicap_class_branch_zero_floor_and_cap_in_one_cascade
    """
    scn = fx.build_league(api, roster=_CLASS_BRANCH_ROSTER)
    _sanction_with_accept(scn)

    plain = _membership(scn, 0)
    assert_fields(
        plain,
        sanction_status=SanctionStatus.SANCTIONED.value,
        entering_average=180,
        handicap_per_game=36,
        average_status=AverageStatus.PROVISIONAL.value,
        certified_games=0,
        certified_pins=0,
    )
    guarded = _membership(scn, 3)
    assert_fields(
        guarded,
        sanction_status=SanctionStatus.SANCTIONED.value,
        entering_average=230,
        handicap_per_game=0,
        average_status=AverageStatus.PROVISIONAL.value,
    )


def test_sanctioning_applies_the_ceiling_after_the_floor_and_the_youth_rate(api: ApiClient):
    """The ceiling clips the floored product, and YOUTH takes its own rate.

    A bowler entering at 130 would earn the floor of 0.90 times 90, which is
    81, but the bylaw ceiling of 60 clips it — the product is floored first
    and the ceiling applied second.  A YOUTH member entering at 150 is priced
    at the youth percentage of 0.80 rather than 0.90, giving the floor of 0.80
    times 70, which is 56 and therefore under the same ceiling.

    Design: Difficulty/combinatorial_formula/bowler_handicap_class_branch_zero_floor_and_cap_in_one_cascade
    """
    scn = fx.build_league(api, roster=_CLASS_BRANCH_ROSTER)
    _sanction_with_accept(scn)

    capped = _membership(scn, 1)
    assert_fields(capped, entering_average=130, handicap_per_game=60)
    assert capped["handicap_per_game"] != 81, (
        "the floored product 81 must be clipped by max_handicap_per_game, not kept"
    )
    youth = _membership(scn, 2)
    assert_fields(youth, entering_average=150, handicap_per_game=56)


def test_the_four_branches_sum_into_their_team_handicaps_and_confirm_the_league(api: ApiClient):
    """Hops two, three and four of the cascade absorb the four branches.

    The first team carries the 36 and the clipped 60, so its roster handicap
    is 96; the second carries the youth 56 and the guarded 0, so its roster
    handicap is 56.  Two sanctioned bowlers reach the legal-lineup minimum on
    each side, both teams confirm, and the confirmed count meeting the
    declared team count carries the league itself to SANCTIONED.

    Design: Difficulty/combinatorial_formula/bowler_handicap_class_branch_zero_floor_and_cap_in_one_cascade
    """
    scn = fx.build_league(api, roster=_CLASS_BRANCH_ROSTER)
    _sanction_with_accept(scn)

    assert_fields(
        _team(scn, 0),
        team_handicap_per_game=96,
        status=TeamStatus.CONFIRMED.value,
        sanctioned_roster_count=2,
    )
    assert_fields(
        _team(scn, 1),
        team_handicap_per_game=56,
        status=TeamStatus.CONFIRMED.value,
        sanctioned_roster_count=2,
    )
    assert_fields(
        _league(scn),
        sanctioned_member_count=4,
        confirmed_team_count=2,
        status=LeagueStatus.SANCTIONED.value,
    )


def test_the_accepted_remittance_prices_the_youth_tier_apart_from_the_adults(api: ApiClient):
    """The cascade's head priced three adult tiers and one youth tier.

    Each of the three adults carries a 2600-cent national fee and each
    membership a flat 500-cent local fee, while the youth membership carries
    1200 plus 500.  Filing on the day the bylaws were adopted is inside the
    twenty-one-day grace period, so no penalty applies and the computed total
    is 11000 cents across four members.

    Design: Difficulty/combinatorial_formula/bowler_handicap_class_branch_zero_floor_and_cap_in_one_cascade
    """
    scn = fx.build_league(api, roster=_CLASS_BRANCH_ROSTER)

    accepted = _sanction_with_accept(scn)

    assert_cents(accepted["computed_amount_cents"], 11000, "computed_amount_cents")
    assert_cents(accepted["declared_amount_cents"], 11000, "declared_amount_cents")
    assert_cents(accepted["penalty_cents"], 0, "penalty_cents")
    assert_fields(
        accepted,
        member_count=4,
        status=FeeRemittanceStatus.ACCEPTED.value,
        national_receipt_no="NR-2913-0002",
        rejection_reason=None,
    )


# ══════════════════════════════════════════════════════════════════════════
# The team handicap: floor per bowler, then sum
# ══════════════════════════════════════════════════════════════════════════

def _deep_roster_league(api: ApiClient) -> Scenario:
    """Two four-strong rosters in a league fielding four positions a side."""
    return fx.build_league(
        api,
        bylaws=_DEEP_LINEUP_BYLAWS,
        roster=_FLOOR_ORDER_ROSTER,
        team_names=_DEEP_TEAM_NAMES,
        with_schedule=False,
    )


def test_each_bowler_handicap_is_floored_to_its_own_integer(api: ApiClient):
    """The four averages floor individually before anything is added.

    Measured from 220 at ninety percent, averages of 178, 183, 191 and 205
    give unfloored products of 37.8, 33.3, 26.1 and 13.5, and each bowler
    carries the floor of their own product: 37, 33, 26 and 13.

    Design: Difficulty/combinatorial_formula/team_handicap_per_bowler_floor_then_sum_109_not_110
    """
    scn = _deep_roster_league(api)
    _sanction_with_accept(scn)

    assert_fields(_membership(scn, 0), entering_average=178, handicap_per_game=37)
    assert_fields(_membership(scn, 1), entering_average=183, handicap_per_game=33)
    assert_fields(_membership(scn, 2), entering_average=191, handicap_per_game=26)
    assert_fields(_membership(scn, 3), entering_average=205, handicap_per_game=13)


def test_team_handicap_sums_the_floored_integers_to_109_not_110(api: ApiClient):
    """The rounding order is load-bearing: 109, never 110.

    Adding the four already-floored handicaps gives 37 plus 33 plus 26 plus
    13, which is 109.  Summing the unfloored products first and flooring once
    at the end would give 110, a different and incorrect number.

    Design: Difficulty/combinatorial_formula/team_handicap_per_bowler_floor_then_sum_109_not_110
    """
    scn = _deep_roster_league(api)
    _sanction_with_accept(scn)

    team = _team(scn, 0)
    assert_fields(team, team_handicap_per_game=109)
    assert team["team_handicap_per_game"] != 110, (
        "flooring once at the end of the sum gives 110 and is the wrong order"
    )


def test_team_handicap_sums_clipped_and_unclipped_bowlers_alike(api: ApiClient):
    """The second team mixes a clipped handicap into the same sum.

    Averages of 150, 160, 170 and 180 give unfloored products of 63, 54, 45
    and 36; the first is floored to 63 and then clipped to the ceiling of 60,
    so the four integers entering the sum are 60, 54, 45 and 36 and the team
    handicap is 195.

    Design: Difficulty/combinatorial_formula/team_handicap_per_bowler_floor_then_sum_109_not_110
    """
    scn = _deep_roster_league(api)
    _sanction_with_accept(scn)

    assert_fields(_membership(scn, 4), entering_average=150, handicap_per_game=60)
    assert_fields(_membership(scn, 5), entering_average=160, handicap_per_game=54)
    assert_fields(_membership(scn, 6), entering_average=170, handicap_per_game=45)
    assert_fields(_membership(scn, 7), entering_average=180, handicap_per_game=36)
    assert_fields(_team(scn, 1), team_handicap_per_game=195)


def test_the_roster_ranking_retains_every_candidate_and_confirms_both_teams(api: ApiClient):
    """Four candidates against four positions leaves nobody ranked out.

    Each team's four sanctioned memberships are exactly as many as the league
    fields per match, so the roster-depth ranking keeps all of them and no
    handicap is dropped from either sum.  Three sanctioned bowlers already
    satisfy the legal-lineup minimum, so both teams confirm, the league
    reaches SANCTIONED, and the eight adult memberships priced at 3100 cents
    each total 24800.

    Design: Difficulty/combinatorial_formula/team_handicap_per_bowler_floor_then_sum_109_not_110
    """
    scn = _deep_roster_league(api)

    accepted = _sanction_with_accept(scn)

    assert_fields(
        _team(scn, 0), status=TeamStatus.CONFIRMED.value, sanctioned_roster_count=4
    )
    assert_fields(
        _team(scn, 1), status=TeamStatus.CONFIRMED.value, sanctioned_roster_count=4
    )
    assert_fields(
        _league(scn),
        sanctioned_member_count=8,
        confirmed_team_count=2,
        status=LeagueStatus.SANCTIONED.value,
        lineup_positions=4,
        legal_lineup_minimum=3,
    )
    assert_cents(accepted["computed_amount_cents"], 24800, "computed_amount_cents")
    assert_fields(accepted, member_count=8)


# ══════════════════════════════════════════════════════════════════════════
# The prize waterfall: reserve tier, half-up fee, floors and the odd cent
# ══════════════════════════════════════════════════════════════════════════

def _closed_season_with_uneven_basis(api: ApiClient) -> Scenario:
    """A settled season whose prize pot does not divide evenly by the weights.

    Weekly dues of 1300 cents against a 500-cent expense share leave an
    800-cent prize share, so four bowlers paying week one put 3200 cents in.
    Week one is certified and week two forfeited, so every match is settled
    and the season closes.
    """
    return fx.build_closed_season(api, bylaws={"weekly_dues_cents": 1300})


def test_waterfall_reads_the_reserve_tier_from_the_basis_and_rounds_the_fee_half_up(
    api: ApiClient,
):
    """The first four steps of the waterfall compose on an uneven basis.

    The settled basis is 3200 cents.  That is below the 100000-cent tier
    threshold, so the reserve is five percent of the basis itself — never of
    the net it reduces — giving 160.  The administrative fee is three percent
    of the post-reserve 3040, which is 91.2 and rounds half up to 91, and the
    distributable figure is 3200 less 160 less 91, which is 2949.

    Design: Difficulty/combinatorial_formula/prize_waterfall_floor_remainder_cent_to_place_one
    """
    scn = _closed_season_with_uneven_basis(api)

    drafted = _draft_plan(scn, BasisVariant.CERTIFIED_TO_DATE)

    assert_cents(drafted["plan_basis_cents"], 3200, "plan_basis_cents")
    assert_cents(drafted["reserve_cents"], 160, "reserve_cents")
    assert_cents(drafted["admin_fee_cents"], 91, "admin_fee_cents")
    assert_cents(drafted["net_distributable_cents"], 2949, "net_distributable_cents")
    assert_fields(drafted, status=PrizeFundStatus.PLAN_DRAFTED.value, place_count=2)


def test_standings_rank_the_confirmed_teams_that_take_the_paying_places(api: ApiClient):
    """Points decide which team stands in which place.

    The home side swept all four points of the certified week one, and the
    week-two forfeit awards it the full four again while the forfeiting side
    is written to zero.  Eight points against none makes the first team place
    one on the points ranking alone.

    Design: Difficulty/combinatorial_formula/prize_waterfall_floor_remainder_cent_to_place_one
    """
    scn = _closed_season_with_uneven_basis(api)

    first = _team(scn, 0)
    second = _team(scn, 1)
    assert_points(first["total_points"], 8.0, "total_points")
    assert_points(second["total_points"], 0.0, "total_points")
    assert_fields(first, status=TeamStatus.CONFIRMED.value)
    assert_fields(second, status=TeamStatus.CONFIRMED.value)
    assert_fields(_league(scn), status=LeagueStatus.SEASON_CLOSED.value)


def test_the_single_remainder_cent_lands_on_place_one(api: ApiClient):
    """Each place floors its share and the leftover cent goes to place 1.

    Sixty percent of 2949 is 1769.4 and forty percent is 1179.6, so the
    floored raw amounts are 1769 and 1179 and one cent is left over.  That
    cent is allocated in ascending place order beginning at place 1, so the
    awards are 1770 and 1179 — never 1769 and 1180.

    Design: Difficulty/combinatorial_formula/prize_waterfall_floor_remainder_cent_to_place_one
    """
    scn = _closed_season_with_uneven_basis(api)
    _draft_plan(scn, BasisVariant.CERTIFIED_TO_DATE)
    fx.approve_plan(scn)

    rows, meta = validate_paginated(
        scn.api.list_prize_awards(
            scn.secretary, params={"prize_fund_id": scn.prize_fund_id(), "limit": 100}
        )
    )
    assert meta["total_count"] == 2, f"approval must mint one award per place: {rows}"
    assert len(rows) == 2, f"expected exactly two award rows, got {rows}"

    first, second = rows
    assert_fields(
        first,
        place=1,
        team_id=scn.team_ids[0],
        weight=0.60,
        status=PrizeAwardStatus.PENDING.value,
    )
    assert_cents(first["amount_cents"], 1770, "place 1 amount_cents")
    assert_fields(
        second,
        place=2,
        team_id=scn.team_ids[1],
        weight=0.40,
        status=PrizeAwardStatus.PENDING.value,
    )
    assert_cents(second["amount_cents"], 1179, "place 2 amount_cents")


def test_the_awards_total_exactly_the_net_distributable_amount(api: ApiClient):
    """Because the remainder is fully allocated, nothing is lost or invented.

    The two award amounts of 1770 and 1179 add to 2949, which is precisely the
    distributable figure the waterfall arrived at.

    Design: Difficulty/combinatorial_formula/prize_waterfall_floor_remainder_cent_to_place_one
    """
    scn = _closed_season_with_uneven_basis(api)
    drafted = _draft_plan(scn, BasisVariant.CERTIFIED_TO_DATE)
    fx.approve_plan(scn)

    rows, _meta = validate_paginated(
        scn.api.list_prize_awards(
            scn.secretary, params={"prize_fund_id": scn.prize_fund_id(), "limit": 100}
        )
    )
    total = sum(row["amount_cents"] for row in rows)
    assert_cents(total, 2949, "total of the awards' amount_cents")
    assert total == drafted["net_distributable_cents"], (
        "the awards must total net_distributable_cents exactly, "
        f"got {total} against {drafted['net_distributable_cents']}"
    )


def test_approval_mints_the_awards_without_moving_any_money(api: ApiClient):
    """Approval transitions the fund and records the approver, and pays nobody.

    The fund reaches PLAN_APPROVED with the approving secretary recorded, but
    every award is still PENDING, so nothing has been paid out and the
    undistributed balance is still the whole 3200 cents the dues ledger
    collected.

    Design: Difficulty/combinatorial_formula/prize_waterfall_floor_remainder_cent_to_place_one
    """
    scn = _closed_season_with_uneven_basis(api)
    _draft_plan(scn, BasisVariant.CERTIFIED_TO_DATE)
    fx.approve_plan(scn)

    fund = _fund_of(scn)
    assert_fields(
        fund,
        status=PrizeFundStatus.PLAN_APPROVED.value,
        plan_approved_by_user_id=scn.secretary_member_id,
        disbursed_at=None,
    )
    assert_cents(fund["paid_award_total_cents"], 0, "paid_award_total_cents")
    assert_cents(fund["collected_prize_cents"], 3200, "collected_prize_cents")
    assert_cents(fund["undistributed_balance_cents"], 3200, "undistributed_balance_cents")
    assert_prize_money_invariant(fund)
