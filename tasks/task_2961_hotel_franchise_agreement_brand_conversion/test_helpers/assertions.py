"""Shape and invariant assertions for the Hotel Franchise Conversion API.

Two families live here: per-entity shape checkers that assert the fields the
PRD says a resource carries, and domain invariant checkers for the properties
the PRD states must hold at every observable instant.
"""

from typing import Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .api_client import canonical_instant


# ─── Envelope helpers (PRD §2.2, §2.3) ───────────────────────────────

def assert_envelope_meta(response) -> dict:
    """Assert the success envelope's meta block and return the parsed body."""
    body = response.json()
    assert "meta" in body, f"Response carries no meta block: {body}"
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str), f"api_request_id missing: {meta}"
    assert meta["api_request_id"].startswith(
        "req_"
    ), f"api_request_id must start with 'req_': {meta['api_request_id']}"
    assert is_iso8601_timestamp(
        meta.get("api_request_timestamp", "")
    ), f"api_request_timestamp is not an ISO-8601 instant: {meta}"
    assert body.get("response_type") in (
        "object",
        "array",
    ), f"Unexpected response_type: {body.get('response_type')}"
    return body


def assert_object_envelope(response, expected_status: int = 200) -> dict:
    """A single-resource read or write: response_type 'object'."""
    data = validate_success(response, expected_status)
    body = assert_envelope_meta(response)
    assert body["response_type"] == "object", (
        f"A single resource must be returned with response_type 'object', "
        f"got {body['response_type']}"
    )
    return data


def validate_unpaginated_list(response, expected_status: int = 200) -> list:
    """A list body that is not windowed: response_type 'array' and no pagination meta.

    Kept alongside the framework's ``validate_paginated`` so a caller has to
    choose deliberately.  Every collection endpoint in this API is windowed,
    so this helper exists for array-valued reads that are not collections.
    """
    data = validate_success(response, expected_status)
    body = response.json()
    assert body.get("response_type") == "array", (
        f"An unpaginated list must carry response_type 'array', got {body.get('response_type')}"
    )
    assert isinstance(data, list), f"Expected a list payload, got {type(data)}"
    return data


def validate_paginated_list(response) -> tuple:
    """A windowed collection read: returns ``(rows, meta)``."""
    rows, meta = validate_paginated(response)
    assert isinstance(rows, list), f"Expected a list of rows, got {type(rows)}"
    return rows, meta


def assert_pagination_window(meta: dict, limit: int, offset: int, total_count: int) -> None:
    """The four pagination keys and the has_more rule of PRD §2.3."""
    assert meta["limit"] == limit, f"limit: expected {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"offset: expected {offset}, got {meta['offset']}"
    assert (
        meta["total_count"] == total_count
    ), f"total_count: expected {total_count}, got {meta['total_count']}"
    expected_has_more = offset + limit < total_count
    assert meta["has_more"] is expected_has_more, (
        f"has_more must be true exactly when rows remain beyond the window: "
        f"offset={offset} limit={limit} total_count={total_count} "
        f"expected {expected_has_more}, got {meta['has_more']}"
    )


def assert_error_envelope(response) -> dict:
    """An error body: response_type 'error', data holds error_id and message,
    and meta carries only the two request-identity keys (PRD §2.2)."""
    body = response.json()
    assert body.get("response_type") == "error", (
        f"An error must be returned with response_type 'error', got {body.get('response_type')}"
    )
    data = body.get("data", {})
    assert isinstance(data.get("error_id"), str), f"error_id missing from {body}"
    assert isinstance(data.get("message"), str), f"message missing from {body}"
    meta = body.get("meta", {})
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"An error envelope's meta carries only api_request_id and api_request_timestamp, "
        f"got {sorted(meta.keys())}"
    )
    return data


# ─── Scalar helpers (PRD §2.5, §2.6) ─────────────────────────────────

def assert_money(actual, expected: float, label: str = "amount") -> None:
    """A money, rate or score field: a JSON number carrying at most 2dp."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be a JSON number, got {type(actual).__name__} ({actual!r})"
    )
    assert round(float(actual), 2) == round(float(expected), 2), (
        f"{label}: expected {expected:.2f}, got {actual}"
    )


def assert_four_dp(actual, expected: float, label: str = "factor") -> None:
    """An intermediate carried at four decimal places (PRD §2.6)."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be a JSON number, got {type(actual).__name__}"
    )
    assert round(float(actual), 4) == round(float(expected), 4), (
        f"{label}: expected {expected:.4f}, got {actual}"
    )


def assert_integer(actual, expected: int, label: str = "count") -> None:
    """A count, span or score the PRD declares an integer."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be a JSON integer, got {type(actual).__name__} ({actual!r})"
    )
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


def assert_instant(actual: Optional[str], expected: Optional[str], label: str = "timestamp") -> None:
    """Compare two ISO-8601 UTC instants irrespective of fractional width."""
    if expected is None:
        assert actual is None, f"{label}: expected null, got {actual!r}"
        return
    assert actual is not None, f"{label}: expected {expected}, got null"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_common_fields(entity: dict, entity_name: str = "resource") -> None:
    """Every resource family carries id, created_at, updated_at, version (PRD §2.5)."""
    assert is_valid_uuid(entity.get("id", "")), (
        f"{entity_name}.id must be a UUID, got {entity.get('id')!r}"
    )
    for field in ("created_at", "updated_at"):
        assert is_iso8601_timestamp(entity.get(field, "")), (
            f"{entity_name}.{field} must be an ISO-8601 instant, got {entity.get(field)!r}"
        )
    assert isinstance(entity.get("version"), int) and not isinstance(entity["version"], bool), (
        f"{entity_name}.version must be an integer, got {entity.get('version')!r}"
    )
    assert entity["version"] >= 1, f"{entity_name}.version starts at 1, got {entity['version']}"


# ─── Per-entity shape checkers ───────────────────────────────────────

def assert_brand(brand: dict) -> None:
    assert_common_fields(brand, "Brand")
    for field in ("code", "name", "tier"):
        assert isinstance(brand.get(field), str), f"Brand.{field} must be a string"
    assert 3 <= len(brand["code"]) <= 12, f"Brand.code must be 3-12 characters: {brand['code']!r}"
    assert brand["code"].isupper() or brand["code"].isdigit() or all(
        c.isdigit() or (c.isalpha() and c.isupper()) for c in brand["code"]
    ), f"Brand.code is upper-case alphanumeric only: {brand['code']!r}"
    for field in ("base_royalty_rate_pct", "marketing_fund_rate_pct", "protected_radius_miles"):
        assert isinstance(brand.get(field), (int, float)), f"Brand.{field} must be a number"
    for field in ("min_room_count", "standard_term_years", "operating_unit_count",
                  "open_application_count"):
        assert isinstance(brand.get(field), int), f"Brand.{field} must be an integer"


def assert_owner(owner: dict) -> None:
    assert_common_fields(owner, "Owner")
    assert isinstance(owner.get("legal_name"), str), "Owner.legal_name must be a string"
    assert isinstance(owner.get("contact_email"), str), "Owner.contact_email must be a string"
    assert owner["contact_email"].count("@") == 1, (
        f"Owner.contact_email carries exactly one '@': {owner['contact_email']!r}"
    )
    for field in ("liquid_assets_amount", "net_worth_amount",
                  "capacity_score_standalone", "capacity_score_portfolio_adjusted"):
        assert isinstance(owner.get(field), (int, float)), f"Owner.{field} must be a number"
    for field in ("credit_score", "existing_units_count", "financial_profile_revision"):
        assert isinstance(owner.get(field), int), f"Owner.{field} must be an integer"
    assert owner.get("status") in ("PROSPECT", "ACTIVE"), f"Owner.status: {owner.get('status')}"
    for field in ("capacity_band_standalone", "capacity_band_portfolio_adjusted"):
        assert owner.get(field) in ("STRONG", "ADEQUATE", "INSUFFICIENT"), (
            f"Owner.{field}: {owner.get(field)}"
        )


def assert_existing_unit(unit: dict) -> None:
    assert_common_fields(unit, "ExistingUnit")
    assert is_valid_uuid(unit.get("brand_id", "")), "ExistingUnit.brand_id must be a UUID"
    assert isinstance(unit.get("unit_name"), str), "ExistingUnit.unit_name must be a string"
    assert 3 <= len(unit.get("market_code", "")) <= 8, (
        f"ExistingUnit.market_code must be 3-8 characters: {unit.get('market_code')!r}"
    )
    for field in ("x_miles", "y_miles", "adr_amount", "occupancy_pct"):
        assert isinstance(unit.get(field), (int, float)), f"ExistingUnit.{field} must be a number"
    assert isinstance(unit.get("room_count"), int), "ExistingUnit.room_count must be an integer"
    assert unit.get("status") in ("OPERATING", "SUSPENDED", "TERMINATED"), (
        f"ExistingUnit.status: {unit.get('status')}"
    )
    for field in ("territory_start_date", "territory_end_date"):
        assert len(unit.get(field, "")) == 10, (
            f"ExistingUnit.{field} is a YYYY-MM-DD date: {unit.get(field)!r}"
        )


def assert_application(application: dict) -> None:
    assert_common_fields(application, "Application")
    for field in ("owner_id", "brand_id"):
        assert is_valid_uuid(application.get(field, "")), f"Application.{field} must be a UUID"
    assert isinstance(application.get("property_name"), str), "Application.property_name"
    for field in ("property_x_miles", "property_y_miles"):
        assert isinstance(application.get(field), (int, float)), f"Application.{field}"
    for field in ("room_count", "building_age_years", "requested_term_years",
                  "revision_round", "sustained_claim_count"):
        assert isinstance(application.get(field), int), f"Application.{field} must be an integer"
    assert application.get("status") in (
        "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED", "APPROVED", "DECLINED"
    ), f"Application.status: {application.get('status')}"
    assert application.get("financial_review_status") in (
        "NOT_STARTED", "PASSED", "FAILED", "STALE"
    ), f"Application.financial_review_status: {application.get('financial_review_status')}"
    assert application.get("impact_study_status") in (
        "NOT_STARTED", "PRELIMINARY", "FINAL"
    ), f"Application.impact_study_status: {application.get('impact_study_status')}"
    assert isinstance(application.get("encroachment_waiver_granted"), bool), (
        "Application.encroachment_waiver_granted must be a boolean"
    )


def assert_encroachment_claim(claim: dict) -> None:
    assert_common_fields(claim, "EncroachmentClaim")
    for field in ("application_id", "existing_unit_id"):
        assert is_valid_uuid(claim.get(field, "")), f"EncroachmentClaim.{field} must be a UUID"
    assert claim.get("status") in ("FILED", "SUSTAINED", "OVERRULED"), (
        f"EncroachmentClaim.status: {claim.get('status')}"
    )
    for field in ("claimed_revenue_loss_pct", "distance_miles", "penalty_points_applied"):
        assert isinstance(claim.get(field), (int, float)), f"EncroachmentClaim.{field}"
    assert isinstance(claim.get("narrative"), str), "EncroachmentClaim.narrative"


def assert_agreement(agreement: dict) -> None:
    assert_common_fields(agreement, "LicenseAgreement")
    assert is_valid_uuid(agreement.get("application_id", "")), "LicenseAgreement.application_id"
    assert isinstance(agreement.get("brand_code"), str), "LicenseAgreement.brand_code"
    assert agreement.get("status") in (
        "DRAFT", "EXECUTED", "OPEN", "TERMINATION_PENDING", "TERMINATED", "VOIDED"
    ), f"LicenseAgreement.status: {agreement.get('status')}"
    assert agreement.get("compliance_status") in (
        "COMPLIANT", "CURE_PERIOD", "DEFAULT_NOTICE", "TERMINATION_ELIGIBLE"
    ), f"LicenseAgreement.compliance_status: {agreement.get('compliance_status')}"
    assert agreement.get("training_status") in ("NOT_STARTED", "COMPLETED")
    assert agreement.get("systems_status") in ("NOT_STARTED", "PROVISIONED", "VALIDATED")
    assert agreement.get("channel_status") in (
        "NOT_CONNECTED", "TESTING", "CONNECTED", "SUSPENDED"
    )
    assert agreement.get("de_identification_status") in (
        "NOT_REQUIRED", "PENDING", "SUBMITTED", "BREACHED", "VERIFIED"
    )
    assert agreement.get("post_termination_status") in ("NOT_APPLICABLE", "OPEN", "CLOSED")
    for field in ("royalty_rate_pct", "marketing_fund_rate_pct", "royalty_fee_to_date",
                  "marketing_fund_contributed_total", "reservation_fee_to_date",
                  "total_fees_assessed", "de_identification_breach_penalty",
                  "liquidated_damages_paid_amount"):
        assert isinstance(agreement.get(field), (int, float)), f"LicenseAgreement.{field}"
    for field in ("term_years", "liquidated_damages_cap_months", "reported_period_count",
                  "consecutive_qa_failure_count", "transfer_consent_count"):
        assert isinstance(agreement.get(field), int), f"LicenseAgreement.{field} must be an integer"
    assert isinstance(agreement.get("transfer_consent_blocked"), bool)
    assert isinstance(agreement.get("revenue_periods"), list)
    assert isinstance(agreement.get("de_identification_items_completed"), list)


def assert_pip(plan: dict) -> None:
    assert_common_fields(plan, "PropertyImprovementPlan")
    assert is_valid_uuid(plan.get("agreement_id", "")), "PropertyImprovementPlan.agreement_id"
    assert plan.get("status") in (
        "SCOPED", "ACCEPTED", "IN_PROGRESS", "DEFAULTED", "COMPLETED", "SUSPENDED"
    ), f"PropertyImprovementPlan.status: {plan.get('status')}"
    for field in ("total_estimated_cost", "cost_per_room", "franchisor_key_money",
                  "owner_net_cost", "owner_net_cost_per_room"):
        assert isinstance(plan.get(field), (int, float)), f"PropertyImprovementPlan.{field}"
    for field in ("items_total_count", "items_pending_count", "items_submitted_count",
                  "items_verified_count", "items_overdue_count", "key_money_pct",
                  "extension_granted_days_total"):
        assert isinstance(plan.get(field), int), f"PropertyImprovementPlan.{field}"
    assert isinstance(plan.get("escalation_required"), bool)


def assert_pip_item(item: dict) -> None:
    assert_common_fields(item, "PipItem")
    assert is_valid_uuid(item.get("pip_id", "")), "PipItem.pip_id must be a UUID"
    assert item.get("status") in ("PENDING", "SUBMITTED", "OVERDUE", "VERIFIED"), (
        f"PipItem.status: {item.get('status')}"
    )
    assert item.get("extension_status") in ("NONE", "PENDING", "GRANTED", "DENIED"), (
        f"PipItem.extension_status: {item.get('extension_status')}"
    )
    assert isinstance(item.get("estimated_cost"), (int, float)), "PipItem.estimated_cost"
    for field in ("extension_requested_days", "extension_granted_days_total",
                  "extension_request_count", "rejection_count"):
        assert isinstance(item.get(field), int), f"PipItem.{field} must be an integer"


def assert_qa_inspection(inspection: dict) -> None:
    assert_common_fields(inspection, "QaInspection")
    assert is_valid_uuid(inspection.get("agreement_id", "")), "QaInspection.agreement_id"
    for field in ("cleanliness_score", "condition_score", "brand_standard_score",
                  "guest_experience_score", "critical_defect_count"):
        assert isinstance(inspection.get(field), int), f"QaInspection.{field} must be an integer"
    for field in ("weighted_score", "total_score"):
        assert isinstance(inspection.get(field), (int, float)), f"QaInspection.{field}"
    assert isinstance(inspection.get("life_safety_defect"), bool)
    assert inspection.get("grade") in ("PASS", "CONDITIONAL", "FAIL"), (
        f"QaInspection.grade: {inspection.get('grade')}"
    )
    assert inspection.get("status") in (
        "CLOSED", "CURE_PENDING", "CURE_SUBMITTED", "CURE_PASSED", "CURE_FAILED"
    ), f"QaInspection.status: {inspection.get('status')}"
    assert is_iso8601_timestamp(inspection.get("inspection_at", "")), "QaInspection.inspection_at"


def assert_transfer_request(request: dict) -> None:
    assert_common_fields(request, "TransferRequest")
    assert is_valid_uuid(request.get("agreement_id", "")), "TransferRequest.agreement_id"
    assert request.get("request_type") in ("TRANSFER", "CHANGE_OF_CONTROL", "REFINANCE"), (
        f"TransferRequest.request_type: {request.get('request_type')}"
    )
    assert request.get("status") in ("SUBMITTED", "CONSENTED", "REFUSED"), (
        f"TransferRequest.status: {request.get('status')}"
    )
    for field in ("transfer_fee", "non_compliance_surcharge", "total_consent_fee"):
        assert isinstance(request.get(field), (int, float)), f"TransferRequest.{field}"


# ─── Domain invariants ───────────────────────────────────────────────

def assert_plan_counter_partition(plan: dict) -> None:
    """The four status buckets partition the plan's scope lines (PRD §3.7)."""
    buckets = (
        plan["items_pending_count"]
        + plan["items_submitted_count"]
        + plan["items_verified_count"]
        + plan["items_overdue_count"]
    )
    assert buckets == plan["items_total_count"], (
        f"pending+submitted+verified+overdue must equal items_total_count: "
        f"{plan['items_pending_count']}+{plan['items_submitted_count']}"
        f"+{plan['items_verified_count']}+{plan['items_overdue_count']} = {buckets} "
        f"but items_total_count = {plan['items_total_count']}"
    )


def assert_fee_ledger_consistent(agreement: dict) -> None:
    """Each running total is the exact sum over surviving periods, and
    total_fees_assessed is the sum of the three lines (PRD §3.8)."""
    surviving = [p for p in agreement["revenue_periods"] if not p.get("superseded")]
    assert agreement["reported_period_count"] == len(surviving), (
        f"reported_period_count must count surviving periods only: "
        f"{agreement['reported_period_count']} vs {len(surviving)} surviving"
    )
    for line, total_field in (
        ("royalty_fee", "royalty_fee_to_date"),
        ("marketing_fee", "marketing_fund_contributed_total"),
        ("reservation_fee", "reservation_fee_to_date"),
    ):
        expected = round(sum(p[line] for p in surviving), 2)
        assert_money(agreement[total_field], expected, total_field)
    expected_total = round(
        agreement["royalty_fee_to_date"]
        + agreement["marketing_fund_contributed_total"]
        + agreement["reservation_fee_to_date"],
        2,
    )
    assert_money(agreement["total_fees_assessed"], expected_total, "total_fees_assessed")
    period_sum = round(sum(p["period_total_fee"] for p in surviving), 2)
    assert_money(agreement["total_fees_assessed"], period_sum, "total_fees_assessed (period sum)")


def assert_capacity_bands(owner: dict) -> None:
    """Each capacity score sits in the band its own value selects (PRD §3.2)."""
    for score_field, band_field in (
        ("capacity_score_standalone", "capacity_band_standalone"),
        ("capacity_score_portfolio_adjusted", "capacity_band_portfolio_adjusted"),
    ):
        score = owner[score_field]
        expected = "STRONG" if score >= 75.00 else "ADEQUATE" if score >= 55.00 else "INSUFFICIENT"
        assert owner[band_field] == expected, (
            f"{band_field}: a score of {score} selects {expected}, got {owner[band_field]}"
        )


def assert_version_advanced_by(before: dict, after: dict, delta: int, label: str = "resource") -> None:
    """A mutation advances version by exactly ``delta`` (PRD §2.5)."""
    assert after["version"] == before["version"] + delta, (
        f"{label}.version: expected {before['version']} + {delta} = "
        f"{before['version'] + delta}, got {after['version']}"
    )
