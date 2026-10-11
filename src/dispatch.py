"""The daily SMS job and the weekly snapshot, as plain functions. Modal only schedules them.

Daily, for each active farmer: assess (refit the model on all their data, decide), turn the
decision into facts, apply the throttling rules, have Haiku word it, send, log.

Throttling (agreed 2026-10-11, tuned for the demo):
  - at most one SMS per farmer per day;
  - advice at most every ADVICE_EVERY_DAYS days, so one change has time to show in the data;
  - a data nudge at most every NUDGE_EVERY_DAYS days;
  - advice worth less than MIN_GAIN_KES a day is not worth a farmer's attention: stay silent.
Only messages that were actually sent count. One farmer failing never stops the others.
"""
import json
import math
from datetime import date, datetime
from zoneinfo import ZoneInfo

from src import db
from src.llm import write_sms
from src.loader import assess_farmer
from src.messages import LANGUAGES, facts_from_decision
from src.sms import send_to_farmer

TZ = ZoneInfo("Africa/Nairobi")
ADVICE_EVERY_DAYS = 14
NUDGE_EVERY_DAYS = 7
MIN_GAIN_KES = 10


def today_in_kenya():
    return datetime.now(TZ).date()


def throttle(kind, recent, today):
    """(ok, reason). `recent` is [{"kind", "day"}] of messages already SENT to this farmer."""
    if any(r["day"] == today for r in recent):
        return False, "already sent a message today"
    gap = {"advice": ADVICE_EVERY_DAYS, "nudge": NUDGE_EVERY_DAYS}[kind]
    last = max((r["day"] for r in recent if r["kind"] == kind), default=None)
    if last is not None and (today - last).days < gap:
        return False, f"last {kind} was {(today - last).days} day(s) ago; one every {gap}"
    return True, None


def _recent(farmer_id):
    return [{"kind": r["kind"], "day": r["sent_at"].astimezone(TZ).date()} for r in db.recent_sms(farmer_id)]


def plan_for_farmer(farmer, today, *, recent=None, assessment=None):
    """What to do for one farmer today, without sending: {"action": "send"|"skip", ...}."""
    lang = farmer.get("language") or "en"
    if lang not in LANGUAGES:
        lang = "en"
    assessment = assessment or assess_farmer(farmer["id"], today)
    facts = facts_from_decision(assessment["decision"], lang)
    if facts is None:
        return {"action": "skip", "reason": "nothing to say"}
    if facts["kind"] == "advice" and (facts["gain"] or 0) < MIN_GAIN_KES:
        return {"action": "skip", "reason": f"gain under KES {MIN_GAIN_KES} a day"}
    ok, reason = throttle(facts["kind"], _recent(farmer["id"]) if recent is None else recent, today)
    if not ok:
        return {"action": "skip", "reason": reason}
    return {"action": "send", "facts": facts}


def run_daily(today=None, *, send=True, farmer_ids=None, llm_client=None, sms_client=None, sender_id=None):
    """Run the daily job. With send=False nothing is sent or logged (a dry run for checking).

    Returns one dict per farmer: farmer_id, action ("sent"/"failed"/"would_send"/"skip"/"error"),
    plus text, source (haiku/template), kind or reason.
    """
    today = today or today_in_kenya()
    report = []
    for farmer in db.list_farmers():
        if farmer_ids is not None and farmer["id"] not in farmer_ids:
            continue
        row = {"farmer_id": farmer["id"]}
        try:
            plan = plan_for_farmer(farmer, today)
            if plan["action"] == "skip":
                row.update(action="skip", reason=plan["reason"])
            else:
                facts = plan["facts"]
                out = write_sms(facts, client=llm_client)
                row.update(kind=facts["kind"], text=out["text"], source=out["source"], problems=out["problems"])
                if not send:
                    row["action"] = "would_send"
                else:
                    res = send_to_farmer(
                        farmer["id"], farmer["phone"], out["text"], client=sms_client, sender_id=sender_id, kind=facts["kind"],
                    )
                    row.update(action="sent" if res["ok"] else "failed", detail=res["detail"])
        except Exception as e:  # one farmer must not stop the rest
            row.update(action="error", reason=f"{type(e).__name__}: {e}")
        report.append(row)
    return report


def _jsonable(x):
    if isinstance(x, float) and not math.isfinite(x):
        return None
    if hasattr(x, "item"):  # numpy scalar
        return _jsonable(x.item())
    if isinstance(x, (date, datetime)):
        return x.isoformat()
    return x


def _clean(obj):
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    return _jsonable(obj)


def run_weekly_snapshot(today=None, farmer_ids=None):
    """Store what the model believes about each farm today. Returns the farmer ids saved."""
    today = today or today_in_kenya()
    saved = []
    for farmer in db.list_farmers():
        if farmer_ids is not None and farmer["id"] not in farmer_ids:
            continue
        try:
            a = assess_farmer(farmer["id"], today)
            db.save_snapshot(
                farmer["id"], today, a["usable_days"], a["decision"]["kind"],
                json.dumps(_clean(a["effects"])), json.dumps(_clean(a["recent_kg"])),
            )
            saved.append(farmer["id"])
        except Exception as e:
            print(f"snapshot failed for farmer {farmer['id']}: {type(e).__name__}: {e}")
    return saved


if __name__ == "__main__":
    import sys

    live = "--send" in sys.argv
    for r in run_daily(send=live):
        print(r)
    if not live:
        print("(dry run: nothing sent. Add --send to send for real.)")
