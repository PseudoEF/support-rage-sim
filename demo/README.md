# Scripted public demo

This folder is a **fully static, offline demo** of the support-rage simulator.
It is intentionally not connected to an LLM, a backend, or the network.

The UI is in Russian because the character and the source prototype are
Russian. The engineering notes below are in English.

## What this is

- `index.html` — semantic chat UI, badge, stage indicator, composer, quick replies.
- `style.css` — dark responsive theme, no external fonts, images, or CDNs.
- `app.js` — deterministic dialogue state machine with scripted reply variants.

Open `index.html` directly from disk (`file://`) or serve the folder from a
static web server. All asset paths are relative, so both work.

```sh
# Option 1: just open the file
xdg-open demo/index.html

# Option 2: static server (example)
python -m http.server 8081 --directory demo
```

There are **no `fetch` calls**, no analytics, no third-party resources, and no
network requests of any kind.

## How the scripted dialogue works

The demo uses the same character as the real prototype: **Артём**, a support
operator at the fictional ISP «СвязьЛайн». The escalation has six stages plus a
capitulation end state:

| Stage | Baseline turns | Behaviour |
| --- | --- | --- |
| 1 | 1–2 | Calm bureaucracy, clarifying questions, standard troubleshooting, first upsell |
| 2 | 3–4 | Tired politeness, repeated steps, more upsell |
| 3 | 5–6 | Passive aggression, requests for account details, cites internal regulations |
| 4 | 7–8 | Sarcasm, blames the customer's equipment, refuses compensation |
| 5 | 9–10 | Cracks in the armour, nervous short replies, first mention of escalation |
| 6 | 11 | Nearly capitulates, offers an absurd small concession |
| 7 | 12 | Full capitulation, disproportionate compensation, emotional apology |

The stage is selected by a pure function:

1. Start with a baseline stage derived from the turn number.
2. Add up to **+2** for aggression (profanity, threats, caps, exclamation marks)
   and escalation keywords (`суд`, `расторг`, `руководство`, `компенсация`, …).
3. Never move backwards.
4. At turn 12, force the capitulation stage regardless of tone.

Each stage has four scripted reply variants, and the final stage has four
capitulation variants. Variants are chosen at random but never repeat
immediately. Escalation keywords can prepend a short acknowledgement line, so
the conversation reacts to what the user actually said without pretending to be
generative.

The demo also demonstrates the same product constraints as the hardened
prototype:

- 500-character message cap (`maxlength` + JS clamp)
- 12-turn cap with a graceful end state
- restart button
- 300–900 ms typing delay with a typing indicator
- suggested quick replies, keyboard accessible
- no network calls

## Accessibility and responsiveness

- Semantic landmarks (`header`, `main`, `form`, `footer`), a skip link, and
  visible `:focus-visible` states.
- The chat log is a polite live region; the typing indicator is a status.
- Quick replies and the composer are real buttons/inputs, usable by keyboard.
- `prefers-reduced-motion` disables animations and smooth scrolling.
- Layout is tested by design at **390×844** and **1440×900**.

## Why scripted instead of the real model?

A public portfolio demo needs to be instant, free, deterministic, and safe to
run anywhere. The scripted demo has no API key, no GPU, no cold start, no
prompt-injection surface, and no inference cost. The real local prototype
(`prototype/server.py`) still uses Ollama and exists to show the full LLM
engineering path: prompt staging, retries, and language-leak cleanup.

See [`../docs/adr/0002-scripted-public-demo.md`](../docs/adr/0002-scripted-public-demo.md)
for the decision record.
