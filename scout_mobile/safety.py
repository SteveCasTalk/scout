"""Safety policy patterns shared by the run engine and the deterministic execution runtime."""
from __future__ import annotations
import re

GUARD_TEXT='This application is not supported on rooted devices or emulators.'
RISKY=re.compile(r'\b(?:pay|purchase|buy|transfer|delete account|subscribe|withdraw)\b',re.I)
CONSENT_GATE=re.compile(r'\b(?:user agreement|terms of (?:use|service)|privacy policy|consent|personal data processing)\b',re.I)
CONSENT_ACTION=re.compile(r'^\s*(?:i\s+agree|agree(?:\s+and\s+continue)?|accept(?:\s+all)?|continue\s+and\s+accept|allow|authorize|consent|grant|start|continue|confirm|submit|yes)\s*$',re.I)
EMAIL_VALUE=re.compile(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b',re.I)
EMAIL_FIELD=re.compile(r'email|e-mail|username|user name|account',re.I)
PASSWORD_FIELD=re.compile(r'password|passcode|pass word|passwd',re.I)
PRIVATE_CODE_FIELD=re.compile(r'(?:^|[^a-z0-9])(?:pin|otp|one[- _]?time[- _]?code|verification[- _]?code|security[- _]?code)(?:$|[^a-z0-9])',re.I)
SWIPE_INSTRUCTION=re.compile(r'\bswipe\s+up\b',re.I)
DATE_OF_BIRTH_GATE=re.compile(r'\b(?:your\s+)?birthday\b|\bdate\s+of\s+birth\b|\bdate\s+of\s+birthday\b',re.I)
SELECTED_DATE_LABEL=re.compile(r'\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})\b')
DATE_VALUE=re.compile(r'\b(\d{4})/(\d{2})/(\d{2})\b')
CREDENTIAL_MANAGER='com.android.credentialmanager'

def known_credential_prompt(text:str)->bool:
    return 'Google Password Manager' in text or 'Save password for UAT-AI Avatar?' in text
