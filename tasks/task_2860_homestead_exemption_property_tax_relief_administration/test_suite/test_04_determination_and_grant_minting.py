"""Determination: the gates an application must clear and the grant it mints.

A reviewer may only act on an application under review, may bounce it back to the
claimant at most twice, and may approve it only once residency, income and asset
gates have all resolved. An approval mints a grant, stamps the consumed income
certification with the tier it produced and reprices the parcel.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_APPLICATION_NOT_INFO_REQUESTED,
    ERR_APPLICATION_NOT_UNDER_REVIEW,
    ERR_ASSET_LIMIT_EXCEEDED,
    ERR_DUPLICATE_PRIMARY_RESIDENCE,
    ERR_EXEMPTION_TYPE_NOT_ELIGIBLE,
    ERR_INCOME_CERTIFICATION_REQUIRED,
    ERR_INCOME_LIMIT_EXCEEDED,
    ERR_INFO_REQUEST_LIMIT_REACHED,
    ERR_OWNERSHIP_NOT_VERIFIED,
    ERR_RESIDENCY_VERIFICATION_FAILED,
    ERR_STALE_PARCEL_VERSION,
)
from test_helpers.assertions import (
    assert_bps,
    assert_calendar_date,
    assert_grant,
    assert_money,
    assert_parcel_decomposition,
    assert_taxpayer_ledger,
)
from test_helpers.constants import ADDR_FARM, ADDR_OAK, ADDR_PINE
from test_helpers.test_users import (
    ANALYST,
    CLERK,
    REVIEWER,
    REVIEWER_2,
    REVIEWER_2_USER_ID,
    REVIEWER_USER_ID,
)


def _info_cycle_world(api):
    """An application under review on a parcel that carries no grants at all.

    Only one cross-match has been recorded, which is what moved the application
    from submitted to under review, so nothing in the chain has ever touched the
    parcel's version.
    """
    fx.set_clock(api)
    program = fx.create_program(api, f.homestead_basic_program())
    parcel = fx.create_parcel(api, f.parcel())
    taxpayer = fx.create_taxpayer(api, f.taxpayer_account())
    application = fx.submitted_application(
        api, parcel["id"], taxpayer["id"], program["id"]
    )
    fx.inject_registry(api, taxpayer["id"], "VOTER_REGISTRY")
    fx.run_checks(api, application["id"], ["VOTER_REGISTRY"])
    return {
        "parcel": parcel,
        "taxpayer": taxpayer,
        "taxpayer_headers": fx.make_taxpayer_headers(taxpayer["id"]),
        "application_id": application["id"],
    }


def test_information_request_cycle_returns_to_review_and_counts_each_round(api):
    """PRD §3.4: "The mildest outcome is a **request for information**, which
    returns the application from `UNDER_REVIEW` to `INFO_REQUESTED` and increments
    its `info_request_round` by 1." PRD §3.4 continues: "a `Taxpayer` acting on
    their own application supplies a fresh `claimed_address_normalized` and
    `claimed_occupancy_date`, which replace the values previously asserted, and
    the application returns from `INFO_REQUESTED` to `UNDER_REVIEW`".

    Design: Difficulty/non_linear_state_machine/application_information_request_cycle_bounded_at_two_rounds
    """
    world = _info_cycle_world(api)
    app_id = world["application_id"]
    version = world["parcel"]["version"]

    first = validate_success(
        api.determine_application(app_id, f.request_info_determination(version), REVIEWER)
    )
    assert first["status"] == "INFO_REQUESTED", (
        f"a request for information parks the application, got {first['status']}"
    )
    assert first["info_request_round"] == 1, (
        f"the first request is round 1, got {first['info_request_round']}"
    )

    answered = validate_success(
        api.respond_info(
            app_id,
            f.respond_info_payload(claimed_occupancy_date="2019-06-15"),
            world["taxpayer_headers"],
        )
    )
    assert answered["status"] == "UNDER_REVIEW", (
        f"answering returns the application to review, got {answered['status']}"
    )
    assert_calendar_date(answered, "claimed_occupancy_date", "2019-06-15")

    second = validate_success(
        api.determine_application(app_id, f.request_info_determination(version), REVIEWER)
    )
    assert second["info_request_round"] == 2, (
        f"the second traversal of the cycle is round 2, got {second['info_request_round']}"
    )

    answered_again = validate_success(
        api.respond_info(
            app_id,
            f.respond_info_payload(claimed_occupancy_date="2019-07-01"),
            world["taxpayer_headers"],
        )
    )
    assert answered_again["status"] == "UNDER_REVIEW", (
        f"the second answer also returns to review, got {answered_again['status']}"
    )
    assert_calendar_date(answered_again, "claimed_occupancy_date", "2019-07-01")


def test_third_information_request_is_refused_and_the_round_counter_holds_at_two(api):
    """PRD §3.4: "A reviewer may do this at most twice: the round counter must be
    below 2 when the request is issued, so the third attempt is refused with
    `ERR_INFO_REQUEST_LIMIT_REACHED`." PRD §3.4 also notes a request for
    information "does **not** increment the parcel's `version`, because no grant
    and no value has changed."

    Design: Difficulty/non_linear_state_machine/application_information_request_cycle_bounded_at_two_rounds
    """
    world = _info_cycle_world(api)
    app_id = world["application_id"]
    parcel_id = world["parcel"]["id"]
    version = world["parcel"]["version"]

    for occupancy_date in ("2019-06-15", "2019-07-01"):
        validate_success(
            api.determine_application(
                app_id, f.request_info_determination(version), REVIEWER
            )
        )
        validate_success(
            api.respond_info(
                app_id,
                f.respond_info_payload(claimed_occupancy_date=occupancy_date),
                world["taxpayer_headers"],
            )
        )

    validate_error(
        api.determine_application(app_id, f.request_info_determination(version), REVIEWER),
        ERR_INFO_REQUEST_LIMIT_REACHED,
        expected_status=409,
    )

    application = validate_success(api.get_application(app_id, REVIEWER))
    assert application["status"] == "UNDER_REVIEW", (
        f"the rejected request leaves the application in review, got {application['status']}"
    )
    assert application["info_request_round"] == 2, (
        f"the counter must stay at 2, got {application['info_request_round']}"
    )

    parcel = validate_success(api.get_parcel(parcel_id, ANALYST))
    assert parcel["version"] == version, (
        f"no request for information may bump the parcel version, got {parcel['version']}"
    )


def _over_ceiling_application_awaiting_information(api):
    """An income-tested application parked at information-requested.

    The claimant's certified household income of 9000000 is half again the
    programme's 6000000 ceiling, so an approval would have a fiscal reason to
    fail as well as a state reason.
    """
    world = fx.approval_world(
        api,
        program=f.disability_income_program(),
        taxpayer=f.taxpayer_account(
            full_name="DANA DISABLED",
            date_of_birth="1970-04-04",
            ssn_last4="1212",
            disability_rating_pct_bps=6000,
        ),
        certification={
            "household_income_cents": 9000000,
            "countable_asset_cents": 1000000,
            "household_size": 2,
            "recertification_due_date": "2026-12-31",
        },
        approve=False,
    )
    world["application"] = validate_success(
        api.determine_application(
            world["application_id"],
            f.request_info_determination(world["parcel"]["version"]),
            REVIEWER,
        )
    )
    return world


def test_state_gate_outranks_the_income_ceiling_on_an_application_awaiting_information(api):
    """PRD §2.10: "Checks are evaluated in the fixed ascending order below, and the
    **first** failure decides the response; later checks are not evaluated at
    all." The state rung reads "The target is in a state that admits the requested
    transition — ... `ERR_APPLICATION_NOT_UNDER_REVIEW`" and sits at position 9,
    while "Household income within the programme ceiling —
    `ERR_INCOME_LIMIT_EXCEEDED`, on an approving determination" is position 30.

    Design: Difficulty/priority_pair_validation_conflict/state_check_beats_income_limit_on_info_requested_application
    """
    world = _over_ceiling_application_awaiting_information(api)

    response = api.determine_application(
        world["application_id"],
        f.approve_determination(world["parcel"]["version"]),
        REVIEWER,
    )
    validate_error(response, ERR_APPLICATION_NOT_UNDER_REVIEW, expected_status=409)
    assert ERR_INCOME_LIMIT_EXCEEDED not in response.text, (
        "the income ceiling sits far below the state rung and must not be reported: "
        f"{response.text}"
    )


def test_a_refused_determination_leaves_certification_application_and_parcel_untouched(api):
    """PRD §3.2: "The certification is created with `status` `PENDING`, its
    `relief_tier` reading `NOT_ASSESSED` and its `relief_multiplier_bps` at 0; the
    tier remains unassessed until a determination consumes the record." PRD §3.4
    adds that only on an approval are "that certification's `relief_tier` and
    `relief_multiplier_bps` ... written from the tier just resolved".

    Design: Difficulty/priority_pair_validation_conflict/state_check_beats_income_limit_on_info_requested_application
    """
    world = _over_ceiling_application_awaiting_information(api)
    parcel_id = world["parcel"]["id"]
    version = world["parcel"]["version"]

    validate_error(
        api.determine_application(
            world["application_id"], f.approve_determination(version), REVIEWER
        ),
        ERR_APPLICATION_NOT_UNDER_REVIEW,
        expected_status=409,
    )

    certification = fx.read_certification(
        api, world["taxpayer"]["id"], world["certification"]["id"]
    )
    assert certification["status"] == "CERTIFIED", (
        f"the revenue match certified the income, got {certification['status']}"
    )
    assert certification["relief_tier"] == "NOT_ASSESSED", (
        "no determination consumed the record, so the tier stays unassessed, got "
        f"{certification['relief_tier']}"
    )
    assert_bps(certification, "relief_multiplier_bps", 0)

    application = validate_success(api.get_application(world["application_id"], REVIEWER))
    assert application["status"] == "INFO_REQUESTED", (
        f"the refused approval leaves the application parked, got {application['status']}"
    )
    assert application["info_request_round"] == 1, (
        f"the round counter is untouched at 1, got {application['info_request_round']}"
    )

    parcel = validate_success(api.get_parcel(parcel_id, ANALYST))
    assert parcel["version"] == version, (
        f"a refused determination never reprices the parcel, got {parcel['version']}"
    )
    assert_parcel_decomposition(
        parcel,
        assessed_value_cents=33600000,
        exempt_value_cents=0,
        taxable_value_cents=33600000,
        exemption_status="UNEXEMPTED",
    )

    rows, meta = validate_paginated(api.list_grants(REVIEWER, parcel_id=parcel_id))
    assert meta["total_count"] == 0, (
        f"no grant may exist on the parcel, got {meta['total_count']}"
    )
    assert rows == [], f"unexpected grants on the parcel: {rows}"


def test_income_exactly_at_the_ceiling_yields_the_partial_tier_and_clears_the_asset_gate(api):
    """PRD §3.4: "Every band boundary is inclusive at its upper edge, so income
    exactly equal to the ceiling yields `TIER_PARTIAL`, and income one cent above
    the ceiling is rejected." PRD §3.4 also fixes the asset gate: "when the
    programme declares an `asset_limit_cents`, a certified `countable_asset_cents`
    strictly greater than that limit is refused with `ERR_ASSET_LIMIT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/income_and_asset_tests_at_exact_limits_versus_one_cent_over
    """
    world = fx.approval_world(
        api,
        program=f.disability_income_program(),
        taxpayer=f.taxpayer_account(
            full_name="EDGE EXACTLY",
            date_of_birth="1970-04-04",
            ssn_last4="6000",
            disability_rating_pct_bps=6000,
        ),
        certification={
            "household_income_cents": 6000000,
            "countable_asset_cents": 4000000,
            "household_size": 2,
            "recertification_due_date": "2026-12-31",
        },
    )

    certification = fx.read_certification(
        api, world["taxpayer"]["id"], world["certification"]["id"]
    )
    assert certification["status"] == "CERTIFIED", (
        f"the revenue match certified the income, got {certification['status']}"
    )
    assert certification["relief_tier"] == "TIER_PARTIAL", (
        "income equal to the ceiling is neither rejected nor promoted to the high "
        f"band, got {certification['relief_tier']}"
    )
    assert_bps(certification, "relief_multiplier_bps", 5000)

    # 6000000 * 3000 / 10000 = 1800000... the statutory share is 10080000 and the
    # partial tier halves it, leaving 5040000 under the 12000000 ceiling.
    assert_grant(
        world["grant"],
        benefit_status="ACTIVE",
        benefit_amount_cents=5040000,
        relief_multiplier_bps=5000,
    )

    parcel = validate_success(api.get_parcel(world["parcel"]["id"], ANALYST))
    assert_parcel_decomposition(
        parcel,
        assessed_value_cents=33600000,
        exempt_value_cents=5040000,
        taxable_value_cents=28560000,
        exemption_status="PARTIALLY_EXEMPT",
    )


def test_income_one_cent_past_the_ceiling_is_refused_and_mints_nothing(api):
    """PRD §3.4: "when the income strictly exceeds the limit the approval is
    refused with `ERR_INCOME_LIMIT_EXCEEDED`. Every band boundary is inclusive at
    its upper edge, so income exactly equal to the ceiling yields `TIER_PARTIAL`,
    and income one cent above the ceiling is rejected."

    Design: Difficulty/boundary_precision_check/income_and_asset_tests_at_exact_limits_versus_one_cent_over
    """
    world = fx.approval_world(
        api,
        program=f.disability_income_program(),
        parcel=f.farm_parcel(),
        taxpayer=f.taxpayer_account(
            full_name="OVER BYONECENT",
            date_of_birth="1971-05-05",
            ssn_last4="6001",
            mailing_address_normalized=ADDR_FARM,
        ),
        certification={
            "household_income_cents": 6000001,
            "countable_asset_cents": 4000000,
            "household_size": 2,
            "recertification_due_date": "2026-12-31",
        },
        approve=False,
    )
    parcel_id = world["parcel"]["id"]
    version = world["parcel"]["version"]

    validate_error(
        api.determine_application(
            world["application_id"], f.approve_determination(version), REVIEWER
        ),
        ERR_INCOME_LIMIT_EXCEEDED,
        expected_status=422,
    )

    certification = fx.read_certification(
        api, world["taxpayer"]["id"], world["certification"]["id"]
    )
    assert certification["status"] == "CERTIFIED", (
        f"the revenue figure still agreed with the filing, got {certification['status']}"
    )
    assert certification["relief_tier"] == "NOT_ASSESSED", (
        "a refused approval consumes nothing, so no tier is stamped, got "
        f"{certification['relief_tier']}"
    )

    application = validate_success(api.get_application(world["application_id"], REVIEWER))
    assert application["status"] == "UNDER_REVIEW", (
        f"the refused approval leaves the application in review, got {application['status']}"
    )

    parcel = validate_success(api.get_parcel(parcel_id, ANALYST))
    assert parcel["version"] == version, (
        f"a refused approval never reprices the parcel, got {parcel['version']}"
    )
    assert_parcel_decomposition(
        parcel,
        assessed_value_cents=20800000,
        exempt_value_cents=0,
        taxable_value_cents=20800000,
        exemption_status="UNEXEMPTED",
    )


def _pending_certification_world(api):
    """An application under review whose income filing has nothing to match against.

    No revenue row was ever injected for the claimant, so the income cross-match
    finds no record and the certification is left uncertified while residency is
    fully verified.
    """
    return fx.approval_world(
        api,
        program=f.disability_income_program(),
        taxpayer=f.taxpayer_account(
            full_name="DEREK DEPENDENT",
            date_of_birth="1972-09-09",
            ssn_last4="5151",
            disability_rating_pct_bps=7000,
        ),
        certification={},
        income_registry=False,
        approve=False,
    )


def test_approval_waits_while_the_income_certification_is_still_pending(api):
    """PRD §3.4: "When the programme's `requires_income_certification` is true, a
    certification must exist for the claimant with `certification_year` equal to
    the application's `tax_year` and `status` `CERTIFIED`; otherwise the approval
    is refused with `ERR_INCOME_CERTIFICATION_REQUIRED`." PRD §3.3: "`NO_RECORD`
    is written when no registry record exists at all for that taxpayer-and-source
    pair".

    Design: Difficulty/cross_entity_state_dependency/determination_waits_for_income_certification_to_leave_pending
    """
    world = _pending_certification_world(api)
    parcel_id = world["parcel"]["id"]
    version = world["parcel"]["version"]

    validate_error(
        api.determine_application(
            world["application_id"], f.approve_determination(version), REVIEWER
        ),
        ERR_INCOME_CERTIFICATION_REQUIRED,
        expected_status=422,
    )

    checks, _ = validate_paginated(
        api.list_verification_checks(
            world["application_id"], REVIEWER, source="INCOME_DOR"
        )
    )
    assert len(checks) == 1, f"exactly one income cross-match was recorded, got {len(checks)}"
    assert checks[0]["result"] == "NO_RECORD", (
        f"with no revenue row on file the result is no-record, got {checks[0]['result']}"
    )

    certification = fx.read_certification(
        api, world["taxpayer"]["id"], world["certification"]["id"]
    )
    assert certification["status"] == "PENDING", (
        f"a no-record income check leaves the filing pending, got {certification['status']}"
    )

    application = validate_success(api.get_application(world["application_id"], REVIEWER))
    assert application["status"] == "UNDER_REVIEW", (
        f"the refused approval leaves the application in review, got {application['status']}"
    )

    parcel = validate_success(api.get_parcel(parcel_id, ANALYST))
    assert parcel["version"] == version, (
        f"a refused approval never reprices the parcel, got {parcel['version']}"
    )


def test_the_same_approval_succeeds_once_a_revenue_match_certifies_the_income(api):
    """PRD §3.3: "an `INCOME_DOR` check whose `result` is `MATCH` certifies income:
    the very certification the comparison selected moves from `PENDING` to
    `CERTIFIED` and its `version` increments by 1." PRD §3.4: "when twice the
    certified `household_income_cents` is no greater than the programme's
    `income_limit_cents` — that is, when income is at or below half the ceiling —
    the tier is `TIER_FULL` and the `relief_multiplier_bps` is 10000".

    Design: Difficulty/cross_entity_state_dependency/determination_waits_for_income_certification_to_leave_pending
    """
    world = _pending_certification_world(api)
    app_id = world["application_id"]
    version = world["parcel"]["version"]

    validate_error(
        api.determine_application(app_id, f.approve_determination(version), REVIEWER),
        ERR_INCOME_CERTIFICATION_REQUIRED,
        expected_status=422,
    )

    fx.inject_registry(
        api,
        world["taxpayer"]["id"],
        "INCOME_DOR",
        record_effective_date="2026-03-01",
        reported_income_cents=3000000,
    )
    second_check = fx.run_checks(api, app_id, ["INCOME_DOR"])[0]
    assert second_check["result"] == "MATCH", (
        f"the revenue figure now agrees with the filing, got {second_check['result']}"
    )

    certification = fx.read_certification(
        api, world["taxpayer"]["id"], world["certification"]["id"]
    )
    assert certification["status"] == "CERTIFIED", (
        f"a matching income check certifies the filing, got {certification['status']}"
    )

    # The identical payload, still naming the version first read, now succeeds.
    determined = validate_success(
        api.determine_application(app_id, f.approve_determination(version), REVIEWER)
    )
    assert determined["status"] == "APPROVED", (
        f"the dependency was on state, not on the request, got {determined['status']}"
    )

    stamped = fx.read_certification(
        api, world["taxpayer"]["id"], world["certification"]["id"]
    )
    assert stamped["relief_tier"] == "TIER_FULL", (
        f"3000000 doubled is exactly the 6000000 ceiling, got {stamped['relief_tier']}"
    )
    assert_bps(stamped, "relief_multiplier_bps", 10000)

    grant = validate_success(api.get_grant(determined["resulting_grant_id"], REVIEWER))
    assert_grant(
        grant,
        benefit_status="ACTIVE",
        benefit_amount_cents=10080000,
        relief_multiplier_bps=10000,
    )

    parcel = validate_success(api.get_parcel(world["parcel"]["id"], ANALYST))
    assert_parcel_decomposition(
        parcel,
        assessed_value_cents=33600000,
        exempt_value_cents=10080000,
        taxable_value_cents=23520000,
        exemption_status="PARTIALLY_EXEMPT",
    )


def test_answering_an_information_request_that_was_never_made_is_refused(api):
    """PRD §3.4: "The taxpayer closes the cycle by answering: a `Taxpayer` acting on
    their own application supplies a fresh `claimed_address_normalized` and
    `claimed_occupancy_date`, which replace the values previously asserted, and the
    application returns from `INFO_REQUESTED` to `UNDER_REVIEW` with its `version`
    incremented by 1. Answering an application that is not in `INFO_REQUESTED` is
    refused with `ERR_APPLICATION_NOT_INFO_REQUESTED`." PRD §2.10 rung 9
    places the state check last, and the error table gives
    `ERR_APPLICATION_NOT_INFO_REQUESTED` an HTTP 409.

    Design: Corner/state_machines/respond_info_while_under_review_is_rejected
    """
    world = _info_cycle_world(api)
    app_id = world["application_id"]

    before = validate_success(api.get_application(app_id, REVIEWER))
    assert before["status"] == "UNDER_REVIEW", (
        f"the first cross-match put the application under review, got {before['status']}"
    )

    # A well-formed answer, from the owner, to a request that was never issued.
    validate_error(
        api.respond_info(
            app_id,
            f.respond_info_payload("2020-01-01", claimed_address_normalized=ADDR_PINE),
            world["taxpayer_headers"],
        ),
        ERR_APPLICATION_NOT_INFO_REQUESTED,
        expected_status=409,
    )

    after = validate_success(api.get_application(app_id, REVIEWER))
    assert after["status"] == "UNDER_REVIEW", (
        f"the refused answer leaves the application under review, got {after['status']}"
    )
    assert after["claimed_address_normalized"] == ADDR_OAK, (
        "the refused answer must not overwrite the address on file, got "
        f"{after['claimed_address_normalized']!r}"
    )
    assert_calendar_date(after, "claimed_occupancy_date", "2019-06-01")
    assert after["info_request_round"] == 0, (
        f"no round was ever opened, got {after['info_request_round']}"
    )


def test_a_second_determination_on_an_approved_application_mints_nothing(api):
    """PRD §3.4: "Determination is the pivot of the whole system, and it belongs
    exclusively to an `ExemptionsReviewer` acting on an application whose `status` is
    `UNDER_REVIEW` — any other status is refused with
    `ERR_APPLICATION_NOT_UNDER_REVIEW`." PRD §2.10 orders
    the optimistic-concurrency check at 8 and the state check at 9, and "the
    **first** failure decides the response".

    Design: Corner/state_machines/determine_on_an_already_approved_application_returns_4xx
    """
    world = fx.approved_homestead_world(api)
    parcel_id = world["parcel"]["id"]
    app_id = world["application_id"]

    # Re-read the parcel so the version the second call carries is current: the
    # concurrency gate cannot fire, leaving the state guard as the only objection.
    repriced = validate_success(api.get_parcel(parcel_id, ANALYST))
    assert repriced["version"] == 2, (
        f"creation and the approval are two mutations, got version {repriced['version']}"
    )

    validate_error(
        api.determine_application(
            app_id,
            f.deny_determination(
                repriced["version"], denial_reason="Reviewer changed their mind."
            ),
            REVIEWER_2,
        ),
        ERR_APPLICATION_NOT_UNDER_REVIEW,
        expected_status=409,
    )

    unchanged = validate_success(api.get_parcel(parcel_id, ANALYST))
    assert unchanged["version"] == repriced["version"], (
        "the rejected determination is not a mutation, so the parcel version must "
        f"hold at {repriced['version']}, got {unchanged['version']}"
    )

    application = validate_success(api.get_application(app_id, REVIEWER))
    assert application["status"] == "APPROVED", (
        f"the approval stands, got {application['status']}"
    )
    assert application["denial_reason"] is None, (
        f"no denial reason may be recorded, got {application['denial_reason']!r}"
    )
    assert application["resulting_grant_id"] == world["grant_id"], (
        "the application still names the grant its approval minted, got "
        f"{application['resulting_grant_id']}"
    )

    rows, meta = validate_paginated(api.list_grants(REVIEWER, parcel_id=parcel_id))
    assert meta["total_count"] == 1, (
        f"the parcel carries exactly one grant, got {meta['total_count']}"
    )
    assert rows[0]["id"] == world["grant_id"], (
        f"unexpected grant on the parcel: {rows[0]['id']}"
    )


def test_one_approval_mints_the_grant_and_reprices_the_parcel_together(api):
    """PRD §3.4: "The approval then writes the grant and cascades outward. A new grant
    row is created with `benefit_status` `ACTIVE`, its `application_id`, `parcel_id`,
    `taxpayer_id` and `program_id` copied from the application ... The application's
    `resulting_grant_id` is stamped with the new grant's identifier, mirroring the
    grant's own `application_id`, and `determined_by_user_id` records the deciding
    reviewer." PRD §3.4 continues: "Three further consequences follow, in order. The
    new grant entering the active set re-runs the parcel value decomposition, rewriting
    `capped_value_cents`, `assessed_value_cents`, `exempt_value_cents`,
    `taxable_value_cents` and the `applied_exempt_value_cents` of every `ACTIVE` grant
    on that parcel. The rewritten exempt total re-derives the parcel's
    `exemption_status` and increments the parcel's `version` by 1."

    Design: Corner/state_machines/approval_mints_a_grant_and_reprices_the_parcel_in_one_request
    """
    world = fx.approval_world(api, approve=False)
    parcel_id = world["parcel"]["id"]
    assert world["parcel"]["version"] == 1, (
        f"the parcel has not been repriced yet, got version {world['parcel']['version']}"
    )

    determined = validate_success(
        api.determine_application(
            world["application_id"],
            f.approve_determination(world["parcel"]["version"]),
            REVIEWER,
        )
    )

    assert determined["status"] == "APPROVED", (
        f"the determination approves the claim, got {determined['status']}"
    )
    assert determined["determined_by_user_id"] == REVIEWER_USER_ID, (
        "the deciding reviewer is stamped on the application, got "
        f"{determined['determined_by_user_id']!r}"
    )
    assert determined["resulting_grant_id"], (
        f"the approval must name its grant, got {determined['resulting_grant_id']!r}"
    )

    # 33600000 * 2500 / 10000 = 8400000, under the 10000000 ceiling, whole share.
    grant = validate_success(api.get_grant(determined["resulting_grant_id"], REVIEWER))
    assert_grant(
        grant,
        benefit_status="ACTIVE",
        benefit_amount_cents=8400000,
        applied_exempt_value_cents=8400000,
        relief_multiplier_bps=10000,
        frozen_value_cents=None,
        portable_balance_cents=None,
    )
    assert grant["exemption_type"] == "HOMESTEAD_BASIC", (
        f"the grant records the programme classification, got {grant['exemption_type']}"
    )
    assert grant["effective_tax_year"] == 2026, (
        f"the grant takes the application's tax year, got {grant['effective_tax_year']}"
    )
    assert_bps(grant, "ownership_pct_bps_snapshot", 10000)
    assert grant["first_eligible_tax_year"] == 2019, (
        "the first eligible year is the calendar year the verified occupancy began, "
        f"got {grant['first_eligible_tax_year']}"
    )

    parcel = validate_success(api.get_parcel(parcel_id, ANALYST))
    assert_parcel_decomposition(
        parcel,
        assessed_value_cents=33600000,
        exempt_value_cents=8400000,
        taxable_value_cents=25200000,
        exemption_status="PARTIALLY_EXEMPT",
    )
    assert parcel["version"] == world["parcel"]["version"] + 1, (
        "the repricing increments the parcel version exactly once, got "
        f"{parcel['version']} from {world['parcel']['version']}"
    )


def test_a_veteran_claim_scales_the_statutory_share_by_the_disability_rating(api):
    """PRD §3.4: "Third, the disability adjustment: the running figure multiplied by
    the claimant's `disability_rating_pct_bps` and divided by ten thousand when and
    only when the programme's `program_code` is `VETERAN_DISABILITY`, and multiplied
    by ten thousand basis points — that is, left unchanged — for every other
    classification."

    Design: Corner/calculations/veteran_benefit_multiplies_relief_by_the_disability_rating
    """
    world = fx.approval_world(
        api,
        program=f.veteran_disability_program(
            relief_pct_bps=5000, max_exempt_value_cents=20000000, priority_rank=30
        ),
        taxpayer=f.taxpayer_account(
            full_name="VICTOR VETERAN",
            date_of_birth="1968-04-02",
            ssn_last4="7788",
            disability_rating_pct_bps=7000,
        ),
    )

    # 33600000 * 5000/10000 = 16800000, then * 7000/10000 = 11760000, under the
    # 20000000 ceiling and taken at the whole share.
    assert_grant(
        world["grant"],
        benefit_status="ACTIVE",
        benefit_amount_cents=11760000,
        applied_exempt_value_cents=11760000,
        relief_multiplier_bps=10000,
    )
    assert world["grant"]["exemption_type"] == "VETERAN_DISABILITY", (
        f"the grant snapshots the classification, got {world['grant']['exemption_type']}"
    )

    parcel = validate_success(api.get_parcel(world["parcel"]["id"], ANALYST))
    assert_parcel_decomposition(
        parcel,
        assessed_value_cents=33600000,
        exempt_value_cents=11760000,
        taxable_value_cents=21840000,
        exemption_status="PARTIALLY_EXEMPT",
    )


def test_income_at_exactly_three_quarters_of_the_ceiling_lands_in_the_high_band(api):
    """PRD §3.4: "otherwise, when four times the income is no greater than three
    times the limit — income at or below three quarters of the ceiling — the tier is
    `TIER_HIGH` at 7500 basis points ... Every band boundary is inclusive at its
    upper edge". PRD §3.4 adds: "where an income certification was consumed, that
    certification's `relief_tier` and `relief_multiplier_bps` are written from the
    tier just resolved".

    Design: Corner/calculations/income_tier_at_exactly_seventy_five_percent_of_the_limit_is_tier_high
    """
    world = fx.approval_world(
        api,
        program=f.disability_income_program(
            relief_pct_bps=3000,
            max_exempt_value_cents=10000000,
            income_limit_cents=6000000,
            asset_limit_cents=2000000,
            priority_rank=20,
        ),
        certification={
            "certification_year": 2026,
            "household_income_cents": 4500000,
            "countable_asset_cents": 1000000,
            "household_size": 3,
            "recertification_due_date": "2027-04-15",
        },
        approve=False,
    )

    # 4 * 4500000 == 3 * 6000000 exactly, the inclusive upper edge of the band.
    assert 4 * 4500000 == 3 * 6000000, "the fixture must sit on the band boundary"
    assert world["certification"]["status"] == "CERTIFIED", (
        "the matching revenue record certifies the declaration, got "
        f"{world['certification']['status']}"
    )

    determined = validate_success(
        api.determine_application(
            world["application_id"],
            f.approve_determination(world["parcel"]["version"]),
            REVIEWER,
        )
    )

    stamped = fx.read_certification(
        api, world["taxpayer"]["id"], world["certification"]["id"]
    )
    assert stamped["relief_tier"] == "TIER_HIGH", (
        f"the boundary belongs to the high band, got {stamped['relief_tier']}"
    )
    assert_bps(stamped, "relief_multiplier_bps", 7500)

    # 33600000 * 3000/10000 = 10080000, then * 7500/10000 = 7560000, under the
    # 10000000 ceiling.
    grant = validate_success(api.get_grant(determined["resulting_grant_id"], REVIEWER))
    assert_grant(
        grant,
        benefit_status="ACTIVE",
        benefit_amount_cents=7560000,
        applied_exempt_value_cents=7560000,
        relief_multiplier_bps=7500,
    )

    parcel = validate_success(api.get_parcel(world["parcel"]["id"], ANALYST))
    assert_parcel_decomposition(
        parcel,
        assessed_value_cents=33600000,
        exempt_value_cents=7560000,
        taxable_value_cents=26040000,
        exemption_status="PARTIALLY_EXEMPT",
    )


def test_a_half_share_owner_receives_exactly_half_the_statutory_benefit(api):
    """PRD §3.4: "Fifth, the ownership share: the result is multiplied by the grant's
    `ownership_pct_bps_snapshot` and divided by ten thousand." PRD §3.4 also fixes
    where that snapshot comes from: "its `ownership_pct_bps_snapshot` taken from the
    `ownership_pct_bps` of the verified ownership record that satisfied the gate".

    Design: Corner/calculations/fractional_ownership_share_prorates_the_benefit
    """
    world = fx.approval_world(api, ownership={"ownership_pct_bps": 5000})

    # The 10000000 ceiling does not bind on 8400000, so only the share halves it.
    assert_bps(world["grant"], "ownership_pct_bps_snapshot", 5000)
    assert_grant(
        world["grant"],
        benefit_status="ACTIVE",
        benefit_amount_cents=4200000,
        applied_exempt_value_cents=4200000,
        relief_multiplier_bps=10000,
    )

    parcel = validate_success(api.get_parcel(world["parcel"]["id"], ANALYST))
    assert_parcel_decomposition(
        parcel,
        assessed_value_cents=33600000,
        exempt_value_cents=4200000,
        taxable_value_cents=29400000,
        exemption_status="PARTIALLY_EXEMPT",
    )


def test_only_the_income_tested_programme_demands_a_certification_on_file(api):
    """PRD §3.4: "When the programme's `requires_income_certification` is true, a
    certification must exist for the claimant with `certification_year` equal to the
    application's `tax_year` and `status` `CERTIFIED`; otherwise the approval is
    refused with `ERR_INCOME_CERTIFICATION_REQUIRED` ... When a programme is not
    income-tested, no certification is consumed and the grant's
    `relief_multiplier_bps` is simply 10000."

    Design: Corner/validations/income_certification_gate_applies_only_to_income_tested_programs
    """
    untested = fx.approval_world(api, program=f.homestead_basic_program(), approve=False)
    tested = fx.approval_world(
        api,
        clock=None,
        program=f.disability_income_program(),
        parcel=f.farm_parcel(),
        taxpayer=f.taxpayer_account(
            full_name="DANA CLAIMANT",
            date_of_birth="1970-09-09",
            ssn_last4="1212",
            mailing_address_normalized=ADDR_FARM,
        ),
        approve=False,
    )
    assert untested["certification"] is None, "no certification exists anywhere"
    assert tested["certification"] is None, "no certification exists anywhere"

    # The programme that is not income-tested approves with nothing on file.
    determined = validate_success(
        api.determine_application(
            untested["application_id"],
            f.approve_determination(untested["parcel"]["version"]),
            REVIEWER,
        )
    )
    assert_grant(
        validate_success(api.get_grant(determined["resulting_grant_id"], REVIEWER)),
        benefit_status="ACTIVE",
        benefit_amount_cents=8400000,
        relief_multiplier_bps=10000,
    )

    # The income-tested one refuses on the identical evidence.
    tested_parcel_id = tested["parcel"]["id"]
    tested_version = tested["parcel"]["version"]
    validate_error(
        api.determine_application(
            tested["application_id"],
            f.approve_determination(tested_version),
            REVIEWER,
        ),
        ERR_INCOME_CERTIFICATION_REQUIRED,
        expected_status=422,
    )

    refused = validate_success(
        api.get_application(tested["application_id"], REVIEWER)
    )
    assert refused["status"] == "UNDER_REVIEW", (
        f"the refused approval leaves the claim in review, got {refused['status']}"
    )
    assert refused["resulting_grant_id"] is None, (
        f"no grant may be stamped on the application, got {refused['resulting_grant_id']}"
    )

    parcel = validate_success(api.get_parcel(tested_parcel_id, ANALYST))
    assert parcel["version"] == tested_version, (
        f"a refused approval never reprices the parcel, got {parcel['version']}"
    )
    assert_parcel_decomposition(
        parcel,
        assessed_value_cents=20800000,
        exempt_value_cents=0,
        taxable_value_cents=20800000,
        exemption_status="UNEXEMPTED",
    )

    rows, meta = validate_paginated(
        api.list_grants(REVIEWER, parcel_id=tested_parcel_id)
    )
    assert meta["total_count"] == 0, (
        f"no grant may exist on the income-tested parcel, got {meta['total_count']}"
    )
    assert rows == [], f"unexpected grants on the parcel: {rows}"


def _two_claims_failing_residency(api):
    """Two claims that both fail residency, only one of which is properly evidenced.

    No registry row exists for either claimant, so the single voter cross-match on
    each application reads ``NO_RECORD`` and the residency gate is violated twice
    over. The first claim rests on a taxpayer affidavit and the second on the deed
    registry, which is the only difference between them.
    """
    fx.set_clock(api)
    program = fx.create_program(api, f.homestead_basic_program())
    first_parcel = fx.create_parcel(api, f.parcel())
    second_parcel = fx.create_parcel(api, f.farm_parcel())
    first_taxpayer = fx.create_taxpayer(api, f.taxpayer_account())
    second_taxpayer = fx.create_taxpayer(
        api,
        f.taxpayer_account(
            full_name="DANA CLAIMANT",
            date_of_birth="1970-09-09",
            ssn_last4="1212",
            mailing_address_normalized=ADDR_FARM,
        ),
    )
    first_ownership = fx.add_ownership(
        api,
        first_parcel["id"],
        first_taxpayer["id"],
        source_system="TAXPAYER_AFFIDAVIT",
    )
    second_ownership = fx.add_ownership(
        api, second_parcel["id"], second_taxpayer["id"]
    )
    first_application = fx.submitted_application(
        api, first_parcel["id"], first_taxpayer["id"], program["id"]
    )
    fx.run_checks(api, first_application["id"], ["VOTER_REGISTRY"])
    second_application = fx.submitted_application(
        api,
        second_parcel["id"],
        second_taxpayer["id"],
        program["id"],
        claimed_address_normalized=ADDR_FARM,
    )
    fx.run_checks(api, second_application["id"], ["VOTER_REGISTRY"])
    return {
        "first_parcel": first_parcel,
        "second_parcel": second_parcel,
        "first_ownership": first_ownership,
        "second_ownership": second_ownership,
        "first_application": first_application,
        "second_application": second_application,
    }


def test_an_unverified_ownership_record_is_reported_ahead_of_the_failed_residency(api):
    """PRD §3.4: "The ownership gate requires a `VERIFIED` ownership record linking
    the application's `taxpayer_id` to its `parcel_id` ... Absent such a record, the
    approval is refused with `ERR_OWNERSHIP_NOT_VERIFIED`. Residency cross-matching
    is the `VOTER_REGISTRY` and `DEED_REGISTRY` latest-check rule of §3.3, refused
    with `ERR_RESIDENCY_VERIFICATION_FAILED`." PRD §2.10 orders those two gates at
    rungs 13 and 14 and rules that "the **first** failure decides the response".
    PRD §3.1: "a record resting on a `TAXPAYER_AFFIDAVIT` is created `UNVERIFIED`.
    Only a `VERIFIED` record can support an approval."

    Design: Corner/validations/unverified_ownership_outranks_the_residency_check_failure
    """
    world = _two_claims_failing_residency(api)
    assert world["first_ownership"]["status"] == "UNVERIFIED", (
        f"an affidavit record is untrusted, got {world['first_ownership']['status']}"
    )
    assert world["second_ownership"]["status"] == "VERIFIED", (
        f"a deed-registry record is trusted, got {world['second_ownership']['status']}"
    )

    # Both gates are violated here, and the earlier rung is the one reported.
    response = api.determine_application(
        world["first_application"]["id"],
        f.approve_determination(world["first_parcel"]["version"]),
        REVIEWER,
    )
    validate_error(response, ERR_OWNERSHIP_NOT_VERIFIED, expected_status=422)
    assert ERR_RESIDENCY_VERIFICATION_FAILED not in response.text, (
        "the ownership rung outranks the residency rung, so the later failure must "
        f"stay unreported: {response.text}"
    )

    # The second claim differs only in its evidence trail, which exposes rung 14.
    validate_error(
        api.determine_application(
            world["second_application"]["id"],
            f.approve_determination(world["second_parcel"]["version"]),
            REVIEWER,
        ),
        ERR_RESIDENCY_VERIFICATION_FAILED,
        expected_status=422,
    )

    for key, parcel_key in (
        ("first_application", "first_parcel"),
        ("second_application", "second_parcel"),
    ):
        application = validate_success(
            api.get_application(world[key]["id"], REVIEWER)
        )
        assert application["status"] == "UNDER_REVIEW", (
            f"the refused approval leaves {key} in review, got {application['status']}"
        )
        assert application["resulting_grant_id"] is None, (
            f"no grant may be stamped on {key}, got {application['resulting_grant_id']}"
        )
        parcel = validate_success(api.get_parcel(world[parcel_key]["id"], ANALYST))
        assert parcel["version"] == world[parcel_key]["version"], (
            f"a refused approval never reprices {parcel_key}, got version "
            f"{parcel['version']}"
        )


def test_the_asset_ceiling_is_only_reached_once_the_income_tier_has_resolved(api):
    """PRD §3.4: "when the income strictly exceeds the limit the approval is refused
    with `ERR_INCOME_LIMIT_EXCEEDED` ... The asset test is a separate gate evaluated
    only after the tier has resolved: when the programme declares an
    `asset_limit_cents`, a certified `countable_asset_cents` strictly greater than
    that limit is refused with `ERR_ASSET_LIMIT_EXCEEDED`." PRD §3.4 also fixes which
    record is read: "Where more than one such certification exists, the one with the
    greatest `created_at` is the one consumed."

    Design: Corner/validations/income_tier_resolves_before_the_asset_test_is_applied
    """
    world = fx.approval_world(
        api,
        program=f.disability_income_program(asset_limit_cents=2000000),
        certification={
            "household_income_cents": 7000000,
            "countable_asset_cents": 1000000,
            "household_size": 2,
            "recertification_due_date": "2026-12-31",
        },
        approve=False,
    )
    taxpayer_id = world["taxpayer"]["id"]
    parcel_id = world["parcel"]["id"]
    version = world["parcel"]["version"]
    assert world["certification"]["status"] == "CERTIFIED", (
        f"the revenue figure agreed with the filing, got {world['certification']['status']}"
    )

    # Assets of 1000000 are well inside the 2000000 ceiling, so only income fails.
    over_income = api.determine_application(
        world["application_id"], f.approve_determination(version), REVIEWER
    )
    validate_error(over_income, ERR_INCOME_LIMIT_EXCEEDED, expected_status=422)
    assert ERR_ASSET_LIMIT_EXCEEDED not in over_income.text, (
        f"the assets were never the problem: {over_income.text}"
    )

    # A later filing halves the income into the partial band and blows the assets.
    # The clock advances first so the new filing's `created_at` is strictly the
    # greatest: PRD §3.3 selects the row with the greatest `created_at` and only
    # breaks a tie in favour of the greatest `version`, and the first filing has
    # already been carried to version 2 by its own certification.
    fx.set_clock(api, "2026-08-15T00:00:00Z")
    second = fx.create_certification(
        api,
        taxpayer_id,
        household_income_cents=5000000,
        countable_asset_cents=5000000,
        household_size=2,
        recertification_due_date="2026-12-31",
    )
    fx.inject_registry(
        api,
        taxpayer_id,
        "INCOME_DOR",
        record_effective_date="2026-03-01",
        reported_income_cents=5000000,
    )
    fx.run_checks(api, world["application_id"], ["INCOME_DOR"])
    certified = fx.read_certification(api, taxpayer_id, second["id"])
    assert certified["status"] == "CERTIFIED", (
        f"the fresh revenue match certified the later filing, got {certified['status']}"
    )

    # 5000000 is inside the 6000000 ceiling, so the tier resolves and the assets
    # then decide: 5000000 is strictly above the 2000000 asset limit.
    over_assets = api.determine_application(
        world["application_id"], f.approve_determination(version), REVIEWER
    )
    validate_error(over_assets, ERR_ASSET_LIMIT_EXCEEDED, expected_status=422)
    assert ERR_INCOME_LIMIT_EXCEEDED not in over_assets.text, (
        f"the income cleared its ceiling this time: {over_assets.text}"
    )

    consumed = fx.read_certification(api, taxpayer_id, second["id"])
    assert consumed["relief_tier"] == "NOT_ASSESSED", (
        "no approval ever consumed the record, so no tier is stamped, got "
        f"{consumed['relief_tier']}"
    )
    assert_bps(consumed, "relief_multiplier_bps", 0)

    application = validate_success(
        api.get_application(world["application_id"], REVIEWER)
    )
    assert application["status"] == "UNDER_REVIEW", (
        f"both refusals leave the claim in review, got {application['status']}"
    )
    assert application["resulting_grant_id"] is None, (
        f"no grant may be stamped, got {application['resulting_grant_id']}"
    )

    parcel = validate_success(api.get_parcel(parcel_id, ANALYST))
    assert parcel["version"] == version, (
        f"neither refusal reprices the parcel, got version {parcel['version']}"
    )
    assert_parcel_decomposition(
        parcel,
        assessed_value_cents=33600000,
        exempt_value_cents=0,
        taxable_value_cents=33600000,
        exemption_status="UNEXEMPTED",
    )


def test_a_fifty_year_old_fails_the_senior_gate_and_cannot_open_a_second_residence(api):
    """PRD §3.4: "Programme eligibility depends on the classification: a
    `SENIOR_FREEZE` claim requires the claimant to reach the age of 65 on or before
    January 1 of the claimed `tax_year`, measured from `date_of_birth` ... A failure
    here is refused with `ERR_EXEMPTION_TYPE_NOT_ELIGIBLE`." PRD §3.1: "Separately,
    nobody may have two primary residences at once: a new `PRIMARY_RESIDENCE`
    interval must not overlap another `PRIMARY_RESIDENCE` interval held by the same
    taxpayer on a *different* parcel, and a violation is rejected with
    `ERR_DUPLICATE_PRIMARY_RESIDENCE`."

    Design: Corner/errors/senior_age_test_and_second_primary_residence_return_4xx
    """
    world = fx.approval_world(
        api,
        program=f.senior_freeze_program(),
        taxpayer=f.taxpayer_account(
            full_name="SAMUEL SENIOR",
            date_of_birth="1975-05-05",
            ssn_last4="5050",
        ),
        approve=False,
    )
    taxpayer_id = world["taxpayer"]["id"]
    parcel_version = world["parcel"]["version"]

    # The ownership record is VERIFIED and both gating cross-matches are matches,
    # so the only gate left to fail is the age test: 50 on 2026-01-01.
    assert world["ownership"]["status"] == "VERIFIED", (
        f"the ownership gate must be passed, got {world['ownership']['status']}"
    )
    response = api.determine_application(
        world["application_id"], f.approve_determination(parcel_version), REVIEWER
    )
    validate_error(response, ERR_EXEMPTION_TYPE_NOT_ELIGIBLE, expected_status=422)
    assert ERR_OWNERSHIP_NOT_VERIFIED not in response.text, (
        f"the ownership gate was passed, so it must not be reported: {response.text}"
    )
    assert ERR_RESIDENCY_VERIFICATION_FAILED not in response.text, (
        f"the residency gate was passed too: {response.text}"
    )

    refused = validate_success(
        api.get_application(world["application_id"], REVIEWER)
    )
    assert refused["status"] == "UNDER_REVIEW", (
        f"the refused determination leaves the claim under review, got {refused['status']}"
    )
    assert refused["resulting_grant_id"] is None, (
        f"no grant may have been minted, got {refused['resulting_grant_id']!r}"
    )
    parcel = validate_success(api.get_parcel(world["parcel"]["id"], ANALYST))
    assert parcel["version"] == parcel_version, (
        "a refused determination is not a parcel mutation: "
        f"{parcel_version} became {parcel['version']}"
    )

    # The same household cannot be resident on a second parcel at the same time.
    second_parcel = fx.create_parcel(api, f.farm_parcel())
    validate_error(
        api.create_ownership_record(
            f.ownership_record(
                second_parcel["id"],
                taxpayer_id,
                deed_recorded_date="2020-01-01",
                occupancy_start_date="2020-01-01",
            ),
            ANALYST,
        ),
        ERR_DUPLICATE_PRIMARY_RESIDENCE,
        expected_status=409,
    )

    rows, meta = validate_paginated(
        api.list_ownership_records(ANALYST, taxpayer_id=taxpayer_id)
    )
    assert meta["total_count"] == 1, (
        f"the household still holds one residence record, got {meta['total_count']}"
    )
    assert rows[0]["parcel_id"] == world["parcel"]["id"], (
        f"and it is still the original parcel, got {rows[0]['parcel_id']}"
    )
    assert rows[0]["status"] == "VERIFIED", (
        f"untouched by the refusal, got {rows[0]['status']}"
    )


def test_the_annual_roll_stales_the_reviewers_view_and_then_enlarges_the_benefit(api):
    """PRD §2.9: "A determination request — `POST /exemption-applications/{id}/determine`
    — must carry `expected_parcel_version` equal to the current `version` of the parcel
    named by the application's `parcel_id`. If it does not, the request is rejected with
    `ERR_STALE_PARCEL_VERSION` and HTTP 412 ... The check forces the reviewer to
    re-read the parcel before deciding." PRD §3.5 says what moved underneath him:
    "every parcel whose `tax_year` is earlier than the target has its `tax_year` set to
    the target and its value decomposition re-run — which is where the assessment cap
    earns another year of growth — with each rolled parcel's `version` incrementing by
    1."

    Design: Corner/cross_cutting_complexity_layers/stale_parcel_version_from_an_annual_roll_run_blocks_the_determination
    """
    world = fx.approval_world(api, approve=False)
    parcel_id = world["parcel"]["id"]
    application_id = world["application_id"]
    cached_version = world["parcel"]["version"]
    assert cached_version == 1, (
        f"the reviewer read the parcel as created, got version {cached_version}"
    )
    assert_money(world["parcel"], "capped_value_cents", 33600000)

    # A third party rolls the whole county forward while the claim waits.
    fx.set_clock(api, "2027-01-02T00:00:00Z")
    roll = validate_success(
        api.create_assessment_roll_run(f.assessment_roll_run(2027), ANALYST)
    )
    assert roll["target_tax_year"] == 2027, (
        f"the sweep reports the year it advanced to, got {roll['target_tax_year']}"
    )
    assert roll["parcels_rolled_count"] == 1, (
        f"the one parcel on the roll was rolled, got {roll['parcels_rolled_count']}"
    )
    assert roll["certifications_lapsed_count"] == 0, (
        f"no certification exists to lapse, got {roll['certifications_lapsed_count']}"
    )
    assert roll["grants_suspended_count"] == 0, (
        f"no grant exists to suspend, got {roll['grants_suspended_count']}"
    )
    assert roll["grants_lapsed_count"] == 0, (
        f"and none to lapse, got {roll['grants_lapsed_count']}"
    )

    validate_error(
        api.determine_application(
            application_id, f.approve_determination(cached_version), REVIEWER
        ),
        ERR_STALE_PARCEL_VERSION,
        expected_status=412,
    )
    refused = validate_success(api.get_application(application_id, REVIEWER))
    assert refused["status"] == "UNDER_REVIEW", (
        f"the refused determination wrote nothing, got {refused['status']}"
    )
    assert refused["resulting_grant_id"] is None, (
        f"and minted nothing, got {refused['resulting_grant_id']!r}"
    )

    rolled = validate_success(api.get_parcel(parcel_id, ANALYST))
    assert rolled["version"] == 2, (
        f"the roll is the parcel's second mutation, got version {rolled['version']}"
    )
    assert rolled["tax_year"] == 2027, (
        f"the parcel now serves the target year, got {rolled['tax_year']}"
    )
    assert_money(rolled, "capped_value_cents", 34200000)
    assert_parcel_decomposition(
        rolled,
        assessed_value_cents=34200000,
        exempt_value_cents=0,
        taxable_value_cents=34200000,
        exemption_status="UNEXEMPTED",
    )

    # The same approval against the re-read version prices the benefit on the new
    # basis rather than the one the reviewer had cached.
    approved = validate_success(
        api.determine_application(
            application_id, f.approve_determination(rolled["version"]), REVIEWER
        )
    )
    assert approved["status"] == "APPROVED", (
        f"the re-issued determination is honoured, got {approved['status']}"
    )
    assert_grant(
        validate_success(api.get_grant(approved["resulting_grant_id"], REVIEWER)),
        benefit_status="ACTIVE",
        benefit_amount_cents=8550000,
        applied_exempt_value_cents=8550000,
    )

    final_parcel = validate_success(api.get_parcel(parcel_id, ANALYST))
    assert final_parcel["version"] == 3, (
        "creation, the roll and the approval are three mutations, got version "
        f"{final_parcel['version']}"
    )
    assert_parcel_decomposition(
        final_parcel,
        assessed_value_cents=34200000,
        exempt_value_cents=8550000,
        taxable_value_cents=25650000,
        exemption_status="PARTIALLY_EXEMPT",
    )


def test_the_determination_response_already_shows_the_grant_and_the_repriced_parcel(api):
    """PRD §3.4: "The application's `resulting_grant_id` is stamped with the new grant's
    identifier, mirroring the grant's own `application_id`, and `determined_by_user_id`
    records the deciding reviewer." PRD §3.4 continues: "The new grant entering the
    active set re-runs the parcel value decomposition, rewriting `capped_value_cents`,
    `assessed_value_cents`, `exempt_value_cents`, `taxable_value_cents` and the
    `applied_exempt_value_cents` of every `ACTIVE` grant on that parcel. The rewritten
    exempt total re-derives the parcel's `exemption_status` and increments the parcel's
    `version` by 1." PRD §2.11: "`net_relief_cents` is `lifetime_refund_cents` minus
    `lifetime_recovery_collected_cents`, and it is re-derived every single time either
    component changes — never stored independently, never patched by hand."

    Design: Corner/consistency_model/determination_response_already_carries_the_grant_and_the_repriced_parcel
    """
    world = fx.approval_world(api, approve=False)
    parcel_id = world["parcel"]["id"]
    application_id = world["application_id"]
    _empty, empty_meta = validate_paginated(
        api.list_grants(REVIEWER, parcel_id=parcel_id)
    )
    assert empty_meta["total_count"] == 0, (
        f"the parcel carries no grant yet, got {empty_meta['total_count']}"
    )

    determined = validate_success(
        api.determine_application(
            application_id,
            f.approve_determination(world["parcel"]["version"]),
            REVIEWER_2,
        )
    )
    assert determined["status"] == "APPROVED", (
        f"the approval is applied in the same request, got {determined['status']}"
    )
    grant_id = determined["resulting_grant_id"]
    assert isinstance(grant_id, str) and grant_id, (
        f"the response body itself names the minted grant, got {grant_id!r}"
    )
    assert determined["determined_by_user_id"] == REVIEWER_2_USER_ID, (
        f"and the deciding reviewer, got {determined['determined_by_user_id']!r}"
    )

    # The very next request already sees it; no re-read and no retry intervened.
    rows, meta = validate_paginated(api.list_grants(REVIEWER, parcel_id=parcel_id))
    assert meta["total_count"] == 1, (
        f"the minted grant is listed immediately, got {meta['total_count']}"
    )
    assert rows[0]["id"] == grant_id, (
        f"and it is the grant the determination named, got {rows[0]['id']}"
    )
    assert rows[0]["application_id"] == application_id, (
        f"the grant mirrors its application, got {rows[0]['application_id']}"
    )
    assert_grant(
        rows[0],
        benefit_status="ACTIVE",
        benefit_amount_cents=8400000,
        applied_exempt_value_cents=8400000,
    )

    parcel = validate_success(api.get_parcel(parcel_id, ANALYST))
    assert parcel["version"] == 2, (
        f"the approval is the parcel's second mutation, got {parcel['version']}"
    )
    assert_parcel_decomposition(
        parcel,
        assessed_value_cents=33600000,
        exempt_value_cents=8400000,
        taxable_value_cents=25200000,
        exemption_status="PARTIALLY_EXEMPT",
    )
    assert (
        parcel["exempt_value_cents"] + parcel["taxable_value_cents"]
        == parcel["assessed_value_cents"]
    ), (
        "the decomposition identity must already hold in this read: "
        f"{parcel['exempt_value_cents']} + {parcel['taxable_value_cents']} != "
        f"{parcel['assessed_value_cents']}"
    )

    account = validate_success(api.get_taxpayer_account(world["taxpayer"]["id"], CLERK))
    assert_taxpayer_ledger(
        account,
        lifetime_refund_cents=0,
        lifetime_recovery_collected_cents=0,
        net_relief_cents=0,
    )
