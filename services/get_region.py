import json
from pathlib import Path

def get_region(country: str) -> str:
    """Return region name for a given country, or 'n/a' if not found."""
    # Get the directory of the current file (get_region.py)
    current_dir = Path(__file__).parent

    # Construct the full path to the JSON file relative to the current directory
    region_file = current_dir / "region_country_mappings.json"


    # Load region mappings
    try:
        with open(region_file, "r", encoding="utf-8") as f:
            region_to_countries = json.load(f)
    except FileNotFoundError as e:
        print(f"❌ ERROR: Could not open {region_file}\n{e}")
        return "n/a"

    if not isinstance(country, str):
        return "n/a"

    country = country.strip().lower()  # normalize
    for region, countries in region_to_countries.items():
        if country in (c.lower() for c in countries):
            return region

    return "n/a"
