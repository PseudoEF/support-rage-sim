# 0001 — Run the prototype against local Ollama

- **Status:** Accepted
- **Date:** 2026-10-26

## Context

The project needs a generative version of the support character for local
experimentation. The character is intentionally difficult: a long Russian system
prompt, six stage prompts, a personality quirk (upselling), and a requirement
to stay in Russian. The prototype should be cheap to run, private, and easy to
start on a developer machine.

The original prototype already used Ollama with `qwen2.5:7b-instruct` and a
stdlib HTTP server. The question was whether to keep that approach or move to a
hosted API.

## Decision

Keep the generative prototype on **local Ollama** with a stdlib-only Python
server.

- Ollama runs on loopback at `/api/chat`.
- The model and URL are configurable through environment variables.
- The server owns prompt assembly; the client cannot choose a stage.
- A language-leak retry loop and output sanitization sit between the model and
  the browser.

## Consequences

### Positive

- No API keys, no per-token cost, and no customer text leaving the machine.
- Works offline once the model is pulled.
- The full model path is visible in the repository and easy to demo.
- The server has no runtime dependencies.

### Negative / trade-offs

- A 7B model needs roughly 6 GB of VRAM or unified memory and adds 10–40 s of
  latency in the observed environment.
- Quantized models occasionally leak another language, which requires retries
  and cleanup.
- The prototype is not suitable for public hosting: no auth, no TLS, in-memory
  sessions, and a local daemon dependency.

## Alternatives considered

1. **Hosted LLM API.** Lower local hardware requirements, but adds cost, a
   secret, network dependency, and a data-processing question. Rejected for a
   local portfolio prototype.
2. **A smaller local model.** Lower VRAM and latency, but weaker instruction
   following for a long Russian prompt and more language drift.
3. **No generative version at all.** Cheaper to maintain, but then the project
   would not demonstrate prompt staging, retries, or Ollama integration.

## Follow-up

- Keep the six-stage prompt design in `prototype/persona.py`.
- Keep the pure language-guard helpers testable without Ollama.
- Do not expose the prototype without authentication and a shared session
  store.
