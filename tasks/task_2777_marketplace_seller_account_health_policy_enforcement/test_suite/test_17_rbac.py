"""The role boundary itself, in both directions: the writes each role owns
exclusively, the reads that are genuinely shared and the two that are not, the
ownership line a seller may not read across, and the four segregation rules that
compare human identifiers rather than role names.
"""

from test_helpers import (
    ANONYMOUS,
    APPEAL_REVIEWER_ALT_USER_ID,
    APPEAL_REVIEWER_USER_ID,
    COMPLIANCE_OFFICER_USER_ID,
    INVESTIGATOR,
    INVESTIGATOR_USER_ID,
    OFFICER,
    OFFICER_ALT,
    REVIEWER,
    REVIEWER_ALT,
    ApiErrorId,
    NON_EXISTENT_UUID,
    appeal_payload,
    assert_cents,
    assert_funds,
    assert_instant_equals,
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
    hold_payload,
    issue_action,
    listing_payload,
    make_appeal_reviewer_headers,
    make_compliance_officer_headers,
    make_seller_headers,
    open_investigation,
    poa_payload,
    policy_rule_payload,
    publish_rule,
    read_action,
    read_holds,
    read_listings,
    read_seller,
    register_seller,
    review_poa,
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
NEXT_DAY = "2026-08-02T00:00:00.000Z"

GROUNDS = "The cited attribute came from the manufacturer feed for that exact part number."
DENIAL_RATIONALE = "The feed extract on file does not cover the reported period at all."
ESCALATION_GROUNDS = "A dated manufacturer extract covering the reported period is attached."
FINAL_RATIONALE = "The dated extract still does not cover the period the report concerns."
PLAN_ROOT_CAUSE = (
    "Our supplier feed mapped compatibility attributes onto the wrong parent listing."
)
PLAN_CORRECTIVE = ["Corrected the attribute mapping for every affected listing"]
PLAN_PREVENTIVE = ["Nightly automated diff of the feed against the published catalogue"]

# The identity signals of the second seller are disjoint from the first's, so
# registration detection cannot mint a link and disturb either posture.
PEER = {
    "legal_name": "Delta Supply Co", "email": "ops@delta-supply.example",
    "tax_id_hash": "TAX-DS-0002", "payout_bank_token": "BANK-DS-0002",
    "address_fingerprint": "ADDR-DS-0002",
}


def _harbor_tools(api, **overrides):
    payload = {"legal_name": "Harbor Tools LLC", "email": "ops@harbor-tools.example",
               "tax_id_hash": "TAX-HT-0001", "payout_bank_token": "BANK-HT-0001",
               "address_fingerprint": "ADDR-HT-0001"}
    payload.update(overrides)
    return register_seller(api, **payload)


def _issued_warning(api, code, evidence_reference, requires_poa=False, seller=None):
    """A two-point account-scoped rule carried to its WARNING rung by inv-1, so every
    row a role probe is aimed at exists and sits in the state its endpoint demands."""
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code=code, category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=requires_poa,
    )
    seller = seller if seller is not None else _harbor_tools(api)
    violation = substantiated_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER",
        evidence_reference=evidence_reference,
        decision_note="The compatibility list on the listing named a part it does not fit.",
    )
    action = issue_action(api, violation["id"])
    return seller, rule, action


# --------------------------------------------------------------------------
# Exclusive writes, one role at a time
# --------------------------------------------------------------------------
def test_no_operator_may_act_in_the_sellers_place(api):
    """PRD §2.1: "Once the caller is authenticated, the server checks the acting role
    against the roles the target endpoint admits, and rejects a role that does not
    appear in that list with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/rbac_seller_only_writes_cannot_be_performed_by_any_operator
    """
    seller, _, action = _issued_warning(api, "LA-RB1-1", "EV-RB1-0001", requires_poa=True)
    listing = create_listing(
        api, seller["id"], sku="SKU-RB1-0001", title="18V Cordless Drill",
        category_code="TOOLS",
    )
    assert action["state"] == "ISSUED"

    probes = [
        ("POST /listings",
         lambda: api.create_listing(
             listing_payload(seller["id"], sku="SKU-RB1-0002", title="Operator Listing",
                             category_code="TOOLS"),
             OFFICER)),
        ("POST /listings/{id}/relist",
         lambda: api.relist_listing(listing["id"], INVESTIGATOR)),
        ("POST /enforcement-actions/{id}/acknowledge",
         lambda: api.acknowledge_action(action["id"], INVESTIGATOR)),
        ("POST /plans-of-action",
         lambda: api.create_plan_of_action(
             poa_payload(action["id"], action["version"], root_cause=PLAN_ROOT_CAUSE,
                         corrective_measures=PLAN_CORRECTIVE,
                         preventive_measures=PLAN_PREVENTIVE),
             OFFICER)),
        ("POST /appeals",
         lambda: api.create_appeal(appeal_payload(action["id"], grounds=GROUNDS), REVIEWER)),
        # A dead appeal id, to show the role check answers before path existence.
        ("POST /appeals/{id}/escalate",
         lambda: api.escalate_appeal(
             NON_EXISTENT_UUID, {"escalation_grounds": ESCALATION_GROUNDS}, OFFICER)),
    ]

    for label, call in probes:
        response = call()
        assert response.status_code == 403, \
            f"{label} answered {response.status_code}: {response.text}"
        validate_error(response, ApiErrorId.UNAUTHORIZED.value, 403)

    assert [row["id"] for row in read_listings(api, seller["id"])] == [listing["id"]]
    plans, plan_meta = validate_paginated(api.list_plans_of_action(OFFICER))
    assert plans == [] and plan_meta["total_count"] == 0
    appeals, appeal_meta = validate_paginated(api.list_appeals(REVIEWER))
    assert appeals == [] and appeal_meta["total_count"] == 0
    unmoved = read_action(api, action["id"])
    assert unmoved["state"] == "ISSUED"
    assert unmoved["version"] == action["version"]
    assert unmoved["acknowledged_at"] is None


def test_filing_a_report_is_shared_but_running_the_case_is_not(api):
    """PRD §2.1: "`PolicyInvestigator` files, investigates and adjudicates violations,
    issues enforcement actions, and opens reserve holds."

    Design: Corner/rbac/rbac_investigator_only_writes_cannot_be_performed_by_officers_or_reviewers
    """
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="LA-RB2-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = _harbor_tools(api)

    # Filing is genuinely shared: the officer's own report is accepted.
    filed = file_violation(
        api, seller["id"], rule["id"], reporter_type="REGULATOR",
        evidence_reference="EV-RB2-0001", headers=OFFICER,
    )
    assert filed["state"] == "REPORTED"
    version = read_seller(api, seller["id"], OFFICER)["version"]

    probes = [
        ("POST /violations/{id}/open-investigation",
         lambda: api.open_investigation(filed["id"], OFFICER)),
        ("POST /violations/{id}/adjudicate",
         lambda: api.adjudicate_violation(filed["id"], {"outcome": "SUBSTANTIATED"}, REVIEWER)),
        # The role check answers before the "not substantiated" state check.
        ("POST /enforcement-actions",
         lambda: api.create_enforcement_action({"violation_id": filed["id"]}, OFFICER)),
        # And before the funds-posture gate on hold creation.
        ("POST /disbursement-holds",
         lambda: api.create_hold(
             hold_payload(seller["id"], NEXT_DAY, "2026-08-05T00:00:00.000Z", version),
             OFFICER)),
    ]

    for label, call in probes:
        response = call()
        assert response.status_code == 403, \
            f"{label} answered {response.status_code}: {response.text}"
        validate_error(response, ApiErrorId.UNAUTHORIZED.value, 403)

    assert validate_success(api.get_violation(filed["id"], INVESTIGATOR))["state"] == "REPORTED"
    actions, action_meta = validate_paginated(api.list_enforcement_actions(INVESTIGATOR))
    assert actions == [] and action_meta["total_count"] == 0
    assert read_holds(api, params={"seller_id": seller["id"]}) == []


def test_the_two_levels_of_appeal_review_belong_to_two_different_roles(api):
    """PRD §2.1: "`AppealReviewer` decides first-level appeals."

    Design: Corner/rbac/rbac_appeal_review_steps_cannot_be_performed_by_the_officer_or_the_investigator
    """
    seller, _, action = _issued_warning(api, "LA-RB3-1", "EV-RB3-0001")
    appeal = file_appeal(api, action["id"], seller["id"], grounds=GROUNDS)
    assert appeal["state"] == "SUBMITTED"

    probes = [
        ("POST /appeals/{id}/start-review",
         lambda: api.start_appeal_review(appeal["id"], OFFICER)),
        ("POST /appeals/{id}/decide",
         lambda: api.decide_appeal(
             appeal["id"], {"outcome": "GRANTED", "rationale": DENIAL_RATIONALE}, OFFICER)),
        # Refused on the role even though the appeal is not in ESCALATED_REVIEW.
        ("POST /appeals/{id}/escalation-decision",
         lambda: api.decide_escalation(
             appeal["id"],
             {"outcome": "FINAL_DENIED", "denial_reason": "EVIDENCE_UPHELD",
              "rationale": FINAL_RATIONALE},
             REVIEWER)),
    ]

    for label, call in probes:
        response = call()
        assert response.status_code == 403, \
            f"{label} answered {response.status_code}: {response.text}"
        validate_error(response, ApiErrorId.UNAUTHORIZED.value, 403)

    unmoved = validate_success(api.get_appeal(appeal["id"], REVIEWER))
    assert unmoved["state"] == "SUBMITTED"
    assert unmoved["decided_by_user_id"] is None
    assert read_action(api, action["id"])["state"] == "ISSUED"


def test_the_rulebook_the_feed_and_the_money_are_closed_to_the_investigator(api):
    """PRD §2.1: "`ComplianceOfficer` owns the policy catalogue, the metric feed,
    seller funds, plan-of-action review, escalation decisions, and related-account
    adjudication." And PRD §3.4: "Evaluating a seller's account health is a
    `PolicyInvestigator` or `ComplianceOfficer` capability that takes no payload
    whatsoever: the subject comes from the seller identified in the request path, and
    every input comes from snapshots already on file."

    Design: Corner/rbac/rbac_officer_only_writes_cannot_be_performed_by_the_investigator_or_reviewer
    """
    set_clock(api, CLOCK)
    seller = _harbor_tools(api)
    filed = file_snapshot(
        api, seller["id"], "2026-07-01T00:00:00.000Z", CLOCK,
        order_volume=400, delivered_or_refunded_volume=400, defect_claims_pending=1,
        defect_claims_substantiated=2, late_shipments=4, pre_fulfillment_cancellations=2,
        shipments_total=400, shipments_with_valid_tracking=396, source="PLATFORM_PIPELINE",
    )

    probes = [
        ("POST /policy-rules",
         lambda: api.create_policy_rule(
             policy_rule_payload(code="LA-RB4-1", category="LISTING_ACCURACY",
                                 base_severity_weight=2.00, removal_scope="ACCOUNT"),
             INVESTIGATOR)),
        ("POST /metric-snapshots",
         lambda: api.create_snapshot(
             snapshot_payload(seller["id"], CLOCK, "2026-09-01T00:00:00.000Z",
                              order_volume=100, delivered_or_refunded_volume=100,
                              defect_claims_pending=3, defect_claims_substantiated=9,
                              late_shipments=1, pre_fulfillment_cancellations=1,
                              shipments_total=100, shipments_with_valid_tracking=99),
             INVESTIGATOR)),
        ("POST /sellers/{id}/proceeds-credits",
         lambda: api.credit_proceeds(seller["id"], {"amount_cents": 50000}, INVESTIGATOR)),
        # Refused on the role, not on the dead link id.
        ("POST /related-account-links/{id}/adjudicate",
         lambda: api.adjudicate_related_account_link(
             NON_EXISTENT_UUID, {"decision": "CONFIRMED"}, REVIEWER)),
    ]

    for label, call in probes:
        response = call()
        assert response.status_code == 403, \
            f"{label} answered {response.status_code}: {response.text}"
        validate_error(response, ApiErrorId.UNAUTHORIZED.value, 403)

    rules, rule_meta = validate_paginated(api.list_policy_rules(OFFICER))
    assert rules == [] and rule_meta["total_count"] == 0
    on_file = validate_success(api.list_seller_snapshots(seller["id"], OFFICER))
    assert [row["id"] for row in on_file] == [filed["id"]]
    assert_funds(read_seller(api, seller["id"]), available=0, held=0, credited=0, debited=0)

    # The complementary positive: the investigator may read the feed it cannot write.
    evaluation = validate_success(
        api.create_health_evaluation(seller["id"], INVESTIGATOR), 201
    )

    assert evaluation["breached_metrics"] == []
    assert evaluation["metric_tier"] == "HEALTHY"
    assert_points(evaluation["health_score"], "100.00", "health_score")
    assert evaluation["auto_violation_id"] is None


def test_registration_is_the_registrants_alone_and_it_may_read_nothing(api):
    """PRD §2.1: "Seller registration is the only operation this role may perform, and
    it is the only role that may perform it."

    Design: Corner/rbac/rbac_registration_is_anonymous_only_and_anonymous_cannot_read
    """
    set_clock(api, CLOCK)
    publish_rule(
        api, code="LA-RB5-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT",
    )
    seller = _harbor_tools(api)

    probes = [
        ("POST /sellers as ComplianceOfficer",
         lambda: api.register_seller(
             seller_payload(legal_name="Officer Registered LLC",
                            email="ops@officer-registered.example",
                            tax_id_hash="TAX-OR-0001", payout_bank_token="BANK-OR-0001",
                            address_fingerprint="ADDR-OR-0001"),
             OFFICER)),
        ("POST /sellers as Seller",
         lambda: api.register_seller(
             seller_payload(legal_name="Seller Registered LLC",
                            email="ops@seller-registered.example",
                            tax_id_hash="TAX-SR-0001", payout_bank_token="BANK-SR-0001",
                            address_fingerprint="ADDR-SR-0001"),
             make_seller_headers(seller["id"]))),
        # The registrant is not a permissive fallback: it reads nothing at all.
        ("GET /policy-rules as Anonymous", lambda: api.list_policy_rules(ANONYMOUS)),
        ("GET /sellers/{id} as Anonymous", lambda: api.get_seller(seller["id"], ANONYMOUS)),
    ]

    for label, call in probes:
        response = call()
        assert response.status_code == 403, \
            f"{label} answered {response.status_code}: {response.text}"
        validate_error(response, ApiErrorId.UNAUTHORIZED.value, 403)

    rows, meta = validate_paginated(api.list_sellers(OFFICER))
    assert [row["id"] for row in rows] == [seller["id"]]
    assert meta["total_count"] == 1


def test_operator_reads_are_shared_except_the_feed_and_the_notification_trail(api):
    """PRD §2.1: "Once the caller is authenticated, the server checks the acting role
    against the roles the target endpoint admits, and rejects a role that does not
    appear in that list with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/rbac_operator_reads_are_shared_except_two_asymmetric_paths
    """
    set_clock(api, CLOCK)
    publish_rule(
        api, code="LA-RB6-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT",
    )
    seller = _harbor_tools(api)
    file_snapshot(
        api, seller["id"], "2026-07-01T00:00:00.000Z", CLOCK,
        order_volume=400, delivered_or_refunded_volume=400, defect_claims_pending=1,
        defect_claims_substantiated=2, late_shipments=4, pre_fulfillment_cancellations=2,
        shipments_total=400, shipments_with_valid_tracking=396,
    )
    owner = make_seller_headers(seller["id"])

    # The seller row is readable by every operator and by its owner.
    for headers in (REVIEWER, INVESTIGATOR, owner):
        assert validate_success(api.get_seller(seller["id"], headers))["id"] == seller["id"]
    # The rulebook is shared with the seller as well.
    catalogue, catalogue_meta = validate_paginated(api.list_policy_rules(owner))
    assert [row["code"] for row in catalogue] == ["LA-RB6-1"]
    assert catalogue_meta["total_count"] == 1
    # The raw feed is open to the investigator and the trail to the reviewer.
    assert len(validate_success(api.list_seller_snapshots(seller["id"], INVESTIGATOR))) == 1
    validate_success(api.list_seller_notifications(seller["id"], REVIEWER))

    hidden_feed = api.list_seller_snapshots(seller["id"], REVIEWER)
    hidden_trail = api.list_seller_notifications(seller["id"], INVESTIGATOR)

    # Two carve-outs in opposite directions, which "all operators read everything"
    # cannot reproduce.
    validate_error(hidden_feed, ApiErrorId.UNAUTHORIZED.value, 403)
    validate_error(hidden_trail, ApiErrorId.UNAUTHORIZED.value, 403)


def test_a_seller_cannot_read_across_the_ownership_boundary(api):
    """PRD §2.1: "Concretely, a `Seller` caller may only reach a listing whose
    `seller_id` equals `X-User-ID`, an enforcement action whose `seller_id` equals
    `X-User-ID`, a plan of action or appeal whose enforcement action's `seller_id`
    equals `X-User-ID`, and a seller-scoped path whose seller identifier equals
    `X-User-ID`."

    Design: Corner/rbac/rbac_seller_reads_cannot_cross_the_ownership_boundary
    """
    set_clock(api, CLOCK)
    seller_a = _harbor_tools(api)
    seller_b = register_seller(api, **PEER)
    _, _, action_b = _issued_warning(api, "LA-RB7-1", "EV-RB7-0001", seller=seller_b)

    # Disjoint identity signals, so no link exists to disturb either posture.
    assert seller_b["registration_risk_flag"] is False
    links, link_meta = validate_paginated(api.list_related_account_links(OFFICER))
    assert links == [] and link_meta["total_count"] == 0

    peer = make_seller_headers(seller_a["id"])
    probes = [
        ("GET /sellers/{id}", lambda: api.get_seller(seller_b["id"], peer)),
        ("GET /sellers/{id}/listings", lambda: api.list_seller_listings(seller_b["id"], peer)),
        ("GET /sellers/{id}/notifications",
         lambda: api.list_seller_notifications(seller_b["id"], peer)),
        ("GET /enforcement-actions/{id}",
         lambda: api.get_enforcement_action(action_b["id"], peer)),
    ]

    for label, call in probes:
        response = call()
        # The Seller role IS granted these reads and the rows do exist, so neither
        # ERR_UNAUTHORIZED nor a 404 would be the right answer.
        assert response.status_code == 403, \
            f"{label} answered {response.status_code}: {response.text}"
        validate_error(response, ApiErrorId.NOT_RESOURCE_OWNER.value, 403)

    own = validate_success(
        api.get_enforcement_action(action_b["id"], make_seller_headers(seller_b["id"]))
    )
    assert own["state"] == "ISSUED"


# --------------------------------------------------------------------------
# Segregation of duties: the guard keys on the human, never on the role
# --------------------------------------------------------------------------
GRANT_RATIONALE = (
    "The manufacturer sheet dated before the report supports the disputed attribute."
)
REVIEW_NOTES = "Root cause and both measure sets are specific and verifiable."


def test_the_issuer_may_not_review_the_appeal_even_wearing_the_reviewers_role(api):
    """PRD §2.7: "Taking an appeal under review, and deciding it at first level,
    require the acting user to differ from the `issued_by_user_id` of the enforcement
    action under appeal."

    Design: Corner/rbac/rbac_appeal_reviewer_cannot_review_an_action_it_issued_itself
    """
    seller, _, action = _issued_warning(api, "LA-SOD1-1", "EV-SOD1-0001")
    appeal = file_appeal(api, action["id"], seller["id"], grounds=GROUNDS)
    assert action["issued_by_user_id"] == INVESTIGATOR_USER_ID
    # A valid AppealReviewer role worn by the human who issued the action.
    tainted = make_appeal_reviewer_headers(INVESTIGATOR_USER_ID)

    refused_start = api.start_appeal_review(appeal["id"], tainted)

    validate_error(refused_start, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)
    assert validate_success(api.get_appeal(appeal["id"], REVIEWER))["state"] == "SUBMITTED"

    # Both steps are gated independently: barring only the decision would let the
    # issuer take the appeal under review and stall it there.
    assert start_review(api, appeal["id"], REVIEWER)["state"] == "UNDER_REVIEW"

    refused_decision = api.decide_appeal(
        appeal["id"], {"outcome": "GRANTED", "rationale": GRANT_RATIONALE}, tainted
    )

    validate_error(refused_decision, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)
    assert validate_success(api.get_appeal(appeal["id"], REVIEWER))["state"] == "UNDER_REVIEW"
    assert read_action(api, action["id"])["state"] == "ISSUED"

    granted = decide_appeal(
        api, appeal["id"], "GRANTED", rationale=GRANT_RATIONALE, headers=REVIEWER_ALT
    )

    assert granted["state"] == "GRANTED"
    assert granted["decided_by_user_id"] == APPEAL_REVIEWER_ALT_USER_ID
    # The vacated rung was a warning, so no reinstatement follows the grant.
    assert granted["reinstatement_granted"] is False
    assert read_action(api, action["id"])["state"] == "VACATED"


def test_the_final_level_bars_both_the_first_decider_and_the_issuer(api):
    """PRD §2.7: "Deciding an escalation requires the acting user to differ from
    **both** the `decided_by_user_id` of the first-level decision **and** the
    `issued_by_user_id` of the enforcement action. Either match is a rejection."

    Design: Corner/rbac/rbac_escalation_officer_cannot_be_the_first_level_decider_or_the_issuer
    """
    seller, _, action = _issued_warning(api, "LA-SOD2-1", "EV-SOD2-0001")
    appeal = file_appeal(api, action["id"], seller["id"], grounds=GROUNDS)
    start_review(api, appeal["id"], REVIEWER)
    denied = decide_appeal(
        api, appeal["id"], "DENIED", denial_reason="EVIDENCE_UPHELD",
        rationale=DENIAL_RATIONALE, headers=REVIEWER,
    )
    assert denied["decided_by_user_id"] == APPEAL_REVIEWER_USER_ID
    assert_instant_equals(denied["escalation_deadline_at"], "2026-08-15T00:00:00.000Z",
                          "escalation_deadline_at")

    set_clock(api, NEXT_DAY)
    escalated = escalate(api, appeal["id"], seller["id"],
                         escalation_grounds=ESCALATION_GROUNDS)
    assert escalated["state"] == "ESCALATED_REVIEW"

    payload = {"outcome": "FINAL_DENIED", "denial_reason": "EVIDENCE_UPHELD",
               "rationale": FINAL_RATIONALE}
    # The denying reviewer, now wearing the officer role, may not confirm itself.
    by_first_decider = api.decide_escalation(
        appeal["id"], payload, make_compliance_officer_headers(APPEAL_REVIEWER_USER_ID)
    )
    # Nor may the investigator who issued the action in the first place.
    by_issuer = api.decide_escalation(
        appeal["id"], payload, make_compliance_officer_headers(INVESTIGATOR_USER_ID)
    )

    validate_error(by_first_decider, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)
    validate_error(by_issuer, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)
    assert validate_success(api.get_appeal(appeal["id"], OFFICER))["state"] == \
        "ESCALATED_REVIEW"

    final = decide_escalation(
        api, appeal["id"], "FINAL_DENIED", denial_reason="EVIDENCE_UPHELD",
        rationale=FINAL_RATIONALE, headers=OFFICER_ALT,
    )

    assert final["state"] == "FINAL_DENIED"
    assert final["reinstatement_granted"] is False
    exhausted = read_action(api, action["id"])
    assert exhausted["state"] == "UPHELD"
    assert exhausted["resolution_reason"] == "ESCALATION_DENIED"
    after = read_seller(api, seller["id"])
    # The exhausted rung was a warning, so the final denial closes the matter
    # without banning the account.
    assert_posture(after, enforcement_state="WATCHLIST", severity_points_balance="2.00")
    assert after["ban_reason"] is None


def test_the_plan_reviewer_may_not_be_the_investigator_who_issued_the_action(api):
    """PRD §2.7: "Reviewing a plan of action requires the acting user to differ from
    the `issued_by_user_id` of the enforcement action the plan answers."

    Design: Corner/rbac/rbac_plan_reviewer_cannot_be_the_investigator_who_issued_the_action
    """
    seller, rule, action = _issued_warning(
        api, "LA-SOD3-1", "EV-SOD3-0001", requires_poa=True
    )
    assert rule["requires_poa"] is True
    plan = submit_poa(
        api, action["id"], seller["id"], root_cause=PLAN_ROOT_CAUSE,
        corrective_measures=PLAN_CORRECTIVE, preventive_measures=PLAN_PREVENTIVE,
    )
    assert plan["state"] == "SUBMITTED"

    # The guard has to reach the action through the plan: the plan itself stores
    # no investigator identifier.
    refused = api.review_plan_of_action(
        plan["id"], {"decision": "ACCEPT", "review_notes": REVIEW_NOTES},
        make_compliance_officer_headers(INVESTIGATOR_USER_ID),
    )

    validate_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)
    unmoved = validate_success(api.get_plan_of_action(plan["id"], OFFICER))
    assert unmoved["state"] == "SUBMITTED"
    assert unmoved["reviewed_by_user_id"] is None

    accepted = review_poa(api, plan["id"], "ACCEPT", REVIEW_NOTES, OFFICER)

    assert accepted["state"] == "ACCEPTED"
    assert accepted["reviewed_by_user_id"] == COMPLIANCE_OFFICER_USER_ID


def test_the_hold_creator_may_not_release_its_own_hold(api):
    """PRD §2.7: "Releasing or forfeiting a disbursement hold requires the acting user
    to differ from the `created_by_user_id` recorded on that hold."

    Design: Corner/rbac/rbac_hold_creator_cannot_release_the_hold_it_opened
    """
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="LA-SOD4-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = _harbor_tools(api)
    credit(api, seller["id"], 100000, "PAYOUT-CYCLE-2026-07-R")
    violation = file_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER",
        evidence_reference="EV-SOD4-0001",
    )
    open_investigation(api, violation["id"])
    version = read_seller(api, seller["id"], INVESTIGATOR)["version"]
    hold = validate_success(
        api.create_hold(
            hold_payload(seller["id"], NEXT_DAY, "2026-08-05T00:00:00.000Z", version),
            INVESTIGATOR,
        ),
        201,
    )
    assert hold["created_by_user_id"] == INVESTIGATOR_USER_ID
    assert_cents(hold["held_amount_cents"], 10000, "held_amount_cents")

    # The same human wearing the officer role to release what it opened as the
    # investigator is exactly the loophole the rule closes.
    refused = api.release_hold(
        hold["id"], {"release_reason": "MANUAL"},
        make_compliance_officer_headers(INVESTIGATOR_USER_ID),
    )

    validate_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)
    assert validate_success(api.get_hold(hold["id"], OFFICER))["state"] == "ACTIVE"
    assert_funds(read_seller(api, seller["id"]), available=90000, held=10000,
                 credited=100000, debited=0)

    released = validate_success(
        api.release_hold(hold["id"], {"release_reason": "MANUAL"}, OFFICER), 200
    )

    assert released["state"] == "RELEASED"
    assert released["release_reason"] == "MANUAL"
    after = read_seller(api, seller["id"])
    assert_funds(after, available=100000, held=0, credited=100000, debited=0)
    # The investigation is still open, so only the hold is gone, not the posture.
    assert_posture(after, disbursement_state="RESERVE_HELD")
