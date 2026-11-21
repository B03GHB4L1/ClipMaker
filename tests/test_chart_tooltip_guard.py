"""The map component must hide an open tooltip before it rebuilds the shared chart.

ECharts re-shows an open tooltip from a zero-delay timer after each update. Rebuilding
the chart with setOption(option, true) destroys the tooltip without cancelling that
timer, which then throws "Cannot set properties of null (setting 'innerHTML')" and made
the macOS browser smoke test fail now and then. cmReplaceOption hides the tip first.
"""
import re
import unittest
from pathlib import Path

COMPONENT = Path(__file__).resolve().parents[1] / "app" / "smp_component" / "frontend" / "index.html"


class ChartTooltipGuardTests(unittest.TestCase):
    def setUp(self):
        self.source = COMPONENT.read_text(encoding="utf-8")

    def test_shared_chart_is_never_rebuilt_directly(self):
        self.assertNotRegex(self.source, r"_cmChart\.setOption\([^;]*,\s*true\)",
                            "Rebuild the shared chart through cmReplaceOption so a stale tooltip timer cannot fire")

    def test_helper_hides_the_tip_before_replacing_the_option(self):
        helper = re.search(r"function cmReplaceOption\(chart, option\) \{(.*?)\n  \}", self.source, re.S)
        self.assertIsNotNone(helper)
        body = helper.group(1)
        self.assertLess(body.index('type: "hideTip"'), body.index("chart.setOption(option, true)"))


if __name__ == "__main__":
    unittest.main()
