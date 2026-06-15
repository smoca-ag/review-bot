import unittest

from review_bot.orchestration.formatter import _derive_severity
from review_bot.models import LineComment


class TestDeriveSeverity(unittest.TestCase):
    def _make_comment(self, risk_score: int, confidence_score: float) -> LineComment:
        return LineComment(
            file="src/app.py",
            line=10,
            risk_score=risk_score,
            category="logic",
            hypothesis="In src/app.py:10, X is wrong because Y",
            falsification_method="scan_code for X in src/",
            verification="confirmed",
            counter_argument="The author might have intended this behavior",
            confidence_score=confidence_score,
            comment="This is wrong",
        )

    def test_critical(self):
        c = self._make_comment(risk_score=5, confidence_score=0.9)
        self.assertEqual(_derive_severity(c), "CRITICAL")

    def test_critical_boundary(self):
        c = self._make_comment(risk_score=5, confidence_score=0.8)
        self.assertEqual(_derive_severity(c), "CRITICAL")

    def test_major_from_risk(self):
        c = self._make_comment(risk_score=4, confidence_score=0.7)
        self.assertEqual(_derive_severity(c), "MAJOR")

    def test_major_from_risk3_high_conf(self):
        c = self._make_comment(risk_score=3, confidence_score=0.85)
        self.assertEqual(_derive_severity(c), "MAJOR")

    def test_minor(self):
        c = self._make_comment(risk_score=2, confidence_score=0.9)
        self.assertEqual(_derive_severity(c), "MINOR")

    def test_minor_low_risk(self):
        c = self._make_comment(risk_score=1, confidence_score=0.95)
        self.assertEqual(_derive_severity(c), "MINOR")


class TestLineCommentModel(unittest.TestCase):
    def test_new_fields(self):
        c = LineComment(
            file="src/auth.py",
            line=42,
            end_line=45,
            risk_score=5,
            category="security",
            hypothesis="In src/auth.py:42, password is passed unsanitized to db.query()",
            falsification_method="scan_code('sanitize.*password', 'src/')",
            verification="confirmed",
            counter_argument="The caller might sanitize before calling",
            confidence_score=0.9,
            comment="Unsanitized password passed to query",
        )
        self.assertEqual(c.end_line, 45)
        self.assertEqual(c.risk_score, 5)
        self.assertEqual(c.verification, "confirmed")

    def test_single_line_no_end(self):
        c = LineComment(
            file="src/app.py",
            line=10,
            risk_score=2,
            category="logic",
            hypothesis="In src/app.py:10, variable is unused",
            falsification_method="scan_code for usage",
            verification="inconclusive",
            counter_argument="May be used dynamically",
            confidence_score=0.6,
            comment="Unused variable",
        )
        self.assertIsNone(c.end_line)

    def test_risk_score_validation(self):
        with self.assertRaises(Exception):
            LineComment(
                file="src/app.py",
                line=10,
                risk_score=0,
                category="logic",
                hypothesis="test",
                falsification_method="test",
                verification="confirmed",
                counter_argument="test",
                confidence_score=0.5,
                comment="test",
            )

    def test_risk_score_too_high(self):
        with self.assertRaises(Exception):
            LineComment(
                file="src/app.py",
                line=10,
                risk_score=6,
                category="logic",
                hypothesis="test",
                falsification_method="test",
                verification="confirmed",
                counter_argument="test",
                confidence_score=0.5,
                comment="test",
            )

    def test_verification_values(self):
        for v in ("confirmed", "inconclusive"):
            c = LineComment(
                file="src/app.py",
                line=10,
                risk_score=3,
                category="logic",
                hypothesis="test",
                falsification_method="test",
                verification=v,
                counter_argument="test",
                confidence_score=0.5,
                comment="test",
            )
            self.assertEqual(c.verification, v)


if __name__ == "__main__":
    unittest.main()
