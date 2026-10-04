"""Blueprint registration."""

from routes.clock import bp as clock_bp
from routes.config import bp as config_bp
from routes.candidates import bp as candidates_bp
from routes.programs import bp as programs_bp
from routes.completions import bp as completions_bp
from routes.exam_apps import bp as exam_apps_bp
from routes.attempts import bp as attempts_bp
from routes.remedial import bp as remedial_bp
from routes.psychomotor import bp as psychomotor_bp
from routes.certifications import bp as certifications_bp
from routes.recerts import bp as recerts_bp
from routes.reentry import bp as reentry_bp
from routes.licenses import bp as licenses_bp
from routes.state_exams import bp as state_exams_bp
from routes.cases import bp as cases_bp

ALL_BLUEPRINTS = [
    clock_bp, config_bp, candidates_bp, programs_bp, completions_bp,
    exam_apps_bp, attempts_bp, remedial_bp, psychomotor_bp, certifications_bp,
    recerts_bp, reentry_bp, licenses_bp, state_exams_bp, cases_bp,
]


def register_routes(app):
    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)
