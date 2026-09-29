"""Generic list-endpoint plumbing (PRD 2.3)."""
from middleware import validate_query
from response import array_response

TIER_SET = frozenset(("OPENING_PRICE", "NBE", "PREMIUM"))
PROGRAM_STATUS_SET = frozenset(("ACTIVE", "RELAUNCH_FREEZE", "CLOSED"))
GAP_STATUS_SET = frozenset(("DRAFT", "ANALYZED", "TIER_APPROVED", "REJECTED"))
QUALIFICATION_SET = frozenset(("PROSPECT", "QUALIFIED", "CONDITIONAL", "SUSPENDED", "DISQUALIFIED"))
AUDIT_TYPE_SET = frozenset(("CAPABILITY", "ONGOING_QUALITY"))
AUDIT_RESULT_SET = frozenset(("PASS", "CONDITIONAL", "FAIL"))
AUDIT_STATUS_SET = frozenset(("SCHEDULED", "FINALIZED"))
DEV_STATUS_SET = frozenset(
    (
        "CONCEPT",
        "SOURCED",
        "BENCHMARKED",
        "PACKAGING_APPROVED",
        "SPEC_LOCKED",
        "LAUNCHED",
        "RELAUNCH_PENDING",
        "RATIONALIZED",
        "DISCONTINUED",
    )
)
POSTURE_SET = frozenset(("GREEN", "WATCH", "PROBATION", "SUSPENDED"))
COST_MODEL_STATUS_SET = frozenset(("SUBMITTED", "ACCEPTED", "REJECTED", "SUPERSEDED"))
STUDY_TYPE_SET = frozenset(("BENCH_TOP", "CONSUMER_PANEL"))
STUDY_STATUS_SET = frozenset(("DRAFT", "FINALIZED"))
VERDICT_SET = frozenset(("SUPERIOR", "PARITY", "INFERIOR"))
ARTWORK_STATUS_SET = frozenset(("DRAFT", "IN_REVIEW", "CHANGES_REQUESTED", "APPROVED", "SUPERSEDED"))
NUTRITION_STATUS_SET = frozenset(("NOT_GENERATED", "VALID", "INVALIDATED"))
CLAIM_TYPE_SET = frozenset(
    ("NUTRIENT_CONTENT", "HEALTH", "ORGANIC", "FREE_FROM", "STRUCTURE_FUNCTION")
)
CLAIM_STATUS_SET = frozenset(("PENDING", "APPROVED", "REJECTED", "RESCINDED"))
SPEC_STATUS_SET = frozenset(("DRAFT", "LOCKED", "SUPERSEDE_PENDING", "SUPERSEDED"))
RUN_TYPE_SET = frozenset(("FIRST_PRODUCTION", "ONGOING"))
RUN_STATUS_SET = frozenset(("SCHEDULED", "APPROVED", "HOLD", "COMPLETED", "CANCELLED"))
DEFECT_SET = frozenset(("FOREIGN_MATERIAL", "SPOILAGE", "PACKAGING", "LABEL", "SENSORY"))
SEVERITY_SET = frozenset(("CRITICAL", "MAJOR", "MINOR"))
CHANGE_STATUS_SET = frozenset(("SUBMITTED", "COUNTERED", "ACCEPTED", "REJECTED", "WITHDRAWN"))
ESCALATION_SET = frozenset(("T1", "T2", "T3"))
SUBSTITUTION_SCOPE_SET = frozenset(("NONE", "PACKAGING_MATERIAL", "INGREDIENT"))


def paginate(collection, filter_spec, serializer, descending=False):
    filters, limit, offset = validate_query(filter_spec)
    rows = []
    for row in collection.values():
        if all(row.get(name) == value for name, value in filters.items()):
            rows.append(row)
    rows.sort(key=lambda row: (row["created_at"], row["_seq"]), reverse=descending)
    total = len(rows)
    window = rows[offset : offset + limit]
    return array_response([serializer(row) for row in window], limit, offset, total)


def no_query():
    """Single-resource reads accept no query parameters at all."""
    validate_query({}, paginated=False)
