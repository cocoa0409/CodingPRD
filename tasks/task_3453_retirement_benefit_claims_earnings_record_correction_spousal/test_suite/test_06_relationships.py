"""Relationship register: verification gates, terminal rejection, and the
half-open marriage-interval exclusivity rule."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_relationship,
    create_worker,
    validate_error,
    validate_success,
)

CS = TEST_USERS["claims_specialist_headers"]


def _list_relationships(api, worker_id):
    return validate_success(api.list_worker_relationships(worker_id, CS))


class TestRelationshipStates:
    def test_relationship_verify_after_reject_returns_invalid_state(self, api):
        """PRD §3.3: "A specialist may instead reject the assertion — `ASSERTED →
        REJECTED` — recording a `rejection_reason`; rejection has no preconditions.
        Both `VERIFIED` and `REJECTED` are terminal."
        PRD §2.9: "**State-machine legality**: the target entity is in a
        from-state of the invoked transition, and terminal entities reject all
        further actions — otherwise `ERR_INVALID_STATE` (409), or
        `ERR_CLAIM_ALREADY_TERMINAL` (409) when the target claim is
        `WITHDRAWN` or `TERMINATED`."

        Design: Corner/state_machines/relationship_verify_after_reject_returns_invalid_state
        """
        w1 = create_worker(full_name="Rel Worker")
        w2 = create_worker(full_name="Rel Spouse")
        rel = create_relationship(w1["id"], w2["id"], "CURRENT_SPOUSE", "2000-01-01")
        validate_success(api.reject_relationship(rel["id"], "no certificate", CS))

        resp = api.verify_relationship(rel["id"], CS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

        fetched = _list_relationships(api, w1["id"])[0]
        assert fetched["status"] == "REJECTED"

    def test_widow_verification_requires_death_rejected(self, api):
        """PRD §3.3: "a `WIDOW` relationship may only be verified when the covered
        worker is `DECEASED`; verifying one for a living worker is rejected with
        `ERR_WORKER_NOT_DECEASED` (422)."

        Design: Corner/validations/widow_verification_requires_death_rejected
        """
        living = create_worker(full_name="Still Living")
        widow = create_worker(full_name="Premature Widow")
        rel = create_relationship(living["id"], widow["id"], "WIDOW", "2010-01-01")

        resp = api.verify_relationship(rel["id"], CS)
        validate_error(resp, ApiErrorId.ERR_WORKER_NOT_DECEASED, 422)

        fetched = _list_relationships(api, living["id"])[0]
        assert fetched["status"] == "ASSERTED"


class TestMarriageIntervalExclusivity:
    def test_adjacent_marriage_on_divorce_date_verifies(self, api):
        """PRD §3.3: "no other `VERIFIED` relationship sharing either endpoint
        worker may have a marriage interval overlapping this one, where intervals
        run from `marriage_date` up to but not including the `divorce_date` —
        half-open semantics, so one marriage ending exactly on the day another
        begins does *not* overlap; a violation is rejected with
        `ERR_RELATIONSHIP_OVERLAP` (409)."

        R2 begins exactly on R1's divorce date: adjacency is not overlap.

        Design: Difficulty/resource_temporal_overlap/marriage_interval_half_open_overlap
        """
        wm = create_worker(full_name="Married Worker")
        p1 = create_worker(full_name="Spouse One")
        p2 = create_worker(full_name="Spouse Two")

        r1 = create_relationship(
            wm["id"], p1["id"], "DIVORCED_SPOUSE", "2000-01-01", divorce_date="2010-06-15"
        )
        verified_r1 = validate_success(api.verify_relationship(r1["id"], CS))
        assert verified_r1["status"] == "VERIFIED"

        r2 = create_relationship(wm["id"], p2["id"], "CURRENT_SPOUSE", "2010-06-15")
        verified_r2 = validate_success(api.verify_relationship(r2["id"], CS))
        assert verified_r2["status"] == "VERIFIED", (
            "a marriage beginning exactly on the prior divorce date must verify"
        )
        assert verified_r2["verified_at"] is not None

    def test_open_interval_rejects_later_marriage(self, api):
        """PRD §3.3: "no other `VERIFIED` relationship sharing either endpoint
        worker may have a marriage interval overlapping this one, where intervals
        run from `marriage_date` up to but not including the `divorce_date` —
        half-open semantics, so one marriage ending exactly on the day another
        begins does *not* overlap; a violation is rejected with
        `ERR_RELATIONSHIP_OVERLAP` (409)."

        R2's interval [2010-06-15, open) is still running; R3 at 2011-01-01
        overlaps it.

        Design: Difficulty/resource_temporal_overlap/marriage_interval_half_open_overlap
        """
        wm = create_worker(full_name="Married Worker")
        p1 = create_worker(full_name="Spouse One")
        p2 = create_worker(full_name="Spouse Two")
        p3 = create_worker(full_name="Spouse Three")

        r1 = create_relationship(
            wm["id"], p1["id"], "DIVORCED_SPOUSE", "2000-01-01", divorce_date="2010-06-15"
        )
        validate_success(api.verify_relationship(r1["id"], CS))
        r2 = create_relationship(wm["id"], p2["id"], "CURRENT_SPOUSE", "2010-06-15")
        validate_success(api.verify_relationship(r2["id"], CS))

        r3 = create_relationship(wm["id"], p3["id"], "CURRENT_SPOUSE", "2011-01-01")
        resp = api.verify_relationship(r3["id"], CS)
        validate_error(resp, ApiErrorId.ERR_RELATIONSHIP_OVERLAP, 409)

        fetched = [r for r in _list_relationships(api, wm["id"]) if r["id"] == r3["id"]][0]
        assert fetched["status"] == "ASSERTED"
