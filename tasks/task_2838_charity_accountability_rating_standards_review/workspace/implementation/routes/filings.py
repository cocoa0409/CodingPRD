"""Filing records: submission, validation and reads."""

from db import SOURCE_KINDS, SOURCE_PRECEDENCE, new_row, rows, store, touch
from errors import ApiError
from middleware import route
from response import ok

CENT_FIELDS = [
    "total_expense_cents",
    "program_expense_cents",
    "fundraising_expense_cents",
    "admin_expense_cents",
    "contributions_cents",
    "total_revenue_cents",
    "net_assets_cents",
    "total_liabilities_cents",
]
OPTIONAL_CENT_FIELDS = [
    "grants_paid_cents",
    "membership_services_cents",
    "joint_cost_allocated_cents",
]

FILING_BODY = {
    "organization_id": {"type": "string", "required": True, "fk": "Organization"},
    "fiscal_year": {"type": "int", "required": True, "min": 2000, "max": 2100},
    "source_kind": {"type": "enum", "required": True, "values": SOURCE_KINDS},
}
for _field in CENT_FIELDS:
    FILING_BODY[_field] = {"type": "int", "required": True, "min": 0}
for _field in OPTIONAL_CENT_FIELDS:
    FILING_BODY[_field] = {"type": "int", "min": 0, "default": 0}
FILING_BODY["expected_organization_version"] = {"type": "int", "required": True}

READ_ROLES = [
    "MethodologyAdmin",
    "RatingAnalyst",
    "PublishingReviewer",
    "AppealPanelist",
    "OrganizationRep",
]


def check_expense_identity(values):
    if values["total_expense_cents"] != (
        values["program_expense_cents"]
        + values["fundraising_expense_cents"]
        + values["admin_expense_cents"]
    ):
        raise ApiError("ERR_EXPENSE_COMPONENTS_MISMATCH")
    if (values["joint_cost_allocated_cents"] or 0) > values["program_expense_cents"]:
        raise ApiError("ERR_EXPENSE_COMPONENTS_MISMATCH")


@route(
    "/filing-records",
    "POST",
    ["RatingAnalyst", "OrganizationRep"],
    body=FILING_BODY,
)
def create_filing(ctx):
    organization = ctx.fk["organization_id"]
    # check 9 - optimistic concurrency on the parent organization
    if ctx.body["expected_organization_version"] != organization["version"]:
        raise ApiError("ERR_STALE_VERSION")
    # check 29 - expense identity
    check_expense_identity(ctx.body)

    payload = {field: ctx.body[field] for field in CENT_FIELDS + OPTIONAL_CENT_FIELDS}
    record = new_row(
        "FilingRecord",
        dict(
            organization_id=organization["id"],
            fiscal_year=ctx.body["fiscal_year"],
            source_kind=ctx.body["source_kind"],
            source_precedence=SOURCE_PRECEDENCE[ctx.body["source_kind"]],
            status="RECEIVED",
            origin=("ORG_PORTAL" if ctx.role == "OrganizationRep" else "ANALYST_ENTRY"),
            validated_at=None,
            rejection_code=None,
            superseded_at=None,
            **payload
        ),
    )
    touch(organization)
    return ok(record, 201)


@route(
    "/filing-records/<filing_record_id>",
    "GET",
    READ_ROLES,
    path_params=[("filing_record_id", "FilingRecord")],
)
def get_filing(ctx):
    return ok(ctx.path["filing_record_id"])


VALIDATE_BODY = {
    "decision": {"type": "enum", "required": True, "values": ["ACCEPT", "REJECT"]},
    "rejection_code": {"type": "string"},
}


@route(
    "/filing-records/<filing_record_id>/validate",
    "POST",
    ["RatingAnalyst"],
    path_params=[("filing_record_id", "FilingRecord")],
    body=VALIDATE_BODY,
)
def validate_filing(ctx):
    filing = ctx.path["filing_record_id"]
    decision = ctx.body["decision"]
    if decision == "REJECT" and not ctx.body["rejection_code"]:
        raise ApiError("ERR_INVALID_REQUEST", "rejection_code is required to reject.")
    if filing["status"] != "RECEIVED":
        raise ApiError("ERR_FILING_STATE_INVALID")
    check_expense_identity(filing)

    if decision == "ACCEPT":
        filing["status"] = "VALIDATED"
        filing["validated_at"] = store.now()
        touch(filing)
        for other in rows("FilingRecord"):
            if other["id"] == filing["id"]:
                continue
            if (
                other["organization_id"] == filing["organization_id"]
                and other["fiscal_year"] == filing["fiscal_year"]
                and other["source_kind"] == filing["source_kind"]
                and other["status"] == "VALIDATED"
            ):
                other["status"] = "SUPERSEDED"
                other["superseded_at"] = store.now()
                touch(other)
    else:
        filing["status"] = "REJECTED"
        filing["rejection_code"] = ctx.body["rejection_code"]
        touch(filing)
    return ok(filing)
