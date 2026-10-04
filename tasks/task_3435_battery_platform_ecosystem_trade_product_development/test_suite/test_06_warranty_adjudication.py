"""Warranty adjudication: parallel state dimensions, booking compensation,
and immediate visibility of computed fields."""
from test_helpers import (
    ApiErrorId,
    adjudicate_claim,
    complete_claim,
    create_account,
    create_battery_asset,
    create_center,
    create_certified_pack,
    create_claim,
    create_platform,
    get_claim,
    make_account_manager_headers,
    make_service_agent_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    warranty_claim_payload,
)


def _setup_two_claims():
    """Platform, CERTIFIED pack (price 20000, 720d/90d), center cap 10 with both
    capabilities, PROFESSIONAL account with one battery asset (manufactured
    2026-06-01), and two claims on it. Returns (pk, sc, ac, asset, ca, cb)."""
    set_clock()
    pf = create_platform(code="MX18")
    pk = create_certified_pack(pf["id"], sku="P-PD")
    sc = create_center(code="SC-1", capabilities=["TOOL_REPAIR", "BATTERY_SERVICE"],
                       daily_capacity=10)
    ac = create_account(org_name="Acme Mechanical", tier="PROFESSIONAL")
    asset = create_battery_asset(ac["id"], pk["id"], serial_number="SN-PD-1",
                                 manufactured_at="2026-06-01T00:00:00Z")
    ca = create_claim(asset["id"], ac["id"], "BATTERY_REPLACEMENT", "2026-09-02", "NO_CHARGE")
    cb = create_claim(asset["id"], ac["id"], "BATTERY_REPLACEMENT", "2026-09-03", "OVERHEAT")
    return pk, sc, ac, asset, ca, cb


def test_claim_dimensions_approve_then_complete_mints_replacement(api, account_manager_headers):
    """PRD §3.5: "Adjudication and fulfillment then evolve as two parallel
    dimensions; the only cross-dimension gate is that completion requires both
    `APPROVED` adjudication and `AWAITING_UNIT` fulfillment."
    PRD §3.5: "For a `BATTERY_REPLACEMENT` claim it additionally mints a
    replacement `TrackedAsset` on the same account: `subject_type` `BATTERY`,
    the same `battery_pack_id`, `is_replacement_unit` true (exempt from the
    account asset limit)"

    Design: Difficulty/non_linear_state_machine/claim_parallel_dimensions_independent_then_joined
    """
    pk, sc, ac, asset, ca, cb = _setup_two_claims()
    approved = adjudicate_claim(ca["id"], ca["service_center_id"], "APPROVED")
    assert approved["adjudication_status"] == "APPROVED"
    assert approved["fulfillment_status"] == "AWAITING_UNIT"
    completed = complete_claim(ca["id"], ca["service_center_id"])
    assert completed["fulfillment_status"] == "COMPLETED"
    assert completed["adjudication_status"] == "APPROVED"
    rows, meta = validate_paginated(api.list_tracked_assets(
        account_manager_headers, params={"account_id": ac["id"]}))
    assert meta["total_count"] == 2
    replacements = [r for r in rows if r["is_replacement_unit"]]
    assert len(replacements) == 1
    assert replacements[0]["subject_type"] == "BATTERY"
    assert replacements[0]["battery_pack_id"] == pk["id"]


def test_claim_dimensions_reject_cancels_and_complete_hits_join_gate(api):
    """PRD §3.5: "Rejection moves fulfillment `NONE` → `CANCELLED` and releases
    the daily booking"
    PRD §3.5: "Completion is the fulfillment edge `AWAITING_UNIT` → `COMPLETED`,
    performed by a `ServiceAgent` whose `X-User-ID` equals the claim's
    `service_center_id` (`ERR_FORBIDDEN`), and gated on the adjudication
    dimension reading `APPROVED` (`ERR_INVALID_STATE` otherwise)."

    Design: Difficulty/non_linear_state_machine/claim_parallel_dimensions_independent_then_joined
    """
    pk, sc, ac, asset, ca, cb = _setup_two_claims()
    rejected = adjudicate_claim(cb["id"], cb["service_center_id"], "REJECTED")
    assert rejected["adjudication_status"] == "REJECTED"
    assert rejected["fulfillment_status"] == "CANCELLED"
    resp = api.complete_warranty_claim(
        cb["id"], make_service_agent_headers(cb["service_center_id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def _setup_single_booked_slot():
    """Center capacity 1; claim A booked for 2026-09-10; asset a2 spare."""
    set_clock()
    pf = create_platform(code="MX18")
    pk = create_certified_pack(pf["id"], sku="P-INV1")
    sc = create_center(code="SC-INV", capabilities=["BATTERY_SERVICE"], daily_capacity=1)
    ac = create_account(org_name="Acme Mechanical", tier="PROFESSIONAL")
    a1 = create_battery_asset(ac["id"], pk["id"], serial_number="SN-INV-1",
                              manufactured_at="2026-06-01T00:00:00Z")
    a2 = create_battery_asset(ac["id"], pk["id"], serial_number="SN-INV-2",
                              manufactured_at="2026-06-01T00:00:00Z")
    ca = create_claim(a1["id"], ac["id"], "BATTERY_REPLACEMENT", "2026-09-10", "F1")
    return sc, ac, a2, ca


def test_claim_booking_blocks_second_claim_while_held(api):
    """PRD §3.5: "its creation books one unit of the selected center's capacity
    for that date."
    PRD §3.5: "an empty pool rejects the claim with `ERR_NO_SERVICE_CAPACITY`."

    Design: Difficulty/compensating_invariant/claim_booking_reject_restores_center_capacity
    """
    sc, ac, a2, ca = _setup_single_booked_slot()
    resp = api.create_warranty_claim(
        warranty_claim_payload(a2["id"], claim_type="BATTERY_REPLACEMENT",
                               fault_code="F2", service_date="2026-09-10"),
        make_account_manager_headers(ac["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NO_SERVICE_CAPACITY)


def test_claim_reject_releases_booking_and_frees_slot(api):
    """PRD §3.5: "Rejection moves fulfillment `NONE` → `CANCELLED` and releases
    the daily booking, decreasing the booked count for that center and date by
    1 as the compensating action of the creation-time booking."

    Design: Difficulty/compensating_invariant/claim_booking_reject_restores_center_capacity
    """
    sc, ac, a2, ca = _setup_single_booked_slot()
    rejected = adjudicate_claim(ca["id"], ca["service_center_id"], "REJECTED")
    assert rejected["fulfillment_status"] == "CANCELLED"
    cb = create_claim(a2["id"], ac["id"], "BATTERY_REPLACEMENT", "2026-09-10", "F2")
    assert cb["service_center_id"] == sc["id"], "the freed slot admits the retry"


def test_adjudicate_response_shows_computed_fields_immediately(api):
    """PRD §3.5: "On approval the computed `age_basis`, `age_days`, `coverage`,
    and `credit_cents` are persisted on the claim and fulfillment moves `NONE`
    → `AWAITING_UNIT`."
    PRD §2.4: "Consistency is immediate: every mutation, including all cascaded
    side effects of a single request, is visible in that request's response and
    in every subsequent read."

    Design: Corner/consistency_model/adjudicate_response_shows_computed_fields_immediately
    """
    set_clock()
    pf = create_platform(code="MX18")
    pk = create_certified_pack(pf["id"], sku="P-LST")
    sc = create_center(code="SC-A", capabilities=["BATTERY_SERVICE"], daily_capacity=5)
    ac = create_account(org_name="Paginators Inc")
    asset = create_battery_asset(ac["id"], pk["id"], serial_number="SN-IMM-1",
                                 manufactured_at="2026-06-01T00:00:00Z")
    claim = create_claim(asset["id"], ac["id"], "BATTERY_REPLACEMENT", "2026-09-10", "F1")
    resp = api.adjudicate_warranty_claim(
        claim["id"], {"decision": "APPROVED"},
        make_service_agent_headers(claim["service_center_id"]),
    )
    data = validate_success(resp, 200)
    assert data["adjudication_status"] == "APPROVED"
    assert data["age_basis"] == "MANUFACTURE"
    assert data["age_days"] == 92  # 2026-06-01 -> 2026-09-01
    assert data["coverage"] == "PRORATED"
    # rate = round_half_up(20000/24) = 833; remaining = floor(628/30) = 20
    assert data["credit_cents"] == 16660
    assert data["fulfillment_status"] == "AWAITING_UNIT"
