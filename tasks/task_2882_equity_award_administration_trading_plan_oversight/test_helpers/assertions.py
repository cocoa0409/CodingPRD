"""Entity assertions and domain invariant checkers for the equity award API."""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

# ---------------------------------------------------------------------------
# Instant helpers
# ---------------------------------------------------------------------------
def canonical_instant(value: str) -> str:
    """Normalise an ISO 8601 UTC instant to exactly three fractional digits so a
    comparison is about the moment in time rather than the serialiser's width."""
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1]
    elif "+" in text[10:]:
        text = text[: text.index("+", 10)]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = text, "000"
    return f"{head}.{frac}Z"


def assert_instant_equals(actual, expected, label="instant"):
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_three_fractional_digits(value, label="timestamp"):
    """The PRD renders every instant with exactly three fractional-second digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert value.endswith("Z"), f"{label} must be a UTC instant ending in Z: {value}"
    assert "." in value, f"{label} must carry fractional seconds: {value}"
    fraction = value.split(".")[1][:-1]
    assert len(fraction) == 3, (
        f"{label} must render exactly three fractional-second digits: {value}"
    )


def assert_iso_date(value, label="date"):
    assert isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"{label} must be a YYYY-MM-DD calendar date, got {value!r}"
    )


def assert_common_fields(data, label="row"):
    """Every stored row is addressed by a server-minted UUID and carries created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID: {data.get('id')!r}"
    assert "_" not in str(data.get("id", "")), f"{label}.id must carry no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 instant: {data.get('created_at')!r}"
    )


def assert_versioned_fields(data, label="row", expected_version=None):
    assert_common_fields(data, label)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 instant: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"{label}.version expected {expected_version}, got {data['version']}"
        )


def assert_immutable_row_fields(data, label="row"):
    """Immutable rows carry only id and created_at - no updated_at, no version."""
    assert_common_fields(data, label)
    assert "updated_at" not in data, f"{label} must not carry updated_at"
    assert "version" not in data, f"{label} must not carry version"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_equity_plan(data):
    assert_versioned_fields(data, "EquityPlan")
    assert data["status"] in ("ACTIVE", "FROZEN", "TERMINATED")
    assert data["reserve_posture"] in ("OPEN", "RESTRICTED")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    for field in (
        "total_authorized_shares", "common_shares_outstanding", "evergreen_pct_bps",
        "evergreen_cap_shares", "burn_rate_limit_bps", "fungible_ratio_full_value_bps",
        "low_reserve_threshold_bps", "shares_committed_cumulative",
        "shares_returned_cumulative", "fiscal_year_gross_granted_shares",
        "fiscal_year_returned_shares", "evergreen_topup_last_shares",
        "available_reserve_shares", "gross_burn_rate_bps", "net_burn_rate_bps",
    ):
        assert isinstance(data[field], int), f"EquityPlan.{field} must be an integer"
    assert_iso_date(data["fiscal_year_start_date"], "EquityPlan.fiscal_year_start_date")
    assert_reserve_conservation(data)


def assert_reserve_conservation(plan):
    """The available reserve, plus cumulative commitments, minus cumulative returns,
    always equals the authorised total."""
    lhs = (
        plan["available_reserve_shares"]
        + plan["shares_committed_cumulative"]
        - plan["shares_returned_cumulative"]
    )
    assert lhs == plan["total_authorized_shares"], (
        "reserve conservation broken: available "
        f"{plan['available_reserve_shares']} + committed "
        f"{plan['shares_committed_cumulative']} - returned "
        f"{plan['shares_returned_cumulative']} != authorized "
        f"{plan['total_authorized_shares']}"
    )


def assert_reserve_posture(plan):
    """OPEN when the available reserve multiplied by 10000 is greater than or equal
    to low_reserve_threshold_bps multiplied by total_authorized_shares."""
    expected = (
        "OPEN"
        if plan["available_reserve_shares"] * 10000
        >= plan["low_reserve_threshold_bps"] * plan["total_authorized_shares"]
        else "RESTRICTED"
    )
    assert plan["reserve_posture"] == expected, (
        f"reserve_posture expected {expected}, got {plan['reserve_posture']}"
    )


def assert_approval_authority(data):
    assert_versioned_fields(data, "ApprovalAuthority")
    assert data["status"] in ("ACTIVE", "EXHAUSTED", "REVOKED", "EXPIRED")
    assert data["authority_type"] in ("DELEGATED_OFFICER", "COMMITTEE")
    assert data["remaining_shares"] == data["aggregate_share_cap"] - data["consumed_shares"], (
        "remaining_shares must equal aggregate_share_cap minus consumed_shares"
    )
    assert_iso_date(data["effective_from"], "ApprovalAuthority.effective_from")
    assert_iso_date(data["effective_to"], "ApprovalAuthority.effective_to")


def assert_participant(data):
    assert_versioned_fields(data, "Participant")
    assert data["employment_status"] in ("ACTIVE", "TERMINATED")
    assert data["insider_status"] in (
        "NON_INSIDER", "DESIGNATED_INSIDER", "SECTION_16_OFFICER"
    )
    assert isinstance(data["age_years"], int)
    assert isinstance(data["service_years"], int)
    assert isinstance(data["retirement_eligible"], bool)
    assert_iso_date(data["hire_date"], "Participant.hire_date")
    assert_iso_date(data["birth_date"], "Participant.birth_date")


def assert_retirement_eligibility(data):
    """retirement_eligible is true when age_years is at least 55 and the sum of
    age_years and service_years is at least 65."""
    expected = data["age_years"] >= 55 and data["age_years"] + data["service_years"] >= 65
    assert data["retirement_eligible"] is expected, (
        f"retirement_eligible expected {expected} for age {data['age_years']} "
        f"and service {data['service_years']}, got {data['retirement_eligible']}"
    )


def assert_mobility_assignment(data):
    assert_immutable_row_fields(data, "MobilityAssignment")
    assert 2 <= len(data["jurisdiction_code"]) <= 8
    assert 0 <= data["tax_rate_bps"] <= 10000
    assert data["workdays"] >= 0
    assert_iso_date(data["start_date"], "MobilityAssignment.start_date")


def assert_grant(data):
    assert_versioned_fields(data, "Grant")
    assert data["status"] in (
        "DRAFT", "PENDING_APPROVAL", "CHANGES_REQUESTED", "APPROVED", "GRANTED",
        "PARTIALLY_FORFEITED", "FORFEITED", "CANCELLED",
    )
    assert data["award_type"] in ("RSU", "PSU", "ISO", "NSO")
    assert data["target_shares"] >= 1
    assert isinstance(data["exercise_price_cents"], int)
    assert isinstance(data["weighted_reserve_shares"], int)
    assert isinstance(data["outstanding_shares"], int)
    assert isinstance(data["changes_requested_count"], int)
    if data["award_type"] in ("RSU", "PSU"):
        assert data["exercise_price_cents"] == 0, (
            "a full-value award carries an exercise price of 0"
        )


def assert_vesting_tranche(data):
    assert_versioned_fields(data, "VestingTranche")
    assert data["status"] in ("UNVESTED", "VESTED", "SETTLED", "FORFEITED")
    assert data["vest_type"] in ("TIME", "PERFORMANCE")
    assert data["tranche_index"] >= 1
    assert data["target_shares"] >= 1
    assert isinstance(data["shares"], int)
    assert_iso_date(data["scheduled_vest_date"], "VestingTranche.scheduled_vest_date")


def assert_performance_cycle(data):
    assert_versioned_fields(data, "PerformanceCycle")
    assert data["status"] in ("OPEN", "CERTIFIED", "CANCELLED")
    assert data["target_value"] > 0
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]


def assert_vesting_event(data):
    assert_versioned_fields(data, "VestingEvent")
    assert data["tax_status"] in ("PENDING_ALLOCATION", "ALLOCATED")
    assert data["settlement_status"] in ("PENDING_TAX", "SETTLED", "REVERSED")
    assert data["withholding_method"] in (
        "SHARE_WITHHOLD", "SELL_TO_COVER", "CASH_REMITTANCE"
    )
    assert data["gross_shares"] >= 0
    assert data["fmv_per_share_cents"] >= 1
    assert data["taxable_income_cents"] == data["gross_shares"] * data["fmv_per_share_cents"], (
        "taxable_income_cents is gross_shares multiplied by fmv_per_share_cents"
    )
    assert_iso_date(data["vest_date"], "VestingEvent.vest_date")


def assert_share_split_identity(event):
    """gross_shares equals net_shares_delivered plus shares_withheld plus shares_sold."""
    total = (
        event["net_shares_delivered"] + event["shares_withheld"] + event["shares_sold"]
    )
    assert event["gross_shares"] == total, (
        f"share split identity broken: gross {event['gross_shares']} != net "
        f"{event['net_shares_delivered']} + withheld {event['shares_withheld']} + "
        f"sold {event['shares_sold']}"
    )


def assert_tax_allocation(data):
    assert_immutable_row_fields(data, "TaxAllocation")
    assert 0 <= data["allocation_bps"] <= 10000
    assert 0 <= data["tax_rate_bps"] <= 10000
    assert data["workdays_in_period"] >= 0
    assert data["tax_amount_cents"] >= 0


def assert_allocations_sum_to_full_bps(rows):
    """The allocations sum to exactly 10000, always."""
    total = sum(r["allocation_bps"] for r in rows)
    assert total == 10000, f"allocation_bps must sum to exactly 10000, got {total}"


def assert_round_then_sum_total(event, rows):
    """total_tax_cents is the sum of the already-rounded per-jurisdiction amounts."""
    total = sum(r["tax_amount_cents"] for r in rows)
    assert event["total_tax_cents"] == total, (
        f"total_tax_cents {event['total_tax_cents']} must be the round-then-sum total "
        f"of the per-jurisdiction amounts, {total}"
    )


def assert_trading_window(data):
    assert_versioned_fields(data, "TradingWindow")
    assert data["status"] in ("SCHEDULED", "OPEN", "SUSPENDED", "CLOSED")
    assert data["approved_shares_cumulative"] >= 0
    assert canonical_instant(data["open_at"]) < canonical_instant(data["close_at"]), (
        "close_at must be strictly after open_at"
    )


def assert_preclearance_request(data):
    assert_versioned_fields(data, "PreclearanceRequest")
    assert data["status"] in (
        "SUBMITTED", "INFO_REQUESTED", "APPROVED", "DENIED", "EXECUTED", "EXPIRED", "VOID"
    )
    assert data["transaction_type"] in ("SELL", "BUY", "GIFT")
    assert data["requested_shares"] >= 1
    assert isinstance(data["revision_count"], int)
    assert isinstance(data["requested_by_user_id"], str) and data["requested_by_user_id"]
    assert_iso_date(data["intended_trade_date"], "PreclearanceRequest.intended_trade_date")


def assert_trading_plan(data):
    assert_versioned_fields(data, "TradingPlan")
    assert data["status"] in (
        "PENDING_COOLING_OFF", "EFFECTIVE", "TERMINATED", "EXPIRED"
    )
    assert data["insider_status_at_adoption"] in (
        "NON_INSIDER", "DESIGNATED_INSIDER", "SECTION_16_OFFICER"
    )
    assert isinstance(data["cooling_off_days"], int) and data["cooling_off_days"] >= 0
    assert data["total_shares"] >= 1
    assert isinstance(data["modification_count"], int)


def assert_transaction_report(data):
    assert_versioned_fields(data, "TransactionReport")
    assert data["status"] in ("PENDING", "FILED", "LATE_FILED")
    assert data["form_type"] in ("FORM_4", "FORM_5")
    assert data["source_type"] in ("VESTING_SETTLEMENT", "PRECLEARANCE_EXECUTION")
    assert data["shares"] >= 0
    assert_three_fractional_digits(data["due_at"], "TransactionReport.due_at")


def assert_burn_rate_summary(data, plan=None):
    for field in (
        "plan_id", "gross_burn_rate_bps", "net_burn_rate_bps",
        "fiscal_year_gross_granted_shares", "fiscal_year_returned_shares",
        "burn_rate_limit_bps", "available_reserve_shares", "reserve_posture",
        "headroom_shares",
    ):
        assert field in data, f"burn-rate summary must expose {field}"
    assert data["headroom_shares"] >= 0, "headroom_shares is floored at 0"
    if plan is not None:
        for field in (
            "gross_burn_rate_bps", "net_burn_rate_bps",
            "fiscal_year_gross_granted_shares", "fiscal_year_returned_shares",
            "burn_rate_limit_bps", "available_reserve_shares", "reserve_posture",
        ):
            assert data[field] == plan[field], (
                f"burn-rate summary {field} must match the plan row: "
                f"{data[field]} vs {plan[field]}"
            )


def assert_envelope_meta(response):
    """The envelope's request id starts with req_ and its timestamp renders three
    fractional-second digits."""
    meta = response.json()["meta"]
    assert str(meta["api_request_id"]).startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']!r}"
    )
    assert_three_fractional_digits(
        meta["api_request_timestamp"], "meta.api_request_timestamp"
    )


def assert_pagination_meta(meta, limit=None, offset=None, total_count=None,
                          has_more=None):
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in meta, f"list meta must carry {field}"
    if limit is not None:
        assert meta["limit"] == limit
    if offset is not None:
        assert meta["offset"] == offset
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"total_count expected {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more


def assert_ascending(values, label="ordering"):
    assert values == sorted(values), f"{label} must be ascending, got {values}"
