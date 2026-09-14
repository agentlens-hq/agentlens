"""Local-first diagnosis with explicit, bounded remote opt-in."""
from __future__ import annotations

import math
import os
from typing import Any

from agentlens_core.privacy import anonymize, residual
from agentlens_core.trace import normalize_run, text_content

from .classifier import (
    SYSTEM_PROMPT,
    build_user_prompt,
    classify_from_evidence,
    parse_diagnosis,
    validate_diagnosis,
)
from .fixes import generate_fix
from .hallucination import detect_hallucinations
from .impact import compute_impact
from .preprocess import preprocess_run


def diagnose_run(run_json: dict[str, Any], use_llm: bool = False, *, provider: str | None = None, timeout: float = 10.0) -> dict[str, Any]:
    if use_llm and provider is None:
        raise ValueError('Remote diagnosis requires an explicit provider: openai or anthropic.')
    if provider not in (None, 'openai', 'anthropic'):
        raise ValueError('Unsupported diagnosis provider.')
    if not math.isfinite(timeout) or not 0 < timeout <= 10:
        raise ValueError('Remote read timeout must be between 0 and 10 seconds.')
    run = normalize_run(run_json)
    compact = preprocess_run(run['spans'], run)
    remote = _diagnose_with_llm(compact, provider, timeout) if provider else None
    if remote is not None and validate_diagnosis(remote, compact):
        remote = None
    diagnosis = remote if remote is not None else classify_from_evidence(compact)
    diagnosis['diagnosis_source'] = 'llm' if remote is not None else 'heuristic'
    diagnosis.setdefault('evidence_strength', 'uncalibrated' if remote is not None else 'insufficient')
    diagnosis['confidence_note'] = 'Evidence-strength score, not a calibrated probability.'
    if provider and remote is None:
        diagnosis['remote_warning'] = 'Remote diagnosis failed or lacked grounded evidence; local rules were used.'
    if remote is None:
        diagnosis['fix'] = generate_fix(diagnosis['root_cause_category'], compact, diagnosis)
    diagnosis['hallucinations'] = detect_hallucinations(run['spans'], compact.get('tool_definitions') or [])
    diagnosis['impact'] = compute_impact(run['spans'], diagnosis)
    if diagnosis['root_cause_category'] == 'unknown' or diagnosis['confidence'] < .6:
        diagnosis['low_confidence_message'] = 'Insufficient evidence to isolate a root cause. No failure is asserted.'
        diagnosis['likely_causes'] = []
        diagnosis['likely_fixes'] = []
    errors = validate_diagnosis(diagnosis, compact)
    if errors:
        raise ValueError('Invalid diagnosis: ' + '; '.join(errors))
    return diagnosis


def _diagnose_with_llm(compact: dict[str, Any], provider: str, timeout: float) -> dict[str, Any] | None:
    cleaned = anonymize(compact)
    if residual(cleaned):
        return None
    prompt = build_user_prompt(cleaned)
    if len(prompt.encode()) > 60000:
        return None
    try:
        import httpx
        timeouts = httpx.Timeout(timeout, connect=3.0)
        client: Any
        if provider == 'openai':
            from openai import OpenAI
            client = OpenAI(timeout=timeouts, max_retries=0)
        else:
            from anthropic import Anthropic
            client = Anthropic(timeout=timeouts, max_retries=0)
        with client:
            for _ in range(2):
                if provider == 'openai':
                    response = client.chat.completions.create(
                        model=os.getenv('AGENTLENS_OPENAI_MODEL', 'gpt-4.1-mini'),
                        messages=[{'role': 'system', 'content': SYSTEM_PROMPT}, {'role': 'user', 'content': prompt}],
                        response_format={'type': 'json_object'}, max_tokens=1500)
                    raw = response.choices[0].message.content
                else:
                    response = client.messages.create(
                        model=os.getenv('AGENTLENS_ANTHROPIC_MODEL', 'claude-sonnet-4-20250514'),
                        max_tokens=1500, system=SYSTEM_PROMPT,
                        messages=[{'role': 'user', 'content': prompt}])
                    raw = text_content(response.model_dump().get('content'))
                try:
                    diagnosis = parse_diagnosis(raw or '')
                    if not validate_diagnosis(diagnosis, cleaned):
                        return diagnosis
                except (TypeError, ValueError):
                    pass
                prompt += '\nReturn valid JSON with exact evidence quotes and original step references.'
    except Exception:
        return None
    return None
