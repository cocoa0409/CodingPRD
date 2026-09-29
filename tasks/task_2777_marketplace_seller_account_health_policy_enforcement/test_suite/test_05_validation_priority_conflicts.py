"""One request breaking two rules at once, three times over, each time from a
different pair of stages in the §2.8 sequence. In every case the losing rule is
proved to have been live all along by fixing only the winner's cause and
re-issuing a byte-identical request.
"""

from test_helpers import (
    INVESTIGATOR,
    OFFICER,
    REVIEWER,
    ApiErrorId,
    assert_funds,
    assert_instant_equals,
    assert_posture,
    credit,
    file_snapshot,
    file_violation,
    hold_payload,
    issue_action,
    make_seller_headers,
    open_investigation,
    poa_payload,
    publish_rule,
    read_action,
    read_holds,
    read_seller,
    register_seller,
    review_poa,
    set_clock,
    start_review,
    substantiated_violation,
    validate_error,
    validate_success,
    file_appeal,
    appeal_payload,
    decide_appeal,
)

CLOCK = "2026-08-01T00:00:00.000Z"


# --------------------------------------------------------------------------
# Stage 10 (transition legality) versus stage 16 (money capacity)
# --------------------------------------------------------------------------
def _unaffordable_exposure_against_an_ordinary_seller(api):
    """The seller stands in NORMAL with 100000 cents and 21 open claim units, so
    a CLAIM_EXPOSURE reserve of 189000 breaks the posture rule and the capacity
    rule at the same time."""
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="LA-CONF-1", category="LISTING_ACCURACY", base_severity_weight=1.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = register_seller(
        api, legal_name="Marrowfield Pantry LLC", email="ops@marrowfield-pantry.example",
        tax_id_hash="TAX-MA-0001", payout_bank_token="BANK-MA-0001",
        address_fingerprint="ADDR-MA-0001",
    )
    credit(api, seller["id"], 100000, "PAYOUT-CYCLE-2026-07-D")
    file_snapshot(
        api, seller["id"], "2026-07-01T00:00:00.000Z", "2026-08-01T00:00:00.000Z",
        order_volume=1200, delivered_or_refunded_volume=1150, defect_claims_pending=21,
        defect_claims_substantiated=4, late_shipments=20, pre_fulfillment_cancellations=8,
        shipments_total=1180, shipments_with_valid_tracking=1160, source="PLATFORM_PIPELINE",
    )
    violation = file_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER", evidence_reference="EV-MA-0001"
    )
    return seller, violation


def _exposure_attempt(api, seller_id):
    """The version is re-read immediately beforehand so the stage-11 concurrency
    check can never fire and mask either error."""
    version = read_seller(api, seller_id, INVESTIGATOR)["version"]
    return api.create_hold(
        hold_payload(
            seller_id, CLOCK, "2026-09-01T00:00:00.000Z", version,
            hold_type="RESERVE", reserve_basis="CLAIM_EXPOSURE",
        ),
        INVESTIGATOR,
    )


def test_the_hold_posture_refusal_hides_the_unaffordable_amount(api):
    """PRD §3.9: "The seller's `disbursement_state` must not be `NORMAL`; opening
    a hold against a seller in ordinary standing is refused with
    `ERR_SELLER_NOT_UNDER_HOLD_POSTURE`."

    Design: Difficulty/priority_pair_validation_conflict/hold_posture_state_check_beats_fiscal_capacity_check
    """
    seller, _ = _unaffordable_exposure_against_an_ordinary_seller(api)
    before = read_seller(api, seller["id"], INVESTIGATOR)
    assert_posture(before, disbursement_state="NORMAL")
    assert before["open_defect_claim_units"] == 21

    response = _exposure_attempt(api, seller["id"])

    # Transition legality is stage 10; money capacity is stage 16.
    error = validate_error(response, ApiErrorId.SELLER_NOT_UNDER_HOLD_POSTURE.value, 409)
    assert error["error_id"] != ApiErrorId.HOLD_EXCEEDS_AVAILABLE.value


def test_fixing_the_posture_alone_exposes_the_capacity_refusal(api):
    """PRD §3.9: "An exposure reserve ignores the balance entirely, which means it
    can exceed it; there is deliberately **no** implicit clamp to the available
    balance, so a claim-exposure reserve larger than `available_balance_cents` is
    refused with `ERR_HOLD_EXCEEDS_AVAILABLE` rather than being quietly reduced."

    Design: Difficulty/priority_pair_validation_conflict/hold_posture_state_check_beats_fiscal_capacity_check
    """
    seller, violation = _unaffordable_exposure_against_an_ordinary_seller(api)
    validate_error(
        _exposure_attempt(api, seller["id"]),
        ApiErrorId.SELLER_NOT_UNDER_HOLD_POSTURE.value, 409,
    )

    open_investigation(api, violation["id"])

    # Only the posture moved; the money did not.
    fixed = read_seller(api, seller["id"], INVESTIGATOR)
    assert_posture(fixed, disbursement_state="RESERVE_HELD")
    assert_funds(fixed, available=100000, held=0, credited=100000, debited=0)

    # 21 x 9000 x the TIER_1 multiplier of 1.00 is 189000, above 100000.
    validate_error(
        _exposure_attempt(api, seller["id"]),
        ApiErrorId.HOLD_EXCEEDS_AVAILABLE.value, 422,
    )

    after = read_seller(api, seller["id"], INVESTIGATOR)
    assert_funds(after, available=100000, held=0, credited=100000, debited=0)
    assert read_holds(api, params={"seller_id": seller["id"]}) == []


# --------------------------------------------------------------------------
# Stage 13 (clock windows) versus stage 15 (cross-row coherence)
# --------------------------------------------------------------------------
def _appeal_citing_a_stale_action_and_a_foreign_plan(api):
    """Action a_x needs no plan and its appeal window has just expired; action a_y
    carries a genuinely ACCEPTED plan that simply belongs to the other action."""
    set_clock(api, CLOCK)
    rule_without_plan = publish_rule(
        api, code="LA-NP-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    rule_with_plan = publish_rule(
        api, code="SP-P-1", category="SHIPPING_PERFORMANCE", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=True,
    )
    seller = register_seller(
        api, legal_name="Northgate Provisions LLC", email="ops@northgate-provisions.example",
        tax_id_hash="TAX-NO-0001", payout_bank_token="BANK-NO-0001",
        address_fingerprint="ADDR-NO-0001",
    )
    appealed_violation = substantiated_violation(
        api, seller["id"], rule_without_plan["id"], reporter_type="BUYER",
        evidence_reference="EV-NO-0001",
    )
    appealed = issue_action(api, appealed_violation["id"])

    other_violation = substantiated_violation(
        api, seller["id"], rule_with_plan["id"], reporter_type="BUYER",
        evidence_reference="EV-NO-0002",
    )
    other = issue_action(api, other_violation["id"])
    seller_headers = make_seller_headers(seller["id"])
    other_version = validate_success(
        api.get_enforcement_action(other["id"], seller_headers)
    )["version"]
    foreign_plan = validate_success(
        api.create_plan_of_action(
            poa_payload(
                other["id"], other_version,
                root_cause="Our third-party fulfilment partner missed the carrier cutoff "
                           "for eleven consecutive business days in July.",
                corrective_measures=[
                    "Moved the affected SKUs to a fulfilment centre with a later carrier cutoff."
                ],
                preventive_measures=[
                    "Daily cutoff-adherence report reviewed by the operations lead."
                ],
            ),
            seller_headers,
        ),
        201,
    )
    review_poa(api, foreign_plan["id"], "ACCEPT", "Root cause and controls are adequate.")
    return seller, appealed, other, foreign_plan


APPEAL_GROUNDS = (
    "The listing data was corrected the same afternoon and the accepted plan on "
    "file already covers this."
)


def _appeal_attempt(api, seller_id, action_id, plan_id):
    return api.create_appeal(
        appeal_payload(action_id, plan_id, grounds=APPEAL_GROUNDS),
        make_seller_headers(seller_id),
    )


def test_the_closed_appeal_window_hides_the_plan_belonging_to_another_action(api):
    """PRD §3.8: "The clock reading must be at or before the action's
    `appeal_deadline_at`, thirty days from issuance; a strictly later reading is
    refused with `ERR_APPEAL_WINDOW_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/appeal_window_temporal_beats_poa_action_mismatch_referential
    """
    seller, appealed, _, foreign_plan = _appeal_citing_a_stale_action_and_a_foreign_plan(api)
    assert_instant_equals(
        appealed["appeal_deadline_at"], "2026-08-31T00:00:00.000Z", "appeal_deadline_at"
    )

    set_clock(api, "2026-09-01T00:00:00.000Z")
    response = _appeal_attempt(api, seller["id"], appealed["id"], foreign_plan["id"])

    # Clock windows are stage 13; cross-row coherence is stage 15.
    error = validate_error(response, ApiErrorId.APPEAL_WINDOW_CLOSED.value, 422)
    assert error["error_id"] != ApiErrorId.POA_ACTION_MISMATCH.value


def test_rewinding_inside_the_window_exposes_the_plan_mismatch(api):
    """PRD §3.8: "a cited `plan_of_action_id` that belongs to some other action is
    refused with `ERR_POA_ACTION_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/appeal_window_temporal_beats_poa_action_mismatch_referential
    """
    seller, appealed, other, foreign_plan = _appeal_citing_a_stale_action_and_a_foreign_plan(api)
    set_clock(api, "2026-09-01T00:00:00.000Z")
    validate_error(
        _appeal_attempt(api, seller["id"], appealed["id"], foreign_plan["id"]),
        ApiErrorId.APPEAL_WINDOW_CLOSED.value, 422,
    )

    set_clock(api, "2026-08-20T00:00:00.000Z")
    validate_error(
        _appeal_attempt(api, seller["id"], appealed["id"], foreign_plan["id"]),
        ApiErrorId.POA_ACTION_MISMATCH.value, 422,
    )

    # The plan is valid; it simply belongs to the other action.
    stored_plan = validate_success(api.get_plan_of_action(foreign_plan["id"], OFFICER))
    assert stored_plan["state"] == "ACCEPTED"
    assert stored_plan["enforcement_action_id"] == other["id"]

    assert validate_success(
        api.list_appeals(OFFICER, {"enforcement_action_id": appealed["id"]})
    ) == []
    assert read_action(api, appealed["id"])["state"] == "ISSUED"
    seller_row = read_seller(api, seller["id"])
    assert_posture(seller_row, enforcement_state="RESTRICTED",
                   severity_points_balance="4.00")


# --------------------------------------------------------------------------
# Stage 5 (resource ownership) versus stage 10 (transition legality)
# --------------------------------------------------------------------------
def _upheld_action_and_an_unrelated_seller(api):
    """A1 belongs to the first seller and is UPHELD after a denied appeal, so
    acknowledgement is no longer reachable from that state; the second seller
    shares no registration signal at all."""
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="RM-ACK-1", category="REVIEW_MANIPULATION", base_severity_weight=2.50,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    owner = register_seller(
        api, legal_name="Oakfern Kitchenware LLC", email="ops@oakfern-kitchenware.example",
        tax_id_hash="TAX-OA-0001", payout_bank_token="BANK-OA-0001",
        address_fingerprint="ADDR-OA-0001",
    )
    stranger = register_seller(
        api, legal_name="Pinehollow Ceramics LLC", email="ops@pinehollow-ceramics.example",
        tax_id_hash="TAX-PI-0002", payout_bank_token="BANK-PI-0002",
        address_fingerprint="ADDR-PI-0002",
    )
    violation = substantiated_violation(
        api, owner["id"], rule["id"], reporter_type="BUYER", evidence_reference="EV-OA-0001"
    )
    action = issue_action(api, violation["id"])
    appeal = file_appeal(
        api, action["id"], owner["id"],
        grounds="The reviews in question were left by verified buyers with no incentive "
                "from us.",
    )
    start_review(api, appeal["id"], REVIEWER)
    decide_appeal(
        api, appeal["id"], "DENIED", "EVIDENCE_UPHELD",
        rationale="Payment records show gift-card reimbursements to eight of the reviewers.",
        headers=REVIEWER,
    )
    return owner, stranger, action


def test_a_stranger_acknowledging_is_refused_for_ownership_not_for_state(api):
    """PRD §2.8: "5. Resource ownership — for any endpoint a `Seller` may call, the
    ownership comparison of §2.1, yielding `ERR_NOT_RESOURCE_OWNER`."

    Design: Difficulty/priority_pair_validation_conflict/acknowledge_ownership_auth_beats_action_not_appealable_state
    """
    _, stranger, action = _upheld_action_and_an_unrelated_seller(api)

    response = api.acknowledge_action(action["id"], make_seller_headers(stranger["id"]))

    # Ownership is stage 5; transition legality is stage 10, so the state of
    # another seller's action stays hidden from a stranger.
    error = validate_error(response, ApiErrorId.NOT_RESOURCE_OWNER.value, 403)
    assert error["error_id"] != ApiErrorId.ACTION_NOT_APPEALABLE_STATE.value

    stranger_row = read_seller(api, stranger["id"])
    assert_posture(stranger_row, enforcement_state="ACTIVE")
    assert stranger_row["registration_risk_flag"] is False


def test_the_rightful_owner_acknowledging_is_refused_for_the_upheld_state(api):
    """PRD §3.6: "An action already in `UPHELD` or `VACATED` cannot be
    acknowledged, and the attempt is refused with
    `ERR_ACTION_NOT_APPEALABLE_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/acknowledge_ownership_auth_beats_action_not_appealable_state
    """
    owner, stranger, action = _upheld_action_and_an_unrelated_seller(api)
    validate_error(
        api.acknowledge_action(action["id"], make_seller_headers(stranger["id"])),
        ApiErrorId.NOT_RESOURCE_OWNER.value, 403,
    )

    validate_error(
        api.acknowledge_action(action["id"], make_seller_headers(owner["id"])),
        ApiErrorId.ACTION_NOT_APPEALABLE_STATE.value, 409,
    )

    after = read_action(api, action["id"])
    assert after["state"] == "UPHELD"
    assert after["acknowledged_at"] is None
    assert after["resolution_reason"] == "APPEAL_DENIED"
