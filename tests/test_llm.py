"""Haiku wording: faithful rewordings pass, anything else falls back to the template. Fake client, no network."""
from types import SimpleNamespace

from src import llm
from src.messages import check_message, facts_from_decision, template_message

DECISION = {"kind": "advice", "nudges": [], "feeds": [], "advice": {
    "feed": "dairy meal", "verdict": "increase", "step_kg": 0.4, "step_kg_used": 0.4, "step_units": None,
    "unit": "bag", "gain_per_day_at_least": 15.0, "recent_kg": 4.0}}
FACTS = facts_from_decision(DECISION)


class FakeClient:
    def __init__(self, text=None, error=None):
        self.text, self.error, self.calls = text, error, []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.text)])


def test_a_faithful_rewording_is_used():
    text = "Milk Tracker: your records say 0.4 kg more dairy meal a day (10% more) pays. Likely at least KES 15 a day. Keep logging."
    assert check_message(text, FACTS) == []
    out = llm.write_sms(FACTS, client=FakeClient(text))
    assert out["source"] == "haiku" and out["text"] == text and out["problems"] == []


def test_the_prompt_shows_the_template_and_sets_the_model(monkeypatch):
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    c = FakeClient(template_message(FACTS))
    llm.write_sms(FACTS, client=c)
    call = c.calls[0]
    assert template_message(FACTS) in call["messages"][0]["content"] and call["model"] == llm.DEFAULT_MODEL
    assert call["max_tokens"] == llm.MAX_TOKENS


def test_rewordings_that_change_the_facts_fall_back_to_the_template():
    bad = {
        "a changed number": "Milk Tracker: add 0.8 kg more dairy meal a day (10% more). At least KES 15 a day.",
        "the opposite direction": "Milk Tracker: use 0.4 kg less dairy meal a day (10% less). At least KES 15 a day.",
        "an invented promise": "Milk Tracker: 0.4 kg more dairy meal (10%), guaranteed KES 15 a day.",
        "a link": "Milk Tracker: 0.4 kg more dairy meal (10%), KES 15 a day. See www.example.com",
        "no app name": "Add 0.4 kg more dairy meal a day (10% more), at least KES 15 a day.",
        "a number word": "Milk Tracker: add 0.4 kg more dairy meal a day (10% more), at least KES 15, maybe double.",
        "an emoji": "Milk Tracker: 0.4 kg more dairy meal (10%), at least KES 15 \U0001F42E",
        "no feed name": "Milk Tracker: add 0.4 kg more a day (10% more), at least KES 15 a day.",
    }
    for why, text in bad.items():
        out = llm.write_sms(FACTS, client=FakeClient(text))
        assert out["source"] == "template" and out["text"] == template_message(FACTS), why
        assert out["problems"] and out["rejected"] == text, why


def test_an_api_error_falls_back_to_the_template():
    out = llm.write_sms(FACTS, client=FakeClient(error=TimeoutError("slow")))
    assert out["source"] == "template" and out["problems"] == ["api error: TimeoutError"]


def test_no_api_key_means_the_template(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = llm.write_sms(FACTS)
    assert out["source"] == "template" and out["text"] == template_message(FACTS)


def test_the_model_can_be_overridden(monkeypatch):
    monkeypatch.setenv("CLAUDE_MODEL", "some-other-model")
    c = FakeClient(template_message(FACTS))
    llm.write_sms(FACTS, client=c)
    assert c.calls[0]["model"] == "some-other-model"
