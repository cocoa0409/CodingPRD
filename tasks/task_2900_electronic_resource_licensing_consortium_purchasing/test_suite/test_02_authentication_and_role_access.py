"""Authentication, role authorization, identity scope and path existence."""

from test_helpers import (
    MISSING_UUID,
    assert_subscription,
    blank_user_id_headers,
    commitment_payload,
    create_vendor,
    make_librarian_headers,
    make_vendor_rep_headers,
    member_payload,
    negotiation_payload,
    pledge,
    probe_payload,
    read_commitment,
    read_member,
    setup_active_subscription,
    setup_agreed_negotiation,
    setup_catalog,
    setup_endorsed_trial,
    setup_members,
    sign_payload,
    usage_report_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_unknown_member_id_returns_member_not_found(api, admin):
    """A member id that names no row answers the member not-found code.

    PRD: "Each resource type has its own not-found code:
    `ERR_MEMBER_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`,
    `ERR_TRIAL_NOT_FOUND`, `ERR_NEGOTIATION_NOT_FOUND`,
    `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
    `ERR_AUTH_CONFIG_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`,
    `ERR_USAGE_REPORT_NOT_FOUND`, `ERR_RENEWAL_DECISION_NOT_FOUND` and
    `ERR_ARCHIVAL_CHECK_NOT_FOUND` — all HTTP 404."

    Design: Corner/errors/unknown_member_id_returns_member_not_found
    """
    response = api.get_member(MISSING_UUID, admin)

    validate_error(response, "ERR_MEMBER_NOT_FOUND", 404)
    assert response.json()["response_type"] == "error"


def test_unknown_vendor_id_returns_vendor_not_found(api, admin):
    """A vendor id that names no row answers the vendor not-found code.

    PRD: "Each resource type has its own not-found code:
    `ERR_MEMBER_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`,
    `ERR_TRIAL_NOT_FOUND`, `ERR_NEGOTIATION_NOT_FOUND`,
    `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
    `ERR_AUTH_CONFIG_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`,
    `ERR_USAGE_REPORT_NOT_FOUND`, `ERR_RENEWAL_DECISION_NOT_FOUND` and
    `ERR_ARCHIVAL_CHECK_NOT_FOUND` — all HTTP 404."

    Design: Corner/errors/unknown_vendor_id_returns_vendor_not_found
    """
    response = api.get_vendor(MISSING_UUID, admin)

    validate_error(response, "ERR_VENDOR_NOT_FOUND", 404)
    assert response.json()["response_type"] == "error"


def test_unknown_product_id_returns_product_not_found(api, admin):
    """A product id that names no row answers the product not-found code.

    PRD: "Each resource type has its own not-found code:
    `ERR_MEMBER_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`,
    `ERR_TRIAL_NOT_FOUND`, `ERR_NEGOTIATION_NOT_FOUND`,
    `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
    `ERR_AUTH_CONFIG_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`,
    `ERR_USAGE_REPORT_NOT_FOUND`, `ERR_RENEWAL_DECISION_NOT_FOUND` and
    `ERR_ARCHIVAL_CHECK_NOT_FOUND` — all HTTP 404."

    Design: Corner/errors/unknown_product_id_returns_product_not_found
    """
    response = api.get_product(MISSING_UUID, admin)

    validate_error(response, "ERR_PRODUCT_NOT_FOUND", 404)
    assert response.json()["response_type"] == "error"


def test_unknown_negotiation_id_returns_negotiation_not_found(api, admin):
    """A negotiation id that names no row answers the negotiation not-found code.

    PRD: "Each resource type has its own not-found code:
    `ERR_MEMBER_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`,
    `ERR_TRIAL_NOT_FOUND`, `ERR_NEGOTIATION_NOT_FOUND`,
    `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
    `ERR_AUTH_CONFIG_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`,
    `ERR_USAGE_REPORT_NOT_FOUND`, `ERR_RENEWAL_DECISION_NOT_FOUND` and
    `ERR_ARCHIVAL_CHECK_NOT_FOUND` — all HTTP 404."

    Design: Corner/errors/unknown_negotiation_id_returns_negotiation_not_found
    """
    response = api.get_negotiation(MISSING_UUID, admin)

    validate_error(response, "ERR_NEGOTIATION_NOT_FOUND", 404)
    assert response.json()["response_type"] == "error"


def test_unknown_commitment_id_returns_commitment_not_found(api, admin):
    """A commitment id that names no row answers the commitment not-found code.

    PRD: "Each resource type has its own not-found code:
    `ERR_MEMBER_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`,
    `ERR_TRIAL_NOT_FOUND`, `ERR_NEGOTIATION_NOT_FOUND`,
    `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
    `ERR_AUTH_CONFIG_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`,
    `ERR_USAGE_REPORT_NOT_FOUND`, `ERR_RENEWAL_DECISION_NOT_FOUND` and
    `ERR_ARCHIVAL_CHECK_NOT_FOUND` — all HTTP 404."

    Design: Corner/errors/unknown_commitment_id_returns_commitment_not_found
    """
    response = api.get_commitment(MISSING_UUID, admin)

    validate_error(response, "ERR_COMMITMENT_NOT_FOUND", 404)
    assert response.json()["response_type"] == "error"


def test_unknown_incident_id_returns_incident_not_found(api, admin):
    """An incident id that names no row answers the incident not-found code.

    PRD: "Each resource type has its own not-found code:
    `ERR_MEMBER_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`,
    `ERR_TRIAL_NOT_FOUND`, `ERR_NEGOTIATION_NOT_FOUND`,
    `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
    `ERR_AUTH_CONFIG_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`,
    `ERR_USAGE_REPORT_NOT_FOUND`, `ERR_RENEWAL_DECISION_NOT_FOUND` and
    `ERR_ARCHIVAL_CHECK_NOT_FOUND` — all HTTP 404."

    Design: Corner/errors/unknown_incident_id_returns_incident_not_found
    """
    response = api.get_access_incident(MISSING_UUID, admin)

    validate_error(response, "ERR_INCIDENT_NOT_FOUND", 404)
    assert response.json()["response_type"] == "error"


def test_unknown_usage_report_id_returns_usage_report_not_found(api, admin):
    """A usage row id that names no row answers the usage not-found code.

    PRD: "Each resource type has its own not-found code:
    `ERR_MEMBER_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`,
    `ERR_TRIAL_NOT_FOUND`, `ERR_NEGOTIATION_NOT_FOUND`,
    `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
    `ERR_AUTH_CONFIG_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`,
    `ERR_USAGE_REPORT_NOT_FOUND`, `ERR_RENEWAL_DECISION_NOT_FOUND` and
    `ERR_ARCHIVAL_CHECK_NOT_FOUND` — all HTTP 404."

    Design: Corner/errors/unknown_usage_report_id_returns_usage_report_not_found
    """
    response = api.get_usage_report(MISSING_UUID, admin)

    validate_error(response, "ERR_USAGE_REPORT_NOT_FOUND", 404)
    assert response.json()["response_type"] == "error"


def test_unknown_auth_config_id_returns_auth_config_not_found(api, engineer):
    """Probing a binding that does not exist answers the binding not-found code.

    PRD: "Each resource type has its own not-found code:
    `ERR_MEMBER_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`,
    `ERR_TRIAL_NOT_FOUND`, `ERR_NEGOTIATION_NOT_FOUND`,
    `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
    `ERR_AUTH_CONFIG_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`,
    `ERR_USAGE_REPORT_NOT_FOUND`, `ERR_RENEWAL_DECISION_NOT_FOUND` and
    `ERR_ARCHIVAL_CHECK_NOT_FOUND` — all HTTP 404."

    Design: Corner/errors/unknown_auth_config_id_returns_auth_config_not_found
    """
    response = api.verify_auth_config(MISSING_UUID, probe_payload("PASS"), engineer)

    validate_error(response, "ERR_AUTH_CONFIG_NOT_FOUND", 404)
    assert response.json()["response_type"] == "error"


def test_unknown_renewal_decision_id_returns_renewal_decision_not_found(api, admin):
    """Executing a decision that does not exist answers the decision not-found code.

    PRD: "Each resource type has its own not-found code:
    `ERR_MEMBER_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`,
    `ERR_TRIAL_NOT_FOUND`, `ERR_NEGOTIATION_NOT_FOUND`,
    `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
    `ERR_AUTH_CONFIG_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`,
    `ERR_USAGE_REPORT_NOT_FOUND`, `ERR_RENEWAL_DECISION_NOT_FOUND` and
    `ERR_ARCHIVAL_CHECK_NOT_FOUND` — all HTTP 404."

    Design: Corner/errors/unknown_renewal_decision_id_returns_renewal_decision_not_found
    """
    response = api.execute_renewal(MISSING_UUID, admin)

    validate_error(response, "ERR_RENEWAL_DECISION_NOT_FOUND", 404)
    assert response.json()["response_type"] == "error"


def test_unknown_archival_check_id_returns_archival_check_not_found(api, admin):
    """Verifying a check that does not exist answers the check not-found code.

    PRD: "Each resource type has its own not-found code:
    `ERR_MEMBER_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`,
    `ERR_TRIAL_NOT_FOUND`, `ERR_NEGOTIATION_NOT_FOUND`,
    `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
    `ERR_AUTH_CONFIG_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`,
    `ERR_USAGE_REPORT_NOT_FOUND`, `ERR_RENEWAL_DECISION_NOT_FOUND` and
    `ERR_ARCHIVAL_CHECK_NOT_FOUND` — all HTTP 404."

    Design: Corner/errors/unknown_archival_check_id_returns_archival_check_not_found
    """
    response = api.verify_archival_check(MISSING_UUID, admin)

    validate_error(response, "ERR_ARCHIVAL_CHECK_NOT_FOUND", 404)
    assert response.json()["response_type"] == "error"


def test_member_create_with_a_blank_x_user_id_header_returns_unauthenticated(api):
    """A present-but-empty principal header is unauthenticated, not unauthorized.

    PRD: "If either header is absent, present but empty, or if `X-User-Role` does
    not name one of the five roles below, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    PRD: "Authentication is decided before anything else about the request is
    inspected — before the URL is resolved, before the body is parsed."

    Design: Corner/errors/member_create_with_a_blank_x_user_id_header_returns_unauthenticated
    """
    response = api.create_member(member_payload(), blank_user_id_headers("ConsortiumAdmin"))

    error = validate_error(response, "ERR_UNAUTHENTICATED", 401)
    assert error["error_id"] != "ERR_ROLE_NOT_PERMITTED", (
        "authentication is decided before the role gate is consulted"
    )
    assert "id" not in error, "no member library was registered"


def test_vendor_rep_creating_a_member_is_forbidden(api, vendor_rep):
    """Registering a member library is not a publisher capability.

    PRD: "The authoritative listing is the Authorized Role(s) column of the
    endpoint table in §4; a role that does not appear there for a given endpoint
    receives `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/errors/vendor_rep_creating_a_member_is_forbidden
    """
    response = api.create_member(member_payload(), vendor_rep)

    error = validate_error(response, "ERR_ROLE_NOT_PERMITTED", 403)
    assert "id" not in error, "no member library was registered"


def test_librarian_pledging_for_another_member_returns_member_scope_violation(api, admin):
    """A librarian cannot pledge on behalf of a different member library.

    PRD: "When `X-User-Role` is `MemberLibrarian`, `X-User-ID` is the `id` of the
    acting `Member`."

    PRD: "A mismatch is `ERR_MEMBER_SCOPE_VIOLATION` (HTTP 403)."

    Design: Corner/errors/librarian_pledging_for_another_member_returns_member_scope_violation
    """
    scenario = setup_catalog()
    product_id = scenario["product"]["id"]
    alpha = scenario["member"]
    bravo = setup_members([{"name": "Bravo University"}])[0]

    response = api.create_commitment(product_id, commitment_payload(bravo["id"]),
                                     make_librarian_headers(alpha["id"]))
    validate_error(response, "ERR_MEMBER_SCOPE_VIOLATION", 403)

    _, meta = validate_paginated(api.list_commitments(admin, {"product_id": product_id}))
    assert meta["total_count"] == 0, "no commitment row was created for either member"
    assert read_member(bravo["id"])["annual_committed_cents"] == 0


def test_foreign_vendor_rep_filing_usage_returns_vendor_scope_violation(api, admin):
    """A publisher may only file usage for its own packages.

    PRD: "Ownership checks compare `X-User-ID` against the `vendor_id` of the
    product behind the targeted resource: answering a negotiation round requires
    that the negotiation's product belongs to the acting vendor, filing usage
    requires that the subscription's product belongs to the acting vendor, and
    attesting an archival deposit requires the same."

    PRD: "A mismatch is `ERR_VENDOR_SCOPE_VIOLATION` (HTTP 403)."

    Design: Corner/errors/foreign_vendor_rep_filing_usage_returns_vendor_scope_violation
    """
    scenario = setup_active_subscription()
    subscription_id = scenario["subscription"]["id"]
    foreign_vendor = create_vendor(name="Meridian Press")

    response = api.create_usage_report(
        subscription_id,
        usage_report_payload(scenario["member"]["id"], "2027-01", 1200, 4000, 10),
        make_vendor_rep_headers(foreign_vendor["id"]),
    )
    validate_error(response, "ERR_VENDOR_SCOPE_VIOLATION", 403)

    _, meta = validate_paginated(
        api.list_usage_reports(admin, {"subscription_id": subscription_id})
    )
    assert meta["total_count"] == 0, "the foreign filing stored nothing"


def test_librarian_cannot_open_a_negotiation(api, admin):
    """Opening a licence negotiation is a collections-office capability.

    PRD: "The authoritative listing is the Authorized Role(s) column of the
    endpoint table in §4; a role that does not appear there for a given endpoint
    receives `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/librarian_cannot_open_a_negotiation
    """
    scenario = setup_endorsed_trial()

    response = api.create_negotiation(
        negotiation_payload(scenario["product"]["id"], scenario["trial"]["id"]),
        make_librarian_headers(scenario["member"]["id"]),
    )
    validate_error(response, "ERR_ROLE_NOT_PERMITTED", 403)

    _, meta = validate_paginated(
        api.list_negotiations(admin, {"product_id": scenario["product"]["id"]})
    )
    assert meta["total_count"] == 0


def test_negotiator_shares_the_trial_read_surface(api, negotiator):
    """A negotiator is listed for the trial listing and reads the endorsed row.

    PRD: "Once the role is recognised, the second gate is whether that role is
    listed for the endpoint being called."

    PRD: "Then, if `final_score` is greater than or equal to 70.00, the trial
    advances `CLOSED → ENDORSED`; a final score of exactly 70.00 endorses."

    Design: Corner/rbac/negotiator_shares_the_trial_read_surface
    """
    scenario = setup_endorsed_trial()

    data, meta = validate_paginated(
        api.list_trials(negotiator, {"product_id": scenario["product"]["id"],
                                     "status": "ENDORSED"})
    )

    assert meta["total_count"] == 1
    assert data[0]["id"] == scenario["trial"]["id"]
    assert data[0]["status"] == "ENDORSED"
    assert float(data[0]["final_score"]) == 90.00
    assert data[0]["feedback_count"] == 3


def test_access_engineer_cannot_sign_a_negotiation(api, admin, engineer):
    """Signing is not an access-services capability and nothing is created.

    PRD: "The authoritative listing is the Authorized Role(s) column of the
    endpoint table in §4; a role that does not appear there for a given endpoint
    receives `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/access_engineer_cannot_sign_a_negotiation
    """
    scenario = setup_agreed_negotiation()
    commitment = pledge(scenario["product"]["id"], scenario["member"]["id"])

    response = api.sign_negotiation(scenario["negotiation"]["id"], sign_payload(), engineer)
    validate_error(response, "ERR_ROLE_NOT_PERMITTED", 403)

    negotiation = validate_success(api.get_negotiation(scenario["negotiation"]["id"], admin))
    assert negotiation["status"] == "AGREED"
    assert read_commitment(commitment["id"])["status"] == "PLEDGED"
    _, meta = validate_paginated(api.list_subscriptions(admin))
    assert meta["total_count"] == 0, "the refused signature created no subscription"


def test_librarian_cannot_list_negotiations(api):
    """The negotiation listing is closed to member librarians.

    PRD: "The authoritative listing is the Authorized Role(s) column of the
    endpoint table in §4; a role that does not appear there for a given endpoint
    receives `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/librarian_cannot_list_negotiations
    """
    scenario = setup_endorsed_trial()

    response = api.list_negotiations(make_librarian_headers(scenario["member"]["id"]),
                                     {"product_id": scenario["product"]["id"]})

    validate_error(response, "ERR_ROLE_NOT_PERMITTED", 403)


def test_submitting_and_signing_split_across_two_users_succeeds(api, admin):
    """Two distinct operators clear the countersignature rule and the contract opens.

    PRD: "Signing is a `ConsortiumAdmin` capability, and the signer's `X-User-ID`
    must differ from `last_submitted_by_user_id`; if the two are equal, the
    signature is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    PRD: "It opens on both state axes at their initial values — `contract_status`
    of `PENDING_ACTIVATION` and `access_status` of `UNCONFIGURED`."

    Design: Corner/rbac/submitting_and_signing_split_across_two_users_succeeds
    """
    scenario = setup_agreed_negotiation(negotiator_user_id="neg-1")
    commitment = pledge(scenario["product"]["id"], scenario["member"]["id"])

    response = api.sign_negotiation(scenario["negotiation"]["id"], sign_payload("2027-01-01"),
                                    admin)
    subscription = validate_success(response, expected_status=201)

    assert_subscription(subscription)
    assert subscription["contract_status"] == "PENDING_ACTIVATION"
    assert subscription["access_status"] == "UNCONFIGURED"
    assert subscription["negotiated_price_cents"] == 9000000
    assert subscription["entitled_title_count"] == 400
    assert subscription["term_start"] == "2027-01-01"
    assert subscription["term_end"] == "2027-12-31"
    assert subscription["notice_deadline_date"] == "2027-10-02"

    negotiation = validate_success(api.get_negotiation(scenario["negotiation"]["id"], admin))
    assert negotiation["status"] == "SIGNED"

    confirmed = read_commitment(commitment["id"])
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["tier_price_cents"] == 4500000
    assert read_member(scenario["member"]["id"])["annual_committed_cents"] == 4500000
