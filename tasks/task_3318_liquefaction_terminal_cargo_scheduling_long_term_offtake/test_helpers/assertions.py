"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer >= 1"
    )


def assert_customer(data: dict):
    _assert_common_fields(data, "Customer")
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["credit_rating"] in ["AAA", "AA", "A", "BBB"]
    assert isinstance(data["billing_currency"], str) and len(data["billing_currency"]) > 0


def assert_spa(data: dict):
    _assert_common_fields(data, "SalesPurchaseAgreement")
    assert data["commodity_index"] in ["HENRY_HUB", "TTF", "JKM"]
    assert data["destination_flexibility"] in ["FOB", "DES"]
    assert data["title_transfer_point"] in ["LOADING_FLANGE", "DISCHARGE_PORT"]
    assert data["status"] in ["EXECUTED", "DELIVERIES_COMMENCED", "EXPIRED"]
    assert data["annual_contract_quantity_mmbtu"] > 0


def assert_train(data: dict):
    _assert_common_fields(data, "LiquefactionTrain")
    assert data["status"] in [
        "CONSTRUCTION",
        "COMMISSIONING",
        "COMMERCIAL_OPERATION",
        "TURNAROUND",
        "DECOMMISSIONED",
    ]
    assert isinstance(data["commissioning_cargoes_required"], int)
    assert isinstance(data["commissioning_cargoes_completed"], int)


def assert_adp(data: dict):
    _assert_common_fields(data, "AnnualDeliveryProgram")
    assert data["status"] in ["DRAFT", "PROPOSED", "CONFIRMED", "LOCKED", "SUPERSEDED"]
    assert isinstance(data["revision_no"], int) and data["revision_no"] >= 1


def assert_cargo_slot(data: dict):
    _assert_common_fields(data, "CargoSlot")
    assert data["lift_status"] in [
        "SCHEDULED",
        "VESSEL_NOMINATED",
        "BERTH_ASSIGNED",
        "LOADED",
        "CANCELLED",
        "RESCHEDULED",
    ]
    assert data["billing_status"] in [
        "UNBILLED",
        "PROVISIONALLY_INVOICED",
        "FINAL_INVOICED",
    ]
    assert isinstance(data["quantity_mmbtu"], int) and data["quantity_mmbtu"] > 0
    assert isinstance(data["scheduled_feed_gas_mmbtu"], int)


def assert_berth(data: dict):
    _assert_common_fields(data, "Berth")
    assert data["status"] in ["IN_SERVICE", "OUT_OF_SERVICE"]


def assert_vessel_call(data: dict):
    _assert_common_fields(data, "VesselCall")
    assert data["status"] in [
        "NOMINATED",
        "ACCEPTED",
        "NOR_TENDERED",
        "BERTHED",
        "DEPARTED",
        "SUPERSEDED",
    ]


def assert_laytime_statement(data: dict):
    _assert_common_fields(data, "LaytimeStatement")
    assert data["status"] in ["SUBMITTED", "AGREED", "DISPUTED", "RESOLVED"]
    assert data["billing_basis"] in ["SOF_BASIS", "PUMP_LOG_BASIS"]


def assert_pipeline(data: dict):
    _assert_common_fields(data, "Pipeline")
    assert data["status"] in ["IN_SERVICE", "OUTAGE"]


def assert_day_schedule(data: dict):
    _assert_common_fields(data, "PipelineDaySchedule")
    assert data["status"] in ["OPEN", "CLOSED"]


def assert_nomination(data: dict):
    _assert_common_fields(data, "FeedGasNomination")
    assert data["status"] in ["SUBMITTED", "CONFIRMED", "CUT", "RECONCILED"]


def assert_cancellation(data: dict):
    _assert_common_fields(data, "CargoCancellation")
    assert data["status"] in ["REGISTERED", "SETTLED"]


def assert_resale(data: dict):
    _assert_common_fields(data, "FeedGasResale")
    assert data["status"] in ["OFFERED", "SOLD", "UNSOLD"]


def assert_turnaround(data: dict):
    _assert_common_fields(data, "MaintenanceTurnaround")
    assert data["status"] in [
        "PROPOSED",
        "APPROVED",
        "IN_PROGRESS",
        "COMPLETED",
        "CANCELLED",
    ]


def assert_schedule_totals_invariant(schedule: dict):
    """Conservation: confirmed + cut == nominated on a pipeline day schedule."""
    assert (
        schedule["total_confirmed_mmbtu"] + schedule["total_cut_mmbtu"]
        == schedule["total_nominated_mmbtu"]
    ), (
        f"total_confirmed ({schedule['total_confirmed_mmbtu']}) + total_cut "
        f"({schedule['total_cut_mmbtu']}) != total_nominated "
        f"({schedule['total_nominated_mmbtu']})"
    )


def assert_adp_quantity_invariant(adp: dict, acq: int):
    """Conservation: scheduled + cancelled + unallocated == ACQ."""
    total = (
        adp["scheduled_quantity_mmbtu"]
        + adp["cancelled_quantity_mmbtu"]
        + adp["unallocated_quantity_mmbtu"]
    )
    assert total == acq, f"ADP quantity sum {total} != ACQ {acq}"
