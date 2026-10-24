"""Smoke tests for tournament records and Perfect Game search filters."""

from datetime import datetime

from loadutil import load_module

tournament_data = load_module(
    "linedrive_tournament_data",
    "scraper/core/tournament_data.py",
)
filters_mod = load_module(
    "linedrive_pg_filters",
    "batch_scrapers/perfect_game/filters.py",
)
utils_mod = load_module(
    "linedrive_pg_utils",
    "batch_scrapers/perfect_game/utils.py",
)

Tournament = tournament_data.Tournament
TournamentData = tournament_data.TournamentData
PerfectGameFilters = filters_mod.PerfectGameFilters
FilterBuilder = filters_mod.FilterBuilder
PerfectGameUtils = utils_mod.PerfectGameUtils


def _tournament(id_, start_date, distance):
    return Tournament(
        id=id_,
        name=f"Tournament {id_}",
        age_group="10U",
        start_date=start_date,
        end_date=start_date,
        location="Houston, TX",
        city="Houston",
        state="TX",
        distance_miles=distance,
    )


def test_tournament_round_trip_and_validation():
    tournament = _tournament("pg-1", "2026-06-01", 12.5)
    as_dict = tournament.to_dict()
    assert as_dict["name"] == "Tournament pg-1"
    assert as_dict["distance_miles"] == 12.5
    assert TournamentData.validate_tournament_data(as_dict) is True

    missing_name = dict(as_dict)
    missing_name["name"] = ""
    assert TournamentData.validate_tournament_data(missing_name) is False
    assert TournamentData.validate_tournament_data({"id": "only-id"}) is False


def test_distance_filter_drops_unknown_and_far_events():
    nearby = _tournament("near", "2026-06-01", 12.0)
    far = _tournament("far", "2026-06-02", 40.0)
    unknown = _tournament("unknown", "2026-06-03", None)

    kept = TournamentData.filter_tournaments_by_distance(
        [nearby, far, unknown], max_distance=25
    )
    assert [item.id for item in kept] == ["near"]


def test_sort_by_start_date_and_search_result_shape():
    june = _tournament("june", "2026-06-01", 10)
    may = _tournament("may", "2026-05-01", 10)
    ordered = TournamentData.sort_tournaments_by_date([june, may])
    assert [item.id for item in ordered] == ["may", "june"]

    result = TournamentData.create_search_result(
        [may],
        search_filters={"age_group": "10U"},
        duration_seconds=1.234,
        total_found=5,
    )
    assert result["search_metadata"]["total_found"] == 5
    assert result["search_metadata"]["returned_count"] == 1
    assert result["search_metadata"]["duration_seconds"] == 1.23
    assert result["search_metadata"]["filters"] == {"age_group": "10U"}
    assert result["tournaments"][0]["id"] == "may"


def test_export_tournaments_to_json(tmp_path):
    destination = tmp_path / "tournaments.json"
    assert TournamentData.export_to_json(
        [_tournament("pg-1", "2026-06-01", 8)],
        str(destination),
    )
    text = destination.read_text(encoding="utf-8")
    assert "Tournament pg-1" in text


def test_perfect_game_filters_and_city_coordinates():
    created = PerfectGameFilters.create_filters(
        city="Dallas", age_group="12U", radius="30"
    )
    assert created["city"] == "Dallas"
    assert created["age_group"] == "12U"
    assert created["radius"] == 30
    assert created["state"] == "TX"

    validated = PerfectGameFilters.validate_filters({"radius": "10"})
    assert validated["radius"] == 10
    assert validated["city"] == "Houston"
    assert validated["lat"] == PerfectGameFilters.HOUSTON_COORDS["lat"]

    builder = FilterBuilder()
    builder.set_location("TX", "Austin", radius=40)
    builder.set_age_group("not-a-real-group")
    assert builder.get_filters()["age_group"] == "10U"
    builder.set_age_group("12U")
    builder.set_sport("Softball")
    current = builder.get_filters()
    assert current["city"] == "Austin"
    assert current["radius"] == 40
    assert current["lat"] == PerfectGameFilters.CITY_COORDS["austin"]["lat"]
    assert current["age_group"] == "12U"
    assert current["sport_type"] == "Softball"

    this_year = PerfectGameFilters.get_date_range_filters("this_year")
    assert this_year["end_date"].endswith("-12-31")
    next_month = PerfectGameFilters.get_date_range_filters("next_month")
    start = datetime.strptime(next_month["start_date"], "%Y-%m-%d")
    end = datetime.strptime(next_month["end_date"], "%Y-%m-%d")
    assert (end - start).days == 30


def test_perfect_game_name_cleanup_and_display():
    assert PerfectGameUtils.clean_tournament_name("  Spring   Classic  ") == (
        "Spring Classic"
    )
    long_name = "A" * 120
    cleaned = PerfectGameUtils.clean_tournament_name(long_name)
    assert cleaned.endswith("...")
    assert len(cleaned) == 100
    assert PerfectGameUtils.clean_tournament_name("") == ""

    record = {
        "name": "Spring Classic",
        "location": "Houston, TX",
        "age_groups": "10U",
        "date_start": "2026-06-01",
    }
    assert PerfectGameUtils.validate_tournament_data(record) is True
    assert PerfectGameUtils.validate_tournament_data({"name": "Spring Classic"}) is False

    display = PerfectGameUtils.format_tournament_display(record)
    assert "Spring Classic" in display
    assert "Houston, TX" in display

    summary = PerfectGameUtils.format_results_summary(
        {
            "success": True,
            "tournament_count": 2,
            "search_duration": 3,
            "filters_applied": {
                "city": "Houston",
                "state": "TX",
                "age_group": "10U",
                "sport_type": "Baseball",
            },
        }
    )
    assert "Found 2 tournaments" in summary
    failed = PerfectGameUtils.format_results_summary(
        {"success": False, "error": "timeout"}
    )
    assert "timeout" in failed
