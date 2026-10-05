import pytest
import pandas as pd

from services.get_benchmark_metrics import (
    get_format_metric_benchmark,
    get_benchmark_metrics,
    normalize_objective_for_benchmark,
    select_campaign_objective,
)


@pytest.mark.parametrize("objective", ["view", "views", "VIEW", " Views "])
def test_view_objectives_use_video_views_benchmarks(objective):
    assert normalize_objective_for_benchmark(objective) == "video_views"


@pytest.mark.parametrize(
    "objective",
    ["website traffic", "website_traffic", "website visit", "website visits"],
)
def test_website_objectives_use_website_visits_benchmarks(objective):
    assert normalize_objective_for_benchmark(objective) == "website_visits"


@pytest.mark.parametrize(
    "objective",
    ["Lead_gen", "lead gen", "lead generation", "lead_generation"],
)
def test_lead_gen_objectives_use_lead_gen_benchmarks(objective):
    assert normalize_objective_for_benchmark(objective) == "lead_gen"


@pytest.mark.parametrize(
    ("input_objective", "workbook_objective", "region"),
    [
        ("views", "video_views", "US+CA"),
        ("website traffic", "website_visits", "US+CA"),
        ("Lead_gen", "lead_gen", "Europe"),
    ],
)
def test_requested_objectives_return_matching_workbook_rows(input_objective, workbook_objective, region):
    ad_sets = pd.DataFrame({"campaign_objective": [input_objective], "format": ["video"]})
    countries = pd.DataFrame({"total_impressions": [1], "region": [region]})

    _, _, benchmarks, _ = get_benchmark_metrics(ad_sets, countries)

    assert not benchmarks.empty
    assert set(benchmarks["Objective"].str.strip().str.lower()) == {workbook_objective}


def test_views_uses_overall_region_video_benchmark_when_campaign_region_is_missing():
    ad_sets = pd.DataFrame({"campaign_objective": ["views"], "format": [" Video "]})
    countries = pd.DataFrame({"total_impressions": [1], "region": ["SAMEA"]})

    _, _, benchmarks, _ = get_benchmark_metrics(ad_sets, countries)

    assert not benchmarks.empty
    assert set(benchmarks["Objective"].str.strip().str.lower()) == {"video_views"}
    assert set(benchmarks["Ad Format"].str.strip().str.lower()) == {"video"}
    assert set(benchmarks["Region"].str.strip().str.lower()) == {"overall"}


def test_views_is_selected_when_an_unset_ad_set_appears_first():
    ad_sets = pd.DataFrame(
        {
            "campaign_objective": ["UNSET", "views"],
            "format": ["video", "video"],
        }
    )
    countries = pd.DataFrame({"total_impressions": [1], "region": ["US+CA"]})

    _, _, benchmarks, _ = get_benchmark_metrics(ad_sets, countries)

    assert select_campaign_objective(ad_sets) == "views"
    assert not benchmarks.empty
    assert set(benchmarks["Objective"].str.strip().str.lower()) == {"video_views"}


def test_views_uses_overall_format_benchmark_for_image_and_audio_campaign():
    ad_sets = pd.DataFrame(
        {
            "campaign_objective": ["views", "views"],
            "format": ["image", "audio"],
        }
    )
    countries = pd.DataFrame({"total_impressions": [1], "region": ["Europe"]})

    _, _, benchmarks, _ = get_benchmark_metrics(ad_sets, countries)

    assert not benchmarks.empty
    assert set(benchmarks["Objective"].str.strip().str.lower()) == {"video_views"}
    assert set(benchmarks["Ad Format"].str.strip().str.lower()) == {"overall"}
    assert set(benchmarks["Region"].str.strip().str.lower()) == {"europe"}
    assert not get_format_metric_benchmark(
        benchmarks, "image", "click-through rate"
    ).empty
    assert not get_format_metric_benchmark(
        benchmarks, "audio", "completion rate"
    ).empty
