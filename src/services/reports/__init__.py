"""
Property valuation PDF reports.

A self-contained sub-package that turns a structured report data object
(`schema.ReportData`) into a clean, client-ready PDF.

Layering (kept deliberately decoupled so each piece can be used alone):

    schema.py   -> the data contract (pydantic). No I/O.
    templates/  -> the HTML/CSS (Jinja2). No Python.
    pdf.py      -> render ReportData -> HTML -> PDF bytes. No DB.
    builder.py  -> assemble ReportData for a property_id from the live DB.
    mock.py     -> a fully-populated ReportData for demos/tests (no DB).

The HTML/PDF path (schema + templates + pdf + mock) has NO database or ML
imports, so it can be rendered anywhere — including the local test script and
lightweight containers.
"""

from src.services.reports.schema import ReportData

__all__ = ["ReportData"]
