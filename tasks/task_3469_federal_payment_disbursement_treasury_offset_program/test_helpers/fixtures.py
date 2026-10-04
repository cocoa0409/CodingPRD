"""Composite setup helpers — multi-step preconditions built from PRD endpoints.

Every helper performs its API calls against the live server and uses the lenient
get_success_data() validator so a setup failure surfaces as a clear error, not a
confusing assertion failure. All temporal preconditions are expressed against the
logical clock (PRD §2.4): helpers that need "30 days after notice" rely on the
default clock 2026-09-01T00:00:00Z plus DEFAULT_NOTICE_SENT_AT (2026-08-01), or
take an explicit clock value — never wall time.

Identity threading: CreditorAnalyst calls always use
make_creditor_analyst_headers(creditor["id"]) (PRD §2.1 entity-backed identity).
Execution defaults to operator "op-1" and refund decisions to officer "ro-1" so
the segregation-of-duties check passes; override the ids to exercise it.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_DEFAULT_UTC,
    DEFAULT_AGREEMENT_WINDOW,
    DEFAULT_DELINQUENT_SINCE,
    DEFAULT_DNP_WINDOW,
    DEFAULT_NOTICE_SENT_AT,
    DEFAULT_SETTLEMENT_DATE,
)
from .factories import (
    create_awg_action_payload,
    create_collection_agency_payload,
    create_creditor_agency_payload,
    create_cross_servicing_action_payload,
    create_debt_payload,
    create_do_not_pay_record_payload,
    create_evaluate_payload,
    create_exemption_policy_payload,
    create_notice_payload,
    create_partial_policy_payload,
    create_payment_file_payload,
    create_payment_payload,
    create_reciprocal_agreement_payload,
    create_refund_claim_payload,
    create_reverse_offset_request_payload,
    create_state_creditor_payload,
)
from .test_users import TEST_USERS, make_creditor_analyst_headers

SUPERVISOR = TEST_USERS["treasury_supervisor_headers"]
OPERATOR = TEST_USERS["treasury_operator_headers"]
AGENCY_ANALYST = TEST_USERS["payment_agency_analyst_headers"]
COORDINATOR = TEST_USERS["state_coordinator_headers"]
OFFICER = TEST_USERS["refund_officer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# =============================================================================
# Tier 0: clock and single-resource creation
# =============================================================================

def set_logical_clock(current_utc=CLOCK_DEFAULT_UTC):
    """Set the logical clock (TreasurySupervisor only, PRD §2.4). Setting the
    clock also runs the settlement sweep and seeds lazy YTD ledger resets."""
    return get_success_data(
        api_client.set_clock({"current_utc": current_utc}, SUPERVISOR)
    )


def create_federal_creditor(**overrides):
    """Register a FEDERAL creditor (ledger counters start at 0, year null)."""
    return get_success_data(
        api_client.create_creditor_agency(
            create_creditor_agency_payload(**overrides), SUPERVISOR
        )
    )


def create_state_creditor(state_code="CA", **overrides):
    """Register a STATE creditor; state_code is required for STATE (PRD §3.1)."""
    return get_success_data(
        api_client.create_creditor_agency(
            create_state_creditor_payload(state_code, **overrides), SUPERVISOR
        )
    )


def register_payee(**overrides):
    """Register a payee. Pass routing_number (non-null) for EFT payments;
    omit it (or pass None) for CHECK (PRD §3.1/§3.4). Default payload carries
    no routing number (CHECK)."""
    from .factories import create_payee_payload
    return get_success_data(
        api_client.create_payee(create_payee_payload(**overrides), OPERATOR)
    )


def register_eft_payee(**overrides):
    """Register a payee with a routing number: its payments disburse by EFT."""
    from .factories import create_eft_payee_payload
    return get_success_data(
        api_client.create_payee(create_eft_payee_payload(**overrides), OPERATOR)
    )


def create_draft_policy(payment_type="VENDOR", exemption_class="FULL",
                        **overrides):
    """Create (but do not activate) an ExemptionPolicy."""
    if exemption_class == "PARTIAL":
        payload = create_partial_policy_payload(payment_type, **overrides)
    else:
        payload = create_exemption_policy_payload(
            payment_type=payment_type, exemption_class=exemption_class, **overrides
        )
    return get_success_data(api_client.create_exemption_policy(payload, SUPERVISOR))


def activate_policy(policy):
    """DRAFT -> ACTIVE; supersedes (RETIRES) the incumbent ACTIVE policy for the
    same payment_type (PRD §3.2)."""
    return get_success_data(
        api_client.activate_exemption_policy(policy["id"], SUPERVISOR)
    )


def create_active_policy(payment_type="VENDOR", exemption_class="FULL",
                         **overrides):
    """Create + activate; the returned policy is ACTIVE."""
    return activate_policy(
        create_draft_policy(payment_type, exemption_class, **overrides)
    )


def register_collection_agency(**overrides):
    return get_success_data(
        api_client.create_collection_agency(
            create_collection_agency_payload(**overrides), SUPERVISOR
        )
    )


# =============================================================================
# Tier 1: state progression
# =============================================================================

def refer_debt(creditor, **overrides):
    """Refer a debt as the owning creditor's CreditorAnalyst. Without
    notice_sent_at the debt starts REFERRED; with it, NOTICED (PRD §3.3)."""
    headers = make_creditor_analyst_headers(creditor["id"])
    return get_success_data(
        api_client.create_debt(
            create_debt_payload(creditor["id"], **overrides), headers
        )
    )


def record_notice(debt, creditor, **overrides):
    """REFERRED or RETURNED -> NOTICED; writes a fresh notice window (PRD §3.3)."""
    headers = make_creditor_analyst_headers(creditor["id"])
    return get_success_data(
        api_client.notice_debt(debt["id"], create_notice_payload(**overrides),
                               headers)
    )


def activate_debt(debt, creditor):
    """NOTICED -> ACTIVE. Caller is responsible for the due-process / 30-day
    notice-window / reciprocal-agreement gates being satisfiable (the defaults
    in this module satisfy the first two at the default clock; the third needs
    an ACTIVE FED_TO_STATE-scoped agreement for STATE creditors)."""
    headers = make_creditor_analyst_headers(creditor["id"])
    return get_success_data(api_client.activate_debt(debt["id"], headers))


def create_active_debt(creditor, notice_sent_at=DEFAULT_NOTICE_SENT_AT,
                       due_process_completed=True, ensure_agreement=False,
                       **overrides):
    """Full referral -> NOTICED -> ACTIVE walk via the notice-at-intake shortcut.

    notice_sent_at defaults to 2026-08-01T00:00:00Z, exactly 31 days before the
    default clock (2026-09-01T00:00:00Z), so the 30-day window has elapsed.
    For a STATE creditor pass ensure_agreement=True to first create + activate a
    covering FED_TO_STATE agreement over the default window (PRD §3.3 gate)."""
    if ensure_agreement and creditor.get("creditor_type") == "STATE":
        create_active_agreement(creditor["state_code"], "FED_TO_STATE")
    debt = refer_debt(
        creditor,
        notice_sent_at=notice_sent_at,
        due_process_completed=due_process_completed,
        **overrides,
    )
    return activate_debt(debt, creditor)


def create_active_agreement(state_code="WA", direction="STATE_TO_FED",
                            window=DEFAULT_AGREEMENT_WINDOW, **overrides):
    """Create + activate a reciprocal agreement; covers the default clock window
    [2026-01-01, 2027-01-01) unless overridden (PRD §2.10)."""
    payload = create_reciprocal_agreement_payload(
        state_code=state_code,
        direction=direction,
        effective_from=window[0],
        effective_until=window[1],
        **overrides,
    )
    agreement = get_success_data(
        api_client.create_reciprocal_agreement(payload, SUPERVISOR)
    )
    return get_success_data(
        api_client.activate_reciprocal_agreement(agreement["id"], SUPERVISOR)
    )


def create_payment_file(**overrides):
    return get_success_data(
        api_client.create_payment_file(
            create_payment_file_payload(**overrides), AGENCY_ANALYST
        )
    )


def add_payment(payment_file, payee, amount_cents=30000, payment_type="SALARY",
                **overrides):
    """Add a payment to a file (intake runs payee verification, payment-method
    determination, the do-not-pay scan, and the intake projection). Requires an
    ACTIVE ExemptionPolicy for payment_type (PRD §3.4)."""
    return get_success_data(
        api_client.create_payment(
            payment_file["id"],
            create_payment_payload(payee, amount_cents, payment_type, **overrides),
            AGENCY_ANALYST,
        )
    )


def evaluate_payment(payment, operator_headers=None):
    """VERIFIED/EVALUATED -> EVALUATED with OCC: the fresh version is read off
    the payment passed in, and the response carries the bumped version."""
    return get_success_data(
        api_client.evaluate_offsets(
            payment["id"],
            create_evaluate_payload(payment["version"]),
            operator_headers or OPERATOR,
        )
    )


def execute_payment(payment, operator_headers=None):
    """EVALUATED -> EXECUTED: offsets APPLIED, fees assessed, ledger credited,
    executed_by_user_id stamped from the operator's X-User-ID (PRD §3.5)."""
    return get_success_data(
        api_client.execute_payment(payment["id"], operator_headers or OPERATOR)
    )


def reverse_payment(payment, operator_headers=None):
    """EXECUTED -> REVERSED with the depth-3 restoration cascade (PRD §3.5)."""
    return get_success_data(
        api_client.reverse_payment(payment["id"], operator_headers or OPERATOR)
    )


def create_awg_action(debt, **overrides):
    """Open an AWG action on an ACTIVE debt (debt flips to IN_COLLECTION);
    projected_per_period_cents = round_half_up(0.15 * estimate) (PRD §3.7)."""
    return get_success_data(
        api_client.create_collection_action(
            debt["id"], create_awg_action_payload(**overrides), OPERATOR
        )
    )


def create_cross_servicing_action(debt, **overrides):
    """Open a CROSS_SERVICING action; the selector assigns collection_agency_id
    from the eligible agency pool (PRD §3.7). Pool must be non-empty."""
    return get_success_data(
        api_client.create_collection_action(
            debt["id"], create_cross_servicing_action_payload(**overrides),
            OPERATOR,
        )
    )


def activate_action(action):
    """INITIATED -> ACTIVE. For AWG the caller must ensure the 15-day hearing
    window has elapsed at the current clock (default notice 2026-08-01 satisfies
    this at the default clock); CROSS_SERVICING has no waiting period."""
    return get_success_data(
        api_client.activate_collection_action(action["id"], OPERATOR)
    )


def collect_awg(action, debt_id, disposable_pay_cents, operator_headers=None):
    """Record an AWG collection event. The debt is re-read for the OCC token so
    a plain sequential collect always carries the current version."""
    debt_now = read_debt(debt_id)
    updated = get_success_data(
        api_client.collect_collection_action(
            action["id"],
            {"expected_debt_version": debt_now["version"],
             "disposable_pay_cents": disposable_pay_cents},
            operator_headers or OPERATOR,
        )
    )
    return updated


def collect_cross_servicing(action, debt_id, remitted_amount_cents,
                            operator_headers=None):
    """Record a cross-servicing remittance (0 < amount <= current balance)."""
    debt_now = read_debt(debt_id)
    return get_success_data(
        api_client.collect_collection_action(
            action["id"],
            {"expected_debt_version": debt_now["version"],
             "remitted_amount_cents": remitted_amount_cents},
            operator_headers or OPERATOR,
        )
    )


def terminate_action(action):
    """INITIATED/ACTIVE -> TERMINATED; the debt returns to ACTIVE (PRD §3.7)."""
    return get_success_data(
        api_client.terminate_collection_action(action["id"], OPERATOR)
    )


def create_dnp_record(tin, window=DEFAULT_DNP_WINDOW,
                      list_source="SAM_EXCLUSION", **overrides):
    """List a TIN on a do-not-pay source over a closed interval; creation runs
    the flag/hold cascade over pre-execution payments of that TIN (PRD §3.9)."""
    return get_success_data(
        api_client.create_do_not_pay_record(
            create_do_not_pay_record_payload(
                tin, list_source=list_source,
                effective_from=window[0], effective_until=window[1], **overrides
            ),
            OPERATOR,
        )
    )


def remove_dnp_record(record):
    """ACTIVE -> REMOVED; runs the release cascade over HELD payments (PRD §3.9)."""
    return get_success_data(
        api_client.remove_do_not_pay_record(record["id"], SUPERVISOR)
    )


def create_reverse_request(state_code="WA", payee_tin="111-22-3333",
                           requested_amount_cents=50000, **overrides):
    """State reverse-offset request; starts MATCHED or NO_MATCH (PRD §3.8).
    Requires a covering ACTIVE STATE_TO_FED/BIDIRECTIONAL agreement."""
    return get_success_data(
        api_client.create_reverse_offset_request(
            create_reverse_offset_request_payload(
                state_code=state_code, payee_tin=payee_tin,
                requested_amount_cents=requested_amount_cents, **overrides
            ),
            COORDINATOR,
        )
    )


def confirm_reverse_request(request):
    """MATCHED -> CONFIRMED: matches re-capped to current balances and applied
    net of fee; after expires_at this flips the request to EXPIRED (PRD §3.8)."""
    return get_success_data(
        api_client.confirm_reverse_offset_request(request["id"], COORDINATOR)
    )


def file_refund_claim(offset, claimed_amount_cents=None, reason="DEBT_NOT_OWED",
                      operator_headers=None):
    """File a refund claim against an APPLIED offset (must be within 180 days of
    Offset.applied_at). Default claim is the full offset amount (PRD §3.6)."""
    if claimed_amount_cents is None:
        claimed_amount_cents = offset["offset_amount_cents"]
    return get_success_data(
        api_client.create_refund_claim(
            create_refund_claim_payload(
                offset["id"], claimed_amount_cents, reason
            ),
            operator_headers or OPERATOR,
        )
    )


def review_claim(claim, officer_headers=None):
    """FILED or APPEALED -> UNDER_REVIEW (RefundOfficer)."""
    return get_success_data(
        api_client.review_refund_claim(
            claim["id"], officer_headers or OFFICER
        )
    )


def decide_claim(claim, decision="APPROVE", officer_headers=None):
    """UNDER_REVIEW -> PAID (clawback cascade) or DENIED. The deciding officer's
    X-User-ID must differ from the executing operator's (PRD §3.6)."""
    return get_success_data(
        api_client.decide_refund_claim(
            claim["id"], {"decision": decision}, officer_headers or OFFICER
        )
    )


def appeal_claim(claim, operator_headers=None):
    """DENIED -> APPEALED; at most one appeal, within 30 days of decided_at."""
    return get_success_data(
        api_client.appeal_refund_claim(
            claim["id"], operator_headers or OPERATOR
        )
    )


# =============================================================================
# Tier 2: read-backs (Auditor) and offset listing
# =============================================================================

def read_creditor(creditor_id):
    return get_success_data(api_client.get_creditor_agency(creditor_id, AUDITOR))


def read_debt(debt_id):
    return get_success_data(api_client.get_debt(debt_id, AUDITOR))


def read_payment(payment_id):
    return get_success_data(api_client.get_payment(payment_id, AUDITOR))


def read_payment_file(payment_file_id):
    return get_success_data(api_client.get_payment_file(payment_file_id, AUDITOR))


def read_offset(offset_id):
    return get_success_data(api_client.get_offset(offset_id, AUDITOR))


def read_refund_claim(refund_claim_id):
    return get_success_data(api_client.get_refund_claim(refund_claim_id, AUDITOR))


def read_collection_action(collection_action_id):
    return get_success_data(
        api_client.get_collection_action(collection_action_id, AUDITOR)
    )


def list_payment_offsets(payment_id, status=None):
    """All offsets of a payment, optionally status-filtered (PRD §3.4 filters)."""
    params = {"payment_id": payment_id, "limit": 100}
    if status is not None:
        params["status"] = status
    return get_success_data(api_client.list_offsets(AUDITOR, params=params))


def list_debt_collection_actions(debt_id):
    params = {"debt_id": debt_id, "limit": 100}
    return get_success_data(
        api_client.list_collection_actions(AUDITOR, params=params)
    )


# =============================================================================
# Tier 3: full-lifecycle composites (the workhorse fixtures)
# =============================================================================

def setup_creditor_with_active_debt(creditor=None, set_clock=True,
                                    **debt_overrides):
    """Federal creditor + one ACTIVE debt (defaults: 50000-cent FEDERAL_NONTAX
    for tin 111-22-3333). Pass an existing creditor dict to add a second debt,
    and pass debtor_tin/debt_type/original_amount_cents/delinquent_since via
    debt_overrides. Returns (creditor, debt)."""
    if set_clock:
        set_logical_clock()
    if creditor is None:
        creditor = create_federal_creditor()
    debt = create_active_debt(creditor, **debt_overrides)
    return creditor, debt


def setup_evaluated_payment(amount_cents=30000, debt_amount_cents=50000,
                            payment_type="SALARY", exemption_class="FULL",
                            policy_overrides=None, tin="111-22-3333",
                            payee_overrides=None, file_overrides=None,
                            debt_overrides=None, creditor=None, payee=None,
                            set_clock=True, evaluate=True):
    """Creditor + EFT payee + ACTIVE policy + ACTIVE debt + file + payment,
    optionally advanced to EVALUATED. Returns a namespace dict with keys:
    creditor, payee, policy, debt, payment_file, payment, offsets (PROPOSED)."""
    if set_clock:
        set_logical_clock()
    if creditor is None:
        creditor = create_federal_creditor()
    if payee is None:
        payee = register_eft_payee(tin=tin, **(payee_overrides or {}))
    policy = create_active_policy(
        payment_type, exemption_class, **(policy_overrides or {})
    )
    debt_kwargs = {"original_amount_cents": debt_amount_cents, "debtor_tin": tin}
    debt_kwargs.update(debt_overrides or {})
    debt = create_active_debt(creditor, **debt_kwargs)
    payment_file = create_payment_file(**(file_overrides or {}))
    payment = add_payment(payment_file, payee, amount_cents, payment_type)
    offsets = []
    if evaluate:
        payment = evaluate_payment(payment)
        offsets = list_payment_offsets(payment["id"])
    return {
        "creditor": creditor,
        "payee": payee,
        "policy": policy,
        "debt": debt,
        "payment_file": payment_file,
        "payment": payment,
        "offsets": offsets,
    }


def setup_applied_offset(amount_cents=30000, debt_amount_cents=50000,
                         payment_type="SALARY", exemption_class="FULL",
                         operator_headers=None, **kwargs):
    """setup_evaluated_payment + execute. Returns the namespace plus:
    payment (EXECUTED, post-execute read-back), offsets (APPLIED), offset (the
    first). The executing operator defaults to "op-1" (TEST_USERS
    treasury_operator_headers) so refund decisions by "ro-1" satisfy segregation
    of duties (PRD §3.6)."""
    ns = setup_evaluated_payment(
        amount_cents=amount_cents, debt_amount_cents=debt_amount_cents,
        payment_type=payment_type, exemption_class=exemption_class, **kwargs
    )
    execute_payment(ns["payment"], operator_headers=operator_headers)
    ns["payment"] = read_payment(ns["payment"]["id"])
    ns["offsets"] = list_payment_offsets(ns["payment"]["id"])
    ns["offset"] = ns["offsets"][0] if ns["offsets"] else None
    return ns


def setup_settled_payment(settlement_date=DEFAULT_SETTLEMENT_DATE,
                          settle_clock=None, **kwargs):
    """Full execution + settlement sweep: the clock is advanced to the file's
    settlement_date so the EXECUTED payment flips to SETTLED and the file may
    bubble to COMPLETED (PRD §2.4/§3.5). Returns the setup_applied_offset
    namespace with payment re-read post-sweep."""
    file_overrides = dict(kwargs.pop("file_overrides", None) or {})
    file_overrides.setdefault("settlement_date", settlement_date)
    ns = setup_applied_offset(file_overrides=file_overrides, **kwargs)
    set_logical_clock(settle_clock or settlement_date)
    ns["payment"] = read_payment(ns["payment"]["id"])
    ns["payment_file"] = read_payment_file(ns["payment_file"]["id"])
    return ns


def setup_claim_under_review(claimed_amount_cents=None, reason="DEBT_NOT_OWED",
                             officer_headers=None, **kwargs):
    """Applied offset + FILED claim + review. Namespace gains claim
    (UNDER_REVIEW)."""
    ns = setup_applied_offset(**kwargs)
    claim = file_refund_claim(ns["offset"], claimed_amount_cents, reason)
    ns["claim"] = review_claim(claim, officer_headers=officer_headers)
    return ns


def setup_decided_claim(decision="APPROVE", officer_headers=None, **kwargs):
    """Claim decided from UNDER_REVIEW. Namespace gains claim (PAID or DENIED);
    on APPROVE the offset is REFUNDED and the debt RETURNED (PRD §3.6)."""
    ns = setup_claim_under_review(**kwargs)
    ns["claim"] = decide_claim(
        ns["claim"], decision, officer_headers=officer_headers
    )
    ns["offset"] = read_offset(ns["offset"]["id"])
    ns["debt"] = read_debt(ns["debt"]["id"])
    ns["creditor"] = read_creditor(ns["creditor"]["id"])
    return ns


def setup_denied_claim(**kwargs):
    """Convenience: a claim decided DENY (DENIED, appeal_count 0)."""
    return setup_decided_claim(decision="DENY", **kwargs)


def setup_paid_claim(**kwargs):
    """Convenience: a claim decided APPROVE (PAID; clawback cascade applied)."""
    return setup_decided_claim(decision="APPROVE", **kwargs)


# =============================================================================
# Tier 4: accumulation / selector targeting
# =============================================================================

def execute_payment_sequence(creditor, payee, payment_type, amounts,
                             payment_file=None, operator_headers=None):
    """Evaluate + execute one payment per amount, strictly in order, against the
    same creditor's ledger — the fixture for fee-tier YTD accumulation (PRD §2.9:
    each event's tier reads the pre-event gross). Returns [(payment, offsets)]."""
    if payment_file is None:
        payment_file = create_payment_file()
    results = []
    for amount in amounts:
        payment = add_payment(payment_file, payee, amount, payment_type)
        payment = evaluate_payment(payment)
        execute_payment(payment, operator_headers=operator_headers)
        payment = read_payment(payment["id"])
        results.append((payment, list_payment_offsets(payment["id"])))
    return results


def setup_agency_pool(capacities=(5, 10, 10)):
    """Register collection agencies in order with the given capacities; returns
    the created agencies in registration order (created_at ascending) — the
    selector ranks by open count ASC, spare capacity DESC, created_at ASC
    (PRD §3.7)."""
    return [
        register_collection_agency(capacity_max_active=cap) for cap in capacities
    ]


def setup_active_collection_action(action_type="AWG", debt_amount_cents=100000,
                                   creditor=None, set_clock=True,
                                   agency_capacities=None,
                                   awg_estimate_cents=25000,
                                   awg_notice_sent_at=DEFAULT_NOTICE_SENT_AT,
                                   **debt_overrides):
    """Creditor + ACTIVE debt + one collection action walked to ACTIVE.
    For CROSS_SERVICING, agencies are registered from agency_capacities
    (default [5]). Returns (creditor, debt, action)."""
    creditor, debt = setup_creditor_with_active_debt(
        creditor=creditor, set_clock=set_clock,
        original_amount_cents=debt_amount_cents, **debt_overrides
    )
    if action_type == "AWG":
        action = create_awg_action(
            debt, notice_sent_at=awg_notice_sent_at,
            disposable_pay_estimate_cents=awg_estimate_cents,
        )
    else:
        setup_agency_pool(agency_capacities or (5,))
        action = create_cross_servicing_action(debt)
    action = activate_action(action)
    return creditor, debt, action


# =============================================================================
# Tier 5: reverse-offset composite
# =============================================================================

def setup_reverse_request(state_code="WA", direction="STATE_TO_FED",
                          debt_specs=((30000, "FEDERAL_TAX", "2026-01-10T00:00:00Z"),),
                          payee_tin="111-22-3333", requested_amount_cents=50000,
                          window=DEFAULT_AGREEMENT_WINDOW, set_clock=True):
    """Covering ACTIVE agreement + federal creditor with ACTIVE debts (one per
    (amount, debt_type, delinquent_since) in debt_specs) + a created
    ReverseOffsetRequest. Returns a namespace: agreement, creditor, debts,
    request (MATCHED or NO_MATCH)."""
    if set_clock:
        set_logical_clock()
    agreement = create_active_agreement(state_code, direction, window=window)
    creditor = create_federal_creditor()
    debts = [
        create_active_debt(
            creditor,
            original_amount_cents=amount,
            debt_type=debt_type,
            delinquent_since=delinquent_since,
            debtor_tin=payee_tin,
        )
        for amount, debt_type, delinquent_since in debt_specs
    ]
    request = create_reverse_request(state_code, payee_tin,
                                     requested_amount_cents)
    return {
        "agreement": agreement,
        "creditor": creditor,
        "debts": debts,
        "request": request,
    }


__all__ = [
    # clock / tier 0
    "set_logical_clock",
    "create_federal_creditor", "create_state_creditor",
    "register_payee", "register_eft_payee",
    "create_draft_policy", "activate_policy", "create_active_policy",
    "register_collection_agency",
    # tier 1: state progression
    "refer_debt", "record_notice", "activate_debt", "create_active_debt",
    "create_active_agreement",
    "create_payment_file", "add_payment",
    "evaluate_payment", "execute_payment", "reverse_payment",
    "create_awg_action", "create_cross_servicing_action",
    "activate_action", "collect_awg", "collect_cross_servicing",
    "terminate_action",
    "create_dnp_record", "remove_dnp_record",
    "create_reverse_request", "confirm_reverse_request",
    "file_refund_claim", "review_claim", "decide_claim", "appeal_claim",
    # tier 2: read-backs
    "read_creditor", "read_debt", "read_payment", "read_payment_file",
    "read_offset", "read_refund_claim", "read_collection_action",
    "list_payment_offsets", "list_debt_collection_actions",
    # tier 3: composites
    "setup_creditor_with_active_debt", "setup_evaluated_payment",
    "setup_applied_offset", "setup_settled_payment",
    "setup_claim_under_review", "setup_decided_claim",
    "setup_denied_claim", "setup_paid_claim",
    # tier 4: accumulation / selector
    "execute_payment_sequence", "setup_agency_pool",
    "setup_active_collection_action",
    # tier 5: reverse offset
    "setup_reverse_request",
]
