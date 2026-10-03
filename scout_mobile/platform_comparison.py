"""Read-only Jev assessment of matched, saved platform checkpoint observations."""
from __future__ import annotations
from .config import getenv
import os
from typing import Any
from .model import ModelError, post_json, validate_choice

CHOICES = {
    'same': 'Same behavior: both observations show equivalent behavior for this expectation. Matching verdicts alone are insufficient.',
    'expected_difference': 'Expected platform difference: a difference explicitly allowed by expected_differences explains the observations.',
    'inconsistency': 'Possible inconsistency: the observed behavior differs for the same expectation. This is a suspected issue, not a confirmed bug.',
    'unknown': 'Insufficient evidence: observations are incomplete, ambiguous, incomparable, or do not support a confident comparison.',
}
LABELS = dict(zip(CHOICES, ['Same behavior', 'Expected platform difference', 'Possible inconsistency', 'Insufficient evidence']))

def assess(packet: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(packet, dict) or len(str(packet)) > 250000:
        raise ValueError('Invalid or oversized comparison packet.')
    rows = packet.get('checkpoints')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 24:
        raise ValueError('No comparable checkpoints with sufficient evidence.')
    key = getenv('TYPESAFE_API_KEY')
    if not key:
        raise ModelError('TYPESAFE_API_KEY is missing from local .env.')
    questions = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get('id'), str):
            raise ValueError('Invalid comparison checkpoint.')
        choices = {k:v for k,v in CHOICES.items() if k != 'expected_difference' or packet.get('expected_differences')}
        questions[f'checkpoint_{index}'] = {'type':'choice', 'criteria': choices, 'instructions': {'rules': packet.get('instruction'), 'expected_differences': packet.get('expected_differences'), 'context': packet.get('context'), 'checkpoint':row}}
    body = {'model':getenv('TYPESAFE_MODEL','jev-latest'), 'state':{'page':{'url':'comparison://saved-runs','title':'Android and iOS checkpoint evidence','text':'Read-only comparison of saved observations; no device actions.'}}, 'questions':questions}
    response = post_json('https://api.typesafe.ai/v1/systemone',key,body)
    assessments = []
    for index,row in enumerate(rows):
        question = f'checkpoint_{index}'
        answer = response.get('answers',{}).get(question,{})
        choice = validate_choice(answer,set(questions[question]['criteria']))
        confidence = answer['confidence']
        if confidence < .85:
            choice = 'unknown'
        reason = f"{CHOICES[choice]} Android: {str(row.get('android',{}).get('observed',''))[:650]} iOS: {str(row.get('ios',{}).get('observed',''))[:650]}"
        assessments.append({'checkpoint_id':row['id'],'conclusion':LABELS[choice],'confidence':confidence,'reason':reason})
    return {'model':response.get('model') or body['model'], 'assessments':assessments}
