"""Validation boundaries: authentication, cross-region references, evidence/account
pairing and the conditional adverse-reason requirement."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    get_success_data,
    make_incident,
    set_clock,
    setup_account,
    setup_background_check_in_review,
    setup_policy,
    setup_trip,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["admin_headers"]
INVESTIGATOR = TEST_USERS["investigator_headers"]
OPERATIONS_LEAD = TEST_USERS["operations_lead_headers"]
BACKGROUND_REVIEWER = TEST_USERS["background_reviewer_headers"]


def test_missing_role_header_is_unauthenticated_and_unknown_role_is_unauthorized(api):
    """PRD §2.1: "A request that omits either header is rejected with `ERR_UNAUTHENTICATED`
    (`401`) before any resource work begins, and that check runs ahead of everything else in
    the request pipeline."
    PRD §2.1: "A request whose `X-User-Role` names a role that is not permitted for the
    operation — including a role string the platform does not recognise at all, which is
    treated as an authorisation failure rather than an authentication failure — is rejected
    with `ERR_UNAUTHORIZED` (`403`)."

    Design: Corner/validations/incident_list_without_role_headers_is_unauthenticated
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy()
    account = setup_account(handle="tara.lund")
    make_incident(account["id"], incident_category="PROPERTY_DAMAGE")

    anonymous = api_client.list_incidents({})
    validate_error(anonymous, ApiErrorId.ERR_UNAUTHENTICATED)
    assert anonymous.status_code == 401, (
        "the header-less request is refused before any resource work"
    )

    unknown_role = api_client.list_incidents(
        {"X-User-ID": "op-unknown", "X-User-Role": "NotARole",
         "Content-Type": "application/json"}
    )
    validate_error(unknown_role, ApiErrorId.ERR_UNAUTHORIZED)
    assert unknown_role.status_code == 403, (
        "an unrecognised role string is an authorisation failure, not an authentication one"
    )

    data, _ = validate_paginated(api_client.list_incidents(INVESTIGATOR))
    assert len(data) == 1, "both refusals left the incident list unchanged"


def test_cross_region_link_is_refused_while_the_in_region_link_succeeds(api):
    """PRD §3.7: "A link whose cluster or referenced incident belongs to a different operating
    region is refused with `ERR_CROSS_REGION_REFERENCE` (`422`)."
    PRD §3.3: "And neither evidence nor a device link may reach across regions"

    Design: Corner/validations/record_link_against_a_different_region_is_refused
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy(region_code="R1")
    setup_policy(region_code="R3")
    account = setup_account(account_type="DRIVER", region_code="R1", handle="xenia.petrova")

    cluster_r1 = get_success_data(
        api_client.create_device_cluster({"cluster_key": "dc-r1", "region_code": "R1"}, ADMIN)
    )
    cluster_r3 = get_success_data(
        api_client.create_device_cluster({"cluster_key": "dc-r3", "region_code": "R3"}, ADMIN)
    )

    in_region = get_success_data(
        api_client.create_account_device_link(
            {"account_id": account["id"], "device_cluster_id": cluster_r1["id"],
             "fingerprint_hash": "fp-in-region"},
            INVESTIGATOR,
        )
    )
    assert in_region["link_status"] == "LINKED"

    res = api_client.create_account_device_link(
        {"account_id": account["id"], "device_cluster_id": cluster_r3["id"],
         "fingerprint_hash": "fp-cross-region"},
        INVESTIGATOR,
    )
    validate_error(res, ApiErrorId.ERR_CROSS_REGION_REFERENCE)
    assert res.status_code == 422

    data, _ = validate_paginated(
        api_client.list_account_device_links(OPERATIONS_LEAD,
                                             params={"account_id": account["id"]})
    )
    assert len(data) == 1, "the cross-region refusal stored no link row"


def test_evidence_from_a_trip_that_does_not_involve_the_counterparty_is_refused(api):
    """PRD §3.3: "A trip attached as `TRIP_DATA` or `IN_APP_MESSAGE` evidence must involve
    both the incident's subject account and the reported counterparty account; a trip that
    involves only one of them is refused with `ERR_TRIP_ACCOUNT_MISMATCH` (`422`)."

    Design: Corner/validations/cross_region_trip_cannot_become_incident_evidence
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy()
    subject = setup_account(handle="ula.bakker", account_type="RIDER")
    counterparty = setup_account(account_type="DRIVER", handle="vito.greco")
    outsider = setup_account(account_type="DRIVER", handle="wren.ashby")

    good_trip = setup_trip(subject["id"], counterparty["id"], in_app_message_count=3)
    bad_trip = setup_trip(outsider["id"], counterparty["id"], in_app_message_count=3)

    incident = make_incident(subject["id"], incident_category="HARASSMENT",
                            reporter_type="RIDER",
                            referenced_trip_id=good_trip["id"])

    accepted = get_success_data(
        api_client.create_evidence(
            incident["id"],
            {"evidence_type": "TRIP_DATA", "source_entity_id": good_trip["id"],
             "evidence_weight": "STANDARD"},
            INVESTIGATOR,
        )
    )
    assert accepted["evidence_status"] == "PENDING"

    res = api_client.create_evidence(
        incident["id"],
        {"evidence_type": "TRIP_DATA", "source_entity_id": bad_trip["id"],
         "evidence_weight": "STANDARD"},
        INVESTIGATOR,
    )
    validate_error(res, ApiErrorId.ERR_TRIP_ACCOUNT_MISMATCH)
    assert res.status_code == 422

    rows, _ = validate_paginated(
        api_client.list_evidence(incident["id"], INVESTIGATOR)
    )
    assert len(rows) == 1, (
        "the refused attachment stored nothing, leaving only the accepted row"
    )
    assert rows[0]["source_entity_id"] == good_trip["id"]


def test_third_party_report_omits_the_reporter_account(api):
    """PRD §3.1: "when the type is `THIRD_PARTY` the `reporter_account_id` member must be
    omitted, and when it is `RIDER` or `DRIVER` it must be populated. A report that violates
    that pairing is refused with `ERR_REPORTER_ACCOUNT_MISMATCH` (`422`)."

    Design: Corner/entities/incident_report_from_third_party_requires_null_reporter_account
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy()
    account = setup_account(handle="fada.onyeka")

    third_party = make_incident(account["id"], incident_category="SAFETY_VIOLATION",
                                reporter_type="THIRD_PARTY")
    assert third_party["reporter_account_id"] is None, (
        "a third-party report carries no reporting account"
    )

    res = api_client.create_incident(
        {"account_id": account["id"], "reporter_type": "RIDER",
         "incident_category": "SAFETY_VIOLATION"},
        INVESTIGATOR,
    )
    validate_error(res, ApiErrorId.ERR_REPORTER_ACCOUNT_MISMATCH)
    assert res.status_code == 422

    rows, _ = validate_paginated(
        api_client.list_incidents(INVESTIGATOR, params={"account_id": account["id"]})
    )
    assert len(rows) == 1, "the refused report created no incident row"


def test_adverse_adjudication_requires_a_reason_code(api):
    """PRD §3.8: "Adjudication then supplies an `adjudication` of `CLEAR`, `ADVERSE` or
    `INCONCLUSIVE` and, for an adverse verdict, an `adverse_reason_code`. An adverse verdict
    arriving without a reason code is refused with `ERR_ADVERSE_REASON_REQUIRED` (`422`)."

    Design: Corner/errors/error_adverse_reason_required_on_a_bare_adverse_verdict
    """
    set_clock("2026-10-01T00:00:00Z")
    setup_policy()
    account = setup_account(account_type="DRIVER", handle="bea.iheanacho")

    check, _ = setup_background_check_in_review(account["id"])
    assert check["check_status"] == "IN_REVIEW", (
        "the acknowledgement precondition is a date rather than a structural state, so the "
        "review moves into review once the clock reaches its acknowledgement window"
    )

    res = api_client.adjudicate_background_check(
        check["id"], {"adjudication": "ADVERSE"}, BACKGROUND_REVIEWER
    )
    validate_error(res, ApiErrorId.ERR_ADVERSE_REASON_REQUIRED)
    assert res.status_code == 422

    after = get_success_data(
        api_client.get_background_check(check["id"], BACKGROUND_REVIEWER)
    )
    assert after["check_status"] == "IN_REVIEW", "the refused call wrote nothing"
    assert after["adjudication"] == "PENDING"