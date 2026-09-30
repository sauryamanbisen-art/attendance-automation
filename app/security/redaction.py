"""Security and secret redaction utilities."""

import re
from typing import Any

# Sensitive field name patterns
SENSITIVE_KEY_PATTERN = re.compile(
    r"(password|secret|token|credential|cookie|auth|session|key|private|auth_code|oauth_code)",
    re.IGNORECASE,
)

# Text pattern for bearer tokens or basic auth in strings
BEARER_PATTERN = re.compile(r"(Bearer\s+)[A-Za-z0-9\-\._~\+\/]+=*", re.IGNORECASE)
QUERY_SECRET_PATTERN = re.compile(
    r"((?:token|api_key|password|secret|code|auth_code)=)[^&\s]+",
    re.IGNORECASE,
)


def redact_string(text: str) -> str:
    """Mask sensitive patterns inside a string."""
    if not text:
        return text
    redacted = BEARER_PATTERN.sub(r"\1[REDACTED]", text)
    redacted = QUERY_SECRET_PATTERN.sub(r"\1[REDACTED]", redacted)
    return redacted


def redact_data(data: Any) -> Any:
    """Recursively redact dictionary or list values with sensitive keys."""
    if isinstance(data, dict):
        cleaned: dict[str, Any] = {}
        for k, v in data.items():
            if isinstance(k, str) and SENSITIVE_KEY_PATTERN.search(k):
                cleaned[k] = "[REDACTED]"
            elif isinstance(v, (dict, list)):
                cleaned[k] = redact_data(v)
            elif isinstance(v, str):
                cleaned[k] = redact_string(v)
            else:
                cleaned[k] = v
        return cleaned
    elif isinstance(data, list):
        return [redact_data(item) for item in data]
    elif isinstance(data, str):
        return redact_string(data)
    return data
