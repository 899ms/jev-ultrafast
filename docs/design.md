# Dynamic operation + target

The input is a natural-language goal. Every page observation builds an indexed table of accessible elements and their current values. One node receives one index, even when it supports both clicking and typing.

One TypeSafe request asks which operation to perform and which target would be appropriate for each available operation. The executor consumes only the target head corresponding to the selected operation. This avoids serial operation-then-target calls and rejects targets incompatible with the operation. Dropdown targets include a code-owned option index.

Operation and target questions receive the same next-step rules. Target criteria include current values and checked/selected state. The questions run independently: a target cannot read the operation answer, so its premise explicitly names the operation it assumes.

TYPE_TEXT sends the goal, selected field, visible page context, and recent actions to a small LLM. Its JSON must contain exactly one valid `text` value. The code does not extract quoted literals. A value can be reused after a stale decision only while the entire helper input is identical, and is discarded after a successful mutation.

## Runtime

Accessibility supplies names, roles, values, and backend node IDs. Cached remote object references avoid resolving the same DOM node every observation; a single read obtains current rectangles and dropdown options. New references resolve concurrently. Document changes invalidate the cache. Geometry is never cached across decisions.

The model sees visible text and accessible alerts/status. Background focus emulation keeps animation frames running in the owned tab. Screenshots are optional and disabled in library calls by default; `screenshots=True` or `record_dir=...` enables them. The inspector enables them explicitly. A continuous screencast can record a run separately.

A full DOM mutation marker plus current form properties invalidates stale decisions. Replaced nodes, changed values, and covered targets cannot silently reuse an old click. Browser mutations are not retried by transport recovery. Completed execution is logged before the next observation, including when that observation encounters a navigation.

## What changed after the first demo

The initial prototype used five manually prepared steps and copied quoted strings. That proved finite-choice browser execution but did not demonstrate task decomposition or text generation. The current policy removes that shortcut and uses the original goal throughout. Operation/target distributions replace the old flat-choice/lookahead/Noul arrangement.

The audit also found that treating every INPUT as editable misclassified checkboxes. Editable roles now control TYPE_TEXT availability. Tests cover checkbox/radio/button distinction, invalid operation/target outputs, stale decisions, text-cache invalidation, missing credentials, waits, and final-route verification.

## Boundaries

Sixty browser actions and 120 decision requests bound a run. Up to 250 action candidates are retained; truncated candidates cannot be selected. The service stays loopback-only, serializes inspector actions, and checks Host, Origin, and a local request token. Credentials remain server-side. Tabs share the existing Chrome profile.

The policy is generic, but two websites do not establish broad reliability. Unsupported frames, canvas, uploads, nested scrolling, pop-ups, and complex keyboard interactions can block progress. A valid action can still be wrong. Independent checks, rather than the model's DONE choice, determine whether the demonstrated task succeeded.
