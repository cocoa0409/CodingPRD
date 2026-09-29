"""
The shape of the hall's records: which fields a creation echoes back, which the
server mints or derives, which optional inputs fall back to a declared default,
and which two record types are deliberately reduced to two audit columns.
"""

import pytest

from test_helpers import (
    CLASSIFICATION_APPRENTICE,
    CLASSIFICATION_JOURNEYWORKER,
    DEFAULT_LIMIT,
    DISPATCHER,
    ERR_INVALID_REQUEST,
    ERR_MEMBER_NOT_FOUND,
    ERR_REGISTRATION_NOT_FOUND,
    GROUP_1,
    GROUP_2,
    GROUP_4,
    HALL_ADMIN,
    LOCAL_KIND_SISTER,
    MIN_OFFSET,
    NON_EXISTENT_UUID,
    OTHER_DISPATCHER,
    OTHER_DISPATCHER_USER_ID,
    REGISTRATION_DISPATCHED_OUT,
    REGISTRATION_REGISTERED,
    SIGNATORY,
    SKILL_FIRE_WATCH,
    SKILL_RIGGING,
    SKILL_WELDING_6G,
    SLOT_JOURNEYWORKER,
    STANDING_GOOD,
    assert_bare_uuid,
    assert_envelope_meta,
    assert_error_meta_is_minimal,
    assert_full_common_fields,
    assert_instant_equals,
    assert_pagination,
    assert_reduced_common_fields,
    assert_single_read_omits_pagination,
    expect_created,
    expect_error,
    expect_ok,
    factories as f,
    fixtures as fx,
    ids_of,
    make_contractor_rep_headers,
    make_member_headers,
    plus_days,
    plus_hours,
    round_half_up_bp,
    validate_list,
)

CLOCK = "2026-09-01T00:00:00.000Z"
REPORT_AT = "2026-09-25T07:00:00.000Z"
CERTIFIED_UNTIL = "2027-01-01T00:00:00.000Z"

# ─── Locals and members ───────────────────────────────────────────────────────

SISTER_LOCAL_NUMBER = 46
SISTER_LOCAL_NAME = "Local 46 (sister)"
SISTER_FACTOR_BP = 5000
HOME_FACTOR_BP = 0
READ_MEMBER_NAME = "Nia Okoye"
READ_MEMBER_HOURS = 6200
DEFAULTS_MEMBER_NAME = "Otto Vance"
DEFAULTS_MEMBER_HOURS = 9000
APPRENTICE_HOURS = 100
VALID_UPPER_PERIOD = 4

# ─── The traveler's credited hours ────────────────────────────────────────────

TRAVELER_NAME = "Pia Solis"
LOCAL_NAME = "Local Larry"
TRAVELER_LOCAL_HOURS = 200
TRAVELER_RAW_HOURS = 1000
TRAVELER_CREDITED_HOURS = 700
RENEWAL_DUE_AT = "2026-10-01T00:00:00.000Z"

# ─── Contractor intake ────────────────────────────────────────────────────────

INTAKE_CONTRACTOR = "Aldridge Mechanical"
DEFAULTING_CONTRACTOR = "Default Signatory Co"
NO_REPORT_TIME_SITE = "No Report Time"
ZERO_HEADCOUNT_SITE = "Zero Headcount"
INTAKE_JOURNEYWORKERS = 2
INTAKE_DURATION_DAYS = 20
INTAKE_RATE_CENTS = 5000

# ─── The issued referral and the dispatch behind it ───────────────────────────

ISSUING_CONTRACTOR = "Kestrel Piping"
ISSUING_JOB_SITE = "Pump House"
ISSUED_MEMBER_NAME = "Quill Adeyemi"
GRAPH_CONTRACTOR = "Orchard Steel"
GRAPH_JOB_SITE = "Bay 6"
GRAPH_MEMBER_NAME = "Uli Nakamura"
CALL_HOURS = 9000

# ─── Endorsement parents ──────────────────────────────────────────────────────

ENDORSED_MEMBER_NAME = "Rue Halvorsen"
FIRST_PARENT_NAME = "Sol Iversen"
SECOND_PARENT_NAME = "Tam Boateng"
SECOND_PARENT_HOURS = 8000


def _three_list_groups(api):
    """Exactly three list groups on file: ranks one, two and four."""
    fx.set_clock(api, CLOCK)
    return {
        GROUP_1: fx.add_list_group(api, f.group_one_payload()),
        GROUP_2: fx.add_list_group(api, f.group_two_payload()),
        GROUP_4: fx.add_list_group(api, f.group_four_payload()),
    }


def _signatory_contractor(api, name):
    """One contractor in good standing with the trust funds and no work yet."""
    fx.set_clock(api, CLOCK)
    return expect_created(api.create_contractor(f.contractor_payload(name=name), HALL_ADMIN))


def _intake(contractor_id, **overrides):
    """The one intake payload the shape legs vary a single field of."""
    fields = {
        "journeyworkers_requested": INTAKE_JOURNEYWORKERS,
        "apprentices_requested": 0,
        "expected_duration_days": INTAKE_DURATION_DAYS,
        "report_at": REPORT_AT,
        "hourly_rate_cents": INTAKE_RATE_CENTS,
    }
    fields.update(overrides)
    return f.job_request_payload(contractor_id, **fields)


def _member_payload(home_local_id, full_name, classification, hours, period=None):
    """A member creation body that carries a period only when one is supplied."""
    payload = {
        "full_name": full_name,
        "home_local_id": home_local_id,
        "classification": classification,
        "local_hours_in_trade": hours,
    }
    if period is not None:
        payload["apprentice_period"] = period
    return payload


def _one_journeyworker_on_one_call(api, contractor_name, job_site, full_name):
    """A registered journeyworker and a long call for exactly one of them."""
    hall = fx.standard_hall(api, clock=CLOCK)
    member = fx.add_journeyworker(api, hall["home_local_id"], full_name, CALL_HOURS)
    registration = fx.sign_book(api, member["id"], hall["group_1_id"])
    contractor = fx.add_contractor(api, name=contractor_name)
    job_request = fx.open_job_request(
        api,
        contractor["id"],
        job_site=job_site,
        journeyworkers_requested=1,
        apprentices_requested=0,
        expected_duration_days=INTAKE_DURATION_DAYS,
        report_at=REPORT_AT,
        hourly_rate_cents=INTAKE_RATE_CENTS,
    )
    return {
        "hall": hall,
        "member": member,
        "registration": registration,
        "contractor": contractor,
        "job_request": job_request,
    }


class TestCreationEchoesInputsAndAppliesDefaults:
    """A creation returns the caller's own fields plus the columns the hall mints."""

    def test_a_new_local_echoes_every_input_and_opens_at_version_one(self, api):
        """
        PRD §2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC
        instant with three fractional digits refreshed on every mutation that changes
        any stored field, and `version`, an integer that begins at 1 on creation and
        increments by exactly 1 on every mutation."

        Design: Corner/entities/local_creation_echoes_inputs_and_adds_common_fields
        """
        fx.set_clock(api, CLOCK)
        payload = f.sister_local_payload()

        response = api.create_local(payload, HALL_ADMIN)
        created = expect_created(response)

        assert_envelope_meta(response)
        assert created["local_number"] == SISTER_LOCAL_NUMBER
        assert created["name"] == SISTER_LOCAL_NAME
        assert created["kind"] == LOCAL_KIND_SISTER
        assert created["reciprocity_factor_bp"] == SISTER_FACTOR_BP
        assert_bare_uuid(created["id"])
        assert_full_common_fields(created, 1)
        assert_instant_equals(created["created_at"], CLOCK)
        assert_instant_equals(created["updated_at"], CLOCK)

    def test_the_registration_optional_inputs_fall_back_to_their_declared_values(
        self, api
    ):
        """
        PRD §3.3: "The request names the `member_id` being registered and the
        `list_id` of the group being signed, and may additionally declare
        `reciprocity_credits`, a `predecessor_registration_id`, which defaults to
        null, and `claim_position_preservation`, which defaults to false."

        Design: Corner/entities/registration_and_contractor_optional_inputs_apply_declared_defaults
        """
        fx.set_clock(api, CLOCK)
        home = fx.add_home_local(api)
        group = fx.add_list_group(api, f.group_one_payload())
        member = fx.add_journeyworker(
            api, home["id"], DEFAULTS_MEMBER_NAME, DEFAULTS_MEMBER_HOURS
        )

        registration = expect_created(
            api.create_registration(
                {"member_id": member["id"], "list_id": group["id"]}, DISPATCHER
            )
        )

        assert registration["reciprocity_credits"] == []
        assert registration["predecessor_registration_id"] is None
        assert registration["claim_position_preservation"] is False
        assert registration["demotion_count"] == 0
        assert registration["priority_flag"] is False
        assert registration["status"] == REGISTRATION_REGISTERED
        assert registration["removal_reason"] is None

    def test_the_contractor_and_local_defaults_are_the_documented_values(self, api):
        """
        PRD §3.5: "A `Contractor` is a signatory employer, entered by a `HallAdmin`
        with a `name` of 1 to 120 characters, an `agreement_expires_at` instant
        recording when its collective bargaining agreement lapses, and a
        `signatory_status` that defaults to `SIGNATORY` and is otherwise
        `DELINQUENT_TRUST_FUNDS` or `TERMINATED`."

        PRD §3.1: "The field defaults to 0, accepts values from 0 through 10,000, and
        a value of 0 means there is no reciprocity agreement with that local at all."

        Design: Corner/entities/registration_and_contractor_optional_inputs_apply_declared_defaults
        """
        fx.set_clock(api, CLOCK)
        local_payload = f.home_local_payload()
        local_payload.pop("reciprocity_factor_bp", None)
        contractor_payload = f.contractor_payload(name=DEFAULTING_CONTRACTOR)
        contractor_payload.pop("signatory_status", None)

        local = expect_created(api.create_local(local_payload, HALL_ADMIN))
        contractor = expect_created(
            api.create_contractor(contractor_payload, HALL_ADMIN)
        )

        assert local["reciprocity_factor_bp"] == HOME_FACTOR_BP
        assert contractor["signatory_status"] == SIGNATORY


class TestShapeConstraintsOnCreation:
    """The shape check is the third gate, and it names one error for every breach."""

    @pytest.mark.parametrize(
        "full_name,classification,period",
        [
            ("Period Five", CLASSIFICATION_APPRENTICE, 5),
            ("Journeyworker With Period", CLASSIFICATION_JOURNEYWORKER, 2),
            ("Apprentice No Period", CLASSIFICATION_APPRENTICE, None),
        ],
    )
    def test_a_period_that_breaks_the_classification_pairing_is_refused(
        self, api, full_name, classification, period
    ):
        """
        PRD §3.1: "An apprentice must also declare an `apprentice_period`, an integer
        from 1 through 4 identifying the wage period; a journeyworker must leave
        `apprentice_period` null. Supplying a period for a journeyworker, or omitting
        it for an apprentice, is a shape violation reported as `ERR_INVALID_REQUEST`."

        Design: Corner/entities/member_apprentice_period_outside_declared_range_rejected
        """
        fx.set_clock(api, CLOCK)
        home = fx.add_home_local(api)

        response = api.create_member(
            _member_payload(
                home["id"], full_name, classification, APPRENTICE_HOURS, period
            ),
            HALL_ADMIN,
        )

        expect_error(response, ERR_INVALID_REQUEST)

    def test_the_top_of_the_period_range_is_itself_accepted(self, api):
        """
        PRD §3.1: "An apprentice must also declare an `apprentice_period`, an integer
        from 1 through 4 identifying the wage period; a journeyworker must leave
        `apprentice_period` null."

        Design: Corner/entities/member_apprentice_period_outside_declared_range_rejected
        """
        fx.set_clock(api, CLOCK)
        home = fx.add_home_local(api)

        created = expect_created(
            api.create_member(
                _member_payload(
                    home["id"],
                    "Valid Apprentice",
                    CLASSIFICATION_APPRENTICE,
                    APPRENTICE_HOURS,
                    VALID_UPPER_PERIOD,
                ),
                HALL_ADMIN,
            )
        )

        assert created["apprentice_period"] == VALID_UPPER_PERIOD
        assert created["classification"] == CLASSIFICATION_APPRENTICE

    def test_an_intake_without_a_reporting_instant_is_refused(self, api):
        """
        PRD §2.7: "Request shape, on every endpoint: required fields present, JSON
        types correct, enum members recognized, integers inside their declared ranges,
        at least one worker requested across the two headcount fields,
        `apprentice_period` present exactly when `classification` is `APPRENTICE` and
        absent otherwise, `limit` within 1 through 100 and `offset` at least 0.
        Failures are `ERR_INVALID_REQUEST`."

        Design: Corner/entities/job_request_missing_required_report_at_returns_invalid_request
        """
        contractor = _signatory_contractor(api, INTAKE_CONTRACTOR)
        payload = _intake(contractor["id"], job_site=NO_REPORT_TIME_SITE)
        payload.pop("report_at", None)

        response = api.create_job_request(
            payload, make_contractor_rep_headers(contractor["id"])
        )

        expect_error(response, ERR_INVALID_REQUEST)

    def test_a_call_for_nobody_is_refused_and_persists_no_request(self, api):
        """
        PRD §3.5: "The headcount is declared as `journeyworkers_requested` and
        `apprentices_requested`, each an integer from 0 through 40, with the additional
        requirement that the two together come to at least 1; a request for nobody is
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/job_request_missing_required_report_at_returns_invalid_request
        """
        contractor = _signatory_contractor(api, INTAKE_CONTRACTOR)
        headers = make_contractor_rep_headers(contractor["id"])
        without_report_at = _intake(contractor["id"], job_site=NO_REPORT_TIME_SITE)
        without_report_at.pop("report_at", None)
        expect_error(api.create_job_request(without_report_at, headers), ERR_INVALID_REQUEST)

        response = api.create_job_request(
            _intake(
                contractor["id"],
                job_site=ZERO_HEADCOUNT_SITE,
                journeyworkers_requested=0,
                apprentices_requested=0,
            ),
            headers,
        )

        expect_error(response, ERR_INVALID_REQUEST)
        rows, meta = validate_list(
            api.list_job_requests(DISPATCHER, {"contractor_id": contractor["id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0


class TestReadsAndListings:
    """One read carries the computed fields; a page carries the whole-set counts."""

    def test_a_member_read_returns_the_stored_inputs_and_the_derived_four(self, api):
        """
        PRD §3.1: "Three member attributes are derived rather than supplied, and one is
        derived from another. `is_traveler` is true exactly when the member's home local
        has `kind` of `SISTER`."

        Design: Corner/entities/member_retrieval_returns_stored_and_computed_fields
        """
        fx.set_clock(api, CLOCK)
        home = fx.add_home_local(api)
        member = expect_created(
            api.create_member(
                f.member_payload(
                    home["id"],
                    full_name=READ_MEMBER_NAME,
                    local_hours_in_trade=READ_MEMBER_HOURS,
                ),
                HALL_ADMIN,
            )
        )

        response = api.get_member(member["id"], HALL_ADMIN)
        read = expect_ok(response)

        assert read["full_name"] == READ_MEMBER_NAME
        assert read["home_local_id"] == home["id"]
        assert read["classification"] == CLASSIFICATION_JOURNEYWORKER
        assert read["local_hours_in_trade"] == READ_MEMBER_HOURS
        assert read["apprentice_period"] is None
        assert read["standing"] == STANDING_GOOD
        assert read["is_traveler"] is False
        assert read["re_registration_eligible_at"] is None
        assert read["refusal_strike_count"] == 0
        assert read["dispatch_eligible"] is True
        assert_single_read_omits_pagination(response)

    def test_the_two_pages_report_the_same_total_over_three_groups(self, api):
        """
        PRD §2.3: "List responses populate four pagination fields inside `meta`:
        `limit` and `offset` echo the effective values used for the page, `total_count`
        reports the number of rows matching the filter before pagination is applied,
        and `has_more` is true when rows remain beyond the current page."

        Design: Corner/entities/out_of_work_list_listing_paginates_with_total_count_and_has_more
        """
        _three_list_groups(api)

        first_rows, first_meta = validate_list(
            api.list_out_of_work_lists(DISPATCHER, {"limit": 2, "offset": 0})
        )
        second_rows, second_meta = validate_list(
            api.list_out_of_work_lists(DISPATCHER, {"limit": 2, "offset": 2})
        )

        assert len(first_rows) == 2
        assert_pagination(first_meta, 2, 0, 3, True)
        assert [row["group_code"] for row in first_rows] == [GROUP_1, GROUP_2]
        assert len(second_rows) == 1
        assert_pagination(second_meta, 2, 2, 3, False)
        assert second_rows[0]["group_code"] == GROUP_4

    def test_the_traveler_filter_narrows_the_total_to_the_matching_group(self, api):
        """
        PRD §3.2: "When list groups are listed they come back in `priority_rank`
        ascending order, optionally filtered by `ordering_policy` and by
        `accepts_travelers`."

        Design: Corner/entities/out_of_work_list_listing_paginates_with_total_count_and_has_more
        """
        groups = _three_list_groups(api)

        rows, meta = validate_list(
            api.list_out_of_work_lists(DISPATCHER, {"accepts_travelers": "true"})
        )

        assert len(rows) == 1
        assert rows[0]["group_code"] == GROUP_4
        assert rows[0]["id"] == groups[GROUP_4]["id"]
        assert_pagination(meta, DEFAULT_LIMIT, MIN_OFFSET, 1, False)

    def test_an_unknown_path_id_answers_with_the_code_for_that_resource(self, api):
        """
        PRD §2.6: "A member id that matches no `Member` yields `ERR_MEMBER_NOT_FOUND`;
        a job request id that matches no `JobRequest` yields
        `ERR_JOB_REQUEST_NOT_FOUND`."

        Design: Corner/entities/member_not_found_returns_member_not_found_404
        """
        fx.set_clock(api, CLOCK)

        member_response = api.get_member(NON_EXISTENT_UUID, HALL_ADMIN)
        registration_response = api.get_registration(NON_EXISTENT_UUID, DISPATCHER)

        member_error = expect_error(member_response, ERR_MEMBER_NOT_FOUND)
        assert isinstance(member_error["message"], str)
        assert member_error["message"].strip() != ""
        assert_error_meta_is_minimal(member_response)
        registration_error = expect_error(
            registration_response, ERR_REGISTRATION_NOT_FOUND
        )
        assert registration_error["error_id"] != ERR_MEMBER_NOT_FOUND


class TestComputedAndSystemFields:
    """Fields no client may supply: the traveler flag, credited hours, the issuer."""

    def test_the_traveler_flag_follows_only_the_home_local_kind(self, api):
        """
        PRD §3.1: "`is_traveler` is true exactly when the member's home local has
        `kind` of `SISTER`."

        Design: Corner/entities/traveler_flag_and_credited_hours_are_computed_not_accepted_as_input
        """
        fx.set_clock(api, CLOCK)
        home = fx.add_home_local(api)
        sister = fx.add_sister_local(api)

        traveler = expect_created(
            api.create_member(
                f.member_payload(
                    sister["id"],
                    full_name=TRAVELER_NAME,
                    local_hours_in_trade=TRAVELER_LOCAL_HOURS,
                ),
                HALL_ADMIN,
            )
        )
        local_member = expect_created(
            api.create_member(
                f.member_payload(
                    home["id"],
                    full_name=LOCAL_NAME,
                    local_hours_in_trade=TRAVELER_LOCAL_HOURS,
                ),
                HALL_ADMIN,
            )
        )

        assert traveler["is_traveler"] is True
        assert local_member["is_traveler"] is False
        assert (
            traveler["local_hours_in_trade"] == local_member["local_hours_in_trade"]
        )

    def test_the_credited_hours_add_one_rounded_credit_to_the_local_hours(self, api):
        """
        PRD §3.3: "The registration's `credited_seniority_hours` — the value the
        `SENIORITY` ordering policy sorts on — is then computed as follows: start from
        the member's `local_hours_in_trade`, which are hours under the home local's own
        agreement and are always credited in full; then walk the declared credits in
        the order they were supplied in the array, and for each one multiply its
        `raw_hours` by that sister local's `reciprocity_factor_bp`, divide by 10,000,
        and round the result half up to a whole hour; finally add those individually
        rounded per-entry results to the base."

        Design: Corner/entities/traveler_flag_and_credited_hours_are_computed_not_accepted_as_input
        """
        fx.set_clock(api, CLOCK)
        fx.add_home_local(api)
        sister = fx.add_sister_local(api)
        group = fx.add_list_group(api, f.group_four_payload())
        traveler = expect_created(
            api.create_member(
                f.member_payload(
                    sister["id"],
                    full_name=TRAVELER_NAME,
                    local_hours_in_trade=TRAVELER_LOCAL_HOURS,
                ),
                HALL_ADMIN,
            )
        )

        registration = expect_created(
            api.create_registration(
                f.traveler_registration_payload(
                    traveler["id"],
                    group["id"],
                    [f.reciprocity_credit(sister["id"], TRAVELER_RAW_HOURS)],
                ),
                make_member_headers(traveler["id"]),
            )
        )

        assert round_half_up_bp(TRAVELER_RAW_HOURS, SISTER_FACTOR_BP) == 500
        assert registration["credited_seniority_hours"] == TRAVELER_CREDITED_HOURS
        assert_instant_equals(registration["registered_at"], CLOCK)
        assert_instant_equals(registration["renewal_due_at"], RENEWAL_DUE_AT)
        assert_instant_equals(registration["renewal_due_at"], plus_days(CLOCK, 30))

    def test_the_referral_records_the_issuing_operator_and_the_logical_clock(self, api):
        """
        PRD §2.1: "When `X-User-Role` is `Dispatcher`, `X-User-ID` is likewise an
        opaque operator identifier not tied to any persisted entity — the server
        records it as `issued_by_user_id` on each `Referral` the dispatcher issues, but
        it does not compare it to any entity's `id`."

        Design: Corner/entities/referral_records_issuing_user_and_issue_instant_as_system_fields
        """
        scene = _one_journeyworker_on_one_call(
            api, ISSUING_CONTRACTOR, ISSUING_JOB_SITE, ISSUED_MEMBER_NAME
        )

        referral = fx.issue_referral(
            api,
            scene["job_request"]["id"],
            headers=OTHER_DISPATCHER,
            slot_kind=SLOT_JOURNEYWORKER,
        )

        assert referral["issued_by_user_id"] == OTHER_DISPATCHER_USER_ID
        assert_instant_equals(referral["issued_at"], CLOCK)
        assert_instant_equals(referral["acceptance_deadline"], plus_hours(CLOCK, 24))
        assert referral["member_id"] == scene["member"]["id"]
        assert referral["registration_id"] == scene["registration"]["id"]
        assert_full_common_fields(referral, 1)
        assert_instant_equals(referral["created_at"], CLOCK)


class TestSkillEndorsementReducedShape:
    """A sighting of a card: two audit columns, one parent, and no mutation path."""

    def test_the_endorsement_carries_neither_updated_at_nor_version(self, api):
        """
        PRD §2.4: "A skill endorsement carries only `id` and `created_at`: it has no
        `updated_at` and no `version`, because an endorsement is a sighting of a
        certification card rather than a mutable object."

        PRD §3.1: "Endorsements are additive: the hall records a new one rather than
        editing an old one, which is why they carry no `version`."

        Design: Corner/entities/skill_endorsement_is_immutable_and_carries_no_version
        """
        fx.set_clock(api, CLOCK)
        home = fx.add_home_local(api)
        member = fx.add_journeyworker(
            api, home["id"], ENDORSED_MEMBER_NAME, CALL_HOURS
        )

        created = expect_created(
            api.create_skill_endorsement(
                member["id"], f.skill_endorsement_payload(), HALL_ADMIN
            )
        )
        read = expect_ok(api.get_skill_endorsement(created["id"], DISPATCHER))
        rows, meta = validate_list(
            api.list_member_skill_endorsements(
                member["id"], DISPATCHER, {"skill_code": SKILL_WELDING_6G}
            )
        )

        assert created["member_id"] == member["id"]
        assert created["skill_code"] == SKILL_WELDING_6G
        assert_instant_equals(created["certified_until"], CERTIFIED_UNTIL)
        assert created["verified"] is True
        assert_reduced_common_fields(created)
        assert_instant_equals(created["created_at"], CLOCK)
        assert read["skill_code"] == SKILL_WELDING_6G
        assert read["verified"] is True
        assert_reduced_common_fields(read)
        assert ids_of(rows) == [created["id"]]
        assert rows[0]["member_id"] == member["id"]
        assert meta["total_count"] == 1

    def test_an_unknown_parent_member_refuses_the_endorsement(self, api):
        """
        PRD §2.6: "Path parameters are resolved strictly left to right, and the first
        segment that fails to resolve determines the error."

        Design: Corner/entities/skill_endorsement_requires_an_existing_member_parent
        """
        fx.set_clock(api, CLOCK)
        home = fx.add_home_local(api)
        first = fx.add_journeyworker(api, home["id"], FIRST_PARENT_NAME, CALL_HOURS)
        second = fx.add_journeyworker(
            api, home["id"], SECOND_PARENT_NAME, SECOND_PARENT_HOURS
        )
        first_endorsement = fx.add_endorsement(
            api, first["id"], skill_code=SKILL_RIGGING
        )
        fx.add_endorsement(api, second["id"], skill_code=SKILL_FIRE_WATCH)

        response = api.create_skill_endorsement(
            NON_EXISTENT_UUID,
            f.skill_endorsement_payload(skill_code=SKILL_RIGGING),
            HALL_ADMIN,
        )

        expect_error(response, ERR_MEMBER_NOT_FOUND)
        rows, meta = validate_list(
            api.list_member_skill_endorsements(first["id"], DISPATCHER)
        )
        assert meta["total_count"] == 1
        assert ids_of(rows) == [first_endorsement["id"]]


class TestGraphPathsToTheMemberAgree:
    """Three routes reach the member from one dispatch, and all three concur."""

    def test_the_dispatch_referral_and_registration_name_the_same_member(self, api):
        """
        PRD §3.8: "It carries the `referral_id` that produced it, the `job_request_id`
        and `member_id` denormalized from that referral, a `start_at` instant, and a
        `status` that begins at `WORKING` and ends in one of three terminal states —
        `LAID_OFF`, `TERMINATED_FOR_CAUSE`, or `QUIT`."

        Design: Corner/entities/referral_member_id_matches_its_registration_member_id_across_graph_paths
        """
        scene = _one_journeyworker_on_one_call(
            api, GRAPH_CONTRACTOR, GRAPH_JOB_SITE, GRAPH_MEMBER_NAME
        )
        referral = fx.issue_referral(
            api, scene["job_request"]["id"], slot_kind=SLOT_JOURNEYWORKER
        )
        dispatch = fx.accept_referral(api, referral["id"], scene["member"]["id"])

        registration = fx.read_registration(api, referral["registration_id"])
        rows, meta = validate_list(
            api.list_dispatches(DISPATCHER, {"member_id": scene["member"]["id"]})
        )

        assert referral["member_id"] == scene["member"]["id"]
        assert registration["member_id"] == scene["member"]["id"]
        assert dispatch["member_id"] == scene["member"]["id"]
        assert referral["registration_id"] == scene["registration"]["id"]
        assert dispatch["referral_id"] == referral["id"]
        assert dispatch["job_request_id"] == scene["job_request"]["id"]
        assert registration["status"] == REGISTRATION_DISPATCHED_OUT
        assert meta["total_count"] == 1
        assert ids_of(rows) == [dispatch["id"]]
        assert rows[0]["member_id"] == scene["member"]["id"]
