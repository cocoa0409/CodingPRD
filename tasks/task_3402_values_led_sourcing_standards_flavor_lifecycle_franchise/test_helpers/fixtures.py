"""Composite setup helpers (PRD §3 workflows).

Every fixture builds its preconditions from scratch via PRD-declared endpoints;
the harness restarts the server before each test, so nothing carries over.
Fixtures use get_success_data (lenient) so setup failures surface clearly.
"""
import uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_audit_payload,
    create_campaign_payload,
    create_certification_payload,
    create_commitment_payload,
    create_enrollment_payload,
    create_flavor_payload,
    create_premium_payment_payload,
    create_revival_request_payload,
    create_scoop_shop_payload,
    create_supplier_payload,
    create_supply_order_payload,
    create_production_slot_payload,
)
from .test_users import (
    TEST_USERS,
    make_audit_verifier_headers,
    make_fan_headers,
    make_independent_board_member_headers,
    make_shop_operator_headers,
    make_sustainability_auditor_headers,
)

SM = TEST_USERS["sourcing_manager_headers"]
DPM = TEST_USERS["dairy_program_manager_headers"]
FM = TEST_USERS["flavor_manager_headers"]
PS = TEST_USERS["plant_scheduler_headers"]
POC = TEST_USERS["parent_ops_controller_headers"]
FA = TEST_USERS["franchise_admin_headers"]
FAN = TEST_USERS["fan_headers"]


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Suppliers / audits (PRD §3.1, §3.2)
# ---------------------------------------------------------------------------

def make_supplier(name=None, category="DAIRY", country_code="US") -> dict:
    """Create a supplier in PROSPECT."""
    payload = create_supplier_payload(
        **({"name": name} if name else {}),
        ingredient_category=category,
        country_code=country_code,
    )
    return get_success_data(api_client.create_supplier(payload, SM))


def run_audit(supplier_id, labor=80, environment=70, community=60, findings=0,
              auditor_id=None, verifier_id=None, scheduled_for=None) -> dict:
    """Schedule -> start -> complete -> verify an audit; returns the VERIFIED audit.

    Default scores 80/70/60 with 0 findings give composite 71 and outcome PASS.
    """
    auditor_id = auditor_id or _uid("aud")
    verifier_id = verifier_id or _uid("ver")
    payload = create_audit_payload(
        **({"scheduled_for": scheduled_for} if scheduled_for else {})
    )
    audit = get_success_data(api_client.create_audit(supplier_id, payload, SM))
    get_success_data(api_client.start_audit(
        audit["id"], make_sustainability_auditor_headers(auditor_id)))
    completed = get_success_data(api_client.complete_audit(
        audit["id"],
        {"labor_score": labor, "environment_score": environment,
         "community_score": community, "findings_count": findings},
        make_sustainability_auditor_headers(auditor_id)))
    verified = get_success_data(api_client.verify_audit(
        audit["id"], make_audit_verifier_headers(verifier_id)))
    return verified


def create_approved_supplier(name=None, category="DAIRY", country_code="US") -> dict:
    """Supplier driven PROSPECT -> APPROVED by a PASS audit (composite 71)."""
    supplier = make_supplier(name=name, category=category, country_code=country_code)
    run_audit(supplier["id"])
    return get_success_data(api_client.get_supplier(supplier["id"], SM))


def fail_supplier_audit(supplier_id, labor=50, environment=50, community=50,
                        findings=5) -> dict:
    """Run a FAIL audit to completion+verification against an existing supplier."""
    return run_audit(supplier_id, labor=labor, environment=environment,
                     community=community, findings=findings)


def get_supplier_version(supplier_id) -> int:
    return get_success_data(api_client.get_supplier(supplier_id, SM))["version"]


def make_commitment(supplier_id, category="DAIRY", **overrides) -> dict:
    """Create a commitment with a fresh OCC version capture."""
    version = get_supplier_version(supplier_id)
    payload = create_commitment_payload(version, ingredient_category=category, **overrides)
    return get_success_data(api_client.create_commitment(supplier_id, payload, SM))


def make_certification(supplier_id, scheme="FAIR_TRADE", scope="DAIRY", declared=95,
                       issued_at=None, valid_until=None, certificate_number=None) -> dict:
    """Register a certification (lands PENDING)."""
    overrides = {}
    if issued_at:
        overrides["issued_at"] = issued_at
    if valid_until:
        overrides["valid_until"] = valid_until
    if certificate_number:
        overrides["certificate_number"] = certificate_number
    payload = create_certification_payload(
        scheme=scheme, ingredient_scope=scope, declared_coverage_pct=declared, **overrides)
    return get_success_data(api_client.create_certification(supplier_id, payload, SM))


def verify_certification(cert_id, verified_pct, verifier_id=None) -> dict:
    verifier_id = verifier_id or _uid("ver")
    return get_success_data(api_client.verify_certification(
        cert_id, {"verified_coverage_pct": verified_pct},
        make_audit_verifier_headers(verifier_id)))


def make_verified_certification(supplier_id, scheme="FAIR_TRADE", scope="DAIRY",
                                declared=95, verified=95, **kw) -> dict:
    cert = make_certification(supplier_id, scheme=scheme, scope=scope,
                              declared=declared, **kw)
    return verify_certification(cert["id"], verified)


# ---------------------------------------------------------------------------
# Flavors / claims / revival (PRD §3.4, §3.5, §3.6)
# ---------------------------------------------------------------------------

def make_flavor(name=None, base_type="DAIRY", chunk_load_pct=5, swirl_load_pct=5,
                pint_price_cents=150) -> dict:
    """Create a flavor in DEVELOPMENT."""
    payload = create_flavor_payload(
        **({"name": name} if name else {}),
        base_type=base_type, chunk_load_pct=chunk_load_pct,
        swirl_load_pct=swirl_load_pct, pint_price_cents=pint_price_cents,
    )
    return get_success_data(api_client.create_flavor(payload, FM))


def promote_flavor_to(flavor_id, target_state) -> dict:
    """Walk DEVELOPMENT -> ... -> target_state one step at a time (PRD §3.4)."""
    chain = ["DEVELOPMENT", "TEST_BATCH", "LIMITED_RUN", "CORE_LINE"]
    current = get_success_data(api_client.get_flavor(flavor_id, FM))["status"]
    flavor = None
    while current != target_state:
        nxt = chain[chain.index(current) + 1]
        flavor = get_success_data(api_client.promote_flavor(
            flavor_id, {"target_state": nxt}, FM))
        current = flavor["status"]
    return flavor if flavor is not None else get_success_data(
        api_client.get_flavor(flavor_id, FM))


def make_flavor_in_state(target_state, **kw) -> dict:
    flavor = make_flavor(**kw)
    if target_state == "DEVELOPMENT":
        return flavor
    return promote_flavor_to(flavor["id"], target_state)


def make_limited_run_flavor(**kw) -> dict:
    return make_flavor_in_state("LIMITED_RUN", **kw)


def make_core_line_flavor(**kw) -> dict:
    return make_flavor_in_state("CORE_LINE", **kw)


def make_retired_flavor(**kw) -> dict:
    """LIMITED_RUN flavor retired by the parent (retired_at = logical clock)."""
    flavor = make_limited_run_flavor(**kw)
    return get_success_data(api_client.retire_flavor(flavor["id"], POC))


def get_flavor_version(flavor_id) -> int:
    return get_success_data(api_client.get_flavor(flavor_id, FM))["version"]


def substantiate_claim(flavor_id, cert_ids, claim_type="FAIR_TRADE_SOURCING") -> dict:
    """Substantiate with a fresh OCC version capture."""
    version = get_flavor_version(flavor_id)
    return get_success_data(api_client.substantiate_claim(
        flavor_id,
        {"claim_type": claim_type, "certification_ids": cert_ids,
         "expected_flavor_version": version},
        FM))


def make_published_claim_flavor(cert_ids, claim_type="FAIR_TRADE_SOURCING", **kw) -> dict:
    """LIMITED_RUN flavor whose claim is substantiated then published."""
    flavor = make_limited_run_flavor(**kw)
    substantiate_claim(flavor["id"], cert_ids, claim_type=claim_type)
    return get_success_data(api_client.publish_claim(flavor["id"], FM))


def make_revival_request(flavor_id, fan_email=None, title=None) -> dict:
    overrides = {}
    if fan_email:
        overrides["fan_email"] = fan_email
    if title:
        overrides["title"] = title
    return get_success_data(api_client.create_revival_request(
        flavor_id, create_revival_request_payload(**overrides), FAN))


def sign_revival(request_id, fan_email, count) -> dict:
    return get_success_data(api_client.sign_revival_request(
        request_id, {"fan_email": fan_email, "count": count}, FAN))


def make_qualified_revival(flavor_id) -> dict:
    """OPEN request signed to exactly the 500-signature threshold."""
    request = make_revival_request(flavor_id)
    return sign_revival(request["id"], f"qualify-{uuid.uuid4().hex[:8]}@example.com", 500)


# ---------------------------------------------------------------------------
# Dairy farm program (PRD §3.3)
# ---------------------------------------------------------------------------

def make_enrollment(baseline_volume_liters=8000, **overrides) -> dict:
    payload = create_enrollment_payload(
        baseline_volume_liters=baseline_volume_liters, **overrides)
    return get_success_data(api_client.create_enrollment(payload, DPM))


def assess_enrollment(enrollment_id, env_score, welfare_score) -> dict:
    return get_success_data(api_client.assess_enrollment(
        enrollment_id,
        {"env_practice_score": env_score, "welfare_practice_score": welfare_score},
        DPM))


def make_assessed_enrollment(env_score=80, welfare_score=70,
                             baseline_volume_liters=8000, **kw) -> dict:
    """Default env 80 / welfare 70 -> blended 75 (tier 8%)."""
    enrollment = make_enrollment(baseline_volume_liters=baseline_volume_liters, **kw)
    return assess_enrollment(enrollment["id"], env_score, welfare_score)


def make_payment(enrollment_id, period="Q1", declared_volume_liters=10000,
                 commodity_price_cents_per_liter=45) -> dict:
    """Create a payment (CALCULATED, PROVISIONAL variant)."""
    payload = create_premium_payment_payload(
        period=period, declared_volume_liters=declared_volume_liters,
        commodity_price_cents_per_liter=commodity_price_cents_per_liter)
    return get_success_data(api_client.create_premium_payment(
        enrollment_id, payload, DPM))


def finalize_payment(payment_id, metered_volume_liters, non_conformance_count) -> dict:
    return get_success_data(api_client.finalize_payment(
        payment_id,
        {"metered_volume_liters": metered_volume_liters,
         "non_conformance_count": non_conformance_count},
        DPM))


def make_final_payment(enrollment_id, metered_volume_liters, non_conformance_count=0,
                       **kw) -> dict:
    payment = make_payment(enrollment_id, **kw)
    return finalize_payment(payment["id"], metered_volume_liters, non_conformance_count)


def make_approved_payment(enrollment_id, metered_volume_liters,
                          non_conformance_count=0, **kw) -> dict:
    payment = make_final_payment(
        enrollment_id, metered_volume_liters, non_conformance_count, **kw)
    return get_success_data(api_client.approve_payment(payment["id"], DPM))


# ---------------------------------------------------------------------------
# Scoop shops and supply orders (PRD §3.8)
# ---------------------------------------------------------------------------

def make_shop(operator_type="FRANCHISEE", credit_limit_cents=10_000_000,
              nonprofit_verified=None, **overrides) -> dict:
    """Create a shop application (SITE_REVIEW)."""
    if nonprofit_verified is not None:
        overrides["nonprofit_verified"] = nonprofit_verified
    payload = create_scoop_shop_payload(
        operator_type=operator_type, credit_limit_cents=credit_limit_cents, **overrides)
    return get_success_data(api_client.create_scoop_shop(payload, FA))


def make_site_approved_shop(**kw) -> dict:
    shop = make_shop(**kw)
    return get_success_data(api_client.approve_site(shop["id"], FA))


def make_operating_shop(**kw) -> dict:
    """SITE_REVIEW -> SITE_APPROVED -> OPERATING. Partner shops default verified."""
    if kw.get("operator_type") == "NONPROFIT_PARTNER" and "nonprofit_verified" not in kw:
        kw["nonprofit_verified"] = True
    shop = make_site_approved_shop(**kw)
    return get_success_data(api_client.open_shop(shop["id"], FA))


def make_supply_order(shop_id, lines, production_date="2026-10-05") -> dict:
    """Place an order as the shop's own operator (ownership-threaded)."""
    payload = create_supply_order_payload(lines, production_date=production_date)
    return get_success_data(api_client.create_supply_order(
        shop_id, payload, make_shop_operator_headers(shop_id)))


def make_confirmed_order(shop_id, lines, production_date="2026-10-05") -> dict:
    order = make_supply_order(shop_id, lines, production_date=production_date)
    return get_success_data(api_client.confirm_supply_order(order["id"], FA))


def make_allocated_order(shop_id, lines, plant_code="VT_ST_ALBANS",
                         production_date="2026-10-05") -> dict:
    order = make_confirmed_order(shop_id, lines, production_date=production_date)
    return get_success_data(api_client.allocate_supply_order(
        order["id"], {"plant_code": plant_code}, PS))


# ---------------------------------------------------------------------------
# Campaigns (PRD §3.7)
# ---------------------------------------------------------------------------

def make_campaign(impact="NONE", issue_area="CLIMATE", proposer_id=None, title=None) -> dict:
    proposer_id = proposer_id or _uid("board")
    overrides = {"issue_area": issue_area, "retail_partner_impact": impact}
    if title:
        overrides["title"] = title
    return get_success_data(api_client.create_campaign(
        create_campaign_payload(**overrides),
        make_independent_board_member_headers(proposer_id)))


def decide_campaign(campaign_id, approve, decider_id=None) -> dict:
    decider_id = decider_id or _uid("board")
    return get_success_data(api_client.board_decision(
        campaign_id, {"approve": approve},
        make_independent_board_member_headers(decider_id)))


def make_approved_campaign(impact="NONE", **kw) -> dict:
    campaign = make_campaign(impact=impact, **kw)
    return decide_campaign(campaign["id"], True)


def make_scheduled_campaign(impact="NONE", **kw) -> dict:
    campaign = make_approved_campaign(impact=impact, **kw)
    return get_success_data(api_client.schedule_ops(campaign["id"], POC))


def make_launched_campaign(impact="NONE", **kw) -> dict:
    campaign = make_scheduled_campaign(impact=impact, **kw)
    if impact != "NONE":
        get_success_data(api_client.dispatch_retail_notices(campaign["id"], POC))
    return get_success_data(api_client.launch_campaign(campaign["id"], POC))
