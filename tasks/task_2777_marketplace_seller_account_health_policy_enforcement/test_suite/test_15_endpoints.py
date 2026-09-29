"""The read and write surface itself: the append-only catalogue and its filter, the
dismissal branch that releases money, the one hold_type a client may not ask for, the
optional link from a hold to its own seller's action, the derived transparency notice,
the case-file reads that must agree with each other, and the registration link that
is reachable from both sides of the pair.
"""

from test_helpers import (
    INVESTIGATOR,
    INVESTIGATOR_USER_ID,
    OFFICER,
    REVIEWER,
    ApiErrorId,
    accepted_poa,
    adjudicate,
    assert_cents,
    assert_funds,
    assert_instant_equals,
    assert_meta,
    assert_nulls,
    assert_points,
    assert_posture,
    credit,
    file_appeal,
    file_violation,
    hold_payload,
    issue_action,
    make_seller_headers,
    open_hold,
    open_investigation,
    publish_rule,
    read_action,
    read_holds,
    read_seller,
    register_seller,
    set_clock,
    substantiated_violation,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00.000Z"
COVERAGE_START = "2026-08-02T00:00:00.000Z"
COVERAGE_END = "2026-08-05T00:00:00.000Z"


def _harbor_tools(api, **overrides):
    payload = {
        "legal_name": "Harbor Tools LLC", "email": "ops@harbor-tools.example",
        "tax_id_hash": "TAX-HT-0001", "payout_bank_token": "BANK-HT-0001",
        "address_fingerprint": "ADDR-HT-0001",
    }
    payload.update(overrides)
    return register_seller(api, **payload)


# --------------------------------------------------------------------------
# The policy catalogue: create and filtered list, and nothing else
# --------------------------------------------------------------------------
def test_the_catalogue_filter_composes_with_the_pagination_envelope(api):
    """PRD §3.2: "The catalogue is readable by sellers as well as operators, filtered
    by `category`, because a seller cannot answer a charge it cannot look up."

    Design: Corner/endpoints/endpoint_policy_rule_create_and_filtered_list
    """
    set_clock(api, CLOCK)
    seller = _harbor_tools(api)

    first = publish_rule(
        api, code="LA-CRUD-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    second = publish_rule(
        api, code="LA-CRUD-2", category="LISTING_ACCURACY", base_severity_weight=3.50,
        removal_scope="LISTING",
    )
    third = publish_rule(
        api, code="IP-CRUD-1", category="INTELLECTUAL_PROPERTY",
        base_severity_weight=4.00, removal_scope="LISTING", requires_poa=True,
    )

    assert first["decay_exempt"] is False
    assert third["decay_exempt"] is True
    # requires_poa was omitted from the second body and defaults to true.
    assert second["requires_poa"] is True
    assert_points(second["base_severity_weight"], "3.50", "base_severity_weight")

    page, meta = validate_paginated(
        api.list_policy_rules(
            make_seller_headers(seller["id"]),
            {"category": "LISTING_ACCURACY", "limit": 1, "offset": 0},
        )
    )

    # total_count counts the filtered set, not the whole catalogue.
    assert_meta(meta, total_count=2, has_more=True, limit=1, offset=0)
    assert len(page) == 1
    assert page[0]["id"] in {first["id"], second["id"]}
    assert page[0]["id"] != third["id"]
    assert page[0]["category"] == "LISTING_ACCURACY"

    everything, all_meta = validate_paginated(
        api.list_policy_rules(INVESTIGATOR, {"limit": 100, "offset": 0})
    )
    assert_meta(all_meta, total_count=3, has_more=False, limit=100, offset=0)
    assert {row["id"] for row in everything} == {first["id"], second["id"], third["id"]}


# --------------------------------------------------------------------------
# The dismissal branch of one action endpoint moves three rows and the ledger
# --------------------------------------------------------------------------
def test_dismissing_the_last_open_investigation_releases_the_reserve(api):
    """PRD §3.5: "Both branches do exactly the same three things to the record: they
    set `adjudicated_at` from the logical clock, they store `decision_note`, and they
    recompute the seller's funds dimension — where no investigation of that seller
    remains open and the enforcement dimension is `ACTIVE`, the seller returns to
    `NORMAL`, which releases every one of that seller's holds still in `ACTIVE` with
    `release_reason` `INVESTIGATION_CLOSED`, moves each hold's cents from
    `held_balance_cents` back to `available_balance_cents`, and emits a
    `FUNDS_RELEASED` notice for each hold released."

    Design: Corner/endpoints/endpoint_dismissing_an_investigation_releases_the_reserve
    """
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="LA-DIS-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = _harbor_tools(api)
    credit(api, seller["id"], 100000)
    violation = file_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER",
        evidence_reference="EV-DIS-0001",
    )
    opened = open_investigation(api, violation["id"])
    assert opened["state"] == "UNDER_INVESTIGATION"
    assert_posture(read_seller(api, seller["id"]), enforcement_state="ACTIVE",
                   disbursement_state="RESERVE_HELD")
    hold = open_hold(api, seller["id"], COVERAGE_START, COVERAGE_END,
                     reserve_basis="ROLLING")
    assert_cents(hold["held_amount_cents"], 10000, "held_amount_cents")

    dismissed = adjudicate(
        api, violation["id"], "DISMISSED",
        "The buyer photo shows a different item than the one listed.",
    )

    assert dismissed["state"] == "DISMISSED"
    assert_instant_equals(dismissed["adjudicated_at"], CLOCK, "adjudicated_at")
    assert dismissed["decision_note"] == \
        "The buyer photo shows a different item than the one listed."

    released = validate_success(api.get_hold(hold["id"], OFFICER))
    assert released["state"] == "RELEASED"
    assert released["release_reason"] == "INVESTIGATION_CLOSED"
    assert_instant_equals(released["released_at"], CLOCK, "released_at")

    after = read_seller(api, seller["id"])
    assert_funds(after, available=100000, held=0, credited=100000, debited=0)
    assert_posture(after, enforcement_state="ACTIVE", disbursement_state="NORMAL",
                   severity_points_balance="0.00")

    notices, notice_meta = validate_paginated(
        api.list_seller_notifications(seller["id"], OFFICER,
                                      {"template_code": "FUNDS_RELEASED"})
    )
    assert_meta(notice_meta, total_count=1)
    assert_cents(notices[0]["amount_cents"], 10000, "amount_cents")
    assert notices[0]["related_entity_type"] == "DISBURSEMENT_HOLD"
    assert notices[0]["related_entity_id"] == hold["id"]

    # Dismissal is terminal, so the charge can never be enforced afterwards.
    validate_error(
        api.create_enforcement_action({"violation_id": violation["id"]}, INVESTIGATOR),
        ApiErrorId.VIOLATION_NOT_SUBSTANTIATED.value,
    )


# --------------------------------------------------------------------------
# One enum member of a declared input that no client may supply
# --------------------------------------------------------------------------
def test_a_client_may_not_mint_the_sweeping_hold_by_hand(api):
    """PRD §3.9: "The third value of `reserve_basis`, `NONE`, appears only on
    cascade-minted sweeping rows and is never a legitimate input on an explicit
    creation."

    Design: Corner/endpoints/endpoint_full_hold_is_cascade_only
    """
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="LA-FH-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = _harbor_tools(api)
    credit(api, seller["id"], 100000)
    violation = file_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER",
        evidence_reference="EV-FH-0001",
    )
    open_investigation(api, violation["id"])
    token = read_seller(api, seller["id"], INVESTIGATOR)["version"]

    sweeping_attempt = api.create_hold(
        hold_payload(seller["id"], COVERAGE_START, COVERAGE_END, token,
                     hold_type="FULL_HOLD", reserve_basis="NONE"),
        INVESTIGATOR,
    )

    # A refused shape, not a posture or a fiscal complaint.
    validate_error(sweeping_attempt, ApiErrorId.INVALID_REQUEST.value, 400)

    reserve = validate_success(
        api.create_hold(
            hold_payload(seller["id"], COVERAGE_START, COVERAGE_END, token,
                         hold_type="RESERVE", reserve_basis="ROLLING"),
            INVESTIGATOR,
        ),
        201,
    )

    assert reserve["hold_type"] == "RESERVE"
    assert reserve["auto_created"] is False
    assert_cents(reserve["held_amount_cents"], 10000, "held_amount_cents")
    rows, meta = validate_paginated(
        api.list_holds(OFFICER, {"seller_id": seller["id"]})
    )
    assert_meta(meta, total_count=1)
    assert rows[0]["id"] == reserve["id"]
    # An explicit reserve never promotes the posture to FULL_HOLD.
    assert_posture(read_seller(api, seller["id"]), enforcement_state="ACTIVE",
                   disbursement_state="RESERVE_HELD")


# --------------------------------------------------------------------------
# The optional cross-reference from a hold to its own seller's action
# --------------------------------------------------------------------------
def test_a_hold_stores_and_is_queryable_by_the_action_that_motivated_it(api):
    """PRD §3.9: "On success the row snapshots its `risk_tier`, computes
    `held_amount_cents` from the declared basis, records `created_by_user_id` from the
    acting investigator's `X-User-ID`, opens in state `ACTIVE` with `auto_created`
    false, `released_at` and `release_reason` null, and `forfeited_amount_cents` zero."

    Design: Corner/endpoints/endpoint_hold_cross_references_its_own_sellers_action
    """
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="LA-LNK-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = _harbor_tools(api)
    credit(api, seller["id"], 100000)
    violation = substantiated_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER",
        evidence_reference="EV-LNK-0001",
        decision_note="Two listings overstated the compatibility of the same part.",
    )
    action = issue_action(api, violation["id"])
    before = read_seller(api, seller["id"], INVESTIGATOR)
    # WATCHLIST alone drives the reserve posture here: no investigation is open.
    assert_posture(before, enforcement_state="WATCHLIST",
                   disbursement_state="RESERVE_HELD", severity_points_balance="2.00")
    action_version = read_action(api, action["id"])["version"]

    hold = validate_success(
        api.create_hold(
            hold_payload(seller["id"], COVERAGE_START, COVERAGE_END, before["version"],
                         enforcement_action_id=action["id"], hold_type="RESERVE",
                         reserve_basis="ROLLING"),
            INVESTIGATOR,
        ),
        201,
    )

    assert hold["enforcement_action_id"] == action["id"]
    assert_cents(hold["held_amount_cents"], 10000, "held_amount_cents")
    assert hold["created_by_user_id"] == INVESTIGATOR_USER_ID
    assert_nulls(hold, "released_at", "release_reason")

    rows, meta = validate_paginated(
        api.list_holds(OFFICER, {"enforcement_action_id": action["id"]})
    )
    assert_meta(meta, total_count=1)
    assert rows[0]["id"] == hold["id"]
    assert rows[0]["created_by_user_id"] == INVESTIGATOR_USER_ID
    assert_funds(read_seller(api, seller["id"]), available=90000, held=10000,
                 credited=100000, debited=0)
    # Opening a hold moves the seller's version, never the cited action's.
    assert read_action(api, action["id"])["version"] == action_version
    assert read_seller(api, seller["id"])["version"] == before["version"] + 1


# --------------------------------------------------------------------------
# A notice assembled from four different source rows
# --------------------------------------------------------------------------
def test_the_action_notice_copies_every_disclosure_from_its_own_source(api):
    """PRD §2.11: "An `ACTION_ISSUED` notice must carry a non-null
    `policy_rule_code`, a non-null `severity_points_disclosed` copying the action's
    `severity_points_applied`, a non-null `appeal_deadline_at` copying the action's own
    deadline, and a non-null `evidence_reference` copying the cited violation's
    evidence bundle reference."

    Design: Corner/endpoints/endpoint_action_notification_carries_the_full_transparency_payload
    """
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="LA-NOTE-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = _harbor_tools(api)
    violation = substantiated_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER",
        evidence_reference="EV-NOTE-0001",
    )
    action = issue_action(api, violation["id"])

    # The appeal clock is anchored on issued_at and runs for thirty days.
    assert_instant_equals(action["appeal_deadline_at"], "2026-08-31T00:00:00.000Z",
                          "appeal_deadline_at")
    assert action["ladder_rung_computed"] == "WARNING"

    notices, meta = validate_paginated(
        api.list_seller_notifications(
            seller["id"], make_seller_headers(seller["id"]),
            {"template_code": "ACTION_ISSUED", "state": "SENT"},
        )
    )

    assert_meta(meta, total_count=1)
    notice = notices[0]
    # The rule's code, not its identifier.
    assert notice["policy_rule_code"] == "LA-NOTE-1"
    assert_points(notice["severity_points_disclosed"], "2.00",
                  "severity_points_disclosed")
    assert_instant_equals(notice["appeal_deadline_at"], "2026-08-31T00:00:00.000Z",
                          "appeal_deadline_at")
    assert notice["evidence_reference"] == "EV-NOTE-0001"
    assert notice["related_entity_type"] == "ENFORCEMENT_ACTION"
    assert notice["related_entity_id"] == action["id"]
    assert notice["state"] == "SENT"
    assert_instant_equals(notice["sent_at"], CLOCK, "sent_at")
    # Fields this template does not demand stay null.
    assert_nulls(notice, "amount_cents", "escalation_deadline_at", "decision_rationale")

    _, funds_meta = validate_paginated(
        api.list_seller_notifications(seller["id"], make_seller_headers(seller["id"]),
                                      {"template_code": "FUNDS_HELD"})
    )
    # A bare warning moves no money, so there is nothing to disclose.
    assert_meta(funds_meta, total_count=0)


# --------------------------------------------------------------------------
# Every write in the case file has a read, and the two read shapes agree
# --------------------------------------------------------------------------
def test_the_case_file_reads_by_id_and_by_filter_return_the_same_rows(api):
    """PRD §3.7: "An accepted plan is terminal, and it is the precondition that
    unlocks an appeal against the same action whenever the rule requires one."

    Design: Corner/endpoints/endpoint_case_file_rows_are_readable_by_id_and_by_filter
    """
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="LA-READ-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=True,
    )
    seller = _harbor_tools(api)
    credit(api, seller["id"], 100000)
    violation = substantiated_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER",
        evidence_reference="EV-READ-0001",
    )
    action = issue_action(api, violation["id"])
    plan = accepted_poa(
        api, action["id"], seller["id"], reviewer=OFFICER,
        review_notes="Root cause and both measure sets are specific and verifiable.",
        root_cause="Our supplier feed mapped compatibility attributes onto the wrong "
                   "parent listing.",
        corrective_measures=["Corrected the attribute mapping for every affected "
                             "listing"],
        preventive_measures=["Nightly automated diff of the feed against the published "
                             "catalogue"],
    )
    assert plan["state"] == "ACCEPTED"
    appeal = file_appeal(
        api, action["id"], seller["id"], plan["id"],
        grounds="The manufacturer sheet supports the disputed attribute for the "
                "reported period.",
    )
    hold = open_hold(api, seller["id"], COVERAGE_START, COVERAGE_END,
                     reserve_basis="ROLLING")

    read_violation = validate_success(api.get_violation(violation["id"], REVIEWER))
    assert read_violation["state"] == "SUBSTANTIATED"
    assert read_violation["auto_generated"] is False

    listed_plans, plan_meta = validate_paginated(
        api.list_plans_of_action(REVIEWER, {"enforcement_action_id": action["id"]})
    )
    assert_meta(plan_meta, total_count=1)
    assert listed_plans[0]["id"] == plan["id"]
    assert listed_plans[0]["state"] == "ACCEPTED"

    by_id = validate_success(
        api.get_plan_of_action(plan["id"], make_seller_headers(seller["id"]))
    )
    # The two read shapes agree, field for field, on the row they describe.
    assert by_id["id"] == listed_plans[0]["id"]
    assert by_id["state"] == "ACCEPTED"
    assert by_id["revision_count"] == 0
    assert by_id["enforcement_action_id"] == action["id"]

    listed_appeals, appeal_meta = validate_paginated(
        api.list_appeals(OFFICER, {"enforcement_action_id": action["id"]})
    )
    assert_meta(appeal_meta, total_count=1)
    assert listed_appeals[0]["id"] == appeal["id"]
    assert listed_appeals[0]["plan_of_action_id"] == plan["id"]

    read_hold = validate_success(api.get_hold(hold["id"], OFFICER))
    assert read_hold["state"] == "ACTIVE"
    assert read_hold["reserve_basis"] == "ROLLING"
    assert_cents(read_hold["held_amount_cents"], 10000, "held_amount_cents")
    assert [row["id"] for row in read_holds(api, params={"seller_id": seller["id"]})] == \
        [hold["id"]]


# --------------------------------------------------------------------------
# A row no client can create, reachable from both sides of the pair
# --------------------------------------------------------------------------
def test_a_minted_registration_link_is_readable_from_both_directions(api):
    """PRD §3.1: "The link records `candidate_seller_id` for the newly registered
    seller and `matched_seller_id` for the incumbent, lists the signals that matched in
    `matched_signals` using the fixed order `TAX_ID`, `BANK_TOKEN`, `ADDRESS`,
    `EMAIL_DOMAIN`, `DEVICE`, and freezes the incumbent's posture at that moment into
    `matched_seller_state_at_detection` so that a later change to the incumbent's
    account cannot rewrite the evidence."

    Design: Corner/endpoints/endpoint_detected_registration_link_is_readable_by_id
    """
    set_clock(api, CLOCK)
    incumbent = _harbor_tools(api, tax_id_hash="TAX-SHARED-9")

    newcomer = register_seller(
        api, legal_name="Delta Supply Co", email="ops@delta-supply.example",
        tax_id_hash="TAX-SHARED-9", payout_bank_token="BANK-DS-0002",
        address_fingerprint="ADDR-DS-0002",
    )

    # A shared tax id alone scores exactly the minting threshold and no more, so the
    # row exists while both accounts stay clean.
    assert newcomer["root_seller_id"] == incumbent["id"]
    assert newcomer["registration_risk_flag"] is False
    assert_posture(newcomer, enforcement_state="ACTIVE", disbursement_state="NORMAL")

    from_candidate, candidate_meta = validate_paginated(
        api.list_related_account_links(INVESTIGATOR,
                                      {"candidate_seller_id": newcomer["id"]})
    )
    assert_meta(candidate_meta, total_count=1)
    link = from_candidate[0]
    assert_points(link["confidence_score"], "0.35", "confidence_score")
    assert link["state"] == "DETECTED"

    from_matched, matched_meta = validate_paginated(
        api.list_related_account_links(OFFICER, {"matched_seller_id": incumbent["id"]})
    )
    assert_meta(matched_meta, total_count=1)
    assert from_matched[0]["id"] == link["id"]

    by_id = validate_success(api.get_related_account_link(link["id"], OFFICER))
    assert by_id["candidate_seller_id"] == newcomer["id"]
    assert by_id["matched_seller_id"] == incumbent["id"]
    assert_points(by_id["confidence_score"], "0.35", "confidence_score")
    assert by_id["matched_seller_state_at_detection"] == "ACTIVE"
    assert by_id["matched_signals"] == ["TAX_ID"]
    assert_instant_equals(by_id["detected_at"], CLOCK, "detected_at")
    assert_nulls(by_id, "adjudicated_by_user_id", "adjudication_note")

    # Links point from the newcomer to the incumbent, never the other way.
    _, reverse_meta = validate_paginated(
        api.list_related_account_links(OFFICER,
                                      {"candidate_seller_id": incumbent["id"]})
    )
    assert_meta(reverse_meta, total_count=0)
