"""Composite setup helpers.

Each fixture builds its preconditions from scratch against an empty database
(the harness restarts the server before every test). Setup calls use the
lenient get_success_data validator so a failed step raises a clear
"Setup step failed" error instead of a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK
from .factories import (
    create_agreement_payload,
    create_auditorium_payload,
    create_box_office_report_payload,
    create_conversion_order_payload,
    create_film_payload,
    create_market_payload,
    create_qa_alert_payload,
    create_release_window_payload,
    create_screen_slot_payload,
    create_studio_payload,
    create_tech_dispatch_payload,
)
from .test_users import TEST_USERS

# Role header shortcuts used across fixtures.
NP = TEST_USERS["network_planner_headers"]
PCM = TEST_USERS["contract_manager_headers"]
SRM = TEST_USERS["studio_manager_headers"]
PPS = TEST_USERS["post_scheduler_headers"]
QAR = TEST_USERS["qa_reviewer_headers"]
RS = TEST_USERS["release_scheduler_headers"]
BOA = TEST_USERS["box_office_analyst_headers"]
FE = TEST_USERS["field_engineer_headers"]


# --------------------------------------------------------------------------
# Tier 1: state progression
# --------------------------------------------------------------------------

def set_clock(to_iso8601=DEFAULT_CLOCK):
    """Set the logical clock (PRD §2.5). Returns the response data."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, PCM)
    )


def create_approved_market(screen_capacity_cap=5, **overrides):
    """Create a market and walk PROSPECT -> EVALUATING -> APPROVED."""
    market = get_success_data(
        api_client.create_market(
            create_market_payload(screen_capacity_cap=screen_capacity_cap, **overrides), NP)
    )
    get_success_data(api_client.begin_market_evaluation(market["id"], NP))
    get_success_data(api_client.approve_market(market["id"], NP))
    return market


def create_signed_agreement(market_id, **overrides):
    """Create an agreement and sign it (market must be APPROVED+)."""
    agreement = get_success_data(
        api_client.create_agreement(
            create_agreement_payload(market_id=market_id, **overrides), PCM)
    )
    get_success_data(api_client.sign_agreement(agreement["id"], PCM))
    return agreement


def create_active_agreement(market_id, **overrides):
    """Agreement driven to ACTIVE; implies an OPERATING auditorium exists."""
    ctx = create_signed_agreement_with_operating_auditorium(market_id, **overrides)
    get_success_data(api_client.activate_agreement(ctx["agreement"]["id"], PCM))
    return ctx


def create_signed_agreement_with_operating_auditorium(
    market_id, seating_capacity=200, auditorium_label="S1", **agreement_overrides
):
    """Signed agreement plus one auditorium walked DESIGN -> OPERATING."""
    agreement = create_signed_agreement(market_id, **agreement_overrides)
    auditorium = create_operating_auditorium(
        agreement["id"], seating_capacity=seating_capacity,
        auditorium_label=auditorium_label)
    return {"agreement": agreement, "auditorium": auditorium, "market_id": market_id}


def create_operating_auditorium(agreement_id, seating_capacity=200,
                                auditorium_label="S1"):
    """Auditorium walked DESIGN -> CONSTRUCTION -> CALIBRATION -> CERTIFIED
    -> OPERATING. Parent agreement must be SIGNED or ACTIVE."""
    auditorium = get_success_data(
        api_client.create_auditorium(
            create_auditorium_payload(
                agreement_id=agreement_id, seating_capacity=seating_capacity,
                auditorium_label=auditorium_label), PCM)
    )
    get_success_data(api_client.begin_auditorium_construction(auditorium["id"], PCM))
    get_success_data(api_client.begin_auditorium_calibration(auditorium["id"], FE))
    get_success_data(api_client.certify_auditorium(auditorium["id"], FE))
    get_success_data(api_client.open_auditorium(auditorium["id"], PCM))
    return auditorium


def create_certified_auditorium(agreement_id, seating_capacity=200,
                                auditorium_label="S1"):
    """Auditorium walked DESIGN -> CONSTRUCTION -> CALIBRATION -> CERTIFIED
    (stopped before open)."""
    auditorium = get_success_data(
        api_client.create_auditorium(
            create_auditorium_payload(
                agreement_id=agreement_id, seating_capacity=seating_capacity,
                auditorium_label=auditorium_label), PCM)
    )
    get_success_data(api_client.begin_auditorium_construction(auditorium["id"], PCM))
    get_success_data(api_client.begin_auditorium_calibration(auditorium["id"], FE))
    get_success_data(api_client.certify_auditorium(auditorium["id"], FE))
    return auditorium


def create_active_studio(**overrides):
    """Studio walked ONBOARDING -> ACTIVE."""
    studio = get_success_data(
        api_client.create_studio(create_studio_payload(**overrides), SRM)
    )
    get_success_data(api_client.activate_studio(studio["id"], SRM))
    return studio


def create_film(studio_id, **overrides):
    """Register a film (enters ANNOUNCED)."""
    return get_success_data(
        api_client.create_film(create_film_payload(studio_id=studio_id, **overrides), SRM)
    )


def create_conversion_order(film_id, **overrides):
    """Submit a conversion order (enters SUBMITTED; cost estimate computed)."""
    return get_success_data(
        api_client.create_conversion_order(
            create_conversion_order_payload(studio_film_id=film_id, **overrides), SRM)
    )


def create_approved_conversion(film_id, qc_at="2026-09-04T00:00:00Z", **overrides):
    """Conversion order walked SUBMITTED -> IN_POST -> QC_REVIEW
    -> APPROVED_FOR_RELEASE."""
    order = create_conversion_order(film_id, **overrides)
    get_success_data(api_client.begin_post(order["id"], PPS))
    set_clock(qc_at)
    get_success_data(api_client.submit_for_qc(order["id"], PPS))
    get_success_data(api_client.approve_release(order["id"], QAR))
    return order


def create_open_window(**overrides):
    """Release window walked DRAFT -> OPEN_FOR_BOOKING.

    The open transition mutates the window (PRD §2.4 increments `version`),
    so the returned snapshot comes from the OPEN response to carry the
    current `version` and `updated_at`."""
    window = get_success_data(
        api_client.create_release_window(create_release_window_payload(**overrides), RS)
    )
    return get_success_data(api_client.open_release_window(window["id"], RS))


def propose_slot(window_id, auditorium_id, film_id, conversion_id, **overrides):
    """Create a PROPOSED slot. The window's current version is read fresh to
    satisfy the OCC field unless expected_window_version is overridden."""
    if "expected_window_version" not in overrides:
        window = get_success_data(api_client.get_release_window(window_id, RS))
        overrides["expected_window_version"] = window["version"]
    return get_success_data(
        api_client.create_screen_slot(
            create_screen_slot_payload(
                window_id=window_id, auditorium_id=auditorium_id,
                studio_film_id=film_id, conversion_order_id=conversion_id,
                **overrides), RS)
    )


def create_confirmed_slot(window_id, auditorium_id, film_id, conversion_id,
                          **overrides):
    """Create a slot and confirm it (PROPOSED -> CONFIRMED)."""
    slot = propose_slot(window_id, auditorium_id, film_id, conversion_id, **overrides)
    get_success_data(api_client.confirm_slot(slot["id"], RS))
    return slot


# --------------------------------------------------------------------------
# Tier 2: entity hierarchy — the standard end-to-end scenario
# --------------------------------------------------------------------------

def setup_bookable_scenario(screen_capacity_cap=5, seating_capacity=200,
                            window_pool_seconds=10000000,
                            window_start="2026-09-07T00:00:00Z",
                            window_end="2026-09-14T00:00:00Z",
                            runtime_minutes=100, agreement_overrides=None,
                            window_label="W37"):
    """The common preamble: market APPROVED, agreement ACTIVE with one
    OPERATING auditorium, studio ACTIVE, one film, one APPROVED_FOR_RELEASE
    conversion, and one OPEN_FOR_BOOKING window. Clock is left at
    2026-09-04 (the approval instant)."""
    set_clock(DEFAULT_CLOCK)
    market = create_approved_market(screen_capacity_cap=screen_capacity_cap)
    ctx = create_active_agreement(
        market["id"], seating_capacity=seating_capacity,
        **(agreement_overrides or {}))
    studio = create_active_studio()
    film = create_film(studio["id"], runtime_minutes=runtime_minutes)
    conversion = create_approved_conversion(film["id"])
    window = create_open_window(
        window_label=window_label, window_start_date=window_start,
        window_end_date=window_end,
        total_premium_screen_seconds_pool=window_pool_seconds)
    return {
        "market": market,
        "agreement": ctx["agreement"],
        "auditorium": ctx["auditorium"],
        "studio": studio,
        "film": film,
        "conversion": conversion,
        "window": window,
    }


def setup_confirmed_slot_scenario(**kwargs):
    """Standard scenario plus one CONFIRMED slot covering the whole window."""
    ctx = setup_bookable_scenario(**kwargs)
    slot = create_confirmed_slot(
        ctx["window"]["id"], ctx["auditorium"]["id"], ctx["film"]["id"],
        ctx["conversion"]["id"],
        slot_start_date=ctx["window"]["window_start_date"],
        slot_end_date=ctx["window"]["window_end_date"])
    ctx["slot"] = slot
    return ctx


def create_validated_report(slot_id, reported_date="2026-09-07T00:00:00Z",
                            gross_receipts_cents=1000000, admissions=100):
    """Submit a report and validate it (RECEIVED -> VALIDATED)."""
    report = get_success_data(
        api_client.create_box_office_report(
            create_box_office_report_payload(
                screen_slot_id=slot_id, reported_date=reported_date,
                gross_receipts_cents=gross_receipts_cents, admissions=admissions),
            BOA)
    )
    get_success_data(api_client.validate_report(report["id"], BOA))
    return report


def create_draft_statement(agreement_id, window_id):
    """Create a DRAFT revenue-share statement."""
    return get_success_data(
        api_client.create_statement(
            {"agreement_id": agreement_id, "window_id": window_id}, BOA)
    )


# --------------------------------------------------------------------------
# Tier 4/5: QA pipeline and resolution
# --------------------------------------------------------------------------

def raise_critical_alert(auditorium_id, alert_code="PROJECTOR_TEMP"):
    """Raise a CRITICAL alert; against an OPERATING auditorium this degrades
    the auditorium and suspends its active slots (PRD §2.8 cascade)."""
    return get_success_data(
        api_client.create_qa_alert(
            create_qa_alert_payload(
                auditorium_id=auditorium_id, alert_code=alert_code,
                severity="CRITICAL"), FE)
    )


def resolve_alert_via_dispatch(alert_id, auditorium_id,
                               visit_date="2026-09-08T00:00:00Z",
                               resolution_notes="replaced lamp"):
    """Acknowledge the alert, run a dispatch SCHEDULED -> EN_ROUTE -> ON_SITE
    -> COMPLETE; the alert auto-resolves when no non-terminal dispatches
    remain (PRD §3.7)."""
    get_success_data(api_client.acknowledge_alert(alert_id, FE))
    dispatch = get_success_data(
        api_client.create_tech_dispatch(
            create_tech_dispatch_payload(
                qa_alert_id=alert_id, auditorium_id=auditorium_id,
                scheduled_visit_date=visit_date), FE)
    )
    get_success_data(api_client.mark_dispatch_en_route(dispatch["id"], FE))
    get_success_data(api_client.mark_dispatch_on_site(dispatch["id"], FE))
    get_success_data(
        api_client.complete_dispatch(
            dispatch["id"], {"resolution_notes": resolution_notes}, FE)
    )
    return dispatch
