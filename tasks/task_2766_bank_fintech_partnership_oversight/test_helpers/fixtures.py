"""Composite setup helpers.

These encapsulate the multi-step chains the API demands before an interesting
rule becomes reachable: a partner has to be registered, underwritten, contracted
and launched before a single cent may move, and custody accounts only ever come
into existence as a side effect of executing a program agreement.

Every helper uses the lenient success reader so that a broken preamble surfaces
as a setup failure rather than as a confusing assertion further down.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CYCLE_1_END, CYCLE_1_START, CYCLE_2_END, CYCLE_2_START
from .factories import (
    create_agreement_payload,
    create_alert_payload,
    create_complaint_payload,
    create_cycle_payload,
    create_diligence_review_payload,
    create_ledger_entry_payload,
    create_marketing_review_payload,
    create_partner_payload,
    create_settlement_batch_payload,
    create_wind_down_plan_payload,
)
from .test_users import (
    COMPLIANCE_OFFICER_1,
    INTERNAL_AUDIT_1,
    PROGRAM_OFFICER_1,
    RISK_COMMITTEE_1,
    make_compliance_officer_headers,
    make_fintech_partner_headers,
    make_internal_audit_headers,
    make_program_officer_headers,
    make_risk_committee_headers,
)

PO = make_program_officer_headers(PROGRAM_OFFICER_1)
CO = make_compliance_officer_headers(COMPLIANCE_OFFICER_1)
RC = make_risk_committee_headers(RISK_COMMITTEE_1)
IA = make_internal_audit_headers(INTERNAL_AUDIT_1)


# --------------------------------------------------------------------------
# Tier 0: the logical clock and the oversight epoch
# --------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Move the server's logical clock. Performs no recomputation."""
    return get_success_data(api_client.set_current_utc(to_iso8601, PO))


def open_cycle(cycle_label="2026-08", period_start=CYCLE_1_START, period_end=CYCLE_1_END) -> dict:
    """Open an oversight cycle so that ledger entries have a period to book into."""
    return get_success_data(
        api_client.create_cycle(
            create_cycle_payload(
                cycle_label=cycle_label, period_start=period_start, period_end=period_end
            ),
            PO,
        )
    )


def open_second_cycle(cycle_label="2026-09") -> dict:
    return open_cycle(cycle_label, CYCLE_2_START, CYCLE_2_END)


def close_cycle(cycle_id, closing_note=None) -> dict:
    payload = {} if closing_note is None else {"closing_note": closing_note}
    return get_success_data(api_client.close_cycle(cycle_id, payload, PO))


# --------------------------------------------------------------------------
# Tier 1: partner state progression
# --------------------------------------------------------------------------

def create_partner(**overrides) -> dict:
    """Register a prospective partner. Lands in PROSPECT with version 1."""
    return get_success_data(api_client.create_partner(create_partner_payload(**overrides), PO))


def read_partner(partner_id) -> dict:
    return get_success_data(api_client.get_partner(partner_id, PO))


def pass_diligence(
    partner,
    business_model_score=91,
    funding_score=87,
    compliance_capability_score=89,
    complaint_history_score=100,
    review_type="INITIAL",
    submitter_headers=None,
    decider_headers=None,
    **review_overrides,
):
    """Open, submit and pass one diligence file. Returns (review, refreshed partner).

    The submitting officer and the deciding compliance officer are deliberately
    different users, since a decision may not be taken by the submitter.
    """
    submitter_headers = submitter_headers or PO
    decider_headers = decider_headers or CO
    partner = read_partner(partner["id"])
    review = get_success_data(
        api_client.create_diligence_review(
            create_diligence_review_payload(
                partner["id"],
                partner["version"],
                review_type=review_type,
                business_model_score=business_model_score,
                funding_score=funding_score,
                compliance_capability_score=compliance_capability_score,
                complaint_history_score=complaint_history_score,
                **review_overrides,
            ),
            submitter_headers,
        )
    )
    review = get_success_data(
        api_client.submit_diligence_review(review["id"], {}, submitter_headers)
    )
    review = get_success_data(
        api_client.decide_diligence_review(review["id"], {"outcome": "PASSED"}, decider_headers)
    )
    return review, read_partner(partner["id"])


def execute_agreement(partner, drafter_headers=None, decider_headers=None, **agreement_overrides):
    """Draft, route and execute one program agreement.

    Execution contracts the partner and opens its two custody accounts, so this
    is the only route by which custody comes into existence.
    Returns (agreement, refreshed partner).
    """
    drafter_headers = drafter_headers or PO
    decider_headers = decider_headers or RC
    partner = read_partner(partner["id"])
    agreement = get_success_data(
        api_client.create_agreement(
            create_agreement_payload(partner["id"], partner["version"], **agreement_overrides),
            drafter_headers,
        )
    )
    agreement = get_success_data(
        api_client.submit_agreement_for_approval(agreement["id"], {}, drafter_headers)
    )
    agreement = get_success_data(
        api_client.decide_agreement_risk(agreement["id"], {"decision": "EXECUTE"}, decider_headers)
    )
    return agreement, read_partner(partner["id"])


def custody_accounts(partner_id):
    """Return (fbo_end_user_account, reserve_account) for a contracted partner."""
    fbo = get_success_data(
        api_client.list_custody_accounts(
            PO, params={"partner_id": partner_id, "account_type": "FBO_END_USER"}
        )
    )
    reserve = get_success_data(
        api_client.list_custody_accounts(
            PO, params={"partner_id": partner_id, "account_type": "RESERVE"}
        )
    )
    return fbo[0], reserve[0]


def read_custody_account(account_id) -> dict:
    return get_success_data(api_client.get_custody_account(account_id, PO))


# --------------------------------------------------------------------------
# Tier 2: seeding custody balances
# --------------------------------------------------------------------------

def post_ledger_entry(partner_id, account, entry_type, amount_cents,
                      effective_at=CYCLE_1_START, headers=None, **overrides):
    """Post one manual custody movement, quoting the account's current version."""
    headers = headers or PO
    account = read_custody_account(account["id"])
    return api_client.create_ledger_entry(
        create_ledger_entry_payload(
            partner_id,
            account["id"],
            account["version"],
            entry_type=entry_type,
            amount_cents=amount_cents,
            effective_at=effective_at,
            **overrides
        ),
        headers,
    )


def seed_end_user_balance(partner_id, fbo_account, amount_cents, effective_at=CYCLE_1_START):
    """Put cents into an FBO_END_USER account with a VARIANCE_ADJUSTMENT.

    A variance adjustment may carry either sign and is not an end-user credit,
    so it bootstraps a balance without passing through the inflow gates that
    guard END_USER_CREDIT.
    """
    return get_success_data(
        post_ledger_entry(
            partner_id, fbo_account, "VARIANCE_ADJUSTMENT", amount_cents, effective_at
        )
    )


def seed_reserve_balance(partner_id, reserve_account, amount_cents, effective_at=CYCLE_1_START):
    """Fund a RESERVE account so that reserve_shortfall_cents can reach 0."""
    return get_success_data(
        post_ledger_entry(
            partner_id, reserve_account, "RESERVE_FUND", amount_cents, effective_at
        )
    )


def launch_partner(partner_id, attestation_note=None) -> dict:
    payload = {} if attestation_note is None else {"attestation_note": attestation_note}
    return get_success_data(api_client.go_live(partner_id, payload, PO))


# --------------------------------------------------------------------------
# Tier 3: full-lifecycle composites
# --------------------------------------------------------------------------

def setup_contracted_partner(
    partner_overrides=None,
    agreement_overrides=None,
    open_the_cycle=True,
    cycle_label="2026-08",
):
    """Register, underwrite and contract one partner.

    Returns a dict with keys cycle, partner, review, agreement, fbo, reserve.
    """
    cycle = open_cycle(cycle_label) if open_the_cycle else None
    partner = create_partner(**(partner_overrides or {}))
    review, partner = pass_diligence(partner)
    agreement, partner = execute_agreement(partner, **(agreement_overrides or {}))
    fbo, reserve = custody_accounts(partner["id"])
    return {
        "cycle": cycle,
        "partner": partner,
        "review": review,
        "agreement": agreement,
        "fbo": fbo,
        "reserve": reserve,
    }


def setup_live_partner(
    partner_overrides=None,
    agreement_overrides=None,
    fbo_balance_cents=20_000_000,
    reserve_balance_cents=1_250_000,
    open_the_cycle=True,
    cycle_label="2026-08",
    effective_at=CYCLE_1_START,
):
    """Walk one partner all the way to LIVE with seeded custody balances.

    The reserve is seeded before launch because launch requires
    reserve_shortfall_cents to be exactly 0.
    Returns a dict with keys cycle, partner, review, agreement, fbo, reserve.
    """
    ctx = setup_contracted_partner(
        partner_overrides=partner_overrides,
        agreement_overrides=agreement_overrides,
        open_the_cycle=open_the_cycle,
        cycle_label=cycle_label,
    )
    if fbo_balance_cents:
        seed_end_user_balance(ctx["partner"]["id"], ctx["fbo"], fbo_balance_cents, effective_at)
    if reserve_balance_cents:
        seed_reserve_balance(
            ctx["partner"]["id"], ctx["reserve"], reserve_balance_cents, effective_at
        )
    ctx["partner"] = launch_partner(ctx["partner"]["id"])
    ctx["fbo"], ctx["reserve"] = custody_accounts(ctx["partner"]["id"])
    return ctx


def setup_ballast_partner(fbo_balance_cents, cycle_open=False, legal_name="Ballast Bank Partner Inc"):
    """A second contracted partner holding end-user custody.

    The concentration ratio is measured against the bank's whole end-user book,
    so a single-partner bank always reads 100.00 percent. A ballast partner in a
    separate corporate group supplies the denominator that lets a first
    END_USER_CREDIT clear a concentration cap below 100.
    Returns a dict with keys partner, agreement, fbo, reserve.
    """
    if cycle_open:
        open_cycle()
    partner = create_partner(legal_name=legal_name)
    _review, partner = pass_diligence(partner)
    agreement, partner = execute_agreement(partner)
    fbo, reserve = custody_accounts(partner["id"])
    if fbo_balance_cents:
        seed_end_user_balance(partner["id"], fbo, fbo_balance_cents)
    return {
        "partner": read_partner(partner["id"]),
        "agreement": agreement,
        "fbo": read_custody_account(fbo["id"]),
        "reserve": read_custody_account(reserve["id"]),
    }


# --------------------------------------------------------------------------
# Tier 4: settlement batches
# --------------------------------------------------------------------------

def create_batch(partner_id, headers=None, **overrides) -> dict:
    headers = headers or PO
    return get_success_data(
        api_client.create_settlement_batch(
            create_settlement_batch_payload(partner_id, **overrides), headers
        )
    )


def reconcile_batch(batch_id, bank_reported_net_cents, headers=None) -> dict:
    headers = headers or IA
    return get_success_data(
        api_client.reconcile_settlement_batch(
            batch_id, {"bank_reported_net_cents": bank_reported_net_cents}, headers
        )
    )


def clear_variance(batch_id, variance_adjustment_cents, root_cause_note="late interchange file"):
    return get_success_data(
        api_client.clear_settlement_variance(
            batch_id,
            {
                "variance_adjustment_cents": variance_adjustment_cents,
                "root_cause_note": root_cause_note,
            },
            IA,
        )
    )


def fund_batch(batch_id, funding_reference="WIRE-1") -> dict:
    return get_success_data(
        api_client.fund_settlement_batch(batch_id, {"funding_reference": funding_reference}, PO)
    )


def clawback_batch(batch_id, clawback_reason="RECONCILIATION_ERROR", headers=None) -> dict:
    headers = headers or PO
    return get_success_data(
        api_client.clawback_settlement_batch(
            batch_id, {"clawback_reason": clawback_reason}, headers
        )
    )


def read_batch(batch_id, headers=None) -> dict:
    headers = headers or PO
    return get_success_data(api_client.get_settlement_batch(batch_id, headers))


def batch_ledger_entries(partner_id, batch_id, headers=None) -> list:
    """Every synthesised ledger leg carrying this batch's id, oldest first."""
    headers = headers or PO
    entries = get_success_data(
        api_client.list_ledger_entries(headers, {"partner_id": partner_id, "limit": 100})
    )
    return [e for e in entries if e.get("settlement_batch_id") == batch_id]


def setup_matched_batch(partner_id, gross_settlement_cents=8_000_000, interchange_cents=120_000,
                        returns_cents=45_000, partner_reported_net_cents=8_000_000, **overrides):
    """A batch whose bank figure equals the partner figure, so it lands MATCHED."""
    batch = create_batch(
        partner_id,
        gross_settlement_cents=gross_settlement_cents,
        interchange_cents=interchange_cents,
        returns_cents=returns_cents,
        partner_reported_net_cents=partner_reported_net_cents,
        **overrides
    )
    return reconcile_batch(batch["id"], partner_reported_net_cents)


def setup_variance_cleared_batch(partner_id, variance_adjustment_cents=30_000,
                                 gross_settlement_cents=8_000_000, interchange_cents=120_000,
                                 returns_cents=45_000, partner_reported_net_cents=8_000_000,
                                 **overrides):
    """A batch driven through VARIANCE_OPEN and out again into VARIANCE_CLEARED."""
    batch = create_batch(
        partner_id,
        gross_settlement_cents=gross_settlement_cents,
        interchange_cents=interchange_cents,
        returns_cents=returns_cents,
        partner_reported_net_cents=partner_reported_net_cents,
        **overrides
    )
    batch = reconcile_batch(
        batch["id"], partner_reported_net_cents + variance_adjustment_cents
    )
    return clear_variance(batch["id"], variance_adjustment_cents)


def setup_funded_batch(partner_id, funding_reference="WIRE-1", **batch_overrides):
    """A MATCHED batch taken all the way to FUNDED."""
    batch = setup_matched_batch(partner_id, **batch_overrides)
    return fund_batch(batch["id"], funding_reference)


# --------------------------------------------------------------------------
# Tier 5: complaints, alerts and marketing
# --------------------------------------------------------------------------

def file_complaint(partner_id, headers=None, **overrides) -> dict:
    headers = headers or CO
    return get_success_data(
        api_client.create_complaint(create_complaint_payload(partner_id, **overrides), headers)
    )


def assign_root_cause(complaint_id, root_cause_code="FEE_CONFIG_ERROR",
                      investigation_note="the posting job double-charged the maintenance fee"):
    return get_success_data(
        api_client.assign_complaint_root_cause(
            complaint_id,
            {"root_cause_code": root_cause_code, "investigation_note": investigation_note},
            CO,
        )
    )


def dispose_complaint(complaint_id, outcome, resolution_note="handled", **overrides):
    payload = {"outcome": outcome, "resolution_note": resolution_note}
    payload.update(overrides)
    return get_success_data(api_client.dispose_complaint(complaint_id, payload, CO))


def raise_alert(partner_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_alert(create_alert_payload(partner_id, **overrides), CO)
    )


def raise_sanctions_alert(partner_id, triggered_at="2026-07-25T09:00:00Z", **overrides) -> dict:
    """A single open sanctions hit is enough to drive the posture to FROZEN."""
    overrides.setdefault("alert_type", "SANCTIONS_HIT")
    overrides.setdefault(
        "detection_note", "name match against a sanctions list on an inbound transfer"
    )
    return raise_alert(partner_id, triggered_at=triggered_at, **overrides)


def dispose_alert(alert_id, disposition, disposition_note="closed after full review of the flow"):
    return get_success_data(
        api_client.dispose_alert(
            alert_id, {"disposition": disposition, "disposition_note": disposition_note}, CO
        )
    )


def file_marketing_review(partner_id, agreement_id, headers=None, **overrides) -> dict:
    """Filing is the submission: material lands directly in SUBMITTED."""
    headers = headers or PO
    return get_success_data(
        api_client.create_marketing_review(
            create_marketing_review_payload(partner_id, agreement_id, **overrides), headers
        )
    )


def decide_marketing_review(review_id, decision, headers=None, **overrides) -> dict:
    headers = headers or CO
    payload = {"decision": decision}
    payload.update(overrides)
    return get_success_data(api_client.decide_marketing_review(review_id, payload, headers))


def approve_marketing_review(partner_id, agreement_id, **overrides) -> dict:
    review = file_marketing_review(partner_id, agreement_id, **overrides)
    return decide_marketing_review(review["id"], "APPROVE", decision_note="approved for run")


# --------------------------------------------------------------------------
# Tier 6: termination and wind-down
# --------------------------------------------------------------------------

def terminate_agreement(agreement_id, termination_trigger="VOLUNTARY", notice_days=30) -> dict:
    """Termination is exercised on the agreement, not on the partner."""
    return get_success_data(
        api_client.terminate_agreement(
            agreement_id,
            {"termination_trigger": termination_trigger, "notice_days": notice_days},
            RC,
        )
    )


def draft_wind_down_plan(partner_id, headers=None, **overrides) -> dict:
    headers = headers or PO
    return get_success_data(
        api_client.create_wind_down_plan(
            create_wind_down_plan_payload(partner_id, **overrides), headers
        )
    )


def approve_wind_down_plan(plan_id, drafter_headers=None, decider_headers=None) -> dict:
    """Submit and approve a drafted plan with two different actors."""
    drafter_headers = drafter_headers or PO
    decider_headers = decider_headers or RC
    plan = get_success_data(api_client.submit_wind_down_plan(plan_id, {}, drafter_headers))
    return get_success_data(
        api_client.decide_wind_down_plan(plan_id, {"decision": "APPROVE"}, decider_headers)
    )


def setup_wind_down_partner(fbo_balance_cents=4_000_000, reserve_balance_cents=333_000,
                            partner_overrides=None, agreement_overrides=None,
                            termination_trigger="VOLUNTARY"):
    """A LIVE partner terminated into WIND_DOWN with custody still holding cents.

    Returns a dict with keys cycle, partner, agreement, fbo, reserve.
    """
    overrides = {"termination_triggers": ["VOLUNTARY"]}
    overrides.update(agreement_overrides or {})
    ctx = setup_live_partner(
        partner_overrides=partner_overrides,
        agreement_overrides=overrides,
        fbo_balance_cents=fbo_balance_cents,
        reserve_balance_cents=reserve_balance_cents,
    )
    ctx["agreement"] = terminate_agreement(ctx["agreement"]["id"], termination_trigger)
    ctx["partner"] = read_partner(ctx["partner"]["id"])
    ctx["fbo"], ctx["reserve"] = custody_accounts(ctx["partner"]["id"])
    return ctx


def drain_custody(partner_id, fbo, reserve, effective_at=CYCLE_2_START):
    """Empty both custody accounts with ordinary movements.

    There is no manual completion step for a wind-down plan: the operator drains
    the accounts and the next cycle close notices the residual has reached zero.
    """
    fbo = read_custody_account(fbo["id"])
    if fbo["balance_cents"]:
        get_success_data(
            post_ledger_entry(
                partner_id, fbo, "END_USER_DEBIT", -fbo["balance_cents"], effective_at
            )
        )
    reserve = read_custody_account(reserve["id"])
    if reserve["balance_cents"]:
        get_success_data(
            post_ledger_entry(
                partner_id, reserve, "RESERVE_RELEASE", -reserve["balance_cents"], effective_at
            )
        )
    return custody_accounts(partner_id)


def oversight_summary(partner_id) -> dict:
    return get_success_data(api_client.get_oversight_summary(partner_id, PO))
