"""Role gating, peer ownership and the two segregation-of-duties rules.

Each refusal is paired with the identical call from the entitled caller, so the
test proves the rejection was about who called and not about what was asked.
"""

from test_helpers import (
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import MAX_DOGS_PER_JUDGE_PER_DAY, SETUP_CLOCK_INSTANT
from test_helpers.factories import (
    assign_judge_payload,
    create_entry_payload,
    create_panel_slot_payload,
    create_protest_payload,
    decide_protest_payload,
    respond_to_slot_payload,
)
from test_helpers.fixtures import (
    apply_for_show,
    approve_show,
    attach_judge,
    begin_review,
    confirmed_slot,
    offer_class,
    propose_slot,
    read_class,
    read_entry,
    read_judge,
    read_judge_version,
    read_protest,
    read_show,
    read_slot,
    register_club,
    register_handler,
    register_judge,
    set_clock,
    setup_completed_class,
    setup_show_with_class,
    submit_show,
)
from test_helpers.test_users import (
    SANCTION_OFFICER_ID,
    make_club_officer_headers,
    make_handler_headers,
    make_judge_headers,
    make_registry_officer_headers,
    make_sanction_officer_headers,
    make_show_secretary_headers,
)


def test_handler_cannot_confirm_its_own_entry_but_the_secretary_can():
    """Confirmation is the secretary's act even for the handler who filed it.

    PRD 4: "| POST | `/dog-shows/entries/{id}/confirm` | The show secretary
    confirms an entry, minting its armband and assessing the provisional fee. |
    `ShowSecretary` |"

    PRD 2.9 rung 2: "`X-User-Role` names one of `ClubOfficer`, `SanctionOfficer`,
    `ShowSecretary`, `Judge`, `Handler`, `RegistryOfficer`, and that role is listed
    for the endpoint being called, else `ERR_ROLE_NOT_PERMITTED`."

    Design: Corner/rbac/handler_cannot_confirm_its_own_entry_but_the_secretary_can
    """
    context = setup_show_with_class(num_dogs=1, num_entries=1)
    entry, handler = context["entries"][0], context["handler"]

    refused = api_client.confirm_entry(
        entry["id"], make_handler_headers(handler["id"])
    )
    validate_error(refused, "ERR_ROLE_NOT_PERMITTED", 403)

    untouched = read_entry(entry)
    assert untouched["entry_status"] == "RECEIVED"
    assert untouched["armband_number"] is None

    confirmed = validate_success(
        api_client.confirm_entry(entry["id"], make_show_secretary_headers()), 200
    )
    assert confirmed["entry_status"] == "CONFIRMED"
    assert confirmed["armband_number"] == 1
    assert confirmed["entry_fee_cents"] == 4663


def test_judge_cannot_propose_a_panel_slot_for_itself_but_the_secretary_can():
    """A judge answers invitations and never issues them.

    PRD 4: "| POST | `/dog-shows/panel-slots` | Propose a panel slot inviting a
    judge onto a show's panel. Pins the judge's version for optimistic
    concurrency. | `ShowSecretary` |"

    PRD 3.3: "A successful proposal is created with `slot_status` `PROPOSED`,
    `responded_at` and `decline_reason` null, `assigned_class_count` 0, and
    `assigned_dog_capacity` set to the smaller of the judge's `max_daily_dog_count`
    and the system-wide ceiling of 175 dogs per judge per day."

    Design: Corner/rbac/judge_cannot_propose_a_panel_slot_for_itself_but_the_secretary_can
    """
    set_clock(SETUP_CLOCK_INSTANT)
    club = register_club()
    judge = register_judge()
    show = apply_for_show(club)
    submit_show(show, club)
    approve_show(show)
    judge_version = read_judge_version(judge)

    refused = api_client.create_panel_slot(
        create_panel_slot_payload(show["id"], judge["id"], judge_version),
        make_judge_headers(judge["id"]),
    )
    validate_error(refused, "ERR_ROLE_NOT_PERMITTED", 403)
    assert read_judge(judge)["version"] == judge_version

    slot = validate_success(
        api_client.create_panel_slot(
            create_panel_slot_payload(show["id"], judge["id"], judge_version),
            make_show_secretary_headers(),
        ),
        201,
    )
    assert slot["slot_status"] == "PROPOSED"
    assert slot["assigned_class_count"] == 0
    assert slot["assigned_dog_capacity"] == MAX_DOGS_PER_JUDGE_PER_DAY


def test_handler_cannot_enter_a_dog_under_another_handlers_id():
    """Handlers are peers, so the role alone never carries an entry.

    PRD 2.9 rung 6: "For an entity-backed role, `X-User-ID` equals the identifier
    of the entity the operation acts for, else `ERR_NOT_RESOURCE_OWNER`. This
    applies to show-application creation, show submission, panel-slot response,
    entry creation, season declaration, protest filing and evidence resubmission."

    PRD 3.5: "A handler enters a dog by naming the `show_id`, the `class_id`, the
    `dog_id` and its own `handler_id`, which must equal the caller's identifier."

    Design: Corner/rbac/handler_cannot_enter_a_dog_under_another_handlers_id
    """
    context = setup_show_with_class(num_dogs=1, num_entries=0)
    show, klass, dog, owner = (
        context["show"], context["klass"], context["dogs"][0], context["handler"]
    )
    stranger = register_handler(handler_name="Bo Trent", member_number="M-1002")

    refused = api_client.create_entry(
        create_entry_payload(show["id"], klass["id"], dog["id"], stranger["id"]),
        make_handler_headers(owner["id"]),
    )
    validate_error(refused, "ERR_NOT_RESOURCE_OWNER", 403)

    accepted = validate_success(
        api_client.create_entry(
            create_entry_payload(show["id"], klass["id"], dog["id"], owner["id"]),
            make_handler_headers(owner["id"]),
        ),
        201,
    )
    assert accepted["handler_id"] == owner["id"]
    assert accepted["entry_status"] == "RECEIVED"

    _, meta = validate_paginated(
        api_client.list_entries(
            make_show_secretary_headers(), {"handler_id": stranger["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_judge_cannot_answer_another_judges_panel_invitation():
    """Two licensed judges, and only the slot's own judge may answer it.

    PRD 3.3: "The invited judge answers with a `decision` of either `ACCEPT` or
    `DECLINE`, and may only answer a slot whose `judge_id` is the judge's own
    identifier."

    PRD 2.9 rung 6: "For an entity-backed role, `X-User-ID` equals the identifier
    of the entity the operation acts for, else `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/judge_cannot_answer_another_judges_panel_invitation
    """
    set_clock(SETUP_CLOCK_INSTANT)
    club = register_club()
    invited = register_judge()
    bystander = register_judge(judge_number="J-78", full_name="Vera Lund")
    show = apply_for_show(club)
    submit_show(show, club)
    approve_show(show)
    slot = propose_slot(show, invited)

    refused = api_client.respond_to_panel_slot(
        slot["id"], respond_to_slot_payload("ACCEPT"),
        make_judge_headers(bystander["id"]),
    )
    validate_error(refused, "ERR_NOT_RESOURCE_OWNER", 403)
    assert read_slot(slot)["slot_status"] == "PROPOSED"

    accepted = validate_success(
        api_client.respond_to_panel_slot(
            slot["id"], respond_to_slot_payload("ACCEPT"),
            make_judge_headers(invited["id"]),
        ),
        200,
    )
    assert accepted["slot_status"] == "CONFIRMED"
    assert read_judge(invited)["confirmed_slot_count"] == 1
    assert read_judge(bystander)["confirmed_slot_count"] == 0


def test_officer_who_approved_the_show_cannot_decide_its_protest():
    """The bar is keyed on the stored caller identifier, not on the role.

    PRD 3.9: "A decision closes the hearing, and the deciding officer must not be
    the officer recorded in the show's `approved_by_user_id`."

    PRD 3.9: "Note that opening a hearing does *not* write `reviewed_by_user_id`;
    that field records the officer who ultimately decides."

    Design: Corner/rbac/officer_who_approved_the_show_cannot_decide_its_protest
    """
    context = setup_completed_class(num_dogs=2)
    assert read_show(context["show"])["approved_by_user_id"] == SANCTION_OFFICER_ID
    target = context["entries"][1]
    filed = validate_success(
        api_client.create_protest(
            create_protest_payload(
                context["show"]["id"], target["id"], context["handler"]["id"]
            ),
            make_handler_headers(context["handler"]["id"]),
        ),
        201,
    )
    protest = begin_review(filed, SANCTION_OFFICER_ID)

    refused = api_client.decide_protest(
        protest["id"], decide_protest_payload("UPHOLD", "VACATE_PLACEMENT"),
        make_sanction_officer_headers(SANCTION_OFFICER_ID),
    )
    validate_error(refused, "ERR_SEGREGATION_CONFLICT", 403)

    unchanged = read_protest(protest)
    assert unchanged["status"] == "UNDER_REVIEW"
    assert unchanged["review_round"] == 1
    assert unchanged["reviewed_by_user_id"] is None
    assert unchanged["decided_at"] is None

    entry = read_entry(target)
    assert entry["placement"] == 2
    assert entry["entry_status"] == "JUDGED"


def test_judge_of_a_feeder_breed_class_cannot_take_its_parent_group_class():
    """The conflict is structural: the same judge already has the feeder class.

    PRD 2.9 rung 7: "Segregation of duties holds, else
    `ERR_SEGREGATION_CONFLICT`: the caller identifier recorded in a show's
    `approved_by_user_id` may not decide a protest on that show, and a judge whose
    panel slot is assigned to a feeder class may not have a slot assigned to the
    class named by that feeder's `parent_class_id`."

    Design: Corner/rbac/judge_of_a_feeder_breed_class_cannot_take_its_parent_group_class
    """
    set_clock(SETUP_CLOCK_INSTANT)
    club = register_club()
    judge = register_judge()
    show = apply_for_show(club)
    submit_show(show, club)
    approve_show(show)

    breed_slot = confirmed_slot(show, judge, panel_role="BREED_JUDGE")
    group_class = offer_class(show, class_level="GROUP")
    breed_class = attach_judge(
        offer_class(show, parent_class_id=group_class["id"]), breed_slot
    )
    group_slot = confirmed_slot(show, judge, panel_role="GROUP_JUDGE")

    refused = api_client.assign_judge_to_class(
        group_class["id"], assign_judge_payload(group_slot["id"]),
        make_show_secretary_headers(),
    )
    validate_error(refused, "ERR_SEGREGATION_CONFLICT", 403)

    unchanged_class = read_class(group_class)
    assert unchanged_class["assigned_slot_id"] is None
    assert unchanged_class["status"] == "OPEN"

    unchanged_slot = read_slot(group_slot)
    assert unchanged_slot["assigned_class_count"] == 0
    assert unchanged_slot["slot_status"] == "CONFIRMED"
    assert read_class(breed_class)["assigned_slot_id"] == breed_slot["id"]


def test_every_declared_role_can_read_the_show():
    """A read is shared by all six roles and never narrowed by identity.

    PRD 4: "| GET | `/dog-shows/shows/{id}` | Read one show with its ledger, heat
    advisory and version. | `SanctionOfficer`, `ClubOfficer`, `ShowSecretary`,
    `Judge`, `Handler`, `RegistryOfficer` |"

    PRD 2.9 rung 2: "`X-User-Role` names one of `ClubOfficer`, `SanctionOfficer`,
    `ShowSecretary`, `Judge`, `Handler`, `RegistryOfficer`, and that role is listed
    for the endpoint being called, else `ERR_ROLE_NOT_PERMITTED`."

    Design: Corner/rbac/every_declared_role_can_read_the_show
    """
    set_clock(SETUP_CLOCK_INSTANT)
    club = register_club()
    judge = register_judge()
    handler = register_handler()
    show = apply_for_show(club)
    submit_show(show, club)
    approve_show(show)

    for headers in (
        make_club_officer_headers(club["id"]),
        make_sanction_officer_headers(),
        make_show_secretary_headers(),
        make_judge_headers(judge["id"]),
        make_handler_headers(handler["id"]),
        make_registry_officer_headers(),
    ):
        role = headers["X-User-Role"]
        response = api_client.get_show(show["id"], headers)
        body = response.json()
        assert body["response_type"] == "object", (
            f"{role} must receive an object envelope, got {body['response_type']}"
        )
        row = validate_success(response, 200)
        assert row["id"] == show["id"], f"{role} must read the same show"
        assert row["status"] == "APPROVED"
        assert row["show_name"] == "Autumn Classic"
        assert row["approved_by_user_id"] == SANCTION_OFFICER_ID
