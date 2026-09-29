# Worklog — task_2952_resort_spa_operations_treatment_scheduling

## Step 1: Create task directory — 2026-09-05T21:25:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2952_resort_spa_operations_treatment_scheduling` and its `workspace/` subdirectory. Index pre-assigned by the orchestrating invocation (2952); no scan of `./tasks/` was performed, per instruction, to avoid collisions with the ~32 concurrent pipelines on this host.

## Step 2: Generate scaffold — 2026-09-05T22:57:30.000Z

All three deliverables are complete, structurally valid, and lint-clean.

**Files generated**

| File | Lines | Top-level keys |
|---|---|---|
| `SCAFFOLD.yaml` | — (125 KB) | `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — neither forbidden design key present |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | — (145 KB) | exactly `scaffold_difficulty_design` |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4870 (265 KB) | exactly `scaffold_corner_design` |

**SCAFFOLD.yaml counts (§1.0–§1.7):** 13 entities, 7 state machines, 2 concurrency rules (§1.2.1: `intake-form-create-stale-guest` / `expected_guest_version`, `settlement-create-stale-appointment` / `expected_appointment_version`), 7 calculations, 34 validations (single global priority ladder 1–34), 51 endpoints, 47 errors, 5 roles (SpaDirector, ComplianceOfficer, SpaCoordinator, Therapist `entity_backed:Therapist`, Guest `entity_backed:Guest`). Envelope is the standard `meta/response_type/data` pair; `api_prefix: ""`; logical clock defaults to `2026-08-01T00:00:00.000Z` and is monotonic.

**§1.8 difficulty design — 9 rule ids / 20 instances:** `dual_variant_calc` (2), `combinatorial_formula` (3), `non_linear_state_machine` (2), `transitive_cascade` (2), `priority_pair_validation_conflict` (3), `boundary_precision_check` (2), `cross_entity_state_dependency` (2), `resource_temporal_overlap` (2), `compensating_invariant` (2).

**§1.9 corner design — 9 sections in taxonomy order / 54 instances (43 active with `test_recipe`, 11 `excluded_because` stubs):** `entities` 8 (8 active), `state_machines` 9 (7), `calculations` 9 (7), `validations` 8 (8), `endpoints` 5 (4), `errors` 4 (1), `rbac` 4 (3), `cross_cutting_complexity_layers` 5 (3), `consistency_model` 2 (2).

**Lint verdict (verbatim, final run):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2952_resort_spa_operations_treatment_scheduling/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2952_resort_spa_operations_treatment_scheduling/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2952_resort_spa_operations_treatment_scheduling/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    51
  §1.1 entities declared:     13
  §1.8 instances scanned:     20
  §1.9 instances scanned:     43
  Calls scanned (§1.8+§1.9):  1251

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Extra verification beyond lint:** all 51 §1.5 endpoints are called at least once across §1.8 ∪ §1.9 (`endpoints never called: []`); all 47 §1.6 error ids are triggered somewhere; no instance `name` is duplicated across §1.8 ∪ §1.9; every active §1.9 instance carries `claim_type`, `grounds`, `distinguishing_aspect` and a four-key `test_recipe`, and every stub carries `excluded_because.{difficulty_instance, rationale}` with no `test_recipe`.

**Two issues fixed en route to clean:** two `expected_*_version` literals (lint check (e)) were replaced with captured `${…}` vars and the asserts reworded so the intended 412/403 still holds; and `GET /therapists/{id}/certifications` was initially never exercised — now covered in the endpoints list-filter instance via a second (revoked) certification plus filtered and unfiltered reads.

**Advisory for the orchestrator:** the scenario text was used verbatim as mandated, so `scenario:` in `SCAFFOLD.yaml` still begins with `Generate task harder than expert level!`. Per the known leak, that one line should be stripped before Step 3 so it does not reach PRD.md.

**Orchestrator post-step action:** acted on that advisory — stripped the `Generate task harder than expert level!` line (and its trailing blank) from `SCAFFOLD.yaml`'s `scenario:` block. Re-verified: the phrase appears in none of the three YAMLs, and all three still parse under `yaml.safe_load` with the expected top-level keys. Final line counts: SCAFFOLD.yaml 2590, SCAFFOLD_DIFFICULTY_DESIGN.yaml 2236, SCAFFOLD_CORNER_DESIGN.yaml 4870.

## Step 3: Copy shared files — 2026-09-05T22:57:45.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (bash-only step, no subagent).

## Step 4: Generate PRD — 2026-09-05T23:16:00.000Z

PRD.md is complete and verified.

**Deliverable:** `workspace/PRD.md` — **429 lines / 105,181 bytes**. Built incrementally (1 `Write` + 12 heredoc appends), no truncation; tail ends cleanly on the last error-table row (`| ERR_CLOCK_REWIND | 422 |`).

**`## ` section headings:** `# Resort Spa Operations API — Product Requirements Document`; `## 1. Introduction`; `## 2. Global Specifications & System-Wide Principles` (2.1 RBAC, 2.2 API Response Structure — verbatim block, byte-checked; 2.3 Pagination, 2.4 The Logical Clock, 2.5 Common Resource Properties and Immutable Records, 2.6 Money/Basis Points/Rounding, 2.7 Validation Precedence: The Thirty-Four-Rung Ladder, 2.8 Path Resolution and Reverse Reachability, 2.9 Optimistic Concurrency Control, 2.10 The Clearance Dimension and Cascade Discipline, 2.11 The Guest Folio, 2.12 Room and Therapist Minute Ledgers); `## 3. Business Logic & Workflows` (3.1 Treatment Menu and Room Inventory, 3.2 Therapist Roster, 3.3 Licensing/CE/Scope of Practice, 3.4 Guest Registration/Intake/Screening, 3.5 Booking — scheduling gate, auto-assignment, price quote; 3.6 Service Delivery, 3.7 Retail Attachment Programme, 3.8 Cancellations/No-Shows/Booking Privilege, 3.9 Settlement, 3.10 Compliance Sweeps and Management Reporting); `## 4. Endpoint Definitions`; `## 5. Error Code Catalogue`.

**Coverage (mechanically verified):** 13 entities all documented; 51 endpoints (table row count exactly 51, matching the 51 scaffold `method:` entries), each with method/path/description/authorized roles; 47 errors (row count exactly 47, statuses matched 1:1 — 401/403/404/409/412/402/422 spread preserved); 34 validations as 34 numbered rungs in §2.7 with error id, HTTP status and `applies_to` scope; 7 state machines / 31 transitions all present (the 8 apparent sweep "misses" were the 6 `NEW → X` creation transitions documented as creation-in-state, plus `BLOCKED → CLEARED` and `CHECKED_IN → CANCELLED`, both documented in prose as re-evaluation promotion and the compensating pre-treatment abort); 7 calculations (quote, assignment selector, settlement distribution both variants, cancellation charge, CE compliance both variants, room utilisation/margin, retail attachment rate) with all constants spot-checked as literal values in prose (multipliers 10,000/11,500/13,000/12,500; caps 2,000/8,000; 4,000 cents; 5,000/10,000 bp bands; 24 h / 4 h / 15 min / 120 min; 92 days; 48 h; 2,500 cents per 15-min block; 1,500/1,800 bp service tiers at the 50,000-cent threshold; 6,000/2,500/1,500 bp buckets; 3,000/3,800/4,500 and 1,200 bp commissions; 8 h category cap, 2 h ethics minimum, 24-month rolling window); 5 roles; 2 concurrency rules (`expected_guest_version` → `ERR_STALE_GUEST_VERSION` 412, `expected_appointment_version` → `ERR_STALE_APPOINTMENT_VERSION` 412) in §2.9 and restated at their endpoints.

**Hard Contracts:** Contract 1 PASS — a scripted sweep of all 149 scaffold identifiers found 142 verbatim in backticks; the 7 absent are internal *calculation names* only, deliberately expressed in prose. Contract 2 PASS. Contract 3 PASS — of 942 backticked spans in §3, zero start with `/`, are a bare HTTP method, or combine method+path. No fuzzy words anywhere; the only code fences are the two JSON blocks inside the verbatim §2.2.

**Scaffold ambiguities resolved** (preconditions the scaffold left without a nominated error id): licence-review expiry gate → `ERR_LICENSE_EXPIRED`; reinstatement credential gate → `ERR_LICENSE_NOT_VERIFIED` / `ERR_LICENSE_EXPIRED`; licence-filing, shift-block and certification date-consistency checks → `ERR_INVALID_REQUEST` (422); no-show grace-period earliness → `ERR_INVALID_APPOINTMENT_STATE`; `CertificationGrant` `LAPSED` documented as judged by `expires_on` comparison with revocation as the only exposed transition; `ERR_NO_ELIGIBLE_THERAPIST` positioned at the bottom of the booking ladder because the selector's eligibility filter subsumes the therapist-specific rungs. One naming correction caught during verification: the CE-compliance response key is `ce_hours_required` (not `required_hours`).

**Untouched, as required:** all three SCAFFOLD yamls, `worklog.md`, `workspace/INSTRUCTION.md`. The two design indices were never opened or grepped; no sibling task directory was read. Scratch confined to `.scratch/step4/`, removed on exit; `.scratch/step2/` left intact.

**Orchestrator verification of the known truncation failure mode:** independently re-ran `wc -l` (429), `wc -c` (105181), `grep -n '^#\{1,3\} '` (28 headings, §1→§5 contiguous, no gaps), and `tail -12`. The document ends at a real section boundary — the final row of the §5 error table — not mid-sentence. Also grepped PRD.md for `harder than expert`, `expert level`, `scaffold`, `test_recipe`: zero hits, so neither the difficulty directive nor any design-index vocabulary leaked into the contract. PRD accepted without regeneration.

## Step 6: Generate implementation — 2026-09-05T23:47:00.000Z

Implementation complete and verified.

## Modules emitted (`workspace/implementation/`, 3219 lines total)

| file | lines | role |
|---|---|---|
| `errors.py` | 130 | 47 error-ID constants, `HTTP_STATUS` map, `ApiError` |
| `envelope.py` | 87 | `meta`/`response_type`/`data` envelope, `iso3()` 3-digit timestamps, `req_`+20-char ids, pagination meta, `scrub()` (drops `_`-prefixed internals, Decimal→float) |
| `store.py` | 74 | 13 in-memory dicts + logical clock (epoch `2026-08-01T00:00:00Z`), `stamp_common`, `touch`, `_seq` tiebreaker |
| `validation.py` | 289 | rung-3 shape layer: typed field/query readers, instant/date parsing, pagination |
| `auth.py` | 65 | rungs 1–2 (authn/role) and rung 7 ownership helpers |
| `calc.py` | 293 | all money/CE math: `round_half_up` on `Decimal`, price quote, cancellation bands, 6-step settlement waterfall, CE `CALENDAR_WINDOW`/`ROLLING_24M` |
| `domain.py` | 480 | service layer: clearance predicate, block/re-clear cascades, capacity ledgers, folio posting, interval geometry, AUTO therapist ranking, `find_*` resolvers |
| `routes_catalog.py` | 290 | 11 endpoints (clock, treatment types, rooms, therapists, suspend/reinstate, shift blocks) |
| `routes_credentials.py` | 290 | 10 endpoints (licences, review/resubmit, CE records, ce-compliance, certifications) |
| `routes_guests.py` | 257 | 10 endpoints (guests, intake create/consent/submit/screen/override/amend) |
| `routes_appointments.py` | 666 | 16 endpoints (book, confirm, check-in, start, complete, cancel, no-show, retail attachments, settlements, folio lists) |
| `routes_reports.py` | 204 | 3 endpoints (compliance sweep, room-utilization, retail-attachment) |
| `app.py` | 83 | blueprint wiring, error handlers (404/405/400→422, generic→500), `threading.Lock` WSGI serializer, `PORT` bind |
| `start.sh` | 10 | `exec python3 app.py` in foreground, `PORT` from env (default 10000), `0.0.0.0` |

**Endpoint count: exactly 51** (url_map enumeration reports 52 including Flask's built-in `/static/<path:filename>`), matching PRD §4 one-for-one.

## Validation precedence ladder
The 34 rungs are realised as ordered code, not scattered checks: rungs 1–2 in `auth.authenticate()` at the top of every handler, rung 3 entirely in `validation.py` (all field readers run before any lookup, so shape always beats existence), then rungs 4–6 (path/body resolution via `domain.find_*`, duplicate codes), rung 7 ownership, rung 8 OCC, rung 9 state legality, and rungs 10–31 as composable gates (`clinical_gate` 12–14, `credential_gate` 15–16/19–20, `room_gate` 21–22) invoked in ladder order inside each handler. Booking is the deepest: guest→type→room→therapist resolution → ownership → clinical → credentials → room → shift/conflict → turnover → lead time → booking privilege → AUTO selection with `ERR_NO_ELIGIBLE_THERAPIST` last. Rung 32 lives in `report_window()`, 33 in the clock setter, 34 in intake amend.

## Smoke-test evidence
Two servers, both on high random ports. First (`PORT=22640`) took 10 targeted curls: `POST /treatment-types` 201, `POST /treatment-rooms` 201, `GET /treatment-rooms/{id}` 200, no headers → 401 `ERR_UNAUTHENTICATED`, wrong role → 403 `ERR_ROLE_NOT_PERMITTED`, dup code → 409 `ERR_DUPLICATE_CODE`, unknown id → 404 `ERR_ROOM_NOT_FOUND`, `limit=0` → 422 `ERR_INVALID_REQUEST`, clock set → 200, rewind → 422 `ERR_CLOCK_REWIND`. Then a 54-request end-to-end script (`.scratch/step6/flow.py`) with hard assertions on computed money — all passed: licence → 2 CE records → `ce-compliance` (12 credited / 4 ethics / compliant) → SoD-refused self-review 409 → verify → certification → shift block → guest → intake (stale-version 412) → consent → submit → screen → book (quote 20000, room ledger 75 min, therapist 60 min, double-book 409) → confirm → check-in (provisional: pool 3600, therapist 2160, support 900, house 540, folio 23600, labor 13160, margin 840) → owner-check 403 → start → retail line-mismatch 409 → attach → gratuity-cap 422 → complete(65 min, 5000 tip) → final settlement (basis 65, pool 8600, therapist 5160, support 2150, house 1290, labor 16577, room 6500, folio 28600, adjustment posting 5000) → both reports (utilization 5.56%, attach rate 0→100%, commission 600) → bad window 422 → AUTO booking → director suspend → cascade `BLOCKED/THERAPIST_SUSPENDED` → check-in 409 → reinstate → re-clear → clock to 2027 → sweep (expired licence, `LICENSE_EXPIRED` suspension, blocked + auto-cancelled appointment, capacity released). Second server on a fresh random port confirmed the clock reads `2026-08-01T00:00:00.000Z` again, i.e. `start.sh` re-invocation wipes all state.

**Kill confirmation:** each server was killed only by resolving its own listener with `lsof -tiTCP:$MYPORT -sTCP:LISTEN` and `kill`-ing that single PID (3094657, then 3131249), verifying the port went free. No `pkill`, no pattern kill, no signal to any process I did not start.

## Compliance with constraints
No reads of `test_helpers/`, `test_suite/`, the two design yamls, or any sibling task dir. Storage is plain dicts — a grep for `sqlite|open(|json.dump|pickle|shelve|/tmp` in the implementation returns nothing; zero seeded rows. `PRD.md`, `INSTRUCTION.md`, `worklog.md` and the three SCAFFOLD yamls are untouched. `python3 -m compileall -q .` is clean, `__pycache__` removed, and no `results.*.json`/logs in the implementation dir (smoke artifacts live in `.scratch/step6/`).

## PRD ambiguities resolved
- Licence `decision`: prose says `VERIFIED`/`REJECTED`, §4 table says `VERIFY`/`REJECT` — all four spellings accepted.
- `started_at`/`completed_at` are in §4 but not the scaffold entity — included, null by default.
- `parse_instant` treats a naive instant as UTC rather than 422-ing legitimate fixtures.
- `clearance_block_reason` is always re-derived from the four-clause predicate (§2.10), which self-consistently yields `LICENSE_INVALID` for the sweep, `THERAPIST_SUSPENDED` for director suspension, and lets `INTAKE_FLAGGED` win when clauses collide.
- `Guest` aborting a `CHECKED_IN` appointment → 403 `ERR_ROLE_NOT_PERMITTED`, evaluated after rung 9 picks the abort path, before the rung-10 clearance check.
- Unresolvable ids in *optional query filters* match nothing instead of 404 (the catalogue scopes not-found to path/body).
- Settlement creation checks OCC (rung 8, 412) before state legality (rung 9, 409) — ladder wins over §3.9 prose order.
- Missing/malformed report `from_at`/`to_at` and malformed CE `as_of` → `ERR_INVALID_REQUEST` (rung 3); only ordering/span violations → `ERR_INVALID_REPORT_WINDOW`.
- Guest `version` bumps exactly once per request even when folio + counter + privilege all change.
- AUTO booking folds rungs 15/16/19/20/23/24 into the eligibility filter and fails last at rung 31.
- `amend` replaces `condition_codes`/`medications`, defaulting to `[]` when omitted.
- Reinstatement's licence gate has no `state_code` clause (prose omits it).
- Sweep hop 2 only reconsiders therapists whose licence expired in hop 1; reported arrays contain only newly affected rows.
- `reason_note` on suspend/revoke is validated but not persisted (no scaffold field).
- Percentages and CE hours serialise as JSON floats.

**Orchestrator verification:** confirmed `test_helpers/` and `test_suite/` are at the task root with no stray copies under `workspace/` (the known Step 5 mislocation bug did not occur).

## Step 5: Generate unit tests — 2026-09-06T00:55:00.000Z

Done. Final report.

## Deliverables

Both directories are at the **task root** — confirmed by `ls -d`, and `workspace/test_helpers` / `workspace/test_suite` do **not** exist.

`test_helpers/` (9 files, 1,912 lines): `__init__.py` 122, `api_client.py` 261, `api_errors.py` 118, `assertions.py` 218, `constants.py` 238, `factories.py` 245, `fixtures.py` 354, `test_users.py` 82, `types.py` 274.

`test_suite/` (conftest + 18 files, 7,402 lines): `conftest.py` 50; `test_01` 268, `test_02` 259, `test_03` 212, `test_04` 244, `test_05` 243, `test_06` 225, `test_07` 223, `test_08` 196, `test_09` 235 (queue A); `test_10` 511, `test_11` 599, `test_12` 1009, `test_13` 1213, `test_14` 543, `test_15` 181, `test_16` 498, `test_17` 409, `test_18` 284 (queue B).

## Coverage

**123 tests, 63 distinct `Design:` tags, 0 audit problems.**

- Queue A (§1.8): 20 instances, 0 stubs — **20/20 translated**.
- Queue B (§1.9): 54 instances, 11 `excluded_because:` stubs — **43/43 non-stub translated**.
- Zero MISS, zero ORPHAN tags (every tag resolves to a real instance; every non-stub instance has >=1 test).
- All 11 stubs' `difficulty_instance` cross-references resolve to real §1.8 instance names, and every referenced instance is itself translated.

## Skips

No whole instance was skipped. Four sub-claims were dropped rather than weakened:

1. **Ladder instance's lead-time sub-claim** (`Difficulty/priority_pair_validation_conflict/...`) — vacuous under the fixture clock; not assertable without contradicting a higher rung. Non-unique-derivability.
2. **`GET /appointments` `from_at`/`to_at` window filtering** — §2.3/§4 name the two params but never say which instant field they filter or whether the bounds are inclusive. Non-unique-derivability.
3. **`meta.api_request_timestamp` equals the logical clock** — §2.2 only says "server-generated"; asserted as a well-formed instant instead. PRD-silence.
4. **Relative order of the TREATMENT and SETTLEMENT_ADJUSTMENT folio postings** in test_17 — they share one `posted_at`, so §2.11's ascending-`posted_at` order does not derive a sequence; asserted as a multiset via `assert_folio_contents`.

Two yaml claims were *corrected* (PRD governs), not skipped: the restriction cascade does auto-cancel the other `REQUESTED` appointment (§3.8), and a guest's intake forms list newest-first (§2.3/§3.4/§4), not `created_at` ASC.

## Checks

- `python3 .scratch/step5/check_tests.py` — every test carries exactly one `Design:` line as its docstring's last line; every >=25-char quoted docstring run appears verbatim (whitespace-normalised) in `workspace/PRD.md`. PROBLEMS: 0.
- `python3 -m compileall -q test_helpers test_suite` — clean (byte-code dirs removed afterwards).
- `python3 -m pyflakes test_helpers test_suite` — no unused imports, no undefined names; the only two remaining notes are intentional `_world` bindings in test_06.
- `workspace/PRD.md`, `workspace/INSTRUCTION.md`, `worklog.md` and the three SCAFFOLD yamls are untouched; no stray worklog anywhere; scratch confined to `.scratch/step5/`; `workspace/implementation/` never read or listed.

**One substantive find worth flagging to the implementation side:** `test_helpers/api_client.py` had shipped five methods for endpoints PRD §4 never defines (`GET /treatment-types`, `GET /treatment-types/{id}`, `GET /treatment-rooms`, `GET /therapists`, `GET /guests`), and three tests called them. The methods were deleted and the three assertions rewritten against PRD-legal observations, so a correct implementation is no longer required to expose phantom routes. All 42 surviving paths were re-derived against the §4 table.

**Orchestrator note on concurrency:** Steps 5 and 6 were launched in a single assistant message, so the implementation generator started before `test_suite/` existed on disk and was physically unable to read the tests it must satisfy.

## Step 7: Run tests and iterate — 2026-09-06T01:07:15.000Z

All 8 rounds green. Done.

## Summary

**Iterations run:** 2 (iteration 1 = baseline diagnosis, iteration 2 = verification after fixes).

**Iteration 1 result:** 118/123 in all 8 rounds — 5 failures, *identical and deterministic in every round* (no flakiness, no load-induced failures, no SIGTERM/`Terminated` pattern).

**Tests deleted:** none. All 5 failing tests passed STEP 1a (verbatim PRD coverage) and STEP 1b (unique derivability).

**Fixes applied to `test_helpers/`:** none — the shared fixture layer was clean.

**Fixes applied to `test_suite/`:**
- `test_11_state_machine_corners.py`, module constant `SETTLEMENT_ADJUSTMENT_CENTS` (used by `test_a_second_final_settlement_is_refused_on_state_not_on_version`) — was hardcoded `7954`, but the test's own failure message and PRD §3.9 ("`folio_total_cents` less the sum of `amount_cents` over every folio posting already recorded against that appointment") both give `58454 - 50504 = 7950`. Replaced the literal with the subtraction of the two constants the same test already asserts, so the arithmetic can no longer drift.
- `test_16_rbac_corners.py`, `test_the_owning_guest_makes_the_same_calls_successfully` — asserted the check-in `TREATMENT` posting equals `quoted_price_cents` (18000). PRD §3.6 says the posting's `amount_cents` "is that row's `folio_total_cents`", which is `realized + retail + service_charge_pool + gratuity` = 21240. The assertion mis-translated the PRD; it now compares against the provisional settlement row's `folio_total_cents` read back through `GET /appointments/{id}/settlements?variant=PROVISIONAL`. The owner-read of the appointment is retained as its own assertion so the RBAC coverage is unchanged.

**Fixes applied to `implementation/`:**
- `validation.py`, `INSTANT_RE` + `parse_instant` — the regex accepted a space separator, omitted seconds, an omitted timezone designator, and arbitrary `+/-HH:MM` offsets (silently converting them). So `"2026-08-10 10:00"` parsed as a valid instant (masking rung 3 and letting rung 5 answer `ERR_GUEST_NOT_FOUND`), and `"2026-08-05T09:00:00.000+02:00"` was normalised to 07:00Z and answered `ERR_CLOCK_REWIND` instead of `ERR_INVALID_REQUEST`. Tightened to `T`-separated, whole seconds, optional fractional digits, mandatory `Z`, and dropped the offset-conversion branch. Traced to PRD §2.5 ("must be a valid ISO 8601 UTC instant... A malformed value is rejected with `ERR_INVALID_REQUEST`") and §3.5, which forecloses the permissive reading outright: the peak band uses "the UTC hour of the submitted instant and never a local-time conversion". This one change fixed 3 of the 5 failures (the two rung-ordering tests in `test_13` and the clock test in `test_14`). I verified no test in the suite submits an instant spelling this now rejects.

**Final sweep evidence (iteration 2):**

| round | passed/total | failed | errors | skipped |
|---|---|---|---|---|
| 1 | 123/123 | 0 | 0 | 0 |
| 2 | 123/123 | 0 | 0 | 0 |
| 3 | 123/123 | 0 | 0 | 0 |
| 4 | 123/123 | 0 | 0 | 0 |
| 5 | 123/123 | 0 | 0 | 0 |
| 6 | 123/123 | 0 | 0 | 0 |
| 7 | 123/123 | 0 | 0 | 0 |
| 8 | 123/123 | 0 | 0 | 0 |

`worklog.md`, `workspace/PRD.md` and the three SCAFFOLD yamls are untouched (mtimes unchanged); sibling scratch dirs `.scratch/step2`, `step5`, `step6` are intact.

**Orchestrator independent verification (the known "claimed-clean sweep with no artifacts" failure mode):** re-read all 8 `workspace/implementation/results.$i.json` directly — every round reports `{'passed': 123, 'total': 123, 'failed': 0, 'errors': 0, 'skipped': 0}`, with a fresh `SWEEP_DONE` sentinel. Confirmed the green sweep post-dates the fixes rather than being a stale pre-fix artifact: the three edited files carry mtimes 01:01:57 (`validation.py`), 01:02:05 (`test_11`) and 01:02:21 (`test_16`), the sweep completed at 01:06:21, and `find test_suite test_helpers workspace/implementation -name '*.py' -newer SWEEP_DONE` returns empty — no post-sweep edits could have invalidated the gate. Test count is still 123 (nothing silently dropped, consistent with 0 deletions), and a grep for `sqlite3|json.dump|pickle|shelve|/tmp/` across the implementation is clean, so storage remains in-memory only. Step 8 is NOT skipped: the run applied 1 `implementation/` fix and 2 `test_suite/` fixes, so the skip condition (0 of everything) does not hold.

## Step 8: Finalize PRD — 2026-09-06T01:19:00.000Z

Done.

## Line counts
- `PRD.md`: 429 lines / 105,181 bytes (byte-identical to its original state — untouched)
- `PRD_FINALIZED.md`: 429 lines / 105,946 bytes
- Delta: 0 lines (0.00%), +765 bytes; exactly 1 line revised (line 100), no lines added or removed.

## Changes
- **§2.5 (Common Resource Properties and Immutable Records)** — *revise* — Pinned the single accepted spelling of a client-submitted instant: fixed-width `YYYY-MM-DDTHH:MM:SS`, literal `T`, whole seconds mandatory, optional `.` plus one-to-nine fractional digits, mandatory literal `Z`; surrounding whitespace trimmed; any other spelling malformed rather than interpreted — space separator, omitted seconds, absent `Z`, and numeric offsets (`+02:00`, `+00:00`) all rejected, with offset-bearing values never converted to UTC. Also noted the rule covers query-parameter instants as well as body fields. — `implementation/validation.py:23-25` (`INSTANT_RE`), `:51-64` (`parse_instant`).

## Per-edit pre-edit search log

**Edit 1 — §2.5 instant spelling**
- (a) **Subject:** the accepted lexical form of every client-submitted datetime, and what happens to non-canonical/offset-bearing spellings.
- (b) **Impl paths enumerated:** grepped all of `implementation/*.py` for `field_instant|query_instant|parse_instant|field_date|query_date|parse_date|fromisoformat|isoformat|strftime`. Every instant input funnels through the single `validation.parse_instant` -> `INSTANT_RE`; there is no second parser anywhere. Callsites read and confirmed consistent: `routes_catalog.py:37` (`current_utc`), `:253-254` (shift-block `start_at`/`end_at`), `:278-279` (shift-block list `from_at`/`to_at` query), `routes_appointments.py:102` (booking `start_at`), `:192-193` (appointment-list `from_at`/`to_at` query), `routes_reports.py:97-98` via `report_window()` (required report `from_at`/`to_at`, which raise `ERR_INVALID_REQUEST` on a malformed value and `ERR_INVALID_REPORT_WINDOW` only after both parse — consistent with rung 3 preceding rung 32, so no §2.7/§3.10 edit was needed). Also checked the output side (`envelope.py:19-24` `iso3`, `:45-48` `scrub`) to be sure the new wording describes only *submitted* values and does not contradict the three-fractional-digit response format; and checked `parse_date`/`DATE_RE` so the date-only clause stayed verbatim.
- (c) **Wording adjustments made:** (1) added "whether it arrives in the request body or as a query parameter" because `query_instant` shares the same regex, so the rule is genuinely universal rather than body-only; (2) added the explicit second example `2026-08-01T09:15:00Z` since the regex makes the fractional part optional — a wording that implied three digits were mandatory would have been a new mismatch; (3) bounded the fractional part at "one to nine" digits to match the regex rather than claiming unlimited precision, while deliberately staying silent on how sub-millisecond digits are truncated internally (under-determined rather than a false claim); (4) added "surrounding whitespace is trimmed before the value is matched" because `parse_instant` calls `value.strip()`, so an absolute "no other spelling" claim would have been false for padded input; (5) said offsets are "rejected outright ... never converted to UTC" rather than naming only `+02:00`, since the dropped branch covered every offset including `+00:00`.

## Items intentionally left unpatched
- `test_11` `SETTLEMENT_ADJUSTMENT_CENTS` literal — pure test arithmetic bug. `routes_appointments.py:613-618` computes `folio_total_cents` minus the sum of all postings already recorded against that appointment, which §3.9 already states verbatim.
- `test_16` check-in posting assertion — pure test bug. `routes_appointments.py:310-318` posts `figures["folio_total_cents"]`, which §3.6 already states verbatim ("`amount_cents` is that row's `folio_total_cents`") and §3.9 already defines as `realized + retail + service_charge_pool + gratuity`.

**Orchestrator verification:** `PRD.md` is unmodified (mtime still 09-05 23:13:37, its Step 4 write time; 429 lines / 105,181 bytes). `PRD_FINALIZED.md` is NOT byte-identical to it — `diff` yields exactly one changed hunk at line 100 (4 diff lines: `100c100` plus the two versions and the separator), matching the single reported edit. No code, test, or scaffold file was touched by this step.


## Step 9: Complete PRD — 2026-09-06T02:02:00.000Z

**Orchestrator design decision (recorded per the autonomy directive).** Step 9 was run as **four sequential passes partitioned by implementation module**, each editing the one shared `workspace/PRD_COMPLETED.md` in place, rather than as a single scan. Reason: a single-pass scan over a 14-module / 51-endpoint implementation has previously no-op'd silently, leaving `PRD_COMPLETED.md` byte-identical to its source — the one outcome Step 9 must never produce. Partitioning gives each pass a small enough lane to walk exhaustively, and the monotonically growing `diff` line count is hard evidence that each pass's edits actually landed on top of its predecessors'. Pass 1 alone performed the `cp` from `PRD_FINALIZED.md`; passes 2–4 were explicitly forbidden to copy, and each verified the expected pre-edit line/char count before its first edit so a clobbered file would have been caught immediately. Lanes: pass 1 = global layer (`errors.py`, `envelope.py`, `store.py`, `validation.py`, `auth.py`, `app.py`); pass 2 = `calc.py` + `domain.py`; pass 3 = `routes_catalog.py` + `routes_credentials.py` + `routes_guests.py`; pass 4 = `routes_appointments.py` + `routes_reports.py`. Each pass handed forward the out-of-lane behaviors it noticed, and the orchestrator relayed those notes into the next pass's prompt so nothing fell between lanes.

**Progression (diff lines vs `PRD_FINALIZED.md`):** pass 1 → 36, pass 2 → 60, pass 3 → 160, pass 4 → 228. Char count 105,946 → 110,242 → 112,047 → 119,933 → 126,740.

### Pass 1 — global layer (errors/envelope/store/validation/auth/app)
Confirmed `cp PRD_FINALIZED.md PRD_COMPLETED.md`. 430 lines / 110,242 chars; diff 36. **8 ambiguity-pins, 1 mismatch-revision.**
- §2.1 — insert — ambiguity — header emptiness is literal (nothing trimmed), so a whitespace-only `X-User-ID`/`X-User-Role` clears rung 1 and is matched against the role list as-is, determining 401 vs 403 — `auth.py:40`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A`–`Z`/`0`–`9` — `envelope.py:16`
- §2.2 — insert — ambiguity — `api_request_timestamp` is the **logical clock** instant with exactly three fractional digits, identical across responses while the clock stands still — `envelope.py:30`
- §2.2 — revise — mismatch — error envelope covers 4xx **and 5xx** — `app.py:68-72`
- §2.2 — insert — ambiguity — transport-level failures: unknown path → `ERR_INVALID_REQUEST` at HTTP **404**, wrong method → **405**, framework-unintelligible request → **422** (all deviating from §5's mapping for that id); trailing slash insignificant; unexpected fault → `ERR_INTERNAL` at 500 (deliberately not in §5) — `app.py:37,53-72`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` is the same shape violation; an empty-valued query parameter (`?limit=`) equals omitted for **every** optional query parameter (an empty filter applies no filter); out-of-range `offset` is an empty page, not an error — `validation.py:227-231,239-252,280`
- §2.3 — insert — ambiguity — ordering tiebreaker: equal `created_at` breaks by ascending mint order, "newest first" is the exact reverse of that total order, and the same tiebreaker settles equal `posted_at` and `start_at` — `store.py:69-74`
- §2.5 — insert — ambiguity — every server-emitted instant carries exactly three fractional digits + `Z` regardless of the submitted spelling; every emitted date-only field is `YYYY-MM-DD` — `envelope.py:19-24,45-48`
- §2.5 — insert — ambiguity — whitespace trimming and single-spelling strictness extend to date-only fields; a well-formed but non-existent date (`2026-02-30`) is malformed — `validation.py:67-78`
- §2.7 rung 3 — insert — ambiguity — strict non-coercing type discipline (string = JSON string >=1 char so `""` fails; integer = JSON integer so booleans, digit strings and `30.5`/`30.0` fail; enum = listed string; code lists = arrays of strings); explicit `null` counts as absent (required fails, optional takes default); absent/unparseable body reads as `{}` and a non-object body is itself a shape violation — `validation.py:33-40,85-90,100-128,167-191`
- Confirmed matching with no edit: all 47 error ids/statuses in §5 match `errors.py` exactly; §2.5's unversioned-record list matches the only two `versioned=False` call sites.

### Pass 2 — calc.py + domain.py
Pre-edit check 430 / 110,242 (passes-1 state confirmed). Final 430 / 112,047; diff 60. **6 ambiguity-pins, 0 mismatch-revisions** — every formula, bp constant, grace, threshold inclusivity and the six-step waterfall already matched the PRD verbatim; the gaps were all silences at tie-breaks and edge boundaries.
- §2.10 — insert — ambiguity — a cascade re-evaluating an already-`BLOCKED` appointment rewrites the reason but is not a fresh block: not reported among newly blocked ids, and its `RECOMMENDED` attachments are not expired again (a recommendation created while already blocked survives); a re-clearing cascade considers only `BLOCKED` rows and leaves `PENDING` alone; a no-op re-evaluation mutates nothing — neither `updated_at` nor `version` moves — `domain.py:263-278,284-298`
- §2.11 — insert — ambiguity — the folio-limit comparison is strict: a projected total exactly equal to `folio_limit_cents` is permitted; only a strictly greater total fails — `domain.py:186`
- §3.3 — insert — ambiguity — the `ROLLING_24M` lower anchor is the same day-of-month two calendar years earlier, clamped back to that month's last day when it does not exist (29 February `as_of`) — `calc.py:104-110,247`
- §3.5 — insert — ambiguity — when a therapist holds several qualifying grants for the required skill, the AUTO ranking's second key uses the *highest* scope rank among them — `domain.py:129-133,402`
- §3.5 — insert — ambiguity — the fourth ranking key (`created_at` ASC) is itself completed by creation order, since a still clock lets two therapists share one `created_at`; earliest-minted wins — `domain.py:400-406`
- §3.4 — insert — ambiguity — authoritative-form selection: after `created_at` then greater `version`, any remaining tie goes to the later-minted form — `domain.py:144-145`
- §3.9 — insert — ambiguity — the shortfall credit's "missing minutes" are the whole `scheduled - actual` difference; the five-minute grace only gates whether a credit arises and is never deducted from it — `calc.py:176-180`

### Pass 3 — routes_catalog.py + routes_credentials.py + routes_guests.py
Pre-edit check 430 / 112,047 (passes-1-2 state confirmed). Final 430 / 119,933; diff 160. **21 ambiguity-pins, 10 mismatch-revisions** (31 in-place Edits, no lines added or removed).
- §2.4 — revise — ambiguity — `current_utc` required (null/omitted = `ERR_INVALID_REQUEST`); echo carries exactly that one key in the uniform 3-digit instant format — `routes_catalog.py:33-42`
- §2.7 rung 7 — revise — mismatch — rung said a Therapist caller is compared to "the appointment's `therapist_id`"; impl compares to the **path** therapist on self-read and shift-block list — `routes_catalog.py:188,281`
- §2.7 rung 32 — revise — mismatch — rung claimed a bad CE `as_of` yields `ERR_INVALID_REPORT_WINDOW`; impl raises `ERR_INVALID_REQUEST` at rung 3 — `routes_credentials.py:226`
- §3.1 — revise — ambiguity — menu `name` 1..200 chars — `routes_catalog.py:54`
- §3.1 — revise — ambiguity — `contraindication_codes` stored verbatim (no case/registry check); `retail_product_line` <=200, `required_consent_version` <=64 — `routes_catalog.py:61-64`
- §3.1 — revise — ambiguity — room `code` has no character-class rule (unlike a menu code); uniqueness is exact string equality — `routes_catalog.py:99,107`
- §3.1 — revise — ambiguity — PATCH payload is `status` alone and required; all other room attributes (incl. `turnover_buffer_minutes`) immutable; no state gate, so a same-status patch is accepted, bumps `version`, and re-runs the cascade for the resulting status — `routes_catalog.py:134-149`
- §3.2 — revise — ambiguity — therapist `full_name` 1..200 — `routes_catalog.py:160`
- §3.2 — revise — mismatch — suspension `reason_note` (<=500) is validated then **discarded**; only the coded `suspension_reason` is stored — `routes_catalog.py:197`
- §3.2 — revise — ambiguity — shift `note` <=500; the `end_at > start_at` rule is rung 3 so it beats `ERR_THERAPIST_NOT_FOUND`; blocks are never validated against one another — `routes_catalog.py:255-258`
- §3.2 — revise — ambiguity — shift-block `from_at`/`to_at` are inclusive comparisons against `start_at` only (no overlap test); Therapist ownership on the listing and self-read — `routes_catalog.py:278-289`
- §3.3 — revise — ambiguity — `license_number` 1..64 — `routes_credentials.py:37`
- §3.3 — revise — mismatch — the three filing conditions fire in impl order (`expires_on`>`issued_on`, then `current_period_start_on`<=`expires_on`, then `state_code` behind path resolution); nothing else is cross-checked — `routes_credentials.py:47-54`
- §3.3 — revise — mismatch — `decision` accepts four spellings (`VERIFY`/`VERIFIED`, `REJECT`/`REJECTED`); `review_note` <=1000 — `routes_credentials.py:102-114`
- §3.3 — revise — ambiguity — resubmission leaves `credited_ce_hours` intact, cannot replace `issued_on`/`license_type`/`state_code`, and re-checks nothing — `routes_credentials.py:150-177`
- §3.3 — revise — ambiguity — `course_code` 1..64 — `routes_credentials.py:189`
- §3.3 — revise — ambiguity — CE filing has no licence-state gate and no date gate on `completed_on` — `routes_credentials.py:185-206`
- §3.3 — revise — ambiguity — `skill_code` 1..32 uppercase; date rule is rung 3; grants may be filed already expired; multiple matching grants resolve to the highest rank — `routes_credentials.py:244-249`, `domain.py:129`
- §3.3 — revise — mismatch — revocation has **no** state gate (re-revoking or revoking an expired grant succeeds and bumps `version`); `reason_note` discarded — `routes_credentials.py:280-290`
- §3.4 — revise — ambiguity — guest `full_name` <=200, `resort_room_number` <=32 and not unique — `routes_guests.py:30-31`
- §3.4 — revise — ambiguity — `expected_guest_version` required, non-negative integer, judged at rung 3 before the 412 — `routes_guests.py:71`
- §3.4 — revise — mismatch — consent is legal from `DRAFT`/`SUBMITTED` **only** (PRD said "before or after screening"); repeatable and overwriting; `consent_version` <=64; plus the full initial-field block (`amendment_round` 0, all review/override fields null) and no cap on concurrent forms — `routes_guests.py:83-99,137-143`
- §3.4 — revise — ambiguity — `flagged_condition_codes` preserves the form's own code order and collapses duplicates — `routes_guests.py:173-178`
- §3.4 — revise — ambiguity — an override mutates the form only; the guest row is untouched, so guest `version` does not move and the pointer stays on the `OVERRIDDEN` form — `routes_guests.py:218-223`
- §3.4 — revise — ambiguity — amendment replaces both lists wholesale and defaults each to `[]`, so omitting one clears it; consent fields survive; `override_reason` 1..1000 — `routes_guests.py:231-251`
- §4 rows — revise — PATCH room (status-only/immutability), suspend (`reason_note` accepted but not persisted), review (decision spellings), shift-blocks list (bounds against `start_at`, Therapist self-only), consent (DRAFT/SUBMITTED only), amend (lists replace wholesale, default `[]`)

### Pass 4 — routes_appointments.py + routes_reports.py (final lane)
Pre-edit check 430 / 119,933 (passes-1-3 state confirmed). Final 430 / 126,740; diff 228 across 57 hunks. **20 ambiguity-pins, 3 mismatch-revisions.**
- §3.5 — insert — ambiguity — `started_at`/`completed_at` are present-and-null on the created appointment — `routes_appointments.py:162,174-175`
- §3.6 confirm — revise — **mismatch** — PRD said `clearance_status` "moves `PENDING -> CLEARED`"; impl writes `CLEARED` unconditionally, so a `REQUESTED`/`BLOCKED` row whose clauses were repaired without a re-clearing cascade is also driven to `CLEARED` — `routes_appointments.py:286-287`
- §3.6 check-in — insert — ambiguity — a pre-existing settlement row of *either* variant yields `ERR_INVALID_APPOINTMENT_STATE`, judged ahead of the clearance rung — `routes_appointments.py:301-306`
- §3.6 check-in — insert — ambiguity — answers with the updated **appointment** (not the settlement row) and HTTP 200 despite minting a row — `routes_appointments.py:320`
- §3.6 start — revise — **mismatch** — "beyond `schedule_status`, `updated_at` and `version` ... no field changes" omitted `started_at`, which impl stamps — `routes_appointments.py:342-343`
- §3.6 complete — revise — **mismatch** — "writes both submitted values ... and stops there" omitted the `completed_at` stamp — `routes_appointments.py:371`
- §3.7 — insert — ambiguity — `product_sku`/`product_line` are each 1..64 chars, `amount_cents` has no upper bound, and a >64-char line is `ERR_INVALID_REQUEST` not `ERR_PRODUCT_LINE_MISMATCH` (the treatment's `retail_product_line` allows 200) — `routes_appointments.py:497-499`
- §3.8 — insert — ambiguity — `cancel_reason` is <=500 chars, validated then discarded (no field on the row) — `routes_appointments.py:410`
- §3.8 abort — insert — ambiguity — a `Guest` on the checked-in path gets `ERR_ROLE_NOT_PERMITTED` (403), judged *after* the state rung and *before* the clearance requirement — `routes_appointments.py:421-427`
- §3.8 abort — insert — ambiguity — the abort leaves `clearance_status` `BLOCKED` and the reason intact — `routes_appointments.py:429-431`
- §3.9 — insert — ambiguity — `expected_appointment_version` must be a non-negative integer, and the three refusals are listed in narrative not precedence order (rung 8 outranks rung 9, so a stale version wins over the state/already-final errors) — `routes_appointments.py:588-600`
- §3.9 — insert — ambiguity — the `SETTLEMENT_ADJUSTMENT` posting is written unconditionally, including when the difference is exactly 0 — `routes_appointments.py:613-618`
- §3.10 sweep — insert — ambiguity — HTTP 200 (mints no resource), all five arrays always present-and-possibly-empty, plus each array's ordering — `routes_reports.py:82-89,35-58`
- §3.10 hop 2 — insert — ambiguity — only therapists whose licence hop 1 just expired are examined, and the survival test **ignores `state_code`** (unlike §2.10's licensing clause), so a therapist holding an out-of-state valid licence escapes suspension and is never visited by the later hops — `routes_reports.py:48-58`
- §3.10 hop 3 — insert — ambiguity — `LICENSE_INVALID` is subject to §2.10's reason precedence, so a simultaneously intake-flagged appointment records `INTAKE_FLAGGED` — `routes_reports.py:64` / `domain.py:219-238`
- §3.10 hop 5 — insert — ambiguity — the auto-cancellation does not rewind the clearance dimension — `routes_reports.py:76-80`
- §3.10 room-util — insert — ambiguity — unrecognised `room_id` → empty `rooms` array not `ERR_ROOM_NOT_FOUND`; `window_minutes` truncated toward zero (sub-minute window ⇒ 0 / `0.00` / 0); the filter is not echoed; rooms ordered by `created_at` — `routes_reports.py:123-129,125,162,165-170`
- §3.10 retail — insert — ambiguity — unrecognised `therapist_id` → count 0 and `attach_rate_pct` `0.00`, never `ERR_THERAPIST_NOT_FOUND` — `routes_reports.py:181-185`
- §3.10 — insert — ambiguity — `ERR_INVALID_REPORT_WINDOW` is reserved for ordering/span; an omitted/empty/malformed bound is rung-3 `ERR_INVALID_REQUEST`; neither report paginates (object envelope) — `routes_reports.py:96-106,82,165,196`
- §2.7 rung 32 — insert — ambiguity — the same missing/malformed-bound split — `routes_reports.py:97-98`
- §4 preamble — insert — ambiguity — object-returning computed reads are not list endpoints and accept no `limit`/`offset` — `routes_reports.py:82,165,196`
- §4 `GET /appointments` — insert — ambiguity — the four id filters are exact-equality with no 404 on an unknown value; `from_at`/`to_at` compare against `start_at` alone and are **both inclusive**, unlike §3.10's half-open windows — `routes_appointments.py:196-211`
- §4 `GET /appointments/{id}/folio-charges` — insert — ambiguity — ascending `posted_at`, coinciding with §2.3's default order — `domain.py:82-85`

**Pass 4 declared its lane exhausted** (all 19 endpoints walked field-by-field) and recorded four residuals it judged out of scope for every lane, with reasons: per-endpoint list ordering for `GET /appointments` and the retail-attachment listing (already pinned globally by §2.3, an insert would duplicate pass 1's prose); §2.3's "three list endpoints deviate" count (the appointment-scoped folio listing sorts by `posted_at`/`_seq`, technically a fourth deviator, but `posted_at` is always the same `db.clock` value as `created_at` so the two orders are observationally identical — pinned in the §4 row as consistent with the default rather than desynchronising pass 1's count); two unreachable defensive branches (`actual_duration_minutes or 0` at `routes_reports.py:139`, and the check-in existing-settlement guard, since no transition returns a settled appointment to `CONFIRMED`) — the guard's error id was pinned, the arithmetic fallback left undocumented; and `report_window()`'s body-field read order, which affects only the human-readable `message` string that §2.2 does not pin.

**Orchestrator final verification.**
- `PRD_COMPLETED.md` exists at 430 lines / 126,740 chars and is **not** byte-identical to `PRD_FINALIZED.md` (`cmp` differs; 228 diff lines) — the Step 9 no-op failure mode did not occur.
- `PRD.md` (429 / 105,181, mtime 09-05 23:13:37) and `PRD_FINALIZED.md` (429 / 105,946, mtime 09-06 01:18:42) are both unmodified — Steps 9's passes wrote only to `PRD_COMPLETED.md`.
- `find test_suite test_helpers workspace/implementation -name '*.py' -newer results.1.json` returns empty: **no code was touched after the green sweep**, so the 8/8 123/123 result remains the valid gate for the shipped implementation. Steps 8 and 9 were documentation-only, as required.
- Structural integrity of the final document: 28 headings (§1–§5 contiguous), 51 endpoint rows in §4 and 47 `ERR_` rows in §5 — identical to the `PRD.md` baseline — and the markdown pipe-count histogram is unchanged from baseline (`{3: 49, 5: 53}`), so no table row was malformed by 57 hunks of in-paragraph editing. The tail ends at a real boundary (final §5 error row).

## Pipeline note: worklog cwd-drift incident and repair — 2026-09-06T02:05:00.000Z

Recording an orchestrator error and its correction, for the durable record.

Bash working directory persists between tool calls in this harness. The verification call that immediately preceded the Step 8 log ran `cd workspace && wc -lc PRD.md PRD_FINALIZED.md`, leaving the shell inside `workspace/`. The Step 8 logging call then used a bare relative `cat >> worklog.md`, so the entire Step 8 entry was appended to a newly created **`workspace/worklog.md`** instead of the canonical `worklog.md` at the task root. The root worklog consequently jumped straight from Step 7 to Step 9.

Detected during the final tree inspection (a `worklog.md` appeared in the `workspace/` listing where the output contract expects only `INSTRUCTION.md`, the three PRDs and `implementation/`). Repaired by splicing the stray file's Step 8 entry back into the root worklog at its correct chronological position — immediately before the Step 9 heading — and then deleting the stray. The splice was verified to be purely additive: `diff` of the pre-splice backup against the merged file reports **0 deleted lines**, so no previously written entry was altered or lost, preserving the append-only contract. The root worklog now carries all nine step entries (order of Steps 5 and 6 reflects completion order, since they ran concurrently and Step 6 finished first), and exactly one `worklog.md` exists anywhere under the task directory.

Every other logging call in this run used an absolute path or an explicit `cd` to the task root, so Step 8 was the only entry affected.
