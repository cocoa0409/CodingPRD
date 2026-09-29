"""Validations decided by the catalogue's own bookkeeping rather than by the facts
of a single row: the two uniqueness keys, the two at-most-one constraints, the pair
of adjacent shape-and-completeness priorities, the write freeze a ban imposes, the
fiscal ceilings on held money, and the two refusals that are permanent by design.
"""

from test_helpers import (
    ANONYMOUS,
    INVESTIGATOR,
    OFFICER,
    OFFICER_ALT,
    REVIEWER,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_cents,
    assert_funds,
    assert_instant_equals,
    assert_meta,
    assert_nulls,
    assert_points,
    assert_posture,
    create_listing,
    credit,
    decide_appeal,
    decide_escalation,
    escalate,
    file_appeal,
    file_snapshot,
    file_violation,
    find_notice,
    hold_payload,
    issue_action,
    listing_payload,
    make_seller_headers,
    open_investigation,
    poa_payload,
    policy_rule_payload,
    publish_rule,
    read_action,
    read_holds,
    read_listings,
    read_notices,
    read_seller,
    register_seller,
    seller_payload,
    set_clock,
    snapshot_payload,
    start_review,
    submit_poa,
    substantiated_violation,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00.000Z"

OUTAGE_GROUNDS = (
    "The shipping delays were caused by a regional carrier outage outside our control."
)
OUTAGE_RATIONALE = (
    "Carrier records show the delays predate the outage window the seller cites."
)
INCIDENT_GROUNDS = (
    "We are submitting the carrier's own incident report, which was issued after the "
    "decision."
)
FINAL_RATIONALE = (
    "The incident report covers a different region than the affected orders."
)


# --------------------------------------------------------------------------
# A removal category that outlives every recovery
# --------------------------------------------------------------------------
def test_a_restricted_product_removal_can_never_be_relisted(api):
    """PRD §3.2: "Finally, a listing whose `removal_policy_category` is
    `RESTRICTED_PRODUCT` may never come back at all, no matter how healthy the
    account becomes; that attempt is refused with
    `ERR_LISTING_RESTRICTED_NO_RELIST`."

    Design: Corner/validations/validation_restricted_product_removal_is_permanent
    """
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="RP-1", category="RESTRICTED_PRODUCT", base_severity_weight=2.00,
        removal_scope="LISTING", requires_poa=False,
    )
    seller = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )
    listing = create_listing(
        api, seller["id"], sku="HT-SKU-777", title="Air rifle scope mount",
        category_code="OUTDOOR-RESTRICTED", restricted_flag=True,
    )
    violation = substantiated_violation(
        api, seller["id"], rule["id"], listing_id=listing["id"],
        reporter_type="PLATFORM_AUTOMATION", evidence_reference="EV-RP-0001",
        decision_note="The mount is sold only through the restricted-product programme.",
    )
    action = issue_action(api, violation["id"])

    # 0.00 + 2.00 = 2.00 selects a bare WARNING, which the category floor lifts.
    assert action["ladder_rung_computed"] == "LISTING_REMOVAL"
    assert action["action_type"] == "LISTING_REMOVAL"
    assert action["override_applied"] is False
    assert_points(action["severity_points_applied"], "2.00", "severity_points_applied")
    assert action["decay_exempt"] is True
    assert action["removed_listing_count"] == 1

    removed = {row["id"]: row for row in read_listings(api, seller["id"])}[listing["id"]]
    assert removed["state"] == "REMOVED"
    assert removed["removal_policy_category"] == "RESTRICTED_PRODUCT"
    # The seller-posture gate of §3.2 is satisfied: WATCHLIST may relist.
    assert_posture(read_seller(api, seller["id"]), enforcement_state="WATCHLIST",
                   severity_points_balance="2.00")

    response = api.relist_listing(listing["id"], make_seller_headers(seller["id"]))

    validate_error(response, ApiErrorId.LISTING_RESTRICTED_NO_RELIST.value, 422)
    still_removed = {row["id"]: row
                     for row in read_listings(api, seller["id"])}[listing["id"]]
    assert still_removed["state"] == "REMOVED"
    assert still_removed["removal_policy_category"] == "RESTRICTED_PRODUCT"


# --------------------------------------------------------------------------
# The two uniqueness keys
# --------------------------------------------------------------------------
def test_the_email_key_ignores_letter_case_but_not_the_local_part(api):
    """PRD §3.1: "If another seller already holds the same `email` — compared
    without regard to letter case — registration is refused with
    `ERR_DUPLICATE_SELLER_EMAIL`."

    Design: Corner/validations/validation_seller_email_uniqueness_ignores_case
    """
    set_clock(api, CLOCK)
    incumbent = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )

    upper_cased = api.register_seller(
        seller_payload(
            legal_name="Harbour Tools Ltd", email="OPS@HARBOR-TOOLS.EXAMPLE",
            tax_id_hash="TAX-HT-0002", payout_bank_token="BANK-HT-0002",
            address_fingerprint="ADDR-HT-0002",
        ),
        ANONYMOUS,
    )

    validate_error(upper_cased, ApiErrorId.DUPLICATE_SELLER_EMAIL.value, 409)

    # The key is the whole address, so a second local part on the same domain is free.
    newcomer = validate_success(
        api.register_seller(
            seller_payload(
                legal_name="Harbour Tools Ltd", email="billing@harbor-tools.example",
                tax_id_hash="TAX-HT-0002", payout_bank_token="BANK-HT-0002",
                address_fingerprint="ADDR-HT-0002",
            ),
            ANONYMOUS,
        ),
        201,
    )

    rows, meta = validate_paginated(api.list_sellers(OFFICER))
    assert_meta(meta, total_count=2)
    assert {row["id"] for row in rows} == {incumbent["id"], newcomer["id"]}
    # Only the email domain matched, and 0.10 sits below the 0.35 minting score.
    assert newcomer["root_seller_id"] is None
    assert newcomer["registration_risk_flag"] is False
    links, link_meta = validate_paginated(
        api.list_related_account_links(OFFICER, {"candidate_seller_id": newcomer["id"]})
    )
    assert_meta(link_meta, total_count=0)
    assert links == []
    # A refused registration touches nothing, so the incumbent is still at its birth
    # version.
    assert read_seller(api, incumbent["id"])["version"] == 1


def test_the_rule_code_is_the_whole_uniqueness_key(api):
    """PRD §3.2: "A `PolicyRule` is published with a `code` of 2 to 32 characters
    that must be unique across the catalogue — a repeat is refused with
    `ERR_DUPLICATE_POLICY_CODE` — a `category` drawn from `LISTING_ACCURACY`,
    `INTELLECTUAL_PROPERTY`, `RESTRICTED_PRODUCT`, `REVIEW_MANIPULATION`, and
    `SHIPPING_PERFORMANCE`, a `base_severity_weight` given to two decimals somewhere
    between 0.50 and 8.00 inclusive, and a `removal_scope` of either `LISTING` or
    `ACCOUNT` declaring whether a removal rung under this rule takes down only the
    cited item or the seller's whole catalogue."

    Design: Corner/validations/validation_policy_rule_code_must_be_unique
    """
    set_clock(api, CLOCK)
    first = publish_rule(
        api, code="LA-DUP-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )

    repeat = api.create_policy_rule(
        policy_rule_payload(
            code="LA-DUP-1", category="SHIPPING_PERFORMANCE", base_severity_weight=5.00,
            removal_scope="LISTING",
        ),
        OFFICER,
    )

    # A different category and a different severity do not make it a different code.
    validate_error(repeat, ApiErrorId.DUPLICATE_POLICY_CODE.value, 409)

    second = validate_success(
        api.create_policy_rule(
            policy_rule_payload(
                code="LA-DUP-2", category="SHIPPING_PERFORMANCE",
                base_severity_weight=5.00, removal_scope="LISTING",
            ),
            OFFICER,
        ),
        201,
    )

    # requires_poa was omitted from the accepted body and defaults to true.
    assert second["requires_poa"] is True
    assert second["decay_exempt"] is False
    rows, meta = validate_paginated(api.list_policy_rules(OFFICER))
    assert_meta(meta, total_count=2)
    catalogue = {row["code"]: row for row in rows}
    assert set(catalogue) == {"LA-DUP-1", "LA-DUP-2"}
    assert catalogue["LA-DUP-2"]["id"] == second["id"]
    # The refused publication left the incumbent row exactly as it was.
    assert catalogue["LA-DUP-1"]["id"] == first["id"]
    assert catalogue["LA-DUP-1"]["category"] == "LISTING_ACCURACY"
    assert catalogue["LA-DUP-1"]["removal_scope"] == "ACCOUNT"
    assert_points(catalogue["LA-DUP-1"]["base_severity_weight"], "2.00",
                  "base_severity_weight")


# --------------------------------------------------------------------------
# The two at-most-one constraints
# --------------------------------------------------------------------------
def test_one_violation_can_carry_only_one_live_action(api):
    """PRD §3.6: "Three preconditions guard the issuance beyond the ordering of
    §2.8: the cited violation must be `SUBSTANTIATED`, no non-vacated action may
    already cite that violation — at most one action per violation may sit in
    `ISSUED`, `ACKNOWLEDGED`, or `UPHELD`, and a second attempt is refused with
    `ERR_ACTION_ALREADY_EXISTS` — and where the cited rule's `requires_poa` is true,
    the seller must not currently have a plan of action in `SUBMITTED` or
    `RETURNED_FOR_REVISION`, since piling a new charge on a seller mid-remedy is
    refused with `ERR_INVALID_STATE`."

    Design: Corner/validations/validation_one_violation_yields_at_most_one_live_action
    """
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="LA-ONE-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )
    violation = substantiated_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER",
        evidence_reference="EV-ONE-0001",
        decision_note="Two listings described a refurbished unit as new.",
    )
    first = issue_action(api, violation["id"])
    assert first["state"] == "ISSUED"

    repeat = api.create_enforcement_action({"violation_id": violation["id"]}, INVESTIGATOR)

    validate_error(repeat, ApiErrorId.ACTION_ALREADY_EXISTS.value, 409)
    rows, meta = validate_paginated(
        api.list_enforcement_actions(INVESTIGATOR, {"violation_id": violation["id"]})
    )
    assert_meta(meta, total_count=1)
    assert rows[0]["id"] == first["id"]

    after = read_seller(api, seller["id"])
    # A missing check would have scored the same charge twice: 2.00 + 2.00 x 1.25.
    # PRD §3.9: a WATCHLIST enforcement posture alone targets RESERVE_HELD.
    assert_posture(after, enforcement_state="WATCHLIST", disbursement_state="RESERVE_HELD",
                   severity_points_balance="2.00")


def test_a_second_plan_is_refused_while_the_first_is_still_submitted(api):
    """PRD §3.7: "And only one plan per action may be open at a time: where a plan
    for that action is already in `SUBMITTED`, the new submission is refused with
    `ERR_POA_ALREADY_OPEN`."

    Design: Corner/validations/validation_only_one_plan_may_be_open_per_action
    """
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="LA-POA-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=True,
    )
    seller = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )
    violation = substantiated_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER",
        evidence_reference="EV-POA-0001",
        decision_note="The condition attribute was wrong on 42 refurbished listings.",
    )
    action = issue_action(api, violation["id"])
    at_issuance = read_action(api, action["id"])["version"]

    plan = submit_poa(
        api, action["id"], seller["id"],
        root_cause="Our catalogue feed mapped the wrong attribute set onto refurbished "
                   "units, so the condition field was wrong.",
        corrective_measures=["Corrected the condition attribute on all 42 affected "
                             "listings."],
        preventive_measures=["Added a pre-publish check that blocks refurbished units "
                             "without a condition note."],
    )
    assert plan["state"] == "SUBMITTED"
    assert plan["revision_count"] == 0
    # Submission bumped the parent action, so the token must be refreshed before the
    # second attempt — a stale one would report 412 and hide the rule under test.
    after_submission = read_action(api, action["id"])["version"]
    assert after_submission == at_issuance + 1

    second = api.create_plan_of_action(
        poa_payload(
            action["id"], after_submission,
            root_cause="A second attempt at the same explanation, restating the "
                       "catalogue mapping defect in more detail.",
            corrective_measures=["Re-checked the remaining catalogue rows for the same "
                                 "defect."],
            preventive_measures=["Scheduled a weekly attribute audit of refurbished "
                                 "inventory."],
        ),
        make_seller_headers(seller["id"]),
    )

    validate_error(second, ApiErrorId.POA_ALREADY_OPEN.value, 409)
    rows, meta = validate_paginated(
        api.list_plans_of_action(OFFICER, {"enforcement_action_id": action["id"]})
    )
    assert_meta(meta, total_count=1)
    assert rows[0]["id"] == plan["id"]
    assert rows[0]["state"] == "SUBMITTED"
    assert rows[0]["revision_count"] == 0
    # The refused write bumped nothing.
    assert read_action(api, action["id"])["version"] == after_submission


# --------------------------------------------------------------------------
# Two adjacent priorities on one endpoint
# --------------------------------------------------------------------------
ABSENT_FLOOR_ROOT_CAUSE = "Our feed mapped the wrong attributes"
ACCEPTED_ROOT_CAUSE = (
    "Our catalogue feed mapped the wrong attribute set onto refurbished units, so the "
    "condition field was wrong."
)
ACCEPTED_CORRECTIVE = ["Corrected the condition attribute on all 42 affected listings."]
ACCEPTED_PREVENTIVE = ["Added a pre-publish check for refurbished units."]


def test_an_absent_root_cause_is_a_shape_error_and_a_short_one_is_incomplete(api):
    """PRD §3.7: "`root_cause` is the seller's own explanation of why the failure
    happened; it must be at least 40 and at most 2000 characters once surrounding
    whitespace has been trimmed, a floor that exists specifically to reject plans
    that merely restate the symptom."

    Design: Corner/validations/validation_request_shape_is_checked_before_plan_completeness
    """
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="LA-INC-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=True,
    )
    seller = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )
    violation = substantiated_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER",
        evidence_reference="EV-INC-0001",
        decision_note="The condition attribute was wrong on 42 refurbished listings.",
    )
    action = issue_action(api, violation["id"])
    token = read_action(api, action["id"])["version"]
    seller_headers = make_seller_headers(seller["id"])

    def attempt(**kwargs):
        return api.create_plan_of_action(
            poa_payload(action["id"], token, corrective_measures=ACCEPTED_CORRECTIVE,
                        preventive_measures=ACCEPTED_PREVENTIVE, **kwargs),
            seller_headers,
        )

    complete = poa_payload(
        action["id"], token, root_cause=ACCEPTED_ROOT_CAUSE,
        corrective_measures=ACCEPTED_CORRECTIVE, preventive_measures=ACCEPTED_PREVENTIVE,
    )
    without_root_cause = {key: value for key, value in complete.items()
                          if key != "root_cause"}

    absent = api.create_plan_of_action(without_root_cause, seller_headers)
    # Stage 7 of §2.8 runs before stage 8, so a missing field is a shape failure.
    validate_error(absent, ApiErrorId.INVALID_REQUEST.value, 400)

    short = attempt(root_cause=ABSENT_FLOOR_ROOT_CAUSE)
    # Thirty-six characters is present but one short of the forty-character floor.
    assert len(ABSENT_FLOOR_ROOT_CAUSE) == 36
    validate_error(short, ApiErrorId.POA_INCOMPLETE.value, 422)

    short_element = api.create_plan_of_action(
        poa_payload(action["id"], token, root_cause=ACCEPTED_ROOT_CAUSE,
                    corrective_measures=["Fixed it."],
                    preventive_measures=ACCEPTED_PREVENTIVE),
        seller_headers,
    )
    validate_error(short_element, ApiErrorId.POA_INCOMPLETE.value, 422)

    # Three refusals wrote nothing, so the very first token is still current.
    assert read_action(api, action["id"])["version"] == token
    accepted = validate_success(api.create_plan_of_action(complete, seller_headers), 201)

    assert accepted["state"] == "SUBMITTED"
    assert accepted["revision_count"] == 0
    assert_nulls(accepted, "reviewed_by_user_id", "review_notes")
    # The plan deadline is the action's issued_at plus seventeen days.
    assert_instant_equals(accepted["deadline_at"], "2026-08-18T00:00:00.000Z",
                          "deadline_at")
    assert read_action(api, action["id"])["version"] == token + 1


# --------------------------------------------------------------------------
# The write freeze a ban imposes, and the ceiling on what may be taken
# --------------------------------------------------------------------------
def _a_banned_seller_swept_of_a_hundred_thousand_cents(api, code, evidence_reference):
    """An eight-point shipping charge overridden up to a suspension sweeps the whole
    credited balance into one FULL_HOLD row; the exhausted escalation against that
    suspension then closes the account for good."""
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code=code, category="SHIPPING_PERFORMANCE", base_severity_weight=8.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )
    credit(api, seller["id"], 100000)
    violation = substantiated_violation(
        api, seller["id"], rule["id"], reporter_type="PLATFORM_AUTOMATION",
        evidence_reference=evidence_reference,
        decision_note="Eleven consecutive dispatches missed their promised ship date.",
    )
    action = issue_action(api, violation["id"],
                         action_type_override="ACCOUNT_SUSPENSION")
    appeal = file_appeal(api, action["id"], seller["id"], grounds=OUTAGE_GROUNDS)
    start_review(api, appeal["id"], REVIEWER)
    decide_appeal(api, appeal["id"], "DENIED", "EVIDENCE_UPHELD", OUTAGE_RATIONALE,
                  REVIEWER)
    escalate(api, appeal["id"], seller["id"], escalation_grounds=INCIDENT_GROUNDS)
    appeal = decide_escalation(api, appeal["id"], "FINAL_DENIED", "EVIDENCE_UPHELD",
                               FINAL_RATIONALE, OFFICER)
    return seller, action, appeal


def test_a_banned_account_still_takes_in_the_money_it_is_owed(api):
    """PRD §2.5: "While a seller is banned, every write operation against that seller
    or against a row that reaches that seller is refused with `ERR_SELLER_BANNED`
    (HTTP 409); the only exceptions are seller registration, crediting proceeds,
    forfeiting a hold, and setting the logical clock."

    Design: Corner/validations/validation_banned_seller_is_write_frozen_except_for_money_in
    """
    seller, _, appeal = _a_banned_seller_swept_of_a_hundred_thousand_cents(
        api, "SP-BAN-1", "EV-BAN-0001"
    )
    assert appeal["state"] == "FINAL_DENIED"
    banned = read_seller(api, seller["id"])
    assert_posture(banned, enforcement_state="BANNED", disbursement_state="FULL_HOLD")
    assert banned["ban_reason"] == "ESCALATION_EXHAUSTED"
    assert_funds(banned, available=0, held=100000, credited=100000, debited=0)

    listing_attempt = api.create_listing(
        listing_payload(seller["id"], sku="HT-SKU-002",
                        title="Replacement vice jaws", category_code="TOOLS-HAND"),
        make_seller_headers(seller["id"]),
    )
    snapshot_attempt = api.create_snapshot(
        snapshot_payload(
            seller["id"], "2026-07-01T00:00:00.000Z", "2026-08-01T00:00:00.000Z",
            order_volume=10, delivered_or_refunded_volume=10, defect_claims_pending=0,
            defect_claims_substantiated=0, late_shipments=0,
            pre_fulfillment_cancellations=0, shipments_total=10,
            shipments_with_valid_tracking=10,
        ),
        OFFICER,
    )

    # The seller's own write and an officer's write are frozen by the same error.
    validate_error(listing_attempt, ApiErrorId.SELLER_BANNED.value, 409)
    validate_error(snapshot_attempt, ApiErrorId.SELLER_BANNED.value, 409)

    credited = credit(api, seller["id"], 5000, "SETTLE-2026-08-01")

    # Money the marketplace already collected still lands on a closed account.
    assert_funds(credited, available=5000, held=100000, credited=105000, debited=0)
    assert_funds(read_seller(api, seller["id"]), available=5000, held=100000,
                 credited=105000, debited=0)
    _, listing_meta = validate_paginated(
        api.list_seller_listings(seller["id"], OFFICER)
    )
    assert_meta(listing_meta, total_count=0)
    _, snapshot_meta = validate_paginated(
        api.list_seller_snapshots(seller["id"], OFFICER)
    )
    assert_meta(snapshot_meta, total_count=0)


def test_a_forfeit_one_cent_over_the_hold_is_refused(api):
    """PRD §3.9: "The figure may not exceed the hold's `held_amount_cents`, and a
    larger one is refused with `ERR_FORFEIT_EXCEEDS_HOLD`; partial forfeiture is
    entirely legitimate."

    Design: Corner/validations/validation_forfeit_cannot_exceed_the_hold_amount
    """
    seller, _, _ = _a_banned_seller_swept_of_a_hundred_thousand_cents(
        api, "SP-FORF-1", "EV-FORF-0001"
    )
    active = read_holds(api, params={"seller_id": seller["id"], "state": "ACTIVE"})
    assert len(active) == 1, f"expected one sweeping row, got {active}"
    sweeping = active[0]
    assert sweeping["hold_type"] == "FULL_HOLD"
    assert sweeping["auto_created"] is True
    assert_cents(sweeping["held_amount_cents"], 100000, "held_amount_cents")

    # co-2 is not the hold's creator, so the segregation rule cannot interfere; the
    # forfeit endpoint is exempt from the ban freeze, so this is a fiscal refusal.
    response = api.forfeit_hold(sweeping["id"], {"forfeited_amount_cents": 100001},
                                OFFICER_ALT)

    validate_error(response, ApiErrorId.FORFEIT_EXCEEDS_HOLD.value, 422)
    unchanged = validate_success(api.get_hold(sweeping["id"], OFFICER))
    assert unchanged["state"] == "ACTIVE"
    assert_cents(unchanged["forfeited_amount_cents"], 0, "forfeited_amount_cents")
    assert_nulls(unchanged, "released_at", "release_reason")
    after = read_seller(api, seller["id"])
    assert_funds(after, available=0, held=100000, credited=100000, debited=0)
    assert_posture(after, enforcement_state="BANNED", disbursement_state="FULL_HOLD")


# --------------------------------------------------------------------------
# The role check that runs before the path is resolved
# --------------------------------------------------------------------------
def test_an_unauthorised_caller_cannot_learn_which_ids_exist(api):
    """PRD §2.8: "Validation therefore proceeds in a strictly ordered sequence, and
    the **first** rule that fails decides the response; no later check is evaluated."

    Design: Corner/validations/validation_role_check_precedes_path_existence
    """
    set_clock(api, CLOCK)
    seller = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )

    as_seller = api.adjudicate_violation(
        NON_EXISTENT_UUID, {"outcome": "SUBSTANTIATED"},
        make_seller_headers(seller["id"]),
    )
    as_investigator = api.adjudicate_violation(
        NON_EXISTENT_UUID, {"outcome": "SUBSTANTIATED"}, INVESTIGATOR,
    )

    # Adjudication is a PolicyInvestigator capability, so role authorisation (step 2)
    # decides the seller's request before path existence (step 3) is ever reached.
    validate_error(as_seller, ApiErrorId.UNAUTHORIZED.value, 403)
    validate_error(as_investigator, ApiErrorId.VIOLATION_NOT_FOUND.value, 404)

    _, meta = validate_paginated(api.list_violations(INVESTIGATOR))
    assert_meta(meta, total_count=0)
    assert read_seller(api, seller["id"])["version"] == 1


# --------------------------------------------------------------------------
# The satisfied side of the fiscal predicate
# --------------------------------------------------------------------------
def test_an_exposure_reserve_equal_to_the_balance_is_not_an_excess(api):
    """PRD §3.9: "An exposure reserve ignores the balance entirely, which means it
    can exceed it; there is deliberately **no** implicit clamp to the available
    balance, so a claim-exposure reserve larger than `available_balance_cents` is
    refused with `ERR_HOLD_EXCEEDS_AVAILABLE` rather than being quietly reduced."

    Design: Corner/validations/validation_reserve_exactly_at_the_available_balance_is_accepted
    """
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="LA-EXACT-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )
    credit(api, seller["id"], 90000)
    file_snapshot(
        api, seller["id"], "2026-07-01T00:00:00.000Z", "2026-08-01T00:00:00.000Z",
        order_volume=100, delivered_or_refunded_volume=100, defect_claims_pending=10,
        defect_claims_substantiated=0, late_shipments=0, pre_fulfillment_cancellations=0,
        shipments_total=100, shipments_with_valid_tracking=100,
    )
    violation = file_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER",
        evidence_reference="EV-EXACT-0001",
    )
    open_investigation(api, violation["id"])
    before = read_seller(api, seller["id"], INVESTIGATOR)
    assert before["open_defect_claim_units"] == 10
    assert before["metric_tier"] is None
    assert_funds(before, available=90000, held=0, credited=90000, debited=0)

    hold = validate_success(
        api.create_hold(
            hold_payload(
                seller["id"], "2026-08-02T00:00:00.000Z", "2026-08-05T00:00:00.000Z",
                before["version"], hold_type="RESERVE", reserve_basis="CLAIM_EXPOSURE",
            ),
            INVESTIGATOR,
        ),
        201,
    )

    # 10 units x 9000 cents x the TIER_1 multiplier of 1.00 is exactly the balance.
    assert_cents(hold["held_amount_cents"], 90000, "held_amount_cents")
    assert hold["risk_tier"] == "TIER_1"
    assert hold["state"] == "ACTIVE"
    assert hold["hold_type"] == "RESERVE"
    assert hold["reserve_basis"] == "CLAIM_EXPOSURE"
    assert hold["auto_created"] is False

    after = read_seller(api, seller["id"], INVESTIGATOR)
    assert_funds(after, available=0, held=90000, credited=90000, debited=0)
    assert_posture(after, enforcement_state="ACTIVE", disbursement_state="RESERVE_HELD",
                   severity_points_balance="0.00")
    notice = find_notice(read_notices(api, seller["id"]), "FUNDS_HELD", hold["id"])
    assert_cents(notice["amount_cents"], 90000, "amount_cents")
