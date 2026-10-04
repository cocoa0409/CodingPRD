"""Launch commitments: window rule, fulfillment, suspension penalty cascade,
capacity conservation on create/cancel, OCC on the agreement, and the
frozen-posture priority over capacity (PRD §2.7–§2.10, §3.3, §3.6, §3.9).
"""
import pytest

from test_helpers import (
    SOURCING,
    ApiErrorId,
    api_client,
    assert_capacity_conservation,
    cancel_commitment,
    create_commitment,
    create_launch_commitment_payload,
    freeze_season,
    get_commitment,
    get_partner,
    get_retail_agreement,
    get_season,
    setup_launch_ready,
    setup_retail_live_fulfilled,
    setup_retail_live_open_commitment,
    setup_season_with_category,
    setup_signed_agreement,
    validate_created,
    validate_error,
    validate_ok,
)


def test_commitment_need_by_outside_agreement_window_rejected(api):
    """PRD §3.6: "The `need_by_date` must lie inside the agreement's half-open
    window — on or after `window_start` and strictly before `window_end` —
    else `ERR_COMMITMENT_OUTSIDE_WINDOW`."

    Design: Corner/validations/commitment_need_by_outside_agreement_window_rejected
    """
    base = setup_season_with_category()
    bundle = setup_launch_ready(base["category"]["id"])
    agreement = setup_signed_agreement(base["category"]["id"])
    payload = create_launch_commitment_payload(
        agreement["id"],
        bundle["variant"]["id"],
        agreement["version"],
        committed_units=100,
        need_by_date="2027-02-01T00:00:00Z",
    )
    resp = api_client.create_launch_commitment(payload, SOURCING)
    validate_error(resp, ApiErrorId.ERR_COMMITMENT_OUTSIDE_WINDOW)


def test_commitment_fulfilled_after_need_by_passes(api):
    """PRD §3.6: "At the run-review, every `OPEN` commitment whose
    `need_by_date` is before the current clock is marked `FULFILLED`, likewise
    releasing its units."

    Design: Corner/state_machines/commitment_fulfilled_after_need_by_passes
    """
    bundle = setup_retail_live_fulfilled()
    assert bundle["commitment"]["status"] == "FULFILLED"
    assert bundle["partner"]["allocated_units"] == 0
    assert bundle["variant"]["lifecycle"] == "RETAIL_LIVE"


def test_partner_suspend_penalizes_open_commitments_and_releases_capacity(api):
    """PRD §3.3: "When a `SourcingManager` suspends a partner, every
    LaunchCommitment still `OPEN` on a variant tooled at that partner becomes
    `SHORTFALL_PENALIZED`: each penalized commitment records `penalty_cents`
    equal to its `committed_units` multiplied by 150 cents per unit, and the
    owning season's `penalty_accrual_cents` increases by each such penalty —
    a running accrual applied at cascade time and never recomputed backward."

    Design: Corner/state_machines/partner_suspend_penalizes_open_commitments_and_releases_capacity
    """
    bundle = setup_retail_live_open_commitment(committed_units=40)
    data = validate_ok(api_client.suspend_partner(bundle["partner"]["id"], SOURCING))
    assert data["status"] == "SUSPENDED"
    assert data["allocated_units"] == 0
    commitment = get_commitment(bundle["commitment"]["id"])
    assert commitment["status"] == "SHORTFALL_PENALIZED"
    assert commitment["penalty_cents"] == 6000  # 40 units x 150 cents
    season = get_season(bundle["season"]["id"])
    assert season["penalty_accrual_cents"] == 6000


def test_occ_stale_agreement_version_rejected_on_commitment(api):
    """PRD §2.8: "Creating a launch commitment requires the request to carry
    `expected_agreement_version`, holding the `version` of the target
    RetailAgreement as the client last observed it; a mismatch with the
    agreement's current `version` is rejected with
    `ERR_STALE_AGREEMENT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_agreement_version_rejected_on_commitment
    """
    base = setup_season_with_category()
    bundle = setup_launch_ready(base["category"]["id"])
    agreement = setup_signed_agreement(base["category"]["id"])
    first = create_commitment(
        agreement["id"], agreement["version"], bundle["variant"]["id"],
        committed_units=100, need_by_date="2026-10-15T00:00:00Z",
    )
    assert first["status"] == "OPEN"
    payload = create_launch_commitment_payload(
        agreement["id"],
        bundle["variant"]["id"],
        agreement["version"],  # stale: the first create advanced it
        committed_units=50,
        need_by_date="2026-10-20T00:00:00Z",
    )
    resp = api_client.create_launch_commitment(payload, SOURCING)
    validate_error(resp, ApiErrorId.ERR_STALE_AGREEMENT_VERSION)


def test_commitment_create_then_cancel_conserves_partner_capacity(api):
    """PRD §2.9: "At all times, for every FactoryPartner, the partner's
    `allocated_units` equals the sum of `committed_units` over all
    LaunchCommitments in `OPEN` status on variants tooled at that partner,
    plus the sum of `quantity_units` over all ReplenishmentOrders in `OPEN`
    status on variants tooled at that partner."

    Design: Difficulty/compensating_invariant/commitment_create_then_cancel_conserves_partner_capacity
    """
    base = setup_season_with_category()
    bundle = setup_launch_ready(base["category"]["id"])
    agreement = setup_signed_agreement(base["category"]["id"])
    assert get_partner(bundle["partner"]["id"])["allocated_units"] == 0
    commitment = create_commitment(
        agreement["id"], agreement["version"], bundle["variant"]["id"],
        committed_units=300, need_by_date="2026-10-15T00:00:00Z",
    )
    assert get_partner(bundle["partner"]["id"])["allocated_units"] == 300
    cancelled = cancel_commitment(commitment["id"])
    assert cancelled["status"] == "CANCELLED"
    partner = get_partner(bundle["partner"]["id"])
    assert partner["allocated_units"] == 0
    assert_capacity_conservation(partner, [], [])


def test_commitment_create_advances_agreement_version_and_midstate_holds(api):
    """PRD §2.5: "Two creations additionally mutate a parent: posting a launch
    commitment advances the parent RetailAgreement's `version` by one" and PRD
    §3.6: "A successful commitment starts `OPEN` with `penalty_cents` 0, adds
    its `committed_units` to the partner's `allocated_units`".

    Design: Difficulty/compensating_invariant/commitment_create_then_cancel_conserves_partner_capacity
    """
    base = setup_season_with_category()
    bundle = setup_launch_ready(base["category"]["id"])
    agreement = setup_signed_agreement(base["category"]["id"])
    commitment = create_commitment(
        agreement["id"], agreement["version"], bundle["variant"]["id"],
        committed_units=300, need_by_date="2026-10-15T00:00:00Z",
    )
    assert commitment["status"] == "OPEN"
    assert commitment["penalty_cents"] == 0
    partner_mid = get_partner(bundle["partner"]["id"])
    assert_capacity_conservation(partner_mid, [commitment], [])
    assert get_retail_agreement(agreement["id"])["version"] == agreement["version"] + 1
    cancel_commitment(commitment["id"])
    assert_capacity_conservation(get_partner(bundle["partner"]["id"]), [], [])


def test_frozen_season_beats_capacity_on_commitment_create(api):
    """PRD §2.10: "The practical consequence: a posture rejection masks every
    business rule beneath it, and a stale-version rejection surfaces before
    any compliance or temporal failure on the same request." PRD §2.7: "While
    a season is `SEASON_FROZEN`, every season-scoped mutation is rejected with
    `ERR_SEASON_FROZEN` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/frozen_season_beats_capacity_on_commitment_create
    """
    base = setup_season_with_category()
    bundle = setup_launch_ready(base["category"]["id"])
    agreement = setup_signed_agreement(base["category"]["id"])
    freeze_season(base["season"]["id"])
    payload = create_launch_commitment_payload(
        agreement["id"],
        bundle["variant"]["id"],
        agreement["version"],
        committed_units=600,  # also exceeds the partner's 500 free units
        need_by_date="2026-10-15T00:00:00Z",
    )
    resp = api_client.create_launch_commitment(payload, SOURCING)
    validate_error(resp, ApiErrorId.ERR_SEASON_FROZEN)


def test_capacity_failure_surfaces_when_season_not_frozen(api):
    """PRD §3.6: "The tooling partner's free capacity must cover the full
    commitment: if `committed_units` exceeds the partner's
    `capacity_units_total` minus its `allocated_units`, the create is rejected
    with `ERR_CAPACITY_EXCEEDED` and no partial fill is booked."

    Design: Difficulty/priority_pair_validation_conflict/frozen_season_beats_capacity_on_commitment_create
    """
    base = setup_season_with_category()
    bundle = setup_launch_ready(base["category"]["id"], partner_capacity=500)
    agreement = setup_signed_agreement(base["category"]["id"])
    payload = create_launch_commitment_payload(
        agreement["id"],
        bundle["variant"]["id"],
        agreement["version"],
        committed_units=600,
        need_by_date="2026-10-15T00:00:00Z",
    )
    resp = api_client.create_launch_commitment(payload, SOURCING)
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)
    assert get_partner(bundle["partner"]["id"])["allocated_units"] == 0
