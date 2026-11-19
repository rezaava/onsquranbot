"""Simple user/usage stats stored in a JSON file."""
import csv
import io
import json
import os
import time
from collections import Counter
from datetime import datetime, timezone

STATE_DIR = os.environ.get("STATE_DIR", "data")
PATH = os.path.join(STATE_DIR, "stats.json")
_d = {"users": {}, "daily": {}, "events": {}}
_dirty, _last_save = False, 0.0


def load():
    global _d
    try:
        with open(PATH, encoding="utf8") as f:
            _d = json.load(f)
    except Exception:
        pass
    for k in ("users", "daily", "events"):
        _d.setdefault(k, {})


def save(force=False):
    global _dirty, _last_save
    if not _dirty or (not force and time.time() - _last_save < 30):
        return
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf8") as f:
        json.dump(_d, f, ensure_ascii=False)
    os.replace(tmp, PATH)
    _dirty, _last_save = False, time.time()


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def record(user, event):
    global _dirty
    if user is None or user.is_bot:
        return
    now, uid = int(time.time()), str(user.id)
    u = _d["users"].get(uid)
    if not u:
        u = _d["users"][uid] = {"first": now, "n": 0}
    u.update(name=user.full_name or "", username=user.username or "", last=now)
    u["n"] += 1
    day = _d["daily"].setdefault(_today(), {"users": [], "n": 0})
    day["n"] += 1
    if uid not in day["users"]:
        day["users"].append(uid)
    _d["events"][event] = _d["events"].get(event, 0) + 1
    _dirty = True
    save()


def summary():
    now, users = time.time(), _d["users"]
    day = _d["daily"].get(_today(), {"users": [], "n": 0})
    last7 = sorted(_d["daily"])[-7:]
    top = Counter(_d["events"]).most_common(8)
    return {
        "total": len(users),
        "new24": sum(1 for u in users.values() if now - u["first"] < 86400),
        "active24": sum(1 for u in users.values() if now - u["last"] < 86400),
        "active7d": sum(1 for u in users.values() if now - u["last"] < 7 * 86400),
        "today_n": day["n"],
        "total_n": sum(u["n"] for u in users.values()),
        "week": [(d, len(_d["daily"][d]["users"]), _d["daily"][d]["n"]) for d in last7],
        "top": top,
    }


def users_list():
    return sorted(_d["users"].items(), key=lambda kv: kv[1]["last"], reverse=True)


def users_csv():
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["id", "name", "username", "first_seen", "last_seen", "requests"])
    ts = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M")
    for uid, u in users_list():
        w.writerow([uid, u["name"], u["username"], ts(u["first"]), ts(u["last"]), u["n"]])
    return ("\ufeff" + out.getvalue()).encode("utf8")
