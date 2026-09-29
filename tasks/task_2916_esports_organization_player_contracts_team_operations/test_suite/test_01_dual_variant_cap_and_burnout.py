"""The two cap-charge variants and the two burnout variants.

Both pairs share their inputs and differ only in the arithmetic the PRD pins to
each variant, so every test here reads both figures out of the same state.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant_equals,
    fixtures,
    make_coaching_staff_headers,
    make_general_manager_headers,
    make_league_admin_headers,
    make_performance_support_headers,
    validate_error,
    validate_success,
)

TIGHT_BUDGET_CENTS = 12400000
PRORATED_CHARGE = 12328767
FULL_SEASON_CHARGE = 12500000


def _signed_on_a_tight_budget():
    """One organization whose budget admits the prorated charge and nothing more."""
    return fixtures.setup_signed_player(
        org_overrides={"annual_salary_budget_cents": TIGHT_BUDGET_CENTS}
    )


def test_acceptance_freezes_the_prorated_charge_and_reports_the_full_season_one():
    """A mid-season signing charges the prorated figure and reports both variants.

    PRD: "The *prorated remaining term* variant first counts `remaining_season_days` as the
    number of whole days from the contract's `effective_at` to the league's `season_end_at`,
    discarding any fractional day; it then multiplies `base_salary_cents` by that day count,
    divides by the 365-day season, rounds the result half up to a whole cent, and finally adds
    `signing_bonus_cents` in full — the bonus is never prorated."
    PRD: "The *full-season-equivalent* variant simply adds `base_salary_cents` and
    `signing_bonus_cents` together, charging the whole annual salary no matter when in the
    season the ink dried."
    PRD: "If it fits, the figure is frozen onto the new contract as
    `provisional_cap_charge_cents` and never recomputed thereafter; it is the only quantity by
    which `committed_salary_cents` ever moves, which is what makes later execution and reversal
    exactly reversible."

    Design: Difficulty/dual_variant_calc/salary_cap_charge_prorated_vs_full_season_on_organization_budget
    """
    ctx = _signed_on_a_tight_budget()
    contract = ctx["contract"]

    assert contract["provisional_cap_charge_cents"] == PRORATED_CHARGE
    assert contract["final_cap_charge_cents"] == FULL_SEASON_CHARGE
    assert_instant_equals(contract["ends_at"], "2027-07-31T00:00:00Z", "contract.ends_at")

    organization = validate_success(
        api_client.get_organization(ctx["org"]["id"], ctx["gm_headers"])
    )
    assert organization["committed_salary_cents"] == PRORATED_CHARGE
    assert organization["uncommitted_salary_cents"] == TIGHT_BUDGET_CENTS - PRORATED_CHARGE


def test_cap_summary_shows_the_two_variants_side_by_side():
    """The computed cap read exposes the gap the league approval will refuse to grant.

    PRD: "`provisional_committed_cents` is the sum of `provisional_cap_charge_cents` over the
    organization's `ACTIVE` and `SUSPENDED` contracts — the same quantity the committed figure
    tracks — while `final_committed_cents` is the sum of `final_cap_charge_cents` over that same
    set of contracts."
    PRD: "For an organization whose signings all took effect at the very start of the season the
    two are equal; for one that signed mid-season the final figure is the larger, and the gap is
    exactly the budget headroom that league approval of a signing will refuse to grant."

    Design: Difficulty/dual_variant_calc/salary_cap_charge_prorated_vs_full_season_on_organization_budget
    """
    ctx = _signed_on_a_tight_budget()

    summary = validate_success(
        api_client.get_organization_cap_summary(ctx["org"]["id"], ctx["gm_headers"])
    )
    assert summary["provisional_committed_cents"] == PRORATED_CHARGE
    assert summary["final_committed_cents"] == FULL_SEASON_CHARGE
    assert summary["final_committed_cents"] - summary["provisional_committed_cents"] == 171233
    assert summary["committed_salary_cents"] == PRORATED_CHARGE
    assert summary["uncommitted_salary_cents"] == TIGHT_BUDGET_CENTS - PRORATED_CHARGE


def test_sign_decision_refuses_the_full_season_charge_that_acceptance_admitted():
    """The stricter variant vetoes at league decision what the prorated variant allowed.

    PRD: "An `APPROVE` decision moves it to `APPROVED`, which unlocks execution, and for a
    `SIGN` move it first re-tests the budget with the **stricter full-season variant**: take the
    organization's `committed_salary_cents`, replace the named contract's contribution of
    `provisional_cap_charge_cents` with that contract's `final_cap_charge_cents`, and require the
    result to be no greater than the organization's `annual_salary_budget_cents`."
    PRD: "A mid-season signing whose prorated charge fit comfortably at acceptance can fail here,
    and the refusal is `ERR_SALARY_CAP_EXCEEDED` (HTTP 422)."

    Design: Difficulty/dual_variant_calc/salary_cap_charge_prorated_vs_full_season_on_organization_budget
    """
    ctx = _signed_on_a_tight_budget()
    move = fixtures.file_roster_move(
        ctx["org"]["id"], ctx["player"]["id"], "SIGN", ctx["contract"]["id"]
    )

    response = api_client.decide_roster_move(
        move["id"],
        {"decision": "APPROVE", "decision_note": "league review"},
        make_league_admin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_SALARY_CAP_EXCEEDED.value, 422)

    stored = validate_success(api_client.get_roster_move(move["id"], ctx["gm_headers"]))
    assert stored["move_status"] == "PENDING"


def _contract_with_three_held_blocks():
    """1080 held minutes banked on 2026-08-10..2026-08-12 plus one wellness report."""
    ctx = fixtures.setup_signed_player(with_team_house=True)
    blocks = [
        fixtures.create_practice_block(
            ctx["org"]["id"],
            ctx["house"]["id"],
            f"2026-08-{day}T10:00:00Z",
            f"2026-08-{day}T16:00:00Z",
            [ctx["player"]["id"]],
        )
        for day in ("10", "11", "12")
    ]
    fixtures.set_clock("2026-08-13T00:00:00Z")
    fixtures.complete_practice_block(blocks[0]["id"])
    fixtures.complete_practice_block(blocks[1]["id"])
    fixtures.file_wellness_report(
        ctx["contract"]["id"], last_self_reported_load=10, reported_streaming_minutes_7d=600
    )
    fixtures.complete_practice_block(blocks[2]["id"])
    ctx["blocks"] = blocks
    return ctx


def test_obligation_summary_reports_the_rolling_and_the_cumulative_burnout_variants():
    """Twelve days after the last block the rolling window is empty and the season one is not.

    PRD: "The **rolling seven-day** variant, which is the one persisted as `burnout_score`, sums
    `duration_minutes` over the player's blocks whose `block_status` is `HELD` and whose
    `starts_at` falls in the window that begins strictly after seven days before the current
    instant and ends at the current instant inclusive; blocks that are merely `SCHEDULED`, and
    blocks that were cancelled, never feed the score."
    PRD: "The **season-cumulative** variant instead divides the contract's
    `season_practice_minutes` by the number of elapsed weeks and rounds that quotient half up
    before scoring it; elapsed weeks are the whole days from the contract's `effective_at` to the
    current instant, divided by seven and raised to the next whole week, with a floor of one week
    so that a contract signed today is never divided by zero."
    PRD: "It returns the contract's current `obligation_status`, its rolling `burnout_score` and
    the freshly-derived `season_burnout_score`, the `scheduled_minutes_this_week` and
    `streaming_minutes_this_week` that the weekly arithmetic charges for that player together
    with the resulting `cap_minutes`, the frozen `provisional_cap_charge_cents` next to the
    recomputed `final_cap_charge_cents`, and the current `wellness_hold_until`."

    Design: Difficulty/dual_variant_calc/burnout_score_rolling_7day_vs_season_cumulative_on_player_wellness
    """
    ctx = _contract_with_three_held_blocks()
    fixtures.set_clock("2026-08-25T00:00:00Z")

    summary = validate_success(
        api_client.get_contract_obligation_summary(
            ctx["contract"]["id"], make_performance_support_headers()
        )
    )
    assert summary["burnout_score"] == 50
    assert summary["season_burnout_score"] == 57
    assert summary["season_burnout_score"] - summary["burnout_score"] == 7


def test_persisted_burnout_score_keeps_the_value_written_by_the_last_mutation():
    """A computed read never rewrites the stored score or the obligation dimension.

    PRD: "Moving the clock mutates no entity eagerly: offers do not become expired at the moment
    the clock passes their deadline, wellness holds do not lift by themselves, and no counter is
    recomputed until the next request touches the affected resource."
    PRD: "A computed obligation summary gathers the whole picture for one contract without
    persisting anything."
    PRD: "A contract sitting in `COMPLIANT` whose refreshed score is at least 70 but strictly
    below 85 moves to `WARNED`."

    Design: Difficulty/dual_variant_calc/burnout_score_rolling_7day_vs_season_cumulative_on_player_wellness
    """
    ctx = _contract_with_three_held_blocks()
    fixtures.set_clock("2026-08-25T00:00:00Z")
    validate_success(
        api_client.get_contract_obligation_summary(
            ctx["contract"]["id"], make_performance_support_headers()
        )
    )

    contract = validate_success(
        api_client.get_contract(
            ctx["contract"]["id"], make_general_manager_headers(ctx["org"]["id"])
        )
    )
    assert contract["season_practice_minutes"] == 1080
    assert contract["burnout_score"] == 70
    assert contract["obligation_status"] == "WARNED"


def test_every_completed_block_is_held_and_feeds_the_season_total():
    """The three completions are the only source of the 1080 banked minutes.

    PRD: "Completion moves `block_status` `SCHEDULED` → `HELD`, records any `coach_note`, and
    then runs a four-link cascade: for every attendee holding an `ACTIVE` contract, that
    contract's `season_practice_minutes` increases by the block's `duration_minutes`; because the
    season total and the trailing seven-day window have both changed, that contract's
    `burnout_score` is recomputed by the rolling method of §3.6; because the score may have
    crossed a threshold, the contract's `obligation_status` escalates to `WARNED` at 70 or to
    `BREACH` at 85; and because the obligation dimension left `COMPLIANT`, every block still
    `SCHEDULED` whose `starts_at` is strictly later than the current instant and which lists that
    player is cancelled with `cancel_reason` of `WELLNESS_HOLD`."
    PRD: "On insertion the server derives `duration_minutes` as the number of whole minutes
    between `starts_at` and `ends_at`, stamps the booking coach's identifier into
    `coach_user_id`, sets `block_status` to `SCHEDULED` and leaves `cancel_reason` null."

    Design: Difficulty/dual_variant_calc/burnout_score_rolling_7day_vs_season_cumulative_on_player_wellness
    """
    ctx = _contract_with_three_held_blocks()

    for block in ctx["blocks"]:
        stored = validate_success(
            api_client.get_practice_block(block["id"], make_coaching_staff_headers())
        )
        assert stored["duration_minutes"] == 360
        assert stored["block_status"] == "HELD"

    contract = validate_success(
        api_client.get_contract(
            ctx["contract"]["id"], make_general_manager_headers(ctx["org"]["id"])
        )
    )
    assert contract["season_practice_minutes"] == 1080
