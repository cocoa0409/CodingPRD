"""Creation-time defaults, echoed reads, and the immediate visibility of every written fact."""
from test_helpers import NON_EXISTENT_UUID, is_valid_uuid
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.api_client import api_client, instants_equal
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import REQUIRED_INCLUSION_ITEM_CODES
from test_helpers.test_users import COORD, ED, ED_PHYSICIAN_USER_ID

CLOCK = "2026-09-01T08:00:00Z"
LKW = "2026-09-01T07:40:00Z"
IMAGING = "2026-09-01T08:10:00Z"


def _center_payload(name, facility_type="SPOKE", **extra):
    """The four caller-supplied inputs of a facility registration and nothing else."""
    payload = {
        "name": name,
        "facility_type": facility_type,
        "state_code": "CA",
        "ems_region_code": "CA-R1",
    }
    payload.update(extra)
    return payload


def _register(payload):
    return validate_success(api_client.register_stroke_center(payload, COORD), 201)


def _case_payload(center_id, **extra):
    """A code stroke activation body carrying every required field explicitly."""
    payload = {
        "center_id": center_id,
        "patient_ref": "P-CORNER-06",
        "door_at": CLOCK,
        "lkw_precision": "EXACT",
        "last_known_well_at": LKW,
        "arrival_mode": "EMS",
    }
    payload.update(extra)
    return payload


def _cases_at(center_id):
    data, meta = validate_paginated(
        api_client.list_code_strokes(ED, {"center_id": center_id, "limit": 100, "offset": 0})
    )
    return data, meta


def test_stroke_center_creation_applies_every_declared_default():
    """Four caller inputs come back with all eleven server-seeded fields already resolved.

    PRD 3.1: "`certification_status` begins at `PROVISIONAL`, both `ct_scanner_ready` and `video_cart_ready` begin true, `equipment_readiness_posture` therefore begins `READY`, `open_case_count` begins 0, and `ems_routing_posture` is derived on the spot — which for a provisional, fully ready facility with no open cases is `ROUTINE`"
    PRD 3.1: "Three fields begin null: `public_dtn_compliance_pct`, `public_report_published_at` and `suspension_reason`. The `consecutive_denied_report_count` begins 0."
    PRD 2.6: "a center whose `public_dtn_compliance_pct` is null has never published a report, which is a different fact from a center that published `0.0`"

    Design: Corner/entities/stroke_center_creation_applies_every_declared_default
    """
    fx.set_clock(CLOCK)
    payload = _center_payload("Lakeside Regional Primary Stroke Center", "HUB_PRIMARY")

    center = _register(payload)

    a.assert_stroke_center(center)
    for field, value in payload.items():
        assert center[field] == value, (
            f"{field} is echoed back unchanged, got {center[field]!r}"
        )
    assert center["certification_status"] == "PROVISIONAL", (
        f"a new facility is provisional, got {center['certification_status']}"
    )
    assert center["ct_scanner_ready"] is True, (
        f"the CT scanner begins ready, got {center['ct_scanner_ready']!r}"
    )
    assert center["video_cart_ready"] is True, (
        f"the video cart begins ready, got {center['video_cart_ready']!r}"
    )
    assert center["equipment_readiness_posture"] == "READY", (
        "two ready components derive a READY posture, got "
        f"{center['equipment_readiness_posture']}"
    )
    assert center["open_case_count"] == 0, (
        f"no case exists yet, got {center['open_case_count']}"
    )
    assert center["ems_routing_posture"] == "ROUTINE", (
        "provisional, fully ready and idle routes routinely, got "
        f"{center['ems_routing_posture']}"
    )
    assert center["public_dtn_compliance_pct"] is None, (
        "an unpublished facility carries null rather than 0.0, got "
        f"{center['public_dtn_compliance_pct']!r}"
    )
    assert center["public_report_published_at"] is None, (
        f"nothing has been published, got {center['public_report_published_at']!r}"
    )
    assert center["suspension_reason"] is None, (
        f"a new facility is not suspended, got {center['suspension_reason']!r}"
    )
    assert center["consecutive_denied_report_count"] == 0, (
        f"the denial streak begins at zero, got {center['consecutive_denied_report_count']}"
    )
    assert is_valid_uuid(center["id"]), f"the id is a server-minted UUID, got {center['id']!r}"
    assert center["version"] == 1, f"creation lands at version 1, got {center['version']}"
    assert instants_equal(center["created_at"], CLOCK), (
        f"created_at is the logical clock at the write, got {center['created_at']}"
    )
    assert instants_equal(center["updated_at"], center["created_at"]), (
        f"an unmutated record has updated_at == created_at, got {center['updated_at']}"
    )


def test_get_stroke_center_returns_the_stored_row_unchanged():
    """Two reads either side of a clock advance return the creation response byte for byte.

    PRD 2.5: "`version` (integer): a monotonically increasing counter that begins at 1 on creation and increments by exactly 1 on every mutation of that record."
    PRD 2.5: "`updated_at` (string): an ISO 8601 UTC instant with three fractional digits, refreshed on every mutation of the record"
    PRD 2.4: "it is the one endpoint outside the `/stroke-network` mount, exposed at `POST /_clock/set_current_utc`, it returns HTTP 200, and it mutates no entity"

    Design: Corner/entities/get_stroke_center_returns_the_stored_row_unchanged
    """
    fx.set_clock(CLOCK)
    payload = _center_payload("Northgate Community Spoke")
    created = _register(payload)

    first = validate_success(api_client.get_stroke_center(created["id"], COORD))

    assert first == created, (
        "the read returns exactly the row the create returned; "
        f"created {created} read {first}"
    )
    assert first["name"] == payload["name"], (
        f"the stored name is the supplied one, got {first['name']!r}"
    )
    assert first["facility_type"] == "SPOKE"
    assert first["state_code"] == "CA"
    assert first["version"] == 1, f"a read is not a mutation, got version {first['version']}"

    fx.set_clock("2026-09-01T09:30:00Z")
    second = validate_success(api_client.get_stroke_center(created["id"], COORD))

    assert second == first, (
        f"advancing the clock changes no stored field; before {first} after {second}"
    )
    assert second["version"] == 1, (
        f"neither the clock call nor the reads bumped the version, got {second['version']}"
    )
    assert instants_equal(second["updated_at"], created["created_at"]), (
        "updated_at still records the creation instant because nothing mutated the row, got "
        f"{second['updated_at']}"
    )


PAGE_REGION = "CA-P6ENT"


def _three_ordered_centers():
    """Three facilities in one private EMS region, registered one minute apart."""
    fx.set_clock("2026-09-01T08:00:00Z")
    first = _register(
        _center_payload("Paged Region Hub", "HUB_PRIMARY", ems_region_code=PAGE_REGION)
    )
    fx.set_clock("2026-09-01T08:01:00Z")
    second = _register(
        _center_payload("Paged Region Spoke", "SPOKE", ems_region_code=PAGE_REGION)
    )
    fx.set_clock("2026-09-01T08:02:00Z")
    third = _register(
        _center_payload(
            "Paged Region Thrombectomy", "THROMBECTOMY_CAPABLE", ems_region_code=PAGE_REGION
        )
    )
    return first, second, third


def test_list_stroke_centers_paginates_with_total_count_and_has_more():
    """The window shows two of three, then the tail, and a second filter narrows to one.

    PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the size of the full filtered result set before the page window is applied and `has_more` indicates whether records remain beyond the current window."
    PRD 2.3: "Unless a specific endpoint says otherwise, list results are ordered by `created_at` ascending."
    PRD 2.3: "Filter parameters offered by a list endpoint combine conjunctively — a request that supplies two filters returns only records matching both."

    Design: Corner/entities/list_stroke_centers_paginates_with_total_count_and_has_more
    """
    first, second, third = _three_ordered_centers()

    page, meta = validate_paginated(
        api_client.list_stroke_centers(
            COORD, {"ems_region_code": PAGE_REGION, "limit": 2, "offset": 0}
        )
    )

    assert [row["id"] for row in page] == [first["id"], second["id"]], (
        "the first window holds the two earliest created_at values, got "
        f"{[row['name'] for row in page]}"
    )
    assert meta["total_count"] == 3, (
        f"the count is the whole filtered set, not the window, got {meta['total_count']}"
    )
    assert meta["has_more"] is True, (
        f"one record remains beyond the window, got {meta['has_more']!r}"
    )
    assert meta["limit"] == 2, f"the requested limit is echoed, got {meta['limit']}"
    assert meta["offset"] == 0, f"the requested offset is echoed, got {meta['offset']}"

    tail, tail_meta = validate_paginated(
        api_client.list_stroke_centers(
            COORD, {"ems_region_code": PAGE_REGION, "limit": 2, "offset": 2}
        )
    )

    assert [row["id"] for row in tail] == [third["id"]], (
        f"the second window holds only the newest facility, got {len(tail)} rows"
    )
    assert tail_meta["total_count"] == 3, (
        f"the count does not shrink with the window, got {tail_meta['total_count']}"
    )
    assert tail_meta["has_more"] is False, (
        f"nothing remains past the third record, got {tail_meta['has_more']!r}"
    )

    narrowed, narrowed_meta = validate_paginated(
        api_client.list_stroke_centers(
            COORD,
            {"ems_region_code": PAGE_REGION, "facility_type": "SPOKE", "limit": 10, "offset": 0},
        )
    )

    assert [row["id"] for row in narrowed] == [second["id"]], (
        "both filters must hold, so only the spoke of that region survives, got "
        f"{[row['name'] for row in narrowed]}"
    )
    assert narrowed_meta["total_count"] == 1, (
        f"the filtered count precedes the window, got {narrowed_meta['total_count']}"
    )
    assert narrowed_meta["has_more"] is False


def test_get_unknown_center_id_returns_center_not_found():
    """A well-formed but unused UUID in the path answers with the collection's own 404.

    PRD 2.11: "Every `id` appearing in a URL path must reference an existing record of the addressed collection, returning that collection's own not-found code: `ERR_CENTER_NOT_FOUND`"
    PRD 2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."

    Design: Corner/entities/get_unknown_center_id_returns_center_not_found
    """
    fx.set_clock(CLOCK)
    live = _register(_center_payload("Bystander Community Spoke"))

    response = api_client.get_stroke_center(NON_EXISTENT_UUID, COORD)

    error = validate_error(response, ApiErrorId.ERR_CENTER_NOT_FOUND.value, 404)
    body = response.json()
    assert body["response_type"] == "error", (
        f"a failed read answers in the error envelope, got {body['response_type']!r}"
    )
    assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}, (
        f"the error meta carries no pagination or other keys, got {sorted(body['meta'])}"
    )
    assert set(error) == {"error_id", "message"}, (
        f"the error data holds exactly the identifier and the message, got {sorted(error)}"
    )
    assert isinstance(error["message"], str) and error["message"], (
        f"the message is a non-empty human-readable string, got {error['message']!r}"
    )

    survivor = validate_success(api_client.get_stroke_center(live["id"], COORD))
    assert survivor["version"] == 1, (
        f"the failed read leaves the real facility alone, got version {survivor['version']}"
    )


def test_code_stroke_activation_omitting_arrival_mode_is_refused():
    """A body missing one required field fails on shape before anything is written.

    PRD 2.11: "The body must contain every required input field of the endpoint with the declared JSON type, must not contain unknown fields, and every datetime field must be a well-formed ISO 8601 UTC instant — `ERR_INVALID_REQUEST` (422)."
    PRD 3.2: "The activation payload names the facility through `center_id`, carries a de-identified `patient_ref` (non-empty, at most 40 characters), the ED arrival instant `door_at` that anchors both clinical clocks, an `arrival_mode` of `EMS`, `WALK_IN` or `INTERFACILITY_TRANSFER`"
    PRD 3.2: "It then cascades to the facility: `open_case_count` rises by 1 and `ems_routing_posture` is re-derived"

    Design: Corner/entities/code_stroke_activation_omitting_arrival_mode_is_refused
    """
    fx.set_clock(CLOCK)
    center = _register(_center_payload("Arrival Mode Community Spoke"))
    payload = _case_payload(center["id"])
    del payload["arrival_mode"]

    response = api_client.activate_code_stroke(payload, ED)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    cases, meta = _cases_at(center["id"])
    assert cases == [], f"no case row was written, got {len(cases)}"
    assert meta["total_count"] == 0, (
        f"the facility has no cases at all, got {meta['total_count']}"
    )

    after = validate_success(api_client.get_stroke_center(center["id"], COORD))
    assert after["open_case_count"] == 0, (
        f"the refused activation never reached the facility cascade, got {after['open_case_count']}"
    )
    assert after["ems_routing_posture"] == "ROUTINE", (
        f"the posture was not re-derived, got {after['ems_routing_posture']}"
    )
    assert after["version"] == 1, (
        f"the facility was not mutated, got version {after['version']}"
    )


def test_spoke_agreement_creation_defaults_to_draft_with_no_credentials():
    """A fresh agreement is unusable until activated and carries an empty credential array.

    PRD 3.1: "A newly created agreement lands in `DRAFT` with an empty `proxy_credentials` array, an `active_consult_count` of 0 and a null `suspension_reason`."
    PRD 2.4: "Caller-supplied instants such as a case's `door_at`, a checklist-independent last-known-well capture, an agreement's `effective_from` and `effective_until`, a report's `period_start` and `period_end`, a proxy credential's `expires_at` and a video session's `started_at` and `ended_at` are taken as given"

    Design: Corner/entities/spoke_agreement_creation_defaults_to_draft_with_no_credentials
    """
    fx.set_clock(CLOCK)
    hub = _register(_center_payload("Agreement Hub Primary", "HUB_PRIMARY"))
    spoke = _register(_center_payload("Agreement Community Spoke"))
    payload = f.spoke_agreement_payload(hub["id"], spoke["id"])

    agreement = validate_success(api_client.create_spoke_agreement(payload, COORD), 201)

    a.assert_spoke_agreement(agreement)
    assert agreement["status"] == "DRAFT", (
        f"creation lands in draft, not active, got {agreement['status']}"
    )
    assert agreement["proxy_credentials"] == [], (
        f"no credential is granted by creation, got {agreement['proxy_credentials']!r}"
    )
    assert agreement["active_consult_count"] == 0, (
        f"a draft agreement carries no load, got {agreement['active_consult_count']}"
    )
    assert agreement["suspension_reason"] is None, (
        f"a draft is not a suspension, got {agreement['suspension_reason']!r}"
    )
    for field, value in payload.items():
        assert agreement[field] == value, (
            f"{field} is stored as supplied, got {agreement[field]!r}"
        )
    assert agreement["version"] == 1, (
        f"creation lands at version 1, got {agreement['version']}"
    )
    assert instants_equal(agreement["created_at"], CLOCK), (
        f"created_at reads the logical clock, got {agreement['created_at']}"
    )


def test_checklist_screening_score_is_recomputed_on_every_inclusion_item():
    """Each of the four confirmations lands 15.0 more points on the row that instant.

    PRD 3.5: "a `screening_eligibility_score` of 0.00, and a null `attested_eligibility_score`, `override_justification`, `determined_at`, `overridden_by_neurologist_id` and `last_amendment_note`"
    PRD 3.5: "The **screening** variant is 15.0 points for each confirmed inclusion item, minus 12.0 for each relative contraindication, minus 100.0 for each absolute contraindication. It is recomputed on every inclusion-item and contraindication write and stored in `screening_eligibility_score`."
    PRD 3.5: "The code is appended, `confirmed_inclusion_item_count` is recomputed as the array's length, and `documentation_status` moves from `NOT_STARTED` to `IN_PROGRESS`."
    PRD 3.5: "It is computed only at determination and stored in `attested_eligibility_score`."

    Design: Corner/entities/checklist_screening_score_is_recomputed_on_every_inclusion_item
    """
    fx.set_clock(CLOCK)
    center = _register(_center_payload("Screening Score Community Spoke"))
    case = fx.activate_case(center["id"], CLOCK, last_known_well_at=LKW)

    checklist = validate_success(
        api_client.create_checklist(f.checklist_payload(case["id"]), ED), 201
    )

    a.assert_thrombolytic_checklist(checklist)
    assert checklist["screening_eligibility_score"] == 0.00, (
        f"an empty checklist screens at zero, got {checklist['screening_eligibility_score']}"
    )
    assert checklist["attested_eligibility_score"] is None, (
        f"nothing has been attested yet, got {checklist['attested_eligibility_score']!r}"
    )
    assert checklist["documentation_status"] == "NOT_STARTED", (
        f"documentation has not begun, got {checklist['documentation_status']}"
    )
    assert checklist["determination_status"] == "PENDING"
    assert checklist["confirmed_inclusion_item_codes"] == []
    assert checklist["confirmed_inclusion_item_count"] == 0

    seen = []
    updated = checklist
    for index, code in enumerate(REQUIRED_INCLUSION_ITEM_CODES, start=1):
        updated = validate_success(
            api_client.confirm_inclusion_item(
                checklist["id"], f.inclusion_item_payload(code), ED
            )
        )
        seen.append(code)
        expected = a.expected_screening_score(index, 0, 0)
        assert updated["confirmed_inclusion_item_codes"] == seen, (
            "the code is appended in confirmation order, got "
            f"{updated['confirmed_inclusion_item_codes']}"
        )
        assert updated["confirmed_inclusion_item_count"] == index, (
            f"the count is the array length, got {updated['confirmed_inclusion_item_count']}"
        )
        assert updated["screening_eligibility_score"] == expected == 15.0 * index, (
            f"{index} items score {15.0 * index}, got {updated['screening_eligibility_score']}"
        )
        a.assert_two_decimal_places(
            updated["screening_eligibility_score"], "screening_eligibility_score"
        )
        assert updated["documentation_status"] == "IN_PROGRESS", (
            f"the first write moves documentation forward, got {updated['documentation_status']}"
        )
        assert updated["attested_eligibility_score"] is None, (
            "a documentation write never computes the attested variant, got "
            f"{updated['attested_eligibility_score']!r}"
        )
        assert updated["determination_status"] == "PENDING", (
            f"the verdict dimension does not move, got {updated['determination_status']}"
        )

    assert updated["screening_eligibility_score"] == 60.00, (
        f"four items and no contraindications screen at 60.00, got "
        f"{updated['screening_eligibility_score']}"
    )


def test_code_stroke_case_system_fields_are_generated_not_supplied():
    """The id, the version, the activation stamp and the operator all come from the server.

    PRD 2.5: "`id` (string): a server-minted UUID. It carries no type prefix and no embedded meaning"
    PRD 2.4: "server-assigned instants such as `activation_at`, `imaging_at`, `needle_at`, `requested_at`, `assigned_at`, `accepted_at`, `completed_at`, `determined_at`, `proposed_at`, `handoff_completed_at`, `submitted_at`, `decided_at`, `published_at`, `granted_at`, `recorded_at` and `public_report_published_at` are always the logical clock as it stands at the moment the write is applied"
    PRD 2.4: "Caller-supplied instants such as a case's `door_at`, a checklist-independent last-known-well capture, an agreement's `effective_from` and `effective_until`, a report's `period_start` and `period_end`, a proxy credential's `expires_at` and a video session's `started_at` and `ended_at` are taken as given"
    PRD 3.2: "The server stamps `activation_at` from the logical clock, records the acting operator as `activated_by_user_id`, sets `status` to `ACTIVATED`, sets `disposition` to `PENDING`, sets `deviation_count` to 0"

    Design: Corner/entities/code_stroke_case_system_fields_are_generated_not_supplied
    """
    fx.set_clock(CLOCK)
    center = _register(_center_payload("System Fields Community Spoke"))
    activation_at = "2026-09-01T08:30:00Z"
    fx.set_clock(activation_at)
    payload = _case_payload(center["id"])

    case = validate_success(api_client.activate_code_stroke(payload, ED), 201)

    a.assert_code_stroke_case(case)
    assert is_valid_uuid(case["id"]), f"the id is a server-minted UUID, got {case['id']!r}"
    assert case["id"] not in payload.values(), (
        f"no supplied value became the id, got {case['id']!r}"
    )
    assert case["version"] == 1, f"activation lands at version 1, got {case['version']}"
    assert instants_equal(case["created_at"], activation_at), (
        f"created_at is the logical clock at the write, got {case['created_at']}"
    )
    assert instants_equal(case["updated_at"], case["created_at"]), (
        f"nothing has mutated the row yet, got {case['updated_at']}"
    )
    assert instants_equal(case["activation_at"], activation_at), (
        f"activation_at is stamped from the clock, got {case['activation_at']}"
    )
    assert not instants_equal(case["activation_at"], case["door_at"]), (
        "the server stamp is its own instant, not a copy of the supplied door_at, got "
        f"{case['activation_at']}"
    )
    assert instants_equal(case["door_at"], CLOCK), (
        f"the caller-supplied arrival instant is taken as given, got {case['door_at']}"
    )
    assert instants_equal(case["last_known_well_at"], LKW), (
        f"the supplied last-known-well capture is stored unchanged, got {case['last_known_well_at']}"
    )
    assert case["activated_by_user_id"] == ED_PHYSICIAN_USER_ID, (
        f"the acting operator is read from the identity header, got {case['activated_by_user_id']!r}"
    )
    assert case["status"] == "ACTIVATED", f"the case opens activated, got {case['status']}"
    assert case["disposition"] == "PENDING", (
        f"no disposition is decided yet, got {case['disposition']}"
    )
    assert case["deviation_count"] == 0, (
        f"a new case carries no deviations, got {case['deviation_count']}"
    )


def test_code_stroke_activation_with_an_undeclared_arrival_mode_value():
    """A mode outside the three declared values is an enum failure, and a declared one passes.

    PRD 2.11: "Every enum-typed input field must carry one of that field's declared values — `ERR_INVALID_ENUM_VALUE` (422)."
    PRD 3.2: "The activation payload names the facility through `center_id`, carries a de-identified `patient_ref` (non-empty, at most 40 characters), the ED arrival instant `door_at` that anchors both clinical clocks, an `arrival_mode` of `EMS`, `WALK_IN` or `INTERFACILITY_TRANSFER`"
    PRD 3.2: "It then cascades to the facility: `open_case_count` rises by 1 and `ems_routing_posture` is re-derived"

    Design: Corner/entities/code_stroke_activation_with_an_undeclared_arrival_mode_value
    """
    fx.set_clock(CLOCK)
    center = _register(_center_payload("Enum Guard Community Spoke"))

    response = api_client.activate_code_stroke(
        _case_payload(center["id"], arrival_mode="AMBULANCE"), ED
    )

    validate_error(response, ApiErrorId.ERR_INVALID_ENUM_VALUE.value, 422)
    refused, refused_meta = _cases_at(center["id"])
    assert refused == [], f"the rejected activation wrote no row, got {len(refused)}"
    assert refused_meta["total_count"] == 0, (
        f"the facility still has no cases, got {refused_meta['total_count']}"
    )
    idle = validate_success(api_client.get_stroke_center(center["id"], COORD))
    assert idle["open_case_count"] == 0, (
        f"the facility cascade never ran, got {idle['open_case_count']}"
    )
    assert idle["version"] == 1, f"the facility was not mutated, got version {idle['version']}"

    accepted = validate_success(
        api_client.activate_code_stroke(
            _case_payload(center["id"], arrival_mode="WALK_IN"), ED
        ),
        201,
    )

    assert accepted["arrival_mode"] == "WALK_IN", (
        f"a declared value is stored as supplied, got {accepted['arrival_mode']}"
    )
    assert accepted["status"] == "ACTIVATED"
    admitted, admitted_meta = _cases_at(center["id"])
    assert admitted_meta["total_count"] == 1, (
        f"exactly the one accepted case exists, got {admitted_meta['total_count']}"
    )
    assert [row["id"] for row in admitted] == [accepted["id"]]
    busy = validate_success(api_client.get_stroke_center(center["id"], COORD))
    assert busy["open_case_count"] == 1, (
        f"only the accepted activation reached the cascade, got {busy['open_case_count']}"
    )


def test_spoke_agreement_period_must_be_strictly_increasing():
    """An inverted period and an empty one are both refused; one second of coverage is enough.

    PRD 3.1: "`effective_from` must be strictly earlier than `effective_until` or the create is rejected with `ERR_INVALID_PERIOD_RANGE`."
    PRD 3.1: "the two ends of its coverage window: `effective_from`, which is inclusive, and `effective_until`, which is exclusive"

    Design: Corner/entities/spoke_agreement_period_must_be_strictly_increasing
    """
    fx.set_clock(CLOCK)
    hub = _register(_center_payload("Period Range Hub Primary", "HUB_PRIMARY"))
    spoke = _register(_center_payload("Period Range Community Spoke"))
    boundary = "2026-10-01T00:00:00Z"

    inverted = api_client.create_spoke_agreement(
        f.spoke_agreement_payload(
            hub["id"], spoke["id"],
            effective_from="2027-08-01T00:00:00Z", effective_until=boundary,
        ),
        COORD,
    )
    validate_error(inverted, ApiErrorId.ERR_INVALID_PERIOD_RANGE.value, 422)

    empty = api_client.create_spoke_agreement(
        f.spoke_agreement_payload(
            hub["id"], spoke["id"], effective_from=boundary, effective_until=boundary,
        ),
        COORD,
    )
    validate_error(empty, ApiErrorId.ERR_INVALID_PERIOD_RANGE.value, 422)

    accepted = validate_success(
        api_client.create_spoke_agreement(
            f.spoke_agreement_payload(
                hub["id"], spoke["id"],
                effective_from=boundary, effective_until="2026-10-01T00:00:01Z",
            ),
            COORD,
        ),
        201,
    )

    assert accepted["status"] == "DRAFT", (
        f"a strictly increasing period is admitted, got {accepted['status']}"
    )
    assert instants_equal(accepted["effective_from"], boundary)
    assert instants_equal(accepted["effective_until"], "2026-10-01T00:00:01Z")

    rows, meta = validate_paginated(
        api_client.list_spoke_agreements(
            COORD, {"hub_center_id": hub["id"], "limit": 100, "offset": 0}
        )
    )
    assert meta["total_count"] == 1, (
        f"only the accepted period became a row, got {meta['total_count']}"
    )
    assert [row["id"] for row in rows] == [accepted["id"]]


def test_code_stroke_activation_naming_an_unknown_center_id():
    """A body-borne foreign key that resolves to nothing answers 404, not a shape failure.

    PRD 2.11: "Every foreign-key field in a request body must reference an existing record of the target entity, returning that entity's not-found code from the same list, and checked in the order the fields are declared in the endpoint's input list."
    PRD 2.12: "a request naming a non-existent record is rejected with that collection's not-found code regardless of what else the body gets wrong"

    Design: Corner/entities/code_stroke_activation_naming_an_unknown_center_id
    """
    fx.set_clock(CLOCK)
    real = _register(_center_payload("Foreign Key Community Spoke"))

    response = api_client.activate_code_stroke(_case_payload(NON_EXISTENT_UUID), ED)

    error = validate_error(response, ApiErrorId.ERR_CENTER_NOT_FOUND.value, 404)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value, (
        f"the body was well-formed, so the failure is existence, got {error['error_id']}"
    )
    orphans, orphan_meta = _cases_at(real["id"])
    assert orphans == [], f"nothing was written anywhere, got {len(orphans)} rows"
    assert orphan_meta["total_count"] == 0
    untouched = validate_success(api_client.get_stroke_center(real["id"], COORD))
    assert untouched["open_case_count"] == 0, (
        f"the real facility was never involved, got {untouched['open_case_count']}"
    )
    assert untouched["version"] == 1

    admitted = validate_success(
        api_client.activate_code_stroke(_case_payload(real["id"]), ED), 201
    )
    assert admitted["center_id"] == real["id"], (
        "the identical body naming an existing facility is accepted, so the id was the only "
        f"defect, got {admitted['center_id']}"
    )


def _consults_for(case_id):
    return validate_paginated(
        api_client.list_consults(ED, {"case_id": case_id, "limit": 100, "offset": 0})
    )


def test_consult_request_whose_agreement_does_not_cover_the_case_center():
    """An ACTIVE agreement covering a different spoke cannot serve this case.

    PRD 3.3: "the named agreement's `spoke_center_id` must equal the case's `center_id` (`ERR_AGREEMENT_CENTER_MISMATCH`)"
    PRD 2.11: "the agreement's spoke must be the case's facility (`ERR_AGREEMENT_CENTER_MISMATCH`, 409)"

    Design: Corner/entities/consult_request_whose_agreement_does_not_cover_the_case_center
    """
    context = fx.setup_network(clock=CLOCK)
    uncovered = _register(_center_payload("Uncovered Community Spoke"))
    case = fx.activate_case(uncovered["id"], CLOCK, last_known_well_at=LKW)
    fx.complete_imaging(case["id"], at=IMAGING)
    live = fx.read_case(case["id"])
    assert live["status"] == "IMAGING_COMPLETE", (
        f"the case is ready for a consult, got {live['status']}"
    )
    agreement = fx.read_agreement(context["agreement"]["id"])
    assert agreement["status"] == "ACTIVE", (
        f"the agreement itself is usable, got {agreement['status']}"
    )
    assert agreement["spoke_center_id"] == context["spoke"]["id"], (
        f"the agreement covers the network's own spoke, got {agreement['spoke_center_id']}"
    )
    assert agreement["spoke_center_id"] != uncovered["id"], (
        "the case sits at a facility this agreement does not cover"
    )

    fx.set_clock("2026-09-01T08:16:00Z")
    response = api_client.request_consult(
        f.consult_request_payload(case["id"], agreement["id"], live["version"]), ED
    )

    validate_error(response, ApiErrorId.ERR_AGREEMENT_CENTER_MISMATCH.value, 409)

    rows, meta = _consults_for(case["id"])
    assert rows == [], f"no consult row was written, got {len(rows)}"
    assert meta["total_count"] == 0, (
        f"the case has no consults at all, got {meta['total_count']}"
    )
    after = fx.read_case(case["id"])
    assert after["status"] == "IMAGING_COMPLETE", (
        f"the case did not advance, got {after['status']}"
    )
    assert after["version"] == live["version"], (
        f"the refused request mutated nothing, got version {after['version']}"
    )
    assert fx.read_agreement(agreement["id"])["active_consult_count"] == 0, (
        "the mismatched agreement takes no load"
    )
    neurologist = fx.read_neurologist(context["neurologist"]["id"])
    assert neurologist["active_consult_count"] == 0, (
        f"no routing pass ran, got {neurologist['active_consult_count']}"
    )
    assert neurologist["on_call_state"] == "ON_CALL", (
        f"the roster is untouched, got {neurologist['on_call_state']}"
    )


def test_the_routing_result_is_already_in_the_create_response_not_in_a_later_read():
    """The 201 body carries the assignment, and the follow-up reads only confirm it.

    PRD 3.3: "The winner is written to `assigned_neurologist_id`, `assigned_at` is stamped from the logical clock, the consult's `status` becomes `ASSIGNED`, `routing_attempt_count` reflects the pass just executed, and both the winner's `active_consult_count` and the agreement's `active_consult_count` are recomputed."
    PRD 2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
    PRD 3.3: "A case sitting in `ACTIVATED` or in `IMAGING_COMPLETE` transitions to `CONSULT_IN_PROGRESS`, and that transition increments the case's `version`"
    PRD 3.1: "`IN_CONSULT` is not settable here at all — it is reached only by accepting a consult and left only by completing or losing one"

    Design: Corner/consistency_model/the_routing_result_is_already_in_the_create_response_not_in_a_later_read
    """
    context = fx.setup_network(clock=CLOCK)
    neurologist_id = context["neurologist"]["id"]
    agreement_id = context["agreement"]["id"]
    case = fx.activate_case(context["spoke"]["id"], CLOCK, last_known_well_at=LKW)
    fx.complete_imaging(case["id"], at=IMAGING)
    before_case = fx.read_case(case["id"])
    assert before_case["status"] == "IMAGING_COMPLETE"
    assert fx.read_neurologist(neurologist_id)["active_consult_count"] == 0
    assert fx.read_agreement(agreement_id)["active_consult_count"] == 0

    created = validate_success(
        api_client.request_consult(
            f.consult_request_payload(case["id"], agreement_id, before_case["version"]), ED
        ),
        201,
    )

    a.assert_telestroke_consult(created)
    assert created["status"] == "ASSIGNED", (
        "the selector runs inside the create, so the row is never observed as REQUESTED, got "
        f"{created['status']}"
    )
    assert created["assigned_neurologist_id"] == neurologist_id, (
        f"the only candidate wins in the create response, got {created['assigned_neurologist_id']}"
    )
    assert instants_equal(created["assigned_at"], IMAGING), (
        f"assigned_at is the clock at the write, got {created['assigned_at']}"
    )
    assert instants_equal(created["requested_at"], created["assigned_at"]), (
        "request and assignment share one instant because they are one operation, got "
        f"{created['requested_at']} and {created['assigned_at']}"
    )
    assert created["routing_attempt_count"] == 1, (
        f"one pass was executed, got {created['routing_attempt_count']}"
    )
    assert created["decline_count"] == 0
    assert created["excluded_neurologist_ids"] == []
    assert created["accepted_at"] is None, (
        f"assignment is not acceptance, got {created['accepted_at']!r}"
    )

    reread = validate_success(api_client.get_consult(created["id"], ED))
    assert reread == created, (
        f"the later read adds nothing; create {created} read {reread}"
    )

    assigned = fx.read_neurologist(neurologist_id)
    assert assigned["active_consult_count"] == 1, (
        f"the winner's load was recomputed in the same write, got {assigned['active_consult_count']}"
    )
    assert assigned["on_call_state"] == "ON_CALL", (
        f"assignment does not move the availability dimension, got {assigned['on_call_state']}"
    )
    assert fx.read_agreement(agreement_id)["active_consult_count"] == 1, (
        "the agreement's load was recomputed in the same write"
    )
    after_case = fx.read_case(case["id"])
    assert after_case["status"] == "CONSULT_IN_PROGRESS", (
        f"the case transitioned inside the create, got {after_case['status']}"
    )
    assert after_case["version"] == before_case["version"] + 1, (
        f"the transition increments the case version once, got {after_case['version']}"
    )


def test_a_cascade_created_deviation_is_discoverable_in_the_same_instant_as_the_write():
    """The needle write returns the raised count and the row is listable immediately after.

    PRD 3.6: "When `door_to_needle_minutes` exceeds 60 a system-detected `ProtocolDeviation` of type `DTN_EXCEEDED` and severity `MAJOR` is opened on the case with `deviation_count` raised by 1"
    PRD 2.12: "This matters most for system-detected deviations, which no caller creates and which are discoverable only by listing deviations filtered by their case."
    PRD 3.8: "Deviations synthesised by the cascades described throughout §3 are identical rows except that their `source` is `SYSTEM_DETECTED` and their `opened_by_user_id` is the literal string `system`."
    PRD 2.8: "Each record touched anywhere in the chain has its own `updated_at` refreshed and its own `version` incremented by 1."
    PRD 3.2: "The effective elapsed minutes are then classified against two boundaries, each inclusive on the lower-numbered class: 180 minutes or fewer is `WITHIN_3H`"

    Design: Corner/consistency_model/a_cascade_created_deviation_is_discoverable_in_the_same_instant_as_the_write
    """
    context = fx.setup_network(clock=CLOCK)
    built = fx.setup_eligible_case(context, CLOCK, dti_minutes=10, last_known_well_at=LKW)
    case_id = built["case"]["id"]
    assert built["checklist"]["determination_status"] == "ELIGIBLE", (
        f"the case is cleared for the drug, got {built['checklist']['determination_status']}"
    )
    assert built["case"]["deviation_count"] == 0, (
        f"nothing has deviated yet, got {built['case']['deviation_count']}"
    )
    assert fx.list_case_deviations(case_id) == [], (
        "the ten-minute imaging clock raised nothing, so the case starts clean"
    )
    before = fx.read_case(case_id)

    treated = fx.administer(case_id, at="2026-09-01T09:10:00Z")

    assert treated["door_to_needle_minutes"] == 70, (
        f"08:00 to 09:10 is seventy whole minutes, got {treated['door_to_needle_minutes']}"
    )
    assert treated["lkw_to_needle_minutes"] == 90, (
        f"07:40 to 09:10 is ninety whole minutes, got {treated['lkw_to_needle_minutes']}"
    )
    assert treated["thrombolytic_window_class"] == "WITHIN_3H", (
        f"ninety minutes is well inside three hours, got {treated['thrombolytic_window_class']}"
    )
    assert treated["status"] == "THROMBOLYSIS_ADMINISTERED", (
        f"the drug moves the case, got {treated['status']}"
    )
    assert treated["disposition"] == "TREATED_LOCAL", (
        f"a local needle sets the local disposition, got {treated['disposition']}"
    )
    assert treated["deviation_count"] == 1, (
        "the cascade's count is already in the response body of the write that caused it, got "
        f"{treated['deviation_count']}"
    )
    assert treated["version"] == before["version"] + 1, (
        f"the case is touched once by this operation, got version {treated['version']}"
    )

    deviations = fx.list_case_deviations(case_id)

    assert len(deviations) == 1, (
        f"the list filtered by case reveals the synthesised row, got {len(deviations)}"
    )
    deviation = deviations[0]
    a.assert_system_detected_deviation(deviation, "DTN_EXCEEDED", "MAJOR")
    assert deviation["case_id"] == case_id, (
        f"the row is opened on the treated case, got {deviation['case_id']}"
    )
    assert deviation["source"] == "SYSTEM_DETECTED", (
        f"no caller created this row, got {deviation['source']}"
    )
    assert deviation["opened_by_user_id"] == "system", (
        f"the opener is the literal string system, got {deviation['opened_by_user_id']!r}"
    )
    assert deviation["status"] == "OPEN", (
        f"the fresh deviation awaits review, got {deviation['status']}"
    )

    narrowed = fx.list_case_deviations(case_id, source="SYSTEM_DETECTED", severity="MAJOR")
    assert [row["id"] for row in narrowed] == [deviation["id"]], (
        "the same row answers the conjunction of both filters, got "
        f"{[row['id'] for row in narrowed]}"
    )

    reread = fx.read_case(case_id)
    assert reread["deviation_count"] == 1, (
        f"the later read agrees with the write's own body, got {reread['deviation_count']}"
    )
    assert reread["version"] == treated["version"], (
        f"no second mutation followed the write, got version {reread['version']}"
    )
