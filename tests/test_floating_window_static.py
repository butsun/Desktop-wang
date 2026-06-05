import ast
from pathlib import Path
from unittest import TestCase


SOURCE = Path("app/ui/floating_window.py")


class FloatingWindowColumnTest(TestCase):
    def test_quote_columns_are_centralized_with_trading_metrics(self) -> None:
        module = ast.parse(SOURCE.read_text())
        assignments = {
            node.targets[0].id: ast.literal_eval(node.value)
            for node in module.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "QUOTE_COLUMNS"
        }

        self.assertEqual(
            [column[0] for column in assignments["QUOTE_COLUMNS"]],
            ["名称", "代码", "现价", "涨跌额", "涨跌幅", "换手率", "成交量", "成交额"],
        )

    def test_header_and_rows_share_quote_column_widths(self) -> None:
        source = SOURCE.read_text()

        self.assertIn("_apply_quote_column_widths(column_header)", source)
        self.assertIn("_apply_quote_column_widths(layout)", source)
