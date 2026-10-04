"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_contract(data):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("agency_name"), str) and data["agency_name"]
    assert isinstance(data.get("measurement_tz"), str) and data["measurement_tz"]
    assert isinstance(data.get("cap_absolutes"), bool)
    assert data.get("status") in ("DRAFT", "ACTIVE", "CLOSED")
    assert isinstance(data.get("withheld_cents_cum"), int)
    assert isinstance(data.get("cure_periods_used"), int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)


def assert_service_level(data):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("contract_id", ""))
    assert isinstance(data.get("program_code"), str) and data["program_code"]
    assert data.get("metric") in ("ASA", "ABANDON", "QA_AVG")
    assert isinstance(data.get("target"), (int, float))
    assert isinstance(data.get("cap_pct_of_gross"), (int, float))
    assert isinstance(data.get("remedy_fee_cents"), int)
    assert data.get("status") in ("DRAFT", "EFFECTIVE", "SUPERSEDED", "ARCHIVED")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data.get("version"), int)


def assert_agent(data):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("languages"), list)
    assert data.get("employment_status") in ("ACTIVE", "INACTIVE")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data.get("version"), int)


def assert_certification(data):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("agent_id", ""))
    assert isinstance(data.get("program_code"), str)
    assert is_valid_uuid(data.get("training_course_id", ""))
    assert isinstance(data.get("valid_until"), str)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    # Append-only record: no version, no updated_at (PRD Section 2.5).
    assert "version" not in data, "certification must not carry version"
    assert "updated_at" not in data, "certification must not carry updated_at"


def assert_course_completion(data):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("training_course_id", ""))
    assert is_valid_uuid(data.get("agent_id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "version" not in data, "course completion must not carry version"
    assert "updated_at" not in data, "course completion must not carry updated_at"


def assert_queue(data):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("contract_id", ""))
    assert data.get("status") in ("OPEN", "PAUSED", "CLOSED")
    assert data.get("queue_type") in ("GENERAL", "SPECIALTY")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data.get("version"), int)


def assert_call(data):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("contract_id", ""))
    assert data.get("status") in (
        "WAITING",
        "ASSIGNED",
        "ANSWERED",
        "COMPLETED",
        "ABANDONED",
    )
    assert isinstance(data.get("route_depth"), int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data.get("version"), int)


def assert_quality_review(data):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("call_id", ""))
    assert 0 <= data.get("accuracy_score") <= 100
    assert 0 <= data.get("compliance_score") <= 100
    assert isinstance(data.get("total_score"), int)
    assert 0 <= data["total_score"] <= 100
    assert data.get("status") in (
        "SUBMITTED",
        "ACCEPTED",
        "DISPUTED",
        "UPHELD",
        "OVERTURNED",
    )
    assert isinstance(data.get("final"), bool)
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_coaching_plan(data):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("agent_id", ""))
    assert data.get("trigger") in ("AUTO_QUALITY", "MANUAL")
    assert data.get("status") in ("OPEN", "COMPLETED", "ESCALATED", "CANCELLED")
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_surge_window(data):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("contract_id", ""))
    assert data.get("surge_type") in (
        "ENROLLMENT_PERIOD",
        "POLICY_CHANGE",
        "PUBLIC_EVENT",
    )
    assert data.get("status") in ("DECLARED", "ACTIVE", "EXPIRED", "CANCELLED")
    assert data.get("expected_volume_factor") > 1.0
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_incident(data):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("contract_id", ""))
    assert data.get("severity") in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert data.get("category") in ("PRIVACY_BREACH", "SECURITY", "DATA_QUALITY")
    assert data.get("status") in ("OPEN", "CONTAINED", "RESOLVED", "CLOSED")
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_invoice(data):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("contract_id", ""))
    assert isinstance(data.get("period"), str)
    assert data.get("status") in ("DRAFT", "SUBMITTED", "APPROVED", "PAID", "REJECTED")
    assert isinstance(data.get("withheld_cents"), int)
    assert isinstance(data.get("auto_review"), bool)
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_invoice_line(data):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("invoice_id", ""))
    assert is_valid_uuid(data.get("service_level_id", ""))
    assert data.get("metric") in ("ASA", "ABANDON", "QA_AVG")
    assert isinstance(data.get("staffing_actual"), int)
    assert isinstance(data.get("staffing_target"), int)
    assert isinstance(data.get("compliant"), bool)
    assert isinstance(data.get("withheld_cents"), int)


def assert_cure_period(data):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("invoice_line_id", ""))
    assert data.get("status") in ("PENDING", "REMEDIED", "FORFEIT")
    assert isinstance(data.get("remedy_fee_cents"), int)
    assert is_iso8601_timestamp(data.get("opened_at", ""))
    assert is_iso8601_timestamp(data.get("deadline", ""))


def assert_invoice_money_invariant(invoice):
    """net_cents == gross_cents - withheld_cents whenever gross is computed."""
    if invoice.get("gross_cents") is not None:
        assert (
            invoice["gross_cents"] - invoice["withheld_cents"] == invoice["net_cents"]
        ), (
            f"money invariant violated: {invoice['gross_cents']} - "
            f"{invoice['withheld_cents']} != {invoice['net_cents']}"
        )
