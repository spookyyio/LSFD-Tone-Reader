import re

# Exported constants used by the GUI and watcher
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
