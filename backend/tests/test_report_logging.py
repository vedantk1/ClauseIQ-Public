"""Retained PDF report diagnostics never bypass configured logging."""

from unittest.mock import MagicMock

import pytest

from services import pdf_service


@pytest.mark.asyncio
async def test_report_uses_quiet_configured_logging(monkeypatch, capsys, caplog):
    template = MagicMock()
    template.build_pdf.return_value = b"synthetic-result"
    template.add_title_page.side_effect = ValueError("PRIVATE_REPORT_SENTINEL")
    monkeypatch.setattr(pdf_service, "LegalReportTemplate", lambda _data: template)

    result = await pdf_service.generate_pdf_report({"filename": "PRIVATE_REPORT_SENTINEL"})

    assert result == b"synthetic-result"
    template.add_final_sections.assert_called_once_with()
    template.build_pdf.assert_called_once_with()
    assert capsys.readouterr().out == ""
    assert "ValueError" in caplog.text
    assert "PRIVATE_REPORT_SENTINEL" not in caplog.text
