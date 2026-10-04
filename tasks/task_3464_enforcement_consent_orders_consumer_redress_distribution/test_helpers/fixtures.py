"""Composite setup helpers (fixtures) for the enforcement pipeline.

Built only from PRD-declared endpoints; every test starts from an empty
database, so these helpers replay the full precondition chains. Setup calls
use get_success_data() so a setup failure surfaces as a clear setup error.

Logical-clock discipline (PRD section 2.5): the clock starts at exactly
2026-09-01T00:00:00Z and is only ever moved forward via the unprefixed
POST /_clock/set_current_utc. All default dates below are reachable by
advancing from that epoch; helpers never move the clock backward.

Identity threading (PRD section 2.1): entity-backed roles are always invoked
through make_company_representative_headers(company_id) /
make_claimant_headers(claimant_id); segregation-of-duties pairs default to
distinct operators (assessor cm-1 vs confirmer cm-2; approver fa-1 vs
issuer do-1).

Bundle convention: composite setups return a dict whose keys name the
entities built, e.g. {"company", "investigation", "order", "judgment",
"fund", "claimants", "claims", "checks"}.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_EPOCH_ISO,
    ADMIN_RESERVE_CAP_CENTS,
    LOSS_CAP_CENTS,
    PENALTY_RATES_PER_DAY_CENTS,
    PROVISIONAL_PROJECTION_DAYS,
    TEST_DEFAULTS,
)
from .factories import (
    clock_payload,
    create_subject_company_payload,
    create_investigation_payload,
    create_cid_payload,
    create_consent_order_payload,
    create_comment_payload,
    create_compliance_report_payload,
    create_violation_penalty_payload,
    create_judgment_payload,
    create_payment_payload,
    create_asset_trace_payload,
    create_claimant_payload,
    create_claim_payload,
    consent_order_transition_payload,
    redress_fund_transition_payload,
)
from .test_users import (
    TEST_USERS,
    make_company_representative_headers,
    make_claimant_headers,
)

_ADMIN = TEST_USERS["fund_administrator_headers"]          # fa-1
_ADMIN_2 = TEST_USERS["fund_administrator_2_headers"]      # fa-2
_OFFICER = TEST_USERS["disbursement_officer_headers"]      # do-1
_MONITOR_1 = TEST_USERS["compliance_monitor_headers"]      # cm-1
_MONITOR_2 = TEST_USERS["compliance_monitor_2_headers"]    # cm-2
_ATTORNEY = TEST_USERS["staff_attorney_headers"]
_COMMISSIONER = TEST_USERS["commissioner_headers"]
_ADMIN_READ = TEST_USERS["platform_admin_headers"]

_ORDER_TRANSITION_ACTOR = {
    "IN_PUBLIC_COMMENT": _ATTORNEY,
    "DRAFT": _ATTORNEY,
    "FINAL": _COMMISSIONER,
    "IN_MONITORING": _COMMISSIONER,
    "TERMINATED": _COMMISSIONER,
}

_INVESTIGATION_PATH = {
    "PRELIMINARY_REVIEW": ["PRELIMINARY_REVIEW"],
    "EVIDENCE_GATHERING": ["PRELIMINARY_REVIEW", "EVIDENCE_GATHERING"],
    "NEGOTIATING": ["PRELIMINARY_REVIEW", "EVIDENCE_GATHERING", "NEGOTIATING"],
}


# ---------------------------------------------------------------------------
# Date / time helpers (logical-clock arithmetic for tests)
# ---------------------------------------------------------------------------

def parse_iso(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def format_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def add_days_iso(iso: str, days: int) -> str:
    return format_iso(parse_iso(iso) + timedelta(days=days))


def add_years_iso(iso: str, years: int) -> str:
    dt = parse_iso(iso)
    try:
        dt = dt.replace(year=dt.year + years)
    except ValueError:  # Feb 29 -> Feb 28 clamp
        dt = dt.replace(year=dt.year + years, day=28)
    return format_iso(dt)


# ---------------------------------------------------------------------------
# Domain computation helpers (mirrors of PRD section 3 arithmetic, for
# boundary-targeting tests to derive expected values rather than hardcode)
# ---------------------------------------------------------------------------

def compute_waterfall(total_collected_cents: int, eligible_losses: list) -> dict:
    """Pinned-order redress waterfall (PRD section 3.6 steps 1-4).

    eligible_losses must be in created_at ASC order (remainder cents go to the
    earliest-created approved claim first). Returns total_eligible_cents,
    admin_reserve_cents, distributable_pool_cents, awards_cents (parallel list).
    """
    total_eligible = sum(eligible_losses)
    reserve = min(-(-total_eligible // 10), ADMIN_RESERVE_CAP_CENTS)  # ceil(10%)
    pool = total_collected_cents - reserve
    if total_eligible == 0:
        awards = [0 for _ in eligible_losses]
    elif pool >= total_eligible:
        awards = list(eligible_losses)
    else:
        awards = [(pool * e) // total_eligible for e in eligible_losses]
        remainder = pool - sum(awards)
        i = 0
        while remainder > 0:
            awards[i] += 1
            remainder -= 1
            i += 1
    return {
        "total_eligible_cents": total_eligible,
        "admin_reserve_cents": reserve,
        "distributable_pool_cents": pool,
        "awards_cents": awards,
    }


def expected_eligible_loss(documented_loss_cents: int) -> int:
    return min(documented_loss_cents, LOSS_CAP_CENTS)


def expected_provisional_penalty(severity: str, max_penalty_cents: int) -> dict:
    """Provisional variant: fixed 30-day projection, capped (PRD section 3.4)."""
    rate = PENALTY_RATES_PER_DAY_CENTS[severity]
    return {
        "provisional_days": PROVISIONAL_PROJECTION_DAYS,
        "provisional_amount_cents": min(rate * PROVISIONAL_PROJECTION_DAYS, max_penalty_cents),
    }


def expected_final_penalty(severity: str, detected_on: str, cured_on: str, max_penalty_cents: int) -> dict:
    """Final variant: whole days detected->cured, floored, minimum 1 (PRD 3.4)."""
    seconds = (parse_iso(cured_on) - parse_iso(detected_on)).total_seconds()
    final_days = max(1, int(seconds // 86400))
    rate = PENALTY_RATES_PER_DAY_CENTS[severity]
    return {
        "final_days": final_days,
        "final_amount_cents": min(rate * final_days, max_penalty_cents),
    }


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def advance_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (runs the automatic transition sweep)."""
    return get_success_data(
        api_client.set_current_utc(clock_payload(to_iso8601), _ADMIN_READ)
    )


def reset_clock_to_epoch() -> dict:
    return advance_clock(CLOCK_EPOCH_ISO)


# ---------------------------------------------------------------------------
# Atomic entity helpers
# ---------------------------------------------------------------------------

def create_company(complaint_count_90d=None, legal_name=None, **overrides) -> dict:
    payload_kwargs = dict(overrides)
    if legal_name is not None:
        payload_kwargs["legal_name"] = legal_name
    if complaint_count_90d is not None:
        payload_kwargs["complaint_count_90d"] = complaint_count_90d
    return get_success_data(
        api_client.create_subject_company(
            create_subject_company_payload(**payload_kwargs), _ADMIN_READ
        )
    )


def create_investigation(company_id, origin="REFERRAL", summary=None, attorney_headers=None, **overrides) -> dict:
    kwargs = dict(overrides)
    kwargs["origin"] = origin
    if summary is not None:
        kwargs["summary"] = summary
    return get_success_data(
        api_client.create_investigation(
            create_investigation_payload(company_id, **kwargs),
            attorney_headers or _ATTORNEY,
        )
    )


def get_investigation(investigation_id) -> dict:
    return get_success_data(api_client.get_investigation(investigation_id, _ATTORNEY))


def get_order(order_id) -> dict:
    return get_success_data(api_client.get_consent_order(order_id, _ADMIN_READ))


def get_fund(fund_id) -> dict:
    return get_success_data(api_client.get_redress_fund(fund_id, _ADMIN))


def get_judgment(judgment_id) -> dict:
    return get_success_data(api_client.get_judgment(judgment_id, _ADMIN_READ))


def get_claim(claim_id) -> dict:
    return get_success_data(api_client.get_claim(claim_id, _ADMIN))


def get_fund_for_judgment(judgment_id) -> dict:
    """The judgment's auto-created redress fund (GET returns an array of 0 or 1)."""
    funds = get_success_data(api_client.get_judgment_redress_fund(judgment_id, _ADMIN))
    assert isinstance(funds, list) and len(funds) == 1, (
        f"Setup failed: expected exactly 1 redress fund for judgment {judgment_id}, got {funds!r}"
    )
    return funds[0]


def get_latest_comment_period(order_id) -> dict:
    """Latest (highest-round) comment period; the listing is ordered round ASC."""
    periods = get_success_data(api_client.list_comment_periods(order_id, _ATTORNEY))
    assert isinstance(periods, list) and len(periods) >= 1, (
        f"Setup failed: no comment periods for order {order_id}"
    )
    return periods[-1]


# ---------------------------------------------------------------------------
# Investigation walk (Tier 1: state progression)
# ---------------------------------------------------------------------------

def advance_investigation_to_state(investigation_id, target_state, attorney_headers=None) -> dict:
    """Walk the investigation machine INTAKE -> ... -> target_state."""
    headers = attorney_headers or _ATTORNEY
    path = _INVESTIGATION_PATH[target_state]
    current = get_investigation(investigation_id)["status"]
    start = path.index(current) + 1 if current in path else 0
    data = None
    for step in path[start:]:
        data = get_success_data(
            api_client.transition_investigation(investigation_id, {"target_state": step}, headers)
        )
    return data if data is not None else get_investigation(investigation_id)


# ---------------------------------------------------------------------------
# Consent order lifecycle helpers (Tier 3)
# ---------------------------------------------------------------------------

def draft_consent_order(investigation_id, attorney_headers=None, **order_overrides) -> dict:
    """Draft a consent order (investigation auto-moves to SETTLED)."""
    return get_success_data(
        api_client.create_consent_order(
            investigation_id,
            create_consent_order_payload(**order_overrides),
            attorney_headers or _ATTORNEY,
        )
    )


def transition_order(order_id, target_state, actor_headers=None) -> dict:
    """OCC-safe order transition: re-reads the version, picks the role the
    target_state belongs to (StaffAttorney for propose/withdraw, Commissioner
    for FINAL/IN_MONITORING/TERMINATED)."""
    headers = actor_headers or _ORDER_TRANSITION_ACTOR[target_state]
    current_version = get_order(order_id)["version"]
    payload = consent_order_transition_payload(target_state, current_version)
    return get_success_data(api_client.transition_consent_order(order_id, payload, headers))


def propose_consent_order(order_id, attorney_headers=None) -> dict:
    """DRAFT -> IN_PUBLIC_COMMENT (opens a PublicCommentPeriod for the round)."""
    return transition_order(order_id, "IN_PUBLIC_COMMENT", attorney_headers)


def withdraw_consent_order(order_id, attorney_headers=None) -> dict:
    """IN_PUBLIC_COMMENT -> DRAFT (voids the OPEN period, bumps proposal_round)."""
    return transition_order(order_id, "DRAFT", attorney_headers)


def finalize_consent_order(order_id, at_iso=None, commissioner_headers=None) -> dict:
    """Close the latest comment period via the clock, then FINAL.

    at_iso defaults to the period's closes_at (the sweep closes it at exactly
    that instant). Never pass a time earlier than the current clock.
    """
    period = get_latest_comment_period(order_id)
    advance_clock(at_iso or period["closes_at"])
    return transition_order(order_id, "FINAL", commissioner_headers)


def start_monitoring(order_id, commissioner_headers=None) -> dict:
    """FINAL -> IN_MONITORING (stamps monitoring_started_at/ends_at)."""
    return transition_order(order_id, "IN_MONITORING", commissioner_headers)


def post_comment(period_id, author_email="watcher@public.org", body="Support the order as drafted.", headers=None) -> dict:
    return get_success_data(
        api_client.post_comment(
            period_id,
            create_comment_payload(author_email=author_email, body=body),
            headers or _ADMIN_READ,
        )
    )


# ---------------------------------------------------------------------------
# Judgment / fund helpers
# ---------------------------------------------------------------------------

def enter_judgment(order_id, amount_cents=None, commissioner_headers=None) -> dict:
    """Enter the monetary judgment; auto-creates the linked fund."""
    order = get_order(order_id)
    amount = amount_cents if amount_cents is not None else order["monetary_relief_cents"]
    return get_success_data(
        api_client.create_judgment(order_id, create_judgment_payload(amount_cents=amount), commissioner_headers or _COMMISSIONER)
    )


def record_payment(judgment_id, company_id, amount_cents, kind="COLLECTION") -> dict:
    """Company-representative payment/reversal (ownership-gated on company id)."""
    return get_success_data(
        api_client.create_payment(
            judgment_id,
            create_payment_payload(amount_cents=amount_cents, kind=kind),
            make_company_representative_headers(company_id),
        )
    )


def suspend_judgment(judgment_id, sworn_total_assets_cents, commissioner_headers=None) -> dict:
    return get_success_data(
        api_client.transition_judgment(
            judgment_id,
            {"target_state": "SUSPENDED", "sworn_total_assets_cents": sworn_total_assets_cents},
            commissioner_headers or _COMMISSIONER,
        )
    )


def reinstate_judgment(judgment_id, commissioner_headers=None) -> dict:
    return get_success_data(
        api_client.transition_judgment(
            judgment_id, {"target_state": "REINSTATED"}, commissioner_headers or _COMMISSIONER
        )
    )


def record_asset_trace(judgment_id, found_assets_cents, trace_ref="trace-1", attorney_headers=None) -> dict:
    return get_success_data(
        api_client.create_asset_trace(
            judgment_id,
            create_asset_trace_payload(found_assets_cents=found_assets_cents, trace_ref=trace_ref),
            attorney_headers or _ATTORNEY,
        )
    )


# ---------------------------------------------------------------------------
# Claimant / claim helpers
# ---------------------------------------------------------------------------

def identify_claimant(fund_id, full_name=None, email=None, identified_from="COMPANY_RECORDS", admin_headers=None) -> dict:
    kwargs = {"identified_from": identified_from}
    if full_name is not None:
        kwargs["full_name"] = full_name
    if email is not None:
        kwargs["email"] = email
    return get_success_data(
        api_client.create_claimant(fund_id, create_claimant_payload(**kwargs), admin_headers or _ADMIN)
    )


def make_claimant_specs(count: int, identified_from="COMPANY_RECORDS") -> list:
    """N distinct claimant specs: Claimant 01 <c01@example.com>, ..."""
    return [
        {
            "full_name": f"Claimant {i:02d}",
            "email": f"c{i:02d}@example.com",
            "identified_from": identified_from,
        }
        for i in range(1, count + 1)
    ]


def identify_claimants(fund_id, specs, admin_headers=None) -> list:
    return [identify_claimant(fund_id, admin_headers=admin_headers, **spec) for spec in specs]


def file_claim(claimant, documented_loss_cents, fund_id=None) -> dict:
    """File a claim as the claimant themself (X-User-ID == claimant id)."""
    return get_success_data(
        api_client.create_claim(
            create_claim_payload(
                claimant["id"],
                fund_id or claimant["redress_fund_id"],
                documented_loss_cents=documented_loss_cents,
            ),
            make_claimant_headers(claimant["id"]),
        )
    )


def move_claim_under_review(claim_id, admin_headers=None) -> dict:
    return get_success_data(
        api_client.transition_claim(claim_id, {"target_state": "UNDER_REVIEW"}, admin_headers or _ADMIN)
    )


def approve_claim(claim_id, admin_headers=None) -> dict:
    """FILED -> UNDER_REVIEW -> APPROVED. Returns the APPROVED claim data
    (whose provisional_award_cents reflects this approval's recomputation)."""
    move_claim_under_review(claim_id, admin_headers)
    return get_success_data(
        api_client.transition_claim(claim_id, {"target_state": "APPROVED"}, admin_headers or _ADMIN)
    )


def deny_claim(claim_id, denial_reason=None, admin_headers=None) -> dict:
    move_claim_under_review(claim_id, admin_headers)
    return get_success_data(
        api_client.transition_claim(
            claim_id,
            {"target_state": "DENIED", "denial_reason": denial_reason or TEST_DEFAULTS["DENIAL_REASON"]},
            admin_headers or _ADMIN,
        )
    )


def file_and_approve_claim(claimant, documented_loss_cents, admin_headers=None, fund_id=None) -> dict:
    claim = file_claim(claimant, documented_loss_cents, fund_id=fund_id)
    return approve_claim(claim["id"], admin_headers)


# ---------------------------------------------------------------------------
# Fund lifecycle helpers (OCC-guarded; Tier 5)
# ---------------------------------------------------------------------------

def transition_fund(fund_id, target_state, admin_headers=None, **extras) -> dict:
    """OCC-safe fund transition: re-reads expected_redress_fund_version.
    extras carries residual_recipient_name for RESIDUAL_DISPOSITION."""
    headers = admin_headers or _ADMIN
    current_version = get_fund(fund_id)["version"]
    payload = redress_fund_transition_payload(target_state, current_version, **extras)
    return get_success_data(api_client.transition_redress_fund(fund_id, payload, headers))


def close_claims_window(fund_id, admin_headers=None) -> dict:
    """OPEN_FOR_CLAIMS -> CLAIMS_CLOSED (recomputes reserve and pool)."""
    return transition_fund(fund_id, "CLAIMS_CLOSED", admin_headers)


def start_disbursing(fund_id, admin_headers=None) -> dict:
    """CLAIMS_CLOSED -> DISBURSING (freezes final_award_cents on APPROVED claims)."""
    return transition_fund(fund_id, "DISBURSING", admin_headers)


def enter_residual_disposition(fund_id, residual_recipient_name=None, admin_headers=None) -> dict:
    return transition_fund(
        fund_id,
        "RESIDUAL_DISPOSITION",
        admin_headers,
        residual_recipient_name=residual_recipient_name or TEST_DEFAULTS["RESIDUAL_RECIPIENT_NAME"],
    )


def close_fund(fund_id, admin_headers=None) -> dict:
    return transition_fund(fund_id, "CLOSED", admin_headers)


# ---------------------------------------------------------------------------
# Refund check helpers
# ---------------------------------------------------------------------------

def issue_check(claim_id, officer_headers=None) -> dict:
    """Issue (or reissue) the refund check. Default issuer do-1 differs from
    the default approver fa-1 (segregation of duties, PRD section 3.7)."""
    return get_success_data(
        api_client.issue_refund_check(claim_id, {}, officer_headers or _OFFICER)
    )


def cash_check(check_id, officer_headers=None) -> dict:
    return get_success_data(
        api_client.transition_refund_check(check_id, {"target_state": "CASHED"}, officer_headers or _OFFICER)
    )


def void_check(check_id, voided_reason=None, officer_headers=None) -> dict:
    return get_success_data(
        api_client.transition_refund_check(
            check_id,
            {"target_state": "VOIDED", "voided_reason": voided_reason or TEST_DEFAULTS["VOIDED_REASON"]},
            officer_headers or _OFFICER,
        )
    )


# ---------------------------------------------------------------------------
# Compliance report helpers
# ---------------------------------------------------------------------------

def submit_compliance_report(order_id, company_id, period_start=None, period_end=None,
                             report_document_ref=None, **overrides) -> dict:
    kwargs = dict(overrides)
    if period_start is not None:
        kwargs["period_start"] = period_start
    if period_end is not None:
        kwargs["period_end"] = period_end
    if report_document_ref is not None:
        kwargs["report_document_ref"] = report_document_ref
    return get_success_data(
        api_client.create_compliance_report(
            order_id,
            create_compliance_report_payload(**kwargs),
            make_company_representative_headers(company_id),
        )
    )


def accept_report(report_id, monitor_headers=None) -> dict:
    return get_success_data(
        api_client.transition_compliance_report(report_id, {"target_state": "ACCEPTED"}, monitor_headers or _MONITOR_1)
    )


def mark_report_deficient(report_id, deficiency_notes=None, monitor_headers=None) -> dict:
    return get_success_data(
        api_client.transition_compliance_report(
            report_id,
            {"target_state": "DEFICIENT", "deficiency_notes": deficiency_notes or TEST_DEFAULTS["DEFICIENCY_NOTES"]},
            monitor_headers or _MONITOR_1,
        )
    )


def resubmit_report(report_id, company_id, report_document_ref="doc-resubmission") -> dict:
    return get_success_data(
        api_client.transition_compliance_report(
            report_id,
            {"target_state": "SUBMITTED", "report_document_ref": report_document_ref},
            make_company_representative_headers(company_id),
        )
    )


# ---------------------------------------------------------------------------
# Violation penalty helpers (segregation of duties: assessor vs confirmer)
# ---------------------------------------------------------------------------

def assess_penalty(order_id, severity="AGGRAVATED", detected_on="2026-10-01T00:00:00Z",
                   description=None, monitor_headers=None, **overrides) -> dict:
    """Assess a provisional penalty. Default assessor is cm-1."""
    kwargs = {"severity": severity, "detected_on": detected_on}
    if description is not None:
        kwargs["description"] = description
    kwargs.update(overrides)
    return get_success_data(
        api_client.create_violation_penalty(
            order_id, create_violation_penalty_payload(**kwargs), monitor_headers or _MONITOR_1
        )
    )


def confirm_penalty(penalty_id, cured_on, monitor_headers=None) -> dict:
    """CONFIRMED transition. Default confirmer cm-2 differs from assessor cm-1."""
    return get_success_data(
        api_client.transition_violation_penalty(
            penalty_id, {"target_state": "CONFIRMED", "cured_on": cured_on}, monitor_headers or _MONITOR_2
        )
    )


def waive_penalty(penalty_id, monitor_headers=None) -> dict:
    return get_success_data(
        api_client.transition_violation_penalty(
            penalty_id, {"target_state": "WAIVED"}, monitor_headers or _MONITOR_2
        )
    )


def pay_penalty(penalty_id, company_id) -> dict:
    return get_success_data(
        api_client.transition_violation_penalty(
            penalty_id, {"target_state": "PAID"}, make_company_representative_headers(company_id)
        )
    )


# ---------------------------------------------------------------------------
# CID helpers
# ---------------------------------------------------------------------------

def create_draft_cid(investigation_id, response_due_date=None, subject_matter=None, attorney_headers=None, **overrides) -> dict:
    kwargs = dict(overrides)
    if response_due_date is not None:
        kwargs["response_due_date"] = response_due_date
    if subject_matter is not None:
        kwargs["subject_matter"] = subject_matter
    return get_success_data(
        api_client.create_cid(investigation_id, create_cid_payload(**kwargs), attorney_headers or _ATTORNEY)
    )


def issue_cid(cid_id, attorney_headers=None) -> dict:
    return get_success_data(
        api_client.transition_cid(cid_id, {"target_state": "ISSUED"}, attorney_headers or _ATTORNEY)
    )


def respond_to_cid(cid_id, company_id, response_document_ref="doc-response-1") -> dict:
    return get_success_data(
        api_client.transition_cid(
            cid_id,
            {"target_state": "RESPONDED", "response_document_ref": response_document_ref},
            make_company_representative_headers(company_id),
        )
    )


def quash_cid(cid_id, company_id) -> dict:
    return get_success_data(
        api_client.transition_cid(
            cid_id, {"target_state": "QUASH_PETITIONED"}, make_company_representative_headers(company_id)
        )
    )


def enforce_cid(cid_id, attorney_headers=None) -> dict:
    return get_success_data(
        api_client.transition_cid(cid_id, {"target_state": "ENFORCED"}, attorney_headers or _ATTORNEY)
    )


def withdraw_cid(cid_id, attorney_headers=None) -> dict:
    return get_success_data(
        api_client.transition_cid(cid_id, {"target_state": "WITHDRAWN"}, attorney_headers or _ATTORNEY)
    )


# ---------------------------------------------------------------------------
# Composite setups (Tiers 2-5) — the canonical pipeline bundles
# ---------------------------------------------------------------------------

def setup_negotiating_case(company_overrides=None, investigation_overrides=None) -> dict:
    """Company + investigation advanced to NEGOTIATING. Clock at the epoch."""
    reset_clock_to_epoch()
    company = create_company(**(company_overrides or {}))
    investigation = create_investigation(company["id"], **(investigation_overrides or {}))
    advance_investigation_to_state(investigation["id"], "NEGOTIATING")
    return {"company": company, "investigation": get_investigation(investigation["id"])}


def setup_draft_order(company_overrides=None, investigation_overrides=None, **order_overrides) -> dict:
    """Negotiating case + draft consent order (investigation now SETTLED)."""
    bundle = setup_negotiating_case(company_overrides, investigation_overrides)
    bundle["order"] = draft_consent_order(bundle["investigation"]["id"], **order_overrides)
    return bundle


def setup_proposed_order(company_overrides=None, investigation_overrides=None, **order_overrides) -> dict:
    """Draft order proposed: IN_PUBLIC_COMMENT with an OPEN comment period."""
    bundle = setup_draft_order(company_overrides, investigation_overrides, **order_overrides)
    bundle["order"] = propose_consent_order(bundle["order"]["id"])
    bundle["comment_period"] = get_latest_comment_period(bundle["order"]["id"])
    return bundle


def setup_final_order(clock_after_propose=None, company_overrides=None, investigation_overrides=None, **order_overrides) -> dict:
    """Order FINAL; comment period closed by the clock sweep at closes_at
    (or at the caller's later instant). Investigation bubbles to
    CLOSED_ORDER_ENTERED."""
    bundle = setup_proposed_order(company_overrides, investigation_overrides, **order_overrides)
    bundle["order"] = finalize_consent_order(bundle["order"]["id"], at_iso=clock_after_propose)
    bundle["comment_period"] = get_latest_comment_period(bundle["order"]["id"])
    bundle["investigation"] = get_investigation(bundle["investigation"]["id"])
    return bundle


def setup_monitored_order(clock_after_propose=None, company_overrides=None, investigation_overrides=None, **order_overrides) -> dict:
    """Order IN_MONITORING (monitoring_started_at stamped at the current clock)."""
    bundle = setup_final_order(clock_after_propose, company_overrides, investigation_overrides, **order_overrides)
    bundle["order"] = start_monitoring(bundle["order"]["id"])
    return bundle


def setup_judgment_with_fund(judgment_amount_cents=None, clock_after_propose=None,
                             company_overrides=None, investigation_overrides=None, **order_overrides) -> dict:
    """Monitored order + judgment entered + auto-created fund (ACCUMULATING)."""
    bundle = setup_monitored_order(clock_after_propose, company_overrides, investigation_overrides, **order_overrides)
    bundle["judgment"] = enter_judgment(bundle["order"]["id"], judgment_amount_cents)
    bundle["fund"] = get_fund_for_judgment(bundle["judgment"]["id"])
    return bundle


def setup_open_fund(judgment_amount_cents=None, claimant_specs=None, collect_cents=None,
                    identify_before_payment=True, clock_after_propose=None,
                    company_overrides=None, investigation_overrides=None, **order_overrides) -> dict:
    """Fund OPEN_FOR_CLAIMS via a collection payment.

    claimant_specs: list of identify_claimant kwargs (or use
    make_claimant_specs(n)). identify_before_payment=True exercises the
    opening cascade (IDENTIFIED -> NOTIFIED); False exercises immediate
    notification at identification on an already-open fund.
    collect_cents defaults to the full judgment amount.
    """
    bundle = setup_judgment_with_fund(
        judgment_amount_cents, clock_after_propose, company_overrides, investigation_overrides, **order_overrides
    )
    fund_id = bundle["fund"]["id"]
    company_id = bundle["company"]["id"]
    claimants = []
    if claimant_specs and identify_before_payment:
        claimants = identify_claimants(fund_id, claimant_specs)
    amount = collect_cents if collect_cents is not None else bundle["judgment"]["amount_cents"]
    record_payment(bundle["judgment"]["id"], company_id, amount, kind="COLLECTION")
    if claimant_specs and not identify_before_payment:
        claimants = identify_claimants(fund_id, claimant_specs)
    bundle["claimants"] = claimants
    bundle["judgment"] = get_judgment(bundle["judgment"]["id"])
    bundle["fund"] = get_fund(fund_id)
    return bundle


def setup_fund_with_approved_claims(losses, judgment_amount_cents=None, claimant_specs=None,
                                    admin_headers=None, clock_after_propose=None,
                                    company_overrides=None, investigation_overrides=None,
                                    **order_overrides) -> dict:
    """OPEN_FOR_CLAIMS fund with one approved claim per loss figure.

    losses are filed and approved in list order, so claims[0] is the
    earliest-created (the waterfall remainder order). claimants default to
    one generated spec per loss; pass claimant_specs to add extra non-filing
    claimants (claim-rate tests).
    """
    specs = claimant_specs if claimant_specs is not None else make_claimant_specs(len(losses))
    bundle = setup_open_fund(
        judgment_amount_cents=judgment_amount_cents,
        claimant_specs=specs,
        clock_after_propose=clock_after_propose,
        company_overrides=company_overrides,
        investigation_overrides=investigation_overrides,
        **order_overrides,
    )
    claims = []
    for claimant, loss in zip(bundle["claimants"], losses):
        claims.append(file_and_approve_claim(claimant, loss, admin_headers=admin_headers))
    bundle["claims"] = claims
    bundle["fund"] = get_fund(bundle["fund"]["id"])
    return bundle


def setup_disbursing_fund(losses, judgment_amount_cents=None, claimant_specs=None,
                          admin_headers=None, clock_after_propose=None,
                          company_overrides=None, investigation_overrides=None,
                          **order_overrides) -> dict:
    """Fund DISBURSING: approved claims carry frozen final_award_cents."""
    bundle = setup_fund_with_approved_claims(
        losses,
        judgment_amount_cents=judgment_amount_cents,
        claimant_specs=claimant_specs,
        admin_headers=admin_headers,
        clock_after_propose=clock_after_propose,
        company_overrides=company_overrides,
        investigation_overrides=investigation_overrides,
        **order_overrides,
    )
    fund_id = bundle["fund"]["id"]
    bundle["fund"] = close_claims_window(fund_id, admin_headers)
    bundle["fund"] = start_disbursing(fund_id, admin_headers)
    bundle["claims"] = [get_claim(c["id"]) for c in bundle["claims"]]
    return bundle


def setup_check_issued_fund(losses=(500_000,), officer_headers=None, **kwargs) -> dict:
    """DISBURSING fund with the first claim's check ISSUED (claim PAYMENT_PENDING)."""
    bundle = setup_disbursing_fund(list(losses), **kwargs)
    check = issue_check(bundle["claims"][0]["id"], officer_headers)
    bundle["checks"] = [check]
    bundle["claims"][0] = get_claim(bundle["claims"][0]["id"])
    bundle["fund"] = get_fund(bundle["fund"]["id"])
    return bundle


def setup_residual_ready_fund(losses=(500_000,), officer_headers=None, **kwargs) -> dict:
    """DISBURSING fund with every approved claim's check ISSUED and CASHED —
    ready for the RESIDUAL_DISPOSITION transition (no checks outstanding)."""
    bundle = setup_disbursing_fund(list(losses), **kwargs)
    checks = []
    for claim in bundle["claims"]:
        check = issue_check(claim["id"], officer_headers)
        checks.append(cash_check(check["id"], officer_headers))
    bundle["checks"] = checks
    bundle["claims"] = [get_claim(c["id"]) for c in bundle["claims"]]
    bundle["fund"] = get_fund(bundle["fund"]["id"])
    return bundle


def setup_suspended_judgment(sworn_total_assets_cents=100_000, judgment_amount_cents=3_000_000,
                             **kwargs) -> dict:
    """Judgment SUSPENDED on a sworn inability-to-pay showing (fund untouched)."""
    kwargs.setdefault("monetary_relief_cents", judgment_amount_cents)
    bundle = setup_judgment_with_fund(judgment_amount_cents=judgment_amount_cents, **kwargs)
    bundle["judgment"] = suspend_judgment(bundle["judgment"]["id"], sworn_total_assets_cents)
    return bundle


def setup_issued_cid(response_due_date=None, company_overrides=None, investigation_overrides=None,
                     subject_matter=None) -> dict:
    """Company + investigation in EVIDENCE_GATHERING + CID moved DRAFT->ISSUED."""
    reset_clock_to_epoch()
    company = create_company(**(company_overrides or {}))
    investigation = create_investigation(company["id"], **(investigation_overrides or {}))
    advance_investigation_to_state(investigation["id"], "EVIDENCE_GATHERING")
    cid = create_draft_cid(investigation["id"], response_due_date=response_due_date, subject_matter=subject_matter)
    cid = issue_cid(cid["id"])
    return {"company": company, "investigation": get_investigation(investigation["id"]), "cid": cid}
