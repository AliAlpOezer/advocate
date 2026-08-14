"""Splicing a drafted `<body>` into the house page shell.

The Lebenslauf template is 14.3 KB, of which roughly a third is the print CSS
that gives it its known page count. Asking a model to reproduce all of it to
change the prose is expensive in exactly the currency that is scarce here - the
stalls measured on 2026-08-06 were a long-horizon generation problem - and it
puts the one part of the document that must not change inside the part the model
rewrites.

So the model sends back the body only, and the shell is kept. The layout cannot
be damaged by a draft, the generated tokens roughly halve, and "did the document
get rewritten" stays a byte comparison against the template because the body is
what differs.
"""

from __future__ import annotations

import re

_BODY_OPEN = re.compile(r"<body\b[^>]*>", re.I)
_BODY_CLOSE = re.compile(r"</body\s*>", re.I)
# Models wrap generated markup in a fence perhaps one time in ten. Cheaper to
# strip it here than to fail the write and spend a turn explaining.
_FENCE = re.compile(r"^\s*```(?:html)?\s*\n(.*?)\n\s*```\s*$", re.S | re.I)


class DocumentError(Exception):
    """Raised into the model as a tool result, never up into the loop."""


def body_of(html: str) -> str:
    """The inner HTML of `<body>`, or the whole string if there is no body tag."""
    if not html:
        return ""
    open_match = _BODY_OPEN.search(html)
    close_match = _BODY_CLOSE.search(html)
    if not open_match or not close_match or close_match.start() < open_match.end():
        return html
    return html[open_match.end() : close_match.start()].strip("\n")


def normalise_body(payload: str) -> str:
    """What the model sent, reduced to a body fragment.

    It is told to send the body only. A model that sends a whole document anyway
    is doing something reasonable, and refusing it would cost a turn to correct
    something we can simply read.
    """
    fenced = _FENCE.match(payload)
    if fenced:
        payload = fenced.group(1)
    return body_of(payload).strip("\n")


def splice_body(shell_html: str, body: str) -> str:
    """`shell_html` with its body replaced. The head, the CSS and the doctype survive."""
    open_match = _BODY_OPEN.search(shell_html)
    close_match = _BODY_CLOSE.search(shell_html)
    if not open_match or not close_match or close_match.start() < open_match.end():
        raise DocumentError(
            "the document on disk has no usable <body> element, so there is no shell to keep"
        )
    return (
        shell_html[: open_match.end()]
        + "\n"
        + body.strip("\n")
        + "\n"
        + shell_html[close_match.start() :]
    )
