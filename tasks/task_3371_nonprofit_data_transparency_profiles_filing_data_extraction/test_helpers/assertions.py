"""Entity assertions and domain invariant checkers (PRD §2.2, §2.5, §2.8)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import TIER_BASE_FEE_CENTS, TIER_OVERAGE_RATE_CENTS

COMMON_FIELDS = ("id", "created_at", "updated_at", "version")


def _parse_instant(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def prospect_organization_id(prospect: dict) -> str:
    """The candidate organization's identifier on a prospect row.

    PRD §3.9 names only `match_score` and `historical_giving_cents` on a prospect
    row; the field that identifies the candidate is never named, so a faithful
    row may carry the organization's own `id` (PRD §2.5) or an
    `organization_id` foreign key in the style of the API's other organization
    references. Either resolves to the same candidate.
    """
    for key in ("organization_id", "id"):
        value = prospect.get(key)
        if isinstance(value, str) and value:
            return value
    raise AssertionError(f"prospect row carries no organization identifier: {prospect}")


def assert_same_instant(actual, expected, *, field="timestamp") -> None:
    """`actual` denotes the same UTC instant as `expected` (PRD §2.4, §3.7).

    The PRD pins the arithmetic of clock-derived dates — `expires_on` is
    `awarded_on` plus 365 days and `renewal_window_opens_on` is 60 days earlier
    — but the only serialization it fixes is the three-fractional-digit rule for
    `created_at`/`updated_at` (PRD §2.5). For the other clock-derived fields it
    says only ISO 8601 UTC, so the assertion is on the instant, not on the
    fractional-digit rendering.
    """
    assert isinstance(actual, str) and actual, f"{field} must be a non-empty string"
    assert _parse_instant(actual) == _parse_instant(expected), (
        f"{field}: expected the instant {expected}, got {actual}"
    )


def assert_common_fields(data: dict, entity: str = "entity") -> None:
    """Every entity carries id + created_at + updated_at + version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer, got {data.get('version')!r}"
    )


def assert_success_envelope(response) -> dict:
    """Assert the §2.2 success envelope and return the body."""
    body = response.json()
    assert "meta" in body and "response_type" in body and "data" in body, (
        f"Malformed success envelope: {body}"
    )
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"], (
        "meta.api_request_id must be a non-empty string"
    )
    assert isinstance(meta.get("api_request_timestamp"), str), (
        "meta.api_request_timestamp must be present"
    )
    assert body["response_type"] in ("object", "array"), (
        f"response_type must be object|array, got {body['response_type']!r}"
    )
    return body


def assert_error_envelope(response) -> dict:
    """Assert the §2.2 error envelope and return data."""
    body = response.json()
    assert body.get("response_type") == "error", (
        f"Expected response_type 'error', got {body.get('response_type')!r}"
    )
    data = body.get("data", {})
    assert isinstance(data.get("error_id"), str) and data["error_id"], "error_id must be present"
    assert isinstance(data.get("message"), str) and data["message"].strip(), (
        "message must be a non-empty string"
    )
    return data


def assert_pagination_meta(meta: dict, *, limit=None, offset=None,
                           total_count=None, has_more=None) -> None:
    """Assert the four pagination fields carried by every list response (PRD §2.3)."""
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in meta, f"meta.{field} is required on list responses"
    assert isinstance(meta["has_more"], bool), "meta.has_more must be a boolean"
    if limit is not None:
        assert meta["limit"] == limit, f"Expected limit {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"Expected offset {offset}, got {meta['offset']}"
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"Expected total_count {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"Expected has_more {has_more}, got {meta['has_more']}"
        )


def assert_organization(data: dict) -> None:
    assert_common_fields(data, "Organization")
    assert isinstance(data.get("legal_name"), str) and data["legal_name"]
    assert isinstance(data.get("ein"), str) and len(data["ein"]) == 9
    assert data.get("org_type") in ["501C3", "501C4", "501C6", "501C7", "527", "OTHER"]
    assert isinstance(data.get("state_code"), str) and len(data["state_code"]) == 2
    assert data.get("profile_status") in ["DRAFT", "ACTIVE", "SUSPENDED", "MERGED", "DISSOLVED"]
    assert data.get("verification_level") in [
        "SELF_REPORTED", "DOCUMENT_VERIFIED", "INDEPENDENTLY_AUDITED"]
    assert isinstance(data.get("former_legal_names"), list)
    assert data.get("transparency_seal_level") in ["NONE", "BRONZE", "SILVER", "GOLD", "PLATINUM"]
    assert isinstance(data.get("disclosure_pct"), (int, float))
    for counter in ("total_revenue_cents", "distinct_funder_count",
                    "active_license_count", "open_correction_count",
                    "verification_evidence_count"):
        assert isinstance(data.get(counter), int), f"Organization.{counter} must be an integer"
        assert data[counter] >= 0, f"Organization.{counter} must not be negative"
    for score in ("provisional_completeness_score", "verified_completeness_score",
                  "profile_completeness_score"):
        assert isinstance(data.get(score), int), f"Organization.{score} must be an integer"
        assert 0 <= data[score] <= 100, f"Organization.{score} must be within 0..100"


def assert_program(data: dict) -> None:
    assert_common_fields(data, "Program")
    assert isinstance(data.get("program_name"), str) and data["program_name"]
    assert data.get("status") == "ACTIVE", "A program row is only ever ACTIVE"
    assert data.get("disclosure_level") in ["PUBLIC", "RESTRICTED", "WITHHELD"]
    assert isinstance(data.get("is_verified"), bool)
    assert isinstance(data.get("fiscal_year"), int)


def assert_filing(data: dict) -> None:
    assert_common_fields(data, "Filing")
    assert data.get("form_type") in ["FORM_990", "FORM_990_EZ", "FORM_990_PF"]
    assert data.get("form_version_year") in [2019, 2020, 2021, 2022, 2023, 2024]
    assert data.get("status") in ["RECEIVED", "EXTRACTED", "EXTRACTION_FAILED",
                                   "NORMALIZED", "DISPUTED", "SUPERSEDED", "VOIDED"]
    assert isinstance(data.get("revision_number"), int) and data["revision_number"] >= 1
    assert isinstance(data.get("extracted_field_count"), int)
    assert isinstance(data.get("total_revenue_cents"), int)
    assert isinstance(data.get("is_verified"), bool)


def assert_extracted_field(data: dict) -> None:
    assert_common_fields(data, "ExtractedField")
    assert isinstance(data.get("line_code"), str) and data["line_code"]
    assert data.get("raw_format") in ["USD_WHOLE", "USD_THOUSANDS", "USD_MILLIONS",
                                      "PLAIN_INTEGER"]
    assert data.get("normalization_status") in ["PENDING", "NORMALIZED", "CORRECTED",
                                                "CONFLICT"]
    assert isinstance(data.get("is_revenue_component"), bool)
    assert isinstance(data.get("correction_count"), int)
    if data.get("normalization_status") in ("NORMALIZED", "CORRECTED"):
        assert isinstance(data.get("normalized_value_cents"), int), (
            "A settled field must carry an integer normalized_value_cents"
        )


def assert_leadership_member(data: dict) -> None:
    assert_common_fields(data, "LeadershipMember")
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("office_title"), str) and data["office_title"]
    assert data.get("status") in ["ACTIVE", "ENDED"]
    assert isinstance(data.get("is_officer"), bool)
    assert isinstance(data.get("is_independent"), bool)
    assert data.get("disclosure_level") in ["PUBLIC", "RESTRICTED", "WITHHELD"]


def assert_demographic_record(data: dict) -> None:
    assert_common_fields(data, "DemographicRecord")
    assert data.get("category") in ["RACE_ETHNICITY", "GENDER_IDENTITY", "AGE_BAND",
                                    "LGBTQIA", "DISABILITY", "VETERAN"]
    assert isinstance(data.get("value_code"), str) and data["value_code"]
    assert data.get("disclosure_level") in ["PUBLIC", "RESTRICTED", "WITHHELD"]
    assert isinstance(data.get("fiscal_year"), int)


def assert_seal(data: dict) -> None:
    assert_common_fields(data, "TransparencySeal")
    assert data.get("level") in ["BRONZE", "SILVER", "GOLD", "PLATINUM"]
    assert data.get("status") in ["ACTIVE", "LAPSED", "REVOKED"]
    assert isinstance(data.get("disclosure_pct_at_award"), (int, float))
    assert isinstance(data.get("renewal_attempt_count"), int)
    for field in ("awarded_on", "expires_on", "renewal_window_opens_on"):
        assert is_iso8601_timestamp(data.get(field, "")), f"seal.{field} must be ISO 8601"


def assert_grant(data: dict) -> None:
    assert_common_fields(data, "Grant")
    assert data.get("status") in ["RECORDED", "VOIDED"]
    assert data.get("recipient_match_status") in ["UNMATCHED", "AMBIGUOUS", "MATCHED"]
    assert isinstance(data.get("match_score"), int) and 0 <= data["match_score"] <= 100
    assert isinstance(data.get("amount_cents"), int)
    assert data.get("taxonomy_source") in ["FUNDER_SUPPLIED", "AUTO_CODED", "UNCODED"]


def assert_license(data: dict) -> None:
    assert_common_fields(data, "DataLicense")
    assert data.get("tier") in ["RESEARCHER", "FUNDER", "PLATFORM"]
    assert data.get("status") in ["DRAFT", "ACTIVE", "EXPIRED"]
    assert isinstance(data.get("included_records"), int)
    assert isinstance(data.get("records_accessed"), int)
    assert isinstance(data.get("overage_records"), int)
    assert isinstance(data.get("overage_flag"), bool)
    assert isinstance(data.get("projected_annual_fee_cents"), int)
    assert isinstance(data.get("final_annual_fee_cents"), int)
    assert is_iso8601_timestamp(data.get("term_start", ""))
    assert is_iso8601_timestamp(data.get("term_end", ""))


def assert_usage_event(data: dict) -> None:
    assert_common_fields(data, "LicenseUsageEvent")
    assert data.get("status") in ["POSTED", "VOIDED"]
    assert data.get("dataset_scope") in ["ORGANIZATION_PROFILES", "FILING_FINANCIALS",
                                         "GRANT_HISTORY", "LEADERSHIP_COMPENSATION"]
    assert isinstance(data.get("record_count"), int) and data["record_count"] >= 1
    assert is_iso8601_timestamp(data.get("occurred_at", ""))


def assert_correction_request(data: dict) -> None:
    assert_common_fields(data, "CorrectionRequest")
    assert data.get("status") in ["SUBMITTED", "UNDER_REVIEW", "ACCEPTED",
                                  "PARTIALLY_ACCEPTED", "REJECTED", "WITHDRAWN"]
    assert isinstance(data.get("submitted_by_user_id"), str) and data["submitted_by_user_id"]
    assert isinstance(data.get("requested_value"), str)
    assert is_iso8601_timestamp(data.get("requested_at", ""))


def assert_identity_case(data: dict) -> None:
    assert_common_fields(data, "IdentityResolutionCase")
    assert data.get("case_type") in ["MERGE", "DISSOLUTION", "NAME_CHANGE"]
    assert data.get("status") in ["OPEN", "FINALIZED", "WITHDRAWN"]
    assert isinstance(data.get("reassigned_grant_count"), int)
    assert is_iso8601_timestamp(data.get("effective_date", ""))


def assert_license_invariants(data: dict) -> None:
    """Domain invariants that hold after any license mutation (PRD §3.9)."""
    assert data["records_accessed"] >= 0
    assert data["overage_records"] == max(0, data["records_accessed"] - data["included_records"]), (
        "overage_records must be max(0, records_accessed - included_records)"
    )
    assert data["overage_flag"] is (data["records_accessed"] > data["included_records"]), (
        "overage_flag must be true exactly when records_accessed exceeds included_records"
    )
    expected_final = (TIER_BASE_FEE_CENTS[data["tier"]]
                      + data["overage_records"] * TIER_OVERAGE_RATE_CENTS[data["tier"]])
    assert data["final_annual_fee_cents"] == expected_final, (
        f"final_annual_fee_cents should be {expected_final}, got {data['final_annual_fee_cents']}"
    )
