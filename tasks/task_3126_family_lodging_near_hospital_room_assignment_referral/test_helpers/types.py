"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class ReferralStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    DECLINED = "DECLINED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFICATION_OK = "VERIFICATION_OK"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"


class AssignmentStatus(str, Enum):
    WAITLISTED = "WAITLISTED"
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class StayStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNDER_REVIEW = "UNDER_REVIEW"
    TRANSITION_PLANNED = "TRANSITION_PLANNED"
    RELOCATION_REQUIRED = "RELOCATION_REQUIRED"
    CHECKED_OUT = "CHECKED_OUT"


class RoomStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"
    OFFLINE = "OFFLINE"


class HousePosture(str, Enum):
    OPEN = "OPEN"
    NEAR_CAPACITY = "NEAR_CAPACITY"
    FULL = "FULL"


class GuestStatus(str, Enum):
    REGISTERED = "REGISTERED"
    DEPARTED = "DEPARTED"


class ScreeningResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ContributionStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    WAIVED = "WAIVED"
    FORGIVEN = "FORGIVEN"


class CertificationStatus(str, Enum):
    UNCERTIFIED = "UNCERTIFIED"
    CERTIFIED = "CERTIFIED"
    EXPIRED = "EXPIRED"


class MealShiftStatus(str, Enum):
    OPEN = "OPEN"
    CLAIMED = "CLAIMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CareSpaceType(str, Enum):
    FAMILY_ROOM = "FAMILY_ROOM"
    MOBILE_CARE_UNIT = "MOBILE_CARE_UNIT"


class BookingStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class DonationStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PARTIALLY_DISTRIBUTED = "PARTIALLY_DISTRIBUTED"
    DEPLETED = "DEPLETED"


class AcuityLevel(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class CareType(str, Enum):
    INPATIENT = "INPATIENT"
    OUTPATIENT = "OUTPATIENT"


class HardshipTier(str, Enum):
    NONE = "NONE"
    PARTIAL = "PARTIAL"
    FULL = "FULL"


class MealType(str, Enum):
    BREAKFAST = "BREAKFAST"
    LUNCH = "LUNCH"
    DINNER = "DINNER"


class SupplyCategory(str, Enum):
    HYGIENE_KIT = "HYGIENE_KIT"
    PANTRY_STAPLE = "PANTRY_STAPLE"
    CLEANING_SUPPLY = "CLEANING_SUPPLY"
    BABY_SUPPLY = "BABY_SUPPLY"


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    HOUSE_MANAGER = "HouseManager"
    HOSPITAL_REFERRER = "HospitalReferrer"
    FAMILY_CONTACT = "FamilyContact"
    VOLUNTEER_COORDINATOR = "VolunteerCoordinator"


class Hospital(TypedDict):
    id: str
    name: str
    city: str
    created_at: str
    updated_at: str
    version: int


class House(TypedDict):
    id: str
    name: str
    city: str
    associated_hospital_id: str
    posture: str
    occupied_room_count: int
    available_room_count: int
    reserved_room_count: int
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict):
    id: str
    house_id: str
    room_number: str
    bed_count: int
    occupancy_limit: int
    status: str
    occupied: bool
    created_at: str
    updated_at: str
    version: int


class Family(TypedDict):
    id: str
    family_name: str
    primary_contact_name: str
    home_city: str
    distance_miles: float
    child_patient_name: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    family_id: str
    hospital_id: str
    treating_unit: str
    care_type: str
    acuity_level: str
    attending_clinician: str
    status: str
    created_by_user_id: str
    verified_by_user_id: Optional[str]
    verified_at: Optional[str]
    valid_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StayRequest(TypedDict):
    id: str
    family_id: str
    house_id: str
    referral_id: str
    expected_nights: int
    self_reported_acuity: str
    verification_status: str
    assignment_status: str
    provisional_score: float
    verified_score: Optional[float]
    offered_room_id: Optional[str]
    offer_expires_at: Optional[str]
    waitlisted_since: str
    superseded_by_request_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Stay(TypedDict):
    id: str
    stay_request_id: str
    family_id: str
    room_id: str
    check_in_date: str
    expected_check_out_date: str
    actual_check_out_date: Optional[str]
    status: str
    approved_extension_count: int
    pending_extension_nights: Optional[int]
    transition_plan_notes: Optional[str]
    review_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GuestRegistration(TypedDict):
    id: str
    stay_id: str
    guest_name: str
    relationship: str
    is_overnight: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class IllnessScreening(TypedDict):
    """Append-only record: carries only id + created_at, no updated_at/version."""
    id: str
    stay_id: str
    temperature_tenths_c: int
    symptom_count: int
    notes: str
    result: str
    screened_at: str
    created_at: str


class ContributionRequest(TypedDict):
    id: str
    stay_id: str
    nightly_rate_cents: int
    planned_nights: int
    hardship_tier: str
    per_night_cents: int
    requested_amount_cents: int
    settled_amount_cents: Optional[int]
    paid_cents: int
    waived_cents: int
    forgiven_cents: int
    outstanding_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VolunteerGroup(TypedDict):
    id: str
    group_name: str
    contact_email: str
    certified_until: Optional[str]
    certification_status: str
    created_at: str
    updated_at: str
    version: int


class MealShift(TypedDict):
    id: str
    house_id: str
    shift_date: str
    meal_type: str
    servings_planned: int
    status: str
    claimed_by_group_id: Optional[str]
    servings_served: Optional[int]
    food_safety_attested: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class CareSpace(TypedDict):
    id: str
    hospital_id: str
    space_name: str
    space_type: str
    capacity: int
    created_at: str
    updated_at: str
    version: int


class CareSpaceBooking(TypedDict):
    id: str
    care_space_id: str
    family_id: str
    start_at: str
    end_at: str
    party_size: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InKindDonation(TypedDict):
    id: str
    house_id: str
    donor_name: str
    supply_category: str
    quantity_received: int
    quantity_distributed: int
    status: str
    created_at: str
    updated_at: str
    version: int
