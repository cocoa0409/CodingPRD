"""Enumerated vocabularies of the PRD, spelled exactly as the document spells them."""


class Role:
    PERMITTEE = "Permittee"
    RANGE_SPECIALIST = "RangeSpecialist"
    AUTHORIZED_OFFICER = "AuthorizedOfficer"
    APPEALS_ADJUDICATOR = "AppealsAdjudicator"
    SYSTEM_ADMIN = "SystemAdmin"


ALL_ROLES = (
    Role.PERMITTEE,
    Role.RANGE_SPECIALIST,
    Role.AUTHORIZED_OFFICER,
    Role.APPEALS_ADJUDICATOR,
    Role.SYSTEM_ADMIN,
)
OPERATIONAL_ROLES = (
    Role.PERMITTEE,
    Role.RANGE_SPECIALIST,
    Role.AUTHORIZED_OFFICER,
    Role.APPEALS_ADJUDICATOR,
)


class AllotmentStatus:
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class HealthDetermination:
    NOT_ASSESSED = "NOT_ASSESSED"
    MEETING = "MEETING"
    MEETING_WITH_PROBLEMS = "MEETING_WITH_PROBLEMS"
    NOT_MEETING = "NOT_MEETING"


class PermitteeStatus:
    IN_GOOD_STANDING = "IN_GOOD_STANDING"
    DEBT_FLAGGED = "DEBT_FLAGGED"


class BasePropertyType:
    LAND = "LAND"
    LIVESTOCK = "LIVESTOCK"


class LivestockKind:
    CATTLE = "CATTLE"
    SHEEP = "SHEEP"
    HORSES = "HORSES"


class PermitStatus:
    PENDING_REVIEW = "PENDING_REVIEW"
    ISSUED = "ISSUED"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    TRANSFERRED = "TRANSFERRED"


class AccountStatus:
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"


class SuspensionReason:
    NONPAYMENT = "NONPAYMENT"
    DECISION = "DECISION"


class AoiStatus:
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    USE_REPORTED = "USE_REPORTED"
    BILLED = "BILLED"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class RecordStatus:
    SCHEDULED = "SCHEDULED"
    ACTUAL_REPORTED = "ACTUAL_REPORTED"
    ACCEPTED = "ACCEPTED"


class NonuseReason:
    DROUGHT = "DROUGHT"
    WILDFIRE = "WILDFIRE"
    RESOURCE_CONSERVATION = "RESOURCE_CONSERVATION"
    PERSONAL_CONVENIENCE = "PERSONAL_CONVENIENCE"


class BillType:
    PRELIMINARY_USE = "PRELIMINARY_USE"
    FINAL_USE = "FINAL_USE"
    REVISED_USE = "REVISED_USE"
    UNAUTHORIZED_USE = "UNAUTHORIZED_USE"
    PROJECT_COST_SHARE = "PROJECT_COST_SHARE"
    ADJUSTMENT_DEBIT = "ADJUSTMENT_DEBIT"
    ADJUSTMENT_CREDIT = "ADJUSTMENT_CREDIT"


class BillStatus:
    ISSUED = "ISSUED"
    PAID = "PAID"
    DELINQUENT = "DELINQUENT"
    VOIDED = "VOIDED"


class MonitoringMethod:
    INDICATOR_ASSESSMENT = "INDICATOR_ASSESSMENT"
    UTILIZATION_MAPPING = "UTILIZATION_MAPPING"


class AssessmentStatus:
    DRAFT = "DRAFT"
    FIELD_REVIEW = "FIELD_REVIEW"
    FINALIZED = "FINALIZED"


class ReviewOutcome:
    CONCUR = "CONCUR"
    REMAND = "REMAND"


class StandardCode:
    UPLAND_HEALTH = "UPLAND_HEALTH"
    RIPARIAN_FUNCTION = "RIPARIAN_FUNCTION"
    WATER_QUALITY = "WATER_QUALITY"
    HABITAT = "HABITAT"


class DecisionType:
    ISSUANCE = "ISSUANCE"
    STOCKING_ADJUSTMENT = "STOCKING_ADJUSTMENT"
    SUSPENSION = "SUSPENSION"
    CANCELLATION = "CANCELLATION"


class DecisionStatus:
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    FINAL = "FINAL"
    EFFECTIVE = "EFFECTIVE"
    STAYED = "STAYED"
    VACATED = "VACATED"


class NepaLevel:
    CX = "CX"
    EA = "EA"
    EIS = "EIS"


class NepaStatus:
    PENDING = "PENDING"
    COMPLETE = "COMPLETE"


class AppealStatus:
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REMANDED = "REMANDED"
    AFFIRMED = "AFFIRMED"
    REVERSED = "REVERSED"
    DISMISSED = "DISMISSED"


class AppealOutcome:
    AFFIRM = "AFFIRM"
    REVERSE = "REVERSE"
    REMAND = "REMAND"
    DISMISS = "DISMISS"


class OrderType:
    DROUGHT_REDUCTION = "DROUGHT_REDUCTION"
    WILDFIRE_CLOSURE = "WILDFIRE_CLOSURE"
    FULL_CLOSURE = "FULL_CLOSURE"


class OrderStatus:
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"
    EXPIRED = "EXPIRED"


class Willfulness:
    NON_WILLFUL = "NON_WILLFUL"
    WILLFUL = "WILLFUL"
    REPEATED_WILLFUL = "REPEATED_WILLFUL"


class IncidentStatus:
    DETECTED = "DETECTED"
    BILLED = "BILLED"
    RESOLVED = "RESOLVED"


class ProjectType:
    FENCE = "FENCE"
    WATER_DEVELOPMENT = "WATER_DEVELOPMENT"
    SEEDING = "SEEDING"


class MaintenanceResponsibility:
    AGENCY = "AGENCY"
    PERMITTEE = "PERMITTEE"
    SHARED = "SHARED"


class ProjectStatus:
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    COST_ALLOCATED = "COST_ALLOCATED"
    TERMINATED = "TERMINATED"


COMMON_FIELDS = ("id", "created_at", "updated_at", "version")

FRACTIONAL_AUM_FIELDS = (
    "planned_aums",
    "actual_aums",
    "planned_aums_total",
    "actual_aums_total",
    "scheduled_aums",
    "unauthorized_aums",
    "billed_aums",
)

WHOLE_AUM_FIELDS = (
    "total_permitted_aums",
    "effective_capacity_aums",
    "allocated_aums",
    "open_aums",
    "permitted_aums",
    "authorized_aums",
    "authorized_aums_at_issue",
    "nonuse_aums",
    "billable_aums",
    "pasture_aum_capacity",
    "carrying_capacity_aums",
    "qualified_aums",
)

MONEY_FIELDS = (
    "outstanding_balance_cents",
    "base_amount_cents",
    "admin_fee_cents",
    "penalty_amount_cents",
    "total_amount_cents",
    "amount_paid_cents",
    "total_cost_cents",
    "permittee_share_cents",
    "allocated_share_cents",
    "fee_rate_cents_per_aum",
)
