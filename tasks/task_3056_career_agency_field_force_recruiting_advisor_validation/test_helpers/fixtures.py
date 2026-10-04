"""Composite setup helpers.

Most of the interesting behaviour in this system can only be exercised from a
multi-step starting state: a representative has to be recruited, assessed,
offered, contracted, licensed, registered, appointed, measured against a
validation window and put in force before commission, override and chargeback
behaviour can be observed at all. These helpers encapsulate those sequences so
tests can concentrate on the assertion under examination.

Every helper builds its preconditions from scratch through the public API with
`get_success_data()` (a lenient setup validator) so a broken precondition
surfaces as a clear "Setup step failed" rather than as a confusing assertion
failure later.
"""
import itertools
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import DEFAULT_CLOCK, TEST_DEFAULTS, PASSING_COMPETENCIES
from .test_users import (
    md_headers, dd_headers, ro_headers, lc_headers, admin_headers, any_headers,
    make_financial_rep_headers, make_managing_director_headers,
    make_district_director_headers,
)

_seq = itertools.count(1000)


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------
def _n() -> int:
    return next(_seq)


def _email(prefix: str) -> str:
    return f"{prefix}.{_n()}@agency.example"


def _ok(response) -> dict:
    return get_success_data(response)


def set_clock(current_utc: str = DEFAULT_CLOCK) -> dict:
    """Install the logical clock. Called first by every top-level setup helper."""
    return _ok(api.set_clock(current_utc, admin_headers))


def new_office(office_code: Optional[str] = None, **overrides) -> dict:
    payload = {
        "office_code": office_code or f"DO-{_n()}",
        "name": TEST_DEFAULTS["OFFICE_NAME"],
        "region_code": TEST_DEFAULTS["REGION_CODE"],
        "state_code": TEST_DEFAULTS["STATE_CODE"],
    }
    payload.update(overrides)
    return _ok(api.create_district_office(payload, md_headers))


def new_advisor(office_id: str, name: str = "Test Advisor", email_prefix: str = "adv",
                rank: str = "REP", sponsor_id: Optional[str] = None,
                email: Optional[str] = None) -> dict:
    payload = {
        "full_name": name,
        "email": email or _email(email_prefix),
        "district_office_id": office_id,
        "rank": rank,
    }
    if sponsor_id is not None:
        payload["sponsoring_advisor_id"] = sponsor_id
    return _ok(api.create_advisor(payload, md_headers))


def fetch_advisor(advisor_id: str) -> dict:
    return _ok(api.get_advisor(advisor_id, any_headers))


def fetch_policy(policy_id: str) -> dict:
    return _ok(api.get_policy(policy_id, any_headers))


def fetch_contract(contract_id: str) -> dict:
    return _ok(api.get_employment_contract(contract_id, any_headers))


def fetch_window(period_id: str) -> dict:
    return _ok(api.get_validation_period(period_id, any_headers))


def fetch_credits(policy_id: str, credit_type: Optional[str] = None) -> list:
    params = {"credit_type": credit_type} if credit_type else None
    data = _ok(api.list_policy_commission_credits(policy_id, any_headers, params))
    return data if isinstance(data, list) else data.get("data", [])


def fetch_advisor_credits(advisor_id: str, credit_type: Optional[str] = None) -> list:
    params = {"credit_type": credit_type} if credit_type else None
    data = _ok(api.list_advisor_commission_credits(advisor_id, any_headers, params))
    return data if isinstance(data, list) else data.get("data", [])


# ---------------------------------------------------------------------------
# Tier 1 — entity creation primitives
# ---------------------------------------------------------------------------
def new_candidate(office_id: str, name: str = "Test Candidate", channel: str = "REFERRAL",
                  campus_name: Optional[str] = None, **overrides) -> dict:
    payload = {
        "full_name": name,
        "source_channel": channel,
        "district_office_id": office_id,
    }
    if campus_name is not None:
        payload["campus_name"] = campus_name
    payload.update(overrides)
    return _ok(api.create_candidate(payload, ro_headers))


def new_license(advisor_id: str, product_line: str = "LIFE",
                effective_date: str = TEST_DEFAULTS["LEGACY_START"],
                expires_at: str = TEST_DEFAULTS["LEGACY_EXPIRY"],
                license_number: Optional[str] = None, activate: bool = True,
                appointment_required: bool = True) -> dict:
    payload = {
        "advisor_id": advisor_id,
        "product_line": product_line,
        "license_number": license_number or f"WI-{product_line}-{_n()}",
        "effective_date": effective_date,
        "expires_at": expires_at,
        "appointment_required": appointment_required,
    }
    license_row = _ok(api.create_product_license(payload, lc_headers))
    if activate:
        license_row = _ok(api.activate_product_license(license_row["id"], lc_headers))
    return license_row


def activate_license(license_id: str) -> dict:
    return _ok(api.activate_product_license(license_id, lc_headers))


def new_registration(advisor_id: str, registration_type: str = "SERIES_66",
                     crd_number: Optional[str] = None,
                     effective_date: str = TEST_DEFAULTS["LEGACY_START"],
                     expires_at: str = TEST_DEFAULTS["LEGACY_EXPIRY"],
                     prerequisite_registration_id: Optional[str] = None,
                     activate: bool = True) -> dict:
    payload = {
        "advisor_id": advisor_id,
        "registration_type": registration_type,
        "crd_number": crd_number or f"CRD-{_n()}",
        "effective_date": effective_date,
        "expires_at": expires_at,
    }
    if prerequisite_registration_id is not None:
        payload["prerequisite_registration_id"] = prerequisite_registration_id
    row = _ok(api.create_securities_registration(payload, lc_headers))
    if activate:
        row = _ok(api.activate_securities_registration(row["id"], lc_headers))
    return row


def activate_registration(registration_id: str) -> dict:
    return _ok(api.activate_securities_registration(registration_id, lc_headers))


def new_appointment(advisor_id: str, requires_license_id: str,
                    carrier_name: str = "Northwestern Mutual",
                    requested_date: str = "2026-01-05T00:00:00Z",
                    approve: bool = True) -> dict:
    payload = {
        "advisor_id": advisor_id,
        "requires_license_id": requires_license_id,
        "carrier_name": carrier_name,
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "requested_date": requested_date,
    }
    row = _ok(api.create_carrier_appointment(payload, lc_headers))
    if approve:
        row = _ok(api.approve_carrier_appointment(row["id"], lc_headers))
    return row


def new_policy(writing_advisor_id: str, annual_premium_cents: int = 510000,
               policy_number: Optional[str] = None, product_line: str = "LIFE",
               issue_date: str = "2026-01-10T00:00:00Z",
               is_advanced_commission: bool = True,
               carrier_name: str = "Northwestern Mutual") -> dict:
    payload = {
        "policy_number": policy_number or f"NM-{_n()}",
        "writing_advisor_id": writing_advisor_id,
        "carrier_name": carrier_name,
        "product_line": product_line,
        "annual_premium_cents": annual_premium_cents,
        "issue_date": issue_date,
        "is_advanced_commission": is_advanced_commission,
    }
    return _ok(api.create_policy(payload, md_headers))


# ---------------------------------------------------------------------------
# Candidate pipeline progression
# ---------------------------------------------------------------------------
def candidate_to_assessment_pending(office_id: str, name: str = "Test Candidate",
                                    channel: str = "REFERRAL",
                                    campus_name: Optional[str] = None,
                                    assessment_version: str = "V2",
                                    scheduled_date: str = TEST_DEFAULTS["CANDIDATE_SCHEDULED_DATE"]):
    """Create -> screen -> schedule. Returns (candidate, assessment)."""
    candidate = new_candidate(office_id, name=name, channel=channel, campus_name=campus_name)
    candidate = _ok(api.screen_candidate(candidate["id"], ro_headers))
    assessment = _ok(api.schedule_assessment(
        candidate["id"],
        {"assessment_version": assessment_version, "scheduled_date": scheduled_date},
        ro_headers))
    return candidate, assessment


def score_assessment_and_assess(candidate_id: str, assessment_id: str,
                                competencies=None, raw_score: int = 85):
    """Score the assessment; the candidate moves to ASSESSED in the same call."""
    payload = {
        "raw_score": raw_score,
        "competency_scores": dict(competencies or PASSING_COMPETENCIES),
    }
    assessment = _ok(api.score_assessment(assessment_id, payload, ro_headers))
    return assessment


def candidate_to_interview_ready(office_id: str, name: str = "Test Candidate",
                                 assessment_version: str = "V2", competencies=None,
                                 channel: str = "REFERRAL"):
    candidate, assessment = candidate_to_assessment_pending(
        office_id, name=name, channel=channel, assessment_version=assessment_version)
    score_assessment_and_assess(candidate["id"], assessment["id"], competencies=competencies)
    candidate = _ok(api.advance_to_interview(candidate["id"], ro_headers))
    return candidate, assessment


def candidate_to_offer_extended(office_id: str, name: str = "Test Candidate",
                                assessment_version: str = "V2", competencies=None,
                                channel: str = "REFERRAL"):
    candidate, assessment = candidate_to_interview_ready(
        office_id, name=name, assessment_version=assessment_version,
        competencies=competencies, channel=channel)
    candidate = _ok(api.extend_offer(candidate["id"], dd_headers))
    return candidate, assessment


def candidate_to_offer_accepted(office_id: str, name: str = "Test Candidate",
                                assessment_version: str = "V2", competencies=None,
                                channel: str = "REFERRAL"):
    candidate, assessment = candidate_to_offer_extended(
        office_id, name=name, assessment_version=assessment_version,
        competencies=competencies, channel=channel)
    candidate = _ok(api.accept_offer(candidate["id"], ro_headers))
    return candidate, assessment


def candidate_to_offer_declined(office_id: str, name: str = "Test Candidate",
                                assessment_version: str = "V2", competencies=None,
                                channel: str = "REFERRAL"):
    candidate, assessment = candidate_to_offer_extended(
        office_id, name=name, assessment_version=assessment_version,
        competencies=competencies, channel=channel)
    candidate = _ok(api.decline_offer(candidate["id"], ro_headers))
    return candidate, assessment


# ---------------------------------------------------------------------------
# Tier 2 — licensing bundle
# ---------------------------------------------------------------------------
def license_and_appoint(office_id: str, advisor_id: str, product_line: str = "LIFE",
                        registration_type: str = "SERIES_66",
                        effective_date: str = TEST_DEFAULTS["LEGACY_START"],
                        expires_at: str = TEST_DEFAULTS["LEGACY_EXPIRY"],
                        appoint: bool = True, register: bool = True) -> dict:
    """Grant an active insurance licence, an active registration and an
    approved carrier appointment to one advisor."""
    license_row = new_license(advisor_id, product_line=product_line,
                              effective_date=effective_date, expires_at=expires_at)
    registration = None
    if register:
        registration = new_registration(advisor_id, registration_type=registration_type,
                                        effective_date=effective_date, expires_at=expires_at)
    appointment = None
    if appoint:
        appointment = new_appointment(advisor_id, license_row["id"])
    return {"license": license_row, "registration": registration, "appointment": appointment}


# ---------------------------------------------------------------------------
# Tier 3 — contracting
# ---------------------------------------------------------------------------
def contract_candidate(advisor_id: str, candidate: dict,
                       mode: str = "PRODUCTION_DRAW",
                       validation_requirement_cents: int = TEST_DEFAULTS["REQUIREMENT_300000"],
                       training_allowance_total_cents: int = TEST_DEFAULTS["ALLOWANCE_TOTAL_1200000"],
                       contract_type: str = "FULL_TIME",
                       start_date: str = TEST_DEFAULTS["CONTRACT_START_DATE"]) -> dict:
    """Contract an OFFER_ACCEPTED candidate; pins the candidate's current version."""
    payload = {
        "advisor_id": advisor_id,
        "candidate_id": candidate["id"],
        "contract_type": contract_type,
        "start_date": start_date,
        "training_allowance_total_cents": training_allowance_total_cents,
        "training_allowance_mode": mode,
        "validation_requirement_cents": validation_requirement_cents,
        "expected_candidate_version": candidate["version"],
    }
    return _ok(api.create_employment_contract(payload, md_headers))


def open_validation_window(contract_id: str, period_number: int = 1,
                           start_date: str = "2026-01-08T00:00:00Z",
                           end_date: str = "2026-12-31T00:00:00Z",
                           required_production_cents: int = 100000) -> dict:
    """Open a window, pinning the contract's *current* version."""
    contract = fetch_contract(contract_id)
    payload = {
        "contract_id": contract_id,
        "period_number": period_number,
        "start_date": start_date,
        "end_date": end_date,
        "required_production_cents": required_production_cents,
        "expected_contract_version": contract["version"],
    }
    return _ok(api.open_validation_period(payload, md_headers))


def setup_contracted_rep(office_id: str, name: str = "Test Rep", rank: str = "REP",
                         sponsor_id: Optional[str] = None, email_prefix: str = "rep",
                         mode: str = "PRODUCTION_DRAW",
                         validation_requirement_cents: int = TEST_DEFAULTS["REQUIREMENT_300000"],
                         training_allowance_total_cents: int = TEST_DEFAULTS["ALLOWANCE_TOTAL_1200000"],
                         contract_type: str = "FULL_TIME",
                         contract_start: str = TEST_DEFAULTS["CONTRACT_START_DATE"],
                         licensing: bool = True, product_line: str = "LIFE",
                         registration_type: str = "SERIES_66",
                         lock_licensing: bool = False,
                         effective_date: str = TEST_DEFAULTS["LEGACY_START"],
                         expires_at: str = TEST_DEFAULTS["LEGACY_EXPIRY"]) -> dict:
    """Advisor + optional licensing furniture + an ACTIVE_TRAINING contract.

    Returns a dict with advisor, license, registration, appointment, candidate,
    assessment and contract.
    """
    advisor = new_advisor(office_id, name=name, rank=rank, sponsor_id=sponsor_id,
                          email_prefix=email_prefix)
    if lock_licensing:
        advisor = _ok(api.lock_licensing_remediation(advisor["id"], md_headers))

    license_row = registration = appointment = None
    if licensing:
        bundle = license_and_appoint(office_id, advisor["id"], product_line=product_line,
                                     registration_type=registration_type,
                                     effective_date=effective_date, expires_at=expires_at)
        license_row = bundle["license"]
        registration = bundle["registration"]
        appointment = bundle["appointment"]

    candidate, assessment = candidate_to_offer_accepted(office_id, name=name)
    contract = contract_candidate(
        advisor["id"], candidate, mode=mode,
        validation_requirement_cents=validation_requirement_cents,
        training_allowance_total_cents=training_allowance_total_cents,
        contract_type=contract_type, start_date=contract_start)

    return {
        "advisor": advisor, "license": license_row, "registration": registration,
        "appointment": appointment, "candidate": candidate, "assessment": assessment,
        "contract": contract,
    }


def setup_validated_rep(office_id: str, name: str = "Test Rep", rank: str = "REP",
                        sponsor_id: Optional[str] = None, email_prefix: str = "rep",
                        mode: str = "PRODUCTION_DRAW",
                        validation_requirement_cents: int = TEST_DEFAULTS["REQUIREMENT_300000"],
                        training_allowance_total_cents: int = TEST_DEFAULTS["ALLOWANCE_TOTAL_1200000"],
                        required_production_cents: int = 100000,
                        annual_premium_cents: int = 510000,
                        policy_number: Optional[str] = None,
                        issue_date: str = "2026-01-10T00:00:00Z",
                        product_line: str = "LIFE",
                        window_start: str = "2026-01-08T00:00:00Z",
                        window_end: str = "2026-12-31T00:00:00Z",
                        create_policy: bool = True,
                        activate_policy: bool = False,
                        lock_licensing: bool = True,
                        contract_type: str = "FULL_TIME") -> dict:
    """Full path to a VALIDATED representative.

    Contract -> window -> (optional) policy -> evaluate. With
    `required_production_cents=0` and `create_policy=False` the window passes on
    zero attainment, producing a VALIDATED advisor with no production at all.
    """
    ctx = setup_contracted_rep(
        office_id, name=name, rank=rank, sponsor_id=sponsor_id,
        email_prefix=email_prefix, mode=mode,
        validation_requirement_cents=validation_requirement_cents,
        training_allowance_total_cents=training_allowance_total_cents,
        lock_licensing=lock_licensing, product_line=product_line,
        contract_type=contract_type)

    window = open_validation_window(
        ctx["contract"]["id"], period_number=1, start_date=window_start,
        end_date=window_end, required_production_cents=required_production_cents)

    policy = None
    if create_policy:
        policy = new_policy(ctx["advisor"]["id"], annual_premium_cents=annual_premium_cents,
                            policy_number=policy_number, product_line=product_line,
                            issue_date=issue_date)

    window = _ok(api.evaluate_validation_period(window["id"], md_headers))
    ctx.update({"window": window, "policy": policy})

    if activate_policy and policy is not None:
        ctx["policy"] = _ok(api.activate_policy(policy["id"], md_headers))

    ctx["advisor"] = fetch_advisor(ctx["advisor"]["id"])
    ctx["contract"] = fetch_contract(ctx["contract"]["id"])
    return ctx


def setup_validated_rep_without_production(office_id: str, name: str = "Silent Rep",
                                           rank: str = "REP", sponsor_id: Optional[str] = None,
                                           email_prefix: str = "silent") -> dict:
    """A VALIDATED representative who has written nothing (window requires 0)."""
    return setup_validated_rep(office_id, name=name, rank=rank, sponsor_id=sponsor_id,
                               email_prefix=email_prefix, required_production_cents=0,
                               create_policy=False)


def setup_hierarchy(office_id: str, cap_cents: Optional[int] = None,
                    rate_pct: Optional[float] = None,
                    premium: int = 510000, required_production_cents: int = 100000,
                    activate_policy: bool = False, name_prefix: str = "") -> dict:
    """MD -> DD -> REP, with the REP validated and (optionally) in force.

    The office cap/rate are re-read from the office response so tests can assert
    the capped accrual. Returns a dict with office, md, dd and every key from the
    representative's context.
    """
    office = _ok(api.get_district_office(office_id, any_headers))

    md = new_advisor(office_id, name=f"{name_prefix}Managing {_n()}".strip(),
                     rank="MANAGING_DIRECTOR", email_prefix="md")
    dd = new_advisor(office_id, name=f"{name_prefix}Director {_n()}".strip(),
                     rank="DISTRICT_DIRECTOR", sponsor_id=md["id"], email_prefix="dd")
    rep = setup_validated_rep(office_id, name=f"{name_prefix}Producer {_n()}".strip(),
                              rank="REP", sponsor_id=dd["id"], email_prefix="rep",
                              annual_premium_cents=premium,
                              required_production_cents=required_production_cents,
                              activate_policy=activate_policy)

    result = dict(rep)
    result.update({"office": office, "md": md, "dd": dd})
    return result


# ---------------------------------------------------------------------------
# Tier 3b — joint work
# ---------------------------------------------------------------------------
def setup_joint_case(office_id: str, split_pct_lead: float = 0.6,
                     annual_premium_cents: int = 510000,
                     lead_sponsor_id: Optional[str] = None,
                     support_sponsor_id: Optional[str] = None,
                     support_validated: bool = True,
                     activate_policy: bool = False,
                     open_case: bool = True) -> dict:
    """Two licensed, appointed representatives and a policy written by the lead.

    The lead is validated against a real 204000-cent credit; the support is
    either validated on a zero-requirement window or left in VALIDATING
    posture. Returns lead/support contexts, the policy and the open case.
    """
    lead = setup_validated_rep(office_id, name=f"Lead {_n()}", rank="REP",
                               sponsor_id=lead_sponsor_id, email_prefix="lead",
                               annual_premium_cents=annual_premium_cents,
                               activate_policy=activate_policy)
    support = setup_validated_rep(office_id, name=f"Support {_n()}", rank="REP",
                                  sponsor_id=support_sponsor_id, email_prefix="support",
                                  required_production_cents=0, create_policy=False)

    policy = lead["policy"]
    case = None
    if open_case:
        policy = fetch_policy(policy["id"])
        payload = {
            "policy_id": policy["id"],
            "lead_advisor_id": lead["advisor"]["id"],
            "support_advisor_id": support["advisor"]["id"],
            "split_pct_lead": split_pct_lead,
            "expected_policy_version": policy["version"],
        }
        case = _ok(api.create_joint_work_case(payload, make_financial_rep_headers(
            lead["advisor"]["id"])))
    return {"lead": lead, "support": support, "policy": policy, "case": case}


def get_credit_by_type(policy_id: str, credit_type: str) -> dict:
    credits = fetch_credits(policy_id, credit_type)
    assert credits, f"expected a {credit_type} credit on policy {policy_id}"
    return credits[0]


# ---------------------------------------------------------------------------
# Tier 4 — accumulation / threshold targeting
# ---------------------------------------------------------------------------
def setup_capped_office_hierarchy(cap_cents: int, rate_pct: float = 0.03,
                                  premium: int = 510000) -> dict:
    """MD -> DD -> REP in an office whose per-measurement override cap is tiny."""
    office = new_office(override_rate_pct=rate_pct, override_cap_cents=cap_cents)
    return setup_hierarchy(office["id"], cap_cents=cap_cents, rate_pct=rate_pct,
                           premium=premium, activate_policy=False)


def setup_chargeback_balance_blocked(office_id: str, premium: int = 1600000,
                                     lapse_date: str = "2026-01-10T00:00:00Z",
                                     new_premium: int = 100000) -> dict:
    """A VALIDATED representative pushed over the chargeback block threshold.

    Writes and lapses a large policy (assessing the full unearned balance) and
    then writes a second, in-force policy whose activation must be refused.
    Returns the rep context plus both policies and the assessed balance.
    """
    rep = setup_validated_rep(office_id, name=f"Blocked {_n()}", rank="REP",
                              email_prefix="blocked", annual_premium_cents=premium,
                              activate_policy=True,
                              policy_number=f"NM-BLK-{_n()}")
    lapsed = _ok(api.lapse_policy(rep["policy"]["id"], lapse_date, md_headers))
    new_pol = new_policy(rep["advisor"]["id"], annual_premium_cents=new_premium,
                         policy_number=f"NM-NEW-{_n()}", issue_date="2026-09-02T00:00:00Z")
    result = dict(rep)
    result.update({"lapsed_policy": lapsed, "new_policy": new_pol})
    result["advisor"] = fetch_advisor(rep["advisor"]["id"])
    return result


def setup_persistency_book(office_id: str, premium: int = 1200000,
                           required_production_cents: int = 480000,
                           policies_issued: int = 20, policies_persisted: int = 20,
                           activate_policy: bool = True,
                           measurement_start: str = "2026-01-01T00:00:00Z",
                           measurement_end: str = "2026-06-30T00:00:00Z") -> dict:
    """MD -> DD -> REP with a policy book and a provisional measurement opened."""
    office = _ok(api.get_district_office(office_id, any_headers))
    md = new_advisor(office_id, name=f"Persist Managing {_n()}", rank="MANAGING_DIRECTOR",
                     email_prefix="pasc.m")
    dd = new_advisor(office_id, name=f"Persist Director {_n()}", rank="DISTRICT_DIRECTOR",
                     sponsor_id=md["id"], email_prefix="pasc.d")
    rep = setup_validated_rep(office_id, name=f"Persist Producer {_n()}", rank="REP",
                              sponsor_id=dd["id"], email_prefix="pasc",
                              annual_premium_cents=premium,
                              required_production_cents=required_production_cents,
                              activate_policy=activate_policy)
    record = _ok(api.create_persistency_record({
        "advisor_id": rep["advisor"]["id"],
        "measurement_period": "2026-H1",
        "measurement_start": measurement_start,
        "measurement_end": measurement_end,
        "policies_issued": policies_issued,
        "policies_persisted": policies_persisted,
    }, md_headers))
    result = dict(rep)
    result.update({"office": office, "md": md, "dd": dd, "record": record})
    return result


def add_second_policy(writing_advisor_id: str, annual_premium_cents: int = 510000,
                      issue_date: str = "2026-02-01T00:00:00Z") -> dict:
    return new_policy(writing_advisor_id, annual_premium_cents=annual_premium_cents,
                      policy_number=f"NM-{_n()}", issue_date=issue_date)


# ---------------------------------------------------------------------------
# Tier 5 — terminal states
# ---------------------------------------------------------------------------
def setup_orphaned_policy(office_id: str, annual_premium_cents: int = 510000,
                          activate_policy: bool = True) -> dict:
    """A validated writer with an in-force policy, then terminated.

    Returns the writer context (including the created OrphanPolicyAssignment)
    plus a NON_CONTRACTED substitute advisor in the same office.
    """
    office = _ok(api.get_district_office(office_id, any_headers))
    writer = setup_validated_rep(office_id, name=f"Writer {_n()}", rank="REP",
                                 email_prefix="writer", annual_premium_cents=annual_premium_cents,
                                 activate_policy=activate_policy)
    substitute = new_advisor(office_id, name=f"Substitute {_n()}", rank="REP",
                             email_prefix="substitute")

    terminated = _ok(api.terminate_advisor(writer["advisor"]["id"], md_headers))
    assignments = _ok(api.list_policy_orphan_assignments(writer["policy"]["id"], any_headers))
    assignments = assignments if isinstance(assignments, list) else assignments.get("data", [])
    assert assignments, "terminating a writer with an in-force policy must open an orphan assignment"

    result = dict(writer)
    result.update({"office": office, "substitute": substitute, "terminated": terminated,
                   "assignment": assignments[0]})
    result["advisor"] = fetch_advisor(writer["advisor"]["id"])
    result["policy"] = fetch_policy(writer["policy"]["id"])
    return result