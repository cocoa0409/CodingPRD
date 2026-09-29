"""Requests that break two rules at once, and the band that gets to answer.

Each conflict is flanked by controls that break only one of the two rules, so the
ordering claim cannot be satisfied by an implementation that simply never reaches
the losing check.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    fixtures,
    make_coaching_staff_headers,
    make_general_manager_headers,
    make_player_agent_headers,
    validate_paginated,
    validate_error,
    validate_success,
)

TIGHT_BUDGET_CENTS = 10000000


def _two_unaffordable_offers():
    """Two organizations, each too poor for its own 12,500,000-cent offer sent on 2026-08-04."""
    league = fixtures.create_league()
    org_one = fixtures.create_organization(
        league["id"], name="Vertex Vanguard", annual_salary_budget_cents=TIGHT_BUDGET_CENTS
    )
    org_two = fixtures.create_organization(
        league["id"], name="Northline Nova", annual_salary_budget_cents=TIGHT_BUDGET_CENTS
    )
    player_one = fixtures.create_player()
    player_two = fixtures.create_player(
        full_name="Marek Rus", birth_date="2000-03-02", region_code="CZ"
    )
    fixtures.set_clock("2026-08-04T00:00:00Z")
    return {
        "league": league,
        "org_one": org_one,
        "org_two": org_two,
        "player_one": player_one,
        "player_two": player_two,
        "offer_one": fixtures.create_offer(org_one["id"], player_one["id"]),
        "offer_two": fixtures.create_offer(org_two["id"], player_two["id"]),
    }


def test_the_cap_refusal_is_genuinely_violated_inside_the_response_window():
    """The control: with the offer still open, the money is what fails.

    PRD: "The prorated charge for the contract about to be created must be less than or equal to the
    organization's current `uncommitted_salary_cents`, and if it is not, acceptance is refused with
    `ERR_SALARY_CAP_EXCEEDED` (HTTP 422)."
    PRD: "The *prorated remaining term* variant first counts `remaining_season_days` as the number
    of whole days from the contract's `effective_at` to the league's `season_end_at`, discarding any
    fractional day; it then multiplies `base_salary_cents` by that day count, divides by the 365-day
    season, rounds the result half up to a whole cent, and finally adds `signing_bonus_cents` in
    full — the bonus is never prorated."

    Design: Difficulty/priority_pair_validation_conflict/expired_offer_state_error_outranks_salary_cap_fiscal_error_on_acceptance
    """
    ctx = _two_unaffordable_offers()
    fixtures.set_clock("2026-08-06T00:00:00Z")

    refused = api_client.accept_contract_offer(
        ctx["offer_two"]["id"],
        {"effective_at": "2026-08-06T00:00:00Z"},
        make_player_agent_headers(ctx["player_two"]["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_SALARY_CAP_EXCEEDED.value, 422)

    gm_headers = make_general_manager_headers(ctx["org_two"]["id"])
    stored = validate_success(api_client.get_contract_offer(ctx["offer_two"]["id"], gm_headers))
    assert stored["offer_status"] == "SENT"

    organization = validate_success(
        api_client.get_organization(ctx["org_two"]["id"], gm_headers)
    )
    assert organization["committed_salary_cents"] == 0
    assert organization["active_roster_count"] == 0


def test_lazy_expiry_answers_before_the_money_is_ever_counted():
    """Band 8 beats band 13 on one request that violates both.

    PRD: "Checks are grouped into thirteen precedence bands, evaluated in ascending order; **the
    first violated band determines the response, and no later band runs**."
    PRD: "And the fiscal checks sit last, so a booking or a signing that is simultaneously unsafe
    for a minor and unaffordable for the organization reports the safety failure, not the money
    failure."
    PRD: "At the start of any operation that reads or mutates an offer — including a single-offer
    read and every offer inside a list page — an offer sitting in `SENT` or `COUNTERED` whose
    `expires_at` the current instant has reached is first moved to `EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/expired_offer_state_error_outranks_salary_cap_fiscal_error_on_acceptance
    """
    ctx = _two_unaffordable_offers()
    fixtures.set_clock("2026-08-08T00:00:00Z")

    refused = api_client.accept_contract_offer(
        ctx["offer_one"]["id"],
        {"effective_at": "2026-08-06T00:00:00Z"},
        make_player_agent_headers(ctx["player_one"]["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_OFFER_EXPIRED.value, 409)

    gm_headers = make_general_manager_headers(ctx["org_one"]["id"])
    stored = validate_success(api_client.get_contract_offer(ctx["offer_one"]["id"], gm_headers))
    assert stored["offer_status"] == "EXPIRED"

    organization = validate_success(
        api_client.get_organization(ctx["org_one"]["id"], gm_headers)
    )
    assert organization["committed_salary_cents"] == 0
    assert organization["active_roster_count"] == 0


def _almost_full_week():
    """2400 of 2700 weekly minutes already booked, in a house with a 60-minute buffer."""
    ctx = fixtures.setup_signed_player(with_team_house=True)
    fixtures.set_clock("2026-08-09T00:00:00Z")
    ctx["block_a"] = fixtures.create_practice_block(
        ctx["org"]["id"],
        ctx["house"]["id"],
        "2026-08-10T00:00:00Z",
        "2026-08-11T16:00:00Z",
        [ctx["player"]["id"]],
    )
    return ctx


def _candidate(ctx, starts_at, ends_at):
    return api_client.create_practice_block(
        {
            "organization_id": ctx["org"]["id"],
            "team_house_id": ctx["house"]["id"],
            "block_type": "REVIEW",
            "starts_at": starts_at,
            "ends_at": ends_at,
            "participant_player_ids": [ctx["player"]["id"]],
        },
        make_coaching_staff_headers(),
    )


def test_each_of_the_two_rules_fires_alone_when_only_it_is_broken():
    """The controls: a buffer-only violation and a cap-only violation.

    PRD: "**Room conflict** pads the candidate — and only the candidate — by the facility's
    `turnaround_buffer_minutes` at each end, then compares that padded interval against the raw,
    unpadded intervals of every `SCHEDULED` or `HELD` block in the same team house."
    PRD: "An overlap exists when the padded interval starts strictly before an existing block ends
    and that existing block starts strictly before the padded interval ends; where it does, the
    booking is refused with `ERR_FACILITY_SLOT_CONFLICT` (HTTP 409)."
    PRD: "A violation is normally refused with `ERR_WEEKLY_HOUR_CAP_EXCEEDED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/weekly_hour_cap_safety_error_outranks_facility_slot_constraint_error
    """
    ctx = _almost_full_week()

    facility_only = _candidate(ctx, "2026-08-11T16:30:00Z", "2026-08-11T20:30:00Z")
    validate_error(facility_only, ApiErrorId.ERR_FACILITY_SLOT_CONFLICT.value, 409)

    cap_only = _candidate(ctx, "2026-08-13T10:00:00Z", "2026-08-13T15:10:00Z")
    validate_error(cap_only, ApiErrorId.ERR_WEEKLY_HOUR_CAP_EXCEEDED.value, 422)


def test_the_workload_safety_band_answers_before_the_facility_band():
    """Band 9 beats band 11 on the one candidate that breaks both, and writes nothing.

    PRD: "9. **Minor protection, education and wellness safety** —
    `ERR_GUARDIAN_CONSENT_REQUIRED`, `ERR_MINOR_CATEGORY_FORBIDDEN`,
    `ERR_EDUCATION_HOURS_RESERVED`, `ERR_WEEKLY_HOUR_CAP_EXCEEDED`, `ERR_WELLNESS_HOLD_ACTIVE` and
    `ERR_OBLIGATION_BREACH_BLOCKS_ASSIGNMENT`, in that internal order, with the
    education-versus-workload tie-break spelled out in §3.5."
    PRD: "11. **Facility, quota and roster-size constraints** — `ERR_FACILITY_SLOT_CONFLICT`,
    `ERR_PLAYER_DOUBLE_BOOKED`, `ERR_FACILITY_CAPACITY_EXCEEDED`, `ERR_DELIVERABLE_QUOTA_EXCEEDED`,
    `ERR_TRYOUT_REQUIRED`, `ERR_ROSTER_SIZE_EXCEEDED` and `ERR_ROSTER_SIZE_BELOW_MINIMUM`."
    PRD: "An attendee's **scheduled minutes** for that week are the sum of `duration_minutes` over
    every block, in any team house of any organization, whose `block_status` is `SCHEDULED` or
    `HELD` and whose `starts_at` falls inside that week window and which lists that attendee —
    cancelled blocks are excluded, and the candidate block being booked is included in the sum."

    Design: Difficulty/priority_pair_validation_conflict/weekly_hour_cap_safety_error_outranks_facility_slot_constraint_error
    """
    ctx = _almost_full_week()
    _candidate(ctx, "2026-08-11T16:30:00Z", "2026-08-11T20:30:00Z")
    _candidate(ctx, "2026-08-13T10:00:00Z", "2026-08-13T15:10:00Z")

    both_broken = _candidate(ctx, "2026-08-11T16:30:00Z", "2026-08-11T21:40:00Z")
    validate_error(both_broken, ApiErrorId.ERR_WEEKLY_HOUR_CAP_EXCEEDED.value, 422)

    rows, _meta = validate_paginated(
        api_client.list_practice_blocks(
            make_coaching_staff_headers(), params={"organization_id": ctx["org"]["id"]}
        )
    )
    assert [row["id"] for row in rows] == [ctx["block_a"]["id"]]
    assert rows[0]["block_status"] == "SCHEDULED"
