"""RoyaltyStatement endpoints and the host settlement waterfall."""

from decimal import Decimal

from flask import Blueprint

import calc
import derived
import store
from auth import authenticate, deny_role, require_owner, require_role
from common import month_window, r2
from envelope import object_response, paginate, pagination
from errors import fail
from helpers import arg, filter_equal, must_find
from serializers import statement_out
from validation import Field, MONTH_PATTERN, parse_body, peek_body, validate

bp = Blueprint("royalty", __name__)

ZERO = Decimal("0")

STATEMENT_FIELDS = [
    Field("site_id", "string", required=True),
    Field("period", "string", required=True, max_len=7, pattern=MONTH_PATTERN),
    Field("expected_site_version", "integer", required=True),
    Field("allowed_deductions_usd", "number", gte=0, default=ZERO),
    Field(
        "variant_override",
        "enum",
        values=("GROSS_REVENUE_SHARE", "NETBACK_SHARE"),
    ),
]

LIVE_STATEMENT_STATUSES = ("DRAFT", "ISSUED", "PAID")


def _settle(site, period, variant_applied, deductions):
    window_start, window_end = month_window(period)

    batches = []
    for batch in store.injection_batches.values():
        if batch["status"] != "INJECTED":
            continue
        if not (window_start <= batch["interval_start"] < window_end):
            continue
        plant = store.plants.get(batch["plant_id"])
        if plant is None or plant["site_id"] != site["id"]:
            continue
        batches.append(batch)
    batches.sort(key=lambda b: (b["interval_start"], b["created_at"], b["_seq"]))

    billable = ZERO
    gas_revenue = ZERO
    for batch in batches:
        billable += batch["gross_mmbtu"]
        price = None
        nomination = (
            store.nominations.get(batch["nomination_id"]) if batch["nomination_id"] else None
        )
        if nomination is not None:
            contract = store.contracts.get(nomination["contract_id"])
            if contract is not None:
                price = contract["price_usd_per_dth"]
        if price is not None:
            gas_revenue += r2(batch["gross_mmbtu"] * price)
    billable = r2(billable)
    gas_revenue = r2(gas_revenue)

    batch_ids = set(b["id"] for b in batches)
    attribute_revenue = ZERO
    for attribute in store.attribute_batches.values():
        if attribute["injection_batch_id"] not in batch_ids:
            continue
        if attribute["status"] not in ("GENERATED", "QA_HOLD", "SEPARATED", "RETIRED"):
            continue
        attribute_revenue += (
            Decimal(attribute["rin_count"]) * calc.RIN_PRICE_USD
            + attribute["lcfs_credits"] * calc.LCFS_PRICE_USD
        )
    attribute_revenue = r2(attribute_revenue)

    gross_revenue = r2(gas_revenue + attribute_revenue)

    if variant_applied == "GROSS_REVENUE_SHARE":
        calculated = r2(gross_revenue * site["host_royalty_pct"])
    else:
        base = gross_revenue - deductions
        if base < 0:
            base = ZERO
        calculated = r2(base * site["host_royalty_pct"])

    floor = r2(billable * site["royalty_floor_usd_per_mmbtu"])
    royalty = calculated if calculated > floor else floor

    return {
        "billable_mmbtu": billable,
        "gas_revenue_usd": gas_revenue,
        "attribute_revenue_usd": attribute_revenue,
        "gross_revenue_usd": gross_revenue,
        "calculated_amount_usd": calculated,
        "floor_amount_usd": floor,
        "royalty_amount_usd": r2(royalty),
    }


@bp.post("/royalty-statements")
def create_statement():
    caller = authenticate()
    require_role(caller, ["ProjectAdmin"])
    body = parse_body()
    data = validate(body, STATEMENT_FIELDS)

    site = must_find("site", data["site_id"])

    # Priority 70 - optimistic concurrency on the parent site.
    if data["expected_site_version"] != site["version"]:
        fail(
            "ERR_STALE_SITE_VERSION",
            "expected_site_version does not match the site's current version.",
        )

    # Priority 110 - the settlement month must have fully elapsed.
    _, window_end = month_window(data["period"])
    if store.now() < window_end:
        fail("ERR_ROYALTY_PERIOD_NOT_CLOSED", "The settlement month has not fully elapsed.")

    # Priority 120 - one live statement per (site, period).
    for other in store.royalty_statements.values():
        if (
            other["site_id"] == site["id"]
            and other["period"] == data["period"]
            and other["status"] in LIVE_STATEMENT_STATUSES
        ):
            fail(
                "ERR_ROYALTY_PERIOD_DUPLICATE",
                "A live royalty statement already exists for this site and period.",
            )

    variant_applied = data["variant_override"] or site["royalty_variant"]
    settled = _settle(site, data["period"], variant_applied, data["allowed_deductions_usd"])

    row = store.new_row(
        site_id=site["id"],
        period=data["period"],
        allowed_deductions_usd=data["allowed_deductions_usd"],
        variant_override=data["variant_override"],
        variant_applied=variant_applied,
        status="DRAFT",
        dispute_reason=None,
        **settled
    )
    store.royalty_statements[row["id"]] = row

    store.touch(site)
    return object_response(statement_out(row), 201)


@bp.get("/royalty-statements/<statement_id>")
def read_statement(statement_id):
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "ComplianceOfficer", "HostRepresentative"])
    row = must_find("statement", statement_id)
    if caller.role == "HostRepresentative":
        require_owner(caller, row["site_id"])
    return object_response(statement_out(row))


@bp.get("/royalty-statements")
def list_statements():
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "ComplianceOfficer", "HostRepresentative"])
    limit, offset = pagination()

    site_filter = arg("site_id")
    if caller.role == "HostRepresentative":
        if site_filter is not None and site_filter != caller.user_id:
            fail(
                "ERR_NOT_RESOURCE_OWNER",
                "A host representative may only list statements of its own site.",
            )
        site_filter = caller.user_id

    rows = store.ordered(store.royalty_statements.values())
    rows = filter_equal(rows, "site_id", site_filter)
    rows = filter_equal(rows, "period", arg("period"))
    rows = filter_equal(rows, "status", arg("status"))
    return paginate(rows, limit, offset, statement_out)


STATEMENT_STATUS_FIELDS = [
    Field("to_status", "enum", required=True, values=("DRAFT", "ISSUED", "DISPUTED", "PAID")),
    Field("dispute_reason", "string", max_len=500),
]

STATEMENT_TRANSITIONS = {
    ("DRAFT", "ISSUED"),
    ("ISSUED", "DISPUTED"),
    ("DISPUTED", "ISSUED"),
    ("ISSUED", "PAID"),
}


@bp.post("/royalty-statements/<statement_id>/status")
def statement_status(statement_id):
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "HostRepresentative"])

    requested = peek_body().get("to_status")
    if caller.role == "HostRepresentative" and requested in ("ISSUED", "PAID", "DRAFT"):
        deny_role("A host representative may only dispute a statement.")
    if caller.role == "ProjectAdmin" and requested == "DISPUTED":
        deny_role("Only the site's host representative may dispute a statement.")

    statement = must_find("statement", statement_id)
    body = parse_body()
    data = validate(body, STATEMENT_STATUS_FIELDS)

    # Priority 60 - resource ownership.
    if caller.role == "HostRepresentative":
        require_owner(caller, statement["site_id"])

    target = data["to_status"]
    current = statement["status"]

    # Priority 80 - state legality.
    if (current, target) not in STATEMENT_TRANSITIONS:
        fail("ERR_INVALID_TRANSITION", "%s -> %s is not a declared transition." % (current, target))

    if current == "DISPUTED" and target == "ISSUED":
        for other in store.royalty_statements.values():
            if other["id"] == statement["id"]:
                continue
            if (
                other["site_id"] == statement["site_id"]
                and other["period"] == statement["period"]
                and other["status"] in LIVE_STATEMENT_STATUSES
            ):
                fail(
                    "ERR_INVALID_TRANSITION",
                    "Another live statement already occupies this site and period.",
                )

    site = store.sites.get(statement["site_id"])
    amount = statement["royalty_amount_usd"]

    if target == "ISSUED":
        changes = {"status": "ISSUED"}
        if current == "DISPUTED":
            changes["dispute_reason"] = None
        derived.apply_changes(statement, changes)
        if site is not None:
            derived.move_payable(site, amount)
    elif target == "DISPUTED":
        derived.apply_changes(
            statement, {"status": "DISPUTED", "dispute_reason": data["dispute_reason"]}
        )
        if site is not None:
            derived.move_payable(site, -amount)
    else:  # PAID
        derived.apply_changes(statement, {"status": "PAID"})
        if site is not None:
            derived.move_payable(site, -amount)

    return object_response(statement_out(statement))
