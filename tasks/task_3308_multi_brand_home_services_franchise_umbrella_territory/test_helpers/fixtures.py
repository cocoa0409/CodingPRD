"""Composite setup helpers.

Every fixture builds its preconditions from scratch through PRD-declared
endpoints; the runner restarts the server before each test, so nothing carries
over. Setup calls use the lenient get_success_data() so that a broken setup
surfaces as a clear "Setup failed" message rather than a confusing assertion.

Identity threading: FranchiseeOperator is entity_backed by Franchisee, so every
ownership-gated call in this module passes make_franchisee_operator_headers(<the
acting Franchisee.id>) rather than the shared constant.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .test_users import TEST_USERS, make_franchisee_operator_headers

ADMIN = TEST_USERS["franchise_admin_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]

_counter = itertools.count(1)

BRAND_MS = {
    "brand_code": "MSP",
    "display_name": "Mosaic Plumbing",
    "trade": "PLUMBING",
    "royalty_rate": 0.06,
    "national_ad_fund_rate": 0.01,
    "min_certification_level": "APPRENTICE",
    "audit_cycle_months": 12,
    "cross_brand_fee_table": {},
}

BRAND_IL = {
    "brand_code": "ILE",
    "display_name": "Illume Electric",
    "trade": "ELECTRICAL",
    "royalty_rate": 0.06,
    "national_ad_fund_rate": 0.01,
    "min_certification_level": "JOURNEYMAN",
    "audit_cycle_months": 12,
    # Tiered table: a receiving IL referral originating from brand MS settles
    # at 0.15 rather than the referral's own referral_fee_rate.
    "cross_brand_fee_table": {"MSP": {"rate": 0.15}},
}

BRAND_RV = {
    "brand_code": "RVR",
    "display_name": "Revive Restoration",
    "trade": "RESTORATION",
    "royalty_rate": 0.07,
    "national_ad_fund_rate": 0.015,
    "min_certification_level": "MASTER",
    "audit_cycle_months": 6,
    "cross_brand_fee_table": {},
}


def _unique(prefix):
    return f"{prefix}-{next(_counter):04d}"


# --------------------------------------------------------------------------
# clock
# --------------------------------------------------------------------------

def set_clock(iso8601=TEST_DEFAULTS["CLOCK_START"]):
    resp = api_client.set_clock(iso8601, ADMIN)
    assert resp.status_code == 200, (
        f"Setup failed: set_clock -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def run_sweep():
    resp = api_client.run_sweep(ADMIN)
    assert resp.status_code == 200, (
        f"Setup failed: run_sweep -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


# --------------------------------------------------------------------------
# portfolio primitives
# --------------------------------------------------------------------------

def create_brand(profile=None, **overrides):
    payload = dict(profile or BRAND_MS)
    payload.update(overrides)
    payload.setdefault("brand_code", _unique("BR"))
    resp = api_client.create_brand(payload, ADMIN)
    assert resp.status_code == 201, (
        f"Setup failed: create_brand -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def create_franchisee(**overrides):
    payload = {
        "legal_name": "Mosaic Central LLC",
        "principal_name": "Dana Vaughn",
        "entity_type": "LLC",
        "shared_services_enrolled": True,
    }
    payload.update(overrides)
    resp = api_client.create_franchisee(payload, ADMIN)
    assert resp.status_code == 201, (
        f"Setup failed: create_franchisee -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def create_territory(brand_id, franchisee_id=None, **overrides):
    payload = {
        "territory_code": _unique("T"),
        "brand_id": brand_id,
        "household_count": TEST_DEFAULTS["HOUSEHOLD_COUNT"],
        "postal_codes": [_unique("P")],
        "expansion_right_households": TEST_DEFAULTS["EXPANSION_RIGHT_HOUSEHOLDS"],
        "protected": True,
    }
    if franchisee_id is not None:
        payload["franchisee_id"] = franchisee_id
    payload.update(overrides)
    resp = api_client.create_territory(payload, ADMIN)
    assert resp.status_code == 201, (
        f"Setup failed: create_territory -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def create_agreement(franchisee_id, brand_id, territory_id, **overrides):
    payload = {
        "agreement_number": _unique("A"),
        "franchisee_id": franchisee_id,
        "brand_id": brand_id,
        "territory_id": territory_id,
        "signed_on": TEST_DEFAULTS["SIGNED_ON"],
        "initial_term_months": TEST_DEFAULTS["TERM_MONTHS"],
        "certification_level": "JOURNEYMAN",
    }
    payload.update(overrides)
    resp = api_client.create_agreement(payload, ADMIN)
    assert resp.status_code == 201, (
        f"Setup failed: create_agreement -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


# --------------------------------------------------------------------------
# version readers (the OCC guards are fed the *current* stored version)
# --------------------------------------------------------------------------

def territory_version(territory_id):
    resp = api_client.get_territory(territory_id, ADMIN)
    assert resp.status_code == 200, (
        f"Setup failed: get_territory -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)["version"]


def agreement_version(agreement_id):
    resp = api_client.get_agreement(agreement_id, ADMIN)
    assert resp.status_code == 200, (
        f"Setup failed: get_agreement -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)["version"]


def franchisee_version(franchisee_id):
    resp = api_client.get_franchisee(franchisee_id, ADMIN)
    assert resp.status_code == 200, (
        f"Setup failed: get_franchisee -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)["version"]


def get_franchisee(franchisee_id):
    resp = api_client.get_franchisee(franchisee_id, ADMIN)
    assert resp.status_code == 200, (
        f"Setup failed: get_franchisee -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def get_agreement(agreement_id):
    resp = api_client.get_agreement(agreement_id, ADMIN)
    assert resp.status_code == 200, (
        f"Setup failed: get_agreement -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def get_territory(territory_id):
    resp = api_client.get_territory(territory_id, ADMIN)
    assert resp.status_code == 200, (
        f"Setup failed: get_territory -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def get_work_order(work_order_id):
    resp = api_client.get_work_order(work_order_id, ADMIN)
    assert resp.status_code == 200, (
        f"Setup failed: get_work_order -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def get_referral(referral_id):
    resp = api_client.get_referral(referral_id, ADMIN)
    assert resp.status_code == 200, (
        f"Setup failed: get_referral -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def get_lead(lead_id):
    resp = api_client.get_lead(lead_id, ADMIN)
    assert resp.status_code == 200, (
        f"Setup failed: get_lead -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def get_audit(audit_id):
    resp = api_client.get_audit(audit_id, ADMIN)
    assert resp.status_code == 200, (
        f"Setup failed: get_audit -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def get_national_account(account_id):
    resp = api_client.get_national_account(account_id, ADMIN)
    assert resp.status_code == 200, (
        f"Setup failed: get_national_account -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def get_statement(statement_id):
    resp = api_client.get_statement(statement_id, ADMIN)
    assert resp.status_code == 200, (
        f"Setup failed: get_statement -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def get_transfer_application(application_id):
    resp = api_client.get_transfer_application(application_id, ADMIN)
    assert resp.status_code == 200, (
        f"Setup failed: get_transfer_application -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


# --------------------------------------------------------------------------
# territory / agreement lifecycle
# --------------------------------------------------------------------------

def offer_territory(territory_id, franchisee_id):
    resp = api_client.offer_territory(territory_id, franchisee_id, ADMIN)
    assert resp.status_code == 200, (
        f"Setup failed: offer_territory -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def award_territory(territory_id, expected_version=None):
    version = territory_version(territory_id) if expected_version is None else expected_version
    resp = api_client.award_territory(territory_id, version, ADMIN)
    assert resp.status_code == 200, (
        f"Setup failed: award_territory -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def offer_agreement(agreement_id):
    resp = api_client.offer_agreement(agreement_id, ADMIN)
    assert resp.status_code == 200, (
        f"Setup failed: offer_agreement -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def activate_agreement(agreement_id):
    resp = api_client.activate_agreement(agreement_id, ADMIN)
    assert resp.status_code == 200, (
        f"Setup failed: activate_agreement -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def offer_award_activate(territory_id, agreement_id, franchisee_id):
    """Offer the agreement, then offer + award the territory, then activate.

    PRD 2.5 rung 8 / §229: the award requires a matching agreement already
    OFFERED or ACTIVE for the territory, so the agreement offer must precede
    the award.
    """
    offer_agreement(agreement_id)
    offer_territory(territory_id, franchisee_id)
    award_territory(territory_id)
    return activate_agreement(agreement_id)


def setup_active_agreement(brand=None, franchisee=None, territory=None,
                           agreement=None, clock=TEST_DEFAULTS["CLOCK_START"],
                           activate=True):
    """Brand + Franchisee + Territory + Agreement, walked to Territory ACTIVE.

    Returns (brand, franchisee, territory, agreement). Pass activate=False to
    stop after the territory is awarded and the agreement is OFFERED.
    """
    set_clock(clock)
    if brand is None:
        brand = create_brand(profile=BRAND_MS)
    elif "id" not in brand:
        # a profile dict — materialize it
        brand = create_brand(profile=brand)
    franchisee = create_franchisee(**(franchisee or {}))
    territory = create_territory(
        brand["id"], franchisee_id=franchisee["id"], **(territory or {}),
    )
    agreement = create_agreement(
        franchisee["id"], brand["id"], territory["id"], **(agreement or {}),
    )
    offer_agreement(agreement["id"])
    offer_territory(territory["id"], franchisee["id"])
    award_territory(territory["id"])
    if activate:
        agreement = activate_agreement(agreement["id"])
        territory = get_territory(territory["id"])
        franchisee = get_franchisee(franchisee["id"])
    return brand, franchisee, territory, agreement


# --------------------------------------------------------------------------
# two-brand referral scenario
# --------------------------------------------------------------------------

def setup_two_brand_pair(clock=TEST_DEFAULTS["CLOCK_START"], il_table=True,
                         ms_agreement=None, il_agreement=None,
                         ms_franchisee=None, il_franchisee=None):
    """MS (originating) and IL (receiving) brands, each with its own franchisee,
    territory and ACTIVE agreement.

    Returns a dict with ms_brand, il_brand, fr_ms, fr_il, ter_ms, ter_il,
    agt_a1 (MS) and agt_a2 (IL).
    """
    set_clock(clock)
    ms_brand = create_brand(profile=BRAND_MS)
    il_profile = dict(BRAND_IL)
    if not il_table:
        il_profile["cross_brand_fee_table"] = {}
    il_brand = create_brand(profile=il_profile)

    fr_ms = create_franchisee(**(ms_franchisee or {}))
    fr_il = create_franchisee(
        legal_name="Illume Metro Corp", principal_name="Ruben Salas",
        entity_type="CORPORATION", shared_services_enrolled=True,
        **(il_franchisee or {}),
    )

    ter_ms = create_territory(ms_brand["id"], franchisee_id=fr_ms["id"])
    ter_il = create_territory(il_brand["id"], franchisee_id=fr_il["id"])

    agt_a1 = create_agreement(
        fr_ms["id"], ms_brand["id"], ter_ms["id"], **(ms_agreement or {}),
    )
    agt_a2 = create_agreement(
        fr_il["id"], il_brand["id"], ter_il["id"], certification_level="MASTER",
        **(il_agreement or {}),
    )

    # PRD 2.5 rung 8 / §219: the award requires a matching agreement already
    # OFFERED or ACTIVE for the territory, so the agreements are offered before
    # the award rather than after it.
    offer_agreement(agt_a1["id"])
    offer_agreement(agt_a2["id"])
    offer_territory(ter_ms["id"], fr_ms["id"])
    award_territory(ter_ms["id"])
    offer_territory(ter_il["id"], fr_il["id"])
    award_territory(ter_il["id"])
    agt_a1 = activate_agreement(agt_a1["id"])
    agt_a2 = activate_agreement(agt_a2["id"])

    return {
        "ms_brand": ms_brand,
        "il_brand": il_brand,
        "fr_ms": fr_ms,
        "fr_il": fr_il,
        "ter_ms": ter_ms,
        "ter_il": ter_il,
        "agt_a1": agt_a1,
        "agt_a2": agt_a2,
    }


def create_referral(originating_agreement_id, receiving_agreement_id,
                    originating_franchisee_id, **overrides):
    payload = {
        "referral_code": _unique("R"),
        "originating_agreement_id": originating_agreement_id,
        "receiving_agreement_id": receiving_agreement_id,
        "customer_household_ref": "HH-9001",
        "job_description": "Panel upgrade surfaced during a drain cleaning visit",
        "estimated_job_value_cents": 120000,
        "referral_fee_rate": 0.10,
    }
    payload.update(overrides)
    resp = api_client.create_referral(
        payload, make_franchisee_operator_headers(originating_franchisee_id),
    )
    assert resp.status_code == 201, (
        f"Setup failed: create_referral -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def accept_referral(referral_id, receiving_franchisee_id):
    resp = api_client.accept_referral(
        referral_id, make_franchisee_operator_headers(receiving_franchisee_id),
    )
    assert resp.status_code == 200, (
        f"Setup failed: accept_referral -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def complete_referral(referral_id, receiving_franchisee_id, settled_job_value_cents):
    resp = api_client.complete_referral(
        referral_id, settled_job_value_cents,
        make_franchisee_operator_headers(receiving_franchisee_id),
    )
    assert resp.status_code == 200, (
        f"Setup failed: complete_referral -> {resp.status_code} {resp.text}"
    )
    referral = get_success_data(resp)
    # PRD 3.5: completion spins off the performing work order (source
    # CROSS_BRAND_REFERRAL, bound to this referral). PRD 3.4 allows an explicit
    # breach only from IN_PROGRESS, so the synthesized order is walked through
    # dispatch and start here rather than being left CREATED.
    page = api_client.list_work_orders(ADMIN, {"referral_id": referral_id}).json()
    for work_order in page.get("data") or []:
        if work_order.get("referral_id") == referral_id:
            _walk_to_in_progress(work_order["id"], receiving_franchisee_id)
            break
    return referral


def _walk_to_in_progress(work_order_id, performing_franchisee_id):
    """Drive a CREATED work order through dispatch and start (PRD 3.4)."""
    dispatch_work_order(work_order_id, performing_franchisee_id)
    return start_work_order(work_order_id, performing_franchisee_id)


def settle_referral(referral_id, originating_agreement_id, expected_version=None):
    """Settle a referral as FranchiseAdmin.

    PRD 2.12: settlement carries `expected_agreement_version`, the originating
    agreement's last observed version. Callers that name the originating
    agreement pass its id and the helper observes the version itself; callers
    that want to exercise a stale view pass `expected_version` explicitly.
    """
    version = agreement_version(originating_agreement_id) \
        if expected_version is None else expected_version
    resp = api_client.settle_referral(referral_id, version, ADMIN)
    assert resp.status_code == 200, (
        f"Setup failed: settle_referral -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def setup_completed_referral(settled_job_value_cents=120000, **pair_overrides):
    """Two-brand pair + referral accepted and completed by the receiving side.

    Returns (ctx, referral).
    """
    ctx = setup_two_brand_pair(**pair_overrides)
    referral = create_referral(
        ctx["agt_a1"]["id"], ctx["agt_a2"]["id"], ctx["fr_ms"]["id"],
    )
    accept_referral(referral["id"], ctx["fr_il"]["id"])
    referral = complete_referral(
        referral["id"], ctx["fr_il"]["id"], settled_job_value_cents,
    )
    return ctx, referral


def setup_settled_referral(settled_job_value_cents=120000, **pair_overrides):
    """Two-brand pair + referral settled by a FranchiseAdmin.

    Returns (ctx, referral). The IL brand carries the MS tier entry, so the
    settlement resolves the tiered brand-pair variant.
    """
    ctx, referral = setup_completed_referral(settled_job_value_cents, **pair_overrides)
    referral = settle_referral(referral["id"], ctx["agt_a1"]["id"])
    return ctx, referral


# --------------------------------------------------------------------------
# national accounts and work orders
# --------------------------------------------------------------------------

def create_national_account(**overrides):
    payload = {
        "account_name": "Northline Property Group",
        "account_type": "PROPERTY_MANAGER",
        "contracted_brands": [],
        "service_level_hours": 8,
        "sla_credit_per_breach_cents": 7500,
        "breach_tolerance": 2,
        "annual_commitment_cents": 25000000,
    }
    payload.update(overrides)
    resp = api_client.create_national_account(payload, ADMIN)
    assert resp.status_code == 201, (
        f"Setup failed: create_national_account -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def create_work_order(agreement_id, **overrides):
    payload = {
        "agreement_id": agreement_id,
        "source": "DIRECT",
        "priority": "STANDARD",
        "service_level_hours": 4,
    }
    payload.update(overrides)
    resp = api_client.create_work_order(payload, ADMIN)
    assert resp.status_code == 201, (
        f"Setup failed: create_work_order -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def _operator_headers(performing_franchisee_id):
    """Accept either a Franchisee id or an already-built header dict.

    FranchiseeOperator is entity_backed by Franchisee, so ownership-gated setup
    calls must send the acting Franchisee's id. Most callers pass the id
    directly; the few that build per-role headers themselves hand in the dict.
    Passing an id is the canonical form.
    """
    if isinstance(performing_franchisee_id, dict):
        return performing_franchisee_id
    return make_franchisee_operator_headers(performing_franchisee_id)


def dispatch_work_order(work_order_id, performing_franchisee_id):
    resp = api_client.dispatch_work_order(
        work_order_id, _operator_headers(performing_franchisee_id),
    )
    assert resp.status_code == 200, (
        f"Setup failed: dispatch_work_order -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def start_work_order(work_order_id, performing_franchisee_id):
    resp = api_client.start_work_order(
        work_order_id, _operator_headers(performing_franchisee_id),
    )
    assert resp.status_code == 200, (
        f"Setup failed: start_work_order -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def complete_work_order(work_order_id, performing_franchisee_id):
    resp = api_client.complete_work_order(
        work_order_id, _operator_headers(performing_franchisee_id),
    )
    assert resp.status_code == 200, (
        f"Setup failed: complete_work_order -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def dispatch_and_start(work_order_id, performing_franchisee_id):
    dispatch_work_order(work_order_id, performing_franchisee_id)
    return start_work_order(work_order_id, performing_franchisee_id)


def setup_in_progress_work_order(brand=None, agreement=None, work_order=None,
                                 clock=TEST_DEFAULTS["CLOCK_START"]):
    """Active agreement + a work order walked to IN_PROGRESS.

    Returns (brand, franchisee, territory, agreement, work_order).
    """
    brand, franchisee, territory, agreement = setup_active_agreement(
        brand=brand, agreement=agreement, clock=clock,
    )
    work_order = create_work_order(agreement["id"], **(work_order or {}))
    dispatch_and_start(work_order["id"], franchisee["id"])
    work_order = get_work_order(work_order["id"])
    return brand, franchisee, territory, agreement, work_order


# --------------------------------------------------------------------------
# brand standards audits and remediation
# --------------------------------------------------------------------------

def create_audit(agreement_id, **overrides):
    payload = {
        "agreement_id": agreement_id,
        "audit_kind": "MYSTERY_SHOP",
        "conducted_iso": TEST_DEFAULTS["SIGNED_ON"],
        "raw_score": 80.0,
        "findings_count": 4,
        "auditor_operator_id": TEST_DEFAULTS["AUDITOR_OPERATOR"],
        "critical_findings_count": 1,
    }
    payload.update(overrides)
    resp = api_client.create_audit(payload, ADMIN)
    assert resp.status_code == 201, (
        f"Setup failed: create_audit -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def conduct_audit(audit_id):
    resp = api_client.conduct_audit(audit_id, ADMIN)
    assert resp.status_code == 200, (
        f"Setup failed: conduct_audit -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def publish_audit(audit_id, agreement_id, expected_version=None):
    version = agreement_version(agreement_id) if expected_version is None else expected_version
    resp = api_client.publish_audit(audit_id, version, ADMIN)
    assert resp.status_code == 200, (
        f"Setup failed: publish_audit -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def remediation_action(audit_id, action, **overrides):
    payload = {"action": action}
    payload.update(overrides)
    resp = api_client.remediation_transition(audit_id, payload, ADMIN)
    assert resp.status_code == 200, (
        f"Setup failed: remediation action {action} -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def setup_published_failing_audit(brand=None, agreement=None,
                                  clock=TEST_DEFAULTS["CLOCK_START"]):
    """Active agreement + a published MYSTERY_SHOP audit scoring 56.5 (FAIL).

    Publishing a failing audit leaves the remediation OPEN and the agreement's
    standards_status at REMEDIATION_REQUIRED.

    Returns (brand, franchisee, territory, agreement, audit).
    """
    brand, franchisee, territory, agreement = setup_active_agreement(
        brand=brand, agreement=agreement, clock=clock,
    )
    audit = create_audit(agreement["id"])
    audit = conduct_audit(audit["id"])
    audit = publish_audit(audit["id"], agreement["id"])
    return brand, franchisee, territory, get_agreement(agreement["id"]), audit


# --------------------------------------------------------------------------
# leads
# --------------------------------------------------------------------------

def create_lead(brand_id, **overrides):
    payload = {
        "brand_id": brand_id,
        "source": "CALL_CENTER",
        "household_income_band": "BAND_2",
        "estimated_value_cents": 120000,
    }
    payload.update(overrides)
    resp = api_client.create_lead(payload, ADMIN)
    assert resp.status_code == 201, (
        f"Setup failed: create_lead -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def allocate_lead(lead_id, franchisee_id, allocated_agreement_id=None,
                  expected_version=None):
    version = franchisee_version(franchisee_id) \
        if expected_version is None else expected_version
    resp = api_client.allocate_lead(
        lead_id, version, ADMIN, allocated_agreement_id=allocated_agreement_id,
    )
    assert resp.status_code == 200, (
        f"Setup failed: allocate_lead -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


# --------------------------------------------------------------------------
# royalty statements
# --------------------------------------------------------------------------

def create_statement(agreement_id, **overrides):
    payload = {
        "agreement_id": agreement_id,
        "period_start": TEST_DEFAULTS["PERIOD_START"],
        "period_end": TEST_DEFAULTS["PERIOD_END"],
        "gross_revenue_cents": 1000000,
    }
    payload.update(overrides)
    resp = api_client.create_statement(payload, ADMIN)
    assert resp.status_code == 201, (
        f"Setup failed: create_statement -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def issue_statement(statement_id):
    resp = api_client.issue_statement(statement_id, ADMIN)
    assert resp.status_code == 200, (
        f"Setup failed: issue_statement -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def preview_statement(statement_id):
    resp = api_client.preview_statement(statement_id, ADMIN)
    assert resp.status_code == 200, (
        f"Setup failed: preview_statement -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


# --------------------------------------------------------------------------
# transfer applications
# --------------------------------------------------------------------------

def create_transfer_application(agreement_id, territory_id,
                                applicant_franchisee_id, submitting_franchisee_id,
                                **overrides):
    payload = {
        "agreement_id": agreement_id,
        "territory_id": territory_id,
        "applicant_franchisee_id": applicant_franchisee_id,
        "transfer_kind": "RESALE",
        "purchase_price_cents": 5000000,
        "target_territory_ids": [],
    }
    payload.update(overrides)
    resp = api_client.create_transfer_application(
        payload, make_franchisee_operator_headers(submitting_franchisee_id),
    )
    assert resp.status_code == 201, (
        f"Setup failed: create_transfer_application -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def begin_review(application_id, reviewer_operator_id=None):
    reviewer = reviewer_operator_id or TEST_DEFAULTS["REVIEWER_OPERATOR"]
    resp = api_client.begin_review(application_id, reviewer, ADMIN)
    assert resp.status_code == 200, (
        f"Setup failed: begin_review -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


def approve_transfer(application_id, approval_operator_id=None):
    approver = approval_operator_id or TEST_DEFAULTS["APPROVER_OPERATOR"]
    resp = api_client.approve_transfer(application_id, approver, ADMIN)
    assert resp.status_code == 200, (
        f"Setup failed: approve_transfer -> {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)