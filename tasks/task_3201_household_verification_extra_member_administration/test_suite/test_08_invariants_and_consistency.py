"""Compensating invariants, immediate consistency, churn summary, and OCC."""
import pytest

from test_helpers import (
    ApiErrorId,
    admin_headers,
    assert_revenue_invariants,
    create_account,
    create_account_with_assigned_slot,
    create_account_with_device,
    get_account,
    get_success_data,
    purchase_slot,
    purchase_slot_payload,
    set_clock,
    support_headers,
    validate_error,
)


def test_slot_purchase_grace_revoke_revenue_conservation(api):
    """PRD §3.1: "The net-revenue counter is always the billed lifetime gross
    minus the lifetime revocation credits and is never decremented by any other
    event." PRD §3.6: "If the revocation occurs within 7 cycle-days of the slot's
    `purchased_day` ... the credit equals the full `price_cents_snapshot`."

    Design: Difficulty/compensating_invariant/slot_purchase_grace_revoke_revenue_conservation
    """
    account, slot, extra_id, owner_h = create_account_with_assigned_slot(
        email="ci1@x.com", extra_email="extra-ci1@x.com"
    )
    before = get_account(account["id"])
    assert before["extra_member_net_revenue_cents"] == 799

    set_clock("2026-09-05T00:00:00Z")  # within the 7-cycle-day full-credit window
    revoked = get_success_data(api.revoke_slot(slot["id"], owner_h))
    assert revoked["credit_cents"] == 799

    after = get_account(account["id"])
    assert after["extra_member_billed_cents"] == 799
    assert after["extra_member_credit_cents"] == 799
    assert after["extra_member_net_revenue_cents"] == 0
    assert_revenue_invariants(after)


def test_slot_purchase_grace_revoke_member_removed(api):
    """PRD §3.6: "The computed credit is stored as the slot's `credit_cents` (0
    until revoked) and added to the account's `extra_member_credit_cents`, and the
    assigned member is transitioned to `REMOVED`."

    Design: Difficulty/compensating_invariant/slot_purchase_grace_revoke_revenue_conservation
    """
    account, slot, extra_id, owner_h = create_account_with_assigned_slot(
        email="ci1b@x.com", extra_email="extra-ci1b@x.com"
    )
    set_clock("2026-09-05T00:00:00Z")
    revoked = get_success_data(api.revoke_slot(slot["id"], owner_h))
    assert revoked["status"] == "REVOKED"
    assert revoked["credit_cents"] == 799

    member_after = get_success_data(api.get_member(extra_id, admin_headers()))
    assert member_after["status"] == "REMOVED"

    after = get_account(account["id"])
    assert after["extra_member_credit_cents"] == 799
    assert after["extra_member_net_revenue_cents"] == 0


def test_download_create_delete_counter_conservation(api):
    """PRD §3.7: "Deleting an `ACTIVE` download transitions it to `DELETED` and
    decrements `downloads_used_this_month` by 1, freeing its slot in the monthly
    allowance".

    Design: Difficulty/compensating_invariant/download_create_delete_counter_conservation
    """
    account, household, device, owner_h = create_account_with_device(
        email="ci2@x.com", plan_tier="BASIC", trust=True, device_type="MOBILE"
    )
    owner_id = account["owner_member_id"]
    owner_before = get_success_data(api.get_member(owner_id, owner_h))
    assert owner_before["downloads_used_this_month"] == 0

    download = get_success_data(
        api.create_download(owner_id, {"device_id": device["id"], "title_id": "t-inv"}, owner_h)
    )
    owner_mid = get_success_data(api.get_member(owner_id, owner_h))
    assert owner_mid["downloads_used_this_month"] == 1

    deleted = get_success_data(api.delete_download(download["id"], owner_h))
    assert deleted["status"] == "DELETED"

    owner_after = get_success_data(api.get_member(owner_id, owner_h))
    assert owner_after["downloads_used_this_month"] == 0


def test_download_delete_frees_allowance_slot(api):
    """PRD §3.7: "Deleting an `ACTIVE` download transitions it to `DELETED` and
    decrements `downloads_used_this_month` by 1, freeing its slot in the monthly
    allowance" — after filling the BASIC allowance of 5 and deleting one, a new
    download succeeds again.

    Design: Difficulty/compensating_invariant/download_create_delete_counter_conservation
    """
    account, household, device, owner_h = create_account_with_device(
        email="ci2b@x.com", plan_tier="BASIC", trust=True, device_type="MOBILE"
    )
    owner_id = account["owner_member_id"]
    downloads = [
        get_success_data(api.create_download(owner_id, {"device_id": device["id"], "title_id": f"t{i}"}, owner_h))
        for i in range(5)
    ]
    resp = api.create_download(owner_id, {"device_id": device["id"], "title_id": "t6"}, owner_h)
    validate_error(resp, ApiErrorId.ERR_DOWNLOAD_LIMIT_REACHED)

    get_success_data(api.delete_download(downloads[0]["id"], owner_h))
    sixth = get_success_data(
        api.create_download(owner_id, {"device_id": device["id"], "title_id": "t6"}, owner_h)
    )
    assert sixth["status"] == "ACTIVE"


def test_slot_purchase_immediately_visible(api):
    """PRD §3.6: "The fee charged is computed at purchase and stored on the slot
    as `price_cents_snapshot`" and "A successful purchase creates the slot in
    status `OFFERED` with `member_id` null, adds the charged fee to the account's
    `extra_member_billed_cents` (which never decreases), and increments the
    account's `version` by 1."

    Design: Corner/consistency_model/slot_purchase_immediately_visible
    """
    account, owner_h = create_account(email="corner-imm@x.com")
    slot = purchase_slot(account, owner_h)
    assert slot["price_cents_snapshot"] == 799
    assert slot["status"] == "OFFERED"
    assert slot["member_id"] is None

    after = get_account(account["id"])
    assert after["extra_member_billed_cents"] == 799
    assert after["extra_member_net_revenue_cents"] == 799


def test_churn_summary_gross_vs_net(api):
    """PRD §3.9: "The `gross_churn_rate` is the churn-signal count divided by that
    denominator, counting every churn signal regardless of winbacks. The
    `net_churn_rate` subtracts winbacks from churn signals first, floors the
    difference at zero, and divides by the same denominator."

    Design: Corner/calculations/churn_summary_gross_vs_net
    """
    account, owner_h = create_account(email="corner-churn@x.com")
    get_success_data(api.record_metric(account["id"], {"metric_type": "CHURN_SIGNAL", "notes": "exit survey"}, support_headers()))
    get_success_data(api.record_metric(account["id"], {"metric_type": "CHURN_SIGNAL", "notes": "cancel intent"}, support_headers()))
    get_success_data(api.record_metric(account["id"], {"metric_type": "WINBACK", "notes": "returned"}, support_headers()))

    summary = get_success_data(api.get_churn_summary(account["id"], support_headers()))
    assert summary["churn_signals"] == 2
    assert summary["winbacks"] == 1
    assert summary["active_flag"] == 1
    assert summary["gross_churn_rate"] == pytest.approx(0.5, abs=1e-4)
    assert summary["net_churn_rate"] == pytest.approx(0.25, abs=1e-4)
    assert summary["gross_churn_rate"] != summary["net_churn_rate"]


def test_occ_slot_purchase_stale_version_rejected(api):
    """PRD §2.6: "Purchasing an extra-member slot for an account requires
    `expected_account_version` in the request body, equal to the account's current
    `version`. If the account's version has advanced since the client last read
    it, the purchase is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_layers/occ_slot_purchase_stale_version_rejected
    """
    account, owner_h = create_account(email="corner-occ1@x.com", plan_tier="PREMIUM")
    observed_version = account["version"]

    slot1 = get_success_data(
        api.purchase_slot(
            account["id"],
            purchase_slot_payload(account["owner_member_id"], observed_version),
            owner_h,
        )
    )
    assert slot1["status"] == "OFFERED"

    stale = api.purchase_slot(
        account["id"],
        purchase_slot_payload(account["owner_member_id"], observed_version),
        owner_h,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_ACCOUNT_VERSION)

    after = get_account(account["id"])
    assert after["version"] == observed_version + 1, "only the first purchase bumped the version"
    assert after["extra_member_billed_cents"] == 599, "PREMIUM NA first slot on anchor day"


def test_occ_transfer_accept_stale_version_rejected(api):
    """PRD §2.6: "Accepting a profile transfer requires
    `expected_profile_transfer_version` in the request body, equal to the
    transfer's current `version`. A mismatch is rejected with
    `ERR_STALE_TRANSFER_VERSION` (HTTP 412)". PRD §3.8: "a stale version is
    rejected with `ERR_STALE_TRANSFER_VERSION` (HTTP 412) before any state check".

    Design: Corner/cross_cutting_layers/occ_transfer_accept_stale_version_rejected
    """
    account, slot, extra_id, owner_h = create_account_with_assigned_slot(
        email="corner-occ2@x.com", extra_email="extra-occ2@x.com"
    )
    transfer = get_success_data(
        api.initiate_transfer(account["id"], {"member_id": extra_id, "target_email": "newhome-occ2@x.com"}, owner_h)
    )
    observed_version = transfer["version"]

    accepted = get_success_data(
        api.accept_transfer(
            transfer["id"],
            {
                "new_account_email": "newhome-occ2@x.com",
                "new_account_region": "NA",
                "new_account_plan_tier": "BASIC",
                "expected_profile_transfer_version": observed_version,
            },
            admin_headers(),
        )
    )
    assert accepted["status"] == "COMPLETED"

    stale = api.accept_transfer(
        transfer["id"],
        {
            "new_account_email": "newhome-occ2b@x.com",
            "new_account_region": "NA",
            "new_account_plan_tier": "BASIC",
            "expected_profile_transfer_version": observed_version,
        },
        admin_headers(),
    )
    validate_error(stale, ApiErrorId.ERR_STALE_TRANSFER_VERSION)

    after = get_success_data(api.get_transfer(transfer["id"], admin_headers()))
    assert after["version"] == observed_version + 1
