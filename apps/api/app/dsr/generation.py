"""Report generation requested from the web page, run in a background thread (one per person-day at a time).

The model takes about a minute, longer than a browser request should hang. Only one generation runs at a
time across the API process, so the GPU is never asked for two reports at once.
"""

import logging
import threading
from datetime import date

from app.db import SessionLocal
from app.dsr import service
from app.models import User

log = logging.getLogger("generation")
_lock = threading.Lock()
_gpu = threading.Lock()
_running: set[tuple[int, date]] = set()
_errors: dict[tuple[int, date], str] = {}
inline = False  # tests set this so the report is written before the request returns


def running(user_id: int, day: date) -> bool:
    with _lock:
        return (user_id, day) in _running


def error(user_id: int, day: date) -> str | None:
    with _lock:
        return _errors.get((user_id, day))


def start(user_id: int, day: date) -> bool:
    key = (user_id, day)
    with _lock:
        if key in _running:
            return True
        _running.add(key)
        _errors.pop(key, None)

    def work():
        try:
            with _gpu, SessionLocal() as db:
                service.generate(db, db.get(User, user_id), day)
        except Exception as e:  # shown to the person on the page, full trace in the API log
            log.exception("generating %s %s", user_id, day)
            with _lock:
                _errors[key] = f"The report could not be written: {e}"
        finally:
            with _lock:
                _running.discard(key)

    if inline:
        work()
        return False
    threading.Thread(target=work, name=f"dsr-{user_id}-{day}", daemon=True).start()
    return True
