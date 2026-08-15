"""Composite setup helpers.

Multi-step arrangements (active wells, verified reports, published basin
snapshots, appealed assessments, closed water years) are built here so tests can
focus on assertions. All helpers use the lenient get_success_data() validator so
a broken precondition surfaces as a clear "Setup step failed" error.

Ownership threading: WellOwner is entity-backed, so every ownership-gated call
uses make_well_owner_headers(<owning account id>).
"""
from uuid import uuid4

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_WATER_YEAR, STANDARD_MEASURED_AT, STANDARD_MONITORING_THRESHOLD_FT
from .test_users import (
    TEST_USERS,
    make_appeals_officer_headers,
    make_enforcement_officer_headers,
    make_well_owner_headers,
)

_WM = TEST_USERS["water_master_headers"]


def _new_meter_serial() -> str:
    return f"M-{uuid4().hex[:8].upper()}"


# ---------------------------------------------------------------------------
# Tier 1/2: accounts and wells
# ---------------------------------------------------------------------------

def create_account(holder_name="Test Pumper", account_type="AGRICULTURAL", base_allocation_af=100.000):
    """WaterMaster onboards an account; returns the persisted account."""
    resp = api_client.create_account(
        {
            "holder_name": holder_name,
            "account_type": account_type,
            "base_allocation_af": base_allocation_af,
        },
        _WM,
    )
    return get_success_data(resp)


def get_account(account_id):
    return get_success_data(api_client.get_account(account_id, _WM))


def create_well(account_id, well_type="PRODUCTION", location_description="Parcel 1",
                minimum_threshold_ft=None):
    """Owner registers a well; returns the REGISTERED well."""
    payload = {
        "account_id": account_id,
        "well_type": well_type,
        "location_description": location_description,
    }
    if minimum_threshold_ft is not None:
        payload["minimum_threshold_ft"] = minimum_threshold_ft
    resp = api_client.create_well(payload, make_well_owner_headers(account_id))
    return get_success_data(resp)


def install_meter(well_id, account_id, meter_serial=None):
    resp = api_client.install_meter(
        well_id, {"meter_serial": meter_serial or _new_meter_serial()},
        make_well_owner_headers(account_id),
    )
    return get_success_data(resp)


def activate_well(well_id):
    return get_success_data(api_client.activate_well(well_id, _WM))


def create_active_production_well(account_id, location_description="Parcel 1"):
    """REGISTERED -> install-meter -> ACTIVE (production metering path)."""
    well = create_well(account_id, "PRODUCTION", location_description)
    install_meter(well["id"], account_id)
    return activate_well(well["id"])


def create_metered_well(account_id, location_description="Parcel 1"):
    """REGISTERED -> METER_INSTALLED (stops short of activation)."""
    well = create_well(account_id, "PRODUCTION", location_description)
    return install_meter(well["id"], account_id)


def create_active_monitoring_well(account_id, minimum_threshold_ft=STANDARD_MONITORING_THRESHOLD_FT,
                                  location_description="MW"):
    """MONITORING wells activate straight from REGISTERED (metering exemption)."""
    well = create_well(account_id, "MONITORING", location_description, minimum_threshold_ft)
    return activate_well(well["id"])


def create_active_domestic_well(account_id, location_description="Home parcel"):
    """DOMESTIC wells activate straight from REGISTERED (metering exemption)."""
    well = create_well(account_id, "DOMESTIC", location_description)
    return activate_well(well["id"])


# ---------------------------------------------------------------------------
# Tier 3: extraction reports and the revision loop
# ---------------------------------------------------------------------------

def submit_extraction_report(well_id, account_id, water_year=DEFAULT_WATER_YEAR, month=6,
                             reported_af=10.000):
    resp = api_client.create_extraction_report(
        {"well_id": well_id, "water_year": water_year, "month": month, "reported_af": reported_af},
        make_well_owner_headers(account_id),
    )
    return get_success_data(resp)


def verify_report(report_id):
    return get_success_data(api_client.verify_report(report_id, _WM))


def dispute_report(report_id):
    return get_success_data(api_client.dispute_report(report_id, _WM))


def resubmit_report(report_id, account_id, reported_af):
    resp = api_client.resubmit_report(
        report_id, {"reported_af": reported_af}, make_well_owner_headers(account_id)
    )
    return get_success_data(resp)


def submit_and_verify_report(well_id, account_id, water_year=DEFAULT_WATER_YEAR, month=6,
                             reported_af=10.000):
    report = submit_extraction_report(well_id, account_id, water_year, month, reported_af)
    return verify_report(report["id"])


# ---------------------------------------------------------------------------
# Tier 3: transfer market
# ---------------------------------------------------------------------------

def propose_transfer(seller_account_id, buyer_account_id, quantity_af=10.000,
                     start="2026-08-01", end="2026-10-01", unit_price_cents=9000):
    resp = api_client.create_transfer_order(
        {
            "seller_account_id": seller_account_id,
            "buyer_account_id": buyer_account_id,
            "quantity_af": quantity_af,
            "unit_price_cents": unit_price_cents,
            "effective_start_date": start,
            "effective_end_date": end,
        },
        make_well_owner_headers(seller_account_id),
    )
    return get_success_data(resp)


def accept_transfer(transfer_id, buyer_account_id):
    return get_success_data(
        api_client.accept_transfer(transfer_id, make_well_owner_headers(buyer_account_id))
    )


def cancel_transfer(transfer_id, seller_account_id):
    return get_success_data(
        api_client.cancel_transfer(transfer_id, make_well_owner_headers(seller_account_id))
    )


def settle_transfer(transfer_id):
    return get_success_data(api_client.settle_transfer(transfer_id, _WM))


def propose_and_accept_transfer(seller_account_id, buyer_account_id, quantity_af=10.000,
                                start="2026-08-01", end="2026-10-01", unit_price_cents=9000):
    order = propose_transfer(seller_account_id, buyer_account_id, quantity_af, start, end,
                             unit_price_cents)
    return accept_transfer(order["id"], buyer_account_id)


def settle_accepted_transfer(seller_account_id, buyer_account_id, quantity_af=10.000,
                             start="2026-08-01", end="2026-10-01"):
    order = propose_and_accept_transfer(seller_account_id, buyer_account_id, quantity_af,
                                        start, end)
    return settle_transfer(order["id"])


# ---------------------------------------------------------------------------
# Tier 4: monitoring data and basin-condition snapshots
# ---------------------------------------------------------------------------

def record_monitoring_reading(well_id, depth_to_water_ft, measured_at=STANDARD_MEASURED_AT,
                              collector_name="Field Tech"):
    resp = api_client.create_monitoring_reading(
        {
            "well_id": well_id,
            "measured_at": measured_at,
            "depth_to_water_ft": depth_to_water_ft,
            "collector_name": collector_name,
        },
        _WM,
    )
    return get_success_data(resp)


def create_basin_snapshot():
    return get_success_data(api_client.create_basin_snapshot(_WM))


def publish_basin_snapshot(snapshot_id):
    return get_success_data(api_client.publish_basin_snapshot(snapshot_id, _WM))


def setup_basin_condition(depths, minimum_threshold_ft=STANDARD_MONITORING_THRESHOLD_FT,
                          measured_at=STANDARD_MEASURED_AT, publish=False,
                          holder_name="Agency Monitor"):
    """Build an agency account with one ACTIVE MONITORING well per depth, record one
    reading per well, compute a fresh DRAFT snapshot, and optionally publish it.

    Returns {"account": ..., "wells": [...], "snapshot": ...}.
    """
    account = create_account(holder_name=holder_name, account_type="MUNICIPAL",
                             base_allocation_af=1000.000)
    wells = []
    for index, depth in enumerate(depths, start=1):
        well = create_active_monitoring_well(
            account["id"], minimum_threshold_ft, location_description=f"MW-{index}"
        )
        record_monitoring_reading(well["id"], depth, measured_at)
        wells.append(well)
    snapshot = create_basin_snapshot()
    if publish:
        snapshot = publish_basin_snapshot(snapshot["id"])
    return {"account": account, "wells": wells, "snapshot": snapshot}


# ---------------------------------------------------------------------------
# Tier 3: penalty assessments and appeals
# ---------------------------------------------------------------------------

def create_penalty_assessment(account_id, reason="LATE_REPORT", water_year=DEFAULT_WATER_YEAR,
                              overdraft_af=None, officer_user_id="eo-1"):
    payload = {"account_id": account_id, "reason": reason, "water_year": water_year}
    if overdraft_af is not None:
        payload["overdraft_af"] = overdraft_af
    resp = api_client.create_penalty_assessment(
        payload, make_enforcement_officer_headers(officer_user_id)
    )
    return get_success_data(resp)


def appeal_assessment(assessment_id, account_id, grounds="disputed charge"):
    return get_success_data(
        api_client.appeal_assessment(
            assessment_id, {"grounds": grounds}, make_well_owner_headers(account_id)
        )
    )


def create_and_appeal_assessment(account_id, reason="LATE_REPORT", water_year=DEFAULT_WATER_YEAR,
                                 officer_user_id="eo-1"):
    assessment = create_penalty_assessment(account_id, reason, water_year,
                                           officer_user_id=officer_user_id)
    return appeal_assessment(assessment["id"], account_id)


def decide_assessment(assessment_id, outcome, reduced_amount_cents=None, appeals_user_id="ao-1"):
    payload = {"outcome": outcome}
    if reduced_amount_cents is not None:
        payload["reduced_amount_cents"] = reduced_amount_cents
    return get_success_data(
        api_client.decide_assessment(assessment_id, payload,
                                     make_appeals_officer_headers(appeals_user_id))
    )


def pay_assessment(assessment_id, account_id):
    return get_success_data(
        api_client.pay_assessment(assessment_id, make_well_owner_headers(account_id))
    )


# ---------------------------------------------------------------------------
# Tier 5: year close, annual reports, logical clock
# ---------------------------------------------------------------------------

def close_water_year(water_year=DEFAULT_WATER_YEAR):
    return get_success_data(api_client.close_water_year({"water_year": water_year}, _WM))


def create_annual_state_report(water_year=DEFAULT_WATER_YEAR):
    return get_success_data(api_client.create_annual_state_report({"water_year": water_year}, _WM))


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, _WM))


# ---------------------------------------------------------------------------
# Composite: account with an ACTIVE PRODUCTION well (most common preamble)
# ---------------------------------------------------------------------------

def setup_account_with_active_production_well(holder_name="Test Pumper",
                                              base_allocation_af=100.000,
                                              account_type="AGRICULTURAL"):
    """Account + metered, ACTIVE production well. Returns (account, well)."""
    account = create_account(holder_name=holder_name, account_type=account_type,
                             base_allocation_af=base_allocation_af)
    well = create_active_production_well(account["id"])
    return account, well


def setup_account_with_verified_extraction(base_allocation_af, verified_af,
                                           holder_name="Test Pumper",
                                           water_year=DEFAULT_WATER_YEAR, month=6):
    """Account + ACTIVE PRODUCTION well + one VERIFIED report of `verified_af`.
    Returns (account, well, report)."""
    account, well = setup_account_with_active_production_well(
        holder_name=holder_name, base_allocation_af=base_allocation_af
    )
    report = submit_and_verify_report(well["id"], account["id"], water_year, month, verified_af)
    return account, well, report
