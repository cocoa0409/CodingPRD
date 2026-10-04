"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AgreementStatus, AgreementType, AlertCode, AlertStatus, AuditoriumStatus,
    DispatchStatus, FilmStatus, Format, MarketStatus, PriorityTier,
    ReportStatus, Severity, SlotStatus, StatementStatus, StudioStatus,
    ConversionOrderStatus, TechSpecialty, WindowStatus, SubmissionChannel,
)


def assert_market(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data["market_name"], str) and data["market_name"]
    assert isinstance(data["country_code"], str) and data["country_code"]
    assert isinstance(data["screen_capacity_cap"], int)
    assert isinstance(data["target_format_mix"], list)
    assert isinstance(data["opened_screen_count"], int)
    assert data["status"] in {s.value for s in MarketStatus}


def assert_agreement(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data["exhibitor_legal_name"], str)
    assert isinstance(data["market_id"], str)
    assert data["agreement_type"] in {t.value for t in AgreementType}
    assert isinstance(data["committed_screen_count"], int)
    assert isinstance(data["total_slots_committed_count"], int)
    assert data["status"] in {s.value for s in AgreementStatus}


def assert_auditorium(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data["agreement_id"], str)
    assert isinstance(data["auditorium_label"], str)
    assert isinstance(data["screen_geometry"], dict)
    assert isinstance(data["seating_capacity"], int)
    assert isinstance(data["supported_formats"], list)
    assert isinstance(data["sound_calibration_profile"], dict)
    assert data["status"] in {s.value for s in AuditoriumStatus}


def assert_studio(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data["studio_legal_name"], str)
    assert isinstance(data["contact_email"], str)
    assert data["status"] in {s.value for s in StudioStatus}


def assert_film(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data["studio_id"], str)
    assert isinstance(data["title"], str)
    assert isinstance(data["runtime_minutes"], int) and data["runtime_minutes"] > 0
    assert isinstance(data["format_targets"], list)
    assert data["status"] in {s.value for s in FilmStatus}


def assert_conversion_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data["studio_film_id"], str)
    assert data["target_format"] in {f.value for f in Format}
    assert isinstance(data["filmmaker_approval_required"], bool)
    assert isinstance(data["filmmaker_signoff"], bool)
    assert isinstance(data["post_cost_estimate_cents"], int)
    assert data["status"] in {s.value for s in ConversionOrderStatus}


def assert_release_window(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data["window_label"], str)
    assert isinstance(data["total_premium_screen_seconds_pool"], int)
    assert isinstance(data["committed_premium_screen_seconds"], int)
    assert data["status"] in {s.value for s in WindowStatus}


def assert_screen_slot(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data["window_id"], str)
    assert isinstance(data["auditorium_id"], str)
    assert isinstance(data["studio_film_id"], str)
    assert isinstance(data["conversion_order_id"], str)
    assert isinstance(data["showings_per_day"], int) and data["showings_per_day"] >= 1
    assert data["priority_tier"] in {t.value for t in PriorityTier}
    assert isinstance(data["committed_screen_seconds"], int)
    assert data["status"] in {s.value for s in SlotStatus}


def assert_box_office_report(data: dict):
    # PRD §2.4: BoxOfficeReport carries only id and created_at of the system
    # fields — updated_at and version are absent on this immutable record.
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "BoxOfficeReport must not carry updated_at"
    assert "version" not in data, "BoxOfficeReport must not carry version"
    assert isinstance(data["screen_slot_id"], str)
    assert isinstance(data["gross_receipts_cents"], int) and data["gross_receipts_cents"] >= 0
    assert isinstance(data["admissions"], int) and data["admissions"] >= 0
    assert data["submission_channel"] in {c.value for c in SubmissionChannel}
    assert data["status"] in {s.value for s in ReportStatus}


def assert_statement(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data["agreement_id"], str)
    assert isinstance(data["window_id"], str)
    assert isinstance(data["statement_lines"], list)
    assert isinstance(data["provisional_total_cents"], (int, float))
    assert isinstance(data["final_total_cents"], (int, float))
    assert data["status"] in {s.value for s in StatementStatus}


def assert_qa_alert(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data["auditorium_id"], str)
    assert data["alert_code"] in {c.value for c in AlertCode}
    assert data["severity"] in {s.value for s in Severity}
    assert data["status"] in {s.value for s in AlertStatus}


def assert_tech_dispatch(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data["qa_alert_id"], str)
    assert isinstance(data["auditorium_id"], str)
    assert data["tech_specialty"] in {s.value for s in TechSpecialty}
    assert data["status"] in {s.value for s in DispatchStatus}


def get_statement_line(statement: dict, slot_id: str) -> dict:
    """Locate one statement line by its screen_slot_id (PRD §3.6)."""
    for line in statement.get("statement_lines", []):
        if line.get("screen_slot_id") == slot_id:
            return line
    raise AssertionError(
        f"No statement line for screen_slot_id={slot_id}; "
        f"lines present: {[l.get('screen_slot_id') for l in statement.get('statement_lines', [])]}"
    )


def assert_line_conservation_invariant(line: dict):
    """PRD §3.6: for each line, exhibitor-retained plus agreed-share always
    equals gross-reported."""
    retained = line["exhibitor_retained_cents"]
    share = line["agreed_share_cents"]
    gross = line["gross_reported_cents"]
    assert abs(retained + share - gross) < 1e-6, (
        f"invariant violated: exhibitor_retained_cents ({retained}) + "
        f"agreed_share_cents ({share}) != gross_reported_cents ({gross})"
    )
