"""ComplianceReport endpoints, segregation of duties and the return cascade."""

from flask import Blueprint

import derived
import store
from auth import authenticate, require_role
from common import month_in_quarter
from envelope import object_response, paginate, pagination
from errors import fail
from helpers import arg, filter_equal, must_find
from serializers import report_out
from validation import Field, QUARTER_PATTERN, parse_body, validate

bp = Blueprint("reports", __name__)

REPORT_FIELDS = [
    Field("site_id", "string", required=True),
    Field(
        "report_type",
        "enum",
        required=True,
        values=("NSPS_ANNUAL", "QUARTERLY_RIN_QAP", "LCFS_QUARTERLY", "TITLE_V_SEMIANNUAL"),
    ),
    Field("period", "string", required=True, max_len=7, pattern=QUARTER_PATTERN),
    Field("nmoc_lb_per_hr_reported", "number", required=True, gte=0),
]


@bp.post("/compliance-reports")
def create_report():
    caller = authenticate()
    require_role(caller, ["ComplianceOfficer"])
    body = parse_body()
    data = validate(body, REPORT_FIELDS)

    site = must_find("site", data["site_id"])

    # Priority 120 - one live filing per (site, type, period).
    for other in store.compliance_reports.values():
        if (
            other["site_id"] == site["id"]
            and other["report_type"] == data["report_type"]
            and other["period"] == data["period"]
            and other["status"] != "RETURNED"
        ):
            fail(
                "ERR_REPORT_PERIOD_DUPLICATE",
                "A live filing already exists for this site, type and period.",
            )

    row = store.new_row(
        site_id=site["id"],
        report_type=data["report_type"],
        period=data["period"],
        nmoc_lb_per_hr_reported=data["nmoc_lb_per_hr_reported"],
        exceedance_flag=data["nmoc_lb_per_hr_reported"] > site["permit_nmoc_limit_lb_per_hr"],
        status="DRAFT",
        prepared_by_user_id=caller.user_id,
        reviewed_by_user_id=None,
        revision_count=0,
        return_reason=None,
        corrective_action_note=None,
    )
    store.compliance_reports[row["id"]] = row
    derived.recompute_compliance_posture(site)
    return object_response(report_out(row), 201)


@bp.get("/compliance-reports/<report_id>")
def read_report(report_id):
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "ComplianceOfficer"])
    row = must_find("report", report_id)
    return object_response(report_out(row))


@bp.get("/compliance-reports")
def list_reports():
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "ComplianceOfficer"])
    limit, offset = pagination()
    rows = store.ordered(store.compliance_reports.values())
    rows = filter_equal(rows, "site_id", arg("site_id"))
    rows = filter_equal(rows, "report_type", arg("report_type"))
    rows = filter_equal(rows, "period", arg("period"))
    rows = filter_equal(rows, "status", arg("status"))
    return paginate(rows, limit, offset, report_out)


REPORT_STATUS_FIELDS = [
    Field(
        "to_status",
        "enum",
        required=True,
        values=("DRAFT", "SUBMITTED", "UNDER_REVIEW", "RETURNED", "ACCEPTED"),
    ),
    Field("return_reason", "string", max_len=500),
    Field("corrective_action_note", "string", max_len=500),
]

REPORT_TRANSITIONS = {
    ("DRAFT", "SUBMITTED"),
    ("SUBMITTED", "UNDER_REVIEW"),
    ("UNDER_REVIEW", "RETURNED"),
    ("UNDER_REVIEW", "ACCEPTED"),
    ("RETURNED", "DRAFT"),
}


def _return_cascade(report, site):
    """Report-return cascade: QA hold on the period's attributes, then the
    site's issued royalty statements for months inside the period."""
    held = 0
    for attribute in store.ordered(store.attribute_batches.values()):
        if attribute["status"] != "GENERATED":
            continue
        if not month_in_quarter(attribute["generation_period"], report["period"]):
            continue
        attribute_site = derived.site_of_attribute(attribute)
        if attribute_site is None or attribute_site["id"] != report["site_id"]:
            continue
        derived.apply_changes(attribute, {"status": "QA_HOLD"})
        held += 1

    if held == 0:
        return

    for statement in store.ordered(store.royalty_statements.values()):
        if statement["site_id"] != report["site_id"]:
            continue
        if statement["status"] != "ISSUED":
            continue
        if not month_in_quarter(statement["period"], report["period"]):
            continue
        derived.apply_changes(
            statement, {"status": "DISPUTED", "dispute_reason": "ATTRIBUTE_QA_HOLD"}
        )
        if site is not None:
            derived.move_payable(site, -statement["royalty_amount_usd"])


@bp.post("/compliance-reports/<report_id>/status")
def report_status(report_id):
    caller = authenticate()
    require_role(caller, ["ComplianceOfficer"])
    report = must_find("report", report_id)
    body = parse_body()
    data = validate(body, REPORT_STATUS_FIELDS)

    target = data["to_status"]
    current = report["status"]

    if target == "RETURNED" and data["return_reason"] is None:
        fail("ERR_VALIDATION", "return_reason is required when returning a filing.")

    # Priority 65 - segregation of duties.
    if target in ("SUBMITTED", "DRAFT"):
        if caller.user_id != report["prepared_by_user_id"]:
            fail(
                "ERR_SEGREGATION_OF_DUTIES",
                "Only the preparing officer may drive this transition.",
            )
    elif target == "UNDER_REVIEW":
        if caller.user_id == report["prepared_by_user_id"]:
            fail(
                "ERR_SEGREGATION_OF_DUTIES",
                "The preparing officer may not review their own filing.",
            )
    elif target in ("RETURNED", "ACCEPTED"):
        if report["reviewed_by_user_id"] is None or caller.user_id != report["reviewed_by_user_id"]:
            fail(
                "ERR_SEGREGATION_OF_DUTIES",
                "Only the reviewing officer may dispose of this filing.",
            )

    # Priority 80 - state legality.
    if (current, target) not in REPORT_TRANSITIONS:
        fail("ERR_INVALID_TRANSITION", "%s -> %s is not a declared transition." % (current, target))

    # Priority 90 - permit exceedance gate.
    if target == "ACCEPTED" and report["exceedance_flag"] and data["corrective_action_note"] is None:
        fail(
            "ERR_PERMIT_EXCEEDANCE_UNRESOLVED",
            "Accepting an exceedance filing requires a corrective_action_note.",
        )

    site = store.sites.get(report["site_id"])

    if target == "UNDER_REVIEW":
        derived.apply_changes(
            report, {"status": "UNDER_REVIEW", "reviewed_by_user_id": caller.user_id}
        )
    elif target == "RETURNED":
        derived.apply_changes(
            report,
            {
                "status": "RETURNED",
                "return_reason": data["return_reason"],
                "revision_count": report["revision_count"] + 1,
            },
        )
        _return_cascade(report, site)
    elif target == "ACCEPTED":
        changes = {"status": "ACCEPTED"}
        if data["corrective_action_note"] is not None:
            changes["corrective_action_note"] = data["corrective_action_note"]
        derived.apply_changes(report, changes)
    else:
        derived.apply_changes(report, {"status": target})

    if site is not None:
        derived.recompute_compliance_posture(site)

    return object_response(report_out(report))
