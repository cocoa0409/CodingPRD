"""The claim appeal ladder.

Covers the first and second rungs, the denial that returns a claim to DISPUTED,
the bounded appeal count and the post-reinstatement lockout.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_claim,
    create_approved_channel,
    create_claim_payload,
    create_classified_item,
    create_reference_file_payload,
    get_success_data,
    make_creator_headers,
    make_rights_holder_headers,
    validate_error,
    validate_success,
)


def _disputed_claim(name, rights_holder_id="rh-ladder-1", fingerprint="fp-ladder-1"):
    channel = create_approved_channel(channel_name=name, country_code="US",
                                      lifetime_watch_hours=8000, subscriber_count=1500,
                                      tax_tin_status="TIN_PROVIDED",
                                      payment_threshold_cents=100)
    item = create_classified_item(channel["id"], title=f"{name} Source")
    ref = get_success_data(api_client.create_reference_file(
        create_reference_file_payload(rights_holder_name=f"{name} Rights",
                                      reference_fingerprint=fingerprint),
        make_rights_holder_headers(rights_holder_id)))
    claim = validate_success(api_client.create_claim(
        create_claim_payload(item["id"], ref["id"], match_confidence=0.900),
        make_rights_holder_headers(ref["id"])), 201)
    claim = validate_success(api_client.dispute_claim(
        claim["id"],
        {"expected_claim_version": claim["version"], "reason_code": "LICENSED"},
        make_creator_headers(channel["id"])), 200)
    return channel, item, ref, claim


# ─── First rung ──────────────────────────────────────

def test_first_appeal_from_disputed_parks_the_revenue_and_counts_once(api):
    """PRD §3.6: "The first rung opens while the claim is `DISPUTED`, provided
    `appeal_count` is zero and the referenced content item is not currently taken
    down."
    PRD §3.6: "The system creates a `ClaimAppeal` row with `appeal_level` set to
    `FIRST` and `status` set to `PENDING`, moves the claim to `APPEALED`, sets the
    claim's `lock_reason` to `RETROACTIVE_OWED`, and recomputes both
    `appeal_attempts` and `appeal_count`."

    Design: Difficulty/non_linear_state_machine/claim_dispute_appeal_cycle_with_bounded_rounds
    """
    channel, _item, ref, claim = _disputed_claim("Cycle US")

    appeal = validate_success(api_client.file_appeal(
        claim["id"], {"grounds_code": "REVIEW_ERROR"},
        make_rights_holder_headers(ref["id"])), 200)
    assert appeal["appeal_level"] == "FIRST"
    assert appeal["status"] == "PENDING"

    after = get_success_data(api_client.get_claim(claim["id"], TEST_USERS["any_headers"]))
    assert_claim(after)
    assert after["status"] == "APPEALED"
    assert after["lock_reason"] == "RETROACTIVE_OWED"
    assert after["appeal_attempts"] == 1
    assert after["appeal_count"] == 1


def test_upholding_a_first_appeal_reinstates_the_claim(api):
    """PRD §3.6: "the `ClaimAppeal` row's status becomes `UPHELD`, the claim moves
    to `REINSTATED`, its `lock_reason` returns to `NONE`"

    Design: Difficulty/non_linear_state_machine/claim_dispute_appeal_cycle_with_bounded_rounds
    """
    channel, _item, ref, claim = _disputed_claim("Reinstate US", "rh-reinstate-1",
                                                 "fp-reinstate-1")
    appeal = validate_success(api_client.file_appeal(
        claim["id"], {"grounds_code": "REVIEW_ERROR"},
        make_rights_holder_headers(ref["id"])), 200)

    decided = validate_success(api_client.decide_appeal(
        claim["id"], appeal["id"], {"decision": "UPHOLD"},
        make_rights_holder_headers(ref["id"])), 200)
    assert decided["status"] == "UPHELD"

    after = get_success_data(api_client.get_claim(claim["id"], TEST_USERS["any_headers"]))
    assert after["status"] == "REINSTATED"
    assert after["lock_reason"] == "NONE"


def test_denying_a_first_appeal_returns_the_claim_to_disputed(api):
    """PRD §3.6: "Denying is the softer outcome: the `ClaimAppeal` row becomes
    `DENIED`, the claim returns to `DISPUTED`"
    PRD §3.6: "and the claim's `lock_reason` stays `RETROACTIVE_OWED`, so the
    money remains parked"

    Design: Difficulty/non_linear_state_machine/claim_dispute_appeal_cycle_with_bounded_rounds
    """
    channel, _item, ref, claim = _disputed_claim("Deny US", "rh-deny-1", "fp-deny-1")
    appeal = validate_success(api_client.file_appeal(
        claim["id"], {"grounds_code": "REVIEW_ERROR"},
        make_rights_holder_headers(ref["id"])), 200)

    decided = validate_success(api_client.decide_appeal(
        claim["id"], appeal["id"], {"decision": "DENY"},
        make_rights_holder_headers(ref["id"])), 200)
    assert decided["status"] == "DENIED"

    after = get_success_data(api_client.get_claim(claim["id"], TEST_USERS["any_headers"]))
    assert after["status"] == "DISPUTED", "denial reopens the state a second rung needs"
    assert after["lock_reason"] == "RETROACTIVE_OWED"


# ─── Second rung and the bounded ladder ──────────────

def test_second_appeal_from_a_denied_first_rung_is_recorded_as_second(api):
    """PRD §3.6: "The second rung opens from `DISPUTED` once `appeal_attempts` has
    reached exactly 1 and the most recently filed appeal has been decided — that
    is, it carries status `DENIED` or `UPHELD` at level `FIRST`."
    PRD §3.6: "The filing creates a `ClaimAppeal` row with `appeal_level` set to
    `SECOND` and `status` set to `PENDING`, returns the claim to `APPEALED`, sets
    `lock_reason` to `RETROACTIVE_OWED`, and recomputes `appeal_attempts` and
    `appeal_count` once more."

    Design: Difficulty/non_linear_state_machine/claim_dispute_appeal_cycle_with_bounded_rounds
    """
    channel, _item, ref, claim = _disputed_claim("Second US", "rh-second-1",
                                                 "fp-second-1")
    first = validate_success(api_client.file_appeal(
        claim["id"], {"grounds_code": "REVIEW_ERROR"},
        make_rights_holder_headers(ref["id"])), 200)
    validate_success(api_client.decide_appeal(
        claim["id"], first["id"], {"decision": "DENY"},
        make_rights_holder_headers(ref["id"])), 200)

    second = validate_success(api_client.file_appeal(
        claim["id"], {"grounds_code": "NEW_EVIDENCE"},
        make_rights_holder_headers(ref["id"])), 200)
    assert second["appeal_level"] == "SECOND"
    assert second["status"] == "PENDING"

    after = get_success_data(api_client.get_claim(claim["id"], TEST_USERS["any_headers"]))
    assert after["status"] == "APPEALED"
    assert after["appeal_attempts"] == 2
    assert after["lock_reason"] == "RETROACTIVE_OWED"


def test_third_appeal_on_a_fully_appealed_claim_is_rejected(api):
    """PRD §3.6: "Attempting a third appeal, or attempting a second-level appeal
    before any first-level appeal has been decided, is refused with
    `ERR_APPEAL_LIMIT_REACHED` (HTTP 409)."
    PRD §3.6: "At most two attempts are recorded against any claim."

    Design: Corner/validations/third_appeal_on_a_fully_appealed_claim_is_rejected
    """
    channel, _item, ref, claim = _disputed_claim("Appeal Limit Channel",
                                                 "rh-appeallimit-1",
                                                 "fp-appeallimit-1")
    first = validate_success(api_client.file_appeal(
        claim["id"], {"grounds_code": "REVIEW_ERROR"},
        make_rights_holder_headers(ref["id"])), 200)
    validate_success(api_client.decide_appeal(
        claim["id"], first["id"], {"decision": "DENY"},
        make_rights_holder_headers(ref["id"])), 200)
    second = validate_success(api_client.file_appeal(
        claim["id"], {"grounds_code": "NEW_EVIDENCE"},
        make_rights_holder_headers(ref["id"])), 200)
    validate_success(api_client.decide_appeal(
        claim["id"], second["id"], {"decision": "DENY"},
        make_rights_holder_headers(ref["id"])), 200)

    res = api.file_appeal(claim["id"], {"grounds_code": "MISIDENTIFIED"},
                          make_rights_holder_headers(ref["id"]))
    validate_error(res, "ERR_APPEAL_LIMIT_REACHED", expected_status=409)

    after = get_success_data(api_client.get_claim(claim["id"], TEST_USERS["any_headers"]))
    assert after["appeal_attempts"] == 2
    assert after["status"] == "DISPUTED"


# ─── The post-reinstatement lockout ──────────────────

def test_reappeal_at_exactly_fourteen_days_after_reinstatement_succeeds(api):
    """PRD §3.6: "It may be appealed again once fourteen days have elapsed since
    the reinstatement"
    PRD §3.6: "the filing requires the claim to be in `REINSTATED` and the logical
    clock to be at or past that appeal's `created_at` plus fourteen days"

    Design: Difficulty/resource_temporal_overlap/dispute_window_half_open_versus_appeal_lockout_closed
    """
    channel, _item, ref, claim = _disputed_claim("Windows US", "rh-windows-1",
                                                 "fp-windows-1")
    first = validate_success(api_client.file_appeal(
        claim["id"], {"grounds_code": "REVIEW_ERROR"},
        make_rights_holder_headers(ref["id"])), 200)
    validate_success(api_client.decide_appeal(
        claim["id"], first["id"], {"decision": "UPHOLD"},
        make_rights_holder_headers(ref["id"])), 200)

    reinstated = get_success_data(api_client.get_claim(claim["id"], TEST_USERS["any_headers"]))
    assert reinstated["status"] == "REINSTATED"

    validate_success(api_client.set_clock("2026-09-15T00:00:00Z",
                                          TEST_USERS["platform_admin_headers"]), 200)

    second = validate_success(api_client.file_appeal(
        claim["id"], {"grounds_code": "NEW_EVIDENCE"},
        make_rights_holder_headers(ref["id"])), 200)
    assert second["appeal_level"] == "FIRST"
    assert second["status"] == "PENDING"

    after = get_success_data(api_client.get_claim(claim["id"], TEST_USERS["any_headers"]))
    assert after["status"] == "APPEALED"


def test_reappeal_before_the_lockout_lapses_is_refused(api):
    """PRD §3.6: "A re-appeal attempted before the lockout lapses is refused with
    `ERR_APPEAL_LOCKOUT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/dispute_window_half_open_versus_appeal_lockout_closed
    """
    channel, _item, ref, claim = _disputed_claim("Lockout US", "rh-lockout-1",
                                                 "fp-lockout-1")
    first = validate_success(api_client.file_appeal(
        claim["id"], {"grounds_code": "REVIEW_ERROR"},
        make_rights_holder_headers(ref["id"])), 200)
    validate_success(api_client.decide_appeal(
        claim["id"], first["id"], {"decision": "UPHOLD"},
        make_rights_holder_headers(ref["id"])), 200)

    res = api.file_appeal(claim["id"], {"grounds_code": "NEW_EVIDENCE"},
                          make_rights_holder_headers(ref["id"]))
    validate_error(res, "ERR_APPEAL_LOCKOUT", expected_status=409)


def test_reappeal_one_second_before_the_far_edge_is_refused(api):
    """PRD §3.6: "the filing requires the claim to be in `REINSTATED` and the
    logical clock to be at or past that appeal's `created_at` plus fourteen days"
    PRD §3.6: "A re-appeal attempted before the lockout lapses is refused with
    `ERR_APPEAL_LOCKOUT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/dispute_window_half_open_versus_appeal_lockout_closed
    """
    channel, _item, ref, claim = _disputed_claim("Lockout Edge US", "rh-lockout-edge-1",
                                                 "fp-lockout-edge-1")
    first = validate_success(api_client.file_appeal(
        claim["id"], {"grounds_code": "REVIEW_ERROR"},
        make_rights_holder_headers(ref["id"])), 200)
    validate_success(api_client.decide_appeal(
        claim["id"], first["id"], {"decision": "UPHOLD"},
        make_rights_holder_headers(ref["id"])), 200)

    validate_success(api_client.set_clock("2026-09-14T23:59:59Z",
                                          TEST_USERS["platform_admin_headers"]), 200)

    res = api.file_appeal(claim["id"], {"grounds_code": "NEW_EVIDENCE"},
                          make_rights_holder_headers(ref["id"]))
    validate_error(res, "ERR_APPEAL_LOCKOUT", expected_status=409)