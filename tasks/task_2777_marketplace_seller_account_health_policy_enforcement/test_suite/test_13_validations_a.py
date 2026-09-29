"""Validations whose verdict depends on a neighbouring row rather than on the
request in isolation: the reporter admitted by a rule's category, the listing a
scope demands, the ownership every cited identifier must share, the balance a
second reserve is measured against, and the two compliance gates that overrule
an operator's own judgement.
"""

from test_helpers import (
    INVESTIGATOR,
    OFFICER,
    REVIEWER,
    ApiErrorId,
    accepted_poa,
    action_payload,
    appeal_decision_payload,
    appeal_payload,
    assert_cents,
    assert_funds,
    assert_instant_equals,
    assert_meta,
    assert_points,
    assert_posture,
    create_listing,
    credit,
    decide_appeal,
    escalation_payload,
    file_appeal,
    file_snapshot,
    file_violation,
    hold_payload,
    issue_action,
    link_adjudication_payload,
    make_seller_headers,
    open_investigation,
    publish_rule,
    read_action,
    read_holds,
    read_seller,
    register_seller,
    set_clock,
    start_review,
    substantiated_violation,
    validate_error,
    validate_paginated,
    validate_success,
    violation_payload,
)

CLOCK = "2026-08-01T00:00:00.000Z"
DEADLINE = "2026-08-15T00:00:00.000Z"
DAY_AFTER_DEADLINE = "2026-08-16T00:00:00.000Z"

OUTAGE_GROUNDS = (
    "The late shipment cluster was caused by a documented regional carrier "
    "outage that closed two sorting hubs for nine days."
)
OUTAGE_RATIONALE = (
    "The carrier outage notice covers the whole measured period and the "
    "seller's dispatch records match it."
)


# --------------------------------------------------------------------------
# What a report may say about rows that all exist
# --------------------------------------------------------------------------
def _catalogue_with_an_ip_rule_beside_an_ordinary_one(api):
    """Two published rules that differ only in category, and one clean seller, so
    nothing but the category/reporter_type pairing can decide a filing."""
    set_clock(api, CLOCK)
    ip_rule = publish_rule(
        api, code="IP-ELIG-1", category="INTELLECTUAL_PROPERTY",
        base_severity_weight=3.00, removal_scope="ACCOUNT", requires_poa=False,
    )
    ordinary_rule = publish_rule(
        api, code="LA-ELIG-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )
    return seller, ip_rule, ordinary_rule


def test_only_a_rights_owner_may_report_an_intellectual_property_rule(api):
    """PRD §3.5: "And an intellectual-property rule may be cited only by a rights
    owner: a report whose `policy_rule_id` names a rule in category
    `INTELLECTUAL_PROPERTY` while its `reporter_type` is anything other than
    `RIGHTS_OWNER` is refused with `ERR_REPORTER_NOT_ELIGIBLE`, because the
    marketplace does not adjudicate infringement on the word of a buyer, a bot, or
    a regulator."

    Design: Corner/validations/validation_ip_rule_admits_only_a_rights_owner_reporter
    """
    seller, ip_rule, ordinary_rule = _catalogue_with_an_ip_rule_beside_an_ordinary_one(api)

    refused = api.create_violation(
        violation_payload(seller["id"], ip_rule["id"], reporter_type="BUYER",
                          evidence_reference="EV-ELIG-0001"),
        INVESTIGATOR,
    )

    validate_error(refused, ApiErrorId.REPORTER_NOT_ELIGIBLE.value, 422)

    # The identical request from an eligible reporter lands.
    by_rights_owner = validate_success(
        api.create_violation(
            violation_payload(seller["id"], ip_rule["id"], reporter_type="RIGHTS_OWNER",
                              evidence_reference="EV-ELIG-0002"),
            INVESTIGATOR,
        ),
        201,
    )
    assert by_rights_owner["state"] == "REPORTED"
    assert by_rights_owner["auto_generated"] is False

    # And the buyer is welcome outside the intellectual-property category.
    by_buyer = validate_success(
        api.create_violation(
            violation_payload(seller["id"], ordinary_rule["id"], reporter_type="BUYER",
                              evidence_reference="EV-ELIG-0003"),
            INVESTIGATOR,
        ),
        201,
    )
    assert by_buyer["listing_id"] is None

    # Filing alone opens no investigation, so neither dimension moves.
    assert_posture(read_seller(api, seller["id"]), enforcement_state="ACTIVE",
                   disbursement_state="NORMAL", severity_points_balance="0.00")


def _catalogue_with_a_listing_scoped_rule_and_one_active_item(api):
    """The same category and weight under two removal scopes, so the requirement
    for a cited item is the only difference between the two filings."""
    set_clock(api, CLOCK)
    listing_scoped = publish_rule(
        api, code="LS-SCOPE-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="LISTING", requires_poa=False,
    )
    account_scoped = publish_rule(
        api, code="AC-SCOPE-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )
    listing = create_listing(
        api, seller["id"], sku="HT-SKU-001", title="Bench vice, 6 inch",
        category_code="TOOLS-HAND",
    )
    return seller, listing_scoped, account_scoped, listing


def test_a_listing_scoped_rule_demands_the_item_an_account_scoped_one_does_not(api):
    """PRD §3.5: "When the cited rule's `removal_scope` is `LISTING`, the report
    must cite a `listing_id`, since a listing-scoped removal has nothing to remove
    otherwise; omitting it is refused with `ERR_LISTING_REQUIRED_FOR_SCOPE`."

    Design: Corner/validations/validation_listing_scope_rule_demands_a_cited_listing
    """
    seller, listing_scoped, account_scoped, listing = \
        _catalogue_with_a_listing_scoped_rule_and_one_active_item(api)

    refused = api.create_violation(
        violation_payload(seller["id"], listing_scoped["id"], reporter_type="BUYER",
                          evidence_reference="EV-SCOPE-0001"),
        INVESTIGATOR,
    )

    # The field is optional at the endpoint, so this is a coherence failure rather
    # than a request-shape one.
    validate_error(refused, ApiErrorId.LISTING_REQUIRED_FOR_SCOPE.value, 422)

    cited = validate_success(
        api.create_violation(
            violation_payload(seller["id"], listing_scoped["id"], listing_id=listing["id"],
                              reporter_type="BUYER", evidence_reference="EV-SCOPE-0002"),
            INVESTIGATOR,
        ),
        201,
    )
    assert cited["listing_id"] == listing["id"]

    account_wide = validate_success(
        api.create_violation(
            violation_payload(seller["id"], account_scoped["id"], reporter_type="BUYER",
                              evidence_reference="EV-SCOPE-0003"),
            INVESTIGATOR,
        ),
        201,
    )
    assert account_wide["listing_id"] is None

    # Reporting a violation never touches the item it names.
    rows, meta = validate_paginated(
        api.list_seller_listings(seller["id"], make_seller_headers(seller["id"]))
    )
    assert_meta(meta, total_count=1)
    assert rows[0]["state"] == "ACTIVE"
    assert rows[0]["removal_policy_category"] is None


def _two_sellers_one_of_them_holding_the_only_listing(api):
    """Seller A has no catalogue at all; the single ACTIVE listing belongs to B."""
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="LS-OWN-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="LISTING", requires_poa=False,
    )
    seller_a = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )
    seller_b = register_seller(
        api, legal_name="Beacon Hardware LLC", email="ops@beacon-hardware.example",
        tax_id_hash="TAX-BH-0001", payout_bank_token="BANK-BH-0001",
        address_fingerprint="ADDR-BH-0001",
    )
    listing_b = create_listing(
        api, seller_b["id"], sku="BH-SKU-001", title="Impact driver kit",
        category_code="TOOLS-POWER",
    )
    return seller_a, seller_b, rule, listing_b


def test_a_cited_listing_must_belong_to_the_accused_seller(api):
    """PRD §3.5: "When a `listing_id` is cited, that listing must belong to the
    accused seller; citing another seller's item is refused with
    `ERR_LISTING_SELLER_MISMATCH`."

    Design: Corner/validations/validation_cited_listing_must_belong_to_the_cited_seller
    """
    seller_a, seller_b, rule, listing_b = _two_sellers_one_of_them_holding_the_only_listing(api)

    crossed = api.create_violation(
        violation_payload(seller_a["id"], rule["id"], listing_id=listing_b["id"],
                          reporter_type="BUYER", evidence_reference="EV-OWN-0001"),
        INVESTIGATOR,
    )

    # Both rows exist, so this is a comparison of two identifiers and not a 404.
    validate_error(crossed, ApiErrorId.LISTING_SELLER_MISMATCH.value, 422)

    mirrored = validate_success(
        api.create_violation(
            violation_payload(seller_b["id"], rule["id"], listing_id=listing_b["id"],
                              reporter_type="BUYER", evidence_reference="EV-OWN-0002"),
            INVESTIGATOR,
        ),
        201,
    )
    assert mirrored["seller_id"] == seller_b["id"]

    for_a, meta_a = validate_paginated(
        api.list_violations(INVESTIGATOR, {"seller_id": seller_a["id"]})
    )
    assert for_a == [], f"the refused report was filed against A anyway: {for_a}"
    assert_meta(meta_a, total_count=0)


# --------------------------------------------------------------------------
# Identifiers cited on a hold and on an appeal
# --------------------------------------------------------------------------
COVERAGE_START = "2026-08-02T00:00:00.000Z"
COVERAGE_END = "2026-08-05T00:00:00.000Z"


def _one_sellers_action_and_another_sellers_reservable_balance(api):
    """A's action is real and enforceable; B is separately credited and under
    investigation, so B's own hold would be affordable at TIER_1."""
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="LA-XREF-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller_a = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )
    seller_b = register_seller(
        api, legal_name="Beacon Hardware LLC", email="ops@beacon-hardware.example",
        tax_id_hash="TAX-BH-0001", payout_bank_token="BANK-BH-0001",
        address_fingerprint="ADDR-BH-0001",
    )
    violation_a = substantiated_violation(
        api, seller_a["id"], rule["id"], reporter_type="BUYER",
        evidence_reference="EV-XREF-0001",
        decision_note="The condition note on the refurbished units was wrong.",
    )
    action_a = issue_action(api, violation_a["id"])
    credit(api, seller_b["id"], 100000, "PAYOUT-CYCLE-2026-07-X")
    violation_b = file_violation(
        api, seller_b["id"], rule["id"], reporter_type="BUYER",
        evidence_reference="EV-XREF-0002",
    )
    open_investigation(api, violation_b["id"])
    return seller_a, seller_b, action_a


def test_a_hold_may_not_cite_an_action_belonging_to_another_seller(api):
    """PRD §3.9: "A cited `enforcement_action_id` that belongs to a different seller
    than `seller_id` is refused with `ERR_HOLD_ACTION_SELLER_MISMATCH`."

    Design: Corner/validations/validation_hold_may_not_cite_another_sellers_action
    """
    seller_a, seller_b, action_a = \
        _one_sellers_action_and_another_sellers_reservable_balance(api)
    before = read_seller(api, seller_b["id"], INVESTIGATOR)
    assert_posture(before, disbursement_state="RESERVE_HELD")

    crossed = api.create_hold(
        hold_payload(seller_b["id"], COVERAGE_START, COVERAGE_END, before["version"],
                     enforcement_action_id=action_a["id"]),
        INVESTIGATOR,
    )

    validate_error(crossed, ApiErrorId.HOLD_ACTION_SELLER_MISMATCH.value, 422)
    # The refusal consumed no concurrency token, which is what lets the same
    # expected version carry the corrected request.
    assert read_seller(api, seller_b["id"], INVESTIGATOR)["version"] == before["version"]

    corrected = validate_success(
        api.create_hold(
            hold_payload(seller_b["id"], COVERAGE_START, COVERAGE_END, before["version"]),
            INVESTIGATOR,
        ),
        201,
    )

    assert corrected["enforcement_action_id"] is None
    assert corrected["risk_tier"] == "TIER_1"
    # Ten percent of the 100000 sitting on B's account.
    assert_cents(corrected["held_amount_cents"], 10000, "held_amount_cents")
    assert_funds(read_seller(api, seller_b["id"]), available=90000, held=10000,
                 credited=100000, debited=0)
    assert read_holds(api, params={"seller_id": seller_a["id"]}) == []


def _one_accepted_plan_answering_the_first_of_two_actions(api):
    """a1 cites a rule that demands a plan and has an ACCEPTED one; a2 cites a rule
    that demands none, so the milder plan-absence error cannot mask a mismatch."""
    set_clock(api, CLOCK)
    plan_bearing = publish_rule(
        api, code="LA-PLAN-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=True,
    )
    plan_free = publish_rule(
        api, code="SP-PLAN-1", category="SHIPPING_PERFORMANCE", base_severity_weight=3.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )
    first_violation = substantiated_violation(
        api, seller["id"], plan_bearing["id"], reporter_type="BUYER",
        evidence_reference="EV-PLAN-0001",
        decision_note="The catalogue feed mapped the wrong attribute set.",
    )
    first_action = issue_action(api, first_violation["id"])
    plan = accepted_poa(api, first_action["id"], seller["id"])
    second_violation = substantiated_violation(
        api, seller["id"], plan_free["id"], reporter_type="PLATFORM_AUTOMATION",
        evidence_reference="EV-PLAN-0002",
        decision_note="Eleven consecutive dispatches missed their promise date.",
    )
    second_action = issue_action(api, second_violation["id"])
    return seller, first_action, plan, second_action


def test_an_appeal_may_not_cite_a_plan_answering_a_different_action(api):
    """PRD §3.8: "Where the action's snapshotted rule had `requires_poa` true, a plan
    of action for that same action must already be in `ACCEPTED`, and the absence of
    one is refused with `ERR_POA_NOT_ACCEPTED`; a cited `plan_of_action_id` that
    belongs to some other action is refused with `ERR_POA_ACTION_MISMATCH`."

    Design: Corner/validations/validation_appealed_action_must_own_the_cited_plan
    """
    seller, first_action, plan, second_action = \
        _one_accepted_plan_answering_the_first_of_two_actions(api)
    assert plan["state"] == "ACCEPTED"
    # 2.00 + 3.00 in two categories, so the second action restricted the account.
    assert_posture(read_seller(api, seller["id"]), enforcement_state="RESTRICTED",
                   severity_points_balance="5.00")

    borrowed = api.create_appeal(
        appeal_payload(second_action["id"], plan["id"], grounds=OUTAGE_GROUNDS),
        make_seller_headers(seller["id"]),
    )

    validate_error(borrowed, ApiErrorId.POA_ACTION_MISMATCH.value, 422)

    # The citation was optional all along; only its coherence was compulsory.
    filed = validate_success(
        api.create_appeal(
            appeal_payload(second_action["id"], grounds=OUTAGE_GROUNDS),
            make_seller_headers(seller["id"]),
        ),
        201,
    )
    assert filed["plan_of_action_id"] is None
    assert filed["state"] == "SUBMITTED"
    assert filed["enforcement_action_id"] == second_action["id"]

    against_first, meta = validate_paginated(
        api.list_appeals(REVIEWER, {"enforcement_action_id": first_action["id"]})
    )
    assert against_first == [], f"an appeal appeared against a1: {against_first}"
    assert_meta(meta, total_count=0)
    assert validate_success(api.get_plan_of_action(plan["id"], OFFICER))["state"] == "ACCEPTED"


def _six_open_claims_against_a_hundred_thousand_cents(api):
    """One window filed purely for its pending-claim count, so the exposure basis
    prices 54000 cents against a 100000-cent balance at TIER_1."""
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="LA-AGG-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )
    credit(api, seller["id"], 100000, "PAYOUT-CYCLE-2026-07-A")
    file_snapshot(
        api, seller["id"], "2026-07-01T00:00:00.000Z", "2026-08-01T00:00:00.000Z",
        order_volume=100, delivered_or_refunded_volume=100, defect_claims_pending=6,
        defect_claims_substantiated=0, late_shipments=0, pre_fulfillment_cancellations=0,
        shipments_total=100, shipments_with_valid_tracking=100,
    )
    violation = file_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER",
        evidence_reference="EV-AGG-0001",
    )
    open_investigation(api, violation["id"])
    return seller


def test_a_second_exposure_reserve_is_measured_against_what_is_left(api):
    """PRD §3.9: "An exposure reserve ignores the balance entirely, which means it
    can exceed it; there is deliberately **no** implicit clamp to the available
    balance, so a claim-exposure reserve larger than `available_balance_cents` is
    refused with `ERR_HOLD_EXCEEDS_AVAILABLE` rather than being quietly reduced."

    Design: Corner/validations/validation_reserve_holds_are_capped_by_the_collective_balance
    """
    seller = _six_open_claims_against_a_hundred_thousand_cents(api)
    opening = read_seller(api, seller["id"], INVESTIGATOR)
    assert opening["open_defect_claim_units"] == 6

    first = validate_success(
        api.create_hold(
            hold_payload(seller["id"], COVERAGE_START, COVERAGE_END, opening["version"],
                         reserve_basis="CLAIM_EXPOSURE"),
            INVESTIGATOR,
        ),
        201,
    )
    # 6 claims x 9000 cents x the TIER_1 multiplier of 1.00.
    assert_cents(first["held_amount_cents"], 54000, "held_amount_cents")
    between = read_seller(api, seller["id"], INVESTIGATOR)
    assert_funds(between, available=46000, held=54000, credited=100000, debited=0)

    # The same 54000, forty-eight hours clear of the first interval, is now
    # unaffordable because only 46000 remains available.
    second = api.create_hold(
        hold_payload(seller["id"], "2026-08-07T00:00:00.000Z", "2026-08-10T00:00:00.000Z",
                     between["version"], reserve_basis="CLAIM_EXPOSURE"),
        INVESTIGATOR,
    )

    validate_error(second, ApiErrorId.HOLD_EXCEEDS_AVAILABLE.value, 422)
    rows, meta = validate_paginated(api.list_holds(OFFICER, {"seller_id": seller["id"]}))
    assert_meta(meta, total_count=1)
    assert [row["id"] for row in rows] == [first["id"]]
    assert rows[0]["state"] == "ACTIVE"
    after = read_seller(api, seller["id"], INVESTIGATOR)
    assert_funds(after, available=46000, held=54000, credited=100000, debited=0)
    assert after["version"] == between["version"]


# --------------------------------------------------------------------------
# A closed window and the two gates that overrule an operator
# --------------------------------------------------------------------------
ESCALATION_GROUNDS = (
    "New carrier evidence became available only after the first-level decision "
    "was issued, and it covers every disputed dispatch."
)


def _a_denial_recorded_on_the_first_of_august(api):
    """The denial is decided at the pinned clock reading, so the escalation window
    it mints is exactly fourteen days wide and known in advance."""
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="LA-ESC-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )
    violation = substantiated_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER",
        evidence_reference="EV-ESC-0001",
        decision_note="The archived listing text contradicts the seller's account.",
    )
    action = issue_action(api, violation["id"])
    appeal = file_appeal(api, action["id"], seller["id"], grounds=OUTAGE_GROUNDS)
    start_review(api, appeal["id"], REVIEWER)
    denied = decide_appeal(
        api, appeal["id"], "DENIED", "EVIDENCE_UPHELD",
        rationale="The archived listing snapshot contradicts the seller's account "
                  "of the description.",
        headers=REVIEWER,
    )
    return seller, action, denied


def test_an_escalation_is_refused_a_day_late_and_admitted_on_the_deadline(api):
    """PRD §3.8: "The appeal must be in `DENIED`, the acting seller must own the
    appealed action, and the clock reading must be at or before
    `escalation_deadline_at`; a strictly later reading is refused with
    `ERR_ESCALATION_WINDOW_CLOSED`."

    Design: Corner/validations/validation_escalation_is_refused_after_the_window_closes
    """
    seller, action, denied = _a_denial_recorded_on_the_first_of_august(api)
    # decided_at 2026-08-01 plus fourteen days.
    assert_instant_equals(denied["escalation_deadline_at"], DEADLINE,
                          "escalation_deadline_at")

    set_clock(api, DAY_AFTER_DEADLINE)
    too_late = api.escalate_appeal(
        denied["id"], escalation_payload(ESCALATION_GROUNDS),
        make_seller_headers(seller["id"]),
    )

    validate_error(too_late, ApiErrorId.ESCALATION_WINDOW_CLOSED.value, 422)
    assert validate_success(api.get_appeal(denied["id"], REVIEWER))["state"] == "DENIED"

    set_clock(api, DEADLINE)
    escalated = validate_success(
        api.escalate_appeal(
            denied["id"], escalation_payload(ESCALATION_GROUNDS),
            make_seller_headers(seller["id"]),
        ),
        200,
    )

    # The boundary is inclusive, and it is measured from the decision rather than
    # from the action's issuance.
    assert escalated["state"] == "ESCALATED_REVIEW"
    assert_instant_equals(escalated["escalation_requested_at"], DEADLINE,
                          "escalation_requested_at")
    assert read_action(api, action["id"])["state"] == "UPHELD"
    assert_posture(read_seller(api, seller["id"]), enforcement_state="WATCHLIST",
                   severity_points_balance="2.00")


def _a_substantiated_eight_point_shipping_violation(api):
    """8.00 points on a clean account compute a LISTING_REMOVAL rung, which leaves
    exactly one rung above and one below it to aim an override at."""
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="SP-OVR-1", category="SHIPPING_PERFORMANCE", base_severity_weight=8.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )
    violation = substantiated_violation(
        api, seller["id"], rule["id"], reporter_type="PLATFORM_AUTOMATION",
        evidence_reference="EV-OVR-0001",
        decision_note="The dispatch scans confirm a sustained late-shipment cluster.",
    )
    return seller, violation


def test_an_override_equal_to_the_computed_rung_is_no_more_severe_than_it(api):
    """PRD §3.6: "On the severity ordering where `WARNING` is milder than
    `LISTING_REMOVAL`, which is milder than `ACCOUNT_SUSPENSION`, an override is
    honoured only when it is **strictly more severe** than the computed rung; an
    override equal to or milder than the computed rung is refused with
    `ERR_OVERRIDE_NOT_MORE_SEVERE`."

    Design: Corner/validations/validation_override_must_be_strictly_more_severe_than_the_rung
    """
    seller, violation = _a_substantiated_eight_point_shipping_violation(api)

    milder = api.create_enforcement_action(
        action_payload(violation["id"], "WARNING"), INVESTIGATOR
    )
    equal = api.create_enforcement_action(
        action_payload(violation["id"], "LISTING_REMOVAL"), INVESTIGATOR
    )

    validate_error(milder, ApiErrorId.OVERRIDE_NOT_MORE_SEVERE.value, 422)
    validate_error(equal, ApiErrorId.OVERRIDE_NOT_MORE_SEVERE.value, 422)

    # Neither refusal issued anything, so the violation is still issuable.
    aggravated = validate_success(
        api.create_enforcement_action(
            action_payload(violation["id"], "ACCOUNT_SUSPENSION"), INVESTIGATOR
        ),
        201,
    )

    assert aggravated["ladder_rung_computed"] == "LISTING_REMOVAL"
    assert aggravated["action_type"] == "ACCOUNT_SUSPENSION"
    assert aggravated["override_applied"] is True
    assert_points(aggravated["severity_points_applied"], "8.00", "severity_points_applied")

    after = read_seller(api, seller["id"])
    # The suspension comes from the honoured override, not from the 8.00 balance.
    assert_posture(after, enforcement_state="SUSPENDED", disbursement_state="FULL_HOLD",
                   severity_points_balance="8.00")
    rows, meta = validate_paginated(
        api.list_enforcement_actions(INVESTIGATOR, {"violation_id": violation["id"]})
    )
    assert_meta(meta, total_count=1)
    assert [row["id"] for row in rows] == [aggravated["id"]]


def _three_listing_accuracy_actions_and_an_appeal_against_the_third(api):
    """The repeat count excludes the appealed action itself, so three actions in one
    category are what it takes to reach the threshold of two."""
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="LA-REP-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )
    actions = []
    for index in (1, 2, 3):
        violation = substantiated_violation(
            api, seller["id"], rule["id"], reporter_type="BUYER",
            evidence_reference=f"EV-REP-000{index}",
            decision_note="The same buyer complaint was confirmed against a fresh order.",
        )
        actions.append(issue_action(api, violation["id"]))
    appeal = file_appeal(api, actions[2]["id"], seller["id"], grounds=OUTAGE_GROUNDS)
    start_review(api, appeal["id"], REVIEWER)
    return seller, actions, appeal


def test_the_reviewer_of_a_third_same_category_action_may_only_deny(api):
    """PRD §3.8: "Where that count reaches 2 or more, a `GRANTED` outcome is refused
    with `ERR_REPEAT_OFFENSE_DENIAL` and the reviewer must deny instead, recording
    `denial_reason` `REPEAT_OFFENSE`."

    Design: Corner/validations/validation_repeat_offender_cannot_be_reinstated
    """
    seller, actions, appeal = _three_listing_accuracy_actions_and_an_appeal_against_the_third(api)
    # 2.00, then 2.00 x 1.25, then 2.00 x 1.50.
    assert_points(actions[1]["severity_points_applied"], "2.50", "severity_points_applied")
    assert_points(actions[2]["severity_points_applied"], "3.00", "severity_points_applied")

    grant = api.decide_appeal(
        appeal["id"],
        appeal_decision_payload(
            "GRANTED",
            rationale="The reviewer judged the underlying buyer complaint to be "
                      "unsupported by the evidence.",
        ),
        REVIEWER,
    )

    # A compliance gate, not an authorisation failure: ar-1 is a permitted decider
    # and inv-1 issued the action, so segregation is satisfied.
    validate_error(grant, ApiErrorId.REPEAT_OFFENSE_DENIAL.value, 422)
    assert validate_success(api.get_appeal(appeal["id"], REVIEWER))["state"] == "UNDER_REVIEW"
    assert read_action(api, actions[2]["id"])["state"] == "ISSUED"

    denial = validate_success(
        api.decide_appeal(
            appeal["id"],
            appeal_decision_payload(
                "DENIED", "REPEAT_OFFENSE",
                rationale="Two prior listing-accuracy notices stand, so reinstatement "
                          "is unavailable under policy.",
            ),
            REVIEWER,
        ),
        200,
    )

    assert denial["state"] == "DENIED"
    assert denial["denial_reason"] == "REPEAT_OFFENSE"
    assert denial["reinstatement_granted"] is False
    assert_instant_equals(denial["escalation_deadline_at"], DEADLINE,
                          "escalation_deadline_at")

    upheld = read_action(api, actions[2]["id"])
    assert upheld["state"] == "UPHELD"
    assert upheld["resolution_reason"] == "APPEAL_DENIED"
    assert_posture(read_seller(api, seller["id"]), enforcement_state="RESTRICTED",
                   severity_points_balance="7.50")


def _a_suspended_incumbent_and_a_flagged_new_registration(api):
    """The incumbent is suspended rather than banned, which is enough to raise the
    candidate's risk flag but deliberately not enough to confirm the link."""
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="SP-LINK-1", category="SHIPPING_PERFORMANCE", base_severity_weight=8.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    incumbent = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-SHARED", payout_bank_token="BANK-SHARED",
        address_fingerprint="ADDR-HT-0001",
    )
    violation = substantiated_violation(
        api, incumbent["id"], rule["id"], reporter_type="PLATFORM_AUTOMATION",
        evidence_reference="EV-LINK-0001",
        decision_note="Dispatch scans confirm a sustained late-shipment cluster.",
    )
    issue_action(api, violation["id"], action_type_override="ACCOUNT_SUSPENSION")
    candidate = register_seller(
        api, legal_name="Beacon Hardware LLC", email="ops@beacon-hardware.example",
        tax_id_hash="TAX-SHARED", payout_bank_token="BANK-SHARED",
        address_fingerprint="ADDR-BH-0001",
    )
    links, _ = validate_paginated(
        api.list_related_account_links(OFFICER, {"candidate_seller_id": candidate["id"]})
    )
    assert len(links) == 1, f"expected exactly one link, got {links}"
    return incumbent, candidate, links[0]


def test_a_link_to_a_merely_suspended_incumbent_cannot_be_confirmed(api):
    """PRD §3.1: "A link to an incumbent who was merely suspended at detection cannot
    be confirmed at all, and the attempt is refused with `ERR_LINK_MATCH_NOT_BANNED`
    — suspension is a reversible sanction and a suspended seller's relatives are
    not, by that fact alone, evading a ban."

    Design: Corner/validations/validation_link_confirmation_requires_a_banned_match
    """
    incumbent, candidate, link = _a_suspended_incumbent_and_a_flagged_new_registration(api)
    assert_posture(read_seller(api, incumbent["id"]), enforcement_state="SUSPENDED")
    assert read_seller(api, incumbent["id"])["ban_reason"] is None
    # 0.35 for the tax id plus 0.45 for the payout token.
    assert_points(link["confidence_score"], "0.80", "confidence_score")
    assert link["matched_signals"] == ["TAX_ID", "BANK_TOKEN"]
    assert link["matched_seller_state_at_detection"] == "SUSPENDED"
    assert link["state"] == "DETECTED"
    assert candidate["registration_risk_flag"] is True
    assert candidate["root_seller_id"] == incumbent["id"]
    assert_posture(read_seller(api, candidate["id"]), enforcement_state="WATCHLIST",
                   disbursement_state="RESERVE_HELD")

    confirmation = api.adjudicate_related_account_link(
        link["id"],
        link_adjudication_payload(
            "CONFIRMED",
            "Shared tax id and payout token with a suspended account.",
        ),
        OFFICER,
    )

    validate_error(confirmation, ApiErrorId.LINK_MATCH_NOT_BANNED.value, 422)
    assert validate_success(api.get_related_account_link(link["id"], OFFICER))["state"] == \
        "DETECTED"
    assert_posture(read_seller(api, candidate["id"]), enforcement_state="WATCHLIST")

    dismissal = validate_success(
        api.adjudicate_related_account_link(
            link["id"],
            link_adjudication_payload(
                "DISMISSED",
                "The shared payout token belongs to a legitimate shared factoring "
                "provider.",
            ),
            OFFICER,
        ),
        200,
    )

    # Dismissal is the reachable decision, and it unwinds both dimensions because
    # no other link points at the candidate.
    assert dismissal["state"] == "DISMISSED"
    cleared = read_seller(api, candidate["id"])
    assert cleared["registration_risk_flag"] is False
    assert cleared["ban_reason"] is None
    assert_posture(cleared, enforcement_state="ACTIVE", disbursement_state="NORMAL",
                   severity_points_balance="0.00")
    assert_posture(read_seller(api, incumbent["id"]), enforcement_state="SUSPENDED")
