"""
Tests for HackathonJudge Intelligent Contract
Run with: pytest test_hackathon_judge.py -v
"""

import pytest
import json
from unittest.mock import patch, MagicMock
from hackathon_judge import HackathonJudge


# ── Fixtures / constants ────────────────────────────────────────────────────

RUBRIC = "Judge on innovation (50%) and code quality (50%)."

ORGANIZER = "0xOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOO"
ALICE     = "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
BOB       = "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
CAROL     = "0xCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"

POOL_WEI = 100 * 10**18  # 100 GEN


def make_contract(sender=ORGANIZER, rubric=RUBRIC):
    with patch("genlayer.gl.message") as msg:
        msg.sender_address = sender
        msg.value = 0
        return HackathonJudge(rubric)


def as_sender(addr, value=0):
    """Context manager-style helper: returns a patched gl.message mock."""
    patcher = patch("genlayer.gl.message")
    msg = patcher.start()
    msg.sender_address = addr
    msg.value = value
    return patcher


def llm_response(score, feedback="Solid project."):
    """A fake raw LLM response string, as the contract expects it."""
    return json.dumps({"score": score, "feedback": feedback})


def fake_eq_principle_prompt_comparative(fn, principle):
    """
    Test double for gl.eq_principle.prompt_comparative.
    In production this runs the function on multiple validators and
    checks agreement via NLP. For unit tests we just run it once.
    """
    return fn()


# ── Constructor ──────────────────────────────────────────────────────────

class TestConstructor:

    def test_deploy_sets_organizer_and_rubric(self):
        c = make_contract()
        status = c.get_status()
        assert status["organizer"] == ORGANIZER
        assert status["rubric"] == RUBRIC
        assert status["prize_pool_wei"] == 0
        assert status["participant_count"] == 0
        assert status["distributed"] is False

    def test_empty_rubric_raises(self):
        with pytest.raises(Exception, match="Rubric cannot be empty"):
            make_contract(rubric="")


# ── Fund pool ────────────────────────────────────────────────────────────

class TestFundPool:

    def test_fund_pool_increases_balance(self):
        c = make_contract()
        with patch("genlayer.gl.message") as msg:
            msg.sender_address = ORGANIZER
            msg.value = POOL_WEI
            c.fund_pool()
        assert c.get_status()["prize_pool_wei"] == POOL_WEI

    def test_fund_pool_accumulates(self):
        c = make_contract()
        for _ in range(2):
            with patch("genlayer.gl.message") as msg:
                msg.sender_address = ORGANIZER
                msg.value = POOL_WEI
                c.fund_pool()
        assert c.get_status()["prize_pool_wei"] == POOL_WEI * 2

    def test_fund_with_zero_value_raises(self):
        c = make_contract()
        with pytest.raises(Exception, match="Must send GEN"):
            with patch("genlayer.gl.message") as msg:
                msg.sender_address = ORGANIZER
                msg.value = 0
                c.fund_pool()


# ── Submit project ───────────────────────────────────────────────────────

class TestSubmitProject:

    def test_submit_records_repo(self):
        c = make_contract()
        with patch("genlayer.gl.message") as msg:
            msg.sender_address = ALICE
            msg.value = 0
            c.submit_project("https://github.com/alice/cool-project")

        board = c.get_leaderboard()
        assert len(board) == 1
        assert board[0]["address"]  == ALICE
        assert board[0]["repo_url"] == "https://github.com/alice/cool-project"
        assert board[0]["judged"]   is False

    def test_empty_repo_url_raises(self):
        c = make_contract()
        with pytest.raises(Exception, match="repo_url cannot be empty"):
            with patch("genlayer.gl.message") as msg:
                msg.sender_address = ALICE
                msg.value = 0
                c.submit_project("")

    def test_duplicate_submission_raises(self):
        c = make_contract()
        with patch("genlayer.gl.message") as msg:
            msg.sender_address = ALICE
            msg.value = 0
            c.submit_project("https://github.com/alice/project")

        with pytest.raises(Exception, match="already submitted"):
            with patch("genlayer.gl.message") as msg:
                msg.sender_address = ALICE
                msg.value = 0
                c.submit_project("https://github.com/alice/other-project")

    def test_multiple_participants_tracked_in_order(self):
        c = make_contract()
        for addr, url in [(ALICE, "https://github.com/alice/p"),
                           (BOB,   "https://github.com/bob/p")]:
            with patch("genlayer.gl.message") as msg:
                msg.sender_address = addr
                msg.value = 0
                c.submit_project(url)

        board = c.get_leaderboard()
        assert [b["address"] for b in board] == [ALICE, BOB]


# ── Judge project ────────────────────────────────────────────────────────

class TestJudgeProject:

    def _submit(self, c, addr, url):
        with patch("genlayer.gl.message") as msg:
            msg.sender_address = addr
            msg.value = 0
            c.submit_project(url)

    def test_judge_records_score_and_feedback(self):
        c = make_contract()
        self._submit(c, ALICE, "https://github.com/alice/project")

        with patch("genlayer.gl.nondet.web.get_text", return_value="# Great README"), \
             patch("genlayer.gl.nondet.exec_prompt",
                   return_value=llm_response(85, "Innovative use of AI.")), \
             patch("genlayer.gl.eq_principle.prompt_comparative",
                   side_effect=fake_eq_principle_prompt_comparative):
            c.judge_project(ALICE)

        sub = c.get_submission(ALICE)
        assert sub["score"]    == 85
        assert sub["feedback"] == "Innovative use of AI."
        assert sub["judged"]   is True

    def test_score_is_clamped_to_0_100(self):
        c = make_contract()
        self._submit(c, ALICE, "https://github.com/alice/project")

        with patch("genlayer.gl.nondet.web.get_text", return_value="readme"), \
             patch("genlayer.gl.nondet.exec_prompt",
                   return_value=llm_response(150, "Way over")), \
             patch("genlayer.gl.eq_principle.prompt_comparative",
                   side_effect=fake_eq_principle_prompt_comparative):
            c.judge_project(ALICE)

        assert c.get_submission(ALICE)["score"] == 100

    def test_llm_response_with_code_fences_is_parsed(self):
        c = make_contract()
        self._submit(c, ALICE, "https://github.com/alice/project")

        fenced = "```json\n" + llm_response(70, "Decent.") + "\n```"

        with patch("genlayer.gl.nondet.web.get_text", return_value="readme"), \
             patch("genlayer.gl.nondet.exec_prompt", return_value=fenced), \
             patch("genlayer.gl.eq_principle.prompt_comparative",
                   side_effect=fake_eq_principle_prompt_comparative):
            c.judge_project(ALICE)

        assert c.get_submission(ALICE)["score"] == 70

    def test_judging_unsubmitted_participant_raises(self):
        c = make_contract()
        with pytest.raises(Exception, match="No submission found"):
            c.judge_project(ALICE)

    def test_double_judging_raises(self):
        c = make_contract()
        self._submit(c, ALICE, "https://github.com/alice/project")

        with patch("genlayer.gl.nondet.web.get_text", return_value="readme"), \
             patch("genlayer.gl.nondet.exec_prompt", return_value=llm_response(80)), \
             patch("genlayer.gl.eq_principle.prompt_comparative",
                   side_effect=fake_eq_principle_prompt_comparative):
            c.judge_project(ALICE)

            with pytest.raises(Exception, match="already been judged"):
                c.judge_project(ALICE)


# ── Distribute prizes ────────────────────────────────────────────────────

class TestDistributePrizes:

    def _setup_judged_contest(self, scores: dict):
        """
        Helper: deploy, fund, register + judge each participant in `scores`
        (a dict of address -> score). Returns the contract.
        """
        c = make_contract()
        with patch("genlayer.gl.message") as msg:
            msg.sender_address = ORGANIZER
            msg.value = POOL_WEI
            c.fund_pool()

        for addr, score in scores.items():
            with patch("genlayer.gl.message") as msg:
                msg.sender_address = addr
                msg.value = 0
                c.submit_project(f"https://github.com/{addr}/p")

            with patch("genlayer.gl.nondet.web.get_text", return_value="readme"), \
                 patch("genlayer.gl.nondet.exec_prompt",
                       return_value=llm_response(score)), \
                 patch("genlayer.gl.eq_principle.prompt_comparative",
                       side_effect=fake_eq_principle_prompt_comparative):
                c.judge_project(addr)

        return c

    def test_distribute_pays_top_3_in_order(self):
        c = self._setup_judged_contest({ALICE: 60, BOB: 95, CAROL: 80})

        proxies = {}
        def get_contract_at(addr):
            mock = MagicMock()
            proxies[str(addr)] = mock
            return mock

        with patch("genlayer.gl.get_contract_at", side_effect=get_contract_at), \
             patch("genlayer.gl.message") as msg:
            msg.sender_address = ORGANIZER
            msg.value = 0
            c.distribute_prizes()

        # BOB (95) -> 1st -> 50%, CAROL (80) -> 2nd -> 30%, ALICE (60) -> 3rd -> 20%
        assert proxies[BOB].transfer.call_args.kwargs["value"]   == POOL_WEI * 50 // 100
        assert proxies[CAROL].transfer.call_args.kwargs["value"] == POOL_WEI * 30 // 100
        assert proxies[ALICE].transfer.call_args.kwargs["value"] == POOL_WEI * 20 // 100
        for p in proxies.values():
            p.transfer.assert_called_once()
            assert p.transfer.call_args.kwargs["on"] == "finalized"

        assert c.get_status()["distributed"] is True

    def test_distribute_with_fewer_than_3_participants(self):
        c = self._setup_judged_contest({ALICE: 70, BOB: 90})

        proxies = {}
        def get_contract_at(addr):
            mock = MagicMock()
            proxies[str(addr)] = mock
            return mock

        with patch("genlayer.gl.get_contract_at", side_effect=get_contract_at), \
             patch("genlayer.gl.message") as msg:
            msg.sender_address = ORGANIZER
            msg.value = 0
            c.distribute_prizes()

        assert proxies[BOB].transfer.call_args.kwargs["value"]   == POOL_WEI * 50 // 100
        assert proxies[ALICE].transfer.call_args.kwargs["value"] == POOL_WEI * 30 // 100
        # No 3rd place — CAROL never participated, nothing to assert

    def test_non_organizer_cannot_distribute(self):
        c = self._setup_judged_contest({ALICE: 80})

        with pytest.raises(Exception, match="Only the organizer"):
            with patch("genlayer.gl.message") as msg:
                msg.sender_address = ALICE
                msg.value = 0
                c.distribute_prizes()

    def test_distribute_before_all_judged_raises(self):
        c = make_contract()
        with patch("genlayer.gl.message") as msg:
            msg.sender_address = ORGANIZER
            msg.value = POOL_WEI
            c.fund_pool()

        with patch("genlayer.gl.message") as msg:
            msg.sender_address = ALICE
            msg.value = 0
            c.submit_project("https://github.com/alice/p")
        # never judged

        with pytest.raises(Exception, match="not been judged yet"):
            with patch("genlayer.gl.message") as msg:
                msg.sender_address = ORGANIZER
                msg.value = 0
                c.distribute_prizes()

    def test_distribute_with_no_participants_raises(self):
        c = make_contract()
        with patch("genlayer.gl.message") as msg:
            msg.sender_address = ORGANIZER
            msg.value = POOL_WEI
            c.fund_pool()

        with pytest.raises(Exception, match="No participants"):
            with patch("genlayer.gl.message") as msg:
                msg.sender_address = ORGANIZER
                msg.value = 0
                c.distribute_prizes()

    def test_double_distribution_raises(self):
        c = self._setup_judged_contest({ALICE: 80})

        with patch("genlayer.gl.get_contract_at", return_value=MagicMock()), \
             patch("genlayer.gl.message") as msg:
            msg.sender_address = ORGANIZER
            msg.value = 0
            c.distribute_prizes()

        with pytest.raises(Exception, match="already been distributed"):
            with patch("genlayer.gl.message") as msg:
                msg.sender_address = ORGANIZER
                msg.value = 0
                c.distribute_prizes()

    def test_submission_closed_after_distribution(self):
        c = self._setup_judged_contest({ALICE: 80})

        with patch("genlayer.gl.get_contract_at", return_value=MagicMock()), \
             patch("genlayer.gl.message") as msg:
            msg.sender_address = ORGANIZER
            msg.value = 0
            c.distribute_prizes()

        with pytest.raises(Exception, match="Submissions are closed"):
            with patch("genlayer.gl.message") as msg:
                msg.sender_address = BOB
                msg.value = 0
                c.submit_project("https://github.com/bob/late")
