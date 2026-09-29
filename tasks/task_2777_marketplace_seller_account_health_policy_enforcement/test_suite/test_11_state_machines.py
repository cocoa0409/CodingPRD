"""The declared shape of each machine: where a fresh row starts, which trigger the
current state admits, which one it refuses and with which code, and what a legal
transition does to the rows and the money hanging off it.
"""

from test_helpers import (
    COMPLIANCE_OFFICER_USER_ID,
    INVESTIGATOR,
    OFFICER,
    REVIEWER,
    ApiErrorId,
    adjudicate,
    adjudication_payload,
    appeal_decision_payload,
    appeal_payload,
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
    escalation_payload,
    file_appeal,
    file_violation,
    issue_action,
    make_seller_headers,
    notices_for,
    open_hold,
    open_investigation,
    poa_payload,
    publish_rule,
    read_action,
    read_holds,
    read_listings,
    read_notices,
    read_seller,
    register_seller,
    release_payload,
    review_poa,
    set_clock,
    start_review,
    submit_poa,
    substantiated_violation,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00.000Z"
APPEAL_DEADLINE = "2026-08-31T00:00:00.000Z"
POA_DEADLINE = "2026-08-18T00:00:00.000Z"

ROOT_CAUSE = (
    "The July catalogue import mapped supplier part numbers onto the wrong "
    "generation of two SKUs."
)
CORRECTIVE = [
    "Corrected the two affected listings and re-verified every SKU from the same "
    "import batch."
]
PREVENTIVE = [
    "Added a part-number diff gate that blocks any catalogue import whose mapping "
    "changes an existing SKU generation."
]

APPEAL_GROUNDS = (
    "The two listings were corrected within an hour of the buyer report and no "
    "order shipped against the wrong description."
)
GRANT_RATIONALE = (
    "The evidence shows the description was accurate at the time of every sale in "
    "the cited window."
)


def _seller_with_one_warning_action(api, code, requires_poa=None):
    """The clock frozen at CLOCK, a 2.00-point account-scoped listing-accuracy
    rule, and one seller whose single substantiated violation carries an issued
    WARNING: a first offence multiplies 2.00 by 1.00, so the balance is 2.00,
    below the 4.00 restriction threshold, and the posture pair is
    WATCHLIST / RESERVE_HELD."""
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code=code, category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=requires_poa,
    )
    seller = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )
    violation = substantiated_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER",
        evidence_reference=f"EV-{code}",
        decision_note="Two SKUs described a different generation of the tool than "
                      "shipped.",
    )
    action = issue_action(api, violation["id"])
    return seller, rule, violation, action


def test_a_new_action_and_its_first_plan_open_in_their_declared_initial_states(api):
    """PRD §3.6: "The action opens in state `ISSUED`, with `acknowledged_at` and
    `resolution_reason` null and `removed_listing_count` at zero."

    PRD §3.7: "A submitted plan opens in state `SUBMITTED`, records `submitted_at`
    from the logical clock, and leaves `reviewed_by_user_id` and `review_notes`
    null until a reviewer touches it; it returns a 201 status."

    Design: Corner/state_machines/state_new_action_and_new_plan_start_in_their_declared_initial_states
    """
    seller, _, _, action = _seller_with_one_warning_action(api, "LA-INIT-1")
    assert action["state"] == "ISSUED"
    assert action["action_type"] == "WARNING"
    assert action["ladder_rung_computed"] == "WARNING"
    assert action["override_applied"] is False
    assert_points(action["severity_points_applied"], "2.00", "severity_points_applied")
    assert_nulls(action, "acknowledged_at", "resolution_reason")
    assert action["removed_listing_count"] == 0
    assert_instant_equals(action["issued_at"], CLOCK, "issued_at")
    assert_instant_equals(action["appeal_deadline_at"], APPEAL_DEADLINE,
                          "appeal_deadline_at")
    seller_headers = make_seller_headers(seller["id"])
    observed = read_action(api, action["id"], seller_headers)
    assert observed["version"] == 1

    plan = validate_success(
        api.create_plan_of_action(
            poa_payload(action["id"], observed["version"], root_cause=ROOT_CAUSE,
                        corrective_measures=CORRECTIVE,
                        preventive_measures=PREVENTIVE),
            seller_headers,
        ),
        201,
    )

    assert plan["state"] == "SUBMITTED"
    # The first plan for an action is revision zero, not revision one.
    assert plan["revision_count"] == 0
    assert_instant_equals(plan["submitted_at"], CLOCK, "submitted_at")
    # Seventeen days from issuance, thirteen days earlier than the appeal clock.
    assert_instant_equals(plan["deadline_at"], POA_DEADLINE, "deadline_at")
    assert_nulls(plan, "reviewed_by_user_id", "review_notes")
    assert read_action(api, action["id"])["version"] == 2
    assert_posture(read_seller(api, seller["id"]), enforcement_state="WATCHLIST",
                   disbursement_state="RESERVE_HELD", severity_points_balance="2.00")


def test_the_seller_acknowledgement_moves_the_action_and_nothing_else(api):
    """PRD §3.6: "The seller may acknowledge receipt of an action, moving it
    `ISSUED → ACKNOWLEDGED` and recording `acknowledged_at` from the clock;
    acknowledging returns a 200 status."

    PRD §3.6: "Acknowledgement is a courtesy, not a remedy: it does not pause the
    appeal clock and it does not change the points."

    Design: Corner/state_machines/state_acknowledge_moves_issued_action_to_acknowledged
    """
    seller, _, _, action = _seller_with_one_warning_action(
        api, "LA-ACK-1", requires_poa=False
    )

    acknowledged = validate_success(
        api.acknowledge_action(action["id"], make_seller_headers(seller["id"])), 200
    )

    assert acknowledged["state"] == "ACKNOWLEDGED"
    assert_instant_equals(acknowledged["acknowledged_at"], CLOCK, "acknowledged_at")
    # The action's own version moved once; nothing else did.
    assert acknowledged["version"] == 2
    assert_instant_equals(acknowledged["appeal_deadline_at"], APPEAL_DEADLINE,
                          "appeal_deadline_at")
    assert acknowledged["resolution_reason"] is None
    assert_points(acknowledged["severity_points_applied"], "2.00",
                  "severity_points_applied")

    after = read_seller(api, seller["id"])
    assert_posture(after, enforcement_state="WATCHLIST",
                   disbursement_state="RESERVE_HELD", severity_points_balance="2.00")


def test_deciding_an_appeal_that_was_never_taken_under_review_is_refused(api):
    """PRD §3.8: "Deciding an appeal that is not in `UNDER_REVIEW` is refused with
    `ERR_INVALID_STATE`, and a decider who issued the action is refused per §2.7."

    Design: Corner/state_machines/state_decide_before_start_review_returns_invalid_state
    """
    seller, _, _, action = _seller_with_one_warning_action(
        api, "LA-PRE-1", requires_poa=False
    )
    appeal = file_appeal(api, action["id"], seller["id"], grounds=APPEAL_GROUNDS)
    assert appeal["state"] == "SUBMITTED"
    assert appeal["reinstatement_granted"] is False

    # The right role, a perfect payload, and the wrong state: two-step review means
    # start-review has to happen first.
    response = api.decide_appeal(
        appeal["id"], appeal_decision_payload("GRANTED", rationale=GRANT_RATIONALE),
        REVIEWER,
    )

    validate_error(response, ApiErrorId.INVALID_STATE.value)
    still = validate_success(api.get_appeal(appeal["id"], REVIEWER))
    assert still["state"] == "SUBMITTED"
    assert_nulls(still, "decided_by_user_id", "decided_at")
    unresolved = read_action(api, action["id"])
    # A refused decision must not half-apply: no vacatur, no reinstatement.
    assert unresolved["state"] == "ISSUED"
    assert unresolved["resolution_reason"] is None
    assert_posture(read_seller(api, seller["id"]), enforcement_state="WATCHLIST",
                   severity_points_balance="2.00")


def test_relisting_a_listing_that_was_never_removed_is_refused(api):
    """PRD §3.2: "If the listing is not in `REMOVED`, the attempt fails with
    `ERR_LISTING_NOT_REMOVED`; and if the owning seller's `enforcement_state` is
    `RESTRICTED` or `SUSPENDED` — relisting is permitted only while the seller is
    `ACTIVE` or `WATCHLIST` — the attempt fails with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/state_relist_an_active_listing_returns_listing_not_removed
    """
    set_clock(api, CLOCK)
    seller = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )
    listing = create_listing(
        api, seller["id"], sku="HT-PRY-18", title="Titanium Pry Bar 18in",
        category_code="TOOLS-HAND",
    )
    assert listing["state"] == "ACTIVE"

    response = api.relist_listing(listing["id"], make_seller_headers(seller["id"]))

    # Relist has exactly one source state, so firing it at ACTIVE is a refusal and
    # not a silent no-op success.
    validate_error(response, ApiErrorId.LISTING_NOT_REMOVED.value)
    # The parent-seller guard passed; the listing's own state is what refused.
    assert_posture(read_seller(api, seller["id"]), enforcement_state="ACTIVE",
                   disbursement_state="NORMAL")
    rows = read_listings(api, seller["id"])
    assert len(rows) == 1, f"expected one listing, got {rows}"
    assert rows[0]["state"] == "ACTIVE"
    assert rows[0]["removal_policy_category"] is None
    assert rows[0]["suppressed_by_suspension"] is False
    assert rows[0]["version"] == 1


def test_repeating_the_investigation_and_adjudication_triggers_is_refused(api):
    """PRD §3.5: "Opening an investigation is a `PolicyInvestigator`-only step that
    moves the report `REPORTED → UNDER_INVESTIGATION`; a report in any other state
    cannot be opened, and a report against a banned seller cannot be opened at
    all."

    PRD §3.5: "Only a violation in `UNDER_INVESTIGATION` may be adjudicated, and
    both outcomes are terminal for the violation."

    Design: Corner/state_machines/state_repeating_investigation_and_adjudication_triggers_is_rejected
    """
    first_note = "Two SKUs shipped an older generation than the listing described."
    second_note = "A second adjudication that must never overwrite the first."
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="LA-IDEM-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )
    violation = file_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER",
        evidence_reference="EV-IDEM-0001",
    )
    opened = open_investigation(api, violation["id"])
    assert opened["state"] == "UNDER_INVESTIGATION"
    assert_posture(read_seller(api, seller["id"]), disbursement_state="RESERVE_HELD")

    replayed_open = api.open_investigation(violation["id"], INVESTIGATOR)

    validate_error(replayed_open, ApiErrorId.INVALID_STATE.value)
    adjudicated = adjudicate(api, violation["id"], "SUBSTANTIATED", first_note)
    assert adjudicated["state"] == "SUBSTANTIATED"

    replayed_decision = api.adjudicate_violation(
        violation["id"], adjudication_payload("DISMISSED", second_note), INVESTIGATOR
    )

    validate_error(replayed_decision, ApiErrorId.INVALID_STATE.value)
    final = validate_success(api.get_violation(violation["id"], INVESTIGATOR))
    # SUBSTANTIATED is terminal, so the DISMISSED payload changed nothing at all.
    assert final["state"] == "SUBSTANTIATED"
    assert final["decision_note"] == first_note
    assert_instant_equals(final["adjudicated_at"], CLOCK, "adjudicated_at")

    after = read_seller(api, seller["id"])
    # The investigation closed once and stayed closed; the funds posture does not
    # flap back to RESERVE_HELD on a refused replay.
    assert_posture(after, enforcement_state="ACTIVE", disbursement_state="NORMAL",
                   severity_points_balance="0.00")


def test_a_vacated_action_and_its_granted_appeal_refuse_three_further_moves(api):
    """PRD §3.8: "Once an action reaches `VACATED` it accepts nothing further:
    acknowledging it is refused with `ERR_ACTION_NOT_APPEALABLE_STATE` and a fresh
    appeal against it is refused with `ERR_APPEAL_ALREADY_EXISTS`."

    PRD §2.8: "Transition legality — the target row must be in a state from which
    the requested transition exists, including the cross-entity gates, yielding
    `ERR_INVALID_STATE` or the more specific state error that applies."

    Design: Corner/state_machines/state_vacated_action_is_locked_against_acknowledge_and_re_appeal
    """
    seller, _, _, action = _seller_with_one_warning_action(
        api, "LA-LOCK-1", requires_poa=False
    )
    appeal = file_appeal(api, action["id"], seller["id"], grounds=APPEAL_GROUNDS)
    start_review(api, appeal["id"], REVIEWER)
    # No other action shares the category, so the repeat-offence gate cannot fire.
    granted = decide_appeal(api, appeal["id"], "GRANTED", rationale=GRANT_RATIONALE,
                            headers=REVIEWER)
    assert granted["state"] == "GRANTED"
    # A vacated warning is not a reinstatement: only a suspension is.
    assert granted["reinstatement_granted"] is False
    vacated = read_action(api, action["id"])
    assert vacated["state"] == "VACATED"
    assert vacated["resolution_reason"] == "APPEAL_GRANTED"

    seller_headers = make_seller_headers(seller["id"])
    validate_error(
        api.acknowledge_action(action["id"], seller_headers),
        ApiErrorId.ACTION_NOT_APPEALABLE_STATE.value,
    )
    validate_error(
        api.create_appeal(
            appeal_payload(
                action["id"],
                grounds="Filing a second appeal against the same action to test the "
                        "at-most-one-appeal rule.",
            ),
            seller_headers,
        ),
        ApiErrorId.APPEAL_ALREADY_EXISTS.value,
    )
    validate_error(
        api.escalate_appeal(
            appeal["id"],
            escalation_payload(
                "Attempting to escalate an appeal that was already granted in full."
            ),
            seller_headers,
        ),
        ApiErrorId.INVALID_STATE.value,
    )

    assert read_action(api, action["id"])["acknowledged_at"] is None
    unchanged = validate_success(api.get_appeal(appeal["id"], REVIEWER))
    # Escalation is reachable only from DENIED, so neither escalation field was set.
    assert unchanged["state"] == "GRANTED"
    assert_nulls(unchanged, "escalation_requested_at", "escalation_deadline_at")
    rows, meta = validate_paginated(
        api.list_appeals(REVIEWER, {"enforcement_action_id": action["id"]})
    )
    assert [row["id"] for row in rows] == [appeal["id"]]
    assert_meta(meta, total_count=1, has_more=False)

    after = read_seller(api, seller["id"])
    assert_posture(after, enforcement_state="ACTIVE", disbursement_state="NORMAL",
                   severity_points_balance="0.00")


def _seller_with_one_removed_and_one_active_listing(api):
    """Two listing-accuracy rules of different removal scope, 100000 cents of
    settled proceeds, listing L1 already REMOVED under an overridden listing
    removal worth 1.00 point, listing L2 still ACTIVE, and a second violation
    standing SUBSTANTIATED and ready to be enforced."""
    set_clock(api, CLOCK)
    listing_scope = publish_rule(
        api, code="LA-SCOPE-L", category="LISTING_ACCURACY", base_severity_weight=1.00,
        removal_scope="LISTING", requires_poa=False,
    )
    account_scope = publish_rule(
        api, code="LA-SCOPE-A", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )
    credit(api, seller["id"], 100000, "SETTLE-2026-07")
    removed = create_listing(
        api, seller["id"], sku="HT-PRY-18", title="Titanium Pry Bar 18in",
        category_code="TOOLS-HAND",
    )
    spared = create_listing(
        api, seller["id"], sku="HT-CLAMP-6", title="Bar Clamp 6in Two Pack",
        category_code="TOOLS-HAND",
    )
    cited = substantiated_violation(
        api, seller["id"], listing_scope["id"], listing_id=removed["id"],
        reporter_type="BUYER", evidence_reference="EV-SCOPE-0001",
    )
    removal = issue_action(api, cited["id"], action_type_override="LISTING_REMOVAL")
    pending = substantiated_violation(
        api, seller["id"], account_scope["id"], reporter_type="BUYER",
        evidence_reference="EV-SCOPE-0002",
    )
    return seller, removed, spared, removal, pending


def test_the_suspension_cascade_suppresses_the_active_listing_and_spares_the_removed_one(api):
    """PRD §3.6: "A rung of `ACCOUNT_SUSPENSION` runs the full suspension cascade:
    every listing of the seller in `ACTIVE` moves to `SUPPRESSED` with
    `suppressed_by_suspension` true; the funds dimension then moves to `FULL_HOLD`,
    which first releases every one of the seller's `ACTIVE` holds with
    `release_reason` `SUPERSEDED_BY_FULL_HOLD` and then mints a single sweeping hold
    as described in §3.9; and a `FUNDS_HELD` notice discloses the swept amount."

    Design: Corner/state_machines/state_suspension_suppresses_only_active_listings_and_spares_removed_ones
    """
    seller, removed, spared, removal, pending = \
        _seller_with_one_removed_and_one_active_listing(api)

    suspension = issue_action(api, pending["id"],
                              action_type_override="ACCOUNT_SUSPENSION")

    # Second offence in the category: 2.00 x 1.25, and the override is honoured
    # because ACCOUNT_SUSPENSION is strictly more severe than the computed WARNING.
    assert_points(suspension["severity_points_applied"], "2.50",
                  "severity_points_applied")
    assert suspension["ladder_rung_computed"] == "WARNING"
    assert suspension["action_type"] == "ACCOUNT_SUSPENSION"
    assert suspension["override_applied"] is True
    # A suspension suppresses; it removes nothing, so the counter stays with the
    # action that did the removing.
    assert suspension["removed_listing_count"] == 0
    assert read_action(api, removal["id"])["removed_listing_count"] == 1

    rows = {row["id"]: row for row in read_listings(api, seller["id"])}
    assert rows[spared["id"]]["state"] == "SUPPRESSED"
    assert rows[spared["id"]]["suppressed_by_suspension"] is True
    # The cascade is conditional on each child's state: a REMOVED listing is left
    # exactly as it was, so a later reinstatement can tell the two apart.
    assert rows[removed["id"]]["state"] == "REMOVED"
    assert rows[removed["id"]]["suppressed_by_suspension"] is False
    assert rows[removed["id"]]["removal_policy_category"] == "LISTING_ACCURACY"

    after = read_seller(api, seller["id"])
    # 3.50 points sit far below the 12.00 suspension threshold: the posture is
    # driven by the live ACCOUNT_SUSPENSION action, not by the balance.
    assert_posture(after, enforcement_state="SUSPENDED",
                   disbursement_state="FULL_HOLD", severity_points_balance="3.50")
    assert_funds(after, available=0, held=100000, credited=100000, debited=0)

    holds = read_holds(api, params={"seller_id": seller["id"]})
    assert len(holds) == 1, f"expected exactly one sweeping row, got {holds}"
    sweeping = holds[0]
    assert sweeping["hold_type"] == "FULL_HOLD"
    assert sweeping["reserve_basis"] == "NONE"
    assert sweeping["auto_created"] is True
    assert sweeping["state"] == "ACTIVE"
    assert sweeping["risk_tier"] == "TIER_3"
    assert_cents(sweeping["held_amount_cents"], 100000, "held_amount_cents")
    assert_instant_equals(sweeping["coverage_start"], CLOCK, "coverage_start")
    assert_instant_equals(sweeping["coverage_end"], "2026-10-30T00:00:00.000Z",
                          "coverage_end")

    held_notices = notices_for(read_notices(api, seller["id"]), "FUNDS_HELD")
    assert len(held_notices) == 1, f"expected one FUNDS_HELD notice, got {held_notices}"
    assert_cents(held_notices[0]["amount_cents"], 100000, "amount_cents")


def test_a_manual_release_returns_the_reserved_cents_to_the_available_balance(api):
    """PRD §3.9: "Release moves the hold `ACTIVE → RELEASED`, records `released_at`
    from the clock, returns `held_amount_cents` from `held_balance_cents` to
    `available_balance_cents`, increments the seller's `version` by one, emits a
    `FUNDS_RELEASED` notice, and returns a 200 status."

    Design: Corner/state_machines/state_manual_hold_release_returns_funds_to_the_seller_ledger
    """
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="LA-LED-1", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = register_seller(
        api, legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
        tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
        address_fingerprint="ADDR-HT-0001",
    )
    credit(api, seller["id"], 200000, "SETTLE-2026-07")
    violation = file_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER",
        evidence_reference="EV-LED-0001",
    )
    open_investigation(api, violation["id"])
    observed = read_seller(api, seller["id"], INVESTIGATOR)
    # Registration, the credit and the opened investigation are the only writes so
    # far, which is what makes the version expectation predictable.
    assert observed["version"] == 3
    assert_posture(observed, enforcement_state="ACTIVE",
                   disbursement_state="RESERVE_HELD")

    hold = open_hold(
        api, seller["id"], CLOCK, "2026-08-15T00:00:00.000Z", reserve_basis="ROLLING",
        expected_version=observed["version"],
    )

    # A clean seller prices at TIER_1, so the rolling share is ten percent.
    assert hold["risk_tier"] == "TIER_1"
    assert_cents(hold["held_amount_cents"], 20000, "held_amount_cents")
    assert_funds(read_seller(api, seller["id"]), available=180000, held=20000,
                 credited=200000, debited=0)

    # inv-1 created the row, so co-1 is the officer who may release it by hand.
    released = validate_success(
        api.release_hold(hold["id"], release_payload("MANUAL"), OFFICER), 200
    )

    assert released["state"] == "RELEASED"
    assert released["release_reason"] == "MANUAL"
    assert_instant_equals(released["released_at"], CLOCK, "released_at")
    assert_cents(released["forfeited_amount_cents"], 0, "forfeited_amount_cents")

    after = read_seller(api, seller["id"])
    # The same 20000 comes back, and a release is not a debit, so the lifetime
    # figures never move and the funds identity closes on 200000.
    assert_funds(after, available=200000, held=0, credited=200000, debited=0)
    assert after["version"] == 5
    # Money movement never relaxes the enforcement dimension, and the investigation
    # is still open, so the funds posture stays gated.
    assert_posture(after, enforcement_state="ACTIVE",
                   disbursement_state="RESERVE_HELD")
    release_notices = notices_for(read_notices(api, seller["id"]), "FUNDS_RELEASED")
    assert len(release_notices) == 1, \
        f"expected one FUNDS_RELEASED notice, got {release_notices}"
    assert_cents(release_notices[0]["amount_cents"], 20000, "amount_cents")


def test_an_appeal_is_refused_while_the_only_plan_stands_rejected(api):
    """PRD §3.8: "Where the action's snapshotted rule had `requires_poa` true, a
    plan of action for that same action must already be in `ACCEPTED`, and the
    absence of one is refused with `ERR_POA_NOT_ACCEPTED`; a cited
    `plan_of_action_id` that belongs to some other action is refused with
    `ERR_POA_ACTION_MISMATCH`."

    Design: Corner/state_machines/state_appeal_blocked_while_the_plan_of_action_was_rejected
    """
    seller, _, _, action = _seller_with_one_warning_action(api, "LA-POA-1")
    plan = submit_poa(api, action["id"], seller["id"], root_cause=ROOT_CAUSE,
                      corrective_measures=CORRECTIVE, preventive_measures=PREVENTIVE)
    # co-1 differs from the issuing inv-1, so segregation of duties is satisfied.
    rejected = review_poa(
        api, plan["id"], "REJECT",
        "The root cause does not explain why the template was never verified.",
        OFFICER,
    )
    assert rejected["state"] == "REJECTED"
    assert rejected["reviewed_by_user_id"] == COMPLIANCE_OFFICER_USER_ID

    response = api.create_appeal(
        appeal_payload(
            action["id"], plan["id"],
            grounds="The rejected plan should not bar review of the underlying "
                    "warning itself.",
        ),
        make_seller_headers(seller["id"]),
    )

    # The plan exists and belongs to this very action, so the gate reads its STATE:
    # only ACCEPTED satisfies the precondition.
    validate_error(response, ApiErrorId.POA_NOT_ACCEPTED.value)
    rows, meta = validate_paginated(
        api.list_appeals(REVIEWER, {"enforcement_action_id": action["id"]})
    )
    # Nothing was persisted, so the seller can still be measured as never having
    # appealed.
    assert rows == [], f"the refused appeal was filed anyway: {rows}"
    assert_meta(meta, total_count=0, has_more=False)
    assert read_action(api, action["id"])["state"] == "ISSUED"
    assert_posture(read_seller(api, seller["id"]), enforcement_state="WATCHLIST",
                   severity_points_balance="2.00")
