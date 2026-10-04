"""Flask app entry point: wiring, error handlers."""
import os
from flask import Flask, jsonify
from errors import ApiError
from response import error_body

import clock, levels, terms, instructors, sections, students, placements, enrollments
import venues, showcases, cohorts, auditions, casts, touring, scholarships, invoices


def create_app():
    app = Flask(__name__)
    for bp in (
        clock.bp, levels.bp, terms.bp, instructors.bp, sections.bp, students.bp,
        placements.bp, enrollments.bp, venues.bp, showcases.bp, cohorts.bp,
        auditions.bp, casts.bp, touring.bp, scholarships.bp, invoices.bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return jsonify(error_body(err.error_id, err.message)), err.http_status

    @app.errorhandler(404)
    def handle_404(err):
        return jsonify(error_body("ERR_NOT_FOUND", "resource not found")), 404

    @app.errorhandler(405)
    def handle_405(err):
        return jsonify(error_body("ERR_NOT_FOUND", "method not allowed")), 404

    @app.errorhandler(Exception)
    def handle_generic(err):
        import traceback
        traceback.print_exc()
        return jsonify(error_body("ERR_INVALID_REQUEST", str(err))), 400

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
