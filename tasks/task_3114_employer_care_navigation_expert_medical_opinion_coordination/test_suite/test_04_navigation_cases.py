"""Navigation cases: conditional inputs, routing boundaries, lifecycle, and
discipline gating."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_member_payload, create_navigation_case_payload,
    set_clock, setup_employer, setup_employer_with_member,
    setup_navigation_case, setup_closed_navigation_case,
)
from test_helpers.test_users import (
    make_member_headers,
    make_care_advocate_headers,
    make_nurse_navigator_headers,
)


class TestIntakeConditionalInputs:
    def test_navigation_case_clinical_requires_acuity(
            self, api, platform_admin_headers):
        """PRD §3.1: "Supplying a dependent without a subscriber, or a
        `CLINICAL` intake without `acuity`, or a `COST` intake without
        `estimated_cost_cents`, or a denial without `denial_reason`, are all
        malformed requests rejected with `ERR_INVALID_REQUEST` (400)".

        Design: Corner/entities/navigation_case_clinical_requires_acuity
        """
        set_clock()
        _, member = setup_employer_with_member()
        resp = api.create_navigation_case(
            member["id"], {"question_type": "CLINICAL"},
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST,
                       expected_status=400)


class TestIntakeRouting:
    def test_cost_threshold_boundary_and_child_clinical_routing(
            self, api, platform_admin_headers):
        """PRD §3.3: "Cost questions route to a `NURSE` when the estimated cost
        is at least 500000 cents — exactly five thousand dollars qualifies,
        since the comparison is inclusive — and to an `ADVOCATE` below that."
        PRD §3.3: "Clinical questions route to a `PHYSICIAN` when `acuity` is
        `HIGH`, and otherwise to a `PHYSICIAN` when the member's `relationship`
        is `CHILD` — children always see a physician — and to a `NURSE` for
        everyone else. Benefit questions always route to an `ADVOCATE`."

        Design: Corner/calculations/intake_routing_cost_threshold_boundary_and_child_clinical
        """
        set_clock()
        emp = setup_employer()
        subscriber = validate_success(api.create_member(
            emp["id"], create_member_payload(external_member_ref="AR-1"),
            platform_admin_headers), expected_status=201)
        kid = validate_success(api.create_member(
            emp["id"], create_member_payload(
                full_name="Kit Kid", relationship="CHILD",
                subscriber_id=subscriber["id"], external_member_ref="AR-2"),
            platform_admin_headers), expected_status=201)

        sub_headers = make_member_headers(subscriber["id"])

        cost_eq = validate_success(api.create_navigation_case(
            subscriber["id"],
            create_navigation_case_payload(
                question_type="COST", estimated_cost_cents=500000),
            sub_headers), expected_status=201)
        assert cost_eq["routed_discipline"] == "NURSE"

        cost_lo = validate_success(api.create_navigation_case(
            subscriber["id"],
            create_navigation_case_payload(
                question_type="COST", estimated_cost_cents=499999),
            sub_headers), expected_status=201)
        assert cost_lo["routed_discipline"] == "ADVOCATE"

        clin_self = validate_success(api.create_navigation_case(
            subscriber["id"],
            create_navigation_case_payload(
                question_type="CLINICAL", acuity="MEDIUM"),
            sub_headers), expected_status=201)
        assert clin_self["routed_discipline"] == "NURSE"

        clin_kid = validate_success(api.create_navigation_case(
            kid["id"],
            create_navigation_case_payload(
                question_type="CLINICAL", acuity="MEDIUM"),
            sub_headers), expected_status=201)
        assert clin_kid["routed_discipline"] == "PHYSICIAN"

        clin_high = validate_success(api.create_navigation_case(
            subscriber["id"],
            create_navigation_case_payload(
                question_type="CLINICAL", acuity="HIGH"),
            sub_headers), expected_status=201)
        assert clin_high["routed_discipline"] == "PHYSICIAN"


class TestNavigationLifecycle:
    def test_navigation_case_full_route_start_resolve_close_happy_path(
            self, api):
        """PRD §3.3: "Starting moves the case from `ROUTED` — or from
        `ESCALATED` after an escalation, again discipline-checked against the
        escalated routing — to `IN_PROGRESS` and stamps `assigned_user_id` with
        the caller's `X-User-ID`."
        PRD §3.3: "Only the operator recorded in `assigned_user_id` may resolve
        an in-progress case, moving it to `RESOLVED` (anyone else hears
        `ERR_NOT_ASSIGNED_NAVIGATOR`), and any navigation-discipline role may
        then close it, moving `RESOLVED` to `CLOSED`."

        Design: Corner/state_machines/navigation_case_full_route_start_resolve_close_happy_path
        """
        set_clock()
        _, member = setup_employer_with_member()
        case = setup_navigation_case(
            member, {"question_type": "COST", "estimated_cost_cents": 100000})
        assert case["routed_discipline"] == "ADVOCATE"
        assert case["status"] == "ROUTED"

        adv = make_care_advocate_headers("adv-9")
        started = validate_success(api.start_navigation_case(case["id"], adv))
        assert started["status"] == "IN_PROGRESS"
        assert started["assigned_user_id"] == "adv-9"

        resolved = validate_success(api.resolve_navigation_case(case["id"], adv))
        assert resolved["status"] == "RESOLVED"

        closed = validate_success(api.close_navigation_case(case["id"], adv))
        assert closed["status"] == "CLOSED"

    def test_cost_case_at_threshold_requires_nurse_discipline(self, api):
        """PRD §3.3: "Cost questions route to a `NURSE` when the estimated cost
        is at least 500000 cents — exactly five thousand dollars qualifies,
        since the comparison is inclusive — and to an `ADVOCATE` below that."
        PRD §3.3: "Work begins when a navigator of the matching discipline
        starts the case: a `NURSE` routing wants a `NurseNavigator`, an
        `ADVOCATE` routing a `CareAdvocate`, a `PHYSICIAN` routing a
        `PhysicianAdvisor`; a mismatch is rejected with
        `ERR_DISCIPLINE_MISMATCH`."

        Design: Corner/state_machines/navigation_case_full_route_start_resolve_close_happy_path
        """
        set_clock()
        _, member = setup_employer_with_member()
        case = setup_navigation_case(
            member, {"question_type": "COST", "estimated_cost_cents": 500000})
        assert case["routed_discipline"] == "NURSE"
        assert case["status"] == "ROUTED"

        mismatch = api.start_navigation_case(
            case["id"], make_care_advocate_headers("adv-1"))
        validate_error(mismatch, ApiErrorId.ERR_DISCIPLINE_MISMATCH,
                       expected_status=403)

        nurse = make_nurse_navigator_headers("nn-7")
        started = validate_success(api.start_navigation_case(case["id"], nurse))
        assert started["status"] == "IN_PROGRESS"
        assert started["assigned_user_id"] == "nn-7"

    def test_navigation_case_escalation_reassigns_discipline_advocate_to_nurse(
            self, api):
        """PRD §3.3: "Any navigator working an in-progress case may escalate
        it: the case moves to `ESCALATED`, its `escalation_count` increases by
        one, its `assigned_user_id` is cleared, and its `routed_discipline`
        climbs one level — an `ADVOCATE` case becomes a `NURSE` case, a `NURSE`
        case becomes a `PHYSICIAN` case, and a `PHYSICIAN` case stays a
        `PHYSICIAN` case (the top of the ladder is a no-op)."
        PRD §3.3: "a mismatch is rejected with `ERR_DISCIPLINE_MISMATCH`."

        Design: Corner/state_machines/navigation_case_escalation_reassigns_discipline_advocate_to_nurse
        """
        set_clock()
        _, member = setup_employer_with_member()
        case = setup_navigation_case(
            member, {"question_type": "COST", "estimated_cost_cents": 100000},
            navigator_id="adv-1", navigator_role="CareAdvocate", start=True)

        escalated = validate_success(api.escalate_navigation_case(
            case["id"], make_care_advocate_headers("adv-1")))
        assert escalated["status"] == "ESCALATED"
        assert escalated["routed_discipline"] == "NURSE"
        assert escalated["escalation_count"] == 1
        assert escalated["assigned_user_id"] is None

        wrong = api.start_navigation_case(
            case["id"], make_care_advocate_headers("adv-2"))
        validate_error(wrong, ApiErrorId.ERR_DISCIPLINE_MISMATCH,
                       expected_status=403)

    def test_resolve_by_non_assigned_navigator_rejected(self, api):
        """PRD §3.3: "Only the operator recorded in `assigned_user_id` may
        resolve an in-progress case, moving it to `RESOLVED` (anyone else hears
        `ERR_NOT_ASSIGNED_NAVIGATOR`)".

        Design: Corner/state_machines/resolve_by_non_assigned_navigator_rejected
        """
        set_clock()
        _, member = setup_employer_with_member()
        case = setup_navigation_case(
            member, {"question_type": "BENEFIT"},
            navigator_id="adv-1", navigator_role="CareAdvocate", start=True)

        resp = api.resolve_navigation_case(
            case["id"], make_care_advocate_headers("adv-2"))
        validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_NAVIGATOR,
                       expected_status=403)
        current = validate_success(api.get_navigation_case(
            case["id"], make_care_advocate_headers("adv-2")))
        assert current["status"] == "IN_PROGRESS"

    def test_navigation_case_terminal_close_lockdown(self, api):
        """PRD §2.6: "Sixth, state-machine legality: the target entity must be
        in a valid from-state (else `ERR_INVALID_STATE` or the more specific
        state error the workflow declares)."

        Design: Corner/state_machines/navigation_case_terminal_close_lockdown
        """
        set_clock()
        _, member = setup_employer_with_member()
        case = setup_closed_navigation_case(member, navigator_id="adv-1")
        assert case["status"] == "CLOSED"
        adv = make_care_advocate_headers("adv-1")

        for call in (api.escalate_navigation_case,
                     api.start_navigation_case,
                     api.resolve_navigation_case):
            resp = call(case["id"], adv)
            validate_error(resp, ApiErrorId.ERR_INVALID_STATE,
                           expected_status=409)
