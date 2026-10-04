"""Payload factories — one per creatable resource, input fields only."""

DEFAULTS = {
    "STATE_CODE": "TX",
    "TERM_YEARS": 1,
    "PRIMARY_NAME": "Ada Adams",
    # 56 years old at the 2026-09-01 clock start (>= 50 eligibility floor).
    "PRIMARY_DOB": "1970-01-15",
    "PROVIDER_NAME": "Summit Insurance Group",
    "AGREEMENT_FROM": "2026-01-01",
    "AGREEMENT_TO": "2030-12-31",
    "PERIOD_YEAR": 2026,
    "PERIOD_QUARTER": 1,
    "REPORTED_SALES": 1_000_000,
    "COMPLAINT_CATEGORY": "SERVICE",
    "COMPLAINT_SEVERITY": "LOW",
    "ENTITY_BALANCE": 100_000_000,
    "TRANSFER_AMOUNT": 1_000,
    "PUB_DATE": "2026-10-01",
    "MIN_CPM": 2000,
    "MAX_CPM": 5000,
    "ADVERTISER": "Riverboat Tours",
    "AD_CATEGORY": "TRAVEL",
    "AGREED_CPM": 3000,
    "CHAPTER_NAME": "Austin Chapter",
    "COURSE_KIND": "TAX_PREP",
    "INSTRUCTOR": "Robin Sage",
    "SESSION_START": "2026-10-10T09:00:00Z",
    "SESSION_END": "2026-10-10T11:00:00Z",
    "CAPACITY": 20,
    "CAMPAIGN_TITLE": "Protect Retirement Savings",
    "CAMPAIGN_LEVEL": "FEDERAL",
    "ISSUE_AREA": "RETIREMENT",
    "CAMPAIGN_START": "2026-09-01",
    "CAMPAIGN_END": "2026-12-31",
    "CHANNEL": "EMAIL",
}


def create_household_payload(**overrides) -> dict:
    defaults = {
        "state_code": DEFAULTS["STATE_CODE"],
        "term_years": DEFAULTS["TERM_YEARS"],
        "primary_full_name": DEFAULTS["PRIMARY_NAME"],
        "primary_date_of_birth": DEFAULTS["PRIMARY_DOB"],
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides) -> dict:
    defaults = {"legal_name": DEFAULTS["PROVIDER_NAME"]}
    defaults.update(overrides)
    return defaults


def create_license_agreement_payload(expected_provider_version, **overrides) -> dict:
    defaults = {
        "product_category": "INSURANCE_AUTO",
        "effective_from": DEFAULTS["AGREEMENT_FROM"],
        "effective_to": DEFAULTS["AGREEMENT_TO"],
        "expected_provider_version": expected_provider_version,
    }
    defaults.update(overrides)
    return defaults


def create_royalty_statement_payload(expected_agreement_version, **overrides) -> dict:
    defaults = {
        "period_year": DEFAULTS["PERIOD_YEAR"],
        "period_quarter": DEFAULTS["PERIOD_QUARTER"],
        "reported_sales_cents": DEFAULTS["REPORTED_SALES"],
        "expected_agreement_version": expected_agreement_version,
    }
    defaults.update(overrides)
    return defaults


def create_complaint_payload(member_id, license_agreement_id, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "license_agreement_id": license_agreement_id,
        "category": DEFAULTS["COMPLAINT_CATEGORY"],
        "severity": DEFAULTS["COMPLAINT_SEVERITY"],
        "description": "member complaint narrative",
    }
    defaults.update(overrides)
    return defaults


def create_legal_entity_payload(**overrides) -> dict:
    defaults = {
        "kind": "MEMBERSHIP_ORG",
        "display_name": "Membership Organization",
        "balance_cents": DEFAULTS["ENTITY_BALANCE"],
    }
    defaults.update(overrides)
    return defaults


def create_fund_transfer_payload(from_entity_id, to_entity_id, **overrides) -> dict:
    defaults = {
        "from_entity_id": from_entity_id,
        "to_entity_id": to_entity_id,
        "amount_cents": DEFAULTS["TRANSFER_AMOUNT"],
        "purpose": "program grant",
    }
    defaults.update(overrides)
    return defaults


def create_publication_payload(**overrides) -> dict:
    defaults = {
        "title": "October Issue",
        "publication_date": DEFAULTS["PUB_DATE"],
        "min_cpm_cents": DEFAULTS["MIN_CPM"],
        "max_cpm_cents": DEFAULTS["MAX_CPM"],
    }
    defaults.update(overrides)
    return defaults


def create_ad_booking_payload(**overrides) -> dict:
    defaults = {
        "advertiser_name": DEFAULTS["ADVERTISER"],
        "category": DEFAULTS["AD_CATEGORY"],
        "agreed_cpm_cents": DEFAULTS["AGREED_CPM"],
    }
    defaults.update(overrides)
    return defaults


def create_chapter_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CHAPTER_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "city": "Austin",
    }
    defaults.update(overrides)
    return defaults


def create_course_session_payload(**overrides) -> dict:
    defaults = {
        "course_kind": DEFAULTS["COURSE_KIND"],
        "instructor_name": DEFAULTS["INSTRUCTOR"],
        "start_time": DEFAULTS["SESSION_START"],
        "end_time": DEFAULTS["SESSION_END"],
        "capacity": DEFAULTS["CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_campaign_payload(sponsor_entity_id, **overrides) -> dict:
    defaults = {
        "title": DEFAULTS["CAMPAIGN_TITLE"],
        "level": DEFAULTS["CAMPAIGN_LEVEL"],
        "issue_area": DEFAULTS["ISSUE_AREA"],
        "start_date": DEFAULTS["CAMPAIGN_START"],
        "end_date": DEFAULTS["CAMPAIGN_END"],
        "sponsor_entity_id": sponsor_entity_id,
    }
    defaults.update(overrides)
    return defaults


def create_mobilization_payload(**overrides) -> dict:
    defaults = {
        "channel": DEFAULTS["CHANNEL"],
        "audience_spec": {},
    }
    defaults.update(overrides)
    return defaults
