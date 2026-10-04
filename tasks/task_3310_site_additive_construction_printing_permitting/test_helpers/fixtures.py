"""Composite setup helpers.

The interesting claims in this API require the system to be in a state that
takes 10–25 calls to reach (site poured and cured, printer qualified, batch
qualified, weather posted, permit approved, job scheduled and started). These
fixtures encapsulate those chains so tests can focus on assertions. All
helpers use ``get_success_data`` so a setup failure surfaces as a clear
"Setup failed" error rather than a confusing assertion failure.

Logical-clock discipline: fixtures accept explicit ISO timestamps; tests drive
the clock via ``set_clock`` and should re-read the site before any
site-version-asserting create (the version bumps on every site-scoped write).
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_jurisdiction_payload,
    create_layer_inspection_payload,
    create_material_batch_payload,
    create_permit_application_payload,
    create_plan_revision_payload,
    create_print_job_payload,
    create_printer_setup_payload,
    create_site_payload,
    create_structural_plan_payload,
    create_trade_task_payload,
    create_weather_observation_payload,
)
from .test_users import (
    TEST_USERS,
    make_engineer_headers,
    make_quality_inspector_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SITE_MGR = TEST_USERS["site_manager_headers"]
PERMIT_COORD = TEST_USERS["permit_coordinator_headers"]
JURIS_REVIEWER = TEST_USERS["jurisdiction_reviewer_headers"]
PRINT_OP = TEST_USERS["print_operator_headers"]
QUALITY_INSP = TEST_USERS["quality_inspector_headers"]
TRADE_CON = TEST_USERS["trade_contractor_headers"]

# Distinct engineer identities for segregation of duties (PRD §3.3): the
# decider's X-User-ID must differ from the submitter's.
ENG_SUBMITTER = make_engineer_headers("eng-alice")
ENG_DECIDER = make_engineer_headers("eng-bob")


# ---------------------------------------------------------------------------
# Tier 1: jurisdiction / clock / plan building blocks
# ---------------------------------------------------------------------------

def set_clock(current_utc: str):
    return get_success_data(api_client.set_clock(current_utc, ADMIN))


def create_jurisdiction(permits_prescriptive=True, am_review_days=30, code="J-AUTOGEN"):
    payload = create_jurisdiction_payload(
        code=code,
        permits_prescriptive_printed_path=permits_prescriptive,
        alternative_means_review_days=am_review_days,
    )
    return get_success_data(api_client.create_jurisdiction(payload, ADMIN))


def create_site(jurisdiction_id, address="1 Test Way", **overrides):
    payload = create_site_payload(jurisdiction_id, address=address, **overrides)
    return get_success_data(api_client.create_site(payload, SITE_MGR))


def create_approved_plan_revision(plan_area_m2=80, required_code_path="PRESCRIPTIVE"):
    """Create a StructuralPlan + one revision, submit and approve it.

    Returns (plan, revision).
    """
    plan = get_success_data(
        api_client.create_structural_plan(
            create_structural_plan_payload(plan_area_m2=plan_area_m2), ENG_SUBMITTER
        )
    )
    revision = get_success_data(
        api_client.create_plan_revision(
            plan["id"],
            create_plan_revision_payload(required_code_path=required_code_path),
            ENG_SUBMITTER,
        )
    )
    get_success_data(
        api_client.plan_revision_action(
            plan["id"], revision["id"], {"action": "SUBMIT"}, ENG_SUBMITTER
        )
    )
    revision = get_success_data(
        api_client.plan_revision_action(
            plan["id"], revision["id"], {"action": "APPROVE"}, ENG_DECIDER
        )
    )
    return plan, revision


def pour_and_cure_foundation(site_id, pour_at, cure_at):
    """REGISTERED → FOUNDATION_POURED at pour_at, then → FOUNDATION_CURED at
    cure_at (>= poured + 72h)."""
    set_clock(pour_at)
    get_success_data(api_client.site_action(site_id, {"action": "POUR_FOUNDATION"}, SITE_MGR))
    set_clock(cure_at)
    return get_success_data(
        api_client.site_action(site_id, {"action": "CONFIRM_CURE"}, SITE_MGR)
    )


def current_site_version(site_id) -> int:
    return get_success_data(api_client.get_site(site_id, PRINT_OP))["version"]


def create_and_qualify_printer(site_id):
    """Create a PrinterSetup and advance ASSEMBLED → LEVELED → QUALIFIED.

    The QUALIFIED advance cascades the site FOUNDATION_CURED → SITE_READY.
    Returns the setup.
    """
    version = current_site_version(site_id)
    setup = get_success_data(
        api_client.create_printer_setup(
            site_id, create_printer_setup_payload(version), PRINT_OP
        )
    )
    get_success_data(
        api_client.advance_printer_setup(site_id, setup["id"], {"to_state": "LEVELED"}, PRINT_OP)
    )
    return get_success_data(
        api_client.advance_printer_setup(site_id, setup["id"], {"to_state": "QUALIFIED"}, PRINT_OP)
    )


def create_qualified_batch(site_id, mix_code="LAVACRETE_A", pump_consistency=50):
    batch = get_success_data(
        api_client.create_material_batch(
            site_id,
            create_material_batch_payload(
                mix_code=mix_code, pump_consistency_kg_per_min=pump_consistency
            ),
            PRINT_OP,
        )
    )
    return get_success_data(
        api_client.qualify_material_batch(site_id, batch["id"], PRINT_OP)
    )


def post_clear_weather(site_id, observed_at):
    return get_success_data(
        api_client.post_weather_observation(
            site_id, create_weather_observation_payload(observed_at), PRINT_OP
        )
    )


def create_approved_permit(site_id, revision_id, requested_path="PRESCRIPTIVE"):
    """Open a permit application, submit it, overpay the fee, and get it
    APPROVED. Requires a jurisdiction that supports the requested path."""
    app = get_success_data(
        api_client.create_permit_application(
            site_id,
            create_permit_application_payload(revision_id, requested_path=requested_path),
            PERMIT_COORD,
        )
    )
    get_success_data(
        api_client.permit_application_action(site_id, app["id"], {"action": "SUBMIT"}, PERMIT_COORD)
    )
    get_success_data(
        api_client.permit_application_action(
            site_id, app["id"], {"action": "PAY_FEE", "amount_cents": 99999999}, PERMIT_COORD
        )
    )
    return get_success_data(
        api_client.permit_application_action(
            site_id, app["id"], {"action": "DECIDE", "decision": "APPROVE"}, JURIS_REVIEWER
        )
    )


# ---------------------------------------------------------------------------
# Tier 2/3: site fully prepared for printing
# ---------------------------------------------------------------------------

def setup_site_ready_for_print(
    plan_area_m2=80,
    pour_at="2026-09-01T00:00:00Z",
    cure_at="2026-09-04T00:00:00Z",
    weather_observed_at="2026-09-04T07:30:00Z",
    mix_code="LAVACRETE_A",
    pump_consistency=50,
    jurisdiction_code="J-READY",
):
    """Full preamble: jurisdiction + approved plan revision + site poured,
    cured, printer QUALIFIED (site → SITE_READY), batch QUALIFIED, clear
    weather posted, permit APPROVED.

    Returns a dict with every artifact a print-job test needs.
    """
    set_clock(pour_at)
    jurisdiction = create_jurisdiction(code=jurisdiction_code)
    plan, revision = create_approved_plan_revision(plan_area_m2=plan_area_m2)
    site = create_site(jurisdiction["id"])
    pour_and_cure_foundation(site["id"], pour_at, cure_at)
    setup = create_and_qualify_printer(site["id"])
    batch = create_qualified_batch(
        site["id"], mix_code=mix_code, pump_consistency=pump_consistency
    )
    weather = post_clear_weather(site["id"], weather_observed_at)
    permit = create_approved_permit(site["id"], revision["id"])
    return {
        "jurisdiction": jurisdiction,
        "plan": plan,
        "revision": revision,
        "site": site,
        "printer_setup": setup,
        "batch": batch,
        "weather": weather,
        "permit": permit,
    }


def schedule_print_job(
    ctx,
    scheduled_start_at="2026-09-04T08:00:00Z",
    scheduled_end_at="2026-09-04T16:00:00Z",
    total_layers_planned=30,
):
    """Create a SCHEDULED PrintJob on the prepared site. Returns the job."""
    site_id = ctx["site"]["id"]
    version = current_site_version(site_id)
    return get_success_data(
        api_client.create_print_job(
            site_id,
            create_print_job_payload(
                ctx["revision"]["id"],
                ctx["printer_setup"]["id"],
                version,
                scheduled_start_at=scheduled_start_at,
                scheduled_end_at=scheduled_end_at,
                total_layers_planned=total_layers_planned,
            ),
            PRINT_OP,
        )
    )


def create_printing_job(ctx, clock_at="2026-09-04T08:00:00Z", **job_overrides):
    """SCHEDULED → READY_TO_PRINT → PRINTING. Returns the PRINTING job."""
    site_id = ctx["site"]["id"]
    job = schedule_print_job(ctx, **job_overrides)
    get_success_data(
        api_client.transition_print_job(site_id, job["id"], {"to_state": "READY_TO_PRINT"}, PRINT_OP)
    )
    set_clock(clock_at)
    return get_success_data(
        api_client.transition_print_job(site_id, job["id"], {"to_state": "PRINTING"}, PRINT_OP)
    )


def record_and_accept_inspection(site_id, job_id, layer_start, layer_end, inspector=None):
    """Record a PASS inspection over the band and ACCEPT it. Returns the
    inspection."""
    recorder = inspector or QUALITY_INSP
    insp = get_success_data(
        api_client.create_layer_inspection(
            site_id,
            job_id,
            create_layer_inspection_payload(
                layer_index_start=layer_start, layer_index_end=layer_end
            ),
            recorder,
        )
    )
    # Segregation of duties (PRD §3.8): the dispositioner must differ from
    # the recorder, so a second inspector identity is used by default.
    disposer = make_quality_inspector_headers("qi-second")
    return get_success_data(
        api_client.disposition_layer_inspection(
            site_id, job_id, insp["id"], {"disposition": "ACCEPTED"}, disposer
        )
    )


def complete_print_job(ctx, job_id, clock_at="2026-09-04T09:00:00Z", layers=None):
    """Inspect-and-accept the full layer band, then transition PRINTING →
    COMPLETED. ``layers`` defaults to the job's total_layers_planned."""
    site_id = ctx["site"]["id"]
    jobs, _meta = validate_paginated(api_client.list_print_jobs(site_id, PRINT_OP))
    job_data = next(j for j in jobs if j["id"] == job_id)
    total = layers if layers is not None else job_data["total_layers_planned"]
    set_clock(clock_at)
    record_and_accept_inspection(site_id, job_id, 1, total)
    return get_success_data(
        api_client.transition_print_job(site_id, job_id, {"to_state": "COMPLETED"}, PRINT_OP)
    )


# ---------------------------------------------------------------------------
# Tier 5: trade-task setup after a completed print
# ---------------------------------------------------------------------------

def create_ready_trade_task(ctx, job_id, earliest_start_at, latest_end_at="2026-09-10T16:00:00Z", **overrides):
    """Create a trade task whose dependencies are already satisfied (print
    COMPLETED, clock at or past earliest_start_at), so it lands in READY."""
    site_id = ctx["site"]["id"]
    version = current_site_version(site_id)
    return get_success_data(
        api_client.create_trade_task(
            site_id,
            create_trade_task_payload(
                job_id,
                version,
                earliest_start_at=earliest_start_at,
                latest_end_at=latest_end_at,
                **overrides,
            ),
            SITE_MGR,
        )
    )
