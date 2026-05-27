from __future__ import annotations

from dataclasses import dataclass
import os
from datetime import datetime
from typing import Any

import requests


EASTMONEY_HOSTS = [
    "push2.eastmoney.com",
    "82.push2.eastmoney.com",
    "7.push2.eastmoney.com",
    "28.push2.eastmoney.com",
]

EASTMONEY_FIELDS = "f12,f13,f14,f2,f3,f4"


@dataclass(frozen=True)
class StockQuote:
    code: str
    name: str
    price: float | None
    change_amount: float | None
    change_percent: float | None


@dataclass(frozen=True)
class StockSearchResult:
    code: str
    name: str
    market: str


@dataclass(frozen=True)
class QuoteResult:
    quotes: list[StockQuote]
    updated_at: datetime
    error: str | None = None
    stale: bool = False


class MarketDataService:
    def __init__(self) -> None:
        self._last_success: QuoteResult | None = None
        self._use_mock_on_failure = os.environ.get("STOCKFLOAT_MOCK_ON_FAILURE") == "1"
        self._eastmoney_cookie = os.environ.get("STOCKFLOAT_EASTMONEY_COOKIE", "").strip()

    def set_cookie(self, cookie: str) -> None:
        self._eastmoney_cookie = cookie.strip()

    def check_connection(self, symbols: list[str]) -> tuple[bool, str]:
        normalized_symbols = [symbol.zfill(6) for symbol in symbols] or ["000001"]
        try:
            quotes = self._fetch_eastmoney_quotes(normalized_symbols[:3])
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)
        found = sum(1 for quote in quotes if quote.price is not None)
        return True, f"接口可用，返回 {found}/{len(quotes)} 条行情"

    def search_stocks(self, keyword: str) -> list[StockSearchResult]:
        keyword = keyword.strip()
        if not keyword:
            return []
        response = requests.get(
            "https://searchapi.eastmoney.com/api/suggest/get",
            params={"input": keyword, "type": "14"},
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://quote.eastmoney.com/",
            },
            timeout=8,
        )
        response.raise_for_status()
        rows = response.json().get("QuotationCodeTable", {}).get("Data") or []
        results: list[StockSearchResult] = []
        seen: set[str] = set()
        for row in rows:
            if row.get("Classify") != "AStock":
                continue
            code = str(row.get("Code", "")).strip().zfill(6)
            if not code or code in seen:
                continue
            seen.add(code)
            results.append(
                StockSearchResult(
                    code=code,
                    name=_as_text(row.get("Name"), fallback=code),
                    market=_as_text(row.get("SecurityTypeName"), fallback="A股"),
                )
            )
        return results[:20]

    def fetch_quotes(self, symbols: list[str]) -> QuoteResult:
        normalized_symbols = [symbol.zfill(6) for symbol in symbols]
        if self._use_mock_on_failure:
            return QuoteResult(
                quotes=_mock_quotes(normalized_symbols),
                updated_at=datetime.now(),
                error="mock data enabled",
                stale=True,
            )
        try:
            quotes = self._fetch_eastmoney_quotes(normalized_symbols)
            result = QuoteResult(quotes=quotes, updated_at=datetime.now())
            self._last_success = result
            return result
        except Exception as exc:  # noqa: BLE001
            if self._last_success is not None:
                return QuoteResult(
                    quotes=self._last_success.quotes,
                    updated_at=self._last_success.updated_at,
                    error=str(exc),
                    stale=True,
                )
            if self._use_mock_on_failure:
                return QuoteResult(
                    quotes=_mock_quotes(normalized_symbols),
                    updated_at=datetime.now(),
                    error=f"mock data: {exc}",
                    stale=True,
                )
            return QuoteResult(quotes=[], updated_at=datetime.now(), error=str(exc), stale=True)

    def _fetch_eastmoney_quotes(self, symbols: list[str]) -> list[StockQuote]:
        if not symbols:
            return []

        params = {
            "fltt": "2",
            "invt": "2",
            "fields": EASTMONEY_FIELDS,
            "secids": ",".join(_eastmoney_secid(symbol) for symbol in symbols),
        }
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://quote.eastmoney.com/center/gridlist.html",
            "Origin": "https://quote.eastmoney.com",
        }
        if self._eastmoney_cookie:
            headers["Cookie"] = self._eastmoney_cookie

        last_error: Exception | None = None
        for host in EASTMONEY_HOSTS:
            try:
                response = requests.get(
                    f"https://{host}/api/qt/ulist.np/get",
                    params=params,
                    headers=headers,
                    timeout=8,
                )
                response.raise_for_status()
                payload = response.json()
                if payload.get("rc") != 0:
                    raise ValueError(f"Eastmoney returned rc={payload.get('rc')}")
                rows = payload.get("data", {}).get("diff") or []
                return _extract_eastmoney_quotes(rows, symbols)
            except Exception as exc:  # noqa: BLE001
                last_error = exc

        if last_error is not None:
            raise last_error
        return []


def _eastmoney_secid(symbol: str) -> str:
    market = "1" if symbol.startswith(("5", "6", "9")) else "0"
    return f"{market}.{symbol}"


def _extract_eastmoney_quotes(rows: list[dict[str, Any]], symbols: list[str]) -> list[StockQuote]:
    by_code = {str(row.get("f12", "")).strip().zfill(6): row for row in rows}
    quotes: list[StockQuote] = []
    for symbol in symbols:
        row = by_code.get(symbol)
        if row is None:
            quotes.append(
                StockQuote(
                    code=symbol,
                    name="未找到",
                    price=None,
                    change_amount=None,
                    change_percent=None,
                )
            )
            continue
        quotes.append(
            StockQuote(
                code=symbol,
                name=_as_text(row.get("f14"), fallback=symbol),
                price=_as_float(row.get("f2")),
                change_amount=_as_float(row.get("f4")),
                change_percent=_as_float(row.get("f3")),
            )
        )
    return quotes


def _as_float(value: Any) -> float | None:
    try:
        if value is None or value == "-":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_text(value: Any, fallback: str) -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def _mock_quotes(symbols: list[str]) -> list[StockQuote]:
    names = {
        "000001": "平安银行",
        "600519": "贵州茅台",
        "300750": "宁德时代",
    }
    base = {
        "000001": (10.12, 0.12, 1.20),
        "600519": (1688.0, -5.50, -0.32),
        "300750": (212.8, 3.62, 1.73),
    }
    quotes: list[StockQuote] = []
    for symbol in symbols:
        price, amount, percent = base.get(symbol, (None, None, None))
        quotes.append(
            StockQuote(
                code=symbol,
                name=names.get(symbol, symbol),
                price=price,
                change_amount=amount,
                change_percent=percent,
            )
        )
    return quotes
