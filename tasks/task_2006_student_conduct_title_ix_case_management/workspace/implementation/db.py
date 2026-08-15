"""In-memory data store. Fresh on every process boot (per-test-server isolation).

No seeding, no preloading: every entity is constructed via the declared API
surface. Dicts are keyed by entity id; values are plain dicts.
"""

COLLECTIONS = [
    "party_profiles",
    "cases",
    "supportive_measures",
    "no_contact_directives",
    "directive_violations",
    "investigator_assignments",
    "evidence_items",
    "evidence_packets",
    "notices",
    "advisor_appointments",
    "hearings",
    "cross_exam_questions",
    "determinations",
    "sanctions",
    "appeals",
    "informal_resolutions",
    "case_events",
    "annual_statistics",
]

db = {name: {} for name in COLLECTIONS}
