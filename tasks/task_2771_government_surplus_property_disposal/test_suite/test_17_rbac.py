"""PRD compliance — role-based access control, ownership scope and segregation
of duties.

Three distinct mechanisms guard the write paths and they answer with three
different identifiers: a caller outside an endpoint's authorised-role list is
refused with ERR_UNAUTHORIZED, an entity-backed caller reaching another
organisation's or another bidder's row is refused with the matching scope code,
and a caller in the right role whose own user id already appears on an earlier
step of the same chain is refused with ERR_SEGREGATION_OF_DUTIES. Every refusal
here is followed by a re-read proving the target row was not mutated.
"""

from test_helpers import (
    ASSESSOR_USER_ID,
    FINANCE_USER_ID,
    NON_EXISTENT_UUID,
    SECOND_ASSESSOR_USER_ID,
    SECOND_OFFICER_USER_ID,
    TECHNICIAN_USER_ID,
    TEST_USERS,
    ApiErrorId,
    add_asset,
    add_asset_with_payload,
    assess_asset,
    create_asset_payload,
    create_bid_payload,
    create_bidder_payload,
    create_clearance_certificate_payload,
    create_condition_assessment_payload,
    create_draft_turn_in,
    create_it_asset_payload,
    create_proceeds_distribution_payload,
    create_turn_in_payload,
    get_success_data,
    make_agency_officer_headers,
    make_bidder_headers,
    make_clearance_technician_headers,
    make_finance_controller_headers,
    read_agency,
    read_asset,
    read_bidder,
    read_distribution,
    read_lot,
    read_turn_in,
    register_bidder,
    register_state_agency,
    register_venue,
    set_clock,
    setup_assessed_asset,
    setup_calculated_distribution,
    setup_open_lot,
    setup_open_lot_with_bidder,
    submit_turn_in,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
ASSESSOR = TEST_USERS["surplus_assessor_headers"]
OFFICER = TEST_USERS["disposal_officer_headers"]
TECHNICIAN = TEST_USERS["clearance_technician_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]


class TestExclusiveOperations:
    """Endpoints declared for a single role, refused to every other role."""

    def test_only_the_surplus_assessor_may_record_a_condition_assessment(self, api):
        """PRD §2.1: "Once the caller is authenticated, the role must appear in
        the authorised-role list of the endpoint being called, as tabulated in
        §4; a role calling an endpoint it is not listed for is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.1: "A `SurplusAssessor` assigns federal condition codes and repair
        estimates."
        PRD §2.1: "A `ProgramAdmin` is the agency administrator: it maintains the
        participant registry, federal donee certifications, auction venues and
        bidder registrations, and reads everything, but it never appraises
        property, never certifies a clearance, never awards property and never
        posts money."
        PRD §3.3: "A `SurplusAssessor` inspects the property and records a
        **condition assessment** against a named asset."
        PRD §3.3: "The server stamps `assessor_user_id` from the caller's
        `X-User-ID` and records `asset_id` as the asset addressed in the path."
        PRD §3.3: "The first assessment on an asset drives `disposition_status`
        from `INTAKE` to `ASSESSED`."

        Design: Corner/rbac/rbac_condition_assessment_exclusive_others_cannot_file
        """
        set_clock()
        agency = register_state_agency()
        turn_in = create_draft_turn_in(agency["id"])
        asset = add_asset(
            agency["id"],
            turn_in["id"],
            description="Modular workstation cluster",
            acquisition_cost_cents=1000000,
            acquisition_date="2026-01-10",
        )
        submit_turn_in(agency["id"], turn_in["id"])
        assert asset["version"] == 1, (
            f"the asset must start at version 1, got {asset['version']}"
        )

        payload = create_condition_assessment_payload(
            asset["version"],
            condition_code="C1",
            functional=True,
            repair_cost_estimate_cents=0,
            assessed_on="2026-07-31",
        )
        refusals = {
            "ProgramAdmin": ADMIN,
            "DisposalOfficer": OFFICER,
            "ClearanceTechnician": TECHNICIAN,
            "AgencyOfficer": make_agency_officer_headers(agency["id"]),
        }
        for role, headers in refusals.items():
            response = api.create_condition_assessment(
                asset["id"], payload, headers
            )
            assert response.status_code == 403, (
                f"a {role} is not listed for condition-assessment recording and "
                f"must be answered HTTP 403, got {response.status_code}"
            )
            validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)

        after_refusals = read_asset(asset["id"])
        assert after_refusals["version"] == 1, (
            "four refused appraisals must leave the asset at version 1, got "
            f"{after_refusals['version']}"
        )
        assert after_refusals["condition_code"] is None, (
            "no refused appraisal may set condition_code, got "
            f"{after_refusals['condition_code']!r}"
        )
        assert after_refusals["fair_market_value_cents"] is None, (
            "no refused appraisal may set fair_market_value_cents, got "
            f"{after_refusals['fair_market_value_cents']!r}"
        )
        _, refused_meta = validate_paginated(
            api.list_condition_assessments(asset["id"], ADMIN)
        )
        assert refused_meta["total_count"] == 0, (
            f"no assessment row may exist yet, got {refused_meta['total_count']}"
        )

        # The refusals consumed no version, so the assessor reuses the same
        # expected_asset_version.
        accepted = api.create_condition_assessment(asset["id"], payload, ASSESSOR)
        assessment = validate_success(accepted, 201)
        assert assessment["assessor_user_id"] == ASSESSOR_USER_ID, (
            "assessor_user_id must be stamped from the caller's X-User-ID, got "
            f"{assessment['assessor_user_id']!r}"
        )
        assert assessment["superseded"] is False, (
            "the first assessment on an asset is the governing one and is not "
            f"superseded, got {assessment['superseded']!r}"
        )

        appraised = read_asset(asset["id"])
        assert appraised["condition_code"] == "C1", (
            f"condition_code must be C1, got {appraised['condition_code']!r}"
        )
        assert appraised["fair_market_value_cents"] == 1000000, (
            "an acquisition cost of 1000000 at C1, functional, with no repair "
            "estimate and inside the first depreciation year must value at "
            f"1000000, got {appraised['fair_market_value_cents']}"
        )
        assert appraised["disposition_status"] == "ASSESSED", (
            "the first assessment drives INTAKE to ASSESSED, got "
            f"{appraised['disposition_status']!r}"
        )
        assert appraised["version"] == 2, (
            f"the accepted assessment increments version to 2, got {appraised['version']}"
        )
        _, accepted_meta = validate_paginated(
            api.list_condition_assessments(asset["id"], ADMIN)
        )
        assert accepted_meta["total_count"] == 1, (
            "exactly one assessment row must exist, got "
            f"{accepted_meta['total_count']}"
        )

    def test_disposal_officer_writes_are_refused_to_every_other_role(self, api):
        """PRD §2.1: "Once the caller is authenticated, the role must appear in
        the authorised-role list of the endpoint being called, as tabulated in
        §4; a role calling an endpoint it is not listed for is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.1: "A `DisposalOfficer` reviews turn-ins, runs the screening
        ladder, issues and voids transfer documents, lists, opens and closes
        auction lots, and releases custody."
        PRD §2.12: "When several rules could reject the same request, the
        **first** rule violated in the order below determines the response, and
        no later rule is evaluated."
        PRD §2.12: "The acting role appears in the called endpoint's
        authorised-role list — otherwise `ERR_UNAUTHORIZED` (403)."
        PRD §2.12: "Generic state preconditions, including every attempt from a
        terminal state and every repeat of an already-applied trigger:
        `ERR_INVALID_STATE` (409), followed by the specialised state codes
        `ERR_TURN_IN_NOT_DRAFT`, `ERR_LOT_NOT_OPEN`, `ERR_ASSET_NOT_ASSESSABLE`,
        `ERR_BIDDER_NOT_REGISTERED`, `ERR_AGENCY_SUSPENDED`,
        `ERR_ASSET_NOT_DISPOSABLE`, `ERR_TURN_IN_NOT_ASSESSED` and
        `ERR_VENUE_CLOSED`, in that order."
        PRD §3.2: "A `DisposalOfficer` then reviews the submitted turn-in,
        supplying a `decision` of either `ACCEPT` or `REJECT`."
        PRD §3.2: "Acceptance moves `status` from `SUBMITTED` to `ACCEPTED`,
        stamps `reviewed_at` from the logical clock, recomputes
        `appraised_total_cents`, and increments the turn-in's `version` by 1."

        Design: Corner/rbac/rbac_disposal_officer_actions_forbidden_to_other_roles
        """
        scenario = setup_assessed_asset(kind="furniture", accept=False)
        agency = scenario["agency"]
        turn_in = scenario["turn_in"]
        asset = scenario["asset"]
        venue = register_venue(name="Austin Auction Yard", venue_code="AUS-01")

        assert asset["fair_market_value_cents"] == 12540, (
            "the appraised furniture must value at 12540, got "
            f"{asset['fair_market_value_cents']}"
        )
        assert turn_in["status"] == "SUBMITTED", (
            f"the turn-in must start SUBMITTED, got {turn_in['status']!r}"
        )

        review_attempt = api.review_turn_in(
            turn_in["id"], {"decision": "ACCEPT"}, ADMIN
        )
        validate_error(review_attempt, ApiErrorId.ERR_UNAUTHORIZED)

        # The role check precedes the disposability check that would otherwise
        # refuse this de-minimis asset.
        cycle_attempt = api.create_screening_cycle(
            {
                "asset_id": asset["id"],
                "opens_at": "2026-08-02T00:00:00Z",
                "tier_window_days": 3,
            },
            ADMIN,
        )
        assert cycle_attempt.status_code == 403, (
            "a ProgramAdmin is not listed for screening-cycle creation, so the "
            "role refusal is answered before any state precondition, got "
            f"{cycle_attempt.status_code}"
        )
        validate_error(cycle_attempt, ApiErrorId.ERR_UNAUTHORIZED)

        lot_attempt = api.create_auction_lot(
            {
                "asset_id": asset["id"],
                "venue_id": venue["id"],
                "opens_at": "2026-08-02T00:00:00Z",
                "closes_at": "2026-08-03T00:00:00Z",
            },
            FINANCE,
        )
        validate_error(lot_attempt, ApiErrorId.ERR_UNAUTHORIZED)

        # The role check precedes the state machine, which would refuse an
        # ASSESSED asset.
        release_attempt = api.release_asset(
            asset["id"], {}, make_agency_officer_headers(agency["id"])
        )
        assert release_attempt.status_code == 403, (
            "an AgencyOfficer is not listed for release of custody, so the role "
            f"refusal is answered before the state check, got "
            f"{release_attempt.status_code}"
        )
        validate_error(release_attempt, ApiErrorId.ERR_UNAUTHORIZED)

        unchanged = read_turn_in(turn_in["id"])
        assert unchanged["status"] == "SUBMITTED", (
            "four refused disposal-officer writes must leave the turn-in "
            f"SUBMITTED, got {unchanged['status']!r}"
        )
        assert unchanged["reviewed_at"] is None, (
            f"reviewed_at must still be null, got {unchanged['reviewed_at']!r}"
        )

        accepted = validate_success(
            api.review_turn_in(turn_in["id"], {"decision": "ACCEPT"}, OFFICER)
        )
        assert accepted["status"] == "ACCEPTED", (
            f"the officer's own review must accept the turn-in, got {accepted['status']!r}"
        )
        assert accepted["reviewed_at"] == "2026-08-01T00:00:00.000Z", (
            "reviewed_at must be stamped from the logical clock, got "
            f"{accepted['reviewed_at']!r}"
        )

        _, cycle_meta = validate_paginated(api.list_screening_cycles(ADMIN))
        assert cycle_meta["total_count"] == 0, (
            f"no screening cycle may exist, got {cycle_meta['total_count']}"
        )
        _, lot_meta = validate_paginated(api.list_auction_lots(ADMIN))
        assert lot_meta["total_count"] == 0, (
            f"no auction lot may exist, got {lot_meta['total_count']}"
        )

    def test_money_endpoints_refuse_the_wrong_role_before_resolving_the_row(self, api):
        """PRD §2.1: "Once the caller is authenticated, the role must appear in
        the authorised-role list of the endpoint being called, as tabulated in
        §4; a role calling an endpoint it is not listed for is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.1: "A `FinanceController` settles invoices and distributes net
        proceeds back to the turning-in agencies."
        PRD §2.12: "When several rules could reject the same request, the
        **first** rule violated in the order below determines the response, and
        no later rule is evaluated."
        PRD §2.12: "The acting role appears in the called endpoint's
        authorised-role list — otherwise `ERR_UNAUTHORIZED` (403)."
        PRD §2.12: "Every identifier in the path resolves, left to right —
        otherwise the matching 404 code from §2.11."

        Design: Corner/rbac/rbac_money_actions_forbidden_before_row_lookup
        """
        set_clock()
        agency = register_state_agency()

        create_attempt = api.create_proceeds_distribution(
            create_proceeds_distribution_payload(
                NON_EXISTENT_UUID, agency["version"], "ACCRUAL"
            ),
            OFFICER,
        )
        assert create_attempt.status_code == 403, (
            "a DisposalOfficer is not listed for distribution creation, so the "
            "role refusal is answered before the unknown lot and before the "
            f"version comparison, got {create_attempt.status_code}"
        )
        validate_error(create_attempt, ApiErrorId.ERR_UNAUTHORIZED)

        post_attempt = api.post_proceeds_distribution(NON_EXISTENT_UUID, ADMIN)
        validate_error(post_attempt, ApiErrorId.ERR_UNAUTHORIZED)

        reverse_attempt = api.reverse_proceeds_distribution(
            NON_EXISTENT_UUID, "Attempted by the wrong role", OFFICER
        )
        validate_error(reverse_attempt, ApiErrorId.ERR_UNAUTHORIZED)

        # The same nonce id from the authorised role reaches path resolution,
        # which proves the refusals above were role refusals.
        finance_attempt = api.post_proceeds_distribution(NON_EXISTENT_UUID, FINANCE)
        assert finance_attempt.status_code == 404, (
            "the FinanceController is listed for posting, so the unresolvable "
            f"path id must answer HTTP 404, got {finance_attempt.status_code}"
        )
        validate_error(finance_attempt, ApiErrorId.ERR_DISTRIBUTION_NOT_FOUND)

        _, meta = validate_paginated(api.list_proceeds_distributions(FINANCE))
        assert meta["total_count"] == 0, (
            f"no distribution row may exist, got {meta['total_count']}"
        )

    def test_bidding_is_the_bidders_own_write_and_deposits_are_shared_with_finance(
        self, api
    ):
        """PRD §2.1: "Once the caller is authenticated, the role must appear in
        the authorised-role list of the endpoint being called, as tabulated in
        §4; a role calling an endpoint it is not listed for is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.1: "A `Bidder` acts as its own bidder row: it deposits, bids and
        pays."
        PRD §3.1: "A `Bidder` may record its own deposits; a `FinanceController`
        may record anyone's."
        PRD §3.1: "A deposit carries an `amount_cents` and adds that amount to
        both `deposit_paid_cents` and `deposit_held_cents`, leaving
        `deposit_applied_cents` and `deposit_forfeited_cents` untouched, which
        keeps the deposit-custody identity of §2.13 intact."
        PRD §3.6: "A registered `Bidder` places a bid on an open lot, supplying
        its own `bidder_id` and an `amount_cents` strictly greater than zero."

        Design: Corner/rbac/rbac_bidding_and_deposits_forbidden_to_staff_roles
        """
        scenario = setup_open_lot()
        lot = scenario["lot"]
        assert lot["reserve_price_cents"] == 7524, (
            "the de-minimis furniture lot's computed reserve must be 7524, got "
            f"{lot['reserve_price_cents']}"
        )
        assert lot["required_deposit_cents"] == 0, (
            "this lot demands no deposit, got "
            f"{lot['required_deposit_cents']}"
        )

        # The bidder record is created by the DisposalOfficer, which does not
        # give that role any funding capability.
        bidder = get_success_data(
            api.create_bidder(
                create_bidder_payload(
                    legal_name="Cedar Ridge Salvage LLC",
                    email="bids@cedarridge.example",
                ),
                OFFICER,
            )
        )
        get_success_data(api.set_bidder_status(bidder["id"], "REGISTERED", OFFICER))

        bid_payload = create_bid_payload(bidder["id"], 7524)
        for role, headers in (
            ("ProgramAdmin", ADMIN),
            ("DisposalOfficer", OFFICER),
            ("FinanceController", FINANCE),
        ):
            response = api.place_bid(lot["id"], bid_payload, headers)
            assert response.status_code == 403, (
                f"a {role} is not listed for bid placement and must be answered "
                f"HTTP 403, got {response.status_code}"
            )
            validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)

        deposit_refusal = api.record_deposit(bidder["id"], 50000, OFFICER)
        assert deposit_refusal.status_code == 403, (
            "deposit recording is shared with the FinanceController only, so the "
            f"DisposalOfficer must be answered HTTP 403, got {deposit_refusal.status_code}"
        )
        validate_error(deposit_refusal, ApiErrorId.ERR_UNAUTHORIZED)

        untouched_bidder = read_bidder(bidder["id"])
        assert untouched_bidder["deposit_paid_cents"] == 0, (
            "the refused deposit must credit nothing, got "
            f"{untouched_bidder['deposit_paid_cents']}"
        )
        untouched_lot = read_lot(lot["id"])
        assert untouched_lot["bid_count"] == 0, (
            f"the three refused bids must record nothing, got {untouched_lot['bid_count']}"
        )
        assert untouched_lot["high_bid_cents"] == 0, (
            f"high_bid_cents must still be 0, got {untouched_lot['high_bid_cents']}"
        )

        funded = validate_success(api.record_deposit(bidder["id"], 50000, FINANCE))
        assert funded["deposit_paid_cents"] == 50000, (
            f"deposit_paid_cents must be 50000, got {funded['deposit_paid_cents']}"
        )
        assert funded["deposit_held_cents"] == 50000, (
            f"deposit_held_cents must be 50000, got {funded['deposit_held_cents']}"
        )

        bid = validate_success(
            api.place_bid(lot["id"], bid_payload, make_bidder_headers(bidder["id"])),
            201,
        )
        assert bid["status"] == "ACTIVE", (
            f"a newly placed bid is ACTIVE, got {bid['status']!r}"
        )
        assert bid["bidder_id"] == bidder["id"], (
            f"the bid must belong to the acting bidder, got {bid['bidder_id']!r}"
        )

        final_lot = read_lot(lot["id"])
        assert final_lot["bid_count"] == 1, (
            f"only the bidder's own bid was recorded, got {final_lot['bid_count']}"
        )
        assert final_lot["high_bid_cents"] == 7524, (
            f"high_bid_cents must be 7524, got {final_lot['high_bid_cents']}"
        )
        final_bidder = read_bidder(bidder["id"])
        assert final_bidder["deposit_held_cents"] == 50000, (
            "the lot requires no deposit, so bidding consumes none of the held "
            f"funds, got {final_bidder['deposit_held_cents']}"
        )


class TestSegregationOfDuties:
    """The two barriers that separate incompatible duties by user id."""

    def test_a_technician_who_appraised_the_asset_cannot_certify_it(self, api):
        """PRD §2.10: "The `ClearanceTechnician` filing a clearance certificate
        against an asset must have an `X-User-ID` that differs from **every**
        `assessor_user_id` recorded on that asset's condition assessments — not
        merely the governing one."
        PRD §2.10: "A technician who also appraised the item, in any assessment,
        is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."
        PRD §2.1: "Once the caller is authenticated, the role must appear in the
        authorised-role list of the endpoint being called, as tabulated in §4; a
        role calling an endpoint it is not listed for is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.1: "A `ClearanceTechnician` signs the sanitisation and
        demilitarisation release gates."
        PRD §3.8: "The certificate stores the `asset_id` it addresses and stamps
        `technician_user_id` from the technician's `X-User-ID`."
        PRD §3.8: "A `DATA_SANITIZATION` certificate is required when
        `is_data_bearing` is true; a `DEMILITARIZATION` certificate is required
        when `is_restricted` is true; an asset with both flags needs both, and
        only certificates with `serials_verified` true count towards the
        requirement."
        PRD §3.8: "From `REQUIRED_PENDING`, a verified certificate that completes
        every required `cert_type` moves the asset to `CLEARED`; a verified
        certificate that still leaves a required type uncovered leaves the asset
        at `REQUIRED_PENDING`."

        Design: Corner/rbac/rbac_assessor_cannot_certify_the_asset_it_appraised
        """
        set_clock()
        agency = register_state_agency()
        turn_in = create_draft_turn_in(agency["id"])
        asset_a = add_asset_with_payload(
            agency["id"],
            create_it_asset_payload(
                turn_in["id"],
                description="Laptop cart A",
                acquisition_cost_cents=300000,
                acquisition_date="2024-05-20",
                is_data_bearing=True,
            ),
        )
        asset_b = add_asset_with_payload(
            agency["id"],
            create_it_asset_payload(
                turn_in["id"],
                description="Laptop cart B",
                acquisition_cost_cents=300000,
                acquisition_date="2024-05-20",
                is_data_bearing=True,
            ),
        )
        submit_turn_in(agency["id"], turn_in["id"])

        assessment_overrides = {
            "condition_code": "C3",
            "functional": True,
            "repair_cost_estimate_cents": 0,
            "assessed_on": "2026-07-31",
        }
        assess_asset(
            asset_a["id"], asset_a["version"],
            assessor_user_id=ASSESSOR_USER_ID, **assessment_overrides,
        )
        assess_asset(
            asset_b["id"], asset_b["version"],
            assessor_user_id=SECOND_ASSESSOR_USER_ID, **assessment_overrides,
        )
        assert read_asset(asset_a["id"])["clearance_status"] == "REQUIRED_PENDING", (
            "a data-bearing asset carries an open sanitisation gate"
        )

        cert_payload = create_clearance_certificate_payload(
            cert_type="DATA_SANITIZATION",
            method="NIST_PURGE",
            serials_verified=True,
            certified_on="2026-08-01",
        )

        for role, headers in (
            ("SurplusAssessor", ASSESSOR),
            ("DisposalOfficer", OFFICER),
        ):
            response = api.create_clearance_certificate(
                asset_a["id"], cert_payload, headers
            )
            assert response.status_code == 403, (
                f"a {role} is not listed for clearance-certificate filing and "
                f"must be answered HTTP 403, got {response.status_code}"
            )
            validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)

        # Right role, but this user id appraised asset A.
        conflicted = api.create_clearance_certificate(
            asset_a["id"],
            cert_payload,
            make_clearance_technician_headers(ASSESSOR_USER_ID),
        )
        assert conflicted.status_code == 409, (
            "a technician whose user id already appears as an assessor on this "
            f"asset must be answered HTTP 409, got {conflicted.status_code}"
        )
        validate_error(conflicted, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        blocked = read_asset(asset_a["id"])
        assert blocked["clearance_status"] == "REQUIRED_PENDING", (
            "the refused filings must leave the clearance axis untouched, got "
            f"{blocked['clearance_status']!r}"
        )
        assert blocked["version"] == 2, (
            "the refused filings must not increment the asset's version beyond "
            f"the one appraisal, got {blocked['version']}"
        )
        _, refused_meta = validate_paginated(
            api.list_clearance_certificates(asset_a["id"], ADMIN)
        )
        assert refused_meta["total_count"] == 0, (
            f"no certificate row may exist yet, got {refused_meta['total_count']}"
        )

        # The conflict is per asset: asset B was appraised by a different user.
        cert_b = validate_success(
            api.create_clearance_certificate(
                asset_b["id"],
                cert_payload,
                make_clearance_technician_headers(ASSESSOR_USER_ID),
            ),
            201,
        )
        assert cert_b["technician_user_id"] == ASSESSOR_USER_ID, (
            "technician_user_id is stamped from the caller's X-User-ID, got "
            f"{cert_b['technician_user_id']!r}"
        )

        cert_a = validate_success(
            api.create_clearance_certificate(asset_a["id"], cert_payload, TECHNICIAN),
            201,
        )
        assert cert_a["technician_user_id"] == TECHNICIAN_USER_ID, (
            "technician_user_id is stamped from the caller's X-User-ID, got "
            f"{cert_a['technician_user_id']!r}"
        )

        assert read_asset(asset_a["id"])["clearance_status"] == "CLEARED", (
            "a verified sanitisation certificate completes the only required "
            "type for asset A"
        )
        assert read_asset(asset_b["id"])["clearance_status"] == "CLEARED", (
            "a verified sanitisation certificate completes the only required "
            "type for asset B"
        )

        rows_a, meta_a = validate_paginated(
            api.list_clearance_certificates(asset_a["id"], ADMIN)
        )
        assert meta_a["total_count"] == 1, (
            f"asset A must hold exactly one certificate, got {meta_a['total_count']}"
        )
        assert [row["id"] for row in rows_a] == [cert_a["id"]], (
            "asset A's certificate listing must hold only the accepted row"
        )
        rows_b, meta_b = validate_paginated(
            api.list_clearance_certificates(asset_b["id"], ADMIN)
        )
        assert meta_b["total_count"] == 1, (
            f"asset B must hold exactly one certificate, got {meta_b['total_count']}"
        )
        assert [row["id"] for row in rows_b] == [cert_b["id"]], (
            "asset B's certificate listing must hold only the accepted row"
        )

    def test_the_user_who_closed_the_lot_may_not_post_its_proceeds(self, api):
        """PRD §2.10: "The `FinanceController` posting a proceeds distribution
        must have an `X-User-ID` that differs from the `closed_by_user_id`
        recorded on the `AuctionLot` the distribution settles."
        PRD §2.10: "The same person closing the lot and posting its proceeds is
        refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."
        PRD §3.9: "The segregation-of-duties barrier of §2.10 is checked before
        the state precondition: the poster's `X-User-ID` must differ from the
        `closed_by_user_id` of the lot the distribution settles, otherwise
        `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.9: "The post stamps `posted_by_user_id` and `posted_at`, moves the
        row to `POSTED`, and in a second hop caused by that stamping recomputes
        the beneficiary agency's `proceeds_account_balance_cents` and
        `posted_distribution_count`."

        Design: Corner/rbac/rbac_lot_closer_cannot_post_the_distribution
        """
        scenario = setup_calculated_distribution(
            basis="ACCRUAL",
            bid_amount_cents=20000,
            officer_user_id=SECOND_OFFICER_USER_ID,
        )
        lot = scenario["lot"]
        distribution = scenario["distribution"]
        agency_id = scenario["agency"]["id"]

        assert lot["closed_by_user_id"] == SECOND_OFFICER_USER_ID, (
            "the lot must record the closing officer's user id, got "
            f"{lot['closed_by_user_id']!r}"
        )
        assert lot["status"] == "CLOSED_MET", (
            f"the lot must have closed with its reserve met, got {lot['status']!r}"
        )
        # Creating the distribution is not guarded by the barrier.
        assert distribution["distributable_base_cents"] == 20000, (
            "the accrual base is the hammer price of 20000, got "
            f"{distribution['distributable_base_cents']}"
        )
        assert distribution["service_fee_cents"] == 2500, (
            f"the service fee on 20000 must be 2500, got {distribution['service_fee_cents']}"
        )
        assert distribution["net_to_agency_cents"] == 17500, (
            f"the net to the agency must be 17500, got {distribution['net_to_agency_cents']}"
        )

        refused = api.post_proceeds_distribution(
            distribution["id"],
            make_finance_controller_headers(SECOND_OFFICER_USER_ID),
        )
        assert refused.status_code == 409, (
            "the user id that closed the lot may not post its proceeds and must "
            f"be answered HTTP 409, got {refused.status_code}"
        )
        validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        after_refusal = read_distribution(distribution["id"])
        assert after_refusal["status"] == "CALCULATED", (
            "the refused post must leave the distribution CALCULATED, got "
            f"{after_refusal['status']!r}"
        )
        assert after_refusal["posted_by_user_id"] is None, (
            "the refused post must stamp nobody, got "
            f"{after_refusal['posted_by_user_id']!r}"
        )
        assert read_agency(agency_id)["proceeds_account_balance_cents"] == 0, (
            "the refused post must credit no ledger"
        )

        posted = validate_success(
            api.post_proceeds_distribution(distribution["id"], FINANCE)
        )
        assert posted["status"] == "POSTED", (
            f"a different finance user may post the same row, got {posted['status']!r}"
        )
        assert posted["posted_by_user_id"] == FINANCE_USER_ID, (
            f"posted_by_user_id must be the poster, got {posted['posted_by_user_id']!r}"
        )

        beneficiary = read_agency(agency_id)
        assert beneficiary["proceeds_account_balance_cents"] == 17500, (
            "the beneficiary ledger must be credited with the net, got "
            f"{beneficiary['proceeds_account_balance_cents']}"
        )
        assert beneficiary["posted_distribution_count"] == 1, (
            "exactly one posted distribution must be counted, got "
            f"{beneficiary['posted_distribution_count']}"
        )


class TestEntityBackedOwnershipScope:
    """AgencyOfficer and Bidder resolve X-User-ID against a stored row, so their
    reach is narrowed to that row's own rows."""

    def test_an_agency_officer_cannot_reach_another_organisations_rows(self, api):
        """PRD §2.1: "Ownership checks on any resource that references an `Agency`
        compare the resource's own agency reference to `X-User-ID`: a `TurnIn` is
        scoped by its `turning_in_agency_id`, a `ScreeningRequest` by its
        `requesting_agency_id`, a `TransferOrder` by its `recipient_agency_id`,
        and an `Agency` read by its own `id`."
        PRD §2.1: "An `AgencyOfficer` reaching a row that belongs to another
        organisation is rejected with `ERR_FORBIDDEN_AGENCY_SCOPE` (HTTP 403); the
        operations that carry this scope check are agency read, turn-in creation,
        turn-in submission, single-turn-in read, screening-request filing,
        screening-request resubmission, single-screening-request read,
        transfer-order acknowledgement, and single-transfer-order read."
        PRD §3.2: "Submission of the turn-in is the relinquishing organisation's
        act, and only the officer of that organisation — the one whose
        `X-User-ID` equals the turn-in's `turning_in_agency_id` — or a
        `ProgramAdmin` may perform it."
        PRD §3.2: "Submission moves `status` from `DRAFT` to `SUBMITTED`, stamps
        `submitted_at` from the logical clock and increments the turn-in's
        `version` by 1."

        Design: Corner/rbac/rbac_agency_officer_cannot_reach_another_organizations_rows
        """
        set_clock()
        owner = register_state_agency()
        other = register_state_agency(
            name="Texas Facilities Commission", agency_code="TFC-02"
        )
        turn_in = create_draft_turn_in(owner["id"])
        asset = add_asset(
            owner["id"],
            turn_in["id"],
            description="Modular workstation cluster",
            acquisition_cost_cents=1000000,
            acquisition_date="2026-01-10",
        )
        intruder = make_agency_officer_headers(other["id"])

        attempts = [
            ("single-turn-in read", lambda: api.get_turn_in(turn_in["id"], intruder)),
            ("agency read", lambda: api.get_agency(owner["id"], intruder)),
            (
                "turn-in creation naming another organisation",
                lambda: api.create_turn_in(
                    create_turn_in_payload(
                        owner["id"], custody_location="Borrowed custody location"
                    ),
                    intruder,
                ),
            ),
            ("turn-in submission", lambda: api.submit_turn_in(turn_in["id"], intruder)),
        ]
        for label, call in attempts:
            response = call()
            assert response.status_code == 403, (
                f"{label} across organisations must answer HTTP 403, got "
                f"{response.status_code}"
            )
            # The role is listed on every one of these endpoints, so this is a
            # scope refusal rather than a role refusal.
            validate_error(response, ApiErrorId.ERR_FORBIDDEN_AGENCY_SCOPE)

        untouched = read_turn_in(turn_in["id"])
        assert untouched["status"] == "DRAFT", (
            f"the refused submission must leave the turn-in DRAFT, got {untouched['status']!r}"
        )
        assert untouched["submitted_at"] is None, (
            f"submitted_at must still be null, got {untouched['submitted_at']!r}"
        )

        owned = validate_success(
            api.get_turn_in(turn_in["id"], make_agency_officer_headers(owner["id"]))
        )
        assert owned["turning_in_agency_id"] == owner["id"], (
            "the owning officer reads its own turn-in, got "
            f"{owned['turning_in_agency_id']!r}"
        )
        assert owned["asset_count"] == 1, (
            f"the turn-in holds one asset, got {owned['asset_count']}"
        )

        submitted = validate_success(
            api.submit_turn_in(turn_in["id"], make_agency_officer_headers(owner["id"]))
        )
        assert submitted["status"] == "SUBMITTED", (
            f"the owning officer may submit its own turn-in, got {submitted['status']!r}"
        )
        assert submitted["submitted_at"] == "2026-08-01T00:00:00.000Z", (
            "submitted_at must be stamped from the logical clock, got "
            f"{submitted['submitted_at']!r}"
        )

        _, meta = validate_paginated(api.list_turn_ins(ADMIN))
        assert meta["total_count"] == 1, (
            "the refused cross-organisation creation wrote nothing, got "
            f"{meta['total_count']} turn-ins"
        )
        assert read_asset(asset["id"])["disposition_status"] == "INTAKE", (
            "the asset stays at INTAKE throughout"
        )

    def test_a_bidder_cannot_act_for_another_bidder(self, api):
        """PRD §2.1: "When `X-User-Role` is `Bidder`, `X-User-ID` is the `id` of
        the acting `Bidder` row and must resolve to one; ownership checks compare
        `Bidder.id`, `Bid.bidder_id` and `SaleInvoice.bidder_id` to `X-User-ID`,
        and a mismatch is rejected with `ERR_FORBIDDEN_BIDDER_SCOPE` (HTTP 403)."
        PRD §2.1: "That scope check guards single-bidder read, the bidder's own
        bid listing, deposit recording, bid placement, single-invoice read and
        invoice payment."
        PRD §3.6: "A bidder may only bid as itself."

        Design: Corner/rbac/rbac_bidder_cannot_act_for_another_bidder
        """
        scenario = setup_open_lot_with_bidder()
        lot = scenario["lot"]
        first = scenario["bidder"]
        second = register_bidder(
            legal_name="Balcones Reclaim Co", email="desk@balconesreclaim.example"
        )
        assert first["status"] == "REGISTERED" and second["status"] == "REGISTERED", (
            "both bidders must be REGISTERED so the refusals cannot be about "
            "registration"
        )
        as_second = make_bidder_headers(second["id"])

        attempts = [
            ("single-bidder read", lambda: api.get_bidder(first["id"], as_second)),
            ("own-bid listing", lambda: api.list_bidder_bids(first["id"], as_second)),
            (
                "deposit recording",
                lambda: api.record_deposit(first["id"], 50000, as_second),
            ),
            (
                "bid placement naming another bidder",
                lambda: api.place_bid(
                    lot["id"], create_bid_payload(first["id"], 7524), as_second
                ),
            ),
        ]
        for label, call in attempts:
            response = call()
            assert response.status_code == 403, (
                f"{label} across bidders must answer HTTP 403, got "
                f"{response.status_code}"
            )
            validate_error(response, ApiErrorId.ERR_FORBIDDEN_BIDDER_SCOPE)

        untouched = read_bidder(first["id"])
        assert untouched["deposit_paid_cents"] == 0, (
            "the refused deposit must credit nothing to the other bidder, got "
            f"{untouched['deposit_paid_cents']}"
        )
        assert read_lot(lot["id"])["bid_count"] == 0, (
            "the refused bid must record nothing"
        )

        own_bid = validate_success(
            api.place_bid(
                lot["id"], create_bid_payload(second["id"], 7524), as_second
            ),
            201,
        )
        assert own_bid["bidder_id"] == second["id"], (
            f"the accepted bid must name the acting bidder, got {own_bid['bidder_id']!r}"
        )
        assert own_bid["status"] == "ACTIVE", (
            f"a newly placed bid is ACTIVE, got {own_bid['status']!r}"
        )

        self_read = validate_success(api.get_bidder(second["id"], as_second))
        assert self_read["deposit_paid_cents"] == 0, (
            "the refused deposit credited nothing to the acting bidder either, got "
            f"{self_read['deposit_paid_cents']}"
        )

        other_bidder = read_bidder(first["id"])
        assert other_bidder["deposit_paid_cents"] == 0, (
            f"the other bidder holds no deposit, got {other_bidder['deposit_paid_cents']}"
        )
        assert other_bidder["winning_lot_count"] == 0, (
            f"the other bidder won nothing, got {other_bidder['winning_lot_count']}"
        )

        final_lot = read_lot(lot["id"])
        assert final_lot["bid_count"] == 1, (
            f"only the acting bidder's own bid was recorded, got {final_lot['bid_count']}"
        )
        assert final_lot["high_bid_cents"] == 7524, (
            f"high_bid_cents must be 7524, got {final_lot['high_bid_cents']}"
        )


class TestSharedOperations:
    """Endpoints declared for more than one role accept every declared role."""

    def test_endpoints_declared_for_two_roles_accept_either_of_them(self, api):
        """PRD §2.1: "Once the caller is authenticated, the role must appear in
        the authorised-role list of the endpoint being called, as tabulated in
        §4; a role calling an endpoint it is not listed for is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §3.2: "Property enters the system through a **turn-in**, opened by an
        `AgencyOfficer` of the relinquishing organisation or by a `ProgramAdmin`
        on its behalf."
        PRD §3.2: "While the turn-in is still `DRAFT`, items are added to it one
        at a time."
        PRD §3.2: "Submission of the turn-in is the relinquishing organisation's
        act, and only the officer of that organisation — the one whose
        `X-User-ID` equals the turn-in's `turning_in_agency_id` — or a
        `ProgramAdmin` may perform it."
        PRD §3.1: "A `ProgramAdmin` or `DisposalOfficer` then drives the
        registration: `PENDING` becomes `REGISTERED`; a `REGISTERED` bidder may
        be moved to `SUSPENDED` and back to `REGISTERED`; and either a
        `REGISTERED` or a `SUSPENDED` bidder may be moved to `DEBARRED`, which is
        terminal and triggers the unwinding cascade described in §3.7."
        PRD §3.1: "A separate capability records the bidder's
        `end_use_certificate_expires_on`, the expiry of the end-use certificate
        that restricted property requires before it may be bid on."
        PRD §3.1: "A `Bidder` may record its own deposits; a `FinanceController`
        may record anyone's."
        PRD §3.1: "A deposit carries an `amount_cents` and adds that amount to
        both `deposit_paid_cents` and `deposit_held_cents`, leaving
        `deposit_applied_cents` and `deposit_forfeited_cents` untouched, which
        keeps the deposit-custody identity of §2.13 intact."
        PRD §4: "Endpoints that bring a new resource into existence answer with
        HTTP 201 Created; endpoints that read, list or modify an existing
        resource answer with HTTP 200 OK."

        Design: Corner/rbac/rbac_shared_operations_accept_either_declared_role
        """
        set_clock()
        agency = register_state_agency()
        officer_headers = make_agency_officer_headers(agency["id"])

        # Opened by the agency officer, then carried on by the administrator.
        turn_in = validate_success(
            api.create_turn_in(create_turn_in_payload(agency["id"]), officer_headers),
            201,
        )
        asset = validate_success(
            api.create_asset(
                create_asset_payload(
                    turn_in["id"],
                    description="Lateral file cabinets, single pallet",
                    acquisition_cost_cents=104500,
                    acquisition_date="2024-05-20",
                ),
                ADMIN,
            ),
            201,
        )
        submitted = validate_success(api.submit_turn_in(turn_in["id"], ADMIN))
        assert submitted["status"] == "SUBMITTED", (
            "the administrator may continue an agency officer's draft, got "
            f"{submitted['status']!r}"
        )
        assert submitted["asset_count"] == 1, (
            f"the turn-in holds the one asset added, got {submitted['asset_count']}"
        )

        # Created by the disposal officer, registered by the administrator, then
        # certified by the disposal officer again.
        bidder = validate_success(
            api.create_bidder(
                create_bidder_payload(
                    legal_name="Cedar Ridge Salvage LLC",
                    email="bids@cedarridge.example",
                ),
                OFFICER,
            ),
            201,
        )
        registered = validate_success(
            api.set_bidder_status(bidder["id"], "REGISTERED", ADMIN)
        )
        assert registered["status"] == "REGISTERED", (
            f"the administrator may drive the registration, got {registered['status']!r}"
        )
        certified = validate_success(
            api.set_bidder_end_use_certificate(bidder["id"], "2027-06-30", OFFICER)
        )
        assert certified["end_use_certificate_expires_on"] == "2027-06-30", (
            "the disposal officer may record the end-use certificate expiry, got "
            f"{certified['end_use_certificate_expires_on']!r}"
        )

        # Deposits arrive from both declared roles and accumulate.
        first_deposit = validate_success(api.record_deposit(bidder["id"], 30000, FINANCE))
        assert first_deposit["deposit_paid_cents"] == 30000, (
            f"the finance controller's deposit must credit 30000, got "
            f"{first_deposit['deposit_paid_cents']}"
        )
        second_deposit = validate_success(
            api.record_deposit(bidder["id"], 20000, make_bidder_headers(bidder["id"]))
        )
        assert second_deposit["deposit_paid_cents"] == 50000, (
            "the two deposits accumulate rather than overwrite, got "
            f"{second_deposit['deposit_paid_cents']}"
        )
        assert second_deposit["deposit_held_cents"] == 50000, (
            f"deposit_held_cents must be 50000, got {second_deposit['deposit_held_cents']}"
        )

        # The single-asset read is declared for six roles; three of them read the
        # identical row, including the officer of the owning organisation.
        reads = {
            "ClearanceTechnician": TECHNICIAN,
            "FinanceController": FINANCE,
            "AgencyOfficer": officer_headers,
        }
        rows = {}
        for role, headers in reads.items():
            response = api.get_asset(asset["id"], headers)
            assert response.status_code == 200, (
                f"a {role} is listed for the single-asset read and must be "
                f"answered HTTP 200, got {response.status_code}"
            )
            rows[role] = validate_success(response)

        for role, row in rows.items():
            assert row == rows["ClearanceTechnician"], (
                f"the {role} read must return the identical asset row"
            )
            assert row["id"] == asset["id"], (
                f"the {role} read must address the created asset"
            )
            assert row["disposition_status"] == "INTAKE", (
                f"the asset stands at INTAKE, got {row['disposition_status']!r}"
            )
            assert row["clearance_status"] == "NOT_REQUIRED", (
                "a furniture item that is neither data-bearing nor restricted has "
                f"no release gate, got {row['clearance_status']!r}"
            )
