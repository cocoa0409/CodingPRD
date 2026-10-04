# Worklog — task_3066_retail_cash_reload_network_bank_as_service

Scenario: Retail Cash Reload Network & Bank-as-a-Service Program Management (Green Dot)

## Step 1: Create task directory — 2026-09-30T00:00:00.000Z

Task directory was pre-allocated by the caller at `./tasks/task_3066_retail_cash_reload_network_bank_as_service/` with `workspace/` already present and empty. No index computation performed; no other `task_*` directory created.

## Step 2: Generate scaffold — 2026-09-29T19:55:47.000Z

All three artifacts are written and the linter passes clean.

## Deliverables

All under `/home/ubuntu/github/CodingPRD/tasks/task_3066_retail_cash_reload_network_bank_as_service/`:

| File | Contents |
|---|---|
| `SCAFFOLD.yaml` | §1.0–§1.7 (no `scaffold_difficulty_design` / `scaffold_corner_design` keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | single top-level key `scaffold_difficulty_design` — §1.8 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | single top-level key `scaffold_corner_design` — §1.9 |

## Counts

- **Entities** 12 · **State machines** 11 (59 transitions) · **Concurrency rules** 3 · **Calculations** 11 · **Validations** 31 (strict-priority 1–31, no duplicates) · **Endpoints** 66 · **Errors** 34 · **Roles** 7
- **§1.8**: 9 rule_id blocks, **18 instances** (2 per rule, meeting every §0.5 minimum)
- **§1.9**: 9 sections, **42 instances** (39 active + 3 `excluded_because` stubs citing §1.8 instances by name)
- Largest cascade chains: depth **5** (alert confirm → freeze → reverse → recover → counter recompute) and depth **3** (brand suspend → account review → pending-load decline)
- Every error code is referenced; every role declares `identity:`; 20 FKs all have reverse-reachability GETs

## Difficulty design (per the caller's "much harder than expert")

- **Rule 1**: two dual-variant calcs on *different domains* — `velocity_trip` (trailing_24h vs epoch_day reset on CardAccount) and `effective_fee_schedule` (round-per-load vs sum-then-round on RetailerAgreement).
- **Rule 2**: two *different modes* — (a) a flat-band/marginal tier walk for `convenience_fee_cents`, (b) pinned rounding order for `settlement_fee_rounding` with a fixture that produces a real ±0.01 divergence.
- **Rule 3**: two cyclic machines on different entities — AmlAlert (confirm→reopen→under_review) and DisputeCase (bounded retailer↔programme negotiation loop). The DisputeCase self-loop transition was added to the scaffold to make the cycle real.
- **Rule 4**: depth-5 and depth-3 cascades from different triggers, each hop spelled out in `side_effects` with explicit `[hop N]` markers.
- **Rule 5**: two *different category pairs* — state vs business_constraint (frozen account beats per-txn limit) and state vs business_fiscal (closed location beats float cap).
- **Rule 6**: numeric threshold crossing (velocity =5) on `/fund` + empty-collection boundary (settlement period with zero qualifying loads) on `/settle`.
- **Rule 7**: two different entity pairs — BrandPartner→Program and SettlementBatch→RetailerAgreement.
- **Rule 8**: half-open interval semantics (trailing 24h window, boundary instant is the discriminator) + buffer-inflated closed-interval semantics (float windows).
- **Rule 9**: two conserved quantities — monetary ledger identity on CardAccount, counted-population posture breach count on Program.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_3066_retail_cash_reload_network_bank_as_service/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_3066_retail_cash_reload_network_bank_as_service/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_3066_retail_cash_reload_network_bank_as_service/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    66
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     39
  Calls scanned (§1.8+§1.9):  632

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

All 632 recipe calls resolve to declared §1.5 endpoints with correct roles and payload shapes; placeholder closure is complete (0 unbound `${var}` across both design files); every OCC `expected_*_version` is a `${var}`; no forbidden concurrency vocabulary appears in any file; and all formula-derived assertions were computed in Python before being written as literals.

I did not read or list any sibling task directory; the scaffold was generated solely from the scenario text and the skill specification.

Verified by orchestrator: SCAFFOLD.yaml (2069 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1623 lines), SCAFFOLD_CORNER_DESIGN.yaml (2270 lines) all present.

## Step 3: Copy shared files — 2026-09-29T19:56:30.000Z

Copied `./INSTRUCTION.md` → `./tasks/task_3066_retail_cash_reload_network_bank_as_service/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-29T20:05:00.000Z

Done. The PRD is written and all three hard contracts verify clean.

## Summary

**File written:** `/home/ubuntu/github/CodingPRD/tasks/task_3066_retail_cash_reload_network_bank_as_service/workspace/PRD.md` — **379 lines**, ~79 KB.

**Sections:**
- `## 1. Introduction` (3 paragraphs)
- `## 2. Global Specifications & System-Wide Principles` — 11 domain-derived subsections: 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 The Reload Network Hierarchy and Posture Gating · 2.5 Common Resource Properties · 2.6 Monetary Values, Precision and Rounding · 2.7 Optimistic Concurrency Control · 2.8 The Two-Dimension Card Account Model · 2.9 The Logical Clock and Epoch Discipline · 2.10 The Segregation-of-Duties Principle · 2.11 Cascading Reconciliation and Hop Ordering
- `## 3. Business Logic & Workflows` — 8 lifecycle-ordered subsections (sponsorship/program stand-up; brand partners; agreements/stores; card accounts + load creation/funding/reversal/re-instatement; posture scoring and oversight; AML velocity/structuring/alert adjudication; disputes; loss allocation/settlement/clawback/float)
- `## 4. Endpoint Definitions` — 4-column table (Method, Path, Description, Authorized Role(s)), 66 rows, preceded by the status-code paragraph
- `## 5. Error Code Catalogue` — 2-column table (Error ID, HTTP Status Code), 34 rows

No audit footer, no contract-report blocks, no `§1.x` scaffold cross-references inside the document.

## Coverage audit

| Scaffold element | Count | Covered verbatim |
| --- | --- | --- |
| Entities (`entities[]`) | 12 (BankSponsor, Program, BrandPartner, RetailerAgreement, ReloadLocation, CardAccount, LoadTransaction, AmlAlert, DisputeCase, LossAllocation, SettlementBatch, FloatWindow) | all named, every field in backticks, every structured field (defaults, sources, enum members) given its rule |
| Entity fields | 129 | 129 verbatim in backticks |
| Endpoint identifiers (`input`/`query_params`) | 72 | 72 verbatim |
| Endpoints (`endpoints[]`) | 66 | all 66 in §4 table with roles; all request params surfaced in §3 prose |
| State machines | 11 | all 11, all 59 transitions (`from`/`to` pair + preconditions + `side_effects`) expressed |
| State/enum strings | 21 state values + 30 enum members | 0 missing |
| Calculations | 11 | all formulas expressed as precise prose; constants (199/249/399, 5, 1000000, 9000–9999, 3, 27000, 0.10/0.20, 60.00/3.99, 0.60, 0.15/0.00, 2500/1500/500/250, 24/48/72, 90, 3000000, 120, 100) embedded in business context |
| Validations | 31 | all 31 paired with their `error_id`; admission-control priority order stated explicitly as "first…fifth", and the §2.4 existence→state→amount precedence stated |
| Concurrency rules (`concurrency_rules[]`) | 3 | all 3: `expected_card_account_version` / `expected_load_transaction_version` / `expected_program_version` named as mandatory, with `ERR_STALE_VERSION` (412) framed purely as stale-observation rejection |
| Errors (`errors[]`) | 34 | all 34 in the §5 table; all 34 also mentioned with trigger narrative somewhere in §2 or §3 |
| Roles (`roles[]`) | 7 | all 7 spelled exactly; every `identity:` translated (BankSponsor/ProgramManager/RetailerClerk as entity-backed with their FK comparison rules; PlatformAdmin/ComplianceAnalyst/ComplianceOfficer/SettlementOperator as opaque) |

## Hard Contract Reports

```
Field coverage check:
- entities[].fields: 129 required, 129 present, 0 missing
- endpoints[].request_body/input: 72 required, 72 present, 0 missing
- endpoints[].query_params: 0 required, 0 present, 0 missing (filters surfaced in §3 prose as free-form "optional filters"; no query_params key in scaffold)
- endpoints[].path_params: 0 required, 0 present, 0 missing (scaffold declares none)
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 31 checked, 31 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 59 checked, 59 fully expressed, 0 missing
- calculations[]: 11 checked, 11 fully expressed, 0 missing
- validations[] conditions: 31 checked, 31 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 66 checked, 66 expressed, 0 missing
- entities[].fields[] structured content: 129 checked, 129 reconstructible from prose, 0 missing
- sibling-branch symmetry: 34 groups checked (Program posture pairs, BrandPartner transitions, RetailerAgreement transitions, ReloadLocation transitions, CardAccount hold transitions, LoadTransaction transitions, AmlAlert transitions, DisputeCase transitions, SettlementBatch/FloatWindow/LossAllocation transitions, plus the REG_E/VOLUNTARY/CORPORATE and BAAS/OWN_BANK variant families), 34 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 252
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Notes: §2.2 body was diffed byte-for-byte against `section-2.2-response-structure.md` and matches exactly (including `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, `UNIQUE_ERROR_IDENTIFIER_STRING`, and `"data": { }`); I did not open the withheld `SCAFFOLD_DIFFICULTY_DESIGN.yaml` / `SCAFFOLD_CORNER_DESIGN.yaml`, and did not read any sibling task. No fuzzy/approximating wording remains (one incidental "conservatively" was rewritten). Precision is stated as "2 decimal places, round half up" with the round-then-sum vs sum-then-round distinction preserved for the settlement delta.

Verified by orchestrator: workspace/PRD.md present, 379 lines, sections 1–5 all present.

## Step 5: Generate unit tests — 2026-09-29T20:35:00.000Z

All work is complete. Here is the summary.

## Files written

**`test_helpers/`** (9 modules, Stage 1)
- `__init__.py` — barrel export (framework generics + PRD-specific)
- `types.py` — 12 entity TypedDicts (all `common_fields: true`, so all carry `id/created_at/updated_at/version`), 17 status enums, `UserRole`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (incl. `set_clock`)
- `api_errors.py` — 34 `ApiErrorId` members + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity asserters + domain invariants (balance/ledger identity, fee-share identity, loss-split identity, rounding-delta identity)
- `constants.py` — tier/velocity/structuring/posture/provisional/loss/response-window/float constants
- `factories.py` — one payload factory per entity (input fields only)
- `test_users.py` — shared constants for all 7 roles + per-instance builders for the 3 `entity_backed` roles
- `fixtures.py` — composite helpers in 5 tiers: primitives, `setup_network` / `setup_brand_program` / `setup_network_with_funded_load`, lifecycle shortcuts (`setup_settled_load`, `setup_posted_loss_allocation`), threshold targeting (`setup_velocity_boundary`, `setup_structuring_account`, `suspend_brands`, `setup_program_frozen`)

**`test_suite/`** (Stage 2) — `conftest.py` + 9 files, **106 tests**

## Coverage

- **Queue A (Difficulty): all 18 instances emitted, every one with ≥2 tests** (range 2–5).
- **Queue B (Corner): all 43 non-stub instances emitted with ≥1 test.** The 3 `excluded_because:` stubs (`brand_onboarding_rejected_on_stale_program_version`, `cascading_side_effects_documented_end_to_end`, `dual_variant_calculation_divergence`) were correctly **not** translated; each cited difficulty instance they point at is covered.
- **No instances skipped on the PRD-first filter.** Every design instance's asserted rule has a verbatim, rule-bearing PRD sentence that uniquely derives the visible outcome.
- Every test carries exactly one `Design:` tag copied verbatim from the source yaml; verified programmatically (0 untagged, 0 dual-tagged, 0 unresolvable tags).
- All 152 PRD citations verified to survive a literal grep of `PRD.md`; 0 `pytest.mark.skip/xfail/skipif`; no "scaffold"/section-reference strings leaked into code.

## PRD-vs-scaffold semantic discrepancies noticed

1. **Directional OCC only.** PRD §2.7 says the load-*reverse* path "carries an expected load version", but the scaffold's `FUNDED_to_REVERSED` transition declares no `expected_load_transaction_version` precondition (unlike `REINITIATE`). Since no design-index instance asserts the reverse-path version gate, no test emits one — noting it as a PRD/state-machine asymmetry.
2. **Odd choke-point in the ERR_ACCOUNT_FROZEN priority pair.** The `account_frozen_beats_per_transaction_limit` difficulty instance asserts the *funding* path (ERR_ACCOUNT_FROZEN, prio 9 vs ERR_PER_TRANSACTION_LIMIT_EXCEEDED, prio 16), but the frozen account carries a live CONFIRMED alert, so `POST /load-transactions/{id}/fund` would first trip priority-15 `ERR_AML_ALERT_PENDING` (409). I emitted the pair against **load creation** instead, where PRD §3.4 explicitly names the "hold dimension must be `CLEAR` (`ERR_ACCOUNT_FROZEN`) … before the load is written" ordering, which is unambiguous.
3. **FROZEN transitions require an overdue clock.** PRD §3.5's freeze band is unreachable from base-λ breaches alone (n≥10 for 60.00). Freeze fixtures use an overdue oversight review (λ=0.20 → six COMPLIANCE suspensions ≈ 73.79), which also necessitates a clock past `oversight_review_due_at`; those three deep-setup tests use `2027-01-01T00:00:00Z`.
4. **§3.8 narrative leaks an AML amount into a settlement test.** The clawback corner's stated `CardAccount.ledger_reversed_cents == 12000` for a 3500-cent load is an AML-domain copy-paste error; I asserted the principled value (3500) derivable from PRD §3.8's clawback text instead of the stale literal.

Verified by orchestrator: test_helpers/ (9 modules) and test_suite/ present.

## Step 6: Generate implementation — 2026-09-29T20:58:00.000Z

Done. Summary of the work:

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_3066_retail_cash_reload_network_bank_as_service/workspace/implementation/`:

- **`start.sh`** — guarded dep install (`if ! python3 -c "import flask"`), reads `$PORT` (default 10000 via `app.py`), binds `0.0.0.0`, `exec python3 app.py`
- **`app.py`** — blueprint registration + error handlers (ApiError, HTTPException, catch-all)
- **`db.py`** — in-memory dicts keyed by id, plus an insertion-order registry for "ascending created_at" listing
- **`errors.py`** — all 34 error IDs with their catalogue HTTP statuses
- **`response.py`** — the verbatim `meta`/`response_type`/`data` envelope; `error_id`/`message`; list pagination in `meta`
- **`middleware.py`** — `X-User-ID` / `X-User-Role`, 7 declared roles
- **`requests_helpers.py`**, **`timeutil.py`** — payload parsing, pagination bounds, logical clock (default `2026-09-01T00:00:00Z`)
- **`calc.py`** — all 11 calculation rules (fee tier walk, velocity, structuring, posture, provisional credit, loss waterfall, funding credit, settlement rounding, response windows, oversight)
- **`services/core.py`** — row factories, serialization, posture gates, cascades, alert helpers, program/sponsor reconciliation
- **`routes/`** — 13 modules (12 resources + the root-mounted clock)

## Endpoint count

**66 routes**, exactly matching the scaffold's `endpoint_count: 66`.

## Verification

Booted cleanly from a fresh process via `start.sh` on both a custom `$PORT` and the default 10000; storage is in-memory only (grep confirms no sqlite/json/open/pickle/tmp writes) and nothing is seeded. Four smoke suites covering every endpoint family pass with zero Python tracebacks. Formulas reproduce the scaffold's worked values exactly: fee walk (199 flat band 1; 230.13 for 3000), loss split summing exactly (bank floor remainder absorbed by program), and posture score (n=2 base 19.00, overdue 36.00, n=3 overdue 48.80).

## Ambiguous PRD passages and interpretations

1. **Convenience-fee band 2 — the "interpretation trap".** The scaffold's `flat_band_read` variant says "a 3000-cent load yields 448 instead of **232.38**". The nominal formula (`199 + 249·min(p,10000)−2000⁄8000`), the PRD prose, and every other worked example give **230.13** for 3000; 232.38 is arithmetically impossible (it implies a 199+249+399 figure only reachable above 10000 cents). I implemented the nominal formula. Note the trap's 448 figure would require the band to be *sequentially cumulative* (band 2 covering 0→10000), which contradicts both the stated 2000 lower bound and the PRD's "a 1500-cent and a 2000-cent load both pay 199". All pseudo-code anchor values (3000→230.13, 10000→448, above-10000→847) hold.

2. **`float_retained_cents` ("capped per constants") is never defined.** I interpreted it as the posted totals the batch's loads contributed to the agreement's float position, capped at the position actually held — so clawback (`float_position -= float_retained_cents`) never drives float negative.

3. **`posted_total_cents` vs the PRD's daily-limit rule.** The PRD says the location accumulates `posted_total_cents` while the admission check compares `principal + posted_total`. I follow the PRD literally (accumulate posted_total; check principal+posted_total). Because the fee's cent-truncation can make a stretch of principals trip the check slightly before the running total reaches the ceiling, this asymmetry is implemented as written rather than reconciled.

4. **Structuring during the `STRUCTURING_BAND` refusal.** The PRD's `risk_flag` rule is "the creation itself trips the predicate", but a create that would trip it is refused by priority 21. I set `risk_flag` after admission passes (so it is effectively always `NONE` at create), while the account's `is_structuring` flips on funding.

5. **`ERR_PROGRAM_RESTRICTED` scope.** Implemented exactly as the PRD enumerates it — onboard, first-fund and re-instate — and deliberately *not* on `POST /v1/brand-partners/{id}/state`, even though the scaffold's `validations[].applies_to` list includes that path. (PRD wins per the skill's precedence rule.)

6. **Body-reference errors.** Body FK misses raise `ERR_REFERENCED_RESOURCE_NOT_FOUND` (distinct helper) while path ID misses raise `ERR_ENTITY_NOT_FOUND`, avoided the scaffold's flat "FK -> X.id" phrasing that could otherwise have collapsed the two.

7. **Read-time recomputation of clock-derived fields.** Because the PRD says trailing windows "move with every read", GET responses for programs/accounts/locations recompute overdue flags, velocity windows and posture scores *without* bumping `version` or `updated_at` (that would inflate the OCC versions tests pin); mutating requests still freeze the computed values and bump once.

Verified by orchestrator: workspace/implementation/ present with start.sh, app.py, 12 route modules, services/core.py, calc.py; 66-route count reported; test_suite/ (10 files) and test_helpers/ (9 modules) confirmed present.

## Step 7: Run tests and iterate — 2026-09-29T22:10:00.000Z

All 8 rounds pass 106/106 with distinct timestamps; implementation storage remains in-memory only.

## Summary

**Iterations run:** 2 (baseline 8-round sweep → 24 deterministic failures; after fixes → clean 8/8).

**Tests deleted:** none. Every failing test's asserted rule traced to a verbatim PRD sentence with a unique, derivable outcome.

**Fixes applied to `test_helpers/`**
- `fixtures.py::setup_posted_loss_allocation` — default precondition was a *SETTLED* load (via `setup_settled_load`). PRD §3.8 places no load-status precondition on raising/posting an allocation, and a SETTLED load is excluded from the fund→confirm reversal hops the depth-5/§3.6 cascades walk, so `allocated_loss_total_reconciles_across_recovery` could never settle its batch. Now builds a plain FUNDED load (with an optional `load=` for callers that reverse their own load first).
- `test_04_state_machines.py` (×2) and `test_09_rbac_and_auth.py` — test-side artifacts: two brand tests suspended a `PENDING_ONBOARDING` brand (PRD §3.2 allows `ACTIVE → SUSPENDED` only); switched to `activate_brand_flag=True`. Added the missing `make_bank_sponsor_headers` import.

**Fixes applied to `implementation/`**
- `calc.py::posted_total_cents` — was truncating the fee to whole cents (`int(3745.69)` → `3746`), contradicting PRD §3.4/§2.6 worked examples (`3230.13`, `3745.69`). Now preserves the 2-dp fee.
- `timeutil.py::iso_instant` (+ `services/core.py::public`) — common props correctly carried 3 fractional digits, but the same serializer also rendered *domain clock stamps* (`funded_at`, `frozen_at`, `posted_at`, `retailer_response_due_at`) with `.000Z`, whereas PRD §2.9 supplies the clock as integer-second `2026-09-01T00:00:00Z`.
- `routes/load_transactions.py` — repeat-fund of a `FUNDED` load now raises `ERR_INVALID_STATE` (PRD §2.4: non-permitted transition) rather than `ERR_ALREADY_TERMINAL` (which §3.4 reserves for `DECLINED`); daily-limit and float accumulators made Decimal-exact.
- `routes/card_accounts.py` — hold moves: `FROZEN → CLEAR` now refused with `ERR_INVALID_STATE` (PRD §3.6 "never straight to `CLEAR`"); `REVIEW → CLEAR` now honours the frozen-program guard (`ERR_PROGRAM_FROZEN`).
- `routes/settlement_batches.py` + `services/core.py::reverse_load(unwind_agreement=…)` — clawback was unwinding the agreement twice (once via the reversal, once via the §3.8 compensation), driving `float_position_cents` to −3746. The reversal now adjusts only the account/ledger (§3.8 is explicit that clawback adjusts "each affected account's balance and ledger"), leaving the documented `float_retained_cents`/`accrued_retailer_share_cents` compensation to the clawback hop.
- `calc.py::float_retained_cents` — made Decimal-exact so it matches the fractional float position.
- `routes/float_windows.py` — the overlap check inflated *both* windows by their buffers; PRD §3.8 extends only the candidate ("a candidate window's interval, extended by its `buffer_minutes` on both sides").

**Test-side assertion corrections (test_suite/, PRD-faithful, no weakening):** the three velocity-breach tests read an undeclared `CardAccount.is_velocity_breached`; PRD declares that field only on `ReloadLocation` (§3.3, recomputed at §3.4 funding), so they now read the store. The freeze-driving test used `CLOCK_NOON` (λ=0.10, five breaches → 40.95, below the 60.00 band); it now advances the clock past `oversight_review_due_at` so λ=0.20 holds, as the other FROZEN fixtures already did. Nothing was skipped, xfailed, or downgraded.

Verified by orchestrator: all 8 `results.{1..8}.json` present, each reporting passed=106 total=106.

## Step 8: Finalize PRD — 2026-09-29T22:28:00.000Z

All ten edits are applied and verified against the implementation. Final state: `PRD_FINALIZED.md` is 379 lines (identical to PRD.md), 80,313 vs 78,549 chars (+2.25%), 10 lines changed.

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_3066_retail_cash_reload_network_bank_as_service/workspace/PRD_FINALIZED.md`

## Changes (one bullet per edit)

- **§2.6 (line 107) — revise** — "stored in integer cents … hold whole cents and are never fractional" reworded to "hold cents", with an added sentence pinning that the 2-dp scale is kept (not re-truncated) for `convenience_fee_cents`, `posted_total_cents`, `retailer_fee_share_cents`, `program_fee_share_cents` (§3.4) and the settlement accrual/payable/delta (§3.8). — `implementation/calc.py:86-97` (`posted_total_cents`), `calc.py:100-102`, `calc.py:232-248`.
- **§3.4 (line 183) — revise** — added the worked example that the fee's 2-dp scale carries through ("a 3000-cent principal whose fee is `230.13` has a posted total of `3230.13`"). — `implementation/calc.py:86`, `test_suite/test_04_state_machines.py:79`.
- **§2.9 (line 131) — revise** — added that domain datetime stamps (workflow stamps and payload deadlines) render at the instant's own precision (integer-second → no fractional part), and that the 3-fractional-digit rendering is scoped to the common properties (§2.5) and envelope (§2.2). — `implementation/timeutil.py:57-72` (`iso_instant`), `services/core.py:26-39,59-68` (`DATETIME_FIELDS`, `public`).
- **§3.2 (line 159) — revise** — added that a `RESTRICTED` program refuses brand activation (and suspended→`ACTIVE` restoration) with `ERR_PROGRAM_RESTRICTED`. — `implementation/routes/brand_partners.py:158-163`.
- **§3.2 (line 163) — revise** — restoration precondition now lists `ERR_PROGRAM_FROZEN` or, for a `RESTRICTED` program, `ERR_PROGRAM_RESTRICTED`. — `implementation/routes/brand_partners.py:158-163`.
- **§3.4 (line 187) — revise** — funding refusal broadened: `DECLINED` → `ERR_ALREADY_TERMINAL`, any other non-permitted source state → `ERR_INVALID_STATE`. — `implementation/routes/load_transactions.py:197-206`.
- **§3.6 (line 233) — revise** — `FROZEN → CLEAR` named as refused with `ERR_INVALID_STATE`. — `implementation/routes/card_accounts.py:168-173`.
- **§3.8 settling (line 261) — revise** — `float_retained_cents` defined concretely: sum of the batch's attached loads' `posted_total_cents`, capped at the agreement's current `float_position_cents`. — `implementation/calc.py:251-259`.
- **§3.8 clawback (line 263) — revise** — added that the reversal hop adjusts only the account balance/ledger and store counters, deliberately leaving the agreement's accrual and float to the separate compensation hop. — `implementation/services/core.py:544-594` (`reverse_load(unwind_agreement=)`), `routes/settlement_batches.py:237-251`.
- **§3.8 float (line 265) — revise** — overlap rule now states the stored window is compared as its own unstretched interval (only the candidate is buffer-extended). — `implementation/routes/float_windows.py:55-71`.

## Per-edit pre-edit search log

1. **§2.6 / §3.4 fee scale (edits 1–2)** — Subject: the fractional scale of fee-derived `_cents` fields.
 (b) Enumerated: `calc.py` `convenience_fee_cents`, `posted_total_cents`, `retailer_fee_share_cents`, `num`, `batch_amounts`, `float_retained_cents`; writer/consumer sites `routes/load_transactions.py` (create, fund, reverse), `core.py` `money_add/sub`, `reverse_load`, `routes/settlement_batches.py` (`settle`, clawback), `routes/loss_allocations.py` (share summation), `core.py` `recompute_location`/`recompute_program`.
 (c) Wording kept the "hold cents" softening plus an explicit bounded list of the 2-dp fields so the universal "never fractional" claim no longer contradicts `3230.13`/`3430.69`, while leaving all other `_cents` fields described as whole.
2. **§2.9 clock rendering (edit 4)** — Subject: precision of serialized datetime fields.
 (b) Enumerated every `timeutil.now()` stamp write and `require_datetime` read: `core.DATETIME_FIELDS` (programs, accounts, loads, alerts, disputes, allocations, batches, floats, banks), `core.public`, `routes/programs.py:57,153,304-305`, `routes/disputes.py:90,202`, `routes/loss_allocations.py:141`, `routes/settlement_batches.py:200`, `routes/load_transactions.py:223`, `routes/card_accounts.py:185`, `routes/aml_alerts.py:154`, `routes/admin_clock.py`, `routes/bank_sponsors.py`, `routes/float_windows.py`, `routes/retailer_agreements.py`.
 (c) Scoped the 3-digit rule explicitly to §2.5 common properties + §2.2 envelope and described domain stamps as "at the instant's own precision", avoiding a claim that all stamps drop fractions.
3. **§3.2 RESTRICTED guard (edits 3, 5)** — Subject: brand `ACTIVE`-entry guards.
 (b) Enumerated: `routes/brand_partners.py` `create_brand_partner` (guard_not_frozen + guard_not_restricted) and `move_brand_state` ACTIVE branch (guard_not_restricted, also for restoration); `services/core.py` `guard_not_restricted`; the §2.4 wording on onboard/first-fund/re-instatement and brand-creation being RESTRICTED-gated.
 (c) Revision limited to activation/restoration; left the §2.4 sentence and all frozen-only paths untouched to avoid re-describing brand creation.
4. **§3.4 funding refusal (edit 6)** — Subject: fund-from-non-`INITIATED` error id.
 (b) Enumerated: `routes/load_transactions.py:197-206` (FUNDED→ERR_INVALID_STATE, DECLINED/SETTLED→ERR_ALREADY_TERMINAL, REVERSED→ERR_INVALID_STATE); `decline_load` already_terminal; `reverse_load_route` invalid_state; `reinstate_load` `ERR_LOAD_NOT_REVERSED`; §2.4 uniform-state wording.
 (c) Wrote "a load in any other non-permitted source state surfaces `ERR_INVALID_STATE`" — covers FUNDED and REVERSED without claiming a single id for all non-`INITIATED` states.
5. **§3.6 hold FROZEN→CLEAR (edit 7)** — Subject: hold-transition error ids.
 (b) Enumerated all `routes/card_accounts.py:116-178` branches (same→invalid_state; non-FROZEN target while program frozen→program_frozen; CLEAR→REVIEW; REVIEW→CLEAR alert/frozen guards; to=FROZEN CLEAR/REVIEW; FROZEN→REVIEW), plus freeze cascades in `aml_alerts.py:150-171`, `programs.py:223-241`.
 (c) Only named the FROZEN→CLEAR case; left REVIEW→CLEAR's alert-then-frozen guard order and the conditional clear unspecified (PRD already determines them).
6. **§3.8 float_retained (edit 3)** — Subject: `float_retained_cents` formula.
 (b) Enumerated: `calc.float_retained_cents` (min of contributed posted totals vs position), `routes/settlement_batches.py:196-198` (caller), clawback consumer, and `float_position_cents` writers (fund `money_add`, float complete, reversal, clawback).
 (c) Replaced the vague "capped per the schedule's constants" with the concrete sum/cap, consistent with my §3.8 clawback wording.
7. **§3.8 clawback unwind (edit 9)** — Subject: which fields the clawback reversal hop touches.
 (b) Enumerated every `core.reverse_load` caller: `routes/load_transactions.py:305` (unwind_agreement default true), `routes/card_accounts.py:_freeze_account:190`, `routes/aml_alerts.py:162`, `routes/programs.py:235`, `routes/settlement_batches.py:237` (unwind_agreement=False); and the full body (`services/core.py:544-594`) — load, account balance/ledger, location counters, optional agreement accrual/float, alert dismissal, program recompute.
 (c) Softened "credits only the affected accounts" to "adjusts each affected account's balance and ledger and the store counters" so the sentence stays true for the store counters the hop also touches, and reordered to avoid the noun phrase "the reversal itself" reading as everything the hop does.
8. **§3.8 float overlap (edit 10)** — Subject: float-window overlap comparison.
 (b) Enumerated: `routes/float_windows.py:55-71` create overlap check, `_intervals_overlap` (closed both ends), the non-`CANCELLED` filter, plus cancel/confirm/complete transitions.
 (c) Added the parenthetical that the stored window is compared unstretched; kept "extended by its `buffer_minutes` on both sides" (candidate-only) verbatim from the PRD.

No new sections, no invented behavior; every change traces to a Step-7 item, and items that were pure fixture/test artifacts (`setup_posted_loss_allocation`, brand-suspend fixtures, velocity-breach reads, the clock-fixture breach test) required no PRD change because the PRD already determined them or the divergence was test-side only.

Verified by orchestrator: PRD_FINALIZED.md present, 379 lines, 80569 bytes (+2.31% over PRD.md's 78747 bytes).

## Step 9: Complete PRD — 2026-09-29T22:40:00.000Z

Done. `PRD_COMPLETED.md` is written and verified in place.

## Deliverable
`/home/ubuntu/github/CodingPRD/tasks/task_3066_retail_cash_reload_network_bank_as_service/workspace/PRD_COMPLETED.md`

## Source vs. completed
- Source: `PRD_FINALIZED.md` (379 lines, 80,569 chars)
- Completed: `PRD_COMPLETED.md` (381 lines, 87,023 chars)
- Delta: **+2 lines, +6,454 chars**; 30 PRD lines touched — 2 lines inserted, 28 revised in place. No new sections (`## ` count unchanged at 5); all changes are inline, in-paragraph.
- Counts: **27 ambiguity-pins**, **3 mismatch-revisions**.

## Changes (one per line)
- §2.2 Success envelope — insert — ambiguity — clock-setting capability returns `200` "object" with `{}` in `data` — `routes/admin_clock.py:26`
- §2.2 Error envelope — insert — ambiguity — unmapped path = `ERR_ENTITY_NOT_FOUND` 404; undeclared method = `ERR_INVALID_REQUEST` 400; other 4xx = `ERR_INVALID_REQUEST` at that status — `app.py:60-74`
- §2.3 Ordering — revise — ambiguity — equal `created_at` breaks by insertion sequence (total order) — `db.py:60-61`
- §2.4 Gate/refusals — revise — ambiguity — `ERR_AGREEMENT_NOT_ACTIVE` covers load-at-non-active store and batch open/settle; `ERR_SETTLEMENT_PERIOD_OVERLAP` covers both schedule overlap and second-open — `routes/settlement_batches.py:122,130-132`
- §2.5 Common properties — revise — ambiguity — read-time derived recompute (window counters, posture score) is not a mutation; leaves `updated_at`/`version` — `services/core.py:323-341`
- §2.7 OCC — revise — ambiguity — reversal/reinstate each guard one load; confirm/reopen/dismiss guard no version — `routes/load_transactions.py:292,318-319`
- §2.8 Card account model — revise — ambiguity — effective hold reported `FROZEN` while enclosing program is `FROZEN`, even if stored dimension unwritten — `services/core.py:233-240`
- §2.9 Clock — revise — ambiguity — payload timestamps without a zone designator are read as UTC — `timeutil.py:39-40`
- §2.9 Clock — revise — ambiguity — `epoch_index` is the UTC calendar-day ordinal of the instant — `timeutil.py:79-81`
- §2.10 SoD — revise — ambiguity — dismiss is officer-exclusive, return is analyst-exclusive — `routes/aml_alerts.py:100,117,194`
- §3.1 Sponsorship — revise — ambiguity — clock instants echo unchanged (no zone added) — `routes/bank_sponsors.py:38`, `timeutil.py:44-55`
- §3.2 Brands — revise — ambiguity — `ledgering_enabled`/`compliance_oversight_enabled` default false; `DISPUTE_HANDLING` exempt from checklist — `routes/brand_partners.py:99-103,49-53`
- §3.2 Suspension — revise — **mismatch** — PRD said "two-hop cascade"; impl runs three hops (brand, accounts, pending loads) — `routes/brand_partners.py:176-188`
- §3.3 Agreements — revise — ambiguity — renegotiation keeps the existing `fee_split_retailer_pct` — `routes/retailer_agreements.py:151-158`
- §3.3 Stores — revise — ambiguity — locations reach `RESTRICTED` only from `OPEN`, `OPEN` only from `RESTRICTED`; terminating an agreement closes every store regardless of state — `routes/reload_locations.py:114-131`, `routes/retailer_agreements.py:165-169`
- §3.4 Load creation — revise — ambiguity — fixed pre-check order: clerk-ownership 403, program not FROZEN/RESTRICTED, agreement ACTIVE, location OPEN, hold CLEAR, no live alert, expected-version, then admission control — `routes/load_transactions.py:57-114`
- §3.4 Funding — revise — ambiguity — clerk-ownership 403; program must be exactly `OPEN`; `DECLINED` and already-`SETTLED` yield `ERR_ALREADY_TERMINAL` — `routes/load_transactions.py:193-212`
- §3.4 Reversal — revise — ambiguity — hop 2 also dismisses `OPEN` `VELOCITY` alerts whose trip fell below limits — `services/core.py:437-443`
- §3.5 Oversight — revise — ambiguity — `review_note` accepted but not retained; `overdue_days` not returned — `routes/programs.py:300-309`
- §3.6 Alerts — revise — ambiguity — manual `STRUCTURING` predicate recomputed from account loads; supplied window bounds do not constrain it — `routes/aml_alerts.py:52-57`
- §3.6 Alerts — revise — ambiguity — system-raised alert records `raised_by_analyst_id` = literal `"system"`, window = now−24h…now — `services/core.py:454-464`
- §3.6 Hold moves — revise — ambiguity — any freeze recomputes the program's alert count/score and advances program version — `routes/card_accounts.py:162-165`
- §3.7 Provisional credit — revise — ambiguity — REG_E provisional preserved at `PROGRAM_REVIEW`; CORPORATE becomes non-zero only at cardholder resolution — `calc.py:192-215`
- §3.7 Deadline — revise — ambiguity — same window-closed refusal applies to supplemental responses and escalation — `routes/disputes.py:141-147,214-222`
- §3.7 Retailer response — revise — ambiguity — `retailer_position` string required — `routes/disputes.py:158`
- §3.7 Resolution — revise — ambiguity — cardholder-favour reverses the load only if it is `FUNDED`/`SETTLED` — `routes/disputes.py:255-256`
- §3.8 Allocation — revise — ambiguity — recover requires a settled batch of the cited agreement whose period contains `posted_at` — `routes/loss_allocations.py:163-189`
- §3.8 Settlement — revise — ambiguity — `period_start_at` must precede `period_end_at` (400); open-time duplicate `OPEN` reuses overlap code — `routes/settlement_batches.py:48-49,126-132`
- §3.8 Settlement — revise — **mismatch** — drop `ERR_LOAD_OUTSIDE_SETTLEMENT_PERIOD` prose (impl never raises it; out-of-period loads are simply not attached, empty period yields `ERR_SETTLEMENT_EMPTY_PERIOD`); settle role narrowed from "ComplianceAnalyst or SettlementOperator" to `SettlementOperator`; settle also requires agreement `ACTIVE` — `routes/settlement_batches.py:139-175`
- §3.8 Float — revise — ambiguity — location must be `OPEN`; `window_start_at` must not exceed `window_end_at`; cancel from `REQUESTED` or `CONFIRMED`; buffered interval touching another window's edge counts as overlap — `routes/float_windows.py:46-71,138`

## Notes
- `ERR_LOAD_OUTSIDE_SETTLEMENT_PERIOD` is retained in the §5 catalogue because the implementation still defines the constructor (`errors.py:100`); only its prose use was corrected. The only other catalogue entries without a live impl raise site are `ERR_PROGRAM_RESTRICTED` on the re-instatement path (impl's re-instatement never restricts-check) — I did not add or remove prose for it, since the PRD never explicitly pinned it.
- I found and reverted one bad edit of my own during the walk: I had briefly added a `FROZEN` guard to the program posture transition, but `routes/programs.py:95-151` performs no frozen-check on a posture move, so the original PRD text was correct and was restored.

Verified by orchestrator: PRD_COMPLETED.md present, 381 lines, 87023 bytes (+8.01% over PRD_FINALIZED.md's 80569 bytes). Full pipeline complete; all 8 stability rounds passing 106/106.