"""Entity creation defaults, computed fields, and not-found handling."""
import test_helpers as th


def test_site_create_returns_defaults_and_common_fields(api, admin_headers):
    """PRD §3.1: "A newly registered site carries `holding_status` `HELD`,
    meaning no store sits on it and it is available for development."
    PRD §2.4: "`version` is an integer starting at 1 that increments by
    exactly 1 on every mutation of the resource, including mutations driven
    by cascades originating on other entities."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."

    Design: Corner/entities/site_create_returns_defaults_and_common_fields
    """
    resp = api.create_site(
        th.create_site_payload(site_code="CS1", address="100 Corner St", acquisition_type="FEE_SIMPLE"),
        admin_headers,
    )
    body = resp.json()
    assert resp.status_code == 201
    assert body["response_type"] == "object"
    site = th.validate_success(resp, expected_status=201)
    th.assert_site(site)
    assert site["holding_status"] == "HELD"
    assert site["version"] == 1
    assert "ground_lease_expiry" not in site or site["ground_lease_expiry"] is None
    assert body["meta"]["api_request_id"].startswith("req_")
    assert th.is_iso8601_timestamp(body["meta"]["api_request_timestamp"])


def test_ground_lease_site_requires_expiry_field(api, admin_headers):
    """PRD §3.1: "For a `GROUND_LEASE` site, `ground_lease_expiry` — the expiry
    of the third-party ground lease — is required; for a `FEE_SIMPLE` site it
    is forbidden."

    Design: Corner/entities/ground_lease_site_requires_expiry_field
    """
    resp = api.create_site(
        th.create_site_payload(site_code="CS2", address="102 Corner St", acquisition_type="GROUND_LEASE"),
        admin_headers,
    )
    assert resp.status_code == 400


def test_operator_defaults_null_capacity_before_review(api, admin_headers):
    """PRD §3.2: "A new operator starts in `CANDIDATE` status, with
    `capacity_score` and `capacity_grade` both null until a review is
    submitted, `stores_operated_count` and `delinquency_balance_cents` at 0,
    and `escrow_balance_cents` — the reserve held against future default
    cures — at 0."
    PRD §3.2: "an operator with no submitted review at all has `max_stores` 0."

    Design: Corner/entities/operator_defaults_null_capacity_before_review
    """
    resp = api.create_operator(
        th.create_operator_payload(legal_name="Corner Op LLC", fy_net_worth_cents=50_000_000,
                                   fy_operating_income_cents=1_000_000),
        admin_headers,
    )
    op = th.validate_success(resp, expected_status=201)
    th.assert_operator(op)
    assert op["status"] == "CANDIDATE"
    assert op["capacity_score"] is None
    assert op["capacity_grade"] is None
    assert op["max_stores"] == 0
    assert op["stores_operated_count"] == 0
    assert op["delinquency_balance_cents"] == 0
    assert op["escrow_balance_cents"] == 0


def test_agreement_term_end_date_computed_from_term(api, admin_headers):
    """PRD §3.3: "The system computes `term_end_date` as `term_start_date`
    plus `term_years`, landing on the same calendar day minus one day."
    PRD §3.3: "A drafted agreement moves `DRAFT → FEE_PENDING` when a
    `FranchisorAdmin` submits it for fee invoicing."

    Design: Corner/entities/agreement_term_end_date_computed_from_term
    """
    site = th.create_site(site_code="CS3", address="103 Corner St")
    operator = th.create_strong_approved_operator(legal_name="Corner Op3 LLC")
    store = th.create_store_for(operator, site, store_code="CST3")
    resp = api.create_agreement(
        th.create_agreement_payload(store["id"], operator["id"], term_years=5, term_start_date="2026-04-01"),
        admin_headers,
    )
    agreement = th.validate_success(resp, expected_status=201)
    th.assert_agreement(agreement)
    assert agreement["term_end_date"] == "2031-03-31"
    assert agreement["status"] == "DRAFT"


def test_site_get_unknown_id_returns_not_found(api, admin_headers):
    """PRD §2.7: "When an endpoint path contains resource identifiers, the
    system validates their existence left to right, rejecting with
    `ERR_RESOURCE_NOT_FOUND` (HTTP 404) at the first identifier that does not
    resolve."

    Design: Corner/entities/site_get_unknown_id_returns_not_found
    """
    resp = api.get_site("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", admin_headers)
    th.validate_error(resp, th.ApiErrorId.ERR_RESOURCE_NOT_FOUND, expected_status=404)
