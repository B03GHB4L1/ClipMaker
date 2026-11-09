import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from team_names import name_score, resolve_home_away, team_options  # noqa: E402


class TeamNameTests(unittest.TestCase):
    def test_scoresway_short_labels_map_to_full_event_names(self):
        # Events list Paris first; event order must not decide home and away.
        teams = ["Paris Saint-Germain FC", "Stade Rennais FC"]
        self.assertEqual(resolve_home_away("Rennes", "Paris SG", teams),
                         ("Stade Rennais FC", "Paris Saint-Germain FC"))

    def test_accented_and_suffixed_names(self):
        self.assertEqual(resolve_home_away("Lyon", "Fenerbahçe", ["Fenerbahçe SK", "Lyon"]),
                         ("Lyon", "Fenerbahçe SK"))

    def test_exact_names_and_unrelated_labels(self):
        self.assertEqual(resolve_home_away("Chelsea", "Arsenal", ["Arsenal", "Chelsea"]), ("Chelsea", "Arsenal"))
        self.assertEqual(resolve_home_away("", "", ["B", "A"]), ("B", "A"))
        self.assertEqual(resolve_home_away("Home", "", ["Visitors", "Home"]), ("Home", "Visitors"))
        self.assertEqual(name_score("Rennes", "Paris Saint-Germain FC"), 0)

    def test_similar_clubs_are_not_confused(self):
        self.assertEqual(resolve_home_away("Man Utd", "Man City", ["Manchester City", "Manchester United"]),
                         ("Manchester United", "Manchester City"))

    def test_options_drop_label_aliases_but_keep_opponents_without_events(self):
        self.assertEqual(team_options([("Rennes", "Paris SG", ["Paris Saint-Germain FC", "Stade Rennais FC"])]),
                         ["Stade Rennais FC", "Paris Saint-Germain FC"])
        self.assertEqual(team_options([("Home", "Away", ["Home"]), ("Home", "Third", ["Third"])]),
                         ["Home", "Away", "Third"])


if __name__ == "__main__":
    unittest.main()
