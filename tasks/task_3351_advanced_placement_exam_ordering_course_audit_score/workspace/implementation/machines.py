"""State-machine tables: the edges each entity admits and its terminal states."""

STATUS_FIELD = {
    "schools": "test_center_status",
    "course_audits": "status",
    "exam_orders": "status",
    "exam_registrations": "status",
    "accommodation_requests": "status",
    "alternate_exam_requests": "status",
    "exam_scores": "status",
    "readers": "calibration_status",
    "material_shipments": "status",
    "score_sends": "status",
    "irregularity_cases": "status",
}

EDGES = {
    "course_audits": {
        ("SUBMITTED", "IN_REVIEW"),
        ("IN_REVIEW", "REVISION_REQUESTED"),
        ("REVISION_REQUESTED", "SUBMITTED"),
        ("IN_REVIEW", "APPROVED"),
        ("IN_REVIEW", "REJECTED"),
        ("APPROVED", "EXPIRED"),
    },
    "exam_orders": {
        ("DRAFT", "OPEN"),
        ("OPEN", "SUBMITTED"),
        ("SUBMITTED", "MATERIALS_SHIPPED"),
        ("MATERIALS_SHIPPED", "MATERIALS_RECEIVED"),
        ("MATERIALS_RECEIVED", "DELIVERED"),
        ("MATERIALS_SHIPPED", "SUBMITTED"),
        ("DRAFT", "VOIDED"),
        ("OPEN", "VOIDED"),
        ("SUBMITTED", "VOIDED"),
    },
    "exam_registrations": {
        ("REGISTERED", "FEE_PENDING"),
        ("FEE_PENDING", "REGISTERED"),
        ("FEE_PENDING", "CONFIRMED"),
        ("REGISTERED", "CONFIRMED"),
        ("CONFIRMED", "MATERIAL_ASSIGNED"),
        ("MATERIAL_ASSIGNED", "SCORED"),
        ("SCORED", "SCORE_RELEASED"),
        ("REGISTERED", "CANCELLED"),
        ("FEE_PENDING", "CANCELLED"),
        ("CONFIRMED", "CANCELLED"),
        ("CANCELLED", "REGISTERED"),
        ("SCORE_RELEASED", "INVALIDATED"),
    },
    "accommodation_requests": {
        ("SUBMITTED", "UNDER_DOC_REVIEW"),
        ("UNDER_DOC_REVIEW", "INFO_REQUESTED"),
        ("INFO_REQUESTED", "SUBMITTED"),
        ("UNDER_DOC_REVIEW", "APPROVED"),
        ("UNDER_DOC_REVIEW", "DENIED"),
        ("APPROVED", "REVOKED"),
    },
    "exam_scores": {
        ("NOT_SCORED", "RUBRIC_PENDING"),
        ("RUBRIC_PENDING", "AGGREGATED"),
        ("AGGREGATED", "RELEASED"),
        ("RELEASED", "WITHHELD"),
        ("AGGREGATED", "WITHHELD"),
        ("AGGREGATED", "CANCELLED"),
        ("WITHHELD", "RELEASED"),
        ("CANCELLED", "AGGREGATED"),
        ("RELEASED", "INVALIDATED"),
        ("RELEASED", "CANCELLED"),
    },
    "readers": {
        ("RECRUITED", "CALIBRATING"),
        ("CALIBRATING", "CALIBRATED"),
        ("CALIBRATING", "RECRUITED"),
        ("CALIBRATED", "DEMOTED"),
        ("DEMOTED", "CALIBRATING"),
        ("CALIBRATED", "INACTIVE"),
    },
    "material_shipments": {
        ("CREATED", "DISPATCHED"),
        ("DISPATCHED", "IN_TRANSIT"),
        ("IN_TRANSIT", "RECEIVED"),
        ("IN_TRANSIT", "SEAL_BROKEN"),
        ("RECEIVED", "RETURNED"),
        ("SEAL_BROKEN", "RETURNED"),
    },
    "alternate_exam_requests": {
        ("FILED", "UNDER_REVIEW"),
        ("UNDER_REVIEW", "APPROVED"),
        ("APPROVED", "SCHEDULED"),
        ("APPROVED", "FILED"),
        ("UNDER_REVIEW", "DENIED"),
        ("FILED", "WITHDRAWN"),
    },
    "irregularity_cases": {
        ("OPEN", "INVESTIGATING"),
        ("INVESTIGATING", "DECISION_PENDING"),
        ("DECISION_PENDING", "CONFIRMED"),
        ("DECISION_PENDING", "DISMISSED"),
        ("CONFIRMED", "APPEALED"),
        ("APPEALED", "INVESTIGATING"),
    },
    "score_sends": {
        ("PENDING", "SENT"),
        ("SENT", "ACKNOWLEDGED"),
        ("PENDING", "CANCELLED"),
        ("SENT", "CANCELLED"),
        ("PENDING", "FAILED"),
    },
    "schools": {
        ("ACTIVE", "SUSPENDED"),
        ("SUSPENDED", "ACTIVE"),
        ("SUSPENDED", "RETIRED"),
    },
}

TERMINAL = {
    "course_audits": {"REJECTED", "EXPIRED"},
    "exam_orders": {"DELIVERED", "VOIDED"},
    "exam_registrations": {"CANCELLED", "INVALIDATED"},
    "accommodation_requests": {"REVOKED"},
    "exam_scores": {"RELEASED", "CANCELLED", "WITHHELD", "INVALIDATED"},
    "readers": {"INACTIVE"},
    "material_shipments": {"RECEIVED", "RETURNED", "SEAL_BROKEN"},
    "alternate_exam_requests": {"DENIED", "WITHDRAWN"},
    "irregularity_cases": {"DISMISSED"},
    "score_sends": {"ACKNOWLEDGED", "FAILED", "CANCELLED"},
    "schools": {"RETIRED"},
}

# Statuses whose transition carries the segregation-of-duties gate (rank 4).
SOD_STATUSES = {
    "course_audits": {"IN_REVIEW", "APPROVED"},
    "accommodation_requests": {"UNDER_DOC_REVIEW", "APPROVED", "REVOKED"},
    "irregularity_cases": {"CONFIRMED"},
}

SOD_FIELD = {
    "course_audits": "submitted_by_user_id",
    "accommodation_requests": "submitted_by_user_id",
    "irregularity_cases": "reporter_user_id",
}


def has_outgoing_edge(store_key, status):
    """True when the machine declares at least one edge leaving `status`."""
    return any(source == status for source, _target in EDGES[store_key])
