"""
The error catalogue, triggered one code at a time: three header defects that all
answer the same way before any lookup happens, seven unknown ids that answer
seven different ways, a classification failure that outranks an undeclared name,
an unexplained skip past rank one, an empty pool refused on both the read and the
write, an hours report one hour past its elapsed cap, a claim whose evidence has
been purged, two remedies that do not fit their decisions, a second live
registration refused hall-wide, and a cancelled call that accepts nothing more.
"""

from test_helpers import (
    BACK_PAY_NOT_APPLICABLE,
    BUSINESS_MANAGER,
    BUSINESS_MANAGER_USER_ID,
    CLAIM_IMPROPER_NAMED_CALL,
    CLAIM_OUT_OF_ORDER_DISPATCH,
    DECISION_DENIED,
    DECISION_SUSTAINED,
    DISPATCH_LAID_OFF,
    DISPATCH_WORKING,
    DISPATCHER,
    ERR_CLASSIFICATION_MISMATCH,
    ERR_CONTRACTOR_NOT_FOUND,
    ERR_DISPATCH_NOT_FOUND,
    ERR_DISPATCH_RECORD_PURGED,
    ERR_GRIEVANCE_NOT_FOUND,
    ERR_HOURS_EXCEED_ELAPSED,
    ERR_JOB_REQUEST_NOT_FOUND,
    ERR_JOB_REQUEST_NOT_OPEN,
    ERR_LEDGER_ENTRY_NOT_FOUND,
    ERR_LIST_NOT_FOUND,
    ERR_LOCAL_NOT_FOUND,
    ERR_MEMBER_ALREADY_REGISTERED,
    ERR_NAMED_CALL_NOT_DECLARED,
    ERR_NO_ELIGIBLE_REGISTRANT,
    ERR_OUT_OF_ORDER_DISPATCH,
    ERR_REMEDY_NOT_APPLICABLE,
    ERR_UNAUTHENTICATED,
    EVENT_REFERRAL_ISSUED,
    GOOD_CAUSE_MEDICAL,
    GRIEVANCE_DENIED,
    GRIEVANCE_UNDER_REVIEW,
    GROUP_1,
    GROUP_4,
    HALL_ADMIN,
    JOB_REQUEST_CANCELLED,
    JOB_REQUEST_OPEN,
    NON_EXISTENT_UUID,
    PURGE_PURGED,
    PURGE_RETAINED,
    REFERRAL_KIND_NAMED_CALL,
    REFERRAL_REFUSED,
    REGISTRATION_REGISTERED,
    REGISTRATION_REMOVED,
    REMEDY_MAKE_WHOLE_HOURS,
    REMEDY_NEXT_AVAILABLE_PRIORITY,
    REMEDY_NONE,
    REMOVAL_VOLUNTARY,
    RETENTION_DAYS,
    SLOT_JOURNEYWORKER,
    VARIANT_NOT_APPLICABLE,
    VARIANT_STRICT_GROUP_ORDER,
    assert_instant_equals,
    expect_created,
    expect_error,
    expect_ok,
    factories as f,
    fixtures as fx,
    headers_blank_role,
    headers_blank_user_id,
    headers_unknown_role,
    make_contractor_rep_headers,
    plus_days,
    validate_list,
)

CLOCK = "2026-09-01T00:00:00.000Z"

# ─── Header defects (§2.1, §2.7 position 1) ───────────────────────────────────

UNRECOGNIZED_ROLE = "Steward"
MALFORMED_LOCAL_NUMBER = "not-an-integer"

# ─── The named call that is declared but misclassified ────────────────────────

APPRENTICE_NAME = "Ada Reyes"
APPRENTICE_PERIOD = 2
APPRENTICE_HOURS = 600
DECLARED_JOURNEYWORKER = "Ben Oyelaran"
DECLARED_HOURS = 9000
UNDECLARED_JOURNEYWORKER = "Cleo Vance"
UNDECLARED_HOURS = 8000
RETUBE_JOB_SITE = "Boiler Retube"
RETUBE_JOURNEYWORKERS = 19
RETUBE_APPRENTICES = 1
RETUBE_DURATION_DAYS = 30
RETUBE_RATE_CENTS = 5000
RETUBE_NAMED_CALL_ALLOWANCE = 4

# ─── The skip past rank one ───────────────────────────────────────────────────

RANK_ONE_NAME = "Dara Ellis"
RANK_ONE_HOURS = 9000
RANK_TWO_NAME = "Emil Ortiz"
RANK_TWO_HOURS = 8000
SKIP_JOB_SITE = "Condenser Retube"
SKIP_JOURNEYWORKERS = 2
SKIP_DURATION_DAYS = 20
SKIP_RATE_CENTS = 5000
OVERRIDE_REASON = "Dara is on a short-call elsewhere; hall agent authorised the skip."

# ─── The empty candidate pool ─────────────────────────────────────────────────

LONE_SIGNER_NAME = "Fern Adeyemi"
LONE_SIGNER_HOURS = 9000
EMPTY_JOB_SITE = "Ash Handling"
EMPTY_DURATION_DAYS = 20
EMPTY_RATE_CENTS = 5000

# ─── The elapsed-hours cap ────────────────────────────────────────────────────

CAPPED_MEMBER = "Gil Ferreira"
CAPPED_HOURS = 9000
CAP_JOB_SITE = "Precipitator Rebuild"
CAP_REPORT_AT = "2026-09-10T14:00:00.000Z"
CAP_DURATION_DAYS = 20
CAP_RATE_CENTS = 5000
LAYOFF_CLOCK = "2026-09-12T14:00:00.000Z"
ELAPSED_CAP_HOURS = 24
ONE_HOUR_TOO_MANY = 25

# ─── The purged dispatch record ───────────────────────────────────────────────

REFERRED_NAME = "Hana Brue"
REFERRED_HOURS = 9000
PASSED_OVER_NAME = "Ivo Salcedo"
PASSED_OVER_HOURS = 8000
PURGE_JOB_SITE = "Stack Liner"
PURGE_DURATION_DAYS = 20
PURGE_RATE_CENTS = 5000
PURGE_NARRATIVE = "I was ahead of Hana on Group 1."
RETENTION_HORIZON = "2031-08-31T00:00:00.000Z"
SWEEP_CLOCK = "2031-09-01T00:00:00.000Z"
SUSTAIN_NOTE = "Out of order on its face."

# ─── The two inapplicable remedies ────────────────────────────────────────────

REFUSING_NAME = "Jae Mburu"
REFUSING_HOURS = 9000
GRIEVING_NAME = "Kaya Lindqvist"
GRIEVING_HOURS = 8000
REMEDY_JOB_SITE = "Air Heater Baskets"
REMEDY_JOURNEYWORKERS = 2
REMEDY_DURATION_DAYS = 20
REMEDY_RATE_CENTS = 5000
REMEDY_NARRATIVE = "This call should have come to me."
DENIAL_NOTE = "The call was properly ordered."

# ─── The hall-wide single-registration rule ───────────────────────────────────

TWICE_SIGNING_NAME = "Lena Marchetti"
TWICE_SIGNING_HOURS = 9000

# ─── The cancelled call ───────────────────────────────────────────────────────

CANCELLED_MEMBER = "Milo Zanetti"
CANCELLED_MEMBER_HOURS = 9000
CANCELLED_JOB_SITE = "Scrubber Outage"
CANCELLED_DURATION_DAYS = 20
CANCELLED_RATE_CENTS = 5000
FIRST_CANCEL_REASON = "Owner deferred the outage."
SECOND_CANCEL_REASON = "Cancelling again."


def _one_real_local(api):
    """A single HOME local, so the target of every defective read below exists."""
    fx.set_clock(api, CLOCK)
    return fx.add_home_local(api)


class TestHeaderAuthenticationOutranksEveryOtherCheck:
    """
    Three different header defects, one code — and an unrecognized role beats a
    malformed body to the answer.
    """

    def test_an_empty_role_header_is_not_an_anonymous_read(self, api):
        """
        PRD §2.1: "If either header is absent, or present but empty, or if `X-User-Role`
        does not spell one of the five recognized roles exactly, the request is rejected
        with `ERR_UNAUTHENTICATED` and HTTP 401."

        Design: Corner/errors/missing_blank_and_unknown_role_headers_are_unauthenticated
        """
        local = _one_real_local(api)

        refused = api.get_local(local["id"], headers_blank_role())

        expect_error(refused, ERR_UNAUTHENTICATED, status=401)

    def test_a_role_outside_the_five_names_is_not_authenticated(self, api):
        """
        PRD §2.1: "The five roles are `HallAdmin`, `Dispatcher`, `BusinessManager`,
        `ContractorRep`, and `Member`."

        PRD §2.7: "Header authentication — both headers present, non-empty, and
        `X-User-Role` one of the five declared roles — on every endpoint, failing with
        `ERR_UNAUTHENTICATED`."

        Design: Corner/errors/missing_blank_and_unknown_role_headers_are_unauthenticated
        """
        local = _one_real_local(api)

        refused = api.get_local(
            local["id"], headers_unknown_role(role=UNRECOGNIZED_ROLE)
        )

        expect_error(refused, ERR_UNAUTHENTICATED, status=401)

    def test_an_empty_user_id_never_reaches_the_entity_lookup(self, api):
        """
        An entity-backed role with an empty `X-User-ID` is refused at position 1, so the
        answer is not the not-found code the id would otherwise earn.

        PRD §2.1: "This check runs before anything else — before body parsing, before
        resource lookup, before any business rule."

        Design: Corner/errors/missing_blank_and_unknown_role_headers_are_unauthenticated
        """
        local = _one_real_local(api)

        refused = api.get_member(local["id"], headers_blank_user_id())

        body = expect_error(refused, ERR_UNAUTHENTICATED, status=401)
        assert body["error_id"] == ERR_UNAUTHENTICATED

    def test_the_bad_role_is_reported_ahead_of_the_bad_body(self, api):
        """
        The body carries a string where an integer belongs, which position 3 would call
        `ERR_INVALID_REQUEST`; position 1 answers first.

        PRD §2.7: "This ordering is contractual: a request that trips both a late check
        and an early one is reported under the early one."

        Design: Corner/errors/missing_blank_and_unknown_role_headers_are_unauthenticated
        """
        _one_real_local(api)

        refused = api.create_local(
            {
                "local_number": MALFORMED_LOCAL_NUMBER,
                "name": "Local 999",
                "kind": "SISTER",
            },
            headers_unknown_role(role=UNRECOGNIZED_ROLE),
        )

        expect_error(refused, ERR_UNAUTHENTICATED, status=401)


class TestEveryEntityOwnsItsOwnNotFoundCode:
    """
    One well-formed but unknown id, seven path-parameter reads, seven distinct
    codes — a single shared not-found code would fail six of these legs.
    """

    def test_the_list_and_local_reads_answer_with_their_own_codes(self, api):
        """
        PRD §2.6: "All existence failures carry HTTP 404, and the family of codes is one
        per resource type: `ERR_LOCAL_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`,
        `ERR_LIST_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, `ERR_CONTRACTOR_NOT_FOUND`,
        `ERR_JOB_REQUEST_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_DISPATCH_NOT_FOUND`,
        `ERR_GRIEVANCE_NOT_FOUND`, and `ERR_LEDGER_ENTRY_NOT_FOUND`."

        Design: Corner/errors/unknown_path_ids_return_each_entitys_own_not_found_code
        """
        fx.set_clock(api, CLOCK)

        expect_error(
            api.get_local(NON_EXISTENT_UUID, HALL_ADMIN),
            ERR_LOCAL_NOT_FOUND,
            status=404,
        )
        expect_error(
            api.get_out_of_work_list(NON_EXISTENT_UUID, DISPATCHER),
            ERR_LIST_NOT_FOUND,
            status=404,
        )

    def test_the_contractor_and_job_request_reads_answer_with_their_own_codes(self, api):
        """
        PRD §2.6: "A member id that matches no `Member` yields `ERR_MEMBER_NOT_FOUND`; a
        job request id that matches no `JobRequest` yields `ERR_JOB_REQUEST_NOT_FOUND`."

        Design: Corner/errors/unknown_path_ids_return_each_entitys_own_not_found_code
        """
        fx.set_clock(api, CLOCK)

        expect_error(
            api.get_contractor(NON_EXISTENT_UUID, DISPATCHER),
            ERR_CONTRACTOR_NOT_FOUND,
            status=404,
        )
        expect_error(
            api.get_job_request(NON_EXISTENT_UUID, DISPATCHER),
            ERR_JOB_REQUEST_NOT_FOUND,
            status=404,
        )

    def test_the_dispatch_grievance_and_ledger_reads_answer_with_their_own_codes(
        self, api
    ):
        """
        PRD §2.7: "Existence of path-templated resources, resolved left to right, on every
        endpoint that has a path parameter, failing with the matching not-found code."

        Design: Corner/errors/unknown_path_ids_return_each_entitys_own_not_found_code
        """
        fx.set_clock(api, CLOCK)

        expect_error(
            api.get_dispatch(NON_EXISTENT_UUID, DISPATCHER),
            ERR_DISPATCH_NOT_FOUND,
            status=404,
        )
        expect_error(
            api.get_grievance(NON_EXISTENT_UUID, BUSINESS_MANAGER),
            ERR_GRIEVANCE_NOT_FOUND,
            status=404,
        )
        expect_error(
            api.get_ledger_entry(NON_EXISTENT_UUID, HALL_ADMIN),
            ERR_LEDGER_ENTRY_NOT_FOUND,
            status=404,
        )


def _retube_call_with_two_declared_names(api):
    """
    A twenty-worker long call that names one apprentice and one journeyworker,
    with a third journeyworker on the list whom nobody named.
    """
    hall = fx.standard_hall(api, clock=CLOCK, groups=(GROUP_1, GROUP_4))
    apprentice = fx.add_apprentice(
        api,
        hall["home_local_id"],
        APPRENTICE_NAME,
        period=APPRENTICE_PERIOD,
        hours=APPRENTICE_HOURS,
    )
    fx.sign_book(api, apprentice["id"], hall["group_4_id"])
    declared = fx.add_journeyworker(
        api, hall["home_local_id"], DECLARED_JOURNEYWORKER, DECLARED_HOURS
    )
    fx.sign_book(api, declared["id"], hall["group_1_id"])
    undeclared = fx.add_journeyworker(
        api, hall["home_local_id"], UNDECLARED_JOURNEYWORKER, UNDECLARED_HOURS
    )
    fx.sign_book(api, undeclared["id"], hall["group_1_id"])
    contractor = fx.add_contractor(api)
    job_request = fx.open_job_request(
        api,
        contractor["id"],
        job_site=RETUBE_JOB_SITE,
        journeyworkers_requested=RETUBE_JOURNEYWORKERS,
        apprentices_requested=RETUBE_APPRENTICES,
        expected_duration_days=RETUBE_DURATION_DAYS,
        hourly_rate_cents=RETUBE_RATE_CENTS,
        named_call_member_ids=[apprentice["id"], declared["id"]],
    )
    return {
        "hall": hall,
        "apprentice": apprentice,
        "declared": declared,
        "undeclared": undeclared,
        "contractor": contractor,
        "job_request": job_request,
    }


def _name_into_a_journeyworker_slot(api, job_request, member_id):
    """A named call aimed at one member, left unwrapped so failures can be read."""
    return api.create_referral(
        job_request["id"],
        f.named_call_referral_payload(
            job_request["version"], member_id, slot_kind=SLOT_JOURNEYWORKER
        ),
        DISPATCHER,
    )


class TestClassificationIsReportedBeforeUndeclaredMembership:
    """
    Two names are well inside the allowance, so neither refusal below is an
    allowance failure: one name is the wrong classification and the other was
    never declared at all.
    """

    def test_twenty_requested_workers_permit_four_named_calls(self, api):
        """
        PRD §3.6: "So a long call for any number of workers from 1 through 9 permits a
        single named call; ten through fourteen permit two; and no request, however large,
        ever permits more than four."

        Design: Corner/errors/named_call_reports_classification_before_undeclared_membership
        """
        scene = _retube_call_with_two_declared_names(api)

        assert scene["job_request"]["named_call_allowance"] == (
            RETUBE_NAMED_CALL_ALLOWANCE
        )
        assert scene["job_request"]["named_call_member_ids"] == [
            scene["apprentice"]["id"],
            scene["declared"]["id"],
        ]

    def test_a_declared_apprentice_cannot_fill_a_journeyworker_slot(self, api):
        """
        The apprentice is a declared name, so only the classification rule can refuse
        her — and it is checked ahead of the declaration rule.

        PRD §3.7: "The member's `classification` must match the requested `slot_kind`, a
        journeyworker for a journeyworker slot and an apprentice for an apprentice slot,
        failing with `ERR_CLASSIFICATION_MISMATCH` and HTTP 422."

        Design: Corner/errors/named_call_reports_classification_before_undeclared_membership
        """
        scene = _retube_call_with_two_declared_names(api)

        refused = _name_into_a_journeyworker_slot(
            api, scene["job_request"], scene["apprentice"]["id"]
        )

        expect_error(refused, ERR_CLASSIFICATION_MISMATCH, status=422)

    def test_a_journeyworker_nobody_named_is_refused_as_undeclared(self, api):
        """
        PRD §3.7: "A `NAMED_CALL` referral bypasses the ranking entirely and goes to the
        member the contractor named — which must be a member appearing in the request's
        `named_call_member_ids`, or the issuance is refused with
        `ERR_NAMED_CALL_NOT_DECLARED` — and records `variant_applied` as `NOT_APPLICABLE`
        with a null `list_position_at_issue`."

        Design: Corner/errors/named_call_reports_classification_before_undeclared_membership
        """
        scene = _retube_call_with_two_declared_names(api)

        refused = _name_into_a_journeyworker_slot(
            api, scene["job_request"], scene["undeclared"]["id"]
        )

        expect_error(refused, ERR_NAMED_CALL_NOT_DECLARED, status=409)
        assert fx.referrals_on(api, scene["job_request"]["id"]) == []

    def test_the_declared_journeyworker_is_referred_without_any_ranking(self, api):
        """
        PRD §2.7: "A named-call referral targets a member the contractor actually
        declared, failing with `ERR_NAMED_CALL_NOT_DECLARED`."

        Design: Corner/errors/named_call_reports_classification_before_undeclared_membership
        """
        scene = _retube_call_with_two_declared_names(api)

        issued = expect_created(
            _name_into_a_journeyworker_slot(
                api, scene["job_request"], scene["declared"]["id"]
            )
        )

        assert issued["member_id"] == scene["declared"]["id"]
        assert issued["referral_kind"] == REFERRAL_KIND_NAMED_CALL
        assert issued["variant_applied"] == VARIANT_NOT_APPLICABLE
        assert issued["list_position_at_issue"] is None


def _two_ranked_registrants(api):
    """A senior and a junior journeyworker on one seniority list, plus a long call."""
    hall = fx.standard_hall(api, clock=CLOCK)
    signed = fx.register_journeyworkers(
        api,
        hall["home_local_id"],
        hall["group_1_id"],
        [(RANK_ONE_NAME, RANK_ONE_HOURS), (RANK_TWO_NAME, RANK_TWO_HOURS)],
    )
    contractor = fx.add_contractor(api)
    job_request = fx.open_job_request(
        api,
        contractor["id"],
        job_site=SKIP_JOB_SITE,
        journeyworkers_requested=SKIP_JOURNEYWORKERS,
        expected_duration_days=SKIP_DURATION_DAYS,
        hourly_rate_cents=SKIP_RATE_CENTS,
    )
    return {
        "hall": hall,
        "rank_one": signed[0],
        "rank_two": signed[1],
        "contractor": contractor,
        "job_request": job_request,
    }


def _name_a_registrant(api, job_request, member_id, **extra):
    """A list-order issuance aimed at an explicit member, left unwrapped."""
    return api.create_referral(
        job_request["id"],
        f.referral_payload(
            job_request["version"],
            member_id=member_id,
            slot_kind=SLOT_JOURNEYWORKER,
            **extra,
        ),
        DISPATCHER,
    )


class TestSkippingRankOneNeedsAWrittenJustification:
    """
    The junior registrant is reachable only with a reason in writing; without one
    the issuance is refused and nothing at all is recorded.
    """

    def test_naming_the_second_ranked_registrant_is_refused(self, api):
        """
        PRD §3.7: "When a dispatcher names a `member_id` explicitly on a `LIST_ORDER` or
        `SPECIAL_SKILL` referral, that member must be the rank-one candidate under the
        governing variant — **unless** the dispatcher supplies a non-empty
        `override_reason`, a written justification for skipping the top of the list."

        Design: Corner/errors/naming_the_second_ranked_registrant_is_refused_without_an_override_reason
        """
        scene = _two_ranked_registrants(api)

        order = expect_ok(
            api.get_dispatch_order(
                scene["job_request"]["id"],
                DISPATCHER,
                {"slot_kind": SLOT_JOURNEYWORKER},
            )
        )
        assert order["top_member_id"] == scene["rank_one"]["member"]["id"]
        assert order["variant"] == VARIANT_STRICT_GROUP_ORDER

        refused = _name_a_registrant(
            api, scene["job_request"], scene["rank_two"]["member"]["id"]
        )

        expect_error(refused, ERR_OUT_OF_ORDER_DISPATCH, status=409)

    def test_the_refused_issuance_leaves_no_referral_row_behind(self, api):
        """
        PRD §3.7: "Naming somebody other than rank one without a justification is refused
        with `ERR_OUT_OF_ORDER_DISPATCH`."

        Design: Corner/errors/naming_the_second_ranked_registrant_is_refused_without_an_override_reason
        """
        scene = _two_ranked_registrants(api)
        junior_id = scene["rank_two"]["member"]["id"]

        expect_error(
            _name_a_registrant(api, scene["job_request"], junior_id),
            ERR_OUT_OF_ORDER_DISPATCH,
            status=409,
        )

        rows, meta = validate_list(
            api.list_referrals(DISPATCHER, {"member_id": junior_id})
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_the_written_reason_carries_the_skip_and_is_recorded(self, api):
        """
        PRD §3.7: "When a justification is supplied, the referral is issued and its
        `out_of_order_override` flag — which is false by default and on every other
        referral — is set to true, which is precisely what makes the referral grievable:
        the written reason and the ranked snapshot both go into the dispatch record, and a
        passed-over member can later ask a business manager to read them."

        Design: Corner/errors/naming_the_second_ranked_registrant_is_refused_without_an_override_reason
        """
        scene = _two_ranked_registrants(api)

        issued = expect_created(
            _name_a_registrant(
                api,
                scene["job_request"],
                scene["rank_two"]["member"]["id"],
                override_reason=OVERRIDE_REASON,
            )
        )

        assert issued["member_id"] == scene["rank_two"]["member"]["id"]
        assert issued["list_position_at_issue"] == 2
        assert issued["variant_applied"] == VARIANT_STRICT_GROUP_ORDER
        assert issued["override_reason"] == OVERRIDE_REASON
        assert issued["out_of_order_override"] is True


def _a_call_whose_list_has_been_emptied(api):
    """One signer, then removed at her own request, leaving an open slot and no pool."""
    hall = fx.standard_hall(api, clock=CLOCK)
    member = fx.add_journeyworker(
        api, hall["home_local_id"], LONE_SIGNER_NAME, LONE_SIGNER_HOURS
    )
    registration = fx.sign_book(api, member["id"], hall["group_1_id"])
    removed = expect_ok(
        api.remove_registration(
            registration["id"], f.removal_payload(REMOVAL_VOLUNTARY), DISPATCHER
        )
    )
    contractor = fx.add_contractor(api)
    job_request = fx.open_job_request(
        api,
        contractor["id"],
        job_site=EMPTY_JOB_SITE,
        expected_duration_days=EMPTY_DURATION_DAYS,
        hourly_rate_cents=EMPTY_RATE_CENTS,
    )
    return {
        "hall": hall,
        "member": member,
        "removed": removed,
        "contractor": contractor,
        "job_request": job_request,
    }


class TestAnEmptyPoolIsRefusedOnTheReadAndOnTheWrite:
    """
    The request has a slot to fill and the hall has nobody to send, and both the
    computed read and the issuance say so with the same code.
    """

    def test_the_computed_read_refuses_an_empty_pool(self, api):
        """
        PRD §3.2: "That read is computed live and stores nothing, and it fails with
        `ERR_NO_ELIGIBLE_REGISTRANT` when the pool is empty, exactly as issuance would."

        Design: Corner/errors/empty_candidate_set_is_refused_on_both_the_read_and_the_issuance
        """
        scene = _a_call_whose_list_has_been_emptied(api)

        assert scene["removed"]["status"] == REGISTRATION_REMOVED
        assert scene["job_request"]["open_journeyworker_slots"] == 1

        refused = api.get_dispatch_order(
            scene["job_request"]["id"], DISPATCHER, {"slot_kind": SLOT_JOURNEYWORKER}
        )

        expect_error(refused, ERR_NO_ELIGIBLE_REGISTRANT, status=409)

    def test_the_issuance_refuses_the_same_empty_pool(self, api):
        """
        PRD §2.7: "The ranked candidate pool is non-empty, on referral issuance and on the
        dispatch-order read, failing with `ERR_NO_ELIGIBLE_REGISTRANT`."

        Design: Corner/errors/empty_candidate_set_is_refused_on_both_the_read_and_the_issuance
        """
        scene = _a_call_whose_list_has_been_emptied(api)

        refused = api.create_referral(
            scene["job_request"]["id"],
            f.referral_payload(
                scene["job_request"]["version"], slot_kind=SLOT_JOURNEYWORKER
            ),
            DISPATCHER,
        )

        expect_error(refused, ERR_NO_ELIGIBLE_REGISTRANT, status=409)

    def test_the_refused_issuance_does_not_advance_the_request(self, api):
        """
        A refused issuance is not a mutation, so the pinned version a client already holds
        stays usable.

        PRD §2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC instant
        with three fractional digits refreshed on every mutation that changes any stored
        field, and `version`, an integer that begins at 1 on creation and increments by
        exactly 1 on every mutation."

        Design: Corner/errors/empty_candidate_set_is_refused_on_both_the_read_and_the_issuance
        """
        scene = _a_call_whose_list_has_been_emptied(api)
        intake_version = scene["job_request"]["version"]

        expect_error(
            api.create_referral(
                scene["job_request"]["id"],
                f.referral_payload(intake_version, slot_kind=SLOT_JOURNEYWORKER),
                DISPATCHER,
            ),
            ERR_NO_ELIGIBLE_REGISTRANT,
            status=409,
        )

        after = fx.read_job_request(api, scene["job_request"]["id"])
        assert after["status"] == JOB_REQUEST_OPEN
        assert after["version"] == intake_version
        assert fx.referrals_on(api, scene["job_request"]["id"]) == []


def _a_dispatch_exactly_two_days_old(api):
    """
    A working dispatch whose `start_at` is the reporting instant, with the clock
    then parked exactly forty-eight hours later.
    """
    scene = fx.working_dispatch(
        api,
        clock=CLOCK,
        hours=CAPPED_HOURS,
        full_name=CAPPED_MEMBER,
        job_site=CAP_JOB_SITE,
        report_at=CAP_REPORT_AT,
        expected_duration_days=CAP_DURATION_DAYS,
        hourly_rate_cents=CAP_RATE_CENTS,
    )
    fx.set_clock(api, LAYOFF_CLOCK)
    return scene


def _report_hours(api, scene, hours):
    """The contractor's own representative closes the record, left unwrapped."""
    return api.layoff_dispatch(
        scene["dispatch"]["id"],
        f.layoff_payload(hours),
        make_contractor_rep_headers(scene["contractor"]["id"]),
    )


class TestReportedHoursAreCappedByElapsedDays:
    """
    Two elapsed days permit twenty-four hours: twenty-five is refused whole, and
    twenty-four is accepted whole.
    """

    def test_one_hour_past_the_cap_is_refused_and_nothing_is_applied(self, api):
        """
        PRD §3.8: "Reported hours are sanity-checked against elapsed time: `hours_worked`
        may not exceed twelve hours for each elapsed calendar day since the dispatch began,
        where the number of elapsed days is the difference between the current instant and
        `start_at` divided by twenty-four hours and rounded up to a whole day."

        Design: Corner/errors/reported_hours_above_the_elapsed_cap_are_refused_and_the_cap_itself_is_accepted
        """
        scene = _a_dispatch_exactly_two_days_old(api)
        assert_instant_equals(scene["dispatch"]["start_at"], CAP_REPORT_AT)
        assert scene["dispatch"]["hours_worked"] == 0

        refused = _report_hours(api, scene, ONE_HOUR_TOO_MANY)

        expect_error(refused, ERR_HOURS_EXCEED_ELAPSED, status=422)
        still_open = expect_ok(api.get_dispatch(scene["dispatch"]["id"], DISPATCHER))
        assert still_open["status"] == DISPATCH_WORKING
        assert still_open["hours_worked"] == 0

    def test_the_cap_itself_is_accepted_and_closes_the_record(self, api):
        """
        PRD §3.8: "`REDUCTION_IN_FORCE`, `JOB_COMPLETE`, and `LACK_OF_WORK` are all
        no-fault endings: the `status` becomes `LAID_OFF`, `ended_at` is set to the current
        instant, the reported `hours_worked` is recorded, and `recall_window_ends_at` is
        set to the current instant plus 7 days."

        Design: Corner/errors/reported_hours_above_the_elapsed_cap_are_refused_and_the_cap_itself_is_accepted
        """
        scene = _a_dispatch_exactly_two_days_old(api)

        closed = expect_ok(_report_hours(api, scene, ELAPSED_CAP_HOURS))

        assert closed["status"] == DISPATCH_LAID_OFF
        assert closed["hours_worked"] == ELAPSED_CAP_HOURS
        assert_instant_equals(closed["ended_at"], LAYOFF_CLOCK)

    def test_only_the_accepted_report_reaches_the_hour_bank(self, api):
        """
        PRD §3.8: "Whichever ending applies, the reported `hours_worked` is added to the
        member's `local_hours_in_trade`, which is how work under the home local's
        agreement accumulates toward the higher list groups and toward seniority on the
        next registration."

        Design: Corner/errors/reported_hours_above_the_elapsed_cap_are_refused_and_the_cap_itself_is_accepted
        """
        scene = _a_dispatch_exactly_two_days_old(api)

        expect_error(
            _report_hours(api, scene, ONE_HOUR_TOO_MANY),
            ERR_HOURS_EXCEED_ELAPSED,
            status=422,
        )
        assert fx.read_member(api, scene["member"]["id"])["local_hours_in_trade"] == (
            CAPPED_HOURS
        )

        expect_ok(_report_hours(api, scene, ELAPSED_CAP_HOURS))

        assert fx.read_member(api, scene["member"]["id"])["local_hours_in_trade"] == (
            CAPPED_HOURS + ELAPSED_CAP_HOURS
        )


def _a_claim_resting_on_one_ledger_entry(api):
    """
    The senior registrant takes the call, the junior one grieves it, and the
    manager opens the file — leaving the decision resting on one issuance record.
    """
    hall = fx.standard_hall(api, clock=CLOCK)
    signed = fx.register_journeyworkers(
        api,
        hall["home_local_id"],
        hall["group_1_id"],
        [(REFERRED_NAME, REFERRED_HOURS), (PASSED_OVER_NAME, PASSED_OVER_HOURS)],
    )
    contractor = fx.add_contractor(api)
    job_request = fx.open_job_request(
        api,
        contractor["id"],
        job_site=PURGE_JOB_SITE,
        expected_duration_days=PURGE_DURATION_DAYS,
        hourly_rate_cents=PURGE_RATE_CENTS,
    )
    referral = fx.issue_referral(
        api, job_request["id"], slot_kind=SLOT_JOURNEYWORKER
    )
    entries = fx.ledger_rows(
        api, referral_id=referral["id"], event_code=EVENT_REFERRAL_ISSUED
    )
    grievance = fx.grievance_under_review(
        api,
        referral["id"],
        signed[1]["member"]["id"],
        claim_type=CLAIM_OUT_OF_ORDER_DISPATCH,
        narrative=PURGE_NARRATIVE,
    )
    return {
        "hall": hall,
        "referred": signed[0],
        "passed_over": signed[1],
        "job_request": job_request,
        "referral": referral,
        "entry": entries[0],
        "grievance": grievance,
    }


def _sweep_past_the_retention_horizon(api):
    """Move five years on and let the housekeeping sweep do its purging pass."""
    fx.set_clock(api, SWEEP_CLOCK)
    return fx.run_sweep(api)


class TestAnOutOfOrderClaimCannotOutliveItsEvidence:
    """
    The ranked snapshot behind an out-of-order finding has a five-year life, and
    once the sweep clears it the claim can no longer be sustained.
    """

    def test_the_issuance_entry_is_retained_for_five_years(self, api):
        """
        PRD §2.10: "Each entry's `retention_until` is its `recorded_at` plus 1,825 days,
        and its `purge_state` is `RETAINED` until the housekeeping sweep flips it to
        `PURGED` and clears `snapshot_json` to null."

        Design: Corner/errors/sustaining_an_out_of_order_claim_on_a_purged_record_is_refused
        """
        scene = _a_claim_resting_on_one_ledger_entry(api)
        entry = scene["entry"]

        assert entry["event_code"] == EVENT_REFERRAL_ISSUED
        assert entry["purge_state"] == PURGE_RETAINED
        assert_instant_equals(
            entry["retention_until"], plus_days(entry["recorded_at"], RETENTION_DAYS)
        )
        assert_instant_equals(entry["retention_until"], RETENTION_HORIZON)
        assert scene["grievance"]["status"] == GRIEVANCE_UNDER_REVIEW

    def test_the_purged_entry_is_still_readable_without_its_snapshot(self, api):
        """
        PRD §2.10: "A purged entry is still readable: it returns with `purge_state` of
        `PURGED` and a null `snapshot_json`."

        Design: Corner/errors/sustaining_an_out_of_order_claim_on_a_purged_record_is_refused
        """
        scene = _a_claim_resting_on_one_ledger_entry(api)
        assert scene["entry"]["snapshot_json"] is not None

        summary = _sweep_past_the_retention_horizon(api)

        assert summary["purged_ledger_entry_count"] >= 1
        purged = expect_ok(api.get_ledger_entry(scene["entry"]["id"], HALL_ADMIN))
        assert purged["purge_state"] == PURGE_PURGED
        assert purged["snapshot_json"] is None

    def test_sustaining_the_claim_is_refused_and_the_file_stays_open(self, api):
        """
        PRD §3.9: "For an `OUT_OF_ORDER_DISPATCH` claim, the `REFERRAL_ISSUED` ledger entry
        of the challenged referral must still have `purge_state` of `RETAINED`, failing
        with `ERR_DISPATCH_RECORD_PURGED` — a claim whose evidence has aged out of the
        five-year retention period cannot be sustained."

        Design: Corner/errors/sustaining_an_out_of_order_claim_on_a_purged_record_is_refused
        """
        scene = _a_claim_resting_on_one_ledger_entry(api)
        _sweep_past_the_retention_horizon(api)

        refused = api.adjudicate_grievance(
            scene["grievance"]["id"],
            f.adjudication_payload(
                decision=DECISION_SUSTAINED, remedy=REMEDY_NONE, note=SUSTAIN_NOTE
            ),
            BUSINESS_MANAGER,
        )

        expect_error(refused, ERR_DISPATCH_RECORD_PURGED, status=409)
        after = expect_ok(
            api.get_grievance(scene["grievance"]["id"], BUSINESS_MANAGER)
        )
        assert after["status"] == GRIEVANCE_UNDER_REVIEW
        assert after["decided_at"] is None
        assert after["decided_by_user_id"] is None


def _a_claim_over_a_referral_that_never_dispatched(api):
    """
    The rank-one registrant turns the call down with good cause, so no dispatch
    ever exists; the next registrant grieves and the manager opens the file.
    """
    hall = fx.standard_hall(api, clock=CLOCK)
    signed = fx.register_journeyworkers(
        api,
        hall["home_local_id"],
        hall["group_1_id"],
        [(REFUSING_NAME, REFUSING_HOURS), (GRIEVING_NAME, GRIEVING_HOURS)],
    )
    contractor = fx.add_contractor(api)
    job_request = fx.open_job_request(
        api,
        contractor["id"],
        job_site=REMEDY_JOB_SITE,
        journeyworkers_requested=REMEDY_JOURNEYWORKERS,
        expected_duration_days=REMEDY_DURATION_DAYS,
        hourly_rate_cents=REMEDY_RATE_CENTS,
    )
    referral = fx.issue_referral(
        api, job_request["id"], slot_kind=SLOT_JOURNEYWORKER
    )
    refused = fx.refuse_referral(
        api, referral["id"], signed[0]["member"]["id"], GOOD_CAUSE_MEDICAL
    )
    grievance = fx.grievance_under_review(
        api,
        referral["id"],
        signed[1]["member"]["id"],
        claim_type=CLAIM_IMPROPER_NAMED_CALL,
        narrative=REMEDY_NARRATIVE,
    )
    return {
        "hall": hall,
        "refusing": signed[0],
        "grieving": signed[1],
        "job_request": job_request,
        "referral": referral,
        "refused": refused,
        "grievance": grievance,
    }


def _decide(api, grievance, decision, remedy, **extra):
    """One adjudication attempt, left unwrapped so refusals can be read."""
    return api.adjudicate_grievance(
        grievance["id"],
        f.adjudication_payload(decision=decision, remedy=remedy, **extra),
        BUSINESS_MANAGER,
    )


class TestRemedyApplicabilityGuardsBothOfItsClauses:
    """
    One grievance trips both halves of the remedy rule: make-whole hours with no
    dispatch to measure, and a denial carrying a remedy anyway.
    """

    def test_make_whole_hours_needs_a_dispatch_to_measure(self, api):
        """
        PRD §3.9: "And a `MAKE_WHOLE_HOURS` remedy requires that the challenged referral
        actually produced a dispatch, while a `DENIED` decision requires `remedy` to be
        `NONE`; either violation is refused with `ERR_REMEDY_NOT_APPLICABLE`."

        Design: Corner/errors/denied_with_a_remedy_and_make_whole_without_a_dispatch_are_both_refused
        """
        scene = _a_claim_over_a_referral_that_never_dispatched(api)
        assert scene["refused"]["status"] == REFERRAL_REFUSED
        _, meta = validate_list(
            api.list_dispatches(DISPATCHER, {"referral_id": scene["referral"]["id"]})
        )
        assert meta["total_count"] == 0

        refused = _decide(
            api, scene["grievance"], DECISION_SUSTAINED, REMEDY_MAKE_WHOLE_HOURS
        )

        expect_error(refused, ERR_REMEDY_NOT_APPLICABLE, status=409)

    def test_a_denial_cannot_carry_a_remedy(self, api):
        """
        PRD §2.7: "Remedy applicability at adjudication, failing with
        `ERR_REMEDY_NOT_APPLICABLE`."

        Design: Corner/errors/denied_with_a_remedy_and_make_whole_without_a_dispatch_are_both_refused
        """
        scene = _a_claim_over_a_referral_that_never_dispatched(api)

        refused = _decide(
            api,
            scene["grievance"],
            DECISION_DENIED,
            REMEDY_NEXT_AVAILABLE_PRIORITY,
        )

        expect_error(refused, ERR_REMEDY_NOT_APPLICABLE, status=409)
        still_open = expect_ok(
            api.get_grievance(scene["grievance"]["id"], BUSINESS_MANAGER)
        )
        assert still_open["status"] == GRIEVANCE_UNDER_REVIEW

    def test_the_inert_denial_is_accepted_and_awards_nothing(self, api):
        """
        PRD §3.9: "Denying is deliberately inert. `status` becomes `DENIED`,
        `decided_by_user_id` and `decided_at` are recorded, `back_pay_variant` stays
        `NOT_APPLICABLE`, and `back_pay_hours` and `back_pay_amount_cents` both stay 0."

        Design: Corner/errors/denied_with_a_remedy_and_make_whole_without_a_dispatch_are_both_refused
        """
        scene = _a_claim_over_a_referral_that_never_dispatched(api)

        decided = expect_ok(
            _decide(
                api,
                scene["grievance"],
                DECISION_DENIED,
                REMEDY_NONE,
                note=DENIAL_NOTE,
            )
        )

        assert decided["status"] == GRIEVANCE_DENIED
        assert decided["remedy"] == REMEDY_NONE
        assert decided["back_pay_variant"] == BACK_PAY_NOT_APPLICABLE
        assert decided["back_pay_hours"] == 0
        assert decided["back_pay_amount_cents"] == 0
        assert decided["decided_by_user_id"] == BUSINESS_MANAGER_USER_ID
        assert_instant_equals(decided["decided_at"], CLOCK)


def _one_signer_and_a_second_easier_list(api):
    """
    A journeyworker signed onto the senior list, with an open list beside it that
    would admit anybody at all.
    """
    hall = fx.standard_hall(api, clock=CLOCK, groups=(GROUP_1, GROUP_4))
    member = fx.add_journeyworker(
        api, hall["home_local_id"], TWICE_SIGNING_NAME, TWICE_SIGNING_HOURS
    )
    registration = fx.sign_book(api, member["id"], hall["group_1_id"])
    return {"hall": hall, "member": member, "registration": registration}


def _sign_again(api, member_id, list_id):
    """A second signing attempt, left unwrapped so refusals can be read."""
    return api.create_registration(
        f.registration_payload(member_id, list_id), DISPATCHER
    )


class TestOnlyOneLiveRegistrationAcrossEveryList:
    """
    The at-most-one rule is counted hall-wide, so a second list is no escape from
    it — and the rule releases the moment the first registration is removed.
    """

    def test_signing_the_same_list_twice_is_refused(self, api):
        """
        PRD §3.3: "A member may hold only one live registration at a time — at most one
        whose `status` is `REGISTERED` or `REFERRED`, counted across every list — and a
        second attempt is refused with `ERR_MEMBER_ALREADY_REGISTERED`."

        PRD §3.1: "`re_registration_eligible_at` is null for a member in ordinary
        standing"

        Design: Corner/errors/second_active_registration_is_refused_on_every_list
        """
        scene = _one_signer_and_a_second_easier_list(api)
        assert scene["registration"]["status"] == REGISTRATION_REGISTERED
        assert scene["registration"]["position_number"] == 1
        # The cooling-off horizon lives on the member, not on the registration,
        # and nothing here has been removed for three refusals.
        assert (
            fx.read_member(api, scene["member"]["id"])["re_registration_eligible_at"]
            is None
        )

        refused = _sign_again(
            api, scene["member"]["id"], scene["hall"]["group_1_id"]
        )

        expect_error(refused, ERR_MEMBER_ALREADY_REGISTERED, status=409)

    def test_a_different_list_is_refused_by_the_same_rule(self, api):
        """
        The second list would admit the member on its own terms, so only a hall-wide
        count can explain the refusal.

        PRD §2.7: "The member holds at most one registration in `REGISTERED` or `REFERRED`
        status across all lists, on list-signing, failing with
        `ERR_MEMBER_ALREADY_REGISTERED`."

        Design: Corner/errors/second_active_registration_is_refused_on_every_list
        """
        scene = _one_signer_and_a_second_easier_list(api)
        open_list = fx.read_list_group(api, scene["hall"]["group_4_id"])
        assert open_list["requires_local_hours"] == 0

        refused = _sign_again(
            api, scene["member"]["id"], scene["hall"]["group_4_id"]
        )

        expect_error(refused, ERR_MEMBER_ALREADY_REGISTERED, status=409)
        assert fx.registrations_on(api, scene["hall"]["group_4_id"]) == []

    def test_removing_the_first_registration_releases_the_member(self, api):
        """
        PRD §3.3: "A member may hold only one live registration at a time — at most one
        whose `status` is `REGISTERED` or `REFERRED`, counted across every list — and a
        second attempt is refused with `ERR_MEMBER_ALREADY_REGISTERED`."

        Design: Corner/errors/second_active_registration_is_refused_on_every_list
        """
        scene = _one_signer_and_a_second_easier_list(api)

        removed = expect_ok(
            api.remove_registration(
                scene["registration"]["id"],
                f.removal_payload(REMOVAL_VOLUNTARY),
                DISPATCHER,
            )
        )
        assert removed["status"] == REGISTRATION_REMOVED

        fresh = expect_created(
            _sign_again(api, scene["member"]["id"], scene["hall"]["group_4_id"])
        )

        assert fresh["status"] == REGISTRATION_REGISTERED
        assert fresh["position_number"] == 1
        assert_instant_equals(fresh["registered_at"], CLOCK)


def _a_cancelled_call(api):
    """A call withdrawn by its own contractor while it was still open."""
    hall = fx.standard_hall(api, clock=CLOCK)
    member = fx.add_journeyworker(
        api, hall["home_local_id"], CANCELLED_MEMBER, CANCELLED_MEMBER_HOURS
    )
    registration = fx.sign_book(api, member["id"], hall["group_1_id"])
    contractor = fx.add_contractor(api)
    job_request = fx.open_job_request(
        api,
        contractor["id"],
        job_site=CANCELLED_JOB_SITE,
        expected_duration_days=CANCELLED_DURATION_DAYS,
        hourly_rate_cents=CANCELLED_RATE_CENTS,
    )
    cancelled = expect_ok(
        api.cancel_job_request(
            job_request["id"],
            f.cancel_payload(FIRST_CANCEL_REASON),
            make_contractor_rep_headers(contractor["id"]),
        )
    )
    return {
        "hall": hall,
        "member": member,
        "registration": registration,
        "contractor": contractor,
        "job_request": job_request,
        "cancelled": cancelled,
    }


class TestACancelledCallAcceptsNothingFurther:
    """
    One code guards two endpoints over two different state sets: after
    cancellation neither an issuance nor a second cancellation is admitted.
    """

    def test_a_referral_is_refused_even_with_the_current_version(self, api):
        """
        The pinned version is the one the cancellation itself produced, so the openness
        check is the only rule that can be refusing this issuance.

        PRD §3.7: "The job request's `status` must be `OPEN` or `PARTIALLY_FILLED`, and the
        open-slot counter matching the requested `slot_kind` must be at least 1 —
        `open_journeyworker_slots` for a journeyworker slot, `open_apprentice_slots` for an
        apprentice slot — failing with `ERR_JOB_REQUEST_NOT_OPEN`."

        Design: Corner/errors/cancelled_request_accepts_neither_a_referral_nor_a_second_cancel
        """
        scene = _a_cancelled_call(api)
        assert scene["cancelled"]["status"] == JOB_REQUEST_CANCELLED

        refused = api.create_referral(
            scene["job_request"]["id"],
            f.referral_payload(
                scene["cancelled"]["version"], slot_kind=SLOT_JOURNEYWORKER
            ),
            DISPATCHER,
        )

        expect_error(refused, ERR_JOB_REQUEST_NOT_OPEN, status=409)

    def test_a_second_cancellation_is_refused_by_the_same_code(self, api):
        """
        PRD §3.6: "Cancelling a request that is already `FILLED`, `CLOSED`, or `CANCELLED`
        is refused with `ERR_JOB_REQUEST_NOT_OPEN`."

        Design: Corner/errors/cancelled_request_accepts_neither_a_referral_nor_a_second_cancel
        """
        scene = _a_cancelled_call(api)

        refused = api.cancel_job_request(
            scene["job_request"]["id"],
            f.cancel_payload(SECOND_CANCEL_REASON),
            make_contractor_rep_headers(scene["contractor"]["id"]),
        )

        expect_error(refused, ERR_JOB_REQUEST_NOT_OPEN, status=409)
        after = fx.read_job_request(api, scene["job_request"]["id"])
        assert after["status"] == JOB_REQUEST_CANCELLED
        assert after["version"] == scene["cancelled"]["version"]

    def test_the_refused_issuance_never_touched_the_list(self, api):
        """
        PRD §2.7: "Job-request openness: for referral issuance the request's `status` is
        `OPEN` or `PARTIALLY_FILLED` and the open-slot counter matching the requested
        `slot_kind` is greater than zero; for cancellation the `status` is `OPEN`,
        `PARTIALLY_FILLED` or `SUSPENDED`. Failures are `ERR_JOB_REQUEST_NOT_OPEN`."

        Design: Corner/errors/cancelled_request_accepts_neither_a_referral_nor_a_second_cancel
        """
        scene = _a_cancelled_call(api)

        expect_error(
            api.create_referral(
                scene["job_request"]["id"],
                f.referral_payload(
                    scene["cancelled"]["version"], slot_kind=SLOT_JOURNEYWORKER
                ),
                DISPATCHER,
            ),
            ERR_JOB_REQUEST_NOT_OPEN,
            status=409,
        )

        held = fx.read_registration(api, scene["registration"]["id"])
        assert held["status"] == REGISTRATION_REGISTERED
        assert fx.referrals_on(api, scene["job_request"]["id"]) == []
