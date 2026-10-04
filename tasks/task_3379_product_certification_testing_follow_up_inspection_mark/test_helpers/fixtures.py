"""Composite setup helpers for the Product Certification Followup API.

The harness restarts the API server before every test, so each test starts
against an empty database and must build the world it needs through the public
API. These helpers do that walking and return the created resources (and the
context dicts that accumulate them) so tests can focus on assertions.

Layers, simplest to most far-reaching:

  Tier 1  primitives - one API call each (create standard, open project, ...)
  Tier 2  the world: standard + manufacturer + factory
  Tier 3  project progression: open -> frozen record -> TESTING -> EVALUATION
          -> APPROVED (with the certification fetched back)
  Tier 4  regime/threshold targeting: drive a factory to PROBATION, licenses
          under a chosen quota variant
  Tier 5  terminal/compliance states: published withdrawal notices, approved
          substitutions, field evaluations

Setup calls use the lenient success reader, so a failure inside a fixture is
reported as a setup failure rather than as a confusing assertion error.

Identity threading: every ownership-gated call uses
``make_manufacturer_rep_headers(manufacturer["id"])`` or
``make_ahj_authority_headers(jurisdiction["id"])`` built from the entity the
fixture itself created - never a shared placeholder header set.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .api_client import ApiClient
from .constants import BASE_CLOCK_ISO
from .test_users import (
    DEFAULT_ENGINEER_ID,
    DEFAULT_INSPECTOR_ID,
    DEFAULT_REVIEWER_ID,
    TEST_USERS,
    make_ahj_authority_headers,
    make_manufacturer_rep_headers,
    make_certification_reviewer_headers,
    make_factory_inspector_headers,
    make_test_engineer_headers,
)

__all__ = [
    # Tier 1: primitives
    "set_clock",
    "create_standard",
    "create_jurisdiction",
    "create_manufacturer",
    "suspend_manufacturer",
    "create_factory",
    "open_project",
    "freeze_construction_record",
    "submit_sample",
    "triage_sample",
    "accept_sample",
    "reject_sample",
    "submit_and_accept_sample",
    "record_result",
    "record_results",
    "record_canonical_passing_results",
    "decide_project",
    "get_certification_for_project",
    "refresh_project",
    "refresh_certification",
    "refresh_factory",
    "refresh_mark_license",
    "create_substitution_request",
    "decide_substitution",
    "implement_substitution",
    "schedule_inspection",
    "complete_inspection",
    "schedule_and_complete_inspection",
    "void_inspection",
    "suspend_certification",
    "reinstate_certification",
    "create_mark_license",
    "issue_label_batch",
    "void_label_batch",
    "create_field_evaluation",
    "evaluate_field_evaluation",
    "decide_acceptance",
    "create_withdrawal_notice",
    "publish_withdrawal_notice",
    # Tier 2-5: composites
    "setup_world",
    "setup_open_project",
    "setup_project_with_record",
    "setup_project_in_testing",
    "setup_project_in_evaluation",
    "setup_certified",
    "setup_certified_with_license",
    "drive_factory_to_probation",
    "setup_probation_certified_with_license",
    "setup_approved_substitution",
    "setup_published_withdrawal_notice",
    "setup_field_evaluation_world",
]

ADMIN_HEADERS = TEST_USERS["certification_body_admin_headers"]
OFFICER_HEADERS = TEST_USERS["compliance_officer_headers"]


# ═══════════════════════════════════════════════════════════════════════════
# Tier 1: primitives - one API call each
# ═══════════════════════════════════════════════════════════════════════════

def set_clock(api: ApiClient, to_iso8601: str = BASE_CLOCK_ISO) -> Dict[str, Any]:
    """Advance the logical clock (running the time sweep); returns {current_utc}."""
    return get_success_data(api.set_clock(f.clock_payload(to_iso8601), ADMIN_HEADERS))


def create_standard(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_standard(f.standard_payload(**overrides), ADMIN_HEADERS))


def create_jurisdiction(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_jurisdiction(f.jurisdiction_payload(**overrides), ADMIN_HEADERS)
    )


def create_manufacturer(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_manufacturer(f.manufacturer_payload(**overrides), ADMIN_HEADERS)
    )


def suspend_manufacturer(
    api: ApiClient, manufacturer_id: str, reason: str = f.DEFAULTS["SUSPEND_REASON"]
) -> Dict[str, Any]:
    return get_success_data(
        api.suspend_manufacturer(
            manufacturer_id, f.suspend_manufacturer_payload(reason), OFFICER_HEADERS
        )
    )


def create_factory(api: ApiClient, manufacturer_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_factory(manufacturer_id, f.factory_payload(**overrides), ADMIN_HEADERS)
    )


def open_project(
    api: ApiClient,
    manufacturer_id: str,
    factory_id: str,
    standard_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open a certification project; manufacturer_id is set from X-User-ID."""
    return get_success_data(
        api.create_project(
            f.project_payload(factory_id, standard_id, **overrides),
            make_manufacturer_rep_headers(manufacturer_id),
        )
    )


def freeze_construction_record(
    api: ApiClient,
    project: Dict[str, Any],
    manufacturer_id: Optional[str] = None,
    components: Optional[List[Dict[str, Any]]] = None,
    expected_project_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Create a FROZEN construction-record revision (superseding any prior one).

    ``expected_project_version`` defaults to the version on the passed project
    dict - pass a freshly read project, or pass the version explicitly.
    """
    mfr_id = manufacturer_id or project["manufacturer_id"]
    version = expected_project_version if expected_project_version is not None else project["version"]
    return get_success_data(
        api.create_construction_record(
            project["id"],
            f.construction_record_payload(version, components=components),
            make_manufacturer_rep_headers(mfr_id),
        )
    )


def submit_sample(
    api: ApiClient, project_id: str, manufacturer_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.submit_sample(
            project_id,
            f.sample_payload(**overrides),
            make_manufacturer_rep_headers(manufacturer_id),
        )
    )


def triage_sample(
    api: ApiClient,
    sample_id: str,
    decision: str = "ACCEPT",
    engineer_id: str = DEFAULT_ENGINEER_ID,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.triage_sample(
            sample_id,
            f.triage_payload(decision, **overrides),
            make_test_engineer_headers(engineer_id),
        )
    )


def accept_sample(api: ApiClient, sample_id: str, engineer_id: str = DEFAULT_ENGINEER_ID) -> Dict[str, Any]:
    return triage_sample(api, sample_id, "ACCEPT", engineer_id)


def reject_sample(
    api: ApiClient, sample_id: str, engineer_id: str = DEFAULT_ENGINEER_ID, note: Optional[str] = None
) -> Dict[str, Any]:
    overrides: Dict[str, Any] = {}
    if note is not None:
        overrides["note"] = note
    return triage_sample(api, sample_id, "REJECT", engineer_id, **overrides)


def submit_and_accept_sample(
    api: ApiClient,
    project_id: str,
    manufacturer_id: str,
    engineer_id: str = DEFAULT_ENGINEER_ID,
    **overrides: Any,
) -> Dict[str, Any]:
    """Submit a sample and triage it ACCEPTED. Returns the accepted sample."""
    sample = submit_sample(api, project_id, manufacturer_id, **overrides)
    return accept_sample(api, sample["id"], engineer_id)


def record_result(
    api: ApiClient,
    sample_id: str,
    protocol_code: str,
    measured_value: Any,
    engineer_id: str = DEFAULT_ENGINEER_ID,
) -> Dict[str, Any]:
    """Record one protocol result; returns the updated sample."""
    return get_success_data(
        api.record_result(
            sample_id,
            f.result_payload(protocol_code, measured_value),
            make_test_engineer_headers(engineer_id),
        )
    )


def record_results(
    api: ApiClient,
    sample_id: str,
    results: Sequence[Tuple[str, Any]],
    engineer_id: str = DEFAULT_ENGINEER_ID,
) -> Dict[str, Any]:
    """Record several ``(protocol_code, measured_value)`` results on one sample."""
    sample: Dict[str, Any] = {}
    for protocol_code, measured_value in results:
        sample = record_result(api, sample_id, protocol_code, measured_value, engineer_id)
    return sample


def record_canonical_passing_results(
    api: ApiClient, sample_id: str, engineer_id: str = DEFAULT_ENGINEER_ID
) -> Dict[str, Any]:
    """P-SAFE 60 (PASS) and P-TEMP 110 (PASS) - the results that satisfy every
    mandatory protocol of the canonical standard."""
    return record_results(api, sample_id, [("P-SAFE", 60), ("P-TEMP", 110)], engineer_id)


def decide_project(
    api: ApiClient,
    project_id: str,
    outcome: str = "APPROVED",
    reviewer_id: str = DEFAULT_REVIEWER_ID,
    validity_months: Optional[int] = None,
    permitted_variations: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Render a certification decision; returns the updated project."""
    overrides: Dict[str, Any] = {}
    if validity_months is not None:
        overrides["validity_months"] = validity_months
    if permitted_variations is not None:
        overrides["permitted_variations"] = permitted_variations
    return get_success_data(
        api.decide_project(
            project_id,
            f.decide_project_payload(outcome, **overrides),
            make_certification_reviewer_headers(reviewer_id),
        )
    )


def get_certification_for_project(api: ApiClient, project_id: str) -> Dict[str, Any]:
    """Fetch the single certification an approved project produced."""
    response = api.list_certifications(OFFICER_HEADERS, params={"project_id": project_id})
    data, _meta = validate_paginated(response)
    assert len(data) == 1, (
        f"Setup failed: expected exactly one certification for project {project_id}, "
        f"found {len(data)}"
    )
    return data[0]


def refresh_project(api: ApiClient, project_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_project(project_id, OFFICER_HEADERS))


def refresh_certification(api: ApiClient, certification_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_certification(certification_id, OFFICER_HEADERS))


def refresh_factory(api: ApiClient, factory_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_factory(factory_id, OFFICER_HEADERS))


def refresh_mark_license(api: ApiClient, license_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_mark_license(license_id, OFFICER_HEADERS))


# ── Substitutions ──────────────────────────────────────────────────────────

def create_substitution_request(
    api: ApiClient, certification_id: str, manufacturer_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_substitution_request(
            certification_id,
            f.substitution_request_payload(**overrides),
            make_manufacturer_rep_headers(manufacturer_id),
        )
    )


def decide_substitution(
    api: ApiClient,
    request_id: str,
    outcome: str = "APPROVE",
    reviewer_id: str = DEFAULT_REVIEWER_ID,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.decide_substitution_request(
            request_id,
            f.substitution_decide_payload(outcome, **overrides),
            make_certification_reviewer_headers(reviewer_id),
        )
    )


def implement_substitution(
    api: ApiClient,
    request_id: str,
    manufacturer_id: str,
    expected_certification_version: int,
) -> Dict[str, Any]:
    return get_success_data(
        api.implement_substitution_request(
            request_id,
            f.substitution_implement_payload(expected_certification_version),
            make_manufacturer_rep_headers(manufacturer_id),
        )
    )


# ── Follow-up inspections ──────────────────────────────────────────────────

def schedule_inspection(
    api: ApiClient,
    factory_id: str,
    scheduled_for: str = BASE_CLOCK_ISO,
    inspector_id: str = DEFAULT_INSPECTOR_ID,
) -> Dict[str, Any]:
    """Schedule a follow-up inspection. ``scheduled_for`` must be at or after
    the current logical time and at least 25 days away from every other
    non-VOIDED inspection of the same factory."""
    return get_success_data(
        api.schedule_inspection(
            factory_id,
            f.inspection_payload(scheduled_for),
            make_factory_inspector_headers(inspector_id),
        )
    )


def complete_inspection(
    api: ApiClient,
    inspection_id: str,
    findings: Optional[List[Dict[str, Any]]] = None,
    inspector_id: str = DEFAULT_INSPECTOR_ID,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.complete_inspection(
            inspection_id,
            f.complete_inspection_payload(findings, **overrides),
            make_factory_inspector_headers(inspector_id),
        )
    )


def schedule_and_complete_inspection(
    api: ApiClient,
    factory_id: str,
    findings: Optional[List[Dict[str, Any]]] = None,
    scheduled_for: str = BASE_CLOCK_ISO,
    inspector_id: str = DEFAULT_INSPECTOR_ID,
) -> Dict[str, Any]:
    """Schedule then immediately complete an inspection. Returns the COMPLETED one."""
    inspection = schedule_inspection(api, factory_id, scheduled_for, inspector_id)
    return complete_inspection(api, inspection["id"], findings, inspector_id)


def void_inspection(
    api: ApiClient, inspection_id: str, reason: str = f.DEFAULTS["VOID_REASON"]
) -> Dict[str, Any]:
    return get_success_data(
        api.void_inspection(inspection_id, f.void_inspection_payload(reason), OFFICER_HEADERS)
    )


# ── Certification compliance actions ───────────────────────────────────────

def suspend_certification(
    api: ApiClient, certification_id: str, reason: str = f.DEFAULTS["SUSPEND_REASON"]
) -> Dict[str, Any]:
    return get_success_data(
        api.suspend_certification(
            certification_id, f.suspend_certification_payload(reason), OFFICER_HEADERS
        )
    )


def reinstate_certification(api: ApiClient, certification_id: str) -> Dict[str, Any]:
    return get_success_data(api.reinstate_certification(certification_id, OFFICER_HEADERS))


# ── Mark licenses and label batches ────────────────────────────────────────

def create_mark_license(
    api: ApiClient, certification_id: str, manufacturer_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_mark_license(
            certification_id,
            f.mark_license_payload(**overrides),
            make_manufacturer_rep_headers(manufacturer_id),
        )
    )


def issue_label_batch(
    api: ApiClient, license_id: str, manufacturer_id: str, quantity: int = f.DEFAULTS["BATCH_QUANTITY"]
) -> Dict[str, Any]:
    return get_success_data(
        api.issue_label_batch(
            license_id,
            f.label_batch_payload(quantity),
            make_manufacturer_rep_headers(manufacturer_id),
        )
    )


def void_label_batch(
    api: ApiClient, batch_id: str, manufacturer_id: str, reason: str = f.DEFAULTS["VOID_REASON"]
) -> Dict[str, Any]:
    return get_success_data(
        api.void_label_batch(
            batch_id,
            f.void_label_batch_payload(reason),
            make_manufacturer_rep_headers(manufacturer_id),
        )
    )


# ── Field evaluations ──────────────────────────────────────────────────────

def create_field_evaluation(
    api: ApiClient,
    manufacturer_id: str,
    standard_id: str,
    evaluating_jurisdiction_id: str,
    site_jurisdiction_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_field_evaluation(
            f.field_evaluation_payload(
                standard_id, evaluating_jurisdiction_id, site_jurisdiction_id, **overrides
            ),
            make_manufacturer_rep_headers(manufacturer_id),
        )
    )


def evaluate_field_evaluation(
    api: ApiClient,
    evaluation_id: str,
    outcome: str = "PASS",
    engineer_id: str = DEFAULT_ENGINEER_ID,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.evaluate_field_evaluation(
            evaluation_id,
            f.evaluate_payload(outcome, **overrides),
            make_test_engineer_headers(engineer_id),
        )
    )


def decide_acceptance(
    api: ApiClient,
    evaluation_id: str,
    site_jurisdiction_id: str,
    decision: str = "ACCEPT",
    **overrides: Any,
) -> Dict[str, Any]:
    """AHJ acceptance decision. ``site_jurisdiction_id`` must be the id of the
    field evaluation's site jurisdiction - the AHJ role is entity-backed."""
    return get_success_data(
        api.decide_field_evaluation_acceptance(
            evaluation_id,
            f.acceptance_decision_payload(decision, **overrides),
            make_ahj_authority_headers(site_jurisdiction_id),
        )
    )


# ── Withdrawal notices ─────────────────────────────────────────────────────

def create_withdrawal_notice(
    api: ApiClient, certification_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_withdrawal_notice(
            certification_id, f.withdrawal_notice_payload(**overrides), OFFICER_HEADERS
        )
    )


def publish_withdrawal_notice(api: ApiClient, notice_id: str) -> Dict[str, Any]:
    return get_success_data(api.publish_withdrawal_notice(notice_id, OFFICER_HEADERS))


# ═══════════════════════════════════════════════════════════════════════════
# Tier 2: the world - standard + manufacturer + factory
# ═══════════════════════════════════════════════════════════════════════════

def setup_world(
    api: ApiClient,
    *,
    clock_iso: str = BASE_CLOCK_ISO,
    set_clock_first: bool = True,
    standard: Optional[Dict[str, Any]] = None,
    manufacturer: Optional[Dict[str, Any]] = None,
    factory: Optional[Dict[str, Any]] = None,
    standard_overrides: Optional[Dict[str, Any]] = None,
    manufacturer_overrides: Optional[Dict[str, Any]] = None,
    factory_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Canonical reference data: an ACTIVE standard (window already open), a
    SMALL-tier manufacturer, and its factory. Pass existing entities to reuse
    them (e.g. a second manufacturer against the same standard)."""
    if set_clock_first:
        set_clock(api, clock_iso)
    standard = standard or create_standard(api, **(standard_overrides or {}))
    manufacturer = manufacturer or create_manufacturer(api, **(manufacturer_overrides or {}))
    factory = factory or create_factory(api, manufacturer["id"], **(factory_overrides or {}))
    return {"standard": standard, "manufacturer": manufacturer, "factory": factory}


# ═══════════════════════════════════════════════════════════════════════════
# Tier 3: project progression
# ═══════════════════════════════════════════════════════════════════════════

def setup_open_project(
    api: ApiClient,
    world: Optional[Dict[str, Any]] = None,
    *,
    project_overrides: Optional[Dict[str, Any]] = None,
    **world_kwargs: Any,
) -> Dict[str, Any]:
    """World + a freshly opened project in STANDARD_SELECTED."""
    ctx = dict(world) if world is not None else setup_world(api, **world_kwargs)
    ctx["project"] = open_project(
        api,
        ctx["manufacturer"]["id"],
        ctx["factory"]["id"],
        ctx["standard"]["id"],
        **(project_overrides or {}),
    )
    return ctx


def setup_project_with_record(
    api: ApiClient,
    world: Optional[Dict[str, Any]] = None,
    *,
    components: Optional[List[Dict[str, Any]]] = None,
    project_overrides: Optional[Dict[str, Any]] = None,
    **world_kwargs: Any,
) -> Dict[str, Any]:
    """World + project + one FROZEN construction-record revision. The project
    in the returned context is refreshed afterwards (the write bumps its
    version)."""
    ctx = setup_open_project(api, world, project_overrides=project_overrides, **world_kwargs)
    ctx["construction_record"] = freeze_construction_record(
        api, ctx["project"], components=components
    )
    ctx["project"] = refresh_project(api, ctx["project"]["id"])
    return ctx


def setup_project_in_testing(
    api: ApiClient,
    world: Optional[Dict[str, Any]] = None,
    *,
    sample_overrides: Optional[Dict[str, Any]] = None,
    engineer_id: str = DEFAULT_ENGINEER_ID,
    **kwargs: Any,
) -> Dict[str, Any]:
    """World + frozen record + one ACCEPTED sample; the project has moved from
    STANDARD_SELECTED to TESTING."""
    ctx = setup_project_with_record(api, world, **kwargs)
    ctx["sample"] = submit_and_accept_sample(
        api,
        ctx["project"]["id"],
        ctx["manufacturer"]["id"],
        engineer_id=engineer_id,
        **(sample_overrides or {}),
    )
    ctx["project"] = refresh_project(api, ctx["project"]["id"])
    return ctx


def setup_project_in_evaluation(
    api: ApiClient,
    world: Optional[Dict[str, Any]] = None,
    *,
    results: Optional[Sequence[Tuple[str, Any]]] = None,
    engineer_id: str = DEFAULT_ENGINEER_ID,
    **kwargs: Any,
) -> Dict[str, Any]:
    """World + frozen record + accepted sample + results for every mandatory
    protocol of the canonical standard, so the project has auto-advanced to
    EVALUATION and snapshotted its fee.

    ``results`` defaults to P-SAFE 60 and P-TEMP 110 (both PASS on an INTACT
    sample); pass explicit ``(protocol_code, measured_value)`` pairs to steer
    outcomes. The sample in the returned context is refreshed afterwards.
    """
    ctx = setup_project_in_testing(api, world, engineer_id=engineer_id, **kwargs)
    if results is None:
        ctx["sample"] = record_canonical_passing_results(
            api, ctx["sample"]["id"], engineer_id=engineer_id
        )
    else:
        ctx["sample"] = record_results(api, ctx["sample"]["id"], results, engineer_id)
    ctx["project"] = refresh_project(api, ctx["project"]["id"])
    return ctx


def setup_certified(
    api: ApiClient,
    world: Optional[Dict[str, Any]] = None,
    *,
    validity_months: Optional[int] = 12,
    reviewer_id: str = DEFAULT_REVIEWER_ID,
    **kwargs: Any,
) -> Dict[str, Any]:
    """The full happy path: world, project, frozen record, accepted sample,
    passing mandatory results, then an APPROVED decision. Adds the minted
    certification (fetched back through the project filter) to the context.
    """
    ctx = setup_project_in_evaluation(api, world, **kwargs)
    ctx["project"] = decide_project(
        api,
        ctx["project"]["id"],
        "APPROVED",
        reviewer_id=reviewer_id,
        validity_months=validity_months,
    )
    ctx["certification"] = get_certification_for_project(api, ctx["project"]["id"])
    return ctx


# ═══════════════════════════════════════════════════════════════════════════
# Tier 4: regime / quota targeting
# ═══════════════════════════════════════════════════════════════════════════

def drive_factory_to_probation(
    api: ApiClient,
    factory_id: str,
    *,
    scheduled_for: str = BASE_CLOCK_ISO,
    inspector_id: str = DEFAULT_INSPECTOR_ID,
    finding_ref: str = "FD-P",
) -> Dict[str, Any]:
    """Drop a factory to PROBATION (score 60) via one factory-level CRITICAL
    finding that names NO certification, so no suspension cascade fires.
    Returns the COMPLETED inspection."""
    inspection = schedule_and_complete_inspection(
        api,
        factory_id,
        findings=[f.finding_entry(finding_ref, "CRITICAL", "Unauthorized material on line 2")],
        scheduled_for=scheduled_for,
        inspector_id=inspector_id,
    )
    return inspection


def setup_certified_with_license(
    api: ApiClient,
    world: Optional[Dict[str, Any]] = None,
    *,
    label_type: str = "STANDARD",
    declared_annual_volume: int = f.DEFAULTS["DECLARED_ANNUAL_VOLUME"],
    **kwargs: Any,
) -> Dict[str, Any]:
    """Certified setup plus one mark license on the certification. With the
    factory in its default STANDARD regime this yields STANDARD_QUOTA
    (110% of declared volume, capped at 100000, lot-rounded)."""
    ctx = setup_certified(api, world, **kwargs)
    ctx["mark_license"] = create_mark_license(
        api,
        ctx["certification"]["id"],
        ctx["manufacturer"]["id"],
        label_type=label_type,
        declared_annual_volume=declared_annual_volume,
    )
    return ctx


def setup_probation_certified_with_license(
    api: ApiClient,
    world: Optional[Dict[str, Any]] = None,
    *,
    probation_scheduled_for: str = BASE_CLOCK_ISO,
    label_type: str = "STANDARD",
    declared_annual_volume: int = f.DEFAULTS["DECLARED_ANNUAL_VOLUME"],
    **kwargs: Any,
) -> Dict[str, Any]:
    """Certification minted while the factory is STANDARD, then the factory is
    driven to PROBATION by a factory-level CRITICAL finding (no certification
    named, so the certification stays ACTIVE), and only then is the license
    created - so it is computed under PROBATION_QUOTA (25% of volume,
    hard-capped at 500)."""
    ctx = setup_certified(api, world, **kwargs)
    ctx["probation_inspection"] = drive_factory_to_probation(
        api, ctx["factory"]["id"], scheduled_for=probation_scheduled_for
    )
    ctx["factory"] = refresh_factory(api, ctx["factory"]["id"])
    ctx["mark_license"] = create_mark_license(
        api,
        ctx["certification"]["id"],
        ctx["manufacturer"]["id"],
        label_type=label_type,
        declared_annual_volume=declared_annual_volume,
    )
    return ctx


# ═══════════════════════════════════════════════════════════════════════════
# Tier 5: terminal / compliance states
# ═══════════════════════════════════════════════════════════════════════════

def setup_approved_substitution(
    api: ApiClient,
    world: Optional[Dict[str, Any]] = None,
    *,
    slot: str = "power_supply",
    proposed_component: Optional[Dict[str, Any]] = None,
    rationale: Optional[str] = None,
    reviewer_id: str = DEFAULT_REVIEWER_ID,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Certified setup plus a substitution request decided APPROVE."""
    ctx = setup_certified(api, world, **kwargs)
    overrides: Dict[str, Any] = {"slot": slot}
    if proposed_component is not None:
        overrides["proposed_component"] = proposed_component
    if rationale is not None:
        overrides["rationale"] = rationale
    ctx["substitution_request"] = create_substitution_request(
        api, ctx["certification"]["id"], ctx["manufacturer"]["id"], **overrides
    )
    ctx["substitution_request"] = decide_substitution(
        api, ctx["substitution_request"]["id"], "APPROVE", reviewer_id=reviewer_id
    )
    return ctx


def setup_published_withdrawal_notice(
    api: ApiClient,
    world: Optional[Dict[str, Any]] = None,
    *,
    notice_overrides: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Certified setup plus a withdrawal notice that has been published
    (published_on stamped, effective_on 14 days later), not yet EFFECTIVE."""
    ctx = setup_certified(api, world, **kwargs)
    notice = create_withdrawal_notice(
        api, ctx["certification"]["id"], **(notice_overrides or {})
    )
    ctx["withdrawal_notice"] = publish_withdrawal_notice(api, notice["id"])
    return ctx


def setup_field_evaluation_world(
    api: ApiClient,
    *,
    clock_iso: str = BASE_CLOCK_ISO,
    standard: Optional[Dict[str, Any]] = None,
    manufacturer: Optional[Dict[str, Any]] = None,
    evaluating_overrides: Optional[Dict[str, Any]] = None,
    site_overrides: Optional[Dict[str, Any]] = None,
    fe_overrides: Optional[Dict[str, Any]] = None,
    evaluate: Optional[str] = None,
    engineer_id: str = DEFAULT_ENGINEER_ID,
) -> Dict[str, Any]:
    """A field evaluation and its two jurisdictions.

    ``jur_evaluating`` defaults to the evaluating authority that itself accepts
    field labels (group NATIONAL); ``jur_site`` defaults to a site authority
    that accepts labels directly (group NATIONAL), so an ACCEPT decision needs
    no reciprocity. Pass overrides to build reciprocity/mismatch variants.
    ``evaluate`` of "PASS"/"FAIL" also records the engineering outcome.
    """
    set_clock(api, clock_iso)
    standard = standard or create_standard(api)
    manufacturer = manufacturer or create_manufacturer(api)
    jur_evaluating = create_jurisdiction(api, **(evaluating_overrides or {}))
    site_payload: Dict[str, Any] = {
        "jurisdiction_code": "US-CPSC",
        "name": "CPSC",
        "accepts_field_labels": True,
        "accepts_reciprocity": False,
        "reciprocity_sources": [],
        "reciprocity_group": "NATIONAL",
    }
    site_payload.update(site_overrides or {})
    jur_site = create_jurisdiction(api, **site_payload)
    field_evaluation = create_field_evaluation(
        api,
        manufacturer["id"],
        standard["id"],
        jur_evaluating["id"],
        jur_site["id"],
        **(fe_overrides or {}),
    )
    if evaluate is not None:
        field_evaluation = evaluate_field_evaluation(
            api, field_evaluation["id"], evaluate, engineer_id=engineer_id
        )
    return {
        "standard": standard,
        "manufacturer": manufacturer,
        "jur_evaluating": jur_evaluating,
        "jur_site": jur_site,
        "field_evaluation": field_evaluation,
    }
