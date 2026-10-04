"""Composite setup helpers and PRD-formula calculators.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so each test
starts against an empty database). Setup calls use the lenient
get_success_data() validator so failures surface as clear "Setup step failed"
errors. Ownership-gated calls thread entity-backed identities via
make_taxpayer_headers / make_tax_preparer_headers — never the shared
TEST_USERS fallback.

The interest helpers at the bottom re-implement the PRD section 3.8 formulas
verbatim so tests can derive expected cent values instead of hardcoding them.
"""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    ANNUAL_RATE_PCT,
    CASE_DEADLINE_DAYS,
    CLOCK_START_ISO,
    DAY_COUNT_BASIS,
    DEFAULT_TAX_YEAR,
    DEPENDENT_CREDIT_CENTS,
    FILING_DEADLINE_BY_TAX_YEAR,
    INTEREST_FREE_DAYS,
    MAX_VERIFICATION_ATTEMPTS,
    REQUIRED_DOCS_BY_CHANNEL,
)
from .factories import (
    annual_pin_regeneration_payload,
    book_appointment_payload,
    confirm_report_payload,
    create_advocate_case_payload,
    create_dependent_payload,
    create_filter_model_config_payload,
    create_identity_theft_report_payload,
    create_preparer_payload,
    create_return_payload,
    create_service_office_payload,
    create_taxpayer_payload,
    create_verification_case_payload,
    next_dependent_tin,
    next_fingerprint,
    opt_in_payload,
    reissue_protection_pin_payload,
    release_disbursement_payload,
    resolve_advocate_case_payload,
    resolve_conflict_payload,
    set_clock_payload,
    submit_document_payload,
    submit_evidence_payload,
    update_taxpayer_payload,
)
from .test_users import (
    TEST_USERS,
    make_fraud_analyst_headers,
    make_system_admin_headers,
    make_tax_preparer_headers,
    make_taxpayer_advocate_headers,
    make_taxpayer_headers,
    make_verification_agent_headers,
)

_ADMIN = TEST_USERS["system_admin_headers"]
_ANALYST = TEST_USERS["fraud_analyst_headers"]
_AGENT = TEST_USERS["verification_agent_headers"]
_ADVOCATE = TEST_USERS["taxpayer_advocate_headers"]


# ─── Platform clock (PRD section 2.4) ────────────────

def set_clock(to_iso8601: str) -> str:
    """Set the logical clock; returns the reported current_utc."""
    resp = api_client.set_clock(set_clock_payload(to_iso8601), _ADMIN)
    return get_success_data(resp)["current_utc"]


def reset_clock_to_startup() -> str:
    """Restore the startup clock value 2026-09-01T00:00:00Z."""
    return set_clock(CLOCK_START_ISO)


# ─── Filter model configs (PRD section 3.4) ──────────

def create_active_config(**overrides) -> dict:
    """Create a DRAFT config and activate it; returns the ACTIVE config.
    Defaults are pass-through: all weights 0, gray_zone_threshold 1,
    hold_threshold 50, so an unweighted return scores 0 and passes."""
    payload = create_filter_model_config_payload(**overrides)
    created = get_success_data(api_client.create_filter_model_config(payload, _ADMIN))
    return get_success_data(api_client.activate_filter_model_config(created["id"], _ADMIN))


# ─── Taxpayers and the IP PIN program (PRD 3.1/3.2) ──

def create_taxpayer(**overrides) -> dict:
    """Register a taxpayer (SystemAdmin) and return it."""
    resp = api_client.create_taxpayer(create_taxpayer_payload(**overrides), _ADMIN)
    return get_success_data(resp)


def get_taxpayer(taxpayer_id: str) -> dict:
    return get_success_data(api_client.get_taxpayer(taxpayer_id, _ADMIN))


def update_taxpayer(taxpayer_id: str, expected_taxpayer_version: int,
                    as_self: bool = False, **fields) -> dict:
    """OCC-guarded profile update. as_self=True acts as the taxpayer
    themselves (entity-backed identity); otherwise SystemAdmin."""
    headers = make_taxpayer_headers(taxpayer_id) if as_self else _ADMIN
    payload = update_taxpayer_payload(expected_taxpayer_version, **fields)
    return get_success_data(api_client.update_taxpayer(taxpayer_id, payload, headers))


def opt_in_taxpayer(taxpayer_id: str, tax_year: int = DEFAULT_TAX_YEAR,
                    delivery_channel: Optional[str] = None,
                    on_behalf: bool = False) -> dict:
    """Opt a taxpayer into the IP PIN program; returns the updated Taxpayer.
    on_behalf=True uses SystemAdmin instead of the taxpayer's own identity."""
    headers = _ADMIN if on_behalf else make_taxpayer_headers(taxpayer_id)
    payload = opt_in_payload(tax_year=tax_year, delivery_channel=delivery_channel)
    return get_success_data(api_client.opt_in_ip_pin(taxpayer_id, payload, headers))


def opt_out_taxpayer(taxpayer_id: str, on_behalf: bool = False) -> dict:
    headers = _ADMIN if on_behalf else make_taxpayer_headers(taxpayer_id)
    return get_success_data(api_client.opt_out_ip_pin(taxpayer_id, headers))


def list_pins(taxpayer_id: str) -> list:
    resp = api_client.list_protection_pins(taxpayer_id, _ADMIN)
    return get_success_data(resp)


def get_active_pin(taxpayer_id: str, tax_year: int = DEFAULT_TAX_YEAR) -> dict:
    """Return the single ACTIVE ProtectionPin for (taxpayer, tax_year)."""
    pins = [p for p in list_pins(taxpayer_id)
            if p.get("status") == "ACTIVE" and p.get("tax_year") == tax_year]
    assert len(pins) == 1, (
        f"Expected exactly 1 ACTIVE pin for taxpayer {taxpayer_id} tax_year "
        f"{tax_year}, found {len(pins)}"
    )
    return pins[0]


def create_enrolled_taxpayer(tax_year: int = DEFAULT_TAX_YEAR, **overrides) -> tuple:
    """Create a taxpayer and opt them in; returns (taxpayer, active_pin)."""
    taxpayer = create_taxpayer(**overrides)
    opt_in_taxpayer(taxpayer["id"], tax_year=tax_year)
    pin = get_active_pin(taxpayer["id"], tax_year)
    return get_taxpayer(taxpayer["id"]), pin


def reissue_pin(taxpayer_id: str, expected_taxpayer_version: int,
                tax_year: int = DEFAULT_TAX_YEAR,
                delivery_channel: Optional[str] = None,
                as_advocate: bool = False) -> dict:
    """OCC-guarded manual pin reissue (SystemAdmin or TaxpayerAdvocate)."""
    headers = _ADVOCATE if as_advocate else _ADMIN
    payload = reissue_protection_pin_payload(
        taxpayer_id, expected_taxpayer_version,
        tax_year=tax_year, delivery_channel=delivery_channel,
    )
    return get_success_data(api_client.reissue_protection_pin(payload, headers))


def run_pin_regeneration(tax_year: int) -> dict:
    """Run the annual regeneration batch; returns
    {created_count, superseded_count, skipped_count}."""
    resp = api_client.run_annual_pin_regeneration(
        annual_pin_regeneration_payload(tax_year), _ADMIN
    )
    return get_success_data(resp)


# ─── Identity theft reports (PRD section 3.3) ────────

def create_theft_report(taxpayer_id: str, source: str = "TAXPAYER_REPORT",
                        description: Optional[str] = None,
                        creator: str = "taxpayer",
                        creator_user_id: Optional[str] = None) -> dict:
    """File a theft report. creator='taxpayer' files as the taxpayer
    themselves (entity-backed); creator='analyst' files as a FraudAnalyst
    with the given creator_user_id (recorded as created_by_user_id, which
    the segregation-of-duties confirm check compares against)."""
    if creator == "analyst":
        headers = make_fraud_analyst_headers(creator_user_id or "analyst-creator-1")
    else:
        headers = make_taxpayer_headers(taxpayer_id)
    payload = create_identity_theft_report_payload(source=source, description=description)
    return get_success_data(
        api_client.create_identity_theft_report(taxpayer_id, payload, headers)
    )


def confirm_report(report_id: str, tax_year: int = DEFAULT_TAX_YEAR,
                   analyst_user_id: str = "analyst-confirmer-1") -> dict:
    """Confirm a SUBMITTED report as a FraudAnalyst distinct from the
    creator. Fires the victim-flag + enrollment + pin-issuance cascade."""
    resp = api_client.confirm_identity_theft_report(
        report_id, confirm_report_payload(tax_year),
        make_fraud_analyst_headers(analyst_user_id),
    )
    return get_success_data(resp)


def reject_report(report_id: str, analyst_user_id: str = "analyst-rejecter-1") -> dict:
    return get_success_data(
        api_client.reject_identity_theft_report(
            report_id, make_fraud_analyst_headers(analyst_user_id)
        )
    )


def reopen_report(report_id: str, taxpayer_id: Optional[str] = None,
                  as_advocate: bool = False) -> dict:
    """Reopen a REJECTED report — as the taxpayer themselves when
    taxpayer_id is given, else as a TaxpayerAdvocate."""
    if as_advocate or taxpayer_id is None:
        headers = _ADVOCATE
    else:
        headers = make_taxpayer_headers(taxpayer_id)
    return get_success_data(api_client.reopen_identity_theft_report(report_id, headers))


def create_victim_taxpayer(tax_year: int = DEFAULT_TAX_YEAR,
                           analyst_user_id: str = "analyst-confirmer-1",
                           **overrides) -> tuple:
    """Taxpayer + TAXPAYER_REPORT + confirm by a different user. Returns
    (taxpayer, report, active_pin) with the taxpayer VICTIM_FLAGGED and
    ENROLLED holding a fresh ACTIVE pin for tax_year."""
    taxpayer = create_taxpayer(**overrides)
    report = create_theft_report(taxpayer["id"], creator="taxpayer")
    confirm_report(report["id"], tax_year=tax_year, analyst_user_id=analyst_user_id)
    pin = get_active_pin(taxpayer["id"], tax_year)
    return get_taxpayer(taxpayer["id"]), report, pin


# ─── Tax returns (PRD section 3.4) ───────────────────

def file_return(taxpayer_id: str, headers: Optional[dict] = None,
                preparer_id: Optional[str] = None, **overrides) -> dict:
    """File a return and return the post-scoring TaxReturn. Identity
    threading: defaults to the taxpayer's own entity-backed headers; when
    preparer_id is set and no headers are given, files as that preparer
    (entity-backed)."""
    if headers is None:
        if preparer_id is not None:
            headers = make_tax_preparer_headers(preparer_id)
        else:
            headers = make_taxpayer_headers(taxpayer_id)
    payload = create_return_payload(taxpayer_id, preparer_id=preparer_id, **overrides)
    return get_success_data(api_client.file_tax_return(payload, headers))


def get_return(return_id: str) -> dict:
    return get_success_data(api_client.get_tax_return(return_id, _ANALYST))


def list_claims(return_id: str) -> list:
    return get_success_data(api_client.list_dependent_claims(return_id, _ANALYST))


def get_return_hold(return_id: str) -> Optional[dict]:
    """A return holds at most one FilterHold; returns it or None."""
    holds = get_success_data(api_client.list_return_filter_holds(return_id, _ANALYST))
    assert len(holds) <= 1, f"Return {return_id} has {len(holds)} holds, expected <= 1"
    return holds[0] if holds else None


def get_return_disbursement(return_id: str) -> Optional[dict]:
    """Exactly one disbursement ever exists per return; returns it or None."""
    rows = get_success_data(api_client.list_return_disbursements(return_id, _ANALYST))
    assert len(rows) <= 1, (
        f"Return {return_id} has {len(rows)} disbursements, expected <= 1"
    )
    return rows[0] if rows else None


def file_passing_return(taxpayer_id: Optional[str] = None,
                        taxpayer_overrides: Optional[dict] = None,
                        **return_overrides) -> tuple:
    """File a return expected to pass the filter. Requires an ACTIVE config
    whose thresholds the payload will not trip (a pass-through config scores
    an unweighted NONE-bank return 0 < gray 1). Returns (taxpayer, return)."""
    if taxpayer_id is None:
        taxpayer = create_taxpayer(**(taxpayer_overrides or {}))
        taxpayer_id = taxpayer["id"]
    else:
        taxpayer = get_taxpayer(taxpayer_id)
    rtn = file_return(taxpayer_id, **return_overrides)
    assert rtn["status"] == "FILTER_PASSED", (
        f"Expected FILTER_PASSED, got {rtn['status']} (score {rtn.get('risk_score')})"
    )
    return taxpayer, rtn


# ─── Held returns and verification cases (PRD 3.4/3.5) ──

def setup_held_return(w_bank_product: int = 60, gray_zone_threshold: int = 25,
                      hold_threshold: int = 50, claimed_refund_cents: int = 60000,
                      config_overrides: Optional[dict] = None,
                      taxpayer_overrides: Optional[dict] = None) -> tuple:
    """Active bank-weighted config + taxpayer + REFUND_TRANSFER filing that
    lands FILTER_HELD. Returns (taxpayer, return, hold). Default weights put
    the score at 60 -> FULL zone (60 >= hold 50); pass
    w_bank_product=30, gray_zone_threshold=25, hold_threshold=50 for GRAY."""
    cfg = dict(w_bank_product=w_bank_product,
               gray_zone_threshold=gray_zone_threshold,
               hold_threshold=hold_threshold)
    cfg.update(config_overrides or {})
    create_active_config(**cfg)
    taxpayer = create_taxpayer(**(taxpayer_overrides or {}))
    rtn = file_return(
        taxpayer["id"],
        claimed_refund_cents=claimed_refund_cents,
        bank_product="REFUND_TRANSFER",
        bank_account_fingerprint=next_fingerprint(),
    )
    assert rtn["status"] == "FILTER_HELD", (
        f"Expected FILTER_HELD, got {rtn['status']} (score {rtn.get('risk_score')})"
    )
    hold = get_return_hold(rtn["id"])
    assert hold is not None and hold["status"] == "OPEN"
    return taxpayer, rtn, hold


def open_verification_case(taxpayer_id: str, return_id: Optional[str] = None,
                           channel: str = "ONLINE",
                           opener: str = "agent") -> dict:
    """Open a verification case (VerificationAgent by default; opener
    'analyst' uses FraudAnalyst)."""
    headers = _ANALYST if opener == "analyst" else _AGENT
    payload = create_verification_case_payload(taxpayer_id, channel=channel,
                                               return_id=return_id)
    return get_success_data(api_client.create_verification_case(payload, headers))


def get_verification_case(case_id: str) -> dict:
    return get_success_data(api_client.get_verification_case(case_id, _AGENT))


def request_documents(case_id: str) -> dict:
    return get_success_data(api_client.request_documents(case_id, _AGENT))


def submit_document(case_id: str, doc_type: str,
                    taxpayer_id: Optional[str] = None) -> dict:
    """Submit one document. As the taxpayer (entity-backed) when
    taxpayer_id is given, else as a VerificationAgent."""
    headers = make_taxpayer_headers(taxpayer_id) if taxpayer_id else _AGENT
    return get_success_data(
        api_client.submit_document(case_id, submit_document_payload(doc_type), headers)
    )


def advance_case_to_docs_submitted(case: dict, taxpayer_id: Optional[str] = None,
                                   extra_doc_types: Optional[list] = None) -> dict:
    """OPENED/FAILED -> DOCS_REQUESTED, then submit every required document
    type for the case's channel (plus any extras) so coverage auto-advances
    the case to DOCS_SUBMITTED. Returns the re-read case."""
    case_id = case["id"]
    if case.get("status") in ("OPENED", "FAILED"):
        request_documents(case_id)
    required = case.get("required_document_types") or REQUIRED_DOCS_BY_CHANNEL[case["channel"]]
    for doc_type in list(required) + list(extra_doc_types or []):
        submit_document(case_id, doc_type, taxpayer_id=taxpayer_id)
    refreshed = get_verification_case(case_id)
    assert refreshed["status"] == "DOCS_SUBMITTED", (
        f"Expected DOCS_SUBMITTED after covering {required}, got {refreshed['status']}"
    )
    return refreshed


def advance_case_to_verified(case: dict, taxpayer_id: Optional[str] = None) -> dict:
    """Drive a case to VERIFIED: request docs, submit the required set, then
    verify. Returns the VERIFIED case."""
    submitted = advance_case_to_docs_submitted(case, taxpayer_id=taxpayer_id)
    return get_success_data(api_client.verify_case(submitted["id"], _AGENT))


def fail_case_attempt(case_id: str) -> dict:
    """Record one failed verification attempt (case must be DOCS_REQUESTED
    or DOCS_SUBMITTED)."""
    return get_success_data(api_client.fail_case(case_id, _AGENT))


def fail_case_until(case_id: str, target_attempts: int) -> dict:
    """Drive the retry loop until attempts_count == target_attempts
    (re-requesting documents after each FAILED). The fail that reaches
    MAX_VERIFICATION_ATTEMPTS lands the case in EXPIRED."""
    case = get_verification_case(case_id)
    while case["attempts_count"] < target_attempts:
        if case["status"] in ("OPENED", "FAILED"):
            case = request_documents(case_id)
        case = fail_case_attempt(case_id)
    assert case["attempts_count"] == target_attempts
    return case


def fail_case_until_expired(case_id: str) -> dict:
    """Third failed attempt: the case lands in EXPIRED with attempts_count
    == MAX_VERIFICATION_ATTEMPTS (3), cascading fraud confirmation when it
    is return-linked to a FILTER_HELD return."""
    case = fail_case_until(case_id, MAX_VERIFICATION_ATTEMPTS)
    assert case["status"] == "EXPIRED", (
        f"Expected EXPIRED after {MAX_VERIFICATION_ATTEMPTS} attempts, "
        f"got {case['status']}"
    )
    return case


def setup_held_return_with_case(channel: str = "ONLINE", **held_kwargs) -> tuple:
    """Held return + an OPENED verification case on it. Returns
    (taxpayer, return, hold, case). Note: a GRAY-zone hold accepts only
    channel ONLINE (PRD section 3.5)."""
    taxpayer, rtn, hold = setup_held_return(**held_kwargs)
    case = open_verification_case(taxpayer["id"], return_id=rtn["id"], channel=channel)
    return taxpayer, rtn, hold, case


# ─── Refund scheduling and release (PRD section 3.8) ──

def schedule_refund(return_id: str) -> dict:
    """Schedule the refund (FraudAnalyst); returns the SCHEDULED
    RefundDisbursement."""
    return get_success_data(api_client.release_refund(return_id, _ANALYST))


def release_disbursement(disbursement_id: str, expected_amount_cents: int) -> dict:
    """Execute a scheduled disbursement (SystemAdmin) with the
    money-consistency handshake."""
    resp = api_client.release_disbursement(
        disbursement_id, release_disbursement_payload(expected_amount_cents), _ADMIN
    )
    return get_success_data(resp)


def setup_scheduled_refund(claimed_refund_cents: int = 50000,
                           clock_iso: str = "2027-05-01T00:00:00Z",
                           taxpayer_overrides: Optional[dict] = None) -> tuple:
    """Clock set, pass-through config active, passing return filed, refund
    scheduled. Returns (taxpayer, return, disbursement)."""
    set_clock(clock_iso)
    create_active_config()
    overrides = {"prior_year_refund_cents": claimed_refund_cents}
    overrides.update(taxpayer_overrides or {})
    taxpayer, rtn = file_passing_return(
        taxpayer_overrides=overrides,
        claimed_refund_cents=claimed_refund_cents,
        bank_product="NONE",
    )
    disbursement = schedule_refund(rtn["id"])
    assert disbursement["status"] == "SCHEDULED"
    return taxpayer, rtn, disbursement


def setup_released_return(claimed_refund_cents: int = 50000,
                          clock_iso: str = "2027-05-01T00:00:00Z") -> tuple:
    """Full path through REFUND_RELEASED within the interest-free window
    (final interest 0, expected amount == base). Returns
    (taxpayer, return, disbursement)."""
    taxpayer, rtn, disbursement = setup_scheduled_refund(
        claimed_refund_cents=claimed_refund_cents, clock_iso=clock_iso
    )
    released = release_disbursement(disbursement["id"], disbursement["base_cents"])
    assert released["status"] == "RELEASED"
    return taxpayer, get_return(rtn["id"]), released


# ─── Dependent claims and conflicts (PRD section 3.6) ──

def setup_dependent_conflict(dependent_tin: Optional[str] = None,
                             claim_a_cents: int = 300000,
                             claim_b_cents: int = 100000,
                             relationship_a: str = "CHILD",
                             relationship_b: str = "CHILD",
                             config_overrides: Optional[dict] = None,
                             clock_iso: Optional[str] = None) -> dict:
    """Two taxpayers file returns claiming the same dependent. Creates a
    pass-through config (unless overridden), both taxpayers, both filings;
    the second intake flips both claims to CONTESTED and auto-creates the
    DependentConflict. Returns a dict with taxpayer_a, return_a, taxpayer_b,
    return_b, conflict."""
    if clock_iso:
        set_clock(clock_iso)
    create_active_config(**(config_overrides or {}))
    dep_tin = dependent_tin or next_dependent_tin()
    tp_a = create_taxpayer()
    tp_b = create_taxpayer()
    rtn_a = file_return(
        tp_a["id"], claimed_refund_cents=claim_a_cents,
        filing_status="HEAD_OF_HOUSEHOLD", bank_product="NONE",
        dependents=[create_dependent_payload(dep_tin, relationship_a)],
    )
    rtn_b = file_return(
        tp_b["id"], claimed_refund_cents=claim_b_cents,
        bank_product="NONE",
        dependents=[create_dependent_payload(dep_tin, relationship_b)],
    )
    conflict = get_conflict_by_tin(dep_tin)
    assert conflict["status"] == "OPEN"
    return {
        "dependent_tin": dep_tin,
        "taxpayer_a": tp_a,
        "return_a": rtn_a,
        "taxpayer_b": tp_b,
        "return_b": rtn_b,
        "conflict": conflict,
    }


def get_conflict_by_tin(dependent_tin: str) -> dict:
    """Look up the single conflict for a dependent TIN via the list filter."""
    rows = get_success_data(
        api_client.list_dependent_conflicts(_ANALYST, params={"dependent_tin": dependent_tin})
    )
    assert len(rows) == 1, (
        f"Expected exactly 1 conflict for dependent_tin {dependent_tin}, got {len(rows)}"
    )
    return rows[0]


def get_conflict(conflict_id: str) -> dict:
    return get_success_data(api_client.get_dependent_conflict(conflict_id, _ANALYST))


def submit_evidence(conflict_id: str, side: str,
                    note: Optional[str] = None,
                    taxpayer_id: Optional[str] = None,
                    analyst_user_id: str = "analyst-evidence-1") -> dict:
    """Submit conflict evidence for one side. As the filer themselves
    (entity-backed) when taxpayer_id is given, else a FraudAnalyst on their
    behalf."""
    if taxpayer_id is not None:
        headers = make_taxpayer_headers(taxpayer_id)
    else:
        headers = make_fraud_analyst_headers(analyst_user_id)
    return get_success_data(
        api_client.submit_conflict_evidence(
            conflict_id, submit_evidence_payload(side=side, note=note), headers
        )
    )


def resolve_conflict(conflict_id: str, winner: str = "FIRST_FILER",
                     analyst_user_id: str = "analyst-resolver-1") -> dict:
    """Analyst resolution of an OPEN conflict."""
    return get_success_data(
        api_client.resolve_dependent_conflict(
            conflict_id, resolve_conflict_payload(winner),
            make_fraud_analyst_headers(analyst_user_id),
        )
    )


# ─── Preparers and scheme detection (PRD section 3.7) ──

def create_preparer(**overrides) -> dict:
    return get_success_data(api_client.create_preparer(
        create_preparer_payload(**overrides), _ADMIN
    ))


def get_preparer(preparer_id: str) -> dict:
    return get_success_data(api_client.get_preparer(preparer_id, _ADMIN))


def file_preparer_rt_returns(preparer_id: str, count: int,
                             claimed_refund_cents: int = 1000,
                             start: int = 0) -> list:
    """File `count` REFUND_TRANSFER returns for one preparer against freshly
    created taxpayers (entity-backed preparer identity), returning the
    created TaxReturn dicts."""
    returns = []
    for _ in range(count):
        tp = create_taxpayer()
        returns.append(file_return(
            tp["id"], preparer_id=preparer_id,
            claimed_refund_cents=claimed_refund_cents,
            bank_product="REFUND_TRANSFER",
            bank_account_fingerprint=next_fingerprint(),
        ))
    return returns


def setup_preparer_with_rt_returns(count: int, **config_overrides) -> tuple:
    """Pass-through config + one preparer + `count` RT filings. Returns
    (preparer, returns)."""
    create_active_config(**config_overrides)
    preparer = create_preparer()
    returns = file_preparer_rt_returns(preparer["id"], count)
    return preparer, returns


def list_preparer_alerts(preparer_id: str, params: Optional[dict] = None) -> list:
    return get_success_data(
        api_client.list_preparer_alerts(preparer_id, _ANALYST, params=params)
    )


def list_scheme_alerts(params: Optional[dict] = None) -> list:
    return get_success_data(api_client.list_fraud_scheme_alerts(_ANALYST, params=params))


def confirm_scheme_alert(alert_id: str,
                         analyst_user_id: str = "analyst-scheme-1") -> dict:
    return get_success_data(
        api_client.confirm_fraud_scheme_alert(
            alert_id, make_fraud_analyst_headers(analyst_user_id)
        )
    )


def clear_scheme_alert(alert_id: str,
                       analyst_user_id: str = "analyst-scheme-1") -> dict:
    return get_success_data(
        api_client.clear_fraud_scheme_alert(
            alert_id, make_fraud_analyst_headers(analyst_user_id)
        )
    )


# ─── Service offices and appointments (PRD section 3.5) ──

def create_office(capacity: int = 2, **overrides) -> dict:
    return get_success_data(api_client.create_service_office(
        create_service_office_payload(capacity=capacity, **overrides), _ADMIN
    ))


def book_appointment(office_id: str, case_id: str,
                     start_at: str = "2027-03-02T10:00:00Z",
                     end_at: str = "2027-03-02T11:00:00Z") -> dict:
    return get_success_data(api_client.book_appointment(
        office_id, book_appointment_payload(case_id, start_at, end_at), _AGENT
    ))


def setup_office_with_in_person_case(capacity: int = 2,
                                     clock_iso: str = "2027-03-01T00:00:00Z",
                                     **held_kwargs) -> dict:
    """Held FULL-zone return + IN_PERSON verification case + office. Returns
    dict(office, case, taxpayer, return, hold)."""
    set_clock(clock_iso)
    taxpayer, rtn, hold = setup_held_return(**held_kwargs)
    case = open_verification_case(taxpayer["id"], return_id=rtn["id"],
                                  channel="IN_PERSON")
    office = create_office(capacity=capacity)
    return {"office": office, "case": case, "taxpayer": taxpayer,
            "return": rtn, "hold": hold}


# ─── Advocate cases (PRD section 3.9) ────────────────

def create_advocate_case(taxpayer_id: str, return_id: Optional[str] = None,
                         hardship_type: str = "MEDICAL",
                         advocate_user_id: str = "advocate-1") -> dict:
    """Open a hardship case; opened_by_user_id records advocate_user_id
    (the segregation-of-duties anchor for resolve)."""
    return get_success_data(api_client.create_advocate_case(
        create_advocate_case_payload(taxpayer_id, hardship_type=hardship_type,
                                     return_id=return_id),
        make_taxpayer_advocate_headers(advocate_user_id),
    ))


def expedite_advocate_case(case_id: str,
                           advocate_user_id: str = "advocate-1") -> dict:
    return get_success_data(
        api_client.expedite_advocate_case(
            case_id, make_taxpayer_advocate_headers(advocate_user_id)
        )
    )


def resolve_advocate_case(case_id: str, resolution_note: Optional[str] = None,
                          advocate_user_id: str = "advocate-2") -> dict:
    """Resolve as a DIFFERENT advocate than the opener (default advocate-2)
    to satisfy segregation of duties."""
    return get_success_data(
        api_client.resolve_advocate_case(
            case_id, resolve_advocate_case_payload(resolution_note),
            make_taxpayer_advocate_headers(advocate_user_id),
        )
    )


# ─── Fraud confirmation (PRD section 3.8) ────────────

def confirm_fraud(return_id: str,
                  analyst_user_id: str = "analyst-fraud-1") -> dict:
    return get_success_data(
        api_client.confirm_fraud(return_id, make_fraud_analyst_headers(analyst_user_id))
    )


def mark_false_positive(hold_id: str,
                        analyst_user_id: str = "analyst-fp-1") -> dict:
    return get_success_data(
        api_client.mark_false_positive(hold_id, make_fraud_analyst_headers(analyst_user_id))
    )


# ═════════════════════════════════════════════════════
# PRD formula calculators — expected-value derivation.
# These re-implement the PRD section 3.4/3.8 arithmetic verbatim so tests
# compute expected cents instead of hardcoding magic numbers.
# ═════════════════════════════════════════════════════

def round_half_up(value) -> int:
    """PRD section 2.6: all interest arithmetic produces integer cents using
    round-half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def daily_rate() -> Decimal:
    """Daily rate = annual rate / day-count basis (PRD section 3.8:
    'a daily rate of 7 percent divided by 365')."""
    return Decimal(str(ANNUAL_RATE_PCT)) / Decimal(100) / Decimal(DAY_COUNT_BASIS)


def date_of(iso_timestamp: str) -> date:
    """Calendar date of an ISO 8601 timestamp."""
    return date.fromisoformat(str(iso_timestamp)[:10])


def anchor_date(received_at_iso: str, tax_year: int = DEFAULT_TAX_YEAR) -> date:
    """PRD section 3.8: 'the later of the return's filing date (the calendar
    date of its `received_at`) and the filing deadline for the return's tax
    year'."""
    deadline = date.fromisoformat(FILING_DEADLINE_BY_TAX_YEAR[tax_year])
    return max(date_of(received_at_iso), deadline)


def days_late(received_at_iso: str, event_at_iso: str,
              tax_year: int = DEFAULT_TAX_YEAR) -> int:
    """Days from the anchor date to the event date, minus the interest-free
    window (PRD section 3.8)."""
    return (date_of(event_at_iso) - anchor_date(received_at_iso, tax_year)).days \
        - INTEREST_FREE_DAYS


def expected_provisional_interest(base_cents: int, days_late_count: int) -> int:
    """PROVISIONAL variant (PRD section 3.8): 0 when days_late <= 0, else the
    base multiplied by the daily rate multiplied by the days-late count,
    rounded half-up in a single rounding at the end."""
    if days_late_count <= 0:
        return 0
    raw = Decimal(base_cents) * daily_rate() * Decimal(days_late_count)
    return round_half_up(raw)


def expected_component_interest(component_cents: int, days: int) -> int:
    """One FINAL-variant component: component * ((1 + daily_rate) ** days - 1),
    rounded half-up individually (PRD section 3.8). Days floor at zero."""
    if days <= 0 or component_cents == 0:
        return 0
    growth = (Decimal(1) + daily_rate()) ** days - Decimal(1)
    return round_half_up(Decimal(component_cents) * growth)


def expected_final_interest(base_cents: int, base_days_late: int,
                            adjustments: Optional[list] = None) -> int:
    """FINAL variant (PRD section 3.8): per-component rounding, then sum.
    base_days_late is floored at zero. Each adjustment is a
    (signed_cents, days_accrued) tuple; the sum-then-round order is
    explicitly rejected."""
    total = expected_component_interest(base_cents, max(0, base_days_late))
    for signed_cents, days_accrued in (adjustments or []):
        total += expected_component_interest(signed_cents, max(0, days_accrued))
    return total


def adjustment_days_accrued(resolution_date_iso: str, released_at_iso: str,
                            received_at_iso: str,
                            tax_year: int = DEFAULT_TAX_YEAR) -> int:
    """PRD section 3.8: an adjustment applied at its resolution date accrues
    from the later of (the anchor date plus the interest-free days) and that
    adjustment's resolution date through the release date, floored at zero."""
    anchor_plus_free = anchor_date(received_at_iso, tax_year) + timedelta(
        days=INTEREST_FREE_DAYS
    )
    start = max(anchor_plus_free, date_of(resolution_date_iso))
    return max(0, (date_of(released_at_iso) - start).days)


def expected_risk_score(claimed_refund_cents: int, prior_year_refund_cents: int,
                        config: dict, victim_flagged: bool = False,
                        bank_product: str = "NONE",
                        preparer_flagged: bool = False,
                        dependent_contested: bool = False) -> int:
    """PRD section 3.4 intake scoring: five weighted signals plus the
    interaction term, refund delta floored into whole steps and capped,
    total clamped to [0, 100]."""
    delta = abs(claimed_refund_cents - prior_year_refund_cents)
    steps = min(3, delta // 100000)  # MAX_DELTA_STEPS / REFUND_DELTA_STEP_CENTS
    raw = config["w_refund_delta"] * steps
    if victim_flagged:
        raw += config["w_victim_flagged"]
    if bank_product == "REFUND_TRANSFER":
        raw += config["w_bank_product"]
    if preparer_flagged:
        raw += config["w_preparer_flagged"]
    if dependent_contested:
        raw += config["w_dependent_conflict"]
    if victim_flagged and bank_product == "REFUND_TRANSFER":
        raw += config["interaction_bonus"]
    return max(0, min(100, raw))
