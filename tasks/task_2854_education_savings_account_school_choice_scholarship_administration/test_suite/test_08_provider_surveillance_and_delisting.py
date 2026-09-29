"""The live risk score, its automatic sanctions, and the scoped delisting cascade."""

from test_helpers import (
    AUTO_PROBATION_AT,
    PA,
    Q1_NET_CENTS,
    SURVEILLANCE_POINTS_PER_CASE,
    accept_award,
    adjudicate_misuse_case,
    create_application,
    create_curriculum_provider_payload,
    create_student,
    decide_purchase_request,
    file_purchase_request,
    open_misuse_case,
    read_account,
    read_misuse_case,
    read_provider,
    read_purchase_request,
    record_determination,
    review_misuse_case,
    run_awarding,
    run_disbursement,
    sanction_provider,
    set_clock,
    setup_approved_provider,
    setup_approved_purchase_request,
    setup_catalog,
    setup_misuse_case_under_review,
    setup_open_year_and_student,
    setup_pending_purchase_request,
    setup_purchase_environment,
    submit_application,
    validate_paginated,
)

SCREENING_CLOCK = "2026-09-01T00:00:00Z"
FOUR_MONTHS_LATER = "2027-01-01T00:00:00Z"
ONE_MONTH_LATER = "2026-10-01T00:00:00Z"
TWELVE_MONTHS_LATER = "2027-09-01T00:00:00Z"

SECOND_STUDENT = {
    "household_id": "HH-7",
    "first_name": "Rosa",
    "last_name": "Lujan",
    "date_of_birth": "2013-03-11",
    "category_flags": ["DISABILITY_IEP"],
}


def _case_under_review_at(clock_iso, *, flags=("NO_STATE_REGISTRATION",)):
    """A screened, admitted provider with one implicated case, judged at ``clock_iso``.

    The provider is screened while the logical clock reads 2026-09-01, so moving the
    clock before the adjudication is what sets the elapsed-months term.
    """
    env = setup_purchase_environment(
        quarters=1, provider_flags=list(flags), provider_codes=("TUTORING",)
    )
    env = setup_pending_purchase_request(env, category_key="tutoring", amount_cents=150000)
    assert env.provider["screened_at"].startswith("2026-09-01"), (
        f"the screening was recorded at the canonical clock, got "
        f"{env.provider['screened_at']!r}"
    )
    set_clock(clock_iso)
    return setup_misuse_case_under_review(
        env, case_overrides={"purchase_request_id": env.purchase_request_id}
    )


def _two_household_environment():
    """Two funded households, one vendor, and one case under review against each."""
    env = setup_open_year_and_student()
    second_student = create_student(**SECOND_STUDENT)

    first_application = create_application(env.program_year_id, env.student_id)
    submit_application(first_application["id"], env.student_id)
    record_determination(first_application["id"])

    second_application = create_application(env.program_year_id, second_student["id"])
    submit_application(second_application["id"], second_student["id"])
    record_determination(second_application["id"])

    run_awarding(env.program_year_id)
    first_accept = accept_award(first_application["id"], env.student_id)
    second_accept = accept_award(second_application["id"], second_student["id"])
    run_disbursement(env.program_year_id, 1)

    env.update(setup_catalog())
    env.update(
        setup_approved_provider(flags=["NO_STATE_REGISTRATION"], codes=["TUTORING"])
    )

    env["application_id"] = first_application["id"]
    env["account_id"] = first_accept["account_id"]
    env["second_student_id"] = second_student["id"]
    env["second_account_id"] = second_accept["account_id"]

    first_request = file_purchase_request(
        env.account_id,
        env.student_id,
        env.provider_id,
        env.tutoring["id"],
        amount_cents=150000,
    )
    second_request = file_purchase_request(
        env.second_account_id,
        env.second_student_id,
        env.provider_id,
        env.tutoring["id"],
        amount_cents=120000,
    )
    env["first_request_id"] = first_request["id"]
    env["second_request_id"] = second_request["id"]

    first_case = open_misuse_case(
        env.account_id,
        purchase_request_id=first_request["id"],
        disallowed_principal_cents=150000,
        narrative="Attendance log does not support the billed sessions.",
    )
    review_misuse_case(first_case["id"])
    second_case = open_misuse_case(
        env.second_account_id,
        purchase_request_id=second_request["id"],
        disallowed_principal_cents=120000,
        narrative="Same tutor, same fabricated session pattern on a second household.",
    )
    review_misuse_case(second_case["id"])
    env["first_case_id"] = first_case["id"]
    env["second_case_id"] = second_case["id"]
    return env


class TestScreeningStaticVersusSurveillanceDecayed:
    """One provider, two risk figures, and they are meant to disagree."""

    def test_four_elapsed_months_and_one_case_land_on_forty_six(self, api):
        """PRD §3.6: "The elapsed time is the number of whole months from `screened_at` to
        the current logical instant, taking the floor. The decay factor is 1 less 0.1 for
        each of those whole months, floored at 0.5 — so a provider twelve months past its
        screening still retains a factor of 0.5, half of its screening term, not none of
        it. The decayed screening term is `screening_score` multiplied by that decay
        factor, rounded half up to a whole number, and it is rounded **before** anything
        else is added. To that term is added 25 points for each substantiated case, and the
        total is capped at 100."

        PRD §3.6: "The screening row's `screening_score` is the sum of the weights of the
        distinct flags submitted, capped at 100."

        Design: Difficulty/dual_variant_calc/provider_score_screening_static_vs_surveillance_decayed
        """
        env = _case_under_review_at(FOUR_MONTHS_LATER)
        assert env.screening["screening_score"] == 35, (
            f"NO_STATE_REGISTRATION alone weighs 35, got {env.screening['screening_score']}"
        )
        assert env.screening["recommended_status"] == "APPROVE", (
            f"35 is below 40, so the row recommends APPROVE, got "
            f"{env.screening['recommended_status']!r}"
        )
        assert env.provider["surveillance_score"] == 35, (
            "before any case the two figures agree at the screening instant, got "
            f"{env.provider['surveillance_score']}"
        )

        case = adjudicate_misuse_case(
            env.misuse_case_id,
            "SUBSTANTIATED",
            "Attendance records contradict the invoiced sessions.",
        )
        assert case["status"] == "SUBSTANTIATED", (
            f"the case is substantiated, got {case['status']!r}"
        )

        provider = read_provider(env.provider_id)
        assert provider["screening_score"] == 35, (
            "the static flag sum is frozen and the substantiation does not touch it, got "
            f"{provider['screening_score']}"
        )
        assert provider["substantiated_case_count"] == 1, (
            f"one case now counts against the vendor, got "
            f"{provider['substantiated_case_count']}"
        )
        assert provider["surveillance_score"] == 46, (
            "four whole months decay 35 by a factor of 0.6 to 21, and 25 case points make "
            f"46, got {provider['surveillance_score']}"
        )
        assert provider["surveillance_score"] != provider["screening_score"], (
            "the decayed figure is deliberately not the static one, got "
            f"{provider['surveillance_score']}"
        )
        assert provider["surveillance_score"] != SURVEILLANCE_POINTS_PER_CASE, (
            "nor is it the case points alone, got "
            f"{provider['surveillance_score']}"
        )
        assert provider["status"] == "APPROVED", (
            f"46 is below the 75 escalation band, so the vendor stays APPROVED, got "
            f"{provider['status']!r}"
        )

        screenings, meta = validate_paginated(
            api.list_fraud_screenings(env.provider_id, PA)
        )
        assert meta["total_count"] == 1, (
            f"the screening history is a single row, got {meta['total_count']}"
        )
        assert screenings[0]["screening_score"] == 35, (
            f"and that row still reads 35, got {screenings[0]['screening_score']}"
        )

        account = read_account(env.account_id)
        assert account["status"] == "SUSPENDED", (
            f"the substantiation suspended the account, got {account['status']!r}"
        )
        request = read_purchase_request(env.purchase_request_id)
        assert request["approval_status"] == "VOID", (
            f"and voided the implicated request, got {request['approval_status']!r}"
        )
        assert request["settlement_status"] == "CANCELLED", (
            f"cancelling its money track, got {request['settlement_status']!r}"
        )

    def test_one_elapsed_month_rounds_the_decayed_term_half_up_to_fifty_seven(self, api):
        """PRD §3.6: "The decayed screening term is `screening_score` multiplied by that
        decay factor, rounded half up to a whole number, and it is rounded **before**
        anything else is added."

        PRD §3.6: "Recording a screening advances the provider `DRAFT → SCREENED` and
        copies `screening_score`, `screening_flags`, and `screened_at` onto the provider."

        Design: Difficulty/dual_variant_calc/provider_score_screening_static_vs_surveillance_decayed
        """
        env = _case_under_review_at(ONE_MONTH_LATER)

        adjudicate_misuse_case(
            env.misuse_case_id,
            "SUBSTANTIATED",
            "The billed hours were never delivered.",
        )

        provider = read_provider(env.provider_id)
        assert provider["screening_score"] == 35, (
            f"the static variant is unchanged by elapsed time, got "
            f"{provider['screening_score']}"
        )
        assert provider["surveillance_score"] == 57, (
            "one whole month decays 35 by 0.9 to 31.5, which rounds half up to 32 before "
            f"the 25 case points are added, giving 57, got {provider['surveillance_score']}"
        )
        assert provider["surveillance_score"] != 56, (
            "rounding the decayed term down would have given 56, got "
            f"{provider['surveillance_score']}"
        )
        assert provider["substantiated_case_count"] == 1, (
            f"one substantiated case, got {provider['substantiated_case_count']}"
        )
        assert provider["status"] == "APPROVED", (
            f"57 is still below the escalation band, got {provider['status']!r}"
        )
        assert provider["screened_at"].startswith("2026-09-01"), (
            "the screening instant the decay measures from is unchanged, got "
            f"{provider['screened_at']!r}"
        )


class TestSurveillanceDecayFloor:
    """The decay factor stops at one half and the term rounds half up."""

    def test_twelve_months_out_the_factor_floors_and_the_term_rounds_up(self, api):
        """PRD §3.6: "The decay factor is 1 less 0.1 for each of those whole months,
        floored at 0.5 — so a provider twelve months past its screening still retains a
        factor of 0.5, half of its screening term, not none of it. The decayed screening
        term is `screening_score` multiplied by that decay factor, rounded half up to a
        whole number, and it is rounded **before** anything else is added."

        PRD §2.6: "The default reduction is **round half up**: a fractional cent of exactly
        one half is rounded away from zero to the next whole cent."

        Design: Corner/calculations/surveillance_decay_stops_at_the_floor_and_rounds_half_up
        """
        env = _case_under_review_at(TWELVE_MONTHS_LATER)
        assert env.screening["screening_score"] == 35, (
            f"the screening scored 35, got {env.screening['screening_score']}"
        )

        adjudicate_misuse_case(
            env.misuse_case_id,
            "SUBSTANTIATED",
            "Attendance logs contradict the billed hours.",
        )

        provider = read_provider(env.provider_id)
        assert provider["screening_score"] == 35, (
            f"the static variant never decays, got {provider['screening_score']}"
        )
        assert provider["surveillance_score"] == 43, (
            "the factor floors at 0.5, so 35 becomes 17.5, which rounds half up to 18 "
            f"before the 25 case points are added, got {provider['surveillance_score']}"
        )
        assert provider["surveillance_score"] != 42, (
            "rounding 17.5 half down would have given 42, got "
            f"{provider['surveillance_score']}"
        )
        assert provider["surveillance_score"] != SURVEILLANCE_POINTS_PER_CASE, (
            "a factor of zero at twelve months would have left only the case points, got "
            f"{provider['surveillance_score']}"
        )
        assert provider["substantiated_case_count"] == 1, (
            f"one substantiated case, got {provider['substantiated_case_count']}"
        )
        assert provider["status"] == "APPROVED", (
            f"43 is below the 75 auto-probation threshold, got {provider['status']!r}"
        )

        assert read_misuse_case(env.misuse_case_id)["status"] == "SUBSTANTIATED", (
            "the case itself is substantiated"
        )
        assert read_account(env.account_id)["status"] == "SUSPENDED", (
            "and the account it names is suspended"
        )


class TestSurveillanceProbationThreshold:
    """The cumulative band is crossed by the second case, with no operator involved."""

    def test_second_case_moves_the_provider_to_probation_automatically(self, api):
        """PRD §3.6: "The recomputed `surveillance_score` then drives an automatic sanction
        with no operator involved. A score of 90 or more cascades the provider to
        `DELISTED`, with the full void-and-release cascade described above. A score of at
        least 75 but below 90 cascades an `APPROVED` provider to `PROBATION`. A score of 74
        leaves the provider `APPROVED` untouched. The boundaries are inclusive on the lower
        side in both bands."

        PRD §3.8: "Fourth, when the case names a `purchase_request_id`, the provider behind
        that request has its `substantiated_case_count` raised by 1 and its
        `surveillance_score` recomputed by the decay-plus-case-points rule of §3.6"

        Design: Corner/cross_cutting_complexity_layers/second_substantiated_case_crosses_the_surveillance_probation_threshold
        """
        env = _two_household_environment()
        assert env.provider["screening_score"] == 35, (
            f"the vendor screened at 35, got {env.provider['screening_score']}"
        )
        assert env.provider["surveillance_score"] == 35, (
            f"with no case history the live score matches it, got "
            f"{env.provider['surveillance_score']}"
        )

        adjudicate_misuse_case(
            env.first_case_id, "SUBSTANTIATED", "Sessions were never delivered."
        )
        after_first = read_provider(env.provider_id)
        assert after_first["substantiated_case_count"] == 1, (
            f"one case counts, got {after_first['substantiated_case_count']}"
        )
        assert after_first["surveillance_score"] == 60, (
            "no month has elapsed, so the score is 35 plus 25 case points, got "
            f"{after_first['surveillance_score']}"
        )
        assert after_first["status"] == "APPROVED", (
            f"60 is below 75, so the threshold is not yet crossed, got "
            f"{after_first['status']!r}"
        )

        adjudicate_misuse_case(
            env.second_case_id,
            "SUBSTANTIATED",
            "Identical fabricated session pattern confirmed.",
        )
        after_second = read_provider(env.provider_id)
        assert after_second["substantiated_case_count"] == 2, (
            f"two cases now count, got {after_second['substantiated_case_count']}"
        )
        assert after_second["surveillance_score"] == 85, (
            "35 plus 50 case points is 85, got "
            f"{after_second['surveillance_score']}"
        )
        assert after_second["surveillance_score"] >= AUTO_PROBATION_AT, (
            f"which lands in the escalation band, got "
            f"{after_second['surveillance_score']}"
        )
        assert after_second["status"] == "PROBATION", (
            "so the vendor is moved to PROBATION with no compliance officer sanctioning "
            f"it, got {after_second['status']!r}"
        )
        assert after_second["screening_score"] == 35, (
            f"the static screening figure is untouched throughout, got "
            f"{after_second['screening_score']}"
        )

        assert read_account(env.account_id)["status"] == "SUSPENDED", (
            "the first household's account is suspended"
        )
        assert read_account(env.second_account_id)["status"] == "SUSPENDED", (
            "and so is the second household's"
        )
        assert read_purchase_request(env.first_request_id)["approval_status"] == "VOID", (
            "each substantiation voided its own account's open request"
        )
        assert read_purchase_request(env.second_request_id)["approval_status"] == "VOID", (
            "including the second household's"
        )


class TestDelistingCascadeScope:
    """A delisting reaches exactly one vendor's requests and no further."""

    def test_delisting_voids_and_releases_only_that_providers_requests(self, api):
        """PRD §3.6: "The delisting records `sanction_reason` and then voids every purchase
        request naming this provider whose `approval_status` is `PENDING_REVIEW` or
        `APPROVED`, setting `approval_status` to `VOID` and `settlement_status` to
        `CANCELLED`. Each voided request that had actually reached `APPROVED` releases its
        hold on its own account: that account's `encumbered_cents` falls by the request's
        `amount_cents` and its `balance_cents` rises by the same amount."

        PRD §3.7: "On success the reviewer's `X-User-ID` is stored as
        `approved_by_user_id`, and the hold is placed: `balance_cents` falls by
        `amount_cents` and `encumbered_cents` rises by the same `amount_cents`."

        Design: Difficulty/transitive_cascade/provider_delisting_voids_that_providers_requests_only
        """
        env = setup_purchase_environment(
            quarters=1, provider_flags=[], provider_codes=("TUTORING",)
        )
        second_vendor = setup_approved_provider(
            payload_builder=create_curriculum_provider_payload,
            flags=[],
            codes=["MATERIALS"],
        )
        env = setup_approved_purchase_request(
            env, category_key="tutoring", amount_cents=150000
        )
        other_request = file_purchase_request(
            env.account_id,
            env.student_id,
            second_vendor.provider_id,
            env.materials["id"],
            amount_cents=50000,
        )
        decide_purchase_request(other_request["id"], "APPROVED")

        before = read_account(env.account_id)
        assert before["balance_cents"] == Q1_NET_CENTS - 150000 - 50000, (
            f"both holds have been placed, leaving 29088, got {before['balance_cents']}"
        )
        assert before["encumbered_cents"] == 200000, (
            f"and 200000 is held, got {before['encumbered_cents']}"
        )

        delisted = sanction_provider(
            env.provider_id,
            "DELIST",
            "Repeated billing irregularities across multiple accounts.",
        )
        assert delisted["status"] == "DELISTED", (
            f"hop one moves the vendor to DELISTED, got {delisted['status']!r}"
        )
        assert delisted["sanction_reason"] == (
            "Repeated billing irregularities across multiple accounts."
        ), f"recording the reason, got {delisted['sanction_reason']!r}"

        voided = read_purchase_request(env.purchase_request_id)
        assert voided["approval_status"] == "VOID", (
            f"hop two voids that vendor's approved request, got "
            f"{voided['approval_status']!r}"
        )
        assert voided["settlement_status"] == "CANCELLED", (
            f"cancelling its money track, got {voided['settlement_status']!r}"
        )

        after = read_account(env.account_id)
        assert after["encumbered_cents"] == 50000, (
            "hop three releases only that request's hold, leaving the other 50000 held, "
            f"got {after['encumbered_cents']}"
        )
        assert after["balance_cents"] == Q1_NET_CENTS - 50000, (
            f"and returns 150000 to the balance, giving 179088, got "
            f"{after['balance_cents']}"
        )

        survivor = read_purchase_request(other_request["id"])
        assert survivor["approval_status"] == "APPROVED", (
            "the other vendor's request is untouched by the cascade, got "
            f"{survivor['approval_status']!r}"
        )
        assert survivor["settlement_status"] == "UNSETTLED", (
            f"on both dimensions, got {survivor['settlement_status']!r}"
        )
        assert read_provider(second_vendor.provider_id)["status"] == "APPROVED", (
            "and the other vendor keeps its admission"
        )
        assert after["status"] == "ACTIVE", (
            "a provider sanction is not an account suspension, got "
            f"{after['status']!r}"
        )

    def test_a_pending_only_request_is_voided_without_moving_money(self, api):
        """PRD §3.6: "A request that was still only `PENDING_REVIEW` moves no money,
        because no hold had been placed. The provider's `version` rises by 1 and so does the
        `version` of every account the hold releases touched."

        Design: Difficulty/transitive_cascade/provider_delisting_voids_that_providers_requests_only
        """
        env = setup_purchase_environment(
            quarters=1, provider_flags=[], provider_codes=("TUTORING",)
        )
        second_vendor = setup_approved_provider(
            payload_builder=create_curriculum_provider_payload,
            flags=[],
            codes=["MATERIALS"],
        )
        env = setup_pending_purchase_request(
            env, category_key="tutoring", amount_cents=150000
        )
        other_request = file_purchase_request(
            env.account_id,
            env.student_id,
            second_vendor.provider_id,
            env.materials["id"],
            amount_cents=50000,
        )

        before = read_account(env.account_id)
        assert before["balance_cents"] == Q1_NET_CENTS, (
            f"no hold has been placed by either filing, got {before['balance_cents']}"
        )
        assert before["encumbered_cents"] == 0, (
            f"so nothing is encumbered, got {before['encumbered_cents']}"
        )

        sanction_provider(env.provider_id, "DELIST", "Falsified attendance logs.")

        voided = read_purchase_request(env.purchase_request_id)
        assert voided["approval_status"] == "VOID", (
            f"the pending request is still voided, got {voided['approval_status']!r}"
        )
        assert voided["settlement_status"] == "CANCELLED", (
            f"with its money track cancelled, got {voided['settlement_status']!r}"
        )

        after = read_account(env.account_id)
        assert after["balance_cents"] == Q1_NET_CENTS, (
            f"but no money moved, got {after['balance_cents']}"
        )
        assert after["encumbered_cents"] == 0, (
            f"and nothing was released, got {after['encumbered_cents']}"
        )
        assert after["version"] == before["version"], (
            "the account's version rises only where a hold release touched it, got "
            f"{after['version']} against {before['version']}"
        )

        survivor = read_purchase_request(other_request["id"])
        assert survivor["approval_status"] == "PENDING_REVIEW", (
            "the other vendor's pending request survives the cascade, got "
            f"{survivor['approval_status']!r}"
        )
        assert read_provider(second_vendor.provider_id)["status"] == "APPROVED", (
            "and that vendor keeps its admission"
        )
