"""Corner queue B — validations section instances."""

from test_helpers import (
    ApiErrorId,
    capture_consent,
    create_approved_recipient,
    create_connection_payload,
    create_consent_payload,
    create_pending_connection,
    get_success_data,
    make_admin_headers,
    make_consumer_headers,
    make_recipient_headers,
    make_reviewer_headers,
    setup_active_stack,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_sod_violation_when_reviewer_equals_creator(api):
    """PRD §3.2: "Segregation of duties applies throughout: the reviewer's
    `X-User-ID` must differ from the `PlatformAdmin` operator who created the
    recipient, otherwise `ERR_SOD_VIOLATION` is returned."

    Design: Corner/validations/sod_violation_when_reviewer_equals_creator
    """
    admin = make_admin_headers("shared_operator_id")
    recipient = get_success_data(
        api.create_recipient(
            {"name": "SodApp", "declared_use_case": "sod test", "minimization_policy": "BROAD"},
            admin,
        )
    )

    resp = api.review_recipient(
        recipient["id"], {"decision": "APPROVE"}, make_reviewer_headers("shared_operator_id")
    )
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

    reread = validate_success(api.get_recipient(recipient["id"], admin))
    assert reread["status"] == "PENDING_REVIEW"


def test_agreement_scope_mismatch_rejected(api):
    """PRD §3.6: "Every scope in the connection consent's `data_scopes` must
    appear as a key of that map; any scope the agreement does not permit is
    rejected with `ERR_AGREEMENT_SCOPE_NOT_PERMITTED`."

    Design: Corner/validations/agreement_scope_mismatch_rejected
    """
    from test_helpers import create_institution_with_agreement

    inst = create_institution_with_agreement(
        api,
        name="ScopeGate Bank",
        permitted_fields_by_scope={"BALANCE": ["current_cents"]},
    )
    rec = create_approved_recipient(
        api, name="ScopeApp", tier_scopes=["TRANSACTIONS"], rate_class="HIGH", tier_name="ScopeTier"
    )
    consent = capture_consent(api, rec["recipient"]["id"], "cons_ab", ["TRANSACTIONS"])

    resp = api.create_connection(
        inst["institution"]["id"],
        create_connection_payload(
            consumer_ref="cons_ab", consent_id=consent["id"], method="CREDENTIALS"
        ),
        make_consumer_headers("cons_ab"),
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_SCOPE_NOT_PERMITTED)

    connections, meta = validate_paginated(
        api.list_institution_connections(inst["institution"]["id"], inst["admin"])
    )
    assert meta["total_count"] == 0, "the rejected connection must not be persisted"


def test_method_not_supported_rejected(api):
    """PRD §3.6: "The method gate then requires the requested `method` to be a
    member of the institution's `supported_methods`, and additionally refuses
    the `CREDENTIALS` method once the institution's `connectivity_mode` has
    become `API_ONLY`; either failure is `ERR_METHOD_NOT_SUPPORTED`."

    Design: Corner/validations/method_not_supported_rejected
    """
    from test_helpers import create_institution_with_agreement

    # A CREDENTIALS-only institution: the target method must be a member of
    # the supported set, but the PRD restricts targets to BANK_API or
    # OAUTH_TOKEN, so a credentials-only institution cannot exist — use a
    # CREDENTIALS+BANK_API institution and request the unsupported OAUTH_TOKEN
    # method on the connection instead.
    inst = create_institution_with_agreement(
        api,
        name="CredOnly Bank",
        supported_methods=["CREDENTIALS", "BANK_API"],
        target_method="BANK_API",
    )
    rec = create_approved_recipient(
        api, name="MethodApp", tier_scopes=["BALANCE"], tier_name="MethodTier"
    )
    consent = capture_consent(api, rec["recipient"]["id"], "cons_ac", ["BALANCE"])

    resp = api.create_connection(
        inst["institution"]["id"],
        create_connection_payload(
            consumer_ref="cons_ac", consent_id=consent["id"], method="OAUTH_TOKEN"
        ),
        make_consumer_headers("cons_ac"),
    )
    validate_error(resp, ApiErrorId.ERR_METHOD_NOT_SUPPORTED)


def test_duplicate_active_consent_same_scopes_rejected(api):
    """PRD §3.4: "There may be at most one non-terminal consent for a given
    combination of `consumer_ref`, recipient, and the exact set of
    `data_scopes`; a duplicate capture is rejected with
    `ERR_DUPLICATE_ACTIVE`."

    Design: Corner/validations/duplicate_active_consent_same_scopes_rejected
    """
    admin = make_admin_headers()
    rec = create_approved_recipient(
        api, name="DupApp", tier_scopes=["BALANCE"], tier_name="DupTier"
    )
    recipient = rec["recipient"]
    capture_consent(api, recipient["id"], "cons_ad", ["BALANCE"])

    current = validate_success(api.get_recipient(recipient["id"], admin))
    resp = api.create_consent(
        recipient["id"],
        create_consent_payload(
            consumer_ref="cons_ad",
            data_scopes=["BALANCE"],
            expected_recipient_version=current["version"],
        ),
        make_consumer_headers("cons_ad"),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE)

    consents, meta = validate_paginated(api.list_recipient_consents(recipient["id"], admin))
    assert meta["total_count"] == 1, "a duplicate capture must not persist a second consent"


def test_ack_from_non_required_recipient_rejected(api):
    """PRD §3.11: "The acknowledging `Recipient` must be one of the recipients
    that received the `DATA_DELETED` webhook for the request and must not have
    acknowledged already; an acknowledgement from anyone else, or a repeated
    one, is rejected with `ERR_ACK_NOT_REQUIRED`."

    Design: Corner/validations/ack_from_non_required_recipient_rejected
    """
    admin = make_admin_headers()
    reviewer = make_reviewer_headers()
    rec1 = get_success_data(
        api.create_recipient(
            {"name": "AckApp1", "declared_use_case": "ack target", "minimization_policy": "BROAD"},
            admin,
        )
    )
    rec1 = get_success_data(api.review_recipient(rec1["id"], {"decision": "APPROVE"}, reviewer))
    rec2 = get_success_data(
        api.create_recipient(
            {"name": "AckApp2", "declared_use_case": "non target", "minimization_policy": "BROAD"},
            admin,
        )
    )
    get_success_data(api.review_recipient(rec2["id"], {"decision": "APPROVE"}, reviewer))

    tier = get_success_data(
        api.create_tier(
            {"tier_name": "AckTier", "scopes_included": ["BALANCE"], "rate_class": "LOW"}, admin
        )
    )
    get_success_data(api.create_tier_assignment(rec1["id"], {"tier_id": tier["id"]}, admin))
    consent = capture_consent(api, rec1["id"], "cons_ae", ["BALANCE"])

    request = validate_success(
        api.create_deletion_request(consent["id"], make_consumer_headers("cons_ae")),
        expected_status=201,
    )

    resp = api.ack_deletion_request(request["id"], make_recipient_headers(rec2["id"]))
    validate_error(resp, ApiErrorId.ERR_ACK_NOT_REQUIRED)

    reread = validate_success(api.get_deletion_request(request["id"], admin))
    assert reread["status"] == "PROPAGATING"
    assert reread["acked_recipient_ids"] == []
