"""Composite bootstrap helpers.

The API server is restarted before every test, so each test begins against an
empty database and must build every row it needs. These helpers do that by
driving real endpoints only — never by reaching behind the API — so the state
they produce is exactly the state the contract describes.

Every helper that plans a packaging run reads the batch back first, because
§3.3 says creating a run increments the owning batch's ``version``, so a second
run planned from a stale observed version would fail the §2.7 concurrency
guard.
"""

from typing import Any, Dict, Optional, Tuple

from prd_bench_local_runner.testing import validate_success

from . import factories as f
from .api_client import ApiClient
from .constants import (
    CLOCK_DEFAULT_UTC,
    DECISION_APPROVED,
    DESTINATION_DISTRIBUTION,
    DESTINATION_TAPROOM,
    FILING_LABEL,
    KEG_SIZE_HALF_BBL,
    LICENSE_SELF_DISTRIBUTION,
    MOVEMENT_TAP,
    NOTICE_ACTION_ACTIVATE,
    PACKAGE_HALF_BBL_KEG,
    PERMIT_DECISION_APPROVED,
)
from .test_users import ADMIN, CELLAR, COMPLIANCE, COMPLIANCE_2, REGULATOR, TAPROOM


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(api: ApiClient, instant: str, headers: Dict[str, str] = ADMIN) -> None:
    """Move the server's logical clock (§2.5). Any of the five roles may do it."""
    validate_success(api.set_clock(instant, headers))


def reset_clock(api: ApiClient, headers: Dict[str, str] = ADMIN) -> None:
    """Return the logical clock to its documented default of 2026-08-01T00:00:00Z."""
    set_clock(api, CLOCK_DEFAULT_UTC, headers)


# ---------------------------------------------------------------------------
# Brewery (§3.1)
# ---------------------------------------------------------------------------
def create_brewery(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Create the brewery singleton; it opens in PENDING_NOTICE."""
    return validate_success(
        api.create_brewery(f.brewery_payload(**overrides), ADMIN), 201
    )


def bootstrap_brewery(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Create the brewery and drive its notice to ACTIVE."""
    create_brewery(api, **overrides)
    return validate_success(
        api.drive_notice(f.notice_payload(NOTICE_ACTION_ACTIVATE), REGULATOR)
    )


def suspend_notice(api: ApiClient, reason: str = "Records audit") -> Dict[str, Any]:
    return validate_success(
        api.drive_notice(f.notice_payload("SUSPEND", reason=reason), REGULATOR)
    )


def reinstate_notice(api: ApiClient) -> Dict[str, Any]:
    return validate_success(api.drive_notice(f.notice_payload("REINSTATE"), REGULATOR))


def set_brewery_carry_in(
    api: ApiClient, taproom_bbl: float = 0.000, distribution_bbl: float = 0.000
) -> Dict[str, Any]:
    """Record pre-go-live barrels via carry_in_taproom_bbl / carry_in_distribution_bbl."""
    return validate_success(
        api.set_brewery_ytd_adjustments(
            f.brewery_ytd_payload(taproom_bbl, distribution_bbl), COMPLIANCE
        )
    )


# ---------------------------------------------------------------------------
# Beers (§3.1)
# ---------------------------------------------------------------------------
def create_exempt_beer(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """A beer with requires_formula false, minted directly in FORMULA_EXEMPT."""
    return validate_success(
        api.create_beer(f.exempt_beer_payload(**overrides), ADMIN), 201
    )


def create_draft_beer(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """A beer with requires_formula defaulted to true, minted in DRAFT."""
    return validate_success(api.create_beer(f.beer_payload(**overrides), ADMIN), 201)


def approve_formula(api: ApiClient, beer_id: str) -> Dict[str, Any]:
    """Drive the formula dimension DRAFT -> FORMULA_PENDING -> FORMULA_APPROVED."""
    validate_success(
        api.create_beer_filing(beer_id, f.formula_filing_payload(), COMPLIANCE)
    )
    return validate_success(
        api.decide_beer_filing(
            beer_id, "FORMULA", f.filing_decision_payload(DECISION_APPROVED), REGULATOR
        )
    )


def approve_label(
    api: ApiClient, beer_id: str, cola_id: str = "COLA-2026-0001"
) -> Dict[str, Any]:
    """Drive the label dimension NO_LABEL -> COLA_PENDING -> COLA_APPROVED."""
    validate_success(
        api.create_beer_filing(beer_id, f.label_filing_payload(), COMPLIANCE)
    )
    return validate_success(
        api.decide_beer_filing(
            beer_id,
            FILING_LABEL,
            f.filing_decision_payload(DECISION_APPROVED, cola_id=cola_id),
            REGULATOR,
        )
    )


def create_distribution_ready_beer(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """A FORMULA_EXEMPT beer whose label_state is COLA_APPROVED.

    §3.1: distribution_sellable is true exactly when the notice is ACTIVE, the
    registration_state is FORMULA_APPROVED or FORMULA_EXEMPT, and the
    label_state is COLA_APPROVED.
    """
    beer = create_exempt_beer(api, **overrides)
    return approve_label(api, beer["id"])


# ---------------------------------------------------------------------------
# Tanks and batches (§3.2)
# ---------------------------------------------------------------------------
def create_tank(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return validate_success(api.create_tank(f.tank_payload(**overrides), CELLAR), 201)


def create_scheduled_batch(
    api: ApiClient, beer_id: str, tank_id: str, **overrides: Any
) -> Dict[str, Any]:
    return validate_success(
        api.create_batch(f.batch_payload(beer_id, tank_id, **overrides), CELLAR), 201
    )


def create_conditioning_batch(
    api: ApiClient,
    beer_id: str,
    tank_id: str,
    actual_yield_bbl: float = 16.000,
    **overrides: Any,
) -> Dict[str, Any]:
    """Schedule, start and condition a batch, leaving it in CONDITIONING."""
    batch = create_scheduled_batch(api, beer_id, tank_id, **overrides)
    validate_success(api.start_batch(batch["id"], CELLAR))
    return validate_success(
        api.condition_batch(
            batch["id"], f.condition_payload(actual_yield_bbl), CELLAR
        )
    )


def batch_version(api: ApiClient, batch_id: str) -> int:
    """Read the batch's current version for the §2.7 concurrency guard."""
    return validate_success(api.get_batch(batch_id, CELLAR))["version"]


# ---------------------------------------------------------------------------
# Packaging runs (§3.3)
# ---------------------------------------------------------------------------
def plan_run(
    api: ApiClient,
    batch_id: str,
    package_type: str = PACKAGE_HALF_BBL_KEG,
    destination: str = DESTINATION_DISTRIBUTION,
    units_planned: int = 10,
    **overrides: Any,
) -> Dict[str, Any]:
    """Plan a run, reading the batch's version back first."""
    payload = f.packaging_run_payload(
        batch_id,
        batch_version(api, batch_id),
        package_type=package_type,
        destination=destination,
        units_planned=units_planned,
        **overrides,
    )
    return validate_success(api.create_packaging_run(payload, CELLAR), 201)


def complete_run(
    api: ApiClient, run_id: str, units_produced: int = 10
) -> Dict[str, Any]:
    return validate_success(
        api.complete_packaging_run(
            run_id, f.complete_run_payload(units_produced), CELLAR
        )
    )


def create_completed_run(
    api: ApiClient,
    batch_id: str,
    package_type: str = PACKAGE_HALF_BBL_KEG,
    destination: str = DESTINATION_DISTRIBUTION,
    units_planned: int = 10,
    units_produced: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Plan and certify a run in one step."""
    run = plan_run(
        api,
        batch_id,
        package_type=package_type,
        destination=destination,
        units_planned=units_planned,
        **overrides,
    )
    produced = units_planned if units_produced is None else units_produced
    return complete_run(api, run["id"], produced)


# ---------------------------------------------------------------------------
# Keg assets (§3.4)
# ---------------------------------------------------------------------------
def create_keg(
    api: ApiClient, size_bbl: float = KEG_SIZE_HALF_BBL, **overrides: Any
) -> Dict[str, Any]:
    return validate_success(
        api.create_keg_asset(f.keg_asset_payload(size_bbl, **overrides), CELLAR), 201
    )


def create_cleaned_keg(
    api: ApiClient, size_bbl: float = KEG_SIZE_HALF_BBL, **overrides: Any
) -> Dict[str, Any]:
    keg = create_keg(api, size_bbl, **overrides)
    return validate_success(
        api.clean_keg_asset(keg["id"], f.keg_clean_payload(), CELLAR)
    )


def create_filled_keg(
    api: ApiClient,
    packaging_run_id: str,
    size_bbl: float = KEG_SIZE_HALF_BBL,
    **overrides: Any,
) -> Dict[str, Any]:
    keg = create_cleaned_keg(api, size_bbl, **overrides)
    return validate_success(
        api.fill_keg_asset(keg["id"], f.keg_fill_payload(packaging_run_id), CELLAR)
    )


def create_tapped_keg(
    api: ApiClient,
    packaging_run_id: str,
    size_bbl: float = KEG_SIZE_HALF_BBL,
    **overrides: Any,
) -> Dict[str, Any]:
    """A keg cleaned, filled from the named run, and tapped for the taproom."""
    keg = create_filled_keg(api, packaging_run_id, size_bbl, **overrides)
    return validate_success(
        api.move_keg_asset(keg["id"], f.keg_movement_payload(MOVEMENT_TAP), TAPROOM)
    )


# ---------------------------------------------------------------------------
# State licences and appointments (§3.6)
# ---------------------------------------------------------------------------
def create_license(
    api: ApiClient,
    state_code: str = "WA",
    license_type: str = LICENSE_SELF_DISTRIBUTION,
    **overrides: Any,
) -> Dict[str, Any]:
    return validate_success(
        api.create_state_license(
            f.state_license_payload(state_code, license_type, **overrides), COMPLIANCE
        ),
        201,
    )


def license_version(api: ApiClient, state_license_id: str) -> int:
    """Read the licence's current version for the §2.7 concurrency guard."""
    return validate_success(api.get_state_license(state_license_id, COMPLIANCE))[
        "version"
    ]


def set_license_carry_in(
    api: ApiClient, state_license_id: str, carry_in_barrels_ytd: float
) -> Dict[str, Any]:
    return validate_success(
        api.set_license_ytd_adjustments(
            state_license_id, f.license_ytd_payload(carry_in_barrels_ytd), COMPLIANCE
        )
    )


def propose_appointment(
    api: ApiClient, state_license_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A BreweryAdmin proposes; the version guard is read back first."""
    payload = f.appointment_payload(
        state_license_id, license_version(api, state_license_id), **overrides
    )
    return validate_success(api.create_distributor_appointment(payload, ADMIN), 201)


def create_active_appointment(
    api: ApiClient, state_license_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Propose then approve, so the appointment lands in ACTIVE.

    §3.6 forbids self-approval, so the approver is a different ComplianceOfficer
    identity from the proposing BreweryAdmin.
    """
    appointment = propose_appointment(api, state_license_id, **overrides)
    return validate_success(api.approve_appointment(appointment["id"], COMPLIANCE))


# ---------------------------------------------------------------------------
# Distribution orders (§3.7)
# ---------------------------------------------------------------------------
def submit_order(
    api: ApiClient, beer_id: str, state_license_id: str, **overrides: Any
) -> Dict[str, Any]:
    return validate_success(
        api.create_distribution_order(
            f.order_payload(beer_id, state_license_id, **overrides), ADMIN
        ),
        201,
    )


def create_allocated_order(
    api: ApiClient, beer_id: str, state_license_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Submit an order and reserve inventory for it."""
    order = submit_order(api, beer_id, state_license_id, **overrides)
    return validate_success(api.allocate_order(order["id"], ADMIN))


def create_shipped_order(
    api: ApiClient, beer_id: str, state_license_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Submit, allocate and ship an order, booking the barrels as removed."""
    order = create_allocated_order(api, beer_id, state_license_id, **overrides)
    return validate_success(api.ship_order(order["id"], ADMIN))


# ---------------------------------------------------------------------------
# Excise reports (§3.8)
# ---------------------------------------------------------------------------
def draft_report(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return validate_success(
        api.create_excise_report(f.excise_report_payload(**overrides), ADMIN), 201
    )


def file_report(api: ApiClient, report_id: str) -> Dict[str, Any]:
    """File a draft. §3.8 forbids the filer from being the preparer."""
    return validate_success(api.file_excise_report(report_id, COMPLIANCE))


def draft_and_file_report(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    report = draft_report(api, **overrides)
    return file_report(api, report["id"])


# ---------------------------------------------------------------------------
# Event permits (§3.9)
# ---------------------------------------------------------------------------
def draft_permit(api: ApiClient, featured_beer_id: str, **overrides: Any) -> Dict[str, Any]:
    return validate_success(
        api.create_event_permit(
            f.event_permit_payload(featured_beer_id, **overrides), COMPLIANCE
        ),
        201,
    )


def submit_permit(api: ApiClient, permit_id: str) -> Dict[str, Any]:
    return validate_success(api.submit_event_permit(permit_id, COMPLIANCE))


def create_approved_permit(
    api: ApiClient, featured_beer_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Draft, submit and approve a permit, leaving it in APPROVED."""
    permit = draft_permit(api, featured_beer_id, **overrides)
    submit_permit(api, permit["id"])
    return validate_success(
        api.decide_event_permit(
            permit["id"], f.permit_decision_payload(PERMIT_DECISION_APPROVED), REGULATOR
        )
    )


# ---------------------------------------------------------------------------
# Whole-scenario bootstraps
# ---------------------------------------------------------------------------
def bootstrap_taproom(
    api: ApiClient,
    units_planned: int = 10,
    actual_yield_bbl: float = 16.000,
    keg_size_bbl: float = KEG_SIZE_HALF_BBL,
) -> Dict[str, Any]:
    """Brewery ACTIVE, exempt beer, conditioning batch, TAPROOM run, tapped keg.

    Returns the ids and rows the taproom tests need.
    """
    bootstrap_brewery(api)
    beer = create_exempt_beer(api)
    tank = create_tank(api)
    batch = create_conditioning_batch(
        api, beer["id"], tank["id"], actual_yield_bbl=actual_yield_bbl
    )
    run = create_completed_run(
        api,
        batch["id"],
        destination=DESTINATION_TAPROOM,
        units_planned=units_planned,
    )
    keg = create_tapped_keg(api, run["id"], keg_size_bbl)
    return {
        "beer": beer,
        "tank": tank,
        "batch": batch,
        "run": run,
        "keg": keg,
    }


def bootstrap_distribution(
    api: ApiClient,
    state_code: str = "WA",
    units_planned: int = 10,
    actual_yield_bbl: float = 16.000,
    annual_barrel_cap: float = 100.00,
    franchise_state: bool = False,
) -> Dict[str, Any]:
    """Brewery ACTIVE, distribution-sellable beer, DISTRIBUTION run, ACTIVE licence."""
    bootstrap_brewery(api)
    beer = create_distribution_ready_beer(api)
    tank = create_tank(api)
    batch = create_conditioning_batch(
        api, beer["id"], tank["id"], actual_yield_bbl=actual_yield_bbl
    )
    run = create_completed_run(
        api,
        batch["id"],
        destination=DESTINATION_DISTRIBUTION,
        units_planned=units_planned,
    )
    license_row = create_license(
        api,
        state_code,
        annual_barrel_cap=annual_barrel_cap,
        franchise_state=franchise_state,
    )
    return {
        "beer": beer,
        "tank": tank,
        "batch": batch,
        "run": run,
        "license": license_row,
    }
