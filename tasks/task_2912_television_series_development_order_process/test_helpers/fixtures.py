"""Composite fixtures: pre-built states reached only through the public endpoints.

The harness restarts the server before every test, so each fixture starts from an
empty database and an unmoved logical clock and walks the development pipeline with
real API calls. Setup calls use the lenient ``get_success_data`` validator so a
broken precondition surfaces as a setup failure rather than an assertion deep
inside a test.

``build_scenario(api, "<stage>")`` runs the pipeline up to and including one stage:

    bootstrap -> writer -> pitch -> covered -> project -> deal ->
    script_complete -> pilot_ordered -> green_to_shoot -> wrapped ->
    screened -> certified -> negotiation -> agreed -> greenlight
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import (
    CLOCK_STARTUP_DEFAULT,
    COMMITTEE_BUSINESS,
    COMMITTEE_CREATIVE,
    COMMITTEE_FINANCE,
    CONTINGENCY_CASTING,
    CONTINGENCY_LOCATION,
    CONTINGENCY_SATISFIED,
    DECISION_APPROVED,
    REVIEW_ACCEPT,
)
from .test_users import (
    USER_BA_1,
    USER_BA_2,
    USER_EXEC,
    USER_FIN_1,
    agency_rep_headers,
    business_affairs_headers,
    development_exec_headers,
    finance_controller_headers,
    platform_admin_headers,
    research_analyst_headers,
    studio_partner_headers,
)
from .types import PIPELINE_STAGES, ScenarioContext

JsonDict = Dict[str, Any]

WRAP_CLOCK = "2026-09-26T00:00:00Z"


# ─── Clock ────────────────────────────────────────────
def set_clock(api, to_iso8601: str) -> JsonDict:
    """Move the logical clock, the sole source of every server-stamped instant."""
    return get_success_data(api.set_clock(to_iso8601, platform_admin_headers()))


# ─── Tier 2: entity hierarchy ─────────────────────────
def create_agency(api, overrides: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(
        api.create_agency(f.agency_payload(overrides), platform_admin_headers())
    )


def create_slate(api, overrides: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(
        api.create_slate(f.slate_payload(overrides), platform_admin_headers())
    )


def create_writer(api, agency_id: str, overrides: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(
        api.create_writer(
            f.writer_payload(agency_id, overrides), agency_rep_headers(agency_id)
        )
    )


def bootstrap(
    api,
    *,
    agency: Optional[JsonDict] = None,
    slate: Optional[JsonDict] = None,
    clock: str = CLOCK_STARTUP_DEFAULT,
) -> ScenarioContext:
    """An agency, a slate and a clock reading its startup default."""
    ctx = ScenarioContext()
    set_clock(api, clock)
    ctx.agency_id = create_agency(api, agency)["id"]
    ctx.slate_id = create_slate(api, slate)["id"]
    return ctx


# ─── Tier 1: pitch state progression ──────────────────
def submit_pitch(
    api, ctx: ScenarioContext, overrides: Optional[JsonDict] = None
) -> JsonDict:
    return get_success_data(
        api.create_pitch(
            f.pitch_payload(ctx.agency_id, ctx.slate_id, overrides),
            agency_rep_headers(ctx.agency_id),
        )
    )


def file_rights_check(
    api, pitch_id: str, overrides: Optional[JsonDict] = None
) -> JsonDict:
    return get_success_data(
        api.file_rights_check(
            pitch_id, f.rights_check_payload(overrides=overrides), business_affairs_headers()
        )
    )


def record_coverage(
    api, pitch_id: str, overrides: Optional[JsonDict] = None
) -> JsonDict:
    return get_success_data(
        api.record_coverage(
            pitch_id, f.coverage_payload(overrides=overrides), development_exec_headers()
        )
    )


def advance_pitch(api, pitch_id: str) -> JsonDict:
    """The advance response is the newly created DevelopmentProject."""
    return get_success_data(api.advance_pitch(pitch_id, development_exec_headers()))


# ─── Tier 3: script deal lifecycle shortcuts ──────────
def execute_script_deal(
    api,
    project_id: str,
    writer_id: str,
    *,
    steps: Optional[List[JsonDict]] = None,
    guaranteed_step_count: int = 1,
    option_period_days: int = 60,
    overrides: Optional[JsonDict] = None,
) -> JsonDict:
    return get_success_data(
        api.create_script_deal(
            f.script_deal_payload(
                project_id,
                writer_id,
                steps=steps,
                guaranteed_step_count=guaranteed_step_count,
                option_period_days=option_period_days,
                overrides=overrides,
            ),
            business_affairs_headers(),
        )
    )


def deal_step_ids(api, deal_id: str) -> List[str]:
    steps = get_success_data(api.list_deal_steps(deal_id, business_affairs_headers()))
    return [step["id"] for step in steps]


def accept_step(api, deal_id: str, step_id: str) -> JsonDict:
    """Exercise, deliver and accept one step in a single move."""
    get_success_data(api.exercise_step(deal_id, step_id, business_affairs_headers()))
    get_success_data(api.deliver_step(deal_id, step_id, business_affairs_headers()))
    return get_success_data(
        api.review_step(
            deal_id, step_id, f.review_payload(REVIEW_ACCEPT), development_exec_headers()
        )
    )


# ─── Tier 3: pilot lifecycle shortcuts ────────────────
def order_pilot(
    api, project_id: str, overrides: Optional[JsonDict] = None, **kwargs
) -> JsonDict:
    return get_success_data(
        api.create_pilot_order(
            f.pilot_order_payload(project_id, overrides=overrides, **kwargs),
            development_exec_headers(),
        )
    )


def clear_contingency(
    api, pilot_order_id: str, kind: str, resolution: str, headers=None, note=None
) -> JsonDict:
    overrides = {"note": note} if note is not None else None
    return get_success_data(
        api.clear_contingency(
            pilot_order_id,
            f.contingency_payload(kind, resolution, overrides=overrides),
            headers or development_exec_headers(),
        )
    )


def greenlight_the_shoot(api, pilot_order_id: str) -> None:
    """Satisfy both contingency dimensions, which auto-greenlights the shoot."""
    clear_contingency(api, pilot_order_id, CONTINGENCY_CASTING, CONTINGENCY_SATISFIED)
    clear_contingency(api, pilot_order_id, CONTINGENCY_LOCATION, CONTINGENCY_SATISFIED)


def wrap_pilot(api, pilot_order_id: str, *, clock: Optional[str] = WRAP_CLOCK) -> JsonDict:
    if clock is not None:
        set_clock(api, clock)
    return get_success_data(api.wrap_pilot(pilot_order_id, development_exec_headers()))


# ─── Tier 4: research and negotiation ─────────────────
def field_screening(
    api,
    pilot_order_id: str,
    expected_pilot_order_version: int,
    overrides: Optional[JsonDict] = None,
    **kwargs,
) -> JsonDict:
    return get_success_data(
        api.field_screening(
            pilot_order_id,
            f.screening_payload(
                expected_pilot_order_version, overrides=overrides, **kwargs
            ),
            research_analyst_headers(),
        )
    )


def certify_screening(api, screening_id: str) -> JsonDict:
    return get_success_data(
        api.certify_screening(screening_id, research_analyst_headers())
    )


def open_negotiation(
    api, project_id: str, overrides: Optional[JsonDict] = None, **kwargs
) -> JsonDict:
    return get_success_data(
        api.create_negotiation(
            f.negotiation_payload(project_id, overrides=overrides, **kwargs),
            business_affairs_headers(),
        )
    )


def accept_negotiation_as_studio(api, negotiation_id: str) -> JsonDict:
    return get_success_data(
        api.accept_negotiation(negotiation_id, studio_partner_headers())
    )


# ─── Tier 5: greenlight and finalisation ──────────────
def project_version(api, project_id: str) -> int:
    return get_success_data(
        api.get_project(project_id, business_affairs_headers())
    )["version"]


def file_greenlight_request(
    api, project_id: str, negotiation_id: str, expected_project_version: int
) -> JsonDict:
    return get_success_data(
        api.create_greenlight_request(
            f.greenlight_payload(
                project_id, negotiation_id, expected_project_version
            ),
            business_affairs_headers(),
        )
    )


def record_creative_decision(
    api, greenlight_id: str, decision: str = DECISION_APPROVED, user_id: str = USER_EXEC
) -> JsonDict:
    return get_success_data(
        api.record_decision(
            greenlight_id,
            f.decision_payload(COMMITTEE_CREATIVE, decision),
            development_exec_headers(user_id),
        )
    )


def record_business_decision(
    api, greenlight_id: str, decision: str = DECISION_APPROVED, user_id: str = USER_BA_2
) -> JsonDict:
    return get_success_data(
        api.record_decision(
            greenlight_id,
            f.decision_payload(COMMITTEE_BUSINESS, decision),
            business_affairs_headers(user_id),
        )
    )


def record_finance_decision(
    api, greenlight_id: str, decision: str = DECISION_APPROVED, user_id: str = USER_FIN_1
) -> JsonDict:
    return get_success_data(
        api.record_decision(
            greenlight_id,
            f.decision_payload(COMMITTEE_FINANCE, decision),
            finance_controller_headers(user_id),
        )
    )


# ─── The pipeline driver ──────────────────────────────
def build_scenario(api, stage: str = "bootstrap", **kw) -> ScenarioContext:
    """Walk the development pipeline up to and including ``stage``.

    Recognised keyword overrides, each a payload override dict:
    ``agency``, ``slate``, ``writer``, ``pitch``, ``rights``, ``coverage``,
    ``deal`` (accepts ``steps``, ``guaranteed_step_count``, ``option_period_days``),
    ``pilot``, ``screening``, ``negotiation``. ``clock`` sets the opening instant and
    ``wrap_clock`` the instant the shoot is wrapped at.
    """
    assert stage in PIPELINE_STAGES, f"unknown stage {stage!r}"
    target = PIPELINE_STAGES.index(stage)

    ctx = bootstrap(
        api,
        agency=kw.get("agency"),
        slate=kw.get("slate"),
        clock=kw.get("clock", CLOCK_STARTUP_DEFAULT),
    )
    if target == PIPELINE_STAGES.index("bootstrap"):
        return ctx

    ctx.writer_id = create_writer(api, ctx.agency_id, kw.get("writer"))["id"]
    if target == PIPELINE_STAGES.index("writer"):
        return ctx

    ctx.pitch_id = submit_pitch(api, ctx, kw.get("pitch"))["id"]
    if target == PIPELINE_STAGES.index("pitch"):
        return ctx

    ctx.rights_check_id = file_rights_check(api, ctx.pitch_id, kw.get("rights"))["id"]
    record_coverage(api, ctx.pitch_id, kw.get("coverage"))
    if target == PIPELINE_STAGES.index("covered"):
        return ctx

    ctx.project_id = advance_pitch(api, ctx.pitch_id)["id"]
    if target == PIPELINE_STAGES.index("project"):
        return ctx

    deal_kw = dict(kw.get("deal") or {})
    deal = execute_script_deal(
        api,
        ctx.project_id,
        ctx.writer_id,
        steps=deal_kw.pop("steps", None),
        guaranteed_step_count=deal_kw.pop("guaranteed_step_count", 1),
        option_period_days=deal_kw.pop("option_period_days", 60),
        overrides=deal_kw or None,
    )
    ctx.deal_id = deal["id"]
    ctx.step_ids = deal_step_ids(api, ctx.deal_id)
    if target == PIPELINE_STAGES.index("deal"):
        return ctx

    for step_id in ctx.step_ids[: kw.get("accept_steps", 1)]:
        accept_step(api, ctx.deal_id, step_id)
    if target == PIPELINE_STAGES.index("script_complete"):
        return ctx

    ctx.pilot_order_id = order_pilot(api, ctx.project_id, kw.get("pilot"))["id"]
    if target == PIPELINE_STAGES.index("pilot_ordered"):
        return ctx

    greenlight_the_shoot(api, ctx.pilot_order_id)
    if target == PIPELINE_STAGES.index("green_to_shoot"):
        return ctx

    wrapped = wrap_pilot(
        api, ctx.pilot_order_id, clock=kw.get("wrap_clock", WRAP_CLOCK)
    )
    ctx.pilot_order_version = wrapped["version"]
    if target == PIPELINE_STAGES.index("wrapped"):
        return ctx

    screening_kw = dict(kw.get("screening") or {})
    ctx.screening_id = field_screening(
        api, ctx.pilot_order_id, ctx.pilot_order_version, **screening_kw
    )["id"]
    if target == PIPELINE_STAGES.index("screened"):
        return ctx

    certify_screening(api, ctx.screening_id)
    if target == PIPELINE_STAGES.index("certified"):
        return ctx

    negotiation_kw = dict(kw.get("negotiation") or {})
    ctx.negotiation_id = open_negotiation(api, ctx.project_id, **negotiation_kw)["id"]
    if target == PIPELINE_STAGES.index("negotiation"):
        return ctx

    accept_negotiation_as_studio(api, ctx.negotiation_id)
    if target == PIPELINE_STAGES.index("agreed"):
        return ctx

    ctx.project_version = project_version(api, ctx.project_id)
    ctx.greenlight_id = file_greenlight_request(
        api, ctx.project_id, ctx.negotiation_id, ctx.project_version
    )["id"]
    return ctx


# ─── Named terminal-state shortcuts ───────────────────
def abandoned_project(api, stage: str = "pilot_ordered", *, reason: str = "showrunner unavailable", **kw):
    """Walk to ``stage``, then abandon the project, freezing its write-off."""
    ctx = build_scenario(api, stage, **kw)
    get_success_data(
        api.abandon_project(
            ctx.project_id, f.abandon_payload(reason), development_exec_headers()
        )
    )
    return ctx


def turnaround_offered(api, stage: str = "pilot_ordered", **kw):
    """Abandon the project and offer it into turnaround, opening the window."""
    ctx = abandoned_project(api, stage, **kw)
    get_success_data(
        api.offer_turnaround(ctx.project_id, business_affairs_headers())
    )
    return ctx


def add_holding_deal(
    api,
    ctx: ScenarioContext,
    writer_id: Optional[str] = None,
    *,
    annual_cost_cents: int = 20000000,
    start_date: str = "2026-08-01",
    end_date: str = "2027-08-01",
    slate_id: Optional[str] = None,
) -> JsonDict:
    return get_success_data(
        api.create_holding_deal(
            f.holding_deal_payload(
                writer_id or ctx.writer_id,
                slate_id or ctx.slate_id,
                annual_cost_cents=annual_cost_cents,
                start_date=start_date,
                end_date=end_date,
            ),
            business_affairs_headers(),
        )
    )


def add_second_writer(
    api, ctx: ScenarioContext, overrides: Optional[JsonDict] = None
) -> str:
    payload = {"full_name": "Bo Nguyen"}
    if overrides:
        payload.update(overrides)
    ctx.writer2_id = create_writer(api, ctx.agency_id, payload)["id"]
    return ctx.writer2_id


def add_second_pitch(
    api, ctx: ScenarioContext, overrides: Optional[JsonDict] = None
) -> str:
    payload = {
        "title": "Deep Water",
        "logline": "A salvage crew finds a wreck that is still logging position.",
        "underlying_ip_key": "IP-DEEP-WATER",
    }
    if overrides:
        payload.update(overrides)
    ctx.pitch2_id = submit_pitch(api, ctx, payload)["id"]
    return ctx.pitch2_id


def covered_second_pitch(
    api,
    ctx: ScenarioContext,
    *,
    pitch: Optional[JsonDict] = None,
    rights: Optional[JsonDict] = None,
    coverage: Optional[JsonDict] = None,
) -> str:
    """A second pitch on the same slate, rights-cleared and recommended to advance."""
    pitch_id = add_second_pitch(api, ctx, pitch)
    ip_key = (pitch or {}).get("underlying_ip_key", "IP-DEEP-WATER")
    rights_overrides = {"underlying_ip_key": ip_key}
    if rights:
        rights_overrides.update(rights)
    file_rights_check(api, pitch_id, rights_overrides)
    record_coverage(api, pitch_id, coverage or {"coverage_score": 80.0})
    return pitch_id


def second_project_through(
    api, ctx: ScenarioContext, stage: str = "script_complete", **kw
) -> str:
    """Bring a second project on the same slate up to ``stage``.

    Only the stages from ``project`` to ``pilot_ordered`` are supported; the second
    project reuses the slate and a second writer so the two never contend for one
    writer's step load.
    """
    writer2 = ctx.writer2_id or add_second_writer(api, ctx, kw.get("writer"))
    pitch2 = covered_second_pitch(
        api, ctx, pitch=kw.get("pitch"), rights=kw.get("rights"), coverage=kw.get("coverage")
    )
    ctx.project2_id = advance_pitch(api, pitch2)["id"]
    if stage == "project":
        return ctx.project2_id

    deal_kw = dict(kw.get("deal") or {})
    deal2 = execute_script_deal(
        api,
        ctx.project2_id,
        writer2,
        steps=deal_kw.pop("steps", None),
        guaranteed_step_count=deal_kw.pop("guaranteed_step_count", 1),
        option_period_days=deal_kw.pop("option_period_days", 60),
        overrides=deal_kw or None,
    )
    ctx.deal2_id = deal2["id"]
    if stage == "deal":
        return ctx.project2_id

    for step_id in deal_step_ids(api, ctx.deal2_id)[:1]:
        accept_step(api, ctx.deal2_id, step_id)
    if stage == "script_complete":
        return ctx.project2_id

    ctx.pilot_order2_id = order_pilot(api, ctx.project2_id, kw.get("pilot"))["id"]
    return ctx.project2_id
