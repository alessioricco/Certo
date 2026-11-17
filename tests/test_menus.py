"""The arrow-key menus' state and the Prompter's choice between menus and
numbered questions. The real menus are driven with keys sent through a
pipe and drawn to a dummy output: no terminal is needed."""

from __future__ import annotations

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from certo import menus
from certo.init_cmd import Cancelled, Prompter
from certo.menus import ChecklistState, Row


def _rows():
    return [
        Row("header", "On gpu-box"),
        Row("item", "qwen", "already set up", checked=True),
        Row("item", "gemma"),
        Row("header", "More"),
        Row("action", "DeepSeek models (asks for a key)"),
        Row("action", "Done"),
    ]


def test_the_cursor_skips_headers_and_stops_at_the_ends():
    state = ChecklistState(_rows())
    assert state.position == 1  # the first item, not the header

    state.move(-1)
    assert state.position == 1
    state.move(2)
    assert state.position == 4  # past the "More" header
    state.move(9)
    assert state.position == 5


def test_space_toggles_only_items_and_enter_says_what_to_do():
    state = ChecklistState(_rows())
    state.move(1)
    state.toggle()
    assert state.rows[2].checked is True
    assert state.enter() is None  # Enter on a model: the list is done

    state.move(1)
    state.toggle()  # an action has no check box
    assert state.rows[4].checked is False
    assert state.enter() == 4


def test_the_drawing_marks_the_cursor_and_the_choices():
    text = "".join(fragment for _style, fragment in ChecklistState(_rows()).lines())

    assert "▸ [x] qwen  already set up" in text
    assert "  [ ] gemma" in text
    assert "  DeepSeek models (asks for a key)" in text
    assert menus.HELP in text


def test_prompter_uses_menus_only_when_told_or_on_a_real_terminal(monkeypatch):
    monkeypatch.setattr(menus, "choose", lambda question, options, default=0: 1)

    assert Prompter(menus=True).choose("Pick", ["a", "b"]) == 1
    # Injected input (tests, scripts): numbered questions.
    assert Prompter(input_fn=lambda _p: "2").menus is False


def test_ctrl_c_in_a_menu_cancels(monkeypatch):
    def interrupted(*_a, **_k):
        raise KeyboardInterrupt

    monkeypatch.setattr(menus, "choose", interrupted)
    with pytest.raises(Cancelled):
        Prompter(menus=True).confirm("Sure?")


def test_no_menus_without_a_usable_terminal(monkeypatch):
    monkeypatch.setenv("TERM", "dumb")
    assert menus.available() is False


# --- the real menus, driven by keys ---------------------------------------------

UP, DOWN, ENTER, CTRL_C = "\x1b[A", "\x1b[B", "\r", "\x03"


def _press(keys: str, menu, *args, **kwargs):
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
        pipe.send_text(keys)
        return menu(*args, **kwargs)


def test_choose_returns_the_option_the_arrows_reach():
    assert _press(ENTER, menus.choose, "Pick", ["a", "b", "c"]) == 0
    assert _press(DOWN + DOWN + ENTER, menus.choose, "Pick", ["a", "b", "c"]) == 2
    assert _press(UP + ENTER, menus.choose, "Pick", ["a", "b", "c"], default=2) == 1


def test_confirm_starts_on_its_default():
    assert _press(ENTER, menus.confirm, "Sure?") is True
    assert _press(ENTER, menus.confirm, "Sure?", default=False) is False
    assert _press(DOWN + ENTER, menus.confirm, "Sure?") is False


def test_choose_ctrl_c_raises_keyboard_interrupt():
    with pytest.raises(KeyboardInterrupt):
        _press(CTRL_C, menus.choose, "Pick", ["a", "b"])


def test_checklist_space_selects_and_enter_on_a_model_is_done():
    state = ChecklistState(_rows())

    # Down to gemma, select it, deselect qwen, Enter on qwen.
    result = _press(DOWN + " " + UP + " " + ENTER, menus.checklist, "Models", state)

    assert result is None
    assert [row.checked for row in state.rows[1:3]] == [False, True]


def test_checklist_enter_on_an_action_returns_its_row_and_keeps_the_choice():
    state = ChecklistState(_rows())

    result = _press(DOWN + " " + DOWN + ENTER, menus.checklist, "Models", state)

    assert result == 4  # "DeepSeek models (asks for a key)", past the header
    assert state.rows[2].checked is True
    # Opened again after the action, the list keeps the cursor and the ticks.
    # Done is an action too; init_models ends the list on its label.
    assert _press(DOWN + ENTER, menus.checklist, "Models", state) == 5
    assert state.rows[2].checked is True


def test_checklist_ctrl_c_raises_keyboard_interrupt():
    with pytest.raises(KeyboardInterrupt):
        _press(" " + CTRL_C, menus.checklist, "Models", ChecklistState(_rows()))


# --- "?": a question for Certo's docs, then the menu again -------------------


@pytest.fixture
def asked(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(menus, "docs_question", lambda: calls.append("asked"))
    return calls


def test_question_mark_in_a_menu_asks_the_docs_then_shows_it_again(asked):
    assert _press("?" + DOWN + ENTER, menus.choose, "Pick", ["a", "b"]) == 1
    assert asked == ["asked"]


def test_question_mark_in_a_checklist_keeps_the_ticks(asked):
    state = ChecklistState(_rows())
    result = _press(DOWN + " " + "?" + ENTER, menus.checklist, "Models", state)
    assert result is None and asked == ["asked"]
    assert state.rows[2].checked is True


def test_docs_question_answers_what_was_typed(monkeypatch):
    answered: list[str] = []
    monkeypatch.setattr(menus, "answer_from_docs", answered.append)
    menus.docs_question(lambda _p: "  what is a rung ")
    menus.docs_question(lambda _p: "")  # Enter: back to the menu
    assert answered == ["what is a rung"]


def test_a_failing_docs_answer_prints_one_line(monkeypatch, capsys):
    def broken(argv):
        raise RuntimeError("no model yet")

    monkeypatch.setattr("certo.ask_cmd.ask_main", broken)
    monkeypatch.setattr("certo.ask_cmd._ask_config", lambda: None)
    menus.answer_from_docs("why")
    assert "certo ask failed: no model yet" in capsys.readouterr().err


def test_prompter_answers_question_marks_and_asks_again():
    answers = iter(["?what is a profile", "?", "y", "?why", "my-api"])
    docs: list[str] = []
    prompter = Prompter(input_fn=lambda _p: next(answers), menus=False, docs_fn=docs.append)

    # A bare ? is an answer (not y or n here, so the question comes back).
    assert prompter.confirm("Go on?") is True
    assert prompter.ask("Project name") == "my-api"
    assert docs == ["what is a profile", "why"]


def test_secrets_are_never_read_as_questions():
    docs: list[str] = []
    prompter = Prompter(secret_fn=lambda _p: "?not-a-question", menus=False, docs_fn=docs.append)
    assert prompter.secret("API key") == "?not-a-question"
    assert docs == []


def test_with_no_model_yet_the_docs_link_is_given(monkeypatch, capsys):
    from certo.config import ConfigError

    def no_model():
        raise ConfigError("CERTO_LLM_API_KEY is required")

    monkeypatch.setattr("certo.ask_cmd._ask_config", no_model)
    monkeypatch.setattr("certo.ask_cmd.ask_main", lambda argv: pytest.fail("asked"))
    menus.answer_from_docs("which provider")
    out = capsys.readouterr().out
    assert "certo ask needs a model, and none is set up yet" in out
    assert menus.DOCS_URL in out
