import pandas as pd
from typing import Dict, Any, Tuple
from .get_campaign_insights_data import campaign_insights_data
from .get_region import get_region
from .get_benchmark_metrics import get_benchmark_metrics, get_format_metric_benchmark
from .get_ppt_report import get_ppt_report
from datetime import datetime, timedelta
from pptx import Presentation
import re
from pathlib import Path
from io import BytesIO
import uuid



class MidcampaignPdfService:
    def generate_report(self, df_dict: Dict[str, pd.DataFrame]) -> Dict[str, Any]:

        def format_schedule(start, end):
            # If dates are in different years: May 19 2025 - May 1 2026
            # If dates are in same year: May 19 - Nov 20 2025
            if start.year != end.year:
                # Different years - show both years
                start_str = f"{start.strftime('%b')} {start.day} {start.year}"
                end_str = f"{end.strftime('%b')} {end.day} {end.year}"
            else:
                # Same year - show year only at the end
                start_str = f"{start.strftime('%b')} {start.day}"
                end_str = f"{end.strftime('%b')} {end.day} {end.year}"
            return f"{start_str} - {end_str}"

 
        def _extract_number_and_currency(val: Any) -> Tuple[float, str]:
            """
            Extract (number, currency_code_or_symbol) from val.
            Handles messy inputs like '1,800', '1800 USD', 'USD 1800', '$1800'.
            Returns ('', '') when not found.
            """
            if val is None or (isinstance(val, float) and pd.isna(val)):
                return 0.0, ""

            s = str(val).strip()
            if not s:
                return 0.0, ""

            # remove common thousand separators
            s = s.replace(",", "").replace("\u00A0", "").strip()

            # Normalize parentheses "1800 (USD)" -> "1800 USD"
            s = re.sub(r"[()\[\]]", " ", s)

            # Regex patterns to capture numbers and 2–4 letter currency codes
            patterns = [
                r'^(?P<code>[A-Za-z]{2,4})\s*(?P<num>-?\d+(\.\d+)?)$',   # USD 1800
                r'^(?P<num>-?\d+(\.\d+)?)\s*(?P<code>[A-Za-z]{2,4})$',   # 1800 USD
                r'^(?P<code>[A-Za-z]{2,4})(?P<num>-?\d+(\.\d+)?)$',      # USD1800
                r'^(?P<num>-?\d+(\.\d+)?)(?P<code>[A-Za-z]{2,4})$',      # 1800USD
                r'^(?P<num>-?\d+(\.\d+)?)$',                             # just number
                r'^(?P<symbol>[^0-9A-Za-z])\s*(?P<num>-?\d+(\.\d+)?)$',  # $1800, €2000
            ]

            for pat in patterns:
                m = re.match(pat, s, flags=re.IGNORECASE)
                if not m:
                    continue
                gd = m.groupdict()
                num = float(gd.get("num") or 0.0)
                code = gd.get("code") or gd.get("symbol") or ""
                return num, code.upper()

            # fallback: grab first number and code if present
            mnum = re.search(r'(-?\d+(\.\d+)?)', s)
            mcode = re.search(r'([A-Za-z]{2,4})', s)
            num = float(mnum.group(1)) if mnum else 0.0
            code = mcode.group(1).upper() if mcode else ""
            return num, code

        def aggregate_with_currency(series: pd.Series, df_ad_set: pd.DataFrame, how="sum", verbose=False) -> str:
            nums, codes = [], []

            for v in series:
                n, c = _extract_number_and_currency(v)
                nums.append(n)
                codes.append(c)

            if verbose:
                print(list(zip(series.astype(str), nums, codes)))

            if not nums:
                return "N/A"

            # Aggregate numbers
            if how == "max":
                value = max(nums)
            elif how == "min":
                value = min(nums)
            else:
                value = sum(nums)

            # Priority 1: currency from the series (must be alphabetic, not just symbol)
            currency = next((c for c in codes if c and c.isalpha()), "")

            # Priority 2: explicit currency columns
            if not currency:
                for col in ("currency", "Currency", "currency_code"):
                    if col in df_ad_set.columns:
                        candidate = df_ad_set[col].iloc[0]
                        if pd.notna(candidate) and str(candidate).strip():
                            currency = str(candidate).strip().upper()
                            break

            # Priority 3: extract from bid_cap
            if not currency and "bid_cap" in df_ad_set.columns:
                bid_val = df_ad_set["bid_cap"].iloc[0]
                _, currency = _extract_number_and_currency(bid_val)

            return f"{value:,.2f} {currency}".strip()



        def calculate_pacing(df, budget_col="lifetime_budget", spend_col="budget_spent") -> str:
            """
            Calculate pacing % using:
            Daily Budget = lifetime_budget / total_flight_days
            Expected Spend = Daily Budget * elapsed_days (till yesterday)
            Actual Spend = budget_spent
            Pacing % = (Actual Spend / Expected Spend) * 100
            """

            # Use yesterday as the last complete reporting day
            report_date = datetime.today().date() - timedelta(days=1)

            # Extract budget and spend
            budget_total = pd.to_numeric(
                df[budget_col].astype(str).str.replace(r"[^\d.]", "", regex=True),
                errors="coerce"
            ).sum()
            print("budget_total", budget_total)
            spend_total = pd.to_numeric(
                df[spend_col].astype(str).str.replace(r"[^\d.]", "", regex=True),
                errors="coerce"
            ).sum()
            print("spend_total", spend_total)
            if budget_total <= 0:
                return "N/A"

            # Campaign start and end - use min for start and max for end
            start_date = pd.to_datetime(df["adset_start"]).min().date()
            end_date = pd.to_datetime(df["adset_end"]).max().date()
            print("start_date",start_date)
            print("end_date",end_date)
            total_days = (end_date - start_date).days + 1
            print("total_days",total_days)
            elapsed_days = (report_date - start_date).days + 1  # inclusive
            print("elapsed_days",elapsed_days)
            if elapsed_days <= 0:
                return "0%"

            if elapsed_days > total_days:
                elapsed_days = total_days

            # Daily budget
            daily_budget = budget_total / total_days
            print("daily_budget",daily_budget)
            # Expected spend till yesterday
            expected_spend = daily_budget * elapsed_days
            print("expected_spend",expected_spend)
            if expected_spend <= 0:
                return "N/A"

            pacing = (spend_total / expected_spend) * 100
            return f"{round(pacing)}%"


        def format_with_commas(value, decimals=None):
            """Format numbers with commas, unless already formatted as string with commas."""
            if isinstance(value, str) and "," in value:
                return value  # already formatted
            try:
                num = float(value)
                if decimals is None:
                    return f"{int(num):,}"
                else:
                    return f"{num:,.{decimals}f}"
            except Exception:
                return str(value)
        def format_range(df):
            """Format 1st and 3rd quartiles as percentage range."""
            if df.empty:
                return ""
            # Multiply by 100 to convert decimal format to percentage
            q1 = df['1st Quartile'].iloc[0] * 100
            q3 = df['3rd Quartile'].iloc[0] * 100
            return f"{q1:.2f}% - {q3:.2f}%"


        def add_benchmark_mapping(mapping, df_benchmark_metrics,df_ad_set):
            # Get unique ad formats (supports up to 4: audio, video, display, image)
            ad_formats = (
                df_ad_set["format"].dropna().astype(str).str.strip().str.lower().unique().tolist()
            )
            print("ad_formats",ad_formats)

            for i, ad_format in enumerate(ad_formats, start=1):
                ad_format_lower = str(ad_format).strip().lower()

                # Map "image" format to "display" for benchmark lookup
                ad_format_for_benchmark = "display" if ad_format_lower == "image" else ad_format_lower
                print(f"Looking up benchmarks: format={ad_format_lower}, mapped to={ad_format_for_benchmark}")

                # CTR placeholder
                ctr_df = get_format_metric_benchmark(
                    df_benchmark_metrics, ad_format_for_benchmark, "click-through rate"
                )
                mapping[f"[ctr_{i}]"] = format_range(ctr_df)
                print(f"CTR for {ad_format_lower}: {mapping[f'[ctr_{i}]']}, rows found: {len(ctr_df)}")

                # Completion Rate placeholder
                comp_df = get_format_metric_benchmark(
                    df_benchmark_metrics, ad_format_for_benchmark, "completion rate"
                )
                mapping[f"[completion_rate_{i}]"] = format_range(comp_df)
                print(f"Completion Rate for {ad_format_lower}: {mapping[f'[completion_rate_{i}]']}, rows found: {len(comp_df)}")

                # Format name (changed from ad_format to format)
                mapping[f"[format_{i}]"] = str(ad_format).capitalize()

            # Ensure placeholders exist for missing formats (up to 4 formats)
            for j in range(len(ad_formats)+1, 5):  # up to 4 formats
                mapping[f"[ctr_{j}]"] = ""
                mapping[f"[completion_rate_{j}]"] = ""
                mapping[f"[format_{j}]"] = ""

            return mapping


        
        # print("in mid campaign  main function")
        
        df_campaign = df_dict.get("Campaign")
        df_ad_set = df_dict.get("Ad Set")
        df_ad = df_dict.get("Ad")
        df_campaign_insights = df_dict.get("Campaign Insights")
       
        gender_insights,genre_insights,country_insights,age_insights,platform_insights=campaign_insights_data(df_campaign_insights)
       
        country_insights["country"] = country_insights["country"].str.strip().str.lower()
        country_insights["region"] = country_insights["country"].apply(get_region)

        _, _, df_benchmark_metrics, _ = get_benchmark_metrics(df_ad_set, country_insights)
        print("df_benchmark_metrics",df_benchmark_metrics)
        # Handle campaign objective - prioritize non-UNSET objectives
        unique_objectives = df_ad_set["campaign_objective"].str.strip().str.lower().unique().tolist()

        # Remove 'unset' from the list if other objectives exist
        non_unset_objectives = [obj for obj in unique_objectives if obj != 'unset']

        if non_unset_objectives:
            # Use the first non-UNSET objective
            objective = non_unset_objectives[0]
        else:
            # Fallback to first objective if no UNSET found
            objective = unique_objectives[0] if unique_objectives else "unknown"

        ad_format = str(df_ad_set["format"].iloc[0]).lower()
       
       
       
        # Filter for active ad sets only
        df_ad_set_active = df_ad_set[df_ad_set["adset_status"].str.lower() == "active"].copy()

        # If there are active ad sets, use them; otherwise fall back to all ad sets
        if not df_ad_set_active.empty:
            # Use active ad sets for all calculations
            df_working = df_ad_set_active
        else:
            # Fall back to all ad sets if no active ones
            df_working = df_ad_set

        # ==================== HANDLE MISSING LIFETIME_BUDGET ====================
        # For adsets without lifetime_budget, calculate it from avg_daily_budget * flight_days
        df_working = df_working.copy()

        for idx in df_working.index:
            lifetime_budget_val = df_working.loc[idx, "lifetime_budget"]

            # Check if lifetime_budget is missing or empty
            if pd.isna(lifetime_budget_val) or str(lifetime_budget_val).strip() == "":
                # Get avg_daily_budget
                avg_daily_budget = df_working.loc[idx, "avg_daily_budget"] if "avg_daily_budget" in df_working.columns else None

                if avg_daily_budget and not pd.isna(avg_daily_budget):
                    # Extract numeric value and currency from avg_daily_budget
                    daily_budget_num, currency = _extract_number_and_currency(avg_daily_budget)

                    # Calculate flight days for this adset
                    adset_start = pd.to_datetime(df_working.loc[idx, "adset_start"]).date()
                    adset_end = pd.to_datetime(df_working.loc[idx, "adset_end"]).date()
                    flight_days = (adset_end - adset_start).days + 1

                    # Calculate lifetime budget
                    calculated_lifetime_budget = daily_budget_num * flight_days

                    # Format with currency
                    df_working.loc[idx, "lifetime_budget"] = f"{calculated_lifetime_budget:.2f} {currency}".strip()
                    print(f"Calculated lifetime_budget for adset at index {idx}: {df_working.loc[idx, 'lifetime_budget']}")

        # ==================== AD PLACEMENT ====================
        placements = df_working["placement"].dropna().unique().tolist()
        # If any active ad set uses "Automatic", display "Automatic"
        if any(str(p).lower() == "automatic" for p in placements):
            ad_placement_str = "Automatic"
        elif len(placements) == 1:
            # All share the same placement
            ad_placement_str = str(placements[0]).capitalize()
        else:
            # Multiple non-automatic placements
            ad_placement_str = ", ".join([str(p).capitalize() for p in placements])

        # ==================== FORMAT ====================
        # Combination of formats of all active ad sets
        formats = df_working["format"].dropna().unique().tolist()
        format_str = ", ".join([str(f).capitalize() for f in formats])

        # ==================== SCHEDULE ====================
        # Min of start dates and max of end dates among active ad sets
        start_date = pd.to_datetime(df_working["adset_start"]).min()
        end_date = pd.to_datetime(df_working["adset_end"]).max()
        schedule_str = format_schedule(start_date, end_date)
        print("schedule_str",schedule_str)

        # ==================== BUDGET & SPEND ====================
        # Sum of all active ad sets
        budget_str = aggregate_with_currency(df_working["lifetime_budget"], df_working, how="sum")
        spend_str = aggregate_with_currency(df_working["budget_spent"], df_working, how="sum")
        print("budget_str",budget_str)

        # ==================== BID CAP ====================
        # Use the bid_cap column directly from df_working
        df_working_copy = df_working.copy()

        # Check if bid_cap column exists
        if "bid_cap" in df_working_copy.columns:
            # Extract numeric values and currency from bid_cap column
            bid_cap_values = []
            currency = ""

            for idx in df_working_copy.index:
                bid_cap_val = df_working_copy.loc[idx, "bid_cap"]
                if pd.notna(bid_cap_val) and str(bid_cap_val).strip():
                    num, curr = _extract_number_and_currency(bid_cap_val)
                    bid_cap_values.append(num)
                    if not currency and curr:
                        currency = curr

            # Get the maximum bid cap value
            max_bid_cap = max(bid_cap_values) if bid_cap_values else 0.0
        else:
            # Fallback: if bid_cap column doesn't exist, use calculated value
            max_bid_cap = 0.0
            currency = ""

        # Ensure we have a currency
        if not currency:
            # Try to extract from lifetime_budget as fallback
            _, currency = _extract_number_and_currency(df_working["lifetime_budget"].iloc[0]) if not df_working.empty else (0.0, "")
            if not currency:
                currency = "USD"  # Default to USD if no currency found

        # Format bid cap string with currency on the right side
        bid_cap_str = f"{max_bid_cap:.2f} {currency}".strip() if max_bid_cap > 0 else f"0.00 {currency}".strip()

        # ==================== PACING ====================
        # Calculate pacing based on active ad sets
        pacing_str = calculate_pacing(df_working)
        print("pacing_str", pacing_str)

        # ==================== METRICS FROM ACTIVE AD SETS ====================
        # Impressions: Sum of total_impressions
        total_impressions = df_working["total_impressions"].sum()

        # Reach: Prioritize reach, then streamed_reach, then unique_reach
        # Skip a column if it exists but its summed value is 0
        total_reach = 0
        for candidate in ("reach", "streamed_reach", "unique_reach"):
            if candidate in df_working.columns:
                candidate_sum = df_working[candidate].sum()
                if candidate_sum > 0:
                    total_reach = candidate_sum
                    break

        # Frequency: Use frequency or streamed_frequency column directly, else calculate
        # Skip a column if it exists but its mean value is 0
        frequency = 0
        for candidate in ("frequency", "streamed_frequency"):
            if candidate in df_working.columns:
                candidate_mean = df_working[candidate].mean()
                if candidate_mean > 0:
                    frequency = candidate_mean
                    break
        else:
            # Calculate frequency: Total impressions / Total reach
            frequency = (total_impressions / total_reach) if total_reach > 0 else 0

        # Clicks: Sum of clicks
        total_clicks = df_working["clicks"].sum()

        # CTR: Total clicks / Total impressions
        ctr = (total_clicks / total_impressions * 100) if total_impressions > 0 else 0

        # Completion Rate: Sum of ad_played_to_100_percent / Total impressions
        if "ad_played_to_100_percent" in df_working.columns:
            total_completions = df_working["ad_played_to_100_percent"].sum()
            completion_rate = (total_completions / total_impressions)*100 if total_impressions > 0 else 0
        elif "ad_completion_rate_cpm" in df_working.columns:
            # Fallback: weighted average of completion rates
            completion_rate = (df_working["ad_completion_rate_cpm"] * df_working["total_impressions"]).sum() / total_impressions * 100 if total_impressions > 0 else 0
        else:
            completion_rate = 0
        
        print("completion_rate",completion_rate)

        # Avg CPM: (Sum of budget_spent / Sum of impressions) * 1000
        total_spend_num = pd.to_numeric(
            df_working["budget_spent"].astype(str).str.replace(r"[^\d.]", "", regex=True),
            errors="coerce"
        ).sum()
        avg_cpm = (total_spend_num / total_impressions * 1000) if total_impressions > 0 else 0

        # Get currency dynamically - try multiple sources with fallback logic
        cpm_currency = ""

        # Priority 1: Try to extract from budget_spent
        if not df_working.empty:
            _, cpm_currency = _extract_number_and_currency(df_working["budget_spent"].iloc[0])
            # Only accept alphabetic currency codes (not just symbols like $)
            if cpm_currency and not cpm_currency.isalpha():
                cpm_currency = ""

        # Priority 2: Check explicit currency columns
        if not cpm_currency:
            for col in ("currency", "Currency", "currency_code"):
                if col in df_working.columns:
                    candidate = df_working[col].iloc[0]
                    if pd.notna(candidate) and str(candidate).strip():
                        cpm_currency = str(candidate).strip().upper()
                        break

        # Priority 3: Try to extract from lifetime_budget
        if not cpm_currency and "lifetime_budget" in df_working.columns and not df_working.empty:
            _, cpm_currency = _extract_number_and_currency(df_working["lifetime_budget"].iloc[0])

        # Priority 4: Try to extract from bid_cap
        if not cpm_currency and "bid_cap" in df_working.columns and not df_working.empty:
            _, cpm_currency = _extract_number_and_currency(df_working["bid_cap"].iloc[0])

        # Default to USD only as last resort
        if not cpm_currency:
            cpm_currency = "USD"

        avg_cpm_str = f"{avg_cpm:.2f} {cpm_currency}".strip()
        print("avg_cpm_str",avg_cpm_str)

        # Extract and format objective with comprehensive handling
        raw_objective = str(df_ad_set["campaign_objective"].iloc[0]).strip().lower()

        # Replace underscores with spaces and format objective
        raw_objective = raw_objective.replace("_", " ")

        # Handle specific multi-word objectives that need pluralization
        if raw_objective in ["podcast stream", "podcast streams"]:
            formatted_objective = "Podcast Streams"
        elif raw_objective in ["video view", "video views"]:
            formatted_objective = "Video Views"
        elif raw_objective in ["app install", "app installs"]:
            formatted_objective = "App Installs"
        elif raw_objective in ["website visit", "website visits"]:
            formatted_objective = "Website Visits"
        elif raw_objective == "page view":
            formatted_objective = "Page Views"
        # Add "s" if objective is single word that needs pluralization
        elif raw_objective in ["click", "impression", "view", "stream"]:
            formatted_objective = (raw_objective + "s").title()
        else:
            # Use title case for other objectives
            formatted_objective = raw_objective.title()

        print("formatted_objective", formatted_objective)

        # ==================== TAKEAWAYS LOGIC ====================

        # --- 1️⃣ Pacing & Spend Takeaway ---
        pacing_takeaway = ""
        try:
            # Extract numeric pacing percentage
            pacing_num = float(pacing_str.replace("%", "").strip())

            if pacing_num < 65:
                # Underpacing
                pacing_takeaway = f"Campaign pacing at {pacing_str}, slightly below target but showing strong efficiency — gradual scaling can help meet delivery goals."
            elif 65 <= pacing_num <= 85:
                # Pacing aligned
                pacing_takeaway = f"Campaign pacing at {pacing_str}, indicating steady delivery and effective budget utilization so far."
            else:  # pacing_num > 85
                # Overpacing
                pacing_takeaway = f"Campaign pacing at {pacing_str}, progressing ahead of plan — a minor pacing adjustment can help sustain performance through the flight."
        except Exception as e:
            print(f"[PACING TAKEAWAY] Error: {e}")
            pacing_takeaway = ""

        # --- 2️⃣ Bid Cap Takeaway ---
        bid_cap_takeaway = ""
        try:
            # Extract numeric values and currency from bid_cap and avg_cpm
            bid_cap_num, bid_cap_currency = _extract_number_and_currency(bid_cap_str)
            avg_cpm_num, avg_cpm_currency = _extract_number_and_currency(avg_cpm_str)

            # Use avg_cpm_currency, fallback to bid_cap_currency if not available
            currency_code = avg_cpm_currency if avg_cpm_currency else (bid_cap_currency if bid_cap_currency else "USD")

            if bid_cap_num > 0 and avg_cpm_num > 0:
                # Calculate percentage difference: ((CPM - Bid Cap) / Bid Cap) * 100
                difference_pct = ((avg_cpm_num - bid_cap_num) / bid_cap_num) * 100
                abs_difference_pct = abs(difference_pct)
                print("abs_difference_pct",abs_difference_pct)

                if abs_difference_pct <= 20:
                    # CPM close to bid cap (within ±20%)
                    bid_cap_takeaway = f"CPM at {avg_cpm_num:.2f} {currency_code}, around {abs_difference_pct:.0f}% below the bid cap of {bid_cap_num:.2f} {currency_code}, suggesting bids may be limiting delivery — consider adjusting cap upward to improve competitiveness."
                else:
                    # CPM far from bid cap (>20% difference)
                    bid_cap_takeaway = f"CPM at {avg_cpm_num:.2f} {currency_code}, within {abs_difference_pct:.0f}% of the bid cap of {bid_cap_num:.2f} {currency_code}, indicating well-balanced bidding and steady auction performance."

        except Exception as e:
            print(f"[BID CAP TAKEAWAY] Error: {e}")
            bid_cap_takeaway = ""

        # --- 3️⃣ CTR Takeaway (Based on Ad Format and Objective) ---
        ctr_takeaway = ""

        # --- 4️⃣ Completion Rate Takeaway (Based on Ad Format and Objective) ---
        completion_rate_takeaway = ""

        try:
            # Get unique ad formats from active ad sets
            ad_formats = df_working["format"].str.lower().unique().tolist()

            # Determine which takeaways to generate based on objective
            # Objective to KPI mapping
            objective_lower = objective.lower()
            show_ctr = False
            show_completion_rate = False

            # Define objective-to-KPI mapping (handle both singular and plural forms)
            if objective_lower in ["click", "clicks", "page view", "page views", "website traffic", "traffic", "app promotion", "app installs"]:
                show_ctr = True
            elif objective_lower in ["reach", "impression", "impressions", "video view", "video views", "stream", "streams", "brand"]:
                show_completion_rate = True
            elif objective_lower in ["awareness", "engagement"]:
                show_ctr = True
                show_completion_rate = True

            # For Display format, only show CTR (no completion rate)
            if any(fmt.lower() == "display" for fmt in ad_formats):
                show_completion_rate = False
                show_ctr = True

            # Debug prints
            print(f"[DEBUG] Objective: {objective_lower}")
            print(f"[DEBUG] Ad Formats: {ad_formats}")
            print(f"[DEBUG] show_ctr: {show_ctr}")
            print(f"[DEBUG] show_completion_rate: {show_completion_rate}")

            # Use calculated CTR from active ad sets
            overall_ctr = ctr  # Already in percentage

            if len(ad_formats) > 1:
                # Multiple ad formats - use new format with overall and per-format breakdown
                ctr_format_parts = []
                completion_format_parts = []

                for ad_format in ad_formats:
                    ad_format_lower = str(ad_format).lower()
                    format_name = ad_format.capitalize()

                    # Filter data for this ad format from active ad sets
                    format_df = df_working[df_working["format"].str.lower() == ad_format_lower]

                    if format_df.empty:
                        continue

                    # Calculate format-level CTR from active ad sets
                    format_clicks = format_df["clicks"].sum()
                    format_impressions = format_df["total_impressions"].sum()
                    format_ctr = (format_clicks / format_impressions * 100) if format_impressions > 0 else 0

                    # Get CTR benchmark for this format
                    ctr_benchmark_df = get_format_metric_benchmark(
                        df_benchmark_metrics, ad_format_lower, "click-through rate"
                    )

                    benchmark_ctr = 0
                    if not ctr_benchmark_df.empty:
                        benchmark_ctr = ctr_benchmark_df['Median'].iloc[0] * 100
                        print(f"[DEBUG] {ad_format} CTR Benchmark Median (after * 100): {benchmark_ctr}")

                    # CTR comparison - only if show_ctr is True
                    if show_ctr and benchmark_ctr > 0:
                        ctr_diff_pct = ((format_ctr - benchmark_ctr) / benchmark_ctr) * 100
                        abs_ctr_diff = abs(ctr_diff_pct)

                        if abs_ctr_diff <= 10:  # Near benchmark
                            ctr_format_parts.append(f"{format_name} stands at {format_ctr:.2f}%, closely aligned with the benchmark of {benchmark_ctr:.2f}%, maintaining consistent engagement levels")
                        elif ctr_diff_pct > 10:  # Above benchmark
                            ctr_format_parts.append(f"{format_name} stands at {format_ctr:.2f}%, which is {abs_ctr_diff:.0f}% above the benchmark of {benchmark_ctr:.2f}%, highlighting strong creative engagement and audience relevance")
                        else:  # Below benchmark
                            ctr_format_parts.append(f"{format_name} stands at {format_ctr:.2f}%, which is {abs_ctr_diff:.0f}% below the benchmark of {benchmark_ctr:.2f}%, indicating room to enhance engagement through creative or audience refinements")

                    # Completion rate for audio/video formats - only if show_completion_rate is True
                    if show_completion_rate and ad_format_lower in ["audio", "video"]:
                        # Calculate from ad_played_to_100_percent if available
                        if "ad_played_to_100_percent" in format_df.columns:
                            format_completions = format_df["ad_played_to_100_percent"].sum()
                            format_completion_rate = (format_completions / format_impressions * 100) if format_impressions > 0 else 0
                        elif "ad_completion_rate_cpm" in format_df.columns:
                            # Weighted average
                            format_completion_rate = (format_df["ad_completion_rate_cpm"] * format_df["total_impressions"]).sum() / format_impressions * 100 if format_impressions > 0 else 0
                        else:
                            format_completion_rate = 0

                        comp_benchmark_df = get_format_metric_benchmark(
                            df_benchmark_metrics, ad_format_lower, "completion rate"
                        )

                        benchmark_comp = 0
                        if not comp_benchmark_df.empty:
                            benchmark_comp = comp_benchmark_df['Median'].iloc[0] * 100
                            print(f"[DEBUG] {ad_format} Completion Rate Benchmark Median (after * 100): {benchmark_comp}")

                        if benchmark_comp > 0:
                            comp_diff_pct = ((format_completion_rate - benchmark_comp) / benchmark_comp) * 100
                            abs_comp_diff = abs(comp_diff_pct)

                            if abs_comp_diff <= 10:  # Aligned
                                completion_format_parts.append(f"{format_name} stands at {format_completion_rate:.0f}%, nearly aligned with the benchmark of {benchmark_comp:.0f}%, maintaining steady audience retention")
                            elif comp_diff_pct > 10:  # Above benchmark
                                completion_format_parts.append(f"{format_name} stands at {format_completion_rate:.0f}%, which is {abs_comp_diff:.0f}% above the benchmark of {benchmark_comp:.0f}%, reflecting strong viewer retention and effective messaging")
                            else:  # Below benchmark
                                completion_format_parts.append(f"{format_name} stands at {format_completion_rate:.0f}%, which is {abs_comp_diff:.0f}% below the benchmark of {benchmark_comp:.0f}%, suggesting scope to optimize early engagement and creative hook")

                # Build CTR takeaway
                if ctr_format_parts:
                    if len(ctr_format_parts) == 1:
                        ctr_takeaway = f"The overall CTR stands at {overall_ctr:.2f}%, where {ctr_format_parts[0]}."
                    else:
                        # Join all parts with proper punctuation
                        parts_text = ", and where ".join(ctr_format_parts)
                        ctr_takeaway = f"The overall CTR stands at {overall_ctr:.2f}%, where {parts_text}."

                # Build Completion Rate takeaway
                if completion_format_parts:
                    # Use calculated completion rate from active ad sets
                    overall_completion_rate = completion_rate  # Already in percentage

                    if len(completion_format_parts) == 1:
                        completion_rate_takeaway = f"The overall Completion rate stands at {overall_completion_rate:.0f}%, where {completion_format_parts[0]}."
                    else:
                        parts_text = ", and where ".join(completion_format_parts)
                        completion_rate_takeaway = f"The overall Completion rate stands at {overall_completion_rate:.0f}%, where {parts_text}."

            else:
                # Single ad format logic
                ad_format = ad_formats[0] if ad_formats else ""
                ad_format_lower = str(ad_format).lower()

                # Get benchmark CTR (median) for the ad format
                ctr_benchmark_df = get_format_metric_benchmark(
                    df_benchmark_metrics, ad_format_lower, "click-through rate"
                )

                benchmark_ctr = 0
                if not ctr_benchmark_df.empty:
                    benchmark_ctr = ctr_benchmark_df['Median'].iloc[0] * 100
                    print(f"[DEBUG] Single format CTR Benchmark Median (after * 100): {benchmark_ctr}")

                # CTR comparison for single format - only if show_ctr is True
                if show_ctr and benchmark_ctr > 0:
                    ctr_diff_pct = ((overall_ctr - benchmark_ctr) / benchmark_ctr) * 100
                    abs_ctr_diff = abs(ctr_diff_pct)

                    if abs_ctr_diff <= 10:  # Near benchmark
                        ctr_takeaway = f"CTR at {overall_ctr:.2f}%, closely aligned with the benchmark of {benchmark_ctr:.2f}%, maintaining consistent engagement levels."
                    elif ctr_diff_pct > 10:  # Above benchmark
                        ctr_takeaway = f"CTR at {overall_ctr:.2f}%, performing {abs_ctr_diff:.0f}% above the benchmark of {benchmark_ctr:.2f}%, highlighting strong creative engagement and audience relevance."
                    else:  # Below benchmark
                        ctr_takeaway = f"CTR at {overall_ctr:.2f}%, around {abs_ctr_diff:.0f}% below the benchmark of {benchmark_ctr:.2f}%, indicating room to enhance engagement through creative or audience refinements."

                # Check if it's audio or video format (completion rate applicable) - only if show_completion_rate is True
                if show_completion_rate and ad_format_lower in ["audio", "video"]:
                    # Use calculated completion rate from active ad sets
                    campaign_completion_rate = completion_rate  # Already in percentage

                    # Get completion rate benchmark
                    comp_benchmark_df = get_format_metric_benchmark(
                        df_benchmark_metrics, ad_format_lower, "completion rate"
                    )

                    benchmark_comp = 0
                    if not comp_benchmark_df.empty:
                        benchmark_comp = comp_benchmark_df['Median'].iloc[0] * 100
                        print(f"[DEBUG] Single format Completion Rate Benchmark Median (after * 100): {benchmark_comp}")

                    # Completion rate comparison
                    if benchmark_comp > 0:
                        comp_diff_pct = ((campaign_completion_rate - benchmark_comp) / benchmark_comp) * 100
                        abs_comp_diff = abs(comp_diff_pct)

                        if abs_comp_diff <= 10:  # Aligned with benchmark
                            completion_rate_takeaway = f"Completion rate at {campaign_completion_rate:.0f}%, nearly aligned with the benchmark of {benchmark_comp:.0f}%, maintaining steady audience retention."
                        elif comp_diff_pct > 10:  # Above benchmark
                            completion_rate_takeaway = f"Completion rate at {campaign_completion_rate:.0f}%, exceeding the benchmark of {benchmark_comp:.0f}% by {abs_comp_diff:.0f}%, reflecting strong viewer retention and effective messaging."
                        else:  # Below benchmark
                            completion_rate_takeaway = f"Completion rate at {campaign_completion_rate:.0f}%, {abs_comp_diff:.0f}% below the benchmark of {benchmark_comp:.0f}%, suggesting scope to optimize early engagement and creative hook."

        except Exception as e:
            print(f"[CTR/COMPLETION RATE TAKEAWAY] Error: {e}")
            ctr_takeaway = ""
            completion_rate_takeaway = ""

        # ==================== DYNAMIC TAKEAWAYS NUMBERING ====================
        # Collect all takeaways in a list
        takeaways_list = []

        if pacing_takeaway and pacing_takeaway.strip():
            takeaways_list.append(pacing_takeaway)

        if bid_cap_takeaway and bid_cap_takeaway.strip():
            takeaways_list.append(bid_cap_takeaway)

        if ctr_takeaway and ctr_takeaway.strip():
            takeaways_list.append(ctr_takeaway)

        if completion_rate_takeaway and completion_rate_takeaway.strip():
            takeaways_list.append(completion_rate_takeaway)

        # Determine maximum number of takeaways to support
        # This can be adjusted based on your template's placeholder count
        MAX_TAKEAWAYS = 5  # Supports up to 5 takeaways, can be increased as needed

        # Create numbered placeholders dynamically
        takeaways_dict = {}
        for i, takeaway_text in enumerate(takeaways_list, start=1):
            takeaways_dict[f"[takeaway_{i}]"] = takeaway_text

        # Fill remaining placeholders with empty strings
        for j in range(len(takeaways_list) + 1, MAX_TAKEAWAYS + 1):
            takeaways_dict[f"[takeaway_{j}]"] = ""

        print(f"\n[TAKEAWAYS] Generated {len(takeaways_list)} takeaways dynamically (max supported: {MAX_TAKEAWAYS}):")
        for key, value in takeaways_dict.items():
            if value:
                print(f"  {key}: {value[:80]}...")
            else:
                print(f"  {key}: (empty)")


        mapping = {
        "[campaign_name]": str(df_campaign["campaign_title"].iloc[0]),
        "[DATE]": datetime.today().strftime("%d/%m/%Y"),
        "[schedule]": str(schedule_str),
        "[ad_placement]": ad_placement_str,
        "[format]": format_str,
        "[objective]": formatted_objective,
        # Currency formatted values
        "[budget]": budget_str,
        "[spend]": spend_str,
        "[bid_cap]": bid_cap_str,
        "[pacing]": pacing_str,
        #metrics - calculated from active ad sets
        "[impressions]": format_with_commas(total_impressions),
        "[reach]": format_with_commas(total_reach),
        "[clicks]": format_with_commas(total_clicks),
        "[frequency]": f"{frequency:.2f}",
        "[ctr]": f"{ctr:.2f}%",
        "[avg_cpm]": avg_cpm_str,
        "[c_rate]": f"{completion_rate:.2f}%"

        }

        # Add dynamic takeaways to mapping
        mapping.update(takeaways_dict)

        # Use df_working (active ad sets only) for benchmark mapping
        mapping = add_benchmark_mapping(mapping, df_benchmark_metrics, df_working)

        template_path = Path(__file__).parent.parent / "standalones/mid_campaign_pdf_template_v2.pptx"
        template = Presentation(str(template_path))

        ppt_buffer = get_ppt_report(mapping, template)

        # ensure we always return bytes
        ppt_bytes = ppt_buffer.getvalue() if isinstance(ppt_buffer, BytesIO) else ppt_buffer

        return ppt_bytes
