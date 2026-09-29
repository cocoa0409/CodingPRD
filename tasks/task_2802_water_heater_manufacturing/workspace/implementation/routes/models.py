"""The model catalogue and its two independent state dimensions (PRD 3.2 / 3.8)."""

from flask import Blueprint

import db
import response
import serializers
import validation
from db import make_row, ordered, touch
from errors import ApiError
from middleware import endpoint
from services import calc
from services.core import require_unique, resolve, rows

bp = Blueprint("models", __name__)

FUEL_TYPES = ("GAS", "ELECTRIC", "HEAT_PUMP")
CHANNELS = ("TRADE", "RETAIL", "BUILDER")
CERTIFICATION_STATUSES = (
    "UNCERTIFIED",
    "TEST_PENDING",
    "CERTIFIED",
    "SUSPENDED",
    "DECERTIFIED",
)
RELEASE_STATUSES = ("DRAFT", "RELEASED", "RESTRICTED", "WITHDRAWN")
VARIANTS = ("COHORT_NAIVE", "EXPOSURE_WEIGHTED")

READ_ROLES = [
    "ComplianceEngineer",
    "CertificationApprover",
    "PlantAdmin",
    "PlantOperator",
    "QualityInspector",
    "WarrantyAnalyst",
]


@bp.post("/product-models")
@endpoint(["ComplianceEngineer"])
def create_model():
    body = validation.json_body()
    model_code = validation.string(
        body, "model_code", max_length=24, pattern=r"^[A-Z0-9-]+$"
    )
    fuel_type = validation.enum(body, "fuel_type", FUEL_TYPES)
    capacity = validation.integer(
        body, "nominal_capacity_gallons", minimum=20, maximum=120
    )
    channel = validation.enum(body, "channel", CHANNELS)
    r_value = validation.number(body, "insulation_r_value", minimum=10.0, maximum=40.0)
    is_private_label = validation.boolean(
        body, "is_private_label", required=False, default=False
    )
    base_model_id = validation.string(body, "base_model_id", required=False)
    if is_private_label:
        brand_label = validation.string(body, "brand_label", max_length=40)
    else:
        validation.forbid(
            body,
            "brand_label",
            "Field 'brand_label' must be omitted on a non-private-label model.",
        )
        brand_label = None

    base = None
    if base_model_id is not None:
        base = resolve("model", base_model_id)

    # Position 16: private-label base consistency.
    if is_private_label:
        if base is None:
            raise ApiError("ERR_PRIVATE_LABEL_BASE_INVALID")
        if base["is_private_label"]:
            raise ApiError("ERR_PRIVATE_LABEL_BASE_INVALID")
        if base["fuel_type"] != fuel_type:
            raise ApiError("ERR_PRIVATE_LABEL_BASE_INVALID")
        if base["nominal_capacity_gallons"] != capacity:
            raise ApiError("ERR_PRIVATE_LABEL_BASE_INVALID")
    elif base is not None:
        raise ApiError("ERR_PRIVATE_LABEL_BASE_INVALID")

    # Position 23: catalogue code uniqueness.
    require_unique("model", "model_code", model_code)

    row = make_row(
        {
            "model_code": model_code,
            "fuel_type": fuel_type,
            "nominal_capacity_gallons": capacity,
            "channel": channel,
            "insulation_r_value": r_value,
            "base_model_id": base["id"] if base is not None else None,
            "is_private_label": is_private_label,
            "brand_label": brand_label,
            "certification_status": "UNCERTIFIED",
            "release_status": "DRAFT",
            "uef_rated": None,
            "fhr_rated": None,
            "recovery_rate_rated": None,
            "label_serial_prefix": None,
            "warranty_reserve_accrued_cents": 0,
            "warranty_paid_cents": 0,
        }
    )
    db.db.models[row["id"]] = row
    return response.created(serializers.product_model(row))


@bp.get("/product-models/<mid>")
@endpoint(READ_ROLES)
def read_model(mid):
    return response.ok(serializers.product_model(resolve("model", mid)))


@bp.get("/product-models")
@endpoint(READ_ROLES)
def list_models():
    base_model_id = validation.query_string("base_model_id")
    channel = validation.query_enum("channel", CHANNELS)
    fuel_type = validation.query_enum("fuel_type", FUEL_TYPES)
    cert_status = validation.query_enum("certification_status", CERTIFICATION_STATUSES)
    release_status = validation.query_enum("release_status", RELEASE_STATUSES)
    result = rows("model")
    if base_model_id is not None:
        result = [r for r in result if r.get("base_model_id") == base_model_id]
    if channel is not None:
        result = [r for r in result if r["channel"] == channel]
    if fuel_type is not None:
        result = [r for r in result if r["fuel_type"] == fuel_type]
    if cert_status is not None:
        result = [r for r in result if r["certification_status"] == cert_status]
    if release_status is not None:
        result = [r for r in result if r["release_status"] == release_status]
    return response.paginate(ordered(result), serializers.product_model)


@bp.post("/product-models/<mid>/release-to-channel")
@endpoint(["ComplianceEngineer"])
def release_to_channel(mid):
    model = resolve("model", mid)
    if model["release_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_MODEL_STATE")
    # Position 41: a private-label variant may not outrun its base.
    if model["is_private_label"]:
        base = db.db.models.get(model.get("base_model_id"))
        if base is None or base["release_status"] not in ("RELEASED", "RESTRICTED"):
            raise ApiError("ERR_BASE_MODEL_NOT_RELEASED")
    model["release_status"] = "RELEASED"
    touch(model)
    return response.ok(serializers.product_model(model))


@bp.post("/product-models/<mid>/lift-restriction")
@endpoint(["PlantAdmin"])
def lift_restriction(mid):
    model = resolve("model", mid)
    if model["release_status"] != "RESTRICTED":
        raise ApiError("ERR_INVALID_MODEL_STATE")
    # Position 33: containment must be fully cleared first.
    if serializers.held_unit_count(model["id"]) != 0:
        raise ApiError("ERR_HELD_UNITS_REMAIN")
    model["release_status"] = "RELEASED"
    touch(model)
    return response.ok(serializers.product_model(model))


@bp.post("/product-models/<mid>/withdraw")
@endpoint(["ComplianceEngineer"])
def withdraw_model(mid):
    model = resolve("model", mid)
    body = validation.json_body()
    validation.string(body, "reason_code")
    if model["release_status"] not in ("RELEASED", "RESTRICTED"):
        raise ApiError("ERR_INVALID_MODEL_STATE")

    model["release_status"] = "WITHDRAWN"
    touch(model)
    # Withdrawal fans out down the private-label tree.
    variants = [
        v
        for v in rows("model")
        if v.get("base_model_id") == model["id"]
        and v["release_status"] in ("RELEASED", "RESTRICTED")
    ]
    for variant in ordered(variants):
        variant["release_status"] = "WITHDRAWN"
        touch(variant)
    return response.ok(serializers.product_model(model))


@bp.post("/product-models/<mid>/suspend-certification")
@endpoint(["CertificationApprover"])
def suspend_certification(mid):
    model = resolve("model", mid)
    body = validation.json_body()
    validation.string(body, "reason_code")
    if model["certification_status"] != "CERTIFIED":
        raise ApiError("ERR_INVALID_MODEL_STATE")
    # The four published values are deliberately retained.
    model["certification_status"] = "SUSPENDED"
    touch(model)
    return response.ok(serializers.product_model(model))


@bp.get("/product-models/<mid>/warranty-analysis")
@endpoint(["WarrantyAnalyst", "ComplianceEngineer", "PlantAdmin"])
def warranty_analysis(mid):
    model = resolve("model", mid)
    production_period = validation.query_string("production_period")
    if production_period is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", "Query parameter 'production_period' is required."
        )
    variant = validation.query_enum("variant", VARIANTS) or "COHORT_NAIVE"

    cohort = ordered(
        [
            u
            for u in rows("unit")
            if u["product_model_id"] == model["id"]
            and u.get("production_period") == production_period
            and u["build_status"] == "SHIPPED"
        ]
    )
    cohort_ids = {u["id"] for u in cohort}
    shipped_unit_count = len(cohort)

    tank_leak_claim_count = sum(
        1
        for c in rows("claim")
        if c["heater_unit_id"] in cohort_ids
        and c["failure_mode"] == "TANK_LEAK"
        and c["status"] in ("VALIDATED", "PAID")
    )

    now = db.db.now()
    pairs = [
        (calc.months_in_service(u.get("shipped_at"), now), u.get("hardness_factor"))
        for u in cohort
    ]
    weighted = calc.weighted_exposure(pairs)

    if variant == "EXPOSURE_WEIGHTED":
        rate = calc.failure_rate_ppm(tank_leak_claim_count, weighted)
    else:
        rate = calc.failure_rate_ppm(tank_leak_claim_count, shipped_unit_count)

    def band_count(band):
        return sum(1 for u in cohort if u.get("water_hardness_band") == band)

    return response.ok(
        {
            "production_period": production_period,
            "variant": variant,
            "shipped_unit_count": shipped_unit_count,
            "tank_leak_claim_count": tank_leak_claim_count,
            "weighted_exposure_unit_months": calc.out_num(weighted),
            "failure_rate_ppm": calc.out_num(rate),
            "soft_unit_count": band_count("SOFT"),
            "moderate_unit_count": band_count("MODERATE"),
            "hard_unit_count": band_count("HARD"),
            "very_hard_unit_count": band_count("VERY_HARD"),
        }
    )
