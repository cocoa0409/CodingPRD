"""Composite setup helpers.

The test harness restarts the server before every individual test, so every
fixture here builds its state from an empty database and an untouched logical
clock.  All setup calls go through ``get_success_data`` so a broken precondition
reports itself as a setup failure rather than as a mysterious assertion.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import CODE_SUPERVISION, DEFAULT_LOGICAL_CLOCK
from .test_users import (
    admin_headers,
    bgu_headers,
    intake_headers,
    make_applicant_headers,
    make_inspector_headers,
    make_investigator_headers,
    supervisor_headers,
)


# ─── Tier 1: primitives ────────────────────────────────────────────────
def set_clock(api: ApiClient, to_iso8601: str, headers: Optional[Dict] = None) -> str:
    """Move the logical clock and return the resulting ``current_utc``."""
    data = get_success_data(
        api.set_clock(to_iso8601, headers=headers or admin_headers())
    )
    return data["current_utc"]


def reset_clock(api: ApiClient) -> str:
    return set_clock(api, DEFAULT_LOGICAL_CLOCK)


def seed_catalog(api: ApiClient, headers: Optional[Dict] = None) -> Dict[str, str]:
    """Register the checklist rows every cascade in the service can reach by
    code.  Returns a ``code -> checklist_item_id`` map."""
    hdrs = headers or admin_headers()
    catalog: Dict[str, str] = {}
    for row in f.CATALOG_SEED:
        item = get_success_data(api.create_checklist_item(dict(row), headers=hdrs))
        catalog[item["code"]] = item["id"]
    return catalog


def register_inspector(
    api: ApiClient,
    full_name: str = "Ivy Cole",
    county_code: str = "CTY-01",
    certified_age_groups: Optional[List[str]] = None,
    max_daily_visits: Optional[int] = None,
    headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_inspector(
            f.inspector_payload(
                full_name=full_name,
                county_code=county_code,
                certified_age_groups=certified_age_groups,
                max_daily_visits=max_daily_visits,
            ),
            headers=headers or admin_headers(),
        )
    )


def create_provider(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Create a provider application.  This is the one operation that sends no
    ``X-User-ID``, so the applicant's later identity is the returned ``id``."""
    from .test_users import applicant_creation_headers

    return get_success_data(
        api.create_provider(
            f.provider_payload(**kwargs), headers=applicant_creation_headers()
        )
    )


def attach_staff(
    api: ApiClient, provider_id: str, headers: Optional[Dict] = None, **kwargs: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_staff_member(
            f.staff_member_payload(provider_id, **kwargs),
            headers=headers or make_applicant_headers(provider_id),
        )
    )


def open_check(
    api: ApiClient,
    staff_member_id: str,
    check_type: str,
    headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_background_check(
            f.background_check_payload(staff_member_id, check_type),
            headers=headers or bgu_headers(),
        )
    )


def record_result(
    api: ApiClient,
    check_id: str,
    result: str,
    tier: Optional[str] = None,
    headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {}
    if tier is not None:
        kwargs["disqualifying_offense_tier"] = tier
    return get_success_data(
        api.record_check_result(
            check_id, result, headers=headers or bgu_headers(), **kwargs
        )
    )


def clear_person(api: ApiClient, staff_member_id: str) -> Dict[str, Dict[str, Any]]:
    """Open and clear the two check types a person's clearance requires:
    ``FBI_FINGERPRINT`` and ``CHILD_ABUSE_REGISTRY``."""
    checks: Dict[str, Dict[str, Any]] = {}
    for check_type in ("FBI_FINGERPRINT", "CHILD_ABUSE_REGISTRY"):
        opened = open_check(api, staff_member_id, check_type)
        checks[check_type] = record_result(api, opened["id"], "CLEARED")
    return checks


def add_roster(
    api: ApiClient, provider_id: str, headers: Optional[Dict] = None, **kwargs: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_roster(
            f.roster_payload(provider_id, **kwargs),
            headers=headers or make_applicant_headers(provider_id),
        )
    )


# ─── Tier 2: the provider dossier ──────────────────────────────────────
@dataclass
class ProviderCtx:
    """Everything a test needs to keep acting on one provider."""

    api: ApiClient
    provider: Dict[str, Any]
    catalog: Dict[str, str] = field(default_factory=dict)
    director: Optional[Dict[str, Any]] = None
    director_checks: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    rosters: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.provider["id"]

    @property
    def headers(self) -> Dict[str, str]:
        return make_applicant_headers(self.provider["id"])

    def reload(self) -> Dict[str, Any]:
        self.provider = get_success_data(
            self.api.get_provider(self.id, headers=self.headers)
        )
        return self.provider

    def reload_roster(self, age_group: str) -> Dict[str, Any]:
        roster = self.rosters[age_group]
        self.rosters[age_group] = get_success_data(
            self.api.get_roster(roster["id"], headers=self.headers)
        )
        return self.rosters[age_group]


def setup_provider_dossier(
    api: ApiClient,
    *,
    legal_name: str = "Bright Start Center",
    county_code: str = "CTY-01",
    site_address: str = "12 Elm St",
    program_type: str = "CENTER",
    requested_capacity: int = 10,
    rooms: Optional[List[Dict[str, Any]]] = None,
    director_name: str = "Dana Reed",
    director_qualified_age_groups: Optional[List[str]] = None,
    clear_director: bool = True,
    seed_checklist: bool = True,
    catalog: Optional[Dict[str, str]] = None,
) -> ProviderCtx:
    """A provider application with a director and its rooms.

    ``rooms`` defaults to a single PRESCHOOL room whose requested group size
    equals the requested capacity, because application submission requires the
    sum of requested group sizes to equal the requested capacity exactly.
    """
    if catalog is None and seed_checklist:
        catalog = seed_catalog(api)
    provider = create_provider(
        api,
        legal_name=legal_name,
        county_code=county_code,
        site_address=site_address,
        program_type=program_type,
        requested_capacity=requested_capacity,
    )
    ctx = ProviderCtx(api=api, provider=provider, catalog=catalog or {})

    ctx.director = attach_staff(
        api,
        ctx.id,
        full_name=director_name,
        member_type="DIRECTOR",
        role_title="Center Director",
        qualified_age_groups=director_qualified_age_groups
        or ["INFANT", "TODDLER", "PRESCHOOL", "SCHOOL_AGE"],
    )
    if clear_director:
        ctx.director_checks = clear_person(api, ctx.director["id"])

    for room in rooms or [{"age_group": "PRESCHOOL", "requested_group_size": requested_capacity}]:
        spec = dict(room)
        age_group = spec.pop("age_group")
        ctx.rosters[age_group] = add_roster(api, ctx.id, age_group=age_group, **spec)

    ctx.reload()
    return ctx


def submit_application(ctx: ProviderCtx) -> Dict[str, Any]:
    ctx.provider = get_success_data(
        ctx.api.submit_application(ctx.id, headers=ctx.headers)
    )
    return ctx.provider


def clear_checks(ctx: ProviderCtx, headers: Optional[Dict] = None) -> Dict[str, Any]:
    ctx.provider = get_success_data(
        ctx.api.clear_checks(ctx.id, headers=headers or supervisor_headers())
    )
    return ctx.provider


def advance_to_checks_cleared(ctx: ProviderCtx) -> Dict[str, Any]:
    """DRAFT -> SUBMITTED -> CHECKS_CLEARED."""
    submit_application(ctx)
    return clear_checks(ctx)


# ─── Tier 3: the inspection visit ──────────────────────────────────────
def schedule_visit(
    api: ApiClient,
    provider_id: str,
    inspector_id: str,
    scheduled_for: str,
    inspection_type: str = "INITIAL",
    target_age_groups: Optional[List[str]] = None,
    duration_minutes: Optional[int] = None,
    complaint_id: Optional[str] = None,
    headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_inspection(
            f.inspection_payload(
                provider_id,
                inspector_id,
                inspection_type=inspection_type,
                scheduled_for=scheduled_for,
                target_age_groups=target_age_groups,
                duration_minutes=duration_minutes,
                complaint_id=complaint_id,
            ),
            headers=headers or supervisor_headers(),
        )
    )


def start_visit(api: ApiClient, inspection_id: str, inspector_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.start_inspection(inspection_id, headers=make_inspector_headers(inspector_id))
    )


def cite(
    api: ApiClient,
    inspection_id: str,
    inspector_id: str,
    checklist_item_id: str,
    primary_age_group: str = "PRESCHOOL",
    severity_override: Optional[str] = None,
    repeat_of_violation_id: Optional[str] = None,
    narrative: str = "Finding recorded during the visit.",
) -> Dict[str, Any]:
    return get_success_data(
        api.create_violation(
            f.violation_payload(
                inspection_id,
                checklist_item_id,
                primary_age_group=primary_age_group,
                narrative=narrative,
                severity_override=severity_override,
                repeat_of_violation_id=repeat_of_violation_id,
            ),
            headers=make_inspector_headers(inspector_id),
        )
    )


def cite_all(
    api: ApiClient,
    inspection_id: str,
    inspector_id: str,
    catalog: Dict[str, str],
    specs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Cite a list of findings.  Each spec names ``code`` plus any of
    ``primary_age_group``, ``severity_override``, ``repeat_of_violation_id`` and
    ``narrative``."""
    cited: List[Dict[str, Any]] = []
    for spec in specs:
        payload = dict(spec)
        code = payload.pop("code", CODE_SUPERVISION)
        cited.append(
            cite(api, inspection_id, inspector_id, catalog[code], **payload)
        )
    return cited


def submit_findings(
    api: ApiClient,
    inspection_id: str,
    inspector_id: str,
    outcome: str,
    age_groups_observed: List[str],
) -> Dict[str, Any]:
    return get_success_data(
        api.submit_for_review(
            inspection_id,
            outcome,
            age_groups_observed,
            headers=make_inspector_headers(inspector_id),
        )
    )


def finalize_visit(
    api: ApiClient, inspection_id: str, headers: Optional[Dict] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.finalize_inspection(inspection_id, headers=headers or supervisor_headers())
    )


def run_visit(
    api: ApiClient,
    provider_id: str,
    inspector_id: str,
    scheduled_for: str,
    *,
    inspection_type: str = "ANNUAL",
    target_age_groups: Optional[List[str]] = None,
    age_groups_observed: Optional[List[str]] = None,
    duration_minutes: Optional[int] = None,
    complaint_id: Optional[str] = None,
    catalog: Optional[Dict[str, str]] = None,
    citations: Optional[List[Dict[str, Any]]] = None,
    outcome: str = "PASS",
    finalize: bool = True,
    supervisor: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Schedule, start, cite, submit and finalize one visit in one call.

    Returns ``{"inspection": ..., "violations": [...]}``.  The outcome must agree
    with what was cited, so callers pass ``FAIL`` whenever a critical finding is
    among the citations and ``PASS`` only when nothing was cited.
    """
    inspection = schedule_visit(
        api,
        provider_id,
        inspector_id,
        scheduled_for,
        inspection_type=inspection_type,
        target_age_groups=target_age_groups,
        duration_minutes=duration_minutes,
        complaint_id=complaint_id,
        headers=supervisor,
    )
    start_visit(api, inspection["id"], inspector_id)
    violations: List[Dict[str, Any]] = []
    if citations:
        violations = cite_all(
            api, inspection["id"], inspector_id, catalog or {}, citations
        )
    observed = age_groups_observed or target_age_groups or ["PRESCHOOL"]
    inspection = submit_findings(
        api, inspection["id"], inspector_id, outcome, observed
    )
    if finalize:
        inspection = finalize_visit(api, inspection["id"], headers=supervisor)
    return {"inspection": inspection, "violations": violations}


# ─── Tier 4: licensure ─────────────────────────────────────────────────
def license_provider(
    ctx: ProviderCtx,
    inspector_id: str,
    *,
    initial_scheduled_for: str = "2026-08-05T09:00:00Z",
    target_age_groups: Optional[List[str]] = None,
    supervisor: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Walk the application from CHECKS_CLEARED through a passing INITIAL visit
    to an issued provisional licence.  Returns the INITIAL inspection."""
    api = ctx.api
    observed = target_age_groups or list(ctx.rosters.keys()) or ["PRESCHOOL"]
    result = run_visit(
        api,
        ctx.id,
        inspector_id,
        initial_scheduled_for,
        inspection_type="INITIAL",
        target_age_groups=observed,
        age_groups_observed=observed,
        outcome="PASS",
        supervisor=supervisor,
    )
    ctx.provider = get_success_data(
        api.license_decision(
            ctx.id, "ISSUE", headers=supervisor or supervisor_headers()
        )
    )
    return result["inspection"]


def setup_licensed_provider(
    api: ApiClient,
    *,
    requested_capacity: int = 10,
    rooms: Optional[List[Dict[str, Any]]] = None,
    program_type: str = "CENTER",
    county_code: str = "CTY-01",
    legal_name: str = "Bright Start Center",
    inspector_id: Optional[str] = None,
    inspector_certified_age_groups: Optional[List[str]] = None,
    initial_scheduled_for: str = "2026-08-05T09:00:00Z",
    catalog: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """A provider holding a provisional licence, plus its finalized INITIAL visit.

    Returns ``{"ctx": ProviderCtx, "inspector": ..., "initial_inspection": ...}``.
    """
    catalog = catalog or seed_catalog(api)
    inspector = None
    if inspector_id is None:
        inspector = register_inspector(
            api, certified_age_groups=inspector_certified_age_groups
        )
        inspector_id = inspector["id"]
    ctx = setup_provider_dossier(
        api,
        legal_name=legal_name,
        county_code=county_code,
        program_type=program_type,
        requested_capacity=requested_capacity,
        rooms=rooms,
        catalog=catalog,
        seed_checklist=False,
    )
    advance_to_checks_cleared(ctx)
    initial = license_provider(
        ctx, inspector_id, initial_scheduled_for=initial_scheduled_for
    )
    ctx.reload()
    return {"ctx": ctx, "inspector": inspector, "initial_inspection": initial}


def setup_licensed_provider_with_citations(
    api: ApiClient,
    citations: List[Dict[str, Any]],
    *,
    requested_capacity: int = 10,
    rooms: Optional[List[Dict[str, Any]]] = None,
    program_type: str = "CENTER",
    inspector_certified_age_groups: Optional[List[str]] = None,
    initial_scheduled_for: str = "2026-08-05T09:00:00Z",
    annual_scheduled_for: str = "2026-08-05T13:00:00Z",
    annual_target_age_groups: Optional[List[str]] = None,
    outcome: str = "FAIL",
    catalog: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """A licensed provider carrying a finalized ANNUAL visit with citations.

    The ANNUAL visit is scheduled only after the INITIAL one has finalized,
    because a finalized visit releases both of its occupancy windows.

    Returns ``{"ctx", "inspector", "initial_inspection", "annual", "violations",
    "catalog"}``.
    """
    catalog = catalog or seed_catalog(api)
    base = setup_licensed_provider(
        api,
        requested_capacity=requested_capacity,
        rooms=rooms,
        program_type=program_type,
        inspector_certified_age_groups=inspector_certified_age_groups,
        initial_scheduled_for=initial_scheduled_for,
        catalog=catalog,
    )
    ctx = base["ctx"]
    observed = annual_target_age_groups or list(ctx.rosters.keys()) or ["PRESCHOOL"]
    result = run_visit(
        api,
        ctx.id,
        base["inspector"]["id"],
        annual_scheduled_for,
        inspection_type="ANNUAL",
        target_age_groups=observed,
        age_groups_observed=observed,
        catalog=catalog,
        citations=citations,
        outcome=outcome,
    )
    ctx.reload()
    return {
        "ctx": ctx,
        "inspector": base["inspector"],
        "initial_inspection": base["initial_inspection"],
        "annual": result["inspection"],
        "violations": result["violations"],
        "catalog": catalog,
    }


# ─── Tier 5: casework, remediation, enforcement, publication ───────────
def intake_complaint(
    api: ApiClient, provider_id: str, headers: Optional[Dict] = None, **kwargs: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_complaint(
            f.complaint_payload(provider_id, **kwargs),
            headers=headers or intake_headers(),
        )
    )


def screen_complaint(
    api: ApiClient, complaint_id: str, decision: str = "SCREEN_IN", headers=None
) -> Dict[str, Any]:
    return get_success_data(
        api.screen_complaint(complaint_id, decision, headers=headers or intake_headers())
    )


def assign_investigator(
    api: ApiClient, complaint_id: str, investigator_id: str, headers=None
) -> Dict[str, Any]:
    return get_success_data(
        api.assign_investigator(
            complaint_id, investigator_id, headers=headers or supervisor_headers()
        )
    )


def record_determination(
    api: ApiClient, complaint_id: str, investigator_id: str, determination: str
) -> Dict[str, Any]:
    return get_success_data(
        api.record_determination(
            complaint_id,
            determination,
            headers=make_investigator_headers(investigator_id),
        )
    )


def setup_complaint_under_investigation(
    api: ApiClient,
    provider_id: str,
    investigator_id: str,
    *,
    allegation_category: str = "SUPERVISION",
    affected_age_group: str = "PRESCHOOL",
    intake_channel: str = "PHONE",
    alleged_serious_harm: Optional[bool] = None,
) -> Dict[str, Any]:
    """Intake -> SCREEN_IN -> investigator assigned."""
    complaint = intake_complaint(
        api,
        provider_id,
        allegation_category=allegation_category,
        affected_age_group=affected_age_group,
        intake_channel=intake_channel,
        alleged_serious_harm=alleged_serious_harm,
    )
    screen_complaint(api, complaint["id"], "SCREEN_IN")
    return assign_investigator(api, complaint["id"], investigator_id)


def submit_cap(
    api: ApiClient,
    provider_id: str,
    inspection_id: str,
    violation_ids: List[str],
    expected_inspection_version: int,
    **kwargs: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_cap(
            f.cap_payload(
                inspection_id, violation_ids, expected_inspection_version, **kwargs
            ),
            headers=make_applicant_headers(provider_id),
        )
    )


def review_cap(
    api: ApiClient, cap_id: str, decision: str, review_note: Optional[str] = None, headers=None
) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {}
    if review_note is not None:
        kwargs["review_note"] = review_note
    return get_success_data(
        api.review_cap(cap_id, decision, headers=headers or supervisor_headers(), **kwargs)
    )


def propose_action(
    api: ApiClient,
    provider_id: str,
    requested_action_type: str,
    source_inspection_id: Optional[str] = None,
    rationale: Optional[str] = None,
    headers=None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_enforcement_action(
            f.enforcement_action_payload(
                provider_id,
                requested_action_type=requested_action_type,
                source_inspection_id=source_inspection_id,
                rationale=rationale,
            ),
            headers=headers or supervisor_headers(),
        )
    )


def issue_action(api: ApiClient, action_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.issue_action(action_id, headers=headers or supervisor_headers())
    )


def effectuate_action(api: ApiClient, action_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.effectuate_action(action_id, headers=headers or admin_headers())
    )


def run_enforcement(
    api: ApiClient,
    provider_id: str,
    requested_action_type: str,
    *,
    source_inspection_id: Optional[str] = None,
    supervisor: Optional[Dict] = None,
    admin: Optional[Dict] = None,
    effectuate: bool = True,
) -> Dict[str, Any]:
    """Propose, issue and (by default) effectuate one rung of the ladder."""
    action = propose_action(
        api,
        provider_id,
        requested_action_type,
        source_inspection_id=source_inspection_id,
        headers=supervisor,
    )
    action = issue_action(api, action["id"], headers=supervisor)
    if effectuate:
        action = effectuate_action(api, action["id"], headers=admin)
    return action


def file_incident_report(
    api: ApiClient, provider_id: str, headers: Optional[Dict] = None, **kwargs: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_incident_report(
            f.incident_report_payload(provider_id, **kwargs),
            headers=headers or make_applicant_headers(provider_id),
        )
    )


def prepare_posting(
    api: ApiClient, inspection_id: str, headers: Optional[Dict] = None, **kwargs: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_posting(
            f.posting_payload(inspection_id, **kwargs), headers=headers or admin_headers()
        )
    )


def publish_posting(api: ApiClient, posting_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api.post_posting(posting_id, headers=headers or admin_headers())
    )
