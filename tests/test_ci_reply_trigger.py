"""리뷰 코멘트 이벤트의 권한·답글 판정은 payload 가 아니라 REST 값으로 한다.

실측(2026-11-17): `pull_request_review_comment` payload 는 같은 코멘트의 `author_association` 을
`CONTRIBUTOR` 로 주는데 REST 단건 조회는 `MEMBER` 로 준다 (`issue_comment` payload 는 `MEMBER` 다).
그래서 호출 워크플로의 `if` 와 이 모듈이 payload 값을 보던 동안, 멤버가 스레드에 단 답글로 뜬 실행이
호출 레포 두 곳에서 100 건 전부 걸러졌다. payload 를 직접 만들어 넣는 테스트로는 재현되지 않는다.
"""

from __future__ import annotations

import unittest
from unittest import mock

from pcr import ci, gh

# payload 가 주는 값 — 권한 판정에 쓰면 답글이 전부 막힌다.
PAYLOAD_COMMENT = {"id": 42, "user": {"login": "member"}, "author_association": "CONTRIBUTOR"}


def run(comment: dict, *, fetched: object = None, error: Exception | None = None):
    payload = {"action": "created", "comment": comment, "pull_request": {"number": 5}}
    with mock.patch.object(ci, "_execute", return_value=0) as execute, mock.patch.object(
        ci.ctx_module, "bot_logins", return_value=["crispin-bot"]
    ), mock.patch.object(gh, "get", side_effect=error or (lambda path: fetched)) as fetch:
        ci._on_review_comment("crispin-lab", "x", payload)
    return execute, fetch


class ReviewCommentTriggerTest(unittest.TestCase):
    def test_member_reply_runs_even_though_payload_says_contributor(self):
        execute, fetch = run(
            PAYLOAD_COMMENT,
            fetched={"author_association": "MEMBER", "in_reply_to_id": 7},
        )
        execute.assert_called_once()
        self.assertTrue(execute.call_args.args[0].reply)
        fetch.assert_called_once_with("repos/crispin-lab/x/pulls/comments/42")

    def test_top_level_comment_does_not_run(self):
        execute, _ = run(PAYLOAD_COMMENT, fetched={"author_association": "MEMBER", "in_reply_to_id": None})
        execute.assert_not_called()

    def test_unprivileged_reply_does_not_run(self):
        # REST 값이 기준이다 — payload 가 무엇이든 권한 없는 사용자는 판단 단계를 열지 못한다.
        for association in ["NONE", "CONTRIBUTOR", "COLLABORATOR"]:
            execute, _ = run(
                PAYLOAD_COMMENT,
                fetched={"author_association": association, "in_reply_to_id": 7},
            )
            execute.assert_not_called()

    def test_lookup_failure_does_not_run(self):
        # 판단 단계는 비용이 들어서, 확인하지 못하면 돌지 않는 쪽이 기본값이다.
        execute, _ = run(PAYLOAD_COMMENT, error=gh.GhError("gh: Not Found (HTTP 404)", 404))
        execute.assert_not_called()

    def test_bot_reply_does_not_run_and_costs_no_lookup(self):
        execute, fetch = run({"id": 42, "user": {"login": "crispin-bot"}, "author_association": "MEMBER"})
        execute.assert_not_called()
        fetch.assert_not_called()

    def test_comment_without_id_does_not_run(self):
        execute, fetch = run({"user": {"login": "member"}, "author_association": "CONTRIBUTOR"})
        execute.assert_not_called()
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
