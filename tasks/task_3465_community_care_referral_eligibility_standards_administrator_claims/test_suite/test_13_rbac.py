"""Role-based access control: header context, exclusive operations denied to
other roles, and shared reads allowed to every role."""
from test_helpers import (
    NON_EXISTENT_UUID, TEST_USERS, api_client, validate_error,
    validate_success,
    create_eligible_assessment, create_referral_authorization_payload,
    create_rx_for_urgent_visit, create_station, create_tpa, create_veteran,
    credential_decision_payload, decide_rx_payload, get_authorization,
    get_provider, make_provider_rep_headers, make_veteran_headers,
    onboard_provider, record_urgent_visit, setup_episode,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK = TEST_USERS["eligibility_clerk_headers"]
COORD = TEST_USERS["care_coordinator_headers"]


def test_call_missing_auth_header_returns_400():
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, naming the capacity in
    which they act. A request where either header is missing or empty is
    rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/call_missing_auth_header_returns_400
    """
    resp = api_client.get_tpa(NON_EXISTENT_UUID, {})
    # Header context (stage 1) precedes existence: 400, not 404.
    validate_error(resp, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")


def test_provider_cannot_credential_decision_returns_unauthorized():
    """PRD §2.1: "If the named role is not among the roles authorized for the
    target endpoint, the request is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)."
    PRD §3.1: "Credentialing is a lifecycle driven by a `NetworkManager`
    through credentialing decisions that name a `target_status`."

    Design: Corner/rbac/provider_cannot_credential_decision_returns_unauthorized
    """
    tpa = create_tpa()
    provider = onboard_provider(tpa, credential=False)  # stays PENDING

    resp = api_client.decide_credential(
        provider["id"], credential_decision_payload("CREDENTIALED"),
        make_provider_rep_headers(provider["id"]),
    )
    validate_error(resp, "ERR_UNAUTHORIZED_ROLE")

    after = get_provider(tpa["id"], provider["id"])
    assert after["credentialing_status"] == "PENDING"


def test_veteran_cannot_create_referral_returns_unauthorized():
    """PRD §2.1: "If the named role is not among the roles authorized for the
    target endpoint, the request is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)."
    PRD §3.3: "A `CareCoordinator` turns a favorable determination into care by
    creating a **referral authorization**, naming the `veteran_id`, the
    `assessment_id` of the supporting assessment, the `provider_id` of the
    chosen community provider, the `service_code`, the `authorized_visits`
    count (an integer from 1 to the initial cap of 12), the episode
    `duration_days` (from 1 to at most 365 days), and the `start_date` as an
    ISO calendar date."

    Design: Corner/rbac/veteran_cannot_create_referral_returns_unauthorized
    """
    station = create_station()
    tpa = create_tpa()
    provider = onboard_provider(tpa)
    veteran = create_veteran(station)
    assessment = create_eligible_assessment(veteran["id"])

    resp = api_client.create_referral_authorization(
        create_referral_authorization_payload(
            veteran["id"], assessment["id"], provider["id"]
        ),
        make_veteran_headers(veteran["id"]),
    )
    validate_error(resp, "ERR_UNAUTHORIZED_ROLE")


def test_clerk_cannot_authorize_referral_returns_unauthorized():
    """PRD §2.1: "If the named role is not among the roles authorized for the
    target endpoint, the request is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)."
    PRD §3.3: "a `CareCoordinator` authorizes a `PENDING_REVIEW` referral,
    moving it to `AUTHORIZED`, stamping `authorized_at` with the current
    logical clock, and incrementing the authorization's `version` by one; from
    any other status the attempt is rejected with `ERR_INVALID_STATE`."

    Design: Corner/rbac/clerk_cannot_authorize_referral_returns_unauthorized
    """
    env = setup_episode(authorize=False)
    auth = env["authorization"]

    resp = api_client.authorize_referral(auth["id"], CLERK)
    validate_error(resp, "ERR_UNAUTHORIZED_ROLE")
    assert get_authorization(auth["id"])["status"] == "PENDING_REVIEW"


def test_coordinator_cannot_decide_prescription_returns_unauthorized():
    """PRD §2.1: "If the named role is not among the roles authorized for the
    target endpoint, the request is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)."
    PRD §3.8: "A `SystemPharmacist` closes the loop with a `decision` of
    `FILLED` or `REFUSED`."

    Design: Corner/rbac/coordinator_cannot_decide_prescription_returns_unauthorized
    """
    station = create_station()
    veteran = create_veteran(station, priority_group=2)
    visit = record_urgent_visit(veteran, clock_iso="2026-09-01T08:00:00Z")
    tpa = create_tpa()
    provider = onboard_provider(tpa)
    rx = create_rx_for_urgent_visit(visit, provider)

    resp = api_client.decide_prescription_fill_request(
        rx["id"], decide_rx_payload("FILLED"), COORD
    )
    validate_error(resp, "ERR_UNAUTHORIZED_ROLE")

    still = api_client.get_prescription_fill_request(rx["id"], COORD)
    assert validate_success(still, 200)["status"] == "REQUESTED"


def test_veteran_can_read_own_referral_via_shared_get():
    """PRD §2.1: "If the named role is not among the roles authorized for the
    target endpoint, the request is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)."
    PRD §4: "| GET | `/community-care/referral-authorizations/{id}` | Get an
    authorization with its visit ledger | Any |"

    Design: Corner/rbac/veteran_can_read_own_referral_via_shared_get
    """
    env = setup_episode(authorize=False)
    auth = env["authorization"]

    resp = api_client.get_referral_authorization(
        auth["id"], make_veteran_headers(env["veteran"]["id"])
    )
    data = validate_success(resp, 200)
    assert data["id"] == auth["id"]
