"""Supplier onboarding, qualification cycle, agreement lifecycle, and the
disqualification / expiry cascades (PRD sections 2.4, 3.1, 3.2)."""
import pytest

from test_helpers import (
    ApiErrorId, TEST_USERS,
    validate_error, validate_success,
    create_supplier_payload, supplier_transition_payload,
    qc_decision_payload,
    create_bare_supplier, create_qualified_supplier,
    create_qualified_active_supplier, qualify_supplier, suspend_supplier,
    disqualify_supplier, create_received_lot, set_clock,
    setup_expired_agreement_supplier,
    fetch_supplier, fetch_lot,
    assert_supplier,
)

_PM = TEST_USERS["procurement_manager_headers"]
_QM = TEST_USERS["quality_manager_headers"]


def test_supplier_create_starts_pending_audit_with_zeroed_counters(api):
    """PRD section 3.1: "The qualification dimension (`qualification_status`)
    opens at `PENDING_AUDIT`" and "The agreement dimension (`agreement_status`)
    opens at `DRAFT`", and "A freshly registered supplier starts with
    `delivered_volume_kg` and `open_lot_count` at zero and a null
    `audit_score`, which stays null until the first successful qualification
    records a score from 0 to 100." PRD section 4: "registering a supplier
    ... answer `201 Created`".

    Design: Corner/entities/cn_ent_supplier_create_defaults
    """
    resp = api.create_supplier(
        create_supplier_payload(supplier_code="SUP-K-1"), _PM)
    data = validate_success(resp, 201)
    assert_supplier(data)
    assert data["qualification_status"] == "PENDING_AUDIT"
    assert data["agreement_status"] == "DRAFT"
    assert data["delivered_volume_kg"] == 0
    assert data["open_lot_count"] == 0
    assert data["audit_score"] is None


def test_supplier_code_reused_is_unique_conflict(api):
    """PRD section 3.1: "a `supplier_code` that must be unique across all
    suppliers (duplicates are refused with `ERR_UNIQUE_CONSTRAINT`)".

    Design: Corner/entities/cn_ent_supplier_code_unique_conflict
    """
    create_bare_supplier(supplier_code="SUP-K-1")
    resp = api.create_supplier(
        create_supplier_payload(
            supplier_code="SUP-K-1", isolate_type="SOY",
            committed_volume_kg=100, base_price_per_kg_cents=300,
            price_floor_cents=250, price_cap_cents=380),
        _PM)
    validate_error(resp, ApiErrorId.ERR_UNIQUE_CONSTRAINT)


def test_first_qualification_score_65_rejected(api):
    """PRD section 3.1: "Qualifying a supplier out of `PENDING_AUDIT` requires
    an `audit_score` of at least 70; a weaker score is refused with
    `ERR_SUPPLIER_NOT_QUALIFIABLE`."

    Design: Corner/validations/cn_val_first_qualify_score_65_rejected
    """
    supplier = create_bare_supplier(supplier_code="SUP-K-39")
    resp = api.transition_supplier(
        supplier["id"],
        supplier_transition_payload("QUALIFICATION", "QUALIFIED",
                                    audit_score=65),
        _PM)
    validate_error(resp, ApiErrorId.ERR_SUPPLIER_NOT_QUALIFIABLE)
    after = fetch_supplier(supplier["id"])
    assert after["qualification_status"] == "PENDING_AUDIT"
    assert after["audit_score"] is None


def test_requalification_score_75_below_stricter_bar_rejected(api):
    """PRD section 3.1: "Re-qualification out of `SUSPENDED` is deliberately
    stricter than first qualification — the score must reach at least 80, and
    a weaker score again draws `ERR_SUPPLIER_NOT_QUALIFIABLE`." A score of 75
    clears the first-qualification bar of 70 but not the requalification bar.

    Design: Difficulty/non_linear_state_machine/nsm_supplier_requalification_cycle
    """
    supplier = create_qualified_supplier(
        supplier_code="SUP-CYC-1", isolate_type="SOY", committed_volume_kg=5000,
        base_price_per_kg_cents=300, price_floor_cents=250,
        price_cap_cents=380)
    suspend_supplier(supplier["id"])
    resp = api.transition_supplier(
        supplier["id"],
        supplier_transition_payload("QUALIFICATION", "QUALIFIED",
                                    audit_score=75),
        _PM)
    validate_error(resp, ApiErrorId.ERR_SUPPLIER_NOT_QUALIFIABLE)
    assert fetch_supplier(supplier["id"])["qualification_status"] == "SUSPENDED"


def test_requalification_score_85_completes_cycle(api):
    """PRD section 3.1: "Re-qualification out of `SUSPENDED` is deliberately
    stricter than first qualification — the score must reach at least 80, and
    a weaker score again draws `ERR_SUPPLIER_NOT_QUALIFIABLE`." A score of 85
    completes the QUALIFIED -> SUSPENDED -> QUALIFIED loop and is stored.

    Design: Difficulty/non_linear_state_machine/nsm_supplier_requalification_cycle
    """
    supplier = create_qualified_supplier(
        supplier_code="SUP-CYC-1", isolate_type="SOY", committed_volume_kg=5000,
        base_price_per_kg_cents=300, price_floor_cents=250,
        price_cap_cents=380)
    suspend_supplier(supplier["id"])
    resp = api.transition_supplier(
        supplier["id"],
        supplier_transition_payload("QUALIFICATION", "QUALIFIED",
                                    audit_score=85),
        _PM)
    data = validate_success(resp)
    assert data["qualification_status"] == "QUALIFIED"
    assert data["audit_score"] == 85


def test_pending_audit_to_suspended_is_not_an_edge(api):
    """PRD section 3.1: "Suspension (`QUALIFIED` → `SUSPENDED`) carries no
    score requirement." — the only suspension edge departs from QUALIFIED.
    PRD section 2.8: "The target resource must sit in a state from which the
    requested transition exists, and terminal states reject every further
    transition — `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/cn_sm_supplier_pending_to_suspended_returns_409
    """
    supplier = create_bare_supplier(supplier_code="SUP-K-3")
    resp = api.transition_supplier(
        supplier["id"],
        supplier_transition_payload("QUALIFICATION", "SUSPENDED"),
        _PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert fetch_supplier(supplier["id"])["qualification_status"] == (
        "PENDING_AUDIT")


def test_disqualified_supplier_locks_both_dimensions(api):
    """PRD section 3.1: "Once a supplier is `DISQUALIFIED` the lockdown is
    absolute — every further transition request against it, on either
    dimension, fails with `ERR_INVALID_STATE` before any other transition gate
    is evaluated."

    Design: Corner/state_machines/cn_sm_supplier_disqualified_terminal_lockdown
    """
    supplier = create_qualified_supplier(supplier_code="SUP-K-4")
    disqualify_supplier(supplier["id"])
    resp = api.transition_supplier(
        supplier["id"],
        supplier_transition_payload("AGREEMENT", "ACTIVE"),
        _PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_agreement_activation_requires_qualified_supplier(api):
    """PRD section 3.1: "Activating an agreement (`DRAFT` → `ACTIVE`) is
    cross-gated: the qualification dimension must already be `QUALIFIED`,
    otherwise `ERR_AGREEMENT_REQUIRES_QUALIFIED`".

    Design: Corner/state_machines/cn_sm_agreement_activate_requires_qualified
    """
    supplier = create_bare_supplier(supplier_code="SUP-K-8")
    resp = api.transition_supplier(
        supplier["id"],
        supplier_transition_payload("AGREEMENT", "ACTIVE"),
        _PM)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_REQUIRES_QUALIFIED)
    assert fetch_supplier(supplier["id"])["agreement_status"] == "DRAFT"


def test_disqualify_terminates_active_agreement(api):
    """PRD section 3.1: "disqualifying a supplier whose agreement is `ACTIVE`
    first terminates that agreement exactly as a manual termination would".

    Design: Difficulty/transitive_cascade/tc_supplier_disqualify_depth2
    """
    set_clock()
    supplier = create_qualified_active_supplier(
        supplier_code="SUP-TC-2", isolate_type="MUNG_BEAN",
        committed_volume_kg=1000, base_price_per_kg_cents=300,
        price_floor_cents=250, price_cap_cents=380)
    lot = create_received_lot(supplier["id"], lot_code="LOT-TC-2",
                              quantity_kg=100, protein_content_pct=80.0)
    assert lot["qc_status"] == "QUARANTINE"
    disqualify_supplier(supplier["id"])
    after = fetch_supplier(supplier["id"])
    assert after["qualification_status"] == "DISQUALIFIED"
    assert after["agreement_status"] == "TERMINATED"


def test_disqualify_cascade_rejects_quarantined_lots(api):
    """PRD section 3.1: "that termination in turn rejects every lot of the
    supplier still sitting in `QUARANTINE`." The lot mutation is caused by the
    agreement termination, not directly by the disqualify call; rejection
    never consumes quantity.

    Design: Difficulty/transitive_cascade/tc_supplier_disqualify_depth2
    """
    set_clock()
    supplier = create_qualified_active_supplier(
        supplier_code="SUP-TC-2", isolate_type="MUNG_BEAN",
        committed_volume_kg=1000, base_price_per_kg_cents=300,
        price_floor_cents=250, price_cap_cents=380)
    lot = create_received_lot(supplier["id"], lot_code="LOT-TC-2",
                              quantity_kg=100, protein_content_pct=80.0)
    disqualify_supplier(supplier["id"])
    lot_after = fetch_lot(lot["id"])
    assert lot_after["qc_status"] == "REJECTED"
    assert lot_after["remaining_kg"] == 100


def test_expired_agreement_leaves_lot_quarantined(api):
    """PRD section 2.4: "every supplier whose `agreement_status` is `ACTIVE`
    and whose `agreement_end_date` falls at or before the new clock value is
    moved to `EXPIRED`. The sweep is deliberately gentle toward inventory —
    quarantined lots of an expired supplier are not auto-rejected; they remain
    in `QUARANTINE` but become unreleasable".

    Design: Difficulty/cross_entity_state_dependency/cesd_lot_release_requires_agreement_active
    """
    ctx = setup_expired_agreement_supplier(
        supplier_code="SUP-CE-3", isolate_type="FABA_BEAN",
        committed_volume_kg=1000, base_price_per_kg_cents=300,
        price_floor_cents=250, price_cap_cents=380,
        lot_overrides={"lot_code": "LOT-CE-3", "quantity_kg": 100,
                       "received_at": "2026-09-05T00:00:00Z",
                       "protein_content_pct": 80.0})
    assert ctx["supplier"]["agreement_status"] == "EXPIRED"
    assert fetch_lot(ctx["lot"]["id"])["qc_status"] == "QUARANTINE"


def test_release_after_agreement_expiry_rejected(api):
    """PRD section 3.2: release "requires the supplier's agreement to still be
    `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`)". After the clock sweep expires the
    agreement, the still-quarantined lot cannot be released.

    Design: Difficulty/cross_entity_state_dependency/cesd_lot_release_requires_agreement_active
    """
    ctx = setup_expired_agreement_supplier(
        supplier_code="SUP-CE-3", isolate_type="FABA_BEAN",
        committed_volume_kg=1000, base_price_per_kg_cents=300,
        price_floor_cents=250, price_cap_cents=380,
        lot_overrides={"lot_code": "LOT-CE-3", "quantity_kg": 100,
                       "received_at": "2026-09-05T00:00:00Z",
                       "protein_content_pct": 80.0})
    resp = api.qc_decision(
        ctx["lot"]["id"],
        qc_decision_payload("RELEASED", invoiced_unit_cost_cents=300,
                            actual_freight_cents_per_kg=35),
        _QM)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)
    assert fetch_lot(ctx["lot"]["id"])["qc_status"] == "QUARANTINE"
