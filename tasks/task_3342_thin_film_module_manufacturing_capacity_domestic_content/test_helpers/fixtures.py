"""Composite setup helpers (PRD §3 workflows).

Every fixture builds its preconditions from scratch against a fresh server,
using only PRD-declared endpoints. Setup calls use the lenient
get_success_data() validator so failures surface as clear "Setup failed"
errors. CustomerAdmin calls always thread the owning Customer.id through
make_customer_admin_headers (ownership checks compare X-User-ID to Customer.id).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_attestation_payload,
    create_component_lot_payload,
    create_customer_payload,
    create_delivery_payload,
    create_module_series_payload,
    create_production_line_payload,
    create_production_run_payload,
    create_recycling_obligation_payload,
    create_reservation_payload,
    create_warranty_claim_payload,
)
from .test_users import TEST_USERS, make_customer_admin_headers

PM = TEST_USERS["plant_manager_headers"]
CO = TEST_USERS["contracts_officer_headers"]
SCA = TEST_USERS["supply_chain_auditor_headers"]
CPL = TEST_USERS["compliance_officer_headers"]
LC = TEST_USERS["logistics_coordinator_headers"]
WA = TEST_USERS["warranty_administrator_headers"]
RC = TEST_USERS["recycling_coordinator_headers"]

DEFAULT_WINDOW_START = "2027-03-01T00:00:00Z"
DEFAULT_WINDOW_END = "2027-04-01T00:00:00Z"
DEFAULT_CONFIRM_INSTANT = "2027-03-15T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation
# ---------------------------------------------------------------------------

def create_customer(**overrides) -> dict:
    """Register a customer (ContractsOfficer). Returns the customer."""
    resp = api_client.create_customer(create_customer_payload(**overrides), CO)
    return get_success_data(resp)


def create_module_series(**overrides) -> dict:
    """Register a module series (PlantManager). Returns the series."""
    resp = api_client.create_module_series(create_module_series_payload(**overrides), PM)
    return get_success_data(resp)


def create_production_line(**overrides) -> dict:
    """Register a production line (PlantManager). Returns the line (COMMISSIONING)."""
    resp = api_client.create_production_line(create_production_line_payload(**overrides), PM)
    return get_success_data(resp)


def get_line(line_id: str) -> dict:
    resp = api_client.get_production_line(line_id, PM)
    return get_success_data(resp)


def get_reservation(reservation_id: str) -> dict:
    resp = api_client.get_reservation(reservation_id, CO)
    return get_success_data(resp)


def get_delivery(delivery_id: str) -> dict:
    resp = api_client.get_delivery(delivery_id, LC)
    return get_success_data(resp)


def post_production_run(line_id: str, series_id: str, quarter: int,
                        input_modules: int = 100, good_modules: int = 70,
                        bin_counts: list = None) -> dict:
    """Post a production run. Bin counts default to an even split across the
    B1/B2 bins of the default series profile; pass bin_counts explicitly for
    series with different bin codes (every bin_code must exist in the produced
    series' bin_profile and counts must sum to good_modules, PRD §3.3)."""
    if bin_counts is None:
        half = good_modules // 2
        bin_counts = [
            {"bin_code": "B1", "count": good_modules - half},
            {"bin_code": "B2", "count": half},
        ]
    resp = api_client.create_production_run(
        create_production_run_payload(
            line_id=line_id, series_id=series_id, quarter=quarter,
            input_modules=input_modules, good_modules=good_modules,
            bin_counts=bin_counts,
        ),
        PM,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: line lifecycle composites
# ---------------------------------------------------------------------------

def create_ramping_line(good_modules: int = 70, input_modules: int = 100,
                        **line_overrides) -> dict:
    """Series S6 + line OH-L3 + first-article run (quarter 0) + commission.

    Returns {"series", "line", "run"}; the line is RAMPING with
    ramp_quarter_index == 0.
    """
    series = create_module_series()
    line = create_production_line(**line_overrides)
    run = post_production_run(line["id"], series["id"], quarter=0,
                              input_modules=input_modules, good_modules=good_modules)
    resp = api_client.commission_line(line["id"], PM)
    line = get_success_data(resp)
    return {"series": series, "line": line, "run": run}


def create_promoted_line(**line_overrides) -> dict:
    """Line driven to AT_CAPACITY: first-article run (0.9 yield) plus two more
    0.9-yield quarters; promotion fires on the third quarter close (pre-increment
    ramp_quarter_index 2 with actual yield >= 0.85, PRD §3.2)."""
    bundle = create_ramping_line(good_modules=90, input_modules=100, **line_overrides)
    series = bundle["series"]
    line = bundle["line"]
    # Close quarter 0 (yield 0.9000, pre-increment index 0: no promotion).
    get_success_data(api_client.close_quarter(PM))
    post_production_run(line["id"], series["id"], quarter=1, good_modules=90)
    # Close quarter 1 (pre-increment index 1: no promotion).
    get_success_data(api_client.close_quarter(PM))
    post_production_run(line["id"], series["id"], quarter=2, good_modules=90)
    # Close quarter 2 (pre-increment index 2, yield 0.9000: promotes).
    get_success_data(api_client.close_quarter(PM))
    bundle["line"] = get_line(line["id"])
    return bundle


# ---------------------------------------------------------------------------
# Tier 3: reservation lifecycle composites
# ---------------------------------------------------------------------------

def create_reservation(customer: dict, line: dict, series: dict, **overrides) -> dict:
    """Create a PENDING reservation (OCC-guarded: fetches the line's current
    version first). Ownership-threaded: the booking CustomerAdmin is the
    reservation's customer."""
    fresh_line = get_line(line["id"])
    payload = create_reservation_payload(
        customer_id=customer["id"], line_id=line["id"], series_id=series["id"],
        expected_line_version=fresh_line["version"], **overrides,
    )
    resp = api_client.create_reservation(
        payload, make_customer_admin_headers(customer["id"])
    )
    return get_success_data(resp)


def create_deposit_held_reservation(customer: dict, line: dict, series: dict,
                                    **overrides) -> dict:
    """PENDING reservation + deposit posted (owning CustomerAdmin)."""
    reservation = create_reservation(customer, line, series, **overrides)
    resp = api_client.post_deposit(
        reservation["id"], make_customer_admin_headers(customer["id"])
    )
    return get_success_data(resp)


def create_active_reservation(customer: dict, line: dict, series: dict,
                              **overrides) -> dict:
    """DEPOSIT_HELD reservation + activation (ContractsOfficer)."""
    reservation = create_deposit_held_reservation(customer, line, series, **overrides)
    resp = api_client.activate_reservation(reservation["id"], CO)
    return get_success_data(resp)


def setup_active_reservation(customer_overrides=None, line_overrides=None,
                             reservation_overrides=None) -> dict:
    """Full booking scenario on a RAMPING line.

    Returns {"customer", "series", "line", "reservation"}.
    """
    customer = create_customer(**(customer_overrides or {}))
    bundle = create_ramping_line(**(line_overrides or {}))
    reservation = create_active_reservation(
        customer, bundle["line"], bundle["series"], **(reservation_overrides or {})
    )
    return {
        "customer": customer,
        "series": bundle["series"],
        "line": get_line(bundle["line"]["id"]),
        "reservation": reservation,
    }


# ---------------------------------------------------------------------------
# Tier 4: traceability and delivery composites
# ---------------------------------------------------------------------------

def create_verified_lot(**overrides) -> dict:
    """Register a component lot and verify it (SupplyChainAuditor)."""
    resp = api_client.create_component_lot(create_component_lot_payload(**overrides), SCA)
    lot = get_success_data(resp)
    resp = api_client.verify_lot(lot["id"], SCA)
    return get_success_data(resp)


def schedule_delivery(reservation: dict, customer: dict, lot_ids: list,
                      volume_mw: float = 2.0,
                      window_start: str = DEFAULT_WINDOW_START,
                      window_end: str = DEFAULT_WINDOW_END) -> dict:
    """Schedule a delivery as the owning CustomerAdmin. Returns the delivery."""
    payload = create_delivery_payload(
        reservation_id=reservation["id"],
        scheduled_window_start=window_start,
        scheduled_window_end=window_end,
        volume_mw=volume_mw,
        lot_ids=list(lot_ids),
    )
    resp = api_client.create_delivery(
        payload, make_customer_admin_headers(customer["id"])
    )
    return get_success_data(resp)


def setup_scheduled_delivery(volume_mw: float = 2.0,
                             window_start: str = DEFAULT_WINDOW_START,
                             window_end: str = DEFAULT_WINDOW_END,
                             customer_overrides=None,
                             reservation_overrides=None) -> dict:
    """ACTIVE reservation + VERIFIED lot + SCHEDULED delivery.

    Returns {"customer", "series", "line", "reservation", "lot", "delivery"}.
    """
    scenario = setup_active_reservation(
        customer_overrides=customer_overrides,
        reservation_overrides=reservation_overrides,
    )
    lot = create_verified_lot()
    delivery = schedule_delivery(
        scenario["reservation"], scenario["customer"], [lot["id"]],
        volume_mw=volume_mw, window_start=window_start, window_end=window_end,
    )
    scenario.update({"lot": lot, "delivery": delivery})
    return scenario


def setup_delivered_reservation(volume_mw: float = 5.0,
                                reservation_overrides=None) -> dict:
    """ACTIVE reservation with one delivery confirmed DELIVERED (clock moved
    inside the window first). reservation['delivered_mw'] == volume_mw."""
    scenario = setup_scheduled_delivery(
        volume_mw=volume_mw, reservation_overrides=reservation_overrides
    )
    set_clock(DEFAULT_CONFIRM_INSTANT)
    resp = api_client.confirm_delivery(scenario["delivery"]["id"], LC)
    get_success_data(resp)
    scenario["delivery"] = get_delivery(scenario["delivery"]["id"])
    scenario["reservation"] = get_reservation(scenario["reservation"]["id"])
    return scenario


# ---------------------------------------------------------------------------
# Tier 5: compliance, warranty, recycling composites
# ---------------------------------------------------------------------------

def create_attestation(line: dict, **overrides) -> dict:
    """Create a DRAFT compliance attestation (ComplianceOfficer)."""
    resp = api_client.create_attestation(
        create_attestation_payload(line_id=line["id"], **overrides), CPL
    )
    return get_success_data(resp)


def create_submitted_attestation(line: dict, **overrides) -> dict:
    """DRAFT attestation + submit (percentages frozen at submission, PRD §3.7)."""
    attestation = create_attestation(line, **overrides)
    resp = api_client.submit_attestation(attestation["id"], CPL)
    return get_success_data(resp)


def file_claim(reservation: dict, customer: dict, **overrides) -> dict:
    """File a warranty claim as the owning CustomerAdmin. Returns FILED claim."""
    resp = api_client.create_warranty_claim(
        create_warranty_claim_payload(reservation_id=reservation["id"], **overrides),
        make_customer_admin_headers(customer["id"]),
    )
    return get_success_data(resp)


def file_under_review_claim(reservation: dict, customer: dict, **overrides) -> dict:
    """FILED claim + review opened (WarrantyAdministrator). Returns UNDER_REVIEW claim."""
    claim = file_claim(reservation, customer, **overrides)
    resp = api_client.review_claim(claim["id"], WA)
    return get_success_data(resp)


def open_obligation(customer: dict, **overrides) -> dict:
    """Open a recycling obligation (RecyclingCoordinator). Returns OPEN obligation."""
    resp = api_client.create_recycling_obligation(
        create_recycling_obligation_payload(customer_id=customer["id"], **overrides),
        RC,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Test-driving operations
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    resp = api_client.set_clock(to_iso8601, PM)
    return get_success_data(resp)


def close_quarter() -> dict:
    resp = api_client.close_quarter(PM)
    return get_success_data(resp)
