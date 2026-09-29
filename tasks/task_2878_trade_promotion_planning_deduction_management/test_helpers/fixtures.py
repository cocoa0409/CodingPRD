"""
Composite setup helpers for the Trade Promotion Deductions API.

Every helper builds its preconditions exclusively out of PRD-declared endpoints,
because each test runs against an empty database. Helpers are grouped in five
tiers: single-entity state progression, entity hierarchy, full-lifecycle
shortcuts, accumulation and threshold targeting, and terminal states.

Setup calls go through `get_success_data`, which accepts any 2xx and raises a
readable error naming the refused rule, so a broken precondition is obvious.
Every helper accepts `**overrides` that are forwarded to the payload factory of
the entity it creates.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import (
    DEFAULT_CLOCK_INSTANT,
    MONDAY_AUG_03,
    MONDAY_AUG_10,
    MONDAY_AUG_17,
    MONDAY_AUG_31,
    MONDAY_SEP_07,
    instant,
    instant_plus_days,
)
from .factories import (
    analyze_promotion_payload,
    cancel_tactic_payload,
    create_accrual_payload,
    create_allocation_payload,
    create_brand_payload,
    create_commitment_document_payload,
    create_compliance_audit_payload,
    create_customer_payload,
    create_deduction_payload,
    create_display_tactic_payload,
    create_dispute_payload,
    create_evidence_document_payload,
    create_feature_tactic_payload,
    create_program_payload,
    create_promotion_payload,
    create_tactic_payload,
    create_tpr_tactic_payload,
    create_volume_fact_payload,
    credit_hold_payload,
    match_deduction_payload,
    record_audit_finding_payload,
    record_recovery_payload,
    request_changes_payload,
    retailer_respond_payload,
    reverse_accrual_payload,
    send_to_retailer_payload,
    validate_deduction_payload,
    withdraw_promotion_payload,
    write_off_payload,
)
from .test_users import (
    ANALYST_HEADERS,
    AUDITOR_HEADERS,
    DIRECTOR_HEADERS,
    KAM_HEADERS,
    SPECIALIST_HEADERS,
    make_portal_user_headers,
)
from .types import (
    AccrualMethod,
    BaselineMethod,
    DeductionValidationPolicy,
    DocClass,
    FactType,
    TacticType,
)


# ─── Logical clock ────────────────────────────────────

def set_clock(api: ApiClient, current_utc: str,
              headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Move the logical clock to an explicit UTC instant."""
    response = api.set_clock(current_utc, headers or ANALYST_HEADERS)
    return get_success_data(response)


def reset_clock(api: ApiClient) -> Dict[str, Any]:
    """Return the logical clock to the instant it starts at."""
    return set_clock(api, DEFAULT_CLOCK_INSTANT)


# ═══ Tier 1 — single-entity state progression ═════════

def setup_program(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """An `OPEN` trade program."""
    response = api.create_program(create_program_payload(**overrides), DIRECTOR_HEADERS)
    return get_success_data(response, 201)


def setup_locked_program(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """A program taken through the terminal year-end lock."""
    program = setup_program(api, **overrides)
    response = api.lock_program(program["id"], DIRECTOR_HEADERS)
    return get_success_data(response)


def setup_brand(api: ApiClient, program_id: str, **overrides: Any) -> Dict[str, Any]:
    """A brand registered under the named program."""
    response = api.create_brand(create_brand_payload(program_id, **overrides),
                               DIRECTOR_HEADERS)
    return get_success_data(response, 201)


def setup_customer(api: ApiClient, program_id: str, **overrides: Any) -> Dict[str, Any]:
    """A retail customer registered under the named program."""
    response = api.create_customer(create_customer_payload(program_id, **overrides),
                                   DIRECTOR_HEADERS)
    return get_success_data(response, 201)


def setup_customer_on_credit_hold(api: ApiClient, program_id: str,
                                  reason: str = "Remittance shortfall under review",
                                  **overrides: Any) -> Dict[str, Any]:
    """A customer moved by hand from `ACTIVE` to `CREDIT_HOLD`."""
    customer = setup_customer(api, program_id, **overrides)
    response = api.place_customer_credit_hold(
        customer["id"], credit_hold_payload(reason=reason), SPECIALIST_HEADERS
    )
    return get_success_data(response)


def setup_draft_allocation(api: ApiClient, program_id: str, customer_id: str,
                           brand_id: str, **overrides: Any) -> Dict[str, Any]:
    """A `DRAFT` budget allocation with an untouched ledger."""
    response = api.create_budget_allocation(
        create_allocation_payload(program_id, customer_id, brand_id, **overrides),
        DIRECTOR_HEADERS,
    )
    return get_success_data(response, 201)


def setup_approved_allocation(api: ApiClient, program_id: str, customer_id: str,
                              brand_id: str, **overrides: Any) -> Dict[str, Any]:
    """An `APPROVED` allocation, the gate promotion planning needs."""
    allocation = setup_draft_allocation(api, program_id, customer_id, brand_id, **overrides)
    response = api.approve_budget_allocation(allocation["id"], DIRECTOR_HEADERS)
    return get_success_data(response)


def setup_volume_fact(api: ApiClient, customer_id: str, brand_id: str,
                      **overrides: Any) -> Dict[str, Any]:
    """One week of shipment or consumption volume in the append-only journal."""
    response = api.create_volume_fact(
        create_volume_fact_payload(customer_id, brand_id, **overrides), ANALYST_HEADERS
    )
    return get_success_data(response, 201)


def setup_volume_facts(api: ApiClient, customer_id: str, brand_id: str,
                       weeks: Dict[str, int], fact_type: str = FactType.CONSUMPTION.value,
                       source: str = "EDI_852") -> List[Dict[str, Any]]:
    """A run of weekly facts, one per Monday in the supplied week/units mapping."""
    rows = []
    for period_start, units in weeks.items():
        rows.append(
            setup_volume_fact(
                api, customer_id, brand_id,
                fact_type=fact_type, period_start=period_start,
                units=units, source=source,
            )
        )
    return rows


def current_allocation_version(api: ApiClient, allocation_id: str,
                              headers: Optional[Dict[str, str]] = None) -> int:
    """The allocation's live `version`, for the promotion create OCC field."""
    data = get_success_data(api.get_budget_allocation(allocation_id,
                                                      headers or DIRECTOR_HEADERS))
    return data["version"]


def current_promotion_version(api: ApiClient, promotion_id: str,
                             headers: Optional[Dict[str, str]] = None) -> int:
    """The promotion's live `version`, for the validate and patch OCC field."""
    data = get_success_data(api.get_promotion(promotion_id, headers or DIRECTOR_HEADERS))
    return data["version"]


def read_program(api: ApiClient, program_id: str,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Read a program with its live budget rollup."""
    return get_success_data(api.get_program(program_id, headers or DIRECTOR_HEADERS))


def read_allocation(api: ApiClient, allocation_id: str,
                    headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Read an allocation with its live ledger rollup and posture."""
    return get_success_data(api.get_budget_allocation(allocation_id,
                                                      headers or DIRECTOR_HEADERS))


def read_promotion(api: ApiClient, promotion_id: str,
                   headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Read a promotion with its planning figures and live spend monitor."""
    return get_success_data(api.get_promotion(promotion_id, headers or DIRECTOR_HEADERS))


def read_customer(api: ApiClient, customer_id: str,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Read a customer with its penalty score and deduction rollups."""
    return get_success_data(api.get_customer(customer_id, headers or DIRECTOR_HEADERS))


def read_deduction(api: ApiClient, deduction_id: str,
                   headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Read a deduction with its valuation figures."""
    return get_success_data(api.get_deduction(deduction_id, headers or SPECIALIST_HEADERS))


def read_dispute(api: ApiClient, dispute_id: str,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Read a dispute with its live aging figure."""
    return get_success_data(api.get_dispute(dispute_id, headers or SPECIALIST_HEADERS))


def read_tactic(api: ApiClient, tactic_id: str,
                headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Read one tactic line."""
    return get_success_data(api.get_tactic(tactic_id, headers or KAM_HEADERS))


def read_accrual(api: ApiClient, accrual_id: str,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Read one accrual ledger entry with its per-tactic breakdown."""
    return get_success_data(api.get_accrual(accrual_id, headers or ANALYST_HEADERS))


def read_analysis(api: ApiClient, analysis_id: str,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Read one post-event analysis with its live lift and ROI figures."""
    return get_success_data(api.get_post_event_analysis(analysis_id,
                                                        headers or ANALYST_HEADERS))


def read_audit(api: ApiClient, audit_id: str,
               headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Read one compliance audit."""
    return get_success_data(api.get_compliance_audit(audit_id, headers or AUDITOR_HEADERS))


# ═══ Tier 2 — entity hierarchy ═════════════════════════

def setup_reference_data(api: ApiClient, program_overrides: Optional[Dict[str, Any]] = None,
                         brand_overrides: Optional[Dict[str, Any]] = None,
                         customer_overrides: Optional[Dict[str, Any]] = None,
                         **overrides: Any) -> Dict[str, Any]:
    """
    A program with one brand and one customer registered under it.

    Returns the keys `program`, `brand` and `customer`.
    """
    program = setup_program(api, **(program_overrides or {}))
    brand = setup_brand(api, program["id"], **(brand_overrides or {}))
    customer = setup_customer(api, program["id"], **(customer_overrides or {}))
    return {"program": program, "brand": brand, "customer": customer, **overrides}


def setup_allocation_context(api: ApiClient, approve: bool = True,
                             program_overrides: Optional[Dict[str, Any]] = None,
                             brand_overrides: Optional[Dict[str, Any]] = None,
                             customer_overrides: Optional[Dict[str, Any]] = None,
                             **overrides: Any) -> Dict[str, Any]:
    """
    Reference data plus one budget allocation, approved by default.

    Returns `program`, `brand`, `customer` and `allocation`.
    """
    context = setup_reference_data(
        api,
        program_overrides=program_overrides,
        brand_overrides=brand_overrides,
        customer_overrides=customer_overrides,
    )
    builder = setup_approved_allocation if approve else setup_draft_allocation
    context["allocation"] = builder(
        api, context["program"]["id"], context["customer"]["id"],
        context["brand"]["id"], **overrides,
    )
    return context


def setup_second_allocation(api: ApiClient, context: Dict[str, Any], approve: bool = True,
                            **overrides: Any) -> Dict[str, Any]:
    """A sibling allocation cell under the same program, brand and customer."""
    builder = setup_approved_allocation if approve else setup_draft_allocation
    return builder(
        api, context["program"]["id"], context["customer"]["id"],
        context["brand"]["id"], **overrides,
    )


def setup_draft_promotion(api: ApiClient, context: Optional[Dict[str, Any]] = None,
                          allocation_id: Optional[str] = None,
                          **overrides: Any) -> Dict[str, Any]:
    """
    A `DRAFT` promotion under an `APPROVED` allocation.

    When no context is supplied one is built. Returns the caller's context with
    a `promotion` key added.
    """
    context = context if context is not None else setup_allocation_context(api)
    target = allocation_id or context["allocation"]["id"]
    expected_version = current_allocation_version(api, target)
    response = api.create_promotion(
        create_promotion_payload(target, expected_version, **overrides), KAM_HEADERS
    )
    context["promotion"] = get_success_data(response, 201)
    return context


def setup_tactic(api: ApiClient, promotion_id: str,
                 tactic_type: str = TacticType.TPR.value, **overrides: Any) -> Dict[str, Any]:
    """One tactic line on a `DRAFT` promotion."""
    response = api.create_tactic(
        promotion_id, create_tactic_payload(tactic_type, **overrides), KAM_HEADERS
    )
    return get_success_data(response, 201)


def setup_promotion_with_tpr_line(api: ApiClient, context: Optional[Dict[str, Any]] = None,
                                  promotion_overrides: Optional[Dict[str, Any]] = None,
                                  **tactic_overrides: Any) -> Dict[str, Any]:
    """
    A `DRAFT` promotion carrying one `TPR` line.

    A promotion with only `TPR` lines has an empty required commitment set, so
    its `commitment_verified` is true with no paperwork at all.
    """
    context = setup_draft_promotion(api, context, **(promotion_overrides or {}))
    context["tactic"] = setup_tactic(
        api, context["promotion"]["id"], TacticType.TPR.value, **tactic_overrides
    )
    context["promotion"] = read_promotion(api, context["promotion"]["id"])
    return context


def setup_promotion_with_display_line(api: ApiClient,
                                      context: Optional[Dict[str, Any]] = None,
                                      promotion_overrides: Optional[Dict[str, Any]] = None,
                                      **tactic_overrides: Any) -> Dict[str, Any]:
    """A `DRAFT` promotion carrying one `DISPLAY` line, which requires paperwork."""
    context = setup_draft_promotion(api, context, **(promotion_overrides or {}))
    context["tactic"] = setup_tactic(
        api, context["promotion"]["id"], TacticType.DISPLAY.value, **tactic_overrides
    )
    context["promotion"] = read_promotion(api, context["promotion"]["id"])
    return context


def setup_promotion_with_feature_line(api: ApiClient,
                                      context: Optional[Dict[str, Any]] = None,
                                      promotion_overrides: Optional[Dict[str, Any]] = None,
                                      **tactic_overrides: Any) -> Dict[str, Any]:
    """A `DRAFT` promotion carrying one `FEATURE` line."""
    context = setup_draft_promotion(api, context, **(promotion_overrides or {}))
    context["tactic"] = setup_tactic(
        api, context["promotion"]["id"], TacticType.FEATURE.value, **tactic_overrides
    )
    context["promotion"] = read_promotion(api, context["promotion"]["id"])
    return context


def setup_promotion_with_lines(api: ApiClient, context: Optional[Dict[str, Any]] = None,
                               lines: Optional[List[Dict[str, Any]]] = None,
                               promotion_overrides: Optional[Dict[str, Any]] = None
                               ) -> Dict[str, Any]:
    """
    A `DRAFT` promotion carrying the supplied tactic lines in order.

    Each entry of `lines` is a payload-override mapping that must name its
    `tactic_type`. Lines are created in list order, so `created_at` ascending
    order matches the list order the accrual breakdown will use.
    """
    context = setup_draft_promotion(api, context, **(promotion_overrides or {}))
    context["tactics"] = []
    for line in lines or []:
        spec = dict(line)
        tactic_type = spec.pop("tactic_type", TacticType.TPR.value)
        context["tactics"].append(
            setup_tactic(api, context["promotion"]["id"], tactic_type, **spec)
        )
    context["promotion"] = read_promotion(api, context["promotion"]["id"])
    return context


def setup_cancelled_tactic(api: ApiClient, tactic_id: str, **overrides: Any) -> Dict[str, Any]:
    """A tactic line moved to the terminal `CANCELLED` status."""
    response = api.cancel_tactic(tactic_id, KAM_HEADERS, cancel_tactic_payload(**overrides))
    return get_success_data(response)


# ═══ Documents ═════════════════════════════════════════

def setup_commitment_document(api: ApiClient, promotion_id: str,
                              **overrides: Any) -> Dict[str, Any]:
    """A `SUBMITTED` `COMMITMENT` document, which counts for nothing yet."""
    response = api.create_document(
        promotion_id, create_commitment_document_payload(**overrides), KAM_HEADERS
    )
    return get_success_data(response, 201)


def setup_evidence_document(api: ApiClient, promotion_id: str,
                            **overrides: Any) -> Dict[str, Any]:
    """A `SUBMITTED` `EVIDENCE` document carrying substantiated cases."""
    response = api.create_document(
        promotion_id, create_evidence_document_payload(**overrides), ANALYST_HEADERS
    )
    return get_success_data(response, 201)


def setup_verified_commitment_document(api: ApiClient, promotion_id: str,
                                       verifier_headers: Optional[Dict[str, str]] = None,
                                       **overrides: Any) -> Dict[str, Any]:
    """
    A `VERIFIED` `COMMITMENT` document.

    A commitment document may be verified only by a `KeyAccountManager`.
    """
    document = setup_commitment_document(api, promotion_id, **overrides)
    response = api.verify_document(document["id"], verifier_headers or KAM_HEADERS)
    return get_success_data(response)


def setup_verified_evidence_document(api: ApiClient, promotion_id: str,
                                     verifier_headers: Optional[Dict[str, str]] = None,
                                     **overrides: Any) -> Dict[str, Any]:
    """
    A `VERIFIED` `EVIDENCE` document whose `units_verified` counts toward
    entitlement.

    An evidence document may be verified only by a `TradeFinanceAnalyst`.
    """
    document = setup_evidence_document(api, promotion_id, **overrides)
    response = api.verify_document(document["id"], verifier_headers or ANALYST_HEADERS)
    return get_success_data(response)


# ═══ Tier 3 — full-lifecycle shortcuts ═════════════════

def setup_submitted_promotion(api: ApiClient, context: Optional[Dict[str, Any]] = None,
                              promotion_overrides: Optional[Dict[str, Any]] = None,
                              **tactic_overrides: Any) -> Dict[str, Any]:
    """
    A `SUBMITTED` promotion carrying one `TPR` line.

    Submission requires at least one tactic line whose `status` is `PLANNED`.
    """
    context = setup_promotion_with_tpr_line(
        api, context, promotion_overrides=promotion_overrides, **tactic_overrides
    )
    response = api.submit_promotion(context["promotion"]["id"], KAM_HEADERS)
    context["promotion"] = get_success_data(response)
    return context


def setup_changes_requested_promotion(api: ApiClient,
                                      context: Optional[Dict[str, Any]] = None,
                                      promotion_overrides: Optional[Dict[str, Any]] = None,
                                      **tactic_overrides: Any) -> Dict[str, Any]:
    """A promotion sent back for rework, with no budget field moved."""
    context = setup_submitted_promotion(
        api, context, promotion_overrides=promotion_overrides, **tactic_overrides
    )
    response = api.request_changes_promotion(
        context["promotion"]["id"], request_changes_payload(), DIRECTOR_HEADERS
    )
    context["promotion"] = get_success_data(response)
    return context


def setup_approved_promotion(api: ApiClient, context: Optional[Dict[str, Any]] = None,
                             promotion_overrides: Optional[Dict[str, Any]] = None,
                             approver_headers: Optional[Dict[str, str]] = None,
                             **tactic_overrides: Any) -> Dict[str, Any]:
    """
    An `APPROVED` promotion whose money and volume are reserved on the allocation.

    The single line is a `TPR` line, so `commitment_verified` is true vacuously.
    """
    context = setup_submitted_promotion(
        api, context, promotion_overrides=promotion_overrides, **tactic_overrides
    )
    response = api.approve_promotion(context["promotion"]["id"],
                                     approver_headers or DIRECTOR_HEADERS)
    context["promotion"] = get_success_data(response)
    context["allocation"] = read_allocation(api, context["allocation"]["id"])
    return context


def setup_approved_promotion_with_lines(api: ApiClient,
                                        lines: List[Dict[str, Any]],
                                        context: Optional[Dict[str, Any]] = None,
                                        promotion_overrides: Optional[Dict[str, Any]] = None,
                                        commitment_covers: Optional[str] = None
                                        ) -> Dict[str, Any]:
    """
    An `APPROVED` promotion carrying the supplied lines in order.

    When any `DISPLAY` or `FEATURE` line is present a `VERIFIED` `COMMITMENT`
    document covering `ALL` tactic types is attached first, because approval
    requires every such tactic type to be covered.
    """
    context = setup_promotion_with_lines(
        api, context, lines=lines, promotion_overrides=promotion_overrides
    )
    needs_paperwork = any(
        line.get("tactic_type") in (TacticType.DISPLAY.value, TacticType.FEATURE.value)
        for line in lines
    )
    if needs_paperwork or commitment_covers:
        context["commitment_document"] = setup_verified_commitment_document(
            api, context["promotion"]["id"],
            covers_tactic_type=commitment_covers or "ALL",
        )
    get_success_data(api.submit_promotion(context["promotion"]["id"], KAM_HEADERS))
    context["promotion"] = get_success_data(
        api.approve_promotion(context["promotion"]["id"], DIRECTOR_HEADERS)
    )
    context["allocation"] = read_allocation(api, context["allocation"]["id"])
    return context


def run_activation(api: ApiClient, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Run the operations checkpoint against the current logical clock."""
    return get_success_data(
        api.create_promotion_activation_run(headers or ANALYST_HEADERS)
    )


def setup_live_promotion(api: ApiClient, context: Optional[Dict[str, Any]] = None,
                         clock_instant: Optional[str] = None,
                         promotion_overrides: Optional[Dict[str, Any]] = None,
                         **tactic_overrides: Any) -> Dict[str, Any]:
    """
    A `LIVE` promotion, activated by moving the clock inside its window.

    Activation is evaluated before ending within a single run, so the clock is
    parked strictly before `window_end` to stop the promotion at `LIVE`.
    """
    context = setup_approved_promotion(
        api, context, promotion_overrides=promotion_overrides, **tactic_overrides
    )
    set_clock(api, clock_instant or instant(MONDAY_AUG_10))
    context["activation_run"] = run_activation(api)
    context["promotion"] = read_promotion(api, context["promotion"]["id"])
    return context


def setup_ended_promotion(api: ApiClient, context: Optional[Dict[str, Any]] = None,
                          clock_instant: Optional[str] = None,
                          promotion_overrides: Optional[Dict[str, Any]] = None,
                          **tactic_overrides: Any) -> Dict[str, Any]:
    """
    An `ENDED` promotion.

    A promotion whose whole window lies in the past traverses `APPROVED` to
    `LIVE` to `ENDED` in a single run.
    """
    context = setup_approved_promotion(
        api, context, promotion_overrides=promotion_overrides, **tactic_overrides
    )
    set_clock(api, clock_instant or instant(MONDAY_SEP_07))
    context["activation_run"] = run_activation(api)
    context["promotion"] = read_promotion(api, context["promotion"]["id"])
    return context


def setup_ended_promotion_with_lines(api: ApiClient, lines: List[Dict[str, Any]],
                                     context: Optional[Dict[str, Any]] = None,
                                     clock_instant: Optional[str] = None,
                                     promotion_overrides: Optional[Dict[str, Any]] = None
                                     ) -> Dict[str, Any]:
    """An `ENDED` promotion carrying the supplied lines in order."""
    context = setup_approved_promotion_with_lines(
        api, lines, context, promotion_overrides=promotion_overrides
    )
    set_clock(api, clock_instant or instant(MONDAY_SEP_07))
    context["activation_run"] = run_activation(api)
    context["promotion"] = read_promotion(api, context["promotion"]["id"])
    return context


def setup_analysis(api: ApiClient, promotion_id: str,
                   baseline_method: str = BaselineMethod.TRAILING.value,
                   **overrides: Any) -> Dict[str, Any]:
    """The post-event analysis of an `ENDED` promotion."""
    response = api.analyze_promotion(
        promotion_id, analyze_promotion_payload(baseline_method, **overrides), ANALYST_HEADERS
    )
    return get_success_data(response, 201)


def setup_analyzed_promotion(api: ApiClient, context: Optional[Dict[str, Any]] = None,
                             baseline_method: str = BaselineMethod.TRAILING.value,
                             clock_instant: Optional[str] = None,
                             promotion_overrides: Optional[Dict[str, Any]] = None,
                             **tactic_overrides: Any) -> Dict[str, Any]:
    """An `ANALYZED` promotion with its analysis row attached to the context."""
    context = setup_ended_promotion(
        api, context, clock_instant=clock_instant,
        promotion_overrides=promotion_overrides, **tactic_overrides
    )
    context["analysis"] = setup_analysis(api, context["promotion"]["id"], baseline_method)
    context["promotion"] = read_promotion(api, context["promotion"]["id"])
    return context


def setup_withdrawn_promotion(api: ApiClient, context: Optional[Dict[str, Any]] = None,
                              promotion_overrides: Optional[Dict[str, Any]] = None,
                              **tactic_overrides: Any) -> Dict[str, Any]:
    """
    A `WITHDRAWN` promotion, the compensating action for approval.

    Withdrawal is permitted only while `gross_accrued_amount` is still 0.00.
    """
    context = setup_approved_promotion(
        api, context, promotion_overrides=promotion_overrides, **tactic_overrides
    )
    response = api.withdraw_promotion(
        context["promotion"]["id"], KAM_HEADERS, withdraw_promotion_payload()
    )
    context["promotion"] = get_success_data(response)
    context["allocation"] = read_allocation(api, context["allocation"]["id"])
    return context


# ═══ Tier 4 — accumulation and threshold targeting ═════

def post_accrual(api: ApiClient, promotion_id: str, period_start: str = MONDAY_AUG_03,
                 **overrides: Any) -> Dict[str, Any]:
    """Post the accrual for one week of a `LIVE`, `ENDED` or `ANALYZED` promotion."""
    response = api.create_accrual(
        promotion_id, create_accrual_payload(period_start, **overrides), ANALYST_HEADERS
    )
    return get_success_data(response, 201)


def setup_accrued_promotion(api: ApiClient, context: Optional[Dict[str, Any]] = None,
                            fact_units: int = 2000,
                            fact_type: str = FactType.SHIPMENT.value,
                            fact_period: str = MONDAY_AUG_03,
                            accrual_period: str = MONDAY_AUG_03,
                            promotion_overrides: Optional[Dict[str, Any]] = None,
                            **tactic_overrides: Any) -> Dict[str, Any]:
    """
    A `LIVE` promotion with one week accrued against a matching volume fact.

    On the `SHIPMENT` basis the effective period is the requested `period_start`
    shifted forward by 14 days, while the facts read are those whose
    `period_start` equals the requested period exactly.
    """
    context = context if context is not None else setup_allocation_context(api)
    context = setup_live_promotion(
        api, context, promotion_overrides=promotion_overrides, **tactic_overrides
    )
    context["volume_fact"] = setup_volume_fact(
        api, context["customer"]["id"], context["brand"]["id"],
        fact_type=fact_type, period_start=fact_period, units=fact_units,
        source="EDI_856" if fact_type == FactType.SHIPMENT.value else "EDI_852",
    )
    context["accrual"] = post_accrual(api, context["promotion"]["id"], accrual_period)
    context["promotion"] = read_promotion(api, context["promotion"]["id"])
    context["allocation"] = read_allocation(api, context["allocation"]["id"])
    return context


def setup_reversed_accrual(api: ApiClient, context: Optional[Dict[str, Any]] = None,
                           **overrides: Any) -> Dict[str, Any]:
    """
    An accrual entry moved to `REVERSED` together with its mirror entry.

    The supplied amount must equal the reversed entry's `amount` exactly, and it
    is the mirror entry that comes back as the response body.
    """
    context = context if context is not None else setup_accrued_promotion(api, **overrides)
    original = context["accrual"]
    response = api.reverse_accrual(
        original["id"], reverse_accrual_payload(original["amount"]), ANALYST_HEADERS
    )
    context["reversal"] = get_success_data(response, 201)
    context["accrual"] = read_accrual(api, original["id"])
    context["promotion"] = read_promotion(api, context["promotion"]["id"])
    context["allocation"] = read_allocation(api, context["allocation"]["id"])
    return context


# ─── Deduction pipeline ───────────────────────────────

def setup_deduction(api: ApiClient, customer_id: str, **overrides: Any) -> Dict[str, Any]:
    """A `RECEIVED` deduction booked against a customer."""
    response = api.create_deduction(create_deduction_payload(customer_id, **overrides),
                                    SPECIALIST_HEADERS)
    return get_success_data(response, 201)


def setup_matched_deduction(api: ApiClient, customer_id: str, promotion_id: str,
                            matcher_headers: Optional[Dict[str, str]] = None,
                            **overrides: Any) -> Dict[str, Any]:
    """A `MATCHED` deduction linked to a matchable promotion of its own customer."""
    deduction = setup_deduction(api, customer_id, **overrides)
    response = api.match_deduction(
        deduction["id"], match_deduction_payload(promotion_id),
        matcher_headers or SPECIALIST_HEADERS,
    )
    return get_success_data(response)


def validate_deduction(api: ApiClient, deduction_id: str, promotion_id: str,
                       headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """
    Value a `MATCHED` claim, reading the promotion's live `version` first.

    The validating analyst must not be the operator recorded in the promotion's
    `approved_by_user_id`.
    """
    expected_version = current_promotion_version(api, promotion_id)
    response = api.validate_deduction(
        deduction_id, validate_deduction_payload(expected_version),
        headers or ANALYST_HEADERS,
    )
    return get_success_data(response)


def setup_validated_deduction(api: ApiClient, context: Optional[Dict[str, Any]] = None,
                              claimed_amount: float = 3000.00,
                              evidence_units: int = 1800,
                              validator_headers: Optional[Dict[str, str]] = None,
                              **overrides: Any) -> Dict[str, Any]:
    """
    A `VALIDATED` deduction on an accrued promotion under the `EVIDENCE_BASED`
    policy.

    Under that policy the matched promotion must carry at least one `VERIFIED`
    `EVIDENCE` document with a `units_verified` greater than zero.
    """
    context = context if context is not None else setup_accrued_promotion(api, **overrides)
    if evidence_units:
        context["evidence_document"] = setup_verified_evidence_document(
            api, context["promotion"]["id"], units_verified=evidence_units
        )
    context["deduction"] = setup_matched_deduction(
        api, context["customer"]["id"], context["promotion"]["id"],
        claimed_amount=claimed_amount,
    )
    context["deduction"] = validate_deduction(
        api, context["deduction"]["id"], context["promotion"]["id"],
        headers=validator_headers,
    )
    context["promotion"] = read_promotion(api, context["promotion"]["id"])
    context["allocation"] = read_allocation(api, context["allocation"]["id"])
    context["customer"] = read_customer(api, context["customer"]["id"])
    return context


def setup_settled_deduction(api: ApiClient, context: Optional[Dict[str, Any]] = None,
                            **overrides: Any) -> Dict[str, Any]:
    """
    A `SETTLED` deduction, the terminal close of a valid claim.

    Settlement requires the customer to be in `trading_status` `ACTIVE`.
    """
    context = context if context is not None else setup_validated_deduction(api, **overrides)
    response = api.settle_deduction(context["deduction"]["id"], ANALYST_HEADERS)
    context["deduction"] = get_success_data(response)
    context["allocation"] = read_allocation(api, context["allocation"]["id"])
    context["customer"] = read_customer(api, context["customer"]["id"])
    return context


# ─── Dispute pipeline ─────────────────────────────────

def open_dispute(api: ApiClient, deduction_id: str, disputed_amount: float,
                 headers: Optional[Dict[str, str]] = None, **overrides: Any) -> Dict[str, Any]:
    """Open a dispute over an invalid claim, which moves the deduction to `DISPUTED`."""
    response = api.dispute_deduction(
        deduction_id, create_dispute_payload(disputed_amount, **overrides),
        headers or SPECIALIST_HEADERS,
    )
    return get_success_data(response, 201)


def setup_disputed_deduction(api: ApiClient, context: Optional[Dict[str, Any]] = None,
                             disputed_amount: float = 500.00,
                             opener_headers: Optional[Dict[str, str]] = None,
                             **overrides: Any) -> Dict[str, Any]:
    """
    An `OPEN` dispute on a `RECEIVED` claim, with no promotion ledger touched.

    While the deduction is still `RECEIVED` or `MATCHED` the whole
    `claimed_amount` is challengeable.
    """
    context = context if context is not None else setup_reference_data(api)
    if "deduction" not in context:
        context["deduction"] = setup_deduction(
            api, context["customer"]["id"], **overrides
        )
    context["dispute"] = open_dispute(
        api, context["deduction"]["id"], disputed_amount, headers=opener_headers
    )
    context["deduction"] = read_deduction(api, context["deduction"]["id"])
    context["customer"] = read_customer(api, context["customer"]["id"])
    return context


def setup_dispute_on_validated_deduction(api: ApiClient,
                                         context: Optional[Dict[str, Any]] = None,
                                         disputed_amount: Optional[float] = None,
                                         opener_headers: Optional[Dict[str, str]] = None,
                                         **overrides: Any) -> Dict[str, Any]:
    """
    An `OPEN` dispute on a `VALIDATED` claim.

    Once a claim has been `VALIDATED` only its `variance_amount` is challengeable.
    """
    context = context if context is not None else setup_validated_deduction(api, **overrides)
    amount = disputed_amount if disputed_amount is not None else (
        context["deduction"]["variance_amount"]
    )
    context["dispute"] = open_dispute(
        api, context["deduction"]["id"], amount, headers=opener_headers
    )
    context["deduction"] = read_deduction(api, context["deduction"]["id"])
    context["customer"] = read_customer(api, context["customer"]["id"])
    return context


def send_dispute(api: ApiClient, dispute_id: str,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Send an `OPEN` dispute to the retailer, incrementing `round_count`."""
    response = api.send_dispute_to_retailer(
        dispute_id, headers or SPECIALIST_HEADERS, send_to_retailer_payload()
    )
    return get_success_data(response)


def retailer_respond(api: ApiClient, dispute_id: str, customer_id: str,
                     **overrides: Any) -> Dict[str, Any]:
    """
    The retailer's answer through the portal, returning the dispute to `OPEN`.

    The acting portal login is the customer of the disputed deduction.
    """
    response = api.retailer_respond_dispute(
        dispute_id, retailer_respond_payload(**overrides),
        make_portal_user_headers(customer_id),
    )
    return get_success_data(response)


def setup_dispute_round_trip(api: ApiClient, context: Dict[str, Any],
                             rounds: int = 1) -> Dict[str, Any]:
    """
    Walk the bounded negotiation loop the requested number of complete cycles.

    Because `round_count` is never reset by the return leg, the loop may run at
    most twice.
    """
    for _ in range(rounds):
        send_dispute(api, context["dispute"]["id"])
        retailer_respond(api, context["dispute"]["id"], context["customer"]["id"])
    context["dispute"] = read_dispute(api, context["dispute"]["id"])
    return context


def run_aging_sweep(api: ApiClient, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Run the aging sweep over open disputes at the current logical clock."""
    return get_success_data(api.create_deduction_aging_run(headers or ANALYST_HEADERS))


def setup_escalated_dispute(api: ApiClient, context: Optional[Dict[str, Any]] = None,
                            days_aged: int = 90, **overrides: Any) -> Dict[str, Any]:
    """
    An `ESCALATED` dispute, aged past the inclusive 90-day threshold by the clock.

    Each escalation adds 5 points to the disputed deduction's customer.
    """
    context = context if context is not None else setup_disputed_deduction(api, **overrides)
    opened_at = context["dispute"]["opened_at"]
    set_clock(api, instant_plus_days(opened_at, days_aged))
    context["aging_run"] = run_aging_sweep(api)
    context["dispute"] = read_dispute(api, context["dispute"]["id"])
    context["customer"] = read_customer(api, context["customer"]["id"])
    return context


def setup_recovered_dispute(api: ApiClient, context: Optional[Dict[str, Any]] = None,
                            recovered_amount: Optional[float] = None,
                            **overrides: Any) -> Dict[str, Any]:
    """A `RECOVERED` dispute: cash back, so the deduction closes as `RECOVERED`."""
    context = context if context is not None else setup_disputed_deduction(api, **overrides)
    amount = recovered_amount if recovered_amount is not None else (
        context["dispute"]["disputed_amount"]
    )
    response = api.record_dispute_recovery(
        context["dispute"]["id"], record_recovery_payload(amount), SPECIALIST_HEADERS
    )
    context["dispute"] = get_success_data(response)
    context["deduction"] = read_deduction(api, context["deduction"]["id"])
    context["customer"] = read_customer(api, context["customer"]["id"])
    return context


def setup_written_off_dispute(api: ApiClient, context: Optional[Dict[str, Any]] = None,
                              write_off_amount: Optional[float] = None,
                              approver_headers: Optional[Dict[str, str]] = None,
                              **overrides: Any) -> Dict[str, Any]:
    """
    A `WRITTEN_OFF` dispute, the terminal bad outcome.

    A `write_off_amount` at or above 500.00 requires a `TradeMarketingDirector`,
    and the user recorded in `opened_by_user_id` may never approve the write-off.
    """
    context = context if context is not None else setup_disputed_deduction(api, **overrides)
    amount = write_off_amount if write_off_amount is not None else (
        context["dispute"]["disputed_amount"]
    )
    response = api.write_off_dispute(
        context["dispute"]["id"], write_off_payload(amount),
        approver_headers or DIRECTOR_HEADERS,
    )
    context["dispute"] = get_success_data(response)
    context["deduction"] = read_deduction(api, context["deduction"]["id"])
    context["customer"] = read_customer(api, context["customer"]["id"])
    if "promotion" in context:
        context["promotion"] = read_promotion(api, context["promotion"]["id"])
    if "allocation" in context:
        context["allocation"] = read_allocation(api, context["allocation"]["id"])
    return context


# ═══ Tier 5 — terminal states and compliance ═══════════

def setup_compliance_audit(api: ApiClient, customer_id: str,
                           auditor_headers: Optional[Dict[str, str]] = None,
                           **overrides: Any) -> Dict[str, Any]:
    """
    A `SCHEDULED` audit, which moves the customer's `audit_status` to
    `AUDIT_IN_PROGRESS`.
    """
    response = api.create_compliance_audit(
        customer_id, create_compliance_audit_payload(**overrides),
        auditor_headers or AUDITOR_HEADERS,
    )
    return get_success_data(response, 201)


def record_finding(api: ApiClient, audit_id: str, recovery_amount: float = 1200.00,
                   **overrides: Any) -> Dict[str, Any]:
    """Record one finding, which takes a `SCHEDULED` audit to `IN_PROGRESS`."""
    response = api.record_audit_finding(
        audit_id, record_audit_finding_payload(recovery_amount, **overrides), AUDITOR_HEADERS
    )
    return get_success_data(response)


def setup_audit_with_findings(api: ApiClient, context: Optional[Dict[str, Any]] = None,
                              finding_amounts: Optional[List[float]] = None,
                              **overrides: Any) -> Dict[str, Any]:
    """An `IN_PROGRESS` audit carrying the supplied findings in order."""
    context = context if context is not None else setup_reference_data(api, **overrides)
    context["audit"] = setup_compliance_audit(api, context["customer"]["id"])
    for amount in (finding_amounts or [1200.00]):
        context["audit"] = record_finding(api, context["audit"]["id"], amount)
    context["customer"] = read_customer(api, context["customer"]["id"])
    return context


def setup_issued_audit(api: ApiClient, context: Optional[Dict[str, Any]] = None,
                       finding_amounts: Optional[List[float]] = None,
                       issuer_headers: Optional[Dict[str, str]] = None,
                       **overrides: Any) -> Dict[str, Any]:
    """
    An audit in the terminal `FINDINGS_ISSUED` status.

    Issuance moves the customer's `audit_status` to `FINDINGS_OPEN` and adds 10
    penalty points on the independent commercial axis.
    """
    context = context if context is not None else setup_audit_with_findings(
        api, finding_amounts=finding_amounts, **overrides
    )
    if "audit" not in context:
        context = setup_audit_with_findings(api, context, finding_amounts=finding_amounts)
    response = api.issue_audit_findings(context["audit"]["id"],
                                        issuer_headers or AUDITOR_HEADERS)
    context["audit"] = get_success_data(response)
    context["customer"] = read_customer(api, context["customer"]["id"])
    return context


# ═══ Threshold-targeting composites ════════════════════

def setup_overspent_promotion(api: ApiClient, context: Optional[Dict[str, Any]] = None,
                              planned_units: int = 2000, rate_per_case: float = 1.250,
                              fact_units: int = 2000,
                              claimed_amount: float = 12250.00,
                              evidence_units: int = 9800) -> Dict[str, Any]:
    """
    A promotion driven to `OVERSPENT` by an evidence-based deduction validation.

    Under the `EVIDENCE_BASED` policy `entitled_amount` is the evidence units
    multiplied by the contract rate and is not capped by the accrual balance, so
    a well-evidenced claim can push the promotion over budget.
    """
    context = context if context is not None else setup_allocation_context(api)
    context = setup_accrued_promotion(
        api, context, fact_units=fact_units,
        planned_units=planned_units, rate_per_case=rate_per_case,
    )
    context = setup_validated_deduction(
        api, context, claimed_amount=claimed_amount, evidence_units=evidence_units
    )
    return context


def setup_restricted_allocation(api: ApiClient, context: Optional[Dict[str, Any]] = None,
                                **overrides: Any) -> Dict[str, Any]:
    """
    An allocation driven from `OPEN` to `RESTRICTED` posture by an overspending
    child promotion.

    `overspend_event_count` counts distinct child promotions that have entered
    `OVERSPENT` at least once and is never decremented.
    """
    context = setup_overspent_promotion(api, context, **overrides)
    context["allocation"] = read_allocation(api, context["allocation"]["id"])
    context["customer"] = read_customer(api, context["customer"]["id"])
    return context


def setup_frozen_allocation(api: ApiClient, context: Optional[Dict[str, Any]] = None,
                            **overrides: Any) -> Dict[str, Any]:
    """An allocation frozen by the terminal year-end lock of its program."""
    context = context if context is not None else setup_allocation_context(api, **overrides)
    context["program"] = get_success_data(
        api.lock_program(context["program"]["id"], DIRECTOR_HEADERS)
    )
    context["allocation"] = read_allocation(api, context["allocation"]["id"])
    return context


def setup_analysis_with_consumption_facts(
    api: ApiClient,
    trailing_weeks: Dict[str, int],
    promoted_weeks: Dict[str, int],
    post_weeks: Optional[Dict[str, int]] = None,
    context: Optional[Dict[str, Any]] = None,
    baseline_method: str = BaselineMethod.TRAILING.value,
    promotion_overrides: Optional[Dict[str, Any]] = None,
    lines: Optional[List[Dict[str, Any]]] = None,
    clock_instant: Optional[str] = None,
) -> Dict[str, Any]:
    """
    An `ANALYZED` promotion whose three measurement windows are pre-loaded.

    Measurement reads `CONSUMPTION` volume facts only, in the trailing, promoted
    and post windows, so every supplied week is written with `fact_type`
    `CONSUMPTION`.
    """
    context = context if context is not None else setup_allocation_context(api)
    if lines is None:
        context = setup_approved_promotion(
            api, context, promotion_overrides=promotion_overrides
        )
    else:
        context = setup_approved_promotion_with_lines(
            api, lines, context, promotion_overrides=promotion_overrides
        )
    all_weeks: Dict[str, int] = {}
    all_weeks.update(trailing_weeks)
    all_weeks.update(promoted_weeks)
    all_weeks.update(post_weeks or {})
    context["consumption_facts"] = setup_volume_facts(
        api, context["customer"]["id"], context["brand"]["id"], all_weeks,
        fact_type=FactType.CONSUMPTION.value, source="EDI_852",
    )
    set_clock(api, clock_instant or instant(MONDAY_SEP_07))
    context["activation_run"] = run_activation(api)
    context["analysis"] = setup_analysis(api, context["promotion"]["id"], baseline_method)
    context["promotion"] = read_promotion(api, context["promotion"]["id"])
    context["allocation"] = read_allocation(api, context["allocation"]["id"])
    return context


def setup_agreement_cap_context(api: ApiClient, fact_units: int = 2000,
                                claimed_amount: float = 3000.00,
                                **overrides: Any) -> Dict[str, Any]:
    """
    An accrued promotion whose customer carries the `AGREEMENT_CAP` policy.

    Under that policy `entitled_amount` is exactly the matched promotion's
    `accrued_balance` as it stands at the moment of the request, and evidence is
    ignored entirely.
    """
    context = setup_allocation_context(
        api,
        customer_overrides={
            "deduction_validation_policy": DeductionValidationPolicy.AGREEMENT_CAP.value
        },
        **overrides,
    )
    context = setup_accrued_promotion(api, context, fact_units=fact_units)
    context["deduction"] = setup_matched_deduction(
        api, context["customer"]["id"], context["promotion"]["id"],
        claimed_amount=claimed_amount,
    )
    return context


def setup_two_promotions_on_one_allocation(api: ApiClient,
                                           context: Optional[Dict[str, Any]] = None,
                                           first_overrides: Optional[Dict[str, Any]] = None,
                                           second_overrides: Optional[Dict[str, Any]] = None
                                           ) -> Dict[str, Any]:
    """
    Two promotions planned against one allocation cell.

    Each create advances the allocation's `version`, so the second create must
    read the version the first left behind.
    """
    context = context if context is not None else setup_allocation_context(api)
    context = setup_draft_promotion(api, context, **(first_overrides or {}))
    context["promotion_one"] = context.pop("promotion")
    context = setup_draft_promotion(api, context, **(second_overrides or {}))
    context["promotion_two"] = context.pop("promotion")
    context["allocation"] = read_allocation(api, context["allocation"]["id"])
    return context


def setup_second_customer(api: ApiClient, context: Dict[str, Any],
                          **overrides: Any) -> Dict[str, Any]:
    """A second retail customer under the same program."""
    return setup_customer(api, context["program"]["id"], **overrides)


def setup_second_brand(api: ApiClient, context: Dict[str, Any],
                       **overrides: Any) -> Dict[str, Any]:
    """A second brand under the same program."""
    return setup_brand(api, context["program"]["id"], **overrides)
