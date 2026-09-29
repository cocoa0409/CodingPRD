"""Test infrastructure for the Employee Perks & Discount Marketplace API.

Importing this package registers the PRD §5 error/HTTP-status map with the
framework validators, so `validate_error` can check statuses automatically.
"""
from . import assertions, constants, factories, fixtures, time_utils, types
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import (
    assert_agreement_shape, assert_append_only_record, assert_common_fields,
    assert_dispute_shape, assert_eligibility_file_shape, assert_employer_shape,
    assert_fields, assert_integral_cents, assert_iso_equals,
    assert_ledger_entry_shape, assert_ledger_nets_to_zero,
    assert_ledger_signature, assert_line_economics, assert_membership_shape,
    assert_merchant_shape, assert_negotiation_round_shape, assert_nulls,
    assert_offer_shape, assert_ordered_by, assert_pagination_meta,
    assert_placement_fee_breakdown, assert_placement_slot_shape,
    assert_redemption_shape, assert_row_suppressed, assert_row_visible,
    assert_statement_shape, assert_sweep_counts, assert_sweep_idle,
    assert_version_is, category_row, ledger_signature, ledger_total,
)
from .factories import OMIT, round_half_up_bps
from .test_users import (
    ADMIN_HEADERS, PARTNER_MANAGER_HEADERS, PARTNER_MANAGER_ID,
    PLATFORM_ADMIN_ID, TEST_USERS, headers_for_role, headers_without_identity,
    make_admin_headers, make_employee_headers, make_employer_admin_headers,
    make_merchant_headers, make_partner_manager_headers,
)
from .time_utils import (
    canonical_iso, format_iso, iso_equal, iso_seconds_between, minus_days,
    minus_hours, parse_iso, plus_days, plus_hours, plus_seconds, shift_iso,
)
from .types import (
    CATEGORIES, REGION_CODES, AgreementStatus, DecisionValue, DiscountType,
    DisputeOutcome, DisputeReason, DisputeStatus, EligibilityFileStatus,
    EmploymentStatus, FulfillmentStatus, IntegrationStatus, LedgerEntryType,
    MembershipStatus, MerchantStatus, OfferStatus, PerkCategory, PlacementTier,
    ProgramPosture, ProposerRole, RegionCode, ReleaseReason, ReviewDecision,
    SlotStatus, StatementBasis, StatementStatus, StorefrontStatus, UserRole,
    VerificationStatus, VoidReason,
)

__all__ = [
    "ApiClient", "ApiErrorId", "HTTP_STATUS_CODES", "OMIT", "api_client",
    "assertions", "constants", "factories", "fixtures", "time_utils", "types",
    "round_half_up_bps",
]
