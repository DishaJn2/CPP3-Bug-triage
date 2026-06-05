_BAD_DOMAINS = (
    "confluence.example.com",
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "example.com",
    "mock.",
    "placeholder",
)


def sanitize_bug_url(
    url: str,
    system_type: str = "",
    bug_id: str = "",
    base_url: str = "",
) -> str:
    """
    Returns the URL unchanged if it looks real.
    If the URL contains a placeholder/mock domain, attempts to reconstruct
    a valid URL from the connector's base_url. Returns "" if unresolvable.
    """
    if not url:
        return ""

    is_bad = any(bad in url.lower() for bad in _BAD_DOMAINS)
    if not is_bad:
        return url

    if not base_url:
        return ""

    base = base_url.rstrip("/")
    st = (system_type or "").lower()

    if "jira" in st:
        return f"{base}/browse/{bug_id}"
    elif "github" in st:
        return f"{base}/issues/{bug_id.lstrip('#')}"
    elif "bugzilla" in st:
        return f"{base}/show_bug.cgi?id={bug_id.replace('BZ-', '')}"
    else:
        return f"{base}/{bug_id}"
