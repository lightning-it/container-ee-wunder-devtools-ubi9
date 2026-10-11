from __future__ import annotations

import re
import unittest
from pathlib import Path


WORKFLOW = (
    Path(__file__).parents[1]
    / ".github"
    / "workflows"
    / "current-revision-rerun.yml"
)


class RequiredWorkflowDiscoveryContractTests(unittest.TestCase):
    def workflow_source(self) -> str:
        return WORKFLOW.read_text(encoding="utf-8")

    def test_lists_by_exact_head_and_validates_event_from_payload(self) -> None:
        source = self.workflow_source()

        self.assertIn(
            "actions/runs?head_sha=${EXPECTED_HEAD}&per_page=100", source
        )
        self.assertNotIn("actions/runs?event=pull_request_target", source)
        self.assertIn('select(.event == "pull_request_target")', source)

    def test_event_writer_is_pilot_gated_and_has_explicit_write_permissions(
        self,
    ) -> None:
        source = self.workflow_source()
        event_job = source.split("\n  event-rerun:\n", 1)[1]
        pilot = (
            "contains(fromJSON('[\"lightning-it/.github\","
            "\"lightning-it/shared-assets-lit\","
            "\"lightning-it/ansible-collection-supplementary\"]'), "
            "github.repository)"
        )
        event_if = event_job.split("\n    permissions:\n", 1)[0].split(
            "\n    if: >-\n", 1
        )[1]
        self.assertIn("vars.LI219_EVENT_MODE == 'enabled'", event_if)
        self.assertIn(pilot, event_if)
        self.assertIn("github.event_name == 'workflow_dispatch'", event_if)
        self.assertIn("inputs.producer_run_attempt > 0", event_if)
        self.assertIn("steps: *canonical_rerun_steps", event_job)
        attempt_gate = re.search(
            r'\[\[ "\$\{EVENT_PRODUCER_RUN_ATTEMPT\}" =~ (\^\(1\|2\)\$) \]\]',
            source,
        )
        if attempt_gate is None:
            self.fail("missing exact producer attempt gate")
        allowed_attempts = {
            attempt
            for attempt in ("0", "1", "2", "3", "10")
            if re.fullmatch(attempt_gate.group(1), attempt)
        }
        self.assertEqual({"1", "2"}, allowed_attempts)
        self.assertIsNone(re.fullmatch(attempt_gate.group(1), "3"))
        self.assertIn("github.run_attempt == 1", event_job)
        self.assertIn("github.actor == 'github-actions[bot]'", event_job)
        self.assertIn("github.triggering_actor == 'github-actions[bot]'", event_job)
        self.assertIn("permissions:\n      actions: write", event_job)
        self.assertIn("checks: write", event_job)
        self.assertIn("contents: write", event_job)
        self.assertIn("pull-requests: read", event_job)

    def test_legacy_writer_is_disabled_only_for_the_exact_event_envelope(
        self,
    ) -> None:
        source = self.workflow_source()
        legacy = source.split("\n  rerun-protected-verifier:\n", 1)[1].split(
            "\n  event-rerun:\n", 1
        )[0]
        legacy_if = legacy.split("\n    permissions:\n", 1)[0].split(
            "\n    if: >-\n", 1
        )[1]
        pilot = (
            "contains(fromJSON('[\"lightning-it/.github\","
            "\"lightning-it/shared-assets-lit\","
            "\"lightning-it/ansible-collection-supplementary\"]'), "
            "github.repository)"
        )
        self.assertIn(
            "!((vars.LI219_EVENT_MODE == 'enabled'", legacy_if
        )
        self.assertIn("vars.LI219_EVENT_MODE == 'enabled'", legacy_if)
        self.assertIn(pilot, legacy_if)
        self.assertIn("github.event_name == 'workflow_dispatch'", legacy_if)
        self.assertIn("inputs.producer_run_attempt > 0", legacy_if)
        self.assertIn("LI219_EVENT_MODE:-disabled", legacy)

    def test_durable_claim_must_win_before_the_single_rerun_post(self) -> None:
        source = self.workflow_source()
        self.assertEqual(
            1,
            source.count(
                '"repos/${REPOSITORY}/actions/jobs/'
                '${required_job_id}/rerun"'
            ),
        )
        claim = source.index(
            'claim_review_operation "${run_id}" "${EXPECTED_HEAD}" '
            '"${EXPECTED_BASE}" "${PR_NUMBER}" || exit 0'
        )
        rerun = source.index(
            '"repos/${REPOSITORY}/actions/jobs/'
            '${required_job_id}/rerun"'
        )
        self.assertLess(claim, rerun)
        claim_function = source.split(
            "claim_review_operation() {", 1
        )[1].split("\n          }", 1)[0]
        self.assertEqual(
            1,
            claim_function.count(
                "mutation($input:CreateCommitOnBranchInput!)"
            ),
        )
        self.assertIn("Exactly one CAS attempt", claim_function)
        self.assertIn("no rerun sent", claim_function)


if __name__ == "__main__":
    unittest.main()
