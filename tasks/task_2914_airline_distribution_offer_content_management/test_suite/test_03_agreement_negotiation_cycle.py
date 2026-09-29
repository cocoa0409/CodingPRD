"""The counter/propose negotiation cycle and the signature that closes it."""

from test_helpers import (
    AGREEMENT_COUNTERED,
    AGREEMENT_PROPOSED,
    AGREEMENT_SIGNED,
    DISTRIBUTION_MANAGER_HEADERS,
    DISTRIBUTION_MANAGER_USER_ID,
    NEGOTIATION_ACCEPT,
    NEGOTIATION_COUNTER,
    NEGOTIATION_PROPOSE,
    OTHER_DISTRIBUTION_MANAGER_HEADERS,
    OTHER_DISTRIBUTION_MANAGER_USER_ID,
    ApiErrorId,
    agency_headers,
    factories as f,
    fixtures as fx,
    validate_error,
)


def _opened_agreement(api):
    channel = fx.create_ndc_channel(api, with_surcharge_rules=False)
    partner = fx.create_alpha_agency(api)
    agreement = fx.open_agreement(
        api,
        partner["id"],
        channel["id"],
        partner["version"],
        proposed_incentive_pct=0.020,
    )
    return channel, partner, agreement


def test_counter_propose_pair_traverses_twice_before_signature(api):
    """PRD §3.3: "A `COUNTER` is the agency's move and advances `PROPOSED → COUNTERED`:
    it may be performed only by the `Agency` whose `X-User-ID` equals the agreement's
    `partner_id`, it increases `negotiation_round` by 1, and it replaces
    `proposed_incentive_pct` with the countered value."
    PRD §3.3: "A `PROPOSE` is the airline's move and closes the cycle, `COUNTERED →
    PROPOSED`: a `DistributionManager` replaces `proposed_incentive_pct` with the
    airline's new value and `proposed_by_user_id` is reset to the acting `X-User-ID`."
    PRD §3.3: "On signing, `agreed_incentive_pct` is frozen to whatever
    `proposed_incentive_pct` currently holds — the frozen figure, not the mutable one,
    is what the accrual calculation uses forever after — `signed_by_user_id` records
    the accepting operator, and `version` increases by 1."

    Design: Difficulty/non_linear_state_machine/agreement_counter_propose_cycle_reaches_signed_on_round_two
    """
    _channel, partner, agreement = _opened_agreement(api)
    headers = agency_headers(partner["id"])

    assert agreement["status"] == AGREEMENT_PROPOSED
    assert agreement["negotiation_round"] == 0
    assert agreement["agreed_incentive_pct"] is None
    assert agreement["signed_by_user_id"] is None
    assert agreement["proposed_by_user_id"] == DISTRIBUTION_MANAGER_USER_ID
    opening_version = agreement["version"]

    round_one = fx.negotiate(
        api,
        agreement["id"],
        NEGOTIATION_COUNTER,
        headers=headers,
        proposed_incentive_pct=0.060,
    )
    assert round_one["status"] == AGREEMENT_COUNTERED
    assert round_one["negotiation_round"] == 1
    assert round_one["proposed_incentive_pct"] == 0.060
    assert round_one["version"] == opening_version + 1

    answer_one = fx.negotiate(
        api,
        agreement["id"],
        NEGOTIATION_PROPOSE,
        proposed_incentive_pct=0.035,
    )
    assert answer_one["status"] == AGREEMENT_PROPOSED
    # PROPOSE answers a counter; it does not consume a round of its own.
    assert answer_one["negotiation_round"] == 1
    assert answer_one["proposed_incentive_pct"] == 0.035
    assert answer_one["version"] == opening_version + 2

    round_two = fx.negotiate(
        api,
        agreement["id"],
        NEGOTIATION_COUNTER,
        headers=headers,
        proposed_incentive_pct=0.050,
    )
    assert round_two["status"] == AGREEMENT_COUNTERED
    assert round_two["negotiation_round"] == 2

    answer_two = fx.negotiate(
        api,
        agreement["id"],
        NEGOTIATION_PROPOSE,
        proposed_incentive_pct=0.040,
    )
    assert answer_two["status"] == AGREEMENT_PROPOSED
    assert answer_two["proposed_incentive_pct"] == 0.040

    signed = fx.negotiate(
        api,
        agreement["id"],
        NEGOTIATION_ACCEPT,
        headers=OTHER_DISTRIBUTION_MANAGER_HEADERS,
    )
    assert signed["status"] == AGREEMENT_SIGNED
    # The frozen figure is the value on the table at signature, not the opening 0.020
    # nor any intermediate counter.
    assert signed["agreed_incentive_pct"] == 0.040
    assert signed["proposed_incentive_pct"] == 0.040
    assert signed["signed_by_user_id"] == OTHER_DISTRIBUTION_MANAGER_USER_ID
    assert signed["negotiation_round"] == 2
    assert signed["version"] == opening_version + 5
    # The ledger has not started moving yet.
    assert signed["cumulative_net_revenue_cents"] == 0
    assert signed["incentive_accrued_cents"] == 0
    assert signed["tier_downgrade_count"] == 0


def test_the_last_proposer_cannot_sign_the_agreement_it_re_proposed(api):
    """PRD §3.3: "`ACCEPT` signs the deal, `PROPOSED → SIGNED`, and it is the single
    operation in this service under segregation of duties: the `DistributionManager`
    performing it must have an `X-User-ID` different from the value stored in
    `proposed_by_user_id`, and an attempt by the proposer to sign its own proposal is
    rejected with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.3: "Because `COUNTERED → PROPOSED` returns the agreement to the state a
    `COUNTER` starts from, the pair can be traversed repeatedly — that is the
    negotiation."

    Design: Difficulty/non_linear_state_machine/agreement_counter_propose_cycle_reaches_signed_on_round_two
    """
    _channel, partner, agreement = _opened_agreement(api)
    headers = agency_headers(partner["id"])

    fx.negotiate(
        api,
        agreement["id"],
        NEGOTIATION_COUNTER,
        headers=headers,
        proposed_incentive_pct=0.060,
    )
    reproposed = fx.negotiate(
        api,
        agreement["id"],
        NEGOTIATION_PROPOSE,
        proposed_incentive_pct=0.035,
    )
    assert reproposed["proposed_by_user_id"] == DISTRIBUTION_MANAGER_USER_ID

    response = api.create_negotiation_round(
        agreement["id"],
        f.negotiation_payload(NEGOTIATION_ACCEPT),
        headers=DISTRIBUTION_MANAGER_HEADERS,
    )
    validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES)

    blocked = fx.read_agreement(api, agreement["id"])
    assert blocked["status"] == AGREEMENT_PROPOSED
    assert blocked["agreed_incentive_pct"] is None
    assert blocked["version"] == reproposed["version"]

    signed = fx.negotiate(
        api,
        agreement["id"],
        NEGOTIATION_ACCEPT,
        headers=OTHER_DISTRIBUTION_MANAGER_HEADERS,
    )
    assert signed["status"] == AGREEMENT_SIGNED
    assert signed["agreed_incentive_pct"] == 0.035
    assert signed["negotiation_round"] == 1
