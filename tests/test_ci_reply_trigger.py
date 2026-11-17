"""payload 에 `in_reply_to_id` 가 없는 스레드 답글도 답글 모드로 돌아야 한다.

실측(2026-11-17): 호출 레포 두 곳에서 `pull_request_review_comment` 실행 100 건이 전부 걸러졌다.
그중 멤버가 스레드에 단 답글도 섞여 있었다. `tests/test_core.py` 의 기존 케이스는 payload 를 직접
만들어 `in_reply_to_id` 를 넣으므로 이 경로를 재현하지 못한다 — 그래서 단위 테스트는 초록인데
실물은 한 번도 돌지 않았다.
"""

from __future__ import annotations

import unittest
from unittest import mock

from pcr import ci, gh


def payload(comment: dict) -> dict:
    return {"action": "created", "comment": comment, "pull_request": {"number": 5}}


def run(comment: dict, *, fetched: object = None, error: Exception | None = None):
    with mock.patch.object(ci, "_execute", return_value=0) as execute, mock.patch.object(
        ci.ctx_module, "bot_logins", return_value=["crispin-bot"]
    ), mock.patch.object(gh, "get", side_effect=error or (lambda path: fetched)) as fetch:
        ci._on_review_comment("crispin-lab", "x", payload(comment))
    return execute, fetch


MEMBER = {"id": 42, "user": {"login": "member"}, "author_association": "MEMBER"}


class ReplyWithoutPayloadFieldTest(unittest.TestCase):
    def test_reply_is_detected_by_lookup(self):
        execute, fetch = run(MEMBER, fetched={"in_reply_to_id": 7})
        execute.assert_called_once()
        self.assertTrue(execute.call_args.args[0].reply)
        fetch.assert_called_once_with("repos/crispin-lab/x/pulls/comments/42")

    def test_top_level_comment_does_not_run(self):
        execute, _ = run(MEMBER, fetched={"in_reply_to_id": None})
        execute.assert_not_called()

    def test_lookup_failure_does_not_run(self):
        # 판단 단계는 비용이 들어서, 확인하지 못하면 돌지 않는 쪽이 기본값이다.
        execute, _ = run(MEMBER, error=gh.GhError("gh: Not Found (HTTP 404)", 404))
        execute.assert_not_called()

    def test_payload_field_short_circuits_the_lookup(self):
        execute, fetch = run({**MEMBER, "in_reply_to_id": 7})
        execute.assert_called_once()
        fetch.assert_not_called()

    def test_bot_reply_does_not_run_and_costs_no_lookup(self):
        execute, fetch = run({"id": 42, "user": {"login": "crispin-bot"}, "author_association": "MEMBER"})
        execute.assert_not_called()
        fetch.assert_not_called()

    def test_unprivileged_reply_costs_no_lookup(self):
        execute, fetch = run({**MEMBER, "author_association": "CONTRIBUTOR"})
        execute.assert_not_called()
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
