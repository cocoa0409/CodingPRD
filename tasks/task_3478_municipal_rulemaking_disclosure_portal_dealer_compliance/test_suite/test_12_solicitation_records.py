"""Advisor solicitation oversight: the organization type gate, the
fiduciary disclosure gate, and the contingent-fee cap, including the
pinned gate ordering (PRD sections 2.5, 3.8)."""
from test_helpers import (
    ApiErrorId,
    assert_solicitation_record,
    create_advisor_org,
    create_dealer_org,
    create_issuer_org,
    make_dealer_rep_headers,
    validate_error,
    validate_success,
)


def _solicitation_payload(advisor_org_id, **overrides):
    payload = {
        "advisor_org_id": advisor_org_id,
        "municipal_entity_name": "City of Example",
        "compensation_type": "CONTINGENT",
        "compensation_cents": 100000,
        "disclosure_provided": True,
    }
    payload.update(overrides)
    return payload


def test_org_type_gate_reports_before_the_fee_cap(api):
    """PRD section 2.5 step 10 fixes the order: "Organization type gates
    (`ERR_ORG_TYPE_NOT_PERMITTED`); the single-subject requirement
    (`ERR_AMBIGUOUS_SUBJECT`); the cited rule must be `EFFECTIVE`
    (`ERR_RULE_NOT_EFFECTIVE`); the annual coverage-overlap check
    (`ERR_COVERAGE_PERIOD_OVERLAP`, HTTP 409); the fiduciary fee cap
    (`ERR_FEE_CAP_EXCEEDED`)". A solicitation naming a BROKER_DEALER
    advisor whose CONTINGENT compensation also exceeds the cap therefore
    reports the type gate. PRD section 3.8: "the firm must be a
    `MUNICIPAL_ADVISOR` (any other type is `ERR_ORG_TYPE_NOT_PERMITTED`)".

    Design: Difficulty/priority_pair_validation_conflict/solicitation_type_gate_beats_fee_cap
    """
    org = create_dealer_org(api, org_code="BD-500", name="Dealer Five")
    resp = api.create_solicitation_record(
        _solicitation_payload(org["id"], compensation_cents=99999999),
        make_dealer_rep_headers(org["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ORG_TYPE_NOT_PERMITTED)


def test_org_type_gate_reports_for_issuer_advisor_over_the_cap(api):
    """PRD section 3.8: "the firm must be a `MUNICIPAL_ADVISOR` (any other
    type is `ERR_ORG_TYPE_NOT_PERMITTED`)"; per the section 2.5 step 10
    ordering the type gate precedes "the fiduciary fee cap
    (`ERR_FEE_CAP_EXCEEDED`)". An ISSUER-typed advisor with an over-cap
    CONTINGENT amount fails the same gate.

    Design: Difficulty/priority_pair_validation_conflict/solicitation_type_gate_beats_fee_cap
    """
    org = create_issuer_org(api, org_code="IS-501", name="Issuer Soliciting")
    resp = api.create_solicitation_record(
        _solicitation_payload(org["id"], compensation_cents=5000000),
        make_dealer_rep_headers(org["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ORG_TYPE_NOT_PERMITTED)


def test_contingent_fee_cap_is_inclusive_at_the_boundary(api):
    """PRD section 3.8: "`CONTINGENT` compensation may not exceed the
    fiduciary fee cap of 25,000 dollars (2,500,000 cents), with an amount
    above the cap rejected as `ERR_FEE_CAP_EXCEEDED` (HTTP 422)" — exactly
    the cap is permitted; one cent above it is rejected.

    Design: Corner/validations/contingent_fee_cap_boundary
    """
    org = create_advisor_org(api, org_code="MA-3006", name="Advisor Cap")
    headers = make_dealer_rep_headers(org["id"])

    over = api.create_solicitation_record(
        _solicitation_payload(org["id"], compensation_cents=2500001), headers
    )
    validate_error(over, ApiErrorId.ERR_FEE_CAP_EXCEEDED)

    at_cap = api.create_solicitation_record(
        _solicitation_payload(org["id"], compensation_cents=2500000), headers
    )
    data = validate_success(at_cap, 201)
    assert_solicitation_record(data)
    assert data["compensation_cents"] == 2500000


def test_solicitation_without_disclosure_is_rejected(api):
    """PRD section 3.8: "Two fiduciary gates guard creation, checked in
    this order per §2.5: the disclosure must have been delivered —
    a record with `disclosure_provided` false is rejected with
    `ERR_DISCLOSURE_REQUIRED` (HTTP 422)".

    Design: Corner/validations/solicitation_without_disclosure_returns_disclosure_required
    """
    org = create_advisor_org(api, org_code="MA-3007", name="Advisor Disclosure")
    resp = api.create_solicitation_record(
        _solicitation_payload(
            org["id"], compensation_type="FIXED", compensation_cents=50000,
            disclosure_provided=False,
        ),
        make_dealer_rep_headers(org["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DISCLOSURE_REQUIRED)
