"""Feedstock lots and batch composition (PRD §3.2): allocation guards,
the allocate/deallocate mass invariant with the DEPLETED round-trip,
supplier reliability, the release mass-balance gate and the embodied-carbon
formula, and immediate read-after-write consistency (PRD §1).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    allocate_to_batch,
    api_client,
    assert_feedstock_lot,
    assert_lot_mass_conserved,
    create_allocate_payload,
    create_batch,
    create_collection,
    create_feedstock_lot_payload,
    create_lot,
    create_qc_passed_lot,
    deallocate_from_batch,
    make_manager_headers,
    qc_lot,
    release_batch,
    set_clock,
    validate_created,
    validate_error,
    validate_success,
    DEFAULT_MANAGER_ID,
)


def test_allocate_deallocate_mass_conserved_to_depletion(api, admin_headers):
    """PRD §3.2: "A successful allocation decreases the lot's `available_kg` by
    the allocated quantity, increases its `allocated_kg` by the same amount,
    and adds or merges the corresponding `feedstock_mix` entry on the batch;
    when the allocation consumes the lot's last available kilogram the lot
    moves automatically from `QC_PASSED` to `DEPLETED`."

    Design: Difficulty/compensating_invariant/feedstock_allocate_deallocate_mass_conserved
    """
    set_clock()
    col = create_collection()
    lot = create_qc_passed_lot(quantity_kg=500, carbon_factor_kgco2e_per_kg=0.50)
    batch = create_batch(col["id"], produced_m2=200, mfg_intensity_kgco2e_per_m2=1.2)

    lot = allocate_to_batch(lot["id"], batch["id"], 300)
    assert lot["available_kg"] == 200 and lot["allocated_kg"] == 300
    assert_lot_mass_conserved(lot)
    assert lot["status"] == "QC_PASSED"

    lot = allocate_to_batch(lot["id"], batch["id"], 200)
    assert lot["available_kg"] == 0 and lot["allocated_kg"] == 500
    assert lot["status"] == "DEPLETED", "last available kilogram triggers DEPLETED"
    assert_lot_mass_conserved(lot)


def test_allocate_deallocate_mass_conserved_through_compensation(api, admin_headers):
    """PRD §3.2: "Deallocation is the exact mirror and the compensating action
    of allocation: kilograms return to the lot's `available_kg`, leave its
    `allocated_kg`, the batch's mix entry is reduced or removed, and a lot
    sitting at `DEPLETED` reverts to `QC_PASSED` as soon as availability
    returns."
    PRD §3.2: "Both operations immediately recompute the batch's two computed
    carbon fields."

    Design: Difficulty/compensating_invariant/feedstock_allocate_deallocate_mass_conserved
    """
    set_clock()
    col = create_collection()
    lot = create_qc_passed_lot(quantity_kg=500, carbon_factor_kgco2e_per_kg=0.50)
    batch = create_batch(col["id"], produced_m2=200, mfg_intensity_kgco2e_per_m2=1.2)

    lot = allocate_to_batch(lot["id"], batch["id"], 300)
    lot = allocate_to_batch(lot["id"], batch["id"], 200)
    assert lot["status"] == "DEPLETED"

    lot = deallocate_from_batch(lot["id"], batch["id"], 120)
    assert lot["available_kg"] == 120 and lot["allocated_kg"] == 380
    assert lot["status"] == "QC_PASSED", "DEPLETED reverts once availability returns"
    assert_lot_mass_conserved(lot)

    data = validate_success(api.get_batch(batch["id"], admin_headers))
    assert data["allocated_mass_kg"] == 380
    # Single all-recycled mix: 100 * 380 / 380 = 100.00 (PRD §3.2).
    assert data["recycled_content_pct"] == pytest.approx(100.00, abs=1e-9)


def test_release_mass_constant_and_embodied_formula(api, admin_headers):
    """PRD §3.2: "the batch's `allocated_mass_kg` must equal its `produced_m2`
    multiplied by the canonical 4.0 kilograms per square meter, with both sides
    compared at 2 decimal places; a mismatch is rejected with
    `ERR_MIX_MASS_MISMATCH` (HTTP 422)."
    PRD §3.2: "first the feedstock component — each mix entry's `quantity_kg`
    multiplied by its lot's `carbon_factor_kgco2e_per_kg`, all summed, divided
    by the batch's `produced_m2`, and rounded half up to 4 decimal places; then
    that rounded component is added to the batch's
    `mfg_intensity_kgco2e_per_m2` and the sum is rounded half up to 3 decimal
    places for storage."

    Design: Corner/calculations/release_mass_constant_and_embodied_formula
    """
    set_clock()
    col = create_collection()
    batch = create_batch(
        col["id"],
        dye_lot_code="DL-25",
        produced_m2=25,
        mfg_intensity_kgco2e_per_m2=0.9,
        delta_e=0.2,
    )
    lot_p = create_qc_passed_lot(
        supplier_name="NETCO", source_type="POST_CONSUMER_TILE",
        quantity_kg=50, carbon_factor_kgco2e_per_kg=0.40,
    )
    lot_v = create_qc_passed_lot(
        supplier_name="POLYCO", source_type="VIRGIN",
        quantity_kg=50, carbon_factor_kgco2e_per_kg=2.10,
    )
    allocate_to_batch(lot_p["id"], batch["id"], 50)
    allocate_to_batch(lot_v["id"], batch["id"], 50)
    # 100 kg == 25 m2 x 4.0 kg/m2 exactly: the release gate passes.
    released = release_batch(batch["id"])
    assert released["status"] == "RELEASED"
    assert released["allocated_mass_kg"] == 100
    assert released["recycled_content_pct"] == pytest.approx(50.00, abs=1e-9)
    # (50*0.40 + 50*2.10)/25 = 5.0000 at 4dp; 5.0000 + 0.9 -> 5.900 at 3dp.
    assert released["embodied_carbon_kg_per_m2"] == pytest.approx(5.900, abs=1e-9)


def test_allocate_requires_qc_passed_lot(api, manager_headers):
    """PRD §3.2: "Allocating kilograms from a lot into a batch's mix requires
    the lot to be in `QC_PASSED` — otherwise `ERR_LOT_NOT_QC_PASSED`
    (HTTP 422)".

    Design: Corner/validations/allocate_requires_qc_passed_lot
    """
    set_clock()
    col = create_collection()
    batch = create_batch(col["id"])
    lot = create_lot(quantity_kg=400, carbon_factor_kgco2e_per_kg=0.50)
    resp = api.allocate_feedstock(
        lot["id"], create_allocate_payload(batch["id"], 100), manager_headers
    )
    validate_error(resp, ApiErrorId.ERR_LOT_NOT_QC_PASSED)
    # The identical call succeeds once the lot is decided PASS.
    qc_lot(lot["id"], "PASS")
    data = validate_success(
        api.allocate_feedstock(
            lot["id"], create_allocate_payload(batch["id"], 100), manager_headers
        )
    )
    assert data["available_kg"] == 300 and data["allocated_kg"] == 100


def test_allocate_over_available_returns_422(api, admin_headers, manager_headers):
    """PRD §3.2: "and requires the requested `quantity_kg` to be no more than
    the lot's `available_kg`, where `available_kg` is the lot's `quantity_kg`
    minus its currently `allocated_kg`; an overdraw is rejected with
    `ERR_INSUFFICIENT_LOT_KG` (HTTP 422)."

    Design: Corner/validations/allocate_over_available_returns_422
    """
    set_clock()
    col = create_collection()
    batch = create_batch(col["id"])
    lot = create_qc_passed_lot(quantity_kg=200, carbon_factor_kgco2e_per_kg=0.50)
    resp = api.allocate_feedstock(
        lot["id"], create_allocate_payload(batch["id"], 200.5), manager_headers
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_LOT_KG)
    data = validate_success(api.get_feedstock_lot(lot["id"], admin_headers))
    assert data["available_kg"] == 200 and data["allocated_kg"] == 0


def test_mix_mass_mismatch_blocks_release_until_exact(api, admin_headers):
    """PRD §3.2: "the batch's `allocated_mass_kg` must equal its `produced_m2`
    multiplied by the canonical 4.0 kilograms per square meter, with both sides
    compared at 2 decimal places; a mismatch is rejected with
    `ERR_MIX_MASS_MISMATCH` (HTTP 422)."

    Design: Corner/validations/mix_mass_mismatch_blocks_release_until_exact
    """
    set_clock()
    col = create_collection()
    lot = create_qc_passed_lot(quantity_kg=400, carbon_factor_kgco2e_per_kg=0.50)
    batch = create_batch(col["id"])  # 100 m2 -> release needs exactly 400 kg
    allocate_to_batch(lot["id"], batch["id"], 300)
    validate_error(
        api.release_batch(batch["id"], admin_headers), ApiErrorId.ERR_MIX_MASS_MISMATCH
    )
    data = validate_success(api.get_batch(batch["id"], admin_headers))
    assert data["status"] == "QUARANTINE"
    # Topping up to the exact mass balance releases the batch.
    allocate_to_batch(lot["id"], batch["id"], 100)
    released = release_batch(batch["id"])
    assert released["status"] == "RELEASED"
    assert released["recycled_content_pct"] == pytest.approx(100.00, abs=1e-9)
    # (400 * 0.50)/100 = 2.0000 at 4dp; 2.0000 + 1.2 -> 3.200 at 3dp.
    assert released["embodied_carbon_kg_per_m2"] == pytest.approx(3.200, abs=1e-9)


def test_supplier_reliability_pass_rate_over_decided_lots(api, admin_headers):
    """PRD §3.2: "when no such decided lots exist the new lot's reliability is
    100.00. Otherwise it is one hundred multiplied by the total received
    kilograms of the decided lots that passed, divided by the total received
    kilograms of all decided lots, rounded half up to 2 decimal places."

    Design: Corner/calculations/supplier_reliability_pass_rate_over_decided_lots
    """
    set_clock()
    r1 = create_lot(supplier_name="NETCO", quantity_kg=100)
    assert r1["supplier_reliability_pct"] == pytest.approx(100.00, abs=1e-9)
    qc_lot(r1["id"], "PASS")
    # Only R1 (PASS, 100 kg) is decided at R2's creation: 100*100/100.
    r2 = create_lot(supplier_name="NETCO", quantity_kg=100)
    assert r2["supplier_reliability_pct"] == pytest.approx(100.00, abs=1e-9)
    qc_lot(r2["id"], "FAIL")
    # R1 PASS 100 of decided 200 kg -> 50.00.
    r3 = create_lot(
        supplier_name="NETCO", source_type="POST_CONSUMER_TILE",
        quantity_kg=300, carbon_factor_kgco2e_per_kg=0.40,
    )
    assert r3["supplier_reliability_pct"] == pytest.approx(50.00, abs=1e-9)
    qc_lot(r3["id"], "PASS")
    # R3's PASS counts only now: passed 400 of decided 500 kg -> 80.00.
    r4 = create_lot(
        supplier_name="NETCO", source_type="POST_INDUSTRIAL_SCRAP",
        quantity_kg=50, carbon_factor_kgco2e_per_kg=0.90,
    )
    assert r4["supplier_reliability_pct"] == pytest.approx(80.00, abs=1e-9)
    for lot in (r1, r2, r3, r4):
        assert_feedstock_lot(lot)


def test_immediate_consistency_read_after_write(api, admin_headers, verifier_headers):
    """PRD §1: "All mutations are immediately consistent: every side effect of
    an operation is visible in that operation's response and in any subsequent
    read."
    PRD §2.4: "`version` (integer): a system-managed integer that starts at 1
    when the resource is created and increments by exactly 1 on every mutation
    of the entity's own stored fields — including mutations that arrive through
    a cascade or an automatic state reconciliation rather than a direct client
    call on that resource."

    Design: Corner/consistency_model/immediate_consistency_read_after_write
    """
    set_clock()
    lot = create_lot(
        supplier_name="FRESHCO", source_type="POST_INDUSTRIAL_SCRAP",
        quantity_kg=75, carbon_factor_kgco2e_per_kg=0.9,
    )
    qc_lot(lot["id"], "PASS")
    data = validate_success(api.get_feedstock_lot(lot["id"], verifier_headers))
    assert data["status"] == "QC_PASSED"
    assert data["version"] == 2, "the QC mutation bumps the lot's own version"
    assert data["supplier_reliability_pct"] == pytest.approx(100.00, abs=1e-9)
    assert data["available_kg"] == 75 and data["allocated_kg"] == 0
