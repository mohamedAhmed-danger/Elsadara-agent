import logging
import threading
import time
from contextlib import contextmanager

from notification_center import send_production_alert

logger = logging.getLogger(__name__)

DEBOUNCE_SECONDS = 7


class UserLock:
    """Per-user lock so only one message per user is processed at a time.

    Locks are ref-counted and removed once nobody holds or waits on them,
    so the dict does not grow forever.
    """

    def __init__(self):
        self.locks = {}  # user_id -> [threading.Lock, ref_count]
        self.manager_lock = threading.Lock()

    def get_lock(self, user_id):
        with self.manager_lock:
            if user_id not in self.locks:
                self.locks[user_id] = [threading.Lock(), 0]
            self.locks[user_id][1] += 1
            lock = self.locks[user_id][0]
            logger.debug(
                "get_lock user=%s ref_count=%d total_users=%d",
                user_id, self.locks[user_id][1], len(self.locks),
            )

        if lock.locked():
            logger.info("user=%s is busy, this thread will wait", user_id)

        return lock

    def release_lock(self, user_id):
        with self.manager_lock:
            entry = self.locks.get(user_id)
            if entry is None:
                logger.error("release_lock called for user=%s but no lock found", user_id)
                return
            entry[1] -= 1
            logger.debug(
                "release_lock user=%s ref_count=%d total_users=%d",
                user_id, entry[1], len(self.locks),
            )
            if entry[1] <= 0:
                del self.locks[user_id]

    @contextmanager
    def lock_for_user(self, user_id):
        """Acquire the user's lock and always release it, even on exceptions."""
        lock = self.get_lock(user_id)
        lock.acquire()
        try:
            yield lock
        finally:
            try:
                lock.release()
            finally:
                self.release_lock(user_id)


def _merge_ocr_usage(usages: list) -> dict | None:
    usages = [u for u in usages if u]
    if not usages:
        return None
    merged = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for u in usages:
        merged["input_tokens"] += u.get("input_tokens", 0) or 0
        merged["output_tokens"] += u.get("output_tokens", 0) or 0
        merged["total_tokens"] += u.get("total_tokens", 0) or 0
    return merged


class MessageDebouncer:
    """Buffers a user's messages and flushes them together after a quiet period."""

    def __init__(self):
        self.buffers = {}  # user_id -> list of (received_at, text, ocr_usage)
        self.timers = {}   # user_id -> (token, threading.Timer)
        self.manager_lock = threading.Lock()

    def add_message(self, user_id, text, ocr_usage, on_flush_callback, received_at=None):
        received_at = received_at if received_at is not None else time.time()
        with self.manager_lock:
            self.buffers.setdefault(user_id, []).append((received_at, text, ocr_usage))
            logger.info(
                "buffered message user=%s buffer_size=%d",
                user_id, len(self.buffers[user_id]),
            )

            previous = self.timers.pop(user_id, None)
            if previous:
                previous[1].cancel()

            # Timer.cancel() cannot stop a timer that already fired and is waiting
            # on manager_lock. The token lets _flush recognise and skip such a
            # stale timer instead of flushing the newer message early.
            token = object()
            timer = threading.Timer(
                DEBOUNCE_SECONDS,
                self._flush,
                args=(user_id, on_flush_callback, token),
            )
            timer.daemon = True
            self.timers[user_id] = (token, timer)
            timer.start()

    def _flush(self, user_id, on_flush_callback, token):
        with self.manager_lock:
            current = self.timers.get(user_id)
            if current is None or current[0] is not token:
                return  # superseded by a newer message
            del self.timers[user_id]
            entries = self.buffers.pop(user_id, [])

        if not entries:
            return

        try:
            # Order by real arrival time, not by when OCR finished.
            entries.sort(key=lambda e: e[0])

            combined_text = "\n".join(t for _, t, _ in entries if t)
            combined_ocr_usage = _merge_ocr_usage([u for _, _, u in entries])

            logger.info(
                "flushing user=%s messages=%d chars=%d",
                user_id, len(entries), len(combined_text),
            )

            on_flush_callback(user_id, combined_text, combined_ocr_usage)
        except Exception as e:
            logger.exception("Exception inside on_flush callback for user=%s", user_id)
            send_production_alert(
                subject="Debouncer Flush Callback Exception",
                body_or_error=e,
                context={"user_id": user_id, "messages_count": len(entries)},
            )


user_lock_manager = UserLock()
message_debouncer = MessageDebouncer()