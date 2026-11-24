"""Match a fixture's home/away labels to the team names used on its events.

Scoresway files store short fixture labels ("Rennes", "Paris SG") while each
event carries the full club name ("Stade Rennais FC", "Paris Saint-Germain FC").
Plain equality or substring checks fail on those, which swapped home and away
in the Analyst Room and left label-only teams with no events in the Tactical Lab.
"""
from __future__ import annotations

import re
import unicodedata

_GENERIC = {"fc", "cf", "sc", "ac", "afc", "sk", "club", "de", "the", "and", "football", "calcio"}


def _tokens(name: str) -> list[str]:
    text = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode("ascii").casefold()
    return [token for token in re.split(r"[^a-z0-9]+", text) if token]


def _token_matches(label_token: str, team_tokens: list[str]) -> bool:
    for token in team_tokens:
        if label_token == token:
            return True
        # Shared stem of four or more letters: "rennes" ~ "rennais", "lyon" ~ "lyonnais".
        shared = 0
        for left, right in zip(label_token, token):
            if left != right:
                break
            shared += 1
        if shared >= 4:
            return True
    # Initials of consecutive words: "sg" ~ "saint germain", "psg" ~ "paris saint germain".
    if 2 <= len(label_token) <= 4:
        initials = "".join(token[0] for token in team_tokens)
        if label_token in initials:
            return True
    return False


def name_score(label: str, team: str) -> float:
    """Return how well a fixture label names an event team (0 means no match)."""
    label_norm, team_norm = str(label).casefold().strip(), str(team).casefold().strip()
    if not label_norm or not team_norm:
        return 0.0
    if label_norm == team_norm:
        return 100.0
    if label_norm in team_norm or team_norm in label_norm:
        return 50.0
    label_tokens = [t for t in _tokens(label) if t not in _GENERIC] or _tokens(label)
    team_tokens = _tokens(team)
    if not label_tokens or not team_tokens:
        return 0.0
    matched = sum(_token_matches(token, team_tokens) for token in label_tokens)
    return 10.0 * matched / len(label_tokens) if matched else 0.0


def team_options(matches) -> list[str]:
    """Selectable teams across matches, home then away per match.

    ``matches`` yields ``(home_label, away_label, event_teams)``. A label is
    replaced by the event team it names; a label naming no event team is kept,
    so an opponent without recorded events stays selectable.
    """
    options = []
    for home_label, away_label, event_teams in matches:
        teams = [str(team).strip() for team in event_teams if str(team).strip()]
        chosen = []
        if len(teams) >= 2:
            home, away = resolve_home_away(home_label, away_label, teams)
            pairs = ((home_label, home), (away_label, away))
        else:
            pairs = ((home_label, ""), (away_label, ""))
        for label, team in pairs:
            label = str(label or "").strip()
            if team and (not label or name_score(label, team)):
                chosen.append(team)
                continue
            match = max(teams, key=lambda candidate: name_score(label, candidate), default="")
            chosen.append(match if label and match and name_score(label, match) else label)
        for name in [*chosen, *teams]:
            if name and name not in options:
                options.append(name)
    return options


def resolve_home_away(home_label: str, away_label: str, event_teams: list[str]) -> tuple[str, str]:
    """Map fixture labels onto distinct event team names, preserving event order as fallback."""
    teams = [str(team) for team in event_teams if str(team)]
    if len(teams) < 2:
        return tuple((teams + ["", ""])[:2])
    best = (0.0, "", "")
    for home in teams:
        for away in teams:
            if home == away:
                continue
            score = name_score(home_label, home) + name_score(away_label, away)
            if score > best[0]:
                best = (score, home, away)
    home, away = best[1], best[2]
    if best[0] and not name_score(home_label, home):
        home = ""
    if best[0] and not name_score(away_label, away):
        away = ""
    remaining = [team for team in teams if team not in {home, away}]
    if not home and remaining:
        home = remaining.pop(0)
    if not away and remaining:
        away = remaining.pop(0)
    return home, away
