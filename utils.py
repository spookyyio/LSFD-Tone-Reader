import re

# NOTE (developer guidance):
#
# This module defines the marker/keyword the rest of the program looks for in
# log lines and provides `clean_text()` to strip the marker and timestamps.
# To detect additional keywords (for example, "** ALERT" or "** ANNOUNCEMENT"),
# you only need to change the two definitions below:
#
#  - KEYWORD: a single literal used by the UI (kept for backwards compatibility
#    with code such as `tonereader.test_tone()` which constructs a test line
#    using this value). This is used by `clean_text()` to remove any leftover
#    literal occurrences.
#
#  - MARKER_RE: a compiled regular expression used by `watcher.py` and code in
#    this module to FIND the marker in a line and determine the end position of
#    the marker. `MARKER_RE.search(line)` must match the marker text at the
#    point where the message begins. The current regex matches variants like
#    "** STATION TONE", "** [STATION TONE]" and is case-insensitive.
#
# Examples of ways to extend detection:
#  - Add simple alternation to the regex: r"\*\*\s*\[?(?:STATION|ALERT)\s+TONE\]?"
#  - Use multiple explicit patterns: r"(?:\*\*\s*\[?STATION\s+TONE\]?|\*\*\s*ALERT)"
#  - If you prefer a list-driven approach, you can build MARKER_RE from a
#    KEYWORDS list using `re.escape()` and joining with `|` (not done here to
#    preserve the simple shape of the existing code).
#
# Important notes / edge cases:
#  - Keep re.IGNORECASE so logs with different case still match.
#  - If you add keywords that are substrings of others, prefer more specific
#    patterns first or use word boundaries to avoid accidental partial matches.
#  - `clean_text()` currently removes the literal `KEYWORD` using `str.replace()`
#    (case-sensitive). If you need case-insensitive removal for multiple
#    keywords, switch to `re.sub()` with flags=re.IGNORECASE or loop over
#    uppercase/lowercase variants.


# Exported constants used by the GUI and watcher.
# Keep `KEYWORD` as a convenience for the UI; `MARKER_RE` is the authoritative
# pattern used when scanning logs.



KEYWORD = "** STATION TONE"
MARKER_RE = re.compile(r"\*\*\s*\[?STATION\s+TONE\]?", re.IGNORECASE)


def clean_text(raw: str) -> str:
    """Return a cleaned message string suitable for speaking.

    - Removes the marker (if still present)
    - Removes timestamps like [HH:MM:SS]
    - Removes the literal KEYWORD
    - Strips surrounding whitespace
    """
    if not raw:
        return ''

    m = MARKER_RE.search(raw)
    if m:
        raw = raw[m.end():]

    # Remove timestamps
    s = re.sub(r"\[\d{2}:\d{2}:\d{2}\]", '', raw)
    # Remove literal keyword
    s = s.replace(KEYWORD, '')
    return s.strip()


# Examples (for reference):
#
#   raw = "[12:34:56] ** STATION TONE Emergency at the docks"
#   MARKER_RE will match the "** STATION TONE" portion and `clean_text` will
#   return "Emergency at the docks".
#
# To add detection for another marker like "** ALERT", edit MARKER_RE above
# (for example: re.compile(r"(?:\*\*\s*\[?STATION\s+TONE\]?|\*\*\s*ALERT)", re.I))
# and, if you want the UI test string to reflect the new default, update
# KEYWORD too (or keep KEYWORD for backward compatibility and add a separate
# DEFAULT_KEYWORD variable if you prefer).
