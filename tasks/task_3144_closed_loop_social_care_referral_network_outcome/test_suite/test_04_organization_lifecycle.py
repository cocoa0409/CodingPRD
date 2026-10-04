"""Organization lifecycle: suspension asymmetry, suspension cascades,
offering/org cross-state dependency, suspension gating, and category terminal
lockdown.
"""
import pytest

from test_helpers import (
    api_client, COORDINATOR,
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    set_clock, create_network, create_category, create_org, create_offering,
    create_client, create_consent, create_and_approve_agreement, create_referral,
    get_referral, get_offering, get_client, get_org,
    setup_routed_referral, setup_submitted_claim,
    route_referral, suspend_org,
    make_case_worker_headers, make_org_admin_headers,
    review_claim,
)


def test_org_suspension_reactivation_cycle_with_cascade_statuses():
    """PRD §3.2: "On suspension, the reason is captured, every one of the
    organization's service offerings is forced to `PAUSED`".
    PRD §3.2: "Reactivating a suspended organization moves it `SUSPENDED` →
    `ACTIVE`, clears the `suspension_reason`, and deliberately leaves its
    offerings `PAUSED` — resuming them is a separate manual act."

    Design: Difficulty/non_linear_state_machine/org_suspension_reactivation_cycle_with_cascade
    """
    set_clock()
    create_network()
    create_category("FOOD")
    receiver = create_org("Receiver R", "CBO", "EIN-R")
    offering = create_offering(receiver["id"], description="Meals")

    suspended = validate_success(suspend_org(receiver["id"]))
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "audit"

    reactivated = validate_success(
        api_client.activate_organization(receiver["id"], COORDINATOR))
    assert reactivated["status"] == "ACTIVE"
    assert reactivated["suspension_reason"] is None


def test_org_suspension_reactivation_leaves_offerings_paused():
    """PRD §3.2: "Reactivating a suspended organization moves it `SUSPENDED` →
    `ACTIVE`, clears the `suspension_reason`, and deliberately leaves its
    offerings `PAUSED` — resuming them is a separate manual act."
    PRD §3.3: "Resuming returns it to `ACTIVE` and requires the owning
    organization to be `ACTIVE`, failing with `ERR_ORG_NOT_ACTIVE` otherwise."

    Design: Difficulty/non_linear_state_machine/org_suspension_reactivation_cycle_with_cascade
    """
    set_clock()
    create_network()
    create_category("FOOD")
    receiver = create_org("Receiver R", "CBO", "EIN-R")
    offering = create_offering(receiver["id"], description="Meals")

    get_success_data(suspend_org(receiver["id"]))
    assert get_offering(offering["id"])["status"] == "PAUSED"

    get_success_data(api_client.activate_organization(receiver["id"], COORDINATOR))
    # The cycle is asymmetric: reactivation does NOT auto-resume offerings.
    assert get_offering(offering["id"])["status"] == "PAUSED"

    resumed = validate_success(api_client.resume_offering(
        offering["id"], make_org_admin_headers(receiver["id"])))
    assert resumed["status"] == "ACTIVE"


def test_org_suspension_depth3_referral_force_decline_overflow_cancel():
    """PRD §3.2: "first, every `ROUTED` referral currently aimed at this
    organization as receiver is force-declined by the system with the reason
    `ORG_SUSPENDED` — the referral moves `ROUTED` → `DECLINED` and its consent
    is left untouched; second, each affected referral's case reservation is
    released, decrementing the routed offering's `capacity_consumed` by 1, and
    the system re-route attempt increments each referral's
    `reassignment_count` by 1; third, if any affected referral's
    `reassignment_count` would now exceed the network's
    `max_reassignment_count`, that referral auto-cancels (`DECLINED` →
    `CANCELLED`) and its client's `open_referral_count` is decremented."

    Design: Difficulty/transitive_cascade/org_suspension_depth3_referral_decline_reassignment_overflow_cancel
    """
    ctx, referral = setup_routed_referral(
        network_overrides={"max_reassignment_count": 0})

    suspended = validate_success(suspend_org(ctx["receiver_id"]))
    assert suspended["status"] == "SUSPENDED"

    referral = get_referral(referral["id"])
    # max_reassignment_count 0: the very first forced decline overflows.
    assert referral["status"] == "CANCELLED"
    assert referral["reassignment_count"] == 1

    offering = get_offering(ctx["offering_id"])
    assert offering["capacity_consumed"] == 0
    assert offering["status"] == "PAUSED"
    assert get_client(ctx["client_id"])["open_referral_count"] == 0


def test_org_suspension_depth3_consent_untouched_by_cascade():
    """PRD §3.2: "every `ROUTED` referral currently aimed at this organization
    as receiver is force-declined by the system with the reason `ORG_SUSPENDED`
    — the referral moves `ROUTED` → `DECLINED` and its consent is left
    untouched".

    Design: Difficulty/transitive_cascade/org_suspension_depth3_referral_decline_reassignment_overflow_cancel
    """
    # With the default max_reassignment_count of 3, one forced decline leaves
    # the referral DECLINED (not cancelled) and the consent ACTIVE.
    ctx, referral = setup_routed_referral()
    get_success_data(suspend_org(ctx["receiver_id"]))

    referral = get_referral(referral["id"])
    assert referral["status"] == "DECLINED"
    assert referral["reassignment_count"] == 1
    consent = get_success_data(api_client.get_consent(ctx["consent_id"], COORDINATOR))
    assert consent["status"] == "ACTIVE"
    assert get_offering(ctx["offering_id"])["capacity_consumed"] == 0


def test_offering_resume_requires_org_active():
    """PRD §3.3: "Resuming returns it to `ACTIVE` and requires the owning
    organization to be `ACTIVE`, failing with `ERR_ORG_NOT_ACTIVE` otherwise."
    PRD §3.2: "Reactivating a suspended organization moves it `SUSPENDED` →
    `ACTIVE`, clears the `suspension_reason`, and deliberately leaves its
    offerings `PAUSED` — resuming them is a separate manual act."

    Design: Difficulty/cross_entity_state_dependency/offering_resume_requires_org_active
    """
    set_clock()
    create_network()
    create_category("FOOD")
    receiver = create_org("Receiver R", "CBO", "EIN-R")
    offering = create_offering(receiver["id"], description="Meals")
    get_success_data(suspend_org(receiver["id"]))

    # The owning org is SUSPENDED, so resume is rejected.
    validate_error(api_client.resume_offering(
        offering["id"], make_org_admin_headers(receiver["id"])),
        ApiErrorId.ERR_ORG_NOT_ACTIVE, expected_status=409)

    # After org reactivation the same resume succeeds.
    get_success_data(api_client.activate_organization(receiver["id"], COORDINATOR))
    resumed = validate_success(api_client.resume_offering(
        offering["id"], make_org_admin_headers(receiver["id"])))
    assert resumed["status"] == "ACTIVE"


def test_offering_resume_rejected_only_while_org_suspended():
    """PRD §3.3: "Resuming returns it to `ACTIVE` and requires the owning
    organization to be `ACTIVE`, failing with `ERR_ORG_NOT_ACTIVE` otherwise."

    Design: Difficulty/cross_entity_state_dependency/offering_resume_requires_org_active
    """
    set_clock()
    create_network()
    create_category("FOOD")
    receiver = create_org("Receiver R", "CBO", "EIN-R")
    offering = create_offering(receiver["id"], description="Meals")
    # An org that has never been suspended can pause and resume freely.
    get_success_data(api_client.pause_offering(
        offering["id"], make_org_admin_headers(receiver["id"])))
    resumed = validate_success(api_client.resume_offering(
        offering["id"], make_org_admin_headers(receiver["id"])))
    assert resumed["status"] == "ACTIVE"


def test_suspend_with_open_claim_blocked_then_succeeds():
    """PRD §3.2: "Suspending an organization — which requires the OCC field
    described in §2.8 and a `suspension_reason` — is allowed only from
    `ACTIVE`, and only while the organization has no claim in `SUBMITTED` or
    `UNDER_REVIEW`; otherwise the request is rejected with
    `ERR_OPEN_CLAIMS_BLOCK_TRANSITION`."
    PRD §3.2: "On suspension, the reason is captured, every one of the
    organization's service offerings is forced to `PAUSED`".

    Design: Corner/endpoints/suspend_with_open_claim_blocked_then_succeeds
    """
    ctx, referral, claim = setup_submitted_claim(delivered_units=5)

    validate_error(suspend_org(ctx["receiver_id"]),
                   ApiErrorId.ERR_OPEN_CLAIMS_BLOCK_TRANSITION, expected_status=409)
    assert get_org(ctx["receiver_id"])["status"] == "ACTIVE"

    # Deny the claim (reviewer rev1, denier rev2 — distinct staff), then the
    # same suspend succeeds.
    review_claim(ctx, claim["id"], "rev1")
    get_success_data(api_client.deny_claim(
        claim["id"], {"reason": "denied"}, ctx["funder_admin_rev2"]))

    suspended = validate_success(suspend_org(ctx["receiver_id"]))
    assert suspended["status"] == "SUSPENDED"
    assert get_offering(ctx["offering_id"])["status"] == "PAUSED"


def test_retire_retired_category_returns_invalid_state():
    """PRD §3.1: "When a category is retired by a coordinator it moves from
    `ACTIVE` to `RETIRED`, a terminal state".
    PRD §2.6: "then state validity, where a resource not in a valid from-state
    for the requested transition is rejected with `ERR_INVALID_STATE` (HTTP
    409)".

    Design: Corner/state_machines/retire_retired_category_returns_invalid_state
    """
    set_clock()
    create_network()
    category = create_category("FOOD")
    retired = validate_success(
        api_client.retire_taxonomy_category(category["id"], COORDINATOR))
    assert retired["status"] == "RETIRED"

    validate_error(api_client.retire_taxonomy_category(category["id"], COORDINATOR),
                   ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    category = get_success_data(
        api_client.get_taxonomy_category(category["id"], COORDINATOR))
    assert category["status"] == "RETIRED"
