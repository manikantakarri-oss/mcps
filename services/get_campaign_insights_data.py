# 
# from reportlab.lib.pagesizes import A4
# from reportlab.pdfgen import canvas
import pandas as pd


def campaign_insights_data(df_campaign_insights):
    print("in campaign insights data",df_campaign_insights)
    # ✅ Function to align columns (handles missing + NaN/blank names)
    def align_columns_with_reference(df, reference_df):
        print("align_columns_with_reference")
        if df is None:
            return None
        
        ref_cols = list(reference_df.columns)
        df_cols = list(df.columns)

        # If column count differs → pad with reference column names
        if len(df_cols) < len(ref_cols):
            for i in range(len(df_cols), len(ref_cols)):
                df_cols.append(ref_cols[i])

        # Replace NaN or blank column names with reference
        df_cols = [
            ref_cols[i] if (i < len(ref_cols) and (pd.isna(col) or str(col).strip() == "")) else col
            for i, col in enumerate(df_cols)
        ]

        df.columns = df_cols
        return df
    
    sections = {
        "gender_insights": "gender_insights",
        "genre_insights": "genre_insights",
        "country_insights": "country_insights",
        "age_insights": "age_insights",
        "platform_insights": "platform_insights"
    }

    result = {}

    for key, marker in sections.items():
        # ✅ Find exact cell match instead of row-wise match
        mask = df_campaign_insights.astype(str).apply(lambda col: col.str.strip() == marker).any(axis=1)
        start_rows = df_campaign_insights.index[mask].tolist()
        if not start_rows:
            continue
        start_row = start_rows[0]

        # header row is just below marker
        header_row = start_row + 1

        # ✅ find next marker row (strict > start_row)
        next_markers = []
        for m in sections.values():
            mask_next = df_campaign_insights.astype(str).apply(lambda col: col.str.strip() == m).any(axis=1)
            indices = df_campaign_insights.index[mask_next]
            indices = indices[indices > start_row]
            if not indices.empty:
                next_markers.append(indices.min())

        end_row = min(next_markers) if next_markers else len(df_campaign_insights)

        # slice section
        table = df_campaign_insights.iloc[header_row:end_row].reset_index(drop=True)

        # ✅ handle missing headers properly
        if not table.empty:
            table.columns = table.iloc[0]
            table = table.drop(0).reset_index(drop=True)
            result[key] = table

    print("Available sections in results:", list(result.keys()))

    # ✅ Assign to separate DataFrames
    gender_insights   = result.get("gender_insights")
    genre_insights    = result.get("genre_insights")
    country_insights  = result.get("country_insights")
    age_insights      = result.get("age_insights")
    platform_insights = result.get("platform_insights")

    # ✅ Use gender as reference if available, else fallback to genre
    reference = gender_insights if gender_insights is not None else genre_insights  

    genre_insights    = align_columns_with_reference(genre_insights, reference)
    country_insights  = align_columns_with_reference(country_insights, reference)
    age_insights      = align_columns_with_reference(age_insights, reference)
    platform_insights = align_columns_with_reference(platform_insights, reference)
    print(gender_insights)

    return gender_insights, genre_insights, country_insights, age_insights, platform_insights
