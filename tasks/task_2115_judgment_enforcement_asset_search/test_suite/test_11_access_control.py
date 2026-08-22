"""Identity headers, role gating and resource ownership."""

from test_helpers import (
    ApiErrorId,
    create_creditor,
    create_debtor,
    create_judgment,
    draft_enforcement_action,
    create_verified_finding,
    make_asset_investigator_headers,
    make_case_manager_headers,
    make_compliance_officer_headers,
    make_creditor_headers,
    read_action,
    setup_perfected_judgment,
    validate_error,
    validate_success,
)

CM = make_case_manager_headers()
CO = make_compliance_officer_headers("co-1")
UNKNOWN_JUDGMENT_ID = "00000000-0000-4000-8000-000000000000"


# ==========================================================================
# Screening order: the role gate closes before the path identifier is resolved
# ==========================================================================
def test_an_unauthorized_role_is_turned_away_before_the_id_is_resolved(api):
    """PRD §2.8: "When several checks would fail on the same request, the response
    is determined by the **first** failing check in the following fixed order.
    This ordering is normative: a request that violates both a
    segregation-of-duties rule and a fiscal floor reports the segregation failure,
    never the floor."
    PRD §2.8: "The acting role appears in the endpoint's authorized list —
    otherwise `ERR_ROLE_NOT_PERMITTED`."
    PRD §3.9: "Renewal is a `ComplianceOfficer` privilege and takes no payload at
    all."

    Design: Difficulty/priority_pair_validation_conflict/role_not_permitted_beats_judgment_not_found
    """
    create_creditor()

    resp = api.renew_judgment(UNKNOWN_JUDGMENT_ID, CM)
    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)


def test_the_permitted_role_reaches_the_identifier_check_instead(api):
    """PRD §2.8: "Every identifier embedded in the URL path resolves to a stored
    row, validated left to right, each reported with its own code:
    `ERR_JUDGMENT_NOT_FOUND`, `ERR_DEBTOR_NOT_FOUND`, `ERR_COUNTY_FILING_NOT_FOUND`,
    `ERR_ASSET_FINDING_NOT_FOUND`, `ERR_ENFORCEMENT_ACTION_NOT_FOUND`,
    `ERR_EXEMPTION_CLAIM_NOT_FOUND`, `ERR_EXAMINATION_NOT_FOUND`,
    `ERR_SETTLEMENT_OFFER_NOT_FOUND`, `ERR_INSTALLMENT_AGREEMENT_NOT_FOUND` or
    `ERR_PAYMENT_NOT_FOUND`."
    PRD §2.8: "The acting role appears in the endpoint's authorized list —
    otherwise `ERR_ROLE_NOT_PERMITTED`."

    Design: Difficulty/priority_pair_validation_conflict/role_not_permitted_beats_judgment_not_found
    """
    create_creditor()

    validate_error(
        api.renew_judgment(UNKNOWN_JUDGMENT_ID, CM),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )
    validate_error(
        api.renew_judgment(UNKNOWN_JUDGMENT_ID, CO),
        ApiErrorId.ERR_JUDGMENT_NOT_FOUND.value,
        404,
    )


# ==========================================================================
# Corner coverage
# ==========================================================================
def test_an_asset_investigator_may_not_request_a_writ(api):
    """PRD §2.1: "Once the caller is authenticated, the service checks the role
    against the endpoint's authorized list from Section 4; a role that does not
    appear there is turned away with `ERR_ROLE_NOT_PERMITTED` and HTTP 403."
    PRD §2.1: "An `AssetInvestigator` runs skip traces and records and verifies
    asset findings, and touches no enforcement instrument."

    Design: Corner/rbac/asset_investigator_cannot_request_a_writ
    """
    ctx = setup_perfected_judgment(
        court_case_number="CV-2026-7001",
        interest_rate_bps=0,
        filing_costs_cents=0,
        filing_overrides={"fee_cents": 0},
    )
    finding = create_verified_finding(
        ctx["judgment"]["id"], "inv-1", estimated_value_cents=900_000
    )
    action = draft_enforcement_action(ctx["judgment"]["id"], finding["id"], "BANK_LEVY")

    validate_error(
        api.request_writ(action["id"], make_asset_investigator_headers("inv-2")),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )
    assert read_action(action["id"])["status"] == "DRAFT"


def test_a_creditor_may_not_read_another_creditors_judgment(api):
    """PRD §2.1: "When `X-User-Role` is `Creditor`, `X-User-ID` is the `id` of the
    acting `Creditor` row; ownership checks on any resource that references a
    `Creditor` compare the resource's foreign-key field to `X-User-ID`."
    PRD §2.1: "Concretely: a `Creditor` caller's `X-User-ID` must equal the
    governing judgment's `creditor_id`, and a `Debtor` caller's `X-User-ID` must
    equal that judgment's `debtor_id`."
    PRD §2.1: "A mismatch anywhere along that chain is `ERR_NOT_RESOURCE_OWNER`
    with HTTP 403."

    Design: Corner/rbac/creditor_cannot_read_another_creditors_judgment
    """
    creditor_a = create_creditor()
    creditor_b = create_creditor(
        name="Beacon Collections Inc", contact_email="ops@beacon.example"
    )
    debtor = create_debtor()
    judgment = create_judgment(
        creditor_a["id"], debtor["id"],
        court_case_number="CV-2026-7004",
        interest_rate_bps=0,
        filing_costs_cents=0,
    )

    validate_error(
        api.get_judgment(judgment["id"], make_creditor_headers(creditor_b["id"])),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
        403,
    )

    own = validate_success(
        api.get_judgment(judgment["id"], make_creditor_headers(creditor_a["id"]))
    )
    assert own["court_case_number"] == "CV-2026-7004"


def test_a_request_without_a_role_header_is_unauthenticated(api):
    """PRD §2.1: "Every request to the service must carry two headers:
    `X-User-ID`, identifying the caller, and `X-User-Role`, naming the capacity in
    which they act."
    PRD §2.1: "A request that omits `X-User-Role`, or supplies a value that is not
    one of those six, is rejected with `ERR_UNAUTHENTICATED` and HTTP 401."

    Design: Corner/errors/request_without_x_user_role_header_returns_unauthenticated
    """
    creditor = create_creditor()
    debtor = create_debtor()
    judgment = create_judgment(
        creditor["id"], debtor["id"],
        court_case_number="CV-2026-6002",
        interest_rate_bps=0,
        filing_costs_cents=0,
    )

    anonymous = api.get(
        f"/judgments/{judgment['id']}",
        headers={"X-User-ID": "cm-1", "Content-Type": "application/json"},
    )
    validate_error(anonymous, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    authenticated = validate_success(api.get_judgment(judgment["id"], CM))
    assert authenticated["id"] == judgment["id"]
