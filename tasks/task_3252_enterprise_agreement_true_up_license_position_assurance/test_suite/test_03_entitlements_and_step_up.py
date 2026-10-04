"""Entitlements: price locking, baseline ratification, OCC, review lock, step-up."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_true_up_line,
    create_active_agreement,
    create_draft_agreement,
    create_entitlement,
    create_organization,
    create_product,
    create_true_up_report,
    create_user_deployment,
    get_success_data,
    make_customer_admin_headers,
    register_anniversary,
    setup_active_agreement_with_anniversary,
    setup_report_in_state,
    setup_settled_report_with_ratified_baseline,
    update_organization_devices,
    validate_error,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["program_admin_headers"]
LS = TEST_USERS["licensing_specialist_headers"]
AUD = TEST_USERS["auditor_headers"]


def test_entitlement_unit_price_locked_at_creation_not_repriced(api):
    """PRD §2.7: "When a `LicenseEntitlement` is purchased, its `unit_price_cents` is captured once from the purchasing organization's then-current price level and is immutable thereafter — later price-level changes do not reprice existing entitlements."

    Design: Corner/calculations/entitlement_unit_price_locked_at_creation_not_repriced
    """
    org, agr = create_active_agreement(enrollment_number="E-LCK-1")
    prod = create_product(sku="PRC1", annual_unit_price_cents=100000)
    ent = create_entitlement(agr["id"], prod["id"], 4)
    assert ent["unit_price_cents"] == 100000, "level A multiplier 1.00 leaves catalog price unchanged"
    update_organization_devices(org["id"], 300)
    org_after = get_success_data(api.get_organization(org["id"], LS))
    assert org_after["price_level"] == "B"
    ent_after = get_success_data(api.get_entitlement(ent["id"], LS))
    assert ent_after["unit_price_cents"] == 100000, "existing entitlement must not be repriced"


def test_entitlement_quantity_below_ratified_baseline_rejected(api):
    """PRD §3.2: "Entitlement quantities can be adjusted afterwards by a `LicensingSpecialist`, but never downward past the ratified floor: a request whose new `quantity` falls below `locked_baseline_quantity` is rejected with `ERR_QUANTITY_BELOW_BASELINE` (HTTP 422)."

    Design: Corner/validations/entitlement_quantity_below_ratified_baseline_rejected
    """
    ctx = setup_settled_report_with_ratified_baseline(entitlement_qty=5, deployment_users=11)
    ent = get_success_data(api.get_entitlement(ctx["entitlement"]["id"], LS))
    assert ent["locked_baseline_quantity"] == 11
    resp = api.adjust_entitlement(ent["id"], {"quantity": 5,
                                              "expected_entitlement_version": ent["version"]}, LS)
    validate_error(resp, ApiErrorId.ERR_QUANTITY_BELOW_BASELINE, 422)


def test_entitlement_locked_while_report_under_review(api):
    """PRD §3.2: "While any true-up report of the entitlement's agreement sits in `SUBMITTED` or `ACCEPTED` status, the license base is considered under review: both quantity adjustments and step-up initiation against that agreement's entitlements are rejected with `ERR_ENTITLEMENT_LOCKED_BY_REVIEW` (HTTP 409)."

    Design: Corner/validations/entitlement_locked_while_report_under_review
    """
    ctx = setup_report_in_state("SUBMITTED", deployment_users=8, entitlement_qty=5)
    ent = get_success_data(api.get_entitlement(ctx["entitlement"]["id"], LS))
    resp = api.adjust_entitlement(ent["id"], {"quantity": 12,
                                              "expected_entitlement_version": ent["version"]}, LS)
    validate_error(resp, ApiErrorId.ERR_ENTITLEMENT_LOCKED_BY_REVIEW, 409)


def test_entitlement_patch_stale_version_occ_conflict(api):
    """PRD §2.8: "Adjusting an entitlement's quantity requires `expected_entitlement_version` holding the entitlement `version` the client last observed; if another writer — a quantity adjustment, a settled true-up line, or an executed step-up — has advanced the entitlement's `version` since, the adjustment is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/entitlement_patch_stale_version_occ_conflict
    """
    org, agr = create_active_agreement(enrollment_number="E-OCC-2")
    prod = create_product(sku="OC2")
    ent = create_entitlement(agr["id"], prod["id"], 5)
    resp1 = api.adjust_entitlement(ent["id"], {"quantity": 8,
                                               "expected_entitlement_version": ent["version"]}, LS)
    data = validate_success(resp1, 200)
    assert data["quantity"] == 8
    resp2 = api.adjust_entitlement(ent["id"], {"quantity": 9,
                                               "expected_entitlement_version": ent["version"]}, LS)
    validate_error(resp2, ApiErrorId.ERR_STALE_VERSION, 412)


def test_duplicate_entitlement_rejected(api):
    """PRD §3.2: "An agreement may hold at most one entitlement per product: creating a second entitlement for the same `agreement_id` and `product_id` pair is rejected with `ERR_DUPLICATE_ENTITLEMENT` (HTTP 409)."

    Design: Corner/errors/duplicate_sku_and_enrollment_and_entitlement
    """
    org, agr = create_active_agreement(enrollment_number="E-DUP-1")
    prod = create_product(sku="DUP1", annual_unit_price_cents=100000)
    create_entitlement(agr["id"], prod["id"], 3)
    resp = api.create_entitlement(agr["id"], {"product_id": prod["id"], "quantity": 5}, LS)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENTITLEMENT, 409)


def test_duplicate_sku_and_enrollment_rejected(api):
    """PRD §3.2: "Each product is registered with a unique `sku` (a duplicate is rejected with `ERR_DUPLICATE_SKU`, HTTP 409)".
    PRD §3.1: "The enrollment number must not collide with any existing agreement's enrollment number; a collision is rejected with `ERR_DUPLICATE_ENROLLMENT` (HTTP 409)."

    Design: Corner/errors/duplicate_sku_and_enrollment_and_entitlement
    """
    org = create_organization(legal_name="Dup Org", qualified_device_count=100)
    create_draft_agreement(org["id"], enrollment_number="E-DUP-1")
    create_product(sku="DUP1")
    resp1 = api.create_product(
        {"sku": "DUP1", "name": "Dup Cal 2", "license_model": "PER_USER",
         "license_kind": "SUBSCRIPTION", "edition": "STANDARD", "family": "CAL",
         "annual_unit_price_cents": 90000, "license_mobility": False}, PA)
    validate_error(resp1, ApiErrorId.ERR_DUPLICATE_SKU, 409)
    resp2 = api.create_agreement(
        {"organization_id": org["id"], "enrollment_number": "E-DUP-1",
         "start_date": "2026-09-01", "end_date": "2029-08-31"}, PA)
    validate_error(resp2, ApiErrorId.ERR_DUPLICATE_ENROLLMENT, 409)


def test_step_up_conserves_total_license_quantity(api):
    """PRD §3.9: "The source entitlement's `quantity` decreases by the converted quantity and its `version` increments. The target entitlement — the one sharing the agreement and the target product — is created with the converted `quantity` if none exists, or has its `quantity` increased by the converted quantity if it does; in both cases the target's `locked_baseline_quantity` tracks the new quantity, and a freshly created target entitlement takes its `unit_price_cents` as the target product's price-level-adjusted price computed below".
    PRD §3.9: "The target's adjusted unit price is the target product's `annual_unit_price_cents` multiplied by the multiplier for the organization's current price level — 1.00 for `A`, 0.95 for `B`, 0.90 for `C`, 0.85 for `D` — rounded half-up to whole cents before any delta is taken. The per-unit delta is that adjusted target price minus the source entitlement's frozen `unit_price_cents`, floored at zero — a step-up never produces a negative charge. The conversion's `charge_cents` is the converted quantity multiplied by that per-unit delta".

    Design: Difficulty/compensating_invariant/step_up_conserves_total_license_quantity
    """
    ctx = setup_active_agreement_with_anniversary(org_devices=3000, with_anniversary=False)
    org, agr = ctx["org"], ctx["agreement"]
    assert org["price_level"] == "C"
    p_std = create_product(sku="O-STD", name="Office Std", license_model="PER_USER",
                           license_kind="SUBSCRIPTION", edition="STANDARD", family="OFFICE",
                           annual_unit_price_cents=100000, license_mobility=False)
    p_ent = create_product(sku="O-ENT", name="Office Ent", license_model="PER_USER",
                           license_kind="SUBSCRIPTION", edition="ENTERPRISE", family="OFFICE",
                           annual_unit_price_cents=200000, license_mobility=False)
    ent = create_entitlement(agr["id"], p_std["id"], 10)
    assert ent["unit_price_cents"] == 90000  # level C multiplier 0.90 on 100000
    resp = api.create_step_up(ent["id"], {"target_product_id": p_ent["id"], "quantity": 7}, LS)
    conv = validate_success(resp, 201)
    resp = api.execute_step_up(conv["id"], LS)
    conv_done = validate_success(resp, 200)
    assert conv_done["charge_cents"] == 7 * (180000 - 90000), \
        "charge = q * (round_half_up(200000*0.90) - 90000)"
    src_after = get_success_data(api.get_entitlement(ent["id"], LS))
    assert src_after["quantity"] == 3, "source loses exactly the converted quantity"
    ents, _ = validate_paginated(api.list_entitlements_of_agreement(agr["id"], LS))
    tgt = next(e for e in ents if e["product_id"] == p_ent["id"])
    assert tgt["quantity"] == 7
    assert tgt["unit_price_cents"] == 180000, "target takes price-level-adjusted unit price"
    assert src_after["quantity"] + tgt["quantity"] == 10, "total licensed units conserved"


def test_step_up_wrong_family_beats_below_baseline_fiscal(api):
    """PRD §2.9: "Requests are validated in a fixed priority order so that the error a caller receives is deterministic when several rules are violated at once. ... finally the business temporal, constraint, referential, and fiscal rules detailed in §3".
    PRD §3.9: "Four validity conditions gate initiation, and violating any of them is rejected with `ERR_STEP_UP_INVALID` (HTTP 422): the target product must belong to the same `family` as the source entitlement's product; the target's `edition` must sit strictly above the source's edition along the `STANDARD` → `PROFESSIONAL` → `ENTERPRISE` ladder; the two products must share the same `license_kind`; and the requested `quantity` must be at least 1."

    Design: Difficulty/priority_pair_validation_conflict/business_constraint_before_business_fiscal_step_up
    """
    ctx = setup_settled_report_with_ratified_baseline(entitlement_qty=10, deployment_users=10)
    ent = get_success_data(api.get_entitlement(ctx["entitlement"]["id"], LS))
    assert ent["quantity"] == 10 and ent["locked_baseline_quantity"] == 10
    p_y = create_product(sku="Y1", name="Db Ent", license_model="PER_USER",
                         license_kind="SUBSCRIPTION", edition="ENTERPRISE", family="DATABASE",
                         annual_unit_price_cents=300000, license_mobility=False)
    resp = api.create_step_up(ent["id"], {"target_product_id": p_y["id"], "quantity": 10}, LS)
    validate_error(resp, ApiErrorId.ERR_STEP_UP_INVALID, 422)


def test_step_up_invalid_when_edition_not_strictly_higher(api):
    """PRD §3.9: "the target's `edition` must sit strictly above the source's edition along the `STANDARD` → `PROFESSIONAL` → `ENTERPRISE` ladder".

    Design: Difficulty/priority_pair_validation_conflict/business_constraint_before_business_fiscal_step_up
    """
    ctx = setup_active_agreement_with_anniversary(with_anniversary=False)
    org, agr = ctx["org"], ctx["agreement"]
    p_std = create_product(sku="X1S", edition="STANDARD", family="OFFICE", annual_unit_price_cents=100000)
    p_std2 = create_product(sku="X1S2", edition="STANDARD", family="OFFICE", annual_unit_price_cents=120000)
    ent = create_entitlement(agr["id"], p_std["id"], 10)
    resp = api.create_step_up(ent["id"], {"target_product_id": p_std2["id"], "quantity": 5}, LS)
    validate_error(resp, ApiErrorId.ERR_STEP_UP_INVALID, 422)
