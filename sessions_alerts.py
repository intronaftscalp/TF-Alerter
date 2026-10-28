import datetime

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


class SessionMonitor(QObject):
    """Monitors UTC-based crypto market sessions and emits transition alerts."""

    alert_signal = pyqtSignal(dict)
    status_signal = pyqtSignal(dict)

    SESSIONS = [
        {
            "key": "asia",
            "name_ru": "Азия",
            "name_en": "Asia",
            "start_hour_utc": 0,
            "end_hour_utc": 8,
        },
        {
            "key": "europe",
            "name_ru": "Европа",
            "name_en": "Europe",
            "start_hour_utc": 8,
            "end_hour_utc": 13,
        },
        {
            "key": "america",
            "name_ru": "Америка",
            "name_en": "America",
            "start_hour_utc": 13,
            "end_hour_utc": 21,
        },
        {
            "key": "pacific",
            "name_ru": "Пасифик",
            "name_en": "Pacific",
            "start_hour_utc": 21,
            "end_hour_utc": 24,
        },
    ]

    def __init__(self, ui):
        super().__init__()
        self.ui = ui
        self.is_monitoring = False
        self.timer = QTimer()
        self.timer.timeout.connect(self.poll)
        self.timer.setInterval(1000)
        self._last_session_key = None
        self._last_warning_anchor = ""
        self._initialized = False

    def start(self):
        if self.is_monitoring:
            return
        self.is_monitoring = True
        self.timer.start()
        self.poll()

    def stop(self):
        self.is_monitoring = False
        self.timer.stop()
        self._last_session_key = None
        self._last_warning_anchor = ""
        self._initialized = False

    def poll(self):
        if not self.is_monitoring:
            return

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        status_payload = self._build_status_payload(now_utc)
        self.status_signal.emit(status_payload)

        local_now = now_utc.astimezone().replace(tzinfo=None)

        current_key = status_payload.get("current_session_key", "")
        if not current_key:
            return

        if not self._initialized:
            self._initialized = True
            self._last_session_key = current_key
            return

        if current_key != self._last_session_key:
            prev_key = self._last_session_key
            self._last_session_key = current_key

            payload = {
                "kind": "session_change",
                "previous_session_key": prev_key,
                "current_session_key": current_key,
                "previous_session_name_ru": self._session_name(prev_key, "ru"),
                "previous_session_name_en": self._session_name(prev_key, "en"),
                "current_session_name_ru": self._session_name(current_key, "ru"),
                "current_session_name_en": self._session_name(current_key, "en"),
                "utc_time": now_utc.strftime("%H:%M"),
                "local_time": local_now.strftime("%H:%M"),
                "tz_offset": status_payload.get("tz_offset", "+00:00"),
            }
            self.alert_signal.emit(payload)

        enabled = self._enabled_session_keys()
        next_key = str(status_payload.get("next_session_key", "") or "")
        next_start_ts = int(status_payload.get("next_session_start_ts", 0) or 0)
        seconds_to_next = int(status_payload.get("seconds_to_next", 9999) or 9999)
        warning_anchor = f"{next_key}:{next_start_ts}"

        if seconds_to_next > 20 and warning_anchor != self._last_warning_anchor:
            self._last_warning_anchor = ""

        if (
            0 < seconds_to_next <= 20
            and next_key in enabled
            and warning_anchor != self._last_warning_anchor
        ):
            self._last_warning_anchor = warning_anchor
            warning_payload = {
                "kind": "session_warning",
                "current_session_key": current_key,
                "current_session_name_ru": self._session_name(current_key, "ru"),
                "current_session_name_en": self._session_name(current_key, "en"),
                "next_session_key": next_key,
                "next_session_name_ru": status_payload.get("next_session_name_ru", ""),
                "next_session_name_en": status_payload.get("next_session_name_en", ""),
                "next_session_start_ts": next_start_ts,
                "seconds_to_next": seconds_to_next,
                "utc_time": now_utc.strftime("%H:%M:%S"),
                "local_time": local_now.strftime("%H:%M:%S"),
                "tz_offset": status_payload.get("tz_offset", "+00:00"),
            }
            self.alert_signal.emit(warning_payload)

    def emit_test_alert(self):
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        status_payload = self._build_status_payload(now_utc)
        current_key = status_payload.get("current_session_key", "")
        local_now = now_utc.astimezone().replace(tzinfo=None)

        payload = {
            "kind": "session_change",
            "previous_session_key": "test",
            "current_session_key": current_key,
            "previous_session_name_ru": "Тест",
            "previous_session_name_en": "Test",
            "current_session_name_ru": self._session_name(current_key, "ru"),
            "current_session_name_en": self._session_name(current_key, "en"),
            "utc_time": now_utc.strftime("%H:%M"),
            "local_time": local_now.strftime("%H:%M"),
            "tz_offset": status_payload.get("tz_offset", "+00:00"),
            "is_test": True,
        }
        self.alert_signal.emit(payload)

    def _enabled_session_keys(self):
        return {session.get("key", "") for session in self.SESSIONS if session.get("key")}

    def _build_status_payload(self, now_utc):
        local_dt = now_utc.astimezone()
        offset = local_dt.utcoffset() or datetime.timedelta(0)
        offset_minutes_total = int(offset.total_seconds() // 60)
        sign = "+" if offset_minutes_total >= 0 else "-"
        abs_minutes = abs(offset_minutes_total)
        offset_hours = abs_minutes // 60
        offset_minutes = abs_minutes % 60
        tz_offset = f"{sign}{offset_hours:02d}:{offset_minutes:02d}"

        current_session = self._session_by_hour(now_utc.hour)
        next_session, next_start = self._next_session(now_utc)

        return {
            "current_session_key": current_session.get("key", ""),
            "current_session_name_ru": current_session.get("name_ru", ""),
            "current_session_name_en": current_session.get("name_en", ""),
            "next_session_key": next_session.get("key", ""),
            "next_session_name_ru": next_session.get("name_ru", ""),
            "next_session_name_en": next_session.get("name_en", ""),
            "next_session_local": next_start.astimezone().strftime("%H:%M"),
            "next_session_utc": next_start.strftime("%H:%M"),
            "next_session_start_ts": int(next_start.timestamp()),
            "seconds_to_next": int((next_start - now_utc).total_seconds()),
            "tz_offset": tz_offset,
        }

    def _session_by_hour(self, hour_utc):
        for session in self.SESSIONS:
            start = int(session.get("start_hour_utc", 0))
            end = int(session.get("end_hour_utc", 0))
            if start <= hour_utc < end:
                return session
        return self.SESSIONS[0]

    def _next_session(self, now_utc):
        candidates = []
        for session in self.SESSIONS:
            start = int(session.get("start_hour_utc", 0))
            candidate_start = now_utc.replace(
                hour=start,
                minute=0,
                second=0,
                microsecond=0,
            )
            if candidate_start <= now_utc:
                candidate_start = candidate_start + datetime.timedelta(days=1)
            candidates.append((candidate_start, session))

        next_start, next_session = min(candidates, key=lambda item: item[0])
        return next_session, next_start

    def _session_name(self, key, lang):
        lang_key = "name_en" if str(lang).lower().startswith("en") else "name_ru"
        for session in self.SESSIONS:
            if session.get("key") == key:
                return session.get(lang_key, key or "")
        return key or ""