# Worklog — task_2166_driver_recruiting_dq_file

## Step 1: Create task directory — 2026-08-28T00:00:00.000Z

Created `tasks/task_2166_driver_recruiting_dq_file/` and `tasks/task_2166_driver_recruiting_dq_file/workspace/`.

## Step 3: Copy INSTRUCTION.md — 2026-08-28T00:25:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 2: Generate scaffold — 2026-08-28T01:00:00.000Z

All three artifacts are generated and verified. No sibling task directory was read at any point — the scaffold comes only from the scenario text plus the skill spec, its `references/claim-extraction-guide.md`, and `scaffold_lint.py`.

## Files written

`/home/ubuntu/github/CodingPRD/tasks/task_2166_driver_recruiting_dq_file/`
- `SCAFFOLD.yaml` (3053 lines) — §1.0–§1.7, no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (3361 lines) — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (8663 lines) — single key `scaffold_corner_design`

## Design shape (deliberately past the Expert band, per the "harder than expert" instruction)

- **Profile**: `compliance_audit` x `workflow_orchestration`; layers `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `derived_field_reconciliation`; topology **flat** (`api_prefix: ""`, absolute top-level paths); shape **parallel**; `segregation_of_duties` role model; self-referential FKs (`DriverApplication.prior_application_id`, `HireRecord.prior_hire_id`) and a cross-aggregate computed field (`DriverApplicant.cdl_downgrade_risk` reads MEDICAL_CERT documents through DqFile -> DriverApplication).
- **Volume**: 14 entities, 13 state machines (two entities carry parallel axes), 4 OCC races, 10 calculations, 37 validations, 74 endpoints, 44 errors, 6 roles.
- **§1.8**: 26 instances across all 9 rules (3 each except `transitive_cascade` at 2). **§1.9**: 86 instances across the guide's 9 sections (78 with full recipes, 8 `excluded_because` stubs).

## Difficulty anchors

- Dual-variant on three different domains: DqFile weights (21.43 vs 10.00), DriverApplication interval coverage (699 vs 1095 days), ScreeningCheck scoring (7.50 vs 9.00).
- Combinatorial modes (a)/(b)/(c): 5-input MVR score with `min` cap + rating multiplier (18.00); pinned sum-then-round completeness (**21.43**, not the per-document 21.42); tuition tier keyed on `base_monthly_cents` (**10560**, not the re-keyed 10080).
- Two 4-hop cascades from different triggers (Clearinghouse PROHIBITED -> application -> DqFile -> Carrier; hire terminate -> tuition clawback -> applicant eligibility -> sibling application).
- Three interval geometries: 12-hour-buffered half-open (orientation), closed touching 180-min slots (examiner), aggregate capacity (session).
- Three conserved quantities: cents (`INV_TUITION_CENTS` = 115205 across clawback/reversal), seats (hire/rescind), weight points (certify/revoke, 6 -> 11 -> 6 of 30).

## Verification run

Every literal in the design files was computed in Python (`Decimal` ROUND_HALF_UP, real date arithmetic) before being written. Checks run to green:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5
and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared:    74
  §1.1 entities declared:     14
  §1.8 instances scanned:     26
  §1.9 instances scanned:     76
  Calls scanned (§1.8+§1.9):  1510
```

Plus custom audits, all clean: zero unbound `${var}` across 1510 calls; unique instance names across both files; all 297 `grounds` refs resolve into §1.1–§1.7; every one of the 44 error codes is both declared in a validation/transition and triggered by a design instance; no forbidden concurrency vocabulary; neither design key present in `SCAFFOLD.yaml`.

Three reachability defects surfaced during §1.9 authoring and were fixed in §1.5/§1.4 rather than papered over: seat exhaustion was decoupled from `Carrier.posture` (otherwise `ERR_NO_OPEN_REQUISITION` was unreachable), and `ERR_CONSENT_NOT_GRANTED` / `ERR_NO_CLAWBACK_TO_REVERSE` / `ERR_COMMITMENT_ALREADY_FULFILLED` were moved ahead of the generic state check (priorities 12/19/18) so each is observable instead of being masked by `ERR_INVALID_STATE`.

## Step 4: Generate PRD — 2026-08-28T01:15:00.000Z

PRD generated at `workspace/PRD.md` (407 lines, ~95 KB), built incrementally in seven appended chunks so nothing was truncated. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

**Structure:** §1 Introduction (3 paragraphs) -> §2 with 11 subsections (RBAC, verbatim response envelope, pagination, resource identity, logical clock, left-to-right path resolution, OCC, precision, the full 37-rung validation ladder, segregation of duties, cascade/reconciliation) -> §3 with 9 domain-derived workflow subsections (carrier posture, applicant/two-axis application, employment history, screening & pre-adverse, Clearinghouse & drug chain, road test/orientation/qualification join, DQ file & annual review & medical certs, hiring/turnover/re-hire, tuition ledger) -> §4 4-column endpoint table -> §5 2-column error table.

**Verified counts in the finished file:** 14/14 entities covered, 13 state machines with all 63 transitions expressed (from/to pairs, preconditions paired with error IDs, side effects incl. the four-hop Clearinghouse and turnover cascades), 10/10 calculations in precise prose with pinned rounding/evaluation orders, 37 validation rungs in explicit priority order (including the three hoisted rules at priorities 12, 18, 19), 74/74 endpoint rows, 44/44 error rows.

**Hard Contracts**

```
Field coverage check:
- entities[].fields: 106 required, 106 present, 0 missing
- endpoints[].request_body: 74 required, 74 present, 0 missing
- endpoints[].query_params: 22 required, 22 present, 0 missing
- endpoints[].path_params: 14 required, 14 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 37 checked, 37 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 4 checked (+ PATCH /carriers from validation p10 = 5 write endpoints), 5 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 63 checked, 63 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed (all constants, variants, pinned orders), 0 missing
- validations[] conditions: 37 checked, 37 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 74 checked, 74 expressed, 0 missing
- entities[].fields[] structured content: 106 checked, 106 reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (mark-no-response round branch, MRO negative from LAB_NEGATIVE/LAB_POSITIVE, adjudicate PASS/PRE_ADVERSE/ADVERSE_FINAL, reschedule from FAILED/NO_SHOW, DqFile OPEN->COMPLETE vs DEFICIENT->COMPLETE, disqualify from ORIENTATION_COMPLETE/QUALIFIED), 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 984
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional spot-checks: §2.2 matches the canonical source byte-for-byte; all 44 error IDs appear in §2/§3 narrative, not only in the §5 table; all state enum values and all `type: enum` field values appear verbatim; the file ends at §5 with no audit footer.

Two scaffold internal inconsistencies resolved toward the authoritative source rather than reproducing both readings: (1) `POST /carriers`'s `side_effects` note implies `open_requisitions == 0` yields a non-OPEN posture, which contradicts `calculations.carrier_posture`'s pinned comment that seat exhaustion is *not* part of posture (it is validation priority 82) — wrote the formula's version and noted that at registration the ratio is 0.0 so posture is `OPEN` unless the rating is `UNSATISFACTORY`; (2) the submit transition's precondition says `rehire_eligibility != PERMANENTLY_INELIGIBLE` while validation priority 75 requires `== ELIGIBLE` for the same endpoint — wrote the validation form, since that rung owns the error code.

## Step 6: Generate implementation — 2026-08-28T01:45:00.000Z

Implementation complete and verified.

## What was built

`workspace/implementation/` — Python + Flask, split across 8 modules (built incrementally, no single giant write):

| File | Lines | Contents |
|---|---|---|
| `core.py` | 515 | in-memory store, logical clock, response envelope, 44-error catalogue, RBAC, body/query validators, path/FK resolution |
| `calc.py` | 400 | all 10 calculations + domain constants and the 12-row DQ document catalogue |
| `domain.py` | 318 | derived-field reconciliation, cascades, DQ-file creation, clock sweep |
| `routes_a.py` | 384 | clock, carriers, applicants, applications |
| `routes_b.py` | 527 | employment verifications, screening checks, Clearinghouse, drug tests |
| `routes_c.py` | 359 | road tests, orientation sessions/enrollments |
| `routes_d.py` | 438 | DQ files/documents, tuition agreements, hire records |
| `app.py` | 76 | app assembly, error handlers, request lock, `0.0.0.0:$PORT` |
| `start.sh` | 10 | guarded `pip install` + `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=3.0.0` |

Every module imports cleanly (`python3 -c "import app"` -> 74 routes registered, exactly matching the PRD §4 table: 0 missing, 0 extra).

## Key fidelity decisions

- **No seeding anywhere.** `DB` is a dict of empty dicts at module load; `grep` confirms no `seed_*`/preload. Three concurrent fresh boots via `start.sh` each answered `total_count: 0` and were ready in <=0.52s.
- **Logical clock** starts at exactly `2026-08-01T00:00:00Z`; wall clock is never read (`api_request_timestamp`, `created_at`/`updated_at` all use it). Setting it runs the full §2.5 reconciliation sweep in the PRD's stated order.
- **Validation ladder** implemented per §2.9 priority, including the three hoisted rungs (`ERR_CONSENT_NOT_GRANTED`, `ERR_COMMITMENT_ALREADY_FULFILLED`, `ERR_NO_CLAWBACK_TO_REVERSE`) outranking the generic state checks.
- **`ERR_ALREADY_TERMINAL` is checked before `ERR_INVALID_STATE`.** The scaffold's priority numbers put 20 (invalid state) above 22 (terminal), but that would make `ERR_ALREADY_TERMINAL` unreachable, contradicting its own catalogue examples ("cancelling a CANCELLED enrollment, adjudicating an ADVERSE_FINAL check, terminating a TERMINATED hire"). Exception preserved: annual-review/revoke on an `ARCHIVED` file reports `ERR_INVALID_STATE`, as §3.7 states explicitly.
- **Existence before ownership.** The ladder puts owner check at priority 4 (above existence at 5), but ownership is undefined on a non-existent row, so path resolution runs first and a missing consent/dispute target returns its 404 code.
- **Version bumps** are once-per-row-per-request (request-scoped dirty set) and only on rows whose values actually changed; read endpoints (`GET /dq-files/{id}`, `GET /driver-applicants/{id}`) recompute derived fields **without** bumping, per §3.7's explicit "without incrementing version".
- **Rounding** uses `Decimal`/`ROUND_HALF_UP` everywhere with the pinned orders (road-test sections rounded to 2dp *then* summed *then* rounded to 1dp; completeness rounded once at the ratio; tuition tier keyed on `base_monthly_cents` only).
- **Requests are serialized** with a global `RLock` so OCC check-then-write and seat arithmetic stay atomic; a 8-way concurrent PATCH race yielded exactly one 200 and seven 412s.

## Ambiguity resolved by judgment

The "at most one non-terminal `ScreeningCheck` per (application, check_type)" rule has no declared error code. Reported as `ERR_INVALID_STATE` (409) at the generic state rung, since it is a state-dependent duplicate rather than a shape violation. If the test suite expects `ERR_VALIDATION` (422), that one line in `routes_b.check_create` is the fix.

## Verification

Four scripted suites run against a live `start.sh` server, all with **0 failures**: full happy path to hire (composite 87.5, tuition 9600/10560/5 matching the scaffold's worked example, completeness 78.57 -> 100.00, `annual_review_final` 63.33), 60+ negative/error-ladder cases covering all 14 404 codes and every OCC path, annual review certify/revoke round-trip (weight 33 and completeness restored identically), hire->rescind seat invariant, clock-driven expiry flipping COMPLETE->DEFICIENT->carrier RESTRICTED at ratio 1.0, cooldown expiry, the four-hop Clearinghouse-prohibited cascade, buffered orientation overlap, capacity, examiner touching-slot conflict, and both coverage variants (strict 0 days vs projected 1095 after three documented good-faith rounds).

## Step 5: Generate unit tests — 2026-08-28T02:15:00.000Z

Test infrastructure and suite generated.

## What was produced

**`test_helpers/`** (2,223 lines, 9 files) — `types.py` (456), `api_client.py` (370, one method per each of the 58 endpoints), `api_errors.py` (101, all 44 codes + status map registered), `assertions.py` (291, per-entity + `assert_tuition_cents_identity` / `assert_coverage_identity` / `assert_carrier_seat_identity` / `assert_completeness_payload`), `constants.py` (90), `factories.py` (181), `fixtures.py` (651, five tiers up to `setup_qualified_application` / `setup_hired_applicant` / `setup_active_tuition_agreement` / `setup_file_due_for_annual_review`), `test_users.py` (47, incl. the mandatory `make_applicant_headers(applicant_id)` builder for the entity-backed `Applicant` role), `__init__.py` (36).

**`test_suite/`** (4,992 lines, 12 files) — `conftest.py` + `test_01`...`test_11`. **128 tests collected.**

## Instance-to-test tally

| Queue | Instances | Tests | Result |
|---|---|---|---|
| A — Difficulty (9 rules) | 26 | 52 | every instance has exactly 2 |
| B — Corner (non-stub) | 76 | 76 | every instance has exactly 1 |
| B — Corner stubs | 10 | 0 | not translated; all 10 `difficulty_instance` cross-refs verified to resolve |

Per file: 12 / 17 / 11 / 10 / 17 / 9 (queue B) and 12 / 10 / 12 / 12 / 6 (queue A).

## Audits run

- **Design tags**: 128/128 tagged, 0 untagged, 0 dual-tagged, 0 tags pointing at non-existent instances, tag is the last docstring line everywhere.
- **PRD citations**: 298 quoted passages extracted and matched verbatim (whitespace-normalized) against `PRD.md` — 0 failures.
- **No `pytest.mark.skip` / `skipif` / `xfail`; no "scaffold"/§1.x/table references** in emitted code.
- `python -m compileall` clean over both directories; `pytest --collect-only` collects 128.
- Import audit: every `from test_helpers import ...` name resolves against the barrel.

## Two adjudications worth flagging

1. **Corrected a wrong literal in the corner design.** `Corner/calculations/rehire_cooldown_expires_exactly_on_the_boundary_day` asserts COOLDOWN at 2027-02-05 and ELIGIBLE at 2027-02-06, but its own setup terminates on 2026-08-20 with `rehire_cooldown_days` 180 -> the boundary is **2027-02-16**. Emitting the yaml's dates would have made the test fail against a correct implementation, so the test uses 2027-02-15 (COOLDOWN) / 2027-02-16 (ELIGIBLE), preserving the instance's claim.

2. **Relaxed one error assertion under the sanctioned `error-precedence` silence pattern.** `Corner/state_machines/adjudicate_on_adverse_final_returns_409_already_terminal` expects `ERR_ALREADY_TERMINAL`, but the PRD never declares `ADVERSE_FINAL` terminal (it does so explicitly for `PASSED`, `CONSENT_DENIED`, `GOOD_FAITH_DOCUMENTED`) and §2.9 puts the generic state rung above the terminal rung — two faithful readers would split between `ERR_INVALID_STATE` and `ERR_ALREADY_TERMINAL`. That single assertion uses `validate_error_is_one_of([...])` plus an explicit 409 check; the instance's cascade assertions (SCREEN_FAILED / DISQUALIFIED / `ADVERSE_SCREENING` / file ARCHIVED) are asserted exactly.

Three instances asserting `ERR_INVALID_STATE` for an unmet *temporal* precondition (early `ADVERSE_FINAL`, early `mark-no-response`, late session `open`) were kept: the PRD's ladder in §2.9 leaves no other rung for them, and the PRD itself applies `ERR_INVALID_STATE` to three analogous "transition not available" cases in prose. A handful of default-value assertions the PRD never states (a fresh `ScreeningCheck`'s `adjudication_score`/`issued_on`, a client-supplied `created_at`) were dropped from otherwise-covered tests rather than guessed.

## Step 7: Test and iterate to green — 2026-08-28T02:30:00.000Z

All three changes are in place and the suite is green across all 8 parallel rounds.

## Summary

**Iterations run:** 2 (sweep 1 -> 3 failures; fixes; sweep 2 -> clean)

- Sweep 1: 125/128 in all 8 rounds — the same 3 failures every round (fully deterministic, no flakiness signal).
- Sweep 2: **128/128 in all 8 rounds.**

**Tests deleted:** none. All three failures survived STEP 1 (PRD verbatim-covers the rule *and* uniquely determines the outcome), so none qualified for deletion.

**Fixes applied to `test_suite/`** (no `test_helpers/` changes were needed — the shared fixtures were all PRD-faithful):

1. `test_06_segregation_and_concurrency.py` -> `test_a_road_test_pass_returns_every_cascade_in_the_same_response` — corrected the completeness arithmetic from `21.43`/`deficiency_count == 8` to `32.14`/`deficiency_count == 7`. The test's own setup calls `complete_negative_drug_test`, and PRD §3.5 states verbatim that `MRO_VERIFIED_NEGATIVE` files the `DRUG_TEST_RESULT` document `PRESENT`; the expected figures had omitted that document's weight of 3. Correct value is `APPLICATION_FORM(3) + DRUG_TEST_RESULT(3) + ROAD_TEST_CERT(3) = 9 / 28 -> 32.14`. The assertion stays exact — it was made more faithful, not weakened.

2. `test_06_segregation_and_concurrency.py` -> `test_a_stale_predecessor_version_blocks_a_second_reapplication` — removed a setup step that disqualified the freshly-minted successor while it sat at `DRAFT`/`NOT_STARTED`. PRD §3.2 declares `SUBMITTED`, `SCREENING`, `INFO_REQUESTED` as the only disqualification origins, so the PRD-faithful implementation correctly returned `ERR_INVALID_STATE` — a test-fixture bug, not an implementation bug. The step was not load-bearing: PRD §2.9 places the optimistic-concurrency rung strictly above the duplicate-active-application rung, so the stale retry reports `ERR_STALE_VERSION` regardless. The `ERR_STALE_VERSION`/412 assertion and every follow-up assertion are untouched.

**Fix applied to `implementation/`:**

3. `workspace/implementation/domain.py` -> `recompute_carrier` (added a `force_touch` parameter) and `cascade_disqualify` (now calls it with `force_touch=True`). PRD §3.5 states verbatim that the fourth hop of the disqualification fan-out "recomputes the carrier's `filled_requisitions`, `deficiency_ratio` and `posture` **and increments the carrier's `version` by one**" — unconditionally, reinforced by §2.4's rule that a cascade counts as a mutation of the row it touches. The old code bumped the version only via `apply_changes`, which no-ops when the recomputed triple lands on unchanged values (the case when no hire exists yet), so the increment was silently skipped.

**Blast-radius check on fix 3:** every other carrier-mutation site already pairs `recompute_carrier` with an explicit `touch(carrier)`, and `touch` is idempotent per request via `g.touched` — so the terminate path (which reaches the carrier through both hop 4 and its own explicit touch) still increments exactly once. A grep of the suite confirmed `test_08:312` was the only assertion on a carrier-version delta across a disqualify cascade.

**Storage constraint verified:** no SQLite, no file writes, no `/tmp` cache, no seeded entities — storage remains in-memory Python dicts, empty on every boot.

## Step 8: Finalize PRD — 2026-08-28T02:45:00.000Z

`PRD_FINALIZED.md` written.

## Size

| | PRD.md | PRD_FINALIZED.md | delta |
|---|---|---|---|
| lines | 407 | 407 | 0 (+0.00%) |
| words | 13,251 | 13,400 | +149 (+1.12%) |
| bytes | 95,378 | 96,200 | +822 (+0.86%) |

Two paragraphs revised; no sections added, no lines added (the PRD is one-paragraph-per-line).

## Changes

- **§2.4 (Resource Identity, Timestamps and the Version Counter)** — revise — added the once-per-row-per-request cap on `version`: a request that writes the same row more than once (several cascade hops landing on one carrier, or a hop landing on a row already written directly) increments `version` once and later writes only refresh `updated_at`; a row minted by the request stays at the `version` of 1 it is born with for the rest of that request — `implementation/core.py:235-246` (`touch`, guarded by `g.touched`), `implementation/core.py:225-231` (`new_row` pre-seeds `g.touched`), `implementation/app.py:33` (`g.touched = set()` per request).
- **§3.2 (Disqualification fan-out)** — revise — the fan-out's carrier hop now states that the carrier's `version` increments by one *even when the recomputed `filled_requisitions`/`deficiency_ratio`/`posture` land on unchanged values*, cross-referenced to the §2.4 cap — `implementation/domain.py:255` (`recompute_carrier(..., force_touch=True)`), `implementation/domain.py:57-63`.

Items 1 and 2 of `<step_7_diff>` produced **no** PRD edits: both were fixture bugs against behavior the PRD already uniquely determines (§3.5's `MRO_VERIFIED_NEGATIVE -> DRUG_TEST_RESULT PRESENT` plus §3.7's weight table give 9/28 -> 32.14 and `deficiency_count` 7; §3.2's declared disqualification origins exclude `DRAFT`, and §2.9 already places the concurrency rung above the duplicate-active rung — `routes_a.py:331-345` and `routes_a.py:348-360` match verbatim).

## Per-edit pre-edit search log

**Edit 1 — §2.4**
- (a) Subject: how `version` behaves when one request mutates the same row through more than one path.
- (b) Enumerated: `grep '\["version"\]' implementation/*.py` -> the only write sites are `core.py:225` (`= 1` at mint) and `core.py:241`/`245` (both inside `touch`); the other five hits are read-only OCC comparisons (`routes_a.py:133,355`, `routes_c.py:288`, `routes_d.py:148,291`). Every mutation funnels through `touch` directly or via `domain.apply_changes` (`domain.py:42-53`). Read `app.py:29-40` (per-request `g.touched`, serialized by `_REQUEST_LOCK`), `core.py:225-246`. Cross-checked the multi-touch paths the wording must not mis-describe: terminate (`routes_d.py:396-407` — hop 4 `cascade_disqualify` plus the explicit `recompute_carrier`+`touch`), hire (`routes_d.py:344-345`), rescind (`routes_d.py:436`), reconfigure (`routes_a.py:140`), the direct-disqualify route (`routes_a.py:343-345`, which touches the application then `apply_changes` touches it again), submit (`routes_a.py:290-295`, which mints a file then writes it twice via `set_document`/`recompute_file`/`recompute_review`), and multi-enrollment cancellation into one session (`domain.py:228-233`, `cancel_enrollment` -> `recompute_session_count` + `touch`).
- (c) Adjustment: dropped an initial draft phrased as "a cascade increments once" (too narrow — it would have excluded the direct-write-then-cascade case in `routes_a.py:343-345` and the mint-then-write case in `routes_a.py:290-295`). Final wording is stated per *request* rather than per *cascade*, names both shapes explicitly, keeps "`updated_at` still refreshes" (true — `core.py:236` runs before the guard), and adds the minted-row clause so `new_row`'s pre-seeding of `g.touched` is not read as a divergence.

**Edit 2 — §3.2**
- (a) Subject: the carrier hop of the disqualification fan-out, and whether its `version` bump is conditional on the recomputed triple actually changing.
- (b) Enumerated every caller of `cascade_disqualify` / `cascade_screen_fail` (`grep -n "cascade_disqualify\|cascade_screen_fail" implementation/*.py`): the direct decision (`routes_a.py:345`), the termination hop-4 loop (`routes_d.py:405`), and every screen-fail cascade routed through `cascade_screen_fail` (`domain.py:259-263`) — adverse-final screening, consent denial, `RESULT_PROHIBITED`, MRO verified positive, and the `PRIOR_DA_VIOLATION` disputed-verification path. Also read the early-return at `domain.py:232-234` (no fan-out at all when `qualification_status` is already terminal) and every other `recompute_carrier` callsite (`routes_a.py:140`, `routes_d.py:165,344,407,436`, `domain.py:68` via `recompute_all_carriers` in `clock_sweep`) to confirm none of them relies on the bump being conditional.
- (c) Adjustment: the sentence was scoped to the fan-out actually firing (left attached to the existing "the consequences fan out" clause, so the `domain.py:232` early-return case is untouched), and the "subject ... to the once-per-row-per-request cap of §2.4" qualifier was appended so the claim stays true on the terminate path, where hop 4 and the terminate handler's own `recompute_carrier`+`touch` together still yield exactly +1. Without that qualifier the sentence would have been a false universal against `routes_d.py:405-407`.

## Step 9: Complete PRD — 2026-08-28T03:00:00.000Z

All 29 edits verified in place. Structure intact.

**Files**
- Source: `workspace/PRD_FINALIZED.md` — 407 lines, 96,200 chars
- Output: `workspace/PRD_COMPLETED.md` — 407 lines, 102,004 chars (**+5,804 chars**, +0 lines)
- Integrity verified: 5 top-level sections, 74 endpoint rows, 44 error rows.

**Counts:** 29 changes — **26 ambiguity-pins**, **3 mismatch-revisions**. No new sections, no new paragraphs; all edits are in-paragraph inserts/revisions.

**Changes**

- §2.3 Pagination — insert — ambiguity — list ties on identical `created_at` broken by mint order, never by identifier — `core.py:253-256`
- §2.5 Logical Clock — insert — ambiguity — sweep bumps `version`/`updated_at` only on rows it actually changes — `domain.py:317-325`, `domain.py:42-51`
- §2.9 Validation Order — revise — **mismatch** — terminal check (`ERR_ALREADY_TERMINAL`) evaluated *before* origin-state check (`ERR_INVALID_STATE`); PRD had the reverse — `routes_a.py:271-276`, `routes_b.py:84-87`
- §2.9 Validation Order — insert — ambiguity — ownership rung runs after the targeted row resolves, so a bad path id still 404s first — `routes_b.py:288-290`, `routes_b.py:356-358`
- §3.1 Carrier — insert — ambiguity — single-read and list both recompute the posture triple in place, filter applies to fresh value, no `version` bump — `routes_a.py:104-123`
- §3.1 Carrier — insert — ambiguity — PATCH always increments `version` even with no knobs supplied or identical values — `routes_a.py:139`
- §3.2 Applicant — insert — ambiguity — single read refreshes silently (no `version`/`updated_at`); list does *not* recompute — `routes_a.py:187`, `routes_a.py:190-198`
- §3.2 Application — insert — ambiguity — fresh application defaults (`revision_round` 0, three nulls, coverage 0, gap 1095) — `routes_a.py:233-246`
- §3.2 Submit — insert — ambiguity — new DQ file opens with `last_annual_review_at`/`next_review_due_on`/`certified_by_user_id` null — `domain.py:288-300`
- §3.2 Reapply — insert — ambiguity — re-hire eligibility gate is *not* re-applied on reapply — `routes_a.py:348-360`
- §3.3 Verification — insert — ambiguity — segment defaults (`request_round` 0, `last_requested_at` null, both booleans false) — `routes_b.py:53-64`
- §3.3 Send-request / mark-no-response — insert — ambiguity — `SCREEN_FAILED` parent, exhausted round budget, and un-elapsed 14-day wait all report `ERR_INVALID_STATE` — `routes_b.py:88-92`, `routes_b.py:141-143`
- §3.4 Screening check order — insert — ambiguity — duplicate non-terminal check reports `ERR_INVALID_STATE` ahead of the posture rung; order defaults (nulls, counts 0, score 0.0) — `routes_b.py:167-185`
- §3.4 Adjudicate PASS — insert — ambiguity — filed document's `source_ref` = check `id` — `routes_b.py:271`
- §3.4 Pre-adverse window — insert — ambiguity — dispute after close and `ADVERSE_FINAL` before close both report `ERR_INVALID_STATE` — `routes_b.py:250-252`, `routes_b.py:297-299`
- §3.5 Clearinghouse create — insert — ambiguity — back-link only onto rows with null `follow_up_full_query_id`, bumps their `version`, links *every* such row — `routes_b.py:327-334`
- §3.5 Record-result gates — revise — **mismatch** — `ERR_CONSENT_NOT_GRANTED` also outranks the terminal rung, and the result/`query_type` compatibility check (`ERR_INVALID_STATE`) sits *between* the two stated gates, ahead of `ERR_CONSENT_EXPIRED` — `routes_b.py:385-396`
- §3.5 Record-result branches — insert — ambiguity — `result` field overwritten with the recorded token; `CLEARINGHOUSE_QUERY` doc `source_ref` = query `id`; wrong `query_type` reports `ERR_INVALID_STATE` on both branches — `routes_b.py:388-406`
- §3.5 MRO verification — insert — ambiguity — `DRUG_TEST_RESULT` doc `source_ref` = order `id` — `routes_b.py:516-518`
- §3.6 Road test pass — insert — ambiguity — `ROAD_TEST_CERT` doc `source_ref` = road test `id` — `routes_c.py:140-142`
- §3.6 Session open — insert — ambiguity — start instant already reached reports `ERR_INVALID_STATE` — `routes_c.py:223-224`
- §3.6 Session complete — insert — ambiguity — early completion, unresolvable member (`ERR_ENROLLMENT_NOT_FOUND`), and wrong-session/non-`RESERVED` member (`ERR_INVALID_STATE`) — `routes_c.py:235-249`
- §3.7 DQ file read — revise — **mismatch** — read recomputes `next_review_due_on` *and* `review_state` (PRD said only `review_state`); list read does the same before filtering — `domain.py:164-171`, `routes_d.py:29-41`
- §3.7 Completeness read — insert — ambiguity — `missing_doc_types` returned in seeded artifact order, never re-sorted — `calc.py:198-200`
- §3.7 Manual document write — insert — ambiguity — optional fields keyed on key presence (explicit null clears, absent key preserves); archived parent still writable; response is the document row — `routes_d.py:150-166`
- §3.8 Rescind — insert — ambiguity — standing clawback refusal reports `ERR_INVALID_STATE` — `routes_d.py:421-425`
- §3.9 Activate — insert — ambiguity — no `ACTIVE` hire reports `ERR_INVALID_STATE` — `routes_d.py:220-225`
- §3.9 Accrue — insert — ambiguity — `service_month` validated only as non-empty string, not persisted — `routes_d.py:238`
- §5 Catalogue preamble — insert — ambiguity — unrouted path / unsupported method answer `ERR_VALIDATION` at 404 / 405 — `app.py:54-61`

**Not changed** (impl already uniquely pinned): all 74 endpoint rows and roles, the eight hire gates and their order, the five OCC endpoints, all seven calculation formulas and their rounding orders, the two completeness and two coverage variants, the cascade fan-outs, the medical-cert risk bands, the re-hire branch list, and every list filter set.
