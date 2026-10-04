"""Domain types: entity status enums and role enum."""
from enum import Enum


class MedicalGroupStatus(str, Enum):
    FORMING = "FORMING"
    OPERATING = "OPERATING"


class MarketField(str, Enum):
    pass


class PracticeStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ONBOARDING = "ONBOARDING"
    AFFILIATED = "AFFILIATED"
    SUSPENDED = "SUSPENDED"
    DEPARTING = "DEPARTING"
    DEPARTED = "DEPARTED"


class ProviderStatus(str, Enum):
    ROSTERED = "ROSTERED"
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"


class ProviderRole(str, Enum):
    PHYSICIAN = "PHYSICIAN"
    APP = "APP"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    SUPERSEDED = "SUPERSEDED"
    TERMINATED = "TERMINATED"


class WaveStatus(str, Enum):
    PLANNED = "PLANNED"
    LOCKED = "LOCKED"
    IN_CUTOVER = "IN_CUTOVER"
    COMPLETE = "COMPLETE"


class ContractStatus(str, Enum):
    NEGOTIATION = "NEGOTIATION"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class ContractType(str, Enum):
    FEE_FOR_SERVICE = "FEE_FOR_SERVICE"
    VALUE_BASED = "VALUE_BASED"
    HYBRID = "HYBRID"


class RateStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class EnrollmentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    EFFECTIVE = "EFFECTIVE"
    TERMINATED = "TERMINATED"


class EnrollmentChannel(str, Enum):
    STANDARD = "STANDARD"
    EXPEDITED = "EXPEDITED"


class BatchStatus(str, Enum):
    POSTED = "POSTED"
    SETTLED = "SETTLED"
    ADJUSTED = "ADJUSTED"


class StatementStatus(str, Enum):
    PROVISIONAL_ISSUED = "PROVISIONAL_ISSUED"
    FINAL_ISSUED = "FINAL_ISSUED"
    AMENDED = "AMENDED"
    REISSUED = "REISSUED"


class PoolStatus(str, Enum):
    OPEN = "OPEN"
    SCORING = "SCORING"
    ALLOCATED = "ALLOCATED"
    DISTRIBUTED = "DISTRIBUTED"
    VOIDED = "VOIDED"


class AllocationStatus(str, Enum):
    ENTERED = "ENTERED"
    SCORED = "SCORED"
    INELIGIBLE = "INELIGIBLE"
    PAYABLE = "PAYABLE"
    PAID = "PAID"
    VOIDED = "VOIDED"


class DepartureCaseStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    SETTLEMENT_PENDING = "SETTLEMENT_PENDING"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"
    RESCINDED = "RESCINDED"


class VoteStatus(str, Enum):
    OPEN = "OPEN"
    PASSED = "PASSED"
    REJECTED = "REJECTED"


class MotionType(str, Enum):
    PAYER_CONTRACT_RATIFICATION = "PAYER_CONTRACT_RATIFICATION"
    FEE_SCHEDULE_ADOPTION = "FEE_SCHEDULE_ADOPTION"


class Ballot(str, Enum):
    FOR = "FOR"
    AGAINST = "AGAINST"


class UserRole(str, Enum):
    GROUP_ADMINISTRATOR = "GroupAdministrator"
    PAYER_CONTRACTING_OFFICER = "PayerContractingOfficer"
    CREDENTIALING_COORDINATOR = "CredentialingCoordinator"
    PRACTICE_EXECUTIVE = "PracticeExecutive"
    DISTRIBUTION_ACCOUNTANT = "DistributionAccountant"
    GROUP_FINANCIAL_CONTROLLER = "GroupFinancialController"
    MARKET_COMMITTEE_CHAIR = "MarketCommitteeChair"
    PHYSICIAN_BOARD_MEMBER = "PhysicianBoardMember"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
