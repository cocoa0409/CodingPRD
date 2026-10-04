"""Composite setup helpers for the prescription data licensing domain.

Every helper builds its preconditions from scratch against a freshly restarted
server (the runner restarts the API before every test, so the database starts
empty and the logical clock reads 2026-09-01T00:00:00Z).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .factories import (
    create_agreement_payload,
    create_batch_payload,
    create_cell_payload,
    create_client_payload,
    create_deid_profile_payload,
    create_delivery_period_payload,
    create_methodology_payload,
    create_prescriber_payload,
    create_product_payload,
    create_supplier_payload,
)
from .test_users import (
    TEST_USERS,
    make_manufacturer_client_headers,
    make_supplier_operator_headers,
)

PA = TEST_USERS["platform_admin_headers"]
DAM = TEST_USERS["data_acquisition_manager_headers"]
PO = TEST_USERS["privacy_officer_headers"]


# ---------------------------------------------------------------------------
# Tier 1: basic entity creation
# ---------------------------------------------------------------------------

def create_client(**overrides):
    return get_success_data(api.create_client(create_client_payload(**overrides), PA))


def create_supplier(**overrides):
    return get_success_data(api.create_supplier(create_supplier_payload(**overrides), DAM))


def create_agreement(supplier_id, **overrides):
    payload = create_agreement_payload(**overrides)
    return get_success_data(api.create_agreement(supplier_id, payload, DAM))


def create_active_agreement(supplier_id, **overrides):
    """Create an agreement for the supplier and activate it. Returns the
    ACTIVE agreement (as returned by the activate call)."""
    agreement = create_agreement(supplier_id, **overrides)
    return get_success_data(api.activate_agreement(agreement["id"], DAM))


def create_deid_profile(**overrides):
    return get_success_data(api.create_deid_profile(create_deid_profile_payload(**overrides), PO))


def create_prescriber(**overrides):
    return get_success_data(api.create_prescriber(create_prescriber_payload(**overrides), PA))


def create_methodology(**overrides):
    return get_success_data(api.create_methodology(create_methodology_payload(**overrides), PA))


def create_cell(methodology_id, **overrides):
    return get_success_data(api.create_cell(create_cell_payload(methodology_id, **overrides), PA))


def create_product(client_id, methodology_id, **overrides):
    payload = create_product_payload(client_id, methodology_id, **overrides)
    return get_success_data(api.create_product(payload, PA))


# ---------------------------------------------------------------------------
# Tier 2: acquisition pipeline — suppliers, agreements, batches
# ---------------------------------------------------------------------------

def submit_batch(agreement_id, supplier_id, **overrides):
    """Submit a feed batch as the owning supplier's operator."""
    payload = create_batch_payload(agreement_id, **overrides)
    return get_success_data(
        api.create_batch(payload, make_supplier_operator_headers(supplier_id))
    )


def validate_batch(batch_id):
    return get_success_data(api.validate_batch(batch_id, DAM))


def deidentify_batch(batch_id, profile_id):
    return get_success_data(
        api.deidentify_batch(batch_id, {"deidentification_profile_id": profile_id}, PO)
    )


def setup_active_agreement(supplier_overrides=None, agreement_overrides=None):
    """Supplier + ACTIVE agreement. Returns (supplier, agreement)."""
    supplier = create_supplier(**(supplier_overrides or {}))
    agreement = create_active_agreement(supplier["id"], **(agreement_overrides or {}))
    return supplier, agreement


def setup_received_batch(supplier_overrides=None, agreement_overrides=None,
                         batch_overrides=None):
    """Supplier + ACTIVE agreement + one RECEIVED batch.
    Returns (supplier, agreement, batch)."""
    supplier, agreement = setup_active_agreement(supplier_overrides, agreement_overrides)
    batch = submit_batch(agreement["id"], supplier["id"], **(batch_overrides or {}))
    return supplier, agreement, batch


def setup_validated_batch(**kwargs):
    """Supplier + ACTIVE agreement + one VALIDATED batch.
    Returns (supplier, agreement, batch)."""
    supplier, agreement, batch = setup_received_batch(**kwargs)
    batch = validate_batch(batch["id"])
    return supplier, agreement, batch


def setup_deidentified_batch(profile_overrides=None, **kwargs):
    """Supplier + ACTIVE agreement + profile + one DEIDENTIFIED batch.
    Returns (supplier, agreement, profile, batch)."""
    supplier, agreement, batch = setup_validated_batch(**kwargs)
    profile = create_deid_profile(**(profile_overrides or {}))
    batch = deidentify_batch(batch["id"], profile["id"])
    return supplier, agreement, profile, batch


def setup_accepted_batch(qa_score=0.95, **kwargs):
    """Full feed pipeline through ACCEPTED.
    Returns (supplier, agreement, profile, batch)."""
    supplier, agreement, profile, batch = setup_deidentified_batch(**kwargs)
    batch = get_success_data(api.accept_batch(batch["id"], {"deid_qa_score": qa_score}, PO))
    return supplier, agreement, profile, batch


# ---------------------------------------------------------------------------
# Tier 3: prescriber opt-out lifecycle
# ---------------------------------------------------------------------------

def create_opt_out(prescriber_id, reason=None):
    payload = {} if reason is None else {"reason": reason}
    return get_success_data(api.create_opt_out(prescriber_id, payload, PO))


def create_verified_opt_out(prescriber_id, reason=None):
    """Submit + verify an opt-out. Returns the VERIFIED opt-out."""
    opt_out = create_opt_out(prescriber_id, reason=reason)
    return get_success_data(api.verify_opt_out(opt_out["id"], PO))


def create_active_opt_out(prescriber_id, reason=None):
    """Submit + verify + activate an opt-out. Returns the ACTIVE opt-out."""
    opt_out = create_verified_opt_out(prescriber_id, reason=reason)
    return get_success_data(api.activate_opt_out(opt_out["id"], PO))


# ---------------------------------------------------------------------------
# Tier 4: report products, periods, deliveries
# ---------------------------------------------------------------------------

def setup_client_methodology_product(cells=(), client_overrides=None,
                                     methodology_overrides=None, product_overrides=None,
                                     prescriber_ids=None):
    """Client + methodology + cells + product.

    `cells` is an iterable of per-cell override dicts (an empty tuple creates
    no cells). Returns a dict with client, methodology, cells, product.
    """
    client = create_client(**(client_overrides or {}))
    methodology = create_methodology(**(methodology_overrides or {}))
    created_cells = [create_cell(methodology["id"], **cell_kw) for cell_kw in cells]
    if prescriber_ids is not None:
        product_overrides = dict(product_overrides or {})
        product_overrides["prescriber_ids"] = prescriber_ids
    product = create_product(client["id"], methodology["id"],
                             **(product_overrides or {}))
    return {
        "client": client,
        "methodology": methodology,
        "cells": created_cells,
        "product": product,
    }


def setup_scheduled_delivery(cells=({"period_code": "2026-08"},),
                             period_code="2026-08", period_end_date="2026-08-31",
                             total_due_deliveries=1, **kwargs):
    """Client + methodology + CURRENT cells + product + period + one SCHEDULED
    delivery. With the default clock (2026-09-01) the delivery window is met.

    Returns a dict with client, methodology, cells, product, period, delivery.
    """
    ctx = setup_client_methodology_product(cells=cells, **kwargs)
    period = get_success_data(api.create_delivery_period(
        ctx["product"]["id"],
        create_delivery_period_payload(
            period_code=period_code,
            period_end_date=period_end_date,
            total_due_deliveries=total_due_deliveries,
        ),
        PA,
    ))
    delivery = get_success_data(api.schedule_delivery(period["id"], PA))
    ctx.update({"period": period, "delivery": delivery})
    return ctx


def compile_delivery(delivery_id, payload=None):
    return get_success_data(api.compile_delivery(delivery_id, PA, payload=payload))


def release_delivery(delivery_id):
    return get_success_data(api.release_delivery(delivery_id, PA))


def recall_delivery(delivery_id, payload=None):
    return get_success_data(api.recall_delivery(delivery_id, PA, payload=payload))


def setup_compiled_delivery(**kwargs):
    """setup_scheduled_delivery + compile. Returns the context dict; the
    `delivery` entry is the COMPILED delivery."""
    ctx = setup_scheduled_delivery(**kwargs)
    ctx["delivery"] = compile_delivery(ctx["delivery"]["id"])
    return ctx


def setup_released_delivery(**kwargs):
    """Compiled delivery advanced to RELEASED."""
    ctx = setup_compiled_delivery(**kwargs)
    ctx["delivery"] = release_delivery(ctx["delivery"]["id"])
    return ctx


def setup_recalled_delivery(**kwargs):
    """Compiled (then released) delivery recalled once."""
    ctx = setup_released_delivery(**kwargs)
    ctx["delivery"] = recall_delivery(ctx["delivery"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: audits and client suspension
# ---------------------------------------------------------------------------

def request_audit(client_id, window_start_date="2026-03-01",
                  window_end_date="2026-03-31", purpose="AUDIT_COMPLIANCE"):
    """Request an audit as the owning ManufacturerClient."""
    payload = {
        "window_start_date": window_start_date,
        "window_end_date": window_end_date,
        "purpose": purpose,
    }
    return get_success_data(
        api.request_audit(client_id, payload, make_manufacturer_client_headers(client_id))
    )


def complete_audit(client_id, outcome="CLEAN", window_start_date="2026-03-01",
                   window_end_date="2026-03-31"):
    """Request + schedule + complete an audit for the client.
    Returns the COMPLETED audit event."""
    audit = request_audit(client_id, window_start_date, window_end_date)
    get_success_data(api.schedule_audit(audit["id"], PA))
    return get_success_data(api.complete_audit(audit["id"], {"outcome": outcome}, PA))


def setup_suspended_client(client_overrides=None, product_count=1):
    """Client (with products) suspended via a REIDENTIFICATION_ATTEMPTED audit.

    Returns (client, products, audit) with the client SUSPENDED and its
    products SUSPENDED.
    """
    client = create_client(**(client_overrides or {}))
    methodology = create_methodology()
    products = [
        create_product(client["id"], methodology["id"], name=f"Product {i}")
        for i in range(product_count)
    ]
    audit = complete_audit(client["id"], outcome="REIDENTIFICATION_ATTEMPTED")
    return client, products, audit
