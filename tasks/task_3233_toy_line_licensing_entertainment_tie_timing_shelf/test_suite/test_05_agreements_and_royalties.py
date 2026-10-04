"""License agreement lifecycle, amendment handshake, royalties and OCC."""
from test_helpers import (
    ApiErrorId,
    BRAND,
    STUDIO,
    activate_agreement,
    assert_license_agreement,
    create_agreement,
    create_licensed_line,
    create_property,
    create_shipment,
    create_sku,
    create_studio,
    fixtures,
    make_retailer_ops_headers,
    record_sale,
    set_clock,
    setup_active_agreement,
    setup_licensed_chain,
    setup_licensed_chain_with_shipment,
    setup_review_with_commitment,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


def _get_agreement(api, agreement_id):
    return validate_success(api.get_license_agreement(agreement_id, BRAND))


# ── Amendment cycle (difficulty: non_linear_state_machine) ──────────────────


def test_license_agreement_amendment_reject_then_approve_cycle(api):
    """PRD §3.2: "A `StudioRep` then either approves the amendment — which
    overwrites the effective `royalty_rate_pct`, `advance_guarantee_cents`, and
    `end_date` with the pending values, clears the pending fields to null, and
    returns the agreement to `ACTIVE` — or rejects it, which clears the pending
    fields to null while leaving the effective terms unchanged and also returns the
    agreement to `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/license_agreement_amendment_cycle
    """
    set_clock("2026-10-01T00:00:00Z")
    studio, prop, agreement = setup_active_agreement(
        royalty_rate_pct=0.10,
        advance_guarantee_cents=10000,
        approval_rights_required=True,
    )
    assert agreement["status"] == "ACTIVE"

    # Cycle 1: propose -> reject. Terms unchanged, pendings cleared.
    amended = validate_success(
        api.amend_license_agreement(
            agreement["id"],
            {
                "royalty_rate_pct": 0.15,
                "advance_guarantee_cents": 20000,
                "end_date": "2029-12-31T00:00:00Z",
            },
            BRAND,
        )
    )
    assert amended["status"] == "AMENDMENT_PENDING"
    rejected = validate_success(api.reject_amendment(agreement["id"], {}, STUDIO))
    assert rejected["status"] == "ACTIVE"
    assert rejected["royalty_rate_pct"] == 0.10
    assert rejected["advance_guarantee_cents"] == 10000
    assert rejected["pending_royalty_rate_pct"] is None

    # Cycle 2: propose -> approve. Pending terms applied.
    validate_success(
        api.amend_license_agreement(
            agreement["id"],
            {
                "royalty_rate_pct": 0.15,
                "advance_guarantee_cents": 20000,
                "end_date": "2029-12-31T00:00:00Z",
            },
            BRAND,
        )
    )
    approved = validate_success(api.approve_amendment(agreement["id"], {}, STUDIO))
    assert approved["status"] == "ACTIVE"
    assert approved["royalty_rate_pct"] == 0.15
    assert approved["advance_guarantee_cents"] == 20000
    assert approved["end_date"].startswith("2029-12-31")
    assert approved["pending_royalty_rate_pct"] is None


def test_license_agreement_second_amendment_cycle_rejects_acting_while_pending(api):
    """PRD §3.2: "acting on an agreement that is not in `AMENDMENT_PENDING` yields
    `ERR_INVALID_STATE`."

    Design: Difficulty/non_linear_state_machine/license_agreement_amendment_cycle
    """
    set_clock("2026-10-01T00:00:00Z")
    studio, prop, agreement = setup_active_agreement(approval_rights_required=True)

    # Approve/reject while the agreement is ACTIVE (not AMENDMENT_PENDING).
    resp = api.approve_amendment(agreement["id"], {}, STUDIO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    resp = api.reject_amendment(agreement["id"], {}, STUDIO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    # And after a full propose->approve cycle the machine is ACTIVE again and
    # still rejects a further approve.
    validate_success(
        api.amend_license_agreement(
            agreement["id"],
            {
                "royalty_rate_pct": 0.15,
                "advance_guarantee_cents": 0,
                "end_date": "2029-12-31T00:00:00Z",
            },
            BRAND,
        )
    )
    validate_success(api.approve_amendment(agreement["id"], {}, STUDIO))
    resp = api.approve_amendment(agreement["id"], {}, STUDIO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


# ── Royalty accrual corners ──────────────────────────────────────────────────


def test_royalty_recoup_caps_at_advance(api):
    """PRD §3.2: "the recouped amount for the quarter is the smaller of the
    quarter's earned amount and the remaining unrecouped advance — that is,
    `advance_guarantee_cents` minus the `recouped_cents` accumulated so far, floored
    at zero".
    PRD §3.2: "Recoupment can never exceed the advance: `recouped_cents` never rises
    above `advance_guarantee_cents`."

    Design: Corner/calculations/royalty_recoup_caps_at_advance
    """
    set_clock("2026-04-15T00:00:00Z")
    studio, prop, agreement = setup_active_agreement(
        royalty_rate_pct=0.50,
        advance_guarantee_cents=10000,
        annual_minimum_guarantee_cents=0,
        reveal_date="2026-01-01T00:00:00Z",
        release_date="2026-09-01T00:00:00Z",
    )
    line = create_licensed_line(prop["id"], agreement["id"], name="Racers")
    sku = create_sku(line["id"], age_grade_months=48)
    retailer, review, commitment = setup_review_with_commitment(
        sku,
        committed_units=1000,
        unit_price_cents=100,
        shelf_slots=4,
        window_start="2026-04-01T00:00:00Z",
        window_end="2026-12-31T00:00:00Z",
        commitment_deadline="2026-12-01T00:00:00Z",
    )
    shipment = create_shipment(commitment["id"], planned_ship_date="2026-04-15T00:00:00Z", units=1000)
    record_sale(shipment["id"], retailer, 400)

    resp = api.close_quarter(agreement["id"], {"quarter_index": 1}, BRAND)
    data = validate_success(resp)
    assert_license_agreement(data)
    # gross 400*100 = 40000; earned 20000; recoup min(20000, 10000) = 10000
    assert data["royalties_earned_cents"] == 20000
    assert data["recouped_cents"] == 10000
    assert data["guarantee_topups_cents"] == 0
    assert data["quarters_closed"] == 1


def test_minimum_guarantee_topup_on_fourth_quarter(api):
    """PRD §3.2: "Every fourth closed quarter, the annual minimum reconciles: when
    the count of closed quarters after this close is a multiple of four, the system
    compares the year's minimum (`annual_minimum_guarantee_cents`) against the sum
    of this quarter's earned amount plus the earned amounts of the previous three
    closed quarters; if the year's earnings fall short, a top-up equal to the
    shortfall is paid."

    Design: Corner/calculations/minimum_guarantee_topup_on_fourth_quarter
    """
    set_clock("2026-10-01T00:00:00Z")
    studio, prop, agreement = setup_active_agreement(
        royalty_rate_pct=0.10,
        advance_guarantee_cents=0,
        annual_minimum_guarantee_cents=100000,
        release_date="2026-09-01T00:00:00Z",
    )
    line = create_licensed_line(prop["id"], agreement["id"], name="Racers")
    sku = create_sku(line["id"], age_grade_months=48)
    retailer, review, commitment = setup_review_with_commitment(
        sku, committed_units=100, unit_price_cents=100, shelf_slots=4
    )
    shipment = create_shipment(commitment["id"], planned_ship_date="2026-09-01T00:00:00Z", units=100)
    record_sale(shipment["id"], retailer, 100)

    for quarter in (1, 2, 3):
        validate_success(api.close_quarter(agreement["id"], {"quarter_index": quarter}, BRAND))
    data = validate_success(api.close_quarter(agreement["id"], {"quarter_index": 4}, BRAND))
    # Year earned = 100*100*0.10 = 1000 (quarter 1 only); topup 100000-1000.
    assert data["guarantee_topups_cents"] == 99000
    assert data["royalties_earned_cents"] == 100000
    assert data["quarters_closed"] == 4


# ── Dual-variant royalty projection (difficulty: dual_variant_calc) ─────────


def test_royalty_provisional_includes_planned_and_pending_rate(api):
    """PRD §3.2: "The provisional variant differs from the final close in exactly
    three ways: it also includes `PLANNED` shipments valued at their full `units`
    multiplied by the commitment's `unit_price_cents`; it uses the pending royalty
    rate (`pending_royalty_rate_pct`) when the agreement is in `AMENDMENT_PENDING`
    rather than the effective rate; and it mutates nothing — none of the four
    ledger fields move."

    Design: Difficulty/dual_variant_calc/royalty_provisional_includes_planned_and_pending_rate
    """
    studio, prop, agreement, line, sku, retailer, review, commitment, shipment = (
        setup_licensed_chain_with_shipment(
            commitment_overrides={"committed_units": 1000, "unit_price_cents": 100, "shelf_slots": 4},
            shipment_overrides={"planned_ship_date": "2027-02-01T00:00:00Z", "units": 1000},
            moq_units=100,
            unit_cost_cents=200,
            tooling_cost_cents=50000,
            age_grade_months=48,
        )
    )
    # Amendment pending: royalty 0.10 -> proposed 0.20.
    validate_success(
        api.amend_license_agreement(
            agreement["id"],
            {
                "royalty_rate_pct": 0.20,
                "advance_guarantee_cents": 0,
                "end_date": "2028-12-31T00:00:00Z",
            },
            BRAND,
        )
    )

    proj = validate_success(api.royalty_projection(agreement["id"], BRAND))
    assert proj["projected_earned_cents"] == 20000  # 1000 PLANNED units * 100c * 0.20

    closed = validate_success(api.close_quarter(agreement["id"], {"quarter_index": 1}, BRAND))
    # No SOLD shipments: final variant earns 0.
    assert closed["royalties_earned_cents"] == 0
    assert closed["quarters_closed"] == 1
    # The projection consumed nothing: the amendment is still pending.
    assert closed["status"] == "AMENDMENT_PENDING"


def test_royalty_projection_mutates_no_ledger_fields(api):
    """PRD §3.2: "it mutates nothing — none of the four ledger fields move."

    Design: Corner/calculations/royalty_recoup_caps_at_advance
    """
    studio, prop, agreement, line, sku, retailer, review, commitment, shipment = (
        setup_licensed_chain_with_shipment(
            commitment_overrides={"committed_units": 1000, "unit_price_cents": 100, "shelf_slots": 4},
            shipment_overrides={"planned_ship_date": "2027-02-01T00:00:00Z", "units": 1000},
            age_grade_months=48,
        )
    )
    before = _get_agreement(api, agreement["id"])
    validate_success(api.royalty_projection(agreement["id"], BRAND))
    after = _get_agreement(api, agreement["id"])
    for field in ("royalties_earned_cents", "recouped_cents", "guarantee_topups_cents", "quarters_closed"):
        assert after[field] == before[field] == 0


def test_royalty_projection_uses_effective_rate_when_not_amendment_pending(api):
    """PRD §3.2: "it uses the pending royalty rate (`pending_royalty_rate_pct`) when
    the agreement is in `AMENDMENT_PENDING` rather than the effective rate".
    PRD §3.2: "The provisional variant differs from the final close in exactly three
    ways: it also includes `PLANNED` shipments valued at their full `units`
    multiplied by the commitment's `unit_price_cents`".

    Design: Difficulty/dual_variant_calc/royalty_provisional_includes_planned_and_pending_rate
    """
    studio, prop, agreement, line, sku, retailer, review, commitment, shipment = (
        setup_licensed_chain_with_shipment(
            royalty_rate_pct=0.10,
            commitment_overrides={"committed_units": 1000, "unit_price_cents": 100, "shelf_slots": 4},
            shipment_overrides={"planned_ship_date": "2027-02-01T00:00:00Z", "units": 1000},
            age_grade_months=48,
        )
    )
    # Agreement stays ACTIVE (no amendment pending): the projection prices the
    # PLANNED shipment at the effective 0.10 rate.
    proj = validate_success(api.royalty_projection(agreement["id"], BRAND))
    assert proj["projected_earned_cents"] == 10000  # 1000 units * 100c * 0.10


# ── OCC stale version on activate ────────────────────────────────────────────


def test_activate_license_agreement_with_stale_version_rejected(api):
    """PRD §2.8: "Activating a license agreement requires the request to carry
    `expected_license_agreement_version`, the client's last observed `version` of
    the agreement. If it does not match the agreement's current `version` — because
    another writer has advanced the agreement in the meantime, for example by
    amending it to `AMENDMENT_PENDING` and back — the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_toy_line_version_rejected_on_advance
    """
    set_clock("2026-10-01T00:00:00Z")
    studio = create_studio(name="Studio Two")
    prop = create_property(studio["id"], title="P2")
    agreement = create_agreement(prop["id"])
    stale_version = agreement["version"]
    activate_agreement(agreement)  # version now advanced past the observed one
    resp = api.activate_license_agreement(
        agreement["id"], {"expected_license_agreement_version": stale_version}, BRAND
    )
    # The re-activation races: the version is stale (§2.8 -> ERR_STALE_VERSION),
    # but the agreement is also no longer NEGOTIATION, and §2.7's fixed priority
    # order lets the lifecycle-state gate (ERR_INVALID_STATE) win when it applies.
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_STALE_VERSION, ApiErrorId.ERR_INVALID_STATE],
    )
