"""Requests whose outcome is decided by the state of a neighbouring row rather
than by anything in the request itself: a relist read against the parent seller's
posture, and an issuance read against the cited violation's adjudication state.
"""

from test_helpers import (
    INVESTIGATOR,
    ApiErrorId,
    assert_points,
    assert_posture,
    create_listing,
    file_violation,
    issue_action,
    make_seller_headers,
    open_investigation,
    publish_rule,
    read_action,
    read_listings,
    read_seller,
    register_seller,
    set_clock,
    substantiated_violation,
    validate_error,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00.000Z"


# --------------------------------------------------------------------------
# Listing <- Seller: the same relist request against two different postures
# --------------------------------------------------------------------------
def _two_sellers_each_with_one_removed_listing(api):
    """Both listings are REMOVED under LISTING_ACCURACY, but the parent postures
    are reached by different routes: A's rung was computed from a 5.00 rule while
    B's came from an override on a 2.00 rule."""
    set_clock(api, CLOCK)
    rule_a = publish_rule(
        api, code="LA-REL-A", category="LISTING_ACCURACY", base_severity_weight=5.00,
        removal_scope="LISTING", requires_poa=False,
    )
    rule_b = publish_rule(
        api, code="LA-REL-B", category="LISTING_ACCURACY", base_severity_weight=2.00,
        removal_scope="LISTING", requires_poa=False,
    )
    seller_a = register_seller(
        api, legal_name="Westmoor Garden LLC", email="ops@westmoor-garden.example",
        tax_id_hash="TAX-WE-0001", payout_bank_token="BANK-WE-0001",
        address_fingerprint="ADDR-WE-0001",
    )
    seller_b = register_seller(
        api, legal_name="Yarrowbank Stationery LLC",
        email="ops@yarrowbank-stationery.example", tax_id_hash="TAX-YA-0002",
        payout_bank_token="BANK-YA-0002", address_fingerprint="ADDR-YA-0002",
    )
    listing_a = create_listing(
        api, seller_a["id"], sku="SKU-WE-1", title="Cedar Raised Bed Kit",
        category_code="GARDEN",
    )
    listing_b = create_listing(
        api, seller_b["id"], sku="SKU-YA-1", title="Linen Notebook A5",
        category_code="OFFICE",
    )
    violation_a = substantiated_violation(
        api, seller_a["id"], rule_a["id"], listing_id=listing_a["id"],
        reporter_type="BUYER", evidence_reference="EV-WE-0001",
    )
    action_a = issue_action(api, violation_a["id"])
    violation_b = substantiated_violation(
        api, seller_b["id"], rule_b["id"], listing_id=listing_b["id"],
        reporter_type="BUYER", evidence_reference="EV-YA-0001",
    )
    action_b = issue_action(api, violation_b["id"], action_type_override="LISTING_REMOVAL")
    return seller_a, seller_b, listing_a, listing_b, action_a, action_b


def test_the_relist_guard_reads_the_parent_seller_and_not_the_listing(api):
    """PRD §3.2: "If the listing is not in `REMOVED`, the attempt fails with
    `ERR_LISTING_NOT_REMOVED`; and if the owning seller's `enforcement_state` is
    `RESTRICTED` or `SUSPENDED` — relisting is permitted only while the seller is
    `ACTIVE` or `WATCHLIST` — the attempt fails with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/relist_blocked_while_seller_restricted_allowed_while_watchlist
    """
    seller_a, _, listing_a, _, action_a, _ = \
        _two_sellers_each_with_one_removed_listing(api)

    # 5.00 points clears the 4.00 restriction threshold on the computed rung alone.
    assert action_a["ladder_rung_computed"] == "LISTING_REMOVAL"
    assert action_a["override_applied"] is False
    assert_posture(read_seller(api, seller_a["id"]), enforcement_state="RESTRICTED",
                   severity_points_balance="5.00")

    response = api.relist_listing(listing_a["id"], make_seller_headers(seller_a["id"]))

    validate_error(response, ApiErrorId.INVALID_STATE.value)
    rows = {row["id"]: row for row in read_listings(api, seller_a["id"])}
    assert rows[listing_a["id"]]["state"] == "REMOVED"
    assert rows[listing_a["id"]]["removal_policy_category"] == "LISTING_ACCURACY"


def test_the_identical_relist_succeeds_while_the_owner_is_only_watchlisted(api):
    """PRD §3.2: "The one recovery a seller may drive itself is relisting, which
    moves a listing `REMOVED → ACTIVE` and clears `removal_policy_category`."

    Design: Difficulty/cross_entity_state_dependency/relist_blocked_while_seller_restricted_allowed_while_watchlist
    """
    _, seller_b, _, listing_b, _, action_b = \
        _two_sellers_each_with_one_removed_listing(api)

    # The removal came from an honoured override, not from the ladder: 2.00 points
    # sit below the 4.00 restriction threshold, so the posture is only WATCHLIST.
    assert action_b["ladder_rung_computed"] == "WARNING"
    assert action_b["action_type"] == "LISTING_REMOVAL"
    assert action_b["override_applied"] is True
    assert_posture(read_seller(api, seller_b["id"]), enforcement_state="WATCHLIST",
                   severity_points_balance="2.00")

    relisted = validate_success(
        api.relist_listing(listing_b["id"], make_seller_headers(seller_b["id"])), 200
    )

    assert relisted["state"] == "ACTIVE"
    assert relisted["removal_policy_category"] is None
    assert relisted["suppressed_by_suspension"] is False
    # The counter is history: a relist does not decrement what the action removed.
    assert read_action(api, action_b["id"])["removed_listing_count"] == 1


# --------------------------------------------------------------------------
# EnforcementAction <- Violation: three of the four states refuse
# --------------------------------------------------------------------------
def _four_violations_one_per_state(api):
    """One seller, one account-scoped shipping rule, and four violations left in
    REPORTED, UNDER_INVESTIGATION, DISMISSED and SUBSTANTIATED respectively."""
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="SP-DEP-1", category="SHIPPING_PERFORMANCE", base_severity_weight=2.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = register_seller(
        api, legal_name="Zephyr Cycle Parts LLC", email="ops@zephyr-cycleparts.example",
        tax_id_hash="TAX-ZE-0001", payout_bank_token="BANK-ZE-0001",
        address_fingerprint="ADDR-ZE-0001",
    )
    reported = file_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER",
        evidence_reference="EV-ZE-0001",
    )
    investigating = file_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER",
        evidence_reference="EV-ZE-0002",
    )
    open_investigation(api, investigating["id"])
    dismissed = file_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER",
        evidence_reference="EV-ZE-0003",
    )
    open_investigation(api, dismissed["id"])
    validate_success(
        api.adjudicate_violation(
            dismissed["id"],
            {"outcome": "DISMISSED",
             "decision_note": "Carrier scan data shows the shipments were on time."},
            INVESTIGATOR,
        ),
        200,
    )
    substantiated = substantiated_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER",
        evidence_reference="EV-ZE-0004",
        decision_note="Eleven consecutive late dispatches confirmed.",
    )
    return seller, reported, investigating, dismissed, substantiated


def test_three_of_the_four_violation_states_refuse_an_enforcement_action(api):
    """PRD §3.5: "No enforcement action may ever be issued for a dismissed
    violation, and an attempt to issue one against a violation in `REPORTED`,
    `UNDER_INVESTIGATION`, or `DISMISSED` is refused with
    `ERR_VIOLATION_NOT_SUBSTANTIATED`."

    Design: Difficulty/cross_entity_state_dependency/action_issuance_requires_substantiated_violation
    """
    seller, reported, investigating, dismissed, _ = _four_violations_one_per_state(api)

    for violation in (reported, investigating, dismissed):
        validate_error(
            api.create_enforcement_action({"violation_id": violation["id"]}, INVESTIGATOR),
            ApiErrorId.VIOLATION_NOT_SUBSTANTIATED.value,
        )

    # DISMISSED is terminal, so that third refusal is permanent rather than a
    # "not yet"; none of the three left a row behind.
    assert validate_success(api.get_violation(dismissed["id"], INVESTIGATOR))["state"] == \
        "DISMISSED"
    existing = validate_success(
        api.list_enforcement_actions(INVESTIGATOR, {"seller_id": seller["id"]})
    )
    assert existing == [], f"the three refusals created something: {existing}"
    assert_posture(read_seller(api, seller["id"]), enforcement_state="ACTIVE",
                   severity_points_balance="0.00")


def test_only_the_substantiated_violation_admits_the_action(api):
    """PRD §3.6: "Fourth, select the rung from that post-issuance balance: a
    balance of 12.00 points or more selects `ACCOUNT_SUSPENSION`; a balance of at
    least 4.00 but below 12.00 selects `LISTING_REMOVAL`; anything below 4.00
    selects `WARNING`."

    Design: Difficulty/cross_entity_state_dependency/action_issuance_requires_substantiated_violation
    """
    seller, reported, investigating, dismissed, substantiated = \
        _four_violations_one_per_state(api)

    action = validate_success(
        api.create_enforcement_action({"violation_id": substantiated["id"]}, INVESTIGATOR),
        201,
    )

    # A first offence multiplies the 2.00 base by 1.00 and nothing else applies,
    # because no evaluation has run and metric_tier is still null.
    assert_points(action["severity_points_applied"], "2.00", "severity_points_applied")
    assert action["ladder_rung_computed"] == "WARNING"
    assert action["removed_listing_count"] == 0

    after = read_seller(api, seller["id"])
    # 2.00 is strictly above 0.00 and below 4.00, and the second violation is
    # still under investigation, which pins the funds dimension.
    assert_posture(after, enforcement_state="WATCHLIST", disbursement_state="RESERVE_HELD",
                   severity_points_balance="2.00")
    assert after["metric_tier"] is None

    rows = validate_success(
        api.list_enforcement_actions(INVESTIGATOR, {"seller_id": seller["id"]})
    )
    assert [row["id"] for row in rows] == [action["id"]]
    assert validate_success(api.get_violation(reported["id"], INVESTIGATOR))["state"] == \
        "REPORTED"
    assert validate_success(api.get_violation(investigating["id"], INVESTIGATOR))["state"] == \
        "UNDER_INVESTIGATION"
    assert validate_success(api.get_violation(dismissed["id"], INVESTIGATOR))["state"] == \
        "DISMISSED"
