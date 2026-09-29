"""Per-entity shape assertions and domain invariant checkers.

The shape assertions enforce the common-field split of PRD S2.4 (ten resources
carry ``updated_at`` and ``version``; ``ProcessAgent`` and ``FeeLedgerEntry``
carry neither), the integer-cents rule of S2.7 and the three-fractional-digit
instant format of S2.4.  The invariant checkers re-assert the two ledger
identities of S3.1 and the two contract-population identities of S2.10.
"""

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_valid_uuid, validate_paginated

from . import constants as C
from .types import (
    APPLICATION_STATUSES,
    AUDIT_STATUSES,
    AUTHORITY_STATUSES,
    COMMODITY_CLASSES,
    COMPLIANCE_RISK_VARIANTS,
    CONTRACT_STATUSES,
    DESIGNATION_STATUSES,
    ENTRANT_STATUSES,
    FILING_STATUSES,
    FILING_TYPES,
    INSURANCE_STATUSES,
    LEDGER_ENTRY_TYPES,
    LIABILITY_VARIANTS,
    NEW_ENTRANT_AUDIT_STATUSES,
    PRE_EMBARGO_STATUSES,
    PROCEEDING_REASONS,
    PROCEEDING_STATUSES,
    SHIPMENT_STATUSES,
    SHIPMENT_STATUSES as _SHIPMENT_STATUSES,
    SUSPENSION_REASONS,
    TRANSPORTATION_TYPES,
    UNIFIED_REGISTRATION_STATUSES,
)

_INSTANT = re.compile(C.ISO_INSTANT_PATTERN)


# ---------------------------------------------------------------------------
# Primitive shape helpers
# ---------------------------------------------------------------------------
def assert_instant_format(value: Any, field: str = "instant") -> None:
    """S2.4: an ISO 8601 UTC instant with exactly three fractional digits."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert _INSTANT.match(value), (
        f"{field} must be ISO 8601 UTC with exactly three fractional digits, "
        f"got {value!r}"
    )


def assert_nullable_instant(value: Any, field: str = "instant") -> None:
    if value is not None:
        assert_instant_format(value, field)


def assert_money_cents(value: Any, field: str = "amount_cents") -> None:
    """S2.7: money is an integer number of cents — never a decimal or a string."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer number of cents, got {value!r} "
        f"({type(value).__name__})"
    )


def assert_count(value: Any, field: str = "count") -> None:
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an exact integer, got {value!r}"
    )
    assert value >= 0, f"{field} must not be negative, got {value}"


def assert_enum(value: Any, allowed, field: str) -> None:
    assert value in allowed, f"{field} must be one of {tuple(allowed)}, got {value!r}"


def assert_mutable_common_fields(record: Dict[str, Any], entity: str = "record") -> None:
    """S2.4: id, created_at, updated_at and version >= 1."""
    assert is_valid_uuid(record.get("id")), f"{entity}.id must be a UUID"
    assert_instant_format(record.get("created_at"), f"{entity}.created_at")
    assert_instant_format(record.get("updated_at"), f"{entity}.updated_at")
    version = record.get("version")
    assert isinstance(version, int) and not isinstance(version, bool), (
        f"{entity}.version must be an integer"
    )
    assert version >= 1, f"{entity}.version starts at 1, got {version}"


def assert_immutable_common_fields(record: Dict[str, Any], entity: str = "record") -> None:
    """S2.4: only id and created_at — no updated_at and no version at all."""
    assert is_valid_uuid(record.get("id")), f"{entity}.id must be a UUID"
    assert_instant_format(record.get("created_at"), f"{entity}.created_at")
    assert "updated_at" not in record, (
        f"{entity} is immutable and must carry no updated_at field"
    )
    assert "version" not in record, (
        f"{entity} is immutable and must carry no version field"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_carrier(record: Dict[str, Any]) -> Dict[str, Any]:
    assert_mutable_common_fields(record, "Carrier")
    assert isinstance(record.get("legal_name"), str) and record["legal_name"]
    assert record.get("dba_name") is None or isinstance(record["dba_name"], str)
    assert record.get("domicile_state") in C.VALID_STATE_CODES
    assert_count(record.get("self_reported_vehicle_count"), "self_reported_vehicle_count")
    assert_count(record.get("self_reported_driver_count"), "self_reported_driver_count")
    assert re.match(C.USDOT_NUMBER_PATTERN, record.get("usdot_number", "")), (
        f"usdot_number must match USDOT-#######, got {record.get('usdot_number')!r}"
    )
    assert_enum(
        record.get("unified_registration_status"),
        UNIFIED_REGISTRATION_STATUSES,
        "unified_registration_status",
    )
    assert_enum(record.get("entrant_status"), ENTRANT_STATUSES, "entrant_status")
    assert_enum(
        record.get("compliance_risk_variant"),
        COMPLIANCE_RISK_VARIANTS,
        "compliance_risk_variant",
    )
    for field in (
        "fee_balance_cents",
        "fees_assessed_total_cents",
        "fees_reversed_total_cents",
        "fees_paid_total_cents",
    ):
        assert_money_cents(record.get(field), field)
    assert_count(record.get("active_authority_count"), "active_authority_count")
    assert_instant_format(record.get("biennial_update_due_at"), "biennial_update_due_at")
    assert_nullable_instant(record.get("last_biennial_update_at"), "last_biennial_update_at")
    assert isinstance(record.get("biennial_delinquent"), bool)
    return record


def assert_authority_application(record: Dict[str, Any]) -> Dict[str, Any]:
    assert_mutable_common_fields(record, "AuthorityApplication")
    assert is_valid_uuid(record.get("carrier_id"))
    assert_enum(record.get("status"), APPLICATION_STATUSES, "status")
    assert_enum(
        record.get("transportation_type"), TRANSPORTATION_TYPES, "transportation_type"
    )
    assert isinstance(record.get("requested_operating_states"), list)
    assert_count(record.get("submission_count"), "submission_count")
    for field in (
        "required_bipd_limit_cents",
        "required_cargo_limit_cents",
        "required_bond_limit_cents",
        "filing_fee_cents",
    ):
        assert_money_cents(record.get(field), field)
    breakdown = record.get("filing_fee_breakdown")
    if breakdown is not None:
        assert sorted(breakdown.keys()) == sorted(C.FEE_BREAKDOWN_KEYS), (
            f"filing_fee_breakdown must carry exactly {C.FEE_BREAKDOWN_KEYS}"
        )
        for key, value in breakdown.items():
            assert_money_cents(value, f"filing_fee_breakdown.{key}")
    return record


def assert_operating_authority(record: Dict[str, Any]) -> Dict[str, Any]:
    assert_mutable_common_fields(record, "OperatingAuthority")
    assert is_valid_uuid(record.get("carrier_id"))
    assert is_valid_uuid(record.get("application_id"))
    assert re.match(C.DOCKET_NUMBER_PATTERN, record.get("docket_number", "")), (
        f"docket_number must match MC-######, got {record.get('docket_number')!r}"
    )
    assert_enum(record.get("authority_status"), AUTHORITY_STATUSES, "authority_status")
    assert_enum(record.get("insurance_status"), INSURANCE_STATUSES, "insurance_status")
    assert_enum(record.get("suspension_reason"), SUSPENSION_REASONS, "suspension_reason")
    assert_enum(
        record.get("new_entrant_audit_status"),
        NEW_ENTRANT_AUDIT_STATUSES,
        "new_entrant_audit_status",
    )
    assert isinstance(record.get("required_jurisdictions"), list)
    assert record["required_jurisdictions"] == sorted(record["required_jurisdictions"]), (
        "required_jurisdictions must be sorted ascending by state code"
    )
    for field in (
        "required_bipd_limit_cents",
        "required_cargo_limit_cents",
        "required_bond_limit_cents",
    ):
        assert_money_cents(record.get(field), field)
    for field in (
        "designated_state_count",
        "active_contract_count",
        "suspended_contract_count",
    ):
        assert_count(record.get(field), field)
    assert isinstance(record.get("designation_coverage_complete"), bool)
    assert_instant_format(record.get("publication_at"), "publication_at")
    assert_instant_format(record.get("activation_eligible_at"), "activation_eligible_at")
    for field in ("activated_at", "suspended_at", "revoked_at", "rescinded_at",
                  "new_entrant_audit_deadline_at"):
        assert_nullable_instant(record.get(field), field)
    return record


def assert_process_agent(record: Dict[str, Any]) -> Dict[str, Any]:
    assert_immutable_common_fields(record, "ProcessAgent")
    assert isinstance(record.get("company_name"), str) and record["company_name"]
    assert isinstance(record.get("coverage_states"), list)
    assert isinstance(record.get("blanket_agent"), bool)
    return record


def assert_designation(record: Dict[str, Any]) -> Dict[str, Any]:
    assert_mutable_common_fields(record, "ProcessAgentDesignation")
    assert is_valid_uuid(record.get("authority_id"))
    assert is_valid_uuid(record.get("process_agent_id"))
    assert record.get("state_code") in C.VALID_STATE_CODES
    assert_enum(record.get("status"), DESIGNATION_STATUSES, "status")
    assert_instant_format(record.get("effective_from"), "effective_from")
    assert_nullable_instant(record.get("effective_to"), "effective_to")
    assert_nullable_instant(record.get("revoked_at"), "revoked_at")
    return record


def assert_insurer(record: Dict[str, Any]) -> Dict[str, Any]:
    assert_mutable_common_fields(record, "Insurer")
    assert isinstance(record.get("company_name"), str) and record["company_name"]
    assert re.match(r"^[0-9]{5}$", record.get("naic_code", "")), (
        f"naic_code must be exactly five digits, got {record.get('naic_code')!r}"
    )
    assert isinstance(record.get("authorized_states"), list)
    return record


def assert_insurance_filing(record: Dict[str, Any]) -> Dict[str, Any]:
    assert_mutable_common_fields(record, "InsuranceFiling")
    assert is_valid_uuid(record.get("authority_id"))
    assert is_valid_uuid(record.get("insurer_id"))
    assert_enum(record.get("filing_type"), FILING_TYPES, "filing_type")
    assert_enum(record.get("status"), FILING_STATUSES, "status")
    assert_money_cents(record.get("coverage_limit_cents"), "coverage_limit_cents")
    assert isinstance(record.get("policy_number"), str) and record["policy_number"]
    assert_instant_format(record.get("effective_at"), "effective_at")
    assert_nullable_instant(
        record.get("cancellation_effective_at"), "cancellation_effective_at"
    )
    assert isinstance(record.get("meets_required_minimum"), bool)
    assert record.get("supersedes_filing_id") is None or is_valid_uuid(
        record["supersedes_filing_id"]
    )
    return record


def assert_revocation_proceeding(record: Dict[str, Any]) -> Dict[str, Any]:
    assert_mutable_common_fields(record, "RevocationProceeding")
    assert is_valid_uuid(record.get("authority_id"))
    assert_enum(record.get("reason"), PROCEEDING_REASONS, "reason")
    assert_enum(record.get("status"), PROCEEDING_STATUSES, "status")
    assert_instant_format(record.get("notice_issued_at"), "notice_issued_at")
    assert_instant_format(record.get("cure_deadline_at"), "cure_deadline_at")
    assert_nullable_instant(record.get("cured_at"), "cured_at")
    assert_nullable_instant(record.get("revoked_at"), "revoked_at")
    return record


def assert_safety_audit(record: Dict[str, Any]) -> Dict[str, Any]:
    assert_mutable_common_fields(record, "SafetyAudit")
    assert is_valid_uuid(record.get("carrier_id"))
    assert_enum(record.get("status"), AUDIT_STATUSES, "status")
    assert_instant_format(record.get("audit_window_opens_at"), "audit_window_opens_at")
    assert_instant_format(record.get("audit_deadline_at"), "audit_deadline_at")
    assert_nullable_instant(record.get("result_recorded_at"), "result_recorded_at")
    return record


def assert_customer_contract(record: Dict[str, Any]) -> Dict[str, Any]:
    assert_mutable_common_fields(record, "CustomerContract")
    assert is_valid_uuid(record.get("authority_id"))
    assert isinstance(record.get("shipper_name"), str) and record["shipper_name"]
    assert_enum(record.get("commodity_class"), COMMODITY_CLASSES, "commodity_class")
    assert_enum(record.get("status"), CONTRACT_STATUSES, "status")
    assert_money_cents(
        record.get("monthly_committed_revenue_cents"), "monthly_committed_revenue_cents"
    )
    assert_money_cents(record.get("disruption_liability_cents"), "disruption_liability_cents")
    assert_enum(
        record.get("disruption_liability_variant"),
        LIABILITY_VARIANTS,
        "disruption_liability_variant",
    )
    assert_count(record.get("embargoed_shipment_count"), "embargoed_shipment_count")
    assert_instant_format(record.get("term_start_at"), "term_start_at")
    assert_instant_format(record.get("term_end_at"), "term_end_at")
    for field in ("suspended_at", "resumed_at", "terminated_at"):
        assert_nullable_instant(record.get(field), field)
    return record


def assert_shipment(record: Dict[str, Any]) -> Dict[str, Any]:
    assert_mutable_common_fields(record, "Shipment")
    assert is_valid_uuid(record.get("contract_id"))
    assert record.get("origin_state") in C.VALID_STATE_CODES
    assert record.get("destination_state") in C.VALID_STATE_CODES
    assert_enum(record.get("status"), SHIPMENT_STATUSES, "status")
    assert_enum(
        record.get("pre_embargo_status"), PRE_EMBARGO_STATUSES, "pre_embargo_status"
    )
    assert_money_cents(record.get("declared_value_cents"), "declared_value_cents")
    assert_count(record.get("embargo_days_accrued"), "embargo_days_accrued")
    assert isinstance(record.get("hazmat"), bool)
    assert_instant_format(record.get("tender_at"), "tender_at")
    assert_instant_format(record.get("expected_delivery_at"), "expected_delivery_at")
    for field in ("embargoed_at", "embargo_released_at", "delivered_at", "diverted_at"):
        assert_nullable_instant(record.get(field), field)
    return record


def assert_fee_ledger_entry(record: Dict[str, Any]) -> Dict[str, Any]:
    assert_immutable_common_fields(record, "FeeLedgerEntry")
    assert is_valid_uuid(record.get("carrier_id"))
    assert_enum(record.get("entry_type"), LEDGER_ENTRY_TYPES, "entry_type")
    assert_money_cents(record.get("amount_cents"), "amount_cents")
    assert record["amount_cents"] != 0, "a ledger entry's amount_cents is never zero"
    if record["entry_type"] == "FILING_FEE_DEBIT":
        assert record["amount_cents"] > 0, "a FILING_FEE_DEBIT is positive"
    else:
        assert record["amount_cents"] < 0, "both credit entry types are negative"
    return record


def assert_sweep_result(record: Dict[str, Any]) -> Dict[str, Any]:
    assert_instant_format(record.get("swept_at"), "swept_at")
    for field in (
        "audits_missed_count",
        "carriers_flagged_delinquent_count",
        "authorities_revoked_count",
        "contracts_terminated_count",
    ):
        assert_count(record.get(field), field)
    return record


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_fee_ledger_identities(client, carrier_id: str, headers: Dict[str, str]) -> None:
    """S3.1: both ledger identities, re-asserted after every append.

    ``fee_balance_cents`` equals the signed sum of every entry, and equals
    ``fees_assessed_total_cents`` minus ``fees_reversed_total_cents`` minus
    ``fees_paid_total_cents``.
    """
    carrier = _data(client.get_carrier(carrier_id, headers))
    entries, meta = validate_paginated(
        client.list_fee_ledger_entries(carrier_id, headers, limit=C.MAX_LIMIT)
    )
    assert meta["total_count"] == len(entries), (
        "the ledger listing must return every entry within one page for this check"
    )
    signed_sum = sum(entry["amount_cents"] for entry in entries)
    assert signed_sum == carrier["fee_balance_cents"], (
        f"fee_balance_cents {carrier['fee_balance_cents']} must equal the signed sum "
        f"of the carrier's ledger entries ({signed_sum})"
    )
    derived = (
        carrier["fees_assessed_total_cents"]
        - carrier["fees_reversed_total_cents"]
        - carrier["fees_paid_total_cents"]
    )
    assert derived == carrier["fee_balance_cents"], (
        "fee_balance_cents must equal assessed - reversed - paid, "
        f"got {carrier['fee_balance_cents']} vs {derived}"
    )
    assessed = sum(
        e["amount_cents"] for e in entries if e["entry_type"] == "FILING_FEE_DEBIT"
    )
    reversed_total = sum(
        -e["amount_cents"]
        for e in entries
        if e["entry_type"] == "FILING_FEE_REVERSAL_CREDIT"
    )
    paid = sum(
        -e["amount_cents"] for e in entries if e["entry_type"] == "FEE_PAYMENT_CREDIT"
    )
    assert assessed == carrier["fees_assessed_total_cents"]
    assert reversed_total == carrier["fees_reversed_total_cents"]
    assert paid == carrier["fees_paid_total_cents"]


def assert_contract_population_identity(
    client, authority_id: str, headers: Dict[str, str]
) -> None:
    """S2.10: active_contract_count + suspended_contract_count equals the number
    of that authority's contracts whose status is not TERMINATED."""
    authority = _data(client.get_authority(authority_id, headers))
    contracts, _ = validate_paginated(
        client.list_authority_contracts(authority_id, headers, limit=C.MAX_LIMIT)
    )
    non_terminated = [c for c in contracts if c["status"] != "TERMINATED"]
    total = authority["active_contract_count"] + authority["suspended_contract_count"]
    assert total == len(non_terminated), (
        f"active_contract_count + suspended_contract_count ({total}) must equal the "
        f"count of non-TERMINATED contracts ({len(non_terminated)})"
    )


def assert_no_embargoed_shipments(client, contract_id: str, headers: Dict[str, str]) -> None:
    """S2.10: after a restoration completes, no shipment remains EMBARGOED."""
    shipments, meta = validate_paginated(
        client.list_shipments(headers, contract_id=contract_id, status="EMBARGOED")
    )
    assert meta["total_count"] == 0, (
        f"no shipment on contract {contract_id} may remain EMBARGOED after restoration"
    )
    assert shipments == []


def assert_created_at_ascending(records: List[Dict[str, Any]]) -> None:
    """S2.3: every list endpoint orders its records by created_at ascending."""
    stamps = [r["created_at"] for r in records]
    assert stamps == sorted(stamps), f"records must be ordered created_at ASC: {stamps}"


def assert_risk_score(actual: Any, expected: float) -> None:
    """S2.7: the risk score is rounded to exactly two decimal places."""
    assert actual is not None, "compliance_risk_score must be written"
    assert abs(float(actual) - float(expected)) < 0.005, (
        f"expected risk score {expected}, got {actual}"
    )
    assert Decimal(str(actual)).as_tuple().exponent >= -2, (
        f"risk score carries at most two decimal places, got {actual}"
    )


def _data(response) -> Dict[str, Any]:
    body = response.json()
    assert response.status_code == 200, f"read failed: {response.text}"
    return body["data"]


# ---------------------------------------------------------------------------
# Independent recomputations of the PRD's pinned formulas
# ---------------------------------------------------------------------------
def _half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def expected_required_minimums(
    transportation_type: str,
    state_count: int,
    hazmat_endorsement_requested: bool = False,
    hazmat_bulk_capable: bool = False,
    passenger_seating_capacity: Optional[int] = None,
) -> Dict[str, int]:
    """S3.2: the three required insurance minimums, in cents."""
    if transportation_type == "PASSENGER":
        base = (
            C.BIPD_PASSENGER_SMALL_CENTS
            if (passenger_seating_capacity or 0) <= C.PASSENGER_SEAT_BREAK
            else C.BIPD_PASSENGER_LARGE_CENTS
        )
    elif transportation_type == "PROPERTY_BROKER":
        base = 0
    else:
        base = C.BIPD_PROPERTY_BASE_CENTS
    if hazmat_endorsement_requested:
        floor = (
            C.BIPD_HAZMAT_BULK_CENTS
            if hazmat_bulk_capable
            else C.BIPD_HAZMAT_NONBULK_CENTS
        )
        base = max(base, floor)
    if base > 0 and state_count >= C.MULTISTATE_UPLIFT_THRESHOLD:
        base += C.MULTISTATE_UPLIFT_CENTS
    return {
        "required_bipd_limit_cents": base,
        "required_cargo_limit_cents": (
            C.CARGO_HOUSEHOLD_GOODS_CENTS
            if transportation_type == "HOUSEHOLD_GOODS"
            else 0
        ),
        "required_bond_limit_cents": (
            C.BROKER_BOND_CENTS
            if transportation_type in ("PROPERTY_BROKER", "FREIGHT_FORWARDER")
            else 0
        ),
    }


def expected_filing_fee(
    application_kind: str,
    transportation_type: str,
    state_count: int,
    hazmat_endorsement_requested: bool = False,
) -> Dict[str, int]:
    """S3.2: four lines, each rounded half-up on its own before summation."""
    kind_multiplier = Decimal(str(C.KIND_MULTIPLIER[application_kind]))
    surcharge = Decimal(str(C.ADMIN_SURCHARGE_FACTOR))
    line_docket = _half_up(Decimal(C.DOCKET_BASE_CENTS) * kind_multiplier * surcharge)
    line_states = _half_up(
        Decimal(C.PER_STATE_SURCHARGE_CENTS) * Decimal(state_count) * surcharge
    )
    line_type = _half_up(
        Decimal(C.TYPE_FEE_CENTS[transportation_type]) * kind_multiplier * surcharge
    )
    line_hazmat = (
        _half_up(Decimal(C.HAZMAT_ENDORSEMENT_FEE_CENTS) * surcharge)
        if hazmat_endorsement_requested
        else 0
    )
    breakdown = {
        "line_docket_cents": line_docket,
        "line_states_cents": line_states,
        "line_type_cents": line_type,
        "line_hazmat_cents": line_hazmat,
    }
    breakdown["filing_fee_cents"] = line_docket + line_states + line_type + line_hazmat
    return breakdown


def _clamped_two_decimals(raw: Decimal) -> float:
    clamped = min(max(raw, Decimal(str(C.SCORE_FLOOR))), Decimal(str(C.SCORE_CEILING)))
    return float(clamped.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def expected_self_reported_score(
    vehicle_count: int, driver_count: int, oos_rate_pct: float
) -> float:
    """S3.6: the self-reported variant of the compliance risk score."""
    oos_component = min(Decimal(str(oos_rate_pct)) * 2, Decimal(100))
    divisor = Decimal(max(vehicle_count, 1))
    driver_component = min(Decimal(driver_count) / divisor * 20, Decimal(100))
    vehicle_component = min(
        Decimal(vehicle_count) / Decimal(C.FLEET_NORMALIZER) * 10, Decimal(100)
    )
    raw = (
        oos_component * Decimal(str(C.W_OOS))
        + driver_component * Decimal(str(C.W_DRIVER))
        + vehicle_component * Decimal(str(C.W_VEHICLE))
    )
    return _clamped_two_decimals(raw)


def expected_audited_score(
    audited_oos_rate_pct: float,
    driver_violation_count: int,
    vehicle_defect_count: int,
    acute_violation_count: int,
) -> float:
    """S3.7: the audited variant, whose components come from measured counts."""
    oos_component = min(Decimal(str(audited_oos_rate_pct)) * 2, Decimal(100))
    driver_component = min(Decimal(driver_violation_count) * 5, Decimal(100))
    vehicle_component = min(Decimal(vehicle_defect_count) * 4, Decimal(100))
    raw = (
        oos_component * Decimal(str(C.W_OOS))
        + driver_component * Decimal(str(C.W_DRIVER))
        + vehicle_component * Decimal(str(C.W_VEHICLE))
        + Decimal(str(C.ACUTE_VIOLATION_PENALTY)) * Decimal(acute_violation_count)
    )
    return _clamped_two_decimals(raw)


def expected_suspension_estimate(monthly_cents: int, remaining_days: int) -> int:
    """S3.9: the forward-looking suspension estimate, in cents."""
    daily = Decimal(monthly_cents) / Decimal(C.DAILY_DIVISOR)
    return _half_up(daily * Decimal(remaining_days) * Decimal(str(C.EMBARGO_PENALTY_PCT)))


def expected_settled_actual(
    monthly_cents: int, elapsed_days: int, embargoed_shipment_count: int
) -> int:
    """S3.9: the settled actual, evaluated in the six pinned steps."""
    daily = Decimal(monthly_cents) / Decimal(C.DAILY_DIVISOR)
    penalty = Decimal(str(C.EMBARGO_PENALTY_PCT))
    base_charge = _half_up(daily * Decimal(elapsed_days) * penalty)
    shipment_penalty = _half_up(daily * Decimal(embargoed_shipment_count) * penalty)
    subtotal = base_charge + shipment_penalty
    waiver_rate = (
        Decimal(str(C.GOODWILL_WAIVER_PCT))
        if subtotal >= C.GOODWILL_TIER_CENTS
        else Decimal(0)
    )
    waiver = _half_up(Decimal(subtotal) * waiver_rate)
    return subtotal - waiver
