from unittest import TestCase

from app.services.market_data import EASTMONEY_FIELDS, _extract_eastmoney_quotes


class MarketDataTest(TestCase):
    def test_extracts_quote_trading_metrics_from_eastmoney_fields(self) -> None:
        self.assertEqual(EASTMONEY_FIELDS, "f12,f13,f14,f2,f3,f4,f8,f5,f6")

        quote = _extract_eastmoney_quotes(
            [
                {
                    "f12": "000001",
                    "f14": "平安银行",
                    "f2": 10.12,
                    "f3": 1.2,
                    "f4": 0.12,
                    "f8": 3.45,
                    "f5": 987654,
                    "f6": 123456789.0,
                }
            ],
            ["000001"],
        )[0]

        self.assertEqual(quote.turnover_rate, 3.45)
        self.assertEqual(quote.volume, 987654.0)
        self.assertEqual(quote.turnover_amount, 123456789.0)

    def test_missing_quote_keeps_trading_metrics_absent(self) -> None:
        quote = _extract_eastmoney_quotes([], ["000001"])[0]

        self.assertIsNone(quote.turnover_rate)
        self.assertIsNone(quote.volume)
        self.assertIsNone(quote.turnover_amount)
