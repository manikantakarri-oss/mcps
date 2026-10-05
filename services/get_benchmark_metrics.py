import json
import pandas as pd
import os


def normalize_objective_for_benchmark(raw_objective):
    """Return the objective key used by the benchmark workbook."""
    original_objective = str(raw_objective).strip().lower().rstrip("s")
    objective = original_objective.replace(" ", "_")

    if objective == "click":
        return "clicks"
    if objective == "impression":
        return "impressions"
    if objective == "view":
        return "video_views"
    if objective in ["video_view", "video view"]:
        return "video_views"
    if objective in ["app_install", "app install"]:
        return "app_installs"
    if objective in ["podcast_stream", "podcast stream"]:
        return "podcast_streams"
    if objective in ["website_visit", "website visit", "website_traffic", "website traffic"]:
        return "website_visits"
    if "app" in objective and "install" in objective:
        return "app_installs"
    if "podcast" in objective or ("stream" in objective and "podcast" not in objective):
        return "podcast_streams"
    if "video" in objective and "view" in objective:
        return "video_views"
    if "website" in objective and ("visit" in objective or "traffic" in objective):
        return "website_visits"
    if "page" in objective and "view" in objective:
        return "page_views"
    if objective in ["lead_gen", "lead_generation"]:
        return "lead_gen"
    if "lead" in objective and "gen" in objective:
        return "lead_gen"
    if objective in ["unset", "nan", "none", ""]:
        return "no_objective"
    return objective


def select_campaign_objective(df_ad_set):
    """Prefer the first meaningful objective instead of blindly using row 1."""
    if "campaign_objective" not in df_ad_set.columns or df_ad_set.empty:
        return ""

    objectives = df_ad_set["campaign_objective"].fillna("").astype(str).str.strip()
    meaningful = objectives[
        ~objectives.str.lower().isin(["", "unset", "nan", "none"])
    ]
    if not meaningful.empty:
        return meaningful.iloc[0]
    return objectives.iloc[0] if not objectives.empty else ""


def get_format_metric_benchmark(df_benchmark_metrics, ad_format, metric):
    """Return format-specific rows, falling back to the Overall format."""
    normalized_format = str(ad_format).strip().lower()
    if normalized_format == "image":
        normalized_format = "display"
    normalized_metric = str(metric).strip().lower()

    metric_mask = (
        df_benchmark_metrics["Metric"].astype(str).str.strip().str.lower()
        == normalized_metric
    )
    format_values = (
        df_benchmark_metrics["Ad Format"].astype(str).str.strip().str.lower()
    )
    rows = df_benchmark_metrics[metric_mask & (format_values == normalized_format)]
    if rows.empty:
        rows = df_benchmark_metrics[metric_mask & (format_values == "overall")]
    return rows



def get_benchmark_metrics(df_ad_set,country_insights):
    # print("inside bench marks function")
    # ✅ Dynamically resolve path relative to this file
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    standalones_dir = os.path.join(base_dir, "standalones")

    kpi_path = os.path.join(standalones_dir, "campaign_kpi_mapping.json")
    # kpi_path = os.path.join(standalones_dir, "kpi_mapping.json")
    # benchmark_path = os.path.join(standalones_dir, "Benchmarks.xlsx")
    benchmark_path = os.path.join(standalones_dir, "Benchmark_2026_Q2.xlsx")

    # Example usage
    print("KPI JSON path:", kpi_path)
    print("Benchmark Excel path:", benchmark_path)

    with open(kpi_path, "r") as f:
        kpi_mapping = json.load(f)

    df_benchmarks = pd.read_excel(benchmark_path)

    # Strip whitespace from string columns to avoid filtering issues
    string_columns = ["Objective", "Ad Format", "Region", "Metric", "Quarter", "revenue_source", "Filters Selected"]
    for col in string_columns:
        if col in df_benchmarks.columns:
            df_benchmarks[col] = df_benchmarks[col].apply(lambda x: x.strip() if isinstance(x, str) else x)

    # Get the original objective (for display in template)
    original_objective = select_campaign_objective(df_ad_set).lower().rstrip("s")

    # Map objective for benchmark lookup
    objective = normalize_objective_for_benchmark(original_objective)

    ad_format = str(df_ad_set["format"].iloc[0]).strip().lower()
    # Get unique ad formats (lowercased, stripped)
    ad_formats = (
        df_ad_set["format"].dropna().astype(str).str.strip().str.lower().unique().tolist()
    )

    # Map 'image' to 'display' for benchmark lookup
    ad_formats = ['display' if fmt == 'image' else fmt for fmt in ad_formats]

    # Get metrics from KPI mapping with default values if not found
    # Try original_objective first, then try with 's' appended for plural forms
    metrics = kpi_mapping.get(original_objective, {}).get(ad_format, None)
    if metrics is None:
        # Try plural form (add 's' back)
        metrics = kpi_mapping.get(original_objective + "s", {}).get(ad_format, None)
        if metrics is not None:
            print(f"KPI mapping: Tried '{original_objective}' not found, using '{original_objective}s'")

    if metrics is None:
        # Fallback to default metrics: Impressions and CPM
        print(f"KPI mapping: No metrics found for objective '{original_objective}' or '{original_objective}s' with format '{ad_format}'")
        print(f"Using default fallback metrics: Impressions, CPM")
        metrics = ["Impressions", "CPM"]

    # Ensure we always have 2 values
    if len(metrics) >= 2:
        metric_1, metric_2 = metrics[0], metrics[1]
    elif len(metrics) == 1:
        metric_1, metric_2 = metrics[0], "CPM"  # Default second metric to CPM
    else:
        metric_1, metric_2 = "Impressions", "CPM"  # Default fallback

    print(f"Final KPI metrics: metric_1={metric_1}, metric_2={metric_2}")

        # --- Example usage ---
    metric_col = "total_impressions"
    # Sort descending and get the first country
    region = (
        country_insights.sort_values(by=metric_col, ascending=False)
        .iloc[0]["region"]
    )

    print("region",region)
    # print("df_benchmarks df",df_benchmarks)
    # Check if objective exists in benchmarks, if not use NaN/null or "n/a" rows as fallback
    available_objectives = df_benchmarks["Objective"].str.strip().str.lower().unique()
    print("available_objectives",available_objectives)

    # Check if objective is no_objective or unset - use no_objective benchmarks with region filter
    if objective.lower().strip() == "no_objective":
        print(f"Objective is 'no_objective', using 'no_objective' benchmarks for region={region}")
        df_benchmark_metrics = df_benchmarks[
            (df_benchmarks["Objective"].str.strip().str.lower() == "no_objective") &
            (df_benchmarks["Ad Format"].str.strip().str.lower().isin(ad_formats)) &
            (df_benchmarks["Region"].str.strip().str.lower() == region.lower())
        ].reset_index(drop=True)
        print(f"'no_objective' benchmark results: {len(df_benchmark_metrics)} rows found")
    else:
        # Try to filter for the specific objective + format + region
        df_benchmark_metrics = df_benchmarks[
            (df_benchmarks["Objective"].str.strip().str.lower() == objective.lower().strip()) &
            (df_benchmarks["Ad Format"].str.strip().str.lower().isin(ad_formats)) &
            (df_benchmarks["Region"].str.strip().str.lower() == region.lower())
        ].reset_index(drop=True)

        print(f"Initial filter results: {len(df_benchmark_metrics)} rows found for objective='{objective}', formats={ad_formats}, region={region}")
        print("df_benchmark_metrics",df_benchmark_metrics)
       

        # Some objective buckets (notably VIDEO_VIEWS) only publish Video and
        # Overall format rows. Preserve the objective and use the Overall
        # format for the campaign region when its specific formats are absent.
        if df_benchmark_metrics.empty:
            df_benchmark_metrics = df_benchmarks[
                (df_benchmarks["Objective"].str.strip().str.lower() == objective.lower().strip()) &
                (df_benchmarks["Ad Format"].str.strip().str.lower() == "overall") &
                (df_benchmarks["Region"].str.strip().str.lower() == region.lower())
            ].reset_index(drop=True)
            if not df_benchmark_metrics.empty:
                print(
                    f"Using Overall-format benchmarks for objective='{objective}', "
                    f"region='{region}'"
                )

        # If the campaign region is not represented, retain the requested
        # objective and formats and use their Overall-region benchmark.
        if df_benchmark_metrics.empty:
            df_benchmark_metrics = df_benchmarks[
                (df_benchmarks["Objective"].str.strip().str.lower() == objective.lower().strip()) &
                (df_benchmarks["Ad Format"].str.strip().str.lower().isin(ad_formats)) &
                (df_benchmarks["Region"].str.strip().str.lower() == "overall")
            ].reset_index(drop=True)
            if not df_benchmark_metrics.empty:
                print(
                    f"Using Overall-region benchmarks for objective='{objective}', "
                    f"formats={ad_formats}"
                )

        # Last objective-specific fallback: Overall format and region.
        if df_benchmark_metrics.empty:
            df_benchmark_metrics = df_benchmarks[
                (df_benchmarks["Objective"].str.strip().str.lower() == objective.lower().strip()) &
                (df_benchmarks["Ad Format"].str.strip().str.lower() == "overall") &
                (df_benchmarks["Region"].str.strip().str.lower() == "overall")
            ].reset_index(drop=True)
            if not df_benchmark_metrics.empty:
                print(f"Using Overall-format/region benchmarks for objective='{objective}'")

        # If no objective-specific rows exist for either the campaign or
        # Overall region, use the generic fallback.
        if df_benchmark_metrics.empty:
            print(f"Objective '{objective}' not found for format={ad_formats} and region={region}")
            print(f"Using fallback: 'no_objective' benchmarks for region={region}")
            df_benchmark_metrics = df_benchmarks[
                (df_benchmarks["Objective"].str.strip().str.lower() == "no_objective") &
                (df_benchmarks["Ad Format"].str.strip().str.lower().isin(ad_formats)) &
            (df_benchmarks["Region"].str.strip().str.lower() == region.lower())
            ].reset_index(drop=True)
            print(f"'no_objective' fallback results: {len(df_benchmark_metrics)} rows found")

            if not df_benchmark_metrics.empty:
                print(f"Fallback - Available formats: {df_benchmark_metrics['Ad Format'].unique().tolist()}")
                print(f"Fallback - Available metrics: {df_benchmark_metrics['Metric'].unique().tolist()}")

    return metric_1,metric_2,df_benchmark_metrics,kpi_mapping

# import json
# import pandas as pd
# import os



# def get_benchmark_metrics(df_ad_set,country_insights):
#     # print("inside bench marks function")
#     # ✅ Dynamically resolve path relative to this file
#     base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#     standalones_dir = os.path.join(base_dir, "standalones")

#     # kpi_path = os.path.join(standalones_dir, "campaign_kpi_mapping.json")
#     # kpi_path = os.path.join(standalones_dir, "kpi_mapping.json")
#     benchmark_path = os.path.join(standalones_dir, "Benchmark_2025_Q4.xlsx")
#     # benchmark_path = os.path.join(standalones_dir, "Benchmark_2025_Q4.xlsx")

#     # Example usage
#     # print("KPI JSON path:", kpi_path)
#     print("Benchmark Excel path:", benchmark_path)

#     # with open(kpi_path, "r") as f:
#     #     kpi_mapping = json.load(f)

#     # Read the 2025_Q4 sheet from the benchmark file
#     df_benchmarks = pd.read_excel(benchmark_path)

#     # Strip whitespace from string columns to avoid filtering issues (preserve NaN values)
#     string_columns = ["Objective", "Ad Format", "Region", "Metric", "Quarter", "revenue_source"]
#     for col in string_columns:
#         if col in df_benchmarks.columns:
#             # Only strip non-NaN values to preserve NaN for fallback logic
#             df_benchmarks[col] = df_benchmarks[col].apply(lambda x: x.strip() if isinstance(x, str) else x)

#     print("df_benchmarks",df_benchmarks)
    

#     # Get the original objective (for display in template)
#     original_objective = str(df_ad_set["campaign_objective"].iloc[0]).strip().lower().rstrip("s")
#     print("original_objective",original_objective)
#     # Map objective for benchmark lookup
#     objective = original_objective

#     # Map "streams" or "podcast streams" to "podcast stream" for benchmark lookup
#     if objective in ["streams", "podcast streams", "podcast stream"]:
#         objective = "podcast stream"
#     if objective.lower() in ["page views", "views"]:
#         objective="view"

#     ad_format = str(df_ad_set["format"].iloc[0]).lower()
#     # Get unique ad formats (lowercased, stripped)
#     ad_formats = df_ad_set["format"].dropna().str.lower().unique().tolist()

#     # Map "image" format to "display" for benchmark lookup
#     ad_formats_for_benchmark = []
#     for fmt in ad_formats:
#         if fmt == "image":
#             ad_formats_for_benchmark.append("display")
#             print(f"Mapping format '{fmt}' to 'display' for benchmark lookup")
#         else:
#             ad_formats_for_benchmark.append(fmt)

#     # Get metrics from KPI mapping with default values if not found
#     # Try original_objective first, then try with 's' appended for plural forms
#     # metrics = kpi_mapping.get(original_objective, {}).get(ad_format, None)
#     # if metrics is None:
#     #     # Try plural form (add 's' back)
#     #     metrics = kpi_mapping.get(original_objective + "s", {}).get(ad_format, None)
#     #     if metrics is not None:
#     #         print(f"KPI mapping: Tried '{original_objective}' not found, using '{original_objective}s'")

#     # if metrics is None:
#     #     # Fallback to default metrics: Impressions and CPM
#     #     print(f"KPI mapping: No metrics found for objective '{original_objective}' or '{original_objective}s' with format '{ad_format}'")
#     #     print(f"Using default fallback metrics: Impressions, CPM")
#     #     metrics = ["Impressions", "CPM"]

#     # Ensure we always have 2 values
#     # if len(metrics) >= 2:
#     #     metric_1, metric_2 = metrics[0], metrics[1]
#     # elif len(metrics) == 1:
#     #     metric_1, metric_2 = metrics[0], "CPM"  # Default second metric to CPM
#     # else:
#     #     metric_1, metric_2 = "Impressions", "CPM"  # Default fallback

#     # print(f"Final KPI metrics: metric_1={metric_1}, metric_2={metric_2}")

#         # --- Example usage ---
#     metric_col = "total_impressions"
#     # Sort descending and get the first country
#     region = (
#         country_insights.sort_values(by=metric_col, ascending=False)
#         .iloc[0]["region"]
#     )
#     print("region",region)

#     # Special handling for "image" and "display" objectives - search by format instead
#     if objective.lower() in ["image", "display"]:
#         print(f"Objective is '{objective}' - searching benchmarks by format instead")
#         # For image/display objectives, search by the ad format (use display for image)
#         df_benchmark_metrics = df_benchmarks[
#             (df_benchmarks["Ad Format"].str.lower().isin(ad_formats_for_benchmark)) &
#             (df_benchmarks["Region"].str.lower() == region.lower())
#         ].reset_index(drop=True)
#     else:
#         # Check if objective exists in benchmarks, if not use NaN/null rows as fallback
#         available_objectives = df_benchmarks["Objective"].dropna().str.lower().unique()
#         print("available_objectives",available_objectives)
#         if objective.lower() not in available_objectives:
#             print(f"Objective '{objective}' not found in benchmarks. Available objectives: {available_objectives}")
#             print(f"Using fallback: rows with null/NaN objective values")

#             # Filter benchmarks with NaN objective (fallback)
#             df_benchmark_metrics = df_benchmarks[
#                 (df_benchmarks["Objective"].isna()) &
#                 (df_benchmarks["Ad Format"].str.lower().isin(ad_formats_for_benchmark)) &
#                 (df_benchmarks["Region"].str.lower() == region.lower())
#             ].reset_index(drop=True)
#         else:
#             # Filter benchmarks for the objective
#             df_benchmark_metrics = df_benchmarks[
#                 (df_benchmarks["Objective"].str.lower() == objective.lower()) &
#                 (df_benchmarks["Ad Format"].str.lower().isin(ad_formats_for_benchmark)) &
#                 (df_benchmarks["Region"].str.lower() == region.lower())
#             ].reset_index(drop=True)
#             print("df_benchmark_metrics",df_benchmark_metrics)

#     return df_benchmark_metrics


# # import json
# # import pandas as pd
# # import os



# # def get_benchmark_metrics(df_ad_set,country_insights):
# #     # print("inside bench marks function")
# #     # ✅ Dynamically resolve path relative to this file
# #     base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  
# #     standalones_dir = os.path.join(base_dir, "standalones")

# #     kpi_path = os.path.join(standalones_dir, "kpi_mapping.json")
# #     benchmark_path = os.path.join(standalones_dir, "Benchmarks.xlsx")

# #     # Example usage
# #     print("KPI JSON path:", kpi_path)
# #     print("Benchmark Excel path:", benchmark_path)

# #     with open(kpi_path, "r") as f:
# #         kpi_mapping = json.load(f)
    
# #     df_benchmarks = pd.read_excel(benchmark_path)

# #     objective = str(df_ad_set["campaign_objective"].iloc[0]).strip().lower().rstrip("s")
# #     ad_format = str(df_ad_set["format"].iloc[0]).lower()
# #     # Get unique ad formats (lowercased, stripped)
# #     ad_formats = df_ad_set["format"].dropna().str.lower().unique().tolist()

# #     metric_1,metric_2  = kpi_mapping.get(objective, {}).get(ad_format, [])

# #         # --- Example usage ---
# #     metric_col = "total_impressions"
# #     # Sort descending and get the first country
# #     region = (
# #         country_insights.sort_values(by=metric_col, ascending=False)
# #         .iloc[0]["region"]
# #     )


# #     # Filter benchmarks for multiple formats
# #     df_benchmark_metrics = df_benchmarks[
# #         (df_benchmarks["Objective"].str.lower() == objective.lower()) &
# #         (df_benchmarks["Ad Format"].str.lower().isin(ad_formats)) &
# #         (df_benchmarks["Region"].str.lower() == region.lower())
# #     ].reset_index(drop=True)


# #     return metric_1,metric_2,df_benchmark_metrics,kpi_mapping
