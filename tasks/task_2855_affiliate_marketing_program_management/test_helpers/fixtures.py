"""Composite setup helpers.

Every helper here drives the API through the same routes a client would use,
so the state it leaves behind is state the contract can actually produce.  All
setup calls go through ``get_success_data`` so a broken precondition surfaces
as a clear setup failure rather than a confusing assertion.

The tiers follow the shape of the workflows in §3: partner admission, rate
cards and tracking, attribution, compliance, and settlement.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import (
    FEE_MODEL_PERCENT_OF_COMMISSION,
    VERIFY_OUTCOME_CLEARED,
)
from .test_users import (
    COMPLIANCE_ANALYST,
    FINANCE_ANALYST,
    FINANCE_CONTROLLER,
    PARTNER_MANAGER,
    PROGRAM_ADMIN,
    SECOND_COMPLIANCE_ANALYST,
    TRACKING_INGESTOR,
    make_affiliate_partner_headers,
)

JsonDict = Dict[str, Any]


# ── tier 1: single steps ────────────────────────────────────────────────────


def pin_clock(api, instant: str, headers=PROGRAM_ADMIN) -> JsonDict:
    """§2.9: pin the logical clock every temporal rule is evaluated against."""
    return get_success_data(api.set_clock(instant, headers))


def create_network(api, **kwargs) -> JsonDict:
    return get_success_data(api.create_network(f.network_payload(**kwargs), PROGRAM_ADMIN))


def register_affiliate(api, network_id: str, **kwargs) -> JsonDict:
    """Register a partner through the anonymous self-registration route."""
    return get_success_data(
        api.create_affiliate(
            f.affiliate_payload(network_id, **kwargs), PROGRAM_ADMIN
        )
    )


def file_application(api, affiliate_id: str, **kwargs) -> JsonDict:
    return get_success_data(
        api.create_application(
            affiliate_id, f.application_payload(**kwargs), PARTNER_MANAGER
        )
    )


def screen_application(api, application_id: str, headers=COMPLIANCE_ANALYST, **kwargs):
    return get_success_data(
        api.screen_application(application_id, f.screen_payload(**kwargs), headers)
    )


def decide_application(
    api,
    application_id: str,
    decision: str,
    affiliate_version: int,
    headers=PARTNER_MANAGER,
    **kwargs,
) -> JsonDict:
    return get_success_data(
        api.decide_application(
            application_id,
            f.decide_payload(decision, affiliate_version, **kwargs),
            headers,
        )
    )


def read_affiliate(api, affiliate_id: str, headers=PROGRAM_ADMIN) -> JsonDict:
    return get_success_data(api.get_affiliate(affiliate_id, headers))


def read_conversion(api, conversion_id: str, headers=TRACKING_INGESTOR) -> JsonDict:
    return get_success_data(api.get_conversion(conversion_id, headers))


def read_batch(api, batch_id: str, headers=FINANCE_ANALYST) -> JsonDict:
    return get_success_data(api.get_payout_batch(batch_id, headers))


def read_line(api, line_id: str, headers=FINANCE_ANALYST) -> JsonDict:
    return get_success_data(api.get_payout_line(line_id, headers))


def mint_link(api, affiliate_id: str, **kwargs) -> JsonDict:
    return get_success_data(
        api.create_tracking_link(
            affiliate_id, f.tracking_link_payload(**kwargs), PARTNER_MANAGER
        )
    )


def ingest_click(api, link_id: str, **kwargs) -> JsonDict:
    return get_success_data(
        api.ingest_click(link_id, f.click_payload(**kwargs), TRACKING_INGESTOR)
    )


def create_conversion(api, **kwargs) -> JsonDict:
    return get_success_data(
        api.create_conversion(f.conversion_payload(**kwargs), TRACKING_INGESTOR)
    )


def attribute(api, conversion_id: str, expected_version: int) -> JsonDict:
    return get_success_data(
        api.attribute_conversion(
            conversion_id, f.attribute_payload(expected_version), TRACKING_INGESTOR
        )
    )


def draft_policy(api, **kwargs) -> JsonDict:
    return get_success_data(
        api.create_commission_policy(f.policy_payload(**kwargs), PROGRAM_ADMIN)
    )


def activate_policy(api, policy_id: str, expected_version: int) -> JsonDict:
    return get_success_data(
        api.activate_commission_policy(
            policy_id, f.activate_policy_payload(expected_version), PROGRAM_ADMIN
        )
    )


def draft_and_activate_policy(api, **kwargs) -> JsonDict:
    policy = draft_policy(api, **kwargs)
    return activate_policy(api, policy["id"], policy["version"])


# ── tier 2: partner admission shortcuts ─────────────────────────────────────


def activated_partner(
    api,
    network_id: str,
    partner_type: str = "CONTENT",
    screen_kwargs: Optional[JsonDict] = None,
    application_kwargs: Optional[JsonDict] = None,
    affiliate_kwargs: Optional[JsonDict] = None,
) -> JsonDict:
    """Register, file, screen to `PASS` and `APPROVE` — a partner that is `ACTIVE`.

    §3.2: "`APPROVE` moves the application `SCREENED → APPROVED` ... It cascades
    the applicant partner `PENDING_APPLICATION → ACTIVE`."
    """
    affiliate = register_affiliate(
        api, network_id, partner_type=partner_type, **(affiliate_kwargs or {})
    )
    application = file_application(api, affiliate["id"], **(application_kwargs or {}))
    application = screen_application(api, application["id"], **(screen_kwargs or {}))
    application = decide_application(
        api, application["id"], "APPROVE", affiliate["version"]
    )
    return {
        "affiliate": read_affiliate(api, affiliate["id"]),
        "affiliate_id": affiliate["id"],
        "application": application,
        "application_id": application["id"],
    }


def screened_partner(
    api,
    network_id: str,
    partner_type: str = "CONTENT",
    screen_kwargs: Optional[JsonDict] = None,
    application_kwargs: Optional[JsonDict] = None,
) -> JsonDict:
    """A partner still `PENDING_APPLICATION` whose application is `SCREENED`."""
    affiliate = register_affiliate(api, network_id, partner_type=partner_type)
    application = file_application(api, affiliate["id"], **(application_kwargs or {}))
    application = screen_application(api, application["id"], **(screen_kwargs or {}))
    return {
        "affiliate": read_affiliate(api, affiliate["id"]),
        "affiliate_id": affiliate["id"],
        "application": application,
        "application_id": application["id"],
    }


# ── tier 3: a full priced program ───────────────────────────────────────────


def build_program(
    api,
    setup_clock: str = f.JUL_05_00_00,
    partner_type: str = "CONTENT",
    fee_model: str = FEE_MODEL_PERCENT_OF_COMMISSION,
    fee_bps: int = 0,
    flat_fee_cents: int = 0,
    policy_category: str = "APPAREL",
    policy_scope: Optional[List[str]] = None,
    new_customer_rate_bps: int = 900,
    returning_customer_rate_bps: int = 400,
    effective_from: str = f.YEAR_2026_START,
    effective_to: str = f.YEAR_2027_START,
    screen_kwargs: Optional[JsonDict] = None,
    application_kwargs: Optional[JsonDict] = None,
    link_kwargs: Optional[JsonDict] = None,
    with_policy: bool = True,
    with_link: bool = True,
) -> JsonDict:
    """Clock, network, `ACTIVE` partner, `ACTIVE` rate card and one `ACTIVE` link."""
    pin_clock(api, setup_clock)
    network = create_network(
        api, fee_model=fee_model, fee_bps=fee_bps, flat_fee_cents=flat_fee_cents
    )
    partner = activated_partner(
        api,
        network["id"],
        partner_type=partner_type,
        screen_kwargs=screen_kwargs,
        application_kwargs=application_kwargs,
    )
    program: JsonDict = {
        "network": network,
        "network_id": network["id"],
        "affiliate": partner["affiliate"],
        "affiliate_id": partner["affiliate_id"],
        "application": partner["application"],
        "application_id": partner["application_id"],
    }
    if with_policy:
        policy = draft_and_activate_policy(
            api,
            product_category=policy_category,
            partner_type_scope=policy_scope or [partner_type],
            new_customer_rate_bps=new_customer_rate_bps,
            returning_customer_rate_bps=returning_customer_rate_bps,
            effective_from=effective_from,
            effective_to=effective_to,
        )
        program["policy"] = policy
        program["policy_id"] = policy["id"]
    if with_link:
        link = mint_link(api, partner["affiliate_id"], **(link_kwargs or {}))
        program["link"] = link
        program["link_id"] = link["id"]
    return program


def attributed_order(
    api,
    program: JsonDict,
    order_total_cents: int = 100000,
    is_new_customer: bool = False,
    coupon_code_used: Optional[str] = None,
    click_at: str = f.JUL_04_10_00,
    placed_at: str = f.JUL_04_12_00,
    device_id: str = "D1",
    order_ref: Optional[str] = None,
    product_category: str = "APPAREL",
) -> JsonDict:
    """One click, one order and one attribution run over an existing program."""
    click = ingest_click(api, program["link_id"], occurred_at=click_at, device_id=device_id)
    conversion = create_conversion(
        api,
        order_ref=order_ref,
        order_total_cents=order_total_cents,
        product_category=product_category,
        is_new_customer=is_new_customer,
        placed_at=placed_at,
        device_id=device_id,
        coupon_code_used=coupon_code_used,
    )
    attributed = attribute(api, conversion["id"], conversion["version"])
    return {
        "click": click,
        "click_id": click["id"],
        "conversion": attributed,
        "conversion_id": conversion["id"],
    }


# ── tier 4: compliance and threshold targeting ──────────────────────────────


def open_case(
    api,
    affiliate_id: str,
    violation_type: str = "TRADEMARK_BIDDING",
    detected_at: str = f.JUL_05_00_00,
    headers=COMPLIANCE_ANALYST,
) -> JsonDict:
    """Hand-file a case: "A hand-filed case records the filer in `opened_by_user_id`"."""
    return get_success_data(
        api.create_violation_case(
            f.violation_case_payload(
                affiliate_id, violation_type=violation_type, detected_at=detected_at
            ),
            headers,
        )
    )


def clear_case(api, case_id: str, affiliate_id: str) -> JsonDict:
    """Walk a case `OPEN → REMEDIATION_REQUESTED → REMEDIATION_SUBMITTED → VERIFIED_CLEARED`.

    §3.7 puts the submission in the partner's own hands — "the caller must be
    the partner the case is against" — and §2.8 keeps the verifier apart from
    the analyst who filed it.
    """
    get_success_data(
        api.transition_violation_case(
            case_id,
            f.case_transition_payload("REQUEST_REMEDIATION", note="please remediate"),
            COMPLIANCE_ANALYST,
        )
    )
    get_success_data(
        api.transition_violation_case(
            case_id,
            f.case_transition_payload(
                "SUBMIT_REMEDIATION",
                note="remediated",
                remediation_evidence_ref="evidence-remediation",
            ),
            make_affiliate_partner_headers(affiliate_id),
        )
    )
    return get_success_data(
        api.transition_violation_case(
            case_id,
            f.case_transition_payload(
                "VERIFY", note="verified clear", verify_outcome=VERIFY_OUTCOME_CLEARED
            ),
            SECOND_COMPLIANCE_ANALYST,
        )
    )


def suspend_partner(api, affiliate_id: str, reason: str = "compliance review"):
    """§3.7: a `ComplianceAnalyst` suspension sets `suspension_cause` `COMPLIANCE_ACTION`."""
    return get_success_data(
        api.change_affiliate_status(
            affiliate_id,
            f.status_change_payload("SUSPENDED", reason),
            COMPLIANCE_ANALYST,
        )
    )


def reinstate_partner(api, affiliate_id: str, reason: str = "cleared for reinstatement"):
    """§3.7: "Reinstatement is a `ProgramAdmin` action on a `SUSPENDED` partner"."""
    return get_success_data(
        api.change_affiliate_status(
            affiliate_id, f.status_change_payload("ACTIVE", reason), PROGRAM_ADMIN
        )
    )


def file_tax_document(api, affiliate_id: str, headers=PROGRAM_ADMIN, **kwargs):
    return get_success_data(
        api.file_tax_document(affiliate_id, f.tax_document_payload(**kwargs), headers)
    )


def verify_tax_document(api, document_id: str, outcome: str = "VALID") -> JsonDict:
    return get_success_data(
        api.verify_tax_document(
            document_id, f.verify_tax_document_payload(outcome), FINANCE_CONTROLLER
        )
    )


def valid_tax_document(api, affiliate_id: str, **kwargs) -> JsonDict:
    """File and accept a `W9`, leaving the partner's `tax_document_status` `VALID`."""
    document = file_tax_document(api, affiliate_id, **kwargs)
    return verify_tax_document(api, document["id"], "VALID")


def record_scan(api, affiliate_id: str, headers=COMPLIANCE_ANALYST, **kwargs):
    return get_success_data(
        api.create_monitoring_scan(
            f.monitoring_scan_payload(affiliate_id, **kwargs), headers
        )
    )


# ── tier 5: settlement ──────────────────────────────────────────────────────


def generate_batch(
    api,
    network_id: str,
    period_start: str = f.PERIOD_START_JUL,
    period_end: str = f.PERIOD_END_AUG,
) -> JsonDict:
    """§3.9: generation runs the validation sweep, the tax refresh, then claims entries."""
    return get_success_data(
        api.create_payout_batch(
            f.payout_batch_payload(network_id, period_start, period_end),
            FINANCE_ANALYST,
        )
    )


def batch_lines(api, batch_id: str) -> List[JsonDict]:
    rows, _meta = _paginated(api.list_payout_lines(FINANCE_ANALYST, {"payout_batch_id": batch_id}))
    return rows


def first_line(api, batch_id: str) -> JsonDict:
    lines = batch_lines(api, batch_id)
    assert lines, f"expected at least one payout line on batch {batch_id}"
    return lines[0]


def validate_batch(api, batch_id: str, statement_gross_cents: int, statement_fee_cents: int):
    return get_success_data(
        api.validate_payout_batch(
            batch_id,
            f.validate_batch_payload(statement_gross_cents, statement_fee_cents),
            FINANCE_ANALYST,
        )
    )


def approve_batch(api, batch_id: str, expected_version: int) -> JsonDict:
    return get_success_data(
        api.approve_payout_batch(
            batch_id, f.approve_batch_payload(expected_version), FINANCE_CONTROLLER
        )
    )


def pay_batch(api, batch_id: str, payment_reference: str = "WIRE-2026-08-05"):
    return get_success_data(
        api.pay_payout_batch(
            batch_id, f.pay_batch_payload(payment_reference), FINANCE_CONTROLLER
        )
    )


def void_batch(api, batch_id: str, reason: str = "period reopened by the network"):
    return get_success_data(
        api.void_payout_batch(batch_id, f.void_batch_payload(reason), FINANCE_CONTROLLER)
    )


def release_line_hold(api, line_id: str, reason: str = "hold cleared by finance"):
    return get_success_data(
        api.release_hold(line_id, f.release_hold_payload(reason), FINANCE_CONTROLLER)
    )


def ledger_entries(api, **params) -> List[JsonDict]:
    rows, _meta = _paginated(api.list_ledger_entries(FINANCE_CONTROLLER, params))
    return rows


def _paginated(response):
    body = response.json()
    assert 200 <= response.status_code < 300, (
        f"Setup listing failed with HTTP {response.status_code}: {response.text}"
    )
    return body["data"], body["meta"]
