"""Role authorization, sponsor-scoped identity, segregation of duties and authentication."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_security_payload,
    create_sponsor,
    deposit_payload,
    get_account,
    get_model_version,
    make_compliance_officer_headers,
    make_sponsor_operator_headers,
    open_account,
    setup_platform,
    submit_version,
    validate_error,
    validate_success,
)

ADMIN_HEADERS = TEST_USERS["platform_admin_headers"]


def test_sponsor_operator_is_refused_when_registering_an_instrument(api):
    """PRD §2.1: "A caller whose role is not listed there is refused with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/roles/sponsor_operator_cannot_create_securities
    """
    sponsor = create_sponsor(platform_code="NRTH", name="Northline Wealth")

    payload = create_security_payload(
        ticker="ALFA",
        name="Alfa Industrials",
        asset_class="US_EQUITY",
        last_price_cents=10000,
    )
    denied = api.create_security(
        payload, make_sponsor_operator_headers(sponsor["id"])
    )
    validate_error(denied, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    # The very same payload is accepted from the authorized role, so the refusal
    # was about the acting role and not about the body.
    allowed = api.create_security(
        create_security_payload(
            ticker="ALFA",
            name="Alfa Industrials",
            asset_class="US_EQUITY",
            last_price_cents=10000,
        ),
        ADMIN_HEADERS,
    )
    security = validate_success(allowed, 201)
    assert security["ticker"] == "ALFA"


def test_sponsor_operator_cannot_deposit_into_a_foreign_sponsors_account(api):
    """PRD §2.1: "Concretely, on a mutating endpoint a `SponsorOperator` may act only within its own sponsor: the account's `sponsor_id` for every account-scoped write, the distribution's `sponsor_id` when activating a distribution, the `sponsor_id` supplied in the body when opening an account, and the sponsor of every member order's account when assembling a block. A mismatch is refused with `ERR_SPONSOR_SCOPE_VIOLATION` (HTTP 403)."

    Design: Corner/roles/sponsor_operator_cannot_deposit_into_another_sponsors_account
    """
    env = setup_platform(
        securities=[("ALFA", "Alfa Industrials", 10000)],
        sleeves=[("ALFA", 10000)],
    )
    northline = env["sponsor"]
    southline = create_sponsor(
        platform_code="SOUT", name="Southline Advisors", revenue_share_bps=2500
    )
    account = open_account(env, "ACC-001")

    response = api.deposit_cash(
        account["id"],
        deposit_payload(500000),
        make_sponsor_operator_headers(southline["id"]),
    )
    validate_error(response, ApiErrorId.ERR_SPONSOR_SCOPE_VIOLATION.value)

    unchanged = get_account(account["id"])
    assert unchanged["cash_cents"] == 0
    assert unchanged["market_value_cents"] == 0
    assert unchanged["sponsor_id"] == northline["id"]

    foreign_sponsor = validate_success(
        api.get_sponsor(southline["id"], ADMIN_HEADERS), 200
    )
    assert foreign_sponsor["account_count"] == 0


def test_model_version_submitter_may_not_approve_their_own_submission(api):
    """PRD §2.1: "The `X-User-ID` that submitted a model version for review may never be the `X-User-ID` that approves or rejects that same version, even when the second request legitimately carries the `ComplianceOfficer` role. Such an attempt is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/roles/model_version_submitter_cannot_approve_their_own_submission
    """
    env = setup_platform(
        securities=[("ALFA", "Alfa Industrials", 10000)],
        sleeves=[("ALFA", 10000)],
        publish=False,
    )
    version_id = env["model_version"]["id"]
    submit_version(version_id, "u-7")

    self_approval = api.approve_model_version(
        version_id, make_compliance_officer_headers("u-7")
    )
    validate_error(self_approval, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    after_refusal = get_model_version(version_id)
    assert after_refusal["status"] == "PENDING_APPROVAL"
    assert after_refusal["approved_by_user_id"] is None
    assert after_refusal["submitted_by_user_id"] == "u-7"

    other_officer = api.approve_model_version(
        version_id, make_compliance_officer_headers("u-9")
    )
    approved = validate_success(other_officer, 200)
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == "u-9"
    assert approved["submitted_by_user_id"] == "u-7"


@pytest.mark.parametrize(
    "bad_headers",
    [
        {"Content-Type": "application/json"},
        {"X-User-Role": "PlatformAdmin", "Content-Type": "application/json"},
        {"X-User-ID": "pa-1", "Content-Type": "application/json"},
        {
            "X-User-ID": "",
            "X-User-Role": "PlatformAdmin",
            "Content-Type": "application/json",
        },
        {"X-User-ID": "pa-1", "X-User-Role": "", "Content-Type": "application/json"},
        {
            "X-User-ID": "pa-1",
            "X-User-Role": "Auditor",
            "Content-Type": "application/json",
        },
    ],
    ids=[
        "both_headers_omitted",
        "user_id_omitted",
        "role_omitted",
        "user_id_empty",
        "role_empty",
        "role_not_one_of_the_five",
    ],
)
def test_reads_are_refused_before_anything_else_when_authentication_fails(
    api, bad_headers
):
    """PRD §2.1: "If either header is missing, is present but empty, or if `X-User-Role` carries a string that is not one of the five roles enumerated below, the request is refused with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/roles/request_missing_auth_headers_returns_unauthenticated
    """
    sponsor = create_sponsor(platform_code="NRTH", name="Northline Wealth")

    refused = api.raw_get(f"/sma/sponsors/{sponsor['id']}", headers=bad_headers)
    validate_error(refused, ApiErrorId.ERR_UNAUTHENTICATED.value)

    # The resource exists all along: the same read with valid headers succeeds.
    allowed = validate_success(api.get_sponsor(sponsor["id"], ADMIN_HEADERS), 200)
    assert allowed["platform_code"] == "NRTH"
