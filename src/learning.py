"""Learn from human review: which blanks reviewers have repeatedly accepted, so they stop escalating."""
from collections import Counter

MIN_VOTES = 2  # a rule is only trusted once this many reviewers' decisions agree


def blank_votes(decisions: dict[str, dict]) -> Counter:
    """How many decisions accepted a blank SI value, per field."""
    votes: Counter = Counter()
    for d in decisions.values():
        if d.get("reason") == "blank_acceptable":
            votes.update(set(d.get("accepted_blanks") or []))
    return votes


def learned_blank_fields(decisions: dict[str, dict], min_votes: int = MIN_VOTES) -> set[str]:
    return {f for f, n in blank_votes(decisions).items() if n >= min_votes}
