"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

REVIEW_STATUSES = [
    "DRAFT", "WITHDRAWN", "POSTED_FOR_COMMENT", "ADMIN_REVIEW",
    "AGENDA_SET", "PANEL_REVIEW", "REFERRED", "DETERMINED",
]
DETERMINATIONS = [
    "PENDING", "APPROVED", "REFERRED_TO_JUNE_MINUTES",
    "REJECTED", "TABLED", "WITHDRAWN",
]
EVIDENCE_TIERS = ["TIER_I", "TIER_II", "TIER_III", "TIER_IV"]
MEETING_STATUSES = ["SCHEDULED", "PUBLIC_COMMENT_OPEN", "OPEN", "RECESSED", "CLOSED"]
AGENDA_STATUSES = ["UNSET", "SET", "ADDENDUM_OPEN"]


def assert_common_fields(data: dict):
    """Every top-level resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), \
        f"version must be an integer, got {data.get('version')!r}"


def assert_specialty_society(data: dict):
    assert_common_fields(data)
    assert data["name"]
    assert data["specialty_code"]
    assert isinstance(data["voting_seat_count"], int) and data["voting_seat_count"] >= 0
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert data["cea_credit_balance"] >= 0


def assert_change_applicant(data: dict):
    assert_common_fields(data)
    assert data["name"]
    assert data["applicant_type"] in [
        "PHYSICIAN", "SPECIALTY_SOCIETY", "MANUFACTURER", "PAYER", "HIT_VENDOR", "OTHER",
    ]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_code_change(data: dict):
    assert_common_fields(data)
    assert data["code"] and len(data["code"]) == 5, \
        f"code must be exactly 5 characters, got {data['code']!r}"
    assert data["change_type"] in ["ADDITION", "REVISION", "DELETION"]
    assert data["category"] in ["CATEGORY_I", "CATEGORY_II", "CATEGORY_III"]
    assert data["clinical_evidence_tier"] in EVIDENCE_TIERS
    assert data["review_status"] in REVIEW_STATUSES
    assert data["determination"] in DETERMINATIONS
    assert data["administrative_review_status"] in [
        "UNDER_ADMIN_REVIEW", "ADMIN_COMPLETE", "ADMIN_RETURNED",
    ]
    assert data["posting_state"] in ["NOT_POSTED", "POSTED", "COMMENT_OPEN"]
    assert data["cea_credits"] >= 0
    assert isinstance(data["cycles_in_process"], int) and data["cycles_in_process"] >= 0
    assert isinstance(data["held_for_full_panel"], bool)


def assert_advisory_committee_review(data: dict):
    assert_common_fields(data)
    assert data["committee_name"] in [
        "CPT_ADVISOR", "CPT_ASSISTANT", "HCPAC", "RUC_HEALTH_CARE_PROFESSIONALS",
    ]
    assert data["decision"] in ["PENDING", "RECOMMENDED", "DEEMED_NOT_RECOMMENDED"]
    assert data["review_status"] in ["OPEN", "COMPLETE"]
    assert data["yes_votes"] >= 0 and data["no_votes"] >= 0


def assert_change_credit_formula(data: dict):
    """Invariant: credits are 0 unless the determination is APPROVED."""
    if data["determination"] != "APPROVED":
        assert data["cea_credits"] == 0, (
            f"determination {data['determination']} must award 0 credits, "
            f"got {data['cea_credits']}"
        )


def assert_credited_approval(data: dict, expected_credits: float):
    """A credited change: APPROVED, holding the exact expected credit award."""
    assert data["determination"] == "APPROVED"
    assert data["cea_credits"] == expected_credits, (
        f"expected cea_credits {expected_credits}, got {data['cea_credits']}"
    )


def assert_editorial_panel_meeting(data: dict):
    assert_common_fields(data)
    assert data["meeting_code"]
    assert data["meeting_month"] in [
        "FEBRUARY", "APRIL", "JUNE", "AUGUST", "OCTOBER", "DECEMBER",
    ]
    assert data["meeting_status"] in MEETING_STATUSES
    assert data["agenda_status"] in AGENDA_STATUSES
    assert isinstance(data["quorum_present"], bool)
    assert isinstance(data["citation_mode"], bool)


def assert_meeting_quorum_invariant(data: dict):
    """quorum_present is derived; it is a boolean and never a count."""
    assert isinstance(data["quorum_present"], bool)


def assert_ballot_tallies_non_negative(data: dict):
    assert data["weighted_yes"] >= 0
    assert data["weighted_no"] >= 0
    assert data["weighted_abstain"] >= 0


def assert_public_comment(data: dict):
    assert_common_fields(data)
    assert data["commenter_type"] in [
        "SPECIALTY_SOCIETY", "PAYER", "MANUFACTURER", "HIT_VENDOR", "INDIVIDUAL",
    ]
    assert isinstance(data["citation_submitted"], bool)
    assert data["body"]


def assert_editorial_vote(data: dict):
    assert_common_fields(data)
    assert data["vote"] in ["YES", "NO", "ABSTAIN"]
    assert data["votes_carried"] >= 0


def assert_value_recommendation(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["BEING_CONVENED", "CONVENED", "RECOMMENDED", "FORWARDED"]
    assert data["recommendation_status"] in [
        "PENDING", "RECOMMENDED", "DEEMED_NOT_RECOMMENDED",
    ]
    assert data["forward_status"] in [
        "WITHHELD", "FORWARDED", "RETAINED_FOR_RECONSIDERATION",
    ]
    assert data["payability_status"] in ["NOT_PAYABLE", "PAYABLE_LOCKED"]


def assert_code_value(data: dict):
    assert_common_fields(data)
    assert data["rounding_variant"] in ["COMPONENT_ROUNDING", "AGGREGATE_ROUNDING"]
    assert data["value_status"] in ["DRAFT", "ACTIVE", "SUPERSEDED", "RETAINED"]
    assert isinstance(data["facility_payment_cents"], int)
    assert isinstance(data["nonfacility_payment_cents"], int)
    assert isinstance(data["component_round_total_cents"], int)
    assert isinstance(data["aggregate_round_total_cents"], int)


def assert_code_value_invariants(data: dict):
    """The rounding variant selects which rounded total publishes as the facility figure."""
    if data["rounding_variant"] == "AGGREGATE_ROUNDING":
        assert data["facility_payment_cents"] == data["aggregate_round_total_cents"], (
            "AGGREGATE_ROUNDING must publish aggregate_round_total_cents as "
            f"facility_payment_cents, got {data['facility_payment_cents']} vs "
            f"{data['aggregate_round_total_cents']}"
        )
    else:
        assert data["facility_payment_cents"] == data["component_round_total_cents"], (
            "COMPONENT_ROUNDING must publish component_round_total_cents as "
            f"facility_payment_cents, got {data['facility_payment_cents']} vs "
            f"{data['component_round_total_cents']}"
        )
    assert data["dollar_split_shortfall_cents"] == (
        data["nonfacility_payment_cents"] - data["component_round_total_cents"]
    )


def assert_errata_notice(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["PROPOSED", "PUBLISHED", "WITHDRAWN"]
    assert isinstance(data["corrected_facility_payment_cents"], int)
    assert isinstance(data["proration_numerator_days"], int)
    assert isinstance(data["proration_denominator_days"], int)


def assert_errata_proration_invariant(data: dict):
    assert 0 < data["proration_numerator_days"] <= data["proration_denominator_days"], (
        "numerator days must be positive and no greater than denominator days"
    )


def assert_review_erratum(data: dict):
    assert_common_fields(data)
    assert data["review_outcome"] in ["UPHELD", "REVERSED"]
    assert data["applied_status"] in ["NONE", "APPLIED", "NOT_APPLICABLE"]
    assert data["review_status"] in ["OPEN", "CLOSED"]


def assert_release_cycle(data: dict):
    assert_common_fields(data)
    assert data["cycle_status"] in ["PLANNING", "OPEN", "CLOSED", "RELEASED"]
    assert data["budget_gate_status"] in ["OPEN", "EXHAUSTED"]
    assert isinstance(data["code_set_capacity"], int)


def assert_release_cycle_pool_invariants(data: dict):
    capacity = data["code_set_capacity"]
    assert data["editorial_reserved_codes"] == int(capacity * 0.40)
    assert data["additions_pool_codes"] == min(140, int(capacity * 0.35))
    assert data["catiii_pool_codes"] == min(25, int(capacity * 0.05))
    assert data["discretionary_codes"] == (
        capacity
        - data["editorial_reserved_codes"]
        - data["additions_pool_codes"]
        - data["catiii_pool_codes"]
    )
    expected_gate = "EXHAUSTED" if data["discretionary_codes"] < 40 else "OPEN"
    assert data["budget_gate_status"] == expected_gate


def assert_licensing_agreement(data: dict):
    assert_common_fields(data)
    assert data["licensee_type"] in ["PAYER", "VENDOR", "PROVIDER", "EDUCATOR"]
    assert data["agreement_status"] in ["DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED"]
    assert data["fee_threshold_gate_status"] in ["PASS", "BELOW_MINIMUM"]


def assert_licence_gate_invariant(data: dict):
    expected = "PASS" if data["sales_unit_count"] >= 4 else "BELOW_MINIMUM"
    assert data["fee_threshold_gate_status"] == expected, (
        f"sales_unit_count {data['sales_unit_count']} must yield gate {expected}, "
        f"got {data['fee_threshold_gate_status']}"
    )


def assert_scope_invariant(data: dict):
    assert data["distribution_scope"] in ["INTERNAL_ONLY", "US_ONLY", "WORLDWIDE"]
    if data["agreement_status"] == "TERMINATED":
        assert data["distribution_scope"] == "INTERNAL_ONLY", (
            "a terminated licence is forced to INTERNAL_ONLY regardless of score"
        )


def assert_distribution_territory(data: dict):
    assert_common_fields(data)
    assert data["method"] in ["DISTRIBUTION", "SITE", "REPRINT"]
    assert data["territory_status"] in ["OPEN", "RESERVED", "WITHDRAWN"]
    assert data["distribution_channel"] in ["EDI", "PRINT_AND_ELECTRONIC", "SITE"]


def assert_territory_derivation_invariant(data: dict):
    assert data["can_license"] == (data["method"] == "SITE")
    assert data["site_exception"] == (data["method"] == "SITE")
    assert data["transaction_set_required"] == (data["distribution_channel"] == "EDI")
    if data["site_exception"]:
        assert data["activation_details"]["electronic_format_required"] is False
        assert data["activation_details"]["media_required"] is False


def assert_content_delivery_order(data: dict):
    assert_common_fields(data)
    assert data["distribution_channel"] in ["EDI", "PRINT_AND_ELECTRONIC", "SITE"]
    assert data["delivery_status"] in ["PENDING", "RESERVED", "READY", "RELEASED", "WITHDRAWN"]
    assert data["activation_mode"] in ["ELECTRONIC", "MEDIA", "SITE"]


def assert_education_activity(data: dict):
    assert_common_fields(data)
    assert data["activity_status"] in ["REGISTERED", "COMPLETED"]
    assert data["cea_credits_awarded"] <= 2.0


def assert_education_credit_invariant(data: dict):
    hours = data["clock_hours"]
    if hours <= 1:
        expected = 0.5
    else:
        expected = round(hours / 2.0, 1)
    if expected > 2.0:
        expected = 2.0
    assert data["cea_credits_awarded"] == expected, (
        f"clock_hours {hours} must award {expected}, got {data['cea_credits_awarded']}"
    )


def assert_interpretation_request(data: dict):
    assert_common_fields(data)
    assert data["response_status"] in ["PENDING", "ANSWERED"]
    assert data["entitlement_status"] in ["NOT_ENTITLED", "ENTITLED"]


def assert_entitlement_invariant(data: dict, licensee_type: str, agreement_status: str):
    """Entitlement is derived from the requesting licence class and status."""
    if agreement_status == "TERMINATED" or licensee_type == "PROVIDER":
        expected = "NOT_ENTITLED"
    elif agreement_status == "ACTIVE" or licensee_type == "EDUCATOR":
        expected = "ENTITLED"
    else:
        expected = None
    if expected is not None:
        assert data["entitlement_status"] == expected, (
            f"licence {licensee_type}/{agreement_status} must yield {expected}, "
            f"got {data['entitlement_status']}"
        )


def assert_version_bumped(before: int, after: int):
    assert after == before + 1, f"version must increment by exactly one: {before} -> {after}"