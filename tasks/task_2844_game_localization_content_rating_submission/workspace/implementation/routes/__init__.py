"""Route registration -- all 63 endpoints of PRD SS4."""


def register_routes(app):
    from routes import (
        clock,
        content_edits,
        market_plans,
        qa_passes,
        lqa_bugs,
        rating_submissions,
        string_keys,
        titles,
        translation_units,
        voice,
    )

    for module in (
        titles,
        market_plans,
        string_keys,
        translation_units,
        voice,
        qa_passes,
        lqa_bugs,
        rating_submissions,
        content_edits,
        clock,
    ):
        app.register_blueprint(module.bp)
