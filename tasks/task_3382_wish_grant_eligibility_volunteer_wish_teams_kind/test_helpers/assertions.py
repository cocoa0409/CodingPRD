"""Entity assertions and domain invariant checkers.

Each assert_<entity>(data) checks the common bookkeeping spine (UUID id,
ISO 8601 created_at/updated_at, integer version >= 1) plus the presence,
type, and enum membership of the entity's own fields. Field names are
PRD-exact. Nullable system fields must be present and are type-checked
only when non-null.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import budget_freeze_threshold_cents
from .types import (
    ClearanceStatus,
    DetermineDecision,
    DonationCategory,
    DonationOfferStatus,
    FulfillmentPlanStatus,
    HoldReturnState,
    PlanLineItemStatus,
    QualifyingCondition,
    ReferralSourceType,
    ReferralStatus,
    ValuationMethod,
    VisitMethod,
    WishEventStatus,
    WishTeamStatus,
    WishType,
    WishUrgency,
    WishStatus,
    VolunteerStatus,
    ChapterPosture,
)


def _enum_values(enum_cls):
    return [member.value for member in enum_cls]


def _assert_spine(data: dict, entity: str):
    assert isinstance(data, dict), f"{entity} must be an object"
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity}.version must be an integer >= 1"


def _assert_nullable_timestamp(data: dict, field: str, entity: str):
    assert field in data, f"{entity}.{field} must be present (null until set)"
    value = data[field]
    if value is not None:
        assert is_iso8601_timestamp(value), \
            f"{entity}.{field} must be ISO 8601 when set"


def _assert_date_string(value, field: str, entity: str):
    assert isinstance(value, str) and len(value) == 10 and value[4] == "-" \
        and value[7] == "-", f"{entity}.{field} must be a YYYY-MM-DD date string"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_chapter(data: dict):
    _assert_spine(data, "Chapter")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["territory_zip_prefixes"], list) \
        and len(data["territory_zip_prefixes"]) >= 1, \
        "Chapter.territory_zip_prefixes must be a non-empty array"
    for prefix in data["territory_zip_prefixes"]:
        assert isinstance(prefix, str) and 1 <= len(prefix) <= 5
    assert isinstance(data["fiscal_year_budget_cents"], int) \
        and data["fiscal_year_budget_cents"] > 0
    assert isinstance(data["target_avg_cost_per_wish_cents"], int) \
        and data["target_avg_cost_per_wish_cents"] > 0
    for field in ("committed_cost_cents", "granted_wish_count",
                  "granted_cost_total_cents", "granted_cash_total_cents",
                  "avg_cost_blended_cents", "avg_cost_cash_cents"):
        assert isinstance(data[field], int) and data[field] >= 0, \
            f"Chapter.{field} must be a non-negative integer"
    assert data["posture"] in _enum_values(ChapterPosture)


def assert_volunteer(data: dict):
    _assert_spine(data, "Volunteer")
    assert is_valid_uuid(data.get("chapter_id", "")), \
        "Volunteer.chapter_id must be a UUID"
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["status"] in _enum_values(VolunteerStatus)


def assert_child(data: dict):
    _assert_spine(data, "Child")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["normalized_full_name"], str) \
        and data["normalized_full_name"]
    _assert_date_string(data["date_of_birth"], "date_of_birth", "Child")
    assert isinstance(data["zip_code"], str) and data["zip_code"]
    assert isinstance(data["parent_email"], str) and data["parent_email"]
    assert isinstance(data["diagnosis_summary"], str)
    assert is_valid_uuid(data.get("chapter_id", "")), \
        "Child.chapter_id must be a UUID"
    assert isinstance(data["treatment_windows"], list)
    for window in data["treatment_windows"]:
        _assert_date_string(window.get("start_date"), "start_date",
                            "treatment_windows entry")
        _assert_date_string(window.get("end_date"), "end_date",
                            "treatment_windows entry")


def assert_referral(data: dict):
    _assert_spine(data, "Referral")
    assert is_valid_uuid(data.get("child_id", "")), "Referral.child_id must be a UUID"
    assert data["source_type"] in _enum_values(ReferralSourceType)
    assert "prognosis_months" in data, "Referral.prognosis_months must be present"
    if data["prognosis_months"] is not None:
        assert isinstance(data["prognosis_months"], int) \
            and data["prognosis_months"] >= 0
    assert data["status"] in _enum_values(ReferralStatus)
    assert "qualifying_condition" in data
    if data["qualifying_condition"] is not None:
        assert data["qualifying_condition"] in _enum_values(QualifyingCondition)
    assert "certification_note" in data
    if data["certification_note"] is not None:
        assert isinstance(data["certification_note"], str)
    _assert_nullable_timestamp(data, "certified_at", "Referral")
    assert isinstance(data["age_months_at_intake"], int)
    assert "denial_reason" in data
    if data["denial_reason"] is not None:
        assert isinstance(data["denial_reason"], str)
    _assert_nullable_timestamp(data, "determined_at", "Referral")
    assert "wish_id" in data
    if data["wish_id"] is not None:
        assert is_valid_uuid(data["wish_id"]), "Referral.wish_id must be a UUID"


def assert_wish(data: dict):
    _assert_spine(data, "Wish")
    for field in ("child_id", "chapter_id", "referral_id"):
        assert is_valid_uuid(data.get(field, "")), f"Wish.{field} must be a UUID"
    assert "wish_type" in data
    if data["wish_type"] is not None:
        assert data["wish_type"] in _enum_values(WishType)
    assert data["urgency"] in _enum_values(WishUrgency)
    assert data["status"] in _enum_values(WishStatus)
    assert "true_wish_description" in data
    if data["true_wish_description"] is not None:
        assert isinstance(data["true_wish_description"], str)
    _assert_nullable_timestamp(data, "determined_at", "Wish")
    assert "hold_return_state" in data
    if data["hold_return_state"] is not None:
        assert data["hold_return_state"] in _enum_values(HoldReturnState)
    _assert_nullable_timestamp(data, "granted_at", "Wish")


def assert_wish_team(data: dict):
    _assert_spine(data, "WishTeam")
    assert is_valid_uuid(data.get("wish_id", "")), "WishTeam.wish_id must be a UUID"
    assert is_valid_uuid(data.get("lead_volunteer_id", "")), \
        "WishTeam.lead_volunteer_id must be a UUID"
    assert is_valid_uuid(data.get("second_volunteer_id", "")), \
        "WishTeam.second_volunteer_id must be a UUID"
    assert data["lead_volunteer_id"] != data["second_volunteer_id"], \
        "WishTeam lead and second must differ"
    assert data["status"] in _enum_values(WishTeamStatus)


def assert_wish_visit(data: dict):
    _assert_spine(data, "WishVisit")
    assert is_valid_uuid(data.get("wish_team_id", "")), \
        "WishVisit.wish_team_id must be a UUID"
    assert is_iso8601_timestamp(data.get("scheduled_start", "")), \
        "WishVisit.scheduled_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("scheduled_end", "")), \
        "WishVisit.scheduled_end must be ISO 8601"
    assert data["scheduled_start"] < data["scheduled_end"], \
        "WishVisit.scheduled_end must be strictly after scheduled_start"
    assert data["visit_method"] in _enum_values(VisitMethod)
    assert data["status"] in _enum_values(WishVisitStatus)
    assert "captured_true_wish" in data
    if data["captured_true_wish"] is not None:
        assert isinstance(data["captured_true_wish"], str)
    assert "captured_wish_type" in data
    if data["captured_wish_type"] is not None:
        assert data["captured_wish_type"] in _enum_values(WishType)


def assert_donation_offer(data: dict):
    _assert_spine(data, "DonationOffer")
    assert isinstance(data["partner_name"], str) and data["partner_name"]
    assert data["category"] in _enum_values(DonationCategory)
    assert data["valuation_method"] in _enum_values(ValuationMethod)
    assert isinstance(data["description"], str)
    for field in ("quantity_total", "quantity_reserved", "quantity_available"):
        assert isinstance(data[field], int) and data[field] >= 0, \
            f"DonationOffer.{field} must be a non-negative integer"
    assert isinstance(data["unit_retail_cents"], int) \
        and data["unit_retail_cents"] >= 1
    assert "partner_declared_unit_cents" in data
    if data["partner_declared_unit_cents"] is not None:
        assert isinstance(data["partner_declared_unit_cents"], int) \
            and data["partner_declared_unit_cents"] >= 1
    assert isinstance(data["fmv_unit_cents"], int) and data["fmv_unit_cents"] >= 1
    _assert_date_string(data["valid_from"], "valid_from", "DonationOffer")
    _assert_date_string(data["valid_until"], "valid_until", "DonationOffer")
    assert data["valid_from"] <= data["valid_until"]
    assert data["status"] in _enum_values(DonationOfferStatus)


def assert_fulfillment_plan(data: dict):
    _assert_spine(data, "FulfillmentPlan")
    assert is_valid_uuid(data.get("wish_id", "")), \
        "FulfillmentPlan.wish_id must be a UUID"
    assert isinstance(data["cash_cost_cents"], int) and data["cash_cost_cents"] >= 0
    assert "notes" in data
    if data["notes"] is not None:
        assert isinstance(data["notes"], str)
    assert isinstance(data["in_kind_value_cents"], int) \
        and data["in_kind_value_cents"] >= 0
    assert isinstance(data["total_cost_cents"], int) and data["total_cost_cents"] >= 0
    assert data["status"] in _enum_values(FulfillmentPlanStatus)
    assert isinstance(data["created_by_user_id"], str) \
        and data["created_by_user_id"]
    assert "approved_by_user_id" in data
    if data["approved_by_user_id"] is not None:
        assert isinstance(data["approved_by_user_id"], str) \
            and data["approved_by_user_id"]
    assert isinstance(data["escalation_required"], bool)


def assert_plan_line_item(data: dict):
    _assert_spine(data, "PlanLineItem")
    assert is_valid_uuid(data.get("plan_id", "")), "PlanLineItem.plan_id must be a UUID"
    assert is_valid_uuid(data.get("donation_offer_id", "")), \
        "PlanLineItem.donation_offer_id must be a UUID"
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["line_fmv_cents"], int) and data["line_fmv_cents"] >= 0
    assert data["status"] in _enum_values(PlanLineItemStatus)


def assert_medical_clearance(data: dict):
    _assert_spine(data, "MedicalClearance")
    assert is_valid_uuid(data.get("wish_id", "")), \
        "MedicalClearance.wish_id must be a UUID"
    assert data["status"] in _enum_values(ClearanceStatus)
    assert isinstance(data["accommodations"], list)
    for item in data["accommodations"]:
        assert isinstance(item, str) and item
    assert "valid_until" in data
    if data["valid_until"] is not None:
        _assert_date_string(data["valid_until"], "valid_until", "MedicalClearance")
    assert "decision_note" in data
    if data["decision_note"] is not None:
        assert isinstance(data["decision_note"], str)
    _assert_nullable_timestamp(data, "decided_at", "MedicalClearance")


def assert_wish_event(data: dict):
    _assert_spine(data, "WishEvent")
    assert is_valid_uuid(data.get("wish_id", "")), "WishEvent.wish_id must be a UUID"
    _assert_date_string(data["event_start_date"], "event_start_date", "WishEvent")
    _assert_date_string(data["event_end_date"], "event_end_date", "WishEvent")
    assert data["event_start_date"] <= data["event_end_date"], \
        "WishEvent.event_end_date must not precede event_start_date"
    assert data["status"] in _enum_values(WishEventStatus)
    _assert_nullable_timestamp(data, "completed_at", "WishEvent")


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------

def assert_offer_quantity_conservation(offer: dict):
    """quantity_reserved + quantity_available == quantity_total at every observation."""
    assert offer["quantity_reserved"] + offer["quantity_available"] \
        == offer["quantity_total"], (
            "quantity conservation violated: "
            f"{offer['quantity_reserved']} + {offer['quantity_available']} "
            f"!= {offer['quantity_total']}"
        )


def assert_offer_quantities(offer: dict, *, quantity_total=None,
                            quantity_reserved=None, quantity_available=None):
    """Pin an offer's quantity triple to exact expected values."""
    if quantity_total is not None:
        assert offer["quantity_total"] == quantity_total, (
            f"expected quantity_total {quantity_total}, "
            f"got {offer['quantity_total']}"
        )
    if quantity_reserved is not None:
        assert offer["quantity_reserved"] == quantity_reserved, (
            f"expected quantity_reserved {quantity_reserved}, "
            f"got {offer['quantity_reserved']}"
        )
    if quantity_available is not None:
        assert offer["quantity_available"] == quantity_available, (
            f"expected quantity_available {quantity_available}, "
            f"got {offer['quantity_available']}"
        )


def assert_plan_totals(plan: dict, *, cash_cost_cents=None,
                       in_kind_value_cents=None, total_cost_cents=None):
    """Plan money: total == cash + in-kind, with optional exact pins."""
    assert plan["total_cost_cents"] == \
        plan["cash_cost_cents"] + plan["in_kind_value_cents"], (
            "plan total must equal cash + in-kind: "
            f"{plan['total_cost_cents']} != {plan['cash_cost_cents']} "
            f"+ {plan['in_kind_value_cents']}"
        )
    if cash_cost_cents is not None:
        assert plan["cash_cost_cents"] == cash_cost_cents
    if in_kind_value_cents is not None:
        assert plan["in_kind_value_cents"] == in_kind_value_cents
    if total_cost_cents is not None:
        assert plan["total_cost_cents"] == total_cost_cents


def assert_chapter_posture(chapter: dict, expected_posture: str):
    """Posture derived from committed vs the 95%-of-budget floor threshold."""
    assert chapter["posture"] == expected_posture, (
        f"expected posture {expected_posture}, got {chapter['posture']} "
        f"(committed {chapter['committed_cost_cents']}, budget "
        f"{chapter['fiscal_year_budget_cents']})"
    )


def assert_chapter_posture_consistency(chapter: dict):
    """The reported posture must agree with the threshold formula."""
    threshold = budget_freeze_threshold_cents(chapter["fiscal_year_budget_cents"])
    expected = "FROZEN" if chapter["committed_cost_cents"] >= threshold else "OPEN"
    assert chapter["posture"] == expected, (
        f"posture {chapter['posture']} inconsistent with committed "
        f"{chapter['committed_cost_cents']} vs threshold {threshold}"
    )


def assert_chapter_fiscal(chapter: dict, *, committed_cost_cents=None,
                          granted_wish_count=None, granted_cost_total_cents=None,
                          granted_cash_total_cents=None,
                          avg_cost_blended_cents=None, avg_cost_cash_cents=None,
                          posture=None):
    """Pin any subset of a chapter's computed fiscal aggregates."""
    pins = {
        "committed_cost_cents": committed_cost_cents,
        "granted_wish_count": granted_wish_count,
        "granted_cost_total_cents": granted_cost_total_cents,
        "granted_cash_total_cents": granted_cash_total_cents,
        "avg_cost_blended_cents": avg_cost_blended_cents,
        "avg_cost_cash_cents": avg_cost_cash_cents,
        "posture": posture,
    }
    for field, expected in pins.items():
        if expected is not None:
            assert chapter[field] == expected, (
                f"Chapter.{field}: expected {expected}, got {chapter[field]}"
            )


def assert_pagination_meta(meta: dict, *, total_count=None, limit=None,
                           offset=None, has_more=None):
    """Pin the pagination fields carried in a list response's meta object."""
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in meta, f"meta.{field} missing from paginated response"
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"expected total_count {total_count}, got {meta['total_count']}"
        )
    if limit is not None:
        assert meta["limit"] == limit, (
            f"expected limit {limit}, got {meta['limit']}"
        )
    if offset is not None:
        assert meta["offset"] == offset, (
            f"expected offset {offset}, got {meta['offset']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"expected has_more {has_more}, got {meta['has_more']}"
        )
