import unittest

from convertcord.football import FootballService, _fmt_ts


class FootballTimestampTests(unittest.TestCase):
    def test_fmt_ts_returns_none_for_none(self) -> None:
        self.assertIsNone(_fmt_ts(None))

    def test_fmt_ts_returns_none_for_empty(self) -> None:
        self.assertIsNone(_fmt_ts(""))

    def test_fmt_ts_parses_iso(self) -> None:
        result = _fmt_ts("2026-06-12T20:00:00Z")
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("<t:"))

    def test_fmt_ts_returns_raw_on_bad_value(self) -> None:
        self.assertEqual(_fmt_ts("not-a-date"), "not-a-date")


class FormatMatchesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fb = FootballService.__new__(FootballService)

    def test_format_matches_shows_upcoming(self) -> None:
        data = {
            "matches": [
                {"homeTeam": {"name": "Brazil"}, "awayTeam": {"name": "Argentina"}, "utcDate": "2099-06-01T20:00:00Z", "matchday": 1, "status": "TIMED"},
            ],
        }
        result = self.fb.format_matches(data)
        self.assertIsNotNone(result)
        if result:
            self.assertIn("Brazil", result)
            self.assertIn("Argentina", result)

    def test_format_matches_ignores_finished(self) -> None:
        data = {
            "matches": [
                {"homeTeam": {"name": "A", "id": 1}, "awayTeam": {"name": "B", "id": 2}, "utcDate": "2020-01-01T20:00:00Z", "matchday": 1, "status": "FINISHED"},
            ],
        }
        result = self.fb.format_matches(data)
        self.assertIsNotNone(result)
        if result:
            self.assertIn("No upcoming matches", result)

    def test_format_matches_returns_none_for_empty(self) -> None:
        self.assertIsNone(self.fb.format_matches({"matches": []}))


class FormatStandingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fb = FootballService.__new__(FootballService)

    def test_format_standings_shows_groups(self) -> None:
        data = {
            "standings": [
                {
                    "group": "Group A",
                    "table": [
                        {"position": 1, "team": {"name": "Brazil", "id": 1}, "playedGames": 2, "won": 2, "draw": 0, "lost": 0, "points": 6, "goalDifference": 4},
                        {"position": 2, "team": {"name": "Argentina", "id": 2}, "playedGames": 2, "won": 1, "draw": 0, "lost": 1, "points": 3, "goalDifference": 1},
                    ],
                },
            ],
        }
        result = self.fb.format_standings(data)
        self.assertIsNotNone(result)
        if result:
            self.assertIn("Group A", result)
            self.assertIn("Brazil", result)
            self.assertIn("Argentina", result)
            self.assertIn("6pts", result)

    def test_format_standings_returns_none_for_empty(self) -> None:
        self.assertIsNone(self.fb.format_standings({"standings": []}))


class FormatTeamFullTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fb = FootballService.__new__(FootballService)

    def test_format_team_full_with_standings_and_match(self) -> None:
        info = {
            "team": {"name": "Brazil", "tla": "BRA"},
            "standings_entry": {"group": "Group A", "position": 1, "points": 6, "won": 2, "draw": 0, "lost": 0, "goalDifference": 3},
            "next_match": {"homeTeam": {"name": "Brazil"}, "awayTeam": {"name": "Argentina"}, "utcDate": "2099-06-01T20:00:00Z", "matchday": 3, "status": "TIMED"},
        }
        result = self.fb.format_team_full(info)
        self.assertIn("Brazil", result)
        self.assertIn("BRA", result)
        self.assertIn("Group A", result)
        self.assertIn("#1", result)
        self.assertIn("6pts", result)
        self.assertIn("Argentina", result)
        self.assertIn("MD3", result)

    def test_format_team_full_minimal(self) -> None:
        info = {"team": {"name": "Test FC"}}
        result = self.fb.format_team_full(info)
        self.assertIn("Test FC", result)

    def test_format_team_full_no_upcoming(self) -> None:
        info = {"team": {"name": "Brazil", "tla": "BRA"}, "standings_entry": None, "next_match": None}
        result = self.fb.format_team_full(info)
        self.assertIn("No upcoming matches", result)


class FormatNextMatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fb = FootballService.__new__(FootballService)

    def test_format_next_match_with_match(self) -> None:
        team = {"name": "Brazil"}
        match = {"homeTeam": {"name": "Brazil"}, "awayTeam": {"name": "Argentina"}, "utcDate": "2099-06-01T20:00:00Z", "matchday": 3, "status": "TIMED"}
        result = self.fb.format_next_match(team, match)
        self.assertIn("Brazil", result)
        self.assertIn("Argentina", result)
        self.assertIn("Matchday", result)

    def test_format_next_match_no_match(self) -> None:
        team = {"name": "Brazil"}
        result = self.fb.format_next_match(team, None)
        self.assertIn("No upcoming matches", result)


class FormatLiveScoresTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fb = FootballService.__new__(FootballService)

    def test_format_live_scores_shows_scores(self) -> None:
        matches = [
            {
                "homeTeam": {"name": "Brazil"},
                "awayTeam": {"name": "Argentina"},
                "score": {"fullTime": {"home": 2, "away": 1}, "halfTime": {"home": 1, "away": 0}},
                "status": "IN_PLAY",
                "matchday": 3,
                "minute": "78",
                "goals": [
                    {"type": "GOAL", "minute": 23, "scorer": {"name": "Vinicius"}, "team": {"name": "Brazil"}},
                    {"type": "GOAL", "minute": 45, "extraTime": 2, "scorer": {"name": "Messi"}, "team": {"name": "Argentina"}},
                    {"type": "GOAL", "minute": 67, "scorer": {"name": "Neymar"}, "team": {"name": "Brazil"}},
                ],
            },
        ]
        result = self.fb.format_live_scores(matches)
        self.assertIn("Brazil", result)
        self.assertIn("Argentina", result)
        self.assertIn("2 – 1", result)
        self.assertIn("78'", result)
        self.assertIn("HT 1-0", result)
        self.assertIn("MD3", result)
        self.assertIn("Vinicius 23'", result)
        self.assertIn("Messi 45+2'", result)
        self.assertIn("Neymar 67'", result)

    def test_format_live_scores_multiple(self) -> None:
        matches = [
            {"homeTeam": {"name": "A"}, "awayTeam": {"name": "B"}, "score": {"fullTime": {"home": 1, "away": 1}}, "status": "IN_PLAY", "matchday": 1},
            {"homeTeam": {"name": "C"}, "awayTeam": {"name": "D"}, "score": {"fullTime": {"home": 0, "away": 0}}, "status": "PAUSED", "matchday": 1},
        ]
        result = self.fb.format_live_scores(matches)
        self.assertIn("A", result)
        self.assertIn("C", result)
        self.assertIn("PAUSED", result)
        self.assertIn("1 – 1", result)
        self.assertIn("0 – 0", result)


class LiveScoresEmbedDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fb = FootballService.__new__(FootballService)

    def test_live_scores_embed_without_stats(self) -> None:
        matches = [
            {
                "homeTeam": {"name": "Brazil"},
                "awayTeam": {"name": "Argentina"},
                "score": {"fullTime": {"home": 1, "away": 0}},
                "status": "IN_PLAY",
                "matchday": 1,
                "minute": "30",
                "goals": [],
            },
        ]
        rows = self.fb.live_scores_embed_data(matches)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["home"], "Brazil")
        self.assertEqual(rows[0]["stats"], {})

    def test_live_scores_embed_with_stats(self) -> None:
        matches = [
            {
                "homeTeam": {"name": "Brazil"},
                "awayTeam": {"name": "Argentina"},
                "score": {"fullTime": {"home": 1, "away": 0}},
                "status": "IN_PLAY",
                "matchday": 1,
                "minute": "30",
                "goals": [],
                "statistics": [
                    {"type": "Ball Possession", "home": "55", "away": "45"},
                    {"type": "Shots", "home": "8", "away": "5"},
                    {"type": "Shots on Goal", "home": "3", "away": "2"},
                    {"type": "Corner Kicks", "home": "4", "away": "3"},
                    {"type": "Fouls", "home": "10", "away": "14"},
                ],
            },
        ]
        rows = self.fb.live_scores_embed_data(matches)
        self.assertEqual(len(rows), 1)
        stats = rows[0]["stats"]
        self.assertEqual(stats["ball_possession"]["home"], 55)
        self.assertEqual(stats["ball_possession"]["away"], 45)
        self.assertEqual(stats["shots"]["home"], 8)
        self.assertEqual(stats["shots_on_goal"]["away"], 2)

    def test_format_live_scores_with_stats(self) -> None:
        matches = [
            {
                "homeTeam": {"name": "Brazil"},
                "awayTeam": {"name": "Argentina"},
                "score": {"fullTime": {"home": 2, "away": 1}},
                "status": "IN_PLAY",
                "matchday": 3,
                "minute": "75",
                "goals": [],
                "statistics": [
                    {"type": "Ball Possession", "home": "60", "away": "40"},
                    {"type": "Shots on Goal", "home": "4", "away": "2"},
                    {"type": "Shots", "home": "10", "away": "6"},
                ],
            },
        ]
        result = self.fb.format_live_scores(matches)
        self.assertIn("Poss: 60%–40%", result)
        self.assertIn("SOT: 4–2", result)
        self.assertIn("Shots: 10–6", result)
        self.assertIn("2 – 1", result)
        self.assertIn("75'", result)


if __name__ == "__main__":
    unittest.main()
