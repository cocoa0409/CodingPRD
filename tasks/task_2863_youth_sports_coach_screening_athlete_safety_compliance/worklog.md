# Worklog — task_2863_youth_sports_coach_screening_athlete_safety_compliance

## Step 1: Create task directory — 2026-09-05T08:07:46.303Z

Created `tasks/task_2863_youth_sports_coach_screening_athlete_safety_compliance/` and `tasks/task_2863_youth_sports_coach_screening_athlete_safety_compliance/workspace/`. Index 2863 was pre-assigned by the invocation (no auto-allocation scan performed, per instructions, to avoid collision with the ~32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-05T09:46:00.000Z

All three scaffold artifacts for task 2863 are complete and lint-clean.

**Files** (`/home/ubuntu/github/CodingPRD/tasks/task_2863_youth_sports_coach_screening_athlete_safety_compliance/`)

| file | lines | top-level key(s) |
|---|---|---|
| `SCAFFOLD.yaml` | 2774 | §1.0–§1.7 only (no `scaffold_difficulty_design`, no `scaffold_corner_design`) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1897 | `scaffold_difficulty_design` |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3744 | `scaffold_corner_design` |

All three parse as valid YAML.

**§1.0–§1.7 content** — `api_prefix: /safesport`, domain `youth-sports-safety-compliance`, `difficulty_level: expert_plus`; 12 entities, 10 state machines (Member carries two parallel dimensions), 3 `concurrency_rules`, 11 calculations, 27 validations in one priority ladder, **57 endpoints** (27 GET / 30 POST), 45 errors, 6 roles (`role_model: segregation_of_duties`; `ClubAdministrator` = entity_backed:Club, `Member` = entity_backed:Member).

**§1.8** — 9 rules / 21 instances (per rule: dual_variant 2, combinatorial 3, non_linear_sm 2, transitive_cascade 2, priority_conflict 3, boundary_precision 3, cross_entity 2, temporal_overlap 2, compensating_invariant 2 — all >= the §0.5 minimum).

**§1.9** — 9 sections / 79 instances (50 live recipes + 29 `excluded_because` stubs): entities 11, state_machines 13, calculations 16, validations 13, endpoints 11, errors 5, rbac 5, cross_cutting_complexity_layers 4, consistency_model 1. Every stub cites an existing `rule_id / instance_name` pair in §1.8; all 100 names are unique across both design files.

**Coverage audit** — all 45 error_ids reachable by at least one live trigger; all 12 entities, all 11 calculations, all 10 state machines and all 27 validation priorities referenced in `grounds`; **all 57 §1.5 endpoints are exercised by at least one recipe call** (0 dead endpoints). `scaffold_lint.py`: 748 calls scanned -> `VERDICT: clean lint`.

**Scaffold defects found and fixed while writing §1.9** (§1.9 as a §1.5 audit pass):
- `ERR_ELECTRONIC_COMM_NOT_PERMITTED` was unreachable — its trigger named a `channel_kind` value missing from the enum; added `PRIVATE_DIRECT_MESSAGE` and extended validation 16.
- `ERR_INVESTIGATING_BODY_NOT_FOUND` was undeclared at priority 3; added.
- Priority 14 (`ERR_CONTACT_NOT_PERMITTED`) shadowed priorities 17/18, making `ERR_SCREENING_NOT_CURRENT`/`ERR_TRAINING_NOT_CURRENT` unobservable; narrowed 14 to a measure-only gate and rewrote two §1.8 instances plus one §1.9 stub accordingly.
- Priority 11 shadowed `ERR_MEMBER_DISQUALIFIED`; retargeted that instance to non-transition creation endpoints.
- Priority 25 covered only `convert-permanent` although the roles table and error catalog also promise reporter-cannot-close; widened check + `applies_to`.
- `expedited` was declared required despite having a default -> `expedited?`.
- 6 FKs had no reverse-reachability GET (Member.club_id, ScreeningOrder.member_id, TrainingAssignment.member_id, ClubAudit.club_id, RoomStay.club_id/member_id): added 9 read endpoints (4 filtered collections + 5 read-ones), taking §1.5 from 48 to 57, and added two §1.9 instances that exercise them.
- Stripped the "Generate task harder than expert level!" directive line from the `scenario:` key (verified no occurrence remains anywhere in the task dir) so it cannot leak into the downstream PRD.

Orchestrator verification: all three files present and non-empty; repo-wide grep for the difficulty directive inside the task dir returns nothing (no leak).

## Step 3: Copy shared files — 2026-09-05T09:47:10.169Z

Copied `./INSTRUCTION.md` -> `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T09:58:00.000Z

PRD generated at `workspace/PRD.md`.

**Size:** 436 lines / 101,966 bytes. Built with chunked `cat >>` appends (7 chunks), never a single Write.

**Section list**
- §1 Introduction (3 paragraphs — pain-point angle)
- §2 Global Specifications: 2.1 Actors, Identity Headers and RBAC · 2.2 API Response Structure (verbatim from `section-2.2-response-structure.md`, confirmed byte-identical) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and `version` · 2.5 The Logical Clock and Lazily Evaluated Lapses · 2.6 Version Pinning on Escrow and Eligibility Writes · 2.7 Precision, Rounding and Monetary Representation · 2.8 The Order in Which a Request Is Refused (all 27 priorities, ordered) · 2.9 Club Compliance Posture as a Gate · 2.10 Cascade Semantics and Hierarchical Consistency · 2.11 Nested Resource Retrieval and Reference Resolution · 2.12 Conserved Quantities (escrow + finding partition)
- §3 Business Logic, 9 subsections: 3.1 Chartering/Escrow/Registration (risk score) · 3.2 Pricing and Ordering a Screen (8 pinned steps) · 3.3 Vendor Returns, Adjudication, Disqualification, Void · 3.4 Training and Contact-Eligibility Derivation · 3.5 Eligibility Projection, Renewal, Records Retention · 3.6 Placement, Activation, Electronic Communication · 3.7 Travel/Lodging Room Slots · 3.8 Incident Reporting, Routing, Interim Measures, Closure · 3.9 Audits, Findings, Sanctions
- §4 Endpoint Definitions (4 columns) · §5 Error Code Catalogue (2 columns)

**Coverage confirmation**
- Endpoints: 57/57 present (table generated directly from `endpoints[]`, row count verified = 57).
- Errors: 45/45 in §5 (verified = 45), and all 45 `error_id` strings also appear in §2/§3 narrative.
- Entities: all 12; every one has `common_fields: true`, so §2.4 states `id`/`created_at`/`updated_at`/`version` universally with no exemptions.
- Field names: 145 required identifiers (entity fields + request bodies + query params + path params + OCC fields) — **0 missing**.
- All state values across the 10 state machines: 0 missing. All enum constraint values: 0 missing.
- All 11 calculations, all 33 transitions, all 3 `concurrency_rules`, all 27 validations expressed in prose.
- §3 path purity: 928 backtick tokens scanned, 0 starting with `/`, 0 bare HTTP methods, 0 method+path.

**Tail is complete** — ends on the final `ERR_ESCROW_INSUFFICIENT | 409` row of the §5 table, no audit footer, no truncation.

**One scaffold inconsistency worth flagging to the pipeline:** three errors carry different HTTP statuses in `validations[]` vs `errors[]` — `ERR_RENEWAL_WINDOW_NOT_OPEN` (422 vs 409), `ERR_ESCROW_INSUFFICIENT` (402 vs 409), `ERR_BODY_SCOPE_MISMATCH` (422 vs 409). I deliberately omitted the status number from prose for exactly those three and let the §5 table (generated from `errors[]`) be the single authority, so the PRD is self-consistent whichever the test suite asserts. Two field-constraint conflicts were resolved in favour of the entity definition: `roster_size_attested` (entity `>= 0` vs `ERR_VALIDATION` trigger `< 1`) and `minor_athlete_age` (entity `5..17` vs trigger `0..17`).

Orchestrator verification (guarding against the known doc-generator truncation failure): `wc -l` = 436; tail shows the §5 table completing at `ERR_ESCROW_INSUFFICIENT`, a real section boundary, not mid-sentence; heading scan shows all of §1–§5 present in order; grep for the difficulty directive / design-index tokens in PRD.md returns 0. No regeneration needed.

## Step 6: Generate implementation — 2026-09-05T10:32:00.000Z

(Steps 5 and 6 were launched concurrently in a single orchestrator message, per the skill, so the impl generator was physically unable to read `test_suite/` — that directory did not exist when it started. Step 6 finished first, so its entry is recorded here ahead of Step 5's.)

Implementation complete and smoke-tested.

## Modules written (`workspace/implementation/`)

| file | lines | role |
|---|---|---|
| `start.sh` | 10 | guarded `pip install`, `exec python3 app.py`, reads `$PORT` |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 89 | blueprint registration under `/safesport`, logical-clock endpoint, ApiError/404/405/HTTPException envelope handlers, `0.0.0.0:$PORT` (default 10000) |
| `errors.py` | 77 | 45-entry error→status catalogue (PRD §5 wins over SCAFFOLD: escrow 409, renewal-window 409, body-scope 409) |
| `clock.py` | 98 | logical clock, default `2026-08-01T00:00:00Z`, ISO-8601 with exactly 3 fraction digits |
| `store.py` | 122 | 12 in-memory dicts, `new_row/touch/bump/ordered`, lookup helpers; **starts empty, nothing seeded** |
| `envelope.py` | 57 | `meta`/`response_type`/`data`, `req_`+20 uppercase alnum, real wall-clock timestamp, pagination fields |
| `validate.py` | 159 | strict body schema (unknown key → `ERR_VALIDATION`), pagination, query enums |
| `auth.py` | 149 | steps 1–5 of the order of refusal, 11 path getters, club scope, member ownership |
| `calc.py` | 149 | tier scoring, order pricing, compliance score, shortfall factor, per-finding fine (Decimal + ROUND_HALF_UP, integer cents) |
| `derive.py` | 232 | projection variants, training status, contact eligibility, posture, the four lazily-evaluated clock transitions |
| `ops.py` | 125 | cascade mechanics, bubble-up, suspend/restore/terminate, measure-window and room-slot arithmetic |
| `serialize.py` | 259 | 12 serializers + eligibility projection |
| `pagelib.py` | 19 | list paging + filter helper |
| `routes_clubs.py` | 184 | 7 endpoints |
| `routes_members.py` | 251 | 9 |
| `routes_screening.py` | 145 | 5 |
| `routes_training.py` | 152 | 6 |
| `routes_coach.py` | 154 | 5 |
| `routes_cases.py` | 258 | 8 |
| `routes_measures.py` | 86 | 4 |
| `routes_audits.py` | 298 | 8 |
| `routes_rooms.py` | 54 | 3 |

3,128 lines total; every file `py_compile`s clean.

## Endpoints
The URL map contains exactly **57 endpoints** (27 GET + 30 POST), matching PRD §4 lines 328–384 one-for-one, including `POST /safesport/_clock/set_current_utc`.

## Smoke test (PORT=18863, killed by exact PID 1452033, port confirmed free)
Full happy path plus refusals all behaved: charter → escrow → member registration → priced expedited order (TIER_2: 5900 gross, 2065 expedite, 7965 charged) → vendor return → CLEAR adjudication (expiry +730d) → course/assign/start/complete → membership bubbled PENDING→ACTIVE with `eligible_through` stamped → placement create/activate (`eligibility_snapshot_version` pinned) → e-comm authorization → room stay then `ERR_MINOR_ADULT_LODGING_PROHIBITED` → case file/route/measure (club posture flipped to RESTRICTED, placement suspended) → lift (posture and `active_assignment_count` restored with zero drift) → `ERR_SEGREGATION_OF_DUTIES` then successful unsubstantiated closure → audit open/finding/finalize (score 10.00 on SELF_ATTESTED denominator 10) → `ERR_DECISION_ROLE_MISMATCH` → SANCTION close (club FROZEN, placements terminated) → `ERR_CLUB_POSTURE_FROZEN` on renewal → clock jump to 2028 driving the lazy screening/membership lapses. Also verified 401 (missing header and unknown role), 403 role and member-ownership, 422 unknown field / bad `limit` / bad `variant`, 412 `ERR_STALE_CLUB_VERSION`, 409 `ERR_ESCROW_INSUFFICIENT`, order→void escrow conservation (5100 → 2600 → 5100 with `total_funded_cents` untouched and member back to UNSCREENED), pagination meta (`limit/offset/total_count/has_more`), and both 404 flavours (`ERR_CLUB_NOT_FOUND` vs `ERR_NOT_FOUND`).

Notable spec decisions: derived-counter and lazy-clock recomputation uses `touch()` (never `bump()`) so OCC pins are not spuriously invalidated; version bumps happen only where SCAFFOLD/PRD declare them plus cascaded rows whose own state changes; empty required-course set yields `training_status = NEVER`; gate 14 is measure-based only (PERMANENT for create/renew, PERMANENT+ACTIVE for activate/e-comm/room-stay); finding decisions check finding state before audit state per the SCAFFOLD precondition order. Scratch files stayed in `/tmp/prdbench_task_2863_impl/`; `worklog.md`, `test_suite/` and `test_helpers/` were never touched or read.

## Step 5: Generate unit tests — 2026-09-05T11:31:00.000Z

Test generation for task 2863 is complete.

## Output (both at the task root, nothing under `workspace/`)

`test_helpers/` — 2225 lines
`__init__.py` 23, `api_client.py` 449, `api_errors.py` 116, `assertions.py` 182, `constants.py` 187, `factories.py` 428, `fixtures.py` 489, `test_users.py` 129, `types.py` 222

`test_suite/` — 8160 lines, **90 tests**
`conftest.py` 23; queue A: `test_01` 326, `test_02` 380, `test_03` 375, `test_04` 325, `test_05` 412, `test_06` 303, `test_07` 340, `test_08` 291, `test_09` 275 (42 tests); queue B: `test_10` 589, `test_11` 689, `test_12` 517, `test_13` 892, `test_14` 897, `test_15` 521, `test_16` 585, `test_17` 420 (48 tests)

## Design-index coverage

- **Queue A (Difficulty)**: 21/21 non-stub instances translated, 0 skipped — exactly 2 tests each (the skill's >=2-per-instance target).
- **Queue B (Corner)**: 48/50 non-stub instances translated, 1 test each; 2 skipped.
  - `entities/coach_assignment_for_a_member_of_another_club_is_rejected` — the yaml wants `ERR_CLUB_SCOPE_VIOLATION` for a placement naming another club's member, but PRD §3.6 states outright that "one member may hold placements at several clubs, and the `club_id` on a placement may legitimately differ from the chartering club recorded on the member". The refusal is not uniquely derivable; the PRD arguably requires the opposite.
  - `errors/active_measure_blocks_placement_and_lodging_for_that_member` — PRD §3.6 blocks placement *creation* only for a member under a **permanent** restriction, and §2.9 says a `PENDING` placement puts nobody in front of athletes, so an ACTIVE temporary measure does not uniquely derive `ERR_CONTACT_NOT_PERMITTED` on creation.

## Verification performed

- `python3 -m py_compile` clean on every helper and test file; `pyflakes` clean on all test modules (only the deliberate re-export "unused import" notices in `test_helpers/__init__.py` and `conftest.py`).
- `pytest --collect-only`: **90 tests collected**, no collection errors.
- Citation checker (`/tmp/prdbench_task_2863_tests/check_citations.py`): every test has exactly one `Design:` line as the last docstring line, every tag resolves to a real non-excluded instance, no dual tags, and **every >=40-char quoted string appears verbatim in `workspace/PRD.md`** — zero problems. No docstring mentions "scaffold".
- Symbol checker: every `test_helpers` import name exists, every `api.<method>` exists on `ApiClient`, every `ApiErrorId.<X>` is a real member.
- `__pycache__`/`.pytest_cache` removed; `worklog.md` untouched; `workspace/implementation/` never read.

## Notable PRD-over-yaml corrections applied in this final batch

- `PHYSICAL_MISCONDUCT` -> `PHYSICAL_ABUSE`, `TRAINING_OVERDUE` -> `TRAINING_LAPSED`, `reporter_kind: CLUB_STAFF` -> `MANDATORY_REPORTER` (yaml values outside the PRD enums).
- consistency_model instance asserted `denominator_count == 1`; under `SELF_ATTESTED` the PRD makes it the club's `roster_size_attested`, so the test asserts **3** (and score `0.00`).
- rbac instance 1 wanted `GET /safesport/clubs` to report `total_count 1`; there is no club-list endpoint in PRD §4, so that sub-assertion was dropped.
- Three instances asserted `membership_status == REVOKED` for members still `PENDING`; PRD §3.3/§3.8 reach `REVOKED` only from `ACTIVE`/`SUSPENDED`/`LAPSED`, so that single sub-assertion was omitted while every other grounded assertion was kept.

Orchestrator verification: `test_helpers/` and `test_suite/` are both at the task root (nothing stray under `workspace/`, which holds only INSTRUCTION.md, PRD.md, implementation/ and the orchestrator's sweep.sh); `pytest --collect-only` re-run independently confirms 90 tests collected with no errors.

## Step 7: Run tests and iterate — 2026-09-05T11:47:00.000Z

`worklog.md` is untouched (timestamp 11:32, before my run), storage is in-memory only, and both test directories are correctly at the task root.

## Summary

**Iterations run:** 2 sweeps (baseline + verification).

**Final per-round results — all 8 rounds of the verification sweep:**

| Round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| passed/total | 90/90 | 90/90 | 90/90 | 90/90 | 90/90 | 90/90 | 90/90 | 90/90 |

Baseline was 89/90 in all 8 rounds — a single deterministic failure, no flakiness anywhere in the suite.

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:** none. I audited `api_client.py`, `factories.py`, `fixtures.py`, `assertions.py`, and `test_users.py` against the PRD; the recurring fixture bugs this pipeline sees were all already absent (money is integer cents throughout, every PRD-declared instant is a full ISO-8601 instant with only `date_of_birth` as a bare date, and `api_client.canonical_instant` already normalises sub-second width to three digits).

**Fixes applied to `implementation/`:** none — the single failure was a test-side over-determination, not a defect.

**Assertion relaxed (STEP 1b unique-derivability correction), in `test_suite/test_11_state_machine_edges.py`:**

- `test_closing_an_unrouted_case_with_an_outcome_is_rejected_then_succeeds_without_it` — **ERROR PRECEDENCE SILENCE.** The test demanded exactly `ERR_VALIDATION`/422 when a case is closed from `INTAKE_REVIEW` with an `outcome` supplied; the implementation reports `ERR_CASE_INVALID_STATE`/409.

  PRD §3.8 makes the refusal itself normative — *"the `outcome` is required when closing from `ROUTED` and forbidden when closing from `INTAKE_REVIEW`"* — but never names the `error_id`. Two PRD-faithful readings diverge: (A) a state-keyed transition rule reported at position 11 of §2.8 (*"The addressed resource is in a state from which the requested transition exists — otherwise … `ERR_CASE_INVALID_STATE`"*), or (B) a state-conditional body-schema rule reported at position 6 (`ERR_VALIDATION`). Reading A is if anything the stronger one: §2.8's shape enumeration lists every *other* conditional-pairing rule in the system (`season_end`/`season_start`, `check_out`/`check_in`, the room stay's `member_id`/`minor_athlete_age`/`occupant_kind` triple) yet conspicuously omits this one, and the rule is keyed on the resource's status rather than on any body field.

  Since PRD supports the "`ERR_VALIDATION` is possible" reading but does not force it, I applied the sanctioned relaxation to `validate_error_is_one_of([ERR_VALIDATION, ERR_CASE_INVALID_STATE])` rather than deleting. Per STEP 1c this keeps every verbatim-covered assertion in the test intact — `report_timeliness == LATE` (30h elapsed vs the inclusive 24h window), the case still reading `INTAKE_REVIEW` after the refusal, and the subsequent outcome-free close moving it to `CLOSED_ADMINISTRATIVE` with `outcome` null. Only the under-determined claim about *which* of the two catalogue members reports the refusal was dropped; the HTTP-status argument went with it because the two candidates carry different statuses (422 vs 409). No `skip`/`xfail` was added and no error_id check was downgraded to a bare status check.

One note for the record: the implementation applies this conditional-outcome rule symmetrically (missing `outcome` when closing from `ROUTED` also yields `ERR_CASE_INVALID_STATE`), and no test in the suite pins an `error_id` for that mirror direction — so the suite had no consistent position on the question the failing assertion was pinning.

Orchestrator verification (guarding against the known "claimed-clean sweep with no artifacts" failure mode): all 8 `workspace/implementation/results.$i.json` files exist with a single consistent mtime of 11:44, and an independent parse of each reports `passed=90 / total=90 / failed=0`. Test count is still 90, confirming nothing was deleted.

## Step 8: Finalize PRD — 2026-09-05T11:52:00.000Z

Step 8 was NOT skipped: Step 7 ran 2 iterations and applied 1 `test_suite/` fix, so the skip condition (0 deletions, 0 test_suite fixes, 0 test_helpers fixes, 0 implementation fixes) was not met.

`PRD_FINALIZED.md` is written. One line changed; nothing lost.

## Line counts
- `PRD.md`: 436 lines
- `PRD_FINALIZED.md`: 436 lines
- Delta: 0 lines (+0.0%); one line revised in place (§3.8, line 298)

## Changes
- **§3.8 (case closure)** — *revise* — pinned the `error_id` and precedence for the state-conditional `outcome` pairing on `POST /cases/{case_id}/close`: a violation in either direction (outcome supplied when closing from `INTAKE_REVIEW`, outcome omitted when closing from `ROUTED`) is refused with `ERR_CASE_INVALID_STATE`, not `ERR_VALIDATION`, and is evaluated at position 11 of §2.8; also noted that the already-closed refusal is reported ahead of the pairing rule — `implementation/routes_cases.py:161-167`

## Pre-edit search log

**Edit 1 — §3.8 closure `outcome` pairing error_id**

(a) **Subject identified:** the `error_id` and refusal position for a body-field requirement that is conditioned on the addressed resource's status — specifically `outcome` vs. case status on case closure. Secondary subject: whether any *other* conditional-pairing validation in the system would be mis-described by calling this class of rule "state-keyed / position 11".

(b) **Impl paths enumerated and read/grepped:**
- `grep -rn "outcome"` across all impl modules -> only `routes_cases.py:97,152,163-167,182-183` and `serialize.py:161`. The pairing is enforced in exactly one place (`close_case`), so there is no parallel endpoint or cascade that re-implements it.
- Read `implementation/routes_cases.py` in full — confirmed check order inside `close_case`: `auth.case` (404) -> `validate.body` (422 shape) -> already-closed -> `INTAKE_REVIEW`+outcome -> `ROUTED`+no-outcome -> segregation of duties. That places the pairing after shape (§2.8 pos 6) and before SoD (§2.8 pos 25), which is exactly §2.8 position 11.
- Read `implementation/validate.py` — `body()` treats an explicit `null` on an optional field as absent, so `{"outcome": null}` from `ROUTED` takes the same `ERR_CASE_INVALID_STATE` branch as omission; the wording ("omitted") covers both without asserting a null-handling rule the PRD does not otherwise state.
- `grep -n "ERR_CASE_INVALID_STATE\|ERR_VALIDATION\|validate.bad"` across all impl modules to find every other conditional/pairing validation, to make sure the new sentence does not generalize: `routes_coach.py:55` (`season_end`/`season_start`), `routes_clubs.py:143,146,149` (`check_out`/`check_in`, `occupant_kind` triple), `routes_audits.py:90` (`audit_period_*`), `routes_cases.py:221` (`effective_to`/`effective_from`), `routes_members.py:44,153` — **all** of these use `ERR_VALIDATION`, matching §2.8 position 6 as the PRD already states. Also checked the other `ERR_CASE_INVALID_STATE` sites (`routes_cases.py:131,229`, `routes_measures.py:51,73`) — all are genuine case-status gates already described by the PRD.

(c) **Wording adjustment made:** scoped the new sentence explicitly to "that pairing" and justified it as "keyed on the case's own status rather than on the body alone" rather than stating any general principle about conditional body-schema rules — precisely so it cannot be read as overriding §2.8 position 6 for the five other pairings (all of which do return `ERR_VALIDATION` in the impl). Added "which is reported ahead of the pairing rule" to the already-closed clause to match the impl's intra-position-11 order. Deliberately left untouched the adjacent clause "a `closure_reason` of either `NO_JURISDICTION` or `DUPLICATE_REPORT`" for the administrative branch — the impl accepts any of the three `closure_reason` values from either state, but that is not a `<step_7_diff>` item and is out of Step 8 scope.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (298c298) and nothing else; both files are 436 lines; the tail of PRD_FINALIZED.md still ends on the complete §5 error table, so no truncation occurred.

## Step 9: Complete PRD — 2026-09-05T12:20:00.000Z

Orchestrator decision (recorded per the AUTONOMY directive): Step 9 was run as **three sequential passes partitioned by implementation module**, all editing one shared `workspace/PRD_COMPLETED.md`. A single-agent full scan of a 21-module / 3,128-line implementation against a 436-line / 100KB PRD reliably exhausts one subagent's working budget and yields a document byte-identical to its input (i.e. the scan never actually ran). Partitioning by module keeps each pass's reading load tractable while still covering every module exactly once. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from copying, so as not to destroy earlier passes' edits. Pass 3, as the final pass, also performed a closing consistency read over passes 1–2's hunks.

Partition:
- Pass 1 — `app.py`, `errors.py`, `clock.py`, `store.py`, `envelope.py`, `validate.py`, `auth.py`, `pagelib.py`, `serialize.py`, `start.sh`
- Pass 2 — `calc.py`, `derive.py`, `ops.py`, `routes_clubs.py`, `routes_members.py`, `routes_screening.py`
- Pass 3 — `routes_training.py`, `routes_coach.py`, `routes_cases.py`, `routes_measures.py`, `routes_audits.py`, `routes_rooms.py`

### Pass 1 (core / cross-cutting modules) — 14 changes: 13 ambiguity-pins, 1 mismatch-revision

Copy of PRD_FINALIZED.md -> PRD_COMPLETED.md verified at 436 lines; all edits made with targeted Edit calls. +3,734 chars.

- §2.1 — insert — ambiguity — a whitespace-only `X-User-ID`/`X-User-Role` counts as empty for `ERR_UNAUTHENTICATED` — `auth.py:23-26`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9` — `envelope.py:10-14`
- §2.2 — insert — ambiguity — `api_request_timestamp` reads real wall-clock time, not the logical clock, so it does not move when the clock is repositioned — `envelope.py:21`, `clock.py:96-98`
- §2.3 — insert — ambiguity — a non-integer `limit`/`offset` is `ERR_VALIDATION`; an empty-string value is treated as absent and falls back to the default — `validate.py:131-150`
- §2.3 — insert — ambiguity — `created_at` ties (frequent, since the logical clock stands still) break on creation sequence, and a descending list is the exact reverse of the ascending order — `store.py:60-62`
- §2.4 — insert — ambiguity — `created_at`/`updated_at` are stamped from the logical clock, not wall-clock time — `store.py:36-37`
- §2.4 — insert — ambiguity — the one exception to "version advances on every mutation" is the clock-driven lapse, which refreshes `updated_at` alone — `store.py:48-51`
- §2.4 — insert — ambiguity — strict body validation: any key the endpoint's schema does not name is `ERR_VALIDATION` (not just server-written fields), and an explicit JSON `null` is treated as omission (required -> refused as missing, optional -> default) — `validate.py:110-128`
- §2.5 — insert — ambiguity — accepted input spellings for instant fields (trailing `Z`, numeric offset normalized to UTC, any/no fractional digits, no zone read as UTC, bare `YYYY-MM-DD` as midnight UTC) and year arithmetic as a calendar-year offset with 29 Feb -> 28 Feb — `clock.py:31-56, 85-93`
- §2.5 — insert — ambiguity — a lapse refreshes `updated_at` without advancing `version` (and pure derived recomputation changes neither), and the lazy evaluation is a global sweep run at the start of every authenticated+authorized request, before the handler — `store.py:48-51`, `auth.py:42`
- §2.11 — insert — ambiguity — filters are exact equality, empty-string filter = absent, enum-valued filters (`status`, `severity`, `score_variant`, `screening_status`, `membership_status`, `contact_eligibility`, `role_type`) reject out-of-enum values with `ERR_VALIDATION`, id/free-text filters are unvalidated — `validate.py:153-159`, `pagelib.py:14-19`
- §4 — insert — ambiguity — every path matches with or without a trailing slash — `app.py:44`
- §4 (room-stay read row) — **revise** — **mismatch** — the row promised a "lodging safety verdict" field that the serializer does not emit; revised to booking status and cancellation reason — `serialize.py:227-241`
- §5 — insert — ambiguity — three transport-level error ids outside the table (`ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500), path/method resolution preceding step 1 of §2.8 (so they win over missing identity headers), unparseable or non-object body -> `ERR_VALIDATION` 422, and an absent body read as `{}` — `app.py:55-79`, `auth.py:48-54`, `errors.py:62-64`

Pass 1 note: `errors.py`'s status map matches §5 exactly — no discrepancies there.

### Pass 2 (calculation/derivation + club, member, screening routes) — 16 changes: 13 ambiguity-pins, 3 mismatch-revisions

Cumulative after pass 2: 110,797 chars, +8,388 vs PRD_FINALIZED.md (pass 2 contributed +4,654), 26 diff hunks.

- §2.3 — insert — ambiguity — both room-stay lists take `created_at` then creation sequence as tie-breaks after `check_in` (pass 1's suspicion was wrong: both lists *do* sort by `check_in`) — `routes_clubs.py:121`, `routes_members.py:139`
- §2.6 — insert — ambiguity — `expected_club_version` must be a non-negative integer; negative/non-integer is `ERR_VALIDATION` before the 412 comparison — `routes_members.py:159`
- §2.7 — insert — ambiguity — compliance scores go on the wire as JSON *numbers* (100.00 -> `100.0`), not decimal strings; `null` when uncomputed — `calc.py:145-149`
- §3.1 — revise — **mismatch** — `minor_athlete_program` gates only the electronic-comm private-DM prohibition; the §3.7 room-slot rules are enforced at every club regardless (PRD had claimed the lodging policy was flag-gated) — `routes_clubs.py:154-169`
- §3.1 — insert — ambiguity — a new member's `screening_expires_at`/`eligible_through`/`records_retained_through`/`last_renewed_at` are null and `active_assignment_count` is 0 — `routes_members.py:53-72`
- §3.2 — revise — **mismatch** — a `DISQUALIFIED` member is carried *past* the state gate so the refusal is `ERR_MEMBER_DISQUALIFIED` (pos 13), not `ERR_MEMBER_INVALID_STATE` (pos 11); `SCREENING_ORDERED`/`FLAGGED` do get the invalid-state error — `routes_members.py:174-182`
- §3.3 — insert — ambiguity — `rationale` is 1–4,000 chars, mandatory, and never persisted or echoed on the order — `routes_screening.py:69,77`
- §3.3 — insert — ambiguity — `NON_DISQUALIFYING_RECORD` is keyed on the member's screening dimension alone and is accepted over a `NO_RECORD` return (vendor disposition not consulted); `CLEAR` additionally requires the member still `SCREENING_ORDERED`; `DISQUALIFYING_RECORD` requires `RECORD_FOUND` *and* `FLAGGED` — `routes_screening.py:83-94`
- §3.3 — revise — **mismatch** — disqualification drives membership to `REVOKED` unconditionally, from `PENDING`/`SUSPENDED` too, not just `ACTIVE`/`LAPSED` — `ops.py:72-75`
- §3.3 — insert — ambiguity — a void never rewrites `screening_expires_at`, so a voided re-screen leaves the old expiry on an `UNSCREENED` member (inert, since §2.5 expiry fires only over `CLEARED`) — `routes_screening.py:142`
- §3.4 — insert — ambiguity — `training_status` is `NEVER` also when the required course set is empty, not only when a required course lacks a completion — `derive.py:62-64,95-101`
- §3.5 — insert — ambiguity — an **empty** required course set yields a *null* training horizon, not an unbounded one; with no course published every projection is null and every member `NEVER` — `derive.py:62-64`
- §3.5 — insert — ambiguity — **`blocking_reasons` token set and order** (pass 1 hand-off): fixed vocabulary `SCREENING_DISQUALIFIED`, `PERMANENT_MEASURE`, `ACTIVE_INTERIM_MEASURE`, `SCREENING_NOT_CURRENT`, `TRAINING_NOT_CURRENT`, `MEMBERSHIP_NOT_ACTIVE` in exactly that order, `SCREENING_NOT_CURRENT` suppressed on a disqualification, empty when nothing blocks, variant-independent — `derive.py:128-142`
- §3.5 — insert — ambiguity — `records_retained_through` drops a null-input horizon rather than nulling the result; case side is `max(closed_at)` over *any* closed status — `derive.py:115-125`
- §3.6 — revise — **mismatch** — a measure becoming permanent stamps `PERMANENT_MEASURE` on `PENDING`/`ACTIVE`/`SUSPENDED` placements alike, not on `SUSPENDED` alone — `ops.py:64-69`
- §3.7 — insert — ambiguity — club scope is checked against the path club only; the occupant `member_id` need not be chartered by the travelling club (borrowed coaches may be lodged); unresolvable id -> `ERR_MEMBER_NOT_FOUND` — `routes_clubs.py:151-153`

Pass 2 confirmed already-pinned (no change): every `calc.py` constant and all eight charge steps, the four risk components and caps, tier thresholds, `club_compliance_score`'s three clauses, `shortfall_factor`, `finding_fine_cents`; `screening_expiry`/`per_course_expiry` latest-with-earliest-`created_at` tie-break; the two variant candidate sets; `contact_eligibility`'s three clauses (and its deliberate independence from `membership_status`); `compliance_posture` and every `recompute_club`/`recompute_audit` counter; `measure_window_conflict` closed endpoints + 14-day buffer; `slot_neighbours` half-open intersection and safety-before-capacity ordering; the renewal gate chain including `attestation_signed: false -> ERR_RENEWAL_WINDOW_NOT_OPEN`; escrow debit/refund conservation.

### Pass 3 (remaining route modules, plus the four hand-off items) — 42 pins over 26 line locations: 31 ambiguity-inserts, 11 mismatch-revisions

Final: 436 lines, 120,561 chars, +18,152 cumulative vs PRD_FINALIZED.md (pass 3 added +9,764), 49 diff hunks, 29 headings, tail intact.

- §2.1 — insert — ambiguity — a finding is club-scoped by the club its own *audit* examines, not by the club chartering the member it names, which also covers an org-level finding with no `member_id` — `auth.py:scope_finding`, `routes_audits.py:70,223`
- §2.3 — revise — mismatch — "Three lists deviate" -> **four**: the flat governing-body-wide room-stay list also orders by `check_in`, then `created_at`, then creation sequence — `routes_rooms.py:30`
- §2.4 — revise — mismatch — the lapse is no longer claimed as the *sole* exception to `version`+1; cross-references §2.10 for re-derivations and the two directly written club fields — `routes_audits.py:197,276,290`
- §2.8 step 8 — insert — ambiguity — a body-supplied `club_id`/`member_id` must belong to the acting `ClubAdministrator`, tested *here* (after step 7 existence), so a 404 or `ERR_TRAINING_COURSE_NOT_FOUND` outranks the scope violation — `routes_coach.py:59-62`, `routes_cases.py:96-99`, `routes_training.py:63-66`
- §2.10 — revise — mismatch — "every affected row's `version` increases by one" now excludes pure re-derivation: an audit's four finding counters, a club's finding counters/`compliance_posture`, and a member's re-derived fields keep `version` *and* `updated_at`; a finalization's club `compliance_score` and a closure's `sanction_status` are written directly yet still don't bump — `routes_audits.py:156,197,276,290`
- §2.11 — insert — ambiguity — no flat collection is club-narrowed; the three lists authorizing `ClubAdministrator` (coach placements, interim measures, audit findings) span the whole governing body — `routes_coach.py:26`, `routes_measures.py:23`, `routes_audits.py:54`
- §2.11 — revise — mismatch — "club scope bites **only** on a single-resource read" corrected: it also bites on writes carrying `club_id`/`member_id`, via §2.8 step 8
- §3.4 — revise — ambiguity — course `title` bounded 1 to 200 characters — `routes_training.py:22`
- §3.4 — insert x3 — ambiguity — assignment creation resolves `member_id` then `course_code`, both before the body-scope rule; `due_at` may lie in the past (row is created and *reported* `ASSIGNED`, only the next request's sweep expires it); `DISQUALIFIED` is the only member gate — `routes_training.py:60-72`
- §3.4 — insert — ambiguity — starting an assignment bumps the assignment alone; the member row's `version`/`updated_at` stand still — `routes_training.py:96`
- §3.4 — revise — ambiguity — a sub-`pass_score` submission is `ERR_TRAINING_ASSIGNMENT_INVALID_STATE` (not `ERR_VALIDATION`), tested *after* the `IN_PROGRESS` check, while a score outside 0–100 is `ERR_VALIDATION` ahead of both — `routes_training.py:118-124`
- §3.6 — insert x4 — ambiguity — placement creation resolves `member_id` then `club_id`; a `RESTRICTED` club may still create and a merely `ACTIVE` measure does not block (only `PERMANENT` does); **`electronic_comm_channel_kind` and `parent_copy_required` carry no default and stay null**; no uniqueness rule on placements at all — `routes_coach.py:55-88`
- §3.6 — revise x2 — mismatch — activation's four preconditions are evaluated in §2.8 order, so `ERR_STALE_MEMBER_VERSION` precedes the not-`PENDING` refusal; activation consults neither the season interval nor the membership dimension — `routes_coach.py:100-112`
- §3.6 — revise — mismatch — `eligibility_snapshot_version` is the value the caller pinned, read before the activation's own increment, so it always reads one less than the member's post-request `version` — `routes_coach.py:114`
- §3.6 — insert x3 — mismatch/ambiguity — `TERMINATED` is carved out of the not-`ACTIVE` condition and refused `ERR_COACH_ASSIGNMENT_INVALID_STATE`; the contact-restriction refusal sits *between* the terminated check and the remaining e-comm conditions; authorization may be re-recorded and is never withdrawn on later suspension/expiry/termination — `routes_coach.py:132-152`
- §3.7 — revise — ambiguity — cancellation `reason` bounded 1 to 1,000 characters — `routes_rooms.py:47`
- §3.8 — revise — ambiguity — investigating-body `name` bounded 1 to 160 characters
- §3.8 — insert x3 — ambiguity — filing resolves `club_id` then `reported_member_id`; filing is gated on nothing else (a `FROZEN` club and a `DISQUALIFIED`/`REVOKED` member are both fileable, and measure imposition likewise consults only an existing `PERMANENT`); a future `occurred_at` classifies `TIMELY` — `routes_cases.py:93-118`
- §3.8 — revise x2 — mismatch — the `closure_reason` enum is **not** partitioned by branch (all three values accepted on both), and administrative closure does not bump the member even though `records_retained_through` picks the closure up — `routes_cases.py:150-170`
- §3.8 (lift) — revise x3 — mismatch — `reason` 1–1,000; `ERR_INTERIM_MEASURE_INVALID_STATE` precedes `ERR_CASE_INVALID_STATE`; restoration is **all-or-nothing** on one clearance test over the whole member, `LAPSED` membership stays `LAPSED`, and `eligible_through` is never re-stamped — `routes_measures.py:45-58`, `ops.py:restore_after_release`
- §3.8 — insert — ambiguity — convert-permanent retains the supplied `rationale` on the measure and echoes it — `routes_measures.py:81`
- §3.8 — insert — ambiguity — a substantiated closure leaves `converted_by_user_id` **and** `rationale` null, and the segregation rule of the explicit conversion does not carry over — `routes_cases.py:189`, `ops.py:make_measures_permanent`
- §3.8 — revise — mismatch — unsubstantiated closure runs the same all-or-nothing restoration (`SUSPENDED` only, never `LAPSED`); `records_retained_through` re-derived, `eligible_through` not re-stamped — `routes_cases.py:197-198`
- §3.9 — insert — ambiguity — `sampled_member_ids` stored and echoed in the caller's exact order, never sorted or canonicalised — `routes_audits.py:104`
- §3.9 — revise x3 — ambiguity — decision `note` 1–4,000; `ERR_FINDING_INVALID_STATE` precedes `ERR_AUDIT_INVALID_STATE`; a rejected remediation deliberately leaves `evidence_note` standing — `routes_audits.py:205,227-243`
- §3.9 — revise — ambiguity — a `SANCTION` over an audit both passing and free of open findings is refused `ERR_AUDIT_INVALID_STATE` — `routes_audits.py:266-268`

**Hand-off notes — all five resolved by pass 3**
1. `converted_by_user_id` null on substantiated closure — pinned in §3.8, together with the null `rationale` and the non-carry-over of segregation of duties.
2. `restore_after_release` — pinned twice (lift and unsubstantiated closure): the all-or-nothing clearance test, `LAPSED` staying `LAPSED`, and `eligible_through` never re-stamped by either compensating path.
3. Placement defaults — pinned: both e-comm fields start null with no default and stay null until an authorization is recorded.
4. `sampled_member_ids` order — pinned as order-preserving (impl does `list(...)` with no sort).
5. §2.8 step 8 — observable in all three of pass 3's write paths (`routes_coach.create_coach_assignment`, `routes_cases.file_case`, `routes_training.create_assignment`), so the rule is now listed in step 8 with its interaction with step 7, plus per-endpoint resolution-order sentences in §3.4/§3.6/§3.8.

**Closing consistency read (pass 3, as final pass)** — all 26 pass-1/2 hunks reviewed against pass 3's modules. Twenty-four consistent (§2.3 ordering matches `routes_rooms.py:30`'s `(check_in, created_at, _seq)` tuple; §2.5's start-of-request sweep explains why a past-`due_at` assignment still reads `ASSIGNED` in its creation response; §2.12's finding partition matches the audit counters; the transport-error prose matches `app.py`'s 404/405/500 handlers). Two contradicted pass 3's findings and were fixed minimally: §2.4's claim that the clock-driven lapse is the *only* exception to `version`+1, and §2.11's claim that club scope bites *only* on a single-resource read.

### Orchestrator verification of Step 9

- `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (`cmp` differs), so the scan genuinely ran — this is the known failure mode Step 9 must never exhibit.
- 436 lines / 120,561 chars vs 436 lines / 102,409 chars: +18,152 chars across 49 diff hunks; line count preserved because every edit was an in-paragraph insert or revision (no new sections, per the skill).
- 29 headings intact; tail still ends on the complete §5 error table (`ERR_ESCROW_INSUFFICIENT | 409`) — no truncation.
- No occurrence of the difficulty directive or the word "SCAFFOLD" anywhere in `PRD_COMPLETED.md`.
- No re-sweep was needed after Step 9: passes 1–3 edited only `PRD_COMPLETED.md`; `implementation/`, `test_suite/` and `test_helpers/` were untouched, so the clean 8-round result (8×90/90, `results.1..8.json`) remains the valid final test evidence.

## Pipeline complete — 2026-09-05T12:22:00.000Z

All nine steps finished. Final artifacts present: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `worklog.md`, `test_helpers/` (9 files), `test_suite/` (conftest + 17 test modules, 90 tests), `workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/, results.1..8.json}`.
