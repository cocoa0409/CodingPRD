"""Composite fixtures that walk the API to a wanted state.

Every test starts against an empty deployment, so each test has to build the
world it needs from scratch through the public API only. Helpers are organised
from the simplest to the most far-reaching:

  Tier 1  single-resource creation and reads (DCA, vendor, clock)
  Tier 2  entity hierarchies (SAR/RAI, vendor/qualification, pipeline/license)
  Tier 3  lifecycle shortcuts (adequate test program, certifiable DCA, ESP in
          HEARINGS, ready-for-advance SAR)
  Tier 5  terminal / certification states (certified DCA with LOCKED
          subscriptions and a cost-share agreement)

Setup calls use the lenient success reader, so a failure inside a fixture is
reported as a setup failure rather than as a mysterious assertion error. Any
ownership-gated utility call uses ``make_utility_headers(utility_id)`` so the
entity-backed identity always matches the commitment's ``utility_id``.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from . import factories as f
from .test_users import TEST_USERS, make_utility_headers

APPLICANT = TEST_USERS["dca_applicant"]
REVIEWER = TEST_USERS["nrc_reviewer"]
REVIEWER_2 = TEST_USERS["nrc_reviewer_2"]
DOE = TEST_USERS["doe_program"]
SCM = TEST_USERS["supply_chain_manager"]
AUDITOR = TEST_USERS["vendor_auditor"]
PERMIT_APPLICANT = TEST_USERS["site_permit_applicant"]
INTERVENOR = TEST_USERS["public_intervenor"]
COORDINATOR = TEST_USERS["workforce_coordinator"]


# ═══ Tier 1: single resources, reads, and the clock ═══════════════════════


def set_clock(api: ApiClient, to_iso8601: str) -> None:
    get_success_data(api.set_clock(f.clock_payload(to_iso8601), DOE))


def create_dca(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_dca(f.dca_payload(**overrides), APPLICANT))


def read_dca(api: ApiClient, dca_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_dca(dca_id, APPLICANT))


def create_sar(api: ApiClient, dca_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_sar(dca_id, f.sar_payload(**overrides), APPLICANT))


def read_sar(api: ApiClient, sar_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_sar(sar_id, APPLICANT))


def create_rai(
    api: ApiClient,
    dca_id: str,
    reviewer_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    headers = reviewer_headers if reviewer_headers is not None else REVIEWER
    return get_success_data(api.create_rai(dca_id, f.rai_payload(**overrides), headers))


def read_rai(api: ApiClient, rai_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_rai(rai_id, APPLICANT))


def create_test_program(api: ApiClient, dca_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_test_program(dca_id, f.test_program_payload(**overrides), APPLICANT)
    )


def read_test_program(api: ApiClient, program_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_test_program(program_id, APPLICANT))


def create_vendor(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_vendor(f.vendor_payload(**overrides), SCM))


def read_vendor(api: ApiClient, vendor_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_vendor(vendor_id, SCM))


def create_qualification(api: ApiClient, vendor_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_qualification(vendor_id, f.qualification_payload(**overrides), AUDITOR)
    )


def read_qualification(api: ApiClient, qual_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_qualification(qual_id, AUDITOR))


def create_component_lot(api: ApiClient, vendor_id: str, program_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_component_lot(f.component_lot_payload(vendor_id, program_id, **overrides), SCM)
    )


def read_component_lot(api: ApiClient, lot_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_component_lot(lot_id, SCM))


def create_site_permit(api: ApiClient, permit_type: str, dca_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_site_permit(f.site_permit_payload(permit_type, dca_id, **overrides), PERMIT_APPLICANT)
    )


def read_site_permit(api: ApiClient, permit_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_site_permit(permit_id, PERMIT_APPLICANT))


def create_hearing(api: ApiClient, permit_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.schedule_hearing(permit_id, f.hearing_payload(**overrides), PERMIT_APPLICANT)
    )


def read_hearing(api: ApiClient, hearing_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_hearing(hearing_id, PERMIT_APPLICANT))


def create_cost_share_agreement(
    api: ApiClient, dca_id: str, total_cost_usd: int, gov_contribution_usd: int
) -> Dict[str, Any]:
    return get_success_data(
        api.create_cost_share_agreement(
            f.cost_share_agreement_payload(dca_id, total_cost_usd, gov_contribution_usd), DOE
        )
    )


def read_cost_share_agreement(api: ApiClient, csa_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_cost_share_agreement(csa_id, DOE))


def create_subscription(api: ApiClient, dca_id: str, utility_id: str, committed_mw: int, **overrides: Any) -> Dict[str, Any]:
    """Create a DRAFT commitment; the caller identity is the utility itself."""
    return get_success_data(
        api.create_subscription(
            dca_id,
            f.subscription_payload(utility_id, committed_mw, **overrides),
            make_utility_headers(utility_id),
        )
    )


def execute_subscription(api: ApiClient, sub_id: str, utility_id: str) -> Dict[str, Any]:
    return get_success_data(api.execute_subscription(sub_id, make_utility_headers(utility_id)))


def withdraw_subscription(api: ApiClient, sub_id: str, utility_id: str, expected_csa_version: int) -> Dict[str, Any]:
    return get_success_data(
        api.withdraw_subscription(
            sub_id,
            f.subscription_withdraw_payload(expected_csa_version),
            make_utility_headers(utility_id),
        )
    )


def read_subscription(api: ApiClient, sub_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_subscription(sub_id, DOE))


def create_pipeline(api: ApiClient, dca_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_workforce_pipeline(dca_id, f.workforce_pipeline_payload(**overrides), COORDINATOR)
    )


def read_pipeline(api: ApiClient, pipeline_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_workforce_pipeline(pipeline_id, COORDINATOR))


def enroll_license(api: ApiClient, pipeline_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.enroll_operator(pipeline_id, f.operator_license_payload(**overrides), COORDINATOR)
    )


def read_license(api: ApiClient, license_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_operator_license(license_id, COORDINATOR))


# ═══ Tier 2: entity hierarchies ═══════════════════════════════════════════


def create_sar_under_review(api: ApiClient, dca_id: str, **sar_overrides: Any) -> Dict[str, Any]:
    """A section opened for review (UNDER_REVIEW)."""
    sar = create_sar(api, dca_id, **sar_overrides)
    return get_success_data(api.review_sar(sar["id"], REVIEWER))


def create_responded_rai(
    api: ApiClient,
    dca_id: str,
    reviewer_headers: Optional[Dict[str, str]] = None,
    response_text: str = "Response attached.",
    **rai_overrides: Any,
) -> Dict[str, Any]:
    """An RAI created by the given reviewer and answered by the applicant."""
    rai = create_rai(api, dca_id, reviewer_headers=reviewer_headers, **rai_overrides)
    return get_success_data(api.respond_rai(rai["id"], f.rai_response_payload(response_text), APPLICANT))


def create_adequate_program(api: ApiClient, dca_id: str, **program_overrides: Any) -> Dict[str, Any]:
    """A test program driven PLANNED -> IN_PROGRESS -> ADEQUATE."""
    program_overrides.setdefault("required_tests", 1)
    program = create_test_program(api, dca_id, **program_overrides)
    get_success_data(api.start_test_program(program["id"], APPLICANT))
    get_success_data(
        api.record_test_result(
            program["id"], f.test_result_payload(outcome="PASS", run_at="2026-09-01T00:00:00Z"), APPLICANT
        )
    )
    return read_test_program(api, program["id"])


def create_qualified_vendor(api: ApiClient, **vendor_overrides: Any) -> Dict[str, Any]:
    """A vendor whose latest active qualification is FULLY_QUALIFIED."""
    vendor = create_vendor(api, **vendor_overrides)
    qual = create_qualification(api, vendor["id"], defects_found=0)
    get_success_data(api.complete_audit(vendor["id"], qual["id"], AUDITOR))
    return read_vendor(api, vendor["id"])


def create_conditional_vendor(
    api: ApiClient, defects_found: int = 1, **vendor_overrides: Any
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A vendor plus its CONDITIONALLY_QUALIFIED qualification."""
    vendor = create_vendor(api, **vendor_overrides)
    qual = create_qualification(api, vendor["id"], defects_found=defects_found)
    qual = get_success_data(api.complete_audit(vendor["id"], qual["id"], AUDITOR))
    return vendor, qual


def create_staffed_pipeline(api: ApiClient, dca_id: str, **overrides: Any) -> Dict[str, Any]:
    """A pipeline driven ENROLLING -> TRAINING -> GRADUATING -> STAFFED."""
    overrides.setdefault("required_operators", 1)
    pipeline = create_pipeline(api, dca_id, **overrides)
    get_success_data(api.start_training(pipeline["id"], COORDINATOR))
    lic = enroll_license(api, pipeline["id"])
    get_success_data(api.license_operator(lic["id"], COORDINATOR))
    get_success_data(api.advance_pipeline(pipeline["id"], COORDINATOR))
    return read_pipeline(api, pipeline["id"])


# ═══ Tier 3: lifecycle shortcuts ══════════════════════════════════════════


def create_certifiable_dca(api: ApiClient, **dca_overrides: Any) -> Dict[str, Any]:
    """An application in ADVANCED_REVIEW with an adequate test program and a
    staffed workforce pipeline - every certification precondition except the
    subscription lock, which the caller adds before calling certify."""
    dca = create_dca(api, **dca_overrides)
    sar = create_sar_under_review(api, dca["id"])
    get_success_data(api.advance_sar(sar["id"], REVIEWER))
    get_success_data(api.enter_safety_review(dca["id"], REVIEWER))
    get_success_data(api.advance_phase(dca["id"], REVIEWER))
    create_adequate_program(api, dca["id"])
    create_staffed_pipeline(api, dca["id"])
    return read_dca(api, dca["id"])


def create_certified_dca(
    api: ApiClient,
    subscriptions: Sequence[Tuple[str, int]] = (("u1", 50),),
    csa_total_cost_usd: int = 1000,
    csa_gov_contribution_usd: int = 0,
    **dca_overrides: Any,
) -> Dict[str, Any]:
    """A certified application with one cost-share agreement and the given
    (utility_id, committed_mw) subscriptions locked by the certify cascade.

    Returns {"dca", "csa", "subscriptions"}. The certification walk runs under
    the caller's current clock position.
    """
    dca = create_dca(api, **dca_overrides)
    csa = create_cost_share_agreement(
        api, dca["id"], csa_total_cost_usd, csa_gov_contribution_usd
    )
    sar = create_sar_under_review(api, dca["id"])
    get_success_data(api.advance_sar(sar["id"], REVIEWER))
    get_success_data(api.enter_safety_review(dca["id"], REVIEWER))
    get_success_data(api.advance_phase(dca["id"], REVIEWER))
    create_adequate_program(api, dca["id"])
    create_staffed_pipeline(api, dca["id"])
    subs: List[Dict[str, Any]] = []
    for utility_id, committed_mw in subscriptions:
        sub = create_subscription(api, dca["id"], utility_id, committed_mw)
        subs.append(execute_subscription(api, sub["id"], utility_id))
    get_success_data(api.certify_dca(dca["id"], REVIEWER))
    return {
        "dca": read_dca(api, dca["id"]),
        "csa": read_cost_share_agreement(api, csa["id"]),
        "subscriptions": [read_subscription(api, s["id"]) for s in subs],
    }


def create_sar_ready_with_responded_rai(
    api: ApiClient, **dca_overrides: Any
) -> Dict[str, Any]:
    """A DCA whose section is READY_FOR_PHASE_ADVANCE, with one accepted RAI
    behind it and a second RAI sitting in RESPONSE_SUBMITTED - one reopen away
    from regressing the section.

    Returns {"dca", "sar", "rai"} where "rai" is the responded one.
    """
    dca = create_dca(api, **dca_overrides)
    sar = create_sar_under_review(api, dca["id"])
    section = sar["section_code"]
    first = create_responded_rai(api, dca["id"], sar_section_code=section)
    get_success_data(api.accept_rai(first["id"], REVIEWER_2))
    get_success_data(api.advance_sar(sar["id"], REVIEWER))
    second = create_responded_rai(api, dca["id"], sar_section_code=section, question_text="Follow-up question")
    return {"dca": dca, "sar": read_sar(api, sar["id"]), "rai": second}


def create_permit_in_hearings(
    api: ApiClient, hearing_at: Optional[str] = None, **dca_overrides: Any
) -> Dict[str, Any]:
    """An ESP permit advanced to HEARINGS. When ``hearing_at`` is given, one
    hearing is scheduled at that instant. Returns {"dca", "permit"} plus
    "hearing" when one was scheduled."""
    dca = create_dca(api, **dca_overrides)
    permit = create_site_permit(api, "ESP", dca["id"])
    get_success_data(api.submit_site_permit(permit["id"], PERMIT_APPLICANT))
    get_success_data(api.advance_to_hearings(permit["id"], PERMIT_APPLICANT))
    result: Dict[str, Any] = {"dca": dca, "permit": read_site_permit(api, permit["id"])}
    if hearing_at is not None:
        result["hearing"] = create_hearing(api, permit["id"], scheduled_at=hearing_at)
    return result
