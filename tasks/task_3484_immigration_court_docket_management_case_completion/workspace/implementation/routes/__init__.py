# routes package — one Flask blueprint per resource group, all mounted under
# the /eoir prefix (SCAFFOLD api_prefix).
MODULES = ("clock", "courts", "judges", "interpreters", "programs", "cases",
           "hearings", "notices", "continuances", "venue_motions",
           "reassignments", "decisions", "appeals", "motions",
           "docket_reviews")


def register_routes(app):
    from . import (clock, courts, judges, interpreters, programs, cases,
                   hearings, notices, continuances, venue_motions,
                   reassignments, decisions, appeals, motions, docket_reviews)
    for m in (clock, courts, judges, interpreters, programs, cases, hearings,
              notices, continuances, venue_motions, reassignments, decisions,
              appeals, motions, docket_reviews):
        app.register_blueprint(m.bp, url_prefix="/eoir")
