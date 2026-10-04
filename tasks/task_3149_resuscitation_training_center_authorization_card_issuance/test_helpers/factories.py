"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "CENTER_NAME": "Lone Star Resuscitation Training Center",
    "REGION": "SOUTHWEST",
    "CENTER_EMAIL": "ops@lonestar-rtc.example",
    "SITE_NAME": "Main Lab",
    "STREET": "100 CPR Way",
    "CITY": "Austin",
    "STATE": "TX",
    "SITE_CAPACITY": 24,
    "GV_CODE": "G2025",
    "GV_TITLE": "2025 AHA Guidelines",
    "GV_PUBLISHED": "2025-10-01T00:00:00Z",
    "GV_DEADLINE": "2027-03-01T00:00:00Z",
}


def create_training_center_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["CENTER_NAME"],
        "region": DEFAULTS["REGION"],
        "contact_email": DEFAULTS["CENTER_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_site_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["SITE_NAME"],
        "street_address": DEFAULTS["STREET"],
        "city": DEFAULTS["CITY"],
        "state_code": DEFAULTS["STATE"],
        "capacity_students": DEFAULTS["SITE_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_instructor_payload(center_id, **overrides) -> dict:
    defaults = {
        "full_name": "Carl Candidate",
        "email": "carl@x.example",
        "discipline": "BLS",
        "home_training_center_id": center_id,
    }
    defaults.update(overrides)
    return defaults


def create_monitoring_payload(**overrides) -> dict:
    defaults = {
        "monitored_at": "2026-09-05T00:00:00Z",
        "course_type_observed": "BLS_PROVIDER",
        "outcome": "SATISFACTORY",
    }
    defaults.update(overrides)
    return defaults


def create_teaching_evaluation_payload(**overrides) -> dict:
    defaults = {
        "score": 5,
        "notes": "Solid performance.",
    }
    defaults.update(overrides)
    return defaults


def create_alignment_payload(instructor_id, **overrides) -> dict:
    defaults = {
        "instructor_id": instructor_id,
        "as_faculty": False,
    }
    defaults.update(overrides)
    return defaults


def create_guidelines_version_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["GV_CODE"],
        "title": DEFAULTS["GV_TITLE"],
        "published_at": DEFAULTS["GV_PUBLISHED"],
        "transition_deadline_at": DEFAULTS["GV_DEADLINE"],
    }
    defaults.update(overrides)
    return defaults


def create_course_session_payload(center_id, site_id, instructor_id,
                                  guidelines_version_id, **overrides) -> dict:
    defaults = {
        "training_center_id": center_id,
        "site_id": site_id,
        "primary_instructor_id": instructor_id,
        "guidelines_version_id": guidelines_version_id,
        "course_type": "BLS_PROVIDER",
        "delivery_format": "CLASSROOM",
        "start_at": "2026-10-10T14:00:00Z",
        "end_at": "2026-10-10T18:00:00Z",
        "capacity": 6,
        "manikin_count": 2,
        "aed_trainer_count": 1,
        "assisting_instructor_count": 0,
    }
    defaults.update(overrides)
    return defaults


def create_roster_entry_payload(**overrides) -> dict:
    defaults = {
        "student_name": "Sam Student",
        "student_email": "sam@x.example",
    }
    defaults.update(overrides)
    return defaults


def skills_checklist_items(passed: int, failed: int,
                           critical_failed: bool = False) -> list:
    """Build a checklist of `passed` + `failed` items; the critical item is the
    first one and is marked failed only when critical_failed is True."""
    items = []
    for i in range(passed):
        items.append({
            "item_code": f"P{i + 1:02d}",
            "critical": (i == 0),
            "passed": True,
        })
    for i in range(failed):
        items.append({
            "item_code": f"F{i + 1:02d}",
            "critical": (i == 0) and critical_failed and passed == 0,
            "passed": False,
        })
    if failed > 0 and passed > 0 and critical_failed:
        # Move the critical flag onto a failed item.
        items[0]["critical"] = False
        items[passed]["critical"] = True
    return items


def create_skills_evaluation_payload(**overrides) -> dict:
    defaults = {
        "items": skills_checklist_items(passed=4, failed=1),
    }
    defaults.update(overrides)
    return defaults


def create_quality_audit_payload(center_id, expected_version) -> dict:
    return {
        "target_training_center_id": center_id,
        "expected_training_center_version": expected_version,
    }


def create_audit_finding_payload(**overrides) -> dict:
    defaults = {
        "severity": "MINOR",
        "description": "Sign-in sheet gaps.",
    }
    defaults.update(overrides)
    return defaults


def create_card_verification_payload(card_code, verification_token,
                                     **overrides) -> dict:
    defaults = {
        "card_code": card_code,
        "verification_token": verification_token,
        "verifier_reference": "Mercy General Hospital HR",
    }
    defaults.update(overrides)
    return defaults
