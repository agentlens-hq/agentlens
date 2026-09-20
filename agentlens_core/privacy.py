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
_SECRET_KEYS.update(base + suffix for base in ('apikey', 'credential', 'token', 'key') for suffix in ('hint', 'prefix', 'suffix', 'last4'))
# Provider namespaces preserve the meaning of compound credential names. Avoid
# generic "token" suffix matching, which would also catch non-secret metrics.
_SECRET_SUFFIXES = {'password', 'secret'} | {
    key for key in _SECRET_KEYS if key != 'token' and key.endswith(('key', 'keyid', 'token'))
}
_PII_KEYS = {'fullname', 'firstname', 'lastname', 'customername', 'patientname', 'personname', 'street', 'streetaddress', 'homeaddress', 'mailingaddress', 'dob', 'dateofbirth', 'ssn', 'socialsecurity', 'phonenumber', 'creditcard', 'cardnumber', 'accountnumber', 'routingnumber', 'passport', 'licensenumber', 'email'}
_KEY_PATTERN = '|'.join('[_.-]*'.join(re.escape(char) for char in key) for key in sorted(_SECRET_KEYS | _PII_KEYS, key=len, reverse=True))
_ASSIGN = re.compile(r'''(?i)\b((?:[a-z][a-z0-9_.-]*?)?(?:''' + _KEY_PATTERN + r'''))\s*["']?\s*[:=]\s*("[^"\n]*"|'[^'\n]*'|[^\s,;}]+)''')
_HINT_LABEL = r'(?:api[ _-]*key|(?:access|auth|session|bearer)[ _-]*token|credentials?|password|secret|key[ _-]*(?:hint|prefix|suffix))'
_HINT_VALUE = r'''(?:"[^"\n]*"|'[^'\n]*'|[^\s,;}"']+)'''
_MASK = r'(?:\*{2,}|\.{3,}|[\u2022\u2026]+|\[(?:REDACTED|MASKED)\])'
_CREDENTIAL_PATTERNS = {
    # Masked provider echoes are still secrets: consume both sides of the mask.
    'masked_key': re.compile(r'\bsk-[A-Za-z0-9_-]+[ \t]*' + _MASK + r'[ \t]*[A-Za-z0-9_-]+'),
    'masked_bearer': re.compile(r'(?i)\bBearer[ \t]+[A-Za-z0-9_+/-]+[ \t]*' + _MASK + r'[ \t]*[A-Za-z0-9_+/=-]+'),
    'authorization': re.compile(r'''(?i)\b(?:proxy[-_ ]?)?authorization["']?[ \t]*[:=][ \t]*(?:"[^"\n]*"|'[^'\n]*'|[^\s;}][^\r\n;}]*)'''),
    'bearer': re.compile(r'(?i)\bBearer[ \t]+[A-Za-z0-9._~+/*=\-\u2022\u2026]+'),
    'api_key': re.compile(r'\b(?:sk-(?:[A-Za-z0-9_*.\-\u2022\u2026]|\[(?:REDACTED|MASKED)\])+|gh[pousr]_[A-Za-z0-9_*.-]{12,}|github_pat_[A-Za-z0-9_*.-]+|AKIA[A-Z0-9*]{16}|xox[baprs]-[A-Za-z0-9*.-]{10,})'),
    'url_credentials': re.compile(r'(?i)(?<![a-z0-9+.-])[a-z][a-z0-9+.-]*://[^\s/@:]+:[^\s/@]+@'),
    'private_key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?(?:-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|$)'),
    'credential_hint': re.compile(r'(?i)(\b' + _HINT_LABEL + r'(?:[ \t]+(?:provided|hint|prefix|suffix|value))?[ \t]*[:=][ \t]*|\b(?:' + _HINT_LABEL + r'|key)[ \t]+(?:ending in|ending with|ends with|starting with|starts with|begins with|prefix|suffix|hint)[ \t]+(?:is[ \t]+)?)(' + _HINT_VALUE + ')'),
}
_PATTERNS = {
    **_CREDENTIAL_PATTERNS,
    'email': re.compile(r'(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'),
    'ssn': re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),
    'phone': re.compile(r'(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b'),
    'card': re.compile(r'\b(?:\d[ -]?){15,16}\b'),
}


def key_kind(key: str) -> str | None:
    normalized = re.sub('[^a-z0-9]', '', key.lower())
    if normalized in _SECRET_KEYS or any(normalized.endswith(k) for k in _SECRET_SUFFIXES):
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


def _redact_text(text: str, depth: int = 0, credentials_only: bool = False) -> str:
    decoded = _decoded(text)
    if isinstance(decoded, (dict, list)) or isinstance(decoded, str) and decoded != text:
        cleaned = _redact(decoded, depth + 1, credentials_only)
        return text if credentials_only and cleaned == decoded else json.dumps(cleaned, ensure_ascii=True)
    original = text
    text = _fragment_text(text)
    unescaped = text
    for kind, pattern in (_CREDENTIAL_PATTERNS if credentials_only else _PATTERNS).items():
        text = pattern.sub(lambda m: (m.group(1) if kind == 'credential_hint' else '') + REDACTED, text)
    text = _ASSIGN.sub(lambda m: m.group(1) + '=' + REDACTED if key_kind(m.group(1)) in (('credential',) if credentials_only else ('credential', 'pii')) else m.group(0), text)
    model = None if credentials_only else _name_model()
    if model is not None and len(text) < model.max_length:
        for entity in reversed(list(model(text).ents)):
            if entity.label_ == 'PERSON':
                text = text[:entity.start_char] + '[PERSON]' + text[entity.end_char:]
    return original if credentials_only and text == unescaped else text


def anonymize(value: Any, _depth: int = 0) -> Any:
    return _redact(value, _depth, credentials_only=False)


def redact_credentials(value: Any) -> Any:
    """Remove credentials at capture/read boundaries without PII/NLP processing."""
    return _redact(value, 0, credentials_only=True)


def exception_message(error: BaseException | str) -> str:
    """Authentication responses can contain opaque hints no regex can recognize."""
    status = getattr(error, 'status_code', None)
    if type(status) is int and status in (401, 403):
        body = getattr(error, 'body', None)
        detail = body.get('error', body) if isinstance(body, dict) else {}
        code = detail.get('code') or detail.get('type') if isinstance(detail, dict) else None
        known = {'invalid_api_key', 'authentication_error', 'invalid_request_error',
                 'permission_denied', 'invalid_token', 'insufficient_permissions'}
        suffix = f' ({code})' if isinstance(code, str) and code in known else ''
        return f'HTTP {status}: Authentication or authorization failed{suffix}. Provider credential details omitted.'
    return str(redact_credentials(str(error)))


def _redact(value: Any, depth: int, credentials_only: bool) -> Any:
    if depth > 40:
        return REDACTED
    if isinstance(value, dict):
        kinds = ('credential',) if credentials_only else ('credential', 'pii')
        return {_redact_text(str(k), depth, credentials_only): REDACTED if key_kind(str(k)) in kinds else _redact(v, depth + 1, credentials_only) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(v, depth + 1, credentials_only) for v in value]
    if isinstance(value, str):
        return _redact_text(value, depth, credentials_only)
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
            for kind, pattern in _PATTERNS.items():
                if any(kind != 'credential_hint' or match.group(2).strip('\"\'') not in _MARKERS for match in pattern.finditer(clean)):
                    found.add(kind)
            if any(key_kind(match.group(1)) and match.group(2).strip('\"\'') not in _MARKERS for match in _ASSIGN.finditer(clean)):
                found.add('credential')
            for marker in _MARKERS:
                clean = clean.replace(marker, '')
            model = _name_model()
            if model is not None and len(clean) < model.max_length and any(e.label_ == 'PERSON' for e in model(clean).ents):
                found.add('person')
    scan(value)
    return sorted(found)
