import os

from flask import Flask

from errors import ApiError
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

import routes_sites
import routes_schools
import routes_applications
import routes_members
import routes_teams
import routes_students
import routes_hours
import routes_stipends
import routes_reports

for bp in (routes_sites.bp, routes_schools.bp, routes_applications.bp,
           routes_members.bp, routes_teams.bp, routes_students.bp,
           routes_hours.bp, routes_stipends.bp, routes_reports.bp):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(Exception)
def handle_unexpected(e):
    return error_response("ERR_INVALID_REQUEST", 500, "Internal server error")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
