# 0002 — Ship a scripted public demo

- **Status:** Accepted
- **Date:** 2026-10-26

## Context

The project needs a public, linkable demo for a portfolio. The generative
prototype requires a local Ollama daemon, several gigabytes of model weights,
and a GPU or a lot of patience. Exposing it as a public service would require
hosting, authentication, rate limiting, and a budget for inference.

The interesting product behavior — a support operator who escalates through
stages and eventually capitulates — can be reproduced without a model.

## Decision

Build a fully static demo in `demo/` with a deterministic dialogue state
machine and hand-written reply variants.

- No backend, no LLM, no network requests.
- Static assets only: `index.html`, `style.css`, `app.js`.
- Works from a static web server and from `file://`.
- Stage progression uses turn count plus aggression/keyword heuristics.
- Each stage has multiple reply variants to avoid an identical transcript.
- The demo carries a visible badge stating that replies are pre-written.
- The real prototype remains the place where Ollama is used.

## Consequences

### Positive

- Instant load and zero inference cost; safe to host on any static host.
- Deterministic behavior that is easy to test and reason about.
- No prompt-injection surface and no model-output safety issues.
- The public demo is honest: it does not pretend to be generative.
- Works offline and without a GPU.

### Negative / trade-offs

- Replies are finite; a determined user can exhaust the variants.
- The demo cannot understand arbitrary language the way the prototype can.
- Two dialogue implementations (scripted and LLM) must be kept conceptually
  aligned.
- Scripted content needs occasional editorial maintenance.

## Alternatives considered

1. **Host the real Ollama prototype.** Best fidelity, but requires GPU hosting,
   authentication, rate limiting, and ongoing cost. Rejected for the public
   demo.
2. **Call a hosted LLM from the browser.** Enables arbitrary dialogue, but
   exposes an API key, creates cost and abuse risk, and breaks the offline/static
   requirement.
3. **Pre-generate a single transcript.** Cheapest, but feels dead: no input,
   no quick replies, no stage control.

## Follow-up

- Keep the shared vocabulary of stage labels and escalation cues aligned with
  `prototype/persona.py`.
- Treat the static demo as a product demo, not as evidence of model quality.
- Document the distinction in the README and in `demo/README.md`.
