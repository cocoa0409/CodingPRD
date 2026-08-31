"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_SELECTION_STATUSES = ["PROPOSED", "SELECTED", "EXEMPTED", "RESCINDED", "SEPARATED"]
_EMPLOYMENT_STATUSES = ["ACTIVE", "PENDING_SEPARATION", "SEPARATED"]
_TRIGGER_STATUSES = ["NONE", "MASS_LAYOFF", "PLANT_CLOSING"]


def assert_common_fields(data: dict):
    """Every persisted resource carries a bare UUID id and an ISO 8601 UTC
    created_at with three fractional digits."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"


def assert_mutation_tracking(data: dict):
    """Resources other than WarnRule additionally carry updated_at + version."""
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_reduction_plan(data: dict):
    assert_common_fields(data)
    assert_mutation_tracking(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["decisional_unit_name"], str) and data["decisional_unit_name"]
    assert data["criteria_status"] in ["DRAFT", "LOCKED"]
    assert data["approval_status"] in [
        "DRAFT",
        "IN_LEGAL_REVIEW",
        "APPROVED",
        "EXECUTED",
    ]
    assert data["warn_status"] in [
        "NOT_ASSESSED",
        "THRESHOLD_PENDING",
        "NOTICES_ISSUED",
        "NOTICE_PERIOD_SATISFIED",
    ]
    for money in (
        "severance_budget_cents",
        "severance_reserve_cents",
        "benefit_liability_cents",
    ):
        assert isinstance(data[money], int), f"{money} must be a whole number of cents"
    for count in (
        "selected_count",
        "pool_count",
        "required_notice_days",
        "legal_return_count",
        "owbpa_consideration_days",
    ):
        assert isinstance(data[count], int), f"{count} must be an integer"
    assert isinstance(data["owbpa_required"], bool)


def assert_site(data: dict):
    assert_common_fields(data)
    assert_mutation_tracking(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["is_single_site"], bool)
    for count in (
        "roster_count",
        "active_headcount",
        "pending_separation_count",
        "separated_count",
        "federal_loss_count",
        "state_loss_count",
        "required_notice_days",
    ):
        assert isinstance(data[count], int), f"{count} must be an integer"
    assert data["warn_trigger_status"] in _TRIGGER_STATUSES
    assert_site_headcount_identity(data)


def assert_site_headcount_identity(site: dict):
    """roster_count == active_headcount + pending_separation_count + separated_count."""
    total = (
        site["active_headcount"]
        + site["pending_separation_count"]
        + site["separated_count"]
    )
    assert site["roster_count"] == total, (
        "headcount identity broken: roster_count "
        f"{site['roster_count']} != {site['active_headcount']} active + "
        f"{site['pending_separation_count']} pending + {site['separated_count']} separated"
    )


def assert_employee(data: dict):
    assert_common_fields(data)
    assert_mutation_tracking(data)
    assert is_valid_uuid(data["site_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["job_title"], str) and data["job_title"]
    assert isinstance(data["birth_date"], str) and len(data["birth_date"]) == 10
    assert isinstance(data["hire_date"], str) and len(data["hire_date"]) == 10
    assert isinstance(data["annual_base_cents"], int) and data["annual_base_cents"] > 0
    assert data["demographic_code"] in ["CLASS_A", "CLASS_B", "CLASS_C"]
    assert data["employment_status"] in _EMPLOYMENT_STATUSES
    assert isinstance(data["is_part_time"], bool)
    assert isinstance(data["release_signed"], bool)
    assert data["benefit_continuation_status"] in ["NONE", "ACTIVE", "TERMINATED"]
    assert data["outplacement_tier"] in ["NONE", "STANDARD", "PREMIUM"]
    assert isinstance(data["benefit_subsidy_months"], int)
    assert isinstance(data["benefit_subsidy_cents"], int)


def assert_selection(data: dict):
    assert_common_fields(data)
    assert_mutation_tracking(data)
    assert is_valid_uuid(data["plan_id"])
    assert is_valid_uuid(data["employee_id"])
    assert isinstance(data["proposed_separation_date"], str)
    assert data["status"] in _SELECTION_STATUSES
    assert data["notice_status"] in ["NOT_DELIVERED", "DELIVERED"]
    assert isinstance(data["short_notice_acknowledged"], bool)
    assert isinstance(data["composite_score"], (int, float))


def assert_warn_rule(data: dict):
    """A configured statute row is immutable: id and created_at only."""
    assert_common_fields(data)
    assert "version" not in data, "WarnRule carries no version field"
    assert "updated_at" not in data, "WarnRule carries no updated_at field"
    assert data["jurisdiction"] in ["FEDERAL", "STATE"]
    assert isinstance(data["rule_code"], str) and data["rule_code"]
    assert isinstance(data["counts_part_time"], bool)
    assert isinstance(data["required_content_codes"], list)


def assert_analysis(data: dict):
    assert_common_fields(data)
    assert_mutation_tracking(data)
    assert is_valid_uuid(data["plan_id"])
    assert data["method"] in ["IMPACT_RATIO", "STANDARD_DEVIATION"]
    assert data["status"] in ["COMPUTED", "FLAGGED", "CLEARED", "SUPERSEDED", "STALE"]
    assert isinstance(data["pool_count"], int)
    assert isinstance(data["selected_count"], int)
    assert isinstance(data["small_sample_suppressed"], bool)
    if data["method"] == "IMPACT_RATIO":
        assert data["standard_deviations"] is None, (
            "standard_deviations is null for method IMPACT_RATIO"
        )
    else:
        assert data["impact_ratio"] is None, (
            "impact_ratio is null for method STANDARD_DEVIATION"
        )


def assert_disclosure(data: dict):
    assert_common_fields(data)
    assert_mutation_tracking(data)
    assert is_valid_uuid(data["plan_id"])
    assert data["status"] in ["ATTACHED", "SUPERSEDED", "STALE"]
    assert isinstance(data["age_bands"], list)
    assert is_iso8601_timestamp(data["generated_utc"])
    assert (
        data["eligible_count"] >= 0
        and data["selected_count"] >= 0
        and data["non_selected_count"] >= 0
    )


def assert_age_bands_sorted(bands: list):
    """One entry per distinct decisional-unit age, sorted by age ascending."""
    ages = [b["age"] for b in bands]
    assert ages == sorted(ages), f"age_bands must be sorted ascending, got {ages}"
    assert len(set(ages)) == len(ages), f"age_bands must not repeat an age, got {ages}"


def assert_warn_notice(data: dict):
    assert_common_fields(data)
    assert_mutation_tracking(data)
    assert is_valid_uuid(data["plan_id"])
    assert is_valid_uuid(data["site_id"])
    assert data["jurisdiction"] in ["FEDERAL", "STATE"]
    assert data["status"] in ["DRAFT", "ISSUED", "VOID"]
    assert data["trigger_type"] in _TRIGGER_STATUSES
    assert isinstance(data["threshold_met"], bool)
    assert isinstance(data["employment_loss_count"], int)
    assert isinstance(data["workforce_count"], int)
    assert isinstance(data["content_codes"], list)


def assert_severance_offer(data: dict):
    assert_common_fields(data)
    assert_mutation_tracking(data)
    assert is_valid_uuid(data["selection_id"])
    assert is_valid_uuid(data["plan_id"])
    assert data["variant"] in ["STANDARD", "ENHANCED_RELEASE"]
    assert data["status"] in [
        "DRAFT",
        "ISSUED",
        "SIGNED",
        "REVOKED",
        "EFFECTIVE",
        "EXPIRED",
    ]
    for money in (
        "weekly_rate_cents",
        "base_severance_cents",
        "notice_pay_offset_cents",
        "benefit_subsidy_cents",
        "outplacement_fee_cents",
        "total_separation_cost_cents",
    ):
        assert isinstance(data[money], int), (
            f"{money} must be a whole number of cents, got {data[money]!r}"
        )
    assert isinstance(data["issue_count"], int)
    assert_offer_total_is_the_sum_of_its_parts(data)


def assert_offer_total_is_the_sum_of_its_parts(offer: dict):
    expected = (
        offer["base_severance_cents"]
        + offer["notice_pay_offset_cents"]
        + offer["benefit_subsidy_cents"]
        + offer["outplacement_fee_cents"]
    )
    assert offer["total_separation_cost_cents"] == expected, (
        "total_separation_cost_cents must be the sum of base severance, notice pay "
        f"offset, benefit subsidy and outplacement fee: expected {expected}, got "
        f"{offer['total_separation_cost_cents']}"
    )


def assert_position_restriction(data: dict):
    assert_common_fields(data)
    assert_mutation_tracking(data)
    assert is_valid_uuid(data["employee_id"])
    assert is_valid_uuid(data["site_id"])
    assert isinstance(data["job_title"], str) and data["job_title"]
    assert data["restriction_status"] in ["RESTRICTED", "WAIVED", "RELEASED"]
    assert is_iso8601_timestamp(data["restricted_until_utc"])


def assert_no_version_drift(before: dict, after: dict):
    """A rejected request must not advance the target resource's version."""
    assert before["version"] == after["version"], (
        f"version moved from {before['version']} to {after['version']} on a "
        "request that was rejected"
    )
