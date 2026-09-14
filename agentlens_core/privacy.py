"""One best-effort redaction and residual-detection policy for all boundaries.

    This detects specified credential/PII formats, not all possible personal data.
    Manual review remains required before sharing traces.
"""
from __future__ import annotations

import json
import re
import warnings
from functools import lru_cache
from typing import Any

REDACTED = '[REDACTED]'
_MARKERS = {REDACTED, '[PII]', '[EMAIL]', '[TOKEN]', '[API_KEY]', '[SECRET]', '[PASSWORD]', '[PERSON]', '[PHONE]', '[CARD]', '[SSN]', '[ID]'}
_SECRET_KEYS = {'apikey', 'accesskey', 'accesskeyid', 'secretaccesskey', 'accesstoken', 'refreshtoken', 'idtoken', 'authtoken', 'sessiontoken', 'bearertoken', 'clientsecret', 'privatekey', 'password', 'passwd', 'pwd', 'secret', 'token', 'bearer', 'authorization', 'proxyauthorization', 'cookie', 'setcookie', 'auth'}
_PII_KEYS = {'fullname', 'firstname', 'lastname', 'customername', 'patientname', 'personname', 'street', 'streetaddress', 'homeaddress', 'mailingaddress', 'dob', 'dateofbirth', 'ssn', 'socialsecurity', 'phonenumber', 'creditcard', 'cardnumber', 'accountnumber', 'routingnumber', 'passport', 'licensenumber', 'email'}
_KEY_PATTERN = '|'.join('[_.-]*'.join(re.escape(char) for char in key) for key in sorted(_SECRET_KEYS | _PII_KEYS, key=len, reverse=True))
_ASSIGN = re.compile(r'''(?i)\b((?:[a-z][a-z0-9_.-]*?)?(?:''' + _KEY_PATTERN + r'''))\s*["']?\s*[:=]\s*(?:"[^"\n]*"|'[^'\n]*'|[^\s,;}]+)''')
_PATTERNS = {
    'email': re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'),
    'bearer': re.compile(r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+'),
    'api_key': re.compile(r'\b(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]+|AKIA[A-Z0-9]{16}|xox[baprs]-[A-Za-z0-9-]{10,})'),
    'url_credentials': re.compile(r'(?i)[a-z][a-z0-9+.-]*://[^\s/@:]+:[^\s/@]+@'),
    'private_key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?(?:-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|$)'),
    'ssn': re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),
    'phone': re.compile(r'(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b'),
    'card': re.compile(r'\b(?:\d[ -]?){15,16}\b'),
}


def key_kind(key: str) -> str | None:
    normalized = re.sub('[^a-z0-9]', '', key.lower())
    if normalized in _SECRET_KEYS or any(normalized.endswith(k) for k in ('apikey', 'password', 'secret', 'accesstoken', 'refreshtoken')):
        return 'credential'
    return 'pii' if normalized in _PII_KEYS else None


def _decoded(text: str) -> Any:
    try:
        return json.loads(text)
    except (ValueError, RecursionError):
        return None


@lru_cache(maxsize=1)
def _name_model() -> Any:
    try:
        import spacy
    except ImportError:
        return None
    try:
        return spacy.load('en_core_web_sm')
    except OSError:
        warnings.warn('Optional person-name redaction is unavailable. Install runlens[pii], then run: python -m spacy download en_core_web_sm. Review names manually before sharing.', RuntimeWarning)
        return None


def _fragment_text(text: str) -> str:
    # Provider errors can contain escaped JSON fragments rather than a JSON document.
    return re.sub(r"""\\+(["'])""", r"\1", text)


def _redact_text(text: str, depth: int = 0) -> str:
    decoded = _decoded(text)
    if isinstance(decoded, (dict, list)) or isinstance(decoded, str) and decoded != text:
        return json.dumps(anonymize(decoded, depth + 1), ensure_ascii=True)
    text = _fragment_text(text)
    for pattern in _PATTERNS.values():
        text = pattern.sub(REDACTED, text)
    text = _ASSIGN.sub(lambda m: m.group(1) + '=' + REDACTED if key_kind(m.group(1)) else m.group(0), text)
    model = _name_model()
    if model is not None and len(text) < model.max_length:
        for entity in reversed(list(model(text).ents)):
            if entity.label_ == 'PERSON':
                text = text[:entity.start_char] + '[PERSON]' + text[entity.end_char:]
    return text


def anonymize(value: Any, _depth: int = 0) -> Any:
    if _depth > 40:
        return REDACTED
    if isinstance(value, dict):
        return {_redact_text(str(k), _depth): REDACTED if key_kind(str(k)) else anonymize(v, _depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [anonymize(v, _depth + 1) for v in value]
    if isinstance(value, str):
        return _redact_text(value, _depth)
    return value


def residual(value: Any) -> list[str]:
    found: set[str] = set()

    def scan(item: Any, depth: int = 0) -> None:
        if depth > 40:
            found.add('excessive nesting')
            return
        if isinstance(item, dict):
            for key, val in item.items():
                kind = key_kind(str(key))
                if kind and val not in (None, '') and not (isinstance(val, str) and val in _MARKERS):
                    found.add(kind)
                scan(str(key), depth + 1)
                scan(val, depth + 1)
        elif isinstance(item, list):
            for val in item:
                scan(val, depth + 1)
        elif isinstance(item, str):
            decoded = _decoded(item)
            if isinstance(decoded, (dict, list)) or isinstance(decoded, str) and decoded != item:
                scan(decoded, depth + 1)
                return
            clean = _fragment_text(item)
            for marker in _MARKERS:
                clean = clean.replace(marker, '')
            for kind, pattern in _PATTERNS.items():
                if pattern.search(clean):
                    found.add(kind)
            if any(key_kind(match.group(1)) for match in _ASSIGN.finditer(clean)):
                found.add('credential')
            model = _name_model()
            if model is not None and len(clean) < model.max_length and any(e.label_ == 'PERSON' for e in model(clean).ents):
                found.add('person')
    scan(value)
    return sorted(found)
