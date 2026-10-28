import datetime
import re
import threading
import time
from html import unescape

import requests
from PyQt6.QtCore import QObject, QTimer, pyqtSignal


class ListingMonitor(QObject):
    """Monitor for exchange listing announcements (no API key)."""

    listing_signal = pyqtSignal(dict)
    status_signal = pyqtSignal(dict)

    EXCHANGES = {
        "binance": {"name": "Binance", "supported": True},
        "bybit": {"name": "Bybit", "supported": True},
        "okx": {"name": "OKX", "supported": True},
        "gate": {"name": "Gate", "supported": True},
        "bitget": {"name": "Bitget", "supported": True},
    }

    BINANCE_LIST_ENDPOINT = (
        "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
    )
    BINANCE_DETAIL_ENDPOINT = (
        "https://www.binance.com/bapi/composite/v1/public/cms/article/detail/query"
    )
    BYBIT_LIST_ENDPOINT = "https://announcements.bybit.com/en-US/?category=new_crypto"
    BYBIT_ANNOUNCE_API_ENDPOINT = "https://api.bybit.com/v5/announcements/index"
    OKX_LIST_ENDPOINT = "https://www.okx.com/support/hc/en-us/sections/360000030652"
    GATE_SPOT_LIST_ENDPOINT = "https://www.gate.com/announcements/newspotlistings"
    GATE_FUTURES_LIST_ENDPOINT = "https://www.gate.com/announcements/newfutureslistings"
    BITGET_LIST_ENDPOINT = "https://www.bitget.com/support/categories/11865590960081"
    TELEGRAM_LISTING_FEEDS = {
        "metascalp": "https://t.me/s/metascalp_announcements_ru",
        "wintrading": "https://t.me/s/wintrading_listings",
        "vataga_bot": "https://t.me/s/vataga_listings_bot",
        "vataga_channel": "https://t.me/s/vataga_listings",
    }

    def __init__(self, ui):
        super().__init__()
        self.ui = ui
        self.is_monitoring = False
        self.monitor_thread = None
        self.timer = QTimer()
        self.timer.timeout.connect(self.poll)
        self.timer.setInterval(30000)
        self.detail_cache = {}
        self.exchange_status = {}
        self._seen_entries = set()
        self._exchange_backoff_until = {}
        self._listed_symbols_cache = {}
        self._listed_symbols_cache_ts = {}
        self._max_listing_future_days = 45

    def start(self):
        if self.is_monitoring:
            return
        self.is_monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        self.timer.start()
        # Первый poll сразу при старте
        QTimer.singleShot(2000, self.poll)

    def clear_cache(self):
        self._seen_entries = set()
        self.detail_cache = {}

    def stop(self):
        self.is_monitoring = False
        self.timer.stop()
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2)

    def _monitor_loop(self):
        while self.is_monitoring:
            try:
                time.sleep(1)
            except Exception:
                pass

    def poll(self):
        """Normal polling for new listings - запускает опрос в фоновом потоке."""
        if not self.is_monitoring:
            return
        thread = threading.Thread(target=self._poll_exchanges, daemon=True)
        thread.start()

    def load_recent_history(self):
        """Load listing history for the last 24 hours without emitting signals.
        Returns list of listing dictionaries found."""
        history_items = []
        exchanges = ["binance", "bybit", "okx", "gate", "bitget"]
        cutoff_time = int((time.time() - 24 * 3600) * 1000)  # 24 hours ago in ms

        for exchange in exchanges:
            try:
                items = self._fetch_exchange_history(exchange, cutoff_time)
                history_items.extend(items)
            except Exception:
                pass

        return history_items

    def _fetch_exchange_history(self, exchange, cutoff_time):
        """Fetch recent listings from an exchange without emitting signals."""
        items = []

        if exchange == "binance":
            items = self._fetch_binance_history(cutoff_time)
        elif exchange == "bybit":
            items = self._fetch_bybit_history(cutoff_time)
        elif exchange == "okx":
            items = self._fetch_okx_history(cutoff_time)
        elif exchange == "gate":
            items = self._fetch_gate_history(cutoff_time)
        elif exchange == "bitget":
            items = self._fetch_bitget_history(cutoff_time)

        return items

    def _fetch_binance_history(self, cutoff_time):
        """Fetch Binance listings from last 24 hours."""
        items = []
        params = {
            "type": 1,
            "catalogId": 48,
            "pageNo": 1,
            "pageSize": 20,
        }
        try:
            response = requests.get(
                self.BINANCE_LIST_ENDPOINT, params=params, timeout=10
            )
            if response.status_code != 200:
                return items
            payload = response.json() or {}
            data = payload.get("data", {})
            catalogs = data.get("catalogs", []) or []
            if not catalogs:
                return items
            articles = catalogs[0].get("articles", []) or []

            for article in articles:
                if not isinstance(article, dict):
                    continue
                release_date = int(article.get("releaseDate", 0) or 0)
                if release_date < cutoff_time:
                    continue

                title = str(article.get("title", "")).strip()
                if not self._is_listing_title(title):
                    continue

                listing_type = self._classify_listing_type(title)
                code = str(article.get("code", "")).strip()
                if not code:
                    continue

                symbol = self._extract_symbol(title)
                listing_time = self._extract_listing_time(code)

                if not listing_time or not symbol:
                    continue

                items.append(
                    {
                        "exchange": "binance",
                        "symbol": symbol,
                        "title": title,
                        "listing_time": listing_time,
                        "release_date": release_date,
                        "article_code": code,
                        "listing_type": listing_type,
                    }
                )
        except Exception:
            pass

        return items

    def _fetch_bybit_history(self, cutoff_time):
        """Fetch Bybit listings from last 24 hours."""
        items = []
        try:
            articles = self._fetch_bybit_articles_api(limit=80)
            if not articles:
                html = self._fetch_html(self.BYBIT_LIST_ENDPOINT)
                if not html:
                    return items
                articles = self._extract_bybit_articles(html)

            for article in articles:
                title = article.get("title", "")
                if not self._is_bybit_listing_title(title):
                    continue

                listing_type = self._classify_listing_type(title)
                symbol = self._extract_symbol(title)
                if not symbol:
                    continue

                url = article.get("url", "")
                listing_time = int(article.get("listing_time", 0) or 0)
                if listing_time <= 0:
                    listing_time = self._parse_bybit_time(
                        f"{title} {article.get('description', '')}"
                    )
                items.append(
                    {
                        "exchange": "bybit",
                        "symbol": symbol,
                        "title": title,
                        "listing_time": listing_time,
                        "release_date": int(
                            article.get("release_date", 0) or int(time.time() * 1000)
                        ),
                        "article_code": url,
                        "listing_type": listing_type,
                    }
                )
        except Exception:
            pass

        return items

    def _fetch_okx_history(self, cutoff_time):
        """Fetch OKX listings from last 24 hours."""
        items = []
        try:
            html = self._fetch_html(self.OKX_LIST_ENDPOINT)
            if not html:
                return items
            articles = self._extract_okx_articles(html)

            for article in articles:
                title = article.get("title", "")
                if not self._is_okx_listing_title(title):
                    continue

                listing_type = self._classify_listing_type(title)
                symbol = self._extract_symbol(title)
                if not symbol:
                    continue

                url = article.get("url", "")
                items.append(
                    {
                        "exchange": "okx",
                        "symbol": symbol,
                        "title": title,
                        "listing_time": 0,
                        "release_date": int(time.time() * 1000),
                        "article_code": url,
                        "listing_type": listing_type,
                    }
                )
        except Exception:
            pass

        return items

    def _fetch_gate_history(self, cutoff_time):
        """Fetch Gate listings from last 24 hours."""
        items = []
        for endpoint, default_type in [
            (self.GATE_SPOT_LIST_ENDPOINT, "spot"),
            (self.GATE_FUTURES_LIST_ENDPOINT, "futures"),
        ]:
            try:
                html = self._fetch_html(endpoint)
                if not html:
                    continue
                articles = self._extract_gate_articles(html)

                for article in articles:
                    title = article.get("title", "")
                    if not self._is_gate_listing_title(title):
                        continue

                    listing_type = self._classify_listing_type(title) or default_type
                    symbol = self._extract_symbol(title)
                    if not symbol:
                        continue

                    url = article.get("url", "")
                    items.append(
                        {
                            "exchange": "gate",
                            "symbol": symbol,
                            "title": title,
                            "listing_time": 0,
                            "release_date": int(time.time() * 1000),
                            "article_code": url,
                            "listing_type": listing_type,
                        }
                    )
            except Exception:
                pass

        return items

    def _fetch_bitget_history(self, cutoff_time):
        """Fetch Bitget listings from last 24 hours."""
        items = []
        try:
            html = self._fetch_html(self.BITGET_LIST_ENDPOINT)
            if not html:
                return items
            articles = self._extract_bitget_articles(html)

            for article in articles:
                title = article.get("title", "")
                if not self._is_bitget_listing_title(title):
                    continue

                listing_type = self._classify_listing_type(title)
                symbol = self._extract_symbol(title)
                if not symbol:
                    continue

                url = article.get("url", "")
                items.append(
                    {
                        "exchange": "bitget",
                        "symbol": symbol,
                        "title": title,
                        "listing_time": 0,
                        "release_date": int(time.time() * 1000),
                        "article_code": url,
                        "listing_type": listing_type,
                    }
                )
        except Exception:
            pass

        return items

    def _poll_exchanges(self):
        enabled_exchanges = self._get_enabled_exchanges()
        for exchange_key in enabled_exchanges:
            try:
                now_ts = time.time()
                backoff_until = float(self._exchange_backoff_until.get(exchange_key, 0))
                if backoff_until and now_ts < backoff_until:
                    self.exchange_status[exchange_key] = {
                        "fetched": 0,
                        "passed": 0,
                        "error": "rate limited",
                    }
                    continue
                if exchange_key == "binance":
                    fetched_count = self._poll_binance()
                    self.exchange_status[exchange_key] = {
                        "fetched": fetched_count,
                        "passed": fetched_count,
                        "error": None,
                    }
                elif exchange_key == "bybit":
                    fetched_count = self._poll_bybit()
                    self.exchange_status[exchange_key] = {
                        "fetched": fetched_count,
                        "passed": fetched_count,
                        "error": None,
                    }
                elif exchange_key == "gate":
                    fetched_count = self._poll_gate()
                    self.exchange_status[exchange_key] = {
                        "fetched": fetched_count,
                        "passed": fetched_count,
                        "error": None,
                    }
                elif exchange_key == "okx":
                    fetched_count = self._poll_okx()
                    self.exchange_status[exchange_key] = {
                        "fetched": fetched_count,
                        "passed": fetched_count,
                        "error": None,
                    }
                elif exchange_key == "bitget":
                    fetched_count = self._poll_bitget()
                    self.exchange_status[exchange_key] = {
                        "fetched": fetched_count,
                        "passed": fetched_count,
                        "error": None,
                    }
                else:
                    self.exchange_status[exchange_key] = {
                        "fetched": 0,
                        "passed": 0,
                        "error": None,
                    }
            except Exception as exc:
                error_text = str(exc).lower()
                if exchange_key == "binance" and (
                    "unsupported" in error_text
                    or "403" in error_text
                    or "451" in error_text
                    or "forbidden" in error_text
                    or "blocked" in error_text
                    or "unavailable for legal reasons" in error_text
                ):
                    self.exchange_status[exchange_key] = {
                        "fetched": 0,
                        "passed": 0,
                        "error": "unsupported",
                    }
                    continue
                if exchange_key == "bitget" and (
                    "403" in error_text
                    or "forbidden" in error_text
                    or "access denied" in error_text
                ):
                    self.exchange_status[exchange_key] = {
                        "fetched": 0,
                        "passed": 0,
                        "error": "unsupported",
                    }
                    continue
                if (
                    "429" in error_text
                    or "rate limit" in error_text
                    or "rate limited" in error_text
                ):
                    self._exchange_backoff_until[exchange_key] = time.time() + 300
                self.exchange_status[exchange_key] = {
                    "fetched": 0,
                    "passed": 0,
                    "error": str(exc)[:120],
                }

        try:
            self._poll_telegram_listing_feeds(enabled_exchanges)
        except Exception:
            pass

        self.status_signal.emit({"exchanges": dict(self.exchange_status)})

    def _poll_telegram_listing_feeds(self, enabled_exchanges):
        enabled_set = set(enabled_exchanges or [])
        if not enabled_set:
            return 0

        fetched = 0
        for source_key, url in self.TELEGRAM_LISTING_FEEDS.items():
            html = self._fetch_html(url)
            if not html:
                continue
            items = self._extract_telegram_feed_items(html)
            for item in items:
                exchange_key = str(item.get("exchange", "")).strip().lower()
                if exchange_key not in enabled_set:
                    continue

                title = str(item.get("title", "") or "")
                if not self._is_listing_type_allowed(
                    exchange_key,
                    title,
                    item.get("listing_type", ""),
                ):
                    continue

                symbol = self._extract_symbol(item.get("symbol", ""))
                if not symbol:
                    symbol = self._extract_symbol(title)
                if not symbol:
                    continue

                listing_time = int(item.get("listing_time", 0) or 0)
                release_date = int(item.get("release_date", 0) or 0)
                if listing_time <= 0:
                    continue
                if not self._is_listing_time_relevant(listing_time, release_date):
                    continue
                article_code = str(item.get("article_code", "") or "").strip()
                if not article_code:
                    article_code = (
                        f"tg:{source_key}:{exchange_key}:{symbol}:{listing_time}"
                    )

                # Deduplicate by exchange+symbol+time(rounded to minute)+type
                # Round to minute to handle slight timing differences between sources
                listing_type = str(item.get("listing_type", "") or "").strip().lower()
                if self._is_symbol_already_listed(exchange_key, symbol, listing_type):
                    continue
                time_minute = (listing_time // 60000) * 60000  # Round to minute
                entry_key = ("tg", exchange_key, symbol, time_minute, listing_type)
                if entry_key in self._seen_entries:
                    continue
                self._seen_entries.add(entry_key)

                self.listing_signal.emit(
                    {
                        "exchange": exchange_key,
                        "symbol": symbol,
                        "title": title,
                        "listing_time": listing_time,
                        "release_date": release_date,
                        "article_code": article_code,
                        "listing_type": self._classify_listing_type(title)
                        or str(item.get("listing_type", "") or ""),
                    }
                )
                fetched += 1
        return fetched

    def _extract_telegram_feed_items(self, html):
        if not html:
            return []

        blocks = self._extract_telegram_message_blocks(html)
        if not blocks:
            return []

        items = []

        pattern = re.compile(
            r"⏰\s*(?P<time>Available\s+for\s+trading|\d{1,2}:\d{1,2})"
            r"(?:\s*(?P<utc>\(UTC\)))?\s*"
            r"✅\s*`?(?P<symbol>[A-Z0-9_\-/]{2,40})`?\s*:\s*"
            r"(?P<exchange>[A-Za-z0-9]+)\s*\((?P<market>[^)]+)\)",
            re.IGNORECASE,
        )

        ru_pattern = re.compile(
            r"⏰\s*Доступно\s+для\s+торговли\s+через\s+(?P<mins>\d{1,4})\s+минут[а-я]*:\s*"
            r"(?P<exchange>[A-Za-z0-9]+)\s+"
            r"(?P<symbol>[A-Z0-9_\-/]{2,40})\s*"
            r"\[(?P<market>[SF])\]\s*"
            r"(?P<time>\d{1,2}:\d{1,2})",
            re.IGNORECASE,
        )

        exchange_first_pattern = re.compile(
            r"(?P<exchange>Binance|Bybit|OKX|Gate|GateIO|Bitget)\s+"
            r"(?P<symbol>[A-Z0-9_\-/]{2,40})\s*"
            r"\[(?P<market>[SF])\]"
            r"(?:\s*(?P<time>\d{1,2}:\d{1,2}))?",
            re.IGNORECASE,
        )

        time_then_exchange_pattern = re.compile(
            r"(?P<time>\d{1,2}(?::|\.|\s)\d{1,2})"
            r".{0,120}?"
            r"(?P<exchange>Binance|Bybit|OKX|Gate|GateIO|Bitget)\s+"
            r"(?P<symbol>[A-Z0-9_\-/]{2,40})\s*"
            r"\[(?P<market>[SF])\]",
            re.IGNORECASE | re.DOTALL,
        )

        def _append_item(
            symbol,
            exchange_raw,
            market_raw,
            time_part,
            base_local_dt,
            message_id="",
        ):
            symbol_value = str(symbol or "").strip().upper()
            if not symbol_value:
                return

            exchange_key = self._map_telegram_exchange(exchange_raw)
            if not exchange_key:
                return

            market_text = str(market_raw or "").strip().lower()
            listing_type = ""
            if "f" in market_text:
                listing_type = "futures"
            elif "s" in market_text:
                listing_type = "spot"

            base_dt = base_local_dt or datetime.datetime.now()
            listing_time = self._parse_telegram_time_to_ms(time_part, base_dt)
            release_date = int(base_dt.timestamp() * 1000)
            title = f"TG listing {symbol_value} {exchange_key} {listing_type}"
            article_code = (
                f"tg:{exchange_key}:{symbol_value}:{listing_time}:{listing_type}"
            )
            # Key for deduplication - round time to minute for cross-source matching
            time_minute = (listing_time // 60000) * 60000
            key = (exchange_key, symbol_value, time_minute, listing_type)
            items.append(
                {
                    "exchange": exchange_key,
                    "symbol": symbol_value,
                    "listing_time": listing_time,
                    "release_date": release_date,
                    "title": title,
                    "article_code": article_code,
                    "listing_type": listing_type,
                    "_key": key,
                }
            )

        for block_text, block_dt, block_msg_id in blocks:
            text = self._strip_tags(block_text)
            if not text:
                continue

            for match in pattern.finditer(text):
                time_part = match.group("time")
                if match.group("utc"):
                    time_part = f"{time_part} UTC"
                _append_item(
                    match.group("symbol"),
                    match.group("exchange"),
                    match.group("market"),
                    time_part,
                    block_dt,
                    block_msg_id,
                )

            for match in ru_pattern.finditer(text):
                _append_item(
                    match.group("symbol"),
                    match.group("exchange"),
                    match.group("market"),
                    match.group("time"),
                    block_dt,
                    block_msg_id,
                )

            for match in exchange_first_pattern.finditer(text):
                _append_item(
                    match.group("symbol"),
                    match.group("exchange"),
                    match.group("market"),
                    match.group("time") or "Available for trading",
                    block_dt,
                    block_msg_id,
                )

            for match in time_then_exchange_pattern.finditer(text):
                _append_item(
                    match.group("symbol"),
                    match.group("exchange"),
                    match.group("market"),
                    match.group("time"),
                    block_dt,
                    block_msg_id,
                )

        unique = {}
        for item in items:
            item_key = item.get("_key")
            existing = unique.get(item_key)
            if existing is None:
                unique[item_key] = item
                continue

            current_time = int(item.get("listing_time", 0) or 0)
            existing_time = int(existing.get("listing_time", 0) or 0)
            if current_time > 0 and (
                existing_time <= 0 or current_time < existing_time
            ):
                unique[item_key] = item
        cleaned = []
        for value in unique.values():
            value.pop("_key", None)
            cleaned.append(value)
        return cleaned

    def _extract_telegram_message_blocks(self, html):
        if not html:
            return []

        blocks = []
        block_pattern = re.compile(
            r'<div class="tgme_widget_message_wrap[\\s\\S]*?'
            r'<div class="tgme_widget_message_text[^\"]*"[^>]*>(?P<body>[\\s\\S]*?)</div>[\\s\\S]*?'
            r'<a class="tgme_widget_message_date" href="[^"]*/(?P<msg_id>\d+)"[\\s\\S]*?'
            r'<time datetime="(?P<dt>[^"]+)"',
            re.IGNORECASE,
        )

        for match in block_pattern.finditer(html):
            body_html = match.group("body")
            dt_raw = str(match.group("dt") or "").strip()
            msg_id = str(match.group("msg_id") or "").strip()
            if not body_html:
                continue

            local_dt = datetime.datetime.now()
            if dt_raw:
                try:
                    parsed = datetime.datetime.fromisoformat(
                        dt_raw.replace("Z", "+00:00")
                    )
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
                    local_dt = parsed.astimezone().replace(tzinfo=None)
                except Exception:
                    pass

            blocks.append((body_html, local_dt, msg_id))

        return blocks

    def _map_telegram_exchange(self, exchange_raw):
        mapping = {
            "binance": "binance",
            "bybit": "bybit",
            "okx": "okx",
            "gate": "gate",
            "gateio": "gate",
            "bitget": "bitget",
        }
        return mapping.get(str(exchange_raw or "").strip().lower(), "")

    def _parse_telegram_time_to_ms(self, time_text, now_local):
        raw = str(time_text or "").strip().lower()
        raw = re.sub(r"\s+", " ", raw)
        is_utc_time = "utc" in raw
        raw = raw.replace("(utc)", "").replace("utc", "").strip()
        if "available" in raw:
            return int(now_local.timestamp() * 1000)

        ru_minutes_match = re.search(r"через\s+(\d{1,4})\s+мин", raw)
        if ru_minutes_match:
            minutes = int(ru_minutes_match.group(1))
            dt = now_local + datetime.timedelta(minutes=minutes)
            return int(dt.timestamp() * 1000)

        en_minutes_match = re.search(r"in\s+(\d{1,4})\s+minutes", raw)
        if en_minutes_match:
            minutes = int(en_minutes_match.group(1))
            dt = now_local + datetime.timedelta(minutes=minutes)
            return int(dt.timestamp() * 1000)

        m = re.match(r"^(\d{1,2})(?::|\.|\s)(\d{1,2})$", raw)
        if not m:
            return int(now_local.timestamp() * 1000)

        hours = int(m.group(1))
        minutes = int(m.group(2))
        if hours < 0 or hours > 23 or minutes < 0 or minutes > 59:
            return int(now_local.timestamp() * 1000)

        if is_utc_time:
            local_tz = datetime.datetime.now().astimezone().tzinfo
            base_local = now_local
            if base_local.tzinfo is None:
                base_local = base_local.replace(tzinfo=local_tz)
            else:
                base_local = base_local.astimezone(local_tz)

            base_utc = base_local.astimezone(datetime.timezone.utc)
            dt_utc = base_utc.replace(
                hour=hours,
                minute=minutes,
                second=0,
                microsecond=0,
            )
            delta_sec = (dt_utc - base_utc).total_seconds()
            if delta_sec < -16 * 3600:
                dt_utc = dt_utc + datetime.timedelta(days=1)
            elif delta_sec > 16 * 3600:
                dt_utc = dt_utc - datetime.timedelta(days=1)
            return int(dt_utc.timestamp() * 1000)

        dt = now_local.replace(hour=hours, minute=minutes, second=0, microsecond=0)

        delta_sec = (dt - now_local).total_seconds()
        if delta_sec < -16 * 3600:
            dt = dt + datetime.timedelta(days=1)
        elif delta_sec > 16 * 3600:
            dt = dt - datetime.timedelta(days=1)

        return int(dt.timestamp() * 1000)

    def _get_enabled_exchanges(self):
        enabled = []
        exchange_checks = {
            "binance": getattr(self.ui, "listing_binance_check", None),
            "bybit": getattr(self.ui, "listing_bybit_check", None),
            "okx": getattr(self.ui, "listing_okx_check", None),
            "gate": getattr(self.ui, "listing_gate_check", None),
            "bitget": getattr(self.ui, "listing_bitget_check", None),
        }
        for key, widget in exchange_checks.items():
            if widget and widget.isChecked():
                enabled.append(key)
        return enabled

    def _is_exchange_enabled(self, exchange):
        """Check if a specific exchange is enabled."""
        exchange_checks = {
            "binance": getattr(self.ui, "listing_binance_check", None),
            "bybit": getattr(self.ui, "listing_bybit_check", None),
            "okx": getattr(self.ui, "listing_okx_check", None),
            "gate": getattr(self.ui, "listing_gate_check", None),
            "bitget": getattr(self.ui, "listing_bitget_check", None),
        }
        widget = exchange_checks.get(exchange)
        return bool(widget.isChecked()) if widget else False

    def _poll_binance(self):
        params = {
            "type": 1,
            "catalogId": 48,
            "pageNo": 1,
            "pageSize": 20,
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.binance.com/en/support/announcement/",
        }
        try:
            response = requests.get(
                self.BINANCE_LIST_ENDPOINT,
                params=params,
                headers=headers,
                timeout=10,
            )
        except Exception:
            return 0

        if response.status_code == 429:
            self._exchange_backoff_until["binance"] = time.time() + 300
            return 0
        if response.status_code in (403, 451):
            raise Exception("unsupported")
        if response.status_code >= 500:
            return 0
        if response.status_code >= 400:
            return 0

        try:
            payload = response.json() or {}
        except Exception:
            return 0

        data = payload.get("data", {})
        catalogs = data.get("catalogs", []) or []
        if not catalogs:
            return 0
        articles = catalogs[0].get("articles", []) or []
        fetched = 0
        for article in articles:
            try:
                if not isinstance(article, dict):
                    continue
                title = str(article.get("title", "")).strip()
                if not self._is_listing_title(title):
                    continue
                if not self._is_listing_type_allowed("binance", title):
                    continue
                listing_type = self._classify_listing_type(title)
                code = str(article.get("code", "")).strip()
                if not code:
                    continue
                symbols = self._extract_symbols_multi(title)
                if not symbols:
                    continue

                release_date = int(article.get("releaseDate", 0) or 0)
                if release_date > 0 and release_date < 10**11:
                    release_date *= 1000

                listing_time = self._extract_listing_time(code)
                # Fallback: for sudden already-open listings, release date is better than dropping the event.
                if listing_time <= 0 and release_date > 0:
                    listing_time = release_date

                if listing_time <= 0:
                    continue
                if not self._is_listing_time_relevant(listing_time, release_date):
                    continue

                for symbol in symbols:
                    if not symbol:
                        continue
                    entry_key = self._listing_seen_key(
                        "binance",
                        symbol,
                        listing_time,
                        listing_type,
                        source=code,
                    )
                    if entry_key in self._seen_entries:
                        continue
                    self._seen_entries.add(entry_key)
                    self.listing_signal.emit(
                        {
                            "exchange": "binance",
                            "symbol": symbol,
                            "title": title,
                            "listing_time": listing_time,
                            "release_date": release_date,
                            "article_code": code,
                            "listing_type": listing_type,
                        }
                    )
                    fetched += 1
            except Exception:
                # Keep Binance monitor alive even if one article has broken details.
                continue
        return fetched

    def _poll_bybit(self):
        articles = self._fetch_bybit_articles_api(limit=60)
        if not articles:
            html = self._fetch_html(self.BYBIT_LIST_ENDPOINT, silent=False)
            if not html:
                return 0
            articles = self._extract_bybit_articles(html)

        fetched = 0
        for article in articles:
            title = article.get("title", "")
            url = article.get("url", "")
            if not title or not url:
                continue
            if not self._is_bybit_listing_title(title):
                continue
            listing_type = self._classify_listing_type(title)
            if not self._is_listing_type_allowed("bybit", title, listing_type):
                continue
            symbols = self._extract_symbols_multi(title)
            if not symbols:
                continue
            listing_time = int(article.get("listing_time", 0) or 0)
            if listing_time <= 0:
                listing_time = self._extract_bybit_listing_time(url)
            if listing_time <= 0:
                listing_time = self._parse_bybit_time(
                    f"{title} {article.get('description', '')}"
                )
            release_date = int(article.get("release_date", 0) or 0)
            if not self._is_listing_time_relevant(listing_time, release_date):
                continue

            for symbol in symbols:
                if not symbol:
                    continue
                if self._is_symbol_already_listed("bybit", symbol, listing_type):
                    continue
                entry_key = self._listing_seen_key(
                    "bybit",
                    symbol,
                    listing_time,
                    listing_type,
                    source=url,
                )
                if entry_key in self._seen_entries:
                    continue
                self._seen_entries.add(entry_key)
                self.listing_signal.emit(
                    {
                        "exchange": "bybit",
                        "symbol": symbol,
                        "title": title,
                        "listing_time": listing_time,
                        "release_date": release_date,
                        "article_code": url,
                        "listing_type": listing_type,
                    }
                )
                fetched += 1
        return fetched

    def _fetch_bybit_articles_api(self, limit=60):
        results = []
        try:
            per_page = max(10, min(50, int(limit)))
            max_pages = 3
            seen_urls = set()

            for page in range(1, max_pages + 1):
                response = requests.get(
                    self.BYBIT_ANNOUNCE_API_ENDPOINT,
                    params={
                        "locale": "en-US",
                        "type": "new_crypto",
                        "page": page,
                        "limit": per_page,
                    },
                    timeout=12,
                )
                response.raise_for_status()
                payload = response.json() or {}
                data = (payload.get("result", {}) or {}).get("list", []) or []
                if not isinstance(data, list) or not data:
                    break

                for item in data:
                    if not isinstance(item, dict):
                        continue
                    title = str(item.get("title", "") or "").strip()
                    url = str(item.get("url", "") or "").strip()
                    if not title or not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    description = str(item.get("description", "") or "").strip()
                    release_date = int(
                        item.get("startDateTimestamp", 0)
                        or item.get("dateTimestamp", 0)
                        or item.get("publishTime", 0)
                        or 0
                    )
                    if release_date > 0 and release_date < 10**11:
                        release_date *= 1000
                    listing_time = self._parse_bybit_time(f"{title} {description}")
                    results.append(
                        {
                            "title": title,
                            "url": url,
                            "description": description,
                            "release_date": release_date,
                            "listing_time": listing_time,
                        }
                    )

                if len(results) >= int(limit):
                    break
        except Exception:
            return []

        return results

    def _poll_gate(self):
        urls = [
            (self.GATE_SPOT_LIST_ENDPOINT, "spot"),
            (self.GATE_FUTURES_LIST_ENDPOINT, "futures"),
        ]
        fetched = 0
        for list_url, default_type in urls:
            html = self._fetch_html(list_url, silent=False)
            if not html:
                continue
            articles = self._extract_gate_articles(html)
            for article in articles:
                title = article.get("title", "")
                url = article.get("url", "")
                if not title or not url:
                    continue
                if not self._is_gate_listing_title(title):
                    continue
                listing_type = self._classify_listing_type(title) or default_type
                if not self._is_listing_type_allowed("gate", title, listing_type):
                    continue
                symbol = self._extract_symbol(title)
                if not symbol:
                    continue
                listing_time = self._extract_gate_listing_time(url)
                if not self._is_listing_time_relevant(listing_time, 0):
                    continue
                entry_key = ("gate", url)
                if entry_key in self._seen_entries:
                    continue
                self._seen_entries.add(entry_key)
                self.listing_signal.emit(
                    {
                        "exchange": "gate",
                        "symbol": symbol,
                        "title": title,
                        "listing_time": listing_time,
                        "release_date": 0,
                        "article_code": url,
                        "listing_type": listing_type,
                    }
                )
                fetched += 1
        return fetched

    def _poll_okx(self):
        html = self._fetch_html(self.OKX_LIST_ENDPOINT, silent=False)
        if not html:
            return 0

        articles = self._extract_okx_articles(html)
        fetched = 0
        for article in articles:
            title = article.get("title", "")
            url = article.get("url", "")
            if not title or not url:
                continue
            if not self._is_okx_listing_title(title):
                continue
            if not self._is_listing_type_allowed("okx", title):
                continue
            listing_type = self._classify_listing_type(title)
            symbol_times = self._extract_okx_symbol_times(url)

            if symbol_times:
                for symbol, listing_time in symbol_times:
                    if self._is_symbol_already_listed("okx", symbol, listing_type):
                        continue
                    if not self._is_listing_time_relevant(listing_time, 0):
                        continue
                    entry_key = ("okx", url, symbol)
                    if entry_key in self._seen_entries:
                        continue
                    self._seen_entries.add(entry_key)
                    self.listing_signal.emit(
                        {
                            "exchange": "okx",
                            "symbol": symbol,
                            "title": title,
                            "listing_time": listing_time,
                            "release_date": 0,
                            "article_code": url,
                            "listing_type": listing_type,
                        }
                    )
                    fetched += 1
                continue

            symbol = self._extract_symbol(title)
            if not symbol:
                continue
            if self._is_symbol_already_listed("okx", symbol, listing_type):
                continue
            listing_time = self._extract_okx_listing_time(url)
            if not self._is_listing_time_relevant(listing_time, 0):
                continue
            entry_key = ("okx", url, symbol)
            if entry_key in self._seen_entries:
                continue
            self._seen_entries.add(entry_key)
            self.listing_signal.emit(
                {
                    "exchange": "okx",
                    "symbol": symbol,
                    "title": title,
                    "listing_time": listing_time,
                    "release_date": 0,
                    "article_code": url,
                    "listing_type": listing_type,
                }
            )
            fetched += 1
        return fetched

    def _is_symbol_already_listed(self, exchange_key, symbol, listing_type=""):
        exchange_key = str(exchange_key or "").strip().lower()
        symbol = str(symbol or "").strip().upper()
        if not exchange_key or not symbol:
            return False

        # Проверяем биржи, где часто встречаются повторные/устаревшие анонсы.
        if exchange_key not in ("okx", "bybit"):
            return False

        now_ts = time.time()
        cache_ttl = 600.0
        normalized_type = str(listing_type or "").strip().lower()
        if normalized_type not in ("spot", "futures"):
            normalized_type = "both"

        cache_key = (exchange_key, normalized_type)
        cached_symbols = self._listed_symbols_cache.get(cache_key)
        cached_at = float(self._listed_symbols_cache_ts.get(cache_key, 0.0) or 0.0)
        if cached_symbols is None or (now_ts - cached_at) > cache_ttl:
            if exchange_key == "okx":
                cached_symbols = self._fetch_okx_listed_symbols(normalized_type)
            else:
                cached_symbols = self._fetch_bybit_listed_symbols(normalized_type)
            self._listed_symbols_cache[cache_key] = cached_symbols
            self._listed_symbols_cache_ts[cache_key] = now_ts

        return symbol in cached_symbols

    def _fetch_bybit_listed_symbols(self, listing_type="both"):
        symbols = set()
        if listing_type == "spot":
            categories = ["spot"]
        elif listing_type == "futures":
            categories = ["linear"]
        else:
            categories = ["spot", "linear"]

        for category in categories:
            cursor = ""
            for _ in range(5):
                try:
                    params = {"category": category, "limit": 1000}
                    if cursor:
                        params["cursor"] = cursor
                    response = requests.get(
                        "https://api.bybit.com/v5/market/instruments-info",
                        params=params,
                        timeout=10,
                    )
                    response.raise_for_status()
                    payload = response.json() if response is not None else {}
                    result = payload.get("result", {}) if isinstance(payload, dict) else {}
                    rows = result.get("list", []) if isinstance(result, dict) else []

                    if isinstance(rows, list):
                        for row in rows:
                            full_symbol = str(row.get("symbol", "") or "").upper()
                            if not full_symbol.endswith("USDT"):
                                continue
                            base = full_symbol[: -len("USDT")].strip(" -_/")
                            if base:
                                symbols.add(base)

                    next_cursor = str(result.get("nextPageCursor", "") or "").strip()
                    if not next_cursor or next_cursor == cursor:
                        break
                    cursor = next_cursor
                except Exception:
                    break

        return symbols

    def _fetch_okx_listed_symbols(self, listing_type="both"):
        symbols = set()
        inst_types = []
        if listing_type == "spot":
            inst_types = ["SPOT"]
        elif listing_type == "futures":
            inst_types = ["SWAP"]
        else:
            inst_types = ["SPOT", "SWAP"]

        for inst_type in inst_types:
            try:
                response = requests.get(
                    "https://www.okx.com/api/v5/public/instruments",
                    params={"instType": inst_type},
                    timeout=10,
                )
                response.raise_for_status()
                payload = response.json()
                rows = payload.get("data", []) if isinstance(payload, dict) else []
                for row in rows:
                    inst_id = str(row.get("instId", "") or "").upper()
                    if not inst_id:
                        continue
                    if "-USDT" not in inst_id:
                        continue
                    base = inst_id.split("-USDT", 1)[0].strip(" -_")
                    if base:
                        symbols.add(base)
            except Exception:
                continue
        return symbols

    def _poll_bitget(self):
        html = self._fetch_html(self.BITGET_LIST_ENDPOINT, silent=False)
        if not html:
            return 0

        articles = self._extract_bitget_articles(html)
        fetched = 0
        for article in articles:
            title = article.get("title", "")
            url = article.get("url", "")
            if not title or not url:
                continue
            if not self._is_bitget_listing_title(title):
                continue
            if not self._is_listing_type_allowed("bitget", title):
                continue
            listing_type = self._classify_listing_type(title)
            symbol = self._extract_symbol(title)
            if not symbol:
                continue
            listing_time = self._extract_bitget_listing_time(url)
            if not self._is_listing_time_relevant(listing_time, 0):
                continue
            entry_key = ("bitget", url)
            if entry_key in self._seen_entries:
                continue
            self._seen_entries.add(entry_key)
            self.listing_signal.emit(
                {
                    "exchange": "bitget",
                    "symbol": symbol,
                    "title": title,
                    "listing_time": listing_time,
                    "release_date": 0,
                    "article_code": url,
                    "listing_type": listing_type,
                }
            )
            fetched += 1
        return fetched

    def _is_listing_title(self, title):
        lowered = title.lower()
        patterns = (
            "will list",
            "will launch",
            "will add",
            "pre-market trading",
        )
        return any(pat in lowered for pat in patterns)

    def _is_bybit_listing_title(self, title):
        lowered = re.sub(r"\s+", " ", str(title or "").lower()).strip()
        exclude = (
            "delist",
            "delisting",
            "suspend",
            "suspension",
            "maintenance",
            "notice",
            "update",
            "already listed",
            "trading pause",
            "convert",
            "conversion",
            "migrate",
            "migration",
            "rename",
            "rebrand",
            "token swap",
            "standard perpetual contract",
        )
        if any(word in lowered for word in exclude):
            return False
        patterns = (
            "will list",
            "to list",
            "listing",
            "spot trading",
            "pre-market perpetuals",
        )
        return any(pat in lowered for pat in patterns)

    def _is_gate_listing_title(self, title):
        lowered = title.lower()
        exclude = (
            "delist",
            "delisting",
            "suspend",
            "suspension",
            "maintenance",
            "already listed",
            "trading closure",
            "settlement",
            "copy trade",
            "airdrop",
            "vote",
            "kickstarter",
        )
        if any(word in lowered for word in exclude):
            return False
        patterns = (
            "list",
            "listing",
            "spot trading",
            "launch",
            "pre-market",
        )
        return any(pat in lowered for pat in patterns)

    def _is_okx_listing_title(self, title):
        lowered = title.lower()
        exclude = (
            "delist",
            "delisting",
            "suspend",
            "suspension",
            "maintenance",
            "already listed",
            "fee adjustment",
            "funding rate",
            "index component",
            "mark price",
            "trading data",
            "risk warning",
            "notice",
            "announcement of",
            "price limit",
            "position limit",
        )
        if any(word in lowered for word in exclude):
            return False
        patterns = (
            "to list",
            "will list",
            "list",
            "listing",
            "spot trading",
            "pre-market",
            "swap",
            "perpetual",
            "futures",
        )
        return any(pat in lowered for pat in patterns)

    def _is_bitget_listing_title(self, title):
        lowered = title.lower()
        exclude = (
            "delist",
            "delisting",
            "suspend",
            "suspension",
            "maintenance",
            "already listed",
            "copy trade",
            "airdrop",
            "notice",
            "update",
        )
        if any(word in lowered for word in exclude):
            return False
        patterns = (
            "to list",
            "will list",
            "list",
            "listing",
            "spot trading",
            "pre-market",
        )
        return any(pat in lowered for pat in patterns)

    def _extract_symbols_multi(self, title):
        """Extract multiple symbols from a title like 'CRWD, PYPL and PANW USDT-M Futures'."""
        # Pattern: "SYM1, SYM2 and SYM3 USDT" or "SYM1, SYM2, SYM3 USDT"
        multi = re.search(
            r"((?:[A-Z0-9]{2,15}\s*,\s*)*[A-Z0-9]{2,15}\s+and\s+[A-Z0-9]{2,15})\s+USDT",
            title,
            re.IGNORECASE,
        )
        if multi:
            text = multi.group(1)
            parts = re.split(r"\s*,\s*|\s+and\s+", text)
            symbols = [
                p.strip().upper()
                for p in parts
                if p.strip() and re.match(r"^[A-Z0-9]{2,15}$", p.strip(), re.IGNORECASE)
            ]
            if len(symbols) > 1:
                return symbols

        # Also try comma-only: "SYM1, SYM2, SYM3 USDT"
        multi2 = re.search(
            r"((?:[A-Z0-9]{2,15}\s*,\s*)+[A-Z0-9]{2,15})\s+USDT",
            title,
            re.IGNORECASE,
        )
        if multi2:
            text = multi2.group(1)
            parts = re.split(r"\s*,\s*", text)
            symbols = [
                p.strip().upper()
                for p in parts
                if p.strip() and re.match(r"^[A-Z0-9]{2,15}$", p.strip(), re.IGNORECASE)
            ]
            if len(symbols) > 1:
                return symbols

        # Fall back to single symbol
        single = self._extract_symbol(title)
        return [single] if single else []

    def _extract_symbol(self, title):
        """Извлекает символ монеты из заголовка."""
        # Сначала ищем паттерн XXXUSDT с опциональным SWAP/PERP/PERPETUAL
        match = re.search(
            r"\b([A-Z0-9]{2,15})[-_/ ]?USDT(?:[-_/ ]?(SWAP|PERP|PERPETUAL|M))?\b",
            title,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip().upper()

        # Ищем символ в скобках, содержащий USDT
        match = re.search(r"\(([^)]+)\)", title)
        if match:
            content = match.group(1).strip().upper()
            if "USDT" in content:
                clean = (
                    content.replace("/USDT", "")
                    .replace("-USDT", "")
                    .replace("USDT", "")
                    .strip()
                )
                if clean and 2 <= len(clean) <= 15 and re.match(r"^[A-Z0-9]+$", clean):
                    return clean

        # Фоллбэк: символ в скобках, 2-10 букв/цифр (Gate/OKX style: "List Espresso (ESP)")
        # Исключаем USDT-M, BTC, USDT и подобные
        exclude = {"USDT", "USDC", "BTC", "ETH", "USDT-M", "USD"}
        all_parens = re.findall(r"\(([A-Z0-9]{2,10})\)", title, re.IGNORECASE)
        for sym in all_parens:
            sym_upper = sym.strip().upper()
            if sym_upper not in exclude and not sym_upper.startswith("-"):
                return sym_upper

        # Фоллбэк: ищем UPPERCASE символ после ключевых слов list/launch(es)
        kw_match = re.search(r"(?:list|launch(?:es)?)\s+", title, re.IGNORECASE)
        if kw_match:
            rest = title[kw_match.end() :]
            sym_match = re.match(r"([A-Z][A-Z0-9]{1,9})\b", rest)
            if sym_match:
                sym = sym_match.group(1)
                if sym not in exclude:
                    return sym

        return ""

    def _listing_seen_key(self, exchange, symbol, listing_time, listing_type, source=""):
        time_minute = (int(listing_time or 0) // 60000) * 60000 if int(listing_time or 0) > 0 else 0
        return (
            str(exchange or "").strip().lower(),
            str(source or "").strip(),
            str(symbol or "").strip().upper(),
            time_minute,
            str(listing_type or "").strip().lower(),
        )

    def _is_listing_time_relevant(self, listing_time, release_date=0):
        try:
            ts = int(listing_time or 0)
        except Exception:
            ts = 0

        if ts <= 0:
            return True

        now_ms = int(time.time() * 1000)
        max_future_ms = int(self._max_listing_future_days * 24 * 60 * 60 * 1000)
        past_grace_ms = 30 * 60 * 1000

        if ts < now_ms - past_grace_ms:
            return False
        if ts > now_ms + max_future_ms:
            return False

        try:
            published_ms = int(release_date or 0)
        except Exception:
            published_ms = 0

        if published_ms > 0 and published_ms < 10**11:
            published_ms *= 1000

        if published_ms > 0 and ts + 10 * 60 * 1000 < published_ms:
            return False

        return True

    def _classify_listing_type(self, title):
        """Classify listing as spot, futures, or unknown based on title text."""
        title_lower = str(title or "").lower()
        if any(
            keyword in title_lower
            for keyword in [
                "futures",
                "perpetual",
                "swap",
                "contract",
                "perp",
                "usdt-m",
                "coin-m",
                "перпетуал",
                "фьючерс",
            ]
        ):
            return "futures"
        if any(
            keyword in title_lower
            for keyword in ["spot", "spot trading", "spot listing", "спот"]
        ):
            return "spot"
        return "spot"

    def _fetch_html(self, url, silent=True):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        last_error = None
        try:
            for _ in range(2):
                response = requests.get(url, headers=headers, timeout=12)
                if response.status_code == 429:
                    raise Exception("rate limited")
                response.raise_for_status()
                return response.text
        except Exception as exc:
            last_error = exc
        if not silent and last_error is not None:
            raise last_error
        return ""

    def _strip_tags(self, value):
        if not value:
            return ""
        text = re.sub(r"<[^>]+>", " ", value)
        text = unescape(text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _extract_bybit_articles(self, html):
        results = []
        pattern = re.compile(
            r'<a[^>]+href="(?P<href>/en/article/[^"]+?)"[^>]*>(?P<title>.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )
        for match in pattern.finditer(html):
            href = match.group("href")
            title = self._strip_tags(match.group("title"))
            if not href or not title:
                continue
            if "category=new_crypto" not in href:
                href = f"{href}?category=new_crypto"
            url = f"https://announcements.bybit.com{href}"
            results.append({"url": url, "title": title})
        return results

    def _extract_gate_articles(self, html):
        results = []
        pattern = re.compile(
            r'<a[^>]+href="(?P<href>/announcements/article/\d+)"[^>]*>(?P<title>.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )
        for match in pattern.finditer(html):
            href = match.group("href")
            title = self._strip_tags(match.group("title"))
            if not href or not title:
                continue
            url = f"https://www.gate.com{href}"
            results.append({"url": url, "title": title})
        return results

    def _extract_okx_articles(self, html):
        results = []
        pattern = re.compile(
            r'<a[^>]+href="(?P<href>/help/[^"]+)"[^>]*>(?P<title>.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )
        for match in pattern.finditer(html):
            href = match.group("href")
            title = self._strip_tags(match.group("title"))
            if not href or not title:
                continue
            title = title.split("Published on")[0].strip()
            url = f"https://www.okx.com{href}"
            results.append({"url": url, "title": title})
        return results

    def _extract_bitget_articles(self, html):
        results = []
        pattern = re.compile(
            r'<a[^>]+href="(?P<href>/support/articles/\d+)"[^>]*>(?P<title>.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )
        for match in pattern.finditer(html):
            href = match.group("href")
            title = self._strip_tags(match.group("title"))
            if not href or not title:
                continue
            url = f"https://www.bitget.com{href}"
            results.append({"url": url, "title": title})
        return results

    def _extract_listing_time(self, article_code):
        if article_code in self.detail_cache:
            return self.detail_cache[article_code]

        try:
            params = {"articleCode": article_code}
            response = requests.get(
                self.BINANCE_DETAIL_ENDPOINT, params=params, timeout=10
            )
            if response.status_code in (403, 451):
                return 0
            response.raise_for_status()
            payload = response.json() or {}
            data = payload.get("data", {})
            text = " ".join(
                [
                    str(data.get("textOnly", "")),
                    str(data.get("body", "")),
                    str(data.get("title", "")),
                ]
            )
            listing_time = self._parse_listing_time(text)
            if listing_time:
                self.detail_cache[article_code] = listing_time
            return listing_time
        except Exception:
            return 0

    def _extract_bybit_listing_time(self, url):
        if url in self.detail_cache:
            return self.detail_cache[url]
        html = self._fetch_html(url)
        if not html:
            return 0
        text = self._strip_tags(html)
        listing_time = self._parse_bybit_time(text)
        if listing_time:
            self.detail_cache[url] = listing_time
        return listing_time

    def _extract_gate_listing_time(self, url):
        if url in self.detail_cache:
            return self.detail_cache[url]
        html = self._fetch_html(url)
        if not html:
            return 0
        # Gate uses Next.js — extract article body from __NEXT_DATA__ JSON
        text = self._extract_nextdata_text(html, "detail", "desc")
        if not text:
            text = self._strip_tags(html)
        listing_time = self._parse_gate_time(text)
        if listing_time:
            self.detail_cache[url] = listing_time
        return listing_time

    def _extract_nextdata_text(self, html, *keys):
        """Extract text content from __NEXT_DATA__ JSON embedded in Next.js pages."""
        try:
            match = re.search(
                r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                html,
                re.DOTALL,
            )
            if not match:
                return ""
            import json

            data = json.loads(match.group(1))
            obj = data.get("props", {}).get("pageProps", {})
            for key in keys:
                if isinstance(obj, dict):
                    obj = obj.get(key, {})
                else:
                    return ""
            if isinstance(obj, str):
                text = re.sub(r"<[^>]+>", " ", obj)
                text = re.sub(r"\\s+", " ", text).strip()
                return text
        except Exception:
            pass
        return ""

    def _extract_okx_listing_time(self, url):
        if url in self.detail_cache:
            return self.detail_cache[url]
        html = self._fetch_html(url)
        if not html:
            return 0
        text = self._strip_tags(html)
        listing_time = self._parse_listing_time(text) or self._parse_okx_time(text)
        if listing_time:
            self.detail_cache[url] = listing_time
        return listing_time

    def _extract_okx_symbol_times(self, url):
        """Extract multiple symbol/time pairs from OKX article body.
        Example: "HOOD/USDT perpetual futures trading will open at 07:00 UTC on February 25, 2026".
        """
        html = self._fetch_html(url)
        if not html:
            return []

        text = self._strip_tags(html)
        results = []
        seen = set()

        patterns = [
            r"\b([A-Z0-9]{2,15})\s*/\s*USDT\b[^.\n]{0,180}?open at\s+(\d{1,2}:\d{2})\s*UTC\s*on\s*([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})",
            r"\b([A-Z0-9]{2,15})[-_/]USDT(?:[-_/]SWAP)?\b[^.\n]{0,180}?open at\s+(\d{1,2}:\d{2})\s*UTC\s*on\s*([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})",
            r"\b([A-Z0-9]{2,15})\s*/\s*USDT\b[^.\n]{0,180}?at\s+(\d{1,2}:\d{2})\s*UTC\s*on\s*([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})",
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                symbol_raw, time_part, date_part = match.groups()
                symbol = str(symbol_raw or "").strip().upper()
                ts = self._parse_utc_date_time(date_part, time_part)
                if not symbol or ts <= 0:
                    continue
                key = (symbol, ts)
                if key in seen:
                    continue
                seen.add(key)
                results.append((symbol, ts))

        return results

    def _parse_utc_date_time(self, date_part, time_part):
        for fmt in ("%b %d, %Y %H:%M", "%B %d, %Y %H:%M"):
            try:
                dt = datetime.datetime.strptime(f"{date_part} {time_part}", fmt)
                dt = dt.replace(tzinfo=datetime.timezone.utc)
                return int(dt.timestamp() * 1000)
            except Exception:
                continue
        return 0

    def _extract_bitget_listing_time(self, url):
        if url in self.detail_cache:
            return self.detail_cache[url]
        html = self._fetch_html(url)
        if not html:
            return 0
        text = self._strip_tags(html)
        listing_time = self._parse_listing_time(text) or self._parse_bitget_time(text)
        if listing_time:
            self.detail_cache[url] = listing_time
        return listing_time

    def _decode_json_escapes(self, text):
        """Decode common JSON unicode escapes in HTML text."""
        try:
            text = text.replace("\\u003c", "<")
            text = text.replace("\\u003e", ">")
            text = text.replace("\\u003C", "<")
            text = text.replace("\\u003E", ">")
            text = text.replace("\\u0026", "&")
            text = text.replace("\\u0027", "'")
            text = text.replace("\\u0022", '"')
            # Also handle without double backslash (\u003c as 6-char literal)
            text = text.replace("\u003c", "<")
            text = text.replace("\u003e", ">")
            text = text.replace("\u003c", "<")
            text = text.replace("\u003e", ">")
        except Exception:
            pass
        return text

    def _parse_listing_time(self, text):
        patterns = [
            r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s*\(UTC\)",
            r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s*UTC",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            date_part, time_part = match.groups()
            try:
                dt = datetime.datetime.strptime(
                    f"{date_part} {time_part}", "%Y-%m-%d %H:%M"
                )
                dt = dt.replace(tzinfo=datetime.timezone.utc)
                return int(dt.timestamp() * 1000)
            except Exception:
                continue
        return 0

    def _parse_bybit_time(self, text):
        patterns = [
            r"(\d{1,2}:\d{2})\s*UTC\s*on\s*([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})",
            r"([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}),?\s+(\d{1,2}:\d{2})\s*UTC",
            r"([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}),?\s+(\d{1,2}:\d{2}\s*[AP]M)\s*UTC",
            r"([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})\s+at\s+(\d{1,2}:\d{2}\s*[AP]M)\s*\(UTC\)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue
            date_part, time_part = match.groups()
            if ":" in date_part:
                date_part, time_part = time_part, date_part
            if (
                "AM" not in str(time_part).upper()
                and "PM" not in str(time_part).upper()
            ):
                parsed = self._parse_utc_date_time(date_part, time_part)
                if parsed:
                    return parsed
            time_part = time_part.replace(" ", "")
            for fmt in ("%b %d, %Y %I:%M%p", "%B %d, %Y %I:%M%p"):
                try:
                    dt = datetime.datetime.strptime(f"{date_part} {time_part}", fmt)
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                    return int(dt.timestamp() * 1000)
                except Exception:
                    continue
        return 0

    def _parse_gate_time(self, text):
        patterns = [
            r"Spot Trading Opens:\s*([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}),?\s+at\s+(\d{1,2}:\d{2})\s*\(UTC\)",
            r"Trading Starts?:\s*([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}),?\s+at\s+(\d{1,2}:\d{2})\s*\(UTC\)",
            r"([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}),?\s+at\s+(\d{1,2}:\d{2})\s*\(UTC\)",
            r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s*\(UTC\)",
            r"([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}),?\s+(\d{1,2}:\d{2})\s*\(UTC\)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue
            date_part, time_part = match.groups()
            if "-" in date_part:
                try:
                    dt = datetime.datetime.strptime(
                        f"{date_part} {time_part}", "%Y-%m-%d %H:%M"
                    )
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                    return int(dt.timestamp() * 1000)
                except Exception:
                    continue
            for fmt in ("%b %d, %Y %H:%M", "%B %d, %Y %H:%M"):
                try:
                    dt = datetime.datetime.strptime(f"{date_part} {time_part}", fmt)
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                    return int(dt.timestamp() * 1000)
                except Exception:
                    continue
        return 0

    def _parse_okx_time(self, text):
        patterns = [
            r"(\d{1,2}:\d{2})\s*UTC\s*on\s*([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})",
            r"(\d{1,2}:\d{2}\s*[AP]M)\s*UTC\s*on\s*([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})",
            r"([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})\s+at\s+(\d{1,2}:\d{2}\s*[AP]M)\s*\(?UTC\)?",
            r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s*\(?UTC\)?",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue
            part1, part2 = match.groups()
            if "-" in part1:
                try:
                    dt = datetime.datetime.strptime(
                        f"{part1} {part2}", "%Y-%m-%d %H:%M"
                    )
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                    return int(dt.timestamp() * 1000)
                except Exception:
                    continue
            if ":" in part1 and "AM" not in part1.upper() and "PM" not in part1.upper():
                parsed = self._parse_utc_date_time(part2, part1)
                if parsed:
                    return parsed
            time_part = part1 if ":" in part1 else part2
            date_part = part2 if ":" in part1 else part1
            time_part = time_part.replace(" ", "")
            for fmt in ("%b %d, %Y %I:%M%p", "%B %d, %Y %I:%M%p"):
                try:
                    dt = datetime.datetime.strptime(f"{date_part} {time_part}", fmt)
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                    return int(dt.timestamp() * 1000)
                except Exception:
                    continue
        return 0

    def _parse_bitget_time(self, text):
        patterns = [
            r"(\d{1,2}:\d{2})\s*UTC\s*on\s*([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})",
            r"(\d{1,2}:\d{2}\s*[AP]M)\s*UTC\s*on\s*([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})",
            r"([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})\s+at\s+(\d{1,2}:\d{2}\s*[AP]M)\s*\(?UTC\)?",
            r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s*\(?UTC\)?",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue
            part1, part2 = match.groups()
            if "-" in part1:
                try:
                    dt = datetime.datetime.strptime(
                        f"{part1} {part2}", "%Y-%m-%d %H:%M"
                    )
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                    return int(dt.timestamp() * 1000)
                except Exception:
                    continue
            if ":" in part1 and "AM" not in part1.upper() and "PM" not in part1.upper():
                parsed = self._parse_utc_date_time(part2, part1)
                if parsed:
                    return parsed
            time_part = part1 if ":" in part1 else part2
            date_part = part2 if ":" in part1 else part1
            time_part = time_part.replace(" ", "")
            for fmt in ("%b %d, %Y %I:%M%p", "%B %d, %Y %I:%M%p"):
                try:
                    dt = datetime.datetime.strptime(f"{date_part} {time_part}", fmt)
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                    return int(dt.timestamp() * 1000)
                except Exception:
                    continue
        return 0

    def _classify_listing_type(self, text):
        lowered = str(text or "").lower()
        futures_words = (
            "futures",
            "perpetual",
            "contract",
            "usdt-m",
            "swap",
            "-swap",
            "perp",
            "coin-m",
            "delivery",
        )
        spot_words = (
            "spot",
            "spot trading",
            "spot listing",
        )
        if any(word in lowered for word in futures_words):
            return "futures"
        if any(word in lowered for word in spot_words):
            return "spot"
        return "spot"

    def _is_listing_type_allowed(self, exchange_key, title, listing_type=""):
        exchange_key = str(exchange_key or "").strip().lower()
        spot_enabled = self._is_spot_enabled(exchange_key)
        futures_enabled = self._is_futures_enabled(exchange_key)
        if spot_enabled and futures_enabled:
            return True
        if not spot_enabled and not futures_enabled:
            return False

        if listing_type:
            normalized = str(listing_type).strip().lower()
            if normalized == "spot":
                return spot_enabled
            if normalized == "futures":
                return futures_enabled

        kind = self._classify_listing_type(title)
        if kind == "spot":
            return spot_enabled
        if kind == "futures":
            return futures_enabled
        return spot_enabled or futures_enabled

    def _is_spot_enabled(self, exchange_key):
        mapping = {
            "binance": getattr(self.ui, "listing_binance_spot_check", None),
            "bybit": getattr(self.ui, "listing_bybit_spot_check", None),
            "okx": getattr(self.ui, "listing_okx_spot_check", None),
            "gate": getattr(self.ui, "listing_gate_spot_check", None),
            "bitget": getattr(self.ui, "listing_bitget_spot_check", None),
        }
        widget = mapping.get(exchange_key)
        return bool(widget.isChecked()) if widget else True

    def _is_futures_enabled(self, exchange_key):
        mapping = {
            "binance": getattr(self.ui, "listing_binance_futures_check", None),
            "bybit": getattr(self.ui, "listing_bybit_futures_check", None),
            "okx": getattr(self.ui, "listing_okx_futures_check", None),
            "gate": getattr(self.ui, "listing_gate_futures_check", None),
            "bitget": getattr(self.ui, "listing_bitget_futures_check", None),
        }
        widget = mapping.get(exchange_key)
        return bool(widget.isChecked()) if widget else True
