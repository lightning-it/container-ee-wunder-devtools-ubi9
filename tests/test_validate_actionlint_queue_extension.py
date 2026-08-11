from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "validate-actionlint-queue-extension.py"
SPEC = importlib.util.spec_from_file_location("queue_validator", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"unable to load {SCRIPT}")
QUEUE_VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QUEUE_VALIDATOR)


class ParseMappingPathsTest(unittest.TestCase):
    def parse(self, content: str) -> dict[tuple[str, ...], str | None]:
        with tempfile.TemporaryDirectory() as directory:
            workflow = Path(directory) / "workflow.yml"
            workflow.write_text(content, encoding="utf-8")
            return QUEUE_VALIDATOR.parse_mapping_paths(workflow)

    def test_accepts_block_style_queue_key(self) -> None:
        document = self.parse(
            "concurrency:\n"
            "  group: release\n"
            "  queue: max\n"
            "  cancel-in-progress: false\n"
        )

        self.assertEqual(document[("concurrency", "queue")], "max")

    def test_detects_flow_style_queue_key(self) -> None:
        document = self.parse(
            "concurrency: { group: release, queue: max, "
            "cancel-in-progress: false }\n"
        )

        self.assertEqual(document[("concurrency", "queue")], "max")

    def test_detects_quoted_flow_style_queue_key(self) -> None:
        document = self.parse("concurrency: { 'queue': max }\n")

        self.assertEqual(document[("concurrency", "queue")], "max")

    def test_detects_escaped_quoted_queue_key(self) -> None:
        document = self.parse('concurrency: { "qu\\u0065ue": max }\n')

        self.assertEqual(document[("concurrency", "queue")], "max")

    def test_detects_flow_mapping_inside_sequence(self) -> None:
        document = self.parse("concurrency: [queue: max]\n")

        self.assertEqual(document[("concurrency", "[0]", "queue")], "max")

    def test_detects_queue_after_hash_inside_plain_scalar(self) -> None:
        document = self.parse("concurrency: {note: abc#def, queue: max}\n")

        self.assertEqual(document[("concurrency", "queue")], "max")

    def test_detects_multiline_explicit_queue_key(self) -> None:
        document = self.parse("concurrency:\n  ? queue\n  : max\n")

        self.assertEqual(document[("concurrency", "queue")], "max")

    def test_rejects_duplicate_and_merge_keys(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate mapping key"):
            self.parse("concurrency:\n  queue: max\n  queue: max\n")
        with self.assertRaisesRegex(ValueError, "YAML merge keys"):
            self.parse("defaults: &defaults\n  group: release\nconcurrency:\n  <<: *defaults\n")

    def test_ignores_queue_text_in_comments_strings_and_block_scalars(self) -> None:
        document = self.parse(
            "name: 'queue: max' # queue: max\n"
            "run: |\n"
            "  echo 'queue: max'\n"
        )

        self.assertNotIn(("queue",), document)


if __name__ == "__main__":
    unittest.main()
