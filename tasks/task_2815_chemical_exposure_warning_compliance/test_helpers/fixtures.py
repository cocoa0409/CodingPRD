"""Composite setup builders and pytest fixtures.

The server is restarted before every single test, so every test starts against
an empty database and must build all of its own preconditions through the
public API.  The builders below are the shared vocabulary for that: each one
drives real endpoints, checks each step leniently with ``get_success_data`` and
returns the created rows so a test can assert on them or extend the chain.

Layering, from cheapest to richest:

* Tier 1 — single-entity creators and state advancers
  (``make_listed_chemical``, ``advance_disclosure``, ``report_lab_result`` …).
* Tier 2 — entity hierarchy: a supplier with a material carrying a chemical
  link at a chosen disclosure state (``make_supplied_material``), and a product
  with that material on its bill of materials (``make_product_with_component``).
* Tier 3 — full-lifecycle shortcuts: a FINAL assessment
  (``finalize_assessment``), an APPROVED determination
  (``make_approved_determination``) and an implemented placement
  (``make_implemented_placement``), plus ``build_warned_product`` which walks the
  whole chain in one call.
* Tier 4 — accumulation and threshold targeting: ``make_notice``,
  ``escalate_notice_to_negotiation`` and ``propose_settlement`` for the money
  waterfall.
* Tier 5 — terminal states: ``execute_settlement`` and
  ``discontinue_product``.
"""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ChemicalComplianceApiClient
from .constants import (
    BENZENE_LEVEL,
    BPA_LEVEL,
    CHANNEL_RETAIL,
    COMPLETENESS_COMPLETE,
    COMPLETENESS_INCOMPLETE,
    DECISION_WARNING_REQUIRED,
    DEFAULT_CLOCK,
    DISCLOSURE_INCOMPLETE,
    DISCLOSURE_NOT_REQUESTED,
    DISCLOSURE_RECEIVED,
    DISCLOSURE_REFUSED,
    DISCLOSURE_REQUESTED,
    DISCLOSURE_VERIFIED,
    LISTING_EFFECTIVE_DATE,
    METHOD_MODELED,
    REQUIRED_CHANNEL_LABEL,
    ROUTE_DERMAL,
    ROUTE_ORAL,
)
from .test_users import (
    COMPLIANCE_ANALYST,
    LABELING_SPECIALIST,
    REGISTRY_ADMIN,
    REGULATORY_COUNSEL,
    REGULATORY_COUNSEL_2,
    TOXICOLOGY_REVIEWER,
)
from .types import Headers, Payload, Row

# ─────────────────────────────────────────────────────────────────────────────
# Tier 1 — the logical clock
# ─────────────────────────────────────────────────────────────────────────────


def set_clock(api: ChemicalComplianceApiClient, instant: str = DEFAULT_CLOCK) -> Row:
    """Move the logical clock and return the ``current_utc``/``previous_utc`` pair."""
    return get_success_data(api.set_clock(instant, REGISTRY_ADMIN))


# ─────────────────────────────────────────────────────────────────────────────
# Tier 1 — listed chemicals
# ─────────────────────────────────────────────────────────────────────────────


def make_listed_chemical(
    api: ChemicalComplianceApiClient,
    payload: Payload,
    list_it: bool = True,
    listing_effective_date: str = LISTING_EFFECTIVE_DATE,
) -> Row:
    """Register a chemical and, by default, drive it to ``LISTED``."""
    chemical = get_success_data(api.create_listed_chemical(payload, REGISTRY_ADMIN))
    if list_it:
        chemical = get_success_data(
            api.listed_chemical_transition(
                chemical["id"], f.list_action(listing_effective_date), REGISTRY_ADMIN
            )
        )
    return chemical


def make_bpa(
    api: ChemicalComplianceApiClient, list_it: bool = True, **overrides: Any
) -> Row:
    return make_listed_chemical(api, f.bpa_payload(**overrides), list_it=list_it)


def make_benzene(
    api: ChemicalComplianceApiClient, list_it: bool = True, **overrides: Any
) -> Row:
    return make_listed_chemical(api, f.benzene_payload(**overrides), list_it=list_it)


def revise_safe_harbor(
    api: ChemicalComplianceApiClient,
    chemical_id: str,
    safe_harbor_basis: Any = f.OMIT,
    safe_harbor_level_ug_per_day: Any = f.OMIT,
) -> Row:
    """Trigger the four-level registry cascade."""
    return get_success_data(
        api.listed_chemical_transition(
            chemical_id,
            f.revise_safe_harbor_action(
                safe_harbor_basis=safe_harbor_basis,
                safe_harbor_level_ug_per_day=safe_harbor_level_ug_per_day,
            ),
            REGISTRY_ADMIN,
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tier 1 — suppliers and warranties
# ─────────────────────────────────────────────────────────────────────────────


def make_supplier(
    api: ChemicalComplianceApiClient,
    legal_name: str = "Northgate Polymers",
    **overrides: Any,
) -> Row:
    return get_success_data(
        api.create_supplier(f.supplier_payload(legal_name, **overrides), COMPLIANCE_ANALYST)
    )


def make_warranted_supplier(
    api: ChemicalComplianceApiClient,
    legal_name: str = "Northgate Polymers",
    warranty_scope: str = "ALL_MATERIALS",
    pass_through_warning_obligation: bool = True,
    indemnity_cap_cents: int = 100000000,
    warranty_effective_from: str = "2026-01-01T00:00:00Z",
    warranty_effective_to: Any = f.OMIT,
    **overrides: Any,
) -> Row:
    """A supplier whose warranty has been executed and is therefore ``ACTIVE``."""
    supplier = make_supplier(
        api,
        legal_name,
        warranty_scope=warranty_scope,
        pass_through_warning_obligation=pass_through_warning_obligation,
        indemnity_cap_cents=indemnity_cap_cents,
        warranty_effective_from=warranty_effective_from,
        warranty_effective_to=warranty_effective_to,
        **overrides,
    )
    return get_success_data(
        api.supplier_transition(
            supplier["id"], f.action_payload("EXECUTE_WARRANTY"), REGULATORY_COUNSEL
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tier 1 — materials, disclosure and chemical links
# ─────────────────────────────────────────────────────────────────────────────


def make_material(
    api: ChemicalComplianceApiClient,
    material_code: str,
    supplier_id: str,
    **overrides: Any,
) -> Row:
    return get_success_data(
        api.create_material(
            f.material_payload(material_code, supplier_id, **overrides),
            COMPLIANCE_ANALYST,
        )
    )


def advance_disclosure(
    api: ChemicalComplianceApiClient,
    material_id: str,
    target_status: str,
    headers: Headers = COMPLIANCE_ANALYST,
) -> Row:
    """Walk the supplier data-collection machine to ``target_status``."""
    if target_status == DISCLOSURE_NOT_REQUESTED:
        return get_success_data(api.get_material(material_id, headers))

    material = get_success_data(
        api.material_disclosure(material_id, f.action_payload("REQUEST"), headers)
    )
    if target_status == DISCLOSURE_REQUESTED:
        return material

    if target_status == DISCLOSURE_REFUSED:
        return get_success_data(
            api.material_disclosure(
                material_id, f.action_payload("MARK_REFUSED"), headers
            )
        )

    completeness = (
        COMPLETENESS_INCOMPLETE
        if target_status == DISCLOSURE_INCOMPLETE
        else COMPLETENESS_COMPLETE
    )
    material = get_success_data(
        api.material_disclosure(
            material_id, f.record_response_action(completeness), headers
        )
    )
    if target_status in (DISCLOSURE_INCOMPLETE, DISCLOSURE_RECEIVED):
        return material

    assert target_status == DISCLOSURE_VERIFIED, (
        f"Unsupported disclosure target status {target_status!r}"
    )
    return get_success_data(
        api.material_disclosure(material_id, f.action_payload("VERIFY"), headers)
    )


def link_chemical(
    api: ChemicalComplianceApiClient,
    material_id: str,
    chemical_id: str,
    declared_concentration_ppm: float,
    headers: Headers = COMPLIANCE_ANALYST,
) -> Row:
    return get_success_data(
        api.create_material_chemical(
            material_id,
            f.material_chemical_payload(chemical_id, declared_concentration_ppm),
            headers,
        )
    )


def request_lab_test(api: ChemicalComplianceApiClient, link_id: str) -> Row:
    return get_success_data(
        api.material_chemical_transition(
            link_id, f.action_payload("REQUEST_TEST"), COMPLIANCE_ANALYST
        )
    )


def report_lab_result(
    api: ChemicalComplianceApiClient,
    link_id: str,
    lab_result_ppm: float,
    lab_loq_ppm: float,
    lab_name: str = "Pacific Analytical",
    request_first: bool = True,
) -> Row:
    """Drive a link to ``TEST_REPORTED`` so its basis becomes ``LAB_TESTED``."""
    if request_first:
        request_lab_test(api, link_id)
    return get_success_data(
        api.material_chemical_transition(
            link_id,
            f.report_result_action(lab_name, lab_result_ppm, lab_loq_ppm),
            COMPLIANCE_ANALYST,
        )
    )


def verify_lab_result(api: ChemicalComplianceApiClient, link_id: str) -> Row:
    return get_success_data(
        api.material_chemical_transition(
            link_id, f.action_payload("VERIFY"), TOXICOLOGY_REVIEWER
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tier 2 — a supplier, its material, one chemical link and a disclosure state
# ─────────────────────────────────────────────────────────────────────────────


def make_supplied_material(
    api: ChemicalComplianceApiClient,
    chemical_id: str,
    declared_concentration_ppm: float = 40.0,
    material_code: str = "RM-100",
    supplier_legal_name: str = "Northgate Polymers",
    disclosure_status: str = DISCLOSURE_VERIFIED,
    supplier_id: Optional[str] = None,
    **material_overrides: Any,
) -> Dict[str, Row]:
    """A material that declares one chemical and sits at a chosen disclosure state.

    The chemical link is created before the disclosure is advanced, matching the
    order the PRD's own workflow describes.
    """
    if supplier_id is None:
        supplier_id = make_supplier(api, supplier_legal_name)["id"]
    material = make_material(api, material_code, supplier_id, **material_overrides)
    link = link_chemical(
        api, material["id"], chemical_id, declared_concentration_ppm
    )
    material = advance_disclosure(api, material["id"], disclosure_status)
    return {"supplier_id": supplier_id, "material": material, "link": link}


# ─────────────────────────────────────────────────────────────────────────────
# Tier 2 — products and the bill of materials
# ─────────────────────────────────────────────────────────────────────────────


def make_product(
    api: ChemicalComplianceApiClient, sku: str, **overrides: Any
) -> Row:
    return get_success_data(
        api.create_product(f.product_payload(sku, **overrides), REGISTRY_ADMIN)
    )


def add_component(
    api: ChemicalComplianceApiClient,
    product_id: str,
    material_id: str,
    quantity_grams_per_unit: float = 0.25,
    contact_factor: float = 0.5,
    **overrides: Any,
) -> Row:
    return get_success_data(
        api.create_component(
            product_id,
            f.component_payload(
                material_id, quantity_grams_per_unit, contact_factor, **overrides
            ),
            COMPLIANCE_ANALYST,
        )
    )


def remove_component(api: ChemicalComplianceApiClient, component_id: str) -> Row:
    return get_success_data(
        api.component_transition(
            component_id, f.action_payload("REMOVE"), COMPLIANCE_ANALYST
        )
    )


def read_product(
    api: ChemicalComplianceApiClient,
    product_id: str,
    headers: Headers = COMPLIANCE_ANALYST,
) -> Row:
    return get_success_data(api.get_product(product_id, headers))


def make_product_with_component(
    api: ChemicalComplianceApiClient,
    chemical_id: str,
    sku: str = "SKU-100",
    declared_concentration_ppm: float = 40.0,
    quantity_grams_per_unit: float = 0.25,
    contact_factor: float = 0.5,
    material_code: str = "RM-100",
    disclosure_status: str = DISCLOSURE_VERIFIED,
    product_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A product carrying exactly one ACTIVE component of one supplied material."""
    supplied = make_supplied_material(
        api,
        chemical_id,
        declared_concentration_ppm=declared_concentration_ppm,
        material_code=material_code,
        disclosure_status=disclosure_status,
    )
    product = make_product(api, sku, **(product_overrides or {}))
    component = add_component(
        api,
        product["id"],
        supplied["material"]["id"],
        quantity_grams_per_unit,
        contact_factor,
    )
    return {
        "supplier_id": supplied["supplier_id"],
        "material": supplied["material"],
        "link": supplied["link"],
        "product": read_product(api, product["id"]),
        "component": component,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Tier 3 — exposure assessments through to FINAL
# ─────────────────────────────────────────────────────────────────────────────


def make_assessment(
    api: ChemicalComplianceApiClient,
    product_id: str,
    chemical_id: str,
    method: str = METHOD_MODELED,
    route: str = ROUTE_ORAL,
    uses_per_day: float = 1.0,
    headers: Headers = COMPLIANCE_ANALYST,
) -> Row:
    return get_success_data(
        api.create_assessment(
            product_id,
            f.assessment_payload(chemical_id, method, route, uses_per_day),
            headers,
        )
    )


def submit_assessment(
    api: ChemicalComplianceApiClient,
    assessment_id: str,
    headers: Headers = COMPLIANCE_ANALYST,
) -> Row:
    return get_success_data(
        api.assessment_transition(
            assessment_id, f.action_payload("SUBMIT"), headers
        )
    )


def peer_review_assessment(
    api: ChemicalComplianceApiClient,
    assessment_id: str,
    headers: Headers = TOXICOLOGY_REVIEWER,
) -> Row:
    return get_success_data(
        api.assessment_transition(
            assessment_id, f.action_payload("PEER_REVIEW"), headers
        )
    )


def finalize_assessment(
    api: ChemicalComplianceApiClient,
    assessment_id: str,
    submitter: Headers = COMPLIANCE_ANALYST,
    reviewer: Headers = TOXICOLOGY_REVIEWER,
    peer_review: bool = True,
) -> Row:
    """Walk a DRAFT assessment to FINAL through submission and peer review."""
    submit_assessment(api, assessment_id, submitter)
    if peer_review:
        peer_review_assessment(api, assessment_id, reviewer)
    return get_success_data(
        api.assessment_transition(
            assessment_id, f.action_payload("FINALIZE"), reviewer
        )
    )


def make_final_assessment(
    api: ChemicalComplianceApiClient,
    product_id: str,
    chemical_id: str,
    method: str = METHOD_MODELED,
    route: str = ROUTE_ORAL,
    uses_per_day: float = 1.0,
) -> Row:
    assessment = make_assessment(
        api, product_id, chemical_id, method, route, uses_per_day
    )
    return finalize_assessment(api, assessment["id"])


# ─────────────────────────────────────────────────────────────────────────────
# Tier 3 — warning determinations and placements
# ─────────────────────────────────────────────────────────────────────────────


def make_determination(
    api: ChemicalComplianceApiClient,
    product_id: str,
    assessment_id: str,
    decision: str = DECISION_WARNING_REQUIRED,
    expected_product_version: Optional[int] = None,
    headers: Headers = LABELING_SPECIALIST,
) -> Row:
    """Open a determination, reading the product's fresh version if none is given."""
    if expected_product_version is None:
        expected_product_version = api.product_version(product_id, headers)
    return get_success_data(
        api.create_determination(
            f.determination_payload(
                product_id, assessment_id, decision, expected_product_version
            ),
            headers,
        )
    )


def approve_determination(
    api: ChemicalComplianceApiClient,
    determination_id: str,
    preparer: Headers = LABELING_SPECIALIST,
    approver: Headers = REGULATORY_COUNSEL,
) -> Row:
    get_success_data(
        api.determination_transition(
            determination_id, f.action_payload("SUBMIT_FOR_APPROVAL"), preparer
        )
    )
    return get_success_data(
        api.determination_transition(
            determination_id, f.action_payload("APPROVE"), approver
        )
    )


def make_approved_determination(
    api: ChemicalComplianceApiClient,
    product_id: str,
    assessment_id: str,
    decision: str = DECISION_WARNING_REQUIRED,
) -> Row:
    determination = make_determination(api, product_id, assessment_id, decision)
    return approve_determination(api, determination["id"])


def add_placement(
    api: ChemicalComplianceApiClient,
    determination_id: str,
    channel: str = REQUIRED_CHANNEL_LABEL,
    effective_from: str = "2026-06-01T00:00:00Z",
    effective_to: Any = f.OMIT,
    headers: Headers = LABELING_SPECIALIST,
    **overrides: Any,
) -> Row:
    return get_success_data(
        api.create_placement(
            determination_id,
            f.placement_payload(
                channel, effective_from, effective_to, **overrides
            ),
            headers,
        )
    )


def implement_placement(
    api: ChemicalComplianceApiClient,
    placement_id: str,
    headers: Headers = LABELING_SPECIALIST,
) -> Row:
    return get_success_data(
        api.placement_transition(
            placement_id, f.action_payload("IMPLEMENT"), headers
        )
    )


def verify_placement(
    api: ChemicalComplianceApiClient,
    placement_id: str,
    headers: Headers = REGULATORY_COUNSEL,
) -> Row:
    return get_success_data(
        api.placement_transition(placement_id, f.action_payload("VERIFY"), headers)
    )


def make_implemented_placement(
    api: ChemicalComplianceApiClient,
    determination_id: str,
    channel: str = REQUIRED_CHANNEL_LABEL,
    effective_from: str = "2026-06-01T00:00:00Z",
    effective_to: Any = f.OMIT,
    **overrides: Any,
) -> Row:
    placement = add_placement(
        api, determination_id, channel, effective_from, effective_to, **overrides
    )
    return implement_placement(api, placement["id"])


# ─────────────────────────────────────────────────────────────────────────────
# Tier 3 — the whole warning chain in one call
# ─────────────────────────────────────────────────────────────────────────────


def build_warned_product(
    api: ChemicalComplianceApiClient,
    chemical_id: str,
    sku: str = "SKU-100",
    declared_concentration_ppm: float = 40.0,
    quantity_grams_per_unit: float = 0.25,
    contact_factor: float = 0.5,
    material_code: str = "RM-100",
    method: str = METHOD_MODELED,
    route: str = ROUTE_DERMAL,
    uses_per_day: float = 1.0,
    channel: str = REQUIRED_CHANNEL_LABEL,
    effective_from: str = "2026-06-01T00:00:00Z",
    effective_to: Any = f.OMIT,
    approve: bool = True,
    place: bool = True,
    implement: bool = True,
    product_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Supplier → material → link → disclosure → product → component →
    FINAL assessment → APPROVED determination → IMPLEMENTED placement.

    Returns every row created along the way so a test can reach into any hop.
    """
    base = make_product_with_component(
        api,
        chemical_id,
        sku=sku,
        declared_concentration_ppm=declared_concentration_ppm,
        quantity_grams_per_unit=quantity_grams_per_unit,
        contact_factor=contact_factor,
        material_code=material_code,
        product_overrides=product_overrides,
    )
    product_id = base["product"]["id"]
    assessment = make_final_assessment(
        api, product_id, chemical_id, method, route, uses_per_day
    )
    determination = make_determination(api, product_id, assessment["id"])
    if approve:
        determination = approve_determination(api, determination["id"])

    placement = None
    if place:
        placement = add_placement(
            api, determination["id"], channel, effective_from, effective_to
        )
        if implement:
            placement = implement_placement(api, placement["id"])

    base.update(
        {
            "assessment": assessment,
            "determination": determination,
            "placement": placement,
            "product": read_product(api, product_id),
        }
    )
    return base


# ─────────────────────────────────────────────────────────────────────────────
# Tier 4 — notices, the cure window and the money waterfall
# ─────────────────────────────────────────────────────────────────────────────


def make_notice(
    api: ChemicalComplianceApiClient,
    product_id: str,
    chemical_id: str,
    earliest_violation_date: str = "2026-06-01T00:00:00Z",
    served_at: str = "2026-07-01T00:00:00Z",
    alleged_units: int = 4000,
    headers: Headers = REGULATORY_COUNSEL,
    **overrides: Any,
) -> Row:
    return get_success_data(
        api.create_notice(
            f.notice_payload(
                product_id,
                chemical_id,
                earliest_violation_date,
                served_at,
                alleged_units=alleged_units,
                **overrides,
            ),
            headers,
        )
    )


def evaluate_notice(
    api: ChemicalComplianceApiClient,
    notice_id: str,
    headers: Headers = REGULATORY_COUNSEL,
) -> Row:
    return get_success_data(
        api.notice_transition(notice_id, f.action_payload("EVALUATE"), headers)
    )


def elect_cure(
    api: ChemicalComplianceApiClient,
    notice_id: str,
    headers: Headers = REGULATORY_COUNSEL,
) -> Row:
    return get_success_data(
        api.notice_transition(notice_id, f.action_payload("ELECT_CURE"), headers)
    )


def dismiss_notice(
    api: ChemicalComplianceApiClient,
    notice_id: str,
    headers: Headers = REGULATORY_COUNSEL,
) -> Row:
    return get_success_data(
        api.notice_transition(notice_id, f.dismiss_action(), headers)
    )


def escalate_notice_to_negotiation(
    api: ChemicalComplianceApiClient,
    notice_id: str,
    headers: Headers = REGULATORY_COUNSEL,
    evaluate_first: bool = True,
) -> Row:
    """Drive a notice to SETTLEMENT_NEGOTIATION so a settlement may be proposed."""
    if evaluate_first:
        evaluate_notice(api, notice_id, headers)
    return get_success_data(
        api.notice_transition(notice_id, f.action_payload("ESCALATE"), headers)
    )


def propose_settlement(
    api: ChemicalComplianceApiClient,
    notice_id: str,
    requested_attorney_fees_cents: int,
    reformulation_commitment: Any = f.OMIT,
    expected_notice_version: Optional[int] = None,
    headers: Headers = REGULATORY_COUNSEL,
) -> Row:
    """Propose a settlement, reading the notice's fresh version if none is given."""
    if expected_notice_version is None:
        expected_notice_version = api.notice_version(notice_id, headers)
    return get_success_data(
        api.create_settlement(
            notice_id,
            f.settlement_payload(
                requested_attorney_fees_cents,
                expected_notice_version,
                reformulation_commitment,
            ),
            headers,
        )
    )


def counter_settlement(
    api: ChemicalComplianceApiClient,
    settlement_id: str,
    requested_attorney_fees_cents: Any = f.OMIT,
    headers: Headers = REGULATORY_COUNSEL,
) -> Row:
    return get_success_data(
        api.settlement_transition(
            settlement_id,
            f.action_payload(
                "COUNTER",
                requested_attorney_fees_cents=requested_attorney_fees_cents,
            ),
            headers,
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tier 5 — terminal states
# ─────────────────────────────────────────────────────────────────────────────


def execute_settlement(
    api: ChemicalComplianceApiClient,
    settlement_id: str,
    executor: Headers = REGULATORY_COUNSEL_2,
) -> Row:
    """Execute a proposed settlement with an approver other than the proposer."""
    return get_success_data(
        api.settlement_transition(
            settlement_id, f.action_payload("ACCEPT_EXECUTE"), executor
        )
    )


def void_settlement(
    api: ChemicalComplianceApiClient,
    settlement_id: str,
    headers: Headers = REGULATORY_COUNSEL,
) -> Row:
    return get_success_data(
        api.settlement_transition(settlement_id, f.action_payload("VOID"), headers)
    )


def market_product(api: ChemicalComplianceApiClient, product_id: str) -> Row:
    return get_success_data(
        api.product_transition(product_id, f.action_payload("MARKET"), REGISTRY_ADMIN)
    )


def discontinue_product(api: ChemicalComplianceApiClient, product_id: str) -> Row:
    return get_success_data(
        api.product_transition(
            product_id, f.action_payload("DISCONTINUE"), REGISTRY_ADMIN
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tier 4 — reformulation projects
# ─────────────────────────────────────────────────────────────────────────────


def make_reformulation_project(
    api: ChemicalComplianceApiClient,
    product_id: str,
    chemical_id: str,
    material_chemical_id: str,
    target_concentration_ppm: float,
    planned_start_date: str = "2026-06-01T00:00:00Z",
    planned_end_date: str = "2026-07-01T00:00:00Z",
    headers: Headers = COMPLIANCE_ANALYST,
) -> Row:
    return get_success_data(
        api.create_reformulation_project(
            f.reformulation_payload(
                product_id,
                chemical_id,
                material_chemical_id,
                target_concentration_ppm,
                planned_start_date,
                planned_end_date,
            ),
            headers,
        )
    )


def submit_reformulation_verification(
    api: ChemicalComplianceApiClient,
    project_id: str,
    start_first: bool = True,
    headers: Headers = COMPLIANCE_ANALYST,
) -> Row:
    if start_first:
        get_success_data(
            api.reformulation_transition(
                project_id, f.action_payload("START"), headers
            )
        )
    return get_success_data(
        api.reformulation_transition(
            project_id, f.action_payload("SUBMIT_VERIFICATION"), headers
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# Pytest fixtures
#
# The server is relaunched before every test, so all of these are function
# scoped: nothing may leak from one test into the next.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def api() -> ChemicalComplianceApiClient:
    """A client pointed at the freshly started server for this test."""
    return ChemicalComplianceApiClient()


@pytest.fixture
def clock(api: ChemicalComplianceApiClient) -> str:
    """Pin the logical clock at the canonical instant and return it."""
    set_clock(api, DEFAULT_CLOCK)
    return DEFAULT_CLOCK


@pytest.fixture
def proposed_bpa(api: ChemicalComplianceApiClient, clock: str) -> Row:
    """Bisphenol A registered but still ``PROPOSED``."""
    return make_bpa(api, list_it=False)


@pytest.fixture
def listed_bpa(api: ChemicalComplianceApiClient, clock: str) -> Row:
    """Bisphenol A, ``LISTED``, MADL 0.5 ug/day."""
    return make_bpa(api)


@pytest.fixture
def listed_benzene(api: ChemicalComplianceApiClient, clock: str) -> Row:
    """Benzene, ``LISTED``, NSRL 6.4 ug/day."""
    return make_benzene(api)


@pytest.fixture
def both_listed_chemicals(api: ChemicalComplianceApiClient, clock: str) -> Dict[str, Row]:
    """Both canonical chemicals: one cancer, one reproductive."""
    return {"bpa": make_bpa(api), "benzene": make_benzene(api)}


@pytest.fixture
def supplier(api: ChemicalComplianceApiClient, clock: str) -> Row:
    """One supplier with no warranty terms at all."""
    return make_supplier(api)


@pytest.fixture
def verified_bpa_material(
    api: ChemicalComplianceApiClient, listed_bpa: Row
) -> Dict[str, Any]:
    """A supplier material declaring Bisphenol A at 40.0 ppm, disclosure VERIFIED."""
    bundle = make_supplied_material(api, listed_bpa["id"])
    bundle["chemical"] = listed_bpa
    return bundle


@pytest.fixture
def bpa_product(api: ChemicalComplianceApiClient, listed_bpa: Row) -> Dict[str, Any]:
    """A product with one ACTIVE component of a 40.0 ppm Bisphenol A material.

    0.25 g of a 40.0 ppm material puts 10.000 ug of the chemical in the product.
    """
    bundle = make_product_with_component(api, listed_bpa["id"])
    bundle["chemical"] = listed_bpa
    return bundle


@pytest.fixture
def warned_bpa_product(
    api: ChemicalComplianceApiClient, listed_bpa: Row
) -> Dict[str, Any]:
    """The whole chain: FINAL assessment, APPROVED determination, IMPLEMENTED LABEL."""
    bundle = build_warned_product(api, listed_bpa["id"])
    bundle["chemical"] = listed_bpa
    return bundle
