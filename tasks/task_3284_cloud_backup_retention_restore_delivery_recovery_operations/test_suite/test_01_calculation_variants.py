"""Dual-variant and combinatorial calculation rules of the backup service."""
import pytest

from test_helpers import (
    api_client as api,
    get_success_data,
    validate_error,
    ApiErrorId,
    GB_10,
    GB_50,
    GB_100,
    GB_300,
    GB_400,
    GB_600,
    RETENTION,
    SYS,
    BACKUP,
    create_pod,
    fail_shards,
    open_and_close_period,
    open_billing_period,
    close_billing_period,
    record_version,
    setup_personal_scenario,
    setup_active_set,
)


def _floor(x):
    from decimal import Decimal, ROUND_FLOOR
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_FLOOR))


def _gross_storage_cents(period, rate):
    """PRD §3.6: gross storage = floor(weighted average volume * tier rate *
    period_days / 30), where the weighted average blends the period's
    usage_gb_avg over the non-active days with its peak over the active days."""
    from datetime import datetime
    start = datetime.fromisoformat(period["period_start_utc"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(period["period_end_utc"].replace("Z", "+00:00"))
    period_days = (end - start).days
    active = int(period["restore_active_days"])
    active = max(0, min(active, period_days))
    weighted = (period["usage_gb_avg"] * (period_days - active)
                + period["peak_usage_gb"] * active) / period_days
    return _floor(weighted * rate * period_days / 30)


def test_restore_egress_is_protected_when_the_restore_point_precedes_a_delete():
    """PRD §3.6: "the free allowance is the raw requested volume limited to 1.0
    gigabyte, the billable partial volume is the raw volume minus that
    allowance, and an oversize surcharge applies on top: the volume above the
    500-gigabyte oversize threshold, never below zero, is multiplied by the 0.25
    operator surcharge rate and added to the billable partial."
    PRD §3.6: "In the protected variant, which applies when
    `is_ransomware_recovery` is true, the free allowance and the oversize
    surcharge are both set aside and the billable volume is instead the raw
    volume minus the 100-gigabyte ransomware-protected allowance, never below
    zero."
    PRD §3.6: "The two variants can diverge sharply: a single 700-gigabyte
    restore bills 749.00 gigabytes under the metered variant but 600.00
    gigabytes under the protected variant."

    Design: Difficulty/dual_variant_calc/billable_egress_metered_vs_ransomware_protected
    """
    scenario = setup_personal_scenario(storage_tier="PRO")
    account_id = scenario["account"]["id"]
    set_id = scenario["set"]["id"]

    # archive.tar: 300 GB, then modified to 400 GB, then destroyed on 2026-09-25.
    record_version(set_id, "/home/u/archive.tar", 1, "CREATE", GB_300,
                   "sha256-arc-v1", "2026-09-10T00:00:00Z")
    record_version(set_id, "/home/u/archive.tar", 2, "MODIFY", GB_400,
                   "sha256-arc-v2", "2026-09-15T00:00:00Z")
    record_version(set_id, "/home/u/notes.txt", 1, "CREATE", GB_100,
                   "sha256-note-v1", "2026-09-12T00:00:00Z")
    record_version(set_id, "/home/u/archive.tar", 3, "DELETE", 0,
                   "sha256-arc-del", "2026-09-25T00:00:00Z")

    from test_helpers import complete_initial, create_restore, validate_restore, begin_restore
    complete_initial(set_id)

    # Before the destructive event: the protected variant applies.
    pre = create_restore(
        scenario, restore_point_in_utc="2026-09-20T00:00:00Z",
        requested_file_count=2, requested_size_gb=700.0,
        requester_mfa_ticket="mfa-ticket-001")
    pre = validate_restore(pre["id"], account_id, "mfa-ticket-001")
    assert pre["is_ransomware_recovery"] is True, (
        "the restore point 2026-09-20 precedes the DELETE at 2026-09-25")
    pre = begin_restore(pre["id"], account_id)
    assert pre["egress_gb"] == pytest.approx(600.0, abs=0.01)

    # After the destructive event: the ordinary metered variant applies.
    post = create_restore(
        scenario, restore_point_in_utc="2026-09-28T00:00:00Z",
        requested_file_count=2, requested_size_gb=700.0,
        requester_mfa_ticket="mfa-ticket-002")
    post = validate_restore(post["id"], account_id, "mfa-ticket-002")
    assert post["is_ransomware_recovery"] is False, (
        "the restore point 2026-09-28 follows the DELETE at 2026-09-25")
    post = begin_restore(post["id"], account_id)
    assert post["egress_gb"] == pytest.approx(749.0, abs=0.01)


def test_restore_egress_metered_and_protected_variants_differ_for_the_same_volume():
    """PRD §3.6: "The two variants can diverge sharply: a single 700-gigabyte
    restore bills 749.00 gigabytes under the metered variant but 600.00
    gigabytes under the protected variant."

    Design: Difficulty/dual_variant_calc/billable_egress_metered_vs_ransomware_protected
    """
    from test_helpers import complete_initial, create_restore, validate_restore, begin_restore

    scenario = setup_personal_scenario(storage_tier="PRO")
    account_id = scenario["account"]["id"]
    set_id = scenario["set"]["id"]

    record_version(set_id, "/home/u/archive.tar", 1, "CREATE", GB_300,
                   "sha256-arc-v1", "2026-09-10T00:00:00Z")
    record_version(set_id, "/home/u/archive.tar", 2, "MODIFY", GB_400,
                   "sha256-arc-v2", "2026-09-15T00:00:00Z")
    record_version(set_id, "/home/u/notes.txt", 1, "CREATE", GB_100,
                   "sha256-note-v1", "2026-09-12T00:00:00Z")
    record_version(set_id, "/home/u/archive.tar", 3, "DELETE", 0,
                   "sha256-arc-del", "2026-09-25T00:00:00Z")
    complete_initial(set_id)

    egress_values = []
    for restore_point, ticket in (("2026-09-20T00:00:00Z", "mfa-ticket-101"),
                                  ("2026-09-28T00:00:00Z", "mfa-ticket-102")):
        restore = create_restore(
            scenario, restore_point_in_utc=restore_point,
            requested_file_count=2, requested_size_gb=700.0,
            requester_mfa_ticket=ticket)
        restore = validate_restore(restore["id"], account_id, ticket)
        restore = begin_restore(restore["id"], account_id)
        egress_values.append(restore["egress_gb"])

    protected, metered = egress_values
    assert protected == pytest.approx(600.0, abs=0.01)
    assert metered == pytest.approx(749.0, abs=0.01)
    assert protected != metered


def test_group_retention_override_wins_over_the_tier_default():
    """PRD §3.4: "Seventh, the requested window is the group request if one
    exists, and the account window otherwise."
    PRD §3.4: "the account's `has_extended_history` boolean is true exactly
    when `retention_days` is strictly greater than the standard 30-day window."

    Design: Difficulty/dual_variant_calc/retention_window_provisional_vs_group_override
    """
    from test_helpers import create_account, create_group, create_policy

    personal = create_account(name="Northwind Personal")
    personal_group = create_group(personal["id"], retention_days_override=45)
    create_policy(personal_group["id"])

    enterprise = create_account(name="Northwind Enterprise", account_type="ENTERPRISE",
                                region="EU_CENTRAL", storage_tier="BASIC",
                                encryption_key_id="aes-256-key-ent")
    enterprise_group = create_group(enterprise["id"], name="Enterprise Fleets",
                                    retention_days_override=None)
    create_policy(enterprise_group["id"])

    personal_group = get_success_data(api.get_backup_group(personal_group["id"], RETENTION))
    personal_acct = get_success_data(api.get_account(personal["id"], SYS))
    enterprise_group = get_success_data(api.get_backup_group(enterprise_group["id"], RETENTION))
    enterprise_acct = get_success_data(api.get_account(enterprise["id"], SYS))

    assert personal_group["group_retention_days"] == 45
    assert personal_acct["retention_days"] == 45
    assert personal_acct["has_extended_history"] is True
    assert enterprise_group["group_retention_days"] == 365
    assert enterprise_acct["retention_days"] == 365
    assert enterprise_acct["has_extended_history"] is True
    assert personal_group["group_retention_days"] != enterprise_group["group_retention_days"]


def test_account_retention_rolls_up_the_tier_default_when_no_override_exists():
    """PRD §3.4: "First, the base window is the account's extended-history
    window of 365 days if the account already carries extended history, and the
    standard window of 30 days otherwise. Second, the account window is the
    account's own `retention_days` if it has one, and the base window
    otherwise."
    PRD §3.4: "A special case is worth naming: when an account's
    `retention_days` was never written by an explicit retention change, the
    first two steps return the tier default of 30 or 365 days, and the group's
    request alone decides the effective window."

    Design: Difficulty/dual_variant_calc/retention_window_provisional_vs_group_override
    """
    from test_helpers import create_account, create_group, create_policy

    personal = create_account(name="Northwind Personal")
    personal_group = create_group(personal["id"], retention_days_override=None)
    create_policy(personal_group["id"])

    enterprise = create_account(name="Northwind Enterprise", account_type="ENTERPRISE",
                                region="EU_CENTRAL", storage_tier="BASIC",
                                encryption_key_id="aes-256-key-ent2")
    enterprise_group = create_group(enterprise["id"], name="Enterprise Fleets",
                                    retention_days_override=None)
    create_policy(enterprise_group["id"])

    personal_group = get_success_data(api.get_backup_group(personal_group["id"], RETENTION))
    enterprise_group = get_success_data(api.get_backup_group(enterprise_group["id"], RETENTION))

    assert personal_group["group_retention_days"] == 30
    assert enterprise_group["group_retention_days"] == 365
    assert enterprise_group["group_retention_days"] != personal_group["group_retention_days"]


def test_pod_reliability_pct_is_derived_from_the_erasure_coding_geometry():
    """PRD §2.7: "The unrecoverable probability is the binomial coefficient
    choosing `parity_shards + 1` shards out of `total_shards`, multiplied by the
    annual shard failure rate raised to the power `parity_shards + 1`; the
    annual shard failure rate constant is 0.01."
    PRD §2.7: "The reported `reliability_pct` is one hundred times one minus
    that unrecoverable probability, rounded half up to six decimal places."

    Design: Difficulty/combinatorial_formula/pod_reliability_pct_from_erasure_coding_geometry
    """
    pod_a = create_pod(region="US_WEST", total_shards=16, data_shards=12, failed_shards=0)
    pod_b = create_pod(region="US_EAST", total_shards=16, data_shards=15, failed_shards=0)

    pod_b = fail_shards(pod_b["id"], 1)
    pod_a = get_success_data(api.get_storage_pod(pod_a["id"], SYS))

    assert pod_a["status"] == "HEALTHY"
    assert pod_a["is_reconstructable"] is True
    assert pod_a["reliability_pct"] == pytest.approx(99.999956, abs=1e-6)

    assert pod_b["status"] == "DEGRADED"
    assert pod_b["reliability_pct"] == pytest.approx(98.8, abs=1e-6)
    assert pod_b["is_reconstructable"] is True
    assert pod_b["failed_shards"] == 1


def test_pod_reliability_pct_changes_with_the_parity_geometry():
    """PRD §2.7: "Each pod declares `total_shards`, the number of shards written
    per object, and `data_shards`, the number required to reconstruct an object."
    PRD §2.7: "The durability percentage `reliability_pct` is derived from the
    same geometry."

    Design: Difficulty/combinatorial_formula/pod_reliability_pct_from_erasure_coding_geometry
    """
    pod_a = create_pod(region="US_WEST", total_shards=16, data_shards=12, failed_shards=0)
    pod_b = create_pod(region="US_EAST", total_shards=16, data_shards=15, failed_shards=0)
    healthy_a = get_success_data(api.get_storage_pod(pod_a["id"], SYS))
    healthy_b = get_success_data(api.get_storage_pod(pod_b["id"], SYS))
    assert healthy_a["parity_shards"] == 4
    assert healthy_b["parity_shards"] == 1
    # PRD 2.7: reliability_pct = 100 * (1 - C(total_shards, parity+1) *
    # 0.01**(parity+1)).  For 16/12 the parity is 4, giving 99.999956; for
    # 16/15 the parity is 1, giving 98.8.
    assert healthy_a["reliability_pct"] == pytest.approx(99.999956, abs=1e-6)
    assert healthy_b["reliability_pct"] == pytest.approx(98.8, abs=1e-6)
    assert healthy_a["reliability_pct"] != healthy_b["reliability_pct"]


def test_storage_charge_floors_each_term_and_consumes_the_credit_once():
    """PRD §3.6: "each per-term value is floored to whole integer cents before
    the terms are summed, and no final rounding pass is applied to the total."
    PRD §3.6: "The one-time initial-upload credit is then applied. The observed
    credit is the account's `initial_full_backup_gb` multiplied by the same tier
    rate and floored to whole cents, and the `initial_upload_credit_cents` is
    that observed credit limited to a cap of 20000 cents."
    PRD §3.6: "Because the credit is tied to the account's earliest closed
    period, it is consumed by the first period the account closes and is zero
    for every later period."

    Design: Difficulty/combinatorial_formula/storage_charge_pinned_rounding_order_and_credit
    """
    scenario = setup_personal_scenario(storage_tier="PRO",
                                       encryption_key_id="aes-256-key-personal")
    account_id = scenario["account"]["id"]
    set_id = scenario["set"]["id"]

    record_version(set_id, "/home/u/archive.tar", 1, "CREATE", GB_400,
                   "sha256-arc-v1", "2026-09-10T00:00:00Z")
    record_version(set_id, "/home/u/notes.txt", 1, "CREATE", GB_100,
                   "sha256-note-v1", "2026-09-12T00:00:00Z")
    from test_helpers import complete_initial
    complete_initial(set_id)
    record_version(set_id, "/home/u/archive2.tar", 1, "CREATE", GB_400,
                   "sha256-arc2-v1", "2026-09-15T00:00:00Z")

    account = get_success_data(api.get_account(account_id, SYS))
    assert account["initial_full_backup_gb"] == pytest.approx(500.0, abs=0.01)
    assert account["usage_gb"] == pytest.approx(900.0, abs=0.01)

    first = open_billing_period(account_id, "2026-09-01T00:00:00Z",
                                "2026-10-01T00:00:00Z", restore_active_days=3)
    first = close_billing_period(first["id"])

    # PRD 3.1 / 3.6: the observed credit is initial_full_backup_gb (500.0) times
    # the tier rate (PRO = 4), i.e. 2000 cents, capped at 20000.
    assert first["initial_upload_credit_cents"] == 2000
    assert first["storage_credit_applied_cents"] == 2000
    # PRD 3.6: net storage is the freshly floored gross charge minus the applied
    # credit, and the total sums the per-term values.
    gross_first = _gross_storage_cents(first, 4)
    assert first["storage_fee_cents"] == gross_first - 2000
    assert first["total_cents"] == first["storage_fee_cents"] + first["egress_fee_cents"] \
        + first["transaction_fee_cents"]

    second = open_billing_period(account_id, "2026-10-01T00:00:00Z",
                                 "2026-11-01T00:00:00Z", restore_active_days=3)
    second = close_billing_period(second["id"])

    # PRD 3.6: the credit is tied to the earliest closed period, so it is zero
    # for every later period, and that is exactly the first-versus-second
    # storage difference.
    assert second["initial_upload_credit_cents"] == 0
    assert second["storage_credit_applied_cents"] == 0
    assert second["storage_fee_cents"] == _gross_storage_cents(second, 4)
    # PRD 3.6: the credit is consumed by the first period the account closes, so
    # the full 2000 cents is applied there and nothing later.
    assert (first["storage_credit_applied_cents"]
            - second["storage_credit_applied_cents"]) == 2000


def test_the_upload_credit_is_consumed_only_by_the_accounts_first_closed_period():
    """PRD §3.2: "`first_closed_period_utc` holds the `period_end_utc` of the
    account's earliest closed `BillingPeriod`, so that the credit is consumed
    only while this field is still null."
    PRD §3.6: "Because the credit is tied to the account's earliest closed
    period, it is consumed by the first period the account closes and is zero
    for every later period."

    Design: Difficulty/combinatorial_formula/storage_charge_pinned_rounding_order_and_credit
    """
    scenario = setup_personal_scenario(storage_tier="PRO",
                                       encryption_key_id="aes-256-key-personal")
    account_id = scenario["account"]["id"]
    set_id = scenario["set"]["id"]

    record_version(set_id, "/home/u/archive.tar", 1, "CREATE", GB_400,
                   "sha256-arc-v1", "2026-09-10T00:00:00Z")
    record_version(set_id, "/home/u/notes.txt", 1, "CREATE", GB_100,
                   "sha256-note-v1", "2026-09-12T00:00:00Z")
    from test_helpers import complete_initial
    complete_initial(set_id)
    record_version(set_id, "/home/u/archive2.tar", 1, "CREATE", GB_400,
                   "sha256-arc2-v1", "2026-09-15T00:00:00Z")

    observed_before = get_success_data(api.get_account(account_id, SYS))
    assert observed_before["first_closed_period_utc"] is None

    first = close_billing_period(open_billing_period(
        account_id, "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z",
        restore_active_days=3)["id"])
    observed_mid = get_success_data(api.get_account(account_id, SYS))
    second = close_billing_period(open_billing_period(
        account_id, "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z",
        restore_active_days=3)["id"])

    assert observed_mid["first_closed_period_utc"] is not None
    # PRD 3.1 / 3.6: 500 GB * the PRO tier rate of 4 cents = 2000 cents.
    assert first["initial_upload_credit_cents"] == 2000
    assert second["initial_upload_credit_cents"] == 0
    assert second["storage_fee_cents"] - first["storage_fee_cents"] != 0