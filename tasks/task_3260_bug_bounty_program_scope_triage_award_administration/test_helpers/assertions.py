"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}: id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}: created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}: updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}: version must be a positive integer"
    )


def assert_program(data: dict):
    _assert_common(data, "Program")
    assert isinstance(data.get("name"), str) and data["name"]
    assert data.get("visibility") in ("PUBLIC", "PRIVATE")
    assert data.get("status") in ("DRAFT", "ACTIVE", "PAUSED", "CLOSED")
    for field in ("min_reputation", "response_sla_hours", "resolution_sla_days",
                  "disclosure_window_days", "bounty_pool_cents",
                  "bounty_reserved_cents", "bounty_paid_cents",
                  "total_withheld_cents", "available_pool_cents"):
        assert isinstance(data.get(field), int), f"Program.{field} must be int"
    assert isinstance(data.get("blackout_windows"), list)


def assert_scope_asset(data: dict):
    _assert_common(data, "ScopeAsset")
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("asset_identifier"), str) and data["asset_identifier"]
    assert data.get("criticality") in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
    assert data.get("status") in ("ACTIVE", "RETIRED")


def assert_scope_version(data: dict):
    _assert_common(data, "ScopeVersion")
    assert is_valid_uuid(data.get("program_id", ""))
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    assert isinstance(data.get("in_scope_asset_ids"), list)
    assert isinstance(data.get("version_seq"), int)


def assert_researcher(data: dict):
    _assert_common(data, "Researcher")
    assert isinstance(data.get("handle"), str) and data["handle"]
    assert isinstance(data.get("email"), str) and data["email"]
    assert isinstance(data.get("country_code"), str) and data["country_code"]
    assert data.get("status") in ("ACTIVE", "SUSPENDED", "BANNED")
    assert isinstance(data.get("strike_count"), int)
    assert isinstance(data.get("reputation_lifetime"), int)
    assert isinstance(data.get("reputation_rolling180"), int)
    assert data.get("tier") in ("NOVICE", "ESTABLISHED", "ELITE")
    assert data.get("tax_document_status") in ("MISSING", "SUBMITTED", "VERIFIED")


def assert_invitation(data: dict):
    _assert_common(data, "ProgramInvitation")
    assert is_valid_uuid(data.get("program_id", ""))
    assert is_valid_uuid(data.get("researcher_id", ""))
    assert data.get("status") in ("PENDING", "ACCEPTED", "DECLINED", "EXPIRED")
    assert is_iso8601_timestamp(data.get("issued_at", ""))
    assert is_iso8601_timestamp(data.get("expires_at", ""))
    assert isinstance(data.get("reputation_at_issue"), int)


def assert_report(data: dict):
    _assert_common(data, "Report")
    assert is_valid_uuid(data.get("program_id", ""))
    assert is_valid_uuid(data.get("asset_id", ""))
    assert is_valid_uuid(data.get("researcher_id", ""))
    assert isinstance(data.get("title"), str)
    assert data.get("vulnerability_class") in (
        "XSS", "SQLI", "CSRF", "SSRF", "AUTHZ", "RCE", "OTHER")
    assert data.get("status") in (
        "NEW", "TRIAGED", "NEEDS_INFO", "VALIDATED", "RESOLVED",
        "DUPLICATE", "NOT_APPLICABLE", "INFORMATIVE")
    assert is_iso8601_timestamp(data.get("submitted_at", ""))
    assert is_iso8601_timestamp(data.get("response_due_at", ""))


def assert_award(data: dict):
    _assert_common(data, "Award")
    assert is_valid_uuid(data.get("report_id", ""))
    assert is_valid_uuid(data.get("researcher_id", ""))
    assert data.get("award_type") in ("BOUNTY", "BONUS", "RETEST")
    assert data.get("status") in ("PROPOSED", "APPROVED", "BLOCKED", "PAID", "VOID")
    assert isinstance(data.get("amount_cents"), int)
    assert isinstance(data.get("capped_by_pool"), bool)
    assert isinstance(data.get("withheld_cents"), int)
    assert isinstance(data.get("net_paid_cents"), int)


def assert_disclosure_request(data: dict):
    _assert_common(data, "DisclosureRequest")
    assert is_valid_uuid(data.get("report_id", ""))
    assert is_valid_uuid(data.get("researcher_id", ""))
    assert data.get("status") in (
        "REQUESTED", "UNDER_NEGOTIATION", "AGREED", "PUBLISHED", "DENIED")
    assert isinstance(data.get("negotiation_round"), int)


def assert_remediation_ticket(data: dict):
    _assert_common(data, "RemediationTicket")
    assert is_valid_uuid(data.get("report_id", ""))
    assert isinstance(data.get("external_ref"), str)
    assert data.get("status") in ("OPEN", "IN_PROGRESS", "FIXED", "VERIFIED", "WONT_FIX")
    assert is_iso8601_timestamp(data.get("due_at", ""))


def assert_pool_ledger_conserved(program: dict):
    """Pool identity: reserved + paid + available == pool, and no counter is negative."""
    reserved = program["bounty_reserved_cents"]
    paid = program["bounty_paid_cents"]
    available = program["available_pool_cents"]
    pool = program["bounty_pool_cents"]
    assert reserved + paid + available == pool, (
        f"pool conservation violated: {reserved} + {paid} + {available} != {pool}")
    assert reserved >= 0 and paid >= 0 and available >= 0
