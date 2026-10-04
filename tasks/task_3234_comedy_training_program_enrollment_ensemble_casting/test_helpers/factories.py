"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS, TERM_START, TERM_END, TERM_DROP_DEADLINE

_seq = {"n": 0}


def _uniq(prefix: str) -> str:
    _seq["n"] += 1
    return f"{prefix}-{_seq['n']}"


def create_curriculum_level_payload(**overrides) -> dict:
    defaults = {
        "code": _uniq("L"),
        "title": "Improv Level",
        "track": "IMPROV",
        "sequence_index": 0,
    }
    defaults.update(overrides)
    return defaults


def create_term_payload(**overrides) -> dict:
    defaults = {
        "name": _uniq("Term"),
        "start_utc": TERM_START,
        "end_utc": TERM_END,
        "drop_deadline_utc": TERM_DROP_DEADLINE,
    }
    defaults.update(overrides)
    return defaults


def create_instructor_payload(**overrides) -> dict:
    defaults = {
        "display_name": _uniq("Teach"),
        "home_track": "IMPROV",
        "certified_tracks": ["IMPROV", "SKETCH", "STANDUP", "CONSERVATORY"],
        "max_weekly_hours": TEST_DEFAULTS["MAX_WEEKLY_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_section_payload(term_id, level_id, instructor_id, **overrides) -> dict:
    defaults = {
        "term_id": term_id,
        "level_id": level_id,
        "instructor_id": instructor_id,
        "capacity": TEST_DEFAULTS["CAPACITY"],
        "tuition_cents": TEST_DEFAULTS["TUITION_CENTS"],
        "weekly_hours": TEST_DEFAULTS["WEEKLY_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(**overrides) -> dict:
    n = _uniq("student")
    defaults = {
        "full_name": f"Student {n}",
        "email": f"{n}@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_placement_evaluation_payload(student_id, target_level_id, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "target_level_id": target_level_id,
        "track": "IMPROV",
        "prior_institution": "UCB",
        "portfolio_score": 0,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(student_id, section_id, expected_section_version, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "section_id": section_id,
        "expected_section_version": expected_section_version,
    }
    defaults.update(overrides)
    return defaults


def create_venue_slot_payload(**overrides) -> dict:
    defaults = {
        "venue_name": "Mainstage",
        "start_utc": "2027-04-01T19:00:00Z",
        "end_utc": "2027-04-01T21:00:00Z",
        "capacity": 200,
    }
    defaults.update(overrides)
    return defaults


def create_showcase_payload(level_id, term_id, venue_slot_id, performer_enrollment_ids, **overrides) -> dict:
    defaults = {
        "level_id": level_id,
        "term_id": term_id,
        "venue_slot_id": venue_slot_id,
        "performer_enrollment_ids": list(performer_enrollment_ids),
    }
    defaults.update(overrides)
    return defaults


def create_cohort_program_payload(term_id, **overrides) -> dict:
    defaults = {
        "kind": "CONSERVATORY",
        "track": "IMPROV",
        "term_id": term_id,
        "cohort_size": 2,
        "requires_audition": True,
        "min_track_level_code": "L1",
    }
    defaults.update(overrides)
    return defaults


def create_audition_payload(student_id, target_kind, rubric_scores=None, **overrides) -> dict:
    """Build an audition payload consistent with PRD §3.7: an ENSEMBLE or TOURING
    audition must name the `ensemble_cast_id` of an existing cast, so when the
    caller does not supply one a fresh cast (and venue slot) is created via the
    declared endpoints to satisfy the reference."""
    if target_kind in ("ENSEMBLE", "TOURING") and "ensemble_cast_id" not in overrides:
        from .api_client import api_client
        from .test_users import TEST_USERS
        from prd_bench_local_runner.testing import get_success_data
        slot = get_success_data(api_client.create_venue_slot(
            create_venue_slot_payload(), TEST_USERS["program_director_headers"]))
        cast = get_success_data(api_client.create_ensemble_cast(
            create_ensemble_cast_payload(slot["id"]),
            TEST_USERS["casting_director_headers"]))
        overrides["ensemble_cast_id"] = cast["id"]
    defaults = {
        "student_id": student_id,
        "target_kind": target_kind,
        "rubric_scores": rubric_scores if rubric_scores is not None else {
            "scene_work": 8, "characters": 7, "musicality": 9, "game": 6,
        },
    }
    defaults.update(overrides)
    return defaults


def create_ensemble_cast_payload(venue_slot_id, **overrides) -> dict:
    defaults = {
        "revue_title": _uniq("Revue"),
        "venue_slot_id": venue_slot_id,
        "cast_size": 1,
        "understudy_slots": 0,
        "source_policy": "OPEN_CALL",
    }
    defaults.update(overrides)
    return defaults


def create_touring_assignment_payload(ensemble_cast_id, principal_student_id,
                                      understudy_student_id, **overrides) -> dict:
    defaults = {
        "ensemble_cast_id": ensemble_cast_id,
        "principal_student_id": principal_student_id,
        "understudy_student_id": understudy_student_id,
        "tour_start_utc": "2027-06-01T00:00:00Z",
        "tour_end_utc": "2027-06-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_scholarship_payload(student_id, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "kind": "NEED_BASED",
        "amount_cents": 2000,
    }
    defaults.update(overrides)
    return defaults


def create_tuition_invoice_payload(student_id, enrollment_id, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "enrollment_id": enrollment_id,
        "base_amount_cents": TEST_DEFAULTS["TUITION_CENTS"],
    }
    defaults.update(overrides)
    return defaults
