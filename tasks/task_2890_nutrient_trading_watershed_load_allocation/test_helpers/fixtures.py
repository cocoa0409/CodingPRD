"""Composite state builders.

The server is restarted with an empty database before every individual test, so
every one of these builders drives real PRD endpoints from scratch. They are
plain functions rather than pytest fixtures so a test can compose exactly the
layers it needs and stop at the state it wants to probe.

Layering
--------
L0  pin the logical clock
L1  watershed
L2  reach network
L3  assessment + inventoried sources
L4  ACTIVE allocation run
L5  PUBLIC_COMMENT -> APPROVED (watershed becomes ACTIVE, trading opens)
L6  permit + derive-limits + annual-report
L7  producer + practice project + baseline/implementation verification
L8  certification (batch ISSUED) + listing (batch LISTED)
L9  credit transaction proposal / approval

All returned values are the API's own response bodies, so a test asserts against
what the server actually stored rather than against a local reconstruction.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import CLOCK_BASE
from .test_users import (
    ADMIN,
    ANALYST,
    BASELINE_VERIFIER,
    IMPLEMENTATION_VERIFIER,
    PERMITTEE_1,
    PERMIT_WRITER,
    REGISTRY,
    REVERIFICATION_VERIFIER,
    make_permittee_headers,
    make_producer_headers,
)

# ---------------------------------------------------------------------------
# Canonical Scioto Headwaters (SCR) topology, reused by most chains.
# ---------------------------------------------------------------------------
SCR_NAME = "Scioto Headwaters"
SCR_STATE = "OH"
SCR_CODE = "SCR"
SCR_POLLUTANT = "TOTAL_PHOSPHORUS"
SCR_BASELINE_YEAR = 2020
SCR_BASELINE_LOAD = 120000.00
SCR_ZONES = ["Z1", "Z2"]

TMDL_CODE = "TMDL-P-2026"
TMDL_LOADING_CAPACITY = 60000.00
TMDL_MOS_PCT = 0.1000
TMDL_BACKGROUND = 6000.00
TMDL_PERIOD_START = "2026-01-01"
TMDL_PERIOD_END = "2035-12-31"


# ---------------------------------------------------------------- L0: the clock
def pin_clock(api: ApiClient, instant: str = CLOCK_BASE, headers: Dict[str, str] = ADMIN) -> str:
    """Pin the logical program clock so every server-written instant is predictable."""
    get_success_data(api.set_clock(instant, headers))
    return instant


# ------------------------------------------------------------- L1: the watershed
def make_watershed(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Register one watershed and return the created row."""
    return get_success_data(api.create_watershed(f.watershed_payload(**kwargs), ADMIN), 201)


def scr_watershed(api: ApiClient) -> Dict[str, Any]:
    """The canonical SCR watershed with all four program parameters stated explicitly."""
    return make_watershed(
        api,
        name=SCR_NAME,
        state_code=SCR_STATE,
        watershed_code=SCR_CODE,
        pollutant=SCR_POLLUTANT,
        baseline_year=SCR_BASELINE_YEAR,
        baseline_load_lbs_yr=SCR_BASELINE_LOAD,
        eligible_zone_codes=list(SCR_ZONES),
        interim_target_pct=25.00,
        uncertainty_ratio=2.0000,
        retirement_ratio=0.1000,
        equivalence_ratio=1.0000,
    )


def set_program_status(
    api: ApiClient, watershed_id: str, target_status: str, reason: Optional[str] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.set_program_status(
            watershed_id, f.program_status_payload(target_status, reason), ADMIN
        )
    )


# ----------------------------------------------------------- L2: the reach network
def make_reach(api: ApiClient, watershed_id: str, reach_code: str, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_reach(f.reach_payload(watershed_id, reach_code, **kwargs), ANALYST), 201
    )


def scr_reaches(api: ApiClient, watershed_id: str, with_background: bool = False) -> Dict[str, Any]:
    """Build the SCR hydrology: R_UP -> R_MID -> R_OUT, optionally plus R_BG -> R_MID.

    R_OUT is the outlet and the compliance point, R_MID is the mainstem it drains
    to, R_UP is the headwater above that, and R_BG is the background reach that
    supplies the monitored background load for the FINAL allocation variant. R_BG
    sits in trading zone Z3, which is deliberately *outside* the watershed's
    eligible zones.
    """
    r_out = make_reach(
        api,
        watershed_id,
        "R_OUT",
        trading_zone_code="Z2",
        reach_class="COMPLIANCE_POINT",
        delivery_factor=1.0000,
    )
    r_mid = make_reach(
        api,
        watershed_id,
        "R_MID",
        trading_zone_code="Z2",
        reach_class="MAINSTEM",
        delivery_factor=0.9000,
        downstream_reach_id=r_out["id"],
    )
    r_up = make_reach(
        api,
        watershed_id,
        "R_UP",
        trading_zone_code="Z1",
        reach_class="HEADWATER",
        delivery_factor=0.8000,
        downstream_reach_id=r_mid["id"],
    )
    reaches = {"r_out": r_out, "r_mid": r_mid, "r_up": r_up}
    if with_background:
        reaches["r_bg"] = make_reach(
            api,
            watershed_id,
            "R_BG",
            trading_zone_code="Z3",
            reach_class="BACKGROUND",
            delivery_factor=0.7000,
            downstream_reach_id=r_mid["id"],
        )
    return reaches


# ------------------------------------------------- L3: assessment and its sources
def make_assessment(api: ApiClient, watershed_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_tmdl_assessment(f.tmdl_assessment_payload(watershed_id, **kwargs), ANALYST),
        201,
    )


def make_source(
    api: ApiClient,
    assessment_id: str,
    reach_id: str,
    source_name: str,
    source_type: str,
    existing_load_lbs_yr: float,
    controllability_index: float,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_source_assessment(
            f.source_assessment_payload(
                assessment_id,
                reach_id,
                source_name,
                source_type,
                existing_load_lbs_yr,
                controllability_index,
                status,
            ),
            ANALYST,
        ),
        201,
    )


def scr_sources(
    api: ApiClient, assessment_id: str, reaches: Dict[str, Any]
) -> Dict[str, Any]:
    """The four INVENTORIED sources: two POINT then two NONPOINT.

    Created in the order the allocation waterfall will also rank them, which is
    `existing_load_lbs_yr` descending within each source family.
    """
    sa_p1 = make_source(
        api, assessment_id, reaches["r_mid"]["id"], "City WWTP", "POINT", 20000.00, 0.8000
    )
    sa_p2 = make_source(
        api, assessment_id, reaches["r_out"]["id"], "Village WWTP", "POINT", 5000.00, 0.5000
    )
    sa_n1 = make_source(
        api, assessment_id, reaches["r_up"]["id"], "Upper Cropland", "NONPOINT", 30000.00, 0.4000
    )
    sa_n2 = make_source(
        api, assessment_id, reaches["r_up"]["id"], "Upper Pasture", "NONPOINT", 10000.00, 0.3000
    )
    return {"sa_p1": sa_p1, "sa_p2": sa_p2, "sa_n1": sa_n1, "sa_n2": sa_n2}


# ------------------------------------------------------ L4: the allocation run
def read_assessment_version(api: ApiClient, assessment_id: str) -> int:
    """Re-read the assessment so the caller declares a fresh `expected_tmdl_assessment_version`."""
    return get_success_data(api.get_tmdl_assessment(assessment_id, ANALYST))["version"]


def make_allocation_run(
    api: ApiClient,
    assessment_id: str,
    run_label: str,
    method: str = "PRO_RATA_BY_EXISTING_LOAD",
    expected_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Execute an allocation run, declaring the assessment version it commits against."""
    if expected_version is None:
        expected_version = read_assessment_version(api, assessment_id)
    return get_success_data(
        api.create_allocation_run(
            assessment_id, f.allocation_run_payload(run_label, expected_version, method), ANALYST
        ),
        201,
    )


# ------------------------------------------------------- L5: assessment approval
def publish_assessment(api: ApiClient, assessment_id: str) -> Dict[str, Any]:
    """DRAFT -> PUBLIC_COMMENT; requires at least one INVENTORIED or ADJUSTED source."""
    return get_success_data(
        api.set_assessment_status(
            assessment_id, f.assessment_status_payload("PUBLIC_COMMENT"), ANALYST
        )
    )


def approve_assessment(api: ApiClient, assessment_id: str) -> Dict[str, Any]:
    """PUBLIC_COMMENT -> APPROVED; requires at least one ACTIVE allocation run."""
    return get_success_data(
        api.set_assessment_status(
            assessment_id, f.assessment_status_payload("APPROVED"), ADMIN
        )
    )


def publish_and_approve(api: ApiClient, assessment_id: str) -> Dict[str, Any]:
    publish_assessment(api, assessment_id)
    return approve_assessment(api, assessment_id)


# ------------------------------------------------------------------- L6: permits
def make_permit(
    api: ApiClient,
    watershed_id: str,
    source_assessment_id: str,
    permit_number: str = "OH0012345",
    permittee_user_id: str = "user-permittee-1",
    **kwargs: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_permit(
            f.permit_payload(
                watershed_id, source_assessment_id, permit_number, permittee_user_id, **kwargs
            ),
            PERMIT_WRITER,
        ),
        201,
    )


def derive_limits(api: ApiClient, permit_id: str) -> Dict[str, Any]:
    return get_success_data(api.derive_limits(permit_id, PERMIT_WRITER))


def finalize_limits(api: ApiClient, permit_id: str) -> Dict[str, Any]:
    return get_success_data(api.finalize_limits(permit_id, PERMIT_WRITER))


def file_annual_report(
    api: ApiClient,
    permit_id: str,
    reported_annual_load_lbs: float,
    reporting_period_year: int = 2026,
    permittee_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.file_annual_report(
            permit_id,
            f.annual_report_payload(reported_annual_load_lbs, reporting_period_year),
            permittee_headers or PERMITTEE_1,
        )
    )


def permit_in_shortfall(
    api: ApiClient,
    watershed_id: str,
    source_assessment_id: str,
    permit_number: str = "OH0012345",
    permittee_user_id: str = "user-permittee-1",
    reported_annual_load_lbs: float = 25000.00,
    reporting_period_year: int = 2026,
    **permit_kwargs: Any
) -> Dict[str, Any]:
    """Permit + derive-limits + annual report, leaving the permit in SHORTFALL.

    Against the canonical SCR allocation this reports 25000.00 lbs against an
    applicable interim limit of 23916.00, i.e. a compliance gap of 1084.00.
    """
    permit = make_permit(
        api,
        watershed_id,
        source_assessment_id,
        permit_number=permit_number,
        permittee_user_id=permittee_user_id,
        **permit_kwargs
    )
    derive_limits(api, permit["id"])
    return file_annual_report(
        api,
        permit["id"],
        reported_annual_load_lbs,
        reporting_period_year,
        make_permittee_headers(permittee_user_id),
    )


# ------------------------------------------- L7: producers, projects, verification
def make_producer(api: ApiClient, headers: Dict[str, str] = ADMIN, **kwargs: Any) -> Dict[str, Any]:
    """Enrol a producer; the minted `id` becomes that producer's own `X-User-ID`."""
    return get_success_data(api.create_producer(f.producer_payload(**kwargs), headers), 201)


def make_practice_project(
    api: ApiClient, producer_id: str, reach_id: str, tract_code: str, **kwargs: Any
) -> Dict[str, Any]:
    """Register a practice project as the owning producer itself."""
    return get_success_data(
        api.create_practice_project(
            f.practice_project_payload(producer_id, reach_id, tract_code, **kwargs),
            make_producer_headers(producer_id),
        ),
        201,
    )


def file_verification_event(
    api: ApiClient,
    project_id: str,
    event_type: str,
    outcome: str,
    headers: Dict[str, str],
    verified_acres: Optional[float] = None,
    narrative: str = "Field inspection completed and documented.",
) -> Dict[str, Any]:
    return get_success_data(
        api.create_verification_event(
            f.verification_event_payload(
                project_id, event_type, outcome, narrative, verified_acres
            ),
            headers,
        ),
        201,
    )


def verify_baseline_pass(api: ApiClient, project_id: str) -> Dict[str, Any]:
    """BASELINE / PASS by verifier-1, recorded in `baseline_verifier_user_id`."""
    return file_verification_event(
        api, project_id, "BASELINE", "PASS", BASELINE_VERIFIER
    )


def verify_implementation_pass(
    api: ApiClient, project_id: str, verified_acres: float
) -> Dict[str, Any]:
    """IMPLEMENTATION / PASS by verifier-2 — a different principal from the
    baseline verifier, as segregation of duties requires."""
    return file_verification_event(
        api,
        project_id,
        "IMPLEMENTATION",
        "PASS",
        IMPLEMENTATION_VERIFIER,
        verified_acres=verified_acres,
    )


def reverify(
    api: ApiClient, project_id: str, outcome: str, verified_acres: Optional[float] = None
) -> Dict[str, Any]:
    """REVERIFICATION by verifier-3, a third distinct principal."""
    return file_verification_event(
        api,
        project_id,
        "REVERIFICATION",
        outcome,
        REVERIFICATION_VERIFIER,
        verified_acres=verified_acres,
    )


def implemented_project(
    api: ApiClient,
    producer_id: str,
    reach_id: str,
    tract_code: str,
    verified_acres: float = 80.00,
    **project_kwargs: Any
) -> Dict[str, Any]:
    """Register, baseline-pass and implementation-pass one project.

    Returns the project row as read back after the implementation event, so
    `verified_acres` and both verifier ids are populated.
    """
    project = make_practice_project(api, producer_id, reach_id, tract_code, **project_kwargs)
    verify_baseline_pass(api, project["id"])
    verify_implementation_pass(api, project["id"], verified_acres)
    return get_success_data(api.get_practice_project(project["id"], REGISTRY))


# --------------------------------------------------- L8: certification and listing
def certify_project(api: ApiClient, project_id: str) -> Dict[str, Any]:
    """Certify an IMPLEMENTED project as registry-1 and return the minted batch.

    registry-1 differs from both verifier-1 and verifier-2, which is what the
    certification segregation-of-duties check requires.
    """
    return get_success_data(api.certify_practice_project(project_id, REGISTRY), 201)


def list_batch(api: ApiClient, batch_id: str) -> Dict[str, Any]:
    """ISSUED -> LISTED. Only a LISTED batch may have a transaction approved."""
    return get_success_data(api.list_credit_batch(batch_id, REGISTRY))


def retire_batch(api: ApiClient, batch_id: str, retire_lbs: float, reason: str = "Program retirement") -> Dict[str, Any]:
    return get_success_data(
        api.retire_credit_batch(batch_id, f.retire_payload(retire_lbs, reason), REGISTRY)
    )


def read_batch_version(api: ApiClient, batch_id: str) -> int:
    """Re-read the batch so the caller declares a fresh `expected_credit_batch_version`."""
    return get_success_data(api.get_credit_batch(batch_id, REGISTRY))["version"]


def listed_batch(
    api: ApiClient,
    producer_id: str,
    reach_id: str,
    tract_code: str,
    verified_acres: float = 80.00,
    **project_kwargs: Any
) -> Dict[str, Any]:
    """Drive one project all the way to a LISTED, tradable batch.

    Returns {"project": ..., "batch": ...} with both rows as last written.
    """
    project = implemented_project(
        api, producer_id, reach_id, tract_code, verified_acres, **project_kwargs
    )
    batch = certify_project(api, project["id"])
    batch = list_batch(api, batch["id"])
    project = get_success_data(api.get_practice_project(project["id"], REGISTRY))
    return {"project": project, "batch": batch}


# ----------------------------------------------------- L9: credit transactions
def propose_transaction(
    api: ApiClient,
    batch_id: str,
    permit_id: str,
    requested_gross_lbs: float,
    reporting_period_year: int = 2026,
    expected_batch_version: Optional[int] = None,
    permittee_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    if expected_batch_version is None:
        expected_batch_version = read_batch_version(api, batch_id)
    return get_success_data(
        api.propose_credit_transaction(
            f.credit_transaction_payload(
                batch_id,
                permit_id,
                requested_gross_lbs,
                reporting_period_year,
                expected_batch_version,
            ),
            permittee_headers or PERMITTEE_1,
        ),
        201,
    )


def approve_transaction(api: ApiClient, txn_id: str) -> Dict[str, Any]:
    return get_success_data(api.approve_credit_transaction(txn_id, REGISTRY))


def void_transaction(api: ApiClient, txn_id: str, reason: str = "REGISTRY_ACTION") -> Dict[str, Any]:
    return get_success_data(api.void_credit_transaction(txn_id, f.void_payload(reason), REGISTRY))


# --------------------------------------------------------------- adaptive reviews
def make_adaptive_review(
    api: ApiClient, watershed_id: str, review_label: str, start: str, end: str
) -> Dict[str, Any]:
    return get_success_data(
        api.create_adaptive_review(
            watershed_id, f.adaptive_review_payload(review_label, start, end), ADMIN
        ),
        201,
    )


def finalize_adaptive_review(api: ApiClient, review_id: str) -> Dict[str, Any]:
    return get_success_data(api.finalize_adaptive_review(review_id, ADMIN))


def make_sample(
    api: ApiClient,
    reach_id: str,
    sample_datetime: str,
    measured_conc_mg_l: float,
    flow_cfs: float,
    qa_status: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_monitoring_sample(
            f.monitoring_sample_payload(
                reach_id, sample_datetime, measured_conc_mg_l, flow_cfs, qa_status
            ),
            ANALYST,
        ),
        201,
    )


# ---------------------------------------------------------------------------
# Top-level composites
# ---------------------------------------------------------------------------
def scr_base(
    api: ApiClient,
    with_background: bool = False,
    clock: str = CLOCK_BASE,
    sources: bool = True,
) -> Dict[str, Any]:
    """L0-L3: clock, SCR watershed, reach network, DRAFT assessment and its sources.

    Returns a world dict with keys `watershed`, `reaches`, `assessment` and, when
    `sources` is true, `sources` plus the four individual source rows.
    """
    pin_clock(api, clock)
    watershed = scr_watershed(api)
    reaches = scr_reaches(api, watershed["id"], with_background=with_background)
    assessment = make_assessment(
        api,
        watershed["id"],
        assessment_code=TMDL_CODE,
        loading_capacity_lbs_yr=TMDL_LOADING_CAPACITY,
        margin_of_safety_pct=TMDL_MOS_PCT,
        background_load_lbs_yr=TMDL_BACKGROUND,
        period_start_date=TMDL_PERIOD_START,
        period_end_date=TMDL_PERIOD_END,
    )
    world: Dict[str, Any] = {
        "watershed": watershed,
        "watershed_id": watershed["id"],
        "reaches": reaches,
        "assessment": assessment,
        "assessment_id": assessment["id"],
    }
    if sources:
        world["sources"] = scr_sources(api, assessment["id"], reaches)
        world.update(world["sources"])
    return world


def scr_allocated(
    api: ApiClient,
    with_background: bool = False,
    run_label: str = "RUN-1",
    method: str = "PRO_RATA_BY_EXISTING_LOAD",
    clock: str = CLOCK_BASE,
) -> Dict[str, Any]:
    """L0-L4: the SCR base plus one ACTIVE PROVISIONAL allocation run."""
    world = scr_base(api, with_background=with_background, clock=clock)
    world["run"] = make_allocation_run(api, world["assessment_id"], run_label, method)
    world["run_id"] = world["run"]["id"]
    return world


def scr_active_program(
    api: ApiClient,
    with_background: bool = False,
    run_label: str = "RUN-1",
    method: str = "PRO_RATA_BY_EXISTING_LOAD",
    clock: str = CLOCK_BASE,
) -> Dict[str, Any]:
    """L0-L5: allocation run in place and the assessment APPROVED.

    Approving the watershed's first assessment is the only way the program opens
    for trading, so on return `program_status` is ACTIVE and `trading_enabled` true.
    """
    world = scr_allocated(
        api, with_background=with_background, run_label=run_label, method=method, clock=clock
    )
    world["assessment"] = publish_and_approve(api, world["assessment_id"])
    world["watershed"] = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    return world


def scr_trading_ready(
    api: ApiClient,
    reported_annual_load_lbs: float = 25000.00,
    clock: str = CLOCK_BASE,
) -> Dict[str, Any]:
    """L0-L8: an ACTIVE program, a permit in SHORTFALL, and a LISTED credit batch.

    The permit is written against City WWTP (the R_MID point source) and reports
    25000.00 lbs against its interim limit. The batch is generated by practice
    project PP-A on tract T-101, one reach above the buyer, so the trade has a
    genuine downstream delivery path to walk.
    """
    world = scr_active_program(api)
    world["permit"] = permit_in_shortfall(
        api,
        world["watershed_id"],
        world["sa_p1"]["id"],
        reported_annual_load_lbs=reported_annual_load_lbs,
    )
    world["permit_id"] = world["permit"]["id"]
    world["producer"] = make_producer(api)
    world["producer_id"] = world["producer"]["id"]
    listed = listed_batch(
        api, world["producer_id"], world["reaches"]["r_up"]["id"], "T-101"
    )
    world["project"] = listed["project"]
    world["project_id"] = listed["project"]["id"]
    world["batch"] = listed["batch"]
    world["batch_id"] = listed["batch"]["id"]
    world["watershed"] = get_success_data(api.get_watershed(world["watershed_id"], ADMIN))
    return world
