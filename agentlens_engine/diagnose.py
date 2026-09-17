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
    remote = _verify_remote_diagnosis(remote, compact) if remote is not None else None
    diagnosis = remote if remote is not None else _supported_diagnosis(compact)
    diagnosis['diagnosis_source'] = 'llm' if remote is not None else 'heuristic'
    diagnosis.setdefault('evidence_strength', 'uncalibrated' if remote is not None else 'insufficient')
    diagnosis['confidence_note'] = 'Evidence-strength score, not a calibrated probability.'
    diagnosis['fix_status'] = 'unverified'
    if provider and remote is None:
        diagnosis['remote_warning'] = 'Remote diagnosis failed or did not match structurally supported claims; local rules were used.'
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


def _supported_diagnosis(compact: dict[str, Any]) -> dict[str, Any]:
    """One source of category predicates, origin ordering, facts and suggestions."""
    result = classify_from_evidence(compact)
    result['fix'] = generate_fix(result['root_cause_category'], compact, result)
    return result


def _verify_remote_diagnosis(value: Any, compact: dict[str, Any]) -> dict[str, Any] | None:
    """Fail closed: quotes alone cannot authorize model-authored causal prose.

    Recompute from the trace, not a candidate echoed back by the provider. Match
    the redacted representation the provider actually saw, then return only local
    facts/templates. Exact text is intentional: arbitrary paraphrase entailment
    is outside this narrow contract. Extra model metadata is never propagated.
    """
    if validate_diagnosis(value, anonymize(compact)):
        return None
    supported = _supported_diagnosis(compact)
    public = anonymize(supported)
    fields = ('root_cause_category', 'failed_at_step', 'failed_at_tool',
              'explanation', 'fix', 'secondary_issues', 'evidence')
    if any(value.get(field) != public[field] for field in fields):
        return None
    if value['confidence'] > supported['confidence']:
        return None
    supported['confidence'] = value['confidence']
    supported['remote_validation'] = 'Matched local structural rules and approved explanation/fix templates.'
    return supported


def _diagnose_with_llm(compact: dict[str, Any], provider: str, timeout: float) -> dict[str, Any] | None:
    cleaned = anonymize({'trace': compact, 'supported_diagnosis': _supported_diagnosis(compact)})
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
                    if _verify_remote_diagnosis(diagnosis, compact) is not None:
                        return diagnosis
                except (TypeError, ValueError):
                    pass
                prompt += '\nReturn valid JSON matching supported_diagnosis exactly; do not add claims or increase confidence.'
    except Exception:
        return None
    return None
