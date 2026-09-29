"""Entity assertions and cross-field invariant checkers for this API."""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant

# ─── Shared structural helpers ────────────────────────────────────────────

FULL_COMMON_FIELDS = ("id", "created_at", "updated_at", "version")


def assert_money_is_integer_cents(value: Any, field_name: str) -> None:
    """Monetary amounts are integers denominated in whole cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field_name} must be an integer number of whole cents, got {value!r}"
    )


def assert_instant(value: Any, field_name: str) -> None:
    """ISO 8601 UTC timestamp with three fractional digits."""
    assert isinstance(value, str), f"{field_name} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), (
        f"{field_name} must be an ISO 8601 UTC timestamp, got {value!r}"
    )
    assert canonical_instant(value) == value or canonical_instant(value) is not None, (
        f"{field_name} must be canonicalisable, got {value!r}"
    )


def assert_calendar_date(value: Any, field_name: str) -> None:
    assert isinstance(value, str) and len(value) == 10 and value[4] == "-", (
        f"{field_name} must be a YYYY-MM-DD calendar date, got {value!r}"
    )


def assert_common_fields(data: Dict[str, Any], entity_name: str) -> None:
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a raw UUID with no type prefix, got "
        f"{data.get('id')!r}"
    )
    assert_instant(data.get("created_at"), f"{entity_name}.created_at")
    assert_instant(data.get("updated_at"), f"{entity_name}.updated_at")
    assert isinstance(data.get("version"), int) and not isinstance(
        data.get("version"), bool
    ), f"{entity_name}.version must be an integer, got {data.get('version')!r}"


def assert_instants_equal(actual: Optional[str], expected: str, label: str) -> None:
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected instant {expected}, got {actual}"
    )


# ─── Entity assertions ────────────────────────────────────────────────────

def assert_rental_account(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "RentalAccount")
    assert isinstance(data["legal_name"], str) and 1 <= len(data["legal_name"]) <= 120
    assert data["account_type"] in ("CONSTRUCTION", "EVENT", "MUNICIPAL")
    assert data["credit_terms_days"] in (0, 15, 30, 45), (
        f"credit_terms_days must be one of 0, 15, 30 or 45, got "
        f"{data['credit_terms_days']!r}"
    )
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert_money_is_integer_cents(
        data["open_credit_balance_cents"], "RentalAccount.open_credit_balance_cents"
    )
    assert data["open_credit_balance_cents"] >= 0
    assert isinstance(data["billing_hold"], bool)


def assert_service_site(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "ServiceSite")
    assert is_valid_uuid(data["account_id"])
    assert isinstance(data["site_label"], str) and 1 <= len(data["site_label"]) <= 120
    assert isinstance(data["jurisdiction_code"], str)
    assert 2 <= len(data["jurisdiction_code"]) <= 24
    assert data["access_class"] in ("OPEN_LOT", "GATED", "STAIR_ACCESS", "CRANE_ONLY")
    assert isinstance(data["right_of_way_required"], bool)
    assert 0 <= data["gate_open_minute"] <= 1439
    assert 1 <= data["gate_close_minute"] <= 1440
    assert data["gate_close_minute"] > data["gate_open_minute"], (
        "gate_close_minute must be strictly greater than gate_open_minute"
    )
    assert 8 <= data["max_truck_length_ft"] <= 60
    assert isinstance(data["deployed_unit_count"], int)
    assert data["deployed_unit_count"] >= 0
    assert data["permit_status"] in (
        "NONE", "PENDING", "APPROVED", "REJECTED", "EXPIRED"
    )
    assert data["site_posture"] in ("OPEN", "RESTRICTED", "BLOCKED")


def assert_placement_permit(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "PlacementPermit")
    assert is_valid_uuid(data["site_id"])
    assert data["permit_kind"] in ("PLACEMENT", "RIGHT_OF_WAY")
    assert isinstance(data["authority_ref"], str)
    assert 1 <= len(data["authority_ref"]) <= 64
    assert_calendar_date(data["effective_from"], "PlacementPermit.effective_from")
    assert_calendar_date(data["effective_to"], "PlacementPermit.effective_to")
    assert data["effective_to"] >= data["effective_from"]
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "EXPIRED"
    )
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0


def assert_asset_unit(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "AssetUnit")
    assert isinstance(data["asset_tag"], str) and 1 <= len(data["asset_tag"]) <= 32
    assert data["unit_class"] in (
        "STANDARD_PORTABLE", "ADA_PORTABLE", "HANDWASH_STATION",
        "TRAILER_2STALL", "TRAILER_8STALL",
    )
    assert isinstance(data["yard_code"], str) and 2 <= len(data["yard_code"]) <= 16
    assert 4 <= data["tare_length_ft"] <= 60
    assert data["status"] in ("IN_YARD", "DEPLOYED", "IN_REPAIR", "RETIRED")
    assert isinstance(data["damage_strikes"], int) and data["damage_strikes"] >= 0
    assert isinstance(data["tip_over_count"], int) and data["tip_over_count"] >= 0


def assert_disposal_site(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "DisposalSite")
    assert isinstance(data["site_code"], str) and 1 <= len(data["site_code"]) <= 24
    assert 100 <= data["daily_gallon_cap"] <= 500000
    classes = data["accepted_waste_classes"]
    assert isinstance(classes, list) and len(classes) >= 1
    assert len(set(classes)) == len(classes), "accepted_waste_classes must be distinct"
    for waste_class in classes:
        assert waste_class in ("GREYWATER", "BLACKWATER", "MIXED")
    assert data["status"] in ("ACCEPTING", "CLOSED")
    assert isinstance(data["committed_gallons_today"], int)
    assert data["committed_gallons_today"] >= 0


def assert_route(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "Route")
    assert isinstance(data["route_code"], str) and 1 <= len(data["route_code"]) <= 24
    assert data["service_day"] in ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
    assert 1 <= data["truck_capacity_units"] <= 400
    assert 100 <= data["waste_capacity_gallons"] <= 6000
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["committed_units"], int) and data["committed_units"] >= 0
    assert 0 <= data["density_planned_pct"] <= 100, (
        "planned density can never exceed 100 percent"
    )
    assert isinstance(data["density_realized_pct"], int)
    assert data["density_realized_pct"] >= 0
    if data["last_run_date"] is not None:
        assert_calendar_date(data["last_run_date"], "Route.last_run_date")


def assert_rental_contract(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "RentalContract")
    assert is_valid_uuid(data["account_id"])
    assert is_valid_uuid(data["site_id"])
    assert data["contract_kind"] in ("EVENT", "CONSTRUCTION")
    assert_calendar_date(data["term_start"], "RentalContract.term_start")
    assert_calendar_date(data["term_end"], "RentalContract.term_end")
    assert data["term_end"] >= data["term_start"]
    assert 1 <= data["headcount"] <= 20000
    assert 1 <= data["event_duration_hours"] <= 24
    assert 1 <= data["service_frequency_per_week"] <= 7
    assert data["season_code"] in ("PEAK", "SHOULDER", "OFF")
    assert data["construction_phase"] in (
        "SITEWORK", "VERTICAL", "FINISHES", "EVENT_NA"
    )
    if data["contract_kind"] == "EVENT":
        assert data["construction_phase"] == "EVENT_NA", (
            "an EVENT contract must carry EVENT_NA as its construction_phase"
        )
    assert isinstance(data["ada_required"], bool)
    assert data["fulfillment_state"] in (
        "DRAFT", "QUOTED", "ACTIVE", "DEMOBILIZED", "CLOSED"
    )
    assert data["billing_state"] in (
        "UNBILLED", "INVOICED", "REBILL_REQUIRED", "SETTLED"
    )
    for field in (
        "quoted_cents", "reconciled_cents", "invoice_subtotal_cents",
        "charge_debits_cents", "credit_accrued_cents", "net_billable_cents",
    ):
        assert_money_is_integer_cents(data[field], f"RentalContract.{field}")
    assert_contract_ledger_identity(data)


def assert_contract_ledger_identity(data: Dict[str, Any]) -> None:
    """net_billable_cents is subtotal plus debits minus credits."""
    expected = (
        data["invoice_subtotal_cents"]
        + data["charge_debits_cents"]
        - data["credit_accrued_cents"]
    )
    assert data["net_billable_cents"] == expected, (
        "net_billable_cents must equal invoice_subtotal_cents plus "
        "charge_debits_cents minus credit_accrued_cents: expected "
        f"{expected}, got {data['net_billable_cents']}"
    )


def assert_quote_line(data: Dict[str, Any]) -> None:
    """A quote line carries only id and created_at from the common set."""
    assert is_valid_uuid(data.get("id", "")), "QuoteLine.id must be a raw UUID"
    assert_instant(data.get("created_at"), "QuoteLine.created_at")
    assert "updated_at" not in data, (
        "updated_at is absent from a quote line entirely"
    )
    assert "version" not in data, "version is absent from a quote line entirely"
    assert is_valid_uuid(data["contract_id"])
    assert data["quote_variant"] in ("PROVISIONAL", "RECONCILED")
    assert data["unit_class"] in (
        "STANDARD_PORTABLE", "ADA_PORTABLE", "HANDWASH_STATION",
        "TRAILER_2STALL", "TRAILER_8STALL",
    )
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1, (
        "a class whose computed quantity is zero produces no row at all"
    )
    assert_money_is_integer_cents(data["unit_rate_cents"], "QuoteLine.unit_rate_cents")
    assert_money_is_integer_cents(data["extended_cents"], "QuoteLine.extended_cents")
    assert_money_is_integer_cents(data["escalated_cents"], "QuoteLine.escalated_cents")
    assert data["extended_cents"] == data["quantity"] * data["unit_rate_cents"], (
        "extended_cents is the exact integer product of quantity and unit_rate_cents"
    )
    assert isinstance(data["is_superseded"], bool)


def assert_unit_deployment(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "UnitDeployment")
    assert is_valid_uuid(data["contract_id"])
    assert is_valid_uuid(data["asset_unit_id"])
    assert is_valid_uuid(data["site_id"])
    assert_calendar_date(data["deploy_from"], "UnitDeployment.deploy_from")
    assert_calendar_date(data["deploy_to"], "UnitDeployment.deploy_to")
    assert data["deploy_to"] >= data["deploy_from"]
    assert data["state"] in ("RESERVED", "DEPLOYED", "RETURNED")
    assert isinstance(data["relocation_count"], int)
    assert data["relocation_count"] >= 0


def assert_service_schedule(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "ServiceSchedule")
    assert is_valid_uuid(data["contract_id"])
    assert is_valid_uuid(data["route_id"])
    assert data["service_day"] in ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
    assert 0 <= data["window_start_minute"] <= 1439
    assert 1 <= data["window_end_minute"] <= 1440
    assert data["window_end_minute"] > data["window_start_minute"]
    assert isinstance(data["units_on_route"], int) and data["units_on_route"] >= 0
    assert data["state"] in ("ACTIVE", "SUSPENDED", "TERMINATED")


def assert_service_visit(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "ServiceVisit")
    assert is_valid_uuid(data["schedule_id"])
    assert is_valid_uuid(data["route_id"])
    assert data["visit_kind"] in ("SETUP", "SERVICE", "TEARDOWN", "RERUN")
    assert_calendar_date(data["scheduled_date"], "ServiceVisit.scheduled_date")
    assert 0 <= data["window_start_minute"] <= 1439
    assert 1 <= data["window_end_minute"] <= 1440
    assert data["window_end_minute"] > data["window_start_minute"]
    assert data["state"] in (
        "PLANNED", "EN_ROUTE", "SERVICED", "MISSED", "CANCELLED", "RERUN_SCHEDULED"
    )
    assert isinstance(data["gallons_pumped"], int) and 0 <= data["gallons_pumped"] <= 6000
    assert isinstance(data["units_serviced"], int) and data["units_serviced"] >= 0
    if data["state"] != "SERVICED":
        assert data["units_serviced"] == 0, (
            "units_serviced is 0 in every state other than SERVICED"
        )


def assert_waste_manifest(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "WasteManifest")
    assert is_valid_uuid(data["route_id"])
    assert is_valid_uuid(data["disposal_site_id"])
    assert_calendar_date(data["manifest_date"], "WasteManifest.manifest_date")
    assert data["waste_class"] in ("GREYWATER", "BLACKWATER", "MIXED")
    assert isinstance(data["gallons_total"], int) and data["gallons_total"] >= 0
    assert data["state"] in ("OPEN", "SEALED", "ACCEPTED")


def assert_charge_event(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "ChargeEvent")
    assert is_valid_uuid(data["contract_id"])
    assert data["charge_kind"] in (
        "DAMAGE", "TIP_OVER", "RELOCATION", "MISSED_SERVICE_CREDIT"
    )
    if data["charge_kind"] == "DAMAGE":
        assert data["severity"] in ("MINOR", "MODERATE", "TOTAL_LOSS")
    if data["charge_kind"] == "TIP_OVER":
        assert data["severity"] is None, "a TIP_OVER charge must not carry a severity"
    assert_money_is_integer_cents(data["amount_cents"], "ChargeEvent.amount_cents")
    assert data["amount_cents"] >= 0, "amounts are always non-negative, credits included"
    assert data["state"] in ("ASSESSED", "DISPUTED", "UPHELD", "WAIVED")
    assert isinstance(data["assessed_by_user_id"], str)
    assert_instant(data["assessed_at"], "ChargeEvent.assessed_at")


# ─── Domain invariant helpers used across test files ──────────────────────

def quote_line_totals(lines: List[Dict[str, Any]]) -> int:
    """Sum of extended_cents over the supplied lines."""
    return sum(line["extended_cents"] for line in lines)


def lines_by_unit_class(lines: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Index a quote-line list by its unit_class."""
    return {line["unit_class"]: line for line in lines}


def unit_classes_in_order(lines: List[Dict[str, Any]]) -> List[str]:
    return [line["unit_class"] for line in lines]


CLASS_ORDER = [
    "STANDARD_PORTABLE",
    "ADA_PORTABLE",
    "HANDWASH_STATION",
    "TRAILER_2STALL",
    "TRAILER_8STALL",
]


def assert_quote_lines_in_class_order(lines: List[Dict[str, Any]]) -> None:
    """Lines are created in a fixed class order."""
    observed = [line["unit_class"] for line in lines]
    ranks = [CLASS_ORDER.index(unit_class) for unit_class in observed]
    assert ranks == sorted(ranks), (
        "quote lines must appear in the fixed class order STANDARD_PORTABLE, "
        f"ADA_PORTABLE, HANDWASH_STATION, TRAILER_2STALL, TRAILER_8STALL; got {observed}"
    )


def assert_quote_line_set(
    lines: List[Dict[str, Any]],
    expected: List[tuple],
    variant: str = "PROVISIONAL",
) -> None:
    """Assert an exact line set as (unit_class, quantity, unit_rate, extended)."""
    assert len(lines) == len(expected), (
        f"expected {len(expected)} {variant} lines, got {len(lines)}: "
        f"{[(l['unit_class'], l['quantity']) for l in lines]}"
    )
    assert_quote_lines_in_class_order(lines)
    indexed = lines_by_unit_class(lines)
    for unit_class, quantity, unit_rate_cents, extended_cents in expected:
        assert unit_class in indexed, f"missing a {unit_class} line"
        line = indexed[unit_class]
        assert_quote_line(line)
        assert line["quote_variant"] == variant, (
            f"{unit_class} line must carry quote_variant {variant}, got "
            f"{line['quote_variant']}"
        )
        assert line["quantity"] == quantity, (
            f"{unit_class} quantity: expected {quantity}, got {line['quantity']}"
        )
        assert line["unit_rate_cents"] == unit_rate_cents, (
            f"{unit_class} unit_rate_cents: expected {unit_rate_cents}, got "
            f"{line['unit_rate_cents']}"
        )
        assert line["extended_cents"] == extended_cents, (
            f"{unit_class} extended_cents: expected {extended_cents}, got "
            f"{line['extended_cents']}"
        )


def assert_site_gate(
    site: Dict[str, Any], permit_status: str, site_posture: str
) -> None:
    assert site["permit_status"] == permit_status, (
        f"expected permit_status {permit_status}, got {site['permit_status']}"
    )
    assert site["site_posture"] == site_posture, (
        f"expected site_posture {site_posture}, got {site['site_posture']}"
    )


def assert_contract_ledger(
    contract: Dict[str, Any],
    invoice_subtotal_cents: Optional[int] = None,
    charge_debits_cents: Optional[int] = None,
    credit_accrued_cents: Optional[int] = None,
    net_billable_cents: Optional[int] = None,
) -> None:
    if invoice_subtotal_cents is not None:
        assert contract["invoice_subtotal_cents"] == invoice_subtotal_cents, (
            f"invoice_subtotal_cents: expected {invoice_subtotal_cents}, got "
            f"{contract['invoice_subtotal_cents']}"
        )
    if charge_debits_cents is not None:
        assert contract["charge_debits_cents"] == charge_debits_cents, (
            f"charge_debits_cents: expected {charge_debits_cents}, got "
            f"{contract['charge_debits_cents']}"
        )
    if credit_accrued_cents is not None:
        assert contract["credit_accrued_cents"] == credit_accrued_cents, (
            f"credit_accrued_cents: expected {credit_accrued_cents}, got "
            f"{contract['credit_accrued_cents']}"
        )
    if net_billable_cents is not None:
        assert contract["net_billable_cents"] == net_billable_cents, (
            f"net_billable_cents: expected {net_billable_cents}, got "
            f"{contract['net_billable_cents']}"
        )
    assert_contract_ledger_identity(contract)


def assert_route_density(
    route: Dict[str, Any],
    committed_units: Optional[int] = None,
    density_planned_pct: Optional[int] = None,
    density_realized_pct: Optional[int] = None,
) -> None:
    if committed_units is not None:
        assert route["committed_units"] == committed_units, (
            f"committed_units: expected {committed_units}, got "
            f"{route['committed_units']}"
        )
    if density_planned_pct is not None:
        assert route["density_planned_pct"] == density_planned_pct, (
            f"density_planned_pct: expected {density_planned_pct}, got "
            f"{route['density_planned_pct']}"
        )
    if density_realized_pct is not None:
        assert route["density_realized_pct"] == density_realized_pct, (
            f"density_realized_pct: expected {density_realized_pct}, got "
            f"{route['density_realized_pct']}"
        )


def assert_error_envelope_shape(error_data: Dict[str, Any]) -> None:
    """The error payload carries exactly error_id and message."""
    assert set(error_data.keys()) == {"error_id", "message"}, (
        "an error payload carries exactly error_id and message, got "
        f"{sorted(error_data.keys())}"
    )
