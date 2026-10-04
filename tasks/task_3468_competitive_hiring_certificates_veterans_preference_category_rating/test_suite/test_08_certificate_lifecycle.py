"""Certificate lifecycle: return lockdown, lazy expiry at the exact instant,
extension limits and OCC, roster exhaustion, and issuance authorization.
"""
from test_helpers import (
    HR, SO, ApiErrorId,
    api_client, create_pass_over_request_payload, extend_certificate_payload,
    get_success_data, return_certificate_payload, select_entry, set_clock,
    setup_competitive_certificate, setup_open_announcement, validate_error,
    validate_paginated, validate_success,
)


def test_returned_certificate_terminal_lockdown(api):
    """PRD §3.7: "Any certificate-scoped action — selections, return, extension,
    or filing a pass-over request against one of its entries — attempted while
    the certificate is not `ACTIVE`, including one that has only just lazily
    expired, is rejected with `ERR_CERTIFICATE_NOT_ACTIVE` (HTTP 409)."

    Design: Corner/state_machines/returned_certificate_terminal_lockdown
    """
    ctx = setup_competitive_certificate()
    certificate = ctx["certificate"]

    set_clock("2026-09-20T00:00:00Z")
    returned = validate_success(
        api_client.return_certificate(
            certificate["id"], return_certificate_payload(), SO), 200)
    assert returned["status"] == "RETURNED"

    resp = api_client.extend_certificate(
        certificate["id"],
        extend_certificate_payload(10, returned["version"]),
        HR)
    validate_error(resp, ApiErrorId.ERR_CERTIFICATE_NOT_ACTIVE)

    reread = get_success_data(api_client.get_certificate(certificate["id"], HR))
    assert reread["status"] == "RETURNED"
    assert reread["expires_at"] == "2026-11-14T00:00:00Z", (
        "the rejected extension must not move expires_at")


def test_certificate_expires_at_exact_expiry_instant(api):
    """PRD §2.9: "Consistent with the closed interval, a certificate is
    `EXPIRED` once the logical clock reaches `expires_at`; at exactly
    `expires_at` it is already expired."
    PRD §3.7: "every application it still holds in `REFERRED` returns to the
    pool, landing back in `RATED` under `CATEGORY_RATING`".

    Design: Corner/state_machines/certificate_expires_at_exact_expiry_instant
    """
    ctx = setup_competitive_certificate()  # expires 2026-11-14T00:00:00Z
    certificate = ctx["certificate"]
    referred_application = ctx["applications"][0]
    assert ctx["entries"][0]["status"] == "REFERRED"

    set_clock("2026-11-13T23:59:59Z")  # one second before expiry
    reread = get_success_data(api_client.get_certificate(certificate["id"], HR))
    assert reread["status"] == "ACTIVE"

    set_clock("2026-11-14T00:00:00Z")  # exactly expires_at: >= boundary
    reread = get_success_data(api_client.get_certificate(certificate["id"], HR))
    assert reread["status"] == "EXPIRED"

    application = get_success_data(
        api_client.get_application(referred_application["id"], HR))
    assert application["status"] == "RATED", "expiry returns referred applications to the rated pool"


def test_third_certificate_extension_rejected(api):
    """PRD §3.7: "each extension adds `additional_days` to `expires_at`,
    between 1 and 30 days per extension, at most two extensions over the
    certificate's life, and breaching either bound is `ERR_EXTENSION_LIMIT`
    (HTTP 422)."

    Design: Corner/validations/third_certificate_extension_rejected
    """
    ctx = setup_competitive_certificate()  # expires 2026-11-14T00:00:00Z
    certificate = ctx["certificate"]

    first = validate_success(
        api_client.extend_certificate(
            certificate["id"],
            extend_certificate_payload(10, certificate["version"]),
            HR),
        200)
    assert first["expires_at"] == "2026-11-24T00:00:00Z"
    assert first["version"] == certificate["version"] + 1

    second = validate_success(
        api_client.extend_certificate(
            certificate["id"],
            extend_certificate_payload(10, first["version"]),
            HR),
        200)
    assert second["expires_at"] == "2026-12-04T00:00:00Z"
    assert second["version"] == first["version"] + 1
    assert second["extension_count"] == 2

    resp = api_client.extend_certificate(
        certificate["id"],
        extend_certificate_payload(10, second["version"]),
        HR)
    validate_error(resp, ApiErrorId.ERR_EXTENSION_LIMIT)

    reread = get_success_data(api_client.get_certificate(certificate["id"], HR))
    assert reread["expires_at"] == "2026-12-04T00:00:00Z", (
        "the rejected third extension must not move expires_at")
    assert reread["extension_count"] == 2


def test_certificate_extend_occ_stale_version(api):
    """PRD §2.6: "Extending a certificate likewise requires
    `expected_certificate_version` matching the certificate's current `version`,
    with the same `ERR_STALE_VERSION` (HTTP 412) rejection on mismatch."

    Design: Corner/cross_cutting_layers/certificate_extend_occ_stale_version
    """
    ctx = setup_competitive_certificate()
    certificate = ctx["certificate"]
    observed_version = certificate["version"]

    extended = validate_success(
        api_client.extend_certificate(
            certificate["id"],
            extend_certificate_payload(10, observed_version),
            HR),
        200)
    assert extended["version"] == observed_version + 1
    assert extended["expires_at"] == "2026-11-24T00:00:00Z"

    resp = api_client.extend_certificate(
        certificate["id"],
        extend_certificate_payload(5, observed_version),  # stale replay
        HR)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    reread = get_success_data(api_client.get_certificate(certificate["id"], HR))
    assert reread["expires_at"] == "2026-11-24T00:00:00Z"
    assert reread["version"] == observed_version + 1


def test_roster_exhausted_certificate_closes_and_announcement_fills(api):
    """PRD §3.7: "When no entry remains `REFERRED` — every entry having resolved
    to `SELECTED`, `PASSED_OVER`, or `NOT_SELECTED` — the roster is exhausted
    and the certificate auto-transitions `ACTIVE` → `CLOSED`."
    PRD §3.2: "When `remaining_vacancies` reaches zero the announcement
    auto-transitions `CERT_ISSUED` → `FILLED`, a terminal state".

    Design: Corner/state_machines/roster_exhausted_certificate_closes_and_announcement_fills
    """
    ctx = setup_competitive_certificate(vacancies_count=3)
    certificate, entries = ctx["certificate"], ctx["entries"]

    select_entry(certificate["id"], entries[0]["id"])
    select_entry(certificate["id"], entries[1]["id"], select_clock=None)
    select_entry(certificate["id"], entries[2]["id"], select_clock=None)

    reread_cert = get_success_data(api_client.get_certificate(certificate["id"], HR))
    assert reread_cert["status"] == "CLOSED", "roster exhausted: no REFERRED entry remains"

    announcement = get_success_data(
        api_client.get_announcement(ctx["announcement"]["id"], HR))
    assert announcement["status"] == "FILLED"
    assert announcement["remaining_vacancies"] == 0

    # The closed certificate is locked down for every certificate-scoped action.
    resp = api_client.create_pass_over_request(
        entries[0]["id"],
        create_pass_over_request_payload(entries[1]["id"], reason_code="OTHER"),
        SO)
    validate_error(resp, ApiErrorId.ERR_CERTIFICATE_NOT_ACTIVE)


def test_selecting_official_cannot_issue_certificate(api):
    """PRD §2.1: "A request whose role is not listed among an endpoint's
    authorized roles, or that violates an entity-backed ownership rule, is
    rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/selecting_official_cannot_issue_certificate
    """
    ctx = setup_open_announcement()
    resp = api_client.issue_certificate(ctx["announcement"]["id"], SO)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    resp_list = api_client.list_announcement_certificates(
        ctx["announcement"]["id"], HR)
    certificates, _meta = validate_paginated(resp_list)
    assert certificates == [], "no certificate may be created by the rejected call"
