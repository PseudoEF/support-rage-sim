"""Unit tests for the pure helpers in prototype/server.py.

These tests never touch Ollama and never start the HTTP server.
"""

import pytest
from prototype import server


def test_base_stage_progression_by_turn():
    stages = [server.base_stage_for_turn(turn) for turn in range(1, 12)]
    assert stages == [1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6]
    assert server.base_stage_for_turn(12) == server.FINAL_STAGE
    assert server.base_stage_for_turn(99) == server.FINAL_STAGE
    assert server.base_stage_for_turn(0) == 1


def test_select_stage_is_monotonic_and_capped_by_turn_limit():
    stage = 1
    for turn in range(1, 12):
        stage = server.select_stage(turn, "спокойное сообщение", previous_stage=stage)
        assert 1 <= stage <= server.STAGE_COUNT
        assert stage >= server.base_stage_for_turn(turn)
    assert server.select_stage(12, "спокойное сообщение", previous_stage=stage) == (
        server.FINAL_STAGE
    )


def test_keyword_detection():
    legal = server.detect_keywords("Я иду в суд и жалуюсь в Роспотребнадзор")
    assert "legal" in legal

    money = server.detect_keywords("Верните деньги за 5 дней простоя")
    assert "money" in money
    assert "outage" in money

    assert server.detect_keywords("Добрый день") == []
    assert server.detect_keywords("") == []


def test_aggression_detection():
    assert server.detect_aggression("Добрый день, интернет не работает") == 0
    assert server.detect_aggression("ВЕРНИТЕ ДЕНЬГИ СРОЧНО!!!") >= 2
    assert server.detect_aggression("вы уроды, я иду в суд") >= 2
    assert server.detect_aggression("Всё нормально") == 0


def test_aggression_and_keywords_accelerate_stage():
    calm = server.select_stage(1, "Добрый день, нет интернета", previous_stage=1)
    angry = server.select_stage(
        1,
        "Вы уроды, верните деньги, я иду в суд!!!",
        previous_stage=1,
    )
    assert calm == 1
    assert angry >= 3
    assert server.stage_label(angry) in {
        "раздражается",
        "трещит по швам",
        "на грани",
    }


def test_language_leak_detection_and_cleanup():
    assert server.has_language_leak("Привет 你好")
    assert server.has_language_leak("Please restart your router now")
    assert not server.has_language_leak("Проверьте Wi-Fi и IP-адрес")
    assert not server.has_language_leak("Обычный русский текст")

    assert server.strip_foreign_script("Привет 你好 мир") == "Привет мир"
    assert server.strip_foreign_script("Нет утечек") == "Нет утечек"


def test_call_ollama_retries_a_language_leak(monkeypatch):
    responses = iter(["Hello there friend", "Проверьте кабель и роутер."])
    calls = []

    def fake_generate(messages):
        calls.append(messages)
        return next(responses)

    monkeypatch.setattr(server, "_generate_once", fake_generate)
    reply = server.call_ollama([{"role": "user", "content": "test"}])

    assert reply == "Проверьте кабель и роутер."
    assert len(calls) == 2
    assert calls[1][-1] == server.RETRY_NUDGE


def test_call_ollama_cleans_a_persistent_leak(monkeypatch):
    responses = iter(["Ответ 你好", "Ещё 你好", "Снова 你好"])
    monkeypatch.setattr(server, "_generate_once", lambda messages: next(responses))

    assert server.call_ollama([]) == "Снова"


def test_reply_sanitization():
    assert server.sanitize_reply("  Привет\x00\n\n\n\nмир  ") == "Привет\n\nмир"
    assert server.sanitize_reply(None) == ""
    assert server.sanitize_reply("") == ""
    long_reply = server.sanitize_reply("а" * 5000)
    assert len(long_reply) <= server.MAX_REPLY_CHARS + 1
    assert long_reply.endswith("…")


def test_message_length_cap_and_sanitization():
    assert server.validate_message("а" * server.MAX_MESSAGE_CHARS) == (
        "а" * server.MAX_MESSAGE_CHARS
    )
    with pytest.raises(server.InputError):
        server.validate_message("а" * (server.MAX_MESSAGE_CHARS + 1))
    with pytest.raises(server.InputError):
        server.validate_message("   ")
    with pytest.raises(server.InputError):
        server.validate_message(None)

    assert server.validate_message("  привет\x00  мир  ") == "привет мир"


def test_session_turn_cap():
    turn = 0
    for expected in range(1, server.MAX_TURNS + 1):
        turn = server.reserve_turn(turn)
        assert turn == expected
    assert server.reserve_turn(turn) is None


def test_rate_limiter_per_key():
    now = [0.0]

    def clock():
        return now[0]

    limiter = server.RateLimiter(limit=2, window=10, clock=clock)
    assert limiter.allow("a")
    assert limiter.allow("a")
    assert not limiter.allow("a")
    assert limiter.allow("b")

    now[0] = 11.0
    assert limiter.allow("a")


def test_session_store_ttl_and_size_cap():
    now = [0.0]

    def clock():
        return now[0]

    store = server.SessionStore(ttl=10, max_sessions=2, clock=clock)

    session = store.get("a")
    session.turn = 5
    now[0] = 1.0
    assert len(store) == 1

    now[0] = 11.0
    fresh = store.get("a")
    assert fresh.turn == 0
    assert len(store) == 1

    store.get("b")
    now[0] = 12.0
    store.get("c")
    assert len(store) <= 2

    store.reset("c")
    assert len(store) == 1
