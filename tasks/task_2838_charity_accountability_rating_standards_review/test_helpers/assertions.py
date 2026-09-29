"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import ALL_STANDARD_CODES, DIMENSION_MAX_POINTS, STANDARD_COUNT


def assert_common_fields(data: dict) -> None:
    """Every stored resource carries a UUID id and an ISO 8601 created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"


def assert_versioned_fields(data: dict) -> None:
    """Twelve of the thirteen entities additionally carry updated_at and version."""
    assert_common_fields(data)
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


def assert_decimal_places(value, places: int, label: str) -> None:
    """A stored figure carries no more precision than the PRD declares for it."""
    assert value is not None, f"{label} must be present"
    assert round(float(value), places) == round(
        float(value), 10
    ), f"{label} must carry at most {places} decimal places, got {value}"


def assert_organization(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"].strip()
    assert isinstance(data["ein"], str)
    assert data["org_type"] in [
        "PUBLIC_CHARITY",
        "PRIVATE_FOUNDATION",
        "RELIGIOUS_CONGREGATION",
        "DONOR_ADVISED_SPONSOR",
        "MEMBERSHIP_ASSOCIATION",
    ]
    assert 1 <= data["fiscal_year_end_month"] <= 12
    assert "@" in data["contact_email"]
    assert data["trend_direction"] in [
        "NOT_APPLICABLE",
        "IMPROVED",
        "UNCHANGED",
        "DECLINED",
    ]
    assert isinstance(data["published_cycle_count"], int)
    assert isinstance(data["substantiated_complaint_count"], int)
    if data.get("latest_published_grade") is not None:
        assert data["latest_published_grade"] in [
            "ACCREDITED",
            "MEETS_STANDARDS",
            "NEEDS_IMPROVEMENT",
            "DOES_NOT_MEET",
            "UNRATED",
        ]


def assert_methodology_version(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["version_label"], str) and 1 <= len(data["version_label"]) <= 32
    assert data["status"] in [
        "DRAFT",
        "COMMENT_OPEN",
        "COMMENT_CLOSED",
        "ADOPTED",
        "RETIRED",
    ]
    weights = [
        data["weight_financial_health"],
        data["weight_accountability"],
        data["weight_transparency"],
        data["weight_impact"],
    ]
    for weight in weights:
        assert weight > 0.0, "each weight must be strictly greater than zero"
        assert_decimal_places(weight, 4, "methodology weight")
    assert round(sum(float(w) for w in weights), 4) == 1.0, (
        f"the four weights must sum to exactly 1.0000, got {weights}"
    )
    assert isinstance(data["comment_count"], int)
    assert isinstance(data["unresolved_comment_count"], int)


def assert_public_comment(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["status"] in ["SUBMITTED", "INCORPORATED", "DECLINED"]
    assert data["commenter_kind"] in ["DONOR", "RATED_ORGANIZATION", "PUBLIC"]
    assert isinstance(data["body"], str) and 1 <= len(data["body"]) <= 2000


def assert_transition_grant(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["status"] in ["ACTIVE", "CONSUMED", "EXPIRED"]
    assert data["trigger_reason"] in ["WEIGHT_CHANGE", "THRESHOLD_TIGHTENED"]
    assert is_iso8601_timestamp(data["grace_until"])
    assert_decimal_places(data["projected_score_delta"], 2, "projected_score_delta")


def assert_filing_record(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["status"] in ["RECEIVED", "VALIDATED", "REJECTED", "SUPERSEDED"]
    assert data["source_kind"] in [
        "AUDITED_STATEMENT",
        "PUBLIC_FILING",
        "ORG_SUBMISSION",
    ]
    assert data["origin"] in ["ORG_PORTAL", "ANALYST_ENTRY", "CORRECTION_APPLIED"]
    assert data["source_precedence"] in (1, 2, 3)
    assert 2000 <= data["fiscal_year"] <= 2100
    for field in (
        "total_expense_cents",
        "program_expense_cents",
        "fundraising_expense_cents",
        "admin_expense_cents",
        "contributions_cents",
        "total_revenue_cents",
        "net_assets_cents",
        "total_liabilities_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be whole cents"
        assert data[field] >= 0, f"{field} must be zero or greater"
    assert data["total_expense_cents"] == (
        data["program_expense_cents"]
        + data["fundraising_expense_cents"]
        + data["admin_expense_cents"]
    ), "total_expense_cents must equal the sum of its three components"


def assert_governance_profile(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["evaluation_status"] in ["PENDING", "EVALUATED"]
    assert 0 <= data["board_member_count"] <= 100
    assert 0 <= data["independent_board_member_count"] <= data["board_member_count"]
    assert 0 <= data["board_meetings_last_year"] <= 52
    assert 0 <= data["outcome_measures_count"] <= 50
    if data.get("independence_ratio") is not None:
        assert_decimal_places(data["independence_ratio"], 4, "independence_ratio")
    assert_standards_partition(data)


def assert_standards_partition(profile: dict) -> None:
    """The four standards counts always partition eight."""
    total = (
        profile["standards_met_count"]
        + profile["standards_not_met_count"]
        + profile["standards_waived_count"]
        + profile["standards_not_applicable_count"]
    )
    assert total in (
        0,
        STANDARD_COUNT,
    ), f"the four standards counts must partition {STANDARD_COUNT}, got {total}"


def assert_standard_evaluation(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["standard_code"] in ALL_STANDARD_CODES
    assert data["result"] in ["MET", "NOT_MET", "WAIVED", "NOT_APPLICABLE"]
    assert isinstance(data["observed_value"], str)
    assert isinstance(data["required_value"], str)
    assert is_iso8601_timestamp(data["evaluated_at"])


def assert_rating_cycle(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["status"] in [
        "DATA_COLLECTION",
        "SCORED",
        "ORG_REVIEW",
        "CORRECTION_REQUESTED",
        "APPEAL_OPEN",
        "APPEAL_RESOLVED",
        "PUBLISHED",
        "WITHDRAWN",
    ]
    assert 2000 <= data["fiscal_year"] <= 2100
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert data["period_end"] > data["period_start"]
    assert isinstance(data["correction_round"], int) and 0 <= data["correction_round"] <= 2
    assert isinstance(data["failed_standard_count"], int)
    assert isinstance(data["accountability_penalty_points"], int)
    if data.get("program_expense_ratio") is not None:
        assert_decimal_places(data["program_expense_ratio"], 4, "program_expense_ratio")
    if data.get("fundraising_efficiency") is not None:
        assert_decimal_places(data["fundraising_efficiency"], 4, "fundraising_efficiency")
    for field in (
        "months_of_reserve",
        "data_completeness_pct",
        "weighted_sum_provisional",
        "provisional_composite_score",
        "weighted_sum_final",
        "final_composite_score",
        "standards_penalty_points",
    ):
        if data.get(field) is not None:
            assert_decimal_places(data[field], 2, field)
    for field in ("provisional_grade", "grade"):
        if data.get(field) is not None:
            assert data[field] in [
                "ACCREDITED",
                "MEETS_STANDARDS",
                "NEEDS_IMPROVEMENT",
                "DOES_NOT_MEET",
                "UNRATED",
            ]


def assert_dimension_score(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["dimension"] in DIMENSION_MAX_POINTS
    assert data["status"] in ["PENDING", "COMPUTED", "OVERRIDDEN", "STALE"]
    assert isinstance(data["raw_points"], int)
    assert isinstance(data["max_points"], int)
    assert isinstance(data["penalty_points"], int)
    assert 0 <= data["raw_points"] <= data["max_points"] or data["max_points"] == 0
    assert_decimal_places(data["normalized_score"], 2, "normalized_score")
    assert_decimal_places(data["weight_applied"], 4, "weight_applied")
    assert_decimal_places(data["weighted_contribution"], 2, "weighted_contribution")
    assert_decimal_places(data["data_completeness_pct"], 2, "data_completeness_pct")


def assert_correction_request(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["status"] in [
        "SUBMITTED",
        "UNDER_ANALYST_REVIEW",
        "ACCEPTED",
        "REJECTED",
    ]
    assert data["target_kind"] in ["FILING_FINANCIAL", "GOVERNANCE_DISCLOSURE"]
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert isinstance(data["proposed_value"], str)
    assert isinstance(data["narrative"], str) and 1 <= len(data["narrative"]) <= 2000


def assert_appeal(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["status"] in [
        "FILED",
        "PANEL_ASSIGNED",
        "GRANTED",
        "DENIED",
        "DISMISSED",
    ]
    assert isinstance(data["panel_member_user_ids"], list)
    assert isinstance(data["grounds"], str) and 1 <= len(data["grounds"]) <= 2000
    assert is_iso8601_timestamp(data["filed_at"])


def assert_complaint(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["status"] in [
        "INTAKE",
        "INVESTIGATING",
        "SUBSTANTIATED",
        "UNSUBSTANTIATED",
        "CLOSED_NO_ACTION",
        "REFERRED_OUT",
    ]
    assert data["complainant_kind"] in ["DONOR", "BENEFICIARY", "EMPLOYEE", "ANONYMOUS"]
    assert data["category"] in [
        "MISUSE_OF_FUNDS",
        "GOVERNANCE",
        "SOLICITATION_PRACTICE",
        "TRANSPARENCY",
        "OTHER",
    ]
    assert 0 <= data["corroborating_document_count"] <= 50
    assert isinstance(data["penalty_points_applied"], int)
    if data.get("credibility_score") is not None:
        assert_decimal_places(data["credibility_score"], 2, "credibility_score")
        assert 0.00 <= float(data["credibility_score"]) <= 100.00
    if data.get("credibility_variant") is not None:
        assert data["credibility_variant"] in ["INTAKE", "INVESTIGATED"]
    if data.get("severity_tier") is not None:
        assert data["severity_tier"] in ["LOW", "MEDIUM", "HIGH"]


def assert_publication_record(data: dict) -> None:
    """The publication ledger is append-only: no updated_at, no version."""
    assert_common_fields(data)
    assert "updated_at" not in data, "a publication record has no updated_at field"
    assert "version" not in data, "a publication record has no version field"
    assert isinstance(data["sequence_number"], int) and data["sequence_number"] >= 1
    assert data["change_direction"] in [
        "FIRST_PUBLICATION",
        "IMPROVED",
        "UNCHANGED",
        "DECLINED",
    ]
    assert_decimal_places(data["published_score"], 2, "published_score")
    assert data["published_grade"] in [
        "ACCREDITED",
        "MEETS_STANDARDS",
        "NEEDS_IMPROVEMENT",
        "DOES_NOT_MEET",
        "UNRATED",
    ]
    assert isinstance(data["notified_recipient_kinds"], list)
    assert data["notified_recipient_kinds"][0] == "RATED_ORGANIZATION"
    assert is_iso8601_timestamp(data["published_at"])


def dimension_by_name(rows, dimension: str) -> dict:
    """Pick one dimension row out of a cycle's dimension-score list."""
    matches = [row for row in rows if row["dimension"] == dimension]
    assert matches, f"no {dimension} dimension row present"
    return matches[0]


def standard_by_code(rows, standard_code: str) -> dict:
    """Pick one standard evaluation out of a profile's eight rows."""
    matches = [row for row in rows if row["standard_code"] == standard_code]
    assert matches, f"no {standard_code} standard evaluation present"
    return matches[0]


def canonical_instant(value):
    """Reduce an ISO 8601 UTC instant to one canonical spelling.

    The envelope renders timestamps with three fractional-second digits, so a
    stored deadline of midnight may read back as `...T00:00:00.000Z`. Sub-second
    width is not what any of these tests are about, so both sides of every
    instant comparison are normalised through here first.
    """
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1]
    for sign in ("+", "-"):
        marker = text.find(sign, 10)
        if marker != -1:
            text = text[:marker]
            break
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000000")[:6].rstrip("0")
        text = head + ("." + frac if frac else "")
    return text + "Z"


def assert_instant(actual, expected, label="timestamp") -> None:
    """Two ISO 8601 UTC instants name the same moment."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def assert_number(actual, expected, places: int, label: str) -> None:
    """A stored figure equals its expected value at the scale the PRD declares."""
    assert actual is not None, f"{label} must be present, got null"
    assert round(float(actual), places) == round(float(expected), places), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_score(actual, expected, label="score") -> None:
    """Scores, deltas and penalties carry two decimal places."""
    assert_number(actual, expected, 2, label)


def assert_ratio(actual, expected, label="ratio") -> None:
    """Ratios and weights carry four decimal places."""
    assert_number(actual, expected, 4, label)
