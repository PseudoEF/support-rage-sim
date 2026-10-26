#!/usr/bin/env python3
"""Local prototype server for the support-rage simulator.

The server is deliberately stdlib-only: it serves a tiny static chat page and
proxies messages to a local Ollama instance. All dialogue state lives in memory.

Run:
    python prototype/server.py

Configuration (environment variables):
    HOST                  bind address (default 127.0.0.1)
    PORT                  bind port (default 8000)
    OLLAMA_URL            Ollama chat endpoint
    OLLAMA_MODEL          model name
    OLLAMA_TIMEOUT        upstream request timeout in seconds
    SESSION_TTL_SECONDS   idle session lifetime
    MAX_SESSIONS          maximum number of in-memory sessions
    RATE_LIMIT_REQUESTS   POST requests allowed per IP per window
    RATE_LIMIT_WINDOW_SECONDS
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

try:  # package import (tests, `python -m prototype.server`)
    from . import persona
except ImportError:  # script import (`python prototype/server.py`)
    import persona

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct")
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "60"))
STATIC_DIR = Path(__file__).parent / "static"

MAX_MESSAGE_CHARS = 500
MAX_TURNS = 12
MAX_BODY_BYTES = 16 * 1024
MAX_REPLY_CHARS = 2000
SESSION_TTL_SECONDS = int(os.environ.get("SESSION_TTL_SECONDS", "1800"))
MAX_SESSIONS = max(1, int(os.environ.get("MAX_SESSIONS", "500")))
RATE_LIMIT_REQUESTS = max(1, int(os.environ.get("RATE_LIMIT_REQUESTS", "30")))
RATE_LIMIT_WINDOW_SECONDS = max(1, int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60")))

STAGE_COUNT = 6
FINAL_STAGE = 7
MAX_GENERATION_ATTEMPTS = 3
FALLBACK_REPLY = "Извините, у меня сорвалась мысль. Повторите, пожалуйста."

STAGE_LABELS = {
    1: "спокоен",
    2: "спокоен",
    3: "раздражается",
    4: "раздражается",
    5: "трещит по швам",
    6: "на грани",
    7: "капитуляция",
}

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}

# CJK/Hangul ranges — quantized Qwen occasionally leaks these mid-sentence.
FOREIGN_SCRIPT_RE = re.compile(r"[一-鿿぀-ヿ가-힯]")

# 3+ consecutive Latin words = a real English phrase leaked in, as opposed to
# an isolated acronym like "Wi-Fi" or "CRM" which is normal in RU tech-speak.
ENGLISH_PHRASE_RE = re.compile(
    r"(?:\b[A-Za-z]+(?:'[A-Za-z]+)?\b\s+){2,}\b[A-Za-z]+(?:'[A-Za-z]+)?\b"
)

RETRY_NUDGE = {
    "role": "system",
    "content": (
        "Твой предыдущий ответ содержал слова на другом языке — это ошибка. "
        "Ответь заново ТОЛЬКО на русском языке, целиком, без единого слова "
        "на другом языке (обычные аббревиатуры вроде Wi-Fi, IP, CRM — можно)."
    ),
}

PROFANITY_RE = re.compile(
    r"(?i)\b(?:хуй|хуя|хуе|хуё|пизд|бля|еб[аоуь]|ёб|заеб|нахуй|нахер|"
    r"сук[аи]|мудак|идиот|дебил|урод|тварь)\w*"
)
THREAT_RE = re.compile(
    r"(?i)(?:суд|иск|роспотребнадзор|прокуратур|жалоб|расторг|ухожу|уйду|"
    r"юрист|адвокат|компенсац|перерасч|верните\s+деньги)"
)
URGENCY_RE = re.compile(
    r"(?i)(?:хватит|достал|надоел|издева|бардак|обман|воры|безобраз|"
    r"срочно|немедленно|сколько\s+можно)"
)
KEYWORD_PATTERNS: dict[str, re.Pattern[str]] = {
    "money": re.compile(r"(?i)(?:деньг|компенсац|перерасч|верните|оплат|списан|тариф|счёт|счет)"),
    "legal": re.compile(r"(?i)(?:суд|иск|роспотребнадзор|прокуратур|юрист|адвокат|жалоб)"),
    "escalation": re.compile(r"(?i)(?:руководств|менеджер|старш|соедин)"),
    "outage": re.compile(
        r"(?i)(?:не\s+работает|нет\s+интернет|пропал|отключ|авари|просто[йяю]|сутк)"
    ),
    "hardware": re.compile(
        r"(?i)(?:роутер|маршрутизатор|кабел|вайфай|wi-?fi|wifi|провод|порт|онт|терминал)"
    ),
    "speed": re.compile(r"(?i)(?:скорост|мегабит|мбит|медленн|тормоз|лага|пинг)"),
    "leave": re.compile(r"(?i)(?:расторг|ухожу|уйду|отключ|другой\s+провайдер|отказ)"),
}

CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
WHITESPACE_RE = re.compile(r"\s+")
SPACE_RUN_RE = re.compile(r"[ \t]+")
NEWLINE_RUN_RE = re.compile(r"\n{3,}")


class InputError(ValueError):
    """Raised when a user message cannot be accepted as-is."""


class RequestError(Exception):
    """An HTTP error that should be rendered as JSON."""

    def __init__(
        self,
        status: int,
        message: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.headers = headers or {}


# ---------------------------------------------------------------------------
# Pure helpers (tested without Ollama or a live server)
# ---------------------------------------------------------------------------


def sanitize_user_text(raw: Any) -> str:
    """Remove control characters and collapse whitespace. Never truncates."""
    if not isinstance(raw, str):
        return ""
    cleaned = CONTROL_CHARS_RE.sub(" ", raw)
    return WHITESPACE_RE.sub(" ", cleaned).strip()


def validate_message(raw: Any) -> str:
    """Return a clean user message or raise :class:`InputError`."""
    text = sanitize_user_text(raw)
    if not text:
        raise InputError("empty message")
    if len(text) > MAX_MESSAGE_CHARS:
        raise InputError(f"message too long (max {MAX_MESSAGE_CHARS} chars)")
    return text


def normalize_session_id(raw: Any) -> str:
    """Keep client session ids short and boring, or generate a fresh one."""
    if isinstance(raw, str):
        cleaned = re.sub(r"[^A-Za-z0-9_.:-]", "", raw.strip())[:128]
        if cleaned:
            return cleaned
    return secrets.token_hex(8)


def detect_aggression(text: str) -> int:
    """Heuristic 0..4 score for rudeness, caps, threats and urgency."""
    if not text:
        return 0
    score = 0
    if PROFANITY_RE.search(text):
        score += 2
    if THREAT_RE.search(text):
        score += 1
    if URGENCY_RE.search(text):
        score += 1
    if text.count("!") >= 2:
        score += 1
    letters = [char for char in text if char.isalpha()]
    if len(letters) >= 12:
        uppercase_ratio = sum(char.isupper() for char in letters) / len(letters)
        if uppercase_ratio > 0.7:
            score += 1
    return min(score, 4)


def detect_keywords(text: str) -> list[str]:
    """Return semantic categories found in the message (deterministic order)."""
    if not text:
        return []
    return [name for name, pattern in KEYWORD_PATTERNS.items() if pattern.search(text)]


def escalation_bonus(text: str) -> int:
    """How many stages a single message can add on top of the turn baseline."""
    aggression = detect_aggression(text)
    keywords = detect_keywords(text)
    bonus = 0
    if aggression >= 2:
        bonus += 1
    if aggression >= 4:
        bonus += 1
    if {"legal", "leave", "escalation"} & set(keywords):
        bonus += 1
    return min(bonus, 2)


def base_stage_for_turn(turn: int) -> int:
    """Calm two-turn-per-stage baseline, capped by the scripted turn limit."""
    if turn >= MAX_TURNS:
        return FINAL_STAGE
    if turn < 1:
        return 1
    return min(STAGE_COUNT, (turn + 1) // 2)


def select_stage(turn: int, text: str = "", previous_stage: int = 1) -> int:
    """Choose the current persona stage.

    The stage advances with the turn count and can be accelerated by aggressive
    language or escalation keywords. It never goes backwards. Reaching the turn
    limit always produces the capitulation stage.
    """
    if previous_stage >= FINAL_STAGE or turn >= MAX_TURNS:
        return FINAL_STAGE
    base = base_stage_for_turn(turn)
    stage = min(STAGE_COUNT, base + escalation_bonus(text))
    return min(STAGE_COUNT, max(previous_stage, stage))


def stage_label(stage: int) -> str:
    if stage >= FINAL_STAGE:
        return STAGE_LABELS[FINAL_STAGE]
    return STAGE_LABELS.get(stage, STAGE_LABELS[1])


def has_language_leak(text: str) -> bool:
    return bool(text and (FOREIGN_SCRIPT_RE.search(text) or ENGLISH_PHRASE_RE.search(text)))


def strip_foreign_script(text: str) -> str:
    """Remove CJK/Hangul characters and tidy the resulting whitespace."""
    cleaned = FOREIGN_SCRIPT_RE.sub("", text or "")
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def sanitize_reply(text: str) -> str:
    """Normalise model output before it reaches the browser."""
    if not isinstance(text, str):
        return ""
    cleaned = text.replace("\x00", "")
    cleaned = CONTROL_CHARS_RE.sub("", cleaned)
    cleaned = SPACE_RUN_RE.sub(" ", cleaned)
    cleaned = NEWLINE_RUN_RE.sub("\n\n", cleaned).strip()
    if len(cleaned) > MAX_REPLY_CHARS:
        cleaned = cleaned[:MAX_REPLY_CHARS].rstrip() + "…"
    return cleaned


def reserve_turn(turn: int) -> int | None:
    """Return the next turn number, or ``None`` when the session is exhausted."""
    if turn >= MAX_TURNS:
        return None
    return turn + 1


# ---------------------------------------------------------------------------
# Ollama integration
# ---------------------------------------------------------------------------


def _generate_once(messages: list[dict[str, str]]) -> str:
    payload = json.dumps(
        {
            "model": MODEL,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.75, "repeat_penalty": 1.25},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.time()
    with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as response:
        body = json.loads(response.read().decode("utf-8"))
    elapsed = time.time() - started
    reply = body["message"]["content"]
    print(f"[ollama] {elapsed:.1f}s model={MODEL}", file=sys.stderr)
    print(f"[reply] {reply}", file=sys.stderr)
    return reply


def call_ollama(messages: list[dict[str, str]]) -> str:
    """Generate a reply, retrying with a corrective nudge on language leaks.

    If the model still leaks after all attempts, strip the offending script
    rather than show broken text. Latin-word leaks are left as-is because
    deleting whole words would mangle the sentence more than it fixes.
    """
    reply = ""
    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        attempt_messages = messages if attempt == 1 else [*messages, RETRY_NUDGE]
        reply = _generate_once(attempt_messages)
        if not has_language_leak(reply):
            return sanitize_reply(reply) or FALLBACK_REPLY
        print(f"[warn] language leak, attempt {attempt}: {reply!r}", file=sys.stderr)
    cleaned = strip_foreign_script(reply) if FOREIGN_SCRIPT_RE.search(reply) else reply
    return sanitize_reply(cleaned) or FALLBACK_REPLY


# ---------------------------------------------------------------------------
# In-memory session store and rate limiter
# ---------------------------------------------------------------------------


@dataclass
class Session:
    turn: int = 0
    stage: int = 1
    history: list[dict[str, str]] = field(default_factory=list)
    last_seen: float = 0.0


class SessionStore:
    """Thread-safe session storage with TTL pruning and a hard size cap."""

    def __init__(
        self,
        ttl: int = SESSION_TTL_SECONDS,
        max_sessions: int = MAX_SESSIONS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl
        self._max_sessions = max(1, max_sessions)
        self._clock = clock
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)

    def _prune_locked(self) -> None:
        now = self._clock()
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if now - session.last_seen > self._ttl
        ]
        for session_id in expired:
            del self._sessions[session_id]

    def _make_room_locked(self) -> None:
        while len(self._sessions) >= self._max_sessions:
            oldest = min(self._sessions.items(), key=lambda item: item[1].last_seen)[0]
            del self._sessions[oldest]

    def get(self, session_id: str) -> Session:
        with self._lock:
            self._prune_locked()
            session = self._sessions.get(session_id)
            if session is None:
                self._make_room_locked()
                session = Session(last_seen=self._clock())
                self._sessions[session_id] = session
            else:
                session.last_seen = self._clock()
            return session

    def reset(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)


class RateLimiter:
    """Fixed-window-ish sliding limiter keyed by client IP."""

    def __init__(
        self,
        limit: int = RATE_LIMIT_REQUESTS,
        window: int = RATE_LIMIT_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = max(1, limit)
        self._window = max(1, window)
        self._clock = clock
        self._buckets: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            bucket = self._buckets.setdefault(key, deque())
            while bucket and now - bucket[0] > self._window:
                bucket.popleft()
            if len(bucket) >= self._limit:
                return False
            bucket.append(now)
            return True


SESSIONS = SessionStore()
RATE_LIMITER = RateLimiter()


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    server_version = "SupportRageSim/1.0"
    sys_version = ""

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[http] {self.address_string()} - {fmt % args}", file=sys.stderr)

    def _send_json(
        self,
        status: int,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for name, value in {**SECURITY_HEADERS, **(headers or {})}.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            self.close_connection = True
            raise RequestError(411, "Content-Length required")
        try:
            length = int(raw_length)
        except ValueError as exc:
            self.close_connection = True
            raise RequestError(400, "invalid Content-Length") from exc
        if length < 0:
            self.close_connection = True
            raise RequestError(400, "invalid Content-Length")
        if length > MAX_BODY_BYTES:
            self.close_connection = True
            raise RequestError(413, f"request body too large (max {MAX_BODY_BYTES} bytes)")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RequestError(400, "bad json") from exc
        if not isinstance(data, dict):
            raise RequestError(400, "json object expected")
        return data

    def _handle_error(self, exc: RequestError) -> None:
        self._send_json(exc.status, {"error": exc.message}, exc.headers)

    def send_error(
        self,
        code: int,
        message: str | None = None,
        explain: str | None = None,
    ) -> None:
        self.close_connection = True
        with contextlib.suppress(OSError):
            self._send_json(code, {"error": message or "request error"})

    def do_GET(self) -> None:
        try:
            path = self.path.split("?", 1)[0]
            if path not in ("/", "/index.html"):
                raise RequestError(404, "not found")
            html = (STATIC_DIR / "index.html").read_bytes()
            self._send_bytes(200, "text/html; charset=utf-8", html)
        except RequestError as exc:
            self._handle_error(exc)
        except OSError:
            print("[error] static file missing", file=sys.stderr)
            self._send_json(500, {"error": "internal server error"})
        except Exception:
            traceback.print_exc()
            self._send_json(500, {"error": "internal server error"})

    def do_POST(self) -> None:
        try:
            client_ip = self.client_address[0]
            if not RATE_LIMITER.allow(client_ip):
                self.close_connection = True
                raise RequestError(
                    429,
                    "too many requests",
                    {"Retry-After": str(RATE_LIMIT_WINDOW_SECONDS)},
                )

            path = self.path.split("?", 1)[0]
            if path not in ("/api/chat", "/api/reset"):
                self.close_connection = True
                raise RequestError(404, "not found")

            data = self._read_json()

            if path == "/api/reset":
                self._handle_reset(data)
            else:
                self._handle_chat(data)
        except RequestError as exc:
            self._handle_error(exc)
        except Exception:
            traceback.print_exc()
            self._send_json(500, {"error": "internal server error"})

    def _handle_reset(self, data: dict[str, Any]) -> None:
        session_id = normalize_session_id(data.get("session_id"))
        SESSIONS.reset(session_id)
        self._send_json(200, {"ok": True, "session_id": session_id})

    def _handle_chat(self, data: dict[str, Any]) -> None:
        session_id = normalize_session_id(data.get("session_id"))
        try:
            user_message = validate_message(data.get("message"))
        except InputError as exc:
            raise RequestError(400, str(exc)) from exc

        session = SESSIONS.get(session_id)
        turn = reserve_turn(session.turn)
        if turn is None:
            self._send_json(
                409,
                {
                    "error": "turn limit reached",
                    "ended": True,
                    "turn": session.turn,
                    "max_turns": MAX_TURNS,
                    "stage": stage_label(FINAL_STAGE),
                    "session_id": session_id,
                },
            )
            return

        stage = select_stage(turn, user_message, previous_stage=session.stage)
        ended = turn >= MAX_TURNS or stage >= FINAL_STAGE
        print(
            f"[user][{session_id}][turn {turn}][stage {stage}] {user_message}",
            file=sys.stderr,
        )

        messages = [
            {"role": "system", "content": persona.system_prompt(stage)},
            *session.history,
            {"role": "user", "content": user_message},
        ]

        try:
            reply = call_ollama(messages)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError) as exc:
            print(f"[error] ollama request failed: {exc!r}", file=sys.stderr)
            raise RequestError(
                502,
                (
                    "Ollama is unreachable. Make sure `ollama serve` is running "
                    f"and the model is pulled ({MODEL})."
                ),
            ) from exc

        session.turn = turn
        session.stage = stage
        session.history.append({"role": "user", "content": user_message})
        session.history.append({"role": "assistant", "content": reply})
        if len(session.history) > MAX_TURNS * 2:
            del session.history[: len(session.history) - MAX_TURNS * 2]

        self._send_json(
            200,
            {
                "reply": reply,
                "turn": turn,
                "max_turns": MAX_TURNS,
                "stage": stage_label(stage),
                "stage_number": stage,
                "ended": ended,
                "session_id": session_id,
            },
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    if HOST not in ("127.0.0.1", "localhost", "::1"):
        print(
            f"[warn] HOST={HOST}: this server is reachable from other machines. "
            "It has no authentication — bind to 127.0.0.1 unless you know why.",
            file=sys.stderr,
        )
    print(f"Model: {MODEL}", file=sys.stderr)
    print(f"Ollama: {OLLAMA_URL} (timeout {OLLAMA_TIMEOUT:g}s)", file=sys.stderr)
    print(f"Serving on http://{HOST}:{PORT} — press Ctrl+C to stop", file=sys.stderr)

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.", file=sys.stderr)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
