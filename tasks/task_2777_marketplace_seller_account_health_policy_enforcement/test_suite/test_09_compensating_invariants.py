"""Two conserved quantities and the operations that must restore them exactly:
a granted appeal that returns the severity balance and every downstream posture to
where they started, and a forfeiture that debits the seller without ever breaking
the funds identity.
"""

from test_helpers import (
    OFFICER,
    OFFICER_ALT,
    REVIEWER,
    ApiErrorId,
    assert_cents,
    assert_funds,
    assert_points,
    assert_posture,
    create_listing,
    credit,
    decide_escalation,
    denied_appeal,
    escalate,
    file_appeal,
    issue_action,
    notices_for,
    publish_rule,
    read_action,
    read_holds,
    read_listings,
    read_notices,
    read_seller,
    register_seller,
    set_clock,
    start_review,
    substantiated_violation,
    validate_error,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00.000Z"

GRANT_GROUNDS = (
    "The roast-date mismatch was a printing error on our label, corrected the same "
    "day and disclosed to every buyer."
)
GRANT_RATIONALE = (
    "Label printing error is documented and every affected buyer was notified "
    "within 24 hours."
)


# --------------------------------------------------------------------------
# The severity balance and the posture pair derived from it
# --------------------------------------------------------------------------
def _suspended_seller_with_an_appeal_under_review(api):
    """One 3.20-point action overridden up to a suspension, so the pre-enforcement
    reading of every conserved quantity is known exactly: balance 0.00, ACTIVE,
    NORMAL, available 500000, held 0, reinstated_count 0."""
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="LA-COMP-1", category="LISTING_ACCURACY", base_severity_weight=3.20,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = register_seller(
        api, legal_name="Coppermill Coffee LLC", email="ops@coppermill-coffee.example",
        tax_id_hash="TAX-CO-0001", payout_bank_token="BANK-CO-0001",
        address_fingerprint="ADDR-CO-0001",
    )
    credit(api, seller["id"], 500000, "PAYOUT-CYCLE-2026-07-G")
    listing = create_listing(
        api, seller["id"], sku="SKU-CO-1", title="Single Origin Whole Bean 1kg",
        category_code="GROCERY",
    )
    violation = substantiated_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER",
        evidence_reference="EV-CO-0001",
        decision_note="Roast date on the listing did not match the shipped lot.",
    )
    action = issue_action(api, violation["id"], action_type_override="ACCOUNT_SUSPENSION")
    appeal = file_appeal(api, action["id"], seller["id"], grounds=GRANT_GROUNDS)
    start_review(api, appeal["id"], REVIEWER)
    return seller, listing, action, appeal


def _grant(api, appeal_id):
    return validate_success(
        api.decide_appeal(
            appeal_id, {"outcome": "GRANTED", "rationale": GRANT_RATIONALE}, REVIEWER
        ),
        200,
    )


def test_the_grant_returns_the_severity_balance_to_exactly_zero(api):
    """PRD §3.6: "`severity_points_balance` on the seller is never incremented in
    place; it is recomputed from scratch over the seller's actions in `ISSUED`,
    `ACKNOWLEDGED`, or `UPHELD`, and a vacated action simply leaves that set, which
    is what makes reinstatement genuinely compensating."

    Design: Difficulty/compensating_invariant/appeal_grant_restores_severity_balance_and_posture_exactly
    """
    seller, _, action, appeal = _suspended_seller_with_an_appeal_under_review(api)
    before = read_seller(api, seller["id"])
    assert_posture(before, enforcement_state="SUSPENDED", disbursement_state="FULL_HOLD",
                   severity_points_balance="3.20")
    assert_funds(before, available=0, held=500000, credited=500000, debited=0)
    assert before["reinstated_count"] == 0

    decided = _grant(api, appeal["id"])

    assert decided["state"] == "GRANTED"
    assert decided["reinstatement_granted"] is True
    assert decided["decided_by_user_id"] == "ar-1"

    vacated = read_action(api, action["id"])
    assert vacated["state"] == "VACATED"
    assert vacated["resolution_reason"] == "APPEAL_GRANTED"
    # The action's own history is not rewritten; it simply leaves the input set.
    assert_points(vacated["severity_points_applied"], "3.20", "severity_points_applied")

    after = read_seller(api, seller["id"])
    # Restored exactly, not merely reduced.
    assert_posture(after, enforcement_state="ACTIVE", disbursement_state="NORMAL",
                   severity_points_balance="0.00")
    # The one permitted residue is a monotone audit counter, not a state.
    assert after["reinstated_count"] == 1


def test_the_grant_unwinds_the_listing_the_hold_and_the_balances(api):
    """PRD §3.9: "Conversely, when a reinstatement takes the seller out of
    `SUSPENDED` and the funds posture leaves `FULL_HOLD` for `RESERVE_HELD` or
    `NORMAL`, every `ACTIVE` hold — the sweeping row included — is released with
    `release_reason` `APPEAL_GRANTED` and a `FUNDS_RELEASED` notice discloses the
    released total."

    Design: Difficulty/compensating_invariant/appeal_grant_restores_severity_balance_and_posture_exactly
    """
    seller, listing, _, appeal = _suspended_seller_with_an_appeal_under_review(api)
    sweeping = read_holds(api, params={"seller_id": seller["id"], "state": "ACTIVE"})
    assert len(sweeping) == 1, f"expected one sweeping hold, got {sweeping}"
    assert sweeping[0]["hold_type"] == "FULL_HOLD"
    assert_cents(sweeping[0]["held_amount_cents"], 500000, "held_amount_cents")

    _grant(api, appeal["id"])

    released = validate_success(api.get_hold(sweeping[0]["id"], OFFICER))
    assert released["state"] == "RELEASED"
    assert released["release_reason"] == "APPEAL_GRANTED"

    rows = {row["id"]: row for row in read_listings(api, seller["id"])}
    assert rows[listing["id"]]["state"] == "ACTIVE"
    assert rows[listing["id"]]["suppressed_by_suspension"] is False

    after = read_seller(api, seller["id"])
    # A grant never debits, so the identity closes on the figures it started from.
    assert_funds(after, available=500000, held=0, credited=500000, debited=0)

    notices = read_notices(api, seller["id"])
    assert notices_for(notices, "APPEAL_DECISION")
    assert notices_for(notices, "FUNDS_RELEASED")


# --------------------------------------------------------------------------
# The funds identity across the only debiting operation in the domain
# --------------------------------------------------------------------------
def _banned_seller_with_the_sweeping_hold_still_active(api):
    """An exhausted escalation against a suspension bans the seller and, by design,
    leaves the 500000-cent sweeping row in ACTIVE so its cents stay forfeitable."""
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="RP-FOR-1", category="RESTRICTED_PRODUCT", base_severity_weight=3.20,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = register_seller(
        api, legal_name="Dunmore Vapor LLC", email="ops@dunmore-vapor.example",
        tax_id_hash="TAX-DU-0001", payout_bank_token="BANK-DU-0001",
        address_fingerprint="ADDR-DU-0001",
    )
    credit(api, seller["id"], 500000, "PAYOUT-CYCLE-2026-07-H")
    violation = substantiated_violation(
        api, seller["id"], rule["id"], reporter_type="REGULATOR",
        evidence_reference="EV-DU-0001",
        decision_note="Nicotine concentration above the permitted limit for this "
                      "marketplace.",
    )
    action = issue_action(api, violation["id"], action_type_override="ACCOUNT_SUSPENSION")
    appeal = denied_appeal(
        api, action["id"], seller["id"], denial_reason="RESTRICTED_PRODUCT_RISK",
        reviewer=REVIEWER, decider=REVIEWER,
        grounds="The tested unit came from a batch we withdrew before the report and "
                "never listed for sale.",
    )
    escalate(
        api, appeal["id"], seller["id"],
        escalation_grounds="Purchase logs show no orders were accepted for that batch "
                           "after the withdrawal.",
    )
    appeal = decide_escalation(
        api, appeal["id"], "FINAL_DENIED", "RESTRICTED_PRODUCT_RISK",
        rationale="Two orders were fulfilled from the withdrawn batch after the stated "
                  "withdrawal date.",
        headers=OFFICER,
    )
    active = read_holds(api, params={"seller_id": seller["id"], "state": "ACTIVE"})
    assert len(active) == 1, f"expected the sweeping row to survive the ban, got {active}"
    return seller, action, appeal, active[0]


def test_forfeiture_debits_only_the_forfeited_part_and_returns_the_residue(api):
    """PRD §3.9: "The seller's `held_balance_cents` falls by the hold's whole
    `held_amount_cents`, `lifetime_debited_cents` rises by `forfeited_amount_cents`,
    and the residue — the hold's `held_amount_cents` less the forfeited figure —
    returns to `available_balance_cents`, so that available plus held still equals
    lifetime credited less lifetime debited."

    Design: Difficulty/compensating_invariant/forfeit_debits_exactly_and_returns_residue_preserving_funds_identity
    """
    seller, _, appeal, sweeping = _banned_seller_with_the_sweeping_hold_still_active(api)
    assert sweeping["hold_type"] == "FULL_HOLD"
    assert_cents(sweeping["held_amount_cents"], 500000, "held_amount_cents")
    assert appeal["state"] == "FINAL_DENIED"
    before = read_seller(api, seller["id"])
    assert_posture(before, enforcement_state="BANNED", disbursement_state="FULL_HOLD")
    assert before["ban_reason"] == "ESCALATION_EXHAUSTED"

    forfeited = validate_success(
        api.forfeit_hold(sweeping["id"], {"forfeited_amount_cents": 300000}, OFFICER_ALT),
        200,
    )

    assert forfeited["state"] == "FORFEITED"
    assert_cents(forfeited["forfeited_amount_cents"], 300000, "forfeited_amount_cents")

    after = read_seller(api, seller["id"])
    # The whole hold leaves held, only 300000 is debited, and 200000 comes back.
    assert_funds(after, available=200000, held=0, credited=500000, debited=300000)


def test_the_replay_of_a_forfeiture_cannot_debit_the_seller_twice(api):
    """PRD §3.9: "A hold in `RELEASED` or `FORFEITED` is terminal and carries
    `forfeited_amount_cents` of zero unless forfeiture was what put it there."

    Design: Difficulty/compensating_invariant/forfeit_debits_exactly_and_returns_residue_preserving_funds_identity
    """
    seller, _, _, sweeping = _banned_seller_with_the_sweeping_hold_still_active(api)
    validate_success(
        api.forfeit_hold(sweeping["id"], {"forfeited_amount_cents": 300000}, OFFICER_ALT),
        200,
    )

    replay = api.forfeit_hold(
        sweeping["id"], {"forfeited_amount_cents": 100000}, OFFICER_ALT
    )

    validate_error(replay, ApiErrorId.INVALID_STATE.value)
    assert_cents(
        validate_success(api.get_hold(sweeping["id"], OFFICER))["forfeited_amount_cents"],
        300000, "forfeited_amount_cents",
    )
    after = read_seller(api, seller["id"])
    assert_funds(after, available=200000, held=0, credited=500000, debited=300000)
    # Forfeiting money never relaxes the posture: the coupling runs one way only.
    assert_posture(after, enforcement_state="BANNED", disbursement_state="FULL_HOLD")
