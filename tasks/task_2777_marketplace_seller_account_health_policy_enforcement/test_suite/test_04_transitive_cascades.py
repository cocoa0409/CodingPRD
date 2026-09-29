"""Cascades that walk three or more entities away from the request's own subject:
a suspension that rewrites listings, posture, holds and balances; a confirmed
related-account link that bans and sweeps a second seller; and a read-shaped
evaluation that mints a violation whose posture then prices a reserve.
"""

from test_helpers import (
    INVESTIGATOR,
    OFFICER,
    REVIEWER,
    assert_cents,
    assert_funds,
    assert_instant_equals,
    assert_notice,
    assert_points,
    assert_posture,
    create_listing,
    credit,
    decide_escalation,
    denied_appeal,
    escalate,
    evaluate,
    file_snapshot,
    file_violation,
    find_notice,
    issue_action,
    notices_for,
    open_hold,
    open_investigation,
    publish_rule,
    read_holds,
    read_listings,
    read_notices,
    read_seller,
    register_seller,
    set_clock,
    substantiated_violation,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00.000Z"


# --------------------------------------------------------------------------
# A suspension cascade
# --------------------------------------------------------------------------
def _seller_primed_for_suspension(api):
    """Two ACTIVE listings, one open investigation, one ROLLING reserve hold of
    50000 cents against 500000 credited, and a second substantiated violation
    that has not yet been enforced."""
    set_clock(api, CLOCK)
    rule_gate = publish_rule(
        api, code="LA-GATE-1", category="LISTING_ACCURACY", base_severity_weight=1.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    rule_sus = publish_rule(
        api, code="RM-SUS-1", category="REVIEW_MANIPULATION", base_severity_weight=3.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = register_seller(
        api, legal_name="Ironhill Tools LLC", email="ops@ironhill-tools.example",
        tax_id_hash="TAX-IR-0001", payout_bank_token="BANK-IR-0001",
        address_fingerprint="ADDR-IR-0001",
    )
    first_listing = create_listing(
        api, seller["id"], sku="SKU-IR-1", title="Forged Bench Vise", category_code="TOOLS"
    )
    second_listing = create_listing(
        api, seller["id"], sku="SKU-IR-2", title="Cast Anvil 40kg", category_code="TOOLS"
    )
    credit(api, seller["id"], 500000, "PAYOUT-CYCLE-2026-07")

    open_violation = file_violation(
        api, seller["id"], rule_gate["id"], reporter_type="BUYER",
        evidence_reference="EV-IR-0001",
    )
    open_investigation(api, open_violation["id"])
    reserve = open_hold(
        api, seller["id"], CLOCK, "2026-08-31T00:00:00.000Z", reserve_basis="ROLLING"
    )

    enforceable = substantiated_violation(
        api, seller["id"], rule_sus["id"], reporter_type="PLATFORM_AUTOMATION",
        evidence_reference="EV-IR-0002",
        decision_note="Purchased-review broker invoices recovered from the seller's own uploads.",
    )
    return seller, first_listing, second_listing, reserve, open_violation, enforceable


def test_suspension_suppresses_the_listings_and_sweeps_the_funds_dimension(api):
    """PRD §3.6: "A rung of `ACCOUNT_SUSPENSION` runs the full suspension
    cascade: every listing of the seller in `ACTIVE` moves to `SUPPRESSED` with
    `suppressed_by_suspension` true; the funds dimension then moves to
    `FULL_HOLD`, which first releases every one of the seller's `ACTIVE` holds
    with `release_reason` `SUPERSEDED_BY_FULL_HOLD` and then mints a single
    sweeping hold as described in §3.9; and a `FUNDS_HELD` notice discloses the
    swept amount."

    Design: Difficulty/transitive_cascade/suspension_cascade_walks_listings_posture_holds_and_balances
    """
    seller, first_listing, second_listing, reserve, _, enforceable = \
        _seller_primed_for_suspension(api)
    assert_cents(reserve["held_amount_cents"], 50000, "held_amount_cents")
    assert reserve["risk_tier"] == "TIER_1"

    action = issue_action(api, enforceable["id"], action_type_override="ACCOUNT_SUSPENSION")
    assert action["action_type"] == "ACCOUNT_SUSPENSION"

    # link 1: the enforcement dimension, on a balance of only 3.00 points.
    after = read_seller(api, seller["id"])
    assert_posture(after, enforcement_state="SUSPENDED", disbursement_state="FULL_HOLD",
                   severity_points_balance="3.00")

    # link 2a: the listings the request never named.
    listings = {row["id"]: row for row in read_listings(api, seller["id"])}
    for listing_id in (first_listing["id"], second_listing["id"]):
        assert listings[listing_id]["state"] == "SUPPRESSED"
        assert listings[listing_id]["suppressed_by_suspension"] is True
    assert action["removed_listing_count"] == 0

    # link 3: the reserve hold the request never named.
    superseded = validate_success(api.get_hold(reserve["id"], OFFICER))
    assert superseded["state"] == "RELEASED"
    assert superseded["release_reason"] == "SUPERSEDED_BY_FULL_HOLD"


def test_the_sweep_holds_the_balance_the_released_reserve_had_just_returned(api):
    """PRD §3.9: "Step two mints a single new hold with `hold_type` `FULL_HOLD`,
    `reserve_basis` `NONE`, `auto_created` true, a freshly snapshotted
    `risk_tier`, a null `created_by_user_id`, a null `enforcement_action_id` — a
    sweep is a consequence of the account's posture and not of one named
    investigation — `coverage_start` at the current clock reading and
    `coverage_end` ninety days later, and `held_amount_cents` equal to
    `available_balance_cents` as it stands **after** step one."

    Design: Difficulty/transitive_cascade/suspension_cascade_walks_listings_posture_holds_and_balances
    """
    seller, _, _, reserve, open_violation, enforceable = _seller_primed_for_suspension(api)

    issue_action(api, enforceable["id"], action_type_override="ACCOUNT_SUSPENSION")

    active = read_holds(api, params={"seller_id": seller["id"], "state": "ACTIVE"})
    assert len(active) == 1, f"exactly one hold should survive the sweep, got {active}"
    sweep = active[0]
    assert sweep["id"] != reserve["id"]
    assert sweep["hold_type"] == "FULL_HOLD"
    assert sweep["reserve_basis"] == "NONE"
    assert sweep["auto_created"] is True
    assert sweep["enforcement_action_id"] is None
    assert sweep["created_by_user_id"] is None
    # The released 50000 was back in available before the sweep priced itself;
    # minting first would have held 450000 and left 50000 disbursable.
    assert_cents(sweep["held_amount_cents"], 500000, "held_amount_cents")
    assert sweep["risk_tier"] == "TIER_3"
    assert_instant_equals(sweep["coverage_start"], CLOCK, "coverage_start")
    assert_instant_equals(sweep["coverage_end"], "2026-10-30T00:00:00.000Z", "coverage_end")

    after = read_seller(api, seller["id"])
    assert_funds(after, available=0, held=500000, credited=500000, debited=0)

    # The cascade never touched the unrelated open investigation.
    assert validate_success(api.get_violation(open_violation["id"], INVESTIGATOR))["state"] == \
        "UNDER_INVESTIGATION"
    swept_amounts = [n["amount_cents"] for n in notices_for(read_notices(api, seller["id"]),
                                                            "FUNDS_HELD")]
    assert 500000 in swept_amounts, f"no FUNDS_HELD notice disclosed the sweep: {swept_amounts}"


# --------------------------------------------------------------------------
# A confirmed related-account link
# --------------------------------------------------------------------------
def _banned_incumbent_and_flagged_candidate(api):
    """S1 is walked to BANNED through an exhausted escalation; S2 then registers
    reusing S1's tax id hash and payout token, is credited, and lists one item."""
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="RP-BAN-1", category="RESTRICTED_PRODUCT", base_severity_weight=3.20,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    incumbent = register_seller(
        api, legal_name="Juniper Wellness LLC", email="ops@juniper-wellness.example",
        tax_id_hash="TAX-JU-0001", payout_bank_token="BANK-JU-0001",
        address_fingerprint="ADDR-JU-0001",
    )
    violation = substantiated_violation(
        api, incumbent["id"], rule["id"], reporter_type="REGULATOR",
        evidence_reference="EV-JU-0001",
        decision_note="Unapproved therapeutic claims on a restricted supplement.",
    )
    action = issue_action(api, violation["id"], action_type_override="ACCOUNT_SUSPENSION")
    appeal = denied_appeal(
        api, action["id"], incumbent["id"], denial_reason="RESTRICTED_PRODUCT_RISK",
        reviewer=REVIEWER, decider=REVIEWER,
        grounds="The supplement is sold under a licence that the investigator did not "
                "review before suspending us.",
        rationale="The licence covers a different formulation than the one listed.",
    )
    escalate(
        api, appeal["id"], incumbent["id"],
        escalation_grounds="The formulation difference is a labelling variant and the "
                           "licence extends to it.",
    )
    decide_escalation(
        api, appeal["id"], "FINAL_DENIED", "RESTRICTED_PRODUCT_RISK",
        rationale="The regulator confirms the listed formulation is outside the licence.",
        headers=OFFICER,
    )

    candidate = register_seller(
        api, legal_name="Kestrel Botanicals LLC", email="ops@kestrel-botanicals.example",
        tax_id_hash="TAX-JU-0001", payout_bank_token="BANK-JU-0001",
        address_fingerprint="ADDR-KE-0002",
    )
    credit(api, candidate["id"], 300000, "PAYOUT-CYCLE-2026-07-B")
    listing = create_listing(
        api, candidate["id"], sku="SKU-KE-1", title="Botanical Sleep Tincture",
        category_code="SUPPLEMENTS",
    )
    links = validate_success(
        api.list_related_account_links(
            OFFICER, {"candidate_seller_id": candidate["id"], "state": "DETECTED"}
        )
    )
    assert len(links) == 1, f"exactly one detected link expected, got {links}"
    return incumbent, candidate, listing, links[0]


def test_confirming_a_link_bans_the_candidate_and_removes_its_listings(api):
    """PRD §3.1: "Confirming the link bans the candidate. `ban_reason` becomes
    `RELATED_ACCOUNT_CONFIRMED`, which pins `enforcement_state` to `BANNED`;
    every listing of the candidate in `ACTIVE` or `SUPPRESSED` moves to
    `REMOVED`; and because the account is now banned, the funds dimension moves
    to `FULL_HOLD` through the release-then-sweep sequence described in §3.9."

    Design: Difficulty/transitive_cascade/related_account_confirmation_bans_and_sweeps_candidate
    """
    incumbent, candidate, listing, link = _banned_incumbent_and_flagged_candidate(api)

    # 0.35 for the tax id plus 0.45 for the bank token; the address and the email
    # domain differ, so nothing else contributes.
    assert_points(link["confidence_score"], "0.80", "confidence_score")
    assert link["matched_seller_state_at_detection"] == "BANNED"
    assert_posture(read_seller(api, incumbent["id"]), enforcement_state="BANNED")
    assert read_seller(api, incumbent["id"])["ban_reason"] == "ESCALATION_EXHAUSTED"

    confirmed = validate_success(
        api.adjudicate_related_account_link(
            link["id"],
            {"decision": "CONFIRMED",
             "adjudication_note": "Identical tax id hash and payout token as the banned "
                                  "Juniper Wellness account."},
            OFFICER,
        )
    )
    assert confirmed["state"] == "CONFIRMED"
    assert confirmed["matched_signals"] == ["TAX_ID", "BANK_TOKEN"]

    after = read_seller(api, candidate["id"])
    assert after["ban_reason"] == "RELATED_ACCOUNT_CONFIRMED"
    assert_posture(after, enforcement_state="BANNED", disbursement_state="FULL_HOLD",
                   severity_points_balance="0.00")
    removed = {row["id"]: row for row in read_listings(api, candidate["id"])}
    assert removed[listing["id"]]["state"] == "REMOVED"


def test_the_ban_sweep_holds_the_whole_available_balance_of_the_candidate(api):
    """PRD §3.9: "When the funds posture is driven to `FULL_HOLD` — by an account
    suspension or by a confirmed related-account ban — three steps run in this
    fixed order, and the order matters because the funds identity of §2.6 must
    hold after each one."

    Design: Difficulty/transitive_cascade/related_account_confirmation_bans_and_sweeps_candidate
    """
    incumbent, candidate, _, link = _banned_incumbent_and_flagged_candidate(api)
    before = read_seller(api, candidate["id"])
    assert before["root_seller_id"] == incumbent["id"]
    assert before["registration_risk_flag"] is True

    validate_success(
        api.adjudicate_related_account_link(
            link["id"], {"decision": "CONFIRMED"}, OFFICER
        )
    )

    active = read_holds(api, params={"seller_id": candidate["id"], "state": "ACTIVE"})
    assert len(active) == 1, f"exactly one sweeping hold expected, got {active}"
    sweep = active[0]
    assert sweep["hold_type"] == "FULL_HOLD"
    assert sweep["reserve_basis"] == "NONE"
    assert sweep["auto_created"] is True
    assert sweep["risk_tier"] == "TIER_3"
    assert_cents(sweep["held_amount_cents"], 300000, "held_amount_cents")

    after = read_seller(api, candidate["id"])
    assert_funds(after, available=0, held=300000, credited=300000, debited=0)
    assert after["root_seller_id"] == incumbent["id"]
    assert after["registration_risk_flag"] is True

    notices = read_notices(api, candidate["id"])
    assert_notice(find_notice(notices, "ACCOUNT_BANNED", link["id"]), "ACCOUNT_BANNED",
                  related_entity_type="RELATED_ACCOUNT_LINK", related_entity_id=link["id"])
    assert_notice(find_notice(notices, "FUNDS_HELD", sweep["id"]), "FUNDS_HELD",
                  related_entity_type="DISBURSEMENT_HOLD", related_entity_id=sweep["id"])


# --------------------------------------------------------------------------
# A read-shaped evaluation that mints a violation
# --------------------------------------------------------------------------
def _seller_with_two_breaching_windows(api):
    """Two shipping-performance rules compete for the automatic citation, and the
    seller's two snapshots put three metrics past their thresholds."""
    set_clock(api, CLOCK)
    publish_rule(
        api, code="SP-LATE-1", category="SHIPPING_PERFORMANCE", base_severity_weight=1.80,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    heavier = publish_rule(
        api, code="SP-LATE-2", category="SHIPPING_PERFORMANCE", base_severity_weight=2.40,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = register_seller(
        api, legal_name="Larkspur Textiles LLC", email="ops@larkspur-textiles.example",
        tax_id_hash="TAX-LA-0001", payout_bank_token="BANK-LA-0001",
        address_fingerprint="ADDR-LA-0001",
    )
    credit(api, seller["id"], 300000, "PAYOUT-CYCLE-2026-07-C")
    file_snapshot(
        api, seller["id"], "2026-06-01T00:00:00.000Z", "2026-07-01T00:00:00.000Z",
        order_volume=1500, delivered_or_refunded_volume=1400, defect_claims_pending=5,
        defect_claims_substantiated=16, late_shipments=56, pre_fulfillment_cancellations=22,
        shipments_total=1450, shipments_with_valid_tracking=1300, source="PLATFORM_PIPELINE",
    )
    file_snapshot(
        api, seller["id"], "2026-07-01T00:00:00.000Z", "2026-08-01T00:00:00.000Z",
        order_volume=1600, delivered_or_refunded_volume=1550, defect_claims_pending=18,
        defect_claims_substantiated=22, late_shipments=80, pre_fulfillment_cancellations=45,
        shipments_total=1580, shipments_with_valid_tracking=1371, source="PLATFORM_PIPELINE",
    )
    return seller, heavier


def test_a_breaching_evaluation_mints_the_platform_violation_and_reserves_the_funds(api):
    """PRD §3.4: "Against that rule the server mints a `Violation` with
    `auto_generated` true, opening directly in state `UNDER_INVESTIGATION` rather
    than in `REPORTED`, with `reporter_type` `PLATFORM_AUTOMATION`, `listing_id`
    null, `policy_rule_id` set to the selected rule, and `evidence_reference`
    formed by prefixing the evaluation's own identifier with the literal text
    `HEALTH-EVAL-`."

    Design: Difficulty/transitive_cascade/breaching_evaluation_mints_violation_then_reserve_posture
    """
    seller, heavier = _seller_with_two_breaching_windows(api)

    evaluation = evaluate(api, seller["id"], INVESTIGATOR)

    assert evaluation["metric_tier"] == "BREACHING"
    assert_points(evaluation["health_score"], "84.23", "health_score")

    # link 1: a violation entity the request never named.
    assert evaluation["auto_violation_id"] is not None
    minted = validate_success(api.get_violation(evaluation["auto_violation_id"], INVESTIGATOR))
    assert minted["state"] == "UNDER_INVESTIGATION"
    assert minted["auto_generated"] is True
    assert minted["reporter_type"] == "PLATFORM_AUTOMATION"
    assert minted["listing_id"] is None
    # base_severity_weight descending selected SP-LATE-2 over SP-LATE-1.
    assert minted["policy_rule_id"] == heavier["id"]
    assert minted["evidence_reference"] == "HEALTH-EVAL-" + evaluation["id"]

    # link 2: the funds dimension moved while the enforcement dimension did not.
    after = read_seller(api, seller["id"])
    assert_posture(after, enforcement_state="ACTIVE", disbursement_state="RESERVE_HELD",
                   severity_points_balance="0.00")
    assert after["metric_tier"] == "BREACHING"
    assert_points(after["health_score"], "84.23", "health_score")
    assert after["open_defect_claim_units"] == 18


def test_only_the_minted_posture_makes_the_claim_exposure_reserve_legal(api):
    """PRD §3.9: "Under `CLAIM_EXPOSURE`, the reserve is the money a wave of open
    defect claims could cost: multiply the seller's `open_defect_claim_units` by
    an assumed exposure of 9000 cents — ninety dollars — per claim, then by the
    tier's exposure multiplier of 1.00 at `TIER_1`, 1.25 at `TIER_2`, or 1.50 at
    `TIER_3`, and round the product half-up to a whole number of cents."

    Design: Difficulty/transitive_cascade/breaching_evaluation_mints_violation_then_reserve_posture
    """
    seller, _ = _seller_with_two_breaching_windows(api)
    evaluation = evaluate(api, seller["id"], INVESTIGATOR)

    hold = open_hold(
        api, seller["id"], CLOCK, "2026-09-01T00:00:00.000Z",
        reserve_basis="CLAIM_EXPOSURE", headers=INVESTIGATOR,
    )

    # link 3: 18 claims x 9000 cents x the TIER_3 multiplier of 1.50.
    assert_cents(hold["held_amount_cents"], 243000, "held_amount_cents")
    # The balance is 0.00 points, so only the BREACHING metric tier reaches TIER_3.
    assert hold["risk_tier"] == "TIER_3"

    after = read_seller(api, seller["id"])
    assert_funds(after, available=57000, held=243000, credited=300000, debited=0)

    notices = read_notices(api, seller["id"])
    assert_notice(find_notice(notices, "HEALTH_BREACH", evaluation["id"]), "HEALTH_BREACH",
                  related_entity_type="HEALTH_EVALUATION", related_entity_id=evaluation["id"])
    assert_notice(find_notice(notices, "FUNDS_HELD", hold["id"]), "FUNDS_HELD",
                  related_entity_type="DISBURSEMENT_HOLD", related_entity_id=hold["id"])
