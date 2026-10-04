"""Guide-publish cascade, RBAC, validation priority, photo-review cascade,
and authentication tests."""
from test_helpers import (
    REQUIRED_PHOTO_TYPES,
    TEST_USERS,
    ApiErrorId,
    accept_photos,
    add_listed_driver,
    create_guide_tool_valuation,
    create_member,
    create_member_payload,
    create_policy_for,
    create_published_guide,
    create_vehicle,
    evaluate_vehicle,
    get_policy,
    make_appraiser_headers,
    make_member_headers,
    make_underwriter_headers,
    propose_and_approve,
    setup_active_policy,
    setup_approved_guide_valuation,
    setup_documented_vehicle,
    submit_all_photos,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
UW = TEST_USERS["underwriter_headers"]


def test_guide_publish_cascade_depth3(api):
    """PRD §3.4: "Publication triggers a three-level cascade. The prior guide
    in `PUBLISHED` becomes `SUPERSEDED`. Every valuation created by the
    guide-tool method that was pinned to that superseded guide and still in
    `APPROVED` status becomes `STALE`. Every `ACTIVE` policy pinned to one of
    those newly stale valuations drops to `UNDER_REVIEW`, where it waits for
    a revaluation."

    Design: Difficulty/transitive_cascade/guide_publish_cascade_depth3
    """
    ctx = setup_active_policy()
    old_guide = ctx["guide"]
    valuation_id = ctx["valuation"]["id"]
    policy_id = ctx["policy"]["id"]
    # Publish a second guide.
    create_published_guide(base_value_cents=3_100_000)
    superseded = validate_success(api.get_valuation_guide(old_guide["id"], ADMIN))
    assert superseded["status"] == "SUPERSEDED", (
        f"Link 1: prior guide must be SUPERSEDED, got {superseded['status']}"
    )
    stale = validate_success(api.get_valuation(valuation_id, UW))
    assert stale["status"] == "STALE", (
        f"Link 2: pinned GUIDE_TOOL valuation must be STALE, got {stale['status']}"
    )
    policy = get_policy(policy_id)
    assert policy["status"] == "UNDER_REVIEW", (
        f"Link 3: ACTIVE policy pinned to the stale valuation must drop to "
        f"UNDER_REVIEW, got {policy['status']}"
    )


def test_guide_publish_cascade_link1_supersedes_prior_guide(api):
    """PRD §3.4: "Publication triggers a three-level cascade. The prior guide
    in `PUBLISHED` becomes `SUPERSEDED`."

    Design: Difficulty/transitive_cascade/guide_publish_cascade_depth3
    """
    first = create_published_guide(base_value_cents=3_000_000)
    second = create_published_guide(base_value_cents=3_100_000)
    assert second["status"] == "PUBLISHED"
    first_after = validate_success(api.get_valuation_guide(first["id"], ADMIN))
    assert first_after["status"] == "SUPERSEDED"


def test_photo_review_cascade_moves_policy_to_quoted(api):
    """PRD §3.3: "Completion has a downstream consequence: any policy of
    this vehicle waiting in `PENDING_DOCUMENTS` is returned to `QUOTED`
    automatically, since the documentation gate has now been satisfied."

    Design: Corner/endpoints/photo_review_cascade_moves_policy_to_quoted
    """
    member, m_headers = create_member(full_name="Rex", email="rex@x.com")
    vehicle = create_vehicle(member, vin="VIN141")
    photos = submit_all_photos(vehicle["id"], m_headers)
    # Accept 7 of 8 before policy creation.
    accept_photos(vehicle["id"], photos, only_types=set(REQUIRED_PHOTO_TYPES) - {"VIN_PLATE"})
    evaluate_vehicle(vehicle["id"])
    create_published_guide()
    valuation = propose_and_approve(
        create_guide_tool_valuation(vehicle["id"], 3_000_000)["id"]
    )
    policy = create_policy_for(member, vehicle, valuation)
    assert policy["status"] == "PENDING_DOCUMENTS", (
        "Policy with incomplete documentation must start in PENDING_DOCUMENTS"
    )
    # Accept the 8th photo: documentation completes, policy cascades to QUOTED.
    validate_success(
        api.review_photo(vehicle["id"], photos["VIN_PLATE"]["id"], {"decision": "ACCEPT"}, UW)
    )
    after = get_policy(policy["id"])
    assert after["status"] == "QUOTED", (
        f"Completing documentation must cascade the policy to QUOTED, got "
        f"{after['status']}"
    )


def test_driver_add_state_vs_business_safety_priority(api):
    """PRD §3.6: "Listing is only possible while the policy is `QUOTED`,
    `PENDING_DOCUMENTS`, or `ACTIVE` — other states are rejected with
    `ERR_INVALID_STATE`".
    PRD §2.8: "State-transition legality is checked next
    (`ERR_INVALID_STATE`), followed by the optimistic-concurrency guard
    (`ERR_STALE_VERSION`) where one applies. Segregation-of-duties checks
    (`ERR_SOD_VIOLATION`) run after the OCC check. Business rules follow in
    their own fixed order — driver eligibility, ...".

    Design: Difficulty/priority_pair_validation_conflict/driver_add_state_vs_business_safety_priority
    """
    ctx = setup_active_policy()
    pid = ctx["policy"]["id"]
    validate_success(api.begin_review(pid, UW))
    # Policy UNDER_REVIEW + driver with violations: state check (priority 4)
    # must fire before driver eligibility (business rule).
    resp = api.add_driver(
        pid,
        {
            "full_name": "Reckless Ray",
            "license_number": "D999",
            "years_licensed": 9,
            "violations_last_3y": 2,
            "is_primary": False,
        },
        ctx["member_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_driver_add_ineligible_on_active_policy(api):
    """PRD §3.6: "each driver must have been licensed for at least five
    years with zero moving violations in the last three years, failing which
    the listing is rejected with `ERR_DRIVER_INELIGIBLE`."

    Design: Difficulty/priority_pair_validation_conflict/driver_add_state_vs_business_safety_priority
    """
    ctx = setup_active_policy()
    # Policy is ACTIVE (state gate passes); only eligibility fails.
    resp = api.add_driver(
        ctx["policy"]["id"],
        {
            "full_name": "Reckless Ray",
            "license_number": "D999",
            "years_licensed": 9,
            "violations_last_3y": 2,
            "is_primary": False,
        },
        ctx["member_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_DRIVER_INELIGIBLE)


def test_driver_violations_rejected(api):
    """PRD §3.6: "each driver must have been licensed for at least five
    years with zero moving violations in the last three years, failing which
    the listing is rejected with `ERR_DRIVER_INELIGIBLE`."

    Design: Corner/validations/driver_violations_rejected
    """
    member, m_headers = create_member(full_name="Gil", email="gil@x.com")
    ctx = setup_approved_guide_valuation((member, m_headers), document=False)
    policy = create_policy_for(member, ctx["vehicle"], ctx["valuation"])
    assert policy["status"] == "PENDING_DOCUMENTS"
    resp = api.add_driver(
        policy["id"],
        {
            "full_name": "Bad Driver",
            "license_number": "D200",
            "years_licensed": 10,
            "violations_last_3y": 1,
            "is_primary": True,
        },
        m_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DRIVER_INELIGIBLE)


def test_member_cannot_approve_valuation_forbidden(api):
    """PRD §2.1: "A request whose role is not permitted for the target
    endpoint — or whose identity does not match the owning resource where
    ownership applies — is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: POST /valuations/{id}/approve is authorized for Underwriter only.

    Design: Corner/rbac/member_cannot_approve_valuation_forbidden
    """
    member, m_headers = create_member(full_name="Tia", email="tia@x.com")
    ctx = setup_approved_guide_valuation((member, m_headers), document=False)
    # Build a fresh PROPOSED valuation to approve as a Member.
    valuation = create_guide_tool_valuation(ctx["vehicle"]["id"], 3_000_000)
    validate_success(api.propose_valuation(valuation["id"], UW))
    resp = api.approve_valuation(valuation["id"], {}, m_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_appraiser_cannot_certify_own_appraisal_forbidden(api):
    """PRD §3.5: "Certification enforces segregation of duties: the acting
    underwriter must not be the appraiser who submitted the opinion, and a
    self-certification attempt is rejected with `ERR_SOD_VIOLATION`."

    Design: Corner/rbac/appraiser_cannot_certify_own_appraisal_forbidden
    """
    member, m_headers = create_member(full_name="Uli", email="uli@x.com")
    vehicle = create_vehicle(member, vin="VIN151")
    appraisal = validate_success(
        api.submit_appraisal(
            vehicle["id"],
            {"appraised_value_cents": 3_500_000, "appraised_at": "2026-09-10T00:00:00Z"},
            make_appraiser_headers("appraiser-9"),
        ),
        expected_status=201,
    )
    # Same X-User-ID, now acting as Underwriter, attempts certification.
    resp = api.certify_appraisal(
        appraisal["id"], {"decision": "CERTIFY"},
        make_underwriter_headers("appraiser-9"),
    )
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)


def test_member_cannot_read_other_members_policy_forbidden(api):
    """PRD §2.1: "A request whose role is not permitted for the target
    endpoint — or whose identity does not match the owning resource where
    ownership applies — is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the
    acting `Member` record; ownership checks on any resource that references
    a member (vehicles, policies, drivers, usage events, claims, restoration
    projects, roadside dispatches, event registrations) compare the
    resource's owning `member_id` — directly or through its parent chain —
    against `X-User-ID`."

    Design: Corner/rbac/member_cannot_read_other_members_policy_forbidden
    """
    member_a, ma_headers = create_member(full_name="A", email="a9@x.com")
    member_b, mb_headers = create_member(full_name="B", email="b9@x.com")
    ctx = setup_approved_guide_valuation((member_b, mb_headers), document=False)
    policy = create_policy_for(member_b, ctx["vehicle"], ctx["valuation"])
    resp = api.get_policy(policy["id"], ma_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_error_unauthenticated_missing_role(api):
    """PRD §2.1: "A request arriving without a declared role in
    `X-User-Role` is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/error_unauthenticated_missing_role
    """
    headers = {"X-User-ID": "admin-1", "Content-Type": "application/json"}
    resp = api.list_members(headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
