"""State machines that are not a straight line: two seller dimensions moving on
different triggers, a bounded revision loop, and the one edge that reopens an
action which already looked resolved.
"""

from test_helpers import (
    INVESTIGATOR,
    OFFICER,
    REVIEWER,
    ApiErrorId,
    assert_instant_equals,
    assert_points,
    assert_posture,
    create_listing,
    denied_appeal,
    escalate,
    file_violation,
    issue_action,
    notices_for,
    open_investigation,
    publish_rule,
    read_action,
    read_holds,
    read_listings,
    read_notices,
    read_seller,
    register_seller,
    set_clock,
    submit_poa,
    substantiated_violation,
    validate_error,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00.000Z"


def _seller_with_two_reported_violations(api):
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="SP-IND-1", category="SHIPPING_PERFORMANCE", base_severity_weight=1.50,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = register_seller(
        api, legal_name="Fernwood Outfitters LLC", email="ops@fernwood-outfitters.example",
        tax_id_hash="TAX-FE-0001", payout_bank_token="BANK-FE-0001",
        address_fingerprint="ADDR-FE-0001",
    )
    first = file_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER", evidence_reference="EV-FE-0001"
    )
    second = file_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER", evidence_reference="EV-FE-0002"
    )
    return seller, first, second


def test_opening_an_investigation_moves_the_funds_dimension_alone(api):
    """PRD §2.5: "The two are coupled in exactly one direction: the enforcement
    dimension feeds the funds dimension, never the reverse."

    Design: Difficulty/non_linear_state_machine/seller_enforcement_and_disbursement_dimensions_evolve_independently
    """
    seller, first, _ = _seller_with_two_reported_violations(api)

    open_investigation(api, first["id"])

    after_open = read_seller(api, seller["id"])
    assert_posture(after_open, enforcement_state="ACTIVE", disbursement_state="RESERVE_HELD",
                   severity_points_balance="0.00")

    validate_success(
        api.adjudicate_violation(
            first["id"],
            {"outcome": "SUBSTANTIATED",
             "decision_note": "Carrier scans confirm the shipments left the facility "
                              "eight days late."},
            INVESTIGATOR,
        )
    )

    after_adjudicate = read_seller(api, seller["id"])
    assert_posture(after_adjudicate, enforcement_state="ACTIVE", disbursement_state="NORMAL")


def test_watchlist_pins_the_funds_dimension_after_the_last_investigation_closes(api):
    """PRD §3.9: "Otherwise, if `enforcement_state` is `WATCHLIST` or `RESTRICTED`,
    **or** any violation of that seller sits in `UNDER_INVESTIGATION`, the target
    is `RESERVE_HELD`."

    Design: Difficulty/non_linear_state_machine/seller_enforcement_and_disbursement_dimensions_evolve_independently
    """
    seller, first, second = _seller_with_two_reported_violations(api)
    open_investigation(api, first["id"])
    validate_success(
        api.adjudicate_violation(first["id"], {"outcome": "SUBSTANTIATED"}, INVESTIGATOR)
    )

    action = issue_action(api, first["id"])
    open_investigation(api, second["id"])
    dismissed = validate_success(
        api.adjudicate_violation(
            second["id"],
            {"outcome": "DISMISSED",
             "decision_note": "Second report duplicates the first window and is withdrawn."},
            INVESTIGATOR,
        )
    )

    assert_points(action["severity_points_applied"], "1.50")
    assert action["ladder_rung_computed"] == "WARNING"
    # 0.00 < 1.50 < 4.00 puts the enforcement dimension on the watchlist, which
    # keeps the funds dimension in reserve even though no investigation is open.
    assert_posture(read_seller(api, seller["id"]), enforcement_state="WATCHLIST",
                   disbursement_state="RESERVE_HELD", severity_points_balance="1.50")
    assert validate_success(api.get_violation(first["id"], INVESTIGATOR))["state"] == \
        "SUBSTANTIATED"
    assert dismissed["state"] == "DISMISSED"
    # No disbursement event ever touched the action.
    assert read_action(api, action["id"])["state"] == "ISSUED"


ROOT_CAUSE_ONE = (
    "Our listing team copied specification data from a supplier sheet that had not "
    "been revalidated since 2024."
)
ROOT_CAUSE_TWO = (
    "The 2024 supplier sheet stayed in circulation because no owner was assigned to "
    "retire superseded specification files."
)
ROOT_CAUSE_THREE = (
    "No owner was assigned to retire superseded specification files and no control "
    "detected the drift between listing and supplier data."
)


def _plan_at_the_revision_limit(api):
    """Two RETURN cycles leave a third plan SUBMITTED with revision_count 2."""
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="LA-POA-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=True,
    )
    seller = register_seller(
        api, legal_name="Glenmark Supply LLC", email="ops@glenmark-supply.example",
        tax_id_hash="TAX-GL-0001", payout_bank_token="BANK-GL-0001",
        address_fingerprint="ADDR-GL-0001",
    )
    violation = substantiated_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER", evidence_reference="EV-GL-0001"
    )
    action = issue_action(api, violation["id"])

    first = submit_poa(
        api, action["id"], seller["id"], root_cause=ROOT_CAUSE_ONE,
        corrective_measures=[
            "Corrected the 14 affected listings against the current supplier "
            "specification sheet."],
        preventive_measures=[
            "Added a second-reviewer sign-off before any specification field is published."],
    )
    validate_success(
        api.review_plan_of_action(
            first["id"],
            {"decision": "RETURN",
             "review_notes": "Root cause does not explain why the 2024 sheet stayed in "
                             "circulation."},
            OFFICER,
        )
    )
    second = submit_poa(
        api, action["id"], seller["id"], root_cause=ROOT_CAUSE_TWO,
        corrective_measures=[
            "Corrected the 14 affected listings and retired the 2024 specification sheet."],
        preventive_measures=[
            "Assigned a named owner for specification file retirement with a monthly audit."],
    )
    validate_success(
        api.review_plan_of_action(
            second["id"],
            {"decision": "RETURN",
             "review_notes": "Preventive measures need a detection control, not only an "
                             "ownership assignment."},
            OFFICER,
        )
    )
    third = submit_poa(
        api, action["id"], seller["id"], root_cause=ROOT_CAUSE_THREE,
        corrective_measures=[
            "Corrected the 14 affected listings and retired the 2024 specification sheet."],
        preventive_measures=[
            "Assigned a named owner for specification retirement.",
            "Added a weekly automated diff between published listing specs and the live "
            "supplier feed."],
    )
    return seller, action, first, second, third


def test_a_third_return_is_refused_once_the_revision_count_reaches_two(api):
    """PRD §3.7: "A return is permitted only while the plan's `revision_count` is
    still below two. Once `revision_count` has reached two, a further return is
    refused with `ERR_POA_REVISION_LIMIT` — the officer must accept or reject
    instead."

    Design: Difficulty/non_linear_state_machine/poa_return_resubmit_cycle_hits_revision_limit
    """
    _, _, first, second, third = _plan_at_the_revision_limit(api)

    response = api.review_plan_of_action(
        third["id"],
        {"decision": "RETURN", "review_notes": "Third return attempt on the same "
                                               "enforcement action."},
        OFFICER,
    )

    validate_error(response, ApiErrorId.POA_REVISION_LIMIT.value)
    assert validate_success(api.get_plan_of_action(first["id"], OFFICER))["revision_count"] == 0
    assert validate_success(api.get_plan_of_action(first["id"], OFFICER))["state"] == "SUPERSEDED"
    assert validate_success(api.get_plan_of_action(second["id"], OFFICER))["revision_count"] == 1
    assert validate_success(api.get_plan_of_action(second["id"], OFFICER))["state"] == "SUPERSEDED"
    # The counter lives on the successor row rather than on a recount of live rows.
    assert validate_success(api.get_plan_of_action(third["id"], OFFICER))["revision_count"] == 2


def test_the_revision_bound_blocks_only_the_return_edge(api):
    """PRD §3.7: "`ACCEPT` moves the plan `SUBMITTED → ACCEPTED`."

    Design: Difficulty/non_linear_state_machine/poa_return_resubmit_cycle_hits_revision_limit
    """
    _, _, _, _, third = _plan_at_the_revision_limit(api)

    accepted = validate_success(
        api.review_plan_of_action(
            third["id"],
            {"decision": "ACCEPT",
             "review_notes": "Detection control satisfies the requirement."},
            OFFICER,
        ),
        200,
    )

    assert accepted["state"] == "ACCEPTED"
    assert accepted["reviewed_by_user_id"] == "co-1"
    # issued_at plus seventeen days.
    assert_instant_equals(accepted["deadline_at"], "2026-08-18T00:00:00.000Z", "deadline_at")


def _escalated_suspension(api):
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="LA-ESC-1", category="LISTING_ACCURACY", base_severity_weight=3.20,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = register_seller(
        api, legal_name="Harborline Goods LLC", email="ops@harborline-goods.example",
        tax_id_hash="TAX-HA-0001", payout_bank_token="BANK-HA-0001",
        address_fingerprint="ADDR-HA-0001",
    )
    listing = create_listing(
        api, seller["id"], sku="SKU-HA-1", title="Brass Deck Cleat", category_code="MARINE"
    )
    violation = substantiated_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER", evidence_reference="EV-HA-0001"
    )
    action = issue_action(api, violation["id"], action_type_override="ACCOUNT_SUSPENSION")
    appeal = denied_appeal(
        api, action["id"], seller["id"],
        grounds="The cited listing was corrected before the report was filed and the "
                "suspension is disproportionate.",
        denial_reason="EVIDENCE_UPHELD",
        reviewer=REVIEWER, decider=REVIEWER,
    )
    escalate(
        api, appeal["id"], seller["id"],
        escalation_grounds="The archived snapshot was taken from a cached page; the "
                           "corrected version was live two days earlier.",
    )
    return seller, listing, action, appeal


def test_an_escalation_grant_reopens_an_upheld_action(api):
    """PRD §3.8: "A `GRANTED_ON_ESCALATION` outcome is the only path in the entire
    service that reopens an action which already looked resolved: the action moves
    `UPHELD → VACATED` with `resolution_reason` `ESCALATION_GRANTED`,
    `reinstatement_granted` becomes true exactly when the vacated `action_type` was
    `ACCOUNT_SUSPENSION`, and the identical reinstatement cascade described above
    runs in full — balance, then enforcement posture, then funds posture, then
    holds, then listings — with `reinstated_count` incrementing when the vacated
    action was a suspension."

    Design: Difficulty/non_linear_state_machine/appeal_denied_then_escalation_grant_reopens_upheld_action
    """
    _, _, action, appeal = _escalated_suspension(api)

    decided = validate_success(
        api.decide_escalation(
            appeal["id"],
            {"outcome": "GRANTED_ON_ESCALATION",
             "rationale": "Origin server logs confirm the corrected specification was "
                          "live before the report date."},
            OFFICER,
        ),
        200,
    )

    assert decided["state"] == "GRANTED_ON_ESCALATION"
    assert_instant_equals(decided["escalation_deadline_at"], "2026-08-15T00:00:00.000Z",
                          "escalation_deadline_at")
    assert decided["decided_by_user_id"] == "ar-1"
    assert decided["escalation_decided_by_user_id"] == "co-1"
    assert decided["reinstatement_granted"] is True

    reopened = read_action(api, action["id"])
    assert reopened["state"] == "VACATED"
    # ESCALATION_GRANTED, not the first-level APPEAL_GRANTED.
    assert reopened["resolution_reason"] == "ESCALATION_GRANTED"
    assert reopened["override_applied"] is True
    assert reopened["ladder_rung_computed"] == "WARNING"


def test_the_escalation_grant_replays_the_whole_reinstatement_cascade(api):
    """PRD §3.8: "Every one of the seller's holds still in `ACTIVE` is released
    with `release_reason` `APPEAL_GRANTED`, returning their cents from
    `held_balance_cents` to `available_balance_cents`, and every listing carrying
    `suppressed_by_suspension` true returns to `ACTIVE` with the flag cleared while
    listings in `REMOVED` stay removed."

    Design: Difficulty/non_linear_state_machine/appeal_denied_then_escalation_grant_reopens_upheld_action
    """
    seller, listing, _, appeal = _escalated_suspension(api)

    validate_success(
        api.decide_escalation(
            appeal["id"],
            {"outcome": "GRANTED_ON_ESCALATION",
             "rationale": "Origin server logs confirm the corrected specification was "
                          "live before the report date."},
            OFFICER,
        ),
        200,
    )

    stored = read_seller(api, seller["id"])
    assert_posture(stored, enforcement_state="ACTIVE", disbursement_state="NORMAL",
                   severity_points_balance="0.00")
    assert stored["reinstated_count"] == 1

    rows = {row["id"]: row for row in read_listings(api, seller["id"])}
    assert rows[listing["id"]]["state"] == "ACTIVE"
    assert rows[listing["id"]]["suppressed_by_suspension"] is False

    sweeping = [h for h in read_holds(api, params={"seller_id": seller["id"]})
                if h["hold_type"] == "FULL_HOLD"]
    assert len(sweeping) == 1
    assert sweeping[0]["state"] == "RELEASED"
    assert sweeping[0]["release_reason"] == "APPEAL_GRANTED"

    notices = read_notices(api, seller["id"])
    assert notices_for(notices, "ESCALATION_DECISION")
    assert notices_for(notices, "FUNDS_RELEASED")
