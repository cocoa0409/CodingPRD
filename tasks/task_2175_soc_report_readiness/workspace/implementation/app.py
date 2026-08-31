import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import auth
import store
import validators as v
from envelope import err, ok
from errors import ApiError, DEFAULT_MESSAGES
from routes.audit_exceptions import bp as audit_exceptions_bp
from routes.audit_samples import bp as audit_samples_bp
from routes.boundary_components import bp as boundary_components_bp
from routes.bridge_letters import bp as bridge_letters_bp
from routes.controls import bp as controls_bp
from routes.criteria_mappings import bp as criteria_mappings_bp
from routes.cuecs import bp as cuecs_bp
from routes.engagements import bp as engagements_bp
from routes.evidence_requests import bp as evidence_requests_bp
from routes.gaps import bp as gaps_bp
from routes.questionnaires import bp as questionnaires_bp
from routes.report_distributions import bp as report_distributions_bp
from routes.subservice_orgs import bp as subservice_orgs_bp
from routes.system_descriptions import bp as system_descriptions_bp
from routes.trust_criteria import bp as trust_criteria_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for bp in (
        engagements_bp,
        system_descriptions_bp,
        boundary_components_bp,
        trust_criteria_bp,
        controls_bp,
        criteria_mappings_bp,
        evidence_requests_bp,
        gaps_bp,
        audit_samples_bp,
        audit_exceptions_bp,
        subservice_orgs_bp,
        cuecs_bp,
        report_distributions_bp,
        bridge_letters_bp,
        questionnaires_bp,
    ):
        app.register_blueprint(bp)

    @app.post("/_clock/set_current_utc")
    def set_clock():
        auth.authenticate({"PlatformAdmin"})
        body = auth.body()
        target = v.req_dt(body, "to_iso8601")
        store.set_clock(target)
        return ok({"current_utc": store.now_iso()})

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return err(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 405:
            return err("ERR_METHOD_NOT_ALLOWED", DEFAULT_MESSAGES["ERR_METHOD_NOT_ALLOWED"], 405)
        if exc.code == 404:
            return err("ERR_NOT_FOUND", DEFAULT_MESSAGES["ERR_NOT_FOUND"], 404)
        if exc.code and 400 <= exc.code < 500:
            return err("ERR_VALIDATION", DEFAULT_MESSAGES["ERR_VALIDATION"], 422)
        return err("ERR_INTERNAL", DEFAULT_MESSAGES["ERR_INTERNAL"], 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return err("ERR_INTERNAL", str(exc) or DEFAULT_MESSAGES["ERR_INTERNAL"], 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
