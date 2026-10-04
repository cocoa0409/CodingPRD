"""Composite setup fixtures that walk the public API to a wanted state.

Every test starts against an empty deployment (the harness restarts the server
before each test), so these helpers rebuild the world from scratch each time.
They are organised in tiers:

  Tier 1  clock and standing reference data (regulation, system, program)
  Tier 2  applicator enrollment and certification
  Tier 3  project + issued specification ("the world")
  Tier 4  work-order progression: prep approval, coats, cure, reports
  Tier 5  warranty issuance, claims and investigations

Setup calls use the lenient success reader, so a failure inside a fixture is
reported as a setup failure, not as a confusing assertion error.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import (
    BASE_CLOCK_UTC,
    COAT_APPLIED_AT,
    CURE_CLOCK_ONE_COAT,
    CURE_CLOCK_TWO_COATS,
    SECOND_COAT_APPLIED_AT,
    WORK_ORDER_WINDOW_END,
    WORK_ORDER_WINDOW_START,
)
from .test_users import (
    COMPLIANCE_OFFICER_HEADERS,
    INSPECTOR_HEADERS,
    OWNER_REPRESENTATIVE_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    PROJECT_ENGINEER_HEADERS,
    TECHNICAL_SERVICE_ENGINEER_HEADERS,
    make_applicator_rep_headers,
)

_UNSET = f._UNSET


# ═══ Tier 1: clock and reference data ══════════════════════════════════════

def set_clock(api: ApiClient, current_utc: str = BASE_CLOCK_UTC) -> Dict[str, Any]:
    return get_success_data(api.set_clock(f.clock_payload(current_utc), PLATFORM_ADMIN_HEADERS))


def create_regulation(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_voc_regulation(f.voc_regulation_payload(**overrides), COMPLIANCE_OFFICER_HEADERS)
    )


def create_coating_system(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_coating_system(f.coating_system_payload(**overrides), TECHNICAL_SERVICE_ENGINEER_HEADERS)
    )


def create_program(api: ApiClient, coating_system_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_qualification_program(
            f.qualification_program_payload(coating_system_id, **overrides),
            TECHNICAL_SERVICE_ENGINEER_HEADERS,
        )
    )


# ═══ Tier 2: applicators and qualifications ════════════════════════════════

def create_applicator(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_applicator(f.applicator_payload(**overrides), PLATFORM_ADMIN_HEADERS))


def read_applicator(api: ApiClient, applicator_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_applicator(applicator_id, TECHNICAL_SERVICE_ENGINEER_HEADERS))


def enroll_qualification(api: ApiClient, applicator_id: str, program_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.enroll_qualification(
            applicator_id,
            f.enrollment_payload(program_id, **overrides),
            make_applicator_rep_headers(applicator_id),
        )
    )


def read_qualification(api: ApiClient, applicator_id: str, qualification_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_qualification(applicator_id, qualification_id, TECHNICAL_SERVICE_ENGINEER_HEADERS)
    )


def certify_qualification(
    api: ApiClient,
    applicator_id: str,
    qualification_id: str,
    expected_applicator_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Certify a CANDIDATE qualification under optimistic concurrency.

    When no version is supplied, the applicator's current version is observed
    first, which is the flow a well-behaved client follows.
    """
    if expected_applicator_version is None:
        expected_applicator_version = read_applicator(api, applicator_id)["version"]
    return get_success_data(
        api.certify_qualification(
            applicator_id,
            qualification_id,
            f.certify_payload(expected_applicator_version),
            TECHNICAL_SERVICE_ENGINEER_HEADERS,
        )
    )


def suspend_qualification(api: ApiClient, applicator_id: str, qualification_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.suspend_qualification(applicator_id, qualification_id, TECHNICAL_SERVICE_ENGINEER_HEADERS)
    )


def reinstate_qualification(api: ApiClient, applicator_id: str, qualification_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.reinstate_qualification(applicator_id, qualification_id, TECHNICAL_SERVICE_ENGINEER_HEADERS)
    )


def create_certified_applicator(
    api: ApiClient,
    coating_system_id: str,
    program_overrides: Optional[Dict[str, Any]] = None,
    applicator_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Applicator + enrollment + certification for one coating system.

    Returns a dict with the applicator, the qualification and the program.
    """
    program = create_program(api, coating_system_id, **(program_overrides or {}))
    applicator = create_applicator(api, **(applicator_overrides or {}))
    qualification = enroll_qualification(api, applicator["id"], program["id"])
    qualification = certify_qualification(api, applicator["id"], qualification["id"])
    return {
        "program": program,
        "applicator": read_applicator(api, applicator["id"]),
        "qualification": qualification,
    }


# ═══ Tier 3: projects and specifications ═══════════════════════════════════

def create_project(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_project(f.project_payload(**overrides), PROJECT_ENGINEER_HEADERS))


def read_project(api: ApiClient, project_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_project(project_id, PLATFORM_ADMIN_HEADERS))


def create_specification(
    api: ApiClient,
    project_id: str,
    coating_system_id: str,
    application_method: str = "SPRAY_AIRLESS",
    supersedes_specification_id: Any = _UNSET,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_specification(
            project_id,
            f.specification_payload(
                coating_system_id,
                application_method=application_method,
                supersedes_specification_id=supersedes_specification_id,
            ),
            PROJECT_ENGINEER_HEADERS,
        )
    )


def read_specification(api: ApiClient, spec_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_specification_flat(spec_id, PLATFORM_ADMIN_HEADERS))


def issue_specification(
    api: ApiClient,
    project_id: str,
    spec_id: str,
    expected_project_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Issue a DRAFT specification, observing the project version when omitted."""
    if expected_project_version is None:
        expected_project_version = read_project(api, project_id)["version"]
    return get_success_data(
        api.issue_specification(
            project_id, spec_id, f.issue_payload(expected_project_version), PROJECT_ENGINEER_HEADERS
        )
    )


def create_world(
    api: ApiClient,
    *,
    jurisdiction_code: str = "US-FED",
    application_method: str = "SPRAY_AIRLESS",
    voc_limit_gpl: int = 340,
    asset_type: str = "BRIDGE",
    warranty_budget_cents: int = 1_000_000,
    with_regulation: bool = True,
    system_overrides: Optional[Dict[str, Any]] = None,
    program_overrides: Optional[Dict[str, Any]] = None,
    applicator_overrides: Optional[Dict[str, Any]] = None,
    certifying: bool = True,
    issuing: bool = True,
) -> Dict[str, Any]:
    """Build the standing world most tests need.

    Clock pinned at the contract's base instant, one ACTIVE regulation covering
    the jurisdiction/method pair for the whole of 2026, one ACTIVE coating
    system, one qualification program, one applicator (certified unless
    ``certifying`` is false), one project, and one specification (issued unless
    ``issuing`` is false). Returns every created record plus the applicator's
    caller headers.
    """
    set_clock(api, BASE_CLOCK_UTC)
    regulation = None
    if with_regulation:
        regulation = create_regulation(
            api,
            jurisdiction_code=jurisdiction_code,
            application_method=application_method,
            voc_limit_gpl=voc_limit_gpl,
        )
    system = create_coating_system(api, **(system_overrides or {}))
    program = create_program(api, system["id"], **(program_overrides or {}))
    applicator = create_applicator(api, **(applicator_overrides or {}))
    qualification = enroll_qualification(api, applicator["id"], program["id"])
    if certifying:
        qualification = certify_qualification(api, applicator["id"], qualification["id"])
        applicator = read_applicator(api, applicator["id"])
    project = create_project(
        api,
        jurisdiction_code=jurisdiction_code,
        asset_type=asset_type,
        warranty_budget_cents=warranty_budget_cents,
    )
    spec = create_specification(api, project["id"], system["id"], application_method=application_method)
    if issuing:
        spec = issue_specification(api, project["id"], spec["id"])
        project = read_project(api, project["id"])
    return {
        "regulation": regulation,
        "system": system,
        "program": program,
        "applicator": applicator,
        "qualification": qualification,
        "project": project,
        "spec": spec,
        "applicator_headers": make_applicator_rep_headers(applicator["id"]),
    }


# ═══ Tier 4: work orders, prep, coats, reports ═════════════════════════════

def create_work_order(
    api: ApiClient,
    project_id: str,
    spec_id: str,
    applicator_id: str,
    asset_zone: str = "ZONE-1",
    window_start: str = WORK_ORDER_WINDOW_START,
    window_end: str = WORK_ORDER_WINDOW_END,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_work_order(
            project_id,
            f.work_order_payload(
                spec_id, applicator_id,
                asset_zone=asset_zone, window_start=window_start, window_end=window_end,
            ),
            PROJECT_ENGINEER_HEADERS,
        )
    )


def read_work_order(api: ApiClient, work_order_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_work_order_flat(work_order_id, PLATFORM_ADMIN_HEADERS))


def begin_prep_inspection(api: ApiClient, project_id: str, work_order_id: str, applicator_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.begin_prep_inspection(
            project_id, work_order_id, make_applicator_rep_headers(applicator_id)
        )
    )


def file_prep_inspection(
    api: ApiClient,
    work_order_id: str,
    *,
    observed_prep_standard: str = "SSPC_SP10_NEAR_WHITE",
    measured_profile_mils: float = 3.0,
    soluble_salt_ug_cm2: float = 5.0,
    ambient_dew_point_spread_c: float = 5.0,
    inspector_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_prep_inspection(
            work_order_id,
            f.prep_inspection_payload(
                observed_prep_standard=observed_prep_standard,
                measured_profile_mils=measured_profile_mils,
                soluble_salt_ug_cm2=soluble_salt_ug_cm2,
                ambient_dew_point_spread_c=ambient_dew_point_spread_c,
            ),
            inspector_headers or INSPECTOR_HEADERS,
        )
    )


def drive_to_prep_approved(
    api: ApiClient,
    world: Dict[str, Any],
    *,
    asset_zone: str = "ZONE-1",
    window_start: str = WORK_ORDER_WINDOW_START,
    window_end: str = WORK_ORDER_WINDOW_END,
) -> Dict[str, Any]:
    """Create a work order and walk it to PREP_APPROVED via a passing prep inspection."""
    work_order = create_work_order(
        api,
        world["project"]["id"],
        world["spec"]["id"],
        world["applicator"]["id"],
        asset_zone=asset_zone,
        window_start=window_start,
        window_end=window_end,
    )
    begin_prep_inspection(api, world["project"]["id"], work_order["id"], world["applicator"]["id"])
    file_prep_inspection(
        api,
        work_order["id"],
        observed_prep_standard=world["system"]["surface_prep_standard"],
        measured_profile_mils=round(
            (world["system"]["min_surface_profile_mils"] + world["system"]["max_surface_profile_mils"]) / 2, 1
        ),
    )
    return read_work_order(api, work_order["id"])


def record_application(
    api: ApiClient,
    work_order_id: str,
    applicator_id: str,
    *,
    coat_number: int = 1,
    applied_at: str = COAT_APPLIED_AT,
    thinner_pct_used: float = 0.0,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_application(
            work_order_id,
            f.application_payload(
                coat_number=coat_number, applied_at=applied_at, thinner_pct_used=thinner_pct_used
            ),
            make_applicator_rep_headers(applicator_id),
        )
    )


def read_application(api: ApiClient, application_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_application(application_id, PLATFORM_ADMIN_HEADERS))


def advance_clock_and_mark_cured(
    api: ApiClient,
    work_order_id: str,
    application_id: str,
    applicator_id: str,
    cure_clock: str = CURE_CLOCK_ONE_COAT,
) -> Dict[str, Any]:
    """Move the logical clock past the twenty-four-hour cure window and mark cured."""
    set_clock(api, cure_clock)
    return get_success_data(
        api.mark_application_cured(
            work_order_id, application_id, make_applicator_rep_headers(applicator_id)
        )
    )


def file_inspection_report(
    api: ApiClient,
    work_order_id: str,
    application_id: str,
    *,
    spot_dft_readings_mils: Optional[List[float]] = None,
    adhesion_readings_psi: Optional[List[float]] = None,
    holiday_count: int = 0,
    tested_area_m2: float = 10.0,
    inspector_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_inspection_report(
            work_order_id,
            application_id,
            f.inspection_report_payload(
                spot_dft_readings_mils=spot_dft_readings_mils,
                adhesion_readings_psi=adhesion_readings_psi,
                holiday_count=holiday_count,
                tested_area_m2=tested_area_m2,
            ),
            inspector_headers or INSPECTOR_HEADERS,
        )
    )


def drive_to_cured_coat(
    api: ApiClient,
    world: Dict[str, Any],
    *,
    asset_zone: str = "ZONE-1",
    coat_number: int = 1,
    applied_at: str = COAT_APPLIED_AT,
    thinner_pct_used: float = 0.0,
    cure_clock: str = CURE_CLOCK_ONE_COAT,
) -> Dict[str, Any]:
    """Work order to PREP_APPROVED, one coat recorded and marked CURED."""
    work_order = drive_to_prep_approved(api, world, asset_zone=asset_zone)
    application = record_application(
        api,
        work_order["id"],
        world["applicator"]["id"],
        coat_number=coat_number,
        applied_at=applied_at,
        thinner_pct_used=thinner_pct_used,
    )
    advance_clock_and_mark_cured(
        api, work_order["id"], application["id"], world["applicator"]["id"], cure_clock
    )
    return {"work_order": read_work_order(api, work_order["id"]), "application": read_application(api, application["id"])}


def complete_work_order(api: ApiClient, project_id: str, work_order_id: str) -> Dict[str, Any]:
    return get_success_data(api.complete_work_order(project_id, work_order_id, PROJECT_ENGINEER_HEADERS))


def drive_to_completed_work_order(
    api: ApiClient,
    world: Dict[str, Any],
    *,
    asset_zone: str = "ZONE-1",
    coat_count: int = 1,
    inspector_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Work order driven to COMPLETED with every coat cured and ACCEPTED.

    Coats are applied one day apart and cured together after the last coat's
    twenty-four-hour window; each receives a passing inspection report.
    """
    work_order = drive_to_prep_approved(api, world, asset_zone=asset_zone)
    applications: List[Dict[str, Any]] = []
    applied_days = [COAT_APPLIED_AT, SECOND_COAT_APPLIED_AT]
    cure_clock = CURE_CLOCK_ONE_COAT if coat_count == 1 else CURE_CLOCK_TWO_COATS
    for index in range(coat_count):
        applications.append(
            record_application(
                api,
                work_order["id"],
                world["applicator"]["id"],
                coat_number=index + 1,
                applied_at=applied_days[index],
            )
        )
    set_clock(api, cure_clock)
    reports: List[Dict[str, Any]] = []
    for application in applications:
        get_success_data(
            api.mark_application_cured(
                work_order["id"], application["id"], world["applicator_headers"]
            )
        )
        reports.append(
            file_inspection_report(
                api, work_order["id"], application["id"], inspector_headers=inspector_headers
            )
        )
    completed = complete_work_order(api, world["project"]["id"], work_order["id"])
    return {
        "work_order": completed,
        "applications": applications,
        "reports": reports,
    }


# ═══ Tier 5: warranties, claims, investigations ════════════════════════════

def issue_warranty(
    api: ApiClient,
    project_id: str,
    work_order_id: str,
    *,
    term_years: int = 5,
    exposure_cents: int = 80_000,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_warranty(
            project_id,
            f.warranty_payload(work_order_id, term_years=term_years, exposure_cents=exposure_cents),
            PROJECT_ENGINEER_HEADERS,
        )
    )


def read_warranty(api: ApiClient, warranty_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_warranty_flat(warranty_id, PLATFORM_ADMIN_HEADERS))


def claim_warranty(
    api: ApiClient,
    project_id: str,
    warranty_id: str,
    *,
    defect_mode: str = "ADHESION_LOSS",
    evidence_notes: str = "blistering at weld seams",
) -> Dict[str, Any]:
    return get_success_data(
        api.claim_warranty(
            project_id,
            warranty_id,
            f.claim_payload(defect_mode=defect_mode, evidence_notes=evidence_notes),
            OWNER_REPRESENTATIVE_HEADERS,
        )
    )


def void_warranty(api: ApiClient, project_id: str, warranty_id: str, void_reason: str) -> Dict[str, Any]:
    return get_success_data(
        api.void_warranty(project_id, warranty_id, f.void_payload(void_reason), TECHNICAL_SERVICE_ENGINEER_HEADERS)
    )


def read_investigation(api: ApiClient, warranty_id: str) -> Dict[str, Any]:
    """The single investigation a claim opens on a warranty."""
    investigations = get_success_data(api.list_investigations(warranty_id, PLATFORM_ADMIN_HEADERS))
    assert isinstance(investigations, list) and investigations, (
        f"Setup failed: no investigation listed for warranty {warranty_id}"
    )
    return investigations[0]


def begin_evidence(api: ApiClient, warranty_id: str, investigation_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.begin_investigation_evidence(warranty_id, investigation_id, TECHNICAL_SERVICE_ENGINEER_HEADERS)
    )


def adjudicate(
    api: ApiClient,
    warranty_id: str,
    investigation_id: str,
    outcome: str,
    adjudicated_fault_pct: Any = _UNSET,
) -> Dict[str, Any]:
    return get_success_data(
        api.adjudicate_investigation(
            warranty_id,
            investigation_id,
            f.adjudicate_payload(outcome, adjudicated_fault_pct),
            TECHNICAL_SERVICE_ENGINEER_HEADERS,
        )
    )


def drive_to_open_investigation(
    api: ApiClient,
    world: Dict[str, Any],
    *,
    asset_zone: str = "ZONE-1",
    coat_count: int = 1,
    exposure_cents: int = 80_000,
    term_years: int = 5,
    defect_mode: str = "ADHESION_LOSS",
    evidence_notes: str = "blistering at weld seams",
    begin: bool = True,
) -> Dict[str, Any]:
    """Completed work order, issued warranty, filed claim, investigation OPENED.

    When ``begin`` is true the investigation is also moved to
    EVIDENCE_GATHERING, ready for adjudication.
    """
    completion = drive_to_completed_work_order(api, world, asset_zone=asset_zone, coat_count=coat_count)
    warranty = issue_warranty(
        api,
        world["project"]["id"],
        completion["work_order"]["id"],
        term_years=term_years,
        exposure_cents=exposure_cents,
    )
    claim_warranty(
        api, world["project"]["id"], warranty["id"],
        defect_mode=defect_mode, evidence_notes=evidence_notes,
    )
    investigation = read_investigation(api, warranty["id"])
    if begin:
        investigation = begin_evidence(api, warranty["id"], investigation["id"])
    return {
        "completion": completion,
        "warranty": read_warranty(api, warranty["id"]),
        "investigation": investigation,
    }


# ═══ Substitution review ═══════════════════════════════════════════════════

def create_substitution_request(
    api: ApiClient,
    spec_id: str,
    proposed_coating_system_id: str,
    *,
    rationale: str = "lead-time advantage",
    max_review_rounds: Any = _UNSET,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_substitution_request(
            spec_id,
            f.substitution_request_payload(
                proposed_coating_system_id, rationale=rationale, max_review_rounds=max_review_rounds
            ),
            OWNER_REPRESENTATIVE_HEADERS,
        )
    )


def read_substitution_request(api: ApiClient, request_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_substitution_request_flat(request_id, PLATFORM_ADMIN_HEADERS))
