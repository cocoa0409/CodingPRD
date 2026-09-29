"""Composite setup helpers.

Every helper drives the public API only and uses the lenient validator so that a
broken preamble reports as a setup failure rather than a confusing assertion.
The harness empties the database before each test, so all state is rebuilt here.

Identity threading: FranchiseOwner, ClubManager and Member are entity-backed
roles, so every ownership-gated call below passes the owning entity's id through
make_franchise_owner_headers / make_club_manager_headers / make_member_headers.
"""

from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .constants import TEST_DEFAULTS
from .test_users import (
    TEST_USERS,
    make_club_manager_headers,
    make_compliance_auditor_headers,
    make_franchise_owner_headers,
    make_member_headers,
)

BRAND = TEST_USERS["brand_administrator_headers"]
BILLING = TEST_USERS["billing_partner_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]


# --------------------------------------------------------------------------
# Tier 1 — single-step primitives
# --------------------------------------------------------------------------


def set_clock(current_utc: str) -> dict:
    """Move the logical clock. Accepts a full UTC timestamp."""
    return get_success_data(
        api_client.set_current_utc(f.set_clock_payload(current_utc), BRAND)
    )


def set_clock_date(date_str: str) -> dict:
    """Move the logical clock to midnight UTC on the given calendar date."""
    return set_clock(f"{date_str}T00:00:00Z")


def create_franchisee(**overrides) -> dict:
    return get_success_data(
        api_client.create_franchisee(f.create_franchisee_payload(**overrides), BRAND)
    )


def create_territory(franchisee_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_territory(
            f.create_territory_payload(franchisee_id, **overrides), BRAND
        )
    )


def create_club(territory_id: str, franchisee_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_club(
            f.create_club_payload(territory_id, **overrides),
            make_franchise_owner_headers(franchisee_id),
        )
    )


def open_club(club_id: str, franchisee_id: str) -> dict:
    return get_success_data(
        api_client.open_club(club_id, {}, make_franchise_owner_headers(franchisee_id))
    )


def create_plan_template(**overrides) -> dict:
    return get_success_data(
        api_client.create_plan_template(f.create_plan_template_payload(**overrides), BRAND)
    )


def publish_plan_template(plan_template_id: str) -> dict:
    return get_success_data(api_client.publish_plan_template(plan_template_id, {}, BRAND))


def create_published_plan_template(**overrides) -> dict:
    """Create a plan template and move it to PUBLISHED so agreements may cite it."""
    template = create_plan_template(**overrides)
    return publish_plan_template(template["id"])


def create_member(club_id: str, **overrides) -> dict:
    """Register a member through the club's own manager."""
    return get_success_data(
        api_client.create_member(
            f.create_member_payload(**overrides), make_club_manager_headers(club_id)
        )
    )


def create_promotion(franchisee_id: str, plan_template_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_promotion(
            f.create_promotion_payload(franchisee_id, plan_template_id, **overrides),
            make_franchise_owner_headers(franchisee_id),
        )
    )


def review_promotion(promotion_id: str, decision: str = "APPROVE") -> dict:
    return get_success_data(
        api_client.review_promotion(
            promotion_id, f.promotion_review_payload(decision), BRAND
        )
    )


def create_approved_promotion(franchisee_id: str, plan_template_id: str, **overrides) -> dict:
    promotion = create_promotion(franchisee_id, plan_template_id, **overrides)
    return review_promotion(promotion["id"], "APPROVE")


def create_corporate_account(**overrides) -> dict:
    return get_success_data(
        api_client.create_corporate_account(
            f.create_corporate_account_payload(**overrides), BRAND
        )
    )


def fund_corporate_account(corporate_account_id: str, amount_cents: int) -> dict:
    return get_success_data(
        api_client.fund_corporate_account(
            corporate_account_id, f.fund_corporate_account_payload(amount_cents), BRAND
        )
    )


def read_club(club_id: str) -> dict:
    return get_success_data(api_client.get_club(club_id, BRAND))


def read_club_version(club_id: str) -> int:
    return read_club(club_id)["version"]


def read_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.get_agreement(agreement_id, BRAND))


def read_agreement_version(agreement_id: str) -> int:
    return read_agreement(agreement_id)["version"]


def read_franchisee(franchisee_id: str) -> dict:
    return get_success_data(api_client.get_franchisee(franchisee_id, BRAND))


def read_territory(territory_id: str) -> dict:
    return get_success_data(api_client.get_territory(territory_id, BRAND))


def read_member(member_id: str) -> dict:
    return get_success_data(api_client.get_member(member_id, BRAND))


def read_promotion(promotion_id: str) -> dict:
    return get_success_data(api_client.get_promotion(promotion_id, BRAND))


def read_plan_template(plan_template_id: str) -> dict:
    return get_success_data(api_client.get_plan_template(plan_template_id, BRAND))


def read_corporate_account(corporate_account_id: str) -> dict:
    return get_success_data(api_client.get_corporate_account(corporate_account_id, BRAND))


def read_transfer_request(transfer_request_id: str) -> dict:
    return get_success_data(api_client.get_transfer_request(transfer_request_id, BRAND))


def read_relocation_request(relocation_request_id: str) -> dict:
    return get_success_data(
        api_client.get_relocation_request(relocation_request_id, BRAND)
    )


def read_inspection(inspection_id: str) -> dict:
    return get_success_data(api_client.get_inspection(inspection_id, BRAND))


def read_usage_settlement(usage_settlement_id: str) -> dict:
    return get_success_data(api_client.get_usage_settlement(usage_settlement_id, BRAND))


def read_guest_usage_event(guest_usage_event_id: str) -> dict:
    return get_success_data(
        api_client.get_guest_usage_event(guest_usage_event_id, BRAND)
    )


def read_royalty_report(royalty_report_id: str) -> dict:
    return get_success_data(api_client.get_royalty_report(royalty_report_id, BRAND))


# --------------------------------------------------------------------------
# Tier 2 — ledger primitives
# --------------------------------------------------------------------------


def post_dues(agreement_id: str, amount_cents: int, occurred_on: str, due_on: str) -> dict:
    """Append a DUES_POSTED charge as the billing partner."""
    return get_success_data(
        api_client.create_billing_event(
            f.dues_posted_payload(agreement_id, amount_cents, occurred_on, due_on), BILLING
        )
    )


def post_payment(agreement_id: str, amount_cents: int, occurred_on: str) -> dict:
    """Append a PAYMENT_RECEIVED credit as the billing partner."""
    return get_success_data(
        api_client.create_billing_event(
            f.payment_received_payload(agreement_id, amount_cents, occurred_on), BILLING
        )
    )


def post_payment_failure(agreement_id: str, occurred_on: str) -> dict:
    """Append a zero-amount PAYMENT_FAILED marker as the billing partner."""
    return get_success_data(
        api_client.create_billing_event(
            f.payment_failed_payload(agreement_id, occurred_on), BILLING
        )
    )


def post_write_off(agreement_id: str, amount_cents: int, occurred_on: str) -> dict:
    return get_success_data(
        api_client.create_billing_event(
            f.write_off_payload(agreement_id, amount_cents, occurred_on), BILLING
        )
    )


def place_in_collections(agreement_id: str, agency_reference: str = "AGENCY-REF-0001") -> dict:
    return get_success_data(
        api_client.place_in_collections(
            agreement_id,
            f.place_in_collections_payload(agency_reference=agency_reference),
            BILLING,
        )
    )


def charge_and_pay(
    agreement_id: str,
    amount_cents: int,
    occurred_on: str = "2026-08-01",
    due_on: str = "2026-08-05",
    paid_on: str = "2026-08-02",
) -> dict:
    """Post one full period charge and settle it, which moves a PENDING agreement to
    ACTIVE on its first non-zero payment and leaves dues_status CURRENT."""
    post_dues(agreement_id, amount_cents, occurred_on, due_on)
    post_payment(agreement_id, amount_cents, paid_on)
    return read_agreement(agreement_id)


# --------------------------------------------------------------------------
# Tier 3 — agreement signing
# --------------------------------------------------------------------------


def sign_agreement(
    member_id: str,
    home_club_id: str,
    plan_template_id: str,
    signed_on: str = "2026-08-01",
    expected_club_version: Optional[int] = None,
    **overrides,
) -> dict:
    """Sign an agreement through the home club's manager, reading the club's current
    version first so the optimistic-concurrency field is fresh."""
    if expected_club_version is None:
        expected_club_version = read_club_version(home_club_id)
    payload = f.create_agreement_payload(
        member_id,
        home_club_id,
        plan_template_id,
        expected_club_version,
        signed_on,
        **overrides,
    )
    return get_success_data(
        api_client.create_agreement(payload, make_club_manager_headers(home_club_id))
    )


def sign_active_agreement(
    member_id: str,
    home_club_id: str,
    plan_template_id: str,
    signed_on: str = "2026-08-01",
    due_on: str = "2026-08-05",
    paid_on: str = "2026-08-02",
    **overrides,
) -> dict:
    """Sign an agreement and drive it to ACTIVE by paying its first full charge."""
    agreement = sign_agreement(
        member_id, home_club_id, plan_template_id, signed_on, **overrides
    )
    charge_and_pay(
        agreement["id"],
        agreement["effective_monthly_dues_cents"],
        occurred_on=signed_on,
        due_on=due_on,
        paid_on=paid_on,
    )
    return read_agreement(agreement["id"])


# --------------------------------------------------------------------------
# Tier 4 — inspection primitives
# --------------------------------------------------------------------------


def schedule_inspection(club_id: str, inspection_date: str, auditor_id: str = "auditor-1") -> dict:
    return get_success_data(
        api_client.create_inspection(
            f.create_inspection_payload(club_id, inspection_date),
            make_compliance_auditor_headers(auditor_id),
        )
    )


def score_inspection(
    inspection_id: str,
    equipment_condition_pts: int,
    cleanliness_pts: int,
    safety_pts: int,
    equipment_age_months_max: int,
    auditor_id: str = "auditor-1",
) -> dict:
    return get_success_data(
        api_client.score_inspection(
            inspection_id,
            f.score_inspection_payload(
                equipment_condition_pts,
                cleanliness_pts,
                safety_pts,
                equipment_age_months_max,
            ),
            make_compliance_auditor_headers(auditor_id),
        )
    )


def inspect_club(
    club_id: str,
    inspection_date: str,
    equipment_condition_pts: int,
    cleanliness_pts: int,
    safety_pts: int,
    equipment_age_months_max: int,
    auditor_id: str = "auditor-1",
) -> dict:
    """Schedule then score one inspection. Returns the scored inspection."""
    inspection = schedule_inspection(club_id, inspection_date, auditor_id=auditor_id)
    return score_inspection(
        inspection["id"],
        equipment_condition_pts,
        cleanliness_pts,
        safety_pts,
        equipment_age_months_max,
        auditor_id=auditor_id,
    )


def waive_remediation(
    inspection_id: str, auditor_id: str = "auditor-2", reason: str = "Replacement cardio floor already on order"
) -> dict:
    return get_success_data(
        api_client.waive_inspection_remediation(
            inspection_id,
            f.waive_remediation_payload(reason=reason),
            make_compliance_auditor_headers(auditor_id),
        )
    )


def fail_inspection_on_club(
    club_id: str, inspection_date: str = "2026-07-15", auditor_id: str = "auditor-1"
) -> dict:
    """Score a 60/60/60 inspection against a 60-month equipment floor. On a club whose
    standard refresh cycle applies this lands a score of 51, which is below the
    remediation threshold and therefore suspends the club."""
    return inspect_club(
        club_id, inspection_date, 60, 60, 60, 60, auditor_id=auditor_id
    )


# --------------------------------------------------------------------------
# Tier 5 — guest usage and settlements
# --------------------------------------------------------------------------


def record_guest_usage(
    agreement_id: str, host_club_id: str, period_month: str, visit_count: int
) -> dict:
    """Record a visit batch through the hosting club's own manager."""
    return get_success_data(
        api_client.create_guest_usage_event(
            f.create_guest_usage_event_payload(
                agreement_id, host_club_id, period_month, visit_count
            ),
            make_club_manager_headers(host_club_id),
        )
    )


def create_usage_settlement(period_month: str, home_club_id: str, host_club_id: str) -> dict:
    return get_success_data(
        api_client.create_usage_settlement(
            f.create_usage_settlement_payload(period_month, home_club_id, host_club_id),
            BRAND,
        )
    )


def post_usage_settlement(usage_settlement_id: str) -> dict:
    return get_success_data(api_client.post_usage_settlement(usage_settlement_id, {}, BRAND))


def reverse_usage_settlement(usage_settlement_id: str, reason: str = "Host club disputed the visit log") -> dict:
    return get_success_data(
        api_client.reverse_usage_settlement(
            usage_settlement_id, f.reverse_usage_settlement_payload(reason=reason), BRAND
        )
    )


# --------------------------------------------------------------------------
# Tier 6 — relocation primitives
# --------------------------------------------------------------------------


def file_relocation_request(club_id: str, franchisee_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_relocation_request(
            f.create_relocation_request_payload(club_id, **overrides),
            make_franchise_owner_headers(franchisee_id),
        )
    )


def submit_relocation_request(relocation_request_id: str, franchisee_id: str) -> dict:
    return get_success_data(
        api_client.submit_relocation_request(
            relocation_request_id, {}, make_franchise_owner_headers(franchisee_id)
        )
    )


def request_relocation_changes(relocation_request_id: str, reviewer_note: str) -> dict:
    return get_success_data(
        api_client.request_changes_relocation_request(
            relocation_request_id, f.request_changes_payload(reviewer_note=reviewer_note), BRAND
        )
    )


def withdraw_relocation_request(
    relocation_request_id: str, franchisee_id: str, reason: str = "Re-siting the proposal"
) -> dict:
    return get_success_data(
        api_client.withdraw_relocation_request(
            relocation_request_id,
            f.withdraw_relocation_payload(reason=reason),
            make_franchise_owner_headers(franchisee_id),
        )
    )


# --------------------------------------------------------------------------
# Tier 7 — composite franchise scenarios
# --------------------------------------------------------------------------


def setup_single_club_franchise(
    legal_name: str = "Harborlight Fitness LLC",
    contact_email: str = "ops@harborlightfit.example",
    royalty_rate_bps: int = 650,
    national_account_eligible: bool = False,
    center_lat: float = 34.0,
    center_lng: float = -118.0,
    protected_radius_km: float = 5.0,
    state_code: str = "CA",
    club_name: str = "Harborlight Club",
    opened_on: str = TEST_DEFAULTS["MODERN_OPENED_ON"],
    guest_fee_cents: int = TEST_DEFAULTS["GUEST_FEE_CENTS"],
    open_the_club: bool = True,
    plan_overrides: Optional[Dict] = None,
    publish_plan: bool = True,
    with_plan: bool = True,
) -> dict:
    """One franchisee, one reserved territory, one club and (optionally) one published
    plan template. Returns a dict keyed franchisee / territory / club / plan_template
    plus ready-made owner and manager headers."""
    franchisee = create_franchisee(
        legal_name=legal_name,
        contact_email=contact_email,
        royalty_rate_bps=royalty_rate_bps,
        national_account_eligible=national_account_eligible,
    )
    territory = create_territory(
        franchisee["id"],
        center_lat=center_lat,
        center_lng=center_lng,
        protected_radius_km=protected_radius_km,
        state_code=state_code,
    )
    club = create_club(
        territory["id"],
        franchisee["id"],
        name=club_name,
        opened_on=opened_on,
        guest_fee_cents=guest_fee_cents,
    )
    if open_the_club:
        club = open_club(club["id"], franchisee["id"])
    plan_template = None
    if with_plan:
        overrides = plan_overrides or {}
        plan_template = (
            create_published_plan_template(**overrides)
            if publish_plan
            else create_plan_template(**overrides)
        )
    return {
        "franchisee": franchisee,
        "territory": territory,
        "club": club,
        "plan_template": plan_template,
        "owner_headers": make_franchise_owner_headers(franchisee["id"]),
        "manager_headers": make_club_manager_headers(club["id"]),
    }


def setup_agreement_at_new_club(
    signed_on: str = "2026-08-01",
    member_overrides: Optional[Dict] = None,
    agreement_overrides: Optional[Dict] = None,
    activate: bool = False,
    **scenario_overrides,
) -> dict:
    """A single-club franchise plus one registered member and one signed agreement.
    When activate is true the first full charge is posted and paid, so the agreement
    reaches ACTIVE and the club's active_agreement_count moves."""
    scenario = setup_single_club_franchise(**scenario_overrides)
    member = create_member(scenario["club"]["id"], **(member_overrides or {}))
    agreement = sign_agreement(
        member["id"],
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
        signed_on,
        **(agreement_overrides or {}),
    )
    if activate:
        charge_and_pay(
            agreement["id"],
            agreement["effective_monthly_dues_cents"],
            occurred_on=signed_on,
        )
        agreement = read_agreement(agreement["id"])
    scenario["member"] = member
    scenario["agreement"] = agreement
    scenario["member_headers"] = make_member_headers(member["id"])
    return scenario


def setup_two_franchise_clubs(
    first: Optional[Dict] = None,
    second: Optional[Dict] = None,
    with_plan: bool = True,
    plan_overrides: Optional[Dict] = None,
) -> dict:
    """Two independent franchisees, each with one open club on a far-apart territory so
    that no protection buffer is ever breached, plus one shared published plan."""
    first_opts = {
        "legal_name": "Lakeview Fitness LLC",
        "contact_email": "ops@lakeviewfit.example",
        "club_name": "Lakeview Club",
        "center_lat": 34.0,
        "center_lng": -118.0,
    }
    first_opts.update(first or {})
    second_opts = {
        "legal_name": "Highpoint Fitness LLC",
        "contact_email": "ops@highpointfit.example",
        "club_name": "Highpoint Club",
        "center_lat": 36.0,
        "center_lng": -120.0,
    }
    second_opts.update(second or {})

    scenario_a = setup_single_club_franchise(with_plan=False, **first_opts)
    scenario_b = setup_single_club_franchise(with_plan=False, **second_opts)
    plan_template = None
    if with_plan:
        plan_template = create_published_plan_template(**(plan_overrides or {}))
    return {
        "first": scenario_a,
        "second": scenario_b,
        "plan_template": plan_template,
    }


def setup_home_and_host_clubs(
    legal_name: str = "Two Rivers Fitness LLC",
    contact_email: str = "ops@tworiversfit.example",
    home_club_name: str = "Two Rivers Home",
    host_club_name: str = "Two Rivers Host",
    home_guest_fee_cents: int = TEST_DEFAULTS["GUEST_FEE_CENTS"],
    host_guest_fee_cents: int = TEST_DEFAULTS["GUEST_FEE_CENTS"],
    host_center_lat: float = 34.3,
    host_center_lng: float = -118.3,
    plan_overrides: Optional[Dict] = None,
) -> dict:
    """One franchisee owning two open clubs on two of its own territories. A franchisee
    never encroaches on itself, so the two circles may sit as close as convenient."""
    scenario = setup_single_club_franchise(
        legal_name=legal_name,
        contact_email=contact_email,
        club_name=home_club_name,
        guest_fee_cents=home_guest_fee_cents,
        plan_overrides=plan_overrides,
    )
    franchisee = scenario["franchisee"]
    host_territory = create_territory(
        franchisee["id"],
        center_lat=host_center_lat,
        center_lng=host_center_lng,
        protected_radius_km=5.0,
        state_code="CA",
    )
    host_club = create_club(
        host_territory["id"],
        franchisee["id"],
        name=host_club_name,
        opened_on=TEST_DEFAULTS["MODERN_OPENED_ON"],
        guest_fee_cents=host_guest_fee_cents,
    )
    host_club = open_club(host_club["id"], franchisee["id"])
    scenario["host_territory"] = host_territory
    scenario["host_club"] = host_club
    scenario["home_club"] = scenario["club"]
    return scenario


def setup_guest_usage_scenario(
    period_visits: Optional[List[tuple]] = None,
    signed_on: str = "2026-08-01",
    host_guest_fee_cents: int = TEST_DEFAULTS["GUEST_FEE_CENTS"],
    **overrides,
) -> dict:
    """Home club plus host club plus one multi-club agreement plus the requested visit
    batches. period_visits is a list of (period_month, visit_count) pairs."""
    scenario = setup_home_and_host_clubs(
        host_guest_fee_cents=host_guest_fee_cents, **overrides
    )
    member = create_member(scenario["home_club"]["id"], full_name="Teodora Vlasic",
                           email="teodora.vlasic@example.com")
    agreement = sign_agreement(
        member["id"],
        scenario["home_club"]["id"],
        scenario["plan_template"]["id"],
        signed_on,
        multi_club_access=True,
    )
    events = []
    for period_month, visit_count in period_visits or []:
        events.append(
            record_guest_usage(
                agreement["id"], scenario["host_club"]["id"], period_month, visit_count
            )
        )
    scenario["member"] = member
    scenario["agreement"] = agreement
    scenario["guest_usage_events"] = events
    return scenario


# --------------------------------------------------------------------------
# Tier 8 — transfer, cancellation, royalty and allocation primitives
# --------------------------------------------------------------------------


def file_transfer_request(
    agreement_id: str,
    from_club_id: str,
    to_club_id: str,
    expected_agreement_version: Optional[int] = None,
    **overrides,
) -> dict:
    """Filed by the releasing club's manager, quoting the agreement's current version."""
    if expected_agreement_version is None:
        expected_agreement_version = read_agreement_version(agreement_id)
    return get_success_data(
        api_client.create_transfer_request(
            f.create_transfer_request_payload(
                agreement_id, from_club_id, to_club_id, expected_agreement_version, **overrides
            ),
            make_club_manager_headers(from_club_id),
        )
    )


def decide_transfer_request(
    transfer_request_id: str, to_club_id: str, decision: str = "APPROVE"
) -> dict:
    return get_success_data(
        api_client.decide_transfer_request(
            transfer_request_id,
            f.transfer_decision_payload(decision),
            make_club_manager_headers(to_club_id),
        )
    )


def complete_transfer_request(transfer_request_id: str, to_club_id: str) -> dict:
    return get_success_data(
        api_client.complete_transfer_request(
            transfer_request_id, {}, make_club_manager_headers(to_club_id)
        )
    )


def freeze_agreement(agreement_id: str, home_club_id: str) -> dict:
    return get_success_data(
        api_client.freeze_agreement(
            agreement_id, {}, make_club_manager_headers(home_club_id)
        )
    )


def unfreeze_agreement(agreement_id: str, home_club_id: str) -> dict:
    return get_success_data(
        api_client.unfreeze_agreement(
            agreement_id, {}, make_club_manager_headers(home_club_id)
        )
    )


def request_cancellation(agreement_id: str, member_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.request_cancellation(
            agreement_id,
            f.request_cancellation_payload(**overrides),
            make_member_headers(member_id),
        )
    )


def finalize_cancellation(agreement_id: str, home_club_id: str) -> dict:
    return get_success_data(
        api_client.finalize_cancellation(
            agreement_id, {}, make_club_manager_headers(home_club_id)
        )
    )


def submit_royalty_report(
    franchisee_id: str, period_month: str, reported_member_count: int
) -> dict:
    return get_success_data(
        api_client.create_royalty_report(
            f.create_royalty_report_payload(
                franchisee_id, period_month, reported_member_count
            ),
            make_franchise_owner_headers(franchisee_id),
        )
    )


def adjudicate_royalty_report(royalty_report_id: str, adjusted_royalty_cents: int, **overrides) -> dict:
    return get_success_data(
        api_client.adjudicate_royalty_report(
            royalty_report_id,
            f.adjudicate_royalty_report_payload(adjusted_royalty_cents, **overrides),
            BRAND,
        )
    )


def allocate_corporate_account(corporate_account_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.allocate_corporate_account(
            corporate_account_id, f.allocate_corporate_account_payload(**overrides), BRAND
        )
    )


def recall_corporate_allocation(corporate_account_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.recall_corporate_allocation(
            corporate_account_id, f.recall_allocation_payload(**overrides), BRAND
        )
    )


def suspend_corporate_account(corporate_account_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.suspend_corporate_account(
            corporate_account_id, f.suspend_corporate_account_payload(**overrides), BRAND
        )
    )


def reinstate_franchisee(franchisee_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.reinstate_franchisee(
            franchisee_id, f.reinstate_franchisee_payload(**overrides), BRAND
        )
    )


def close_inspection(inspection_id: str) -> dict:
    return get_success_data(api_client.close_inspection(inspection_id, {}, BRAND))


# --------------------------------------------------------------------------
# Tier 9 — standing and posture targeting
# --------------------------------------------------------------------------


def drive_franchisee_to_probation(
    club_id: str,
    dates: Optional[List[str]] = None,
    equipment_condition_pts: int = 78,
    cleanliness_pts: int = 86,
    safety_pts: int = 80,
    equipment_age_months_max: int = 54,
) -> List[dict]:
    """Score two failing inspections on the club so its franchisee's fail streak reaches
    two, which drives the compliance score below the probation threshold."""
    inspections = []
    for inspection_date in dates or ["2026-07-10", "2026-07-20"]:
        inspections.append(
            inspect_club(
                club_id,
                inspection_date,
                equipment_condition_pts,
                cleanliness_pts,
                safety_pts,
                equipment_age_months_max,
            )
        )
    return inspections
