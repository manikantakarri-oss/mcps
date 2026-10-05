"""
A simple AI Action template for retrieving Wikipedia article summary

Please check out the base guidance on AI Actions in our main repository readme:
https://github.com/sema4ai/actions/blob/master/README.md

"""

import os
from sema4ai.actions import Response, action

from pathlib import Path
from typing import Dict, Any
from io import BytesIO
import pandas as pd
import uuid
from pptx import Presentation
from sema4ai.actions import ActionError, Response, action, chat
from services.midcampaign_pdf_service import MidcampaignPdfService
import json
import os
import base64


# Instantiate service
midcampaign_pdf_service = MidcampaignPdfService()

def _unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _local_workbook_candidates() -> list[Path]:
    pack_root = Path(__file__).resolve().parent
    search_roots = [
        Path.cwd(),
        Path.cwd() / "input",
        Path.cwd() / "output",
        pack_root,
        pack_root / "input",
        pack_root / "output",
    ]
    candidates: list[Path] = []
    for root in search_roots:
        if not root.exists() or not root.is_dir():
            continue
        candidates.extend(sorted(root.glob("*.xlsx")))
    return _unique_paths(candidates)


def _resolve_workbook(filename: str | None = None) -> tuple[str, Path]:
    """
    Resolve the single uploaded workbook without depending on an exact filename.

    Resolution order:
    1. If a matching local workbook exists, use it.
    2. If the thread has exactly one .xlsx file attached, use it.
    3. If the thread has a matching workbook name, use it.
    4. If a filename was given, try fetching it directly from the thread
       (same as a plain chat.get_file() call) - covers chat.list_files()
       missing/omitting a file that is genuinely attached.
    """
    requested = (filename or "").strip()
    requested_basename = Path(requested).name if requested else ""
    pack_root = Path(__file__).resolve().parent

    if requested_basename:
        requested_path = Path(requested)
        exact_candidates = [
            requested_path,
            Path.cwd() / requested_path,
            Path.cwd() / requested_basename,
            Path.cwd() / "input" / requested_basename,
            Path.cwd() / "output" / requested_basename,
            pack_root / requested_path,
            pack_root / requested_basename,
            pack_root / "input" / requested_basename,
            pack_root / "output" / requested_basename,
        ]
        for candidate in exact_candidates:
            if candidate.exists() and candidate.is_file():
                print(f"[INFO] Found local file at: {candidate.resolve()}")
                return candidate.name, candidate.resolve()

    local_candidates = _local_workbook_candidates()
    if len(local_candidates) == 1:
        chosen = local_candidates[0].resolve()
        print(f"[INFO] Auto-selected local workbook: {chosen}")
        return chosen.name, chosen

    try:
        thread_files = [name for name in chat.list_files() if str(name).lower().endswith(".xlsx")]
    except Exception:
        thread_files = []

    if requested_basename and requested_basename in thread_files:
        chosen = Path(chat.get_file(requested_basename))
        print(f"[INFO] Found thread workbook by name: {chosen}")
        return requested_basename, chosen

    if len(thread_files) == 1:
        chosen_name = thread_files[0]
        chosen = Path(chat.get_file(chosen_name))
        print(f"[INFO] Auto-selected thread workbook: {chosen}")
        return chosen_name, chosen

    if requested_basename:
        # `chat.list_files()` is best-effort and may miss a file that is
        # genuinely attached (e.g. a listing-endpoint hiccup) - fall back to
        # fetching the named file directly before giving up.
        try:
            chosen = Path(chat.get_file(requested_basename))
            print(f"[INFO] Fetched thread workbook directly by name: {chosen}")
            return requested_basename, chosen
        except Exception as err:
            print(f"[WARNING] Direct chat.get_file fallback failed for '{requested_basename}': {err}")

        raise ActionError(
            f"❌ Could not resolve workbook '{requested_basename}'. "
            "Upload exactly one .xlsx file in the thread, or pass the workbook name."
        )

    raise ActionError(
        "❌ Could not resolve an uploaded .xlsx workbook. "
        "Please attach exactly one .xlsx file to the thread."
    )


def _access_file(filename: str | None = None):
    return _resolve_workbook(filename)



# 1️⃣ Action: Calculate metrics from Excel
@action(is_consequential=False, display_name="Generate Campaign summary & PPT Report")
def get_mid_campaign_ppt_report(filename: str = "") -> Response:
    """
    Reads an uploaded Excel workbook, calculates campaign performance metrics, 
    and generates a PowerPoint (PPTX) report with those metrics.

    Workflow:
        1. Validates the uploaded file is in `.xlsx` format.
        2. Reads all sheets from the Excel file into pandas DataFrames.
        3. Optionally loads a "Campaign Insights" sheet if present.
        4. Calls the report generator service to compute campaign metrics 
           and produce a PPTX report.
        5. Attaches the PPTX file to the agent chat for download.

    Args:
        filename (str): Name of the uploaded Excel file.

    Returns:
        Response:
            - `result`: A dict containing:
                - `file_name` (str): The generated PPT file name.

    Raises:
        ActionError: If the file is not an `.xlsx` or if reading/processing fails.
    """

    try:
        orig_basename, temp_path = _access_file(filename)
        if temp_path.suffix.lower() != ".xlsx":
            return Response(error="❌ Only .xlsx Excel files are supported. Please upload a valid .xlsx file.")
        
        # Load with pandas for much faster processing
        df_dict = pd.read_excel(temp_path, sheet_name=None, engine='openpyxl')
        
        # Add "Campaign Insights" if it exists
        try:
            df_dict["Campaign Insights"] = pd.read_excel(
                temp_path, sheet_name="Campaign Insights", header=None, engine="openpyxl"
            )
        except Exception:
            pass

        ppt_bytes = midcampaign_pdf_service.generate_report(df_dict)
        
        # Create a unique file name
        file_name = f"MidCampaign_{uuid.uuid4().hex}.pptx"

        local_path = os.path.join(os.getcwd(), file_name)

        # Store PPT locally as well
        with open(local_path, "wb") as f:
            f.write(ppt_bytes)
        print(f"[OK] PPT saved locally at: {local_path}")

        # Attach the file to the chat (Sema4 Cloud / MCP mode). If platform
        # context isn't available (e.g. local testing outside the Agent
        # Server), skip the attach instead of crashing - the PPTX is already
        # saved locally above.
        attach_status = "Saved locally"
        try:
            chat.attach_file_content(
                name=file_name,
                data=ppt_bytes,
                content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation"
            )
            attach_status = "Attached to chat thread"
        except Exception as attach_err:
            print(f"[INFO] Skipping chat attach (local/MCP mode): {attach_err}")

        return Response(
            result={
                "file_name": file_name,
                "status": attach_status
            }
        )

    except ActionError:
        raise
    except Exception as e:
        raise ActionError(f"❌ Failed to generate PPT report: {str(e)}")



