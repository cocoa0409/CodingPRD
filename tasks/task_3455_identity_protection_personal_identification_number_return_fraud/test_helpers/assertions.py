"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the common system-managed fields (PRD
section 2.5) plus the entity's own field types and enum memberships, using
PRD-exact field names. VerificationDocument is the sole common-fields
exception: it carries only id and created_at, and both updated_at and
version must be ABSENT.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    AdvocateCaseStatus,
    AlertStatus,
    AppointmentStatus,
    BankProduct,
    ClaimStatus,
    ConfigStatus,
    ConflictResolution,
    ConflictResolvedReason,
    ConflictStatus,
    DocType,
    FilingStatus,
    FilterHoldStatus,
    HardshipType,
    HoldZone,
    IpPinEnrollment,
    PatternType,
    PinDeliveryChannel,
    PinStatus,
    PreparerStatus,
    Relationship,
    ReportSource,
    ReportStatus,
    TaxpayerStatus,
    TaxReturnStatus,
    VerificationCaseStatus,
    VerificationChannel,
    DisbursementStatus,
)


# ─── Common-field helpers (PRD section 2.5) ──────────

def assert_common_fields(data: dict):
    """id (UUID), created_at/updated_at (ISO 8601), version (int >= 1)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an int starting at 1, got {data.get('version')!r}"
    )


def _assert_enum(data: dict, field: str, enum_cls):
    assert data.get(field) in {e.value for e in enum_cls}, (
        f"{field} must be one of {[e.value for e in enum_cls]}, got {data.get(field)!r}"
    )


def _assert_cents(data: dict, field: str, minimum=None):
    assert isinstance(data.get(field), int) and not isinstance(data.get(field), bool), (
        f"{field} must be integer cents, got {data.get(field)!r}"
    )
    if minimum is not None:
        assert data[field] >= minimum, f"{field} must be >= {minimum}, got {data[field]}"


def _assert_tin(value: str, field: str = "tin"):
    assert isinstance(value, str) and len(value) == 9 and value.isdigit(), (
        f"{field} must be exactly 9 digits, got {value!r}"
    )


# ─── Per-entity assertions ───────────────────────────

def assert_taxpayer(data: dict):
    assert_common_fields(data)
    _assert_tin(data.get("tin"))
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("date_of_birth"), str) and data["date_of_birth"]
    _assert_cents(data, "prior_year_refund_cents", minimum=0)
    _assert_enum(data, "pin_delivery_channel", PinDeliveryChannel)
    _assert_enum(data, "status", TaxpayerStatus)
    _assert_enum(data, "ip_pin_enrollment", IpPinEnrollment)


def assert_identity_theft_report(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("taxpayer_id", "")), "taxpayer_id must be a UUID"
    _assert_enum(data, "source", ReportSource)
    assert isinstance(data.get("description"), str)
    assert isinstance(data.get("created_by_user_id"), str) and data["created_by_user_id"]
    cty = data.get("confirmed_tax_year")
    assert cty is None or isinstance(cty, int), (
        f"confirmed_tax_year must be null or an int, got {cty!r}"
    )
    _assert_enum(data, "status", ReportStatus)


def assert_protection_pin(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("taxpayer_id", "")), "taxpayer_id must be a UUID"
    assert isinstance(data.get("tax_year"), int)
    pin = data.get("pin_value")
    assert isinstance(pin, str) and len(pin) == 6 and pin.isdigit(), (
        f"pin_value must be a 6-digit string, got {pin!r}"
    )
    _assert_enum(data, "delivery_channel", PinDeliveryChannel)
    _assert_enum(data, "status", PinStatus)


def assert_preparer(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("ptin"), str) and data["ptin"]
    assert isinstance(data.get("firm_name"), str) and data["firm_name"]
    _assert_enum(data, "status", PreparerStatus)
    assert isinstance(data.get("filed_return_count"), int) and data["filed_return_count"] >= 0


def assert_tax_return(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("taxpayer_id", "")), "taxpayer_id must be a UUID"
    pid = data.get("preparer_id")
    assert pid is None or is_valid_uuid(pid), f"preparer_id must be null or UUID, got {pid!r}"
    assert isinstance(data.get("tax_year"), int)
    _assert_enum(data, "filing_status", FilingStatus)
    _assert_cents(data, "claimed_refund_cents", minimum=0)
    _assert_enum(data, "bank_product", BankProduct)
    assert is_iso8601_timestamp(data.get("received_at", "")), "received_at must be ISO 8601"
    score = data.get("risk_score")
    assert isinstance(score, int) and 0 <= score <= 100, (
        f"risk_score must be an int in [0, 100], got {score!r}"
    )
    assert isinstance(data.get("scoring_model_version"), str) and data["scoring_model_version"]
    _assert_cents(data, "adjustment_cents")
    _assert_enum(data, "status", TaxReturnStatus)


def assert_filter_hold(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("return_id", "")), "return_id must be a UUID"
    assert isinstance(data.get("risk_score"), int)
    assert isinstance(data.get("model_version"), str) and data["model_version"]
    _assert_enum(data, "zone", HoldZone)
    reasons = data.get("reason_codes")
    assert isinstance(reasons, list) and all(isinstance(r, str) for r in reasons), (
        f"reason_codes must be a list of strings, got {reasons!r}"
    )
    assert isinstance(data.get("priority_review"), bool)
    _assert_enum(data, "status", FilterHoldStatus)


def assert_verification_case(data: dict):
    assert_common_fields(data)
    rid = data.get("return_id")
    assert rid is None or is_valid_uuid(rid), f"return_id must be null or UUID, got {rid!r}"
    assert is_valid_uuid(data.get("taxpayer_id", "")), "taxpayer_id must be a UUID"
    _assert_enum(data, "channel", VerificationChannel)
    assert isinstance(data.get("attempts_count"), int) and data["attempts_count"] >= 0
    docs = data.get("required_document_types")
    assert isinstance(docs, list) and all(
        d in {e.value for e in DocType} for d in docs
    ), f"required_document_types must list valid doc types, got {docs!r}"
    assert is_iso8601_timestamp(data.get("deadline_at", "")), "deadline_at must be ISO 8601"
    _assert_enum(data, "status", VerificationCaseStatus)


def assert_verification_document(data: dict):
    """VerificationDocument is immutable: id + created_at only as common
    fields; updated_at and version must be absent (PRD section 2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "VerificationDocument must not carry updated_at"
    assert "version" not in data, "VerificationDocument must not carry version"
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a UUID"
    _assert_enum(data, "doc_type", DocType)
    assert is_iso8601_timestamp(data.get("received_at", "")), "received_at must be ISO 8601"


def assert_service_office(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("office_code"), str) and data["office_code"]
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("capacity"), int) and data["capacity"] >= 1, (
        f"capacity must be an int >= 1, got {data.get('capacity')!r}"
    )


def assert_verification_appointment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("office_id", "")), "office_id must be a UUID"
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a UUID"
    assert is_iso8601_timestamp(data.get("start_at", "")), "start_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("end_at", "")), "end_at must be ISO 8601"
    assert data["end_at"] > data["start_at"], "end_at must be strictly after start_at"
    _assert_enum(data, "status", AppointmentStatus)


def assert_dependent_claim(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("return_id", "")), "return_id must be a UUID"
    _assert_tin(data.get("dependent_tin"), field="dependent_tin")
    _assert_enum(data, "relationship", Relationship)
    _assert_cents(data, "credit_cents", minimum=0)
    _assert_enum(data, "status", ClaimStatus)


def assert_dependent_conflict(data: dict):
    assert_common_fields(data)
    _assert_tin(data.get("dependent_tin"), field="dependent_tin")
    assert isinstance(data.get("tax_year"), int)
    assert is_valid_uuid(data.get("return_a_id", "")), "return_a_id must be a UUID"
    assert is_valid_uuid(data.get("return_b_id", "")), "return_b_id must be a UUID"
    assert is_iso8601_timestamp(data.get("evidence_window_ends_at", "")), (
        "evidence_window_ends_at must be ISO 8601"
    )
    assert isinstance(data.get("evidence_a_submitted"), bool)
    assert isinstance(data.get("evidence_b_submitted"), bool)
    res = data.get("resolution")
    assert res is None or res in {e.value for e in ConflictResolution}, (
        f"resolution must be null/FIRST_FILER/SECOND_FILER, got {res!r}"
    )
    why = data.get("resolved_reason")
    assert why is None or why in {e.value for e in ConflictResolvedReason}, (
        f"resolved_reason must be null or a declared reason, got {why!r}"
    )
    _assert_enum(data, "status", ConflictStatus)


def assert_fraud_scheme_alert(data: dict):
    assert_common_fields(data)
    pid = data.get("preparer_id")
    assert pid is None or is_valid_uuid(pid), f"preparer_id must be null or UUID, got {pid!r}"
    _assert_enum(data, "pattern_type", PatternType)
    evidence = data.get("evidence")
    assert isinstance(evidence, dict), "evidence must be an object"
    assert isinstance(evidence.get("return_ids"), list), "evidence.return_ids must be a list"
    assert isinstance(evidence.get("window_days"), int), "evidence.window_days must be an int"
    assert isinstance(evidence.get("match_count"), int), "evidence.match_count must be an int"
    cb = data.get("confirmed_by_user_id")
    assert cb is None or isinstance(cb, str)
    _assert_enum(data, "status", AlertStatus)


def assert_refund_disbursement(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("return_id", "")), "return_id must be a UUID"
    _assert_cents(data, "base_cents")
    _assert_cents(data, "provisional_interest_cents", minimum=0)
    fin = data.get("final_interest_cents")
    assert fin is None or isinstance(fin, int), (
        f"final_interest_cents must be null or int, got {fin!r}"
    )
    _assert_cents(data, "amount_cents")
    assert is_iso8601_timestamp(data.get("scheduled_at", "")), "scheduled_at must be ISO 8601"
    rel = data.get("released_at")
    assert rel is None or is_iso8601_timestamp(rel), (
        f"released_at must be null or ISO 8601, got {rel!r}"
    )
    _assert_enum(data, "status", DisbursementStatus)


def assert_advocate_case(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("taxpayer_id", "")), "taxpayer_id must be a UUID"
    rid = data.get("return_id")
    assert rid is None or is_valid_uuid(rid), f"return_id must be null or UUID, got {rid!r}"
    _assert_enum(data, "hardship_type", HardshipType)
    assert isinstance(data.get("expedited"), bool)
    assert isinstance(data.get("opened_by_user_id"), str) and data["opened_by_user_id"]
    assert isinstance(data.get("resolution_note"), str)
    _assert_enum(data, "status", AdvocateCaseStatus)


def assert_filter_model_config(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("model_version"), str) and data["model_version"]
    for knob in (
        "w_victim_flagged",
        "w_refund_delta",
        "w_bank_product",
        "w_preparer_flagged",
        "w_dependent_conflict",
        "interaction_bonus",
        "gray_zone_threshold",
        "hold_threshold",
    ):
        assert isinstance(data.get(knob), int) and not isinstance(data.get(knob), bool), (
            f"{knob} must be an int, got {data.get(knob)!r}"
        )
    _assert_enum(data, "status", ConfigStatus)


# ─── Domain invariants ───────────────────────────────

def assert_single_active_pin(pins: list, tax_year: int):
    """At most one ProtectionPin may be ACTIVE for a given taxpayer and tax
    year (PRD section 3.2)."""
    active = [
        p for p in pins
        if p.get("status") == "ACTIVE" and p.get("tax_year") == tax_year
    ]
    assert len(active) == 1, (
        f"Expected exactly 1 ACTIVE pin for tax_year {tax_year}, got {len(active)}: {pins}"
    )
    return active[0]


def assert_envelope_meta(meta: dict):
    """Success/error meta object: api_request_id starts with 'req_' and
    api_request_timestamp is ISO 8601 (PRD section 2.2)."""
    req_id = meta.get("api_request_id")
    assert isinstance(req_id, str) and req_id.startswith("req_"), (
        f"meta.api_request_id must start with 'req_', got {req_id!r}"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", "")), (
        f"meta.api_request_timestamp must be ISO 8601, got "
        f"{meta.get('api_request_timestamp')!r}"
    )


def assert_amount_consistency(disbursement: dict):
    """While SCHEDULED, amount_cents == base_cents + provisional_interest_cents;
    once RELEASED, amount_cents == base_cents + final_interest_cents
    (PRD section 3.8)."""
    status = disbursement.get("status")
    if status == "RELEASED":
        assert disbursement["amount_cents"] == (
            disbursement["base_cents"] + disbursement["final_interest_cents"]
        ), "RELEASED disbursement amount must equal base + final interest"
    elif status == "SCHEDULED":
        assert disbursement["amount_cents"] == (
            disbursement["base_cents"] + disbursement["provisional_interest_cents"]
        ), "SCHEDULED disbursement amount must equal base + provisional interest"
