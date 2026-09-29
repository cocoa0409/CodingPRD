"""The error catalogue read as a set of distinctions: which code, from which band, on which
route.

Four structurally identical 404s must name four different families. A request with no identity
at all never reaches the role check. Two clubs in one territory fail differently depending on
how far the first one got, and a promotion, a relocation and a transfer each have their own
way of being refused.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    build_user_headers,
    create_agreement_payload,
    create_approved_promotion,
    create_club,
    create_club_payload,
    create_franchisee_payload,
    create_member,
    create_promotion,
    create_relocation_request_payload,
    create_territory,
    create_transfer_request_payload,
    file_relocation_request,
    finalize_cancellation,
    make_club_manager_headers,
    make_franchise_owner_headers,
    make_member_headers,
    open_club,
    post_dues,
    post_payment,
    post_payment_failure,
    promotion_review_payload,
    publish_plan_template,
    read_agreement,
    read_club,
    read_club_version,
    read_member,
    read_plan_template,
    read_promotion,
    read_relocation_request,
    read_territory,
    request_cancellation,
    request_cancellation_payload,
    review_promotion,
    set_clock_date,
    setup_home_and_host_clubs,
    setup_single_club_franchise,
    sign_active_agreement,
    sign_agreement,
    withdraw_relocation_request,
)

BRAND = TEST_USERS["brand_administrator_headers"]

MISSING_TERRITORY_ID = "00000000-0000-0000-0000-0000000000a1"
MISSING_PLAN_TEMPLATE_ID = "00000000-0000-0000-0000-0000000000a2"
MISSING_AGREEMENT_ID = "00000000-0000-0000-0000-0000000000a3"
MISSING_INSPECTION_ID = "00000000-0000-0000-0000-0000000000a4"

NO_IDENTITY_HEADERS = {"Content-Type": "application/json"}


def test_the_territory_and_plan_asset_families_answer_with_their_own_codes():
    """Two well-formed identifiers the system never issued, on two routes of identical shape,
    and the 404 payload names the family rather than a generic miss.

    PRD 2.6: "The 404 codes are grouped by family: `ERR_FRANCHISEE_NOT_FOUND` for a missing
    `Franchisee`; `ERR_TERRITORY_NOT_FOUND` for a missing `Territory`; `ERR_CLUB_NOT_FOUND` for
    any missing club reference, whether it arrived as `club_id`, `home_club_id`, `host_club_id`,
    `from_club_id` or `to_club_id`; `ERR_MEMBER_NOT_FOUND` for a missing `Member`;
    `ERR_PLAN_ASSET_NOT_FOUND` for a missing `MembershipPlanTemplate`, `Promotion` or
    `CorporateAccount`"

    Design: Corner/errors/corner_each_not_found_family_returns_its_own_code
    """
    validate_error(
        api_client.get_territory(MISSING_TERRITORY_ID, BRAND),
        ApiErrorId.ERR_TERRITORY_NOT_FOUND.value,
        404,
    )
    validate_error(
        api_client.get_plan_template(MISSING_PLAN_TEMPLATE_ID, BRAND),
        ApiErrorId.ERR_PLAN_ASSET_NOT_FOUND.value,
        404,
    )


def test_the_membership_record_and_ops_record_families_answer_with_their_own_codes():
    """The remaining two families cover the contract side and the operations side of the
    network, and each keeps its own code.

    PRD 2.6: "`ERR_MEMBERSHIP_RECORD_NOT_FOUND` for a missing `MembershipAgreement`,
    `TransferRequest`, `GuestUsageEvent` or `BillingEvent`; and `ERR_OPS_RECORD_NOT_FOUND` for a
    missing `RelocationRequest`, `FacilityInspection`, `UsageSettlement` or `RoyaltyReport`."

    Design: Corner/errors/corner_each_not_found_family_returns_its_own_code
    """
    validate_error(
        api_client.get_agreement(MISSING_AGREEMENT_ID, BRAND),
        ApiErrorId.ERR_MEMBERSHIP_RECORD_NOT_FOUND.value,
        404,
    )
    validate_error(
        api_client.get_inspection(MISSING_INSPECTION_ID, BRAND),
        ApiErrorId.ERR_OPS_RECORD_NOT_FOUND.value,
        404,
    )


def test_a_write_with_no_identity_headers_is_refused_before_anything_else_is_read():
    """The body would be a perfectly good headquarters franchisee create; without an identity it
    never gets that far and no row appears.

    PRD 2.6: "1. **Authentication.** Both `X-User-ID` and `X-User-Role` are present, and
    `X-User-Role` is one of the six declared roles. Otherwise `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/errors/corner_a_request_with_no_identity_header_is_unauthenticated
    """
    payload = create_franchisee_payload(
        legal_name="Harborline Fitness LLC", contact_email="ops@harborlinefit.example"
    )

    validate_error(
        api_client.create_franchisee(payload, NO_IDENTITY_HEADERS),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )
    _, meta = validate_paginated(api_client.list_franchisees(BRAND))
    assert meta["total_count"] == 0


def test_a_read_with_no_identity_and_a_read_with_an_undeclared_role_are_both_refused():
    """Listing is open to all six roles, but only to the six: an absent identity and a role
    outside the declared set are the same failure.

    PRD 2.6: "1. **Authentication.** Both `X-User-ID` and `X-User-Role` are present, and
    `X-User-Role` is one of the six declared roles. Otherwise `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/errors/corner_a_request_with_no_identity_header_is_unauthenticated
    """
    validate_error(
        api_client.list_franchisees(NO_IDENTITY_HEADERS),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )
    invented_role = build_user_headers("facilities-vendor-1", "FacilitiesVendor")
    validate_error(
        api_client.list_franchisees(invented_role),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )


def _one_pre_opening_club_in_a_reserved_territory() -> dict:
    """A single granted territory holding one club shell that has not yet been brought into
    service, so the territory is still RESERVED."""
    return setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        opened_on="2024-05-01",
        open_the_club=False,
        with_plan=False,
    )


def _build_a_second_club(scenario: dict):
    payload = create_club_payload(
        scenario["territory"]["id"], name="Harborline Downtown Annex", opened_on="2024-07-01"
    )
    return api_client.create_club(
        payload, make_franchise_owner_headers(scenario["franchisee"]["id"])
    )


def test_a_second_shell_in_a_reserved_territory_is_refused_as_occupied():
    """The first club has not opened yet, so the territory is merely occupied rather than in
    service, and that is the code the caller gets.

    PRD 3.1: "Exactly one club may inhabit a territory, and the refusal depends on how the
    territory got occupied: a `RESERVED` territory that already holds a `PRE_OPENING` shell is
    refused with `ERR_TERRITORY_OCCUPIED`, whereas a territory that has already reached `ACTIVE`
    because its club opened is caught by the earlier state band and refused with
    `ERR_INVALID_TERRITORY_STATE`."

    Design: Corner/errors/corner_occupied_and_already_active_territories_are_rejected_differently
    """
    scenario = _one_pre_opening_club_in_a_reserved_territory()

    assert scenario["club"]["status"] == "PRE_OPENING"
    assert read_territory(scenario["territory"]["id"])["status"] == "RESERVED"
    validate_error(
        _build_a_second_club(scenario), ApiErrorId.ERR_TERRITORY_OCCUPIED.value, 409
    )


def test_once_the_club_opens_the_same_attempt_fails_on_the_earlier_state_band():
    """Opening the club flips the territory to ACTIVE, and from there a new shell is not an
    occupancy clash but a transition that no longer exists.

    PRD 2.6: "only a `RESERVED` territory may take a new club shell, so a territory that has
    already reached `ACTIVE` because its club opened is refused with
    `ERR_INVALID_TERRITORY_STATE`"

    Design: Corner/errors/corner_occupied_and_already_active_territories_are_rejected_differently
    """
    scenario = _one_pre_opening_club_in_a_reserved_territory()

    open_club(scenario["club"]["id"], scenario["franchisee"]["id"])
    assert read_territory(scenario["territory"]["id"])["status"] == "ACTIVE"
    response = _build_a_second_club(scenario)
    validate_error(response, ApiErrorId.ERR_INVALID_TERRITORY_STATE.value, 409)


def _an_open_club_and_a_member_with_the_plan_left_in_draft() -> dict:
    """Everything needed to sell a membership except a published template."""
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        opened_on="2024-05-01",
        publish_plan=False,
    )
    scenario["member"] = create_member(
        scenario["club"]["id"], full_name="Ana Reyes", email="ana.reyes@example.com"
    )
    return scenario


def _sign(scenario: dict, **overrides):
    payload = create_agreement_payload(
        scenario["member"]["id"],
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
        read_club_version(scenario["club"]["id"]),
        "2026-08-01",
        **overrides,
    )
    return api_client.create_agreement(
        payload, make_club_manager_headers(scenario["club"]["id"])
    )


def test_a_draft_template_cannot_back_a_membership():
    """The club is open, the member exists and the club version is fresh, so the only thing left
    to object to is the template's own status.

    PRD 3.3: "The references supplied must cohere with each other and with the current state of
    the world. Exactly one plan template participates and it must be `PUBLISHED`, otherwise
    `ERR_PLAN_NOT_PUBLISHED`."

    Design: Corner/errors/corner_agreement_on_a_draft_plan_template_is_rejected
    """
    scenario = _an_open_club_and_a_member_with_the_plan_left_in_draft()

    validate_error(_sign(scenario), ApiErrorId.ERR_PLAN_NOT_PUBLISHED.value, 409)
    assert read_plan_template(scenario["plan_template"]["id"])["status"] == "DRAFT"
    assert read_club(scenario["club"]["id"])["active_agreement_count"] == 0


def test_publishing_that_same_template_makes_the_identical_request_land():
    """Nothing else about the request changes, which locates the whole refusal in the template's
    unpublished state.

    PRD 3.2: "Only a `PUBLISHED` template may back a promotion or a membership agreement, and
    citing a `DRAFT` one is refused with `ERR_PLAN_NOT_PUBLISHED`."

    Design: Corner/errors/corner_agreement_on_a_draft_plan_template_is_rejected
    """
    scenario = _an_open_club_and_a_member_with_the_plan_left_in_draft()

    validate_error(_sign(scenario), ApiErrorId.ERR_PLAN_NOT_PUBLISHED.value, 409)
    publish_plan_template(scenario["plan_template"]["id"])
    agreement = validate_success(_sign(scenario), expected_status=201)
    assert agreement["plan_template_id"] == scenario["plan_template"]["id"]
    assert agreement["agreement_status"] == "PENDING"


def _an_already_approved_promotion() -> dict:
    """One filed discount that headquarters has already waved through."""
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        opened_on="2024-05-01",
    )
    scenario["promotion"] = create_promotion(
        scenario["franchisee"]["id"],
        scenario["plan_template"]["id"],
        code="FALL125",
        discount_pct=0.125,
        starts_on="2026-09-01",
        ends_on="2026-09-30",
    )
    scenario["reviewed"] = review_promotion(scenario["promotion"]["id"], "APPROVE")
    return scenario


def _review_again(scenario: dict, decision: str = "REJECT"):
    return api_client.review_promotion(
        scenario["promotion"]["id"],
        promotion_review_payload(decision=decision, note="Changed our mind."),
        BRAND,
    )


def test_brand_review_is_a_one_shot_decision():
    """The promotion has already left PENDING_REVIEW, so a second review — even one flipping the
    decision — has no transition to take.

    PRD 3.2: "Brand governance then reviews the filing with a `decision` of `APPROVE` or `REJECT`
    and an optional `note`, moving it `PENDING_REVIEW → APPROVED` or `PENDING_REVIEW → REJECTED`;
    either decision stamps `reviewed_by_user_id` with the reviewing identifier and increments the
    promotion's `version`. Reviewing a promotion that is not in `PENDING_REVIEW` is refused with
    `ERR_INVALID_PROMOTION_STATE`."

    Design: Corner/errors/corner_reviewing_an_already_approved_promotion_is_rejected
    """
    scenario = _an_already_approved_promotion()

    assert scenario["reviewed"]["status"] == "APPROVED"
    validate_error(
        _review_again(scenario), ApiErrorId.ERR_INVALID_PROMOTION_STATE.value, 409
    )
    assert read_promotion(scenario["promotion"]["id"])["status"] == "APPROVED"


def test_the_refused_second_review_leaves_the_first_decision_exactly_as_it_stood():
    """The stamp and the version belong to the decision that actually happened; the rejected
    attempt adds nothing.

    PRD 3.2: "either decision stamps `reviewed_by_user_id` with the reviewing identifier and
    increments the promotion's `version`"

    Design: Corner/errors/corner_reviewing_an_already_approved_promotion_is_rejected
    """
    scenario = _an_already_approved_promotion()
    before = read_promotion(scenario["promotion"]["id"])

    _review_again(scenario, decision="APPROVE")
    after = read_promotion(scenario["promotion"]["id"])
    assert after["reviewed_by_user_id"] == "brand-reviewer-1"
    assert after["version"] == before["version"]
    assert after["withdrawn_reason"] is None


def _an_approved_promotion_whose_window_has_closed() -> dict:
    """A lawful 12.5 percent discount whose quotable window ran through June only."""
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        opened_on="2024-05-01",
    )
    scenario["promotion"] = create_approved_promotion(
        scenario["franchisee"]["id"],
        scenario["plan_template"]["id"],
        code="JUNE125",
        discount_pct=0.125,
        starts_on="2026-06-01",
        ends_on="2026-06-30",
    )
    scenario["member"] = create_member(
        scenario["club"]["id"], full_name="Ana Reyes", email="ana.reyes@example.com"
    )
    return scenario


def test_an_expired_promotion_invalidates_the_signing_rather_than_being_ignored():
    """The clock stands on 2026-08-01 and the window closed on 2026-06-30, so the quote is not
    silently dropped — the whole request falls.

    PRD 3.3: "its closed `starts_on` through `ends_on` window must contain the logical clock
    date, or the request is refused with `ERR_PROMOTION_WINDOW_CLOSED`"

    Design: Corner/errors/corner_agreement_signed_outside_the_promotion_window_is_rejected
    """
    scenario = _an_approved_promotion_whose_window_has_closed()

    response = _sign(scenario, promotion_id=scenario["promotion"]["id"])
    validate_error(response, ApiErrorId.ERR_PROMOTION_WINDOW_CLOSED.value, 409)
    assert read_promotion(scenario["promotion"]["id"])["status"] == "APPROVED"
    assert read_club(scenario["club"]["id"])["active_agreement_count"] == 0


def test_a_promotion_whose_window_covers_the_clock_date_prices_the_membership():
    """The same discount over a window that contains 2026-08-01 takes 563 cents off the 4500-cent
    list price, which is what the refused quote would have done.

    PRD 3.3: "`promo_discount_cents` is 0 when no `promotion_id` was quoted and otherwise the
    base multiplied by the promotion's `discount_pct`, rounded half up"

    Design: Corner/errors/corner_agreement_signed_outside_the_promotion_window_is_rejected
    """
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        opened_on="2024-05-01",
    )
    scenario["promotion"] = create_approved_promotion(
        scenario["franchisee"]["id"],
        scenario["plan_template"]["id"],
        code="AUG125",
        discount_pct=0.125,
        starts_on="2026-07-28",
        ends_on="2026-08-05",
    )
    scenario["member"] = create_member(
        scenario["club"]["id"], full_name="Ana Reyes", email="ana.reyes@example.com"
    )

    agreement = validate_success(
        _sign(scenario, promotion_id=scenario["promotion"]["id"]), expected_status=201
    )
    assert agreement["monthly_dues_base_cents"] == 4500
    assert agreement["promo_discount_cents"] == 563
    assert agreement["effective_monthly_dues_cents"] == 3937


def _a_club_with_one_draft_relocation_request() -> dict:
    """An open club whose owner has drafted, but not submitted, a proposal to move it."""
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        opened_on="2024-05-01",
        with_plan=False,
    )
    scenario["relocation_request"] = file_relocation_request(
        scenario["club"]["id"],
        scenario["franchisee"]["id"],
        requested_lat=34.05,
        requested_lng=-118.02,
        requested_radius_km=5.0,
        justification="Lease expiry at the current site.",
    )
    return scenario


def _file_a_second_relocation(scenario: dict):
    payload = create_relocation_request_payload(
        scenario["club"]["id"],
        requested_lat=34.08,
        requested_lng=-118.04,
        requested_radius_km=5.0,
        justification="A second candidate site.",
    )
    return api_client.create_relocation_request(
        payload, make_franchise_owner_headers(scenario["franchisee"]["id"])
    )


def test_a_club_may_only_have_one_relocation_request_open_at_a_time():
    """The first proposal is still a draft — unsubmitted and unscored — and that alone is enough
    to block a rival proposal for the same club.

    PRD 3.1: "The draft is created in `DRAFT` with `revision_count` at 0, and only one request
    per club may be open at a time: a second draft is refused with `ERR_RELOCATION_PENDING` while
    an existing request is in `DRAFT`, `SUBMITTED` or `CHANGES_REQUESTED`."

    Design: Corner/errors/corner_second_open_relocation_request_for_one_club_is_rejected
    """
    scenario = _a_club_with_one_draft_relocation_request()

    validate_error(
        _file_a_second_relocation(scenario), ApiErrorId.ERR_RELOCATION_PENDING.value, 409
    )
    first = read_relocation_request(scenario["relocation_request"]["id"])
    assert first["status"] == "DRAFT"
    assert first["revision_count"] == 0
    assert read_territory(scenario["territory"]["id"])["relocation_count"] == 0


def test_withdrawing_the_open_request_frees_the_club_to_draft_another():
    """The block is on openness rather than on history, so abandoning the first proposal lets the
    second one through.

    PRD 3.1: "The franchisee may also abandon its own request, moving it `DRAFT → WITHDRAWN` or
    `CHANGES_REQUESTED → WITHDRAWN` with an optional `reason`, which frees the club to draft a
    fresh one."

    Design: Corner/errors/corner_second_open_relocation_request_for_one_club_is_rejected
    """
    scenario = _a_club_with_one_draft_relocation_request()

    withdrawn = withdraw_relocation_request(
        scenario["relocation_request"]["id"], scenario["franchisee"]["id"]
    )
    assert withdrawn["status"] == "WITHDRAWN"
    second = validate_success(_file_a_second_relocation(scenario), expected_status=201)
    assert second["status"] == "DRAFT"
    assert second["club_id"] == scenario["club"]["id"]


def _three_open_clubs_and_one_membership_at_the_first() -> dict:
    """One franchisee running three open California clubs, with a paid-up membership homed at
    the first of them."""
    scenario = setup_home_and_host_clubs(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        home_club_name="Harborline Downtown",
        host_club_name="Harborline Northside",
    )
    franchisee_id = scenario["franchisee"]["id"]
    third_territory = create_territory(
        franchisee_id,
        center_lat=34.6,
        center_lng=-118.0,
        protected_radius_km=5.0,
        state_code="CA",
    )
    third_club = create_club(
        third_territory["id"],
        franchisee_id,
        name="Harborline Foothills",
        opened_on="2024-07-01",
        guest_fee_cents=1250,
    )
    scenario["third_club"] = open_club(third_club["id"], franchisee_id)
    scenario["member"] = create_member(
        scenario["home_club"]["id"], full_name="Ana Reyes", email="ana.reyes@example.com"
    )
    scenario["agreement"] = sign_active_agreement(
        scenario["member"]["id"],
        scenario["home_club"]["id"],
        scenario["plan_template"]["id"],
        due_on="2026-09-05",
    )
    return scenario


def _file_transfer(scenario: dict, from_club_id: str, to_club_id: str, acting_club_id: str):
    agreement_id = scenario["agreement"]["id"]
    payload = create_transfer_request_payload(
        agreement_id,
        from_club_id,
        to_club_id,
        read_agreement(agreement_id)["version"],
        reason="Member relocated across town.",
    )
    return api_client.create_transfer_request(
        payload, make_club_manager_headers(acting_club_id)
    )


def test_a_transfer_to_the_clubs_own_home_club_is_refused_as_a_same_club_move():
    """Both club references are well formed and both name the agreement's own home, which is
    exactly the degenerate move the route has a code for.

    PRD 3.6: "The supplied `from_club_id` must equal the agreement's current `home_club_id`,
    otherwise `ERR_HOME_CLUB_MISMATCH`. The two clubs must differ, otherwise
    `ERR_SAME_CLUB_TRANSFER`."

    Design: Corner/errors/corner_transfer_endpoints_reject_same_club_and_foreign_home_club
    """
    scenario = _three_open_clubs_and_one_membership_at_the_first()
    home_club_id = scenario["home_club"]["id"]

    response = _file_transfer(scenario, home_club_id, home_club_id, home_club_id)
    validate_error(response, ApiErrorId.ERR_SAME_CLUB_TRANSFER.value, 409)
    agreement = read_agreement(scenario["agreement"]["id"])
    assert agreement["home_club_id"] == home_club_id
    assert agreement["transfer_count"] == 0


def test_a_transfer_filed_from_a_club_that_is_not_the_home_club_is_refused():
    """The second club releases a membership it never held, and the two named clubs do differ,
    so the mismatch is what the route reports and nothing is recorded.

    PRD 3.6: "Opening the request is gated on five things beyond ownership and concurrency. The
    supplied `from_club_id` must equal the agreement's current `home_club_id`, otherwise
    `ERR_HOME_CLUB_MISMATCH`."

    Design: Corner/errors/corner_transfer_endpoints_reject_same_club_and_foreign_home_club
    """
    scenario = _three_open_clubs_and_one_membership_at_the_first()
    sibling_club_id = scenario["host_club"]["id"]

    response = _file_transfer(
        scenario, sibling_club_id, scenario["third_club"]["id"], sibling_club_id
    )
    validate_error(response, ApiErrorId.ERR_HOME_CLUB_MISMATCH.value, 409)
    _, meta = validate_paginated(api_client.list_transfer_requests(BRAND))
    assert meta["total_count"] == 0
    assert read_agreement(scenario["agreement"]["id"])["transfer_count"] == 0


def _a_delinquent_membership_with_a_sibling_club_to_move_to() -> dict:
    """A membership that paid one cent short of nothing on a 9000-cent charge, left to rot until
    the clock stands a month past the due date."""
    scenario = setup_home_and_host_clubs(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        home_club_name="Harborline Downtown",
        host_club_name="Harborline Northside",
    )
    scenario["member"] = create_member(
        scenario["home_club"]["id"], full_name="Ana Reyes", email="ana.reyes@example.com"
    )
    agreement = sign_agreement(
        scenario["member"]["id"],
        scenario["home_club"]["id"],
        scenario["plan_template"]["id"],
        "2026-08-01",
    )
    post_dues(agreement["id"], 9000, "2026-08-01", due_on="2026-09-05")
    post_payment(agreement["id"], 100, "2026-08-02")
    set_clock_date("2026-10-05")
    post_payment_failure(agreement["id"], "2026-10-05")
    scenario["agreement"] = read_agreement(agreement["id"])
    return scenario


def test_a_delinquent_member_cannot_cancel_their_way_out_of_the_arrears():
    """Thirty days past due on 8900 cents, the membership is DELINQUENT, and the member's own
    cancellation right is the thing the arrears close off.

    PRD 3.5: "It is available only from `ACTIVE`, and it is barred while the collections dimension
    is `DELINQUENT`, `IN_COLLECTIONS` or `WRITTEN_OFF`: a member cannot walk away from arrears,
    and the attempt is refused with `ERR_CANCELLATION_BLOCKED_BY_ARREARS`."

    Design: Corner/errors/corner_arrears_block_both_cancellation_and_transfer
    """
    scenario = _a_delinquent_membership_with_a_sibling_club_to_move_to()
    agreement_id = scenario["agreement"]["id"]

    assert scenario["agreement"]["dues_status"] == "DELINQUENT"
    assert scenario["agreement"]["outstanding_balance_cents"] == 8900
    response = api_client.request_cancellation(
        agreement_id,
        request_cancellation_payload(reason="Wants out while in arrears."),
        make_member_headers(scenario["member"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CANCELLATION_BLOCKED_BY_ARREARS.value, 409)
    after = read_agreement(agreement_id)
    assert after["agreement_status"] == "ACTIVE"
    assert after["cancellation_requested_on"] is None


def test_the_same_delinquent_membership_cannot_be_handed_to_a_sibling_club():
    """The destination is the franchisee's own open, compliant second club and the versions are
    fresh, so the arrears are the only thing standing in the way — under a different code.

    PRD 3.6: "Finally, a membership in arrears cannot be handed off: a `dues_status` of
    `DELINQUENT`, `IN_COLLECTIONS` or `WRITTEN_OFF` is refused with
    `ERR_TRANSFER_BLOCKED_BY_ARREARS`."

    Design: Corner/errors/corner_arrears_block_both_cancellation_and_transfer
    """
    scenario = _a_delinquent_membership_with_a_sibling_club_to_move_to()
    agreement_id = scenario["agreement"]["id"]

    payload = create_transfer_request_payload(
        agreement_id,
        scenario["home_club"]["id"],
        scenario["host_club"]["id"],
        read_agreement(agreement_id)["version"],
        reason="Wants to move while in arrears.",
    )
    response = api_client.create_transfer_request(
        payload, make_club_manager_headers(scenario["home_club"]["id"])
    )
    validate_error(response, ApiErrorId.ERR_TRANSFER_BLOCKED_BY_ARREARS.value, 409)
    assert read_agreement(agreement_id)["agreement_status"] == "ACTIVE"


def _a_cancellation_waiting_out_its_thirty_day_notice() -> dict:
    """A California membership sold on 2026-08-01 and cancelled on 2026-08-20 — well past the
    five-day rescission window, so the member owes thirty days' notice."""
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        opened_on="2024-05-01",
    )
    scenario["member"] = create_member(
        scenario["club"]["id"], full_name="Ana Reyes", email="ana.reyes@example.com"
    )
    scenario["agreement"] = sign_active_agreement(
        scenario["member"]["id"],
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
        due_on="2026-09-05",
    )
    set_clock_date("2026-08-20")
    scenario["cancellation"] = request_cancellation(
        scenario["agreement"]["id"],
        scenario["member"]["id"],
        reason="Thirty days' written notice.",
    )
    return scenario


def _finalize(scenario: dict):
    return api_client.finalize_cancellation(
        scenario["agreement"]["id"],
        {"note": "Trying to close it out early."},
        make_club_manager_headers(scenario["club"]["id"]),
    )


def test_a_notice_period_cancellation_cannot_be_closed_out_on_the_day_it_was_requested():
    """The effective date is a month away, so the home club's own manager, acting correctly on a
    correctly pending cancellation, still has no transition to take.

    PRD 3.5: "It requires that the logical clock date has reached `cancellation_effective_on`;
    earlier attempts are refused with `ERR_NOTICE_PERIOD_NOT_ELAPSED`, and the boundary is
    inclusive, so the operation succeeds on the effective date itself."

    Design: Corner/errors/corner_finalizing_a_cancellation_before_the_notice_elapses_is_rejected
    """
    scenario = _a_cancellation_waiting_out_its_thirty_day_notice()

    validate_error(_finalize(scenario), ApiErrorId.ERR_NOTICE_PERIOD_NOT_ELAPSED.value, 409)
    agreement = read_agreement(scenario["agreement"]["id"])
    assert agreement["agreement_status"] == "CANCELLATION_PENDING"
    assert read_club(scenario["club"]["id"])["active_agreement_count"] == 1


def test_the_pending_cancellation_carries_its_effective_date_and_a_zero_refund():
    """Thirty days from the 2026-08-20 request lands on 2026-09-19, which is later than the
    2026-08-31 the member has pre-paid through, so there is nothing to give back.

    PRD 3.5: "`cancellation_effective_on` becomes the logical clock date plus the agreement's
    pinned `cancellation_notice_days`. The refund calculation asks how far the member has
    pre-paid: the number of fully paid periods is `dues_paid_cents` divided by
    `effective_monthly_dues_cents`, discarding any fraction, and the paid-through date is
    `signed_on` plus 30 days multiplied by that number of periods. The unused days are the whole
    days from `cancellation_effective_on` to the paid-through date. When the governing statute
    prorates on cancellation — `CA` and `TX` do, `NY` does not — and the unused days are greater
    than 0, `refund_cents` is `effective_monthly_dues_cents` multiplied by those unused days,
    divided by 30, rounded half up to whole cents. In every other case, including any `NY`
    agreement and any case where the paid-through date is on or before the effective date,
    `refund_cents` is 0."

    Design: Corner/errors/corner_finalizing_a_cancellation_before_the_notice_elapses_is_rejected
    """
    scenario = _a_cancellation_waiting_out_its_thirty_day_notice()

    _finalize(scenario)
    agreement = read_agreement(scenario["agreement"]["id"])
    assert agreement["cancellation_requested_on"] == "2026-08-20"
    assert agreement["cancellation_effective_on"] == "2026-09-19"
    assert agreement["dues_paid_cents"] == 4500
    assert agreement["refund_cents"] == 0


def test_the_early_termination_fee_is_already_pinned_at_the_cap():
    """Eleven unexpired months at 2250 cents a month comes to 24750, which the 15000-cent cap
    cuts down, and with no refund the member ends up owing that whole sum.

    PRD 3.5: "The monthly charge is `effective_monthly_dues_cents` multiplied by 0.5 — half a
    month's dues — rounded half up to whole cents, and that rounded monthly figure is then
    multiplied by the remaining months. Only after the multiplication is the cap applied:
    `early_termination_fee_cents` is the lesser of that product and 15000 cents. Rounding the
    product instead of the monthly charge, or applying the cap per month instead of to the total,
    produces a different figure and is wrong. `net_settlement_cents` is then `refund_cents` minus
    `early_termination_fee_cents`, and a negative result is meaningful: it means the member owes
    the club rather than the reverse."

    Design: Corner/errors/corner_finalizing_a_cancellation_before_the_notice_elapses_is_rejected
    """
    scenario = _a_cancellation_waiting_out_its_thirty_day_notice()

    validate_error(_finalize(scenario), ApiErrorId.ERR_NOTICE_PERIOD_NOT_ELAPSED.value, 409)
    agreement = read_agreement(scenario["agreement"]["id"])
    assert agreement["effective_monthly_dues_cents"] == 4500
    assert agreement["early_termination_fee_cents"] == 15000
    assert agreement["net_settlement_cents"] == -15000


def test_on_the_effective_date_itself_the_same_finalization_lands_and_cascades():
    """The refusal was purely about the clock: moved to 2026-09-19, the identical call closes the
    membership and takes it out of every count that held it.

    PRD 3.5: "Finalization fires exactly the same cascade the cooling-off branch fired: the club's
    `active_agreement_count` decreases by 1 with `delinquent_member_count` and `collections_watch`
    recomputed, the franchisee's `compliance_score` recomputed, the member's `agreement_count`
    decreased by 1 with a flip to `INACTIVE` at zero, the corporate account's enrolled agreement
    count recomputed where applicable, and a `version` increment on the agreement, the club and
    the member."

    Design: Corner/errors/corner_finalizing_a_cancellation_before_the_notice_elapses_is_rejected
    """
    scenario = _a_cancellation_waiting_out_its_thirty_day_notice()
    validate_error(_finalize(scenario), ApiErrorId.ERR_NOTICE_PERIOD_NOT_ELAPSED.value, 409)

    set_clock_date("2026-09-19")
    finalized = finalize_cancellation(
        scenario["agreement"]["id"], scenario["club"]["id"]
    )
    assert finalized["agreement_status"] == "CANCELLED"
    assert read_club(scenario["club"]["id"])["active_agreement_count"] == 0
    member = read_member(scenario["member"]["id"])
    assert member["agreement_count"] == 0
    assert member["status"] == "INACTIVE"
