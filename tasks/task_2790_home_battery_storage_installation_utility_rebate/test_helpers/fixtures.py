"""
Scenario builders.

The server is restarted before every test, so each test begins with an empty store
and the logical clock at its epoch. Everything a test needs must therefore be built
from scratch through the public endpoints — there is no seeding and no back door.

The builders below are layered: each one calls the one before it and adds a single
step of the project lifecycle, so a test asks for the state it needs by name and gets
exactly that. They all return a `Project`, a plain record of the identifiers and
header dicts created along the way.

    project = commissioned_project(api)          # bank built, tested and commissioned
    project = pto_granted_project(api)           # ... and permission to operate granted
    project = enrolled_project(api)              # ... and enrolled in dispatch with consent

Every builder asserts its own step succeeded, so a setup break surfaces as a clear
failure inside the builder rather than as a puzzling assertion in the test body.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import ApiClient
from .constants import CLOCK_EPOCH
from .test_users import (
    AHJ_HEADERS,
    REBATE_ADMIN_2_HEADERS,
    REBATE_ADMIN_HEADERS,
    UTILITY_REVIEWER_2_HEADERS,
    UTILITY_REVIEWER_HEADERS,
    WARRANTY_AGENT_HEADERS,
    make_homeowner_headers,
    make_installer_headers,
)
from .types import TestType

Json = Dict[str, Any]

# The instant the canonical project is commissioned at: after the last test window of
# 2026-08-10 has closed, so the four verdicts are all on record.
COMMISSIONING_INSTANT = "2026-08-10T17:00:00Z"


@dataclass
class Project:
    """Everything one project's tests need to keep referring to."""

    installer_id: str = ""
    site_id: str = ""
    load_calculation_id: str = ""
    battery_system_id: str = ""
    permit_id: str = ""
    application_id: str = ""
    test_ids: Dict[str, str] = field(default_factory=dict)
    program_ids: Dict[str, str] = field(default_factory=dict)
    claim_ids: List[str] = field(default_factory=list)
    enrollment_id: str = ""
    event_id: str = ""
    performance_id: str = ""
    clock: str = CLOCK_EPOCH

    @property
    def installer_headers(self) -> Json:
        return make_installer_headers(self.installer_id)

    @property
    def homeowner_headers(self) -> Json:
        return make_homeowner_headers(self.site_id)


# ── The logical clock ────────────────────────────────
def advance_clock(api: ApiClient, project: Project, to_iso8601: str) -> Project:
    """Move the logical clock, from which every deadline and window rule reads."""
    get_success_data(api.set_clock(to_iso8601, headers=project.installer_headers))
    project.clock = to_iso8601
    return project


# ── Reads that tests need before a guarded write ─────
def system_version(api: ApiClient, project: Project) -> int:
    """The bank's current version, required by the concurrency-guarded writes."""
    system = get_success_data(
        api.get_battery_system(project.battery_system_id, headers=project.installer_headers)
    )
    return system["version"]


def event_version(api: ApiClient, project: Project, event_id: Optional[str] = None) -> int:
    """The event's current version, required when calling a battery into it."""
    event = get_success_data(
        api.get_dispatch_event(event_id or project.event_id, headers=UTILITY_REVIEWER_HEADERS)
    )
    return event["version"]


def read_system(api: ApiClient, project: Project) -> Json:
    return get_success_data(
        api.get_battery_system(project.battery_system_id, headers=project.installer_headers)
    )


def read_program(api: ApiClient, program_id: str) -> Json:
    return get_success_data(api.get_program(program_id, headers=REBATE_ADMIN_HEADERS))


def read_claim(api: ApiClient, project: Project, claim_id: str) -> Json:
    return get_success_data(api.get_claim(claim_id, headers=REBATE_ADMIN_HEADERS))


# ── Layer 1: a certified installer ───────────────────
def certified_installer(api: ApiClient, **overrides: Any) -> Project:
    """An installation company certified for all three catalog models."""
    installer = get_success_data(
        api.create_installer(
            factories.installer_payload(**overrides), headers=WARRANTY_AGENT_HEADERS
        ),
        expected_status=201,
    )
    return Project(installer_id=installer["id"])


# ── Layer 2: a premises ──────────────────────────────
def site_for(api: ApiClient, project: Project, **overrides: Any) -> Project:
    """A premises owned by the household whose user id is the site's own id."""
    site = get_success_data(
        api.create_site(
            factories.site_payload(**overrides), headers=project.installer_headers
        ),
        expected_status=201,
    )
    project.site_id = site["id"]
    return project


# ── Layer 3: an approved load calculation ────────────
def approved_load_calculation(
    api: ApiClient, project: Project, payload: Optional[Json] = None
) -> Project:
    """A calculation created, submitted and approved by the electrical authority."""
    body = payload if payload is not None else factories.load_calculation_payload(project.site_id)
    calc = get_success_data(
        api.create_load_calculation(body, headers=project.installer_headers),
        expected_status=201,
    )
    calc_id = calc["id"]
    get_success_data(
        api.submit_load_calculation(calc_id, headers=project.installer_headers)
    )
    get_success_data(
        api.review_load_calculation(
            calc_id, factories.load_calc_approval_payload(), headers=AHJ_HEADERS
        )
    )
    project.load_calculation_id = calc_id
    return project


# ── Layer 4: a bank design ───────────────────────────
def design_draft_project(api: ApiClient, **system_overrides: Any) -> Project:
    """A bank at DESIGN_DRAFT on the build dimension and NOT_APPLIED on the grid."""
    project = certified_installer(api)
    project = site_for(api, project)
    project = approved_load_calculation(api, project)
    system = get_success_data(
        api.create_battery_system(
            factories.battery_system_payload(
                project.site_id,
                project.installer_id,
                project.load_calculation_id,
                **system_overrides
            ),
            headers=project.installer_headers,
        ),
        expected_status=201,
    )
    project.battery_system_id = system["id"]
    return project


def design_locked_project(api: ApiClient, **system_overrides: Any) -> Project:
    """A bank frozen for permitting and interconnection."""
    project = design_draft_project(api, **system_overrides)
    get_success_data(
        api.lock_design(project.battery_system_id, headers=project.installer_headers)
    )
    return project


# ── Layer 5: an issued permit ────────────────────────
def open_permit(api: ApiClient, project: Project, **overrides: Any) -> Project:
    """A permit opened in DRAFT against the design-locked bank."""
    permit = get_success_data(
        api.create_permit(
            factories.permit_payload(project.battery_system_id, **overrides),
            headers=project.installer_headers,
        ),
        expected_status=201,
    )
    project.permit_id = permit["id"]
    return project


def submitted_permit(api: ApiClient, project: Project, **overrides: Any) -> Project:
    project = open_permit(api, project, **overrides)
    get_success_data(api.submit_permit(project.permit_id, headers=project.installer_headers))
    return project


def permit_issued_project(
    api: ApiClient, expires_on: str = "2027-06-30T00:00:00.000Z", **system_overrides: Any
) -> Project:
    """A design-locked bank whose permit has been issued with a validity window."""
    project = design_locked_project(api, **system_overrides)
    project = submitted_permit(api, project)
    get_success_data(
        api.review_permit(
            project.permit_id,
            factories.permit_issue_payload(expires_on=expires_on),
            headers=AHJ_HEADERS,
        )
    )
    return project


# ── Layer 6: an approved interconnection application ──
def open_application(api: ApiClient, project: Project, **overrides: Any) -> Project:
    application = get_success_data(
        api.create_application(
            factories.application_payload(project.battery_system_id, **overrides),
            headers=project.installer_headers,
        ),
        expected_status=201,
    )
    project.application_id = application["id"]
    return project


def submitted_application(api: ApiClient, project: Project, **overrides: Any) -> Project:
    project = open_application(api, project, **overrides)
    get_success_data(
        api.submit_application(project.application_id, headers=project.installer_headers)
    )
    return project


def approved_to_install_project(
    api: ApiClient,
    approved_export_kw: float = 8.0,
    application_overrides: Optional[Json] = None,
    **system_overrides: Any
) -> Project:
    """A permitted bank the utility has cleared for installation."""
    project = permit_issued_project(api, **system_overrides)
    project = submitted_application(api, project, **(application_overrides or {}))
    get_success_data(
        api.review_application(
            project.application_id,
            factories.application_approval_payload(approved_export_kw=approved_export_kw),
            headers=UTILITY_REVIEWER_HEADERS,
        )
    )
    return project


# ── Layer 7: a physically installed bank ─────────────
def installed_project(api: ApiClient, **kwargs: Any) -> Project:
    """A bank recorded as physically installed, awaiting commissioning tests."""
    project = approved_to_install_project(api, **kwargs)
    get_success_data(
        api.mark_installed(project.battery_system_id, headers=project.installer_headers)
    )
    return project


# ── Layer 8: four recorded, passing tests ────────────
def schedule_four_tests(api: ApiClient, project: Project) -> Project:
    """Book all four required verifications in non-conflicting windows."""
    for test_type, window_start, window_end in factories.FOUR_TEST_WINDOWS:
        booked = get_success_data(
            api.create_commissioning_test(
                factories.commissioning_test_payload(
                    project.battery_system_id, test_type, window_start, window_end
                ),
                headers=project.installer_headers,
            ),
            expected_status=201,
        )
        project.test_ids[test_type] = booked["id"]
    return project


def record_four_results(
    api: ApiClient, project: Project, overrides: Optional[Dict[str, Json]] = None
) -> Project:
    """Record the measured figure for each booked test; verdicts are computed."""
    overrides = overrides or {}
    for test_type in TestType.ALL:
        payload = factories.result_payload_for(test_type, **overrides.get(test_type, {}))
        get_success_data(
            api.record_test_result(
                project.test_ids[test_type], payload, headers=project.installer_headers
            )
        )
    return project


def tests_recorded_project(
    api: ApiClient, result_overrides: Optional[Dict[str, Json]] = None, **kwargs: Any
) -> Project:
    """An installed bank with all four verifications booked and recorded."""
    project = installed_project(api, **kwargs)
    project = schedule_four_tests(api, project)
    project = record_four_results(api, project, result_overrides)
    return project


# ── Layer 9: a passed field inspection ───────────────
def pass_inspection(api: ApiClient, project: Project) -> Project:
    get_success_data(
        api.record_inspection_result(
            project.permit_id, factories.inspection_pass_payload(), headers=AHJ_HEADERS
        )
    )
    return project


def inspection_passed_project(api: ApiClient, **kwargs: Any) -> Project:
    """An installed, fully tested bank whose field inspection has passed."""
    project = tests_recorded_project(api, **kwargs)
    return pass_inspection(api, project)


# ── Layer 10: a commissioned bank ────────────────────
def commissioned_project(
    api: ApiClient, commissioning_instant: str = COMMISSIONING_INSTANT, **kwargs: Any
) -> Project:
    """A bank at COMMISSIONED, with verified capacity and a warranty deadline."""
    project = inspection_passed_project(api, **kwargs)
    project = advance_clock(api, project, commissioning_instant)
    get_success_data(
        api.commission(project.battery_system_id, headers=project.installer_headers)
    )
    return project


# ── Layer 11: permission to operate ──────────────────
def grant_pto(api: ApiClient, project: Project) -> Project:
    """Granted by a second reviewer, as segregation of duties requires."""
    get_success_data(
        api.grant_pto(project.application_id, headers=UTILITY_REVIEWER_2_HEADERS)
    )
    return project


def pto_granted_project(api: ApiClient, **kwargs: Any) -> Project:
    """A commissioned bank the utility has given permission to operate."""
    project = commissioned_project(api, **kwargs)
    return grant_pto(api, project)


# ── Layer 12: an active manufacturer warranty ────────
def register_warranty(api: ApiClient, project: Project, **overrides: Any) -> Project:
    get_success_data(
        api.register_warranty(
            project.battery_system_id,
            factories.warranty_registration_payload(**overrides),
            headers=project.installer_headers,
        )
    )
    return project


def warranty_active_project(api: ApiClient, **kwargs: Any) -> Project:
    """An energized bank whose warranty is registered on time and therefore ACTIVE."""
    project = pto_granted_project(api, **kwargs)
    return register_warranty(api, project)


# ── Incentive programs and rebate claims ─────────────
def create_state_program(api: ApiClient, project: Project, **overrides: Any) -> str:
    """The wide-ceiling state capacity program, priority 1."""
    program = get_success_data(
        api.create_program(
            factories.state_program_payload(**overrides), headers=REBATE_ADMIN_HEADERS
        ),
        expected_status=201,
    )
    project.program_ids["state"] = program["id"]
    return program["id"]


def create_utility_program(api: ApiClient, project: Project, **overrides: Any) -> str:
    """A second program at priority 2, for the stacking-waterfall scenarios."""
    program = get_success_data(
        api.create_program(
            factories.utility_program_payload(**overrides), headers=REBATE_ADMIN_HEADERS
        ),
        expected_status=201,
    )
    project.program_ids["utility"] = program["id"]
    return program["id"]


def create_federal_program(api: ApiClient, project: Project, **overrides: Any) -> str:
    program = get_success_data(
        api.create_program(
            factories.federal_program_payload(**overrides), headers=REBATE_ADMIN_HEADERS
        ),
        expected_status=201,
    )
    project.program_ids["federal"] = program["id"]
    return program["id"]


def reserve_claim(api: ApiClient, project: Project, program_id: str, **overrides: Any) -> Json:
    """Reserve an incentive, re-reading the bank's version as the guard requires."""
    claim = get_success_data(
        api.create_claim(
            factories.claim_payload(
                project.battery_system_id,
                program_id,
                system_version(api, project),
                **overrides
            ),
            headers=project.installer_headers,
        ),
        expected_status=201,
    )
    project.claim_ids.append(claim["id"])
    return claim


def submit_claim(api: ApiClient, project: Project, claim_id: str) -> Json:
    return get_success_data(
        api.submit_claim(claim_id, headers=project.installer_headers)
    )


def approve_claim(api: ApiClient, claim_id: str) -> Json:
    """Approved by the first administrator, whose id the payment rule will exclude."""
    return get_success_data(
        api.decide_claim(
            claim_id, factories.claim_approval_payload(), headers=REBATE_ADMIN_HEADERS
        )
    )


def pay_claim(api: ApiClient, claim_id: str) -> Json:
    """Paid by a second administrator, as segregation of duties requires."""
    return get_success_data(api.pay_claim(claim_id, headers=REBATE_ADMIN_2_HEADERS))


def paid_claim(api: ApiClient, project: Project, program_id: str, **overrides: Any) -> Json:
    """A claim taken all the way from reservation to disbursement."""
    claim = reserve_claim(api, project, program_id, **overrides)
    submit_claim(api, project, claim["id"])
    approve_claim(api, claim["id"])
    return pay_claim(api, claim["id"])


def claimable_project(api: ApiClient, **kwargs: Any) -> Project:
    """An energized, warranted bank with the state program funded and ready.

    This is the state a claim needs: the bank is COMMISSIONED and PTO_GRANTED with an
    ACTIVE warranty, so a reservation can be submitted, adjudicated and paid.
    """
    project = warranty_active_project(api, **kwargs)
    create_state_program(api, project)
    return project


# ── BYOD enrollment ──────────────────────────────────
def create_enrollment(api: ApiClient, project: Project, **overrides: Any) -> Json:
    enrollment = get_success_data(
        api.create_enrollment(
            factories.enrollment_payload(project.battery_system_id, **overrides),
            headers=project.installer_headers,
        ),
        expected_status=201,
    )
    project.enrollment_id = enrollment["id"]
    return enrollment


def consent_enrollment(api: ApiClient, project: Project) -> Json:
    """Only the household itself can activate its own enrollment."""
    return get_success_data(
        api.consent_enrollment(project.enrollment_id, headers=project.homeowner_headers)
    )


def pending_consent_project(api: ApiClient, **kwargs: Any) -> Project:
    """An enrollment filed by the installer, awaiting the household's consent."""
    project = pto_granted_project(api, **kwargs)
    create_enrollment(api, project)
    return project


def enrolled_project(api: ApiClient, **kwargs: Any) -> Project:
    """A consented, active enrollment ready to be called into dispatch."""
    project = pending_consent_project(api, **kwargs)
    consent_enrollment(api, project)
    return project


# ── Dispatch events, participations and settlement ───
def create_event(api: ApiClient, project: Project, **overrides: Any) -> Json:
    event = get_success_data(
        api.create_dispatch_event(
            factories.dispatch_event_payload(**overrides), headers=UTILITY_REVIEWER_HEADERS
        ),
        expected_status=201,
    )
    project.event_id = event["id"]
    return event


def call_into_event(
    api: ApiClient,
    project: Project,
    event_id: Optional[str] = None,
    enrollment_id: Optional[str] = None,
) -> Json:
    """Call a battery into a scheduled event, guarded on the event's version."""
    target_event = event_id or project.event_id
    performance = get_success_data(
        api.create_participation(
            target_event,
            factories.participation_payload(
                enrollment_id or project.enrollment_id,
                event_version(api, project, target_event),
            ),
            headers=UTILITY_REVIEWER_HEADERS,
        ),
        expected_status=201,
    )
    project.performance_id = performance["id"]
    return performance


def event_with_participation(api: ApiClient, **kwargs: Any) -> Project:
    """An enrolled battery called into a scheduled two-hour economic event."""
    project = enrolled_project(api, **kwargs)
    create_event(api, project)
    call_into_event(api, project)
    return project


def report_delivery(
    api: ApiClient, project: Project, delivered_kwh: float, performance_id: Optional[str] = None
) -> Json:
    """Report metered energy; the window must already have closed on the clock."""
    return get_success_data(
        api.report_delivery(
            performance_id or project.performance_id,
            factories.delivery_payload(delivered_kwh),
            headers=UTILITY_REVIEWER_HEADERS,
        )
    )


def settle_event(api: ApiClient, project: Project, event_id: Optional[str] = None) -> Json:
    return get_success_data(
        api.settle_event(event_id or project.event_id, headers=UTILITY_REVIEWER_HEADERS)
    )
