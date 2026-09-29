"""Authentication, role admission and the three ownership identities.

PRD 2.1 splits access control into four distinct refusals: absent or blank
headers (401), a role the endpoint does not admit (403), a `CarrierRep`
reaching across carriers (403) and an `InsuranceFiler` reaching across
insurers (403).  Each test below proves one of them fires on its own trigger
and that the positive path immediately beside it still succeeds.
"""

from test_helpers import (
    ApiErrorId,
    COMPLIANCE_OFFICER,
    COMPLIANCE_OFFICER_ALT,
    FEE_NEW_FOR_HIRE_THREE_STATES_CENTS,
    MAX_LIMIT,
    NON_EXISTENT_UUID,
    NO_HEADERS,
    REGISTRY_ADMIN,
    VETTING_ANALYST,
    application_payload,
    assert_fee_ledger_identities,
    audit_result_payload,
    authority_version,
    cancel_filing_payload,
    carrier_payload,
    create_carrier,
    create_draft_application,
    create_insurer,
    fee_payment_payload,
    file_insurance,
    filing_payload,
    get_success_data,
    headers_with_empty_role,
    headers_with_empty_user_id,
    headers_without_role,
    headers_without_user_id,
    make_analyst_headers,
    make_carrier_headers,
    make_insurer_headers,
    make_officer_headers,
    read_authority,
    set_clock,
    setup_pending_authority_with_coverage,
    setup_published_authority,
    setup_submitted_application,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_exclusive_operations_are_closed_to_every_other_role(api):
    """Four single-role endpoints refuse the wrong role before anything else.

    PRD 2.1: "Once both headers are present, the role is matched against the set of
    roles the target endpoint admits (§4); a role outside that set is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    PRD 2.8: "2. The acting role is admitted by the target endpoint —
    `ERR_UNAUTHORIZED`. Applies to every request."

    PRD 4: "The authorized roles named in the final column are checked after
    authentication and before anything else, in the order given in §2.8."

    Design: Corner/rbac/exclusive_operations_are_closed_to_every_other_role
    """
    env = setup_published_authority(api)

    # Activation is a ComplianceOfficer-only operation.
    validate_error(
        api.activate_authority(env.authority_id, env.carrier_headers),
        ApiErrorId.UNAUTHORIZED,
    )
    # Opening an application is a CarrierRep-only operation.
    validate_error(
        api.create_application(
            application_payload(env.carrier_id), COMPLIANCE_OFFICER
        ),
        ApiErrorId.UNAUTHORIZED,
    )
    # Enrolling a carrier is a RegistryAdmin-only operation.
    validate_error(
        api.create_carrier(
            carrier_payload(legal_name="Unauthorized Enrolment LLC"),
            env.carrier_headers,
        ),
        ApiErrorId.UNAUTHORIZED,
    )
    # Recording an audit result is a ComplianceOfficer-only operation, and the
    # role refusal outranks the fact that this audit id does not exist at all.
    validate_error(
        api.record_audit_result(
            NON_EXISTENT_UUID, audit_result_payload(), VETTING_ANALYST
        ),
        ApiErrorId.UNAUTHORIZED,
    )

    after = read_authority(api, env.authority_id)
    assert after["authority_status"] == "PENDING"
    assert after["activated_at"] is None
    assert after["version"] == env.authority["version"]

    # None of the four refusals created anything.
    applications, _ = validate_paginated(
        api.list_applications(REGISTRY_ADMIN, limit=MAX_LIMIT)
    )
    assert [row["id"] for row in applications] == [env.application_id]


def test_missing_or_empty_authentication_headers_are_rejected(api):
    """A blank header value is treated as an absent one, and 401 precedes 403.

    PRD 2.1: "Both headers must be present and non-empty; a header sent with an
    empty-string value counts as absent and the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401). This check precedes every other check in the
    system, including the existence of the resources named in the path."

    Design: Corner/rbac/missing_or_empty_authentication_headers_are_rejected
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    carrier = create_carrier(api, legal_name="San Marcos Drayage LLC")

    variants = {
        "role header absent": headers_without_role(),
        "user-id header absent": headers_without_user_id(),
        "user-id header empty string": headers_with_empty_user_id(),
        "role header empty string": headers_with_empty_role(),
        "both headers absent": NO_HEADERS,
    }
    for label, headers in variants.items():
        error = validate_error(
            api.get_carrier(carrier["id"], headers), ApiErrorId.UNAUTHENTICATED
        )
        assert error["error_id"] == "ERR_UNAUTHENTICATED", label

    # The same blank-header rule holds on a path whose resource does not exist,
    # because authentication is decided before path resolution.
    validate_error(
        api.get_carrier(NON_EXISTENT_UUID, headers_with_empty_user_id()),
        ApiErrorId.UNAUTHENTICATED,
    )

    # Nothing above touched the carrier, and a properly authenticated read works.
    readable = get_success_data(api.get_carrier(carrier["id"], COMPLIANCE_OFFICER))
    assert readable["id"] == carrier["id"]
    assert readable["legal_name"] == "San Marcos Drayage LLC"


def test_carrier_rep_cannot_act_on_another_carriers_application(api):
    """Carrier B can neither submit A's draft nor open a draft naming A.

    PRD 2.1: "ownership checks on any resource that references a `Carrier` compare
    the resource's carrier-linking field to `X-User-ID`, following `authority_id` to
    the authority's `carrier_id`, and `contract_id` to the contract's `authority_id`
    and from there to that authority's `carrier_id`, as deep as the resource
    requires. A `CarrierRep` acting on a resource owned by a different carrier is
    rejected with `ERR_NOT_CARRIER_OWNER` (HTTP 403)."

    PRD 2.8: "4. Carrier ownership — `ERR_NOT_CARRIER_OWNER`. Applies to
    `POST /carriers/{id}/biennial-update`, `POST /carriers/{id}/fee-payments`,
    `POST /authority-applications`, `POST /authority-applications/{id}/submit`"

    Design: Corner/rbac/carrier_rep_cannot_act_on_another_carriers_application
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    carrier_a = create_carrier(api, legal_name="Atascosa Freight A LLC")
    carrier_b = create_carrier(api, legal_name="Atascosa Freight B LLC")
    headers_a = make_carrier_headers(carrier_a["id"])
    headers_b = make_carrier_headers(carrier_b["id"])

    draft = create_draft_application(api, carrier_a["id"])
    assert draft["carrier_id"] == carrier_a["id"]

    # B holds valid credentials for a real carrier; it simply owns nothing here.
    validate_error(
        api.submit_application(draft["id"], headers_b), ApiErrorId.NOT_CARRIER_OWNER
    )
    validate_error(
        api.create_application(application_payload(carrier_a["id"]), headers_b),
        ApiErrorId.NOT_CARRIER_OWNER,
    )

    # A's own submission goes through untouched by the two refusals.
    submitted = validate_success(api.submit_application(draft["id"], headers_a))
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submission_count"] == 1

    rows, _ = validate_paginated(api.list_applications(REGISTRY_ADMIN, limit=MAX_LIMIT))
    assert [row["carrier_id"] for row in rows] == [carrier_a["id"]]

    # The refused create never reached the fee ledger of either carrier.
    carrier_b_now = get_success_data(api.get_carrier(carrier_b["id"], REGISTRY_ADMIN))
    assert carrier_b_now["fee_balance_cents"] == 0
    assert carrier_b_now["fees_assessed_total_cents"] == 0


def test_insurance_filer_cannot_cancel_another_insurers_filing(api):
    """Insurer B cannot cancel A's filing, nor file in A's name.

    PRD 2.1: "on a filing create the check compares `X-User-ID` to the `insurer_id`
    supplied in the request body, and on a filing cancel it compares `X-User-ID` to
    the target filing's stored `insurer_id`. A mismatch is rejected with
    `ERR_INSURER_NOT_FILING_PARTY` (HTTP 403)."

    PRD 2.8: "5. Insurer identity — `ERR_INSURER_NOT_FILING_PARTY`. Applies to
    `POST /insurance-filings` and `POST /insurance-filings/{id}/cancel`."

    Design: Corner/rbac/insurance_filer_cannot_cancel_another_insurers_filing
    """
    env = setup_published_authority(api)
    insurer_b = create_insurer(
        api, company_name="Balcones Fidelity Assurance", naic_code="67890"
    )
    headers_b = make_insurer_headers(insurer_b["id"])

    minimum = env.authority["required_bipd_limit_cents"]
    incumbent = file_insurance(
        api,
        env.insurer_id,
        env.authority_id,
        minimum,
        filing_type="BIPD",
        effective_at=env.publish_at,
    )
    assert incumbent["insurer_id"] == env.insurer_id
    assert incumbent["status"] == "ACTIVE"
    version_after_filing = authority_version(api, env.authority_id)

    validate_error(
        api.cancel_filing(
            incumbent["id"],
            cancel_filing_payload("2026-08-20T00:00:00Z"),
            headers_b,
        ),
        ApiErrorId.INSURER_NOT_FILING_PARTY,
    )
    # B supplies A's insurer_id in the body, which is exactly the create-side
    # comparison the rule describes.
    validate_error(
        api.create_filing(
            filing_payload(
                env.authority_id,
                env.insurer_id,
                minimum,
                version_after_filing,
                filing_type="BIPD",
                policy_number="BIPD-IMPOSTOR",
                effective_at="2026-08-11T00:00:00Z",
            ),
            headers_b,
        ),
        ApiErrorId.INSURER_NOT_FILING_PARTY,
    )

    still_there = get_success_data(api.get_filing(incumbent["id"], REGISTRY_ADMIN))
    assert still_there["status"] == "ACTIVE"
    assert still_there["cancellation_effective_at"] is None
    assert still_there["supersedes_filing_id"] is None

    authority = read_authority(api, env.authority_id)
    assert authority["insurance_status"] == "FILED"
    assert authority["version"] == version_after_filing

    rows, _ = validate_paginated(api.list_filings(REGISTRY_ADMIN, limit=MAX_LIMIT))
    on_authority = [row for row in rows if row["authority_id"] == env.authority_id]
    assert len(on_authority) == 1
    assert on_authority[0]["id"] == incumbent["id"]


def test_the_user_who_published_the_application_cannot_activate_the_authority(api):
    """One staff identifier holding both roles is still barred from activating.

    PRD 2.1: "Opaque operator identifiers are drawn from one shared
    compliance-office staff directory, so the same person may legitimately hold both
    the `VettingAnalyst` and the `ComplianceOfficer` role. That is precisely why the
    segregation-of-duties comparison is made on the recorded identifier and not on
    the role."

    PRD 3.6: "The activating officer must not be the analyst who published the
    application: the acting `X-User-ID` is compared to the application's stored
    `published_by_user_id`, and equality is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/the_user_who_published_the_application_cannot_activate_the_authority
    """
    dual_role_user = "staff-dual-001"
    env = setup_pending_authority_with_coverage(
        api, analyst=make_analyst_headers(dual_role_user)
    )
    assert env.application["published_by_user_id"] == dual_role_user
    assert env.authority["authority_status"] == "PENDING"

    eligible_at = env.authority["activation_eligible_at"]
    set_clock(api, eligible_at)

    # Same identifier, admitted role, but it published this very application.
    validate_error(
        api.activate_authority(env.authority_id, make_officer_headers(dual_role_user)),
        ApiErrorId.SEGREGATION_OF_DUTIES,
    )
    refused = read_authority(api, env.authority_id)
    assert refused["authority_status"] == "PENDING"
    assert refused["activated_at"] is None
    assert refused["version"] == env.authority["version"]

    # A different officer, at the very same logical instant, is admitted.
    activated = validate_success(
        api.activate_authority(env.authority_id, COMPLIANCE_OFFICER_ALT)
    )
    assert activated["authority_status"] == "ACTIVE"
    assert activated["activated_at"] == "2026-08-26T00:00:00.000Z"
    assert activated["version"] == env.authority["version"] + 1

    carrier = get_success_data(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert carrier["unified_registration_status"] == "REGISTERED"
    assert carrier["active_authority_count"] == 1


def test_fee_payments_are_open_to_both_the_carrier_rep_and_the_registry_admin(api):
    """Two admitted roles settle one balance between them; a third is refused.

    PRD 3.1: "A payment is recorded by a `CarrierRep` acting for its own carrier or
    by a `RegistryAdmin`, and consists of an `amount_cents` figure plus an optional
    `memo`."

    PRD 3.1: "Recording it appends a ledger entry whose `entry_type` is
    `FEE_PAYMENT_CREDIT` and whose `amount_cents` is the negation of the submitted
    amount, then increases `fees_paid_total_cents` by the submitted amount and
    decreases `fee_balance_cents` by the same amount."

    PRD 2.3: "Every list endpoint, without exception, orders its records by
    `created_at` ascending"

    Design: Corner/rbac/fee_payments_are_open_to_both_the_carrier_rep_and_the_registry_admin
    """
    env = setup_submitted_application(api, with_agent=False, with_insurer=False)
    assert env.filing_fee_cents == FEE_NEW_FOR_HIRE_THREE_STATES_CENTS
    assert env.filing_fee_cents == 64791
    assert get_success_data(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))[
        "fee_balance_cents"
    ] == 64791

    by_carrier = validate_success(
        api.record_fee_payment(
            env.carrier_id,
            fee_payment_payload(30000, memo="part payment by the carrier"),
            env.carrier_headers,
        ),
        201,
    )
    assert by_carrier["fee_balance_cents"] == 34791
    assert by_carrier["fees_paid_total_cents"] == 30000

    by_admin = validate_success(
        api.record_fee_payment(
            env.carrier_id,
            fee_payment_payload(34791, memo="balance settled at the counter"),
            REGISTRY_ADMIN,
        ),
        201,
    )
    assert by_admin["fee_balance_cents"] == 0
    assert by_admin["fees_paid_total_cents"] == 64791

    # A VettingAnalyst is not among the roles this endpoint admits.
    validate_error(
        api.record_fee_payment(
            env.carrier_id, fee_payment_payload(100), VETTING_ANALYST
        ),
        ApiErrorId.UNAUTHORIZED,
    )

    final = get_success_data(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert final["fee_balance_cents"] == 0
    assert final["fees_paid_total_cents"] == 64791
    assert final["fees_assessed_total_cents"] == 64791
    assert final["fees_reversed_total_cents"] == 0

    entries, _ = validate_paginated(
        api.list_fee_ledger_entries(env.carrier_id, REGISTRY_ADMIN, limit=MAX_LIMIT)
    )
    credits = [row for row in entries if row["entry_type"] == "FEE_PAYMENT_CREDIT"]
    assert [row["amount_cents"] for row in credits] == [-30000, -34791]
    debits = [row for row in entries if row["entry_type"] == "FILING_FEE_DEBIT"]
    assert [row["amount_cents"] for row in debits] == [64791]
    # The refused payment appended nothing at all.
    assert len(entries) == 3
    assert_fee_ledger_identities(api, env.carrier_id, REGISTRY_ADMIN)
