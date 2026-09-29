"""Endpoints read back what they wrote, and action verbs branch on the clock.

Every row in this service is created once and thereafter moved only by named
action endpoints, so a read is the only way to observe a write and the same
action endpoint has to carry every outcome its rule admits.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_id_set,
    assert_instants_equal,
    assert_rate,
)
from test_helpers.constants import (
    ANALYTICS_BASIS_AS_DETERMINED,
    ANALYTICS_BASIS_AS_REPORTED,
    APPEAL_CODE_NEW_EVIDENCE,
    BALLOT_DISPOSITION_NON_PREVENTABLE,
    BALLOT_DISPOSITION_PREVENTABLE,
    CLOCK_EPOCH,
    DECISION_BASIS_UNWEIGHTED_MAJORITY,
    DETERMINATION_NON_PREVENTABLE,
    DETERMINATION_PREVENTABLE,
    DRIVER_STATUS_ACTIVE,
    EVIDENCE_POSTURE_COMPLETE,
    EVIDENCE_SCENE_PHOTO,
    EVIDENCE_TELEMATICS,
    PRESERVATION_PRESERVED,
    REPORTING_STATUS_FILED,
    REPORTING_STATUS_LATE_FILED,
    REPORTING_STATUS_NOT_REQUIRED,
    REPORTING_STATUS_PENDING_FILING,
    REVIEW_STATE_DELIBERATION,
    RISK_TIER_CRITICAL,
    RISK_TIER_ELEVATED,
    RISK_TIER_STANDARD,
    ROUTE_CLASS_LINEHAUL,
    ROUTE_CLASS_LOCAL,
    ROUTE_CLASS_REGIONAL,
    SEVERITY_MINOR,
    SEVERITY_MODERATE,
    STAFFING_POSTURE_OK,
    TENURE_OVER_36_MONTHS,
    TENURE_UNDER_12_MONTHS,
    TOW_REASON_CONVENIENCE,
    TOW_REASON_NONE,
)
from test_helpers.fixtures import (
    AUDITOR,
    SAFETY_ADMIN,
    SAFETY_MANAGER,
    build_case_in_deliberation,
    build_crash,
    build_driver,
    build_statement,
    build_terminal,
    cast_quorum,
    decide_case,
    grant_appeal,
    preserve_evidence,
    request_evidence,
    set_clock,
)

GREENVILLE_MILES = 7.5
HILLSBORO_MILES = 1.25
SHARED_EMPLOYEE_CODE = "D-5701"
OUT_OF_DOMAIN_DRIVER_STATUS = "ON_LEAVE"


def _two_terminals(api: ApiClient) -> dict:
    """Two terminals in different regions, created but never touched again."""
    greenville = build_terminal(
        api,
        name="Greenville Terminal",
        terminal_code="GRE02",
        region_code="OH",
        annual_miles_millions=GREENVILLE_MILES,
    )
    hillsboro = build_terminal(
        api,
        name="Hillsboro Terminal",
        terminal_code="HIL03",
        region_code="IN",
        annual_miles_millions=HILLSBORO_MILES,
    )
    return {"greenville": greenville, "hillsboro": hillsboro}


class TestCreateThenReadThenList:
    """The only verbs are POST and GET, so a read is the sole witness to a write."""

    def test_the_terminal_read_returns_the_created_row_field_for_field(
        self, api: ApiClient
    ):
        """The mileage comes back as a number, and the read never bumps the version.

        PRD: "`annual_miles_millions` — the exposure denominator, expressed in
        millions of miles driven per year, which must be greater than zero and carry
        at most four decimal places ... A freshly registered terminal reports zero
        for every counter and an `OK` `staffing_posture`."

        Design: Corner/endpoints/create_read_list_round_trip_with_no_update_or_delete_verb
        """
        context = _two_terminals(api)
        created = context["greenville"]

        fetched = validate_success(api.get_terminal(created["id"], AUDITOR))

        assert fetched["id"] == created["id"]
        assert fetched["name"] == created["name"] == "Greenville Terminal"
        assert fetched["terminal_code"] == "GRE02"
        assert fetched["region_code"] == "OH"
        assert not isinstance(fetched["annual_miles_millions"], str)
        assert float(fetched["annual_miles_millions"]) == GREENVILLE_MILES
        assert float(created["annual_miles_millions"]) == GREENVILLE_MILES
        assert_instants_equal(fetched["created_at"], created["created_at"], "created_at")
        assert fetched["version"] == created["version"] == 1

        assert fetched["active_driver_count"] == 0
        assert fetched["suspended_driver_count"] == 0
        assert fetched["preventable_crash_count"] == 0
        assert fetched["late_filing_count"] == 0
        assert_rate(
            fetched["crash_rate_per_million_miles"], 0.000, "crash_rate_per_million_miles"
        )
        assert fetched["risk_tier"] == RISK_TIER_STANDARD
        assert fetched["staffing_posture"] == STAFFING_POSTURE_OK

        again = validate_success(api.get_terminal(created["id"], AUDITOR))
        assert again["version"] == created["version"]

    def test_an_employee_code_is_unique_only_within_its_own_terminal(
        self, api: ApiClient
    ):
        """The same code is accepted twice because the two drivers sit apart.

        PRD: "an `employee_code` that must be unique among the drivers of that same
        terminal, so the same payroll code may legitimately appear at two different
        terminals but never twice at one, with a collision refused as
        `ERR_EMPLOYEE_CODE_DUPLICATE`"

        Design: Corner/endpoints/create_read_list_round_trip_with_no_update_or_delete_verb
        """
        context = _two_terminals(api)

        first = validate_success(
            api.create_driver(
                factories.driver_payload(
                    context["greenville"]["id"],
                    employee_code=SHARED_EMPLOYEE_CODE,
                    full_name="Bodil Achterberg",
                    cdl_number="OH-CDL-5701",
                    hire_date="2018-04-16",
                ),
                SAFETY_ADMIN,
            ),
            201,
        )
        assert first["tenure_band"] == TENURE_OVER_36_MONTHS
        assert first["status"] == DRIVER_STATUS_ACTIVE
        assert first["employee_code"] == SHARED_EMPLOYEE_CODE

        second = validate_success(
            api.create_driver(
                factories.driver_payload(
                    context["hillsboro"]["id"],
                    employee_code=SHARED_EMPLOYEE_CODE,
                    full_name="Cato Villanueva",
                    cdl_number="IN-CDL-5702",
                    hire_date="2019-05-17",
                ),
                SAFETY_ADMIN,
            ),
            201,
        )
        assert second["employee_code"] == SHARED_EMPLOYEE_CODE
        assert second["id"] != first["id"]
        assert second["terminal_id"] == context["hillsboro"]["id"]

    def test_every_declared_filter_narrows_and_an_undeclared_value_is_refused(
        self, api: ApiClient
    ):
        """A filter value outside its enum is an error, never an empty page.

        PRD: "Terminals may be listed with `region_code`, `risk_tier` and
        `staffing_posture` filters, and drivers with `terminal_id`, `status`,
        `tenure_band` and `required_action_tier` filters."

        Design: Corner/endpoints/create_read_list_round_trip_with_no_update_or_delete_verb
        """
        context = _two_terminals(api)
        greenville_driver = build_driver(
            api,
            context["greenville"]["id"],
            employee_code=SHARED_EMPLOYEE_CODE,
            full_name="Bodil Achterberg",
            cdl_number="OH-CDL-5701",
            hire_date="2018-04-16",
        )
        hillsboro_driver = build_driver(
            api,
            context["hillsboro"]["id"],
            employee_code=SHARED_EMPLOYEE_CODE,
            full_name="Cato Villanueva",
            cdl_number="IN-CDL-5702",
            hire_date="2019-05-17",
        )

        rows, meta = validate_paginated(
            api.list_drivers(
                AUDITOR,
                {"terminal_id": context["greenville"]["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 1
        assert_id_set(rows, [greenville_driver["id"]])

        active, active_meta = validate_paginated(
            api.list_drivers(
                AUDITOR, {"status": DRIVER_STATUS_ACTIVE, "limit": 10, "offset": 0}
            )
        )
        assert active_meta["total_count"] == 2
        assert_id_set(active, [greenville_driver["id"], hillsboro_driver["id"]])

        validate_error(
            api.list_drivers(AUDITOR, {"status": OUT_OF_DOMAIN_DRIVER_STATUS}),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

        indiana, indiana_meta = validate_paginated(
            api.list_terminals(AUDITOR, {"region_code": "IN", "limit": 10, "offset": 0})
        )
        assert indiana_meta["total_count"] == 1
        assert indiana_meta["has_more"] is False
        assert indiana_meta["limit"] == 10
        assert indiana_meta["offset"] == 0
        assert_id_set(indiana, [context["hillsboro"]["id"]])


IRONTON_MILES = 3.0
IRONTON_DUE_R = "2026-08-03T06:00:00Z"
IRONTON_DUE_L = "2026-08-02T06:00:00Z"
ONE_SECOND_PAST_IRONTON_DUE_L = "2026-08-02T06:00:01Z"
IRONTON_REFERENCE_R = "FMCSA-2026-IRN03-0001"
IRONTON_REFERENCE_N = "FMCSA-2026-IRN03-0002"
IRONTON_REFERENCE_L = "FMCSA-2026-IRN03-0003"


def _ironton_three_crashes(api: ApiClient) -> dict:
    """Two recordable crashes with different due instants, plus one that is not.

    Crash R was reported on 2026-07-31T06:00:00Z and crash L a day earlier, so
    their 72-hour windows close a day apart; crash N was towed for convenience
    and therefore fires no recordability trigger at all.
    """
    terminal = build_terminal(
        api,
        name="Ironton Terminal",
        terminal_code="IRN03",
        region_code="OH",
        annual_miles_millions=IRONTON_MILES,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-5801",
        full_name="Dario Selvaggio",
        cdl_number="OH-CDL-5801",
        hire_date="2013-03-13",
    )
    crash_r = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-31T06:00:00Z",
        notified_at="2026-07-31T06:30:00Z",
        location_text="US-52 at Center St",
        severity=SEVERITY_MODERATE,
        route_class=ROUTE_CLASS_REGIONAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
        injury_transported_count=1,
    )
    crash_l = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-30T06:00:00Z",
        notified_at="2026-07-30T06:30:00Z",
        location_text="SR-93 at the tunnel",
        severity=SEVERITY_MODERATE,
        route_class=ROUTE_CLASS_REGIONAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
        injury_transported_count=1,
    )
    crash_n = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-31T09:00:00Z",
        notified_at="2026-07-31T09:05:00Z",
        location_text="Yard row C",
        severity=SEVERITY_MINOR,
        route_class=ROUTE_CLASS_LOCAL,
        tow_away=True,
        tow_reason=TOW_REASON_CONVENIENCE,
    )
    return {
        "terminal": terminal,
        "driver": driver,
        "crash_r": crash_r,
        "crash_l": crash_l,
        "crash_n": crash_n,
    }


class TestRegulatoryReportActionBranchesOnTheClock:
    """One filing endpoint carries three outcomes: on time, late, and refused."""

    def test_a_filing_inside_the_window_records_the_reference_and_the_clock(
        self, api: ApiClient
    ):
        """The stamp is the logical instant of the request, not the crash time.

        PRD: "Either way the supplied `filing_reference` is recorded and `filed_at`
        is set to the current logical instant."

        Design: Corner/endpoints/regulatory_report_action_files_late_or_refuses_outright
        """
        context = _ironton_three_crashes(api)
        assert context["terminal"]["late_filing_count"] == 0

        crash_r = context["crash_r"]
        assert crash_r["dot_recordable"] is True
        assert crash_r["reporting_status"] == REPORTING_STATUS_PENDING_FILING
        assert crash_r["filed_at"] is None
        assert crash_r["filing_reference"] is None
        assert_instants_equal(crash_r["report_due_at"], IRONTON_DUE_R, "report_due_at")
        assert_instants_equal(
            context["crash_l"]["report_due_at"], IRONTON_DUE_L, "report_due_at"
        )

        filed = validate_success(
            api.file_regulatory_report(
                crash_r["id"],
                factories.regulatory_report_payload(
                    filing_reference=IRONTON_REFERENCE_R
                ),
                SAFETY_MANAGER,
            )
        )

        assert filed["reporting_status"] == REPORTING_STATUS_FILED
        assert filed["filing_reference"] == IRONTON_REFERENCE_R
        assert_instants_equal(filed["filed_at"], CLOCK_EPOCH, "filed_at")
        assert_instants_equal(filed["report_due_at"], IRONTON_DUE_R, "report_due_at")
        assert filed["version"] == crash_r["version"] + 1

        terminal = validate_success(
            api.get_terminal(context["terminal"]["id"], SAFETY_ADMIN)
        )
        assert terminal["late_filing_count"] == 0

    def test_a_crash_with_nothing_to_report_and_one_already_filed_are_both_refused(
        self, api: ApiClient
    ):
        """A convenience tow is not a trigger, and a refusal overwrites nothing.

        PRD: "It is legal only on a crash that is recordable and whose
        `reporting_status` is still `PENDING_FILING`; a non-recordable crash, or one
        already filed, is refused with `ERR_CRASH_STATE_INVALID`."

        Design: Corner/endpoints/regulatory_report_action_files_late_or_refuses_outright
        """
        context = _ironton_three_crashes(api)
        crash_n = context["crash_n"]
        assert crash_n["dot_recordable"] is False
        assert crash_n["recordability_codes"] == []
        assert crash_n["reporting_status"] == REPORTING_STATUS_NOT_REQUIRED
        assert crash_n["report_due_at"] is None

        validate_error(
            api.file_regulatory_report(
                crash_n["id"],
                factories.regulatory_report_payload(
                    filing_reference=IRONTON_REFERENCE_N
                ),
                SAFETY_MANAGER,
            ),
            ApiErrorId.CRASH_STATE_INVALID.value,
            409,
        )

        filed = validate_success(
            api.file_regulatory_report(
                context["crash_r"]["id"],
                factories.regulatory_report_payload(
                    filing_reference=IRONTON_REFERENCE_R
                ),
                SAFETY_MANAGER,
            )
        )
        validate_error(
            api.file_regulatory_report(
                context["crash_r"]["id"],
                factories.regulatory_report_payload(
                    filing_reference="FMCSA-2026-IRN03-0001-DUP"
                ),
                SAFETY_MANAGER,
            ),
            ApiErrorId.CRASH_STATE_INVALID.value,
            409,
        )

        untouched = validate_success(
            api.get_crash(context["crash_r"]["id"], SAFETY_MANAGER)
        )
        assert untouched["filing_reference"] == IRONTON_REFERENCE_R
        assert untouched["reporting_status"] == REPORTING_STATUS_FILED
        assert untouched["version"] == filed["version"]

        unmoved = validate_success(api.get_crash(crash_n["id"], SAFETY_MANAGER))
        assert unmoved["reporting_status"] == REPORTING_STATUS_NOT_REQUIRED
        assert unmoved["filing_reference"] is None
        assert unmoved["version"] == crash_n["version"]

    def test_one_second_past_the_due_instant_takes_the_late_branch(
        self, api: ApiClient
    ):
        """Only the late branch touches the terminal's late-filing counter.

        PRD: "Filing at or before the exact due instant moves `reporting_status`
        from `PENDING_FILING` to `FILED`; filing after it moves `PENDING_FILING` to
        `LATE_FILED`. ... The late branch carries one extra consequence: the
        terminal frozen on the crash reports a `late_filing_count` one higher on its
        next read."

        Design: Corner/endpoints/regulatory_report_action_files_late_or_refuses_outright
        """
        context = _ironton_three_crashes(api)
        validate_success(
            api.file_regulatory_report(
                context["crash_r"]["id"],
                factories.regulatory_report_payload(
                    filing_reference=IRONTON_REFERENCE_R
                ),
                SAFETY_MANAGER,
            )
        )

        set_clock(api, ONE_SECOND_PAST_IRONTON_DUE_L)
        late = validate_success(
            api.file_regulatory_report(
                context["crash_l"]["id"],
                factories.regulatory_report_payload(
                    filing_reference=IRONTON_REFERENCE_L
                ),
                SAFETY_MANAGER,
            )
        )

        assert late["reporting_status"] == REPORTING_STATUS_LATE_FILED
        assert late["filing_reference"] == IRONTON_REFERENCE_L
        assert_instants_equal(
            late["filed_at"], ONE_SECOND_PAST_IRONTON_DUE_L, "filed_at"
        )

        terminal = validate_success(
            api.get_terminal(context["terminal"]["id"], SAFETY_ADMIN)
        )
        assert terminal["late_filing_count"] == 1

        rows, meta = validate_paginated(
            api.list_crashes(
                AUDITOR,
                {
                    "terminal_id": context["terminal"]["id"],
                    "reporting_status": REPORTING_STATUS_LATE_FILED,
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert meta["total_count"] == 1
        assert_id_set(rows, [context["crash_l"]["id"]])


JACKSON_CENTER_MILES = 2.0
CITED_DEVICE_ID = "ECM-5901"
CITED_COPY_URI = "s3://evidence/2923jax/ecm-5901.json"
CITED_HASH = "0d0d1e1e2f2f3a3a4b4b5c5c6d6d7e7e"
UNCITED_DEVICE_ID = "PHONE-5901"
UNCITED_COPY_URI = "s3://evidence/2923jax/scene-5901.jpg"
UNCITED_HASH = "1e1e2f2f3a3a4b4b5c5c6d6d7e7e8f8f"
NEW_EVIDENCE_GROUNDS = "the preserved ECM snapshot shows the tractor was stationary"


def _decided_case_and_two_preserved_items(api: ApiClient) -> dict:
    """A case decided non-preventable, with one citable item and one decoy.

    The citable telematics snapshot belongs to the case's own crash and brackets
    its `occurred_at`; the scene photo belongs to a second crash on the same
    driver and is never referenced by any appeal.
    """
    terminal = build_terminal(
        api,
        name="Jackson Center Terminal",
        terminal_code="JAX03",
        region_code="OH",
        annual_miles_millions=JACKSON_CENTER_MILES,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-5901",
        full_name="Eero Tshabalala",
        cdl_number="OH-CDL-5901",
        hire_date="2012-12-01",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-29T15:00:00Z",
        notified_at="2026-07-29T15:10:00Z",
        location_text="SR-274 at the co-op",
        severity=SEVERITY_MINOR,
        route_class=ROUTE_CLASS_LOCAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
    )
    requested_cited = request_evidence(
        api,
        crash["id"],
        kind=EVIDENCE_TELEMATICS,
        source_device_id=CITED_DEVICE_ID,
        window_start_at="2026-07-29T14:00:00Z",
        window_end_at="2026-07-29T16:00:00Z",
        retention_deadline_at="2027-06-30T00:00:00Z",
    )
    cited = preserve_evidence(
        api,
        requested_cited["id"],
        preserved_copy_uri=CITED_COPY_URI,
        evidence_hash=CITED_HASH,
    )

    other_crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-29T19:00:00Z",
        notified_at="2026-07-29T19:10:00Z",
        location_text="SR-119 at the grain bins",
        severity=SEVERITY_MINOR,
        route_class=ROUTE_CLASS_LOCAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
    )
    requested_uncited = request_evidence(
        api,
        other_crash["id"],
        kind=EVIDENCE_SCENE_PHOTO,
        source_device_id=UNCITED_DEVICE_ID,
        window_start_at="2026-07-29T18:00:00Z",
        window_end_at="2026-07-29T20:00:00Z",
        retention_deadline_at="2027-06-30T00:00:00Z",
    )
    uncited = preserve_evidence(
        api,
        requested_uncited["id"],
        preserved_copy_uri=UNCITED_COPY_URI,
        evidence_hash=UNCITED_HASH,
    )

    build_statement(
        api,
        crash["id"],
        driver["id"],
        narrative="The gate swung into my mirror.",
        conditions_note=None,
    )
    opened = build_case_in_deliberation(
        api, crash["id"], committee_name="Jackson Center Safety Review Committee"
    )
    cast_quorum(
        api,
        opened,
        vote=BALLOT_DISPOSITION_NON_PREVENTABLE,
        scores=factories.uniform_criterion_scores(1),
    )
    decided = decide_case(api, opened["id"])
    return {
        "terminal": terminal,
        "driver": driver,
        "crash": crash,
        "other_crash": other_crash,
        "cited": cited,
        "uncited": uncited,
        "review_case": decided,
    }


class TestAppealEvidenceLinkIsWrittenOnceAndQueryableBothWays:
    """The pointer lives on the review case and is discoverable from the item."""

    def test_the_grant_writes_the_citation_onto_the_review_case(self, api: ApiClient):
        """The link is null until the appeal, then names the cited item.

        PRD: "An accepted appeal moves the case `DECIDED → DELIBERATION`, increases
        `appeal_round` by 1, records `appeal_grounds`, `appeal_grounds_code` and —
        where cited — `appeal_evidence_item_id`"

        Design: Corner/endpoints/appeal_evidence_link_is_stored_and_reverse_reachable
        """
        context = _decided_case_and_two_preserved_items(api)
        decided = context["review_case"]
        assert decided["determination"] == DETERMINATION_NON_PREVENTABLE
        assert decided["decision_basis"] == DECISION_BASIS_UNWEIGHTED_MAJORITY
        assert decided["appeal_evidence_item_id"] is None
        assert decided["appeal_grounds"] is None
        assert decided["appeal_grounds_code"] is None

        crash = validate_success(api.get_crash(context["crash"]["id"], SAFETY_MANAGER))
        assert crash["evidence_posture"] == EVIDENCE_POSTURE_COMPLETE

        appealed = grant_appeal(
            api,
            decided["id"],
            appeal_grounds=NEW_EVIDENCE_GROUNDS,
            appeal_grounds_code=APPEAL_CODE_NEW_EVIDENCE,
            appeal_evidence_item_id=context["cited"]["id"],
        )

        assert appealed["appeal_evidence_item_id"] == context["cited"]["id"]
        assert appealed["appeal_grounds_code"] == APPEAL_CODE_NEW_EVIDENCE
        assert appealed["appeal_grounds"] == NEW_EVIDENCE_GROUNDS
        assert appealed["status"] == REVIEW_STATE_DELIBERATION
        assert appealed["appeal_round"] == 1

    def test_the_case_is_reachable_from_the_cited_item_and_not_from_the_other(
        self, api: ApiClient
    ):
        """The evidence filter finds the association from the evidence side.

        PRD: "Review cases may be listed with `crash_id`, `appeal_evidence_item_id`,
        `status` and `determination` filters."

        Design: Corner/endpoints/appeal_evidence_link_is_stored_and_reverse_reachable
        """
        context = _decided_case_and_two_preserved_items(api)
        case_id = context["review_case"]["id"]
        grant_appeal(
            api,
            case_id,
            appeal_grounds=NEW_EVIDENCE_GROUNDS,
            appeal_grounds_code=APPEAL_CODE_NEW_EVIDENCE,
            appeal_evidence_item_id=context["cited"]["id"],
        )

        by_cited, cited_meta = validate_paginated(
            api.list_review_cases(
                AUDITOR,
                {
                    "appeal_evidence_item_id": context["cited"]["id"],
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert cited_meta["total_count"] == 1
        assert cited_meta["has_more"] is False
        assert_id_set(by_cited, [case_id])

        by_uncited, uncited_meta = validate_paginated(
            api.list_review_cases(
                AUDITOR,
                {
                    "appeal_evidence_item_id": context["uncited"]["id"],
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert uncited_meta["total_count"] == 0
        assert by_uncited == []

    def test_the_cited_item_itself_is_left_exactly_as_it_was(self, api: ApiClient):
        """Citing an item in an appeal writes nothing to the item.

        PRD: "a `NEW_EVIDENCE` appeal must cite `appeal_evidence_item_id`; that item
        must resolve or the response is `ERR_EVIDENCE_ITEM_NOT_FOUND`, and it must
        belong to the case's own crash and be in `PRESERVED` state or the response is
        `ERR_APPEAL_EVIDENCE_INVALID`."

        Design: Corner/endpoints/appeal_evidence_link_is_stored_and_reverse_reachable
        """
        context = _decided_case_and_two_preserved_items(api)
        cited = context["cited"]
        assert cited["preservation_state"] == PRESERVATION_PRESERVED

        grant_appeal(
            api,
            context["review_case"]["id"],
            appeal_grounds=NEW_EVIDENCE_GROUNDS,
            appeal_grounds_code=APPEAL_CODE_NEW_EVIDENCE,
            appeal_evidence_item_id=cited["id"],
        )

        after = validate_success(api.get_evidence_item(cited["id"], AUDITOR))
        assert after["preservation_state"] == PRESERVATION_PRESERVED
        assert after["version"] == cited["version"]
        assert after["crash_id"] == context["crash"]["id"]
        assert after["preserved_copy_uri"] == CITED_COPY_URI
        assert after["evidence_hash"] == CITED_HASH


KENTON_MILES = 1.0
KENTON_WINDOW_START = "2025-08-01T00:00:00Z"
KENTON_WINDOW_END = CLOCK_EPOCH
DETERMINED_RATE = 2.000
REPORTED_RATE = 3.000
LINEHAUL_ONLY_RATE = 1.000


def _three_crashes_two_decided_preventable(api: ApiClient) -> dict:
    """Three MINOR crashes on one 1.0-million-mile terminal, two of them decided.

    Crash X1 belongs to the recently hired driver and crash X3 to the veteran,
    and both are found preventable; crash X2 stays at `REPORTED`, so the two
    counting bases disagree by exactly one crash.
    """
    terminal = build_terminal(
        api,
        name="Kenton Terminal",
        terminal_code="KEN03",
        region_code="OH",
        annual_miles_millions=KENTON_MILES,
    )
    driver_g = build_driver(
        api,
        terminal["id"],
        employee_code="D-6001",
        full_name="Fionn Okereke",
        cdl_number="OH-CDL-6001",
        hire_date="2026-06-01",
    )
    driver_v = build_driver(
        api,
        terminal["id"],
        employee_code="D-6002",
        full_name="Greta Solomos",
        cdl_number="OH-CDL-6002",
        hire_date="2011-01-03",
    )

    crash_x1 = build_crash(
        api,
        driver_g["id"],
        terminal["id"],
        occurred_at="2026-07-20T08:00:00Z",
        notified_at="2026-07-20T08:20:00Z",
        location_text="I-75 MM 111",
        severity=SEVERITY_MINOR,
        route_class=ROUTE_CLASS_LINEHAUL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
    )
    requested_x1 = request_evidence(
        api,
        crash_x1["id"],
        kind=EVIDENCE_TELEMATICS,
        source_device_id="ECM-6001",
        window_start_at="2026-07-20T07:00:00Z",
        window_end_at="2026-07-20T09:00:00Z",
        retention_deadline_at="2027-06-30T00:00:00Z",
    )
    preserve_evidence(
        api,
        requested_x1["id"],
        preserved_copy_uri="s3://evidence/2923ken/ecm-6001.json",
        evidence_hash="2f2f3a3a4b4b5c5c6d6d7e7e8f8f9a9a",
    )
    build_statement(
        api,
        crash_x1["id"],
        driver_g["id"],
        narrative="Traffic braked at the construction taper.",
        conditions_note=None,
    )
    opened_x1 = build_case_in_deliberation(
        api, crash_x1["id"], committee_name="Kenton Safety Review Committee"
    )
    cast_quorum(
        api,
        opened_x1,
        vote=BALLOT_DISPOSITION_PREVENTABLE,
        scores=factories.uniform_criterion_scores(3),
    )
    decided_x1 = decide_case(api, opened_x1["id"])

    crash_x2 = build_crash(
        api,
        driver_g["id"],
        terminal["id"],
        occurred_at="2026-07-22T13:00:00Z",
        notified_at="2026-07-22T13:10:00Z",
        location_text="Kenton dock apron",
        severity=SEVERITY_MINOR,
        route_class=ROUTE_CLASS_LOCAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
    )

    crash_x3 = build_crash(
        api,
        driver_v["id"],
        terminal["id"],
        occurred_at="2026-07-24T17:00:00Z",
        notified_at="2026-07-24T17:15:00Z",
        location_text="SR-309 at the fairground gate",
        severity=SEVERITY_MINOR,
        route_class=ROUTE_CLASS_REGIONAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
    )
    requested_x3 = request_evidence(
        api,
        crash_x3["id"],
        kind=EVIDENCE_TELEMATICS,
        source_device_id="ECM-6002",
        window_start_at="2026-07-24T16:00:00Z",
        window_end_at="2026-07-24T18:00:00Z",
        retention_deadline_at="2027-06-30T00:00:00Z",
    )
    preserve_evidence(
        api,
        requested_x3["id"],
        preserved_copy_uri="s3://evidence/2923ken/ecm-6002.json",
        evidence_hash="3a3a4b4b5c5c6d6d7e7e8f8f9a9a0b0b",
    )
    build_statement(
        api,
        crash_x3["id"],
        driver_v["id"],
        narrative="I clipped the gate post backing in.",
        conditions_note=None,
    )
    opened_x3 = build_case_in_deliberation(
        api, crash_x3["id"], committee_name="Kenton Safety Review Committee"
    )
    cast_quorum(
        api,
        opened_x3,
        vote=BALLOT_DISPOSITION_PREVENTABLE,
        scores=factories.uniform_criterion_scores(3),
    )
    decided_x3 = decide_case(api, opened_x3["id"])

    return {
        "terminal": terminal,
        "driver_g": driver_g,
        "driver_v": driver_v,
        "crash_x1": crash_x1,
        "crash_x2": crash_x2,
        "crash_x3": crash_x3,
        "decided_x1": decided_x1,
        "decided_x3": decided_x3,
    }


class TestCrashAnalyticsRecomputesPerBasisAndPerFilter:
    """The same three crashes report a different rate for every question asked."""

    def test_the_unparameterised_read_defaults_to_the_determined_basis(
        self, api: ApiClient
    ):
        """The trailing year is half-open and the basis need not be supplied.

        PRD: "The `basis` query parameter selects what is counted and defaults to
        `AS_DETERMINED`. Under `AS_DETERMINED` only crashes whose
        `preventability_status` is `PREVENTABLE` are counted, so a crash awaiting
        determination or found non-preventable contributes nothing."

        Design: Corner/endpoints/crash_analytics_read_recomputes_every_basis_and_breakdown
        """
        context = _three_crashes_two_decided_preventable(api)
        assert context["driver_g"]["tenure_band"] == TENURE_UNDER_12_MONTHS
        assert context["driver_v"]["tenure_band"] == TENURE_OVER_36_MONTHS
        assert context["decided_x1"]["determination"] == DETERMINATION_PREVENTABLE
        assert context["decided_x3"]["determination"] == DETERMINATION_PREVENTABLE

        analytics = validate_success(
            api.get_crash_analytics(context["terminal"]["id"], AUDITOR)
        )

        assert analytics["terminal_id"] == context["terminal"]["id"]
        assert analytics["basis"] == ANALYTICS_BASIS_AS_DETERMINED
        assert_instants_equal(
            analytics["window_start_at"], KENTON_WINDOW_START, "window_start_at"
        )
        assert_instants_equal(
            analytics["window_end_at"], KENTON_WINDOW_END, "window_end_at"
        )
        assert analytics["crash_count"] == 3
        assert analytics["preventable_crash_count"] == 2
        assert_rate(
            analytics["crash_rate_per_million_miles"],
            DETERMINED_RATE,
            "crash_rate_per_million_miles",
        )
        assert analytics["risk_tier"] == RISK_TIER_ELEVATED

    def test_the_terminal_row_reports_only_the_determined_answer(self, api: ApiClient):
        """The stored fields and the unparameterised read agree exactly.

        PRD: "The `preventable_crash_count`, `crash_rate_per_million_miles` and
        `risk_tier` fields stored on the terminal itself always reflect the
        `AS_DETERMINED` basis with no route or tenure narrowing, so a terminal read
        and an unparameterised analytics read agree exactly."

        Design: Corner/endpoints/crash_analytics_read_recomputes_every_basis_and_breakdown
        """
        context = _three_crashes_two_decided_preventable(api)
        terminal_id = context["terminal"]["id"]

        reported = validate_success(
            api.get_crash_analytics(
                terminal_id, AUDITOR, {"basis": ANALYTICS_BASIS_AS_REPORTED}
            )
        )
        assert reported["basis"] == ANALYTICS_BASIS_AS_REPORTED
        assert reported["preventable_crash_count"] == 3
        assert_rate(
            reported["crash_rate_per_million_miles"],
            REPORTED_RATE,
            "crash_rate_per_million_miles",
        )
        assert reported["risk_tier"] == RISK_TIER_CRITICAL

        terminal = validate_success(api.get_terminal(terminal_id, AUDITOR))
        assert terminal["preventable_crash_count"] == 2
        assert_rate(
            terminal["crash_rate_per_million_miles"],
            DETERMINED_RATE,
            "crash_rate_per_million_miles",
        )
        assert terminal["risk_tier"] == RISK_TIER_ELEVATED

    def test_a_narrowing_filter_lowers_the_numerator_and_leaves_the_mileage_whole(
        self, api: ApiClient
    ):
        """Filtering produces the subset's own rate, not a share of the whole.

        PRD: "The optional `route_class` and `tenure_band` parameters narrow the
        counted crash set before the rate is computed, not afterwards, so filtering
        to one route class produces that subset's own rate rather than a share of the
        whole terminal's rate."

        Design: Corner/endpoints/crash_analytics_read_recomputes_every_basis_and_breakdown
        """
        context = _three_crashes_two_decided_preventable(api)
        terminal_id = context["terminal"]["id"]

        linehaul = validate_success(
            api.get_crash_analytics(
                terminal_id,
                AUDITOR,
                {
                    "basis": ANALYTICS_BASIS_AS_DETERMINED,
                    "route_class": ROUTE_CLASS_LINEHAUL,
                },
            )
        )
        assert linehaul["preventable_crash_count"] == 1
        assert_rate(
            linehaul["crash_rate_per_million_miles"],
            LINEHAUL_ONLY_RATE,
            "crash_rate_per_million_miles",
        )
        assert linehaul["risk_tier"] == RISK_TIER_STANDARD

        rookie = validate_success(
            api.get_crash_analytics(
                terminal_id,
                AUDITOR,
                {
                    "basis": ANALYTICS_BASIS_AS_REPORTED,
                    "tenure_band": TENURE_UNDER_12_MONTHS,
                },
            )
        )
        assert rookie["preventable_crash_count"] == 2
        assert_rate(
            rookie["crash_rate_per_million_miles"],
            DETERMINED_RATE,
            "crash_rate_per_million_miles",
        )
        assert rookie["risk_tier"] == RISK_TIER_ELEVATED

    def test_each_breakdown_names_exactly_the_values_present_in_the_window(
        self, api: ApiClient
    ):
        """One entry per value that actually occurs, counted independently.

        PRD: "Each entry of `by_route_class` names one `route_class` value present in
        the window together with that subset's `crash_count`,
        `preventable_crash_count` and `crash_rate_per_million_miles`; each entry of
        `by_tenure_band` does the same for one `tenure_band` value, with the band
        taken from the involved driver's tenure as re-derived at read time."

        Design: Corner/endpoints/crash_analytics_read_recomputes_every_basis_and_breakdown
        """
        context = _three_crashes_two_decided_preventable(api)
        analytics = validate_success(
            api.get_crash_analytics(context["terminal"]["id"], AUDITOR)
        )

        by_route = {row["route_class"]: row for row in analytics["by_route_class"]}
        assert set(by_route) == {
            ROUTE_CLASS_LINEHAUL,
            ROUTE_CLASS_REGIONAL,
            ROUTE_CLASS_LOCAL,
        }
        assert by_route[ROUTE_CLASS_LINEHAUL]["crash_count"] == 1
        assert by_route[ROUTE_CLASS_LINEHAUL]["preventable_crash_count"] == 1
        assert by_route[ROUTE_CLASS_REGIONAL]["crash_count"] == 1
        assert by_route[ROUTE_CLASS_REGIONAL]["preventable_crash_count"] == 1
        assert by_route[ROUTE_CLASS_LOCAL]["crash_count"] == 1
        assert by_route[ROUTE_CLASS_LOCAL]["preventable_crash_count"] == 0

        by_tenure = {row["tenure_band"]: row for row in analytics["by_tenure_band"]}
        assert set(by_tenure) == {TENURE_UNDER_12_MONTHS, TENURE_OVER_36_MONTHS}
        assert by_tenure[TENURE_UNDER_12_MONTHS]["crash_count"] == 2
        assert by_tenure[TENURE_UNDER_12_MONTHS]["preventable_crash_count"] == 1
        assert by_tenure[TENURE_OVER_36_MONTHS]["crash_count"] == 1
        assert by_tenure[TENURE_OVER_36_MONTHS]["preventable_crash_count"] == 1
