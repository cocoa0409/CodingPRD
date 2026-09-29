"""Who may act, and on which record: the role check, the ownership check and segregation of
duties, kept apart from one another.

A wrong role is not a wrong tenant, and a wrong tenant is not a wrong pair of hands. Every
refusal here is issued to an authenticated caller carrying a well-formed body, and in most cases
the identical request is shown landing once the right identity makes it.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_agreement_payload,
    create_franchisee,
    create_franchisee_payload,
    create_member,
    create_plan_template,
    create_promotion_payload,
    create_published_plan_template,
    file_relocation_request,
    inspect_club,
    make_brand_administrator_headers,
    make_club_manager_headers,
    make_franchise_owner_headers,
    make_member_headers,
    place_in_collections_payload,
    post_dues,
    post_payment,
    post_payment_failure,
    read_agreement,
    read_club,
    read_club_version,
    read_franchisee,
    read_inspection,
    read_member,
    read_plan_template,
    read_relocation_request,
    read_territory,
    relocation_decision_payload,
    request_cancellation,
    request_cancellation_payload,
    schedule_inspection,
    score_inspection_payload,
    set_clock_date,
    setup_single_club_franchise,
    sign_active_agreement,
    sign_agreement,
    submit_relocation_request,
    waive_remediation,
    waive_remediation_payload,
)

BRAND = TEST_USERS["brand_administrator_headers"]
BILLING = TEST_USERS["billing_partner_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]


def _a_club_a_member_a_draft_template_and_a_scheduled_inspection() -> dict:
    """Everything four different roles might be tempted to reach for, all of it legitimately
    present and none of it theirs to touch."""
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        opened_on="2024-05-01",
        with_plan=False,
    )
    scenario["plan_template"] = create_plan_template()
    scenario["member"] = create_member(
        scenario["club"]["id"], full_name="Ana Reyes", email="ana.reyes@example.com"
    )
    scenario["inspection"] = schedule_inspection(scenario["club"]["id"], "2026-07-15")
    return scenario


def test_a_member_cannot_create_a_franchisee_and_a_club_manager_cannot_score_an_inspection():
    """Two authenticated callers with two perfectly good bodies, each reaching for a route their
    role does not appear on.

    PRD 2.6: "2. **Role authorization.** The acting role appears in the called endpoint's
    authorized list. Otherwise `ERR_UNAUTHORIZED` (403)."

    Design: Corner/rbac/corner_four_roles_cannot_reach_another_roles_exclusive_operation
    """
    scenario = _a_club_a_member_a_draft_template_and_a_scheduled_inspection()

    validate_error(
        api_client.create_franchisee(
            create_franchisee_payload(
                legal_name="Rogue Fitness Holdings LLC", contact_email="rogue@example.com"
            ),
            make_member_headers(scenario["member"]["id"]),
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    validate_error(
        api_client.score_inspection(
            scenario["inspection"]["id"],
            score_inspection_payload(95, 95, 95, 6),
            make_club_manager_headers(scenario["club"]["id"]),
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    assert read_inspection(scenario["inspection"]["id"])["status"] == "SCHEDULED"


def test_the_billing_partner_cannot_sell_a_membership_nor_the_owner_publish_a_template():
    """The vendor that bills the dues has no authority over membership state, and the franchisee
    that sells the plans has none over the brand's own library.

    PRD 2.1: "A `BillingPartner` is the third-party dues-billing and collections vendor, which
    appends immutable ledger entries and places delinquent accounts with collections but can never
    alter pricing, membership state directly, or franchise records."

    Design: Corner/rbac/corner_four_roles_cannot_reach_another_roles_exclusive_operation
    """
    scenario = _a_club_a_member_a_draft_template_and_a_scheduled_inspection()

    payload = create_agreement_payload(
        scenario["member"]["id"],
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
        read_club_version(scenario["club"]["id"]),
        "2026-08-01",
    )
    validate_error(
        api_client.create_agreement(payload, BILLING), ApiErrorId.ERR_UNAUTHORIZED.value, 403
    )
    validate_error(
        api_client.publish_plan_template(
            scenario["plan_template"]["id"],
            {},
            make_franchise_owner_headers(scenario["franchisee"]["id"]),
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    assert read_plan_template(scenario["plan_template"]["id"])["status"] == "DRAFT"
    assert read_club(scenario["club"]["id"])["active_agreement_count"] == 0


def _an_agreement_sixty_days_delinquent() -> dict:
    """A 9000-cent charge due 2026-09-05 with 100 cents paid against it, read at 2026-11-04 —
    exactly the sixty days collections placement demands."""
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        opened_on="2024-05-01",
    )
    scenario["member"] = create_member(
        scenario["club"]["id"], full_name="Ana Reyes", email="ana.reyes@example.com"
    )
    agreement = sign_agreement(
        scenario["member"]["id"],
        scenario["club"]["id"],
        scenario["plan_template"]["id"],
        "2026-08-01",
    )
    post_dues(agreement["id"], 9000, "2026-08-01", due_on="2026-09-05")
    post_payment(agreement["id"], 100, "2026-08-02")
    set_clock_date("2026-11-04")
    post_payment_failure(agreement["id"], "2026-11-04")
    scenario["agreement"] = read_agreement(agreement["id"])
    return scenario


def _place_in_collections(agreement_id: str, headers):
    return api_client.place_in_collections(
        agreement_id,
        place_in_collections_payload(agency_reference="AGY-2026-0007"),
        headers,
    )


def test_headquarters_holds_no_override_on_the_billing_partners_collections_route():
    """The account is eligible on every substantive ground, and the caller is the role that owns
    almost every other write in the domain — and it is still the wrong role for this one.

    PRD 3.4: "Placing an account with a collections agency is the `BillingPartner`'s exclusive act
    and requires an `agency_reference` identifying the placement at the vendor."

    Design: Corner/rbac/corner_brand_administrator_cannot_place_an_agreement_in_collections
    """
    scenario = _an_agreement_sixty_days_delinquent()

    assert scenario["agreement"]["dues_status"] == "DELINQUENT"
    assert scenario["agreement"]["delinquency_days"] == 60
    validate_error(
        _place_in_collections(scenario["agreement"]["id"], BRAND),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    assert read_agreement(scenario["agreement"]["id"])["dues_status"] == "DELINQUENT"


def test_the_billing_partners_identical_placement_goes_through():
    """Nothing about the request changes except the identity behind it, which locates the whole
    refusal in the role rather than in the account's condition.

    PRD 3.4: "Placement appends a system ledger entry of type `COLLECTION_PLACED` with
    `amount_cents` 0 and `source` `SYSTEM`, leaves the club's `delinquent_member_count` untouched
    because `DELINQUENT` and `IN_COLLECTIONS` both count as delinquent, and increments the
    agreement's `version`."

    Design: Corner/rbac/corner_brand_administrator_cannot_place_an_agreement_in_collections
    """
    scenario = _an_agreement_sixty_days_delinquent()
    agreement_id = scenario["agreement"]["id"]

    validate_error(
        _place_in_collections(agreement_id, BRAND), ApiErrorId.ERR_UNAUTHORIZED.value, 403
    )
    validate_success(_place_in_collections(agreement_id, BILLING))
    assert read_agreement(agreement_id)["dues_status"] == "IN_COLLECTIONS"
    rows, _ = validate_paginated(
        api_client.list_agreement_billing_events(agreement_id, BRAND)
    )
    placements = [row for row in rows if row["event_type"] == "COLLECTION_PLACED"]
    assert len(placements) == 1
    assert placements[0]["amount_cents"] == 0
    assert placements[0]["source"] == "SYSTEM"
    assert read_club(scenario["club"]["id"])["delinquent_member_count"] == 1


def _two_franchisees_and_one_published_plan() -> dict:
    """Two peers of equal standing, and a plan template either of them may price against."""
    first = create_franchisee(
        legal_name="Harborline Fitness LLC", contact_email="ops@harborlinefit.example"
    )
    second = create_franchisee(
        legal_name="Ridgeway Athletics LLC", contact_email="ops@ridgewayath.example"
    )
    return {
        "first": first,
        "second": second,
        "plan_template": create_published_plan_template(),
    }


def _file_promotion(scenario: dict, owning_franchisee_id: str, acting_franchisee_id: str):
    return api_client.create_promotion(
        create_promotion_payload(
            owning_franchisee_id,
            scenario["plan_template"]["id"],
            code="NOTMINE1",
            discount_pct=0.1,
            starts_on="2026-09-01",
            ends_on="2026-09-30",
        ),
        make_franchise_owner_headers(acting_franchisee_id),
    )


def test_holding_the_franchise_owner_role_is_not_enough_to_price_a_peers_memberships():
    """The caller is a real franchisee acting with its own identifier; the body simply names
    somebody else's, which is a tenancy failure rather than a role failure.

    PRD 2.6: "3. **Resource ownership.** For entity-backed roles on any non-GET operation whose
    path or body names a `Territory`, `Club`, `RelocationRequest`, `Promotion`,
    `MembershipAgreement`, `TransferRequest`, `GuestUsageEvent`, or `RoyaltyReport`, the ownership
    rules of §2.1 hold. Otherwise `ERR_NOT_RESOURCE_OWNER` (403). GET operations are exempt."

    Design: Corner/rbac/corner_franchise_owner_cannot_file_a_promotion_for_another_franchisee
    """
    scenario = _two_franchisees_and_one_published_plan()

    validate_error(
        _file_promotion(scenario, scenario["second"]["id"], scenario["first"]["id"]),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
        403,
    )
    assert read_franchisee(scenario["second"]["id"])["status"] == "ACTIVE"


def test_the_same_filing_for_its_own_franchisee_is_accepted():
    """Ownership is compared field to header, so the identical body under the owner's own
    identifier is a lawful filing.

    PRD 2.1: "When `X-User-Role` is `FranchiseOwner`, `X-User-ID` is the `id` of the acting
    `Franchisee`; ownership checks on any resource that references a `Franchisee` compare the
    resource's `franchisee_id` to `X-User-ID`."

    Design: Corner/rbac/corner_franchise_owner_cannot_file_a_promotion_for_another_franchisee
    """
    scenario = _two_franchisees_and_one_published_plan()

    validate_error(
        _file_promotion(scenario, scenario["second"]["id"], scenario["first"]["id"]),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
        403,
    )
    promotion = validate_success(
        _file_promotion(scenario, scenario["first"]["id"], scenario["first"]["id"]),
        expected_status=201,
    )
    assert promotion["franchisee_id"] == scenario["first"]["id"]
    assert promotion["status"] == "PENDING_REVIEW"


def _two_members_at_one_club_and_a_live_membership_for_the_first() -> dict:
    """Ana holds the contract; Ben merely shops at the same club."""
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        opened_on="2024-05-01",
    )
    scenario["holder"] = create_member(
        scenario["club"]["id"], full_name="Ana Reyes", email="ana.reyes@example.com"
    )
    scenario["stranger"] = create_member(
        scenario["club"]["id"], full_name="Ben Oduya", email="ben.oduya@example.com"
    )
    scenario["agreement"] = sign_active_agreement(
        scenario["holder"]["id"], scenario["club"]["id"], scenario["plan_template"]["id"]
    )
    return scenario


def _cancel_as(agreement_id: str, member_id: str):
    return api_client.request_cancellation(
        agreement_id,
        request_cancellation_payload(reason="Member is moving out of state"),
        make_member_headers(member_id),
    )


def test_one_member_cannot_tear_up_another_members_contract():
    """Both callers are `Member`s of the same club, so the role check passes for each of them and
    only the named `member_id` separates the holder from the stranger.

    PRD 2.1: "When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; it
    may write against a `MembershipAgreement` only when that agreement's `member_id` equals
    `X-User-ID`."

    Design: Corner/rbac/corner_member_cannot_cancel_another_members_agreement
    """
    scenario = _two_members_at_one_club_and_a_live_membership_for_the_first()

    validate_error(
        _cancel_as(scenario["agreement"]["id"], scenario["stranger"]["id"]),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
        403,
    )
    agreement = read_agreement(scenario["agreement"]["id"])
    assert agreement["agreement_status"] == "ACTIVE"
    assert agreement["cancellation_requested_on"] is None
    assert agreement["net_settlement_cents"] is None
    assert read_member(scenario["stranger"]["id"])["agreement_count"] == 0


def test_the_holders_own_cancellation_unwinds_the_contract_inside_the_cooling_off_window():
    """The stranger's refusal is not the route refusing cancellation as such: the same call from
    the member the agreement names rescinds it on the spot and hands back every cent collected.

    PRD 3.5: "`refund_cents` is the sum of `initiation_fee_cents` and `dues_paid_cents`, which is
    every cent the club has collected. `early_termination_fee_cents` is 0, and
    `net_settlement_cents` therefore equals `refund_cents`."

    Design: Corner/rbac/corner_member_cannot_cancel_another_members_agreement
    """
    scenario = _two_members_at_one_club_and_a_live_membership_for_the_first()

    validate_error(
        _cancel_as(scenario["agreement"]["id"], scenario["stranger"]["id"]),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
        403,
    )
    cancelled = request_cancellation(scenario["agreement"]["id"], scenario["holder"]["id"])
    assert cancelled["agreement_status"] == "CANCELLED"
    assert cancelled["refund_cents"] == 9400
    assert cancelled["early_termination_fee_cents"] == 0
    assert cancelled["net_settlement_cents"] == 9400


def _a_failed_inspection_scored_by_the_first_auditor() -> dict:
    """60/60/60 against a 60-month floor on a 2024 club: 51 points, below the 70 mark, so the
    inspection needs remediation and the club is suspended."""
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        opened_on="2024-05-01",
        with_plan=False,
    )
    scenario["inspection"] = inspect_club(
        scenario["club"]["id"], "2026-07-15", 60, 60, 60, 60, auditor_id="auditor-1"
    )
    return scenario


def test_the_auditor_who_wrote_the_finding_cannot_forgive_it():
    """Both auditors hold the identical role and the identical route; the only discriminator is
    whether the acting identifier is the one already stamped on the inspection.

    PRD 3.9: "The acting `X-User-ID` may not equal `scored_by_user_id`; the same auditor
    attempting to forgive their own finding is refused with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/corner_the_auditor_who_scored_an_inspection_cannot_waive_its_remediation
    """
    scenario = _a_failed_inspection_scored_by_the_first_auditor()

    assert scenario["inspection"]["score"] == 51
    assert scenario["inspection"]["status"] == "REMEDIATION_REQUIRED"
    assert scenario["inspection"]["scored_by_user_id"] == "auditor-1"
    validate_error(
        api_client.waive_inspection_remediation(
            scenario["inspection"]["id"], waive_remediation_payload(), AUDITOR
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )
    inspection = read_inspection(scenario["inspection"]["id"])
    assert inspection["status"] == "REMEDIATION_REQUIRED"
    assert inspection["waived_by_user_id"] is None
    assert inspection["waiver_reason"] is None


def test_a_second_auditors_waiver_is_accepted_and_stamps_the_second_pair_of_hands():
    """One waiver carries two identifiers: the hand that found the fault and the different hand
    that forgave it.

    PRD 3.9: "A waiver moves `REMEDIATION_REQUIRED → REMEDIATION_WAIVED`, requires a `reason`
    which is stored as `waiver_reason`, and records `waived_by_user_id` from the `X-User-ID`
    header."

    Design: Corner/rbac/corner_the_auditor_who_scored_an_inspection_cannot_waive_its_remediation
    """
    scenario = _a_failed_inspection_scored_by_the_first_auditor()

    validate_error(
        api_client.waive_inspection_remediation(
            scenario["inspection"]["id"], waive_remediation_payload(), AUDITOR
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )
    waived = waive_remediation(
        scenario["inspection"]["id"],
        auditor_id="auditor-2",
        reason="Replacement cardio floor already on order",
    )
    assert waived["status"] == "REMEDIATION_WAIVED"
    assert waived["scored_by_user_id"] == "auditor-1"
    assert waived["waived_by_user_id"] == "auditor-2"
    assert waived["waiver_reason"] == "Replacement cardio floor already on order"


def test_the_second_auditors_waiver_reopens_the_club_without_erasing_the_record():
    """What the second pair of hands can and cannot undo: the suspension lifts, the failing score
    and the franchisee's streak stand.

    PRD 3.9: "The waiver sets the club's `equipment_compliance_state` to `WATCH` — leaving
    `last_inspection_score` untouched, because the failing score is a historical fact — and
    returns a `SUSPENDED` club to `OPEN`. It deliberately does *not* reset the franchisee's
    `inspection_fail_streak`; the franchisee's `compliance_score` is recomputed with the streak
    unchanged, so a waiver reopens the club without erasing the franchisee's record."

    Design: Corner/rbac/corner_the_auditor_who_scored_an_inspection_cannot_waive_its_remediation
    """
    scenario = _a_failed_inspection_scored_by_the_first_auditor()
    club_id = scenario["club"]["id"]

    suspended = read_club(club_id)
    assert suspended["status"] == "SUSPENDED"
    assert suspended["equipment_compliance_state"] == "NON_COMPLIANT"
    waive_remediation(scenario["inspection"]["id"], auditor_id="auditor-2")
    club = read_club(club_id)
    assert club["status"] == "OPEN"
    assert club["equipment_compliance_state"] == "WATCH"
    assert club["last_inspection_score"] == 51
    assert read_franchisee(scenario["franchisee"]["id"])["inspection_fail_streak"] == 1


def _a_submitted_relocation_request() -> dict:
    """The owner drafts a move one tenth of a degree east and submits it under its own
    identifier, which is therefore the identifier on file as the submitter."""
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        center_lat=34.0,
        center_lng=-118.0,
        protected_radius_km=5.0,
        club_name="Harborline Downtown",
        opened_on="2024-05-01",
        with_plan=False,
    )
    request = file_relocation_request(
        scenario["club"]["id"],
        scenario["franchisee"]["id"],
        requested_lat=34.0,
        requested_lng=-117.9,
        requested_radius_km=5.0,
        justification="Landlord redevelopment forces a move",
    )
    scenario["request"] = submit_relocation_request(
        request["id"], scenario["franchisee"]["id"]
    )
    return scenario


def _decide(relocation_request_id: str, headers):
    return api_client.decide_relocation_request(
        relocation_request_id,
        relocation_decision_payload(decision="APPROVE", reviewer_note="Site inspected"),
        headers,
    )


def test_borrowing_the_reviewers_role_does_not_let_the_submitter_approve_its_own_move():
    """The refusal does not read the role at all — it compares the acting identifier with the one
    already stored as the submitter, so presenting as headquarters changes nothing.

    PRD 3.1: "Segregation of duties bites here: the identifier stored as `submitted_by_user_id`
    may not decide its own request, even when it presents itself with the `BrandAdministrator`
    role, and an attempt is refused with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/corner_the_relocation_submitter_cannot_also_approve_the_request
    """
    scenario = _a_submitted_relocation_request()
    franchisee_id = scenario["franchisee"]["id"]

    assert scenario["request"]["submitted_by_user_id"] == franchisee_id
    validate_error(
        _decide(scenario["request"]["id"], make_brand_administrator_headers(franchisee_id)),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )
    request = read_relocation_request(scenario["request"]["id"])
    assert request["status"] == "SUBMITTED"
    assert request["decided_by_user_id"] is None


def test_an_independent_reviewer_approves_the_very_same_request_and_moves_the_geometry():
    """A second, unrelated operator identifier decides the request the submitter could not, and
    the territory and its club travel together to the requested coordinates.

    PRD 3.1: "When it clears, the request moves `SUBMITTED → APPROVED`, `decided_by_user_id` is
    stamped with the deciding identifier, the parent territory's `center_lat`, `center_lng` and
    `protected_radius_km` are rewritten to the requested values with `relocation_count`
    incremented by 1, and because the territory moved, the club's own `lat` and `lng` are
    rewritten to the same requested values."

    Design: Corner/rbac/corner_the_relocation_submitter_cannot_also_approve_the_request
    """
    scenario = _a_submitted_relocation_request()

    validate_error(
        _decide(
            scenario["request"]["id"],
            make_brand_administrator_headers(scenario["franchisee"]["id"]),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )
    decided = validate_success(_decide(scenario["request"]["id"], BRAND))
    assert decided["status"] == "APPROVED"
    assert decided["decided_by_user_id"] == "brand-reviewer-1"
    territory = read_territory(scenario["territory"]["id"])
    assert territory["center_lat"] == 34.0
    assert territory["center_lng"] == -117.9
    assert territory["protected_radius_km"] == 5.0
    assert territory["relocation_count"] == 1
    club = read_club(scenario["club"]["id"])
    assert club["lat"] == 34.0
    assert club["lng"] == -117.9


def _one_open_club_and_headers_for_all_six_roles() -> dict:
    """The same club, named by six callers who differ in everything except the right to read."""
    scenario = setup_single_club_franchise(
        legal_name="Harborline Fitness LLC",
        contact_email="ops@harborlinefit.example",
        club_name="Harborline Downtown",
        opened_on="2024-05-01",
        guest_fee_cents=1250,
        with_plan=False,
    )
    member = create_member(
        scenario["club"]["id"], full_name="Ana Reyes", email="ana.reyes@example.com"
    )
    scenario["member"] = member
    scenario["all_headers"] = [
        BRAND,
        make_franchise_owner_headers(scenario["franchisee"]["id"]),
        make_club_manager_headers(scenario["club"]["id"]),
        AUDITOR,
        BILLING,
        make_member_headers(member["id"]),
    ]
    return scenario


def test_every_one_of_the_six_roles_may_read_the_club():
    """One retrieval route, six callers, six 200s: the billing vendor and a single member see the
    club as plainly as its own franchisee does.

    PRD 4: "| GET | `/franchise/clubs/{id}` | Reads one club including its version for optimistic
    concurrency, equipment_compliance_state, last_inspection_score, active_agreement_count,
    delinquent_member_count, collections_watch and settlement_ledger_cents. |
    `BrandAdministrator`, `FranchiseOwner`, `ClubManager`, `ComplianceAuditor`, `BillingPartner`,
    `Member` |"

    Design: Corner/rbac/corner_all_six_roles_share_the_read_routes
    """
    scenario = _one_open_club_and_headers_for_all_six_roles()
    club_id = scenario["club"]["id"]

    assert len(scenario["all_headers"]) == 6
    for headers in scenario["all_headers"]:
        club = validate_success(api_client.get_club(club_id, headers))
        assert club["id"] == club_id
        assert club["status"] == "OPEN"
        assert club["franchisee_id"] == scenario["franchisee"]["id"]
        assert club["guest_fee_cents"] == 1250


def test_no_role_is_shown_a_narrowed_view_of_the_club():
    """Read access is not merely granted to all six roles, it is granted identically: no field is
    masked and no view is scoped to the caller's own corner of the network.

    PRD 2.1: "Read operations are never ownership-scoped: any of the six roles may read any
    resource it can name, so the visibility of a franchisee's compliance posture or a competitor's
    territory is deliberately open across the network."

    Design: Corner/rbac/corner_all_six_roles_share_the_read_routes
    """
    scenario = _one_open_club_and_headers_for_all_six_roles()
    club_id = scenario["club"]["id"]

    views = [
        validate_success(api_client.get_club(club_id, headers))
        for headers in scenario["all_headers"]
    ]
    assert len(views) == 6
    for view in views[1:]:
        assert view == views[0]
