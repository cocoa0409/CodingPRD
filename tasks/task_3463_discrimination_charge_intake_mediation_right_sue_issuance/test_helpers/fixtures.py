"""Composite setup helpers for the EEOC Charge Processing API.

The harness restarts the server before every test, so each fixture builds its
preconditions from scratch through PRD-declared endpoints. Every composite
fixture sets the logical clock explicitly (clock_start, defaulting to the
PRD section 2.4 boot default 2026-09-01T00:00:00Z) before creating anything,
so deadline scenarios are reachable regardless of execution order.

Identity threading: ChargingParty calls use make_charging_party_headers(
charge["complainant_id"]); RespondentRep calls use make_respondent_rep_headers(
charge["employer_id"]). Opaque operator ids default to fresh unique values per
call so segregation-of-duties and calendar-buffer checks never collide unless
a test passes explicit ids.

Setup calls validate their PRD status codes explicitly (201 for creates, 200
otherwise) and raise AssertionError("Setup failed: ...") on any mismatch.
"""
import itertools
from datetime import date, timedelta
from typing import Dict, List, Optional, Sequence

from . import factories
from .api_client import api_client
from .constants import CLOCK_BOOT_DEFAULT
from .test_users import (
    TEST_USERS,
    make_charging_party_headers,
    make_commissioner_headers,
    make_director_headers,
    make_investigator_headers,
    make_intake_officer_headers,
    make_mediator_headers,
    make_platform_admin_headers,
    make_respondent_rep_headers,
)

_ADMIN = TEST_USERS["platform_admin_headers"]
_INTAKE = TEST_USERS["intake_officer_headers"]
_DIRECTOR = TEST_USERS["director_headers"]

_counter = itertools.count(1)


def fresh_id(prefix: str) -> str:
    """A unique opaque operator id, e.g. fresh_id("inv") -> "inv-000001"."""
    return f"{prefix}-{next(_counter):06d}"


# ---------------------------------------------------------------------------
# Date helpers (day granularity per PRD section 2.4)
# ---------------------------------------------------------------------------
def _to_date(value: str) -> date:
    return date.fromisoformat(str(value)[:10])


def date_to_iso(day: str) -> str:
    """'2026-06-01' -> '2026-06-01T00:00:00Z' (date-precision inputs)."""
    return f"{_to_date(day).isoformat()}T00:00:00Z"


def iso_at(day: str, hhmmss: str) -> str:
    """Full timestamp on a date, e.g. iso_at('2026-10-01', '10:30:00')."""
    return f"{_to_date(day).isoformat()}T{hhmmss}Z"


def add_days(day: str, days: int) -> str:
    """'YYYY-MM-DD' + N days -> 'YYYY-MM-DD'."""
    return (_to_date(day) + timedelta(days=days)).isoformat()


def days_between(start: str, end: str) -> int:
    """Whole days from start to end (either may be a date or a timestamp)."""
    return (_to_date(end) - _to_date(start)).days


# ---------------------------------------------------------------------------
# Setup-call plumbing
# ---------------------------------------------------------------------------
def _expect(response, status: int, what: str) -> dict:
    assert response.status_code == status, (
        f"Setup failed: {what} expected HTTP {status}, got "
        f"{response.status_code}: {response.text[:400]}"
    )
    body = response.json()
    return body["data"]


def _expect_created(response, what: str) -> dict:
    return _expect(response, 201, what)


def _expect_ok(response, what: str) -> dict:
    return _expect(response, 200, what)


# ---------------------------------------------------------------------------
# Clock (PRD section 2.4 — the endpoint lives under /eeoc like all others)
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock. Returns {current_utc}."""
    return _expect_ok(
        api_client.set_clock(factories.set_clock_payload(to_iso8601=to_iso8601), _ADMIN),
        f"set clock to {to_iso8601}",
    )


def set_clock_to_date(day: str) -> dict:
    return set_clock(date_to_iso(day))


# ---------------------------------------------------------------------------
# Reference data (PRD section 3.1)
# ---------------------------------------------------------------------------
def create_employer(
    state_code: str = "FL",
    employee_count_current: int = 40,
    legal_name: Optional[str] = None,
) -> dict:
    payload = factories.create_employer_payload(
        legal_name=legal_name or f"Employer-{fresh_id('co')}",
        state_code=state_code,
        employee_count_current=employee_count_current,
    )
    return _expect_created(
        api_client.create_employer(payload, _INTAKE),
        f"create employer {payload['legal_name']}",
    )


def create_complainant(
    full_name: Optional[str] = None, email: Optional[str] = None
) -> dict:
    tag = fresh_id("person")
    payload = factories.create_complainant_payload(
        full_name=full_name or f"Complainant {tag}",
        email=email or f"{tag}@example.com",
    )
    return _expect_created(
        api_client.create_complainant(payload, _INTAKE),
        f"create complainant {payload['full_name']}",
    )


def create_deferral_agency(
    state_code: str = "CA",
    filing_deadline_days: int = 300,
    work_sharing_policy: str = "DUAL_FILE_DEFAULT",
    covers_age: bool = True,
    agency_name: Optional[str] = None,
) -> dict:
    payload = factories.create_deferral_agency_payload(
        state_code=state_code,
        agency_name=agency_name or f"{state_code} FEPA",
        filing_deadline_days=filing_deadline_days,
        work_sharing_policy=work_sharing_policy,
        covers_age=covers_age,
    )
    return _expect_created(
        api_client.create_deferral_agency(payload, _ADMIN),
        f"create deferral agency {state_code}",
    )


# ---------------------------------------------------------------------------
# Charge intake (PRD section 3.2)
# ---------------------------------------------------------------------------
def file_charge(
    employer: dict,
    complainant: dict,
    basis_codes: Sequence[str] = ("RACE",),
    incident_date: str = "2026-06-01",
    harm_description: str = "Unlawful employment practice",
    employee_count_at_incident: Optional[int] = None,
    as_charging_party: bool = False,
) -> dict:
    """File a charge. incident_date defaults to 2026-06-01 — before the boot
    clock and timely under both the 180- and 300-day deadlines, so the
    default lands DOCKETED for an EEOC-owned employer."""
    payload = factories.create_charge_payload(
        complainant_id=complainant["id"],
        employer_id=employer["id"],
        basis_codes=list(basis_codes),
        incident_date=incident_date,
        harm_description=harm_description,
        employee_count_at_incident=(
            employee_count_at_incident
            if employee_count_at_incident is not None
            else employer["employee_count_current"]
        ),
    )
    headers = (
        make_charging_party_headers(complainant["id"])
        if as_charging_party
        else _INTAKE
    )
    return _expect_created(api_client.create_charge(payload, headers), "file charge")


def read_charge(charge_id: str, headers: Optional[Dict] = None) -> dict:
    return _expect_ok(
        api_client.get_charge(charge_id, headers or _DIRECTOR), f"read charge {charge_id}"
    )


# ---------------------------------------------------------------------------
# Mediation (PRD section 3.4)
# ---------------------------------------------------------------------------
def offer_mediation(charge: dict) -> dict:
    return _expect_created(
        api_client.offer_mediation(charge["id"], _INTAKE),
        f"offer mediation on charge {charge['id']}",
    )


def respond_to_mediation(charge: dict, mediation_case: dict, party: str,
                         response: str) -> dict:
    """party: 'complainant' or 'respondent'. The server derives the recorded
    side from X-User-ID, so entity-backed headers are mandatory."""
    if party == "complainant":
        headers = make_charging_party_headers(charge["complainant_id"])
    elif party == "respondent":
        headers = make_respondent_rep_headers(charge["employer_id"])
    else:
        raise ValueError(f"party must be 'complainant' or 'respondent', got {party!r}")
    return _expect_ok(
        api_client.respond_mediation(
            mediation_case["id"],
            factories.respond_mediation_payload(response=response),
            headers,
        ),
        f"{party} responds {response}",
    )


def decline_mediation(charge: dict, mediation_case: dict,
                      party: str = "complainant") -> dict:
    """One DECLINED response: mediation -> DECLINED; a DOCKETED charge moves
    to UNDER_INVESTIGATION with an auto-created InvestigationCase."""
    return respond_to_mediation(charge, mediation_case, party, "DECLINED")


def activate_mediation(charge: dict, mediation_case: dict) -> dict:
    """Both parties accept: mediation -> ACTIVE, charge -> IN_MEDIATION."""
    respond_to_mediation(charge, mediation_case, "complainant", "ACCEPTED")
    return respond_to_mediation(charge, mediation_case, "respondent", "ACCEPTED")


def schedule_session(mediation_case: dict, mediator_user_id: Optional[str] = None,
                     scheduled_start: str = "2026-10-01T10:00:00Z",
                     scheduled_end: str = "2026-10-01T11:00:00Z") -> dict:
    """Defaults are future relative to the boot clock. mediator_user_id
    defaults to a fresh unique id; pass an explicit id to reuse a calendar
    (overlap checks are per mediator)."""
    mediator_id = mediator_user_id or fresh_id("med")
    payload = factories.create_mediation_session_payload(
        scheduled_start=scheduled_start, scheduled_end=scheduled_end
    )
    return _expect_created(
        api_client.create_mediation_session(
            mediation_case["id"], payload, make_mediator_headers(mediator_id)
        ),
        f"schedule session {scheduled_start}",
    )


def conclude_mediation(mediation_case: dict, outcome: str = "IMPASSE",
                       settlement_amount_cents: Optional[int] = None,
                       mediator_user_id: Optional[str] = None) -> dict:
    payload = factories.conclude_mediation_payload(outcome=outcome)
    if settlement_amount_cents is not None:
        payload["settlement_amount_cents"] = settlement_amount_cents
    return _expect_ok(
        api_client.conclude_mediation(
            mediation_case["id"], payload,
            make_mediator_headers(mediator_user_id or fresh_id("med")),
        ),
        f"conclude mediation {outcome}",
    )


# ---------------------------------------------------------------------------
# Investigation (PRD section 3.5)
# ---------------------------------------------------------------------------
def charge_investigation_case_id(charge_id: str) -> str:
    """Read the charge as Director and return its investigation_case_id."""
    charge = read_charge(charge_id)
    assert charge["investigation_case_id"], (
        f"Setup failed: charge {charge_id} has no investigation_case_id"
    )
    return charge["investigation_case_id"]


def assign_investigator(case_id: str, investigator_user_id: Optional[str] = None,
                        director_user_id: Optional[str] = None) -> dict:
    inv_id = investigator_user_id or fresh_id("inv")
    result = _expect_ok(
        api_client.assign_investigator(
            case_id,
            factories.assign_investigator_payload(investigator_user_id=inv_id),
            make_director_headers(director_user_id or fresh_id("dir")),
        ),
        f"assign {inv_id} to {case_id}",
    )
    result["_assigned_investigator_id"] = inv_id
    return result


def issue_evidence_request(case_id: str, investigator_user_id: str,
                           request_type: str = "POSITION_STATEMENT") -> dict:
    return _expect_created(
        api_client.create_evidence_request(
            case_id,
            factories.create_evidence_request_payload(request_type=request_type),
            make_investigator_headers(investigator_user_id),
        ),
        f"issue {request_type}",
    )


def issue_evidence_requests(case_id: str, investigator_user_id: str,
                            count: int) -> List[dict]:
    types = ["POSITION_STATEMENT", "RFI", "DOCUMENT_DEMAND"]
    return [
        issue_evidence_request(case_id, investigator_user_id, types[i % len(types)])
        for i in range(count)
    ]


def log_interview(case_id: str, investigator_user_id: str, **overrides) -> dict:
    return _expect_created(
        api_client.create_witness_interview(
            case_id,
            factories.create_interview_payload(**overrides),
            make_investigator_headers(investigator_user_id),
        ),
        "log witness interview",
    )


def draft_determination(case_id: str, investigator_user_id: str,
                        **payload_overrides) -> dict:
    """Pass outcome='CAUSE' plus the four remedy components and
    harm_start_date via payload_overrides (or use cause_determination_payload
    values) — the default is a bare NO_CAUSE draft."""
    return _expect_created(
        api_client.create_determination(
            case_id,
            factories.create_determination_payload(**payload_overrides),
            make_investigator_headers(investigator_user_id),
        ),
        f"draft determination ({payload_overrides.get('outcome', 'NO_CAUSE')})",
    )


def draft_cause_determination(case_id: str, investigator_user_id: str,
                              **payload_overrides) -> dict:
    return _expect_created(
        api_client.create_determination(
            case_id,
            factories.cause_determination_payload(**payload_overrides),
            make_investigator_headers(investigator_user_id),
        ),
        "draft CAUSE determination",
    )


def submit_determination(determination_id: str, investigator_user_id: str) -> dict:
    return _expect_ok(
        api_client.submit_determination(
            determination_id, make_investigator_headers(investigator_user_id)
        ),
        f"submit determination {determination_id}",
    )


def review_determination(determination_id: str, decision: str = "APPROVE",
                         director_user_id: Optional[str] = None,
                         return_reason: Optional[str] = None) -> dict:
    payload = factories.review_determination_payload(decision=decision)
    if return_reason is not None:
        payload["return_reason"] = return_reason
    return _expect_ok(
        api_client.review_determination(
            determination_id, payload,
            make_director_headers(director_user_id or fresh_id("dir")),
        ),
        f"review determination {decision}",
    )


# ---------------------------------------------------------------------------
# Conciliation (PRD section 3.7)
# ---------------------------------------------------------------------------
def conciliation_for_charge(charge_id: str) -> dict:
    """The single ConciliationProcess of a CONCILIATION charge."""
    body = api_client.list_conciliation_processes(charge_id, _DIRECTOR)
    assert body.status_code == 200, (
        f"Setup failed: list conciliations for {charge_id} -> "
        f"{body.status_code}: {body.text[:400]}"
    )
    rows = body.json()["data"]
    assert len(rows) == 1, (
        f"Setup failed: expected exactly 1 conciliation for charge "
        f"{charge_id}, found {len(rows)}"
    )
    return rows[0]


def remedy_package_for_conciliation(process_id: str) -> dict:
    """The single RemedyPackage of a conciliation process."""
    body = api_client.list_remedy_packages(process_id, _DIRECTOR)
    assert body.status_code == 200, (
        f"Setup failed: list remedy packages for {process_id} -> "
        f"{body.status_code}: {body.text[:400]}"
    )
    rows = body.json()["data"]
    assert len(rows) == 1, (
        f"Setup failed: expected exactly 1 remedy package for conciliation "
        f"{process_id}, found {len(rows)}"
    )
    return rows[0]


def table_offer(process: dict, amount_cents: int, side: str, charge: dict,
                director_user_id: Optional[str] = None) -> dict:
    """side: 'COMMISSION' (Director) or 'RESPONDENT' (RespondentRep).
    Carries the process's current version for the OCC guard."""
    if side == "COMMISSION":
        headers = make_director_headers(director_user_id or fresh_id("dir"))
    elif side == "RESPONDENT":
        headers = make_respondent_rep_headers(charge["employer_id"])
    else:
        raise ValueError(f"side must be 'COMMISSION' or 'RESPONDENT', got {side!r}")
    payload = factories.table_offer_payload(
        amount_cents=amount_cents,
        expected_conciliation_version=process["version"],
    )
    return _expect_ok(
        api_client.table_offer(process["id"], payload, headers),
        f"table offer {amount_cents} by {side}",
    )


def accept_conciliation(process: dict, charge: dict) -> dict:
    return _expect_ok(
        api_client.accept_conciliation(
            process["id"], make_charging_party_headers(charge["complainant_id"])
        ),
        "accept conciliation offer",
    )


def fail_conciliation(process: dict, reason: str = "Respondent refused to engage",
                      director_user_id: Optional[str] = None) -> dict:
    return _expect_ok(
        api_client.fail_conciliation(
            process["id"],
            factories.fail_conciliation_payload(reason=reason),
            make_director_headers(director_user_id or fresh_id("dir")),
        ),
        "fail conciliation",
    )


# ---------------------------------------------------------------------------
# Right-to-sue (PRD section 3.8)
# ---------------------------------------------------------------------------
def issue_rts_as_charging_party(charge: dict) -> dict:
    return _expect_created(
        api_client.issue_right_to_sue(
            charge["id"], make_charging_party_headers(charge["complainant_id"])
        ),
        "charging-party RTS request",
    )


def issue_rts_as_director(charge: dict,
                          director_user_id: Optional[str] = None) -> dict:
    return _expect_created(
        api_client.issue_right_to_sue(
            charge["id"],
            make_director_headers(director_user_id or fresh_id("dir")),
        ),
        "director-discretion RTS issuance",
    )


# ---------------------------------------------------------------------------
# Systemic cases and disclosures (PRD section 3.9)
# ---------------------------------------------------------------------------
def create_systemic_case(title: str = "Pattern-or-practice probe",
                         basis_focus: Sequence[str] = ("RACE",),
                         commissioner_user_id: Optional[str] = None) -> dict:
    return _expect_created(
        api_client.create_systemic_case(
            factories.create_systemic_case_payload(
                title=title, basis_focus=list(basis_focus)
            ),
            make_commissioner_headers(commissioner_user_id or fresh_id("com")),
        ),
        "open systemic case",
    )


def link_charge(systemic_case: dict, charge: dict,
                commissioner_user_id: Optional[str] = None) -> dict:
    return _expect_ok(
        api_client.link_charge(
            systemic_case["id"],
            factories.link_charge_payload(charge_id=charge["id"]),
            make_commissioner_headers(commissioner_user_id or fresh_id("com")),
        ),
        f"link charge {charge['id']}",
    )


def record_disclosure(charge: dict, legal_basis: str = "PARTY_CONSENT",
                      target_description: str = "Authorized recipient",
                      director_user_id: Optional[str] = None) -> dict:
    return _expect_created(
        api_client.create_disclosure(
            charge["id"],
            factories.create_disclosure_payload(
                legal_basis=legal_basis, target_description=target_description
            ),
            make_director_headers(director_user_id or fresh_id("dir")),
        ),
        f"record disclosure {legal_basis}",
    )


def vacate_settlement(charge: dict, reason: str = "Settlement repudiated",
                      director_user_id: Optional[str] = None) -> dict:
    return _expect_ok(
        api_client.vacate_settlement(
            charge["id"],
            factories.vacate_settlement_payload(reason=reason),
            make_director_headers(director_user_id or fresh_id("dir")),
        ),
        "vacate settlement",
    )


# ===========================================================================
# Composite scenario fixtures (tiers 1-5)
# ===========================================================================
def setup_docketed_charge(
    basis_codes: Sequence[str] = ("RACE",),
    incident_date: str = "2026-06-01",
    employee_count: int = 40,
    state_code: str = "FL",
    clock_start: str = CLOCK_BOOT_DEFAULT,
    agency: Optional[dict] = None,
) -> dict:
    """Employer + complainant + one freshly screened charge.
    Keys: employer, complainant, charge (+ agency when supplied)."""
    set_clock(clock_start)
    if agency is None:
        employer = create_employer(state_code=state_code,
                                   employee_count_current=employee_count)
    else:
        employer = create_employer(state_code=agency["state_code"],
                                   employee_count_current=employee_count)
    complainant = create_complainant()
    charge = file_charge(
        employer, complainant, basis_codes=basis_codes,
        incident_date=incident_date, employee_count_at_incident=employee_count,
    )
    result = {"employer": employer, "complainant": complainant, "charge": charge}
    if agency is not None:
        result["agency"] = agency
    return result


def setup_under_investigation(
    basis_codes: Sequence[str] = ("RACE",),
    incident_date: str = "2026-06-01",
    employee_count: int = 40,
    state_code: str = "FL",
    clock_start: str = CLOCK_BOOT_DEFAULT,
    decline_by: str = "complainant",
    agency: Optional[dict] = None,
) -> dict:
    """DOCKETED charge whose mediation offer was declined: charge is
    UNDER_INVESTIGATION with an auto-created OPEN InvestigationCase.
    Keys: employer, complainant, charge, mediation_case,
    investigation_case_id (+ agency when supplied)."""
    base = setup_docketed_charge(
        basis_codes=basis_codes, incident_date=incident_date,
        employee_count=employee_count, state_code=state_code,
        clock_start=clock_start, agency=agency,
    )
    mediation = offer_mediation(base["charge"])
    decline_mediation(base["charge"], mediation, party=decline_by)
    base["mediation_case"] = mediation
    base["investigation_case_id"] = charge_investigation_case_id(base["charge"]["id"])
    base["charge"] = read_charge(base["charge"]["id"])
    return base


def setup_gathering(
    basis_codes: Sequence[str] = ("RACE",),
    incident_date: str = "2026-06-01",
    employee_count: int = 40,
    state_code: str = "FL",
    clock_start: str = CLOCK_BOOT_DEFAULT,
    investigator_user_id: Optional[str] = None,
    agency: Optional[dict] = None,
) -> dict:
    """UNDER_INVESTIGATION + assigned investigator + first evidence request:
    the case is GATHERING. Adds keys investigator_user_id, evidence_request."""
    base = setup_under_investigation(
        basis_codes=basis_codes, incident_date=incident_date,
        employee_count=employee_count, state_code=state_code,
        clock_start=clock_start, agency=agency,
    )
    inv_id = investigator_user_id or fresh_id("inv")
    assign_investigator(base["investigation_case_id"], inv_id)
    request = issue_evidence_request(base["investigation_case_id"], inv_id)
    base["investigator_user_id"] = inv_id
    base["evidence_request"] = request
    return base


def setup_pending_review(
    outcome: str = "NO_CAUSE",
    cause_components: Optional[dict] = None,
    basis_codes: Sequence[str] = ("RACE",),
    incident_date: str = "2026-06-01",
    employee_count: int = 40,
    state_code: str = "FL",
    clock_start: str = CLOCK_BOOT_DEFAULT,
    investigator_user_id: Optional[str] = None,
    agency: Optional[dict] = None,
) -> dict:
    """GATHERING case with a submitted determination: determination is
    PENDING_REVIEW and the charge is DETERMINATION_REVIEW.
    cause_components: dict of back_pay_cents/front_pay_cents/
    compensatory_damages_cents/punitive_damages_cents/harm_start_date used
    when outcome == 'CAUSE'. Adds key determination."""
    base = setup_gathering(
        basis_codes=basis_codes, incident_date=incident_date,
        employee_count=employee_count, state_code=state_code,
        clock_start=clock_start, investigator_user_id=investigator_user_id,
        agency=agency,
    )
    if outcome == "CAUSE":
        components = dict(cause_components or {})
        determination = draft_cause_determination(
            base["investigation_case_id"], base["investigator_user_id"],
            **components,
        )
    else:
        determination = draft_determination(
            base["investigation_case_id"], base["investigator_user_id"],
            outcome=outcome,
        )
    submit_determination(determination["id"], base["investigator_user_id"])
    base["determination"] = read_determination_via_list(
        base["investigation_case_id"], determination["id"]
    )
    return base


def read_determination_via_list(case_id: str, determination_id: str) -> dict:
    body = api_client.list_determinations(case_id, _DIRECTOR)
    assert body.status_code == 200, (
        f"Setup failed: list determinations for {case_id} -> "
        f"{body.status_code}: {body.text[:400]}"
    )
    for row in body.json()["data"]:
        if row["id"] == determination_id:
            return row
    raise AssertionError(
        f"Setup failed: determination {determination_id} not in case {case_id} list"
    )


def setup_conciliation(
    cause_components: Optional[dict] = None,
    basis_codes: Sequence[str] = ("RACE",),
    incident_date: str = "2026-06-01",
    employee_count: int = 40,
    state_code: str = "FL",
    clock_start: str = CLOCK_BOOT_DEFAULT,
    investigator_user_id: Optional[str] = None,
    director_user_id: Optional[str] = None,
    agency: Optional[dict] = None,
) -> dict:
    """Full CAUSE path: charge in CONCILIATION with an INITIATED
    ConciliationProcess and a PROVISIONAL RemedyPackage; the investigation is
    CLOSED. The reviewing director defaults to a fresh id distinct from the
    investigator (segregation of duties). Adds keys determination,
    conciliation, remedy_package, director_user_id."""
    base = setup_pending_review(
        outcome="CAUSE", cause_components=cause_components,
        basis_codes=basis_codes, incident_date=incident_date,
        employee_count=employee_count, state_code=state_code,
        clock_start=clock_start, investigator_user_id=investigator_user_id,
        agency=agency,
    )
    dir_id = director_user_id or fresh_id("dir")
    review_determination(base["determination"]["id"], "APPROVE",
                         director_user_id=dir_id)
    charge = read_charge(base["charge"]["id"])
    assert charge["case_status"] == "CONCILIATION", (
        f"Setup failed: expected CONCILIATION, got {charge['case_status']}"
    )
    conciliation = conciliation_for_charge(charge["id"])
    base["charge"] = charge
    base["conciliation"] = conciliation
    base["remedy_package"] = remedy_package_for_conciliation(conciliation["id"])
    base["director_user_id"] = dir_id
    return base


def setup_closed_no_cause(
    outcome: str = "NO_CAUSE",
    basis_codes: Sequence[str] = ("RACE",),
    incident_date: str = "2026-06-01",
    employee_count: int = 40,
    state_code: str = "FL",
    clock_start: str = CLOCK_BOOT_DEFAULT,
    agency: Optional[dict] = None,
) -> dict:
    """Approve a NO_CAUSE/UNABLE_TO_DETERMINE determination: charge is
    CLOSED_NO_CAUSE and one AUTO_ON_DISMISSAL right-to-sue notice exists.
    Adds keys determination, notice."""
    base = setup_pending_review(
        outcome=outcome, basis_codes=basis_codes, incident_date=incident_date,
        employee_count=employee_count, state_code=state_code,
        clock_start=clock_start, agency=agency,
    )
    review_determination(base["determination"]["id"], "APPROVE")
    charge = read_charge(base["charge"]["id"])
    assert charge["case_status"] == "CLOSED_NO_CAUSE", (
        f"Setup failed: expected CLOSED_NO_CAUSE, got {charge['case_status']}"
    )
    notices = api_client.list_right_to_sue_notices(charge["id"], _DIRECTOR)
    assert notices.status_code == 200, (
        f"Setup failed: list RTS notices -> {notices.status_code}"
    )
    rows = notices.json()["data"]
    assert len(rows) == 1, (
        f"Setup failed: expected 1 auto-issued RTS notice, found {len(rows)}"
    )
    base["charge"] = charge
    base["notice"] = rows[0]
    return base


def setup_in_mediation(
    basis_codes: Sequence[str] = ("RACE",),
    incident_date: str = "2026-06-01",
    employee_count: int = 40,
    state_code: str = "FL",
    clock_start: str = CLOCK_BOOT_DEFAULT,
    agency: Optional[dict] = None,
) -> dict:
    """Both parties accepted: mediation ACTIVE, charge IN_MEDIATION.
    Keys: employer, complainant, charge, mediation_case."""
    base = setup_docketed_charge(
        basis_codes=basis_codes, incident_date=incident_date,
        employee_count=employee_count, state_code=state_code,
        clock_start=clock_start, agency=agency,
    )
    mediation = offer_mediation(base["charge"])
    activate_mediation(base["charge"], mediation)
    base["mediation_case"] = _expect_ok(
        api_client.get_mediation_case(
            mediation["id"], TEST_USERS["mediator_headers"]
        ),
        "re-read mediation case",
    )
    base["charge"] = read_charge(base["charge"]["id"])
    return base


def setup_settled_via_mediation(
    settlement_amount_cents: int = 500_000,
    basis_codes: Sequence[str] = ("RACE",),
    incident_date: str = "2026-06-01",
    employee_count: int = 40,
    state_code: str = "FL",
    clock_start: str = CLOCK_BOOT_DEFAULT,
) -> dict:
    """Mediation concluded SETTLED: charge CLOSED_SETTLED with
    settled_via == MEDIATION and settled_at == clock_start.
    Adds keys mediation_case (SETTLED)."""
    base = setup_in_mediation(
        basis_codes=basis_codes, incident_date=incident_date,
        employee_count=employee_count, state_code=state_code,
        clock_start=clock_start,
    )
    settled = conclude_mediation(
        base["mediation_case"], outcome="SETTLED",
        settlement_amount_cents=settlement_amount_cents,
    )
    base["mediation_case"] = settled
    base["charge"] = read_charge(base["charge"]["id"])
    return base


def setup_settled_via_conciliation(
    offer_amount_cents: int = 120_000,
    cause_components: Optional[dict] = None,
    basis_codes: Sequence[str] = ("RACE",),
    incident_date: str = "2026-06-01",
    employee_count: int = 40,
    state_code: str = "FL",
    clock_start: str = CLOCK_BOOT_DEFAULT,
) -> dict:
    """Conciliation offer accepted: process SETTLED (FINAL remedy), charge
    CLOSED_SETTLED with settled_via == CONCILIATION."""
    base = setup_conciliation(
        cause_components=cause_components, basis_codes=basis_codes,
        incident_date=incident_date, employee_count=employee_count,
        state_code=state_code, clock_start=clock_start,
    )
    offer = table_offer(base["conciliation"], offer_amount_cents, "COMMISSION",
                        base["charge"])
    settled = accept_conciliation(offer, base["charge"])
    base["conciliation"] = settled
    base["remedy_package"] = remedy_package_for_conciliation(settled["id"])
    base["charge"] = read_charge(base["charge"]["id"])
    return base


def setup_sealed_charge(
    basis_codes: Sequence[str] = ("SEX",),
    basis_focus: Sequence[str] = ("SEX",),
    incident_date: str = "2026-06-01",
    employee_count: int = 40,
    clock_start: str = CLOCK_BOOT_DEFAULT,
) -> dict:
    """DOCKETED charge linked into a systemic case: disclosure_hold SEALED,
    systemic case EXPANDING. Adds key systemic_case."""
    base = setup_docketed_charge(
        basis_codes=basis_codes, incident_date=incident_date,
        employee_count=employee_count, clock_start=clock_start,
    )
    systemic = create_systemic_case(basis_focus=basis_focus)
    link_charge(systemic, base["charge"])
    base["systemic_case"] = systemic
    base["charge"] = read_charge(base["charge"]["id"])
    return base


def setup_rts_issued(
    via: str = "director",
    days_elapsed: int = 180,
    basis_codes: Sequence[str] = ("RACE",),
    incident_date: str = "2026-06-01",
    employee_count: int = 40,
    clock_start: str = CLOCK_BOOT_DEFAULT,
) -> dict:
    """A charge with its right-to-sue notice issued.
    via='director' issues at discretion (no elapsed-days requirement);
    via='charging_party' first advances the clock so that
    days_elapsed_since_filing == days_elapsed (default 180, the inclusive
    threshold), then files the party request.
    Adds key notice; charge is refreshed to RTS_ISSUED."""
    base = setup_docketed_charge(
        basis_codes=basis_codes, incident_date=incident_date,
        employee_count=employee_count, clock_start=clock_start,
    )
    if via == "charging_party":
        target = add_days(clock_start, days_elapsed)
        set_clock_to_date(target)
        notice = issue_rts_as_charging_party(base["charge"])
    elif via == "director":
        notice = issue_rts_as_director(base["charge"])
    else:
        raise ValueError(f"via must be 'director' or 'charging_party', got {via!r}")
    base["notice"] = notice
    base["charge"] = read_charge(base["charge"]["id"])
    return base


def setup_overdue_evidence(
    request_count: int = 1,
    days_after_due: int = 1,
    basis_codes: Sequence[str] = ("RETALIATION",),
    incident_date: str = "2026-06-01",
    employee_count: int = 40,
    clock_start: str = CLOCK_BOOT_DEFAULT,
) -> dict:
    """GATHERING case with request_count PENDING requests, then the clock
    advanced days_after_due days past their 30-day due date: every request
    reads OVERDUE. Adds keys investigator_user_id, evidence_requests."""
    base = setup_gathering(
        basis_codes=basis_codes, incident_date=incident_date,
        employee_count=employee_count, clock_start=clock_start,
    )
    requests = [base["evidence_request"]]
    if request_count > 1:
        requests.extend(
            issue_evidence_requests(
                base["investigation_case_id"], base["investigator_user_id"],
                request_count - 1,
            )
        )
    due_date = requests[0]["due_date"]
    set_clock_to_date(add_days(due_date, days_after_due))
    base["evidence_requests"] = requests
    return base
