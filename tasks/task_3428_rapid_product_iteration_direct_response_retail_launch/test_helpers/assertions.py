"""Entity assertions and domain invariant checkers.

validate_created / validate_ok wrap the framework validator with the expected
status fixed, so no call site can silently default to 200 and mask a create's
201 (PRD §4: creations return 201, actions and reads return 200).
"""
from typing import Iterable, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
)

from .types import (
    AgreementStatus,
    CaseStatus,
    Channel,
    ClaimClearance,
    CommitmentStatus,
    ConceptStatus,
    ExposureLevel,
    JudgmentOutcome,
    KilledReason,
    MediaDecision,
    MediaStatus,
    PartnerStatus,
    ReplenishmentStatus,
    RoundStatus,
    SeasonPosture,
    Severity,
    StudyStatus,
    VariantLifecycle,
)


# --- Explicit-status validators (PRD §4) -------------------------------------

def validate_created(response) -> dict:
    """Assert HTTP 201 and return the data payload (create endpoints)."""
    return validate_success(response, 201)


def validate_ok(response) -> dict:
    """Assert HTTP 200 and return the data payload (action/read endpoints)."""
    return validate_success(response, 200)


# --- Shared field helpers -----------------------------------------------------

def _assert_common_fields(data: dict, entity: str) -> None:
    """PRD §2.5 common system-managed fields present on every resource."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1"
    )


def _assert_optional_iso(data: dict, field: str, entity: str) -> None:
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), (
        f"{entity}.{field} must be null or an ISO 8601 timestamp"
    )


def _assert_optional_int(data: dict, field: str, entity: str,
                         minimum: Optional[int] = None,
                         maximum: Optional[int] = None) -> None:
    value = data.get(field)
    assert value is None or (isinstance(value, int) and not isinstance(value, bool)), (
        f"{entity}.{field} must be null or an integer"
    )
    if value is not None:
        if minimum is not None:
            assert value >= minimum, f"{entity}.{field} must be >= {minimum}"
        if maximum is not None:
            assert value <= maximum, f"{entity}.{field} must be <= {maximum}"


def _enum_values(enum_cls) -> list:
    return [member.value for member in enum_cls]


# --- Per-entity assertions ----------------------------------------------------

def assert_launch_season(data: dict) -> None:
    _assert_common_fields(data, "LaunchSeason")
    assert isinstance(data.get("season_code"), str) and data["season_code"], (
        "season_code must be a non-empty string"
    )
    assert data.get("posture") in _enum_values(SeasonPosture)
    assert isinstance(data.get("review_index"), int) and data["review_index"] >= 0
    fri = data.get("frozen_at_review_index")
    assert fri is None or isinstance(fri, int), (
        "frozen_at_review_index must be null or an integer"
    )
    gsi = data.get("guarded_since_review_index")
    assert gsi is None or isinstance(gsi, int), (
        "guarded_since_review_index must be null or an integer"
    )
    _assert_optional_iso(data, "last_review_at", "LaunchSeason")
    assert isinstance(data.get("penalty_accrual_cents"), int), (
        "penalty_accrual_cents must be an integer"
    )


def assert_category(data: dict) -> None:
    _assert_common_fields(data, "Category")
    assert is_valid_uuid(data.get("season_id", "")), "season_id must be a valid UUID"
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("crowding_base"), int) and 0 <= data["crowding_base"] <= 10, (
        "crowding_base must be an integer 0..10 (PRD §3.1)"
    )
    assert isinstance(data.get("exposure_index"), int) and data["exposure_index"] >= 0
    assert data.get("exposure_level") in _enum_values(ExposureLevel)
    assert isinstance(data.get("active_reserve_cents"), int) and data["active_reserve_cents"] >= 0


def assert_product_concept(data: dict) -> None:
    _assert_common_fields(data, "ProductConcept")
    assert is_valid_uuid(data.get("category_id", "")), "category_id must be a valid UUID"
    assert isinstance(data.get("title"), str) and data["title"]
    assert data.get("status") in _enum_values(ConceptStatus)
    insights = data.get("research_insights")
    assert isinstance(insights, list), "research_insights must be a list"
    for entry in insights:
        assert isinstance(entry.get("points"), int) and 1 <= entry["points"] <= 100, (
            "each insight's points must be an integer 1..100 (PRD §3.2)"
        )
        assert is_iso8601_timestamp(entry.get("observed_at", "")), (
            "each insight's observed_at must be an ISO 8601 timestamp"
        )
    momentum = data.get("research_momentum")
    assert isinstance(momentum, (int, float)) and not isinstance(momentum, bool), (
        "research_momentum must be numeric"
    )
    assert isinstance(data.get("rounds_used"), int) and data["rounds_used"] >= 0
    assert data.get("killed_reason") is None or data["killed_reason"] in _enum_values(KilledReason)


def assert_prototype_round(data: dict) -> None:
    _assert_common_fields(data, "PrototypeRound")
    assert is_valid_uuid(data.get("concept_id", "")), "concept_id must be a valid UUID"
    assert isinstance(data.get("round_number"), int) and data["round_number"] >= 1
    assert data.get("status") in _enum_values(RoundStatus)
    assert is_iso8601_timestamp(data.get("opened_at", "")), (
        "opened_at must be an ISO 8601 timestamp"
    )
    _assert_optional_int(data, "score", "PrototypeRound", minimum=0, maximum=100)
    feedback = data.get("feedback")
    assert feedback is None or isinstance(feedback, str)


def assert_factory_partner(data: dict) -> None:
    _assert_common_fields(data, "FactoryPartner")
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("capacity_units_total"), int) and data["capacity_units_total"] > 0
    assert isinstance(data.get("allocated_units"), int) and data["allocated_units"] >= 0
    assert data.get("status") in _enum_values(PartnerStatus)


def assert_model_variant(data: dict) -> None:
    _assert_common_fields(data, "ModelVariant")
    assert is_valid_uuid(data.get("concept_id", "")), "concept_id must be a valid UUID"
    partner_id = data.get("factory_partner_id")
    assert partner_id is None or is_valid_uuid(partner_id), (
        "factory_partner_id must be null or a valid UUID"
    )
    assert isinstance(data.get("model_number"), str) and data["model_number"]
    assert data.get("channel") in _enum_values(Channel)
    assert data.get("lifecycle") in _enum_values(VariantLifecycle)
    assert data.get("claim_clearance") in _enum_values(ClaimClearance)
    _assert_optional_iso(data, "tooled_at", "ModelVariant")
    _assert_optional_iso(data, "retail_live_at", "ModelVariant")
    _assert_optional_iso(data, "refresh_candidate_at", "ModelVariant")
    _assert_optional_iso(data, "retired_at", "ModelVariant")


def _assert_optional_number(data: dict, field: str, entity: str) -> None:
    value = data.get(field)
    assert value is None or (isinstance(value, (int, float)) and not isinstance(value, bool)), (
        f"{entity}.{field} must be null or numeric"
    )


def assert_claim_study(data: dict) -> None:
    _assert_common_fields(data, "ClaimStudy")
    assert is_valid_uuid(data.get("variant_id", "")), "variant_id must be a valid UUID"
    assert isinstance(data.get("claim_text"), str) and data["claim_text"]
    assert isinstance(data.get("conducted_by_user_id"), str) and data["conducted_by_user_id"], (
        "conducted_by_user_id records the creator's X-User-ID (PRD §3.4)"
    )
    assert data.get("status") in _enum_values(StudyStatus)
    _assert_optional_number(data, "our_metric", "ClaimStudy")
    _assert_optional_number(data, "baseline_metric", "ClaimStudy")
    _assert_optional_int(data, "sample_size", "ClaimStudy", minimum=1)
    _assert_optional_number(data, "margin", "ClaimStudy")
    sub_by = data.get("substantiated_by_user_id")
    assert sub_by is None or (isinstance(sub_by, str) and sub_by)
    reason = data.get("challenge_reason")
    assert reason is None or isinstance(reason, str)


def assert_media_test(data: dict) -> None:
    _assert_common_fields(data, "MediaTest")
    assert is_valid_uuid(data.get("variant_id", "")), "variant_id must be a valid UUID"
    assert isinstance(data.get("title"), str) and data["title"]
    assert isinstance(data.get("media_spend_cents"), int) and data["media_spend_cents"] > 0
    assert data.get("status") in _enum_values(MediaStatus)
    _assert_optional_int(data, "projected_gross_cents", "MediaTest", minimum=0)
    _assert_optional_number(data, "provisional_mer", "MediaTest")
    _assert_optional_number(data, "settled_mer", "MediaTest")
    lines = data.get("order_lines")
    assert lines is None or isinstance(lines, list), "order_lines must be null or a list"
    for line in lines or []:
        for key in ("revenue_cents", "cancels_cents", "returns_cents"):
            assert isinstance(line.get(key), int) and not isinstance(line[key], bool), (
                f"order line {key} must be an integer (PRD §3.5)"
            )
    _assert_optional_iso(data, "aired_at", "MediaTest")
    _assert_optional_iso(data, "decided_at", "MediaTest")


def assert_retail_agreement(data: dict) -> None:
    _assert_common_fields(data, "RetailAgreement")
    assert is_valid_uuid(data.get("category_id", "")), "category_id must be a valid UUID"
    assert isinstance(data.get("retailer_name"), str) and data["retailer_name"]
    assert isinstance(data.get("exclusive"), bool)
    assert is_iso8601_timestamp(data.get("window_start", "")), (
        "window_start must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("window_end", "")), (
        "window_end must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("min_launch_units"), int) and data["min_launch_units"] > 0
    assert data.get("status") in _enum_values(AgreementStatus)
    _assert_optional_iso(data, "signed_at", "RetailAgreement")


def assert_launch_commitment(data: dict) -> None:
    _assert_common_fields(data, "LaunchCommitment")
    assert is_valid_uuid(data.get("agreement_id", "")), "agreement_id must be a valid UUID"
    assert is_valid_uuid(data.get("variant_id", "")), "variant_id must be a valid UUID"
    assert isinstance(data.get("committed_units"), int) and data["committed_units"] > 0
    assert is_iso8601_timestamp(data.get("need_by_date", "")), (
        "need_by_date must be an ISO 8601 timestamp"
    )
    assert data.get("status") in _enum_values(CommitmentStatus)
    assert isinstance(data.get("penalty_cents"), int) and data["penalty_cents"] >= 0


def assert_replenishment_order(data: dict) -> None:
    _assert_common_fields(data, "ReplenishmentOrder")
    assert is_valid_uuid(data.get("variant_id", "")), "variant_id must be a valid UUID"
    assert isinstance(data.get("weekly_velocity"), int) and data["weekly_velocity"] >= 0
    assert isinstance(data.get("on_hand_units"), int) and data["on_hand_units"] >= 0
    assert isinstance(data.get("in_transit_units"), int) and data["in_transit_units"] >= 0
    assert isinstance(data.get("case_pack_units"), int) and data["case_pack_units"] > 0
    assert isinstance(data.get("quantity_units"), int) and data["quantity_units"] >= 0
    assert data.get("status") in _enum_values(ReplenishmentStatus)
    superseded_by = data.get("superseded_by_id")
    assert superseded_by is None or is_valid_uuid(superseded_by), (
        "superseded_by_id must be null or a valid UUID"
    )


def assert_patent_case(data: dict) -> None:
    _assert_common_fields(data, "PatentCase")
    assert is_valid_uuid(data.get("category_id", "")), "category_id must be a valid UUID"
    assert isinstance(data.get("case_number"), str) and data["case_number"]
    assert isinstance(data.get("claim_cents"), int) and data["claim_cents"] > 0
    assert data.get("severity") in _enum_values(Severity)
    assert isinstance(data.get("filed_by_user_id"), str) and data["filed_by_user_id"], (
        "filed_by_user_id records the filer's X-User-ID (PRD §3.8)"
    )
    assert data.get("status") in _enum_values(CaseStatus)
    assert isinstance(data.get("provisional_reserve_cents"), int), (
        "provisional_reserve_cents must be integer cents"
    )
    _assert_optional_int(data, "final_amount_cents", "PatentCase", minimum=0)


# --- Domain invariant checkers (PRD §2.9) -------------------------------------

def assert_capacity_conservation(partner: dict,
                                 open_commitments: Iterable[dict],
                                 open_replenishments: Iterable[dict]) -> None:
    """PRD §2.9: allocated_units == sum of committed_units over OPEN
    commitments plus sum of quantity_units over OPEN replenishment orders on
    variants tooled at this partner. Callers pass only the OPEN rows."""
    expected = sum(c["committed_units"] for c in open_commitments)
    expected += sum(r["quantity_units"] for r in open_replenishments)
    assert partner["allocated_units"] == expected, (
        f"partner_capacity_conservation violated: allocated_units "
        f"{partner['allocated_units']} != expected {expected}"
    )


def assert_reserve_reconciliation(category: dict, cases: Iterable[dict]) -> None:
    """PRD §2.9: active_reserve_cents == provisional reserves over FILED/ACTIVE
    cases plus final amounts over SETTLED/JUDGED_ADVERSE cases; favorable
    judgments contribute zero."""
    expected = 0
    for case in cases:
        if case["status"] in (CaseStatus.FILED.value, CaseStatus.ACTIVE.value):
            expected += case["provisional_reserve_cents"]
        elif case["status"] in (CaseStatus.SETTLED.value, CaseStatus.JUDGED_ADVERSE.value):
            expected += case.get("final_amount_cents") or 0
    assert category["active_reserve_cents"] == expected, (
        f"litigation_reserve_reconciliation violated: active_reserve_cents "
        f"{category['active_reserve_cents']} != expected {expected}"
    )


__all__ = [
    "validate_created",
    "validate_ok",
    "assert_launch_season",
    "assert_category",
    "assert_product_concept",
    "assert_prototype_round",
    "assert_factory_partner",
    "assert_model_variant",
    "assert_claim_study",
    "assert_media_test",
    "assert_retail_agreement",
    "assert_launch_commitment",
    "assert_replenishment_order",
    "assert_patent_case",
    "assert_capacity_conservation",
    "assert_reserve_reconciliation",
]
