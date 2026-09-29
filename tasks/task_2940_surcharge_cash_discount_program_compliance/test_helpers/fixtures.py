"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because each test runs against an empty database.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    AUDITOR_USER_ID,
    CLOCK_AUG_01,
    CLOCK_AUG_31,
    CLOCK_DEC_31,
    CONTENT_HASH_A,
    CONTENT_HASH_B,
    CONTENT_HASH_C,
    CONTENT_HASH_D,
    OFFICER_ONE_USER_ID,
    OFFICER_TWO_USER_ID,
    REGULATOR_USER_ID,
)
from . import factories as f
from .test_users import (
    make_compliance_officer_headers,
    make_merchant_operator_headers,
    make_network_auditor_headers,
    make_platform_admin_headers,
    make_state_regulator_headers,
    make_terminal_agent_headers,
)

ADMIN = make_platform_admin_headers()
OFFICER_ONE = make_compliance_officer_headers(OFFICER_ONE_USER_ID)
OFFICER_TWO = make_compliance_officer_headers(OFFICER_TWO_USER_ID)
AUDITOR = make_network_auditor_headers(AUDITOR_USER_ID)
REGULATOR = make_state_regulator_headers(REGULATOR_USER_ID)


def channel_headers(source: str) -> dict:
    """The role that owns a complaint channel: a NetworkAuditor owns NETWORK and
    CARDHOLDER cases, a StateRegulator owns ATTORNEY_GENERAL cases."""
    return REGULATOR if source == "ATTORNEY_GENERAL" else AUDITOR


# --------------------------------------------------------------------------
# Single-step helpers
# --------------------------------------------------------------------------
def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(f.clock_payload(to_iso8601), ADMIN))


def create_jurisdiction(profile: str = "AZ", **overrides) -> dict:
    return get_success_data(
        api_client.create_jurisdiction(f.jurisdiction_payload(profile, **overrides), ADMIN)
    )


def apply_law_change(jurisdiction_id: str, surcharge_permitted: bool, **overrides) -> dict:
    return get_success_data(
        api_client.apply_law_change(
            jurisdiction_id, f.law_change_payload(surcharge_permitted, **overrides), REGULATOR
        )
    )


def create_merchant(jurisdiction_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_merchant(f.merchant_payload(jurisdiction_id, **overrides), ADMIN)
    )


def read_merchant(merchant_id: str) -> dict:
    return get_success_data(api_client.get_merchant(merchant_id, ADMIN))


def read_program(program_id: str) -> dict:
    return get_success_data(api_client.get_program(program_id, ADMIN))


def read_terminal(terminal_id: str) -> dict:
    return get_success_data(api_client.get_terminal(terminal_id, ADMIN))


def read_artifact(artifact_id: str) -> dict:
    return get_success_data(api_client.get_disclosure_artifact(artifact_id, ADMIN))


def read_registration(registration_id: str) -> dict:
    return get_success_data(api_client.get_network_registration(registration_id, ADMIN))


def read_transaction(transaction_id: str) -> dict:
    return get_success_data(api_client.get_transaction(transaction_id, ADMIN))


def read_complaint_case(case_id: str) -> dict:
    return get_success_data(api_client.get_complaint_case(case_id, ADMIN))


def read_refund(refund_id: str) -> dict:
    return get_success_data(api_client.get_refund(refund_id, ADMIN))


def file_cost_documentation(
    merchant_id: str, expected_merchant_version=None, profile: str = "docA", **overrides
) -> dict:
    if expected_merchant_version is None:
        expected_merchant_version = read_merchant(merchant_id)["version"]
    return get_success_data(
        api_client.create_cost_documentation(
            merchant_id,
            f.cost_documentation_payload(expected_merchant_version, profile, **overrides),
            OFFICER_ONE,
        )
    )


def create_program(
    merchant_id: str,
    jurisdiction_id: str,
    cost_documentation_id: str,
    program_type: str = "SURCHARGE",
    consistency_scope: str = "BRAND_LEVEL",
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_program(
            f.program_payload(
                merchant_id,
                jurisdiction_id,
                cost_documentation_id,
                program_type,
                consistency_scope,
                **overrides,
            ),
            OFFICER_ONE,
        )
    )


def file_rate_rule(program_id: str, expected_program_version=None, **overrides) -> dict:
    if expected_program_version is None:
        expected_program_version = read_program(program_id)["version"]
    return get_success_data(
        api_client.create_rate_rule(
            program_id, f.rate_rule_payload(expected_program_version, **overrides), OFFICER_ONE
        )
    )


def submit_registration(program_id: str, network: str = "VISA", registration_ref=None) -> dict:
    ref = registration_ref or f"VS-2940-{network[:2]}-0001"
    return get_success_data(
        api_client.create_network_registration(
            program_id, f.network_registration_payload(network, ref), OFFICER_ONE
        )
    )


def decide_registration(registration_id: str, decision: str = "ACKNOWLEDGE", **overrides) -> dict:
    return get_success_data(
        api_client.decide_network_registration(
            registration_id, f.registration_decision_payload(decision, **overrides), AUDITOR
        )
    )


def effectuate_registration(registration_id: str) -> dict:
    return get_success_data(
        api_client.effectuate_network_registration(registration_id, OFFICER_ONE)
    )


def draft_artifact(
    program_id: str, merchant_id: str, artifact_type: str = "ENTRY_SIGNAGE", content_hash=CONTENT_HASH_A
) -> dict:
    return get_success_data(
        api_client.create_disclosure_artifact(
            program_id,
            f.disclosure_artifact_payload(artifact_type, content_hash),
            make_merchant_operator_headers(merchant_id),
        )
    )


def attest_artifact(
    artifact_id: str,
    effective_from: str = CLOCK_AUG_01,
    expires_at: str = CLOCK_DEC_31,
    officer_user_id: str = OFFICER_TWO_USER_ID,
) -> dict:
    return get_success_data(
        api_client.attest_disclosure_artifact(
            artifact_id,
            f.attestation_payload(effective_from, expires_at),
            make_compliance_officer_headers(officer_user_id),
        )
    )


def provision_terminal(merchant_id: str, serial_number: str = "TRM-0001") -> dict:
    return get_success_data(
        api_client.create_terminal(
            merchant_id,
            f.terminal_payload(serial_number),
            make_merchant_operator_headers(merchant_id),
        )
    )


def configure_terminal(
    terminal_id: str, merchant_id: str, program_id: str, debit_exclusion_enabled: bool = True, **overrides
) -> dict:
    return get_success_data(
        api_client.configure_terminal(
            terminal_id,
            f.terminal_configuration_payload(program_id, debit_exclusion_enabled, **overrides),
            make_merchant_operator_headers(merchant_id),
        )
    )


def terminal_action(terminal_id: str, merchant_id: str, action: str, **overrides) -> dict:
    return get_success_data(
        api_client.terminal_state_action(
            terminal_id,
            f.terminal_action_payload(action, **overrides),
            make_merchant_operator_headers(merchant_id),
        )
    )


def program_status_action(program_id: str, action: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.program_status_action(
            program_id, f.program_status_action_payload(action, **overrides), headers or OFFICER_ONE
        )
    )


def activate_program(program_id: str, officer_user_id: str = OFFICER_ONE_USER_ID) -> dict:
    return get_success_data(
        api_client.activate_program(program_id, make_compliance_officer_headers(officer_user_id))
    )


def capture_sale(terminal_id: str, program_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_transaction(
            f.transaction_payload(terminal_id, program_id, **overrides),
            make_terminal_agent_headers(terminal_id),
        )
    )


def file_complaint(program_id: str, source: str = "NETWORK", **overrides) -> dict:
    return get_success_data(
        api_client.create_complaint_case(
            f.complaint_case_payload(program_id, source, **overrides), channel_headers(source)
        )
    )


def investigation_action(case_id: str, action: str, source: str = "NETWORK", **overrides) -> dict:
    headers = OFFICER_ONE if action == "REVIEW" else channel_headers(source)
    return get_success_data(
        api_client.complaint_investigation_action(
            case_id, f.investigation_action_payload(action, **overrides), headers
        )
    )


def remediation_action(case_id: str, action: str, source: str = "NETWORK", **overrides) -> dict:
    headers = OFFICER_ONE if action == "SUBMIT_PLAN" else channel_headers(source)
    return get_success_data(
        api_client.complaint_remediation_action(
            case_id, f.remediation_action_payload(action, **overrides), headers
        )
    )


def create_refund(case_id: str, transaction_id: str, refund_amount_cents: int, officer_user_id: str = OFFICER_ONE_USER_ID) -> dict:
    return get_success_data(
        api_client.create_refund(
            case_id,
            f.refund_payload(transaction_id, refund_amount_cents),
            make_compliance_officer_headers(officer_user_id),
        )
    )


def issue_refund(refund_id: str, officer_user_id: str = OFFICER_TWO_USER_ID) -> dict:
    return get_success_data(
        api_client.issue_refund(refund_id, make_compliance_officer_headers(officer_user_id))
    )


def void_refund(refund_id: str, officer_user_id: str = OFFICER_TWO_USER_ID, **overrides) -> dict:
    return get_success_data(
        api_client.void_refund(
            refund_id, f.void_payload(**overrides), make_compliance_officer_headers(officer_user_id)
        )
    )


# --------------------------------------------------------------------------
# Disclosure readiness helpers
# --------------------------------------------------------------------------
def required_artifact_types(program_type: str, jurisdiction: dict) -> list:
    """The required set implied by the program type and the jurisdiction's flags.
    PRICE_LIST_POSTING is deliberately never a member."""
    required = []
    if program_type == "SURCHARGE":
        if jurisdiction["disclosure_signage_required"]:
            required.extend(["ENTRY_SIGNAGE", "POS_SIGNAGE"])
        if jurisdiction["receipt_line_item_required"]:
            required.append("RECEIPT_TEMPLATE")
    else:
        if jurisdiction["disclosure_signage_required"]:
            required.append("POS_SIGNAGE")
    return required


_HASHES = {
    "ENTRY_SIGNAGE": CONTENT_HASH_A,
    "POS_SIGNAGE": CONTENT_HASH_B,
    "RECEIPT_TEMPLATE": CONTENT_HASH_C,
    "PRICE_LIST_POSTING": CONTENT_HASH_D,
}


def attest_disclosures(
    program_id: str,
    merchant_id: str,
    artifact_types: list,
    effective_from: str = CLOCK_AUG_01,
    expires_at: str = CLOCK_DEC_31,
    officer_user_id: str = OFFICER_TWO_USER_ID,
) -> dict:
    """Draft and attest one artifact of each named type over the same window.
    Returns a mapping of artifact_type to the attested artifact."""
    attested = {}
    for artifact_type in artifact_types:
        artifact = draft_artifact(
            program_id, merchant_id, artifact_type, _HASHES.get(artifact_type, CONTENT_HASH_A)
        )
        attested[artifact_type] = attest_artifact(
            artifact["id"], effective_from, expires_at, officer_user_id
        )
    return attested


# --------------------------------------------------------------------------
# Tier 1 / Tier 2: merchant, documentation, draft program
# --------------------------------------------------------------------------
def setup_merchant_with_documentation(
    jurisdiction_profile: str = "AZ",
    doc_profile: str = "docA",
    clock: str = CLOCK_AUG_01,
    **merchant_overrides,
) -> dict:
    """Clock at a known instant, one jurisdiction, one merchant, one ACTIVE
    cost documentation. Returns a context dict."""
    set_clock(clock)
    jurisdiction = create_jurisdiction(jurisdiction_profile)
    merchant = create_merchant(jurisdiction["id"], **merchant_overrides)
    documentation = file_cost_documentation(
        merchant["id"], merchant["version"], doc_profile
    )
    return {
        "jurisdiction": jurisdiction,
        "merchant": merchant,
        "cost_documentation": documentation,
    }


def setup_draft_program(
    jurisdiction_profile: str = "AZ",
    doc_profile: str = "docA",
    program_type: str = "SURCHARGE",
    consistency_scope: str = "BRAND_LEVEL",
    clock: str = CLOCK_AUG_01,
    with_rate_rule: bool = True,
    rate_pct: float = 2.19,
    brand: str = "VISA",
    product_tier: str = "ALL",
    effective_from: str = CLOCK_AUG_01,
    effective_to: str = CLOCK_DEC_31,
    **merchant_overrides,
) -> dict:
    """A DRAFT program on a fresh merchant, optionally with one rate rule.
    Any surplus keyword arguments describe the merchant itself."""
    ctx = setup_merchant_with_documentation(
        jurisdiction_profile, doc_profile, clock, **merchant_overrides
    )
    program = create_program(
        ctx["merchant"]["id"],
        ctx["jurisdiction"]["id"],
        ctx["cost_documentation"]["id"],
        program_type,
        consistency_scope,
    )
    ctx["program"] = program
    if with_rate_rule:
        ctx["rate_rule"] = file_rate_rule(
            program["id"],
            program["version"],
            brand=brand,
            product_tier=product_tier,
            rate_pct=rate_pct,
            effective_from=effective_from,
            effective_to=effective_to,
        )
        ctx["program"] = read_program(program["id"])
    return ctx


def setup_program_pending_registration(
    jurisdiction_profile: str = "AZ",
    doc_profile: str = "docA",
    consistency_scope: str = "BRAND_LEVEL",
    network: str = "VISA",
    registration_ref: str = "VS-2940-0001",
    **draft_overrides,
) -> dict:
    """A SURCHARGE program driven to PENDING_REGISTRATION by its first
    registration submission."""
    ctx = setup_draft_program(
        jurisdiction_profile=jurisdiction_profile,
        doc_profile=doc_profile,
        program_type="SURCHARGE",
        consistency_scope=consistency_scope,
        **draft_overrides,
    )
    ctx["registration"] = submit_registration(
        ctx["program"]["id"], network, registration_ref
    )
    ctx["program"] = read_program(ctx["program"]["id"])
    return ctx


def setup_program_with_effective_registration(
    jurisdiction_profile: str = "AZ",
    doc_profile: str = "docA",
    consistency_scope: str = "BRAND_LEVEL",
    network: str = "VISA",
    effective_clock: str = CLOCK_AUG_31,
    **kwargs,
) -> dict:
    """A SURCHARGE program whose registration has been acknowledged and then
    effectuated once the notice period elapsed. The clock is left at
    effective_clock."""
    ctx = setup_program_pending_registration(
        jurisdiction_profile=jurisdiction_profile,
        doc_profile=doc_profile,
        consistency_scope=consistency_scope,
        network=network,
        **kwargs,
    )
    decide_registration(ctx["registration"]["id"], "ACKNOWLEDGE")
    set_clock(effective_clock)
    ctx["registration"] = effectuate_registration(ctx["registration"]["id"])
    ctx["program"] = read_program(ctx["program"]["id"])
    return ctx


def setup_active_surcharge_program(
    jurisdiction_profile: str = "AZ",
    doc_profile: str = "docA",
    consistency_scope: str = "BRAND_LEVEL",
    network: str = "VISA",
    effective_clock: str = CLOCK_AUG_31,
    activating_officer_user_id: str = OFFICER_ONE_USER_ID,
    attesting_officer_user_id: str = OFFICER_TWO_USER_ID,
    **kwargs,
) -> dict:
    """A SURCHARGE program in ACTIVE, with whatever disclosure artifacts the
    jurisdiction's flags demand attested over a window containing the clock."""
    ctx = setup_program_with_effective_registration(
        jurisdiction_profile=jurisdiction_profile,
        doc_profile=doc_profile,
        consistency_scope=consistency_scope,
        network=network,
        effective_clock=effective_clock,
        **kwargs,
    )
    required = required_artifact_types("SURCHARGE", ctx["jurisdiction"])
    if required:
        ctx["artifacts"] = attest_disclosures(
            ctx["program"]["id"],
            ctx["merchant"]["id"],
            required,
            officer_user_id=attesting_officer_user_id,
        )
    ctx["program"] = activate_program(ctx["program"]["id"], activating_officer_user_id)
    return ctx


def setup_active_cash_discount_program(
    jurisdiction_profile: str = "AZ",
    doc_profile: str = "docA",
    consistency_scope: str = "BRAND_LEVEL",
    activating_officer_user_id: str = OFFICER_ONE_USER_ID,
    attesting_officer_user_id: str = OFFICER_TWO_USER_ID,
    **kwargs,
) -> dict:
    """A CASH_DISCOUNT program in ACTIVE. No registration is involved; the
    posted price list is attested whenever the jurisdiction demands one."""
    ctx = setup_draft_program(
        jurisdiction_profile=jurisdiction_profile,
        doc_profile=doc_profile,
        program_type="CASH_DISCOUNT",
        consistency_scope=consistency_scope,
        **kwargs,
    )
    required = required_artifact_types("CASH_DISCOUNT", ctx["jurisdiction"])
    if ctx["jurisdiction"]["price_posting_required"]:
        required = required + ["PRICE_LIST_POSTING"]
    if required:
        ctx["artifacts"] = attest_disclosures(
            ctx["program"]["id"],
            ctx["merchant"]["id"],
            required,
            officer_user_id=attesting_officer_user_id,
        )
    ctx["program"] = activate_program(ctx["program"]["id"], activating_officer_user_id)
    return ctx


# --------------------------------------------------------------------------
# Tier 3: terminals reaching enforcement
# --------------------------------------------------------------------------
def setup_enforcing_terminal(
    merchant_id: str,
    program_id: str,
    serial_number: str = "TRM-0001",
    debit_exclusion_enabled: bool = True,
) -> dict:
    """Provision, configure and drive one terminal to ENFORCING."""
    terminal = provision_terminal(merchant_id, serial_number)
    configure_terminal(terminal["id"], merchant_id, program_id, debit_exclusion_enabled)
    return terminal_action(terminal["id"], merchant_id, "ENFORCE")


def setup_configured_terminal(
    merchant_id: str,
    program_id: str,
    serial_number: str = "TRM-0001",
    debit_exclusion_enabled: bool = True,
) -> dict:
    terminal = provision_terminal(merchant_id, serial_number)
    return configure_terminal(
        terminal["id"], merchant_id, program_id, debit_exclusion_enabled
    )


def setup_enforcing_surcharge_estate(
    jurisdiction_profile: str = "AZ",
    doc_profile: str = "docA",
    terminal_count: int = 1,
    serial_prefix: str = "TRM-AZ-",
    **kwargs,
) -> dict:
    """An ACTIVE SURCHARGE program with terminal_count terminals all ENFORCING.
    ctx["terminals"] is the list; ctx["terminal"] is the first of them."""
    ctx = setup_active_surcharge_program(
        jurisdiction_profile=jurisdiction_profile, doc_profile=doc_profile, **kwargs
    )
    terminals = []
    for index in range(terminal_count):
        terminals.append(
            setup_enforcing_terminal(
                ctx["merchant"]["id"],
                ctx["program"]["id"],
                f"{serial_prefix}{index + 1:04d}",
            )
        )
    ctx["terminals"] = terminals
    ctx["terminal"] = terminals[0] if terminals else None
    return ctx


def setup_enforcing_cash_discount_estate(
    jurisdiction_profile: str = "AZ",
    doc_profile: str = "docA",
    terminal_count: int = 1,
    serial_prefix: str = "TRM-CD-",
    debit_exclusion_enabled: bool = True,
    **kwargs,
) -> dict:
    """An ACTIVE CASH_DISCOUNT program with terminal_count terminals ENFORCING."""
    ctx = setup_active_cash_discount_program(
        jurisdiction_profile=jurisdiction_profile, doc_profile=doc_profile, **kwargs
    )
    terminals = []
    for index in range(terminal_count):
        terminals.append(
            setup_enforcing_terminal(
                ctx["merchant"]["id"],
                ctx["program"]["id"],
                f"{serial_prefix}{index + 1:04d}",
                debit_exclusion_enabled,
            )
        )
    ctx["terminals"] = terminals
    ctx["terminal"] = terminals[0] if terminals else None
    return ctx


# --------------------------------------------------------------------------
# Tier 4: captured sales and the complaint / remediation track
# --------------------------------------------------------------------------
def setup_surcharged_sale(
    jurisdiction_profile: str = "AZ",
    base_amount_cents: int = 10000,
    requested_surcharge_cents: int = 219,
    rate_pct: float = 2.19,
    **kwargs,
) -> dict:
    """An ACTIVE SURCHARGE program with one ENFORCING terminal that has captured
    one credit sale. ctx["transaction"] is the captured sale."""
    ctx = setup_enforcing_surcharge_estate(
        jurisdiction_profile=jurisdiction_profile, rate_pct=rate_pct, **kwargs
    )
    ctx["transaction"] = capture_sale(
        ctx["terminal"]["id"],
        ctx["program"]["id"],
        base_amount_cents=base_amount_cents,
        requested_surcharge_cents=requested_surcharge_cents,
    )
    return ctx


def drive_case_to_plan_accepted(case_id: str, source: str = "CARDHOLDER") -> dict:
    """SUBSTANTIATE the investigation, submit a remediation plan and accept it,
    which is what unlocks refund creation on the case."""
    investigation_action(case_id, "SUBSTANTIATE", source)
    remediation_action(case_id, "SUBMIT_PLAN", source)
    return remediation_action(case_id, "ACCEPT_PLAN", source)


def setup_case_with_accepted_plan(program_id: str, source: str = "CARDHOLDER", **overrides) -> dict:
    case = file_complaint(program_id, source, **overrides)
    drive_case_to_plan_accepted(case["id"], source)
    return read_complaint_case(case["id"])


def setup_refundable_sale(
    jurisdiction_profile: str = "AZ",
    source: str = "CARDHOLDER",
    base_amount_cents: int = 10000,
    requested_surcharge_cents: int = 219,
    rate_pct: float = 2.19,
    **kwargs,
) -> dict:
    """A captured surcharged sale plus a complaint case on the same program whose
    remediation plan has been accepted, so refunds may be created.

    A CARDHOLDER case scores 20.00 under the network method, which stays below
    the remediation threshold, so the program remains ACTIVE and no cascade
    perturbs the ledger.
    """
    ctx = setup_surcharged_sale(
        jurisdiction_profile=jurisdiction_profile,
        base_amount_cents=base_amount_cents,
        requested_surcharge_cents=requested_surcharge_cents,
        rate_pct=rate_pct,
        **kwargs,
    )
    ctx["complaint_case"] = setup_case_with_accepted_plan(ctx["program"]["id"], source)
    ctx["program"] = read_program(ctx["program"]["id"])
    return ctx
