"""Per-resource assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

COMMON_FIELDS_EXEMPT = ("BreedHandlingRule", "RabiesCertificate", "GroomingRiskScreening")


def _assert_common(data: dict, label: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{label} id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label} created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label} updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{label} version must be an integer"
    assert data["version"] >= 1, f"{label} version starts at 1"


def _assert_append_only(data: dict, label: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{label} id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label} created_at must be ISO 8601"
    assert "updated_at" not in data, f"{label} must not carry updated_at"
    assert "version" not in data, f"{label} must not carry version"


def assert_store(data: dict) -> None:
    _assert_common(data, "Store")
    assert isinstance(data["store_code"], str) and data["store_code"]
    assert data["state_code"] in ("CA", "TX", "NY", "FL")
    assert isinstance(data["service_bay_count"], int) and data["service_bay_count"] >= 1
    assert isinstance(data["hospital_capacity"], int) and data["hospital_capacity"] >= 1
    assert isinstance(data["hospital_occupancy"], int)
    assert data["hospital_posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    assert data.get("pharmacy_hold_until") is None or is_iso8601_timestamp(data["pharmacy_hold_until"])
    for field in (
        "cross_sell_credit_balance_cents",
        "incident_risk_index",
        "restricted_training_slots_pending",
        "frozen_vaccination_clinics",
        "stores_held_total",
    ):
        assert isinstance(data[field], int), f"Store.{field} must be an integer"


def assert_member(data: dict) -> None:
    _assert_common(data, "Member")
    assert data["status"] in ("ACTIVE", "DORMANT", "SUSPENDED")
    assert isinstance(data["outstanding_balance_cents"], int)
    assert "@" in data["email"]


def assert_pet(data: dict) -> None:
    _assert_common(data, "Pet")
    assert data["species"] in ("CANINE", "FELINE")
    assert data["status"] in ("ACTIVE", "ARCHIVED")
    assert isinstance(data["risk_score"], int)
    assert data["weight_kg"] > 0
    expiry = data.get("rabies_vaccination_expires_at")
    assert expiry is None or is_iso8601_timestamp(expiry)


def assert_breed_rule(data: dict) -> None:
    _assert_append_only(data, "BreedHandlingRule")
    assert data["species"] in ("CANINE", "FELINE")
    assert data["handling_tier"] in ("STANDARD", "SENSITIVE", "HIGH_RISK")
    assert isinstance(data["risk_points"], int) and data["risk_points"] >= 0
    assert isinstance(data["allowed_for_grooming"], bool)


def assert_service_bay(data: dict) -> None:
    _assert_common(data, "ServiceBay")
    assert data["bay_code"] in ("GROOMING", "VETERINARY", "TRAINING", "VACCINATION")
    assert data["status"] in ("ACTIVE", "FROZEN", "DISABLED")
    assert isinstance(data["is_frozen"], bool)


def assert_service_booking(data: dict) -> None:
    _assert_common(data, "ServiceBooking")
    assert data["service_type"] in ("GROOMING", "TRAINING", "VETERINARY", "VACCINATION")
    assert data["status"] in (
        "REQUESTED", "SCREENED", "BAY_CONFIRMED", "IN_SERVICE", "COMPLETED", "CANCELLED", "NO_SHOW"
    )
    assert isinstance(data["screening_score"], int)
    assert isinstance(data["re_screen_required"], bool)


def assert_veterinary_encounter(data: dict) -> None:
    _assert_common(data, "VeterinaryEncounter")
    assert data["status"] in ("SCHEDULED", "CHECKED_IN", "IN_EXAM", "COMPLETED", "CANCELLED")
    assert isinstance(data["charge_total_cents"], int)
    assert data.get("exam_date") is None or is_iso8601_timestamp(data["exam_date"])


def assert_vaccination_clinic(data: dict) -> None:
    _assert_common(data, "VaccinationClinic")
    assert data["clinic_status"] in ("SCHEDULED", "OPEN", "FROZEN", "CLOSED")
    assert isinstance(data["coverage_required"], bool)


def assert_vaccination_visit(data: dict) -> None:
    _assert_common(data, "VaccinationVisit")
    assert data["vaccine_type"] in ("RABIES", "BORDETELLA", "DHPP", "FVRCP")
    assert data["status"] in ("REGISTERED", "CERTIFICATE_ISSUED", "REPORT_REQUIRED", "REPORTED", "BLOCKED")
    assert data["state_report_status"] in ("PENDING", "SUBMITTED", "NOT_REQUIRED", "OVERDUE")


def assert_rabies_certificate(data: dict) -> None:
    _assert_append_only(data, "RabiesCertificate")
    assert isinstance(data["serial"], str) and data["serial"]
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["effective_days"] in (365, 1095)
    assert isinstance(data["is_booster"], bool)
    assert isinstance(data["is_effective"], bool)


def assert_grooming_risk_screening(data: dict) -> None:
    _assert_append_only(data, "GroomingRiskScreening")
    assert isinstance(data["risk_total"], int)
    assert data["handling_level"] in ("STANDARD", "SENSITIVE", "HIGH_RISK")
    assert isinstance(data["aggression_acknowledged"], bool)


def assert_prescription_authorization(data: dict) -> None:
    _assert_common(data, "PrescriptionAuthorization")
    assert data["item_type"] in ("MEDICATION", "DIET", "TREATMENT")
    assert data["status"] in (
        "PENDING_EXAM", "AUTHORIZED", "PARTIALLY_DISPENSED", "DISPENSED", "EXPIRED", "REVOKED"
    )
    assert data["retail_facing"] is True
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1


def assert_pharmacy_order(data: dict) -> None:
    _assert_common(data, "PharmacyOrder")
    assert data["status"] in ("REQUESTED", "AUTHORIZED", "DISPENSED", "REJECTED")
    assert data["on_hold"] in ("NONE", "HOLDING")
    assert isinstance(data["requested_quantity"], int) and data["requested_quantity"] >= 1


def assert_incident_record(data: dict) -> None:
    _assert_common(data, "IncidentRecord")
    assert data["severity"] in ("MINOR", "MODERATE", "SEVERE")
    assert data["incident_type"] in ("PET_INJURY", "HANDLER_INJURY", "BITE")
    assert data["claim_status"] in ("UNREVIEWED", "UNDER_REVIEW", "APPROVED", "DENIED")
    assert isinstance(data["claim_amount_cents"], int) and data["claim_amount_cents"] >= 0
    assert isinstance(data["payout_amount_cents"], int)


def assert_service_package(data: dict) -> None:
    _assert_common(data, "ServicePackage")
    assert data["tier"] in ("ESSENTIAL", "PLUS", "UNLIMITED")
    assert data["status"] in ("ACTIVE", "PAUSED", "CANCELLED")
    assert data["billing_cycle_count"] in (1, 3, 6, 12)
    assert isinstance(data["included_visits_total"], int)
    assert isinstance(data["consumed_visits"], int)
    assert isinstance(data["cycles_consumed"], int)


def assert_package_billing_cycle(data: dict) -> None:
    _assert_common(data, "PackageBillingCycle")
    assert data["status"] in ("PENDING", "BILLED", "FAILED", "VOID")
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 1


def assert_retail_cross_sell(data: dict) -> None:
    _assert_common(data, "RetailCrossSell")
    assert data["status"] in ("PENDING", "REDEEMED", "EXPIRED")
    assert isinstance(data["credit_granted_cents"], int)
    assert isinstance(data["credit_redeemed_cents"], int)


def assert_training_enrollment(data: dict) -> None:
    _assert_common(data, "TrainingEnrollment")
    assert data["status"] in ("PENDING_ACK", "RESTRICTED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert isinstance(data["courses_required"], int) and data["courses_required"] >= 1
    assert 0 <= data["courses_completed"] <= data["courses_required"]
    assert data["courses_needed"] == data["courses_required"] - data["courses_completed"]


# ── Domain invariants ────────────────────────────────────────────────────────

def assert_store_invariants(data: dict) -> None:
    """Counters that must hold after any operation against the store."""
    assert data["hospital_occupancy"] >= 0
    assert data["cross_sell_credit_balance_cents"] >= 0
    assert data["incident_risk_index"] >= 0
    assert data["restricted_training_slots_pending"] >= 0
    assert data["frozen_vaccination_clinics"] >= 0
    assert data["stores_held_total"] >= 0
    if data["hospital_posture"] == "OPEN":
        assert data.get("pharmacy_hold_until") is None or is_iso8601_timestamp(data["pharmacy_hold_until"])


def assert_member_balance_invariant(member: dict, packages: list, cycles: list) -> None:
    """Member balance equals the sum of live package totals less billed cycles.

    PRD §2.9: the balance is the sum of ``total_price_cents`` across packages
    whose status is not CANCELLED, less the sum of ``cycle_total_cents`` across
    the BILLED cycles of those packages.
    """
    live = [p for p in packages if p["status"] != "CANCELLED"]
    live_ids = {p["id"] for p in live}
    granted = sum(float(p["total_price_cents"]) for p in live)
    billed = sum(float(c["cycle_total_cents"]) for c in cycles
                 if c["status"] == "BILLED" and c["package_id"] in live_ids)
    expected = round(granted - billed, 2)
    assert member["outstanding_balance_cents"] == expected, (
        f"Balance {member['outstanding_balance_cents']} != {expected} "
        f"(granted {granted} minus billed {billed})"
    )


def assert_cross_sell_balance_invariant(store: dict, cross_sells: list) -> None:
    """Store cross-sell balance equals granted minus redeemed over live cross-sells.

    PRD §2.9: EXPIRED cross-sells drop out of the granted term.
    """
    granted = sum(
        c["credit_granted_cents"] for c in cross_sells if c["status"] in ("PENDING", "REDEEMED")
    )
    redeemed = sum(c["credit_redeemed_cents"] for c in cross_sells if c["status"] == "REDEEMED")
    assert store["cross_sell_credit_balance_cents"] == round(granted - redeemed, 2)