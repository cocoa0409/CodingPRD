"""Sales reports, exclusion lines and the filing / acceptance / estimate cascades."""

from flask import request

import calc
from core import (
    ApiError,
    DB,
    add_days,
    all_of,
    bad,
    body,
    clock_now,
    endpoint,
    find,
    make_record,
    must_get,
    need_dt,
    need_int,
    need_str,
    ok,
    paginate,
    qs_bool,
    require_lease_tenant,
    touch,
)
from serializers import report_is_delinquent, ser, ser_report


def _rebuild_exclusions(report, lines):
    for old in calc.exclusions_of_report(report):
        DB["sales_exclusions"].pop(old["id"], None)
    for line in lines:
        make_record(
            "sales_exclusions",
            {
                "sales_report_id": report["id"],
                "code": line["code"],
                "claimed_cents": line["claimed_cents"],
                "allowed_cents": 0,
                "status": "CLAIMED",
            },
        )


def register(app):
    @app.post("/retail/lease-years/<yid>/sales-reports")
    @endpoint("LeaseAdministrator")
    def create_sales_report(yid):
        ly = must_get("lease_years", yid)
        payload = body()
        period_start = need_dt(payload, "period_start")
        period_end = need_dt(payload, "period_end")
        if period_end <= period_start:
            bad("period_end must be strictly after period_start.")
        # step 6 - state
        if ly["status"] != "OPEN":
            raise ApiError("ERR_LEASE_YEAR_STATE_INVALID", 409)
        # step 11 - interval rules
        if calc.report_period_conflicts(ly, period_start, period_end):
            raise ApiError("ERR_REPORTING_PERIOD_OVERLAP", 409)
        # step 12 - domain shape
        if period_start < ly["period_start"] or period_end > ly["period_end"]:
            raise ApiError("ERR_PERIOD_OUTSIDE_LEASE_YEAR", 422)

        lease = calc.lease_of_year(ly)
        rec = make_record(
            "sales_reports",
            {
                "lease_year_id": ly["id"],
                "period_start": period_start,
                "period_end": period_end,
                "due_at": add_days(period_end, lease["reporting_deadline_days"]),
                "submitted_at": None,
                "gross_sales_cents": None,
                "allowed_exclusions_cents": 0,
                "net_sales_cents": 0,
                "source": "TENANT_REPORTED",
                "amendment_round": 0,
                "is_delinquent": False,
                "status": "PENDING",
            },
        )
        return ok(ser_report(rec), 201)

    @app.get("/retail/sales-reports/<rid>")
    @endpoint("CenterAdmin", "LeaseAdministrator", "Auditor", "OwnershipAnalyst", "TenantUser")
    def get_sales_report(rid):
        return ok(ser_report(must_get("sales_reports", rid)))

    @app.get("/retail/sales-reports")
    @endpoint("CenterAdmin", "LeaseAdministrator", "Auditor", "OwnershipAnalyst", "TenantUser")
    def list_sales_reports():
        rows = all_of("sales_reports")
        for key in ("lease_year_id", "status", "source"):
            value = request.args.get(key)
            if value:
                rows = [r for r in rows if r[key] == value]
        delinquent = qs_bool("is_delinquent")
        if delinquent is not None:
            rows = [r for r in rows if report_is_delinquent(r) == delinquent]
        return paginate(rows, ser_report)

    @app.get("/retail/sales-reports/<rid>/exclusions")
    @endpoint("CenterAdmin", "LeaseAdministrator", "Auditor", "TenantUser")
    def list_exclusions(rid):
        report = must_get("sales_reports", rid)
        rows = calc.exclusions_of_report(report)
        for key in ("code", "status"):
            value = request.args.get(key)
            if value:
                rows = [r for r in rows if r[key] == value]
        return paginate(rows, ser)

    # ------------------------------------------------------------------ submit

    @app.post("/retail/sales-reports/<rid>/submit")
    @endpoint("TenantUser")
    def submit_report(rid):
        report = must_get("sales_reports", rid)
        ly = calc.year_of_report(report)
        lease = calc.lease_of_year(ly)
        require_lease_tenant(lease)

        payload = body()
        gross = need_int(payload, "gross_sales_cents", minimum=0)
        raw_lines = payload.get("exclusions")
        lines = []
        if raw_lines is not None:
            if not isinstance(raw_lines, list):
                bad("Field 'exclusions' must be an array.")
            for entry in raw_lines:
                if not isinstance(entry, dict):
                    bad("Each exclusion must be an object.")
                code = entry.get("code")
                if not isinstance(code, str) or code not in calc.EXCLUSION_CODES:
                    bad("Exclusion 'code' must be a declared exclusion category.")
                claimed = entry.get("claimed_cents")
                if claimed is None or isinstance(claimed, bool) or not isinstance(claimed, int):
                    bad("Exclusion 'claimed_cents' must be an integer.")
                if claimed < 0:
                    bad("Exclusion 'claimed_cents' must be >= 0.")
                lines.append({"code": code, "claimed_cents": claimed})

        # step 6 - state
        if report["status"] not in ("PENDING", "ESTIMATED", "AMENDED"):
            raise ApiError("ERR_REPORT_STATE_INVALID", 409)
        if report["status"] == "AMENDED":
            calc.require_year_status(ly, ("OPEN", "RECONCILING"))
        else:
            calc.require_year_status(ly, ("OPEN",))

        # step 12 - domain shape: zero-capped codes may not be claimed at all
        caps = calc.EXCLUSION_CAP_BPS[lease["exclusion_profile"]]
        for line in lines:
            if caps[line["code"]] == 0 and line["claimed_cents"] > 0:
                raise ApiError("ERR_EXCLUSION_CODE_NOT_PERMITTED", 422)

        origin = report["status"]
        former_net = report["net_sales_cents"]

        report["gross_sales_cents"] = gross
        report["source"] = "TENANT_REPORTED"
        report["submitted_at"] = clock_now()
        report["status"] = "SUBMITTED"
        _rebuild_exclusions(report, lines)
        calc.net_reported_sales(report)
        touch(report)

        if origin == "ESTIMATED":
            # L2 - withdraw the estimate from the year's cumulative sales
            calc.move_net(
                ly,
                -former_net,
                "REPORT_WITHDRAWN",
                "SalesReport withdrawn from counted set on late actual submission",
            )
            # L3 - void the ESTIMATE charge the estimate produced
            for charge in calc.charges_of_year(ly):
                if (
                    charge["sales_report_id"] == report["id"]
                    and charge["charge_type"] == "ESTIMATE"
                    and charge["billing_status"] == "ISSUED"
                ):
                    charge["billing_status"] = "VOID"
                    touch(charge)
                    calc.move_billed(
                        ly,
                        -charge["amount_cents"],
                        "ESTIMATE_VOIDED",
                        "PercentageRentCharge voided on late actual submission",
                    )
        return ok(ser_report(report))

    # ------------------------------------------------------------------ accept

    @app.post("/retail/sales-reports/<rid>/accept")
    @endpoint("LeaseAdministrator")
    def accept_report(rid):
        report = must_get("sales_reports", rid)
        ly = calc.year_of_report(report)
        if report["status"] != "SUBMITTED":
            raise ApiError("ERR_REPORT_STATE_INVALID", 409)
        calc.require_year_status(ly, ("OPEN", "RECONCILING"))

        # L1 - report enters the counted set
        report["status"] = "ACCEPTED"
        touch(report)
        # L2 - year running sales move
        calc.move_net(ly, report["net_sales_cents"], "REPORT_ACCEPTED", "SalesReport accepted")
        # L3 - percentage rent billed
        calc.bill_percentage_rent(
            ly,
            report,
            "PERIODIC",
            "PERIODIC",
            "PERIODIC_CHARGE_ISSUED",
            "CREDIT_ISSUED",
            "PercentageRentCharge issued on SalesReport acceptance",
        )
        # L4/L5 - occupancy cost ratio and watchlist posture
        calc.occupancy_cost_ratio(calc.lease_of_year(ly))
        return ok(ser_report(report))

    # ----------------------------------------------------------- estimate-bill

    @app.post("/retail/sales-reports/<rid>/estimate-bill")
    @endpoint("LeaseAdministrator")
    def estimate_bill(rid):
        report = must_get("sales_reports", rid)
        ly = calc.year_of_report(report)
        payload = body()
        expected = need_int(payload, "expected_lease_year_version")
        # step 6 - state
        if report["status"] != "PENDING":
            raise ApiError("ERR_REPORT_STATE_INVALID", 409)
        calc.require_year_status(ly, ("OPEN", "RECONCILING"))
        # step 7 - optimistic concurrency
        if expected != ly["version"]:
            raise ApiError("ERR_STALE_LEASE_YEAR_VERSION", 412)
        # step 11 - clock rule
        if not (clock_now() > report["due_at"]):
            raise ApiError("ERR_REPORT_NOT_DELINQUENT", 409)

        lease = calc.lease_of_year(ly)
        estimated_gross = calc.delinquency_estimate(ly, report)
        report["gross_sales_cents"] = estimated_gross
        report["allowed_exclusions_cents"] = 0
        report["net_sales_cents"] = estimated_gross
        report["source"] = "LANDLORD_ESTIMATE"
        report["status"] = "ESTIMATED"
        touch(report)

        calc.move_net(ly, estimated_gross, "ESTIMATE_ISSUED", "SalesReport estimate-billed")
        calc.bill_percentage_rent(
            ly,
            report,
            "ESTIMATE",
            "ESTIMATE",
            "ESTIMATE_ISSUED",
            "ESTIMATE_ISSUED",
            "PercentageRentCharge issued on estimate billing",
        )
        lease["delinquency_strikes"] += 1
        touch(lease)
        calc.occupancy_cost_ratio(lease)
        touch(ly)
        return ok(ser_report(report))

    # ----------------------------------------------------------------- dispute

    @app.post("/retail/sales-reports/<rid>/dispute")
    @endpoint("TenantUser")
    def dispute_report(rid):
        report = must_get("sales_reports", rid)
        ly = calc.year_of_report(report)
        lease = calc.lease_of_year(ly)
        require_lease_tenant(lease)
        payload = body()
        need_str(payload, "reason")
        if report["status"] != "UNDER_AUDIT":
            raise ApiError("ERR_REPORT_STATE_INVALID", 409)
        calc.require_year_status(ly, ("OPEN", "RECONCILING"))
        audit = _audit_for_report(report, ("OPEN", "FINDINGS_ISSUED"))
        if audit is None or audit["status"] != "FINDINGS_ISSUED":
            raise ApiError("ERR_AUDIT_STATE_INVALID", 409)
        if report["amendment_round"] >= calc.MAX_AMENDMENT_ROUNDS:
            raise ApiError("ERR_AMENDMENT_LIMIT_EXCEEDED", 422)
        report["status"] = "DISPUTED"
        touch(report)
        return ok(ser_report(report))

    # ------------------------------------------------------------------- amend

    @app.post("/retail/sales-reports/<rid>/amend")
    @endpoint("TenantUser")
    def amend_report(rid):
        report = must_get("sales_reports", rid)
        ly = calc.year_of_report(report)
        lease = calc.lease_of_year(ly)
        require_lease_tenant(lease)
        payload = body()
        need_str(payload, "reason")
        if report["status"] != "DISPUTED":
            raise ApiError("ERR_REPORT_STATE_INVALID", 409)
        calc.require_year_status(ly, ("OPEN", "RECONCILING"))
        if report["amendment_round"] >= calc.MAX_AMENDMENT_ROUNDS:
            raise ApiError("ERR_AMENDMENT_LIMIT_EXCEEDED", 422)

        withdrawn_net = report["net_sales_cents"]
        report["amendment_round"] += 1
        report["status"] = "AMENDED"
        touch(report)
        calc.move_net(
            ly, -withdrawn_net, "REPORT_WITHDRAWN", "SalesReport withdrawn for amendment"
        )
        for line in calc.exclusions_of_report(report):
            line["status"] = "CLAIMED"
            line["allowed_cents"] = 0
            touch(line)
        audit = _audit_for_report(report, ("FINDINGS_ISSUED",))
        if audit is not None:
            audit["status"] = "RESCINDED"
            touch(audit)
            ly["open_audit_count"] = max(0, ly["open_audit_count"] - 1)
            touch(ly)
        return ok(ser_report(report))


def _audit_for_report(report, statuses):
    matches = [
        a
        for a in find("audits", sales_report_id=report["id"])
        if a["status"] in statuses
    ]
    if matches:
        return matches[-1]
    return None
