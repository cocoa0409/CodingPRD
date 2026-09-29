"""Machines that are not a straight line.

An offer walks SENT -> COUNTERED -> SENT as often as the round ceiling allows and
locks solid once it is declined; a contract carries an employment dimension and a
wellness dimension on the same row, and neither one drives the other.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant_equals,
    fixtures,
    make_general_manager_headers,
    make_league_admin_headers,
    make_performance_support_headers,
    make_player_agent_headers,
    validate_error,
    validate_success,
)


def _open_negotiation():
    """One SENT offer stamped at 2026-08-04, so it expires at 2026-08-07."""
    ctx = fixtures.setup_league_and_org()
    ctx["player"] = fixtures.create_player()
    fixtures.set_clock("2026-08-04T00:00:00Z")
    ctx["offer"] = fixtures.create_offer(ctx["org"]["id"], ctx["player"]["id"])
    ctx["agent_headers"] = make_player_agent_headers(ctx["player"]["id"])
    return ctx


def _counter(ctx, base_salary_cents, note=None):
    payload = {
        "counter_base_salary_cents": base_salary_cents,
        "counter_prize_split_player_pct_bp": 4900,
        "counter_streaming_hours_per_week": 9,
    }
    if note is not None:
        payload["counter_note"] = note
    return api_client.counter_contract_offer(
        ctx["offer"]["id"], payload, ctx["agent_headers"]
    )


def _revise(ctx, base_salary_cents, prize_split_bp, streaming_hours):
    return api_client.revise_contract_offer(
        ctx["offer"]["id"],
        {
            "base_salary_cents": base_salary_cents,
            "prize_split_player_pct_bp": prize_split_bp,
            "streaming_hours_per_week": streaming_hours,
        },
        make_general_manager_headers(ctx["org"]["id"]),
    )


def test_revision_restarts_the_response_window_and_reopens_the_cycle():
    """A counter after the original deadline is admitted because revise re-stamped it.

    PRD: "Countering belongs to the player's agent, who may act only on offers naming their own
    player. The counter carries `counter_base_salary_cents`, `counter_prize_split_player_pct_bp`
    and `counter_streaming_hours_per_week` as mandatory values plus an optional `counter_note`,
    and it moves the offer `SENT` → `COUNTERED` while recording all four fields."
    PRD: "That revision moves the offer `COUNTERED` → `SENT`, increases `round_number` by exactly
    1, overwrites the three headline terms with the revised ones, clears all four counter fields
    back to null, re-stamps `sent_at` to the current instant and recomputes `expires_at` from that
    new instant plus the league's response window — so each round of haggling restarts the clock
    rather than eating into a single fixed deadline."

    Design: Difficulty/non_linear_state_machine/contract_offer_negotiation_cycle_round_cap_and_terminal_lockdown
    """
    ctx = _open_negotiation()
    assert_instant_equals(
        ctx["offer"]["expires_at"], "2026-08-07T00:00:00Z", "offer.expires_at"
    )

    fixtures.set_clock("2026-08-05T00:00:00Z")
    countered = validate_success(_counter(ctx, 13500000, "round 1 counter"))
    assert countered["offer_status"] == "COUNTERED"
    assert countered["round_number"] == 1
    assert countered["counter_base_salary_cents"] == 13500000

    fixtures.set_clock("2026-08-06T00:00:00Z")
    revised = validate_success(_revise(ctx, 13000000, 4800, 9))
    assert revised["offer_status"] == "SENT"
    assert revised["round_number"] == 2
    assert revised["base_salary_cents"] == 13000000
    assert revised["counter_base_salary_cents"] is None
    assert revised["counter_prize_split_player_pct_bp"] is None
    assert revised["counter_streaming_hours_per_week"] is None
    assert_instant_equals(revised["sent_at"], "2026-08-06T00:00:00Z", "offer.sent_at")
    assert_instant_equals(revised["expires_at"], "2026-08-09T00:00:00Z", "offer.expires_at")

    fixtures.set_clock("2026-08-08T00:00:00Z")
    second_counter = validate_success(_counter(ctx, 13200000, "round 2 counter"))
    assert second_counter["offer_status"] == "COUNTERED"
    assert second_counter["round_number"] == 2


def test_third_counter_is_refused_once_the_round_counter_reaches_the_ceiling():
    """The loop terminates at max_negotiation_rounds and the offer stays open at SENT.

    PRD: "Countering does not itself change `round_number`, but it is only permitted while
    `round_number` is strictly less than the league's `max_negotiation_rounds`; once the round
    counter has reached that ceiling the counter is refused with
    `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` (HTTP 409)."
    PRD: "With the default ceiling of three rounds, an agent therefore gets three bites at the
    terms."

    Design: Difficulty/non_linear_state_machine/contract_offer_negotiation_cycle_round_cap_and_terminal_lockdown
    """
    ctx = _open_negotiation()
    fixtures.set_clock("2026-08-05T00:00:00Z")
    validate_success(_counter(ctx, 13500000, "round 1 counter"))
    fixtures.set_clock("2026-08-06T00:00:00Z")
    validate_success(_revise(ctx, 13000000, 4800, 9))
    fixtures.set_clock("2026-08-08T00:00:00Z")
    validate_success(_counter(ctx, 13200000, "round 2 counter"))
    fixtures.set_clock("2026-08-08T12:00:00Z")
    third_round = validate_success(_revise(ctx, 13100000, 4850, 9))
    assert third_round["round_number"] == 3
    assert_instant_equals(third_round["sent_at"], "2026-08-08T12:00:00Z", "offer.sent_at")
    assert_instant_equals(
        third_round["expires_at"], "2026-08-11T12:00:00Z", "offer.expires_at"
    )

    fixtures.set_clock("2026-08-09T00:00:00Z")
    refused = _counter(ctx, 13300000)
    validate_error(refused, ApiErrorId.ERR_NEGOTIATION_ROUNDS_EXHAUSTED.value, 409)

    stored = validate_success(
        api_client.get_contract_offer(
            ctx["offer"]["id"], make_general_manager_headers(ctx["org"]["id"])
        )
    )
    assert stored["offer_status"] == "SENT"
    assert stored["round_number"] == 3


def test_declining_locks_the_cycle_out_for_good():
    """DECLINED is terminal, so the agent's next counter finds a closed offer.

    PRD: "An agent who wants nothing to do with the terms declines instead, optionally recording a
    `decline_note`; the offer moves from `SENT` or from `COUNTERED` to `DECLINED` and nothing else
    in the system changes."
    PRD: "An offer's six states are `SENT`, `COUNTERED`, `ACCEPTED`, `DECLINED`, `EXPIRED` and
    `SUPERSEDED`, of which the last four are terminal — an offer in any of them accepts no further
    action, and an attempt to act on one is refused with `ERR_OFFER_NOT_OPEN` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/contract_offer_negotiation_cycle_round_cap_and_terminal_lockdown
    """
    ctx = _open_negotiation()
    fixtures.set_clock("2026-08-05T00:00:00Z")
    validate_success(_counter(ctx, 13500000, "round 1 counter"))
    fixtures.set_clock("2026-08-06T00:00:00Z")
    validate_success(_revise(ctx, 13000000, 4800, 9))

    declined = validate_success(
        api_client.decline_contract_offer(
            ctx["offer"]["id"], {"decline_note": "agent walked away"}, ctx["agent_headers"]
        )
    )
    assert declined["offer_status"] == "DECLINED"

    refused = _counter(ctx, 13400000)
    validate_error(refused, ApiErrorId.ERR_OFFER_NOT_OPEN.value, 409)

    stored = validate_success(
        api_client.get_contract_offer(
            ctx["offer"]["id"], make_general_manager_headers(ctx["org"]["id"])
        )
    )
    assert stored["offer_status"] == "DECLINED"


def _contract_with_1890_held_minutes():
    """One ACTIVE contract carrying 1890 HELD minutes, clock parked at 2026-08-11T15:00Z."""
    ctx = fixtures.setup_signed_player(with_team_house=True)
    ctx["blocks"] = fixtures.setup_held_blocks(
        ctx["org"]["id"],
        ctx["house"]["id"],
        [ctx["player"]["id"]],
        [
            ("2026-08-10T06:00:00Z", "2026-08-11T00:00:00Z"),
            ("2026-08-11T01:00:00Z", "2026-08-11T14:30:00Z"),
        ],
        complete_at="2026-08-11T15:00:00Z",
    )
    return ctx


def _report(ctx, load, streaming_minutes):
    return api_client.file_wellness_report(
        ctx["contract"]["id"],
        {
            "last_self_reported_load": load,
            "reported_streaming_minutes_7d": streaming_minutes,
        },
        make_performance_support_headers(),
    )


def test_warned_and_breach_escalations_differ_by_exactly_two_side_effects():
    """Only the breach stamps a hold and a flag, and neither touches employment.

    PRD: "A contract sitting in `COMPLIANT` whose refreshed score is at least 70 but strictly below
    85 moves to `WARNED`. A contract in `COMPLIANT` or in `WARNED` whose refreshed score is at
    least 85 moves to `BREACH`."
    PRD: "Only entry into `BREACH` additionally stamps `wellness_hold_until` at the current instant
    plus seven days and increases the organization's `wellness_flag_count` by 1; a `WARNED`
    escalation stamps neither."
    PRD: "Neither drives the other: suspending a contract leaves its obligation dimension exactly
    where it was, and a burnout escalation leaves employment untouched."

    Design: Difficulty/non_linear_state_machine/player_contract_parallel_dimensions_suspension_versus_obligation_escalation
    """
    ctx = _contract_with_1890_held_minutes()
    gm_headers = make_general_manager_headers(ctx["org"]["id"])

    baseline = validate_success(api_client.get_contract(ctx["contract"]["id"], gm_headers))
    assert baseline["season_practice_minutes"] == 1890
    assert baseline["burnout_score"] == 35
    assert baseline["obligation_status"] == "COMPLIANT"

    warned = validate_success(_report(ctx, 6, 600))
    assert warned["burnout_score"] == 73
    assert warned["obligation_status"] == "WARNED"
    assert warned["contract_status"] == "ACTIVE"
    assert warned["wellness_hold_until"] is None
    assert validate_success(api_client.get_organization(ctx["org"]["id"], gm_headers))[
        "wellness_flag_count"
    ] == 0

    breached = validate_success(_report(ctx, 10, 600))
    assert breached["burnout_score"] == 85
    assert breached["obligation_status"] == "BREACH"
    assert breached["contract_status"] == "ACTIVE"
    assert_instant_equals(
        breached["wellness_hold_until"], "2026-08-18T15:00:00Z", "contract.wellness_hold_until"
    )
    assert validate_success(api_client.get_organization(ctx["org"]["id"], gm_headers))[
        "wellness_flag_count"
    ] == 1


def test_the_obligation_dimension_never_walks_back_down():
    """A clean report drops the score to 35 and the contract stays in BREACH.

    PRD: "The wellness dimension is escalation-only — `COMPLIANT` may move to `WARNED` or straight
    to `BREACH`, and `WARNED` may move to `BREACH`, but nothing ever moves back down, so `BREACH`
    is terminal for that dimension."
    PRD: "The report carries `last_self_reported_load`, a mandatory integer from 0 to 10, and
    optionally `reported_streaming_minutes_7d`, an integer of zero or more describing the streaming
    minutes the player actually delivered over the trailing seven days. Both are stored on the
    contract and both feed the score."

    Design: Difficulty/non_linear_state_machine/player_contract_parallel_dimensions_suspension_versus_obligation_escalation
    """
    ctx = _contract_with_1890_held_minutes()
    validate_success(_report(ctx, 10, 600))

    cleared = validate_success(_report(ctx, 0, 0))
    assert cleared["burnout_score"] == 35
    assert cleared["obligation_status"] == "BREACH"
    assert cleared["last_self_reported_load"] == 0
    assert cleared["reported_streaming_minutes_7d"] == 0


def test_suspension_moves_only_the_employment_dimension_and_then_gates_reports():
    """The combined (SUSPENDED, BREACH) state is reachable, and dimension A closes the endpoint.

    PRD: "The league administrator supplies a mandatory `suspension_reason`, which is recorded, and
    the contract moves `ACTIVE` → `SUSPENDED`."
    PRD: "The organization's `active_roster_count` decreases by 1, but its
    `committed_salary_cents` is **not** released — a suspended contract still consumes cap space,
    which is what stops suspension from being used as a budget trick."
    PRD: "Performance-support staff drive the wellness dimension by filing a report against an
    `ACTIVE` contract — a `SUSPENDED` or `TERMINATED` contract takes no new reports and yields
    `ERR_CONTRACT_NOT_ACTIVE`."

    Design: Difficulty/non_linear_state_machine/player_contract_parallel_dimensions_suspension_versus_obligation_escalation
    """
    ctx = _contract_with_1890_held_minutes()
    gm_headers = make_general_manager_headers(ctx["org"]["id"])
    validate_success(_report(ctx, 10, 600))
    validate_success(_report(ctx, 0, 0))

    suspended = validate_success(
        api_client.suspend_contract(
            ctx["contract"]["id"],
            {"suspension_reason": "medical leave"},
            make_league_admin_headers(),
        )
    )
    assert suspended["contract_status"] == "SUSPENDED"
    assert suspended["obligation_status"] == "BREACH"

    organization = validate_success(api_client.get_organization(ctx["org"]["id"], gm_headers))
    assert organization["committed_salary_cents"] == 12328767
    assert organization["active_roster_count"] == 0

    refused = _report(ctx, 4, 300)
    validate_error(refused, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value, 409)

    stored = validate_success(api_client.get_contract(ctx["contract"]["id"], gm_headers))
    assert stored["burnout_score"] == 35
    assert stored["obligation_status"] == "BREACH"
