"""Education award trust: use creation guards (status, deadline, balance,
Title IV), optimistic concurrency, decide/rescind ledger conservation, and
the exact-second deadline boundary (PRD §2.8, §3.7)."""
from test_helpers import (
    ApiErrorId,
    create_award_use_payload,
    decide_use_payload,
    education_award_version,
    make_member_headers,
    rescind_use_payload,
    set_clock,
    setup_education_award,
    validate_error,
    validate_paginated,
    validate_success,
)

DEADLINE_EXACT = "2033-10-02T00:00:00Z"
DEADLINE_PLUS_1S = "2033-10-02T00:00:01Z"
DEADLINE_PLUS_1D = "2033-10-03T00:00:00Z"


def _prorated_award(api):
    """Member exited COMPELLING at 36000/102000 minutes -> 261000 cents, v1."""
    scenario = setup_education_award(
        minutes_chunks=(36000,), exit_reason="COMPELLING_CIRCUMSTANCE"
    )
    edu_id = scenario["education_award_id"]
    return scenario, edu_id


def _full_award(api):
    """Member exited SUCCESSFUL at 102000 minutes -> 739500 cents, v1,
    use_deadline_at 2033-10-02T00:00:00Z."""
    scenario = setup_education_award(
        minutes_chunks=(48000, 48000, 6000), exit_reason="SUCCESSFUL"
    )
    return scenario, scenario["education_award_id"]


class TestUseDeadlineExactSecond:
    def test_use_at_exact_deadline_instant_is_allowed(self, api, trust_admin_headers):
        """At exactly use_deadline_at the use is created PENDING_APPROVAL and
        the award's version increments by exactly 1.

        PRD §3.7: "Next, the use deadline: the current logical time must be at or before `use_deadline_at`, with the deadline instant itself still usable"
        PRD §3.7: "A created use enters `PENDING_APPROVAL`, and its creation increments the education award's `version` by 1."

        Design: Difficulty/boundary_precision_check/award_use_deadline_exact_second
        """
        scenario, edu_id = _full_award(api)
        assert education_award_version(edu_id) == 1
        set_clock(DEADLINE_EXACT)
        resp = api.create_award_use(
            edu_id,
            create_award_use_payload("TUITION", 1000, 1, institution_title_iv=True),
            make_member_headers(scenario["member_id"]),
        )
        use = validate_success(resp, 201)
        assert use["status"] == "PENDING_APPROVAL"
        assert education_award_version(edu_id) == 2

    def test_one_second_past_deadline_rejected_and_award_expires(self, api, trust_admin_headers):
        """One second after the deadline the use is rejected and the rejection
        itself flips the award to EXPIRED; the balance is untouched because the
        earlier use was only PENDING_APPROVAL.

        PRD §3.7: "a use after the deadline is `ERR_AWARD_USE_DEADLINE_PASSED`, and that very rejection flips the award to `EXPIRED` as a side effect."

        Design: Difficulty/boundary_precision_check/award_use_deadline_exact_second
        """
        scenario, edu_id = _full_award(api)
        member = make_member_headers(scenario["member_id"])
        set_clock(DEADLINE_EXACT)
        validate_success(
            api.create_award_use(
                edu_id,
                create_award_use_payload("TUITION", 1000, 1, institution_title_iv=True),
                member,
            ),
            201,
        )
        version = education_award_version(edu_id)
        set_clock(DEADLINE_PLUS_1S)
        resp = api.create_award_use(
            edu_id,
            create_award_use_payload("QUALIFIED_LOAN", 1000, version),
            member,
        )
        validate_error(resp, ApiErrorId.ERR_AWARD_USE_DEADLINE_PASSED)
        assert resp.status_code == 422
        award = validate_success(api.get_education_award(edu_id, trust_admin_headers))
        assert award["status"] == "EXPIRED"
        assert award["remaining_balance_cents"] == 739500


class TestTrustLedgerConservation:
    def _setup_two_approved_uses(self, api, trust_admin_headers):
        """261000 award: use_1 TUITION 100000 APPROVED, use_2 QUALIFIED_LOAN
        50000 APPROVED. Returns (scenario, edu_id, use_1, use_2)."""
        scenario, edu_id = _prorated_award(api)
        member = make_member_headers(scenario["member_id"])
        use_1 = validate_success(
            api.create_award_use(
                edu_id,
                create_award_use_payload("TUITION", 100000, 1, institution_title_iv=True),
                member,
            ),
            201,
        )
        validate_success(
            api.decide_use(use_1["id"], decide_use_payload("APPROVE"), trust_admin_headers)
        )
        use_2 = validate_success(
            api.create_award_use(
                edu_id,
                create_award_use_payload(
                    "QUALIFIED_LOAN", 50000, education_award_version(edu_id)
                ),
                member,
            ),
            201,
        )
        validate_success(
            api.decide_use(use_2["id"], decide_use_payload("APPROVE"), trust_admin_headers)
        )
        return scenario, edu_id, use_1, use_2

    def test_approvals_debit_balance_and_move_status(self, api, trust_admin_headers):
        """Approving use_1 drops the balance to 161000 (PARTIALLY_USED);
        approving use_2 drops it to 111000.

        PRD §3.7: "then debits the award: `remaining_balance_cents` falls by the amount, the award's `version` increments, and the award's status becomes `EXHAUSTED` when the balance hits zero and `PARTIALLY_USED` otherwise."

        Design: Difficulty/compensating_invariant/education_award_trust_ledger_approve_rescind
        """
        scenario, edu_id, use_1, use_2 = self._setup_two_approved_uses(api, trust_admin_headers)
        award = validate_success(api.get_education_award(edu_id, trust_admin_headers))
        assert award["remaining_balance_cents"] == 111000
        assert award["status"] == "PARTIALLY_USED"

    def test_rescind_restores_exact_debit_with_zero_drift(self, api, trust_admin_headers):
        """Rescinding use_1 restores its 100000 to the balance (211000) and
        the status stays PARTIALLY_USED because use_2 remains approved:
        211000 + 50000 == 261000 == issued_amount_cents.

        PRD §3.7: "An approved use can later be rescinded — a compensating action requiring a `reason` that moves the use `APPROVED` → `RESCINDED` — which restores the amount to `remaining_balance_cents`, increments the award's `version` again, and recomputes the award's status: `ISSUED` when the restoration returns the balance to the full `issued_amount_cents`, `PARTIALLY_USED` otherwise."

        Design: Difficulty/compensating_invariant/education_award_trust_ledger_approve_rescind
        """
        scenario, edu_id, use_1, use_2 = self._setup_two_approved_uses(api, trust_admin_headers)
        rescinded = validate_success(
            api.rescind_use(use_1["id"], rescind_use_payload("Duplicate disbursement"),
                            trust_admin_headers)
        )
        assert rescinded["status"] == "RESCINDED"
        award = validate_success(api.get_education_award(edu_id, trust_admin_headers))
        assert award["remaining_balance_cents"] == 211000
        assert award["status"] == "PARTIALLY_USED", (
            "not ISSUED — use_2 still holds 50000 approved"
        )
        assert award["remaining_balance_cents"] + 50000 == award["issued_amount_cents"] == 261000
        rows, _ = validate_paginated(api.list_award_uses(edu_id, trust_admin_headers))
        by_id = {u["id"]: u for u in rows}
        assert by_id[use_1["id"]]["status"] == "RESCINDED"
        assert by_id[use_2["id"]]["status"] == "APPROVED"


class TestUseCreationGuards:
    def test_use_above_remaining_balance_rejected_exactly_at_balance_allowed(self, api, trust_admin_headers):
        """A use of 300000 against a 261000 balance is rejected; a use of
        exactly 261000 is created (the failed first call consumed no version).

        PRD §3.7: "Finally, the requested amount must not exceed `remaining_balance_cents` (`ERR_INSUFFICIENT_AWARD_BALANCE`)."

        Design: Corner/validations/use_above_remaining_balance_rejected
        """
        scenario, edu_id = _prorated_award(api)
        member = make_member_headers(scenario["member_id"])
        assert education_award_version(edu_id) == 1
        over = api.create_award_use(
            edu_id, create_award_use_payload("QUALIFIED_LOAN", 300000, 1), member
        )
        validate_error(over, ApiErrorId.ERR_INSUFFICIENT_AWARD_BALANCE)
        exact = api.create_award_use(
            edu_id, create_award_use_payload("QUALIFIED_LOAN", 261000, 1), member
        )
        use = validate_success(exact, 201)
        assert use["status"] == "PENDING_APPROVAL"

    def test_tuition_requires_title_iv_loan_ignores_flag(self, api):
        """TUITION with institution_title_iv false is rejected; QUALIFIED_LOAN
        needs no institution flag.

        PRD §3.7: "Tuition carries an extra eligibility rule: `institution_title_iv` must be true, certifying a Title IV institution, else `ERR_INSTITUTION_NOT_ELIGIBLE`; for a `QUALIFIED_LOAN` use the flag is ignored."

        Design: Corner/validations/tuition_use_requires_title_iv_institution
        """
        scenario, edu_id = _prorated_award(api)
        member = make_member_headers(scenario["member_id"])
        tuition = api.create_award_use(
            edu_id,
            create_award_use_payload("TUITION", 50000, 1, institution_title_iv=False),
            member,
        )
        validate_error(tuition, ApiErrorId.ERR_INSTITUTION_NOT_ELIGIBLE)
        loan = api.create_award_use(
            edu_id, create_award_use_payload("QUALIFIED_LOAN", 50000, 1), member
        )
        use = validate_success(loan, 201)
        assert use["status"] == "PENDING_APPROVAL"

    def test_deadline_guard_fires_before_balance_guard(self, api, trust_admin_headers):
        """Past the deadline AND above the balance, the deadline guard (which
        runs before the balance guard) rejects and flips the award to EXPIRED.

        PRD §3.7: "Three guards then protect the balance, and their relative order matters."
        PRD §3.7: "a use after the deadline is `ERR_AWARD_USE_DEADLINE_PASSED`, and that very rejection flips the award to `EXPIRED` as a side effect."

        Design: Corner/validations/deadline_temporal_beats_balance_fiscal
        """
        scenario, edu_id = _prorated_award(api)
        member = make_member_headers(scenario["member_id"])
        set_clock(DEADLINE_PLUS_1D)
        resp = api.create_award_use(
            edu_id, create_award_use_payload("QUALIFIED_LOAN", 999999, 1), member
        )
        err = validate_error(resp, ApiErrorId.ERR_AWARD_USE_DEADLINE_PASSED)
        assert err["error_id"] != ApiErrorId.ERR_INSUFFICIENT_AWARD_BALANCE
        award = validate_success(api.get_education_award(edu_id, trust_admin_headers))
        assert award["status"] == "EXPIRED"

    def test_decide_twice_and_rescind_pending_rejected(self, api, trust_admin_headers):
        """A second decide on an APPROVED use and a rescind on a
        PENDING_APPROVAL use are both rejected; the balance is unmoved.

        PRD §3.7: "Deciding a use that is not `PENDING_APPROVAL` is `ERR_USE_NOT_PENDING`."
        PRD §3.7: "Rescinding a use that is not `APPROVED` is likewise `ERR_USE_NOT_PENDING`."

        Design: Corner/validations/decide_twice_and_rescind_pending_rejected
        """
        scenario, edu_id = _prorated_award(api)
        member = make_member_headers(scenario["member_id"])
        use_1 = validate_success(
            api.create_award_use(
                edu_id, create_award_use_payload("QUALIFIED_LOAN", 50000, 1), member
            ),
            201,
        )
        validate_success(
            api.decide_use(use_1["id"], decide_use_payload("APPROVE"), trust_admin_headers)
        )
        use_2 = validate_success(
            api.create_award_use(
                edu_id,
                create_award_use_payload(
                    "TUITION", 10000, education_award_version(edu_id),
                    institution_title_iv=True,
                ),
                member,
            ),
            201,
        )
        re_decide = api.decide_use(use_1["id"], decide_use_payload("APPROVE"), trust_admin_headers)
        validate_error(re_decide, ApiErrorId.ERR_USE_NOT_PENDING)
        premature = api.rescind_use(
            use_2["id"], rescind_use_payload("Premature"), trust_admin_headers
        )
        validate_error(premature, ApiErrorId.ERR_USE_NOT_PENDING)
        award = validate_success(api.get_education_award(edu_id, trust_admin_headers))
        assert award["remaining_balance_cents"] == 211000, "rejections move nothing"

    def test_stale_education_award_version_rejected(self, api, trust_admin_headers):
        """The first use create carries the award's current version 1 and
        succeeds (version advances to 2); a second create replaying version 1
        is rejected 412.

        PRD §2.8: "The use-creation request must carry `expected_education_award_version` equal to the education award's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (412), preventing the client from acting on a balance it has not observed."

        Design: Corner/cross-cutting complexity layers/stale_education_award_version_on_use_create_returns_412
        """
        scenario, edu_id = _prorated_award(api)
        member = make_member_headers(scenario["member_id"])
        first = api.create_award_use(
            edu_id, create_award_use_payload("QUALIFIED_LOAN", 10000, 1), member
        )
        validate_success(first, 201)
        assert education_award_version(edu_id) == 2
        stale = api.create_award_use(
            edu_id, create_award_use_payload("QUALIFIED_LOAN", 20000, 1), member
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        assert stale.status_code == 412
        award = validate_success(api.get_education_award(edu_id, trust_admin_headers))
        assert award["remaining_balance_cents"] == 261000, (
            "no debits — uses only debit at approval time"
        )
