"""State adoptions: publication gate, certification branches, duplicate and OCC
guards, the publish supersede/coverage cascade, and role segregation."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_score1_equals,
    factories,
    fixtures,
    make_state_regulator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

STAFF = TEST_USERS["association_staff_headers"]


def _list_adoptions(api, act_id):
    data, _meta = validate_paginated(api.list_adoptions(act_id, STAFF))
    return data


def _list_reviews(api, state_id):
    data, _meta = validate_paginated(api.list_reviews(state_id, STAFF))
    return data


class TestAdoptions:
    def test_adoption_requires_published_act(self, api):
        """PRD §3.2: "Three domain checks follow in order: the act must be `PUBLISHED` (`ERR_ACT_NOT_PUBLISHED`, 422), the expected version must match (`ERR_STALE_VERSION`, 412), and the state must not already hold a `PENDING_CERTIFICATION` adoption for the same act (`ERR_DUPLICATE_ADOPTION`, 409)."
        PRD §3.2: "The new adoption starts in `PENDING_CERTIFICATION`."

        Design: Difficulty/cross_entity_state_dependency/adoption_requires_published_act
        """
        bundle = fixtures.create_adopted_act(
            api, voting=("CA",), model_code="MDL-703", version_label="v1",
            title="Model Rebating Act",
        )
        act = bundle.act
        state = bundle.states["CA"]
        assert act["status"] == "ADOPTED", "the gating state for this test"
        # The act is ADOPTED but not PUBLISHED: the adoption is refused.
        resp = api.create_adoption(
            factories.adoption_payload(
                act["id"], "CA", fixtures.state_version(api, state["id"]),
                adopted_citation="CIC 703",
            ),
            make_state_regulator_headers(state["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ACT_NOT_PUBLISHED)
        # After publish the identical payload succeeds.
        published = validate_success(api.publish_model_act(act["id"], STAFF))
        assert published["status"] == "PUBLISHED"
        adoption = fixtures.create_adoption(
            api, published, state, adopted_citation="CIC 703"
        )
        assert adoption["status"] == "PENDING_CERTIFICATION"

    def test_publish_supersede_coverage_cascade(self, api):
        """PRD §3.2: "Hop 1: any other model act sharing the same `model_code` that is currently `PUBLISHED` becomes `SUPERSEDED` — a version line never has two published members. Hop 2: every adoption of each superseded act whose status is `PENDING_CERTIFICATION`, `CERTIFIED_SIMILAR`, or `CERTIFIED_VARIED` becomes `SUPERSEDED`; adoptions already in `REJECTED_NOT_SIMILAR` are left untouched. Hop 3: `core_act_coverage_pct` is recomputed for every state whose adoption was superseded in hop 2. Hop 4: for each such state that is currently `ACCREDITED` and whose recomputed coverage has fallen below 50.0 percent, the system auto-creates an accreditation review with `origin` `AUTO_COVERAGE`, a null `team_lead_id`, a period running from the current clock to 180 days later, self-assessment counts of 0 out of 1, and status `SCHEDULED` (§3.3)."
        PRD §3.2: "the numerator counts the state's own adoptions in `CERTIFIED_SIMILAR` or `CERTIFIED_VARIED` status whose act has `is_core` true, and the denominator counts all model acts in `PUBLISHED` status with `is_core` true."

        Design: Difficulty/transitive_cascade/publish_supersede_coverage_cascade
        """
        bundle = fixtures.setup_publish_cascade_ready(api, model_code="MDL-101")
        state = bundle.state
        before = fixtures.read_state(api, state["id"])
        assert_score1_equals(
            before["core_act_coverage_pct"], 100.0, "coverage before publish"
        )
        validate_success(api.publish_model_act(bundle.act_v2["id"], STAFF))
        v1 = fixtures.read_model_act(api, bundle.act_v1["id"])
        assert v1["status"] == "SUPERSEDED", "hop 1: prior PUBLISHED act superseded"
        adoptions = _list_adoptions(api, bundle.act_v1["id"])
        assert len(adoptions) == 1
        assert adoptions[0]["status"] == "SUPERSEDED", (
            "hop 2: the certified adoption of the superseded act is superseded"
        )
        after = fixtures.read_state(api, state["id"])
        assert_score1_equals(
            after["core_act_coverage_pct"], 0.0, "coverage after publish"
        )
        reviews = _list_reviews(api, state["id"])
        assert any(
            r["origin"] == "AUTO_COVERAGE" and r["status"] == "SCHEDULED"
            for r in reviews
        ), "hop 4: coverage below 50.0 while ACCREDITED auto-creates a review"

    def test_certify_twice_rejected(self, api):
        """PRD §3.2: "Certification is an `AssociationStaff` decision supplied as `variation_class`, and it is only available while the adoption is `PENDING_CERTIFICATION` (`ERR_ADOPTION_NOT_PENDING`, 409)."

        Design: Corner/state_machines/certify_twice_rejected
        """
        bundle = fixtures.setup_certified_adoption(
            api, variation_class="SUBSTANTIALLY_SIMILAR", state_code="CA",
            model_code="MDL-813", version_label="v1",
        )
        assert bundle.adoption["status"] == "CERTIFIED_SIMILAR"
        resp = api.certify_adoption(
            bundle.adoption["id"],
            factories.certify_payload("SUBSTANTIVE_VARIATIONS"),
            STAFF,
        )
        validate_error(resp, ApiErrorId.ERR_ADOPTION_NOT_PENDING)

    def test_duplicate_adoption_pending_rejected(self, api):
        """PRD §3.2: "the state must not already hold a `PENDING_CERTIFICATION` adoption for the same act (`ERR_DUPLICATE_ADOPTION`, 409)."

        Design: Corner/validations/duplicate_adoption_pending_rejected
        """
        published = fixtures.create_published_act(
            api, voting=("CA",), model_code="MDL-833", version_label="v1"
        )
        state = published.states["CA"]
        first = fixtures.create_adoption(
            api, published.act, state, adopted_citation="CIC 833"
        )
        assert first["status"] == "PENDING_CERTIFICATION"
        # A fresh state version (so OCC passes) does not save the duplicate.
        resp = api.create_adoption(
            factories.adoption_payload(
                published.act["id"], "CA",
                fixtures.state_version(api, state["id"]),
                adopted_citation="CIC 833b", enacted_on="2026-12-01T00:00:00Z",
            ),
            make_state_regulator_headers(state["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ADOPTION)
        adoptions = _list_adoptions(api, published.act["id"])
        assert len(adoptions) == 1
        assert adoptions[0]["id"] == first["id"]
        assert adoptions[0]["status"] == "PENDING_CERTIFICATION"

    def test_occ_adoption_stale_version_rejected(self, api):
        """PRD §2.6: "Recording a state adoption (`POST /naic/adoptions`) requires `expected_state_version`, carrying the client's last observed `version` of the adopting state. A mismatch with the state's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.2: "the act must be `PUBLISHED` (`ERR_ACT_NOT_PUBLISHED`, 422), the expected version must match (`ERR_STALE_VERSION`, 412), and the state must not already hold a `PENDING_CERTIFICATION` adoption for the same act (`ERR_DUPLICATE_ADOPTION`, 409)."

        Design: Corner/cross_cutting_layers/occ_adoption_stale_version_rejected
        """
        published = fixtures.create_published_act(
            api, voting=("CA",), model_code="MDL-860", version_label="v1"
        )
        state = published.states["CA"]
        stale_version = state["version"]
        first = fixtures.create_adoption(
            api, published.act, state, expected_state_version=stale_version,
            adopted_citation="CIC 860",
        )
        assert first["status"] == "PENDING_CERTIFICATION"
        # The first create advanced the state's version; the stale echo is
        # refused (and would otherwise also collide as a duplicate).
        resp = api.create_adoption(
            factories.adoption_payload(
                published.act["id"], "CA", stale_version,
                adopted_citation="CIC 860b", enacted_on="2026-12-01T00:00:00Z",
            ),
            make_state_regulator_headers(state["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_coverage_cascade_skips_rejected_adoptions(self, api):
        """PRD §3.2: "Hop 2: every adoption of each superseded act whose status is `PENDING_CERTIFICATION`, `CERTIFIED_SIMILAR`, or `CERTIFIED_VARIED` becomes `SUPERSEDED`; adoptions already in `REJECTED_NOT_SIMILAR` are left untouched."
        PRD §3.2: "Hop 3: `core_act_coverage_pct` is recomputed for every state whose adoption was superseded in hop 2. Hop 4: for each such state that is currently `ACCREDITED` and whose recomputed coverage has fallen below 50.0 percent, the system auto-creates an accreditation review"

        Design: Corner/cross_cutting_layers/coverage_cascade_skips_rejected_adoptions
        """
        bundle = fixtures.setup_publish_cascade_ready(
            api, model_code="MDL-861", variation_class="NOT_SIMILAR"
        )
        assert bundle.adoption["status"] == "REJECTED_NOT_SIMILAR"
        validate_success(api.publish_model_act(bundle.act_v2["id"], STAFF))
        v1 = fixtures.read_model_act(api, bundle.act_v1["id"])
        assert v1["status"] == "SUPERSEDED"
        adoptions = _list_adoptions(api, bundle.act_v1["id"])
        assert len(adoptions) == 1
        assert adoptions[0]["status"] == "REJECTED_NOT_SIMILAR", (
            "the cascade leaves terminal rejections untouched"
        )
        reviews = _list_reviews(api, bundle.state["id"])
        assert reviews == [], (
            "no adoption of this state was superseded in hop 2, so hop 4 "
            "creates no AUTO_COVERAGE review for it"
        )

    def test_rbac_state_regulator_cannot_certify(self, api):
        """PRD §3.2: "Certification is an `AssociationStaff` decision supplied as `variation_class`"
        PRD §2.1: "A request whose role is not listed on the target endpoint, or that fails the ownership rules below, is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/rbac_state_regulator_cannot_certify
        """
        published = fixtures.create_published_act(
            api, voting=("CA",), model_code="MDL-850", version_label="v1"
        )
        state = published.states["CA"]
        adoption = fixtures.create_adoption(
            api, published.act, state, adopted_citation="CIC 850"
        )
        resp = api.certify_adoption(
            adoption["id"],
            factories.certify_payload("SUBSTANTIALLY_SIMILAR"),
            make_state_regulator_headers(state["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        adoptions = _list_adoptions(api, published.act["id"])
        assert adoptions[0]["status"] == "PENDING_CERTIFICATION"
