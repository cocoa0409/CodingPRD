"""Composite setup helpers for the Toy Licensing test suite.

The harness restarts the API server before every test, so every test starts
against an empty database and builds the world it needs through the public
API. These helpers encapsulate the repeated multi-step preambles (studio +
property + agreement, line + sku, retailer + confirmed open review, ...) so
tests can focus on assertions.

Setup calls are checked for HTTP success so a setup failure surfaces as a
clear ``Setup failed`` message instead of an assertion traceback.

Ownership threading: any ``RetailerOps`` call whose authorization depends on
the acting retailer (review scheduling, sale recording) uses
``make_retailer_ops_headers(retailer["id"])``.
"""
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .test_users import TEST_USERS, make_retailer_ops_headers

ADMIN = TEST_USERS["platform_admin"]
BRAND = TEST_USERS["brand_manager"]
STUDIO = TEST_USERS["studio_rep"]
SAFETY = TEST_USERS["safety_engineer"]


def _setup_fail(step: str, response) -> AssertionError:
    try:
        body = response.json()
    except Exception:
        body = response.text
    return AssertionError(f"Setup failed at {step}: HTTP {response.status_code} body={body}")


def set_clock(to_iso8601: str) -> None:
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    if resp.status_code >= 400:
        raise _setup_fail("set_clock", resp)


def create_studio(name: str = "Studio One", confidentiality_tier: Optional[str] = None) -> dict:
    payload = factories.create_studio_payload(name=name)
    if confidentiality_tier is not None:
        payload["confidentiality_tier"] = confidentiality_tier
    resp = api_client.create_studio(payload, ADMIN)
    if resp.status_code >= 400:
        raise _setup_fail("create_studio", resp)
    return get_success_data(resp)


def create_property(studio_id: str, **overrides) -> dict:
    resp = api_client.create_property(factories.create_property_payload(studio_id, **overrides), STUDIO)
    if resp.status_code >= 400:
        raise _setup_fail("create_property", resp)
    return get_success_data(resp)


def create_agreement(property_id: str, **overrides) -> dict:
    resp = api_client.create_license_agreement(
        factories.create_license_agreement_payload(property_id, **overrides), BRAND
    )
    if resp.status_code >= 400:
        raise _setup_fail("create_license_agreement", resp)
    return get_success_data(resp)


def activate_agreement(agreement: dict, as_studio_rep: bool = False) -> dict:
    """Activate an agreement, passing its current version for the OCC check."""
    headers = STUDIO if as_studio_rep else BRAND
    resp = api_client.activate_license_agreement(
        agreement["id"],
        {"expected_license_agreement_version": agreement["version"]},
        headers,
    )
    if resp.status_code >= 400:
        raise _setup_fail("activate_license_agreement", resp)
    return get_success_data(resp)


def setup_active_agreement(
    *,
    royalty_rate_pct: float = 0.10,
    advance_guarantee_cents: int = 0,
    annual_minimum_guarantee_cents: int = 0,
    approval_rights_required: bool = False,
    reveal_date: str = "2026-09-01T00:00:00Z",
    release_date: str = "2027-03-01T00:00:00Z",
    confidentiality_tier: Optional[str] = None,
):
    """Studio + property + agreement activated to ACTIVE.

    Returns ``(studio, property, agreement)`` with the agreement in its
    post-activation state.
    """
    studio = create_studio(confidentiality_tier=confidentiality_tier)
    prop = create_property(studio["id"], reveal_date=reveal_date, release_date=release_date)
    agreement = create_agreement(
        prop["id"],
        royalty_rate_pct=royalty_rate_pct,
        advance_guarantee_cents=advance_guarantee_cents,
        annual_minimum_guarantee_cents=annual_minimum_guarantee_cents,
        approval_rights_required=approval_rights_required,
    )
    agreement = activate_agreement(agreement, as_studio_rep=approval_rights_required)
    return studio, prop, agreement


def create_evergreen_line(name: str = "Evergreen Blocks", street: str = "2027-01-01T00:00:00Z") -> dict:
    resp = api_client.create_toy_line(
        factories.create_toy_line_payload(name=name, target_street_date_input=street), BRAND
    )
    if resp.status_code >= 400:
        raise _setup_fail("create_evergreen_line", resp)
    return get_success_data(resp)


def create_licensed_line(property_id: str, agreement_id: str, name: str = "Licensed Line") -> dict:
    resp = api_client.create_toy_line(
        factories.create_toy_line_payload(
            name=name,
            brand_kind="LICENSED",
            property_id=property_id,
            license_agreement_id=agreement_id,
        ),
        BRAND,
    )
    if resp.status_code >= 400:
        raise _setup_fail("create_licensed_line", resp)
    return get_success_data(resp)


def create_sku(toy_line_id: str, **overrides) -> dict:
    resp = api_client.create_sku(factories.create_sku_payload(toy_line_id, **overrides), BRAND)
    if resp.status_code >= 400:
        raise _setup_fail("create_sku", resp)
    return get_success_data(resp)


def create_factory(**overrides) -> dict:
    resp = api_client.create_factory(factories.create_factory_payload(**overrides), ADMIN)
    if resp.status_code >= 400:
        raise _setup_fail("create_factory", resp)
    return get_success_data(resp)


def create_tooling_order(toy_line_id: str, sku_id: str, factory_id: str, **overrides) -> dict:
    resp = api_client.create_tooling_order(
        factories.create_tooling_order_payload(toy_line_id, sku_id, factory_id, **overrides), BRAND
    )
    if resp.status_code >= 400:
        raise _setup_fail("create_tooling_order", resp)
    return get_success_data(resp)


def create_retailer(name: str = "ToyBox Stores") -> dict:
    resp = api_client.create_retailer(factories.create_retailer_payload(name=name), ADMIN)
    if resp.status_code >= 400:
        raise _setup_fail("create_retailer", resp)
    return get_success_data(resp)


def create_confirmed_review(retailer: dict, **overrides) -> dict:
    """Create a line review as the owning RetailerOps and confirm it as BrandManager."""
    resp = api_client.create_line_review(
        factories.create_line_review_payload(retailer["id"], **overrides),
        make_retailer_ops_headers(retailer["id"]),
    )
    if resp.status_code >= 400:
        raise _setup_fail("create_line_review", resp)
    review = get_success_data(resp)
    resp = api_client.approve_line_review(review["id"], {}, BRAND)
    if resp.status_code >= 400:
        raise _setup_fail("approve_line_review", resp)
    return get_success_data(resp)


def create_commitment(line_review_id: str, sku_id: str, **overrides) -> dict:
    resp = api_client.create_commitment(
        factories.create_commitment_payload(line_review_id, sku_id, **overrides), BRAND
    )
    if resp.status_code >= 400:
        raise _setup_fail("create_commitment", resp)
    return get_success_data(resp)


def create_shipment(commitment_id: str, **overrides) -> dict:
    resp = api_client.create_shipment(factories.create_shipment_payload(commitment_id, **overrides), BRAND)
    if resp.status_code >= 400:
        raise _setup_fail("create_shipment", resp)
    return get_success_data(resp)


def submit_safety_test(sku: dict, **overrides) -> dict:
    overrides.setdefault("claimed_age_grade_months", sku["age_grade_months"])
    resp = api_client.create_safety_test(factories.create_safety_test_payload(sku["id"], **overrides), SAFETY)
    if resp.status_code >= 400:
        raise _setup_fail("create_safety_test", resp)
    return get_success_data(resp)


def pass_safety_test(safety_test: dict, sku: dict) -> dict:
    """Record a conforming PASS so the SKU moves to safety_status PASSED."""
    resp = api_client.record_safety_result(
        safety_test["id"],
        {
            "outcome": "PASS",
            "result_age_grade_months": sku["age_grade_months"],
            "validated_claims": list(sku["packaging_claims"]),
        },
        SAFETY,
    )
    if resp.status_code >= 400:
        raise _setup_fail("record_safety_result", resp)
    return get_success_data(resp)


def certify_sku(sku: dict) -> dict:
    """Submit + pass a safety test for the SKU; returns the updated SKU."""
    test = submit_safety_test(sku)
    pass_safety_test(test, sku)
    resp = api_client.get_sku(sku["id"], BRAND)
    if resp.status_code >= 400:
        raise _setup_fail("get_sku", resp)
    return get_success_data(resp)


def advance_line(line: dict) -> dict:
    """Advance a toy line one stage, passing its current version (OCC)."""
    resp = api_client.advance_toy_line(line["id"], {"expected_toy_line_version": line["version"]}, BRAND)
    if resp.status_code >= 400:
        raise _setup_fail("advance_toy_line", resp)
    return get_success_data(resp)


# ─────────────────────────────────────────────────────────────────────────────
# Composite scenario builders
# ─────────────────────────────────────────────────────────────────────────────


def setup_evergreen_line_with_sku(
    *,
    street: str = "2027-01-01T00:00:00Z",
    line_name: str = "Evergreen Blocks",
    **sku_overrides,
):
    """Evergreen line + one SKU. Returns ``(line, sku)``."""
    line = create_evergreen_line(name=line_name, street=street)
    sku = create_sku(line["id"], **sku_overrides)
    return line, sku


def setup_retail_open_review(
    *,
    retailer_name: str = "ToyBox Stores",
    shelf_slots_total: int = 20,
    **review_overrides,
):
    """Retailer + CONFIRMED review whose window is OPEN at the current clock.

    Default window: 2026-09-15 .. 2026-11-15 with deadline 2026-11-01 — OPEN
    at the common setup clock of 2026-10-01.
    Returns ``(retailer, review)``.
    """
    retailer = create_retailer(name=retailer_name)
    review = create_confirmed_review(retailer, shelf_slots_total=shelf_slots_total, **review_overrides)
    return retailer, review


def setup_review_with_commitment(
    sku: dict,
    *,
    retailer_name: str = "ToyBox Stores",
    shelf_slots_total: int = 20,
    **commitment_overrides,
):
    """Retailer + CONFIRMED OPEN review + one commitment on the SKU.

    Review-window keys (``window_start``, ``window_end``,
    ``commitment_deadline``) are forwarded to the review; everything else
    configures the commitment.
    Returns ``(retailer, review, commitment)``.
    """
    review_keys = ("window_start", "window_end", "commitment_deadline")
    review_overrides = {k: commitment_overrides.pop(k) for k in review_keys if k in commitment_overrides}
    retailer, review = setup_retail_open_review(
        retailer_name=retailer_name, shelf_slots_total=shelf_slots_total, **review_overrides
    )
    commitment = create_commitment(review["id"], sku["id"], **commitment_overrides)
    return retailer, review, commitment


def setup_line_in_development_with_passed_sku(
    *,
    street: str = "2027-01-01T00:00:00Z",
    line_name: str = "Evergreen Blocks",
    **sku_overrides,
):
    """Evergreen line advanced to IN_DEVELOPMENT with a safety-PASSED SKU.

    The SKU is created (and tested) after the first advance so the test gate
    (line in CONCEPT or IN_DEVELOPMENT) is satisfied in both states.
    Returns ``(line, sku)`` with the line in IN_DEVELOPMENT.
    """
    line = create_evergreen_line(name=line_name, street=street)
    line = advance_line(line)  # CONCEPT -> IN_DEVELOPMENT
    sku = create_sku(line["id"], **sku_overrides)
    sku = certify_sku(sku)
    return line, sku


def setup_tooled_line(
    *,
    street: str = "2027-01-01T00:00:00Z",
    line_name: str = "Evergreen Blocks",
    factory_capacity: int = 100000,
    tooling_units: int = 100,
    production_month: str = "2026-11",
    **sku_overrides,
):
    """Evergreen line advanced to TOOLED: PASSED SKU + one APPROVED tooling order.

    Returns ``(line, sku, factory, tooling_order)``.
    """
    line, sku = setup_line_in_development_with_passed_sku(
        street=street, line_name=line_name, **sku_overrides
    )
    factory = create_factory(capacity_units_per_month=factory_capacity)
    order = create_tooling_order(
        line["id"], sku["id"], factory["id"], production_month=production_month, units=tooling_units
    )
    line = advance_line(line)  # IN_DEVELOPMENT -> TOOLED
    return line, sku, factory, order


def setup_committed_line(
    *,
    street: str = "2026-09-01T00:00:00Z",
    line_name: str = "Nostalgia Minis",
    commitment_overrides: Optional[dict] = None,
    **sku_overrides,
):
    """Evergreen line advanced to COMMITTED with one commitment on its SKU.

    Default street date is already in the past at the usual setup clock, so a
    subsequent clock-set also exercises the auto-advance to ON_SHELF.
    Returns ``(line, sku, retailer, review, commitment, factory, order)``.
    """
    commitment_overrides = commitment_overrides or {}
    line, sku, factory, order = setup_tooled_line(street=street, line_name=line_name, **sku_overrides)
    retailer, review = setup_retail_open_review()
    commitment = create_commitment(review["id"], sku["id"], **commitment_overrides)
    line = advance_line(line)  # TOOLED -> COMMITTED
    return line, sku, retailer, review, commitment, factory, order


def setup_licensed_chain(
    *,
    clock: str = "2026-10-01T00:00:00Z",
    royalty_rate_pct: float = 0.10,
    advance_guarantee_cents: int = 0,
    annual_minimum_guarantee_cents: int = 0,
    approval_rights_required: bool = False,
    reveal_date: str = "2026-09-01T00:00:00Z",
    release_date: str = "2027-03-01T00:00:00Z",
    line_name: str = "Galaxy Racers Vehicles",
    **sku_overrides,
):
    """Clock + studio + revealed property + ACTIVE agreement + LICENSED line + SKU.

    Returns ``(studio, property, agreement, line, sku)``.
    """
    set_clock(clock)
    studio, prop, agreement = setup_active_agreement(
        royalty_rate_pct=royalty_rate_pct,
        advance_guarantee_cents=advance_guarantee_cents,
        annual_minimum_guarantee_cents=annual_minimum_guarantee_cents,
        approval_rights_required=approval_rights_required,
        reveal_date=reveal_date,
        release_date=release_date,
    )
    line = create_licensed_line(prop["id"], agreement["id"], name=line_name)
    sku = create_sku(line["id"], **sku_overrides)
    return studio, prop, agreement, line, sku


def setup_licensed_chain_with_shipment(
    *,
    clock: str = "2026-10-01T00:00:00Z",
    commitment_overrides: Optional[dict] = None,
    shipment_overrides: Optional[dict] = None,
    **chain_kwargs,
):
    """Licensed chain plus a retail review, a commitment, and a PLANNED shipment.

    Returns ``(studio, property, agreement, line, sku, retailer, review, commitment, shipment)``.
    """
    commitment_overrides = commitment_overrides or {}
    shipment_overrides = shipment_overrides or {}
    studio, prop, agreement, line, sku = setup_licensed_chain(clock=clock, **chain_kwargs)
    retailer, review, commitment = setup_review_with_commitment(sku, **commitment_overrides)
    shipment = create_shipment(commitment["id"], **shipment_overrides)
    return studio, prop, agreement, line, sku, retailer, review, commitment, shipment


def record_sale(shipment_id: str, retailer: dict, units_sold: int) -> dict:
    """Record sell-through as the shipment-owning RetailerOps operator."""
    resp = api_client.record_sale(
        shipment_id, {"units_sold": units_sold}, make_retailer_ops_headers(retailer["id"])
    )
    if resp.status_code >= 400:
        raise _setup_fail("record_sale", resp)
    return get_success_data(resp)
