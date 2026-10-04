"""Integration partner certification gate, daily quota, and grant-scope
coverage for the metered data pull."""

from test_helpers import (
    ADMIN,
    ApiErrorId,
    certify_partner,
    create_grant,
    create_org,
    create_partner,
    data_pull_payload,
    make_partner_app_headers,
    setup_org_dealer,
    validate_error,
    validate_success,
)


def _pull(api, partner_id, org_id, scope="TELEMATICS"):
    return api.partner_data_pull(
        partner_id,
        data_pull_payload(org_id, scope),
        headers=make_partner_app_headers(partner_id),
    )


def test_partner_data_pull_before_certification_rejected(api):
    """PRD section 3.9: "the partner must be `CERTIFIED`
    (`ERR_PARTNER_NOT_CERTIFIED`, HTTP 403)" — a `REGISTERED` partner is
    refused even when a valid grant exists, and consumes no quota.

    Design: Corner/state_machines/partner_data_pull_before_certification_rejected
    """
    ctx = setup_org_dealer(api)
    partner = create_partner(api, name="AgriSight Analytics",
                             api_quota_calls_per_day=100)
    create_grant(ctx, api, grantee_type="THIRD_PARTY_APP",
                 grantee_ref_id=partner["id"], scopes=["TELEMATICS"])

    response = _pull(api, partner["id"], ctx["org"]["id"])
    validate_error(response, ApiErrorId.ERR_PARTNER_NOT_CERTIFIED)

    data = validate_success(
        api.get_integration_partner(partner["id"], headers=ADMIN), 200
    )
    assert data["calls_today"] == 0
    assert data["status"] == "REGISTERED"


def test_partner_quota_exhausted_alone_rejected(api):
    """PRD section 3.9: "the partner's `calls_today` for the current UTC date
    must still be below its `api_quota_calls_per_day` — at the quota the pull
    is rejected with `ERR_PARTNER_QUOTA_EXCEEDED`. Each successful pull
    consumes one unit" and the response reports `calls_remaining_today`.

    Design: Corner/validations/partner_quota_exhausted_alone_rejected
    """
    ctx = setup_org_dealer(api)
    partner = create_partner(api, name="TractorSync Lite",
                             api_quota_calls_per_day=1)
    certify_partner(api, partner["id"])
    create_grant(ctx, api, grantee_type="THIRD_PARTY_APP",
                 grantee_ref_id=partner["id"], scopes=["TELEMATICS"])

    data = validate_success(_pull(api, partner["id"], ctx["org"]["id"]), 200)
    assert data["calls_remaining_today"] == 0

    response = _pull(api, partner["id"], ctx["org"]["id"])
    validate_error(response, ApiErrorId.ERR_PARTNER_QUOTA_EXCEEDED)

    data = validate_success(
        api.get_integration_partner(partner["id"], headers=ADMIN), 200
    )
    assert data["calls_today"] == 1


def test_data_pull_without_covering_grant_rejected(api):
    """PRD section 3.9: "an `ACTIVE`, in-window grant naming this partner as
    `grantee_ref_id` with `grantee_type` `THIRD_PARTY_APP` must cover the
    requested scope for the target organization
    (`ERR_DATA_SCOPE_NOT_GRANTED`, HTTP 403)" — a grant for a different scope
    does not authorize the pull.

    Design: Corner/validations/data_pull_without_covering_grant_rejected
    """
    ctx = setup_org_dealer(api)
    partner = create_partner(api, name="AgriSight Analytics",
                             api_quota_calls_per_day=100)
    certify_partner(api, partner["id"])
    create_grant(ctx, api, grantee_type="THIRD_PARTY_APP",
                 grantee_ref_id=partner["id"], scopes=["AGRONOMIC"])

    response = _pull(api, partner["id"], ctx["org"]["id"], scope="TELEMATICS")
    validate_error(response, ApiErrorId.ERR_DATA_SCOPE_NOT_GRANTED)

    data = validate_success(
        _pull(api, partner["id"], ctx["org"]["id"], scope="AGRONOMIC"), 200
    )
    assert isinstance(data["record_count"], int)
    assert data["calls_remaining_today"] == 99


def test_data_pull_scope_safety_beats_quota_fiscal(api):
    """PRD section 2.10: consent and compliance gates (step "7. **Consent and
    compliance gates** — ... grant coverage for partner data pulls
    (`ERR_DATA_SCOPE_NOT_GRANTED`, HTTP 403)") evaluate before step "11.
    **Quota and monetary gates** — a partner data pull at its daily quota is
    rejected with `ERR_PARTNER_QUOTA_EXCEEDED` (HTTP 409)". A pull that
    violates both reports the safety error.

    Design: Difficulty/priority_pair_validation_conflict/data_pull_scope_safety_beats_quota_fiscal
    """
    ctx = setup_org_dealer(api)
    partner = create_partner(api, name="AgriSight Analytics",
                             api_quota_calls_per_day=1)
    certify_partner(api, partner["id"])
    create_grant(ctx, api, grantee_type="THIRD_PARTY_APP",
                 grantee_ref_id=partner["id"], scopes=["TELEMATICS"])
    validate_success(_pull(api, partner["id"], ctx["org"]["id"]), 200)

    org2 = create_org(api, name="Cottonwood Creek Coop", region_code="US-KS")
    response = _pull(api, partner["id"], org2["id"])
    error = validate_error(response, ApiErrorId.ERR_DATA_SCOPE_NOT_GRANTED)
    assert error["error_id"] != "ERR_PARTNER_QUOTA_EXCEEDED"


def test_rejected_data_pull_consumes_no_quota(api):
    """PRD section 3.9: "Each successful pull consumes one unit:
    `calls_today` increments" — a pull rejected at the grant-coverage gate is
    not successful, so the partner's counter stays at the one successful call
    already made.

    Design: Difficulty/priority_pair_validation_conflict/data_pull_scope_safety_beats_quota_fiscal
    """
    ctx = setup_org_dealer(api)
    partner = create_partner(api, name="AgriSight Analytics",
                             api_quota_calls_per_day=1)
    certify_partner(api, partner["id"])
    create_grant(ctx, api, grantee_type="THIRD_PARTY_APP",
                 grantee_ref_id=partner["id"], scopes=["TELEMATICS"])
    validate_success(_pull(api, partner["id"], ctx["org"]["id"]), 200)

    org2 = create_org(api, name="Cottonwood Creek Coop", region_code="US-KS")
    response = _pull(api, partner["id"], org2["id"])
    validate_error(response, ApiErrorId.ERR_DATA_SCOPE_NOT_GRANTED)

    data = validate_success(
        api.get_integration_partner(partner["id"], headers=ADMIN), 200
    )
    assert data["calls_today"] == 1
