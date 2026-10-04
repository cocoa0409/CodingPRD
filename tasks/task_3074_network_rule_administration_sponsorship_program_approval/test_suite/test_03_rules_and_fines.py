"""Network rule publication, regional variation, and violation fine tests."""
from test_helpers import (
    ApiErrorId,
    assess_violation,
    cite_violation,
    create_active_member,
    create_published_rule,
    create_rule_payload,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS, make_member_headers, make_rules_admin_headers

OP = TEST_USERS["network_operator_headers"]
RA1 = TEST_USERS["rules_admin_headers"]
RA2 = TEST_USERS["rules_admin_2_headers"]
PA = TEST_USERS["pricing_analyst_headers"]

GLOBAL_SCHEDULE = [
    {"min_amount_minor": 1, "max_amount_minor": 9999, "fine_cents": 1000},
    {"min_amount_minor": 10000, "max_amount_minor": 99999, "fine_cents": 10000},
    {"min_amount_minor": 100000, "max_amount_minor": None, "fine_cents": 50000},
]
EU_SCHEDULE = [
    {"min_amount_minor": 1, "max_amount_minor": 99999, "fine_cents": 5000},
    {"min_amount_minor": 100000, "max_amount_minor": None, "fine_cents": 20000},
]


def _setup_regional_pair(api):
    """EU member + GLOBAL base rule + EU regional override, both published
    and effective at the default logical clock. Returns (member, global_rule,
    eu_rule)."""
    member = create_active_member(legal_name="EU Bank", member_kind="BOTH",
                                  region="EU")
    global_rule = get_success_data(api.create_rule(create_rule_payload(
        "R-AML-1", title="AML reporting", body="base",
        fine_schedule=GLOBAL_SCHEDULE), RA1))
    get_success_data(api.publish_rule(global_rule["id"], RA1))
    eu_rule = get_success_data(api.create_rule(create_rule_payload(
        "R-AML-1-EU", title="AML reporting EU", body="eu variation",
        region_scope="EU", regional_override_of_rule_id=global_rule["id"],
        fine_schedule=EU_SCHEDULE), RA1))
    get_success_data(api.publish_rule(eu_rule["id"], RA1))
    return member, global_rule, eu_rule


class TestFineAssessment:
    def test_fine_assessed_against_global_base_rule(self, api):
        """PRD §3.5: "First, tier selection: the rule's `fine_schedule` is
        consulted in ascending `min_amount_minor` order, and the selected tier
        is the last entry whose `min_amount_minor` is at or below the
        violation's `transaction_amount_minor` and whose `max_amount_minor` is
        either null or at or above it; that tier's `fine_cents` is the base
        fine."
        PRD §3.5: "Second, a severity multiplier is applied after tier
        selection: `MINOR` multiplies by one, `MAJOR` by two, and `CRITICAL`
        by three."

        Design: Difficulty/dual_variant_calc/fine_regional_override_vs_global_base
        """
        _, global_rule, _ = _setup_regional_pair(api)
        # The EU override applies to EU members; cite against an NA member so
        # the GLOBAL rule's own schedule governs (no regional override whose
        # region_scope matches the subject's home region exists for NA).
        member = create_active_member(legal_name="NA Bank", member_kind="BOTH",
                                      region="NA")
        violation = cite_violation(global_rule["id"], member["id"],
                                   severity="MINOR",
                                   transaction_amount_minor=150000)
        assessed = assess_violation(violation["id"], assessor_id="ra-2")
        assert assessed["status"] == "ASSESSED"
        assert assessed["fine_cents"] == 50000, \
            "150000 falls in the 100000+ tier of the GLOBAL schedule: 50000 x MINOR(1)"

    def test_fine_assessed_against_regional_override(self, api):
        """PRD §3.5: "When a published regional rule exists whose
        `regional_override_of_rule_id` is the cited `GLOBAL` rule, whose
        `region_scope` matches the subject member's home region, and which is
        effective at assessment time, the `fine_schedule` is taken from the
        regional override rather than the global base rule."

        Design: Difficulty/dual_variant_calc/fine_regional_override_vs_global_base
        """
        member, _, eu_rule = _setup_regional_pair(api)
        violation = cite_violation(eu_rule["id"], member["id"],
                                   severity="MINOR",
                                   transaction_amount_minor=150000)
        assessed = assess_violation(violation["id"], assessor_id="ra-2")
        assert assessed["status"] == "ASSESSED"
        assert assessed["fine_cents"] == 20000, \
            "the EU override's 100000+ tier yields 20000 for identical inputs"

    def test_fine_severity_multiplier_stacks_on_tier(self, api):
        """PRD §3.5: "Second, a severity multiplier is applied after tier
        selection: `MINOR` multiplies by one, `MAJOR` by two, and `CRITICAL`
        by three. The result — an integer number of cents with no rounding —
        is stored in the violation's `fine_cents`, which is null until
        assessment."

        Design: Corner/calculations/fine_severity_multiplier_stacks_on_tier
        """
        member = create_active_member(region="NA")
        rule = create_published_rule(
            "R-T1",
            fine_schedule=[
                {"min_amount_minor": 1, "max_amount_minor": 9999,
                 "fine_cents": 1000},
                {"min_amount_minor": 10000, "max_amount_minor": None,
                 "fine_cents": 9000},
            ])
        violation = cite_violation(rule["id"], member["id"],
                                   severity="CRITICAL",
                                   transaction_amount_minor=5000)
        assessed = assess_violation(violation["id"], assessor_id="ra-2")
        assert assessed["fine_cents"] == 3000, \
            "tier-1 fine 1000 x CRITICAL multiplier 3 = 3000 (no tier re-lookup)"

    def test_cite_violation_on_non_effective_rule_rejected(self, api):
        """PRD §3.5: "The cited rule must be `PUBLISHED` and already effective
        — its `effective_from` at or before the current logical time —
        otherwise the citation is rejected with `ERR_RULE_NOT_EFFECTIVE`;
        there is no provisional fine for a not-yet-effective rule."

        Design: Corner/validations/cite_violation_on_non_effective_rule_rejected
        """
        member = create_active_member(region="NA")
        rule = create_published_rule(
            "R-F1", effective_from="2026-12-01T00:00:00Z")
        res = api.create_rule_violation(
            {"rule_id": rule["id"], "subject_member_id": member["id"],
             "severity": "MINOR", "transaction_amount_minor": 100}, RA1)
        validate_error(res, ApiErrorId.ERR_RULE_NOT_EFFECTIVE)


class TestSegregationOfDuties:
    def _setup_assessed_violation(self, api):
        member = create_active_member(region="NA")
        rule = create_published_rule(
            "R-SOD-1",
            fine_schedule=[{"min_amount_minor": 1, "max_amount_minor": None,
                            "fine_cents": 1000}])
        violation = cite_violation(rule["id"], member["id"], citer_id="ra-1")
        assessed = assess_violation(violation["id"], assessor_id="ra-2")
        return member, rule, assessed

    def test_assess_by_citing_admin_rejected_sod(self, api):
        """PRD §3.5: "The assessor must differ from the administrator recorded
        in `cited_by_id`; otherwise the assessment is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Difficulty/priority_pair_validation_conflict/violation_assess_state_vs_sod
        """
        member = create_active_member(region="NA")
        rule = create_published_rule("R-SOD-2")
        violation = cite_violation(rule["id"], member["id"], citer_id="ra-1")
        res = api.assess_rule_violation(violation["id"],
                                        make_rules_admin_headers("ra-1"))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        current = get_success_data(api.get_rule_violation(violation["id"], RA1))
        assert current["status"] == "CITED"

    def test_assess_terminal_violation_rejected_invalid_state(self, api):
        """PRD §2.7: "a stale-state rejection surfaces before any
        segregation-of-duties rejection on the same call."
        PRD §2.7: "(5) the target resource being in a state from which the
        requested transition exists (`ERR_INVALID_STATE`)".

        Design: Difficulty/priority_pair_validation_conflict/violation_assess_state_vs_sod
        """
        _, _, assessed = self._setup_assessed_violation(api)
        # Drive the violation to terminal CONFIRMED (confirmer differs from
        # assessor per the segregation rule).
        get_success_data(api.confirm_rule_violation(
            assessed["id"], make_rules_admin_headers("ra-1")))
        # Re-assessing a terminal violation fails the state check — even
        # when the caller is the citing admin (whose SoD check would also
        # fail), the state error surfaces first.
        res = api.assess_rule_violation(assessed["id"],
                                        make_rules_admin_headers("ra-1"))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        current = get_success_data(api.get_rule_violation(assessed["id"], RA1))
        assert current["status"] == "CONFIRMED"

    def test_identity_mismatch_on_violation_appeal(self, api):
        """PRD §3.5: "The subject member itself may appeal — the requester's
        `X-User-ID` must equal the violation's `subject_member_id`, with a
        mismatch rejected as `ERR_IDENTITY_MISMATCH` — moving the violation
        from `ASSESSED` to `APPEALED`."

        Design: Corner/validations/identity_mismatch_on_violation_appeal
        """
        member, _, assessed = self._setup_assessed_violation(api)
        other = create_active_member(legal_name="B2")

        res = api.appeal_rule_violation(assessed["id"],
                                        make_member_headers(other["id"]))
        validate_error(res, ApiErrorId.ERR_IDENTITY_MISMATCH)

        res = api.appeal_rule_violation(assessed["id"],
                                        make_member_headers(member["id"]))
        data = validate_success(res)
        assert data["status"] == "APPEALED"


class TestWaiveConservation:
    def _setup_two_assessed_violations(self, api):
        member = create_active_member(legal_name="F Bank", member_kind="BOTH",
                                      region="NA")
        rule = create_published_rule(
            "R-FIN-1",
            fine_schedule=[{"min_amount_minor": 1, "max_amount_minor": None,
                            "fine_cents": 50000}])
        v1 = cite_violation(rule["id"], member["id"],
                            transaction_amount_minor=150000, citer_id="ra-1")
        v2 = cite_violation(rule["id"], member["id"],
                            transaction_amount_minor=150000, citer_id="ra-1")
        assess_violation(v1["id"], assessor_id="ra-2")
        assess_violation(v2["id"], assessor_id="ra-2")
        return member, rule, v1, v2

    def test_waive_resets_fine_to_zero(self, api):
        """PRD §3.5: "Alternatively, a `RulesAdministrator` may waive the fine
        from either `ASSESSED` or `APPEALED`, moving it to the terminal
        `WAIVED` state under the same segregation-of-duties constraint, and
        waiver resets `fine_cents` to zero."

        Design: Difficulty/compensating_invariant/fine_waive_conserves_collected_total
        """
        _, _, v1, _ = self._setup_two_assessed_violations(api)
        res = api.waive_rule_violation(v1["id"], make_rules_admin_headers("ra-3"))
        data = validate_success(res)
        assert data["status"] == "WAIVED"
        assert data["fine_cents"] == 0, \
            "assess-then-waive must net the fine back to zero"

    def test_waived_plus_confirmed_aggregate_fine(self, api):
        """PRD §3.5: "waiver resets `fine_cents` to zero."
        PRD §3.5: "A `RulesAdministrator` may confirm the fine from either
        `ASSESSED` or `APPEALED`, moving it to the terminal `CONFIRMED`
        state, but only if the confirmer's `X-User-ID` differs from
        `assessed_by_id`."

        Design: Difficulty/compensating_invariant/fine_waive_conserves_collected_total
        """
        member, _, v1, v2 = self._setup_two_assessed_violations(api)
        validate_success(api.waive_rule_violation(
            v1["id"], make_rules_admin_headers("ra-3")))
        confirmed = get_success_data(api.confirm_rule_violation(
            v2["id"], make_rules_admin_headers("ra-3")))
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["fine_cents"] == 50000

        waived = get_success_data(api.get_rule_violation(v1["id"], RA1))
        assert waived["fine_cents"] == 0
        assert waived["status"] == "WAIVED"
        assert waived["fine_cents"] + confirmed["fine_cents"] == 50000, \
            "the waived violation contributes 0 and the confirmed twin keeps its 50000"


class TestRulePublication:
    def test_publish_supersedes_earlier_effective_same_code(self, api):
        """PRD §3.4: "Publication also fires the supersede cascade: any
        existing `PUBLISHED` rule carrying the same `rule_code` and an
        overlapping scope — the same `region_scope`, or a `GLOBAL`-over-
        `GLOBAL` pairing — whose `effective_from` is earlier than the new
        rule's transitions to `SUPERSEDED` with a version increment."

        Design: Difficulty/resource_temporal_overlap/rule_publication_supersede_adjacency_semantics
        """
        create_active_member(region="NA")
        ra = create_published_rule("R-SUP-1",
                                   effective_from="2026-09-10T00:00:00Z",
                                   fine_schedule=[{"min_amount_minor": 1,
                                                   "max_amount_minor": None,
                                                   "fine_cents": 100}])
        rc = create_published_rule("R-SUP-1",
                                   effective_from="2026-09-20T00:00:00Z",
                                   fine_schedule=[{"min_amount_minor": 1,
                                                   "max_amount_minor": None,
                                                   "fine_cents": 200}])
        ra_now = get_success_data(api.get_rule(ra["id"], RA1))
        rc_now = get_success_data(api.get_rule(rc["id"], RA1))
        assert ra_now["status"] == "SUPERSEDED", \
            "the later-effective rule supersedes the earlier one"
        assert rc_now["status"] == "PUBLISHED"

    def test_earlier_effective_rule_does_not_supersede(self, api):
        """PRD §3.4: "Publication also fires the supersede cascade: any
        existing `PUBLISHED` rule carrying the same `rule_code` and an
        overlapping scope — the same `region_scope`, or a `GLOBAL`-over-
        `GLOBAL` pairing — whose `effective_from` is earlier than the new
        rule's transitions to `SUPERSEDED` with a version increment."

        Design: Difficulty/resource_temporal_overlap/rule_publication_supersede_adjacency_semantics
        """
        create_active_member(region="NA")
        ra = create_published_rule("R-SUP-1",
                                   effective_from="2026-09-10T00:00:00Z",
                                   fine_schedule=[{"min_amount_minor": 1,
                                                   "max_amount_minor": None,
                                                   "fine_cents": 100}])
        rb = create_published_rule("R-SUP-1",
                                   effective_from="2026-09-05T00:00:00Z",
                                   fine_schedule=[{"min_amount_minor": 1,
                                                   "max_amount_minor": None,
                                                   "fine_cents": 50}])
        ra_now = get_success_data(api.get_rule(ra["id"], RA1))
        rb_now = get_success_data(api.get_rule(rb["id"], RA1))
        assert ra_now["status"] == "PUBLISHED", \
            "an earlier-effective publication must not supersede the later rule"
        assert rb_now["status"] == "PUBLISHED"

    def test_occ_stale_rule_supersede_rejected(self, api):
        """PRD §2.6: "When the client supplies `supersedes_rule_id` on rule
        creation, it must also supply `expected_rule_version` carrying the
        client's last observed `version` of the referenced rule. If that
        rule's `version` has advanced since the client observed it — meaning
        the supersede decision was made against an outdated `effective_from`
        or `fine_schedule` — the create is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_rule_supersede_rejected
        """
        rule = get_success_data(api.create_rule(create_rule_payload(
            "R-O1", fine_schedule=[{"min_amount_minor": 1,
                                    "max_amount_minor": None,
                                    "fine_cents": 100}]), RA1))
        stale_version = rule["version"]
        get_success_data(api.publish_rule(rule["id"], RA1))
        fresh = get_success_data(api.get_rule(rule["id"], RA1))
        assert fresh["version"] > stale_version

        payload = create_rule_payload(
            "R-O1", title="B", body="b",
            effective_from="2026-10-01T00:00:00Z",
            fine_schedule=[{"min_amount_minor": 1, "max_amount_minor": None,
                            "fine_cents": 200}],
            supersedes_rule_id=rule["id"],
            expected_rule_version=stale_version)
        res = api.create_rule(payload, RA1)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    def test_occ_fresh_rule_supersede_succeeds(self, api):
        """PRD §2.6: "When `supersedes_rule_id` is not supplied,
        `expected_rule_version` is not required."
        PRD §2.6: "it must also supply `expected_rule_version` carrying the
        client's last observed `version` of the referenced rule."

        Design: Corner/cross_cutting_layers/occ_stale_rule_supersede_rejected
        """
        rule = create_published_rule("R-O1")
        fresh = get_success_data(api.get_rule(rule["id"], RA1))
        payload = create_rule_payload(
            "R-O1", title="B", body="b",
            effective_from="2026-10-01T00:00:00Z",
            fine_schedule=[{"min_amount_minor": 1, "max_amount_minor": None,
                            "fine_cents": 200}],
            supersedes_rule_id=rule["id"],
            expected_rule_version=fresh["version"])
        res = api.create_rule(payload, RA1)
        data = validate_success(res, 201)
        assert data["status"] == "DRAFT"

    def test_duplicate_rule_registration_rejected(self, api):
        """PRD §3.4: "The combination of `rule_code`, `region_scope`, and
        `effective_from` must be unique among rules that are not `RETIRED`; a
        collision is rejected with `ERR_DUPLICATE`."

        Design: Corner/cross_cutting_layers/duplicate_rule_registration_rejected
        """
        payload = create_rule_payload(
            "R-D1", title="A", body="a",
            effective_from="2026-09-10T00:00:00Z",
            fine_schedule=[{"min_amount_minor": 1, "max_amount_minor": None,
                            "fine_cents": 100}])
        get_success_data(api.create_rule(payload, RA1))
        dup = dict(payload, title="B", body="b",
                   fine_schedule=[{"min_amount_minor": 1,
                                   "max_amount_minor": None,
                                   "fine_cents": 200}])
        res = api.create_rule(dup, RA1)
        validate_error(res, ApiErrorId.ERR_DUPLICATE)

    def test_pricing_analyst_cannot_publish_rules(self, api):
        """PRD §2.1: "Once authenticated, a request whose role is not
        permitted for the target endpoint is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."
        PRD §2.1: "`RulesAdministrator` — publishes network rules and enforces
        compliance through the violation workflow."

        Design: Corner/rbac/pricing_analyst_cannot_publish_rules
        """
        rule = get_success_data(api.create_rule(create_rule_payload("R-R1"),
                                                RA1))
        res = api.publish_rule(rule["id"], PA)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)
        current = get_success_data(api.get_rule(rule["id"], RA1))
        assert current["status"] == "DRAFT"
