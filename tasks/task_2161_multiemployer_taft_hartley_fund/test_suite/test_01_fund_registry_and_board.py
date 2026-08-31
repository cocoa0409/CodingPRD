"""Chartering the trust, registering its constituents and seating its board."""

from test_helpers import (
    TEST_USERS,
    UNKNOWN_IDS,
    ApiErrorId,
    assert_employer,
    assert_fund,
    assert_motion_vote,
    assert_trustee,
    create_employer_payload,
    create_fund,
    create_fund_payload,
    create_trustee,
    file_single_line_report,
    is_valid_uuid,
    make_employer_headers,
    make_trustee_headers,
    move_motion,
    read_fund,
    seat_board,
    set_clock,
    setup_employer_with_one_participant,
    setup_open_board_with_sister_fund,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["fund_administrator_headers"]


def test_chartered_fund_opens_frozen_with_the_whole_pool_unallocated(api):
    """PRD §3.1: "A newly chartered fund is not yet governable. Because no
    trustees have been seated, its `governance_posture` initialises to `FROZEN`,
    `active_union_trustees` and `active_employer_trustees` are both 0, and
    `suspended_employer_count`, `reciprocal_receipts_cents`,
    `allocated_uvb_cents` and `collections_run_index` all start at 0.
    `unallocated_uvb_cents` starts equal to `total_uvb_cents`, and
    `reciprocity_agreement_status` starts at `NONE`."
    PRD §3.1: "`fund_role` defaults to `HOME` and may be set to `SISTER`; a
    `HOME` fund is one this API administers, while `SISTER` rows exist only as
    reciprocity counterparties. `plan_year_start_month` defaults to 1 and must
    be a calendar month from 1 through 12."
    PRD §2.4: "Every resource is created with a server-minted `id`: a UUID
    string carrying no type prefix of any kind."

    Design: Corner/entities/fund_create_returns_every_declared_field_with_derived_posture_frozen
    """
    set_clock()

    response = api.create_fund(create_fund_payload(), ADMIN)
    data = validate_success(response, 201)

    assert response.json()["response_type"] == "object"
    assert_fund(data)
    assert data["fund_role"] == "HOME", "fund_role defaults to HOME"
    assert data["plan_year_start_month"] == 1, "plan_year_start_month defaults to 1"
    assert data["allocated_uvb_cents"] == 0
    assert data["unallocated_uvb_cents"] == 100_000_000
    assert data["reciprocity_agreement_status"] == "NONE"
    assert data["governance_posture"] == "FROZEN"
    assert data["active_union_trustees"] == 0
    assert data["active_employer_trustees"] == 0
    assert data["collections_run_index"] == 0
    assert data["suspended_employer_count"] == 0
    assert data["reciprocal_receipts_cents"] == 0
    assert data["version"] == 1, "version begins at 1 when the row is created"
    assert is_valid_uuid(data["id"]) and not data["id"].startswith("fund")


def test_seating_trustees_walks_the_posture_from_frozen_through_open_and_back(api):
    """PRD §3.2: "An optional `seat_status` defaults to `ACTIVE` and may instead
    be `RESIGNED`."
    PRD §3.2: "If either count is 0, `governance_posture` is `FROZEN` — a board
    missing a bargaining party entirely cannot act at all. Otherwise, if the two
    counts differ from one another, or if the smaller of the two counts is below
    two trustees per party, the posture is `RESTRICTED`. Only when both counts
    are equal and each is at least two is the posture `OPEN`."
    PRD §3.2: "Trustee listings for a fund may be filtered by `seat_status` and
    by `appointing_party`."

    Design: Corner/entities/trustee_create_defaults_seat_status_to_active_and_lifts_posture_to_open
    """
    set_clock()
    fund = create_fund(name="Posture Fund", ein="36-3000001")

    first_union = create_trustee(fund["id"], "UNION", full_name="Union Trustee One")
    assert_trustee(first_union)
    assert first_union["seat_status"] == "ACTIVE", "seat_status defaults to ACTIVE"
    assert read_fund(fund["id"])["governance_posture"] == "FROZEN"

    create_trustee(fund["id"], "EMPLOYER", full_name="Employer Trustee One")
    one_and_one = read_fund(fund["id"])
    assert one_and_one["governance_posture"] == "RESTRICTED"
    assert one_and_one["active_union_trustees"] == 1
    assert one_and_one["active_employer_trustees"] == 1

    create_trustee(fund["id"], "UNION", full_name="Union Trustee Two")
    create_trustee(fund["id"], "EMPLOYER", full_name="Employer Trustee Two")
    assert read_fund(fund["id"])["governance_posture"] == "OPEN"

    create_trustee(fund["id"], "UNION", full_name="Union Trustee Three")
    lopsided = read_fund(fund["id"])
    assert lopsided["governance_posture"] == "RESTRICTED"
    assert lopsided["active_union_trustees"] == 3
    assert lopsided["active_employer_trustees"] == 2

    rows, meta = validate_paginated(api.list_fund_trustees(fund["id"], ADMIN))
    assert meta["total_count"] == 5
    employer_rows, employer_meta = validate_paginated(
        api.list_fund_trustees(
            fund["id"], ADMIN, params={"appointing_party": "EMPLOYER"}
        )
    )
    assert employer_meta["total_count"] == 2
    assert all(row["appointing_party"] == "EMPLOYER" for row in employer_rows)


def test_resigned_seat_persists_but_never_counts_toward_the_posture(api):
    """PRD §3.2: "Count the fund's trustees whose `seat_status` is `ACTIVE` and
    whose `appointing_party` is `UNION`, and store that count as
    `active_union_trustees`; count the active `EMPLOYER`-appointed trustees the
    same way into `active_employer_trustees`. Seats marked `RESIGNED` never
    count toward either."
    PRD §3.2: "Trustee listings for a fund may be filtered by `seat_status` and
    by `appointing_party`."

    Design: Corner/entities/resigned_trustee_seat_is_created_but_never_counted_toward_posture
    """
    set_clock()
    fund = create_fund(name="Resigned Seat Fund", ein="36-3000002")
    seat_board(fund["id"], union=2, employer=2)

    resigned = create_trustee(
        fund["id"], "UNION", full_name="Retired Union Trustee", seat_status="RESIGNED"
    )

    assert resigned["seat_status"] == "RESIGNED"
    fund_now = read_fund(fund["id"])
    assert fund_now["active_union_trustees"] == 2, "the resigned seat is not counted"
    assert fund_now["active_employer_trustees"] == 2
    assert fund_now["governance_posture"] == "OPEN"

    _rows, meta = validate_paginated(
        api.list_fund_trustees(fund["id"], ADMIN, params={"seat_status": "RESIGNED"})
    )
    assert meta["total_count"] == 1


def test_employer_registration_without_a_contribution_rate_is_malformed(api):
    """PRD §3.1: "An employer registration carries `fund_id`, the employer's
    `legal_name` and `ein`, its bargained `contribution_rate_millicents_per_hour`
    — the rate in thousandths of a cent per credited hour, which must be at
    least 1 — and two five-element arrays used later for withdrawal liability:
    `prior_year_contributions_cents`, the employer's own contributions for the
    five plan years preceding a withdrawal, and `prior_year_base_units`, the
    employer's credited hours for those same five years."
    PRD §2.8: "**Request shape.** Required fields present, types correct, enum
    members valid, every month key matching a four-digit year, a hyphen, and a
    two-digit month between 01 and 12, both prior-year arrays holding exactly
    five entries, hours values at least 0 with at most two decimal places, and
    every cents field a non-negative integer — otherwise `ERR_INVALID_REQUEST`
    (400)."

    Design: Corner/entities/employer_create_missing_required_rate_returns_invalid_request
    """
    set_clock()
    fund = create_fund(name="Required Field Fund", ein="36-3000003")

    payload = create_employer_payload(fund["id"], legal_name="No Rate Co", ein="36-3100001")
    payload.pop("contribution_rate_millicents_per_hour")

    validate_error(
        api.create_employer(payload, ADMIN), ApiErrorId.ERR_INVALID_REQUEST.value
    )

    _rows, meta = validate_paginated(
        api.list_employers(ADMIN, params={"fund_id": fund["id"]})
    )
    assert meta["total_count"] == 0, "no employer row survives a malformed registration"


def test_controlled_group_parent_is_stored_and_reverse_reachable(api):
    """PRD §3.1: "An employer that is a subsidiary in a controlled group may name
    its parent through the optional `controlled_group_parent_employer_id`, which
    is a reference to another employer row and defaults to null."
    PRD §3.1: "Employer listings may be filtered by `fund_id`, by
    `controlled_group_parent_employer_id`, and by `status`."

    Design: Corner/entities/controlled_group_parent_self_reference_is_queryable_from_the_parent
    """
    set_clock()
    fund = create_fund(name="Controlled Group Fund", ein="36-3000008")
    parent = validate_success(
        api.create_employer(
            create_employer_payload(
                fund["id"], legal_name="Ironbridge Holdings", ein="36-8000001"
            ),
            ADMIN,
        ),
        201,
    )

    child = validate_success(
        api.create_employer(
            create_employer_payload(
                fund["id"],
                legal_name="Ironbridge Subsidiary",
                ein="36-8000002",
                prior_year_contributions_cents=[1_000_000] * 5,
                prior_year_base_units=[1200] * 5,
                controlled_group_parent_employer_id=parent["id"],
            ),
            ADMIN,
        ),
        201,
    )

    assert_employer(child)
    assert child["controlled_group_parent_employer_id"] == parent["id"]
    assert parent["controlled_group_parent_employer_id"] is None

    children, child_meta = validate_paginated(
        api.list_employers(
            ADMIN, params={"controlled_group_parent_employer_id": parent["id"]}
        )
    )
    assert child_meta["total_count"] == 1
    assert children[0]["id"] == child["id"]

    _all_rows, all_meta = validate_paginated(
        api.list_employers(ADMIN, params={"fund_id": fund["id"]})
    )
    assert all_meta["total_count"] == 2


def test_every_path_addressed_collection_answers_with_its_own_not_found_code(api):
    """PRD §2.8: "**Path existence.** Every identifier appearing in the URL path
    resolves to an existing row, validated strictly left to right, so that the
    leftmost unresolvable segment determines the error. The applicable codes are
    `ERR_FUND_NOT_FOUND`, `ERR_EMPLOYER_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`,
    `ERR_REPORT_NOT_FOUND`, `ERR_COVERAGE_MONTH_NOT_FOUND`,
    `ERR_ASSESSMENT_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`,
    `ERR_WITHDRAWAL_NOT_FOUND`, `ERR_INSTALLMENT_NOT_FOUND`,
    `ERR_MOTION_NOT_FOUND`, `ERR_VOTE_NOT_FOUND`, and `ERR_TRANSFER_NOT_FOUND`,
    each at HTTP 404."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."

    Design: Corner/entities/not_found_sweep_across_every_path_addressed_collection
    """
    set_clock()

    reads = [
        (api.get_fund(UNKNOWN_IDS["fund"], ADMIN), ApiErrorId.ERR_FUND_NOT_FOUND),
        (
            api.get_employer(UNKNOWN_IDS["employer"], ADMIN),
            ApiErrorId.ERR_EMPLOYER_NOT_FOUND,
        ),
        (
            api.get_participant(UNKNOWN_IDS["participant"], ADMIN),
            ApiErrorId.ERR_PARTICIPANT_NOT_FOUND,
        ),
        (
            api.get_contribution_report(UNKNOWN_IDS["report"], ADMIN),
            ApiErrorId.ERR_REPORT_NOT_FOUND,
        ),
        (
            api.get_coverage_month(UNKNOWN_IDS["coverage_month"], ADMIN),
            ApiErrorId.ERR_COVERAGE_MONTH_NOT_FOUND,
        ),
        (
            api.get_payroll_audit(UNKNOWN_IDS["audit"], ADMIN),
            ApiErrorId.ERR_AUDIT_NOT_FOUND,
        ),
        (
            api.get_withdrawal_assessment(UNKNOWN_IDS["withdrawal"], ADMIN),
            ApiErrorId.ERR_WITHDRAWAL_NOT_FOUND,
        ),
        (
            api.get_board_motion(UNKNOWN_IDS["motion"], ADMIN),
            ApiErrorId.ERR_MOTION_NOT_FOUND,
        ),
        (api.get_motion_vote(UNKNOWN_IDS["vote"], ADMIN), ApiErrorId.ERR_VOTE_NOT_FOUND),
        (
            api.get_reciprocity_transfer(UNKNOWN_IDS["transfer"], ADMIN),
            ApiErrorId.ERR_TRANSFER_NOT_FOUND,
        ),
        (
            api.settle_delinquency_assessment(
                UNKNOWN_IDS["assessment"], {"settlement_amount_cents": 100}, ADMIN
            ),
            ApiErrorId.ERR_ASSESSMENT_NOT_FOUND,
        ),
        (
            api.pay_installment(
                UNKNOWN_IDS["installment"],
                {"amount_cents": 100},
                make_employer_headers(UNKNOWN_IDS["user"]),
            ),
            ApiErrorId.ERR_INSTALLMENT_NOT_FOUND,
        ),
    ]

    for response, expected in reads:
        error_data = validate_error(response, expected.value)
        assert response.json()["response_type"] == "error"
        assert isinstance(error_data["message"], str) and error_data["message"].strip()


def test_report_listing_windows_rows_and_reports_the_pre_window_total(api):
    """PRD §2.3: "Every list endpoint accepts two optional query parameters,
    `limit` and `offset`. `limit` defaults to 10 when omitted, may not be smaller
    than 1, and may not be larger than 100."
    PRD §2.3: "The `meta` block of a list response carries `limit` and `offset`
    as they were applied, `total_count` giving the number of rows matching the
    filter before the window was taken, and `has_more`, which is true exactly
    when rows remain beyond the current window."
    PRD §3.3: "Reports may be listed and filtered by `employer_id`, by
    `amends_report_id`, by `filing_status`, by `payment_status`, by
    `work_period`, and by `origin`; the lines of one report may be listed on
    their own, and a participant's lines across every report may be listed and
    narrowed with a `report_id` filter."

    Design: Corner/entities/contribution_report_listing_paginates_with_total_count_and_has_more
    """
    base = setup_employer_with_one_participant()
    for work_period in ("2026-01", "2026-02", "2026-03"):
        file_single_line_report(
            base["employer"]["id"], base["participant"]["id"], work_period, 100.00
        )

    first_page, first_meta = validate_paginated(
        api.list_contribution_reports(
            ADMIN, params={"employer_id": base["employer"]["id"], "limit": 2, "offset": 0}
        )
    )
    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0

    second_page, second_meta = validate_paginated(
        api.list_contribution_reports(
            ADMIN, params={"employer_id": base["employer"]["id"], "limit": 2, "offset": 2}
        )
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    filtered, filtered_meta = validate_paginated(
        api.list_contribution_reports(
            ADMIN,
            params={"employer_id": base["employer"]["id"], "work_period": "2026-02"},
        )
    )
    assert filtered_meta["total_count"] == 1
    assert filtered[0]["work_period"] == "2026-02"
    assert filtered[0]["due_date"] == "2026-03-20"

    listing = api.list_contribution_reports(
        ADMIN, params={"employer_id": base["employer"]["id"]}
    )
    assert listing.json()["response_type"] == "array"


def test_a_cast_vote_is_an_immutable_ledger_row_with_no_version(api):
    """PRD §2.4: "Two resource types are the exception: contribution lines and
    motion votes are immutable ledger rows, and they carry only `id` and
    `created_at`. Neither `updated_at` nor `version` exists on a contribution
    line or on a motion vote, and neither should appear in their serialized
    form."
    PRD §3.2: "A vote carries the `motion_id` and a `position` of `FOR`,
    `AGAINST`, or `ABSTAIN`; the `trustee_id` is taken from the acting trustee's
    identity rather than the payload."
    PRD §3.2: "Vote listings may be filtered by `motion_id`, by `trustee_id`,
    and by `position`."

    Design: Corner/entities/motion_vote_is_immutable_and_carries_no_version_field
    """
    board_setup = setup_open_board_with_sister_fund(union=2, employer=2)
    motion = move_motion(
        board_setup["fund"]["id"],
        "RECIPROCITY_AGREEMENT",
        board_setup["sister"]["id"],
        board_setup["board"]["union"][0],
    )
    voter_id = board_setup["board"]["union"][1]

    created = validate_success(
        api.create_motion_vote(
            {"motion_id": motion["id"], "position": "ABSTAIN"},
            make_trustee_headers(voter_id),
        ),
        201,
    )

    assert_motion_vote(created)
    assert created["trustee_id"] == voter_id, "trustee_id comes from the acting identity"
    assert "updated_at" not in created
    assert "version" not in created

    fetched = validate_success(api.get_motion_vote(created["id"], ADMIN))
    assert fetched["id"] == created["id"]
    assert fetched["position"] == "ABSTAIN"
    assert "updated_at" not in fetched and "version" not in fetched

    _by_motion, motion_meta = validate_paginated(
        api.list_motion_votes(ADMIN, params={"motion_id": motion["id"]})
    )
    assert motion_meta["total_count"] == 1
    _by_trustee, trustee_meta = validate_paginated(
        api.list_motion_votes(ADMIN, params={"trustee_id": voter_id})
    )
    assert trustee_meta["total_count"] == 1
