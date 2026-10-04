"""Entry point: Flask app, error handlers, route registration."""
import os
from flask import Flask, request

from db import store, iso
from domain import (
    err, find_report, get_body, paginate, req_iso, run_timed_evaluations,
    sorted_items,
)
from errors import ApiError
from middleware import require_role
from response import success, error as error_response
from views import report_view

import routes_members
import routes_loans
import routes_transfers
import routes_qa
import routes_sor


def create_app():
    app = Flask(__name__)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(err("ERR_INVALID_REQUEST", "Resource path not found"))

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(err("ERR_INVALID_REQUEST", "Method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e)
        return error_response(err("ERR_INVALID_REQUEST", str(e)))

    app.register_blueprint(routes_members.bp, url_prefix="/registry")
    app.register_blueprint(routes_loans.bp, url_prefix="/registry")
    app.register_blueprint(routes_transfers.bp, url_prefix="/registry")
    app.register_blueprint(routes_qa.bp, url_prefix="/registry")
    app.register_blueprint(routes_sor.bp, url_prefix="/registry")

    # ---------------- logical clock ----------------
    @app.post("/registry/_clock/set_current_utc")
    def set_clock():
        body = get_body()
        require_role("RegistryAdmin")
        target = req_iso(body, "to_iso8601")
        store.clock = target
        run_timed_evaluations()
        return success({"current_utc": iso(store.clock)})

    # ---------------- annual reports (flat reads) ----------------
    @app.get("/registry/annual-reports")
    def list_annual_reports():
        require_role("RegistryAdmin", "MemberRep", "QAAuditor")
        items = sorted_items(store.reports)
        member_id = request.args.get("member_id")
        status = request.args.get("status")
        report_year = request.args.get("report_year")
        if member_id is not None:
            items = [r for r in items if r["member_id"] == member_id]
        if status is not None:
            items = [r for r in items if r["status"] == status]
        if report_year is not None:
            try:
                year = int(report_year)
            except (TypeError, ValueError):
                raise err("ERR_INVALID_REQUEST", "report_year must be an integer")
            items = [r for r in items if r["report_year"] == year]
        page, meta = paginate(items)
        return success([report_view(r) for r in page], is_list=True, pagination=meta)

    @app.get("/registry/annual-reports/<reportId>")
    def get_annual_report(reportId):
        require_role("RegistryAdmin", "MemberRep", "QAAuditor")
        return success(report_view(find_report(reportId)))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
