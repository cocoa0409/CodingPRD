"""Program configuration: tiers, device categories and the criteria catalogue
(PRD 3.1)."""

from flask import Blueprint

import calc
import lookups
import serialize
import store
import validation as v
from auth import ALL_ROLES, PROGRAM_ADMINISTRATOR, caller
from envelope import created, created_list, ok
from errors import bad_request
from store import base_row

bp = Blueprint("config", __name__)

TIER_CODE_PATTERN = r"^[A-Z0-9_]+$"
ROUTES = ("SELF_ATTESTATION", "THIRD_PARTY_TEST")
ELIGIBILITY_STATUSES = ("ELIGIBLE", "EXCLUDED")


@bp.post("/labeling/program-tiers")
def create_program_tier():
    caller(PROGRAM_ADMINISTRATOR)
    body = v.raw_body()

    tier_code = v.field_str(body, "tier_code", min_len=3, max_len=32, pattern=TIER_CODE_PATTERN)
    required_route = v.field_enum(body, "required_route", ROUTES)
    label_validity_days = v.field_int(body, "label_validity_days", minimum=1, maximum=3650)
    min_overall_score = v.field_number(
        body, "min_overall_score", minimum=0, maximum=100, max_dp=2
    )
    unverified_weight_factor = v.field_number(
        body, "unverified_weight_factor", minimum=0, maximum=1, max_dp=2
    )
    issuance_base_fee_cents = v.field_int(body, "issuance_base_fee_cents", minimum=0)
    max_deficiency_rounds = v.field_int(body, "max_deficiency_rounds", minimum=0, maximum=10)

    lookups.unique_or_reject(store.program_tiers, "tier_code", tier_code)

    row = base_row()
    row.update(
        {
            "tier_code": tier_code,
            "required_route": required_route,
            "label_validity_days": label_validity_days,
            "min_overall_score": calc.q2(min_overall_score),
            "unverified_weight_factor": calc.q2(unverified_weight_factor),
            "issuance_base_fee_cents": issuance_base_fee_cents,
            "max_deficiency_rounds": max_deficiency_rounds,
        }
    )
    store.program_tiers[row["id"]] = row
    return created(serialize.program_tier(row))


@bp.get("/labeling/program-tiers/<identifier>")
def read_program_tier(identifier):
    caller(*ALL_ROLES)
    return ok(serialize.program_tier(lookups.need_tier(identifier)))


@bp.post("/labeling/device-categories")
def create_device_category():
    caller(PROGRAM_ADMINISTRATOR)
    body = v.raw_body()

    lookups.resolve_fk(body, "program_tier_id", lookups.need_tier)

    category_code = v.field_str(body, "category_code", max_len=64)
    display_name = v.field_str(body, "display_name", max_len=200)
    eligibility_status = v.field_enum(body, "eligibility_status", ELIGIBILITY_STATUSES)
    program_tier_id = v.field_str(body, "program_tier_id")
    min_support_period_days = v.field_int(body, "min_support_period_days", minimum=0)
    exclusion_reason = v.field_str(body, "exclusion_reason", required=False, max_len=500)

    if eligibility_status == "EXCLUDED" and exclusion_reason is None:
        raise bad_request("Field 'exclusion_reason' is required when the category is EXCLUDED.")
    if eligibility_status == "ELIGIBLE" and exclusion_reason is not None:
        raise bad_request("Field 'exclusion_reason' must be omitted when the category is ELIGIBLE.")

    tier = lookups.need_tier(program_tier_id)
    lookups.unique_or_reject(store.device_categories, "category_code", category_code)

    row = base_row()
    row.update(
        {
            "category_code": category_code,
            "display_name": display_name,
            "eligibility_status": eligibility_status,
            "exclusion_reason": exclusion_reason,
            "program_tier_id": tier["id"],
            "min_support_period_days": min_support_period_days,
        }
    )
    store.device_categories[row["id"]] = row
    return created(serialize.device_category(row))


@bp.get("/labeling/device-categories/<identifier>")
def read_device_category(identifier):
    caller(*ALL_ROLES)
    return ok(serialize.device_category(lookups.need_category(identifier)))


@bp.get("/labeling/program-tiers/<identifier>/device-categories")
def list_tier_device_categories(identifier):
    caller(*ALL_ROLES)
    tier = lookups.need_tier(identifier)
    rows = [
        row
        for row in store.device_categories.values()
        if row["program_tier_id"] == tier["id"]
    ]
    rows.sort(key=lambda row: (row["category_code"], row["id"]))
    return lookups.listing(rows, serialize.device_category)


@bp.post("/labeling/security-criteria")
def create_security_criteria():
    caller(PROGRAM_ADMINISTRATOR)
    body = v.raw_body()

    criteria = v.field_array(body, "criteria")

    prepared = []
    seen_codes = set()
    for index, element in enumerate(criteria):
        if not isinstance(element, dict):
            raise bad_request("Element %d of 'criteria' must be an object." % index)
        criterion_code = v.field_str(element, "criterion_code", max_len=64)
        practice_area = v.field_enum(element, "practice_area", calc.PRACTICE_AREAS)
        weight = v.field_int(element, "weight", minimum=1, maximum=1000)
        requires_lab_verification = v.field_bool(element, "requires_lab_verification")
        criterion_text = v.field_str(element, "criterion_text", max_len=2000)

        if criterion_code in seen_codes:
            raise bad_request(
                "Field 'criterion_code' is repeated within the batch: %s." % criterion_code
            )
        seen_codes.add(criterion_code)
        lookups.unique_or_reject(store.security_criteria, "criterion_code", criterion_code)

        prepared.append(
            {
                "criterion_code": criterion_code,
                "practice_area": practice_area,
                "weight": weight,
                "requires_lab_verification": requires_lab_verification,
                "criterion_text": criterion_text,
            }
        )

    written = []
    for values in prepared:
        row = base_row(with_common=False)
        row.update(values)
        store.security_criteria[row["id"]] = row
        written.append(serialize.security_criterion(row))
    return created_list(written)


@bp.get("/labeling/security-criteria/<identifier>")
def read_security_criterion(identifier):
    caller(*ALL_ROLES)
    return ok(serialize.security_criterion(lookups.need_criterion(identifier)))


@bp.get("/labeling/security-criteria")
def list_security_criteria():
    caller(*ALL_ROLES)
    practice_area = v.query_enum("practice_area", calc.PRACTICE_AREAS)
    requires_lab_verification = v.query_bool("requires_lab_verification")

    rows = list(store.security_criteria.values())
    if practice_area is not None:
        rows = [row for row in rows if row["practice_area"] == practice_area]
    if requires_lab_verification is not None:
        rows = [
            row
            for row in rows
            if row["requires_lab_verification"] == requires_lab_verification
        ]
    rows.sort(key=lambda row: (row["practice_area"], row["criterion_code"]))
    return lookups.listing(rows, serialize.security_criterion)
