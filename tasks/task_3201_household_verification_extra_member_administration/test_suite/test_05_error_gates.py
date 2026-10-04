"""Error gating: priority pairs, state gates, cross-entity preconditions."""
from test_helpers import (
    ApiErrorId,
    WRONG_CODE,
    admin_headers,
    create_account,
    create_account_with_assigned_slot,
    create_account_with_device,
    create_account_with_household,
    create_account_with_slot,
    get_account,
    get_success_data,
    issue_challenge,
    lock_out_challenge,
    purchase_slot_payload,
    submit_challenge_payload,
    validate_error,
    validate_paginated,
)


def test_suspended_state_beats_slot_limit(api):
    """PRD §3.1: "While an account is `SUSPENDED`, new revenue or usage operations
    are refused with `ERR_ACCOUNT_SUSPENDED` (HTTP 409): purchasing, assigning, or
    re-offering extra-member slots".

    Design: Difficulty/priority_pair_validation_conflict/suspended_state_beats_slot_limit
    """
    account, slot, owner_h = create_account_with_slot(email="pp1@x.com")
    get_success_data(api.suspend_account(account["id"], admin_headers()))
    fresh = get_account(account["id"])

    resp = api.purchase_slot(
        account["id"],
        purchase_slot_payload(account["owner_member_id"], fresh["version"]),
        owner_h,
    )
    error_data = validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED)
    assert error_data["error_id"] != ApiErrorId.ERR_SLOT_LIMIT_EXCEEDED

    after = get_account(account["id"])
    assert after["extra_member_billed_cents"] == 799, "no second charge"


def test_suspended_state_beats_slot_limit_still_suspended(api):
    """PRD §3.1: "While an account is `SUSPENDED`, new revenue or usage operations
    are refused with `ERR_ACCOUNT_SUSPENDED` (HTTP 409)". The slot count stays at
    the pre-suspension level after the refused purchase.

    Design: Difficulty/priority_pair_validation_conflict/suspended_state_beats_slot_limit
    """
    account, slot, owner_h = create_account_with_slot(email="pp1b@x.com")
    get_success_data(api.suspend_account(account["id"], admin_headers()))
    fresh = get_account(account["id"])

    resp = api.purchase_slot(
        account["id"],
        purchase_slot_payload(account["owner_member_id"], fresh["version"]),
        owner_h,
    )
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED)

    slots, meta = validate_paginated(api.list_account_slots(account["id"], admin_headers()))
    assert meta["total_count"] == 1, "the refused purchase created no slot"
    after = get_account(account["id"])
    assert after["status"] == "SUSPENDED"


def test_challenge_locked_safety_beats_member_referential(api):
    """PRD §3.4: "Submission against a `LOCKED_OUT` challenge is rejected with
    `ERR_CHALLENGE_LOCKED` (HTTP 409)." PRD §3.4: "when that increment reaches the
    channel's attempt cap — 3 attempts for `EMAIL` and `SMS`, 5 for `VOICE_CALL` —
    the challenge transitions `PENDING` → `LOCKED_OUT` and the account's
    `verification_posture` becomes `LOCKED`."

    Design: Difficulty/priority_pair_validation_conflict/challenge_locked_safety_beats_member_referential
    """
    account_a, owner_a_h = create_account(email="pp2a@x.com")
    challenge = issue_challenge(account_a["id"], channel="EMAIL", challenge_reason="NEW_DEVICE")
    lock_out_challenge(challenge["id"], account_a["owner_member_id"], owner_a_h, attempts=3)

    locked = get_success_data(api.get_challenge(challenge["id"], admin_headers()))
    assert locked["status"] == "LOCKED_OUT"
    acc_after = get_account(account_a["id"])
    assert acc_after["verification_posture"] == "LOCKED"

    account_b, owner_b_h = create_account(email="pp2b@x.com")
    # Headers identity must belong to the challenged account (§2.1 RBAC runs
    # before state gates per §2.3); the body member_id is the referential
    # mismatch the LOCKED_OUT state gate must beat.
    resp = api.submit_challenge(
        challenge["id"],
        submit_challenge_payload(WRONG_CODE, account_b["owner_member_id"]),
        owner_a_h,
    )
    error_data = validate_error(resp, ApiErrorId.ERR_CHALLENGE_LOCKED)
    assert error_data["error_id"] != ApiErrorId.ERR_MEMBER_NOT_IN_ACCOUNT


def test_challenge_lockout_at_email_attempt_cap(api):
    """PRD §3.4: "when that increment reaches the channel's attempt cap — 3
    attempts for `EMAIL` and `SMS`, 5 for `VOICE_CALL` — the challenge
    transitions `PENDING` → `LOCKED_OUT` and the account's `verification_posture`
    becomes `LOCKED`."

    Design: Difficulty/priority_pair_validation_conflict/challenge_locked_safety_beats_member_referential
    """
    account, owner_h = create_account(email="pp2c@x.com")
    challenge = issue_challenge(account["id"], channel="EMAIL")

    for i in (1, 2):
        resp = api.submit_challenge(
            challenge["id"], submit_challenge_payload(WRONG_CODE, account["owner_member_id"]), owner_h
        )
        validate_error(resp, ApiErrorId.ERR_CHALLENGE_CODE_MISMATCH)
        mid = get_success_data(api.get_challenge(challenge["id"], admin_headers()))
        assert mid["status"] == "PENDING"
        assert mid["attempts_used"] == i

    resp = api.submit_challenge(
        challenge["id"], submit_challenge_payload(WRONG_CODE, account["owner_member_id"]), owner_h
    )
    validate_error(resp, ApiErrorId.ERR_CHALLENGE_CODE_MISMATCH)
    locked = get_success_data(api.get_challenge(challenge["id"], admin_headers()))
    assert locked["status"] == "LOCKED_OUT"
    assert get_account(account["id"])["verification_posture"] == "LOCKED"


def test_playback_requires_device_trusted(api):
    """PRD §3.7: "First, the device must exist, belong to the account's household,
    and either be `TRUSTED` or hold an `ACTIVE` travel pass; otherwise the request
    is rejected with `ERR_DEVICE_NOT_TRUSTED` (HTTP 403)."

    Design: Difficulty/cross_entity_state_dependency/playback_requires_device_trusted
    """
    account, household, device, owner_h = create_account_with_device(
        email="ce1@x.com", trust=False
    )
    resp = api.start_playback(
        account["owner_member_id"], {"device_id": device["id"], "requested_resolution": "HD"}, owner_h
    )
    validate_error(resp, ApiErrorId.ERR_DEVICE_NOT_TRUSTED)

    device_after = get_success_data(api.get_device(device["id"], owner_h))
    assert device_after["trust_status"] == "UNTRUSTED"
    owner_after = get_success_data(api.get_member(account["owner_member_id"], owner_h))
    assert owner_after["current_streams"] == 0


def test_playback_admitted_with_active_travel_pass(api):
    """PRD §3.7: "the device must exist, belong to the account's household, and
    either be `TRUSTED` or hold an `ACTIVE` travel pass" — an UNTRUSTED device
    holding an ACTIVE travel pass satisfies the device gate.

    Design: Difficulty/cross_entity_state_dependency/playback_requires_device_trusted
    """
    account, household, device, owner_h = create_account_with_device(
        email="ce1b@x.com",
        device_network="fp-away-1",
        device_geo="geo-away-1",
        device_type="MOBILE",
        trust=False,
    )
    get_success_data(
        api.grant_travel_pass(device["id"], {"grant_type": "TEMPORARY_14D", "starts_at": "2026-09-01T00:00:00Z"}, owner_h)
    )
    session = get_success_data(
        api.start_playback(account["owner_member_id"], {"device_id": device["id"], "requested_resolution": "HD"}, owner_h)
    )
    assert session["status"] == "ACTIVE"
    assert session["resolution_granted"] == "HD"


def test_slot_assign_requires_verified_posture(api):
    """PRD §3.1: "Two account-level operations require the posture to be
    `VERIFIED` and are otherwise rejected with `ERR_ACCOUNT_NOT_VERIFIED`
    (HTTP 409): marking a device trusted, and assigning an extra-member slot."

    Design: Difficulty/cross_entity_state_dependency/slot_assign_requires_verified_posture
    """
    account, slot, owner_h = create_account_with_slot(email="ce2@x.com")
    issue_challenge(account["id"])  # flips posture to CHALLENGE_PENDING

    resp = api.assign_slot(
        slot["id"], {"email": "extra-ce2@x.com", "display_name": "Extra CE2", "member_region": "NA"}, owner_h
    )
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_VERIFIED)

    slot_after = get_success_data(api.get_slot(slot["id"], owner_h))
    assert slot_after["status"] == "OFFERED"
    assert get_account(account["id"])["verification_posture"] == "CHALLENGE_PENDING"


def test_device_trust_requires_verified_posture(api):
    """PRD §3.1: "Two account-level operations require the posture to be
    `VERIFIED` and are otherwise rejected with `ERR_ACCOUNT_NOT_VERIFIED`
    (HTTP 409): marking a device trusted, and assigning an extra-member slot."

    Design: Difficulty/cross_entity_state_dependency/slot_assign_requires_verified_posture
    """
    account, household, device, owner_h = create_account_with_device(
        email="ce2b@x.com", trust=False
    )
    issue_challenge(account["id"])  # posture CHALLENGE_PENDING

    resp = api.trust_device(device["id"], owner_h)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_VERIFIED)
    device_after = get_success_data(api.get_device(device["id"], owner_h))
    assert device_after["trust_status"] == "UNTRUSTED"


def test_extra_member_region_mismatch_rejected(api):
    """PRD §3.6: "the extra member's region to equal the account's `region_code`
    — a cross-region assignment is rejected with `ERR_REGION_MISMATCH` (HTTP
    422)."

    Design: Corner/errors/extra_member_region_mismatch_rejected
    """
    account, slot, owner_h = create_account_with_slot(email="corner-region@x.com")
    resp = api.assign_slot(
        slot["id"], {"email": "extra-region@x.com", "display_name": "Extra Reg", "member_region": "EMEA"}, owner_h
    )
    validate_error(resp, ApiErrorId.ERR_REGION_MISMATCH)
    slot_after = get_success_data(api.get_slot(slot["id"], owner_h))
    assert slot_after["status"] == "OFFERED"


def test_profile_transfer_target_self_rejected(api):
    """PRD §3.8: "The target email must differ from the source account's own
    `email`; a self-addressed transfer is rejected with `ERR_TRANSFER_TARGET_SELF`
    (HTTP 422)."

    Design: Corner/errors/profile_transfer_target_self_rejected
    """
    account, slot, extra_id, owner_h = create_account_with_assigned_slot(
        email="corner-self@x.com", extra_email="extra-self@x.com"
    )
    resp = api.initiate_transfer(
        account["id"], {"member_id": extra_id, "target_email": "corner-self@x.com"}, owner_h
    )
    validate_error(resp, ApiErrorId.ERR_TRANSFER_TARGET_SELF)

    transfers, meta = validate_paginated(api.list_account_transfers(account["id"], owner_h))
    assert meta["total_count"] == 0


def test_second_household_rejected(api):
    """PRD §3.2: "At most one household per account may be non-dissolved at any
    moment: attempting to establish a second household while one exists in any
    status other than `DISSOLVED` is rejected with
    `ERR_ACCOUNT_ALREADY_HAS_HOUSEHOLD` (HTTP 409)."

    Design: Corner/endpoints/second_household_rejected
    """
    account, household, owner_h = create_account_with_household(email="corner-hh2@x.com")
    resp = api.create_household(
        account["id"],
        {"label": "Cabin", "primary_location": "7 Lake Rd", "network_fingerprint": "fp-cabin-1", "geo_cell": "geo-cabin-1"},
        owner_h,
    )
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_ALREADY_HAS_HOUSEHOLD)

    households, meta = validate_paginated(api.list_households(account["id"], owner_h))
    assert meta["total_count"] == 1
