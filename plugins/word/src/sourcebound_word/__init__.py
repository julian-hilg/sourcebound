"""Word documents for Sourcebound.

    sb template new ID --kind docx [--design ID]     the standard template, built from a design
    sb word inspect FILE                             what a corporate template offers
    sb word adopt FILE --id ID [--design ID]         register a corporate .docx/.dotx/.dotm as a template
    sb render TARGET --template ID                   a piece or a deliverable as a Word file
    sb word status | refresh | pull FILE             after a person edited the file

See README.md of this package for the walkthrough and the limits.
"""
from __future__ import annotations

__version__ = "0.1.0"


def register(api) -> None:
    from . import cli, render, template
    api.renderer("docx", render.render, title="Word document from a .docx template, numbers and citations as content controls",
                 outputs=(".docx",))
    api.check("docx", render.check)
    api.scaffold("docx", template.scaffold)
    api.command("word", cli.setup, cli.run, help="Word files after a person edited them; corporate templates")
