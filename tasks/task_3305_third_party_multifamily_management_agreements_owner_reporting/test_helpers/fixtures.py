"""Composite setup helpers (PRD §3 workflows).

Every fixture builds its preconditions from scratch via the public API —
each test runs against a freshly restarted server with an empty database.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as _api
from .constants import (
    DEFAULT_EFFECTIVE_DATE,
    DEFAULT_LEASE_END_DATE,
    DEFAULT_TAKEOVER_DATE,
    DEFAULT_TERM_END_DATE,
)
from .factories import (
    create_agreement_payload,
    create_budget_payload,
    create_claim_payload,
    create_onboarding_payload,
    create_owner_payload,
    create_property_payload,
    create_resident_payload,
)
from .test_users import TEST_USERS, make_acct_headers, make_owner_rep_headers

PM = TEST_USERS["pm_headers"]
ACCT = TEST_USERS["acct_headers"]
ANALYST = TEST_USERS["analyst_headers"]
RISK = TEST_USERS["risk_headers"]


def setup_owner(legal_name="Test Owner LP", distribution_day_of_month=10):
    """Tier 1: create an ACTIVE Owner. Returns the owner dict."""
    return get_success_data(
        _api.create_owner(
            create_owner_payload(
                legal_name=legal_name,
                distribution_day_of_month=distribution_day_of_month,
            ),
            PM,
        )
    )


def setup_property(owner, name="Test Property", unit_count=100):
    """Tier 1: create a Property (OPEN, UNMANAGED) under the owner."""
    return get_success_data(
        _api.create_property(
            owner["id"], create_property_payload(name=name, unit_count=unit_count), PM
        )
    )


def setup_draft_agreement(owner, prop, **agreement_overrides):
    """Tier 1: create a DRAFT ManagementAgreement for the property."""
    return get_success_data(
        _api.create_agreement(
            owner["id"],
            create_agreement_payload(property_id=prop["id"], **agreement_overrides),
            PM,
        )
    )


def setup_active_agreement(owner, prop, **agreement_overrides):
    """Tier 1: create + activate an agreement (OCC on the create-version)."""
    ag = setup_draft_agreement(owner, prop, **agreement_overrides)
    return get_success_data(
        _api.activate_agreement(
            ag["id"], {"expected_agreement_version": ag["version"]}, PM
        )
    )


def start_onboarding(prop, **overrides):
    """Start an OnboardingTransition (INTAKE); posture moves to ONBOARDING."""
    return get_success_data(
        _api.create_onboarding(
            prop["id"], create_onboarding_payload(**overrides), PM
        )
    )


def setup_resident(prop, unit_label="101", full_name="Res One", **overrides):
    """Create one Resident on the property."""
    return get_success_data(
        _api.create_resident(
            prop["id"],
            create_resident_payload(
                unit_label=unit_label, full_name=full_name, **overrides
            ),
            ACCT,
        )
    )


def drive_onboarding_to_ready(onboarding, deposits=0, prepaid=0, delinquency=0):
    """Walk INTAKE -> DATA_VERIFIED -> LEDGER_IMPORTED -> VENDOR_REVIEW -> READY.

    Requires at least one resident to already exist on the property and every
    vendor contract to be resolved (none PENDING).
    """
    get_success_data(_api.verify_resident_data(onboarding["id"], ACCT))
    get_success_data(
        _api.import_ledger(
            onboarding["id"],
            {
                "deposits_received_cents": deposits,
                "prepaid_rent_cents": prepaid,
                "delinquency_cents": delinquency,
            },
            ACCT,
        )
    )
    get_success_data(_api.begin_vendor_review(onboarding["id"], ACCT))
    return get_success_data(_api.complete_vendor_review(onboarding["id"], ACCT))


def setup_managed_property(
    legal_name="Test Owner LP",
    property_name="Test Property",
    unit_count=100,
    distribution_day_of_month=10,
    unit_label="101",
    takeover_date=DEFAULT_TAKEOVER_DATE,
    effective_date=DEFAULT_EFFECTIVE_DATE,
    term_end_date=DEFAULT_TERM_END_DATE,
    lease_end_date=DEFAULT_LEASE_END_DATE,
    **agreement_overrides,
):
    """Tier 2: Owner + Property + ACTIVE agreement + ACTIVATED onboarding.

    Returns dict with keys: owner, prop, agreement, onboarding, resident,
    owner_headers (entity-backed OwnerRep headers for the owning Owner).
    The property is MANAGED (PRD §3.3) and ready for statements, budgets,
    pricing, claims.
    """
    owner = setup_owner(
        legal_name=legal_name, distribution_day_of_month=distribution_day_of_month
    )
    prop = setup_property(owner, name=property_name, unit_count=unit_count)
    agreement = setup_active_agreement(
        owner, prop, effective_date=effective_date, term_end_date=term_end_date,
        **agreement_overrides,
    )
    ob = start_onboarding(prop, takeover_date=takeover_date)
    resident = setup_resident(
        prop, unit_label=unit_label, lease_end_date=lease_end_date
    )
    ob = drive_onboarding_to_ready(ob)
    ob = get_success_data(_api.activate_onboarding(ob["id"], PM))
    prop = get_success_data(_api.get_property(prop["id"], PM))
    return {
        "owner": owner,
        "prop": prop,
        "agreement": agreement,
        "onboarding": ob,
        "resident": resident,
        "owner_headers": make_owner_rep_headers(owner["id"]),
    }


def set_clock(to_iso8601):
    """Set the logical clock (PRD §2.4)."""
    return get_success_data(
        _api.set_clock({"to_iso8601": to_iso8601}, PM)
    )


def post_ledger_entry(prop, kind, amount_cents, accrual_month, collected_month=None,
                      resident_id=None):
    """Post a POSTED ledger entry; returns the entry dict."""
    payload = {"kind": kind, "amount_cents": amount_cents,
               "accrual_month": accrual_month}
    if collected_month is not None:
        payload["collected_month"] = collected_month
    if resident_id is not None:
        payload["resident_id"] = resident_id
    return get_success_data(_api.create_ledger_entry(prop["id"], payload, ACCT))


def open_statement(prop, period_month="2026-09", basis="CASH"):
    """Open an OPEN MonthlyStatement for the property."""
    return get_success_data(
        _api.create_statement(
            prop["id"], {"period_month": period_month, "basis": basis}, ACCT
        )
    )


def close_statement_at(statement, clock_iso):
    """Set the logical clock then close the statement. Returns CLOSED statement."""
    set_clock(clock_iso)
    return get_success_data(_api.close_statement(statement["id"], ACCT))


def create_submitted_budget(prop, acct_headers=None, **overrides):
    """Create a DRAFT budget and submit it. Returns SUBMITTED budget."""
    hdrs = acct_headers or ACCT
    b = get_success_data(
        _api.create_budget(
            create_budget_payload(property_id=prop["id"], **overrides), hdrs
        )
    )
    return get_success_data(_api.submit_budget(b["id"], hdrs))


def create_approved_budget(owner, prop, acct_headers=None, **overrides):
    """Create + submit + approve an ANNUAL budget. Returns APPROVED budget."""
    b = create_submitted_budget(prop, acct_headers=acct_headers, **overrides)
    return get_success_data(
        _api.approve_budget(b["id"], make_owner_rep_headers(owner["id"]))
    )


def create_published_pricing(prop, unit_label="U1", recommended_rent_cents=200000,
                             start="2026-10-01T00:00:00Z",
                             end="2026-11-01T00:00:00Z"):
    """Create + publish a pricing recommendation. Returns PUBLISHED row."""
    pr = get_success_data(
        _api.create_pricing(
            prop["id"],
            {
                "unit_label": unit_label,
                "recommended_rent_cents": recommended_rent_cents,
                "effective_start_date": start,
                "effective_end_date": end,
            },
            ANALYST,
        )
    )
    return get_success_data(_api.publish_pricing(pr["id"], ANALYST))


def create_claim_under_review(prop, expected_version_out=None, **overrides):
    """File a claim and move it OPEN -> UNDER_REVIEW. Returns claim dict."""
    c = get_success_data(
        _api.create_claim(prop["id"], create_claim_payload(**overrides), RISK)
    )
    return get_success_data(_api.begin_claim_review(c["id"], RISK))
