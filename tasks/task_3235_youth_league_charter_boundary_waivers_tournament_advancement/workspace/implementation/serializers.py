"""Entity serializers: internal record -> API JSON."""
from decimal import Decimal


def _pub(rec, fields):
    return {f: rec.get(f) for f in fields}


def league_view(r):
    return _pub(r, ["id", "league_name", "region_code", "season_year",
                    "charter_status", "total_team_count",
                    "created_at", "updated_at", "version"])


def renewal_view(r):
    return _pub(r, ["id", "league_id", "season_year", "window_classification",
                    "provisional_fee_cents", "final_fee_cents", "late_fee_paid",
                    "status", "created_at", "updated_at", "version"])


def division_view(r):
    return _pub(r, ["id", "league_id", "division_code", "min_league_age",
                    "max_league_age", "team_count", "status",
                    "created_at", "updated_at", "version"])


def player_view(r):
    v = _pub(r, ["id", "league_id", "division_id", "first_name", "last_name",
                 "birth_date", "residence_within_boundary", "school_within_boundary",
                 "games_played", "games_scheduled", "league_age",
                 "eligibility_status", "created_at", "updated_at", "version"])
    pct = r.get("participation_pct")
    v["participation_pct"] = float(pct) if pct is not None else None
    return v


def document_view(r):
    # Immutable evidence: id + created_at only, no updated_at/version
    return _pub(r, ["id", "player_id", "doc_type", "issued_date", "created_at"])


def waiver_view(r):
    return _pub(r, ["id", "league_id", "player_id", "waiver_type", "reason",
                    "valid_from", "valid_until", "target_division_id", "status",
                    "created_at", "updated_at", "version"])


def volunteer_view(r):
    return _pub(r, ["id", "league_id", "full_name", "role_title", "status",
                    "created_at", "updated_at", "version"])


def screening_view(r):
    return _pub(r, ["id", "volunteer_id", "offense_category", "valid_from",
                    "valid_through", "auto_flagged", "status",
                    "created_at", "updated_at", "version"])


def certificate_view(r):
    return _pub(r, ["id", "league_id", "carrier_name", "coverage_start",
                    "coverage_end", "status", "created_at", "updated_at", "version"])


def roster_view(r):
    return _pub(r, ["id", "league_id", "division_id", "season_year", "selections",
                    "roster_size", "status", "created_at", "updated_at", "version"])


def entry_view(r):
    return _pub(r, ["id", "league_id", "roster_id", "level", "elimination_format",
                    "losses_count", "status", "created_at", "updated_at", "version"])


def game_view(r):
    return _pub(r, ["id", "entry_id", "opponent_entry_id", "play_status",
                    "protest_status", "game_date", "our_score", "opponent_score",
                    "result", "recorded_pitch_total",
                    "created_at", "updated_at", "version"])


def appearance_view(r):
    return _pub(r, ["id", "game_id", "player_id", "pitches_thrown",
                    "official_pitches", "appearance_date", "rest_days_required",
                    "eligible_again_on", "status",
                    "created_at", "updated_at", "version"])


def protest_view(r):
    return _pub(r, ["id", "game_id", "protest_type", "target_player_id",
                    "grounds", "status", "created_at", "updated_at", "version"])
