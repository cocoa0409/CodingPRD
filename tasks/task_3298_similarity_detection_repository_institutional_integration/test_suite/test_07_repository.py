"""Repository deposits, participation cascades, consent cascades (PRD §2.8, §3.2, §3.6, §3.10)."""
from test_helpers import (
    TEST_USERS,
    get_assessment,
    get_report,
    grant_consent,
    make_instructor_headers,
    process,
    setup_basic_scenario,
    submit,
    validate_paginated,
    validate_success,
    withdraw_consent,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INST_ADMIN = TEST_USERS["institutional_admin_headers"]


def _inst_count(api, inst_id):
    return validate_success(api.get_institution(inst_id, ADMIN))["comparable_submission_count"]


def test_deposit_create_withdraw_conserve_comparable_count(api):
    """PRD §3.6: "the institution's `comparable_submission_count` is recomputed:
    it always equals the number of the institution's deposits that are
    simultaneously in `deposit_state` `STORED` and `scope` `GLOBAL_SHARED`."
    PRD §3.10: "Withdrawal moves the deposit to terminal `WITHDRAWN`, recomputes
    the institution's `comparable_submission_count`, increments the deposit's
    `version`, and — because the deposit's auto-created `STUDENT_REPOSITORY`
    source is retracted as part of withdrawal"

    Design: Difficulty/compensating_invariant/deposit_create_withdraw_conserve_comparable_count
    """
    inst, integ, instr, student, asg = setup_basic_scenario(
        "US",
        inst_overrides={"repository_participation": "GLOBAL_SHARED"},
        assignment_overrides={"repository_option": "STORE_AND_COMPARE"},
    )
    sub = submit(asg["id"], student["id"], "invariant body")
    assert _inst_count(api, inst["id"]) == 0

    process(sub["id"], instr["id"])
    assert _inst_count(api, inst["id"]) == 1, "STORED + GLOBAL_SHARED deposit counts"

    deps, _ = validate_paginated(api.list_deposits_of_submission(sub["id"], INST_ADMIN))
    dep = deps[0]
    withdrawn = validate_success(api.withdraw_deposit(dep["id"], INST_ADMIN))
    assert withdrawn["deposit_state"] == "WITHDRAWN"
    assert _inst_count(api, inst["id"]) == 0, "the conserved quantity returns exactly to its pre-pair value"

    sources, _ = validate_paginated(api.list_source_documents(inst["id"], ADMIN))
    repo_sources = [s for s in sources if s["source_type"] == "STUDENT_REPOSITORY"]
    assert repo_sources and repo_sources[0]["status"] == "RETRACTED"


def test_compare_only_creates_no_deposit(api):
    """PRD §3.6: "When `repository_option` is `COMPARE_ONLY`, no deposit and no
    auto source are created — the submission is compared against the corpora but
    never joins them."

    Design: Corner/cross_cutting_layers/repository_option_compare_only_creates_no_deposit
    """
    inst, integ, instr, student, asg = setup_basic_scenario(
        "US", inst_overrides={"repository_participation": "GLOBAL_SHARED"}
    )
    sub = submit(asg["id"], student["id"], "compare only body")
    process(sub["id"], instr["id"])

    report = get_report(sub["id"], instr["id"])
    assert report["report_state"] == "DRAFT", "report is still generated"
    deps, _ = validate_paginated(api.list_deposits_of_submission(sub["id"], INST_ADMIN))
    assert deps == []
    assert _inst_count(api, inst["id"]) == 0


def test_opt_out_institution_deposits_quarantined_at_creation(api):
    """PRD §2.8: "`repository_participation` takes one of `GLOBAL_SHARED`,
    `INSTITUTION_ONLY`, or `OPT_OUT` and determines both the `scope` of new
    deposits (`GLOBAL_SHARED` only when participation is `GLOBAL_SHARED`,
    otherwise `INSTITUTION_ONLY`) and their initial `deposit_state`
    (`QUARANTINED` under `OPT_OUT`, otherwise `STORED`)"

    Design: Corner/cross_cutting_layers/opt_out_institution_deposits_quarantined_at_creation
    """
    inst, integ, instr, student, asg = setup_basic_scenario(
        "US",
        inst_overrides={"repository_participation": "OPT_OUT"},
        assignment_overrides={"repository_option": "STORE_AND_COMPARE"},
    )
    sub = submit(asg["id"], student["id"], "opt out body")
    process(sub["id"], instr["id"])

    deps, _ = validate_paginated(api.list_deposits_of_submission(sub["id"], INST_ADMIN))
    assert deps[0]["deposit_state"] == "QUARANTINED", "QUARANTINED at creation, never STORED"
    assert _inst_count(api, inst["id"]) == 0


def test_institution_optout_quarantines_stored_deposits(api):
    """PRD §3.1: "flipping `repository_participation` to `OPT_OUT` quarantines
    every one of the institution's `STORED` deposits and recomputes
    `comparable_submission_count`, while restoring participation to
    `GLOBAL_SHARED` or `INSTITUTION_ONLY` returns exactly the deposits that
    participation-quarantine cascade had quarantined to `STORED`"

    Design: Corner/cross_cutting_layers/institution_optout_quarantines_stored_deposits
    """
    inst, integ, instr, student, asg = setup_basic_scenario(
        "US",
        inst_overrides={"repository_participation": "GLOBAL_SHARED"},
        assignment_overrides={"repository_option": "STORE_AND_COMPARE"},
    )
    sub = submit(asg["id"], student["id"], "optout body")
    process(sub["id"], instr["id"])
    assert _inst_count(api, inst["id"]) == 1

    inst_now = validate_success(api.get_institution(inst["id"], ADMIN))
    patched = validate_success(
        api.patch_institution(
            inst["id"],
            {"expected_institution_version": inst_now["version"], "repository_participation": "OPT_OUT"},
            ADMIN,
        )
    )
    assert patched["comparable_submission_count"] == 0
    deps, _ = validate_paginated(api.list_deposits_of_submission(sub["id"], INST_ADMIN))
    assert deps[0]["deposit_state"] == "QUARANTINED"

    restored = validate_success(
        api.patch_institution(
            inst["id"],
            {"expected_institution_version": patched["version"], "repository_participation": "GLOBAL_SHARED"},
            ADMIN,
        )
    )
    assert restored["comparable_submission_count"] == 1
    deps, _ = validate_paginated(api.list_deposits_of_submission(sub["id"], INST_ADMIN))
    assert deps[0]["deposit_state"] == "STORED", "cycle edge QUARANTINED -> STORED on restore"


def test_consent_withdraw_quarantines_student_deposits(api):
    """PRD §3.2: "when a student moves to `WITHDRAWN`, every `RepositoryDeposit`
    belonging to that student's submissions that is currently `STORED` flips to
    `QUARANTINED`, and each such quarantine recomputes the owning institution's
    `comparable_submission_count`." PRD §3.2: "consent-quarantined deposits do
    not come back when participation settings later change, and they are
    re-stored only if the student grants consent again through the normal
    transition rules (a re-grant moves consent state, but quarantined deposits
    stay quarantined unless separately restored by the participation-reversal
    cascade, which they are not eligible for)"

    Design: Corner/cross_cutting_layers/consent_withdraw_quarantines_student_deposits
    """
    inst, integ, instr, student, asg = setup_basic_scenario(
        "US",
        inst_overrides={"repository_participation": "GLOBAL_SHARED"},
        assignment_overrides={"repository_option": "STORE_AND_COMPARE"},
    )
    sub = submit(asg["id"], student["id"], "withdraw body")
    process(sub["id"], instr["id"])
    assert _inst_count(api, inst["id"]) == 1

    # read the student's current version via the students list
    data, _ = validate_paginated(api.list_students(inst["id"], INST_ADMIN))
    sv = [s for s in data if s["id"] == student["id"]][0]["version"]
    st3 = withdraw_consent(student["id"], sv)

    deps, _ = validate_paginated(api.list_deposits_of_submission(sub["id"], INST_ADMIN))
    assert deps[0]["deposit_state"] == "QUARANTINED"
    assert _inst_count(api, inst["id"]) == 0

    grant_consent(student["id"], st3["version"])
    deps, _ = validate_paginated(api.list_deposits_of_submission(sub["id"], INST_ADMIN))
    assert deps[0]["deposit_state"] == "QUARANTINED", (
        "consent-quarantined deposits do not auto-reinstate on re-grant"
    )


def test_supersede_withdraws_prior_deposit(api):
    """PRD §3.4: "Supersession also cascades into the repository: any
    `RepositoryDeposit` of the superseded submission that is currently `STORED`
    flips to `WITHDRAWN`, and the institution's `comparable_submission_count` is
    recomputed."

    Design: Corner/cross_cutting_layers/supersede_withdraws_prior_deposit
    """
    inst, integ, instr, student, asg = setup_basic_scenario(
        "US",
        inst_overrides={"repository_participation": "GLOBAL_SHARED"},
        assignment_overrides={"repository_option": "STORE_AND_COMPARE"},
    )
    sub1 = submit(asg["id"], student["id"], "supersede v1")
    process(sub1["id"], instr["id"])
    assert _inst_count(api, inst["id"]) == 1

    sub2 = submit(asg["id"], student["id"], "supersede v2", supersedes_submission_id=sub1["id"])

    deps, _ = validate_paginated(api.list_deposits_of_submission(sub1["id"], INST_ADMIN))
    assert deps[0]["deposit_state"] == "WITHDRAWN"
    assert _inst_count(api, inst["id"]) == 0, "count returns to 0 until sub2 is processed"

    s1 = validate_success(api.get_submission(sub1["id"], make_instructor_headers(instr["id"])))
    s2 = validate_success(api.get_submission(sub2["id"], make_instructor_headers(instr["id"])))
    assert s1["pipeline_state"] == "SUPERSEDED"
    assert s2["pipeline_state"] == "RECEIVED"


def test_resubmit_supersede_conserves_submission_count(api):
    """PRD §3.4: "A resubmission — one carrying `supersedes_submission_id` —
    gets `revision_number` equal to the prior revision's number plus one, and
    the prior submission is transitioned to `SUPERSEDED` (its `version`
    increments) as part of the same intake." PRD §3.4: "Either way, the
    assignment's `submission_count` is recomputed after intake; that counter
    always equals the number of the assignment's submissions whose
    `pipeline_state` is not `SUPERSEDED`, so a resubmission leaves the count
    unchanged (one enters `RECEIVED`, one leaves to `SUPERSEDED`)."

    Design: Difficulty/compensating_invariant/resubmit_supersede_conserves_submission_count
    """
    inst, integ, instr, student, asg = setup_basic_scenario("US")
    sub1 = submit(asg["id"], student["id"], "first revision")
    process(sub1["id"], instr["id"])

    sub2 = submit(asg["id"], student["id"], "second revision body",
                  supersedes_submission_id=sub1["id"])
    assert sub2["revision_number"] == 2
    assert sub2["supersedes_submission_id"] == sub1["id"]

    asg_after = validate_success(api.get_assignment(asg["id"], make_instructor_headers(instr["id"])))
    assert asg_after["submission_count"] == 1, "resubmission leaves the count unchanged"

    s1 = validate_success(api.get_submission(sub1["id"], make_instructor_headers(instr["id"])))
    assert s1["pipeline_state"] == "SUPERSEDED"


def test_resubmit_reverse_lookup_by_supersedes(api):
    """PRD §4: "GET /integrity/submissions | List submissions with optional
    `student_id` / `supersedes_submission_id` filters" PRD §3.4: "the prior
    submission is transitioned to `SUPERSEDED` (its `version` increments) as
    part of the same intake."

    Design: Difficulty/compensating_invariant/resubmit_supersede_conserves_submission_count
    """
    inst, integ, instr, student, asg = setup_basic_scenario("US")
    sub1 = submit(asg["id"], student["id"], "first revision")
    process(sub1["id"], instr["id"])
    sub2 = submit(asg["id"], student["id"], "second revision body",
                  supersedes_submission_id=sub1["id"])

    data, meta = validate_paginated(
        api.list_submissions(make_instructor_headers(instr["id"]),
                             params={"supersedes_submission_id": sub1["id"]})
    )
    assert [s["id"] for s in data] == [sub2["id"]], "self-referential FK reverse lookup"


def test_institution_only_deposit_scope_not_counted(api):
    """PRD §3.6: "Its `scope` is `GLOBAL_SHARED` exactly when the institution's
    `repository_participation` is `GLOBAL_SHARED`, and `INSTITUTION_ONLY`
    otherwise." PRD §3.6: "it always equals the number of the institution's
    deposits that are simultaneously in `deposit_state` `STORED` and `scope`
    `GLOBAL_SHARED`."

    Design: Difficulty/compensating_invariant/deposit_create_withdraw_conserve_comparable_count
    """
    inst, integ, instr, student, asg = setup_basic_scenario(
        "US",
        inst_overrides={"repository_participation": "INSTITUTION_ONLY"},
        assignment_overrides={"repository_option": "STORE_AND_COMPARE"},
    )
    sub = submit(asg["id"], student["id"], "institution only body")
    process(sub["id"], instr["id"])

    deps, _ = validate_paginated(api.list_deposits_of_submission(sub["id"], INST_ADMIN))
    assert deps[0]["deposit_state"] == "STORED"
    assert deps[0]["scope"] == "INSTITUTION_ONLY"
    # STORED but not GLOBAL_SHARED -> not counted
    assert _inst_count(api, inst["id"]) == 0
