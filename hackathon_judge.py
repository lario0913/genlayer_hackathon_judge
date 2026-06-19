# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *
import json

# ═══════════════════════════════════════════════════════════════════════════
#  Hackathon Judge — AI-Powered Submission Scoring & Prize Distribution
#
#  Flow:
#   1. Organizer deploys with a rubric (plain-English judging criteria).
#   2. Organizer calls fund_pool() to deposit the prize pool in GEN.
#   3. Participants call submit_project(repo_url) with their GitHub repo.
#   4. Anyone calls judge_project(participant) — the contract fetches the
#      repo's README and uses an LLM to score it 0-100 against the rubric.
#      Validators reach consensus via the Prompt Comparative Equivalence
#      Principle (scores within 10 points = "equivalent").
#   5. Organizer calls distribute_prizes() — ranks all judged participants
#      and pays out 50% / 30% / 20% of the pool to the top 3.
#
#  IMPORTANT: gl.get_contract_at() targets other GenVM Intelligent Contracts.
#  Winners here are plain wallet addresses (EOAs) — sending value to an EOA
#  must go through the EVM ghost-contract layer instead, via a
#  @gl.evm.contract_interface wrapper. Using gl.get_contract_at() on an EOA
#  causes GenVM to attempt deploying a contract there, which fails.
# ═══════════════════════════════════════════════════════════════════════════

@gl.evm.contract_interface
class Wallet:
    """Minimal EVM interface used only to send plain GEN value to an
    address that may be a wallet (EOA) rather than a GenVM contract."""
    class View:
        pass

    class Write:
        pass


class HackathonJudge(gl.Contract):

    # ── State ────────────────────────────────────────────────────────────
    organizer:    str               # address of the contract deployer
    rubric:       str                # plain-English judging criteria
    prize_pool:   u256                # total GEN (wei) available for prizes
    distributed:  bool                # True once prizes have been paid out

    participants: DynArray[str]       # ordered list of participant addresses
    repo_urls:    TreeMap[str, str]   # address -> submitted repo URL
    scores:       TreeMap[str, u256]  # address -> score (0-100)
    feedback:     TreeMap[str, str]   # address -> one-line LLM feedback
    judged:       TreeMap[str, bool]  # address -> has been judged?

    # ── Constructor ──────────────────────────────────────────────────────
    def __init__(self, rubric: str) -> None:
        """
        Deploy the contest.

        Args:
            rubric: Plain-English description of what makes a winning
                    submission, e.g. "Judge on innovation (40%),
                    technical execution (40%), and presentation (20%)."
        """
        if rubric == "":
            raise gl.vm.UserError("Rubric cannot be empty")

        self.organizer   = str(gl.message.sender_address)
        self.rubric      = rubric
        self.prize_pool  = u256(0)
        self.distributed = False

    # ════════════════════════════════════════════════════════════════════
    #  FUND THE PRIZE POOL
    # ════════════════════════════════════════════════════════════════════

    @gl.public.write.payable
    def fund_pool(self) -> None:
        """Add GEN to the prize pool. Anyone may contribute, any time
        before distribution."""
        if self.distributed:
            raise gl.vm.UserError("Cannot fund after prizes are distributed")
        if gl.message.value == u256(0):
            raise gl.vm.UserError("Must send GEN (set value > 0)")

        self.prize_pool = self.prize_pool + gl.message.value

    # ════════════════════════════════════════════════════════════════════
    #  SUBMIT A PROJECT
    # ════════════════════════════════════════════════════════════════════

    @gl.public.write
    def submit_project(self, repo_url: str) -> None:
        """
        Register your submission. One submission per address.

        Args:
            repo_url: Public URL to your project's GitHub repository.
        """
        if self.distributed:
            raise gl.vm.UserError("Submissions are closed")
        if repo_url == "":
            raise gl.vm.UserError("repo_url cannot be empty")

        addr = str(gl.message.sender_address)

        if self.repo_urls.get(addr, "") != "":
            raise gl.vm.UserError("You have already submitted a project")

        self.repo_urls[addr] = repo_url
        self.judged[addr]    = False
        self.participants.append(addr)

    # ════════════════════════════════════════════════════════════════════
    #  JUDGE A PROJECT  (the core Intelligent Contract logic)
    # ════════════════════════════════════════════════════════════════════

    @gl.public.write
    def judge_project(self, participant: str) -> None:
        """
        Fetch a participant's repo and score it against the rubric
        using an LLM. Can be called by anyone (e.g. the organizer,
        or an automated judging bot) once per participant.

        Args:
            participant: address of the participant to judge.
        """
        if self.distributed:
            raise gl.vm.UserError("Judging is closed — prizes already distributed")

        repo_url = self.repo_urls.get(participant, "")
        if repo_url == "":
            raise gl.vm.UserError("No submission found for this participant")

        if self.judged.get(participant, False):
            raise gl.vm.UserError("This participant has already been judged")

        # Capture state needed inside the nondet block as plain variables —
        # storage (`self.*`) is not accessible from inside nondet functions.
        rubric_text = self.rubric

        # ── Non-deterministic block ────────────────────────────────────
        def nondet():
            readme = gl.nondet.web.render(repo_url, mode="text")

            prompt = f"""
You are judging a hackathon submission.

RUBRIC:
{rubric_text}

PROJECT README / REPOSITORY CONTENT:
{readme[:3000]}

Score this project from 0 to 100 based on how well it satisfies the rubric.
Respond using ONLY the following JSON format, nothing else:
{{"score": <integer 0-100>, "feedback": "<one sentence of feedback>"}}

It is mandatory that you respond only using the JSON format above.
Do not include any other words, explanation, or formatting.
"""
            res = gl.nondet.exec_prompt(prompt)
            res = res.replace("```json", "").replace("```", "").strip()
            data = json.loads(res)

            score = int(data["score"])
            score = max(0, min(100, score))  # clamp to valid range

            return {"score": score, "feedback": str(data["feedback"])}

        # ── Equivalence Principle ────────────────────────────────────────
        # Hackathon scoring is subjective — different validators may phrase
        # feedback differently or land on slightly different scores. We use
        # the Prompt Comparative principle: validators use an LLM to judge
        # whether the leader's result is an "equivalent" assessment of the
        # SAME project against the SAME rubric.
        result = gl.eq_principle.prompt_comparative(
            nondet,
            "The scores must be within 10 points of each other and both "
            "represent the same overall judgment of project quality "
            "relative to the rubric."
        )
        # ── End of non-deterministic block ──────────────────────────────

        # All storage writes happen after eq_principle returns
        self.scores[participant]   = u256(result["score"])
        self.feedback[participant] = result["feedback"]
        self.judged[participant]   = True

    # ════════════════════════════════════════════════════════════════════
    #  DISTRIBUTE PRIZES
    # ════════════════════════════════════════════════════════════════════

    @gl.public.write
    def distribute_prizes(self) -> None:
        """
        Rank all participants by score and pay out the prize pool.

        Splits: 1st = 50%, 2nd = 30%, 3rd = 20% of the pool.
        If fewer than 3 participants exist, remaining shares stay
        in the contract (can be reclaimed via fund_pool logic in a
        future version, or sent manually by the organizer).

        Only the organizer may call this. Requires every submitted
        project to have been judged first.
        """
        if str(gl.message.sender_address) != self.organizer:
            raise gl.vm.UserError("Only the organizer can distribute prizes")
        if self.distributed:
            raise gl.vm.UserError("Prizes have already been distributed")
        if len(self.participants) == 0:
            raise gl.vm.UserError("No participants to judge")

        # Ensure every participant has been judged
        for addr in self.participants:
            if not self.judged.get(addr, False):
                raise gl.vm.UserError(
                    f"Participant {addr} has not been judged yet"
                )

        # Build a plain Python list of (address, score) and sort it —
        # this is fully deterministic, so no nondet block is needed.
        ranked: list[tuple[str, int]] = []
        for addr in self.participants:
            ranked.append((addr, int(self.scores.get(addr, u256(0)))))

        ranked.sort(key=lambda pair: pair[1], reverse=True)

        # Prize split: 50% / 30% / 20% to the top 3
        splits = [50, 30, 20]
        pool   = int(self.prize_pool)

        for i in range(min(3, len(ranked))):
            addr, _score = ranked[i]
            payout = pool * splits[i] // 100
            if payout > 0:
                Wallet(Address(addr)).emit_transfer(value=u256(payout))

        self.distributed = True

    # ════════════════════════════════════════════════════════════════════
    #  VIEW METHODS
    # ════════════════════════════════════════════════════════════════════

    @gl.public.view
    def get_status(self) -> dict:
        """Overview of the contest."""
        return {
            "organizer":         self.organizer,
            "rubric":            self.rubric,
            "prize_pool_wei":    int(self.prize_pool),
            "participant_count": len(self.participants),
            "distributed":       self.distributed,
        }

    @gl.public.view
    def get_leaderboard(self) -> list:
        """Every participant with their submission, score, and feedback."""
        result = []
        for addr in self.participants:
            result.append({
                "address":  addr,
                "repo_url": self.repo_urls.get(addr, ""),
                "score":    int(self.scores.get(addr, u256(0))),
                "feedback": self.feedback.get(addr, ""),
                "judged":   self.judged.get(addr, False),
            })
        return result

    @gl.public.view
    def get_submission(self, addr: str) -> dict:
        """Details for a single participant."""
        return {
            "repo_url": self.repo_urls.get(addr, ""),
            "score":    int(self.scores.get(addr, u256(0))),
            "feedback": self.feedback.get(addr, ""),
            "judged":   self.judged.get(addr, False),
        }
