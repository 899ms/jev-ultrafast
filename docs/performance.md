# Real tasks, dynamic actions

The current agent accepts one natural-language goal, indexes the live page, and asks TypeSafe for an operation plus operation-specific targets in one request. A small LLM generates text. There are no prepared browser steps or quoted-value extraction in these runs.

| Recorded smoke | Agent time | Jev requests | Text-model calls | Independent result |
| --- | ---: | ---: | ---: | --- |
| Google Flights: Zürich → London, one way, 20 September 2026 | **11.387 s** | 23 | 2 | Route, date, year, one-way setting, visible flights checked |
| Wikipedia: open Gödel’s incompleteness theorems | **3.678 s** | 3 | 1 | Exact destination article URL checked |

[Google Flights recording](demo.mp4) · [Machine-readable evidence](flights-measurement.json)

These are two live smoke tasks, not a broad benchmark or a matched causal speed claim. They used an existing Chrome profile, live network responses, and caches. The policy is site-independent; the outcome checks are task-specific and are not shown to the model.

## Recorded flight run

The clock starts with the first prediction, after the generic Google Flights homepage is observed. It ends at the final DONE choice. It includes generated text, model requests, browser operations, observation, discarded stale decisions, and loading waits. Initial navigation, browser setup, and independent post-run checks are outside the clock.

- TypeSafe: `jev-1.13.0`, 23 requests, 175 ms median, 4,160 ms total request time.
- Text helper: `google/gemini-2.5-flash-lite`, JSON output, reasoning disabled.
- Generated values: Zurich in 873 ms; London in 590 ms. Two actual helper requests.
- Browser: 10 interactions and one explicit wait. Additional loading was observed during freshness recovery.
- Video: 309 continuous screencast frames at original timestamps. 1× playback, with a 750 ms intro and 2-second final hold. Every frame crops out the Google account/navigation strip.

Observed results included easyJet ZRH → LGW, 16:45–17:35, $216; British Airways/BA Cityflyer ZRH → LCY, 20:25–21:00, $265; and British Airways ZRH → LHR, 13:20–14:20, $271. These are observed fares, not a guarantee of current or cheapest pricing. No flight was selected or booked.

## Changes and failures retained

The audit found blocking screenshots in a text-only policy, repeated whole-DOM copies, and hidden-tab animation throttling. Reading current geometry for cached candidate nodes reduced a settled Google homepage observation from roughly 100 ms to 30 ms in the local probe. Removing screenshots initially broke menus because Chrome throttled hidden rendering; focus emulation fixed that cause without switching the visible tab.

A first natural-goal flight run took 15.580 s with unnecessary waits after the form was ready. The next took 13.753 s using GLM. The first continuous recording with Gemini took 13.152 s. The final run took 11.387 s after reducing page text to the visible viewport. These changed-code/provider development attempts are **not matched performance comparisons**.

Wikipedia initially hit a transient document-evaluation error during navigation. After adding read-only navigation recovery, it completed in 11.645 s; the final visible-context version completed in 3.678 s. Provider latency and page context changed, so the difference is not attributed solely to the code.

Text-helper probes also rejected two tempting shortcuts: Llama 3.1 8B returned the destination for an origin field, and a Qwen route emitted commentary. The helper now requires exactly one valid JSON `text` field and stops before typing malformed output. This validates the output format, not the semantic correctness of every generated value.

### Filter regression after the recording

A local hotel fixture exposed a policy failure: the agent opened a matching property before applying requested filters, returned to the list repeatedly, and could report DONE with unmet requirements. One earlier attempt reached the 60-action limit. The diagnostic runner now writes its trace even on exceptions and retains separate attempt directories.

The target question lacked the operation question's next-step rules. Both now receive the same rules; each target also includes checked/selected state directly. A further rule distinguishes typing into a search field from submitting that search. This keeps the policy generic, with no hotel selectors or prepared browser steps.

After these changes, the original task, “Find a Design stay in Lisbon with Free cancellation and open Casa Flora,” passed in **4.404 s**, with six Jev requests, one text-helper call, and five actions. An explicitly worded search/filter task passed in **1.846 s**. Both independently checked the final property and all three applied filters. The original wording's pre-fix failure is retained; the explicit wording is a separate diagnostic, not a matched improvement claim.

The final policy then passed the same Google Flights task in **12.898 s**, with 23 Jev requests and two text-helper calls. Route, date, year, one-way setting, and visible results passed a fresh post-run observation. The **11.387 s video predates this filter-policy change**; its original source hashes remain in the recording manifest, alongside the separate final-policy regression hashes. These are development smoke runs, not a reliability estimate.

## Historical prepared demo

The original 12.884-second flight demo used five hand-written goal steps and copied quoted city strings. It is not the current architecture. Its measurements remain in [flights-prepared-measurement.json](flights-prepared-measurement.json) and [performance-prepared.md](performance-prepared.md). The earlier 1.086–1.311-second hotel runs were authored local fixtures, documented in [measurement.json](measurement.json).

## Remaining limits

A DONE choice is not independent evidence of success. The action space is capped and can omit elements; frames, canvas, uploads, pop-up tabs, nested scrolling, and arbitrary keyboard controls are unsupported. The two successful tasks demonstrate the same runtime on two sites, not broad generalization or production reliability.
