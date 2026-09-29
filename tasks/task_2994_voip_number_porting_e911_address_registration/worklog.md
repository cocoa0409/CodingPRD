# Worklog — task_2994_voip_number_porting_e911_address_registration

## Step 1: Create task directory — 2026-09-06T03:32:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2994_voip_number_porting_e911_address_registration` and its `workspace/` subdirectory. Index 2994 was pre-assigned by the orchestrating harness; no scan of `./tasks/` was performed (concurrent pipelines on this host make auto-allocation unsafe).

## Step 2: Generate scaffold — 2026-09-06T04:40:00.000Z

All three scaffold artifacts are complete, valid YAML, and the lint is clean.

## Deliverables

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` | 2976 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1383 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3135 |

`SCAFFOLD.yaml` top-level keys are §1.0–§1.7 only (no `scaffold_difficulty_design`/`scaffold_corner_design`); the other two files each have exactly one top-level key. Shape: 14 entities, 10 state machines, 2 concurrency rules, 12 calculations, 53 validations, 52 endpoints, 53 errors, 8 roles; `domain_name: voip-porting-e911`, `api_prefix: /voip`.

## Counts
- §1.8: **9 rules x 2 = 18 instances** (all nine §0.5 rule types, globally unique names).
- §1.9: **84 instances across 9 sections** — 63 real `test_recipe` instances + 21 `excluded_because` stubs, every stub citing an existing §1.8 instance name (verified programmatically). Sections: entities 12, state_machines 14, calculations 13, validations 13, endpoints 7, errors 12, rbac 5, cross_cutting_complexity_layers 7, consistency_model 1.

## Lint
```
Coverage
  §1.5 endpoints declared:    52
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     63
  Calls scanned (§1.8+§1.9):  670

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
First lint pass reported 8 violations, all from one cause: the negative-instance exemption regex matches `_returns_4\d\d`, not the literal `_returns_4XX` I had used. Renamed three §1.9 instance names to `_returns_403`; second pass clean.

## Design adjudications
1. **§1.2-vs-§1.5 actor conflicts (5 transitions)** — resolved in favour of §1.5+§1.7: `CarrierLiaison`->`PortingSpecialist` on all four `complete-cutover`-triggered transitions, and `AccountAdmin`->`NumberingAdmin` on PhoneNumber `ASSIGNED->PARKED`.
2. **Resubmittable rejection codes** — added `ACCOUNT_NOT_FOUND` to the PortRequest state machine's set so it agrees with validation priority 13.
3. **`ERR_NUMBER_RESERVATION_OVERLAP` reachability** — priority 17 now lets a RESERVED number take a further disjoint hold, so priority 48 is reachable.
4. **New: `PortRequest.created_by_user_id`** — validation priority 29 (segregation of duties) compared X-User-ID against "the user recorded on the port request's own creation", but no §1.1 field held it. Added it as a `source: system` field and made the `POST /voip/port-requests` side effect name it explicitly, mirroring `FeeAssessment.assessed_by_user_id`.
5. **Dropped `scheduled_slot_id` asserts** — two §1.9 instances I drafted asserted a PortRequest field that §1.1 does not declare; the scheduling link lives on `CutoverSlot.booked_port_request_id`, so the asserts were rewritten against that instead of inventing a field.

Every numeric assert was computed before transcription (e.g. RELAXED CSR match at exactly 85; business-day FOC floor `2026-08-06 + 3 -> 2026-08-11`; `round_half_up(175*17/31) = 96`; fraud scores 39/49/59/69 across four one-minute calls at a frozen clock, straddling `FRAUD_BLOCK_THRESHOLD 60`).

### Orchestrator post-step action
The subagent flagged that `SCAFFOLD.yaml`'s `scenario:` block retained the verbatim first line `Generate task harder than expert level!`. That directive is for the scaffold generator only and is a known leak path into PRD.md, so the orchestrator deleted that line (and its trailing blank line) from `SCAFFOLD.yaml` immediately after Step 2 and re-verified the file still parses as valid YAML with all 13 §1.0–§1.7 top-level keys intact. `SCAFFOLD.yaml` is now 2974 lines. Verified via grep that the phrase appears in none of the three scaffold files.

## Step 3: Copy shared files — 2026-09-06T04:40:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-06T05:00:00.000Z

PRD generation is complete.

## Deliverable

`workspace/PRD.md` — **521 lines / 111,389 chars** (paragraphs are single long lines, so line count understates volume). Written via one `Write` plus six `cat >> ... <<'PRD_EOF'` appends; the file ends on the final row of the §5 error table, at a real section boundary.

## Sections

- §1 Introduction
- §2 Global Specifications (11 subsections): 2.1 RBAC · 2.2 API Response Structure (verbatim from the skill) · 2.3 Pagination · 2.4 Logical Clock & Temporal Semantics · 2.5 Common Resource Properties & Immutable Records · 2.6 Optimistic Concurrency · 2.7 Validation Precedence (all 53 rules as an ordered ladder) · 2.8 Nested Addressing · 2.9 Money, Counts & Rounding · 2.10 Segregation of Duties · 2.11 Cascades & Derived-State Recomputation
- §3 Business Logic (9 subsections): 3.1 Reference data · 3.2 Number inventory · 3.3 Reservations · 3.4 Port-in filing, CSR comparison, correction · 3.5 Cutover calendars & booking · 3.6 Bridging, completion, unwind cascade · 3.7 Devices, dispatchable locations, nomadic relocation · 3.8 Call gating, toll-fraud scoring, international spend · 3.9 Fee assessment, voiding, remittance
- §4 Endpoint Definitions (4-column table, 52 rows)
- §5 Error Code Catalogue (2-column table, 53 rows)

## Coverage verification (programmatic, YAML-loaded, code-fence-stripped)

| Check | Result |
|---|---|
| 14 entity names | 14/14 |
| 120 entity field names, backticked | 120/120 — all also present in §2/§3 prose, not only tables |
| 81 endpoint `input` / query-param / path-param identifiers | 81/81 — all in prose |
| 52 method+path rows in §4 | 52/52 exact match |
| 53 error ids | 53/53 in §5 **and** all 53 in §2/§3 prose |
| 53 validation rules in §2.7 ladder | 53 numbered entries, priorities 1–53, no gaps, every `error_id` present |
| 39 distinct state names across 10 state machines | 39/39 backticked |
| 8 roles | 8/8 |
| 2 concurrency rules | both narrated in §2.6 |
| 12 calculations | all narrated in §3 |

**Hard Contract 1 (Field-Name Coverage): PASS.** **Hard Contract 2 (Rule Coverage): PASS.** **Hard Contract 3 (§3 Path Purity): PASS** — zero backticked tokens in §3 start with `/`, are a bare HTTP method, or combine method+path; zero raw `/voip` or `METHOD /` occurrences anywhere in §3. Leak scan for `SCAFFOLD`, `test_recipe`, `difficulty`, `approximately`, `roughly`: zero hits. `worklog.md` and `SCAFFOLD.yaml` untouched; `.scratch/step4/` removed (parent `.scratch/` left in place).

## Scaffold self-contradictions resolved (each pinned to one choice per the Zero-Silence Rule)

1. **Reservation window equality** — `calculations.reservation_interval_capacity` rejects `reserved_until <= reserved_from`, but validation 43 and the error catalogue both permit equality. Followed the calculation (strictly later). *Accepted risk: a test written from the error-catalogue wording would expect equality to pass.*
2. **Port-request reject/cancel source statuses** — validation 11 disagrees with the state-machine rows and their `note:` lines; followed the state machine (reject from `{SUBMITTED, CSR_MISMATCH, VALIDATED, SCHEDULED, BRIDGED}`, cancel from all six non-terminal statuses).
3. **`ERR_ACCOUNT_E911_BLOCKED` scope** — validation 25's `applies_to` omits cutover booking, but the `VALIDATED -> SCHEDULED` precondition names it; included booking and edited the §2.7 ladder to match.
4. **Remittance sentinel** — endpoint side-effect says `system:remittance`, entity field and state machine say `system:remittance-run`; chose `system:remittance-run` (2-of-3).
5. **Silences closed by explicit decision** (no scaffold rule existed): list tie-breaks pinned to insertion order in both directions; an `UNVERIFIED` prior registration is superseded too (preserving the one-current-registration invariant); which `CallAttempt` computed fields are stored at each gate (steps 1–2 always; day-level fields and `realtime_risk_score` are 0 when the refusal precedes their gate, and `Device.toll_fraud_score` is left untouched then); domestic attempts record `day_subtotal_cents`/`surcharge_pct_applied`/`projected_day_total_cents` as 0 with no cap check; `BLOCK_INTL`/`BLOCK_ALL` never weaken a stronger existing block; `REVIEW_UNBLOCK` on an already-`UNRESTRICTED` device still runs both gates; `note` and `void_note` are accepted but not persisted (no field exists); `PER_LOCATION` anchor tie-break is `created_at` then `id`; a remittance run skips accounts already `REMITTED` for the triple, making a re-run money-idempotent.

### Orchestrator verification (truncation guard)
Independently checked `PRD.md` after the subagent exited: 521 lines / 111,877 bytes on disk, `tail` confirms the file ends on the final `ERR_REMITTANCE_PERIOD_NOT_CLOSED | 422` table row (a real section boundary, not mid-sentence), section headings run §1 -> §5 with no gaps, and a grep for `harder than expert`, `scaffold`, `test_recipe` returns zero hits. No regeneration needed.

## Step 6: Generate implementation — 2026-09-06T05:35:00.000Z

(Recorded before Step 5's entry because Steps 5 and 6 ran concurrently and Step 6 returned first.)

Implementation complete and verified. Summary follows.

## Files written — `workspace/implementation/`

| File | Lines |
|---|---|
| `app.py` | 57 |
| `common.py` | 212 |
| `errors.py` | 77 |
| `lookup.py` | 73 |
| `store.py` | 49 |
| `util.py` | 127 |
| `validate.py` | 186 |
| `routes/__init__.py` | 0 |
| `routes/reference.py` | 163 |
| `routes/inventory.py` | 324 |
| `routes/porting.py` | 465 |
| `routes/devices.py` | 343 |
| `routes/e911.py` | 141 |
| `routes/fees.py` | 106 |
| `services/__init__.py` | 0 |
| `services/derive.py` | 157 |
| `services/porting.py` | 165 |
| `services/fraud.py` | 109 |
| `services/fees.py` | 144 |
| `requirements.txt` | 1 (`flask>=2.2`) |
| `start.sh` | 10, executable |

2898 Python lines. All modules pass `ast.parse`. `__pycache__` removed.

## Parity
- **Endpoints: 52 / 52.** Flask's `url_map` registers exactly 52 non-static rules, path-for-path and method-for-method against the PRD §4 table (including the unprefixed `POST /_clock/set_current_utc`).
- **Error ids: 53 / 53.** `ERROR_STATUS` exactly equals the set of `ERR_*` ids in `PRD.md` (a diff showed only my own regex truncating at digits, e.g. `ERR_ACCOUNT_E911_BLOCKED`).
- **Storage:** 14 plain in-memory dicts plus a clock/seq dict. Greps for `sqlite`, `pickle`, `shelve`, `/tmp`, `json.dump`, `open(...,'w')` return nothing. No seeding.

## Smoke test (port 47994)
Three scripted passes over one process, **135 requests, zero 500s**: 71x200, 28x201, 8x400, 2x401, 5x403, 2x404, 12x409, 2x412, 5x422. Matching the access log against `url_map` shows **all 52 route/method pairs exercised, none missed**.

Verified behaviour includes: envelope + `req_`/3-fractional-digit clock timestamps; `ERR_INVALID_PAGINATION` on `limit=0` and `offset=-1`; both OCC endpoints returning 412 on a stale version; CSR STRICT scoring (100 -> `VALIDATED` + `earliest_cutover_at` 2026-08-06 from a 3-business-day FOC; 60 -> `MISMATCHED` with `mismatch_fields` sorted); buffer-expanded slot-overlap 409 at +20 min vs 201 at +65 min; bridge activation refused outside the window then accepted inside; E911 supersede/verify driving device `REGISTERED` and the posture sweep (`AT_RISK` -> nomadic device `INTL_BLOCKED`, `COMPLIANT` -> back to `UNRESTRICTED`); call-attempt audit rows persisted with scores (domestic 6, UK 29); prorated provisional fee of 87 cents (150 x 18/31, half-up) and the remittance run voiding provisionals with the `system:remittance-run` sentinel, writing a `FINAL`/`REMITTED` 150-cent row and moving the jurisdiction to pending 0 / remitted 150; SoD 403 on csr-post, reject and void; the full reject unwind cascade (slot `RELEASED` with nulls -> bridge `ORPHANED` with `released_at` -> reservation `RELEASED`/`BRIDGE_ORPHANED` -> number `RESERVED -> PARKED` +168 h, `park_cycle_count` 1 -> census recomputed); resubmission budget and `ERR_REJECTION_NOT_RESUBMITTABLE` on `NUMBER_NOT_PORTABLE`; release + reclamation returning parked numbers to `AVAILABLE` only after `parked_until`.

Two `start.sh` properties were confirmed directly: `$!` from `bash start.sh &` **is** the listening Python PID (`exec` semantics hold — an earlier apparent leak was my own `cd X && ... &` compound forking a subshell, not the script), and a fresh boot on the same port comes up with empty collections and the clock back at `2026-08-01T00:00:00.000Z`. Only the exact captured PIDs were killed; no pattern kills. Port 47994 is free and `.scratch/step6` is removed (`.scratch/step5` untouched).

## PRD ambiguities resolved
- `api_request_timestamp` is rendered from the logical clock, not wall time; instants parse leniently (0–6 fractional digits, `Z`/`+-00:00`) but always serialise with exactly 3 digits.
- Whitespace-only auth headers are treated as empty -> 401.
- `ERR_ACCOUNT_NOT_ACTIVE` on a call attempt persists no `CallAttempt` row (no `decision` enum value fits); every gate that does have a decision value persists the row before raising.
- Call-attempt fraud fields bump the device `version` only when a value actually changes; a refused `REVIEW_UNBLOCK` stores the DAILY_REVIEW score without bumping.
- Block `version` increments unconditionally on census recomputation, whereas posture, ledger and ported-count recomputes bump only on real change.
- `FINAL` remittance rows are created and driven to `REMITTED` within one request at `version` 1; a second run for an already-remitted account is skipped rather than duplicated.
- Bridge activation with no `BOOKED` slot yields `ERR_BRIDGE_ACTIVATION_OUTSIDE_WINDOW`.
- Assigning a device to a `RESERVED` number prefers a `HELD` `NEW_LINE` reservation of the same account; otherwise the earliest `HELD` row supplies the 409/422.
- `complete-cutover` applies the same "no other `HELD` reservation remains" guard as a manual release; a `VERIFIED` outcome drives the device to `REGISTERED` unconditionally.
- Ladder ordering: for endpoints whose role list includes `AccountAdmin` the path resource is resolved before body parsing (rule 3 ownership precedes rules 4–5); elsewhere body shape and pagination precede id resolution. Creation endpoints compare the body-named owner as a raw string before validation.
- Where the scaffold and the PRD disagreed (reject/cancel source statuses; scaffold priority 33's extra clause) the PRD won.

## Step 5: Generate unit tests — 2026-09-06T05:47:00.000Z

(Ran concurrently with Step 6, in a single orchestrator dispatch pair; returned second, hence recorded after Step 6.)

Step 5 is complete and verified.

## Files written (all at the TASK ROOT, nothing under `workspace/`)

`test_helpers/` — 2,383 lines
| file | lines |
|---|---|
| `__init__.py` | 33 |
| `api_client.py` | 240 |
| `api_errors.py` | 123 |
| `assertions.py` | 378 |
| `constants.py` | 173 |
| `factories.py` | 449 |
| `fixtures.py` | 638 |
| `test_users.py` | 121 |
| `types.py` | 228 |

`test_suite/` — 7,419 lines, **112 tests**
| file | lines | tests |
|---|---|---|
| `conftest.py` | 45 | — |
| `test_01_variant_divergence_and_formulas.py` | 775 | 11 |
| `test_02_nonlinear_states_and_cascades.py` | 718 | 12 |
| `test_03_precedence_and_boundaries.py` | 767 | 10 |
| `test_04_dependencies_overlaps_and_invariants.py` | 913 | 16 |
| `test_05_entities.py` | 498 | 12 |
| `test_06_state_machines.py` | 734 | 9 |
| `test_07_calculations.py` | 646 | 8 |
| `test_08_validations.py` | 577 | 9 |
| `test_09_endpoint_round_trips.py` | 481 | 6 |
| `test_10_errors.py` | 497 | 10 |
| `test_11_rbac_and_cross_cutting.py` | 768 | 9 |

## Design-index coverage

- **§1.8 difficulty: 18 / 18 non-stub instances translated, 0 skipped** — 49 tests, every instance carrying 2 or 3.
- **§1.9 corner: 63 / 63 non-stub instances translated, 0 skipped** — 63 tests, 1:1.
- **Skipped: only the 21 corner stubs**, each of which the yaml itself marks `excluded_because` (state_machines 5, calculations 5, validations 4, endpoints 1, errors 2, cross_cutting 4). **No instance was skipped for PRD-silence or non-unique-derivability.**

## Verification I ran myself (not just agent claims)

- `def test_` count == `Design:` count, per file and in aggregate (112 == 112); zero duplicate test names.
- An AST pass over all 11 files: every test has exactly one `Design:` line, it is the last docstring line, and **every tag resolves to a real non-stub instance** in the correct yaml section (`rule_id` for difficulty, `section` for corner). Zero problems; zero stub tags.
- `py_compile` clean on all 20 files; a real import pass of all 11 test modules through `test_helpers` resolves every name.
- All 41 distinct `ApiErrorId` members referenced exist; **zero raw `"ERR_*"` string literals** anywhere.
- `api_client.py` has exactly 52 methods against the PRD §4 table's 52 rows, with every path segment present.
- Hazard greps all clean: no `parked_at` / `window_length_minutes` / `MISSING_OVERDUE` / `rejection_code` (the `last_rejection_code` hits are the real PRD field, confirmed in PRD.md); the sentinel is `system:remittance-run` in all 5 occurrences; no `" "` blank headers; no date-only instant literals; no money-as-string; no `xfail`/`skip`/`TODO`; no double-unwrap of the `data` envelope; no `scaffold` / `design index` / `§1.x` leakage (the `§` hits are all PRD section references, which is legitimate).

## One real fix I made during verification

An AST sweep found that 14 `fixtures.py` helpers took `**overrides` straight into a request payload without popping `headers`, so a future `headers=` kwarg would have been silently POSTed as a body field. No live call site was affected (the only `headers=` call sites, in test_01, target `run_remittance`, which already popped correctly), but I hardened the 8 atomic ones — `seed_account`, `seed_carrier`, `seed_jurisdiction`, `seed_number_block`, `seed_phone_number`, `seed_reservation`, `verify_registration`, `apply_restriction` — to `headers = overrides.pop("headers", None) or <role default>`, then recompiled and re-ran the import pass. This matters for Step 7, which will want non-default actors on those calls.

## Notes for the orchestrator

- `PRD.md`, `worklog.md` and all three `SCAFFOLD*.yaml` are untouched by me. `worklog.md`'s recent mtime is Step 6's own entry, not a Step 5 subagent.
- `.scratch/step5/` survived intact (`SPEC.md` plus `verify_tags.py`, the tag checker, if Step 7/9 want to re-run it).
- Step 6's worklog records adjudications that may collide with test expectations in Step 7 — notably "bridge activation with no `BOOKED` slot yields `ERR_BRIDGE_ACTIVATION_OUTSIDE_WINDOW`" and "`ERR_ACCOUNT_NOT_ACTIVE` on a call attempt persists no `CallAttempt` row". Those are contract questions for Step 7 to adjudicate against the PRD, not test-artifact bugs.
- `validate_unpaginated` exists in `assertions.py` but is unused: all 54 list assertions use `validate_paginated`, which is correct here since every collection endpoint in this contract is paginated.

### Orchestrator verification
Confirmed independently: `test_helpers/` and `test_suite/` both sit at the task root, `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation/` and the pre-written `sweep.sh` (no stray `workspace/test_*` dirs). `grep -c "def test_"` over `test_suite/` totals 112, matching 112 `Design:` tags. All `__pycache__` dirs cleared before Step 7.

## Step 7: Run tests and iterate — 2026-09-06T06:00:00.000Z

All 8 rounds passed on the first sweep — no test or implementation changes were needed.

## Summary

**Iterations run:** 1 (single 8-round sweep; exit condition met immediately).

**Tests deleted:** none. No test failed in any round, so no PRD-coverage or unique-derivability adjudication was triggered.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:** none.

**Fixes applied to `implementation/`:** none.

**Final sweep evidence** (from `workspace/implementation/results.$i.json`):

| Round | passed/total |
|---|---|
| 1 | 112/112 |
| 2 | 112/112 |
| 3 | 112/112 |
| 4 | 112/112 |
| 5 | 112/112 |
| 6 | 112/112 |
| 7 | 112/112 |
| 8 | 112/112 |

**Validation of the green result** (guarding against the known false-green shapes):
- Sweep was launched via `setsid nohup bash .../workspace/sweep.sh` and completion was confirmed only by the `workspace/SWEEP_DONE` sentinel (~4 min wall time, `duration_seconds` ~ 199s per round).
- Schema cross-check: each `results.$i.json` reports `total: 112, passed: 112, failed: 0, errors: 0, skipped: 0`, and the `tests[]` array holds exactly 112 entries with 112 distinct `name` values, all `status: "passed"`. `total - passed == 0` reconciles with 0 parsed failures, so the summarizer is keyed correctly on `status`/`error_message`.
- No round log contains `Terminated`, so no round was reaped mid-request; all 8 runner processes exited cleanly with their own `Results: 112/112 passed` line and released their ports normally.

**Incidental audit** (not a fix, just confirmation the green isn't an artifact): `workspace/implementation/store.py` holds all 14 collections as plain module-level Python dicts with `_state = {"clock": CLOCK_EPOCH, "seq": 0}`, and a grep for `sqlite|open(|json.dump|/tmp|pickle|shelve` across the implementation returns nothing — storage is in-memory only, with no startup seeding, so `start.sh` re-invocation wipes all state as required.

The only file I created is the scratch summarizer at `.scratch/step7/summarize.py`; `worklog.md` and the `SCAFFOLD*.yaml` files were not read or written.

### Orchestrator independent verification
Because a Step 7 subagent can report a clean sweep without one having happened, the orchestrator re-parsed all 8 `results.*.json` itself rather than trusting the summary. Confirmed: 8 files on disk; each `total=112 passed=112 failed=0 errors=0 skipped=0` with `len(tests)==112` and every entry `status="passed"`; the union of non-passed test names across all 8 rounds is empty; per-round `duration_seconds` clusters tightly at ~199.3s (consistent with 8 genuinely concurrent rounds, not a truncated or copied artifact); `grep -l Terminated workspace/round.*.log` returns nothing, ruling out sweep reaping. The green is real.

## Step 8: Finalize PRD — SKIPPED — 2026-09-06T06:01:00.000Z

Step 8's documented skip condition is met exactly: Step 7 exited on the first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. With an empty `<step_7_diff>` there is no PRD-silence or PRD-mismatch site for Step 8 to target, and spawning the subagent could only produce unmotivated edits outside its hard scope. No `PRD_FINALIZED.md` is produced; Step 9 therefore starts from `workspace/PRD.md`, as the skill specifies for the Step-8-absent case.

Decision recorded by the orchestrator under the run's autonomy directive (no user available to confirm).

## Step 9: Complete PRD — 2026-09-06T07:35:00.000Z

Run as FOUR sequential module-partitioned passes over one shared `workspace/PRD_COMPLETED.md`, rather than one monolithic pass. Rationale (orchestrator decision under the run's autonomy directive): a single agent scanning 2898 lines of implementation against a 111KB PRD reliably runs out of working context and returns a byte-identical no-op file. Pass 1 owned the `cp`; passes 2–4 were explicitly forbidden from re-copying (which would have discarded their predecessors' edits). Each pass was given a disjoint slice of `implementation/` and a disjoint slice of PRD territory, told to report rather than edit out-of-partition findings, and pass 4 existed solely to close the cross-pass contradictions the partitioning necessarily produced.

Source file: `workspace/PRD.md` (521 lines / 111,877 chars). Step 8 was skipped, so no `PRD_FINALIZED.md` existed.
Final: `workspace/PRD_COMPLETED.md` — 522 lines / 133,944 chars (**+22,067 chars, +1 line**, 109 changed lines).

**Totals across the four passes: 63 changes — 45 ambiguity-pins, 18 mismatch-revisions.** One new line (a bullet inside an existing §2.2 list); no new sections at any point (headings constant at 28).

### Pass 1 — core machinery + reference + inventory (app/common/errors/lookup/store/util/validate, routes/reference, routes/inventory)
21 changes (18 pins, 3 mismatches), confined to §2.1–§2.11, §3.1–§3.3, §4 intro:
- §2.1 — insert — ambiguity — whitespace-stripped header values, so a whitespace-only header is empty -> `ERR_UNAUTHENTICATED` — `common.py:66-68`
- §2.1 — insert — ambiguity — no endpoint admitting `PhoneNumber`/`NumberReservation` comparands authorizes `AccountAdmin`, so rule 2 turns it away first and those comparands never fire — `reference.py:74`, `inventory.py:56,106,279`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars (24 total) — `util.py:28-29`
- §2.2 — insert — ambiguity — new bullet: undefined path/method -> `ERR_RESOURCE_NOT_FOUND` 404; unparseable JSON body -> `ERR_INVALID_REQUEST` 400 — `app.py:34-43`
- §2.3 — insert — ambiguity — empty-string `limit`/`offset` fall back to defaults, whitespace ignored, decimals/exponents/leading `+` are non-integers; pagination sanity settles BEFORE filter-enum checks so `ERR_INVALID_PAGINATION` beats `ERR_INVALID_REQUEST` — `common.py:121-143`
- §2.3 — insert — ambiguity — `has_more` = `offset + returned < total_count` — `common.py:45`
- §2.3 — insert — ambiguity — an id-shaped filter naming a nonexistent resource is not an error; empty page, `total_count` 0 — `inventory.py:64-67`
- §2.4 — insert — ambiguity — clock response `data` carries exactly `current_utc` + `previous_utc`; instant required; backwards moves permitted; first move reports the epoch — `reference.py:24-33`
- §2.4 — revise — mismatch — PRD demanded 3 fractional digits on SUPPLIED instants too; impl only EMITS that shape and accepts a lenient grammar (fraction optional/any width truncated at microseconds; `T`/`t`; `Z`/`z`/`+00:00`/`-00:00`). Separated emission from acceptance — `util.py:16-18,32-60`
- §2.7 rule 4 — insert — ambiguity — declared-input endpoints require a JSON object body; JSON null counts as absent; bool-where-int is a type error; unrecognized fields ignored; no-input endpoints accept and ignore any body — `common.py:102-115`, `validate.py:16,100`
- §2.8 — insert — ambiguity — "body fields in document order" only orders references sharing a ladder rung; an unresolvable `Account` outranks an unresolvable `NumberBlock`/`PhoneNumber` because rule 6 precedes rule 9 — `inventory.py:219-221`
- §2.11 — revise — mismatch — "every entity a cascade touches has its version incremented" is false: block census is rewritten and bumped unconditionally, while posture/account liability/jurisdiction counters/ported count compare first — `services/derive.py:22` vs `:100-146`
- §3.1 — insert — ambiguity — all five `Carrier` inputs required — `reference.py:88-92`
- §3.1 — insert — ambiguity — all five `Jurisdiction` inputs required — `reference.py:122-126`
- §3.2 — insert — ambiguity — all four `NumberBlock` inputs required; `max_concurrent_reservations` unbounded — `inventory.py:29-32`
- §3.2 — insert — ambiguity — reclaimed `PARKED` numbers tie-break on insertion order after `created_at` — `inventory.py:163`
- §3.2 — insert — ambiguity — expiring `HELD` reservations processed `created_at` asc, insertion-order tie-break; expiry sets no `released_reason`; non-`RESERVED` number untouched — `inventory.py:170-179`
- §3.3 — insert — ambiguity — automatic selection adds insertion order as final tie-break — `inventory.py:203`
- §3.3 — insert — ambiguity — when the named number was already `RESERVED` the number row is not rewritten but the census still recomputes and the block `version` still +1 — `inventory.py:270-273`
- §3.3 — insert — ambiguity — releasing a reservation whose number stays `RESERVED` still recomputes census and bumps block `version` — `inventory.py:317-323`
- §4 intro — revise — mismatch — "Every endpoint below is rooted at the `/voip` prefix" is false for `/_clock/set_current_utc`; also pinned trailing-slash acceptance — `app.py:24`, `reference.py:24`

### Pass 2 — porting / CSR / cutover / bridging (routes/porting, services/porting, services/derive)
19 changes (13 pins, 6 mismatches), in §3.4–§3.6 and four §4 rows:
- §3.4 — insert — ambiguity — `requested_numbers` stored/echoed in supplied order, never sorted — `routes/porting.py:50`, `validate.py:178`
- §3.4 — insert — ambiguity — all five claimed values incl. `claimed_pin` echoed verbatim, never masked — `routes/porting.py:81`
- §3.4 — insert — ambiguity — CSR comparison is strictly on normalized forms, so two punctuation-only values both reducing to `""` count as equal and score their weight — `services/porting.py:38-41`, `util.py:112`
- §3.4 — insert — ambiguity — `expected_port_request_version` is a precondition only, not persisted on the snapshot — `routes/porting.py:131,150-159`
- §3.4 — insert — ambiguity — superseding a snapshot is a write: refreshes `updated_at`, +1 to that snapshot's `version` — `services/porting.py:161-165`
- §3.4 — insert — ambiguity — same version-bump note on the resubmission path — `routes/porting.py:217`
- §3.5 — insert — ambiguity — window length is the span FLOORED to whole minutes (residual seconds discarded), so 480m30s passes and 59m59s fails — `services/porting.py:62`
- §3.6 — insert — ambiguity — CONFIRMED impl-gen's flag: no `BOOKED` slot naming the request yields `ERR_BRIDGE_ACTIVATION_OUTSIDE_WINDOW`, never `ERR_BRIDGE_SLOT_NOT_BOOKED` — `routes/porting.py:426-428`
- §3.6 — insert — ambiguity — nothing caps a request at one bridge; activating a second on an already-`BRIDGED` request still bumps `version` — `routes/porting.py:433-436`
- §3.6 — insert — ambiguity — REFINED impl-gen's flag: the live-bridge guard hangs on the `SCHEDULED` path only; completion from `BRIDGED` is never blocked and a still-`PROVISIONED` bridge is left untouched with its reservation `CONSUMED` — `routes/porting.py:304-310`, `services/porting.py:152-153`
- §3.6 — insert — ambiguity — a consumed slot retains `booked_at` as well as `booked_port_request_id` — `services/porting.py:148-151`
- §3.6 — revise — mismatch — CONFIRMED impl-gen's flag: completion's number-release is gated on `RESERVED` AND no surviving `HELD` reservation; when the gate fails the census is NOT recomputed and block `version` does not move — explicitly contrasted with §3.3's always-recompute manual release — `services/porting.py:106-123` vs `routes/inventory.py:316-323`
- §3.6 — revise — mismatch — same two-condition gate on the orphan/park path: number stays `RESERVED`, no `parked_until`, no `park_cycle_count` bump, no census recompute — `services/porting.py:114-123`, `services/derive.py:26-31`
- §3.6 — insert — ambiguity — rejection `note` is unbounded free text, validated then discarded — `routes/porting.py:227`
- §3.6 — insert — ambiguity — cancel body may be omitted entirely; `reason_note` likewise discarded — `routes/porting.py:249-250`
- §4 reject row — revise — mismatch — "rejection of a scheduled port" -> any live request `SUBMITTED`..`BRIDGED` — `routes/porting.py:21`
- §4 cancel row — revise — mismatch — "Cancels a rejected port request" -> any non-terminal status incl. `REJECTED`, same unwind cascade — `routes/porting.py:22,252`
- §4 complete-cutover row — revise — mismatch — "releasing any bridge" -> releasing any **`ACTIVE`** bridge — `services/porting.py:152-153`
- §4 cutover-slots row — revise — mismatch — said the CANDIDATE window is buffer-expanded, contradicting §3.5; now says every live slot of the carrier is expanded (algebraically identical predicate, but the two passages disagreed) — `services/porting.py:82-84`

Pass 2 independently re-verified pass 1's §2.11 wording against `services/derive.py` and confirmed it exactly (`recompute_census` bumps unconditionally at `:14-23`; the other four compare before writing at `:103-110, 123-126, 134-136, 155-157`). No contradiction.

### Pass 3 — devices / E911 / calls / fraud / fees / remittance (routes/devices, routes/e911, routes/fees, services/fraud, services/fees)
18 changes (12 pins, 6 mismatches), in §2.11 (delegated), §3.7–§3.9:
- §2.11 — revise — mismatch — "The other four families are compared before written" -> "Three of the other four...", plus a clause pinning the toll-fraud family's split behaviour — `routes/devices.py:271-285,329-342`
- §3.7 — insert — ambiguity — which `HELD` reservation a device assignment speaks for when a `RESERVED` number carries several: `created_at`/insertion order, prefer own-account+`NEW_LINE`, else earliest row supplies the 422; account compared before purpose — `routes/devices.py:26-70`
- §3.7 — insert — ambiguity — location capture writes the device unconditionally (`version`+1 even when already `ADDRESS_UNVERIFIED`); superseded row takes its own increment — `routes/e911.py:51-78`
- §3.7 — insert — ambiguity — capture's `ERR_ACCOUNT_NOT_ACTIVE` precedes `ERR_JURISDICTION_STATE_MISMATCH`; no `account_id` input so `AccountAdmin` ownership compares against the named device's account, and an unresolvable `device_id` defers to `ERR_DEVICE_NOT_FOUND` — `routes/e911.py:21-49`
- §3.7 — revise — ambiguity — CONFIRMED impl-gen's flag: `VERIFIED`->device `REGISTERED` and `REJECTED`->device `SUSPENDED_911` are unconditional on prior status; `STALE -> REJECTED` retains the earlier `verified_at` — `routes/e911.py:127-136`
- §3.7 — revise — mismatch — "comparing ... as exact strings after uppercasing" -> no case folding at all; non-uppercase/non-digit reported codes are `ERR_INVALID_REQUEST` first — `routes/devices.py:144-164`
- §3.7 — insert — ambiguity — relocation reports rewrite `registration_status` only from exactly `REGISTERED` and drive the registration `STALE` only from exactly `VERIFIED`; otherwise no move, no registration `version` bump — `routes/devices.py:174-183`
- §3.7 — insert — ambiguity — the `AT_RISK` sweep can catch the device being registered: a nomadic number-holding device returns from its own 201 already at `INTL_BLOCKED`, `version` 2 — `routes/devices.py:106`, `services/derive.py:85-110`
- §3.8 — revise — mismatch — the gating stage also requires the owning account `ACTIVE`; CONFIRMED impl-gen's flag that `ERR_ACCOUNT_NOT_ACTIVE` persists NO `CallAttempt` row (no fitting `decision`) and outranks all gates — `routes/devices.py:236`
- §3.8 — insert — ambiguity — device `version` on a call attempt: exactly one increment iff any of `toll_fraud_score`/`fraud_block_count`/`calling_status` moved; none at gates 1–6; no second at gate 8 — `routes/devices.py:271-293`
- §3.8 — revise — ambiguity — the full-block test is at-or-above 3 and applied first out of whatever `calling_status` was held; the `UNRESTRICTED -> INTL_BLOCKED` rule fires only below 3 — `routes/devices.py:275-281`
- §3.8 — insert — ambiguity — `REVIEW_UNBLOCK` with NO current registration reports the same `ERR_UNBLOCK_REVIEW_SCORE_TOO_HIGH` — `routes/devices.py:330`
- §3.8 — insert — ambiguity — a refused `REVIEW_UNBLOCK` writes the score before the gates, so the write survives the error as a bare field write: `updated_at` and `version` unchanged — `routes/devices.py:327-333`
- §3.9 — insert — ambiguity — unit ordering's final tie-break is insertion order, deliberately NOT the `id` fallback of the intra-group anchor key — `services/fees.py:33-46`
- §3.9 — insert — ambiguity — CONFIRMED impl-gen's flag: `void_note` validated then discarded; void body may be omitted entirely — `routes/fees.py:59-60`
- §3.9 — revise — mismatch — provisional voids taken in insertion order, each taking a `version` increment; the account walk is INSERTION order, not ascending `created_at` — `services/fees.py:107-118`
- §3.9 — insert — ambiguity — CONFIRMED impl-gen's flag: a `FINAL` row is born remitted, returned at `version` 1 with `updated_at == created_at`, never 2 — `services/fees.py:127-130`
- §3.9 — insert — mismatch — "touched accounts" defined and compare-before-write, EXCEPT the jurisdiction: counters and `last_remitted_period` written unconditionally with `version` +1 on every run, including a money-idempotent re-run — `services/fees.py:134-141`

**Delegated §2.11 toll-fraud verdict:** compare-before-write holds only on the call-attempt path (`routes/devices.py:271-285` snapshots the triple and uses `common.bump_if_changed`). `services/fraud.py` has no recompute-and-compare helper of its own, and the other call site `apply_calling_restriction` (`routes/devices.py:329-342`) does the opposite twice: an accepted action bumps unconditionally, and a refused `REVIEW_UNBLOCK` writes the score with no bump. §2.11's enumeration sentence was rewritten accordingly.

### Pass 4 — reconciliation (5 surgical edits closing the cross-pass contradictions)
- **C1 §2.7 "single deliberate exception" — FIXED.** A mechanical mutation-before-raise scan over all of `routes/` and `services/` found **exactly two** functions in the codebase that mutate before raising, both in `routes/devices.py`: `:243-247` (the `CallAttempt` audit row) and `:274-282`/`:288` (the fraud gate commits `toll_fraud_score`/`fraud_block_count`/`calling_status` with a real bump before the rule-51 and rule-53 refusals) plus `:329` (refused `REVIEW_UNBLOCK`, bare field write). Everything else mutates strictly after its last guard. §2.7 now names exactly two exceptions, distinguishes which moves `updated_at`/`version`, and closes with "no other refusal writes anything".
- **C2 §2.11 vs §3.9 — FIXED; both prior passes were right about their own path.** `services/derive.py:116-126` (`recompute_jurisdiction_ledger`, used by assess and void) DOES compare before writing; `services/fees.py:134-141` (`run_remittance`) bypasses that helper and writes the counters plus `last_remitted_period` then bumps unconditionally. §2.11 now frames this as a difference between write PATHS rather than a wobble in the rule, pointing at §3.9 (which needed no change).
- **C3 §2.5 "version increases by exactly 1 on every mutation" — FIXED, and a second falsifier caught.** `devices.py:329` writes `toll_fraud_score` with no bump; additionally §3.9's `FINAL` assessment is read at `version` 1 with `updated_at == created_at` despite `status`/`remitted_at` being settled after `new_entity()` (`services/fees.py:127-129`). §2.5 hedged once for both, cross-referencing §3.8 and §3.9; the `updated_at`/`version`-move-as-a-pair rule kept otherwise absolute.
- **C4 §2.7 rules 3 and 42 — BOTH FIXED.** (a) Rule 3's "before any body parsing" was falsified two ways: `body_or_error()` (`common.py:102-107`) raises `ERR_INVALID_REQUEST` for a non-object body BEFORE the guard runs, and `v.peek_str` (`validate.py:181-186`) returns `None` for absent/null/non-string/empty whereupon `guard_account_owner` (`common.py:82-90`) explicitly defers to rule 4 or 7; path-addressed endpoints load the row first so a bad id gives `ERR_PORT_REQUEST_NOT_FOUND`. Changed to "before any body FIELD is validated" plus the deferral rules, phrased to build on pass 1's §2.1/§2.8 clauses rather than duplicate them, and newly pinned the `e911.py:20-27` body-`device_id` case §2.1's path-only sentence did not reach. (b) Verified `porting.py:426-428` is `if slot is None or not (window_start <= now < window_end)`; rule 42 widened to the conjunction, cross-referencing §3.6.
- **C5 scaffold leakage — FIXED.** The §4 `POST /voip/number-reservations` row's "delegates selection to `calculations.reservation_number_selector`" was the file's ONLY leak; greps for `calculations.`, `validations.`, `state_machines.`, `entities.`, `endpoints.` and a general dotted-identifier sweep now return zero. Replaced with plain-language prose matching the real rule at `routes/inventory.py:197-204` (`AVAILABLE` candidates sorted by `line_number`, `created_at`, `_seq`) and consistent with pass 1's §3.3 text.
- **Extra global-vs-specific check.** §2.6's "no other endpoint accepts a version field" verified exhaustively (`grep 'expected_'` yields only `inventory.py:216` and `porting.py:131`). Deliberately left: §2.6's cascade sentence and §2.11's "every entity a cascade actually writes to" — §3.6's stopped-chain passage describes a cascade NOT REACHING a resource, not a written resource skipping its bump, so there is no contradiction, and §2.11 already self-qualifies. All remaining §3 contrast markers are intra-§3 (interval conventions, minute vs millisecond granularity, conditional vs unconditional arrows).

### Orchestrator independent verification of the final artifact
`PRD.md` 521 lines / 111,877 chars -> `PRD_COMPLETED.md` 522 lines / 133,944 chars. `cmp -s` reports the files DIFFER (so the scan genuinely ran — a byte-identical output would have meant no-op). `diff` shows 109 changed lines. `tail` ends at `| ERR_REMITTANCE_PERIOD_NOT_CLOSED | 422 |`, the same real section boundary as the source. Structure intact: 28 headings, 52 method rows in the §4 table, 53 `ERR_` rows in §5. Greps for `calculations.`, `state_machines.`, `validations.` and `harder than expert` all return zero — no scaffold or difficulty-directive leakage in the delivered contract.

## Pipeline complete
Steps 1–7 and 9 executed; Step 8 skipped under its documented skip condition. Final state: 112/112 tests passing in all 8 rounds of the stability sweep, and `workspace/PRD_COMPLETED.md` written.
