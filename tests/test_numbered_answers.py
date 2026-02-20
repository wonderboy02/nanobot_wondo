"""Tests for TelegramChannel._parse_numbered_answers."""

from nanobot.channels.telegram import TelegramChannel


def test_basic_numbered_answers():
    """Single-line answers with various separators."""
    mapping = {1: "q_abc", 2: "q_def", 3: "q_ghi"}
    text = "1. 응 시작했어\n2) 유튜브\n3: React"
    answers, unmatched = TelegramChannel._parse_numbered_answers(text, mapping)

    assert answers == {"q_abc": "응 시작했어", "q_def": "유튜브", "q_ghi": "React"}
    assert unmatched == []


def test_multiline_answer():
    """Answer spans multiple lines (continuation)."""
    mapping = {1: "q_abc", 2: "q_def"}
    text = "1 응 시작했어\nReact 16부터 공부중\n2 유튜브"
    answers, unmatched = TelegramChannel._parse_numbered_answers(text, mapping)

    assert answers == {"q_abc": "응 시작했어\nReact 16부터 공부중", "q_def": "유튜브"}
    assert unmatched == []


def test_continuation_after_last_answer():
    """Non-numbered line after a numbered answer is continuation of that answer."""
    mapping = {1: "q_abc", 2: "q_def"}
    text = "1 응 시작했어\nReact 16부터 공부중\n2 유튜브\n나머지는 모르겠어"
    answers, unmatched = TelegramChannel._parse_numbered_answers(text, mapping)

    assert answers == {
        "q_abc": "응 시작했어\nReact 16부터 공부중",
        "q_def": "유튜브\n나머지는 모르겠어",
    }
    assert unmatched == []


def test_unmatched_lines_before_any_number():
    """Lines before any numbered answer go to unmatched."""
    mapping = {1: "q_abc"}
    text = "잡담\n1. 답변"
    answers, unmatched = TelegramChannel._parse_numbered_answers(text, mapping)

    assert answers == {"q_abc": "답변"}
    assert unmatched == ["잡담"]


def test_number_not_in_mapping():
    """Number exists but not in mapping → goes to unmatched."""
    mapping = {1: "q_abc"}
    text = "1. 답변1\n5. 이건 매핑 없음"
    answers, unmatched = TelegramChannel._parse_numbered_answers(text, mapping)

    assert answers == {"q_abc": "답변1"}
    assert unmatched == ["5. 이건 매핑 없음"]


def test_empty_text():
    """Empty input returns empty results."""
    mapping = {1: "q_abc"}
    answers, unmatched = TelegramChannel._parse_numbered_answers("", mapping)
    assert answers == {}
    assert unmatched == []


def test_no_numbered_lines():
    """No numbered lines → everything unmatched."""
    mapping = {1: "q_abc"}
    text = "그냥 일반 메시지\n아무거나"
    answers, unmatched = TelegramChannel._parse_numbered_answers(text, mapping)

    assert answers == {}
    assert unmatched == ["그냥 일반 메시지", "아무거나"]


def test_only_spaces_between():
    """Blank lines are skipped."""
    mapping = {1: "q_abc", 2: "q_def"}
    text = "1. 답변1\n\n\n2. 답변2"
    answers, unmatched = TelegramChannel._parse_numbered_answers(text, mapping)

    assert answers == {"q_abc": "답변1", "q_def": "답변2"}
    assert unmatched == []


def test_continuation_after_unmapped_number():
    """After an unmapped number, continuation lines go to unmatched."""
    mapping = {1: "q_abc"}
    text = "1. 답변\n3. 없는 번호\n이건 continuation인데 last_qid는 None"
    answers, unmatched = TelegramChannel._parse_numbered_answers(text, mapping)

    assert answers == {"q_abc": "답변"}
    assert "3. 없는 번호" in unmatched
    assert "이건 continuation인데 last_qid는 None" in unmatched
