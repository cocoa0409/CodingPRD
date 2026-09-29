"""Request payload builders carrying PRD-valid defaults.

Two conventions hold throughout:

* Numeric fields are emitted as JSON numbers. `grams`, `calories_per_100g`,
  `sodium_mg_per_100g`, `added_sugar_g_per_100g`, `sodium_warning_threshold_mg`
  and every count or cent amount are declared numeric by the PRD, so they are
  never quoted.
* Instant fields (`effective_from`, `effective_to`, `to_iso8601`) carry a full
  ISO 8601 UTC instant, while the date-only fields the PRD lists
  (`first_offered_on`, `start_date`, `end_date`, `requested_start_date`,
  `requested_end_date`, `effective_start_date`, `effective_end_date`) carry a
  bare `YYYY-MM-DD` calendar date.

Optional fields are omitted from the body unless a value is supplied, so a
caller can distinguish "not sent" from "sent as null" by passing `None`
explicitly where the PRD allows a null.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    ALLERGEN_EGG,
    ALLERGEN_MILK,
    ALLERGEN_NONE,
    ALLERGEN_WHEAT,
    BASIS_OPERATING_ONLY,
    BOARD_PRIMARY_MENU_BOARD,
    CHANNEL_IN_STORE_BINDER,
    CHANNEL_WEBSITE,
    CITATION_CALORIES_NOT_DECLARED,
    CLOCK_EPOCH_COMPACT,
    CROSS_CONTACT_NONE,
    DECISION_CERTIFY,
    EXTRA_REQUIREMENT_NONE,
    ITEM_CLASS_STANDARD,
    METHOD_DATABASE,
    PREEMPTION_VARIANCE_ALLOWED,
    REQUIREMENT_SUCCINCT_STATEMENT,
    ROLE_BASE,
    STATEMENT_FEDERAL_DEFAULT,
    TIER_FEDERAL_ALIGNED,
    UNIT_OPERATING,
    VARIABLE_NONE,
)


class _Omit:
    """Sentinel meaning "leave this key out of the request body entirely"."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<OMIT>"


OMIT = _Omit()


def _put(body: Dict[str, Any], key: str, value: Any) -> None:
    if not isinstance(value, _Omit):
        body[key] = value


# ---------------------------------------------------------------------------
# Registry (PRD 3.1)
# ---------------------------------------------------------------------------
def brand_payload(
    legal_name: str = "Golden Grill Holdings LLC",
    doing_business_as: Any = "Golden Grill",
    **extra: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"legal_name": legal_name}
    _put(body, "doing_business_as", doing_business_as)
    body.update(extra)
    return body


def jurisdiction_payload(
    code: str = "CA-VAR",
    name: str = "California",
    preemption_mode: Any = PREEMPTION_VARIANCE_ALLOWED,
    extra_requirement: Any = EXTRA_REQUIREMENT_NONE,
    enforcement_tier: Any = TIER_FEDERAL_ALIGNED,
    sodium_warning_threshold_mg: Any = OMIT,
    required_succinct_statement_variant: Any = OMIT,
    **extra: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"code": code, "name": name}
    _put(body, "preemption_mode", preemption_mode)
    _put(body, "extra_requirement", extra_requirement)
    _put(body, "enforcement_tier", enforcement_tier)
    _put(body, "sodium_warning_threshold_mg", sodium_warning_threshold_mg)
    _put(
        body,
        "required_succinct_statement_variant",
        required_succinct_statement_variant,
    )
    body.update(extra)
    return body


def establishment_payload(
    brand_id: str,
    jurisdiction_id: str,
    unit_label: str = "CA-0001",
    unit_status: Any = UNIT_OPERATING,
    operates_under_brand_name: Any = True,
    **extra: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "brand_id": brand_id,
        "jurisdiction_id": jurisdiction_id,
        "unit_label": unit_label,
    }
    _put(body, "unit_status", unit_status)
    _put(body, "operates_under_brand_name", operates_under_brand_name)
    body.update(extra)
    return body


def establishment_batch_payload(
    jurisdiction_id: str,
    unit_count: int = 19,
    unit_status: Any = UNIT_OPERATING,
    operates_under_brand_name: Any = True,
    unit_label_prefix: Any = "CA-B",
    **extra: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "jurisdiction_id": jurisdiction_id,
        "unit_count": unit_count,
    }
    _put(body, "unit_status", unit_status)
    _put(body, "operates_under_brand_name", operates_under_brand_name)
    _put(body, "unit_label_prefix", unit_label_prefix)
    body.update(extra)
    return body


def status_change_payload(
    new_unit_status: str,
    effective_note: Any = "Status change recorded by the register",
    **extra: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"new_unit_status": new_unit_status}
    _put(body, "effective_note", effective_note)
    body.update(extra)
    return body


def coverage_determination_payload(
    basis: str = BASIS_OPERATING_ONLY, **extra: Any
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"basis": basis}
    body.update(extra)
    return body


# ---------------------------------------------------------------------------
# Menu (PRD 3.2)
# ---------------------------------------------------------------------------
def menu_item_payload(
    brand_id: str,
    name: str = "Grill Sandwich",
    item_class: str = ITEM_CLASS_STANDARD,
    variable_type: Any = VARIABLE_NONE,
    first_offered_on: Any = "2026-01-05",
    **extra: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"brand_id": brand_id, "name": name,
                            "item_class": item_class}
    _put(body, "variable_type", variable_type)
    _put(body, "first_offered_on", first_offered_on)
    body.update(extra)
    return body


def offer_window_payload(
    start_date: str, end_date: str, **extra: Any
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"start_date": start_date, "end_date": end_date}
    body.update(extra)
    return body


def exemption_review_payload(review_year: int = 2026, **extra: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"review_year": review_year}
    body.update(extra)
    return body


# ---------------------------------------------------------------------------
# Recipes and analyses (PRD 3.3, 3.4)
# ---------------------------------------------------------------------------
def recipe_payload(
    expected_menu_item_version: Any,
    change_note: str = "Initial specification",
    **extra: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {}
    _put(body, "expected_menu_item_version", expected_menu_item_version)
    _put(body, "change_note", change_note)
    body.update(extra)
    return body


def component_payload(
    component_name: str,
    role: str = ROLE_BASE,
    grams: Any = 100,
    calories_per_100g: Any = 200,
    sodium_mg_per_100g: Any = 300,
    added_sugar_g_per_100g: Any = OMIT,
    allergen_group: Any = OMIT,
    cross_contact_risk: Any = OMIT,
    choice_group: Any = OMIT,
    selection_mode: Any = OMIT,
    selection_limit: Any = OMIT,
    **extra: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"component_name": component_name, "role": role}
    _put(body, "grams", grams)
    _put(body, "calories_per_100g", calories_per_100g)
    _put(body, "sodium_mg_per_100g", sodium_mg_per_100g)
    _put(body, "added_sugar_g_per_100g", added_sugar_g_per_100g)
    _put(body, "allergen_group", allergen_group)
    _put(body, "cross_contact_risk", cross_contact_risk)
    _put(body, "choice_group", choice_group)
    _put(body, "selection_mode", selection_mode)
    _put(body, "selection_limit", selection_limit)
    body.update(extra)
    return body


def submit_for_analysis_payload(
    method: str = METHOD_DATABASE, **extra: Any
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"method": method}
    body.update(extra)
    return body


def analysis_decision_payload(
    decision: str = DECISION_CERTIFY,
    decision_note: Any = "Database values verified",
    **extra: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"decision": decision}
    _put(body, "decision_note", decision_note)
    body.update(extra)
    return body


def withdraw_certification_payload(
    reason: str = "Supplier delisted; revert to the certified sandwich", **extra: Any
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"reason": reason}
    body.update(extra)
    return body


# --- The sandwich the PRD's worked examples describe -----------------------
# 140 g at 140 cal/100 g + 60 g at 330 cal/100 g + 20 g at 680 cal/100 g sums
# to 530.00 raw calories and 548.90 raw sodium, declaring 530 Cal / 550 mg.
def chicken_breast_component(**overrides: Any) -> Dict[str, Any]:
    return component_payload(
        component_name="Grilled chicken breast",
        role=ROLE_BASE,
        grams=140,
        calories_per_100g=140,
        sodium_mg_per_100g=240,
        added_sugar_g_per_100g=0,
        allergen_group=ALLERGEN_NONE,
        cross_contact_risk=CROSS_CONTACT_NONE,
        **overrides,
    )


def brioche_bun_component(**overrides: Any) -> Dict[str, Any]:
    return component_payload(
        component_name="Brioche bun",
        role=ROLE_BASE,
        grams=60,
        calories_per_100g=330,
        sodium_mg_per_100g=148,
        added_sugar_g_per_100g=4,
        allergen_group=ALLERGEN_WHEAT,
        cross_contact_risk=CROSS_CONTACT_NONE,
        **overrides,
    )


def herb_mayonnaise_component(grams: Any = 20, **overrides: Any) -> Dict[str, Any]:
    return component_payload(
        component_name="Herb mayonnaise",
        role=ROLE_BASE,
        grams=grams,
        calories_per_100g=680,
        sodium_mg_per_100g=620,
        added_sugar_g_per_100g=1,
        allergen_group=ALLERGEN_EGG,
        cross_contact_risk=CROSS_CONTACT_NONE,
        **overrides,
    )


def cheddar_slice_component(**overrides: Any) -> Dict[str, Any]:
    return component_payload(
        component_name="Cheddar slice",
        role=ROLE_BASE,
        grams=34,
        calories_per_100g=400,
        sodium_mg_per_100g=365,
        added_sugar_g_per_100g=0,
        allergen_group=ALLERGEN_MILK,
        cross_contact_risk=CROSS_CONTACT_NONE,
        **overrides,
    )


def garlic_butter_component(**overrides: Any) -> Dict[str, Any]:
    return component_payload(
        component_name="Garlic butter spread",
        role=ROLE_BASE,
        grams=45,
        calories_per_100g=680,
        sodium_mg_per_100g=590,
        added_sugar_g_per_100g=0,
        allergen_group=ALLERGEN_MILK,
        cross_contact_risk=CROSS_CONTACT_NONE,
        **overrides,
    )


def dressed_greens_component(grams: Any = 50, **overrides: Any) -> Dict[str, Any]:
    return component_payload(
        component_name="Dressed greens",
        role=ROLE_BASE,
        grams=grams,
        calories_per_100g=200,
        sodium_mg_per_100g=300,
        added_sugar_g_per_100g=2,
        allergen_group=ALLERGEN_NONE,
        cross_contact_risk=CROSS_CONTACT_NONE,
        **overrides,
    )


# ---------------------------------------------------------------------------
# Disclosure packets (PRD 3.5)
# ---------------------------------------------------------------------------
def disclosure_packet_payload(
    expected_brand_version: Any,
    cross_contact_statement: Any = "",
    written_info_channels: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {}
    _put(body, "expected_brand_version", expected_brand_version)
    _put(body, "cross_contact_statement", cross_contact_statement)
    body["written_info_channels"] = (
        list(written_info_channels)
        if written_info_channels is not None
        else [CHANNEL_IN_STORE_BINDER, CHANNEL_WEBSITE]
    )
    body.update(extra)
    return body


# ---------------------------------------------------------------------------
# Menu boards (PRD 3.6, 3.7)
# ---------------------------------------------------------------------------
def menu_board_payload(
    establishment_id: str,
    board_type: str = BOARD_PRIMARY_MENU_BOARD,
    succinct_statement_variant: Any = STATEMENT_FEDERAL_DEFAULT,
    **extra: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "establishment_id": establishment_id,
        "board_type": board_type,
    }
    _put(body, "succinct_statement_variant", succinct_statement_variant)
    body.update(extra)
    return body


def listing_payload(
    menu_item_id: str, sodium_warning_icon: Any = False, **extra: Any
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"menu_item_id": menu_item_id}
    _put(body, "sodium_warning_icon", sodium_warning_icon)
    body.update(extra)
    return body


def board_publish_payload(
    effective_from: str = CLOCK_EPOCH_COMPACT,
    effective_to: Any = OMIT,
    **extra: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"effective_from": effective_from}
    _put(body, "effective_to", effective_to)
    body.update(extra)
    return body


def reprint_payload(
    reprint_note: Any = "Board reprinted with the current declarations", **extra: Any
) -> Dict[str, Any]:
    body: Dict[str, Any] = {}
    _put(body, "reprint_note", reprint_note)
    body.update(extra)
    return body


# ---------------------------------------------------------------------------
# Variances (PRD 3.8)
# ---------------------------------------------------------------------------
def variance_request_payload(
    brand_id: str,
    jurisdiction_id: str,
    requirement_code: str = REQUIREMENT_SUCCINCT_STATEMENT,
    justification: str = "Statewide wording change lands later; interim relief asked",
    requested_start_date: str = "2026-09-01",
    requested_end_date: str = "2026-09-30",
    **extra: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "brand_id": brand_id,
        "jurisdiction_id": jurisdiction_id,
        "requirement_code": requirement_code,
        "justification": justification,
        "requested_start_date": requested_start_date,
        "requested_end_date": requested_end_date,
    }
    body.update(extra)
    return body


def variance_decision_payload(
    decision: str,
    decision_note: Any = "Docketed for review",
    effective_start_date: Any = OMIT,
    effective_end_date: Any = OMIT,
    **extra: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"decision": decision}
    _put(body, "decision_note", decision_note)
    _put(body, "effective_start_date", effective_start_date)
    _put(body, "effective_end_date", effective_end_date)
    body.update(extra)
    return body


# ---------------------------------------------------------------------------
# Enforcement (PRD 3.9)
# ---------------------------------------------------------------------------
def enforcement_action_payload(
    establishment_id: str,
    citation_code: str = CITATION_CALORIES_NOT_DECLARED,
    inspection_note: Any = "Board shows no calorie declarations",
    **extra: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "establishment_id": establishment_id,
        "citation_code": citation_code,
    }
    _put(body, "inspection_note", inspection_note)
    body.update(extra)
    return body


def enforcement_response_payload(
    response_type: str, response_note: Any = "Response filed by the brand", **extra: Any
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"response_type": response_type}
    _put(body, "response_note", response_note)
    body.update(extra)
    return body


def regulator_action_payload(
    action_type: str,
    penalty_basis: Any = OMIT,
    action_note: Any = "Regulator action recorded",
    **extra: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"action_type": action_type}
    _put(body, "penalty_basis", penalty_basis)
    _put(body, "action_note", action_note)
    body.update(extra)
    return body


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4)
# ---------------------------------------------------------------------------
def clock_payload(to_iso8601: str = CLOCK_EPOCH_COMPACT, **extra: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"to_iso8601": to_iso8601}
    body.update(extra)
    return body
