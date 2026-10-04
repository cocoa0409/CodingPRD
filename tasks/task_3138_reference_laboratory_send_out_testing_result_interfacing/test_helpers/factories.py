"""Payload factories — one per entity, input fields only.

Defaults mirror the catalogue and specimen data the workflows describe in PRD §3,
so a fixture can build a coherent scenario without every caller restating it.
"""

# =============================================================================
# ClientLaboratory
# =============================================================================

def create_client_laboratory_payload(**overrides) -> dict:
    defaults = {
        "name": "Valley Regional Medical Center",
        "clia_number": "45D-1001",
        "client_type": "HOSPITAL",
        "state_code": "UT",
        "billing_arrangement": "CLIENT",
        "credit_limit_cents": 5_000_000,
    }
    defaults.update(overrides)
    return defaults


# =============================================================================
# TestCatalogEntry
# =============================================================================

def create_catalog_entry_payload(**overrides) -> dict:
    """Ferritin, the default serum assay used across the workflow scenarios."""
    defaults = {
        "test_code": "FERRITIN",
        "test_name": "Ferritin, Serum",
        "test_category": "ROUTINE",
        "method": "IMMUNOASSAY",
        "required_specimen_type": "SERUM_SST",
        "container_type": "GOLD_SST",
        "min_volume_ml": 1.0,
        "transport_temperature": "AMBIENT",
        "stability_hours_ambient": 72,
        "stability_hours_refrigerated": 168,
        "stability_hours_frozen": 720,
        "base_tat_hours": 6,
        "list_price_cents": 1200,
        "client_price_cents": 1000,
        "floor_price_cents": 450,
        "reference_low": None,
        "reference_high": None,
        "critical_value_low": 5,
        "critical_value_high": 400,
        "reflex_test_code": None,
        "reflex_condition": "NONE",
        "reflex_within_hours": 24,
        "reflex_min_remaining_hours": 12,
        "is_utilization_managed": True,
    }
    defaults.update(overrides)
    return defaults


def ferritin_entry_payload(**overrides) -> dict:
    """The ferritin entry as the fixtures declare it (list 1200, client 1000, floor 450)."""
    return create_catalog_entry_payload(**overrides)


# =============================================================================
# CourierRun
# =============================================================================

def create_courier_run_payload(client_laboratory_id, expected_client_laboratory_version,
                               **overrides) -> dict:
    defaults = {
        "client_laboratory_id": client_laboratory_id,
        "route_code": "SLC-AM",
        "origin_city": "Provo",
        "destination_city": "Salt Lake City",
        "vehicle_id": "VAN-7",
        "scheduled_departure_at": "2026-09-01T05:00:00Z",
        "scheduled_arrival_at": "2026-09-01T09:30:00Z",
        "scheduled_pickup_at": "2026-09-01T05:00:00Z",
        "scheduled_delivery_at": "2026-09-01T09:30:00Z",
        "temperature_control_mode": "AMBIENT",
        "expected_client_laboratory_version": expected_client_laboratory_version,
    }
    defaults.update(overrides)
    return defaults


# =============================================================================
# Specimen
# =============================================================================

def create_specimen_payload(client_laboratory_id, courier_run_id, **overrides) -> dict:
    defaults = {
        "client_laboratory_id": client_laboratory_id,
        "courier_run_id": courier_run_id,
        "accession_number": "ACC-1001",
        "patient_mrn": "MRN-5001",
        "specimen_type": "SERUM_SST",
        "container_type": "GOLD_SST",
        "volume_ml": 3.0,
        "aliquot_parent_id": None,
        "aliquot_volume_ml": None,
        "collection_at": "2026-09-01T06:00:00Z",
        "received_at": "2026-09-01T06:30:00Z",
        "transport_temperature": "AMBIENT",
        "condition": "ACCEPTABLE",
        "condition_reason_code": None,
    }
    defaults.update(overrides)
    return defaults


def create_aliquot_payload(**overrides) -> dict:
    defaults = {
        "aliquot_volume_ml": 1.0,
        "container_type": "GOLD_SST",
        "accession_number": "ACC-1001-A1",
    }
    defaults.update(overrides)
    return defaults


# =============================================================================
# SendOutOrder
# =============================================================================

def create_send_out_order_payload(client_laboratory_id, specimen_id, test_lines, **overrides) -> dict:
    defaults = {
        "client_laboratory_id": client_laboratory_id,
        "specimen_id": specimen_id,
        "order_number": "REQ-1001",
        "patient_mrn": "MRN-5001",
        "client_requested_at": "2026-09-01T06:35:00Z",
        "priority": "ROUTINE",
        "test_lines": test_lines,
        "override_utilization_guard": False,
    }
    defaults.update(overrides)
    return defaults


def order_line(test_catalog_entry_id, line_sequence, **overrides) -> dict:
    line = {"test_catalog_entry_id": test_catalog_entry_id, "line_sequence": line_sequence}
    line.update(overrides)
    return line


def enter_results_payload(expected_send_out_order_version, result_lines) -> dict:
    return {
        "expected_send_out_order_version": expected_send_out_order_version,
        "result_lines": result_lines,
    }


def result_line(order_test_line_id, result_value, result_units="ng/mL",
                critical_value_notified_to=None, critical_value_notified_at=None) -> dict:
    return {
        "order_test_line_id": order_test_line_id,
        "result_value": result_value,
        "result_units": result_units,
        "critical_value_notified_to": critical_value_notified_to,
        "critical_value_notified_at": critical_value_notified_at,
    }


def add_on_payload(test_catalog_entry_id, line_sequence, add_on_at) -> dict:
    return {
        "test_catalog_entry_id": test_catalog_entry_id,
        "line_sequence": line_sequence,
        "add_on_at": add_on_at,
    }


# =============================================================================
# InstrumentRun
# =============================================================================

def create_instrument_run_payload(test_catalog_entry_id, **overrides) -> dict:
    defaults = {
        "test_catalog_entry_id": test_catalog_entry_id,
        "instrument_code": "IMM-01",
        "section": "CORE",
        "decontamination_buffer_minutes": 30,
        "reserved_start_at": "2026-09-01T07:00:00Z",
        "reserved_end_at": "2026-09-01T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# =============================================================================
# InterfaceBuild
# =============================================================================

def create_interface_build_payload(client_laboratory_id, **overrides) -> dict:
    defaults = {
        "client_laboratory_id": client_laboratory_id,
        "build_version_label": "v1",
        "format": "HL7_V2_5_1",
        "order_interface_enabled": True,
        "result_interface_enabled": True,
    }
    defaults.update(overrides)
    return defaults


# =============================================================================
# ResultInterfaceMessage
# =============================================================================

def create_interface_message_payload(send_out_order_id, interface_build_id,
                                     control_id, expected_send_out_order_version,
                                     message_type="RESULT", **overrides) -> dict:
    defaults = {
        "send_out_order_id": send_out_order_id,
        "interface_build_id": interface_build_id,
        "message_type": message_type,
        "control_id": control_id,
        "expected_send_out_order_version": expected_send_out_order_version,
    }
    defaults.update(overrides)
    return defaults


# =============================================================================
# BillingLedger
# =============================================================================

def create_billing_ledger_payload(client_laboratory_id) -> dict:
    return {"client_laboratory_id": client_laboratory_id}


# =============================================================================
# UtilizationAdvisory
# =============================================================================

def create_utilization_advisory_payload(client_laboratory_id, test_catalog_entry_id,
                                        message="Duplicate order advisory.",
                                        **overrides) -> dict:
    defaults = {
        "client_laboratory_id": client_laboratory_id,
        "test_catalog_entry_id": test_catalog_entry_id,
        "source_order_id": None,
        "advisory_type": "DUPLICATE_ORDER",
        "message": message,
    }
    defaults.update(overrides)
    return defaults