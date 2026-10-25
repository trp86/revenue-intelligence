# 08 Explore and Decision Assistant (Epic E8)

Status: DRAFT. FR-U5, FR-U6. Both use the same allow-listed query
layer (spec 06 section 4).

## 1. Purpose and scope
| In | Out |
|---|---|
| Explore: guided self-service | Free-form SQL, user-defined measures |
| Assistant: chat with fixed, tested tools | Autonomous actions, web search, RAG |
| Suggested questions, evidence display, refusal | Forecasting |

## 2. Explore (FR-U5)
| Item | Rule |
|---|---|
| Measures (fixed) | net sales, quantity, order count, active customers, average order value [x] |
| Dimensions (fixed) | month, quarter, year, region, branch, channel, category, brand, product, customer (top-N only) |
| Filters | any dimension; date range |
| Period comparison | prior period, prior year; shows absolute and % change; zero base shows "n/a" not infinity |
| Drill-through | click a row to apply the dimension as a filter or open Customer 360 |
| Export | CSV of exactly the displayed query, with a header row stating definition, filters, as-of |
| Definition | every view shows measure definition and net sales field |
| Limits | caps from spec 06 (rows, dimensions, timeout) |
| State | query held in URL |

Catalog comes from `GET /explore/catalog`; UI builds controls from it
(no hard-coded lists).

## 3. Decision Assistant (FR-U6)
Architecture: Gemini receives the user question plus tool
declarations; it selects a tool and arguments; Python executes the
tool; results go back for a plain-language answer. The model never
computes numbers (same rule as spec 05).

### 3.1 Tools (fixed, tested, each a pydantic-typed function)
| Tool | Wraps |
|---|---|
| `run_explore_query` | allow-listed query layer |
| `list_opportunities` | /opportunities service (filters, top N) |
| `get_opportunity_evidence` | evidence facts for an opp |
| `get_customer_summary` | Customer 360 service |
| `compare_periods` | query layer with `compare_to` |
| `get_backtest_summary` | backtest metrics |
| `get_definition` | definitions lookup |
No tool accepts SQL text. Unknown tool or invalid args are rejected.

### 3.2 Behaviour rules
| ID | Rule |
|---|---|
| A1 | Every answer lists the tools called, arguments and the evidence rows/figures used (expandable) |
| A2 | Numbers in the answer must appear in tool results (same post-check as spec 05 G2) |
| A3 | If no tool can answer, reply "The data cannot answer this" plus what is available; no guess |
| A4 | Out-of-scope topics (margin, inventory, promotion, forecasting, competitors) get a refusal naming the scope |
| A5 | Max `assistant.max_tool_calls` per turn (default 5); history window `assistant.history_turns` (default 6) |
| A6 | Prompt-injection text in data fields is treated as data; tool outputs are never executed as instructions |
| A7 | Identifiers masked to Gemini per spec 05; tool results sent are aggregates or top-N rows only, capped by `assistant.max_result_rows` (default 20) |
| A8 | If AI disabled, the assistant page shows the suggested questions as pre-built Explore links |
| A9 | Each turn stored in `app_chat_turns` (question, tools, evidence hash, model, prompt version, time) |

### 3.3 Suggested questions (success criterion 6)
Examples of the type to support; the exact list [x] is agreed with the client:
- Which opportunities are highest priority this month?
- Which customers are dormant in <branch>?
- How did net sales in <channel> change versus last year?
- Why is <customer> flagged?
- How reliable is the recovery logic? (backtest)
Each has a golden test: expected tools, expected figures from SQL.

## 4. Configurable parameters
| Key | Default |
|---|---|
| `assistant.max_tool_calls` | 5 |
| `assistant.history_turns` | 6 |
| `assistant.max_result_rows` | 20 |
| `assistant.enabled` | follows `ai.enabled` |
| `explore.*` | spec 06 |

## 5. Edge cases
- Ambiguous question: assistant asks one clarifying question.
- Empty result: says so with filters used.
- Tool error / timeout: says it could not retrieve, shows no figure.
- Very long input: truncated at [x] chars with notice.
- Customer name typed in a question: resolved by a lookup tool, locally.

## 6. Acceptance-level checks
- [ ] Explore result for each measure equals an independent SQL check on `v_net_sales`
- [ ] CSV export matches the on-screen table (row count and totals)
- [ ] Period comparison: zero-base case returns n/a
- [ ] Assistant with a scripted fake model: golden suggested questions return expected tool calls and figures
- [ ] Question outside data returns the "cannot answer" message (test)
- [ ] An answer containing a number absent from tool results is rejected (test)
- [ ] No tool or endpoint accepts raw SQL (test)
- [ ] Evidence panel renders tool name, args, rows for each answer
- [ ] Assistant tests run offline

## 7. Dependencies
Specs 06 (query layer, chat endpoint), 05 (client, guardrails), 07 (shell), 04 (Proof tool).

## 8. OPEN QUESTIONS
- OPEN QUESTION: The official list of suggested questions. Default:
  the five above. Why: success criterion 6 needs a testable list.
- OPEN QUESTION: Should chat be streaming? Default: no. Why: POC simplicity.
- OPEN QUESTION: Persist chat history across sessions? Default: store turns for audit, UI shows current session only. Why: minimal scope.
- OPEN QUESTION: Does Explore expose customer-level rows? Default: yes, top-N cap, no cap on export except row limit. Why: internal tool; revisit with privacy decision.
