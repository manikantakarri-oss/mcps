import io

import pandas as pd
import pytest

import legacy_actions
import server
from sema4ai.actions import ActionError, Response, chat


def test_unwrap_returns_result():
    assert server._unwrap(Response(result={"file_name": "x.pptx"})) == {"file_name": "x.pptx"}


def test_unwrap_raises_on_error():
    with pytest.raises(RuntimeError, match="boom"):
        server._unwrap(Response(error="boom"))


def test_get_mid_campaign_ppt_report_rejects_non_xlsx(tmp_path):
    bogus = tmp_path / "not_excel.csv"
    bogus.write_text("a,b\n1,2\n")
    with pytest.raises(RuntimeError, match="Only .xlsx"):
        server.get_mid_campaign_ppt_report(filename=str(bogus))


def test_get_mid_campaign_ppt_report_generates_pptx(tmp_path, monkeypatch):
    # The real report-generation business logic (services/midcampaign_pdf_service.py,
    # copied byte-identical) expects a full multi-sheet campaign export (ad-set
    # data + a marker-delimited "Campaign Insights" sheet + columns matching the
    # bundled benchmark/KPI mappings). Fabricating a realistic fixture for that
    # is out of scope for this migration test; instead this isolates what the
    # MCP wrapper itself is responsible for: file resolution in, attach-and-return
    # out. The business logic itself is unchanged (verbatim) and is the source
    # pack's own responsibility to test.
    workbook_path = tmp_path / "campaign.xlsx"
    pd.DataFrame({"Ad Format": ["Video"]}).to_excel(workbook_path, index=False)

    attached: dict[str, bytes] = {}

    def fake_attach_file_content(name, data, content_type="application/octet-stream"):
        attached["name"] = name
        attached["data"] = data
        return [{"name": name}]

    monkeypatch.setattr("agent_server_helper.attach_file_content", fake_attach_file_content)
    monkeypatch.setattr(
        "legacy_actions.midcampaign_pdf_service.generate_report",
        lambda df_dict: b"%FAKE-PPTX-BYTES%",
    )
    # Legacy code also writes the PPTX to os.getcwd() as a local copy; contain
    # that side effect to tmp_path instead of the repo directory.
    monkeypatch.chdir(tmp_path)

    result = server.get_mid_campaign_ppt_report(filename=str(workbook_path))

    assert result["file_name"].endswith(".pptx")
    assert result["status"] == "Attached to chat thread"
    assert attached["name"] == result["file_name"]
    assert attached["data"] == b"%FAKE-PPTX-BYTES%"


def test_get_mid_campaign_ppt_report_survives_missing_platform_context(tmp_path, monkeypatch):
    # attach_file_content requires platform context (agent_id/thread_id from
    # X-Tool-Invocation-Context); running server.py locally without that
    # context previously crashed the whole tool. It should now degrade to a
    # successful "Saved locally" result instead of raising.
    workbook_path = tmp_path / "campaign.xlsx"
    pd.DataFrame({"Ad Format": ["Video"]}).to_excel(workbook_path, index=False)

    def _raise_missing_context(name, data, content_type="application/octet-stream"):
        raise RuntimeError("Missing required platform context fields for thread files: agent_id, thread_id")

    monkeypatch.setattr("agent_server_helper.attach_file_content", _raise_missing_context)
    monkeypatch.setattr(
        "legacy_actions.midcampaign_pdf_service.generate_report",
        lambda df_dict: b"%FAKE-PPTX-BYTES%",
    )
    monkeypatch.chdir(tmp_path)

    result = server.get_mid_campaign_ppt_report(filename=str(workbook_path))

    assert result["file_name"].endswith(".pptx")
    assert result["status"] == "Saved locally"
    assert (tmp_path / result["file_name"]).exists()


def test_resolve_workbook_raises_clean_error_when_nothing_found(tmp_path, monkeypatch):
    # No filename, no local .xlsx anywhere findable, no thread files -> a
    # single clean ActionError, not a downstream pandas/AttributeError crash
    # (this was the bug in the outdated _access_file: it silently fell back
    # to a nonexistent Path and blew up later inside pd.read_excel).
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(chat, "list_files", lambda: [])
    with pytest.raises(ActionError, match="Could not resolve an uploaded .xlsx workbook"):
        legacy_actions._resolve_workbook(None)


def test_resolve_workbook_raises_clean_error_for_unresolvable_named_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(chat, "list_files", lambda: [])

    def _fail_get_file(name):
        raise FileNotFoundError(name)

    monkeypatch.setattr(chat, "get_file", _fail_get_file)
    with pytest.raises(ActionError, match="Could not resolve workbook 'missing.xlsx'"):
        legacy_actions._resolve_workbook("missing.xlsx")


def test_resolve_workbook_auto_selects_single_thread_file(tmp_path, monkeypatch):
    # No local file under that name anywhere in the search roots, but exactly
    # one .xlsx is attached to the thread -> auto-select it via
    # chat.list_files() + chat.get_file(), not a local filesystem scan.
    empty_cwd = tmp_path / "cwd"
    empty_cwd.mkdir()
    monkeypatch.chdir(empty_cwd)

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    thread_workbook = elsewhere / "thread_upload.xlsx"
    pd.DataFrame({"Ad Format": ["Video"]}).to_excel(thread_workbook, index=False)

    monkeypatch.setattr(chat, "list_files", lambda: ["thread_upload.xlsx"])
    monkeypatch.setattr(chat, "get_file", lambda name: thread_workbook)

    name, resolved = legacy_actions._resolve_workbook("some_stale_name.xlsx")

    assert name == "thread_upload.xlsx"
    assert resolved == thread_workbook
