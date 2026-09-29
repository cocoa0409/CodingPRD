"""Ballots, the quorum arithmetic and the nine-step renewal offer."""

from test_helpers import (
    ACTIVATION_CLOCK_UTC,
    assert_ballot,
    assert_renewal_decision,
    assert_subscription,
    ballot_payload,
    cast_vote,
    create_member,
    decide_payload,
    file_usage_months,
    make_librarian_headers,
    open_renewal_decision,
    open_vote,
    read_subscription,
    renewal_decision_payload,
    set_clock,
    setup_active_subscription,
    setup_multi_member_subscription,
    setup_signed_subscription,
    setup_voting_decision,
    subscription_version,
    validate_error,
    validate_paginated,
    validate_success,
)


def _read_decision(api, headers, subscription_id, decision_id):
    """One renewal decision of a subscription, read back through its listing."""
    rows, _ = validate_paginated(
        api.list_renewal_decisions(subscription_id, headers))
    matching = [row for row in rows if row["id"] == decision_id]
    assert len(matching) == 1, "the decision under test is on the subscription"
    return matching[0]


def _two_participants_and_one_ballot():
    """Two CONFIRMED participants, a VOTING decision and a single YES from Alpha."""
    scenario = setup_multi_member_subscription(
        [{"name": "Alpha College"}, {"name": "Bravo University"}], activate=True)
    subscription_id = scenario["subscription"]["id"]
    decision = open_renewal_decision(subscription_id, "RENEW", 0.00)
    decision = open_vote(decision["id"])
    scenario["ballot"] = cast_vote(decision["id"], scenario["members"][0]["id"], "YES")
    scenario["decision"] = decision
    return scenario


def test_second_ballot_from_the_same_member_is_rejected(api, admin):
    """One entry per member: a member cannot vote twice to manufacture a quorum.

    PRD: "And it must not have voted already: at most one entry per member is
    permitted on a decision, and a second attempt is `ERR_DUPLICATE_BALLOT` (409)."

    PRD: "Two counters are then recomputed: `yes_count` is the number of `ballots`
    entries whose `ballot` is `YES`, and `quorum_met` becomes true once the number
    of entries in `ballots` reaches or exceeds the number of confirmed participants
    multiplied by 60 and divided by 100, **rounded up to the next whole number**."

    Design: Corner/validations/second_ballot_from_the_same_member_is_rejected
    """
    scenario = _two_participants_and_one_ballot()
    alpha = scenario["members"][0]
    decision_id = scenario["decision"]["id"]

    response = api.cast_vote(decision_id, ballot_payload(alpha["id"], "NO"),
                             make_librarian_headers(alpha["id"]))
    validate_error(response, "ERR_DUPLICATE_BALLOT", 409)

    stored = _read_decision(api, admin, scenario["subscription"]["id"], decision_id)
    assert_renewal_decision(stored)
    assert stored["status"] == "VOTING"
    assert len(stored["ballots"]) == 1, "the refused ballot appended nothing"
    assert_ballot(stored["ballots"][0])
    assert stored["ballots"][0]["member_id"] == alpha["id"]
    assert stored["ballots"][0]["ballot"] == "YES", "the recorded vote was not overwritten"
    assert stored["yes_count"] == 1
    assert stored["quorum_met"] is False, "one of two participants is short of quorum"


def test_vote_from_a_member_without_a_confirmed_commitment_is_rejected(api, admin):
    """Membership in the consortium is not participation in the package.

    PRD: "The member must actually be a participant — it must hold a commitment row
    with `status` of `CONFIRMED` on the decision's subscription, otherwise
    `ERR_MEMBER_NOT_PARTICIPANT` (409)."

    Design: Corner/validations/vote_from_a_member_without_a_confirmed_commitment_is_rejected
    """
    scenario = setup_multi_member_subscription(
        [{"name": "Alpha College"}, {"name": "Bravo University"}], activate=True)
    decision = open_vote(
        open_renewal_decision(scenario["subscription"]["id"], "RENEW", 0.00)["id"])
    charlie = create_member(name="Charlie Institute")

    response = api.cast_vote(decision["id"], ballot_payload(charlie["id"], "YES"),
                             make_librarian_headers(charlie["id"]))
    validate_error(response, "ERR_MEMBER_NOT_PARTICIPANT", 409)

    stored = _read_decision(api, admin, scenario["subscription"]["id"], decision["id"])
    assert stored["status"] == "VOTING"
    assert stored["ballots"] == [], "no entry was appended for a non-participant"
    assert stored["yes_count"] == 0
    assert stored["quorum_met"] is False

    _, meta = validate_paginated(
        api.list_commitments(admin, {"member_id": charlie["id"]}))
    assert meta["total_count"] == 0, "Charlie holds no commitment anywhere"


def test_deciding_a_renewal_below_the_vote_quorum_is_rejected(api, admin):
    """One turnout of two participants is fifty percent, under the sixty percent floor.

    PRD: "All three require the decision to be in `VOTING` and require `quorum_met`
    to be true — a decision put without quorum is `ERR_VOTE_QUORUM_NOT_MET` (409)."

    PRD: "Note that quorum counts turnout, not agreement — a ballot that is not
    `YES` still advances quorum even though it does not advance `yes_count`."

    Design: Corner/validations/deciding_a_renewal_below_the_vote_quorum_is_rejected
    """
    scenario = _two_participants_and_one_ballot()
    subscription_id = scenario["subscription"]["id"]
    decision_id = scenario["decision"]["id"]

    response = api.decide_renewal(decision_id, decide_payload("RENEW"), admin)
    validate_error(response, "ERR_VOTE_QUORUM_NOT_MET", 409)

    stored = _read_decision(api, admin, subscription_id, decision_id)
    assert stored["status"] == "VOTING", "the fork never ran"
    assert stored["quorum_met"] is False, "two participants need two ballots"
    assert stored["resolved_action"] is None

    subscription = read_subscription(subscription_id)
    assert_subscription(subscription)
    assert subscription["contract_status"] == "ACTIVE", (
        "no branch reached into the contract axis"
    )
    assert subscription["negotiated_price_cents"] == 9000000


def test_renew_decide_above_the_inflation_cap_without_acceptance_is_rejected(api, admin):
    """The cap cannot be waived silently: the request must acknowledge it.

    PRD: "**The renew branch** additionally requires that either the decision's
    `vendor_requested_increase_pct` is less than or equal to the product's
    `inflation_cap_pct`, or the request explicitly carries `accept_capped_offer` set
    to true, acknowledging that the consortium will pay only the capped increase."

    PRD: "Neither being satisfied is `ERR_INFLATION_CAP_EXCEEDED` (422)."

    Design: Corner/validations/renew_decide_above_the_inflation_cap_without_acceptance_is_rejected
    """
    scenario = setup_voting_decision("RENEW", 12.00)
    subscription_id = scenario["subscription"]["id"]
    decision_id = scenario["decision"]["id"]
    cast_vote(decision_id, scenario["member"]["id"], "YES")

    response = api.decide_renewal(decision_id, decide_payload("RENEW"), admin)
    validate_error(response, "ERR_INFLATION_CAP_EXCEEDED", 422)

    stored = _read_decision(api, admin, subscription_id, decision_id)
    assert stored["status"] == "VOTING"
    assert stored["quorum_met"] is True, "the single participant did turn out"
    assert stored["resolved_action"] is None
    assert float(stored["vendor_requested_increase_pct"]) == 12.00

    subscription = read_subscription(subscription_id)
    assert subscription["negotiated_price_cents"] == 9000000
    assert subscription["contract_status"] == "ACTIVE"


def test_open_vote_computes_the_preliminary_offer(api, admin):
    """Putting the decision to the members stamps the figures they will vote on.

    PRD: "Putting the decision to the members advances it `DRAFT → VOTING`."

    PRD: "The transition also stamps a **preliminary offer**, computing
    `cost_per_use_cents`, `cost_per_use_band`, `capped_increase_pct`,
    `loyalty_credit_cents`, `sla_credit_applied_cents` and `offer_price_cents` so
    that members can see, before they vote, what renewal would cost."

    PRD: "If the pooled usage count is 0, the band is `NO_USE`."

    Design: Corner/endpoints/open_vote_computes_the_preliminary_offer
    """
    scenario = setup_active_subscription()
    decision = open_renewal_decision(scenario["subscription"]["id"], "RENEW", 0.00)
    assert decision["status"] == "DRAFT"
    assert decision["offer_price_cents"] is None, "nothing is computed at creation"

    response = api.open_vote(decision["id"], admin)
    data = validate_success(response)

    assert_renewal_decision(data)
    assert data["status"] == "VOTING"
    assert float(data["capped_increase_pct"]) == 0.00
    assert data["cost_per_use_cents"] is None, "no usage was ever filed"
    assert data["cost_per_use_band"] == "NO_USE"
    assert data["loyalty_credit_cents"] == 0, "a NO_USE band earns nothing"
    assert data["sla_credit_applied_cents"] == 0
    assert data["offer_price_cents"] == 9000000, (
        "no escalation and no credits leaves the running term's price"
    )
    assert data["ballots"] == []
    assert data["yes_count"] == 0
    assert data["quorum_met"] is False


def test_executing_a_decision_that_never_opened_voting_is_rejected(api, admin):
    """Only the three decided states have an execute edge out of them.

    PRD: "**Executing a renewal** requires the decision to be in `DECIDED_RENEW`
    and the subscription's `contract_status` to be `ACTIVE`."

    PRD: "The decision is created in `DRAFT` with `resolved_action` null,
    `capped_increase_pct`, `cost_per_use_cents`, `cost_per_use_band` and
    `offer_price_cents` all null, `loyalty_credit_cents` and
    `sla_credit_applied_cents` both 0, `ballots` empty, `yes_count` 0, `quorum_met`
    false and `delta_price_cents` null."

    Design: Corner/errors/executing_a_decision_that_never_opened_voting_is_rejected
    """
    scenario = setup_active_subscription()
    subscription_id = scenario["subscription"]["id"]
    decision = open_renewal_decision(subscription_id, "RENEW", 0.00)
    assert decision["status"] == "DRAFT"

    response = api.execute_renewal(decision["id"], admin)
    validate_error(response, "ERR_RENEWAL_INVALID_STATE", 409)

    stored = _read_decision(api, admin, subscription_id, decision["id"])
    assert stored["status"] == "DRAFT", "the refused execution moved nothing"
    assert stored["offer_price_cents"] is None
    assert stored["resolved_action"] is None
    assert stored["delta_price_cents"] is None

    subscription = read_subscription(subscription_id)
    assert subscription["term_end"] == "2027-12-31", "no term rolled forward"
    assert subscription["negotiated_price_cents"] == 9000000
    assert subscription["renewal_term_count"] == 0


def test_renewal_decision_create_with_a_stale_subscription_version_is_rejected(api, admin):
    """A version observed before activation is stale once the clock has moved the row.

    PRD: "`POST /erm/subscriptions/{id}/renewal-decisions` requires
    `expected_subscription_version` as a non-optional body field, carrying the
    `version` the client last observed on that subscription. If the value does not
    equal the subscription's current `version`, the request is rejected with
    `ERR_STALE_SUBSCRIPTION_VERSION` (HTTP 412)."

    PRD: "Most resources additionally carry `updated_at` — same format as
    `created_at`, refreshed on every mutation of the row — and `version`, an integer
    that starts at 1 when the row is created and increments by exactly 1 on every
    mutation."

    Design: Corner/cross_cutting_complexity_layers/renewal_decision_create_with_a_stale_subscription_version_is_rejected
    """
    scenario = setup_signed_subscription()
    subscription_id = scenario["subscription"]["id"]
    observed_version = subscription_version(subscription_id)

    set_clock(ACTIVATION_CLOCK_UTC)
    assert read_subscription(subscription_id)["contract_status"] == "ACTIVE"
    assert subscription_version(subscription_id) != observed_version, (
        "the activation was a mutation of the subscription row"
    )

    response = api.create_renewal_decision(
        subscription_id,
        renewal_decision_payload(observed_version, "RENEW", 0.00),
        admin,
    )
    validate_error(response, "ERR_STALE_SUBSCRIPTION_VERSION", 412)

    _, meta = validate_paginated(api.list_renewal_decisions(subscription_id, admin))
    assert meta["total_count"] == 0, "the stale create stored no decision"
    assert read_subscription(subscription_id)["contract_status"] == "ACTIVE"


def _vote_open_on_an_above_cap_request():
    """A VOTING RENEW decision asking 8.00 percent against a 5.00 percent cap.

    Two filed months pool to 6,200 full-text requests once the clock reads
    2027-03-01, and the subscription has never degraded, so the only credit in
    play is the loyalty credit the band earns.
    """
    scenario = setup_active_subscription()
    subscription_id = scenario["subscription"]["id"]
    file_usage_months(subscription_id, scenario["vendor"]["id"],
                      scenario["member"]["id"],
                      [("2027-01", 3000), ("2027-02", 3200)])
    set_clock("2027-03-01T00:00:00Z")

    decision = open_renewal_decision(subscription_id, "RENEW", 8.00)
    scenario["decision"] = open_vote(decision["id"])
    scenario["ballot"] = cast_vote(decision["id"], scenario["member"]["id"], "YES")
    return scenario


def test_the_renewal_offer_keys_its_band_on_the_prior_term_price(api, admin):
    """The band comes from 9,000,000 over 6,200 uses, never from the escalated price.

    PRD: "The circle is broken by pinning the evaluation order, and the pin is not
    negotiable: **the band is always keyed on the prior term's price, never on the
    offer being computed**."

    PRD: "Compute the loyalty credit: multiply the prior price by the band's credit
    percentage divided by 100, and round half up to whole cents."

    PRD: "Set `offer_price_cents` to the larger of that floor and the escalated
    amount less the loyalty credit less the applied SLA credit."

    Design: Difficulty/combinatorial_formula/renewal_offer_band_keyed_on_prior_term_price_not_on_the_offer_being_computed
    """
    scenario = _vote_open_on_an_above_cap_request()
    subscription_id = scenario["subscription"]["id"]

    response = api.decide_renewal(
        scenario["decision"]["id"],
        decide_payload("RENEW", accept_capped_offer=True),
        admin,
    )
    data = validate_success(response)

    assert_renewal_decision(data)
    assert data["status"] == "DECIDED_RENEW"
    assert data["resolved_action"] == "RENEW"
    assert float(data["capped_increase_pct"]) == 5.00, "8.00 asked, 5.00 conceded"
    assert data["cost_per_use_cents"] == 1452, (
        "9,000,000 over 6,200 requests, rounded half up"
    )
    assert data["cost_per_use_cents"] != 1524, (
        "keying the band on the escalated 9,450,000 would have read 1,524"
    )
    assert data["cost_per_use_band"] == "GOOD", "1,452 is below the 1,500 threshold"
    assert data["loyalty_credit_cents"] == 180000, "two percent of the prior price"
    assert data["sla_credit_applied_cents"] == 0
    assert data["offer_price_cents"] == 9270000, (
        "9,450,000 escalated less 180,000 of loyalty credit"
    )
    assert data["offer_price_cents"] != 9000000, (
        "a POOR band would have credited five percent and landed on 9,000,000"
    )
    assert data["offer_price_cents"] != 9540000, (
        "the uncapped 8.00 percent escalation is not what the consortium pays"
    )

    subscription = read_subscription(subscription_id)
    assert subscription["negotiated_price_cents"] == 9000000, (
        "deciding computes the offer; it does not spend it"
    )
    assert subscription["renewal_term_count"] == 0
    assert subscription["term_end"] == "2027-12-31"


def test_the_pinned_band_is_stamped_identically_at_the_preliminary_offer(api, admin):
    """The offer is computed at three moments and the pin holds at every one of them.

    PRD: "The **renewal offer price** is computed at three moments — as the
    preliminary offer when the vote opens, as the final figures when the decision is
    decided, and as the fourth hop of the reopen cascade for any decision still in
    `VOTING`."

    PRD: "Re-deriving the band from `offer_price_cents` is forbidden."

    PRD: "Compute the floor: multiply the prior price by 50 and divide by 100 — half
    the running-term price — and round half up to whole cents."

    Design: Difficulty/combinatorial_formula/renewal_offer_band_keyed_on_prior_term_price_not_on_the_offer_being_computed
    """
    scenario = _vote_open_on_an_above_cap_request()
    subscription_id = scenario["subscription"]["id"]
    preliminary = scenario["decision"]

    assert preliminary["status"] == "VOTING"
    assert preliminary["cost_per_use_cents"] == 1452
    assert preliminary["cost_per_use_band"] == "GOOD"
    assert preliminary["loyalty_credit_cents"] == 180000
    assert preliminary["offer_price_cents"] == 9270000, (
        "the preliminary offer already exceeds the 4,500,000 floor"
    )

    final = validate_success(api.decide_renewal(
        preliminary["id"], decide_payload("RENEW", accept_capped_offer=True), admin))

    for field in ("capped_increase_pct", "cost_per_use_cents", "cost_per_use_band",
                  "loyalty_credit_cents", "sla_credit_applied_cents",
                  "offer_price_cents"):
        assert final[field] == preliminary[field], (
            f"{field} moved between the preliminary and the final offer"
        )

    stored = _read_decision(api, admin, subscription_id, preliminary["id"])
    assert stored["status"] == "DECIDED_RENEW"
    assert stored["offer_price_cents"] == 9270000
    assert stored["yes_count"] == 1
    assert stored["quorum_met"] is True, "one ballot from one participant is quorum"
    assert read_subscription(subscription_id)["negotiated_price_cents"] == 9000000
