"""Approval settlement, independent state axes and remaining corner contracts."""
import datetime as dt

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_share_conservation,
    create_approved_channel,
    create_channel_payload,
    create_content_item_payload,
    create_payout_lock_payload,
    create_reference_file_payload,
    create_revenue_routing_payload,
    get_success_data,
    make_creator_headers,
    make_rights_holder_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _parse(ts: str) -> dt.datetime:
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


# ─── The approval settlement cascade ─────────────────

def test_review_settlement_materialises_a_claim_on_the_settled_item(api):
    """PRD §3.2: "2. That settlement materialises claims: for each content item,
    one claim is created against every reference file whose rights-scan match
    reaches a `match_confidence` of at least 0.500."
    PRD §3.3: "one claim is created for each matching reference file, with
    `source` set to `REFERENCE_AUTO` and `match_confidence` set to the scan score"

    Design: Difficulty/transitive_cascade/claim_creation_locks_item_revenue_three_hops
    """
    channel = get_success_data(api_client.create_channel(create_channel_payload(
        channel_name="Cascade US", country_code="US", lifetime_watch_hours=8000,
        subscriber_count=1500, tax_tin_status="TIN_PROVIDED",
        payment_threshold_cents=100), TEST_USERS["anonymous_headers"]))
    creator = make_creator_headers(channel["id"])

    item = validate_success(api.request_review(
        channel["id"],
        get_success_data(api_client.create_content_item(
            channel["id"], create_content_item_payload(title="Cascade Source",
                                                      duration_seconds=900),
            creator))["id"], creator), 200)
    validate_success(api_client.create_revenue_routing(
        create_revenue_routing_payload(item["id"], item["version"], stream_type="AD",
                                       gross_revenue_cents=10000),
        TEST_USERS["platform_admin_headers"]), 201)
    validate_success(api.create_reference_file(
        create_reference_file_payload(rights_holder_name="Cascade Rights",
                                      reference_fingerprint="fp-cascade-1"),
        make_rights_holder_headers("rh-cascade-1")), 201)
    validate_success(api.apply_monetization(channel["id"], creator), 200)

    approved = validate_success(api.review_monetization(
        channel["id"], {"decision": "APPROVE"},
        TEST_USERS["monetization_reviewer_headers"]), 200)
    assert approved["monetization_status"] == "MONETIZATION_APPROVED"

    settled = get_success_data(api.get_content_item(item["id"], TEST_USERS["any_headers"]))
    assert settled["upload_status"] == "CLAIM_SCAN_COMPLETE"

    claims, meta = validate_paginated(api.list_claims(
        TEST_USERS["any_headers"], params={"content_item_id": item["id"]}))
    assert meta["total_count"] >= 1, "the settlement must leave a claim on the item"
    assert claims[0]["source"] == "REFERENCE_AUTO"


def test_review_settlement_locks_revenue_that_was_already_paid_out(api):
    """PRD §3.2: "3. Each claim that is now `ACTIVE` fires the claim-revenue-lock
    cascade. Every revenue routing row belonging to that content item whose status
    is `PAID_CREATOR` is moved to `RETROACTIVE_OWED`, its `creator_share_cents` is
    zeroed and its `partner_share_cents` is raised to the full
    `gross_revenue_cents` of the row, and the content item's
    `routed_revenue_cents` is recomputed to zero."
    PRD §3.2: "4. The same cascade recomputes the content item's `holds_revenue` to
    true."

    Design: Difficulty/transitive_cascade/claim_creation_locks_item_revenue_three_hops
    """
    channel = get_success_data(api_client.create_channel(create_channel_payload(
        channel_name="Cascade Lock US", country_code="US", lifetime_watch_hours=8000,
        subscriber_count=1500, tax_tin_status="TIN_PROVIDED",
        payment_threshold_cents=100), TEST_USERS["anonymous_headers"]))
    creator = make_creator_headers(channel["id"])

    item = validate_success(api.request_review(
        channel["id"],
        get_success_data(api_client.create_content_item(
            channel["id"], create_content_item_payload(title="Cascade Lock Source"),
            creator))["id"], creator), 200)
    routing = validate_success(api_client.create_revenue_routing(
        create_revenue_routing_payload(item["id"], item["version"], stream_type="AD",
                                       gross_revenue_cents=10000),
        TEST_USERS["platform_admin_headers"]), 201)
    assert routing["status"] == "PAID_CREATOR"
    assert routing["creator_share_cents"] == 5500

    validate_success(api.create_reference_file(
        create_reference_file_payload(rights_holder_name="Cascade Lock Rights",
                                      reference_fingerprint="fp-cascadelock-1"),
        make_rights_holder_headers("rh-cascadelock-1")), 201)
    validate_success(api.apply_monetization(channel["id"], creator), 200)
    validate_success(api.review_monetization(channel["id"], {"decision": "APPROVE"},
                                             TEST_USERS["monetization_reviewer_headers"]), 200)

    rows, meta = validate_paginated(api.list_item_routings(
        item["id"], TEST_USERS["any_headers"]))
    assert meta["total_count"] == 1
    locked = rows[0]
    assert locked["status"] == "RETROACTIVE_OWED"
    assert locked["creator_share_cents"] == 0
    assert locked["partner_share_cents"] == 10000
    assert_share_conservation(locked)

    settled = get_success_data(api.get_content_item(item["id"], TEST_USERS["any_headers"]))
    assert settled["routed_revenue_cents"] == 0
    assert settled["holds_revenue"] is True


# ─── Independent state axes on the same subject ──────

def _reinstated_claim(name, rights_holder_id, fingerprint):
    channel = create_approved_channel(channel_name=name, country_code="US",
                                      lifetime_watch_hours=8000, subscriber_count=1500,
                                      tax_tin_status="TIN_PROVIDED",
                                      payment_threshold_cents=100)
    item = validate_success(api_client.request_review(
        channel["id"],
        get_success_data(api_client.create_content_item(
            channel["id"], create_content_item_payload(title=f"{name} Source",
                                                       duration_seconds=800),
            make_creator_headers(channel["id"])))["id"],
        make_creator_headers(channel["id"])), 200)
    ref = validate_success(api_client.create_reference_file(
        create_reference_file_payload(rights_holder_name=f"{name} Rights",
                                      reference_fingerprint=fingerprint),
        make_rights_holder_headers(rights_holder_id)), 201)
    claim = validate_success(api_client.create_claim(
        {"content_item_id": item["id"], "reference_file_id": ref["id"],
         "match_confidence": 0.900},
        make_rights_holder_headers(ref["id"])), 201)
    claim = validate_success(api_client.dispute_claim(
        claim["id"],
        {"expected_claim_version": claim["version"], "reason_code": "FAIR_USE"},
        make_creator_headers(channel["id"])), 200)
    appeal = validate_success(api_client.file_appeal(
        claim["id"], {"grounds_code": "REVIEW_ERROR"},
        make_rights_holder_headers(ref["id"])), 200)
    validate_success(api_client.decide_appeal(
        claim["id"], appeal["id"], {"decision": "UPHOLD"},
        make_rights_holder_headers(ref["id"])), 200)
    return channel, item, claim


def test_appeal_decision_moves_only_the_claim_axis(api):
    """PRD §3.6: "the `ClaimAppeal` row's status becomes `UPHELD`, the claim moves
    to `REINSTATED`, its `lock_reason` returns to `NONE`, and every revenue routing
    row of the claimed content item that sits in `RETROACTIVE_OWED` is moved to
    `RELEASED_TO_CREATOR`"

    Design: Difficulty/non_linear_state_machine/parallel_dimensions_upload_ad_and_claim_axes
    """
    channel, item, claim = _reinstated_claim("Parallel US", "rh-parallel-1",
                                             "fp-parallel-1")

    after = get_success_data(api.get_claim(claim["id"], TEST_USERS["any_headers"]))
    assert after["status"] == "REINSTATED"
    assert after["lock_reason"] == "NONE"

    item_after = get_success_data(api.get_content_item(item["id"], TEST_USERS["any_headers"]))
    assert item_after["upload_status"] == "CLAIM_SCAN_COMPLETE", (
        "an appeal decision touches the claim axis, not the upload axis")


def test_appeal_decision_leaves_the_channel_monetization_axes_untouched(api):
    """PRD §3.6: "the claim moves to `REINSTATED`, its `lock_reason` returns to
    `NONE`"
    PRD §3.2: "An `APPROVE` decision moves the channel from `MONETIZATION_PENDING`
    to `MONETIZATION_APPROVED`"

    Design: Difficulty/non_linear_state_machine/parallel_dimensions_upload_ad_and_claim_axes
    """
    channel, _item, _claim = _reinstated_claim("Parallel Channel US",
                                               "rh-parallel-2", "fp-parallel-2")

    after = get_success_data(api.get_channel(channel["id"], TEST_USERS["any_headers"]))
    assert after["monetization_status"] == "MONETIZATION_APPROVED"
    assert after["monetization_posture"] == "OPEN"
    assert after["copyright_strike_count"] == 0
    assert after["policy_strike_count"] == 0


# ─── Strike expiry arithmetic ────────────────────────

def test_copyright_strike_expires_exactly_ninety_days_after_creation(api):
    """PRD §3.7: "One `CopyrightStrike` row is created in status `ACTIVE`, with
    its `expires_at` set to ninety days after its own creation."

    Design: Corner/state_machines/copyright_strike_issues_with_ninety_day_expiry
    """
    channel = create_approved_channel(channel_name="Strike Clock Channel",
                                      country_code="US", lifetime_watch_hours=4000,
                                      subscriber_count=1000)
    creator = make_creator_headers(channel["id"])
    item = validate_success(api.request_review(
        channel["id"],
        get_success_data(api_client.create_content_item(
            channel["id"], create_content_item_payload(title="Strike Clock Item"),
            creator))["id"], creator), 200)
    ref = validate_success(api.create_reference_file(
        create_reference_file_payload(rights_holder_name="Strike Clock Rights",
                                      reference_fingerprint="fp-strikeclock-1"),
        make_rights_holder_headers("rh-strikeclock-1")), 201)
    claim = validate_success(api.create_claim(
        {"content_item_id": item["id"], "reference_file_id": ref["id"],
         "match_confidence": 0.900},
        make_rights_holder_headers(ref["id"])), 201)
    claim = validate_success(api.dispute_claim(
        claim["id"],
        {"expected_claim_version": claim["version"], "reason_code": "FAIR_USE"},
        creator), 200)
    first = validate_success(api.file_appeal(
        claim["id"], {"grounds_code": "REVIEW_ERROR"},
        make_rights_holder_headers(ref["id"])), 200)
    validate_success(api.decide_appeal(
        claim["id"], first["id"], {"decision": "DENY"},
        make_rights_holder_headers(ref["id"])), 200)
    validate_success(api.file_appeal(
        claim["id"], {"grounds_code": "NEW_EVIDENCE"},
        make_rights_holder_headers(ref["id"])), 200)
    validate_success(api.take_down_claim(claim["id"],
                                        make_rights_holder_headers(ref["id"])), 200)

    strikes, meta = validate_paginated(api.list_channel_copyright_strikes(
        channel["id"], TEST_USERS["any_headers"]))
    assert meta["total_count"] == 1
    strike = strikes[0]
    assert strike["status"] == "ACTIVE"
    assert strike["strike_sequence"] == 1
    assert strike["claim_id"] == claim["id"]

    delta = _parse(strike["expires_at"]) - _parse(strike["created_at"])
    assert delta == dt.timedelta(days=90), (
        f"expires_at must be exactly ninety days after creation, got {delta}")

    after = get_success_data(api.get_channel(channel["id"], TEST_USERS["any_headers"]))
    assert after["copyright_strike_count"] == 1
    assert after["last_copyright_strike_activated_at"] is not None


# ─── Match-confidence floor ──────────────────────────

def test_manual_claim_match_confidence_below_the_floor_is_rejected(api):
    """PRD §2.10: "13. **Match-confidence range** — a manual claim's
    `match_confidence` must lie within the inclusive range from 0.500 to 1.000; a
    value of 0.499 is rejected and 0.500 is accepted, with
    `ERR_INVALID_MATCH_CONFIDENCE` (HTTP 400)."

    Design: Corner/validations/manual_claim_match_confidence_below_the_floor_is_rejected
    """
    channel = get_success_data(api_client.create_channel(create_channel_payload(
        channel_name="Confidence Channel", lifetime_watch_hours=4000,
        subscriber_count=1000), TEST_USERS["anonymous_headers"]))
    creator = make_creator_headers(channel["id"])
    ref = validate_success(api.create_reference_file(
        create_reference_file_payload(rights_holder_name="Confidence Rights",
                                      reference_fingerprint="fp-confidence-1"),
        make_rights_holder_headers("rh-confidence-1")), 201)
    item = validate_success(api.request_review(
        channel["id"],
        get_success_data(api_client.create_content_item(
            channel["id"], create_content_item_payload(title="Confidence Item"),
            creator))["id"], creator), 200)

    rejected = api.create_claim(
        {"content_item_id": item["id"], "reference_file_id": ref["id"],
         "match_confidence": 0.499},
        make_rights_holder_headers(ref["id"]))
    validate_error(rejected, "ERR_INVALID_MATCH_CONFIDENCE", expected_status=400)

    accepted = validate_success(api.create_claim(
        {"content_item_id": item["id"], "reference_file_id": ref["id"],
         "match_confidence": 0.500},
        make_rights_holder_headers(ref["id"])), 201)
    assert accepted["match_confidence"] == 0.500


# ─── Payout lock assembly ────────────────────────────

def _locked_batch(name):
    channel = create_approved_channel(channel_name=name, country_code="US",
                                      lifetime_watch_hours=4000, subscriber_count=1000,
                                      tax_tin_status="TIN_PROVIDED",
                                      payment_threshold_cents=100)
    item = validate_success(api_client.request_review(
        channel["id"],
        get_success_data(api_client.create_content_item(
            channel["id"], create_content_item_payload(title=f"{name} Item"),
            make_creator_headers(channel["id"])))["id"],
        make_creator_headers(channel["id"])), 200)
    validate_success(api_client.create_revenue_routing(
        create_revenue_routing_payload(item["id"], item["version"], stream_type="AD",
                                       gross_revenue_cents=10000),
        TEST_USERS["platform_admin_headers"]), 201)
    current = get_success_data(api_client.get_channel(channel["id"], TEST_USERS["any_headers"]))
    return validate_success(api_client.lock_payout(
        channel["id"], create_payout_lock_payload(current["version"]),
        TEST_USERS["platform_admin_headers"]), 200)


def test_payout_lock_assembles_sums_over_the_period(api):
    """PRD §3.11: "The batch created by the lock carries its `stage` set to `ROUTE`
    and its `status` set to `LOCKED`, and its aggregate fields — `gross_cents`,
    `creator_share_cents`, `partner_share_cents` and `held_cents` — are summed over
    the routed set."
    PRD §3.11: "`gross_cents` sums those rows' gross amounts, `creator_share_cents`
    sums their creator shares, and `held_cents` sums the creator shares of the
    `ESCROW` subset only — money that is parked rather than payable."

    Design: Corner/endpoints/payout_lock_assembles_sums_over_the_period
    """
    batch = _locked_batch("Lock Channel")

    assert batch["stage"] == "ROUTE"
    assert batch["status"] == "LOCKED"
    assert batch["gross_cents"] == 10000
    assert batch["creator_share_cents"] == 5500
    assert batch["partner_share_cents"] == 4500
    assert batch["held_cents"] == 0


def test_payout_lock_conserves_the_split_across_the_routed_set(api):
    """PRD §2.8: "the two shares always sum exactly to the record's gross"
    PRD §3.11: "A batch is always born `LOCKED`; the payment threshold is enforced
    at release time and never at lock time, so a batch that is too small to pay can
    still be assembled and inspected."

    Design: Corner/endpoints/payout_lock_assembles_sums_over_the_period
    """
    batch = _locked_batch("Lock Conservative Channel")

    assert batch["creator_share_cents"] + batch["partner_share_cents"] == batch["gross_cents"], (
        "the assembled batch must conserve the routed gross exactly")
    assert batch["adjusted_net_cents"] == (
        batch["creator_share_cents"] - batch["held_cents"] - batch["tax_withheld_cents"])