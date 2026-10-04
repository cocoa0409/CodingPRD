"""Composite setup helpers built from PRD-declared endpoints only.

Every helper builds its preconditions from scratch: the server is restarted and
the database emptied before every individual test, so nothing may be carried in
from a previous test.

Setup steps use the framework's lenient `get_success_data()` so a broken
precondition reports "Setup step failed" rather than a confusing assertion.
Helpers accept `**overrides` for the values individual tests must control.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import THRESHOLDS, TEST_DEFAULTS
from .factories import (
    create_network_payload, create_practice_payload, create_drug_product_payload,
    create_provider_payload, create_affiliation_contract_payload,
    create_pricing_agreement_payload, create_purchase_order_payload,
    create_receipt_payload, create_pathway_protocol_payload,
    create_treatment_payload, create_rebate_program_payload,
    create_rebate_qualification_payload, create_management_agreement_payload,
    create_research_participation_payload, create_shortage_payload,
    create_pricing_agreement_submit_payload, create_administer_payload,
    create_claim_submit_payload, next_ndc, next_npi,
)
from .test_users import (
    TEST_USERS, make_practice_admin_headers, make_network_admin_headers,
    make_revenue_cycle_manager_headers, make_payer_adjudicator_headers,
    make_network_analyst_headers, make_platform_admin_headers,
)

NETWORK_ADMIN = TEST_USERS["network_admin_headers"]
REVENUE_CYCLE_MANAGER = TEST_USERS["revenue_cycle_manager_headers"]
PAYER_ADJUDICATOR = TEST_USERS["payer_adjudicator_headers"]
NETWORK_ANALYST = TEST_USERS["network_analyst_headers"]
PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]

DEFAULT_CLOCK = TEST_DEFAULTS["CLOCK_START"]
DEFAULT_LOT_EXPIRY = "2027-09-15T00:00:00Z"


def ok(response):
    """Lenient 2xx unwrap used for every setup step."""
    return get_success_data(response)


# ─── Tier 0: primitives ─────────────────────────────────────────────────────

def set_clock(current_utc):
    """Move the logical clock. The clock never advances on its own."""
    return ok(api_client.set_clock({"current_utc": current_utc}, PLATFORM_ADMIN))


def create_network(**overrides):
    return ok(api_client.create_network(create_network_payload(**overrides), NETWORK_ADMIN))


def create_practice(network_id, **overrides):
    return ok(api_client.create_practice(
        network_id, create_practice_payload(**overrides), NETWORK_ADMIN))


def create_product(network_id, **overrides):
    return ok(api_client.create_drug_product(
        network_id, create_drug_product_payload(**overrides), NETWORK_ADMIN))


def create_provider(practice_id, **overrides):
    """PracticeAdmin is entity-backed, so the acting user id is the practice id."""
    return ok(api_client.create_provider(
        practice_id, create_provider_payload(**overrides),
        make_practice_admin_headers(practice_id)))


def create_published_protocol(network_id, **overrides):
    protocol = ok(api_client.create_pathway_protocol(
        network_id, create_pathway_protocol_payload(**overrides), NETWORK_ADMIN))
    protocol = ok(api_client.update_pathway_protocol(
        protocol["id"], {"status": "PUBLISHED"}, NETWORK_ADMIN))
    return protocol


def get_practice(practice_id):
    return ok(api_client.get_practice(practice_id, NETWORK_ADMIN))


def get_practice_version(practice_id):
    """Re-read the practice so a stale-version guard never fires by accident."""
    return get_practice(practice_id)["version"]


def create_activated_contract(practice_id, **overrides):
    """Create an affiliation contract and activate it.

    Activation promotes a PROSPECTIVE practice to AFFILIATED.
    """
    contract = ok(api_client.create_affiliation_contract(
        practice_id, create_affiliation_contract_payload(**overrides), NETWORK_ADMIN))
    return ok(api_client.activate_affiliation_contract(contract["id"], NETWORK_ADMIN))


def create_approved_agreement(practice_id, practice_version, **overrides):
    """Create a pricing agreement, submit it as the practice itself, and approve
    it as a distinct NetworkAdmin user."""
    practice_headers = make_practice_admin_headers(practice_id)
    agreement = ok(api_client.create_pricing_agreement(
        practice_id, create_pricing_agreement_payload(**overrides), practice_headers))
    ok(api_client.submit_pricing_agreement(
        agreement["id"], create_pricing_agreement_submit_payload(practice_version),
        practice_headers))
    return ok(api_client.approve_pricing_agreement(agreement["id"], NETWORK_ADMIN))


def create_draft_agreement(practice_id, **overrides):
    practice_headers = make_practice_admin_headers(practice_id)
    return ok(api_client.create_pricing_agreement(
        practice_id, create_pricing_agreement_payload(**overrides), practice_headers))


def receive_new_lot(practice_id, product_id, quantity, expires_at=None,
                    lot_number=None, allocation_id=None, confirm=True):
    """Submit → confirm → ship → receive one order, producing an inventory lot.

    Returns (order, lot).
    """
    practice_headers = make_practice_admin_headers(practice_id)
    order = ok(api_client.create_purchase_order(
        create_purchase_order_payload(practice_id, product_id,
                                      quantity_units=quantity,
                                      shortage_allocation_id=allocation_id),
        practice_headers))
    if confirm:
        ok(api_client.confirm_order(order["id"], NETWORK_ADMIN))
    ok(api_client.ship_order(order["id"], NETWORK_ADMIN))
    lot_number = lot_number or "L-{}".format(order["id"][:8])
    order = ok(api_client.receive_order(
        order["id"],
        create_receipt_payload(lot_number=lot_number,
                               expires_at=expires_at or DEFAULT_LOT_EXPIRY),
        practice_headers))
    lots = ok(api_client.list_order_lots(order["id"], NETWORK_ADMIN))
    return order, lots[0]


def adopt_pathways(practice_id):
    return ok(api_client.adopt_pathways(
        practice_id, make_practice_admin_headers(practice_id)))


def find_draft_claim(treatment_id):
    claims = ok(api_client.list_treatment_claims(
        treatment_id, REVENUE_CYCLE_MANAGER, params={"status": "DRAFT"}))
    assert claims, "expected a DRAFT claim for treatment {}".format(treatment_id)
    return claims[0]


# ─── Tier 2: entity hierarchy ───────────────────────────────────────────────

def setup_network_and_practice(clock=DEFAULT_CLOCK, **overrides):
    """Logical clock + one network + one prospective practice."""
    set_clock(clock)
    network = create_network(**overrides.get("network_overrides", {}))
    practice = create_practice(network["id"], **overrides.get("practice_overrides", {}))
    return network, practice


def setup_affiliated_practice(clock=DEFAULT_CLOCK,
                              contract_overrides=None,
                              agreement_overrides=None,
                              create_agreement=True,
                              **overrides):
    """Network + practice + ACTIVE affiliation contract (+ ACTIVE pricing agreement).

    Returns (network, practice, contract, agreement_or_None).
    """
    network, practice = setup_network_and_practice(clock=clock, **overrides)
    contract = create_activated_contract(practice["id"], **(contract_overrides or {}))
    practice = get_practice(practice["id"])
    agreement = None
    if create_agreement:
        agreement = create_approved_agreement(
            practice["id"], practice["version"], **(agreement_overrides or {}))
        practice = get_practice(practice["id"])
    return network, practice, contract, agreement


def setup_operational_practice(clock=DEFAULT_CLOCK,
                               contract_overrides=None,
                               agreement_overrides=None,
                               product_overrides=None,
                               provider_overrides=None,
                               protocol_overrides=None,
                               adopt_pathway_program=True,
                               stock_units=None,
                               lot_overrides=None,
                               treating_clock=None,
                               **overrides):
    """The full operating context most workflows need.

    Network + practice + ACTIVE contract + ACTIVE pricing agreement + drug
    product + provider + PUBLISHED pathway protocol (+ optional stock lot).

    Returns a context dict with keys: network, practice, contract, agreement,
    product, provider, protocol, lot.
    """
    network, practice, contract, agreement = setup_affiliated_practice(
        clock=clock,
        contract_overrides=contract_overrides,
        agreement_overrides=agreement_overrides,
        **overrides)

    product = create_product(network["id"], **(product_overrides or {}))
    provider = create_provider(practice["id"], **(provider_overrides or {}))
    protocol = create_published_protocol(network["id"], **(protocol_overrides or {}))
    if adopt_pathway_program:
        practice = adopt_pathways(practice["id"])

    lot = None
    if stock_units:
        _, lot = receive_new_lot(practice["id"], product["id"], stock_units,
                                 **(lot_overrides or {}))
    practice = get_practice(practice["id"])
    return {
        "network": network,
        "practice": practice,
        "contract": contract,
        "agreement": agreement,
        "product": product,
        "provider": provider,
        "protocol": protocol,
        "lot": lot,
    }


# ─── Tier 3: full lifecycle shortcuts ───────────────────────────────────────

def schedule_and_administer(ctx, administered_units=None, dose_count=None,
                            vial_yield_units=None, admin_fee_cents=None,
                            administered_at=None, dose_plan="WASTE_BILLED",
                            regimen_code=None, patient_reference=None,
                            treatment_overrides=None):
    """Schedule a treatment on the context and administer it.

    The logical clock is moved to `administered_at` first, because the PRD
    requires the administration instant to be at or before the logical clock.
    Returns the ADMINISTERED treatment.
    """
    practice_id = ctx["practice"]["id"]
    administered_at = administered_at or "2026-09-02T00:00:00Z"
    set_clock(administered_at)

    payload_overrides = dict(treatment_overrides or {})
    if administered_units is not None:
        payload_overrides["administered_units"] = administered_units
    if dose_count is not None:
        payload_overrides["dose_count"] = dose_count
    if vial_yield_units is not None:
        payload_overrides["vial_yield_units"] = vial_yield_units
    if admin_fee_cents is not None:
        payload_overrides["admin_fee_cents"] = admin_fee_cents
    if regimen_code is not None:
        payload_overrides["regimen_code"] = regimen_code
    if patient_reference is not None:
        payload_overrides["patient_reference"] = patient_reference
    payload_overrides["administered_at"] = administered_at

    practice_headers = make_practice_admin_headers(practice_id)
    treatment = ok(api_client.create_treatment(
        create_treatment_payload(practice_id, ctx["provider"]["id"],
                                 ctx["product"]["id"], ctx["protocol"]["id"],
                                 **payload_overrides),
        practice_headers))
    version = get_practice_version(practice_id)
    return ok(api_client.administer_treatment(
        treatment["id"], create_administer_payload(version, dose_plan=dose_plan),
        practice_headers))


def submit_and_settle_claim(ctx, treatment, outcome="paid", paid_amount_cents=None,
                            denial_reason_code="MEDICAL_NECESSITY"):
    """Submit the treatment's DRAFT claim and settle it as paid or denied."""
    claim = find_draft_claim(treatment["id"])
    version = get_practice_version(ctx["practice"]["id"])
    claim = ok(api_client.submit_claim(
        claim["id"], create_claim_submit_payload(version), REVENUE_CYCLE_MANAGER))
    if outcome == "paid":
        amount = paid_amount_cents or claim["billed_amount_cents"]
        claim = ok(api_client.adjudicate_claim(
            claim["id"], {"paid_amount_cents": amount}, PAYER_ADJUDICATOR))
    elif outcome == "denied":
        claim = ok(api_client.deny_claim(
            claim["id"], {"denial_reason_code": denial_reason_code}, PAYER_ADJUDICATOR))
    else:
        raise ValueError("unknown settlement outcome: {}".format(outcome))
    return claim


def add_settled_claim(ctx, outcome="paid", **kwargs):
    """Administer one further treatment and settle its claim."""
    kwargs.setdefault("patient_reference", "PT-SETTLE")
    treatment = schedule_and_administer(ctx, **kwargs)
    claim = submit_and_settle_claim(ctx, treatment, outcome=outcome)
    return treatment, claim


# ─── Tier 4: accumulation / threshold targeting ─────────────────────────────

def setup_denial_ratio_scenario(denied_count, paid_count,
                                denial_ratio_threshold_pct=None,
                                clock=DEFAULT_CLOCK,
                                stock_units=20000):
    """Build a practice whose lifetime claim counters are exactly
    (denied_count DENIED) / (denied_count + paid_count settled).

    Returns the operational context; `ctx["agreement"]` is the ACTIVE pricing
    agreement whose suspension the denial ratio governs.
    """
    overrides = {}
    if denial_ratio_threshold_pct is not None:
        overrides["practice_overrides"] = {
            "denial_ratio_threshold_pct": denial_ratio_threshold_pct}
    ctx = setup_operational_practice(
        clock=clock, stock_units=stock_units,
        product_overrides={"unit_type": "VIAL"},
        **overrides)

    for index in range(paid_count):
        add_settled_claim(ctx, outcome="paid", administered_units=100,
                          vial_yield_units=100, admin_fee_cents=0,
                          patient_reference="PT-PAID-{}".format(index))
    for index in range(denied_count):
        add_settled_claim(ctx, outcome="denied", administered_units=100,
                          vial_yield_units=100, admin_fee_cents=0,
                          patient_reference="PT-DENY-{}".format(index))
    ctx["practice"] = get_practice(ctx["practice"]["id"])
    return ctx


def create_shortage_grants(network, product, supply_available_units,
                           allocation_method="PRO_RATA_BASELINE",
                           authorization_by_practice=None,
                           activate=True, reported_at=DEFAULT_CLOCK):
    """Report a shortage, run the allocation waterfall, and (optionally) activate it.

    Returns (shortage, grants).
    """
    shortage = ok(api_client.report_shortage(
        network["id"],
        create_shortage_payload(product["id"],
                                supply_available_units=supply_available_units,
                                allocation_method=allocation_method,
                                reported_at=reported_at),
        NETWORK_ADMIN))
    shortage = ok(api_client.allocate_shortage(
        shortage["id"],
        {"practice_consumption_authorization_cents": authorization_by_practice or {}},
        NETWORK_ADMIN))
    if activate:
        shortage = ok(api_client.activate_shortage(shortage["id"], NETWORK_ADMIN))
    grants = ok(api_client.list_shortage_grants(shortage["id"], NETWORK_ADMIN))
    return shortage, grants


def setup_shortage_network(baselines, supply_available_units,
                           allocation_method="PRO_RATA_BASELINE",
                           product_price_cents=2000,
                           authorization_cents=600000,
                           clock=DEFAULT_CLOCK):
    """Network + N affiliated practices (each with a contract and agreement) +
    a shortage product + a reported and allocated shortage.

    `baselines` is a list of drug_shortage_baseline_units, one per practice.
    Returns (network, product, practices, shortage, grants).
    """
    set_clock(clock)
    network = create_network()
    product = create_product(network["id"],
                             network_base_price_cents=product_price_cents,
                             unit_type="VIAL", is_shortage_candidate=True)

    practices = []
    for baseline in baselines:
        practice = create_practice(network["id"],
                                   drug_shortage_baseline_units=baseline)
        create_activated_contract(practice["id"])
        practice = get_practice(practice["id"])
        create_approved_agreement(practice["id"], practice["version"])
        practices.append(get_practice(practice["id"]))

    auth = {p["id"]: authorization_cents for p in practices}
    shortage, grants = create_shortage_grants(
        network, product, supply_available_units,
        allocation_method=allocation_method,
        authorization_by_practice=auth)
    return network, product, practices, shortage, grants


# ─── Tier 5: finalization / terminal state ──────────────────────────────────

def drive_practice_to_departing(ctx, notice_clock=None):
    """Issue a departure notice and return the DEPARTING practice."""
    if notice_clock:
        set_clock(notice_clock)
    practice = ok(api_client.departure_notice(
        ctx["practice"]["id"], make_practice_admin_headers(ctx["practice"]["id"])))
    ctx["practice"] = practice
    return practice


def drive_practice_to_departed(ctx, by_epochs=1):
    """Advance the epoch until the departure takes effect; returns
    (network, practice, contract)."""
    ok(api_client.advance_epoch(ctx["network"]["id"], {"by_epochs": by_epochs},
                                NETWORK_ADMIN))
    ctx["practice"] = get_practice(ctx["practice"]["id"])
    ctx["contract"] = ok(api_client.get_affiliation_contract(
        ctx["contract"]["id"], NETWORK_ADMIN))
    ctx["network"] = ok(api_client.get_network(ctx["network"]["id"], NETWORK_ADMIN))
    return ctx["network"], ctx["practice"], ctx["contract"]


# ─── Domain-specific composite fixtures ─────────────────────────────────────

def setup_rebate_program(network_id, **overrides):
    program = ok(api_client.create_rebate_program(
        network_id, create_rebate_program_payload(**overrides), NETWORK_ADMIN))
    return ok(api_client.activate_rebate_program(program["id"], NETWORK_ADMIN))


def create_rebate_program(network_id, **overrides):
    """Create a rebate program and activate it — a qualification can only be
    raised against an ACTIVE program."""
    return setup_rebate_program(network_id, **overrides)


def create_rebate_qualification(practice_id, program_id, **overrides):
    return ok(api_client.create_rebate_qualification(
        create_rebate_qualification_payload(practice_id, program_id, **overrides),
        make_practice_admin_headers(practice_id)))


def setup_two_networks(clock=DEFAULT_CLOCK):
    """Two independent networks, for cross-network referential-integrity tests."""
    set_clock(clock)
    n1 = create_network(network_agreement_code="GPO-A-1", name="Alpha Oncology Network")
    n2 = create_network(network_agreement_code="GPO-B-1", name="Beta Oncology Network")
    return n1, n2


def setup_practice_with_management_agreement(ctx, **overrides):
    agreement = ok(api_client.create_management_agreement(
        create_management_agreement_payload(ctx["practice"]["id"], **overrides),
        NETWORK_ADMIN))
    return ok(api_client.activate_management_agreement(agreement["id"], NETWORK_ADMIN))