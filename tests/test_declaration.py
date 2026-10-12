"""Prove della dichiarazione del motore: i limiti sono quelli della decisione 14."""

import json
import unittest

from regodoc import declaration


class LimitsTest(unittest.TestCase):
    def test_envelope_limits(self) -> None:
        self.assertEqual(
            dict(declaration.ENVELOPE_LIMITS),
            {
                "compressed_bytes": 12 * 1024 * 1024,
                "expanded_bytes": 40 * 1024 * 1024,
                "compression_ratio": 20,
                "files": 200,
            },
        )

    def test_content_limits(self) -> None:
        limits = declaration.CONTENT_LIMITS
        self.assertEqual(limits["parts"], 48)
        self.assertEqual(limits["characters"], 1_500_000)
        self.assertEqual(limits["part_bytes"], 384 * 1024)
        self.assertEqual(limits["images"], 80)
        self.assertEqual(limits["image_bytes"], 8 * 1024 * 1024)
        self.assertEqual(limits["images_total_bytes"], 40 * 1024 * 1024)
        self.assertEqual(limits["table_rows"], 600)
        self.assertEqual(limits["table_columns"], 10)
        self.assertEqual(limits["table_columns_normal_size"], 8)
        self.assertEqual(limits["variables"], 1500)

    def test_images_fit_in_expanded_envelope(self) -> None:
        self.assertLessEqual(
            declaration.CONTENT_LIMITS["images_total_bytes"],
            declaration.ENVELOPE_LIMITS["expanded_bytes"],
        )

    def test_limits_are_read_only(self) -> None:
        with self.assertRaises(TypeError):
            declaration.ENVELOPE_LIMITS["files"] = 10_000  # type: ignore[index]


class DescribeTest(unittest.TestCase):
    def test_json_round_trip(self) -> None:
        described = declaration.describe()
        self.assertEqual(json.loads(json.dumps(described)), described)

    def test_current_grammar_is_readable(self) -> None:
        self.assertIn(declaration.GRAMMAR_CURRENT, declaration.GRAMMARS_READ)
        self.assertEqual(declaration.GRAMMARS_READ[-1], declaration.GRAMMAR_CURRENT)


if __name__ == "__main__":
    unittest.main()
