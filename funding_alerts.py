from PyQt6.QtCore import QObject, pyqtSignal, QTimer
import threading
import time
import requests
import json
from datetime import datetime, timedelta
from collections import defaultdict


class FundingMonitor(QObject):
    """Monitor for funding rates from multiple exchanges"""

    alert_signal = pyqtSignal(dict)  # Emitted when a funding alert occurs
    log_signal = pyqtSignal(dict)  # Emitted for logging information
    status_signal = pyqtSignal(dict)  # Emitted for status updates

    # Funding rate thresholds and timing
    MIN_FUNDING_RATE = 0.001  # 0.001% - very low threshold since most rates are tiny
    ALERT_MINUTES_BEFORE = 5  # Alert when X minutes before funding

    # Exchange endpoints
    EXCHANGES = {
        "binance": {
            "name": "Binance",
            "endpoint": "https://fapi.binance.com/fapi/v1/fundingRate",
            "rate_key": "fundingRate",
            "time_key": "fundingTime",
        },
        "bybit": {
            "name": "Bybit",
            "endpoint": "https://api.bybit.com/v5/market/funding/history",
            "rate_key": "fundingRate",
            "time_key": "fundingTime",
        },
        "okx": {
            "name": "OKX",
            "endpoint": "https://www.okx.com/api/v5/public/funding-rate",
            "rate_key": "fundingRate",
            "time_key": "nextFundingTime",
        },
        "gate": {
            "name": "Gate.io",
            "endpoint": "https://api.gateio.ws/api/v4/futures/usdt/funding_rates",
            "rate_key": "funding_rate",
            "time_key": "next_funding_time",
        },
        "bitget": {
            "name": "Bitget",
            "endpoint": "https://api.bitget.com/api/v2/mix/market/current-fund-rate",
            "rate_key": "fundingRate",
            "time_key": "fundingTime",
        },
    }

    def __init__(self, ui):
        super().__init__()
        self.ui = ui
        self.is_monitoring = False
        self.monitor_thread = None
        self.timer = QTimer()
        self.timer.timeout.connect(self.poll)
        self.timer.setInterval(60000)  # Poll every 60 seconds

        self.cache = {}  # Cache for funding data
        self.last_alerts = {}  # Track last alerts to avoid duplicates
        self.exchange_status = {}  # Status of each exchange
        self.fetched_counts = defaultdict(int)  # Count of fetched coins per exchange

    def start(self):
        """Start the funding monitor"""
        if not self.is_monitoring:
            self.is_monitoring = True
            self.monitor_thread = threading.Thread(
                target=self._monitor_loop, daemon=True
            )
            self.monitor_thread.start()
            self.timer.start()
            self.poll()

            self.log_signal.emit(
                {"level": "info", "message": "Funding monitor started"}
            )

    def stop(self):
        """Stop the funding monitor"""
        self.is_monitoring = False
        self.timer.stop()
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2)

        self.log_signal.emit({"level": "info", "message": "Funding monitor stopped"})

    def _monitor_loop(self):
        """Main monitoring loop"""
        while self.is_monitoring:
            try:
                time.sleep(1)
            except Exception as e:
                self.log_signal.emit(
                    {"level": "error", "message": f"Monitor loop error: {str(e)}"}
                )

    def poll(self):
        """Poll all exchanges for funding data"""
        if not self.is_monitoring:
            return

        thread = threading.Thread(target=self._poll_exchanges, daemon=True)
        thread.start()

    def _poll_exchanges(self):
        """Poll exchanges in background thread"""
        try:
            enabled_exchanges = self._get_enabled_exchanges()

            for exchange_key in enabled_exchanges:
                try:
                    self.fetched_counts[exchange_key] = 0
                    self._poll_exchange(exchange_key)
                    self.exchange_status[exchange_key] = {
                        "fetched": self.fetched_counts[exchange_key],
                        "passed": 0,
                        "error": None,
                    }
                except Exception as e:
                    import traceback

                    error_msg = (
                        f"{self.EXCHANGES[exchange_key]['name']} error: {str(e)}"
                    )
                    self.log_signal.emit({"level": "error", "message": error_msg})
                    self.exchange_status[exchange_key] = {
                        "fetched": 0,
                        "passed": 0,
                        "error": str(e)[:100],
                    }
                    traceback.print_exc()

            # Emit status update
            self.status_signal.emit({"exchanges": dict(self.exchange_status)})

        except Exception as e:
            import traceback

            self.log_signal.emit(
                {"level": "error", "message": f"Polling error: {str(e)}"}
            )
            traceback.print_exc()

    def _get_enabled_exchanges(self):
        """Get list of enabled exchanges from UI checkboxes"""
        enabled = []
        exchange_checks = {
            "binance": (
                self.ui.funding_binance_check
                if hasattr(self.ui, "funding_binance_check")
                else None
            ),
            "bybit": (
                self.ui.funding_bybit_check
                if hasattr(self.ui, "funding_bybit_check")
                else None
            ),
            "okx": (
                self.ui.funding_okx_check
                if hasattr(self.ui, "funding_okx_check")
                else None
            ),
            "gate": (
                self.ui.funding_gate_check
                if hasattr(self.ui, "funding_gate_check")
                else None
            ),
            "bitget": (
                self.ui.funding_bitget_check
                if hasattr(self.ui, "funding_bitget_check")
                else None
            ),
        }

        for exchange_key, check_widget in exchange_checks.items():
            if check_widget and check_widget.isChecked():
                enabled.append(exchange_key)

        return enabled

    def _poll_exchange(self, exchange_key):
        """Poll a specific exchange for funding data"""
        exchange_config = self.EXCHANGES[exchange_key]

        if exchange_key == "binance":
            self._poll_binance()
        elif exchange_key == "bybit":
            self._poll_bybit()
        elif exchange_key == "okx":
            self._poll_okx()
        elif exchange_key == "gate":
            self._poll_gate()
        elif exchange_key == "bitget":
            self._poll_bitget()

    def _poll_binance(self):
        """Poll Binance for funding rates"""
        response = requests.get(
            "https://fapi.binance.com/fapi/v1/premiumIndex",
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        if isinstance(data, dict):
            data = [data]

        data = [
            item
            for item in data
            if isinstance(item, dict) and str(item.get("symbol", "")).endswith("USDT")
        ]

        self._process_funding_data(
            data,
            "binance",
            {
                "symbol_key": "symbol",
                "rate_key": "lastFundingRate",
                "time_key": "nextFundingTime",
                "rate_multiplier": 100,  # Convert to percentage
            },
        )

    def _poll_bybit(self):
        """Poll Bybit for funding rates"""
        response = requests.get(
            "https://api.bybit.com/v5/market/tickers",
            params={"category": "linear"},
            timeout=10,
        )
        response.raise_for_status()
        result = response.json()
        data = result.get("result", {}).get("list", [])

        # Filter to only USDT perpetuals with funding
        filtered_data = []
        for item in data:
            if "USDT" in item.get("symbol", ""):
                filtered_data.append(item)

        self._process_funding_data(
            filtered_data,
            "bybit",
            {
                "symbol_key": "symbol",
                "rate_key": "fundingRate",
                "time_key": "nextFundingTime",
                "rate_multiplier": 100,
            },
        )

    def _poll_okx(self):
        """Poll OKX for funding rates"""
        instruments_resp = requests.get(
            "https://www.okx.com/api/v5/public/instruments",
            params={"instType": "SWAP"},
            timeout=10,
        )
        instruments_resp.raise_for_status()
        instruments_json = instruments_resp.json()
        instruments = (
            instruments_json.get("data", [])
            if isinstance(instruments_json, dict)
            else []
        )

        preferred_ids = [
            "BTC-USDT-SWAP",
            "ETH-USDT-SWAP",
            "SOL-USDT-SWAP",
            "XRP-USDT-SWAP",
            "DOGE-USDT-SWAP",
            "BNB-USDT-SWAP",
            "ADA-USDT-SWAP",
            "TRX-USDT-SWAP",
            "DOT-USDT-SWAP",
            "LINK-USDT-SWAP",
            "AVAX-USDT-SWAP",
            "LTC-USDT-SWAP",
            "BCH-USDT-SWAP",
            "TON-USDT-SWAP",
            "ETC-USDT-SWAP",
        ]

        known_ids = {
            str(item.get("instId", ""))
            for item in instruments
            if isinstance(item, dict)
        }
        inst_ids = [inst_id for inst_id in preferred_ids if inst_id in known_ids]

        data = []
        for inst_id in inst_ids:
            try:
                response = requests.get(
                    "https://www.okx.com/api/v5/public/funding-rate",
                    params={"instId": inst_id},
                    timeout=8,
                )
                response.raise_for_status()
                payload = response.json()
                rows = payload.get("data", []) if isinstance(payload, dict) else []
                if rows:
                    data.extend(rows)
            except Exception:
                continue

        self._process_funding_data(
            data,
            "okx",
            {
                "symbol_key": "instId",
                "rate_key": "fundingRate",
                "time_key": "nextFundingTime",
                "rate_multiplier": 100,
            },
        )

    def _poll_gate(self):
        """Poll Gate.io for funding rates"""
        response = requests.get(
            "https://api.gateio.ws/api/v4/futures/usdt/contracts",
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        if isinstance(data, dict):
            data = [data]

        data = [
            item
            for item in data
            if isinstance(item, dict)
            and str(item.get("name", "")).endswith("_USDT")
            and item.get("funding_next_apply")
        ]

        self._process_funding_data(
            data,
            "gate",
            {
                "symbol_key": "name",
                "rate_key": "funding_rate",
                "time_key": "funding_next_apply",
                "rate_multiplier": 100,
            },
        )

    def _poll_bitget(self):
        """Poll Bitget for funding rates"""
        response = requests.get(
            "https://api.bitget.com/api/v2/mix/market/current-fund-rate",
            params={"productType": "USDT-FUTURES"},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data", []) if isinstance(payload, dict) else []

        self._process_funding_data(
            data,
            "bitget",
            {
                "symbol_key": "symbol",
                "rate_key": "fundingRate",
                "time_key": "nextUpdate",
                "rate_multiplier": 100,
            },
        )

    def _process_funding_data(self, data, exchange_key, config):
        """Process funding data and emit alerts"""
        if not isinstance(data, list):
            data = [data] if isinstance(data, dict) else []

        exchange_name = self.EXCHANGES[exchange_key]["name"]
        now = datetime.now()
        count_processed = 0
        log_minutes_limit = self._get_log_minutes_limit()

        for item in data:
            try:
                if not isinstance(item, dict):
                    continue

                symbol = item.get(config["symbol_key"], "")
                rate_str = item.get(config["rate_key"], "0")
                time_ms = item.get(config["time_key"], 0)

                # Parse rate
                try:
                    rate = float(rate_str)
                except (ValueError, TypeError):
                    continue

                # Convert rate to percentage
                rate_pct = rate * config.get("rate_multiplier", 1)

                # Skip if rate is too low (absolute value)
                if abs(rate_pct) < self.MIN_FUNDING_RATE:
                    continue

                # Parse funding time
                try:
                    if isinstance(time_ms, str):
                        time_ms = int(time_ms)
                    if time_ms > 10**10:  # Milliseconds
                        funding_time = datetime.fromtimestamp(time_ms / 1000)
                    else:  # Seconds
                        funding_time = datetime.fromtimestamp(time_ms)
                except (ValueError, TypeError):
                    continue

                # Calculate minutes until funding
                minutes_to = (funding_time - now).total_seconds() / 60

                # Skip if already funded or too far in past
                if minutes_to < 0 or minutes_to > 1440:  # 24 hours
                    continue

                count_processed += 1
                self.fetched_counts[exchange_key] += 1

                # Check if we should alert (within 5 minutes before funding)
                alert_key = f"{exchange_key}:{symbol}"
                if 0 <= minutes_to <= self.ALERT_MINUTES_BEFORE:
                    if (
                        alert_key not in self.last_alerts
                        or (
                            datetime.now() - self.last_alerts[alert_key]
                        ).total_seconds()
                        > 300
                    ):

                        self.alert_signal.emit(
                            {
                                "exchange": exchange_name,
                                "symbol": symbol,
                                "minutes_to": int(minutes_to),
                                "signed_rate_pct": round(rate_pct, 4),
                                "next_funding_time": int(
                                    funding_time.timestamp() * 1000
                                ),
                            }
                        )
                        self.last_alerts[alert_key] = datetime.now()

                # Log funding data for upcoming funding (within user-selected window)
                if minutes_to <= log_minutes_limit:
                    self.log_signal.emit(
                        {
                            "exchange": exchange_name,
                            "symbol": symbol,
                            "signed_rate_pct": round(rate_pct, 4),
                            "minutes_to": int(minutes_to),
                            "next_funding_time": int(funding_time.timestamp() * 1000),
                        }
                    )

            except Exception as e:
                continue

        # Log summary
        if count_processed > 0:
            self.log_signal.emit(
                {
                    "level": "info",
                    "message": f"{exchange_name}: processed {count_processed} coins with funding in next 24 hours",
                }
            )

    def _get_log_minutes_limit(self):
        default_minutes = 60.0
        try:
            if not hasattr(self.ui, "funding_minutes_edit"):
                return default_minutes
            raw = (
                str(self.ui.funding_minutes_edit.text() or "").strip().replace(",", ".")
            )
            if not raw:
                return default_minutes
            value = float(raw)
            if value < 0:
                return 0.0
            # В данных мы и так ограничиваемся ближайшими 24 часами.
            return min(1440.0, value)
        except Exception:
            return default_minutes

    def clear_cache(self):
        """Clear funding data cache"""
        self.cache.clear()
        self.last_alerts.clear()
