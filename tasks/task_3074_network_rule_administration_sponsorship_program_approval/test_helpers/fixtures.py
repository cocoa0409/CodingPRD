"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch out of public endpoints,
because each individual test starts against an empty database (the harness
restarts the server before every test). Setup steps use ``get_success_data()``
so a broken precondition reports as a clear setup failure rather than a
confusing assertion failure in the test body.

Identity threading: after a helper creates a Member, every ownership-gated
call (disputes, appeals, evidence) uses ``make_member_headers(member_id)``
with the real entity id — never the shared role constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_bin_range_payload,
    create_dispute_payload,
    create_evidence_payload,
    create_fraud_case_payload,
    create_fraud_program_cycle_payload,
    create_interchange_rate_payload,
    create_member_payload,
    create_merchant_payload,
    create_participant_payload,
    create_program_payload,
    create_rule_payload,
    create_rule_violation_payload,
    create_settlement_line_payload,
    create_settlement_window_payload,
)
from .test_users import (
    TEST_USERS,
    make_member_headers,
    make_rules_admin_headers,
)

OP = TEST_USERS["network_operator_headers"]
SM = TEST_USERS["sponsorship_manager_headers"]
RA1 = TEST_USERS["rules_admin_headers"]
RA2 = TEST_USERS["rules_admin_2_headers"]
DA = TEST_USERS["dispute_analyst_headers"]
PA = TEST_USERS["pricing_analyst_headers"]
FA = TEST_USERS["fraud_analyst_headers"]
SO = TEST_USERS["settlement_operator_headers"]
CE = TEST_USERS["certification_engineer_headers"]


# ═══════════════════════════════════════════════════════
# Clock
# ═══════════════════════════════════════════════════════

def set_clock(to_iso8601):
    """Advance the logical clock; returns the reported current_utc."""
    res = api_client.set_clock(to_iso8601, OP)
    return get_success_data(res)["current_utc"]


# ═══════════════════════════════════════════════════════
# Tier 1: single-entity state progression
# ═══════════════════════════════════════════════════════

def create_member(legal_name=TEST_DEFAULTS["LEGAL_NAME"], member_kind="BOTH",
                  region=TEST_DEFAULTS["REGION"]):
    """Create a member application (status APPLICATION)."""
    res = api_client.create_member(
        create_member_payload(legal_name=legal_name, member_kind=member_kind,
                              region=region), OP)
    return get_success_data(res)


def create_active_member(**kwargs):
    """Create a member and approve it to ACTIVE."""
    member = create_member(**kwargs)
    res = api_client.approve_member(member["id"], OP)
    return get_success_data(res)


def create_participant_for(sponsor_id, **kwargs):
    """Register a participant under a sponsor (status PENDING_REVIEW)."""
    res = api_client.create_participant(
        create_participant_payload(sponsor_id, **kwargs), SM)
    return get_success_data(res)


def create_active_participant(sponsor_id, **kwargs):
    """Register and approve a participant (status ACTIVE)."""
    participant = create_participant_for(sponsor_id, **kwargs)
    res = api_client.approve_participant(participant["id"], SM)
    return get_success_data(res)


def create_merchant_under_participant(participant_id, **kwargs):
    """Board a merchant under a participant (status ACTIVE)."""
    res = api_client.create_merchant(
        create_merchant_payload(participant_id=participant_id, **kwargs), SM)
    return get_success_data(res)


def create_merchant_under_acquirer(acquirer_member_id, **kwargs):
    """Board a merchant directly under an acquirer member (status ACTIVE)."""
    res = api_client.create_merchant(
        create_merchant_payload(acquirer_member_id=acquirer_member_id,
                                **kwargs), SM)
    return get_success_data(res)


def create_bin_range_for(issuer_id, **kwargs):
    """Request a BIN range for an issuer (status REQUESTED)."""
    res = api_client.create_bin_range(
        create_bin_range_payload(issuer_id, **kwargs), OP)
    return get_success_data(res)


def create_program_for(owner_member_id, **kwargs):
    """Register a program (status REGISTERED)."""
    res = api_client.create_program(
        create_program_payload(owner_member_id, **kwargs), CE)
    return get_success_data(res)


def create_published_rule(rule_code="R-TEST-1", effective_from="2026-09-01T00:00:00Z",
                          fine_schedule=None, headers=None, **overrides):
    """Draft and publish a rule. Returns the PUBLISHED rule."""
    if fine_schedule is None:
        fine_schedule = [{"min_amount_minor": 1, "max_amount_minor": None,
                          "fine_cents": 1000}]
    res = api_client.create_rule(
        create_rule_payload(rule_code, effective_from=effective_from,
                            fine_schedule=fine_schedule, **overrides),
        headers or RA1)
    rule = get_success_data(res)
    res = api_client.publish_rule(rule["id"], headers or RA1)
    return get_success_data(res)


def create_published_rate(effective_from="2026-09-01T00:00:00Z", **overrides):
    """Draft and publish an interchange rate. Returns the PUBLISHED rate."""
    res = api_client.create_interchange_rate(
        create_interchange_rate_payload(effective_from=effective_from,
                                        **overrides), PA)
    rate = get_success_data(res)
    res = api_client.publish_interchange_rate(rate["id"], PA)
    return get_success_data(res)


# ═══════════════════════════════════════════════════════
# Tier 2: hierarchies
# ═══════════════════════════════════════════════════════

def setup_sponsorship_chain(member_kind="BOTH", region=TEST_DEFAULTS["REGION"],
                            **merchant_kwargs):
    """ACTIVE member + ACTIVE sponsored participant + merchant under the
    participant. Returns (member, participant, merchant)."""
    member = create_active_member(member_kind=member_kind, region=region)
    participant = create_active_participant(member["id"])
    merchant = create_merchant_under_participant(participant["id"],
                                                 region=region,
                                                 **merchant_kwargs)
    return member, participant, merchant


def setup_issuer_acquirer_merchant(issuer_region=TEST_DEFAULTS["REGION"],
                                   acquirer_region=TEST_DEFAULTS["REGION"],
                                   **merchant_kwargs):
    """ACTIVE issuer + ACTIVE acquirer + merchant boarded directly under the
    acquirer. Returns (issuer, acquirer, merchant)."""
    issuer = create_active_member(legal_name="Issuer Bank",
                                  member_kind="ISSUER", region=issuer_region)
    acquirer = create_active_member(legal_name="Acquirer Bank",
                                    member_kind="ACQUIRER",
                                    region=acquirer_region)
    merchant = create_merchant_under_acquirer(acquirer["id"],
                                              region=acquirer_region,
                                              **merchant_kwargs)
    return issuer, acquirer, merchant


# ═══════════════════════════════════════════════════════
# Tier 3: program lifecycle shortcuts
# ═══════════════════════════════════════════════════════

def create_program_under_certification(owner_member_id, scope="NEW_PRODUCT",
                                       **program_kwargs):
    """Register a program and submit one certification test run. Returns
    (program, test). The test's evaluated_program_version equals the program's
    post-submission version."""
    program = create_program_for(owner_member_id, **program_kwargs)
    res = api_client.create_certification_test(program["id"], {"scope": scope}, CE)
    test = get_success_data(res)
    program = get_success_data(api_client.get_program(program["id"], CE))
    return program, test


def create_approved_program(owner_member_id, scope="NEW_PRODUCT",
                            **program_kwargs):
    """Program carried through to APPROVED: register, submit test, pass test,
    approve with the OCC version pin. Returns the APPROVED program."""
    program, test = create_program_under_certification(
        owner_member_id, scope=scope, **program_kwargs)
    get_success_data(api_client.pass_certification_test(test["id"], CE))
    program = get_success_data(api_client.get_program(program["id"], CE))
    res = api_client.approve_program(
        program["id"], {"expected_program_version": program["version"]}, CE)
    return get_success_data(res)


def create_production_enabled_program(owner_member_id, scope="NEW_PRODUCT",
                                      **program_kwargs):
    """Program carried through to PRODUCTION_ENABLED."""
    program = create_approved_program(owner_member_id, scope=scope,
                                      **program_kwargs)
    res = api_client.enable_program_production(program["id"], CE)
    return get_success_data(res)


def create_active_bin_range(issuer_id, program_id, **kwargs):
    """Request a BIN range and approve it against a PRODUCTION_ENABLED
    program. Returns the ACTIVE range."""
    bin_range = create_bin_range_for(issuer_id, **kwargs)
    res = api_client.approve_bin_range(bin_range["id"],
                                       {"program_id": program_id}, OP)
    return get_success_data(res)


# ═══════════════════════════════════════════════════════
# Tier 3: violation workflow
# ═══════════════════════════════════════════════════════

def cite_violation(rule_id, subject_member_id, severity="MINOR",
                   transaction_amount_minor=100, citer_id="ra-1"):
    """Cite a violation as a specific RulesAdministrator. Returns CITED
    violation."""
    res = api_client.create_rule_violation(
        create_rule_violation_payload(
            rule_id, subject_member_id, severity=severity,
            transaction_amount_minor=transaction_amount_minor),
        make_rules_admin_headers(citer_id))
    return get_success_data(res)


def assess_violation(violation_id, assessor_id="ra-2"):
    """Assess a violation as a specific RulesAdministrator. Returns ASSESSED
    violation."""
    res = api_client.assess_rule_violation(
        violation_id, make_rules_admin_headers(assessor_id))
    return get_success_data(res)


def setup_member_with_effective_rule_and_violation(
        rule_code="R-V-1", fine_cents=1000, severity="MINOR",
        transaction_amount_minor=100, region=TEST_DEFAULTS["REGION"]):
    """ACTIVE member + published effective rule + one CITED violation.
    Returns (member, rule, violation)."""
    member = create_active_member(region=region)
    rule = create_published_rule(
        rule_code,
        fine_schedule=[{"min_amount_minor": 1, "max_amount_minor": None,
                        "fine_cents": fine_cents}])
    violation = cite_violation(rule["id"], member["id"], severity=severity,
                               transaction_amount_minor=transaction_amount_minor)
    return member, rule, violation


# ═══════════════════════════════════════════════════════
# Tier 3: disputes
# ═══════════════════════════════════════════════════════

def create_open_dispute(transaction_amount_cents=10000, currency="USD",
                        reason_code="10.4", region=TEST_DEFAULTS["REGION"],
                        **merchant_kwargs):
    """Issuer/acquirer/merchant trio plus an OPENED dispute filed by the
    issuer. Returns (issuer, acquirer, merchant, dispute)."""
    issuer, acquirer, merchant = setup_issuer_acquirer_merchant(
        issuer_region=region, acquirer_region=region, **merchant_kwargs)
    res = api_client.create_dispute(
        create_dispute_payload(
            issuer["id"], acquirer["id"], merchant["id"],
            reason_code=reason_code,
            transaction_amount_cents=transaction_amount_cents,
            currency=currency),
        make_member_headers(issuer["id"]))
    dispute = get_success_data(res)
    return issuer, acquirer, merchant, dispute


# ═══════════════════════════════════════════════════════
# Tier 3: settlement
# ═══════════════════════════════════════════════════════

def create_settlement_window(window_date=TEST_DEFAULTS["WINDOW_DATE"],
                             opens_at=TEST_DEFAULTS["WINDOW_OPENS_AT"],
                             closes_at=TEST_DEFAULTS["WINDOW_CLOSES_AT"]):
    """Schedule a settlement window (status SCHEDULED)."""
    res = api_client.create_settlement_window(
        create_settlement_window_payload(window_date=window_date,
                                         opens_at=opens_at,
                                         closes_at=closes_at), SO)
    return get_success_data(res)


def create_open_window(**kwargs):
    """Schedule and open a settlement window (status OPEN)."""
    window = create_settlement_window(**kwargs)
    res = api_client.open_settlement_window(window["id"], SO)
    return get_success_data(res)


def create_draft_line(window_id, from_member_id, to_member_id,
                      amount_cents=1000, currency="USD", reference="ref-1"):
    """Draft a settlement line (status DRAFT)."""
    res = api_client.create_settlement_line(
        create_settlement_line_payload(window_id, from_member_id,
                                       to_member_id, amount_cents=amount_cents,
                                       currency=currency, reference=reference),
        SO)
    return get_success_data(res)


def setup_open_window_with_two_members(**window_kwargs):
    """Two ACTIVE members + one OPEN window covering the default logical
    clock. Returns (member1, member2, window)."""
    m1 = create_active_member(legal_name="Bank One")
    m2 = create_active_member(legal_name="Bank Two")
    window = create_open_window(**window_kwargs)
    return m1, m2, window


# ═══════════════════════════════════════════════════════
# Tier 4: fraud monitoring / threshold targeting
# ═══════════════════════════════════════════════════════

def create_confirmed_fraud_case(merchant_id, reported_by_member_id,
                                fraud_amount_cents):
    """Report and confirm a fraud case. Returns the CONFIRMED case."""
    res = api_client.create_fraud_case(
        create_fraud_case_payload(merchant_id, reported_by_member_id,
                                  fraud_amount_cents=fraud_amount_cents), FA)
    case = get_success_data(res)
    res = api_client.confirm_fraud_case(case["id"], FA)
    return get_success_data(res)


def create_cycle(cycle_label="C1", period_start="2026-09-01T00:00:00Z",
                 period_end="2026-09-16T00:00:00Z"):
    """Schedule a fraud program cycle (status SCHEDULED)."""
    res = api_client.create_fraud_program_cycle(
        create_fraud_program_cycle_payload(cycle_label=cycle_label,
                                           period_start=period_start,
                                           period_end=period_end), FA)
    return get_success_data(res)


def evaluate_cycle(cycle_id):
    """Evaluate a cycle; returns the COMPLETED cycle."""
    res = api_client.evaluate_fraud_program_cycle(cycle_id, FA)
    return get_success_data(res)


def list_cycle_plans(cycle_id):
    """Return the remediation plans spawned by a cycle as a list."""
    res = api_client.list_cycle_remediation_plans(cycle_id, FA)
    return get_success_data(res)


def setup_flagged_merchant_plan(fraud_amount_cents=10000,
                                declared_volume_cents=10000000,
                                via_participant=False):
    """Acquirer + issuer + one merchant whose confirmed fraud meets the
    100 bps merchant threshold, evaluated in a cycle. Returns
    (acquirer, issuer, merchant, cycle, plan)."""
    acquirer = create_active_member(legal_name="Acq Bank", member_kind="ACQUIRER")
    issuer = create_active_member(legal_name="Iss Bank", member_kind="ISSUER")
    if via_participant:
        participant = create_active_participant(acquirer["id"])
        merchant = create_merchant_under_participant(
            participant["id"],
            declared_monthly_volume_cents=declared_volume_cents)
    else:
        merchant = create_merchant_under_acquirer(
            acquirer["id"], declared_monthly_volume_cents=declared_volume_cents)
    create_confirmed_fraud_case(merchant["id"], issuer["id"], fraud_amount_cents)
    cycle = create_cycle()
    set_clock("2026-09-20T00:00:00Z")
    cycle = evaluate_cycle(cycle["id"])
    plans = list_cycle_plans(cycle["id"])
    plan = plans[0] if plans else None
    return acquirer, issuer, merchant, cycle, plan
