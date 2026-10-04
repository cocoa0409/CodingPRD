"""Cross-entity cascades: suspension chain, transfer acceptance, billing failure."""
from test_helpers import (
    ApiErrorId,
    admin_headers,
    create_account,
    create_account_with_assigned_slot,
    create_account_with_device,
    create_account_with_slot,
    get_account,
    get_success_data,
    grant_pass,
    simulate_billing_payload,
    validate_paginated,
)


def test_suspend_cascades_device_pass_metric(api):
    """PRD §2.10: "Suspending an account ends every active playback session
    across all of its members, untrusts every trusted device of its household,
    and revokes each affected device's active travel passes — and each such pass
    revocation records a churn-signal enforcement metric on the account."

    Design: Difficulty/transitive_cascade/suspend_cascades_device_pass_metric
    """
    account, household, device, owner_h = create_account_with_device(
        email="tc1@x.com", trust=True
    )
    pass_ = grant_pass(device["id"], owner_h)

    suspended = get_success_data(api.suspend_account(account["id"], admin_headers()))
    assert suspended["status"] == "SUSPENDED"

    device_after = get_success_data(api.get_device(device["id"], admin_headers()))
    assert device_after["trust_status"] == "UNTRUSTED"

    pass_after = get_success_data(api.get_travel_pass(pass_["id"], admin_headers()))
    assert pass_after["status"] == "REVOKED"

    metrics, meta = validate_paginated(api.list_metrics(account["id"], admin_headers()))
    assert meta["total_count"] == 1
    assert metrics[0]["metric_type"] == "CHURN_SIGNAL"

    household_after = get_success_data(api.get_household(household["id"], admin_headers()))
    assert household_after["trusted_device_count"] == 0


def test_suspend_cascade_ends_sessions_and_bumps_version(api):
    """PRD §3.1: "Suspension triggers the full cascade described in §2.10: every
    `ACTIVE` playback session of every member of the account is ended (with
    `ended_at` set to the current logical time and each ended session
    decrementing its member's `current_streams`) ... The account's `version`
    increments by 1."

    Design: Difficulty/transitive_cascade/suspend_cascades_device_pass_metric
    """
    account, household, device, owner_h = create_account_with_device(
        email="tc1b@x.com", trust=True
    )
    session = get_success_data(
        api.start_playback(account["owner_member_id"], {"device_id": device["id"], "requested_resolution": "HD"}, owner_h)
    )
    suspended = get_success_data(api.suspend_account(account["id"], admin_headers()))
    assert suspended["status"] == "SUSPENDED"
    assert suspended["version"] == 2

    session_after = get_success_data(api.get_playback_session(session["id"], admin_headers()))
    assert session_after["status"] == "ENDED"
    assert session_after["ended_at"] is not None

    owner_after = get_success_data(api.get_member(account["owner_member_id"], admin_headers()))
    assert owner_after["current_streams"] == 0


def test_transfer_accept_cascades_member_move_slot_revoke(api):
    """PRD §3.8: "the member row itself moves — `account_id` rewritten to the new
    account, `member_role` rewritten to `OWNER`, status remaining `ACTIVE`" and
    "if the moving member was assigned to an `ACTIVE` `ExtraMemberSlot`, that
    slot transitions to `REVOKED` with `credit_cents` 0".

    Design: Difficulty/transitive_cascade/transfer_accept_cascades_member_move_slot_revoke
    """
    account, slot, extra_id, owner_h = create_account_with_assigned_slot(
        email="tc2@x.com", extra_email="extra-tc2@x.com"
    )
    transfer = get_success_data(
        api.initiate_transfer(account["id"], {"member_id": extra_id, "target_email": "newhome-tc2@x.com"}, owner_h)
    )
    accepted = get_success_data(
        api.accept_transfer(
            transfer["id"],
            {
                "new_account_email": "newhome-tc2@x.com",
                "new_account_region": "NA",
                "new_account_plan_tier": "BASIC",
                "expected_profile_transfer_version": transfer["version"],
            },
            admin_headers(),
        )
    )
    assert accepted["status"] == "COMPLETED"
    target_account_id = accepted["target_account_id"]
    assert target_account_id

    member_after = get_success_data(api.get_member(extra_id, admin_headers()))
    assert member_after["account_id"] == target_account_id
    assert member_after["member_role"] == "OWNER"
    assert member_after["status"] == "ACTIVE"

    slot_after = get_success_data(api.get_slot(slot["id"], admin_headers()))
    assert slot_after["status"] == "REVOKED"
    assert slot_after["credit_cents"] == 0

    members, meta = validate_paginated(
        api.list_members(account["id"], admin_headers(), params={"status": "ACTIVE"})
    )
    assert meta["total_count"] == 1, "only the original OWNER remains ACTIVE"


def test_transfer_accept_preserves_history_and_seed(api):
    """PRD §3.8: "with `viewing_history` and `recommendation_seed` preserved
    verbatim (the snapshots exist for audit, the live fields are what travel)".

    Design: Difficulty/transitive_cascade/transfer_accept_cascades_member_move_slot_revoke
    """
    account, slot, extra_id, owner_h = create_account_with_assigned_slot(
        email="tc2b@x.com", extra_email="extra-tc2b@x.com"
    )
    member_before = get_success_data(api.get_member(extra_id, owner_h))
    transfer = get_success_data(
        api.initiate_transfer(account["id"], {"member_id": extra_id, "target_email": "newhome-tc2b@x.com"}, owner_h)
    )
    assert transfer["history_snapshot"] == member_before["viewing_history"]
    assert transfer["recommendation_snapshot"] == member_before["recommendation_seed"]

    accepted = get_success_data(
        api.accept_transfer(
            transfer["id"],
            {
                "new_account_email": "newhome-tc2b@x.com",
                "new_account_region": "NA",
                "new_account_plan_tier": "BASIC",
                "expected_profile_transfer_version": transfer["version"],
            },
            admin_headers(),
        )
    )
    assert accepted["status"] == "COMPLETED"

    member_after = get_success_data(api.get_member(extra_id, admin_headers()))
    assert member_after["viewing_history"] == member_before["viewing_history"]
    assert member_after["recommendation_seed"] == member_before["recommendation_seed"]

    target = get_success_data(api.get_account(accepted["target_account_id"], admin_headers()))
    assert target["email"] == "newhome-tc2b@x.com"
    assert target["owner_member_id"] == extra_id


def test_billing_failure_lapses_slot(api):
    """PRD §3.9: "when the outcome is `FAILED`, an `ACTIVE` account is suspended
    with the full cascade of §3.1 ... and additionally every slot of the account
    in `OFFERED` or `ACTIVE` lapses to `LAPSED` per §3.6 — `OFFERED` slots lapse
    with no credit and no member impact".

    Design: Corner/cross_cutting_layers/billing_failure_lapses_slot
    """
    account, slot, owner_h = create_account_with_slot(email="corner-bill@x.com")

    result = get_success_data(
        api.simulate_billing(simulate_billing_payload(account["id"], "FAILED"), admin_headers())
    )
    assert result["status"] == "SUSPENDED"

    slot_after = get_success_data(api.get_slot(slot["id"], admin_headers()))
    assert slot_after["status"] == "LAPSED"

    after = get_account(account["id"])
    assert after["extra_member_billed_cents"] == 799
    assert after["extra_member_credit_cents"] == 0
