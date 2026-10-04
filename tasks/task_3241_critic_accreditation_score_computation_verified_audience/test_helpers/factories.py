"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_publication_payload(**overrides) -> dict:
    defaults = {
        "outlet_name": f"Outlet {_seq()}",
        "reach_tier": "NATIONAL",
    }
    defaults.update(overrides)
    return defaults


def create_critic_payload(publication_id, **overrides) -> dict:
    defaults = {
        "full_name": f"Critic {_seq()}",
        "publication_id": publication_id,
        "is_top_critic": False,
    }
    defaults.update(overrides)
    return defaults


def create_accreditation_review_payload(**overrides) -> dict:
    defaults = {
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_title_payload(**overrides) -> dict:
    defaults = {
        "canonical_name": f"Title {_seq()}",
        "release_year": 2026,
    }
    defaults.update(overrides)
    return defaults


def create_release_payload(**overrides) -> dict:
    defaults = {
        "cut_label": "THEATRICAL",
        "theatrical_window_start": "2026-09-01T00:00:00Z",
        "theatrical_window_end": "2026-10-01T00:00:00Z",
        "embargo_until": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_review_payload(critic_id, **overrides) -> dict:
    defaults = {
        "critic_id": critic_id,
        "body_text": f"Review body {_seq()}.",
        "self_designation": "FRESH",
    }
    defaults.update(overrides)
    return defaults


def create_audience_member_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "email": f"member{n:04d}@example.com",
        "display_name": f"Member {n}",
    }
    defaults.update(overrides)
    return defaults


def create_ticket_verification_payload(audience_member_id, **overrides) -> dict:
    defaults = {
        "audience_member_id": audience_member_id,
        "showtime_at": "2026-09-02T00:00:00Z",
        "exhibitor_code": "AMC",
    }
    defaults.update(overrides)
    return defaults


def create_audience_rating_payload(audience_member_id, **overrides) -> dict:
    defaults = {
        "audience_member_id": audience_member_id,
        "stars": 4,
    }
    defaults.update(overrides)
    return defaults
