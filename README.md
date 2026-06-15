What We're Building
A hackathon judging contract that:

The organizer deploys with a rubric — plain English judging criteria, e.g. "Judge on innovation (50%) and code quality (50%)"
The organizer funds a prize pool in GEN
Participants submit their GitHub repo URL
Anyone calls judge_project() — the contract fetches the repo's README, sends it to an LLM along with the rubric, and gets back a 0-100 score and one-line feedback
Once everyone is judged, the organizer calls distribute_prizes() — the contract ranks all submissions and automatically pays out 50% / 30% / 20% to the top 3

No human judges. No spreadsheet. No manual wire transfers. The scoring, ranking, and payout all happen inside the Intelligent Contract.
