"""Providers: catalogue of prescribers under a practice."""

import db
from errors import ApiError
from registry import route
from routes._shared import filtered, paginate, serial
from services import helpers
from services.helpers import as_bool, as_enum, as_str

READ_ROLES = [
    "NetworkAdmin",
    "PracticeAdmin",
    "RevenueCycleManager",
    "NetworkAnalyst",
    "PlatformAdmin",
]


@route(
    "POST",
    "/networks/practices/{practiceId}/providers",
    roles=["PracticeAdmin"],
    status=201,
    write=True,
)
def create_provider(ctx):
    practice = helpers.practice_or_404(ctx.path_id("practiceId"))
    helpers.may_edit_practice(ctx.principal, practice["id"])
    data = ctx.body
    provider = db.create(
        "providers",
        {
            "practice_id": practice["id"],
            "full_name": as_str(data, "full_name"),
            "npi": as_str(data, "npi"),
            "specialty": as_enum(
                data,
                "specialty",
                ("MEDICAL_ONCOLOGY", "HEMATOLOGY", "RADIATION_ONCOLOGY"),
                required_=True,
            ),
            "is_billing_provider": as_bool(data, "is_billing_provider", default=True),
            "status": "ACTIVE",
        },
    )
    return serial(provider), 201


@route("GET", "/networks/providers", roles=READ_ROLES)
def list_providers(ctx):
    rows = filtered(
        db.all_records("providers"),
        ctx,
        {"practice_id": "practice_id", "status": "status", "specialty": "specialty"},
    )
    return paginate(ctx, rows)


@route("GET", "/networks/providers/{providerId}", roles=READ_ROLES)
def get_provider(ctx):
    return serial(helpers.provider_or_404(ctx.path_id("providerId")))


@route("GET", "/networks/providers/{providerId}/treatments", roles=READ_ROLES)
def provider_treatments(ctx):
    provider = helpers.provider_or_404(ctx.path_id("providerId"))
    rows = filtered(
        db.where("treatments", provider_id=provider["id"]), ctx, {"status": "status"}
    )
    return paginate(ctx, rows)


@route("POST", "/networks/providers/{providerId}/deactivate", roles=["PracticeAdmin"], write=True)
def deactivate_provider(ctx):
    provider = helpers.provider_or_404(ctx.path_id("providerId"))
    helpers.may_edit_practice(ctx.principal, provider.get("practice_id"))
    if provider["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    scheduled = [
        t
        for t in db.where("treatments", provider_id=provider["id"])
        if t["status"] == "SCHEDULED"
    ]
    if scheduled:
        raise ApiError("ERR_TREATMENT_NOT_SCHEDULED")
    provider["status"] = "INACTIVE"
    db.touch(provider)
    return serial(provider)


@route("POST", "/networks/providers/{providerId}/reactivate", roles=["PracticeAdmin"], write=True)
def reactivate_provider(ctx):
    provider = helpers.provider_or_404(ctx.path_id("providerId"))
    helpers.may_edit_practice(ctx.principal, provider.get("practice_id"))
    if provider["status"] != "INACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    provider["status"] = "ACTIVE"
    db.touch(provider)
    return serial(provider)