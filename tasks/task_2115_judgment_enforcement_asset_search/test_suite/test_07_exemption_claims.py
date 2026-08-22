"""The debtor's answer: exemption claims, opposition, rulings and the quash cascade."""

from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    assert_custody_conservation,
    assert_sweep_summary_shape,
    book_payment,
    create_exemption_claim_payload,
    create_payment_payload,
    create_verified_finding,
    debtor_version,
    draft_enforcement_action,
    file_exemption_claim,
    make_case_manager_headers,
    make_compliance_officer_headers,
    make_debtor_headers,
    make_enforcement_officer_headers,
    read_action,
    read_claim,
    read_finding,
    read_judgment,
    setup_filed_exemption_claim,
    setup_opposed_exemption_claim,
    setup_perfected_judgment,
    setup_served_bank_levy,
    skip_trace_payload,
    make_asset_investigator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CM = make_case_manager_headers()
EO = make_enforcement_officer_headers("eo-1")
CO = make_compliance_officer_headers("co-1")


# ==========================================================================
# A sustained claim unwinds the levy end to end
# ==========================================================================
def test_a_sustained_household_claim_quashes_the_writ_and_exhausts_the_asset(api):
    """PRD §3.6: "An outcome of `SUSTAINED` moves the claim `OPPOSED → SUSTAINED`
    and unwinds the levy end to end. The linked enforcement action is quashed —
    `SERVED → QUASHED` or `SUSPENDED → QUASHED`, depending on where it was
    sitting."
    PRD §3.6: "That quash returns `levy_hold_cents` from the finding's
    `frozen_cents` to its `available_cents` and sets `levy_hold_cents` to 0, and
    sets `weekly_withholding_cents` to 0."
    PRD §3.6: "When the `claim_type` is `HEAD_OF_HOUSEHOLD` or `HOMESTEAD` the
    underlying asset is placed permanently out of reach and the finding moves
    `VERIFIED → EXHAUSTED`; for `SOCIAL_SECURITY` and `WAGE_CAP` claims the
    finding keeps its `VERIFIED` status, because only this particular writ was
    defeated."

    Design: Difficulty/transitive_cascade/exemption_sustained_quash_cascade_depth_four
    """
    ctx = setup_opposed_exemption_claim(
        claim_type="HEAD_OF_HOUSEHOLD",
        claimed_amount_cents=725_000,
        opposing_officer_user_id="eo-2",
        finding_value_cents=900_000,
        court_case_number="CV-2026-0401",
        debtor_overrides={"head_of_household": True,
                          "weekly_disposable_earnings_cents": 100_000},
        filing_overrides={"fee_cents": 0},
    )

    ruled = validate_success(
        api.rule_exemption_claim(ctx["claim"]["id"], "SUSTAINED", CO)
    )
    assert ruled["status"] == "SUSTAINED"

    action = read_action(ctx["action"]["id"])
    assert action["status"] == "QUASHED"
    assert action["levy_hold_cents"] == 0

    finding = read_finding(ctx["finding"]["id"])
    assert finding["status"] == "EXHAUSTED"
    assert finding["frozen_cents"] == 0
    assert finding["available_cents"] == 900_000
    assert_custody_conservation(finding)


def test_the_served_levy_and_its_claim_carry_the_declared_deadlines(api):
    """PRD §3.6: "Filing stamps `filed_on` with the current clock date, sets
    `filing_deadline_on` to 20 days after the writ's `served_on`, and sets
    `opposition_deadline_on` to 10 days after `filed_on`."
    PRD §3.6: "An `EnforcementOfficer` may **oppose** it, moving `FILED →
    OPPOSED` and stamping `opposed_on` with the current clock date and
    `opposed_by_user_id` with the officer's `X-User-ID`; the linked enforcement
    action must be in `SERVED` or `SUSPENDED` at that moment."

    Design: Difficulty/transitive_cascade/exemption_sustained_quash_cascade_depth_four
    """
    ctx = setup_opposed_exemption_claim(
        claim_type="HEAD_OF_HOUSEHOLD",
        claimed_amount_cents=725_000,
        opposing_officer_user_id="eo-2",
        finding_value_cents=900_000,
        court_case_number="CV-2026-0404",
        debtor_overrides={"head_of_household": True,
                          "weekly_disposable_earnings_cents": 100_000},
        filing_overrides={"fee_cents": 0},
    )

    assert ctx["action"]["levy_hold_cents"] == 725_000
    assert ctx["claim"]["filed_on"] == "2026-08-01"
    assert ctx["claim"]["opposition_deadline_on"] == "2026-08-11"
    assert ctx["claim"]["status"] == "OPPOSED"
    assert ctx["claim"]["opposed_by_user_id"] == "eo-2"

    judgment = read_judgment(ctx["judgment"]["id"])
    assert judgment["status"] == "ACTIVE"
    assert judgment["costs_balance_cents"] == 57_500


# ==========================================================================
# A live claim blocks the money
# ==========================================================================
def test_money_cannot_be_booked_while_a_claim_is_still_opposed(api):
    """PRD §3.6: "One more consequence of a live claim: while any exemption claim
    on an enforcement action sits in `FILED` or `OPPOSED`, money may not be booked
    against that action. A payment naming that `enforcement_action_id` is refused
    with `ERR_EXEMPTION_PENDING` until every claim on it has resolved."

    Design: Difficulty/cross_entity_state_dependency/levy_payment_blocked_while_exemption_claim_pending
    """
    ctx = setup_opposed_exemption_claim(
        claim_type="SOCIAL_SECURITY",
        claimed_amount_cents=300_000,
        opposing_officer_user_id="eo-2",
        finding_value_cents=900_000,
        court_case_number="CV-2026-0703",
        filing_overrides={"fee_cents": 0},
    )

    validate_error(
        api.create_payment(
            create_payment_payload(
                ctx["judgment"]["id"], 725_000, "2026-08-01",
                source="LEVY", enforcement_action_id=ctx["action"]["id"],
            ),
            CM,
        ),
        ApiErrorId.ERR_EXEMPTION_PENDING.value,
        409,
    )
    assert read_action(ctx["action"]["id"])["status"] == "SERVED"


def test_an_overruled_claim_lets_the_levy_remittance_collect(api):
    """PRD §3.6: "An outcome of `OVERRULED` moves the claim `OPPOSED → OVERRULED`
    and changes nothing outside the claim row. The linked enforcement action keeps
    its status, keeps its `levy_hold_cents`, and the finding's custody split
    between `available_cents`, `frozen_cents` and `swept_cents` is untouched."
    PRD §3.5: "When it collects, `collected_cents` rises by the payment amount,
    and for a bank levy the finding's `frozen_cents` falls by `levy_hold_cents`
    while its `swept_cents` rises by the same amount, leaving `available_cents`
    untouched so that the three-way custody identity still holds, after which
    `levy_hold_cents` is set to 0 and the action moves `SERVED → COLLECTED`,
    decrementing `active_enforcement_count`."

    Design: Difficulty/cross_entity_state_dependency/levy_payment_blocked_while_exemption_claim_pending
    """
    ctx = setup_opposed_exemption_claim(
        claim_type="SOCIAL_SECURITY",
        claimed_amount_cents=300_000,
        opposing_officer_user_id="eo-2",
        finding_value_cents=900_000,
        court_case_number="CV-2026-0704",
        filing_overrides={"fee_cents": 0},
    )

    ruled = validate_success(
        api.rule_exemption_claim(ctx["claim"]["id"], "OVERRULED", CO)
    )
    assert ruled["status"] == "OVERRULED"

    book_payment(
        ctx["judgment"]["id"], 725_000, received_on="2026-08-01",
        source="LEVY", enforcement_action_id=ctx["action"]["id"],
    )

    action = read_action(ctx["action"]["id"])
    assert action["status"] == "COLLECTED"
    assert action["collected_cents"] == 725_000

    finding = read_finding(ctx["finding"]["id"])
    assert finding["frozen_cents"] == 0
    assert finding["available_cents"] == 175_000
    assert finding["swept_cents"] == 725_000
    assert_custody_conservation(finding)
    assert read_judgment(ctx["judgment"]["id"])["collected_to_date_cents"] == 725_000


# ==========================================================================
# Screening order: segregation of duties beats the stale-finding check
# ==========================================================================
def _levy_drafted_then_staled_by_its_own_verifier():
    """A BANK_LEVY drafted against a SKIP_TRACE finding verified by inv-7, which a
    later trace by the same investigator has since staled."""
    ctx = setup_perfected_judgment(
        court_case_number="CV-2026-0502",
        debtor_overrides={"weekly_disposable_earnings_cents": 100_000},
        filing_overrides={"fee_cents": 0},
        filing_costs_cents=0,
    )
    ctx["finding"] = create_verified_finding(
        ctx["judgment"]["id"], "inv-7",
        estimated_value_cents=900_000, source="SKIP_TRACE",
    )
    ctx["action"] = draft_enforcement_action(
        ctx["judgment"]["id"], ctx["finding"]["id"], "BANK_LEVY"
    )
    validate_success(
        api_client.skip_trace(
            ctx["debtor"]["id"],
            skip_trace_payload(
                debtor_version(ctx["debtor"]["id"]), vendor="IDI", hits_count=5
            ),
            make_asset_investigator_headers("inv-7"),
        )
    )
    return ctx


def test_a_superseding_trace_stales_the_finding_the_levy_rests_on(api):
    """PRD §3.3: "Every asset finding whose `source` is `SKIP_TRACE`, which hangs
    off a judgment whose `debtor_id` is the traced debtor, and whose own status is
    `OPEN` or `VERIFIED`, is moved to `STALE` — `OPEN → STALE` or `VERIFIED →
    STALE` as the case may be — in `created_at` ascending order."
    PRD §3.3: "Verification stamps `verified_by_user_id` with the calling
    investigator's `X-User-ID` and `verified_on` with the current clock date,
    re-stamping both on a re-verification, and recomputes the preliminary
    recoverability score."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_stale_finding
    """
    ctx = _levy_drafted_then_staled_by_its_own_verifier()

    finding = read_finding(ctx["finding"]["id"])
    assert finding["verified_by_user_id"] == "inv-7"
    assert finding["status"] == "STALE"
    assert read_action(ctx["action"]["id"])["status"] == "DRAFT"


def test_segregation_of_duties_is_reported_before_the_stale_finding(api):
    """PRD §2.8: "When several checks would fail on the same request, the response
    is determined by the **first** failing check in the following fixed order.
    This ordering is normative: a request that violates both a
    segregation-of-duties rule and a fiscal floor reports the segregation failure,
    never the floor."
    PRD §2.8: "The writ requester's `X-User-ID` differs from the linked finding's
    `verified_by_user_id` — otherwise `ERR_SEGREGATION_OF_DUTIES` and HTTP 403, on
    writ request."
    PRD §2.8: "The linked asset finding has not been staled since drafting —
    otherwise `ERR_FINDING_STALE` and HTTP 409, on writ request."
    PRD §2.9: "Note that these are identity comparisons, not role comparisons: the
    same human operating under two roles is still the same `X-User-ID` and is
    still blocked."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_stale_finding
    """
    ctx = _levy_drafted_then_staled_by_its_own_verifier()

    resp = api.request_writ(
        ctx["action"]["id"], make_enforcement_officer_headers("inv-7")
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    assert read_action(ctx["action"]["id"])["status"] == "DRAFT"


# ==========================================================================
# Corner coverage
# ==========================================================================
def test_ruling_an_already_overruled_claim_is_an_invalid_transition(api):
    """PRD §3.6: "All three of `SUSTAINED`, `OVERRULED` and `DEFAULTED` are
    terminal."
    PRD §3.6: "An outcome of `OVERRULED` moves the claim `OPPOSED → OVERRULED` and
    changes nothing outside the claim row. The linked enforcement action keeps its
    status, keeps its `levy_hold_cents`, and the finding's custody split between
    `available_cents`, `frozen_cents` and `swept_cents` is untouched."
    PRD §2.8: "The target resource sits in one of the states from which the
    requested transition is legal — otherwise `ERR_INVALID_STATE` and HTTP 409.
    This applies to every state-transition endpoint."

    Design: Corner/state_machines/ruling_an_already_overruled_claim_rejected_as_invalid_state
    """
    ctx = setup_opposed_exemption_claim(
        claim_type="WAGE_CAP",
        claimed_amount_cents=100_000,
        opposing_officer_user_id="eo-2",
        finding_value_cents=900_000,
        court_case_number="CV-2026-2005",
        filing_overrides={"fee_cents": 0},
    )

    first = validate_success(
        api.rule_exemption_claim(ctx["claim"]["id"], "OVERRULED", CO)
    )
    assert first["status"] == "OVERRULED"
    assert first["ruled_by_user_id"] == "co-1"

    validate_error(
        api.rule_exemption_claim(
            ctx["claim"]["id"], "SUSTAINED", make_compliance_officer_headers("co-2")
        ),
        ApiErrorId.ERR_INVALID_STATE.value,
        409,
    )

    claim = read_claim(ctx["claim"]["id"])
    assert claim["status"] == "OVERRULED"
    assert claim["ruled_by_user_id"] == "co-1"

    action = read_action(ctx["action"]["id"])
    assert action["status"] == "SERVED"
    assert action["levy_hold_cents"] == 725_000

    finding = read_finding(ctx["finding"]["id"])
    assert finding["frozen_cents"] == 725_000
    assert finding["status"] == "VERIFIED"
    assert read_judgment(ctx["judgment"]["id"])["enforcement_posture"] == "ENFORCING"


def test_an_unopposed_claim_defaults_on_the_sweep_and_quashes_the_levy(api):
    """PRD §2.5: "**Step 2 — unopposed exemption claims.** Every exemption claim
    still in `FILED` whose `opposition_deadline_on` falls strictly before the new
    clock date becomes `DEFAULTED`, cascading as described in Section 3.6."
    PRD §3.6: "**An unopposed claim is granted by default, with the same
    consequences as one that is sustained.**"
    PRD §3.6: "The default branch travels the same cascade as `SUSTAINED`: when
    the sweep moves a claim `FILED → DEFAULTED`, the linked action moves `SERVED →
    QUASHED`, the quash returns the hold to `available_cents`, a
    `HEAD_OF_HOUSEHOLD` or `HOMESTEAD` claim exhausts the finding,
    `active_enforcement_count` falls by one, and the posture steps back to
    `LIEN_PERFECTED` when the count reaches 0."

    Design: Corner/state_machines/clock_sweep_defaults_unopposed_exemption_claim_and_quashes_levy
    """
    ctx = setup_filed_exemption_claim(
        claim_type="SOCIAL_SECURITY",
        claimed_amount_cents=725_000,
        finding_value_cents=900_000,
        court_case_number="CV-2026-2007",
        filing_overrides={"fee_cents": 0},
    )
    assert ctx["claim"]["opposition_deadline_on"] == "2026-08-11"

    summary = advance_clock("2026-08-12T00:00:00Z", CO)
    assert_sweep_summary_shape(summary)
    assert summary["defaulted_claim_count"] == 1
    assert summary["expired_judgment_count"] == 0

    assert read_claim(ctx["claim"]["id"])["status"] == "DEFAULTED"

    action = read_action(ctx["action"]["id"])
    assert action["status"] == "QUASHED"
    assert action["levy_hold_cents"] == 0

    finding = read_finding(ctx["finding"]["id"])
    assert finding["frozen_cents"] == 0
    assert finding["available_cents"] == 900_000
    assert finding["status"] == "VERIFIED"
    assert_custody_conservation(finding)


def test_the_opposing_officer_may_not_rule_on_their_own_opposition(api):
    """PRD §2.9: "Likewise the `EnforcementOfficer` whose identifier sits in an
    exemption claim's `opposed_by_user_id` may not be the `ComplianceOfficer` who
    rules on that claim; an equal comparison there draws the same refusal."
    PRD §2.8: "The ruling officer's `X-User-ID` differs from the claim's
    `opposed_by_user_id` — otherwise `ERR_SEGREGATION_OF_DUTIES` and HTTP 403, on
    ruling an exemption claim."

    Design: Corner/rbac/opposing_officer_cannot_rule_on_the_claim_they_opposed
    """
    ctx = setup_opposed_exemption_claim(
        claim_type="HOMESTEAD",
        claimed_amount_cents=500_000,
        opposing_officer_user_id="dual-1",
        finding_value_cents=900_000,
        court_case_number="CV-2026-7003",
        interest_rate_bps=0,
        filing_costs_cents=0,
        filing_overrides={"fee_cents": 0},
    )
    assert ctx["claim"]["opposed_by_user_id"] == "dual-1"

    validate_error(
        api.rule_exemption_claim(
            ctx["claim"]["id"], "SUSTAINED", make_compliance_officer_headers("dual-1")
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )

    ruled = validate_success(
        api.rule_exemption_claim(
            ctx["claim"]["id"], "SUSTAINED", make_compliance_officer_headers("co-9")
        )
    )
    assert ruled["status"] == "SUSTAINED"
    assert ruled["ruled_by_user_id"] == "co-9"
    assert read_action(ctx["action"]["id"])["status"] == "QUASHED"
    assert read_finding(ctx["finding"]["id"])["status"] == "EXHAUSTED"
    assert read_finding(ctx["finding"]["id"])["available_cents"] == 900_000


def test_an_enforcement_officer_may_not_rule_on_an_exemption_claim(api):
    """PRD §2.1: "Once the caller is authenticated, the service checks the role
    against the endpoint's authorized list from Section 4; a role that does not
    appear there is turned away with `ERR_ROLE_NOT_PERMITTED` and HTTP 403."
    PRD §3.6: "An opposed claim goes to a `ComplianceOfficer`, who supplies an
    `outcome` of either `SUSTAINED` or `OVERRULED`."

    Design: Corner/rbac/enforcement_officer_cannot_rule_on_an_exemption_claim
    """
    ctx = setup_opposed_exemption_claim(
        claim_type="WAGE_CAP",
        claimed_amount_cents=100_000,
        opposing_officer_user_id="eo-2",
        finding_value_cents=900_000,
        court_case_number="CV-2026-7002",
        interest_rate_bps=0,
        filing_costs_cents=0,
        filing_overrides={"fee_cents": 0},
    )

    validate_error(
        api.rule_exemption_claim(
            ctx["claim"]["id"], "SUSTAINED", make_enforcement_officer_headers("eo-3")
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )
    assert read_claim(ctx["claim"]["id"])["status"] == "OPPOSED"
    assert read_action(ctx["action"]["id"])["status"] == "SERVED"


def test_a_debtor_cannot_file_against_another_debtors_levy(api):
    """PRD §2.1: "The governing judgment is found by following the target
    resource's own foreign-key chain — an exemption claim reaches its enforcement
    action through `enforcement_action_id` and that action reaches the judgment
    through `judgment_id`; a settlement offer, a payment, and an enforcement action
    each carry `judgment_id` directly; a judgment is its own governing judgment."
    PRD §2.1: "A mismatch anywhere along that chain is `ERR_NOT_RESOURCE_OWNER`
    with HTTP 403."

    Design: Corner/rbac/debtor_cannot_file_an_exemption_claim_on_another_debtors_levy
    """
    ctx = setup_served_bank_levy(
        finding_value_cents=900_000,
        court_case_number="CV-2026-7005",
        interest_rate_bps=0,
        filing_costs_cents=0,
        filing_overrides={"fee_cents": 0},
    )
    from test_helpers import create_debtor

    other_debtor = create_debtor(full_name="Jules Okafor")

    validate_error(
        api.create_exemption_claim(
            create_exemption_claim_payload(
                ctx["action"]["id"], claimed_amount_cents=200_000
            ),
            make_debtor_headers(other_debtor["id"]),
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
        403,
    )

    own_claim = file_exemption_claim(
        ctx["action"]["id"], ctx["debtor"]["id"], claimed_amount_cents=200_000
    )
    assert own_claim["status"] == "FILED"

    _rows, meta = validate_paginated(
        api.list_exemption_claims(
            CM, {"enforcement_action_id": ctx["action"]["id"]}
        )
    )
    assert meta["total_count"] == 1
