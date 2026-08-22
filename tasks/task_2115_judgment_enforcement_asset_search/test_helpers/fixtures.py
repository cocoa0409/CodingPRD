"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared endpoints,
because each test starts against an empty database.  Setup calls go through the
lenient validator so a broken precondition surfaces as "Setup step failed".
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_DATE, TEST_DEFAULTS
from .factories import (
    create_asset_finding_payload,
    create_county_filing_payload,
    create_creditor_payload,
    create_debtor_payload,
    create_employment_finding_payload,
    create_enforcement_action_payload,
    create_examination_payload,
    create_exemption_claim_payload,
    create_judgment_payload,
    create_payment_payload,
    create_settlement_offer_payload,
    issue_subpoena_payload,
    skip_trace_payload,
)
from .test_users import (
    make_asset_investigator_headers,
    make_case_manager_headers,
    make_compliance_officer_headers,
    make_debtor_headers,
    make_enforcement_officer_headers,
)

CM = make_case_manager_headers()


# ==========================================================================
# Tier 0 — single-row creation
# ==========================================================================
def create_creditor(**overrides) -> dict:
    return get_success_data(
        api_client.create_creditor(create_creditor_payload(**overrides), CM)
    )


def create_debtor(**overrides) -> dict:
    return get_success_data(
        api_client.create_debtor(create_debtor_payload(**overrides), CM)
    )


def create_judgment(creditor_id: str, debtor_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_judgment(
            create_judgment_payload(creditor_id, debtor_id, **overrides), CM
        )
    )


def read_judgment(judgment_id: str) -> dict:
    return get_success_data(api_client.get_judgment(judgment_id, CM))


def judgment_version(judgment_id: str) -> int:
    return read_judgment(judgment_id)["version"]


def read_debtor(debtor_id: str) -> dict:
    return get_success_data(api_client.get_debtor(debtor_id, CM))


def debtor_version(debtor_id: str) -> int:
    return read_debtor(debtor_id)["version"]


def read_finding(finding_id: str) -> dict:
    return get_success_data(
        api_client.get_asset_finding(finding_id, make_asset_investigator_headers())
    )


def read_action(action_id: str) -> dict:
    return get_success_data(api_client.get_enforcement_action(action_id, CM))


def read_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_exemption_claim(claim_id, CM))


def read_examination(examination_id: str) -> dict:
    return get_success_data(api_client.get_examination(examination_id, CM))


def read_offer(offer_id: str) -> dict:
    return get_success_data(api_client.get_settlement_offer(offer_id, CM))


def read_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.get_installment_agreement(agreement_id, CM))


def read_filing(filing_id: str) -> dict:
    return get_success_data(api_client.get_county_filing(filing_id, CM))


def read_payment(payment_id: str) -> dict:
    return get_success_data(api_client.get_payment(payment_id, CM))


def advance_clock(to_iso8601: str, headers=None) -> dict:
    """Move the logical clock forward, running the four-step docket sweep."""
    return get_success_data(api_client.set_clock(to_iso8601, headers or CM))


# ==========================================================================
# Tier 1 — state progression on one entity
# ==========================================================================
def locate_debtor(debtor_id: str, investigator_user_id: str = "inv-1", **overrides) -> dict:
    """Run one completed skip trace so locate_status becomes LOCATED."""
    payload = skip_trace_payload(debtor_version(debtor_id), **overrides)
    return get_success_data(
        api_client.skip_trace(
            debtor_id, payload, make_asset_investigator_headers(investigator_user_id)
        )
    )


def record_county_filing(judgment_id: str, recorded_on: str = DEFAULT_CLOCK_DATE,
                         **overrides) -> dict:
    """Draft, submit and record one county filing.  Returns the RECORDED row."""
    filing = get_success_data(
        api_client.create_county_filing(
            create_county_filing_payload(judgment_id, **overrides), CM
        )
    )
    get_success_data(api_client.submit_county_filing(filing["id"], CM))
    return get_success_data(
        api_client.adjudicate_county_filing(
            filing["id"], {"outcome": "RECORDED", "recorded_on": recorded_on}, CM
        )
    )


def submit_county_filing(judgment_id: str, **overrides) -> dict:
    """Draft and submit one county filing, stopping short of adjudication."""
    filing = get_success_data(
        api_client.create_county_filing(
            create_county_filing_payload(judgment_id, **overrides), CM
        )
    )
    return get_success_data(api_client.submit_county_filing(filing["id"], CM))


def create_open_finding(judgment_id: str, investigator_user_id: str = "inv-1",
                        **overrides) -> dict:
    return get_success_data(
        api_client.create_asset_finding(
            create_asset_finding_payload(judgment_id, **overrides),
            make_asset_investigator_headers(investigator_user_id),
        )
    )


def create_verified_finding(judgment_id: str, investigator_user_id: str = "inv-1",
                            **overrides) -> dict:
    finding = create_open_finding(judgment_id, investigator_user_id, **overrides)
    return get_success_data(
        api_client.verify_asset_finding(
            finding["id"], make_asset_investigator_headers(investigator_user_id)
        )
    )


def create_verified_employment_finding(judgment_id: str,
                                       weekly_disposable_earnings_cents: int,
                                       investigator_user_id: str = "inv-1",
                                       **overrides) -> dict:
    finding = get_success_data(
        api_client.create_asset_finding(
            create_employment_finding_payload(
                judgment_id, weekly_disposable_earnings_cents, **overrides
            ),
            make_asset_investigator_headers(investigator_user_id),
        )
    )
    return get_success_data(
        api_client.verify_asset_finding(
            finding["id"], make_asset_investigator_headers(investigator_user_id)
        )
    )


def draft_enforcement_action(judgment_id: str, finding_id: str,
                             action_type: str = "BANK_LEVY", **overrides) -> dict:
    payload = create_enforcement_action_payload(
        judgment_id, finding_id, judgment_version(judgment_id),
        action_type=action_type, **overrides
    )
    return get_success_data(api_client.create_enforcement_action(payload, CM))


# ==========================================================================
# Tier 2 — entity hierarchy
# ==========================================================================
def setup_judgment(creditor_overrides=None, debtor_overrides=None, **judgment_overrides):
    """Creditor + debtor + docketed judgment.  Returns a context dict."""
    creditor = create_creditor(**(creditor_overrides or {}))
    debtor = create_debtor(**(debtor_overrides or {}))
    judgment = create_judgment(creditor["id"], debtor["id"], **judgment_overrides)
    return {"creditor": creditor, "debtor": debtor, "judgment": judgment}


def setup_perfected_judgment(creditor_overrides=None, debtor_overrides=None,
                             filing_overrides=None, recorded_on=DEFAULT_CLOCK_DATE,
                             **judgment_overrides):
    """A judgment whose county filing has been recorded in the debtor's own state,
    so enforcement_posture stands at LIEN_PERFECTED."""
    ctx = setup_judgment(creditor_overrides, debtor_overrides, **judgment_overrides)
    ctx["filing"] = record_county_filing(
        ctx["judgment"]["id"], recorded_on=recorded_on, **(filing_overrides or {})
    )
    ctx["judgment"] = read_judgment(ctx["judgment"]["id"])
    return ctx


# ==========================================================================
# Tier 3 — full enforcement lifecycle shortcuts
# ==========================================================================
def setup_drafted_bank_levy(finding_value_cents: int = TEST_DEFAULTS["BANK_BALANCE_CENTS"],
                            investigator_user_id: str = "inv-1",
                            finding_overrides=None, **kwargs):
    """Perfected judgment + VERIFIED BANK_ACCOUNT finding + DRAFT bank levy."""
    ctx = setup_perfected_judgment(**kwargs)
    ctx["finding"] = create_verified_finding(
        ctx["judgment"]["id"],
        investigator_user_id,
        estimated_value_cents=finding_value_cents,
        **(finding_overrides or {}),
    )
    ctx["action"] = draft_enforcement_action(
        ctx["judgment"]["id"], ctx["finding"]["id"], "BANK_LEVY"
    )
    return ctx


def setup_requested_bank_levy(officer_user_id: str = "eo-1", **kwargs):
    """...through to WRIT_REQUESTED."""
    ctx = setup_drafted_bank_levy(**kwargs)
    ctx["action"] = get_success_data(
        api_client.request_writ(
            ctx["action"]["id"], make_enforcement_officer_headers(officer_user_id)
        )
    )
    return ctx


def setup_served_bank_levy(served_on: str = DEFAULT_CLOCK_DATE,
                           officer_user_id: str = "eo-1", **kwargs):
    """...through to SERVED, which freezes the levy hold on the finding."""
    ctx = setup_requested_bank_levy(officer_user_id=officer_user_id, **kwargs)
    ctx["action"] = get_success_data(
        api_client.serve_writ(
            ctx["action"]["id"], served_on,
            make_enforcement_officer_headers(officer_user_id),
        )
    )
    ctx["finding"] = read_finding(ctx["finding"]["id"])
    ctx["judgment"] = read_judgment(ctx["judgment"]["id"])
    return ctx


def setup_drafted_wage_garnishment(weekly_disposable_earnings_cents: int,
                                  debtor_overrides=None, officer_user_id: str = "eo-1",
                                  **kwargs):
    """Perfected judgment + VERIFIED EMPLOYMENT finding + DRAFT wage garnishment."""
    debtor_overrides = dict(debtor_overrides or {})
    debtor_overrides.setdefault(
        "weekly_disposable_earnings_cents", weekly_disposable_earnings_cents
    )
    ctx = setup_perfected_judgment(debtor_overrides=debtor_overrides, **kwargs)
    ctx["finding"] = create_verified_employment_finding(
        ctx["judgment"]["id"], weekly_disposable_earnings_cents
    )
    ctx["action"] = draft_enforcement_action(
        ctx["judgment"]["id"], ctx["finding"]["id"], "WAGE_GARNISHMENT"
    )
    return ctx


def file_exemption_claim(action_id: str, debtor_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_exemption_claim(
            create_exemption_claim_payload(action_id, **overrides),
            make_debtor_headers(debtor_id),
        )
    )


def setup_opposed_exemption_claim(claim_type: str = "SOCIAL_SECURITY",
                                  claimed_amount_cents: int = 100_000,
                                  opposing_officer_user_id: str = "eo-2",
                                  served_on: str = DEFAULT_CLOCK_DATE, **kwargs):
    """Served bank levy + an exemption claim the creditor has opposed."""
    ctx = setup_served_bank_levy(served_on=served_on, **kwargs)
    ctx["claim"] = file_exemption_claim(
        ctx["action"]["id"], ctx["debtor"]["id"],
        claim_type=claim_type, claimed_amount_cents=claimed_amount_cents,
    )
    ctx["claim"] = get_success_data(
        api_client.oppose_exemption_claim(
            ctx["claim"]["id"],
            make_enforcement_officer_headers(opposing_officer_user_id),
        )
    )
    return ctx


def setup_filed_exemption_claim(claim_type: str = "SOCIAL_SECURITY",
                                claimed_amount_cents: int = 100_000,
                                served_on: str = DEFAULT_CLOCK_DATE, **kwargs):
    """Served bank levy + an exemption claim nobody has opposed yet."""
    ctx = setup_served_bank_levy(served_on=served_on, **kwargs)
    ctx["claim"] = file_exemption_claim(
        ctx["action"]["id"], ctx["debtor"]["id"],
        claim_type=claim_type, claimed_amount_cents=claimed_amount_cents,
    )
    return ctx


# ==========================================================================
# Tier 4 — negotiation and installment agreements
# ==========================================================================
def tender_offer(judgment_id: str, headers, **overrides) -> dict:
    """Tender an offer carrying the judgment's current version."""
    payload = create_settlement_offer_payload(
        judgment_id, judgment_version(judgment_id), **overrides
    )
    return get_success_data(api_client.create_settlement_offer(payload, headers))


def agreement_for_offer(offer_id: str) -> dict:
    """The cascade-created agreement is discoverable only by a filtered list."""
    data, _meta = _paginated(
        api_client.list_installment_agreements(CM, {"settlement_offer_id": offer_id})
    )
    assert data, f"Setup step failed: no installment agreement for offer {offer_id}"
    return data[0]


def agreements_for_judgment(judgment_id: str) -> list:
    data, _meta = _paginated(
        api_client.list_installment_agreements(CM, {"judgment_id": judgment_id})
    )
    return data


def _paginated(response):
    body = get_success_data(response)
    # The list endpoints answer with an array payload; meta carries the counters.
    meta = response.json()["meta"]
    return body, meta


def setup_active_agreement(amount_cents: int = 3_600_000, installment_count: int = 12,
                           concession: str = None, ctx: dict = None, **kwargs):
    """A CREDITOR instalment offer accepted by the debtor, producing an ACTIVE agreement."""
    ctx = ctx if ctx is not None else setup_judgment(**kwargs)
    overrides = {
        "offered_by": "CREDITOR",
        "kind": "INSTALLMENT",
        "amount_cents": amount_cents,
        "installment_count": installment_count,
    }
    if concession is not None:
        overrides["application_order_concession"] = concession
    ctx["offer"] = tender_offer(ctx["judgment"]["id"], CM, **overrides)
    ctx["offer"] = get_success_data(
        api_client.accept_settlement_offer(
            ctx["offer"]["id"], make_debtor_headers(ctx["debtor"]["id"])
        )
    )
    ctx["agreement"] = agreement_for_offer(ctx["offer"]["id"])
    ctx["judgment"] = read_judgment(ctx["judgment"]["id"])
    return ctx


def setup_stayed_judgment(amount_cents: int = 3_600_000, installment_count: int = 12,
                          concession: str = None, **kwargs):
    """Served bank levy, then an accepted instalment offer that stays enforcement."""
    ctx = setup_served_bank_levy(**kwargs)
    return setup_active_agreement(
        amount_cents=amount_cents,
        installment_count=installment_count,
        concession=concession,
        ctx=ctx,
    )


def record_misses(agreement_id: str, count: int) -> dict:
    last = None
    for _ in range(count):
        last = get_success_data(api_client.record_installment_miss(agreement_id, CM))
    return last


def setup_defaulted_agreement(**kwargs):
    """An ACTIVE agreement driven to DEFAULTED by three recorded misses."""
    ctx = setup_active_agreement(**kwargs)
    ctx["agreement"] = record_misses(ctx["agreement"]["id"], 3)
    ctx["judgment"] = read_judgment(ctx["judgment"]["id"])
    return ctx


# ==========================================================================
# Tier 5 — examinations
# ==========================================================================
def schedule_examination(judgment_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_examination(
            create_examination_payload(judgment_id, **overrides), CM
        )
    )


def issue_subpoena(examination_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.issue_subpoena(
            examination_id, issue_subpoena_payload(**overrides), CM
        )
    )


def setup_scheduled_examination(scheduled_at: str = "2026-09-01T15:00:00Z",
                                locate: bool = True, **kwargs):
    """A judgment whose debtor is located, plus one SCHEDULED examination."""
    ctx = setup_judgment(**kwargs)
    if locate:
        ctx["debtor"] = locate_debtor(ctx["debtor"]["id"])
    ctx["examination"] = schedule_examination(
        ctx["judgment"]["id"], scheduled_at=scheduled_at
    )
    return ctx


def setup_served_examination(scheduled_at: str = "2026-09-01T15:00:00Z",
                             served_on: str = DEFAULT_CLOCK_DATE, **kwargs):
    ctx = setup_scheduled_examination(scheduled_at=scheduled_at, **kwargs)
    ctx["examination"] = get_success_data(
        api_client.serve_examination(ctx["examination"]["id"], served_on, CM)
    )
    return ctx


# ==========================================================================
# Tier 6 — money
# ==========================================================================
def book_payment(judgment_id: str, amount_cents: int,
                 received_on: str = DEFAULT_CLOCK_DATE, **overrides) -> dict:
    return get_success_data(
        api_client.create_payment(
            create_payment_payload(judgment_id, amount_cents, received_on, **overrides),
            CM,
        )
    )


def reverse_payment(payment_id: str, reason: str = "NSF returned item",
                    officer_user_id: str = "co-1") -> dict:
    return get_success_data(
        api_client.reverse_payment(
            payment_id, reason, make_compliance_officer_headers(officer_user_id)
        )
    )


def setup_satisfied_judgment(principal_cents: int = 100_000, **kwargs):
    """A small judgment paid in full, so the lifecycle status reaches SATISFIED."""
    ctx = setup_judgment(
        original_principal_cents=principal_cents,
        interest_rate_bps=0,
        filing_costs_cents=0,
        **kwargs,
    )
    ctx["payment"] = book_payment(ctx["judgment"]["id"], principal_cents)
    ctx["judgment"] = read_judgment(ctx["judgment"]["id"])
    return ctx
