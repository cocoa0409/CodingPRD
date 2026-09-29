"""Programme configuration: participants, policy rows, physical estate, channels
and the logical clock (PRD 3.1)."""

from flask import Blueprint

import access
import constants as C
import serialize
import store
import validators as V
from envelope import list_response, object_response, paginate

bp = Blueprint("config", __name__)


# --------------------------------------------------------------------------
# customers
# --------------------------------------------------------------------------
@bp.post("/customers")
def create_customer():
    V.guard("ProgramAdmin")
    payload = V.body()
    email = V.str_field(payload, "email")
    full_name = V.str_field(payload, "full_name")
    loyalty_tier = V.enum_field(
        payload, "loyalty_tier", C.LOYALTY_TIERS, required=False, default="STANDARD"
    )
    V.unique_or_reject("customers", "email", email)
    row = store.create(
        "customers",
        {
            "email": email,
            "full_name": full_name,
            "loyalty_tier": loyalty_tier,
            "status": "ACTIVE",
            "credit_balance_minor": 0,
            "diverted_grams_total": 0,
        },
    )
    return object_response(serialize.out(row), 201)


@bp.patch("/customers/<customer_id>")
def patch_customer(customer_id):
    V.guard("ProgramAdmin")
    payload = V.body()
    status = V.enum_field(payload, "status", C.CUSTOMER_STATUSES, required=False)
    loyalty_tier = V.enum_field(payload, "loyalty_tier", C.LOYALTY_TIERS, required=False)
    customer = store.require("customers", customer_id)
    if status is not None:
        customer["status"] = status
    if loyalty_tier is not None:
        customer["loyalty_tier"] = loyalty_tier
    store.touch(customer)
    return object_response(serialize.out(customer))


@bp.get("/customers/<customer_id>")
def get_customer(customer_id):
    user_id, role = V.guard("ProgramAdmin", "IntakeAgent", "MerchandisingManager", "Customer")
    customer = store.require("customers", customer_id)
    access.require_owner(role, user_id, customer["id"])
    return object_response(serialize.out(customer))


# --------------------------------------------------------------------------
# condition-tier policies
# --------------------------------------------------------------------------
@bp.post("/grade-policies")
def create_grade_policy():
    V.guard("ProgramAdmin")
    payload = V.body()
    product_category = V.enum_field(payload, "product_category", C.PRODUCT_CATEGORIES)
    condition_grade = V.enum_field(payload, "condition_grade", C.CONDITION_GRADES)
    base_credit_pct_bp = V.int_field(payload, "base_credit_pct_bp", maximum=10000)
    resale_price_pct_bp = V.int_field(payload, "resale_price_pct_bp", maximum=10000)
    refurb_budget_cap_pct_bp = V.int_field(payload, "refurb_budget_cap_pct_bp", maximum=10000)
    restock_fee_pct_bp = V.int_field(payload, "restock_fee_pct_bp", maximum=10000)
    warranty_days = V.int_field(payload, "warranty_days")
    previous = store.active_grade_policy(product_category, condition_grade)
    row = store.create(
        "grade_policies",
        {
            "product_category": product_category,
            "condition_grade": condition_grade,
            "base_credit_pct_bp": base_credit_pct_bp,
            "resale_price_pct_bp": resale_price_pct_bp,
            "refurb_budget_cap_pct_bp": refurb_budget_cap_pct_bp,
            "restock_fee_pct_bp": restock_fee_pct_bp,
            "warranty_days": warranty_days,
            "status": "ACTIVE",
        },
    )
    if previous is not None:
        previous["status"] = "RETIRED"
        store.touch(previous)
    return object_response(serialize.out(row), 201)


@bp.get("/grade-policies/<policy_id>")
def get_grade_policy(policy_id):
    V.guard("ProgramAdmin", "MerchandisingManager", "Authenticator")
    return object_response(serialize.out(store.require("grade_policies", policy_id)))


# --------------------------------------------------------------------------
# brand-currency policies
# --------------------------------------------------------------------------
@bp.post("/credit-policies")
def create_credit_policy():
    V.guard("ProgramAdmin")
    payload = V.body()
    code = V.str_field(payload, "code")
    expiry_days = V.int_field(payload, "expiry_days", minimum=1)
    mail_in_bonus_pct_bp = V.int_field(payload, "mail_in_bonus_pct_bp", maximum=10000)
    max_redemption_pct_bp = V.int_field(
        payload, "max_redemption_pct_bp", minimum=1, maximum=10000
    )
    min_cash_remainder_minor = V.int_field(payload, "min_cash_remainder_minor")
    eligible_assortment = V.enum_field(payload, "eligible_assortment", C.ASSORTMENTS)
    previous = store.active_credit_policy()
    row = store.create(
        "credit_policies",
        {
            "code": code,
            "expiry_days": expiry_days,
            "mail_in_bonus_pct_bp": mail_in_bonus_pct_bp,
            "max_redemption_pct_bp": max_redemption_pct_bp,
            "min_cash_remainder_minor": min_cash_remainder_minor,
            "eligible_assortment": eligible_assortment,
            "status": "ACTIVE",
        },
    )
    if previous is not None:
        previous["status"] = "RETIRED"
        store.touch(previous)
    return object_response(serialize.out(row), 201)


@bp.get("/credit-policies/<policy_id>")
def get_credit_policy(policy_id):
    V.guard("ProgramAdmin", "MerchandisingManager")
    return object_response(serialize.out(store.require("credit_policies", policy_id)))


# --------------------------------------------------------------------------
# store locations and refurbishment bays
# --------------------------------------------------------------------------
@bp.post("/store-locations")
def create_store_location():
    V.guard("ProgramAdmin")
    payload = V.body()
    code = V.str_field(payload, "code")
    region_code = V.str_field(payload, "region_code")
    V.unique_or_reject("store_locations", "code", code)
    row = store.create(
        "store_locations",
        {"code": code, "region_code": region_code, "status": "ACTIVE"},
    )
    return object_response(serialize.out(row), 201)


@bp.patch("/store-locations/<store_id>")
def patch_store_location(store_id):
    V.guard("ProgramAdmin")
    payload = V.body()
    status = V.enum_field(payload, "status", C.STORE_STATUSES)
    row = store.require("store_locations", store_id)
    row["status"] = status
    store.touch(row)
    return object_response(serialize.out(row))


@bp.get("/store-locations/<store_id>")
def get_store_location(store_id):
    V.guard("ProgramAdmin", "IntakeAgent", "RefurbTechnician")
    return object_response(serialize.out(store.require("store_locations", store_id)))


@bp.post("/store-locations/<store_id>/refurb-bays")
def create_refurb_bay(store_id):
    V.guard("ProgramAdmin")
    payload = V.body()
    code = V.str_field(payload, "code")
    bay_type = V.enum_field(payload, "bay_type", C.BAY_TYPES)
    location = store.require("store_locations", store_id)
    V.unique_or_reject(
        "refurb_bays", "code", code, scope=("store_location_id", location["id"])
    )
    row = store.create(
        "refurb_bays",
        {
            "store_location_id": location["id"],
            "code": code,
            "bay_type": bay_type,
            "status": "AVAILABLE",
        },
    )
    return object_response(serialize.out(row), 201)


@bp.get("/store-locations/<store_id>/refurb-bays")
def list_refurb_bays(store_id):
    V.guard("ProgramAdmin", "RefurbTechnician")
    limit, offset = V.pagination()
    bay_type = V.enum_query("bay_type", C.BAY_TYPES)
    status = V.enum_query("status", C.BAY_STATUSES)
    location = store.require("store_locations", store_id)
    rows = [b for b in store.rows("refurb_bays") if b["store_location_id"] == location["id"]]
    if bay_type is not None:
        rows = [b for b in rows if b["bay_type"] == bay_type]
    if status is not None:
        rows = [b for b in rows if b["status"] == status]
    page, total = paginate(store.ordered(rows), limit, offset)
    return list_response(serialize.out_list(page), limit, offset, total)


@bp.patch("/refurb-bays/<bay_id>")
def patch_refurb_bay(bay_id):
    V.guard("ProgramAdmin")
    payload = V.body()
    status = V.enum_field(payload, "status", C.BAY_STATUSES)
    row = store.require("refurb_bays", bay_id)
    row["status"] = status
    store.touch(row)
    return object_response(serialize.out(row))


# --------------------------------------------------------------------------
# sales channels
# --------------------------------------------------------------------------
@bp.post("/channels")
def create_channel():
    V.guard("ProgramAdmin")
    payload = V.body()
    code = V.str_field(payload, "code")
    channel_type = V.enum_field(payload, "channel_type", C.CHANNEL_TYPES)
    allowed_assortment = V.enum_field(payload, "allowed_assortment", C.ASSORTMENTS)
    max_resale_price_ratio_bp = V.int_field(
        payload, "max_resale_price_ratio_bp", minimum=1, maximum=10000
    )
    region_code = V.str_field(payload, "region_code")
    V.unique_or_reject("channels", "code", code)
    row = store.create(
        "channels",
        {
            "code": code,
            "channel_type": channel_type,
            "allowed_assortment": allowed_assortment,
            "max_resale_price_ratio_bp": max_resale_price_ratio_bp,
            "region_code": region_code,
            "status": "ACTIVE",
        },
    )
    return object_response(serialize.out(row), 201)


@bp.patch("/channels/<channel_id>")
def patch_channel(channel_id):
    V.guard("ProgramAdmin")
    payload = V.body()
    status = V.enum_field(payload, "status", C.CHANNEL_STATUSES)
    row = store.require("channels", channel_id)
    row["status"] = status
    store.touch(row)
    return object_response(serialize.out(row))


@bp.get("/channels/<channel_id>")
def get_channel(channel_id):
    V.guard("ProgramAdmin", "MerchandisingManager", "Customer")
    return object_response(serialize.out(store.require("channels", channel_id)))


@bp.get("/channels/<channel_id>/markdown-campaigns")
def list_channel_campaigns(channel_id):
    V.guard("ProgramAdmin", "MerchandisingManager")
    limit, offset = V.pagination()
    product_category = V.enum_query("product_category", C.PRODUCT_CATEGORIES)
    status = V.enum_query("status", C.CAMPAIGN_STATUSES)
    channel = store.require("channels", channel_id)
    rows = [c for c in store.rows("markdown_campaigns") if c["channel_id"] == channel["id"]]
    if product_category is not None:
        rows = [c for c in rows if c["product_category"] == product_category]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    page, total = paginate(store.ordered(rows), limit, offset)
    return list_response(serialize.out_list(page), limit, offset, total)


# --------------------------------------------------------------------------
# the logical clock — the one endpoint exempt from the header checks
# --------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    payload = V.body()
    current_utc = V.ts_field(payload, "current_utc")
    store.set_clock(current_utc)
    return object_response({"current_utc": store.fmt_ts(store.now())})
