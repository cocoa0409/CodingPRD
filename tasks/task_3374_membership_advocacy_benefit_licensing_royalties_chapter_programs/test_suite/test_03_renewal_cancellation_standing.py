"""Renewal batch, cancellation lifecycle, household standing, and the
renewal cascade's three observable links."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
    set_clock, create_household_with_term, cancel_term_ok, get_household,
    list_household_terms, list_household_members,
    create_chapter_ok, create_session_ok, make_member_headers,
)

MSA = TEST_USERS["member_services_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def _run_batch():
    return validate_success(api_client.run_renewal_batch(ADMIN))


class TestRenewalPricingDiscountCap:
    def _setup_two_auto_renew_households(self):
        set_clock()
        hh_a5, term_a5, _ = create_household_with_term(
            state_code="OH", term_years=5, primary_full_name="Cara Chen",
            primary_date_of_birth="1965-07-04", auto_renew_enabled=True)
        hh_b3, term_b3, _ = create_household_with_term(
            state_code="OH", term_years=3, primary_full_name="Dan Doyle",
            primary_date_of_birth="1972-12-01", auto_renew_enabled=True)
        assert term_a5["paid_cents"] == 6400
        assert term_b3["paid_cents"] == 4320
        set_clock("2031-09-01T00:00:00Z")
        return hh_a5, hh_b3

    def test_five_year_renewal_hits_discount_cap(self, api):
        """PRD §3.1: "a term created by the renewal batch adds a further 5
        percentage points of loyalty discount." PRD §3.1: "The combined
        discount is capped at 25% — a five-year renewal reaches exactly the
        cap and no more." PRD §3.1: "A five-year initial purchase therefore
        costs 6,400 cents, and a five-year renewal costs 6,000 cents."

        Design: Difficulty/combinatorial_formula/renewal_pricing_discount_cap_nested_min
        """
        hh_a5, hh_b3 = self._setup_two_auto_renew_households()
        result = _run_batch()
        assert result["renewed_count"] == 2
        assert result["lapsed_count"] == 0

        terms_a = list_household_terms(hh_a5["id"])
        renewals_a = [t for t in terms_a if t["is_renewal"]]
        assert len(renewals_a) == 1
        renewal_a = renewals_a[0]
        # min(0.25, 0.20 + 0.05) binds: 1600 * 5 * 0.75 = 6000.
        assert renewal_a["paid_cents"] == 6000
        assert renewal_a["start_date"] == "2031-09-01"
        assert renewal_a["end_date"] == "2036-09-01"
        assert renewal_a["status"] == "ACTIVE"

    def test_three_year_renewal_below_discount_cap(self, api):
        """PRD §3.1: "Multi-year terms earn a discount of 0% for one year,
        10% for three years, or 20% for five years; a term created by the
        renewal batch adds a further 5 percentage points of loyalty discount."
        PRD §3.2: "the expiring term transitions `ACTIVE` → `RENEWED` and a
        fresh term is created seamlessly: `is_renewal` true, `start_date`
        equal to the old term's `end_date`".

        Design: Difficulty/combinatorial_formula/renewal_pricing_discount_cap_nested_min
        """
        hh_a5, hh_b3 = self._setup_two_auto_renew_households()
        _run_batch()

        terms_b = list_household_terms(hh_b3["id"])
        renewals_b = [t for t in terms_b if t["is_renewal"]]
        assert len(renewals_b) == 1
        renewal_b = renewals_b[0]
        # min(0.25, 0.10 + 0.05) does not bind: 1600 * 3 * 0.85 = 4080.
        assert renewal_b["paid_cents"] == 4080
        assert renewal_b["start_date"] == "2029-09-01"
        assert renewal_b["end_date"] == "2032-09-01"

        for hh in (hh_a5, hh_b3):
            terms = list_household_terms(hh["id"])
            originals = [t for t in terms if not t["is_renewal"]]
            assert len(originals) == 1
            assert originals[0]["status"] == "RENEWED"
            assert get_household(hh["id"])["status"] == "ACTIVE"


class TestRenewalBatchCascade:
    def _setup_renewal_cascade(self):
        set_clock()
        hh_a, _ta, _ma = create_household_with_term(
            state_code="CO", term_years=1, primary_full_name="Ivy Irwin",
            primary_date_of_birth="1971-06-06", auto_renew_enabled=True)
        hh_b, _tb, member_b = create_household_with_term(
            state_code="CO", term_years=1, primary_full_name="Jack Jones",
            primary_date_of_birth="1969-08-08", auto_renew_enabled=False)
        chapter = create_chapter_ok(
            name="Denver Metro Chapter", state_code="CO", city="Denver")
        session = create_session_ok(
            chapter["id"], course_kind="DRIVER_SAFETY",
            instructor_name="Pat Rowe", start_time="2027-09-05T09:00:00Z",
            end_time="2027-09-05T11:00:00Z", capacity=10)
        set_clock("2027-09-01T00:00:00Z")
        return hh_a, hh_b, member_b, session

    def test_batch_renews_and_lapses_and_recomputes_standing(self, api):
        """PRD §3.2: "It visits every `ACTIVE` membership term whose
        `end_date` is on or before the current clock date and splits them by
        household preference." PRD §3.2: "After the sweep, each touched
        household's standing is recomputed — a renewed household stays
        `ACTIVE` because the new term covers the clock date, while a
        non-renewed household becomes `LAPSED` if no other covering term
        exists".

        Design: Difficulty/transitive_cascade/renewal_batch_three_hop_cascade
        """
        hh_a, hh_b, _member_b, _session = self._setup_renewal_cascade()
        result = _run_batch()
        assert result["renewed_count"] == 1
        assert result["lapsed_count"] == 1

        terms_a = list_household_terms(hh_a["id"])
        renewals = [t for t in terms_a if t["is_renewal"]]
        assert len(renewals) == 1
        # 1-year renewal loyalty price: 1600 * 1 * (1 - 0.05) = 1520.
        assert renewals[0]["paid_cents"] == 1520
        assert renewals[0]["start_date"] == "2027-09-01"
        assert renewals[0]["end_date"] == "2028-09-01"
        originals = [t for t in terms_a if not t["is_renewal"]]
        assert originals[0]["status"] == "RENEWED"

        assert get_household(hh_a["id"])["status"] == "ACTIVE"
        assert get_household(hh_b["id"])["status"] == "LAPSED"

    def test_lapsed_member_standing_blocks_enrollment(self, api):
        """PRD §3.2: "and every member's `in_good_standing` follows." PRD
        §3.8: "Standing second: the member must be in good standing,
        otherwise `ERR_MEMBER_NOT_ACTIVE` (HTTP 409)."

        Design: Difficulty/transitive_cascade/renewal_batch_three_hop_cascade
        """
        _hh_a, hh_b, member_b, session = self._setup_renewal_cascade()
        _run_batch()

        members = list_household_members(hh_b["id"])
        member_b_row = next(m for m in members if m["id"] == member_b)
        assert member_b_row["in_good_standing"] is False

        resp = api.enroll_member(
            session["id"], {"member_id": member_b}, make_member_headers(member_b))
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ACTIVE)


class TestCancellationLifecycle:
    def test_second_cancel_rejected_and_no_double_refund(self, api):
        """PRD §3.2: "Only an `ACTIVE` term can be cancelled; a term already
        `RENEWED`, `LAPSED`, or `CANCELLED` is rejected with
        `ERR_TERM_NOT_ACTIVE` (HTTP 409)."

        Design: Corner/state_machines/cancel_already_cancelled_term_returns_invalid_state
        """
        set_clock()
        hh, term, _member = create_household_with_term(
            state_code="ID", term_years=1, primary_full_name="Ira Iles",
            primary_date_of_birth="1960-10-10")
        first = cancel_term_ok(term["id"], "VOLUNTARY")
        # Cancelled in the purchase month: months_used == 1, 1600 - 133 = 1467.
        assert first["refunded_cents"] == 1467

        resp = api.cancel_term(term["id"], {"reason": "VOLUNTARY"}, MSA)
        validate_error(resp, ApiErrorId.ERR_TERM_NOT_ACTIVE)

        terms = list_household_terms(hh["id"])
        cancelled = next(t for t in terms if t["id"] == term["id"])
        assert cancelled["refunded_cents"] == 1467

    def test_cancel_unknown_term_returns_not_found(self, api):
        """PRD §2.8 rung 6: "Path identifiers exist, validated left to right,
        followed by body-supplied foreign keys (`member_id`,
        `license_agreement_id`, `sponsor_entity_id`, `from_entity_id`,
        `to_entity_id`); otherwise `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/validations/cancel_unknown_term_returns_not_found
        """
        set_clock()
        resp = api.cancel_term(NON_EXISTENT_UUID, {"reason": "VOLUNTARY"}, MSA)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_cancel_immediately_visible_everywhere(self, api):
        """PRD §3.2: "A successful cancellation records `refunded_cents`
        (which is 0 on any term until it is cancelled), `cancel_reason`, and
        `cancelled_at` stamped from the logical clock, and moves the term to
        `CANCELLED`." PRD §3.2: "The household's `lifetime_refunded_cents`,
        which starts at 0, grows by the refund; this cascade mutation
        increments the household's `version` and refreshes its `updated_at`."

        Design: Corner/consistency_model/cancel_immediately_visible_everywhere
        """
        set_clock()
        hh, term, member_id = create_household_with_term(
            state_code="CT", term_years=3, primary_full_name="Fay Fenn",
            primary_date_of_birth="1965-05-05")
        assert term["paid_cents"] == 4320
        set_clock("2026-11-15T00:00:00Z")

        resp = api.cancel_term(term["id"], {"reason": "VOLUNTARY"}, MSA)
        cancelled = validate_success(resp)
        # months_used == 3 -> 4320 - 3*133 = 3921.
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["refunded_cents"] == 3921

        household = get_household(hh["id"])
        assert household["status"] == "LAPSED"
        assert household["lifetime_refunded_cents"] == 3921
        assert household["lifetime_collected_cents"] == 4320

        terms = list_household_terms(hh["id"])
        term_row = next(t for t in terms if t["id"] == term["id"])
        assert term_row["status"] == "CANCELLED"
        assert term_row["cancelled_at"] == "2026-11-15T00:00:00Z"

        members = list_household_members(hh["id"])
        member_row = next(m for m in members if m["id"] == member_id)
        assert member_row["in_good_standing"] is False

    def test_household_version_increments_on_cancel_cascade(self, api):
        """PRD §2.5: "Mutation cascades count as mutations of every resource
        they touch." PRD §2.5: "Cancelling a membership term, for example,
        increments the owning household's `version` and refreshes its
        `updated_at`, because the household's lifetime counters change".

        Design: Corner/cross_cutting_complexity_layers/household_version_increments_on_cascade
        """
        set_clock()
        hh, term, _member = create_household_with_term(
            state_code="AR", term_years=1, primary_full_name="Eli Earp",
            primary_date_of_birth="1964-04-04")
        assert hh["version"] == 1

        cancel_term_ok(term["id"], "VOLUNTARY")
        household = get_household(hh["id"])
        assert household["version"] == 2
        # months_used == 1 at the unchanged clock: 1600 - 133 = 1467.
        assert household["lifetime_refunded_cents"] == 1467


class TestRenewalSweepNoop:
    def test_renewal_run_before_end_date_is_noop(self, api):
        """PRD §3.2: "It visits every `ACTIVE` membership term whose
        `end_date` is on or before the current clock date and splits them by
        household preference." PRD §3.2: "The batch response tallies the run
        as `renewed_count`, `lapsed_count`, `renewed_term_ids`, and
        `lapsed_term_ids`."

        Design: Corner/endpoints/renewal_run_before_end_date_is_noop
        """
        set_clock()
        hh, term, _member = create_household_with_term(
            state_code="NE", term_years=1, primary_full_name="Yara Yost",
            primary_date_of_birth="1967-07-07", auto_renew_enabled=True)
        assert term["end_date"] == "2027-09-01"
        set_clock("2027-08-31T00:00:00Z")

        result = _run_batch()
        assert result["renewed_count"] == 0
        assert result["lapsed_count"] == 0

        terms = list_household_terms(hh["id"])
        assert len(terms) == 1
        assert terms[0]["status"] == "ACTIVE"
        assert get_household(hh["id"])["version"] == 1
