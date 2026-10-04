"""Temporal gates and version guards: agreement effective_at half-open gate
and OCC on referral reassignment.
"""
import pytest

from test_helpers import (
    api_client, COORDINATOR,
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    set_clock, create_network, create_category, create_org,
    get_referral, create_consent, create_offering,
    create_and_approve_agreement,
    setup_two_receiver_scenario, route_referral, decline_referral,
    reassign_referral,
    make_case_worker_headers, make_org_admin_headers,
)
from test_helpers import factories


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / agreement_effective_at_half_open_temporal_gate
# ---------------------------------------------------------------------------

def test_agreement_effective_at_exactly_now_approves():
    """PRD §3.4: "An agreement starts `PENDING`; a coordinator approves it to
    `ACTIVE` only once `effective_at` is at or before the server clock
    (otherwise `ERR_AGREEMENT_NOT_YET_EFFECTIVE`) and only while both party
    organizations are `ACTIVE` (otherwise `ERR_ORG_NOT_ACTIVE`)."

    Design: Difficulty/resource_temporal_overlap/agreement_effective_at_half_open_temporal_gate
    """
    set_clock("2026-09-01T12:00:00Z")
    create_network()
    sender = create_org("Sender S", "CLINIC", "EIN-S")
    receiver = create_org("Receiver R", "CBO", "EIN-R")
    # effective_at == clock: the gate is inclusive.
    agreement = get_success_data(api_client.create_agreement(
        factories.create_agreement_payload(
            party_a_org_id=sender["id"], party_b_org_id=receiver["id"],
            effective_at="2026-09-01T12:00:00Z"),
        COORDINATOR))
    approved = validate_success(
        api_client.approve_agreement(agreement["id"], COORDINATOR))
    assert approved["status"] == "ACTIVE"


def test_agreement_effective_at_one_second_future_rejected():
    """PRD §3.4: "An agreement starts `PENDING`; a coordinator approves it to
    `ACTIVE` only once `effective_at` is at or before the server clock
    (otherwise `ERR_AGREEMENT_NOT_YET_EFFECTIVE`) and only while both party
    organizations are `ACTIVE` (otherwise `ERR_ORG_NOT_ACTIVE`)."

    Design: Difficulty/resource_temporal_overlap/agreement_effective_at_half_open_temporal_gate
    """
    set_clock("2026-09-01T12:00:00Z")
    create_network()
    sender = create_org("Sender S", "CLINIC", "EIN-S")
    receiver = create_org("Receiver R2", "CBO", "EIN-R2")
    # effective_at one second in the future: not yet effective.
    agreement = get_success_data(api_client.create_agreement(
        factories.create_agreement_payload(
            party_a_org_id=sender["id"], party_b_org_id=receiver["id"],
            effective_at="2026-09-01T12:00:01Z"),
        COORDINATOR))
    validate_error(api_client.approve_agreement(agreement["id"], COORDINATOR),
                   ApiErrorId.ERR_AGREEMENT_NOT_YET_EFFECTIVE, expected_status=409)
    agreements, _ = validate_paginated(api_client.list_agreements(
        COORDINATOR, params={"party_a_org_id": sender["id"]}))
    assert agreements[0]["status"] == "PENDING"


# ---------------------------------------------------------------------------
# Corner: errors / error_stale_version_on_reassign
# ---------------------------------------------------------------------------

def _setup_three_receiver_scenario():
    """Two-receiver scenario plus a third receiver R3 with its own offering,
    agreement, and consent from the shared client."""
    ctx = setup_two_receiver_scenario()
    r3 = create_org("Receiver R3", "CBO", factories._uniq("EIN-R3"))
    o3 = create_offering(r3["id"], description="Meals R3")
    create_and_approve_agreement(ctx["sender_id"], r3["id"])
    c3 = create_consent(ctx["client_id"], ctx["sender_id"], r3["id"])
    ctx.update({"r3": r3, "r3_id": r3["id"], "o3": o3, "o3_id": o3["id"],
                "c3": c3})
    return ctx


def test_error_stale_version_on_reassign():
    """PRD §2.8: "Reassigning a referral requires `expected_referral_version`
    matching the referral's current `version`. This captures the case where
    another writer has just re-routed the referral — which legitimately
    overwrites its `receiver_org_id` under the decline-reassign policy — so the
    current writer's view is stale."

    Design: Corner/errors/error_stale_version_on_reassign
    """
    ctx = _setup_three_receiver_scenario()
    route_referral(ctx, ctx["referral_id"])
    decline_referral(ctx, ctx["referral_id"], receiver_id=ctx["r1_id"], reason="no")

    # Sender reads version V (stale snapshot).
    stale_version = get_referral(ctx["referral_id"])["version"]

    # Coordinator reassigns to R2 first, bumping the version.
    current = get_referral(ctx["referral_id"])
    get_success_data(reassign_referral(COORDINATOR, ctx["referral_id"],
                                       ctx["r2_id"], ctx["o2_id"], current["version"]))
    # R2 declines, reopening the reassign path.
    decline_referral(ctx, ctx["referral_id"], receiver_id=ctx["r2_id"],
                     reason="decline again to reopen")

    # The sender's reassign carries the stale version and is rejected.
    validate_error(reassign_referral(ctx["case_worker"], ctx["referral_id"],
                                     ctx["r3_id"], ctx["o3_id"], stale_version),
                   ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    referral = get_referral(ctx["referral_id"])
    assert referral["receiver_org_id"] == ctx["r2_id"], \
        "the stale reassign did not apply"
    assert referral["status"] == "DECLINED"


def test_reassign_with_current_version_succeeds_after_stale_rejection():
    """PRD §2.8: "Reassigning a referral requires `expected_referral_version`
    matching the referral's current `version`."
    PRD §3.5: "A declined referral can be re-routed by a `CaseWorker` or
    `NetworkCoordinator` to a `new_receiver_org_id` and
    `new_service_offering_id`, which overwrites the referral's
    `receiver_org_id` and `service_offering_id` and reserves capacity on the
    new offering."

    Design: Corner/errors/error_stale_version_on_reassign
    """
    ctx = _setup_three_receiver_scenario()
    route_referral(ctx, ctx["referral_id"])
    decline_referral(ctx, ctx["referral_id"], receiver_id=ctx["r1_id"], reason="no")
    stale_version = get_referral(ctx["referral_id"])["version"]
    current = get_referral(ctx["referral_id"])
    get_success_data(reassign_referral(COORDINATOR, ctx["referral_id"],
                                       ctx["r2_id"], ctx["o2_id"], current["version"]))
    decline_referral(ctx, ctx["referral_id"], receiver_id=ctx["r2_id"],
                     reason="decline again to reopen")
    validate_error(reassign_referral(ctx["case_worker"], ctx["referral_id"],
                                     ctx["r3_id"], ctx["o3_id"], stale_version),
                   ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    # Reading the fresh version and retrying succeeds.
    fresh = get_referral(ctx["referral_id"])
    reassigned = validate_success(reassign_referral(
        ctx["case_worker"], ctx["referral_id"], ctx["r3_id"], ctx["o3_id"],
        fresh["version"]))
    assert reassigned["status"] == "ROUTED"
    assert reassigned["receiver_org_id"] == ctx["r3_id"]
