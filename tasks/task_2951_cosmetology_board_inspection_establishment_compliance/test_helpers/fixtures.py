"""Composite setup helpers and pytest fixtures.

The runner wipes the database and relaunches the server before every test, so
the logical clock is back at ``2026-08-01T00:00:00Z`` and every helper below
builds the state it needs from scratch.  Setup calls go through
``get_success_data`` so a broken precondition reports the server's own
``error_id`` rather than a bare status code.
"""
from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient, api_client
from .test_users import (
    BOARD_ADMIN_HEADERS,
    INSPECTOR_HEADERS,
    INSPECTOR_USER_ID,
    make_establishment_owner_headers,
)


# --- Reference data -----------------------------------------------------------
def create_violation_code(
    client: ApiClient,
    severity: str = "MINOR",
    base_points: float = 1.00,
    fine_cents_base: int = 10000,
    category: str = "SANITATION",
    code: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_violation_code(
            f.violation_code_payload(
                code=code,
                category=category,
                severity=severity,
                base_points=base_points,
                fine_cents_base=fine_cents_base,
            ),
            BOARD_ADMIN_HEADERS,
        )
    )


def create_school(
    client: ApiClient,
    required_clock_hours: float = 16.00,
    accreditation_status: Optional[str] = None,
    apprenticeship_program_approved: Optional[bool] = None,
    county_code: str = "AAA",
) -> Dict[str, Any]:
    return get_success_data(
        client.create_school(
            f.school_payload(
                county_code=county_code,
                required_clock_hours=required_clock_hours,
                accreditation_status=accreditation_status,
                apprenticeship_program_approved=apprenticeship_program_approved,
            ),
            BOARD_ADMIN_HEADERS,
        )
    )


def create_establishment(
    client: ApiClient,
    station_capacity: int = 5,
    establishment_type: str = "SALON",
    county_code: str = "AAA",
    legal_name: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_establishment(
            f.establishment_payload(
                legal_name=legal_name,
                establishment_type=establishment_type,
                county_code=county_code,
                station_capacity=station_capacity,
            ),
            BOARD_ADMIN_HEADERS,
        )
    )


# --- Practitioners ------------------------------------------------------------
def create_candidate(
    client: ApiClient,
    school_id: Optional[str] = None,
    license_type: str = "COSMETOLOGIST",
    full_name: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_practitioner(
            f.practitioner_payload(
                full_name=full_name, license_type=license_type, school_id=school_id
            ),
            BOARD_ADMIN_HEADERS,
        )
    )


def file_training_record(
    client: ApiClient,
    practitioner_id: str,
    credit_type: str = "SCHOOL_CLOCK_HOUR",
    hours: float = 8.00,
    performed_on: str = "2026-07-06",
    discipline: str = "THEORY",
    school_id: Optional[str] = None,
    sponsor_practitioner_id: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_training_record(
            f.training_record_payload(
                practitioner_id=practitioner_id,
                credit_type=credit_type,
                hours=hours,
                performed_on=performed_on,
                discipline=discipline,
                school_id=school_id,
                sponsor_practitioner_id=sponsor_practitioner_id,
            ),
            BOARD_ADMIN_HEADERS,
        )
    )


def apply_action(
    client: ApiClient,
    practitioner_id: str,
    action: str,
    effective_at: Optional[str] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.apply_license_action(
            practitioner_id,
            f.license_action_payload(action, effective_at=effective_at, reason=reason),
            BOARD_ADMIN_HEADERS,
        )
    )


def create_licensed_practitioner(
    client: ApiClient,
    school_id: Optional[str] = None,
    license_type: str = "COSMETOLOGIST",
    effective_at: str = "2026-08-01T00:00:00.000Z",
    full_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Walk PRD 3.2 all the way to an ``ACTIVE`` licence.

    A candidate needs `credited_hours_total >= required_clock_hours_effective`
    plus at least one `SANITATION` and one `DISINFECTION` record before
    `GRANT_EXAM_ELIGIBILITY` is legal, so the school is opened with a 16-hour
    requirement and two eight-hour records satisfy both gates at once.
    """
    if school_id is None:
        school_id = create_school(client, required_clock_hours=16.00)["id"]
    candidate = create_candidate(
        client, school_id=school_id, license_type=license_type, full_name=full_name
    )
    file_training_record(
        client,
        candidate["id"],
        hours=8.00,
        performed_on="2026-07-06",
        discipline="SANITATION",
        school_id=school_id,
    )
    file_training_record(
        client,
        candidate["id"],
        hours=8.00,
        performed_on="2026-07-07",
        discipline="DISINFECTION",
        school_id=school_id,
    )
    apply_action(client, candidate["id"], "GRANT_EXAM_ELIGIBILITY")
    return apply_action(
        client, candidate["id"], "ISSUE_LICENSE", effective_at=effective_at
    )


# --- Build-out ----------------------------------------------------------------
def add_workstation(
    client: ApiClient,
    establishment_id: str,
    station_number: int = 1,
    station_type: str = "STYLING_CHAIR",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_workstation(
            establishment_id,
            f.workstation_payload(
                station_number=station_number, station_type=station_type
            ),
            headers if headers is not None else BOARD_ADMIN_HEADERS,
        )
    )


def refresh_workstation(client: ApiClient, workstation_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_workstation(workstation_id, BOARD_ADMIN_HEADERS))


def refresh_establishment(client: ApiClient, establishment_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.get_establishment(establishment_id, BOARD_ADMIN_HEADERS)
    )


def refresh_practitioner(client: ApiClient, practitioner_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.get_practitioner(practitioner_id, BOARD_ADMIN_HEADERS)
    )


def refresh_inspection(client: ApiClient, inspection_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_inspection(inspection_id, BOARD_ADMIN_HEADERS))


def refresh_citation(client: ApiClient, citation_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_citation(citation_id, BOARD_ADMIN_HEADERS))


def refresh_booth_rental(client: ApiClient, booth_rental_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.get_booth_rental(booth_rental_id, BOARD_ADMIN_HEADERS)
    )


def propose_rental(
    client: ApiClient,
    workstation_id: str,
    practitioner_id: str,
    term_start_at: str = "2026-08-01T00:00:00.000Z",
    term_end_at: Optional[str] = None,
    rental_type: str = "BOOTH_RENTER_INDEPENDENT_CONTRACTOR",
    monthly_rent_cents: int = 50000,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Create a rental, reading the station's current ``version`` first (PRD 2.8)."""
    station = refresh_workstation(client, workstation_id)
    return get_success_data(
        client.create_booth_rental(
            f.booth_rental_payload(
                workstation_id=workstation_id,
                practitioner_id=practitioner_id,
                expected_workstation_version=station["version"],
                rental_type=rental_type,
                term_start_at=term_start_at,
                term_end_at=term_end_at,
                monthly_rent_cents=monthly_rent_cents,
            ),
            headers if headers is not None else BOARD_ADMIN_HEADERS,
        )
    )


def post_licence(
    client: ApiClient,
    workstation_id: str,
    practitioner_id: Optional[str],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.post_licence_at_workstation(
            workstation_id,
            f.posting_payload(practitioner_id),
            headers if headers is not None else BOARD_ADMIN_HEADERS,
        )
    )


def activate_rental(
    client: ApiClient, booth_rental_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        client.activate_booth_rental(
            booth_rental_id, headers if headers is not None else BOARD_ADMIN_HEADERS
        )
    )


def setup_compliant_station(
    client: ApiClient,
    establishment_id: str,
    practitioner_id: str,
    station_number: int = 1,
    station_type: str = "STYLING_CHAIR",
    term_start_at: str = "2026-08-01T00:00:00.000Z",
    term_end_at: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD 3.3's two-step choreography: propose, post, then activate.

    Only after activation does the station read ``COMPLIANT``, because a
    ``PROPOSED`` rental never satisfies the third posting condition.
    """
    station = add_workstation(
        client, establishment_id, station_number=station_number, station_type=station_type
    )
    rental = propose_rental(
        client,
        station["id"],
        practitioner_id,
        term_start_at=term_start_at,
        term_end_at=term_end_at,
    )
    post_licence(client, station["id"], practitioner_id)
    rental = activate_rental(client, rental["id"])
    return {
        "workstation": refresh_workstation(client, station["id"]),
        "booth_rental": rental,
    }


def setup_establishment_with_posted_practitioner(
    client: ApiClient,
    station_capacity: int = 5,
    station_type: str = "STYLING_CHAIR",
) -> Dict[str, Any]:
    """An operable salon with one ``COMPLIANT`` station and a linked licensee."""
    school = create_school(client, required_clock_hours=16.00)
    practitioner = create_licensed_practitioner(client, school_id=school["id"])
    establishment = create_establishment(client, station_capacity=station_capacity)
    built = setup_compliant_station(
        client,
        establishment["id"],
        practitioner["id"],
        station_number=1,
        station_type=station_type,
    )
    return {
        "school": school,
        "practitioner": practitioner,
        "establishment": refresh_establishment(client, establishment["id"]),
        "workstation": built["workstation"],
        "booth_rental": built["booth_rental"],
        "owner_headers": make_establishment_owner_headers(establishment["id"]),
    }


# --- Inspection windows -------------------------------------------------------
# PRD 3.5 imposes a closed-interval overlap check plus a symmetric 24-hour
# cooldown, so successive inspections on one establishment need windows spaced
# well clear of each other.  Three-day spacing satisfies both.
def window_for(index: int) -> Dict[str, str]:
    day = 1 + 3 * index
    return {
        "window_start_at": f"2026-08-{day:02d}T09:00:00.000Z",
        "window_end_at": f"2026-08-{day:02d}T17:00:00.000Z",
    }


def schedule_inspection(
    client: ApiClient,
    establishment_id: str,
    inspection_type: str = "ROUTINE",
    inspector_user_id: str = INSPECTOR_USER_ID,
    window_index: int = 0,
    window_start_at: Optional[str] = None,
    window_end_at: Optional[str] = None,
    reinspection_of_id: Optional[str] = None,
    complaint_reference: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    window = window_for(window_index)
    return get_success_data(
        client.create_inspection(
            f.inspection_payload(
                establishment_id=establishment_id,
                inspector_user_id=inspector_user_id,
                inspection_type=inspection_type,
                window_start_at=window_start_at or window["window_start_at"],
                window_end_at=window_end_at or window["window_end_at"],
                reinspection_of_id=reinspection_of_id,
                complaint_reference=complaint_reference,
            ),
            headers if headers is not None else BOARD_ADMIN_HEADERS,
        )
    )


def record_finding(
    client: ApiClient,
    inspection_id: str,
    violation_code_id: str,
    observed_count: int = 1,
    corrected_on_site: bool = False,
    attributed_practitioner_id: Optional[str] = None,
    workstation_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_finding(
            inspection_id,
            f.finding_payload(
                violation_code_id=violation_code_id,
                observed_count=observed_count,
                corrected_on_site=corrected_on_site,
                attributed_practitioner_id=attributed_practitioner_id,
                workstation_id=workstation_id,
            ),
            headers if headers is not None else INSPECTOR_HEADERS,
        )
    )


def setup_inspection_in_progress(
    client: ApiClient,
    establishment_id: str,
    inspection_type: str = "ROUTINE",
    inspector_user_id: str = INSPECTOR_USER_ID,
    window_index: int = 0,
    reinspection_of_id: Optional[str] = None,
) -> Dict[str, Any]:
    inspection = schedule_inspection(
        client,
        establishment_id,
        inspection_type=inspection_type,
        inspector_user_id=inspector_user_id,
        window_index=window_index,
        reinspection_of_id=reinspection_of_id,
    )
    return get_success_data(
        client.start_inspection(inspection["id"], BOARD_ADMIN_HEADERS)
    )


def setup_submitted_inspection(
    client: ApiClient,
    establishment_id: str,
    findings: Optional[List[Dict[str, Any]]] = None,
    inspection_type: str = "ROUTINE",
    inspector_user_id: str = INSPECTOR_USER_ID,
    window_index: int = 0,
    reinspection_of_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Schedule, start, record every finding, then submit for review."""
    inspection = setup_inspection_in_progress(
        client,
        establishment_id,
        inspection_type=inspection_type,
        inspector_user_id=inspector_user_id,
        window_index=window_index,
        reinspection_of_id=reinspection_of_id,
    )
    recorded = []
    for spec in findings or []:
        recorded.append(record_finding(client, inspection["id"], **spec))
    submitted = get_success_data(
        client.submit_inspection(inspection["id"], BOARD_ADMIN_HEADERS)
    )
    return {"inspection": submitted, "findings": recorded}


def setup_finalized_inspection(
    client: ApiClient,
    establishment_id: str,
    findings: Optional[List[Dict[str, Any]]] = None,
    inspection_type: str = "ROUTINE",
    inspector_user_id: str = INSPECTOR_USER_ID,
    window_index: int = 0,
    reinspection_of_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Drive one visit all the way through the five-hop finalize cascade."""
    submitted = setup_submitted_inspection(
        client,
        establishment_id,
        findings=findings,
        inspection_type=inspection_type,
        inspector_user_id=inspector_user_id,
        window_index=window_index,
        reinspection_of_id=reinspection_of_id,
    )
    finalized = get_success_data(
        client.finalize_inspection(submitted["inspection"]["id"], BOARD_ADMIN_HEADERS)
    )
    return {"inspection": finalized, "findings": submitted["findings"]}


# --- Citations, hearings, payments ---------------------------------------------
def issue_citation(
    client: ApiClient,
    inspection_id: str,
    subject_type: str = "ESTABLISHMENT",
    subject_practitioner_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Re-read the inspection's ``version`` first, as PRD 2.8 requires."""
    inspection = refresh_inspection(client, inspection_id)
    return get_success_data(
        client.create_citation(
            f.citation_payload(
                inspection_id=inspection_id,
                expected_inspection_version=inspection["version"],
                subject_type=subject_type,
                subject_practitioner_id=subject_practitioner_id,
            ),
            BOARD_ADMIN_HEADERS,
        )
    )


def contest_citation(
    client: ApiClient, citation_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return get_success_data(
        client.contest_citation(
            citation_id,
            f.contest_payload(),
            headers if headers is not None else BOARD_ADMIN_HEADERS,
        )
    )


def schedule_hearing(
    client: ApiClient,
    citation_id: str,
    presiding_officer_user_id: str,
    scheduled_at: str = "2026-08-10T10:00:00.000Z",
) -> Dict[str, Any]:
    return get_success_data(
        client.schedule_hearing(
            citation_id,
            f.hearing_payload(presiding_officer_user_id, scheduled_at=scheduled_at),
            BOARD_ADMIN_HEADERS,
        )
    )


def decide_hearing(
    client: ApiClient,
    hearing_id: str,
    decision: str = "AFFIRMED",
    amended_fine_cents: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.record_hearing_decision(
            hearing_id,
            f.decision_payload(decision=decision, amended_fine_cents=amended_fine_cents),
            headers if headers is not None else BOARD_ADMIN_HEADERS,
        )
    )


def pay_citation(
    client: ApiClient,
    citation_id: str,
    amount_cents: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.pay_citation(
            citation_id,
            f.payment_payload(amount_cents),
            headers if headers is not None else BOARD_ADMIN_HEADERS,
        )
    )


def setup_contested_citation_with_hearing(
    client: ApiClient,
    citation_id: str,
    presiding_officer_user_id: str,
    scheduled_at: str = "2026-08-10T10:00:00.000Z",
) -> Dict[str, Any]:
    contest_citation(client, citation_id)
    hearing = schedule_hearing(
        client, citation_id, presiding_officer_user_id, scheduled_at=scheduled_at
    )
    return {"citation": refresh_citation(client, citation_id), "hearing": hearing}


# --- Sanitation ----------------------------------------------------------------
def file_sanitation_log(
    client: ApiClient,
    workstation_id: str,
    log_type: str = "IMPLEMENT_DISINFECTION",
    performed_at: str = "2026-08-01T09:00:00.000Z",
    contact_minutes: float = 10.00,
    implement_batch_count: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_sanitation_log(
            f.sanitation_log_payload(
                workstation_id=workstation_id,
                log_type=log_type,
                performed_at=performed_at,
                contact_minutes=contact_minutes,
                implement_batch_count=implement_batch_count,
            ),
            headers if headers is not None else BOARD_ADMIN_HEADERS,
        )
    )


# --- Infection incidents -------------------------------------------------------
def open_incident(
    client: ApiClient,
    establishment_id: str,
    case_count: int = 1,
    suspected_practitioner_id: Optional[str] = None,
    onset_date: str = "2026-07-28",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_infection_incident(
            f.infection_incident_payload(
                establishment_id=establishment_id,
                case_count=case_count,
                onset_date=onset_date,
                suspected_practitioner_id=suspected_practitioner_id,
            ),
            headers if headers is not None else BOARD_ADMIN_HEADERS,
        )
    )


def notify_incident(
    client: ApiClient, incident_id: str, notified_at: Optional[str] = None
) -> Dict[str, Any]:
    return get_success_data(
        client.notify_infection_incident(
            incident_id,
            f.notification_payload(notified_at=notified_at),
            BOARD_ADMIN_HEADERS,
        )
    )


def resolve_incident(
    client: ApiClient, incident_id: str, resolution: str = "SUBSTANTIATED"
) -> Dict[str, Any]:
    return get_success_data(
        client.resolve_infection_incident(
            incident_id, f.resolution_payload(resolution=resolution), BOARD_ADMIN_HEADERS
        )
    )


def setup_substantiated_incident(
    client: ApiClient,
    establishment_id: str,
    suspected_practitioner_id: str,
    case_count: int = 1,
) -> Dict[str, Any]:
    """Report, notify, then substantiate — the only path that posts sanction points."""
    incident = open_incident(
        client,
        establishment_id,
        case_count=case_count,
        suspected_practitioner_id=suspected_practitioner_id,
    )
    notify_incident(client, incident["id"])
    return resolve_incident(client, incident["id"], resolution="SUBSTANTIATED")


# --- Logical clock -------------------------------------------------------------
def advance_clock(client: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    return get_success_data(client.set_clock(to_iso8601, BOARD_ADMIN_HEADERS))


# --- Ledger --------------------------------------------------------------------
def ledger_entries(
    client: ApiClient, params: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    merged: Dict[str, Any] = {"limit": 100}
    merged.update(params or {})
    return get_success_data(client.list_ledger_entries(BOARD_ADMIN_HEADERS, merged))


# --- Pytest fixtures -----------------------------------------------------------
@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the runner owns the server lifecycle."""
    return api_client


@pytest.fixture
def minor_code(api: ApiClient) -> Dict[str, Any]:
    """A MINOR schedule entry with base_points 1.00 and a 10000-cent base fine."""
    return create_violation_code(
        api, severity="MINOR", base_points=1.00, fine_cents_base=10000
    )


@pytest.fixture
def major_code(api: ApiClient) -> Dict[str, Any]:
    return create_violation_code(
        api,
        severity="MAJOR",
        base_points=2.00,
        fine_cents_base=20000,
        category="DISINFECTION",
    )


@pytest.fixture
def critical_code(api: ApiClient) -> Dict[str, Any]:
    return create_violation_code(
        api,
        severity="CRITICAL",
        base_points=2.00,
        fine_cents_base=30000,
        category="IMPLEMENT_HANDLING",
    )


@pytest.fixture
def hazard_code(api: ApiClient) -> Dict[str, Any]:
    return create_violation_code(
        api,
        severity="IMMINENT_HAZARD",
        base_points=5.00,
        fine_cents_base=40000,
        category="FOOT_SPA",
    )


@pytest.fixture
def establishment(api: ApiClient) -> Dict[str, Any]:
    return create_establishment(api, station_capacity=5)


@pytest.fixture
def licensed_practitioner(api: ApiClient) -> Dict[str, Any]:
    return create_licensed_practitioner(api)


@pytest.fixture
def posted_salon(api: ApiClient) -> Dict[str, Any]:
    """An operable salon, a licensed occupant and one COMPLIANT station."""
    return setup_establishment_with_posted_practitioner(api)
