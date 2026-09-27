"""Input guardrails (SPEC §8.1) that don't need an LLM: sanitising and length limits, prompt
injection scoring, PII redaction and harmful-intent detection. All are pure functions."""

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from app.core.exceptions import InvalidQueryError

# ---------------------------------------------------------------- sanitising & length
_CONTROL_CHARS = {"Cc", "Cf"}  # control + format (zero-width, bidi overrides)


def sanitize_query(raw: str, *, min_chars: int, max_chars: int) -> str:
    """Strip control/format characters, collapse whitespace, then enforce length limits."""
    cleaned = "".join(
        " " if unicodedata.category(ch) in _CONTROL_CHARS else ch
        for ch in unicodedata.normalize("NFKC", raw)
    )
    cleaned = " ".join(cleaned.split())
    if len(cleaned) < min_chars:
        raise InvalidQueryError(f"The question must be at least {min_chars} characters long.")
    if len(cleaned) > max_chars:
        raise InvalidQueryError(f"The question must be at most {max_chars} characters long.")
    return cleaned


# ---------------------------------------------------------------- prompt injection
@dataclass(frozen=True, slots=True)
class InjectionRule:
    name: str
    pattern: re.Pattern[str]
    weight: float


def _rule(name: str, pattern: str, weight: float) -> InjectionRule:
    return InjectionRule(name, re.compile(pattern, re.IGNORECASE), weight)


INJECTION_RULES: tuple[InjectionRule, ...] = (
    _rule(
        "ignore_instructions",
        r"\b(ignore|disregard|forget|override|bypass)\b.{0,40}\b(previous|prior|above|earlier|"
        r"all|your|system|the)\b.{0,20}\b(instructions?|prompts?|rules|guidelines|context)\b",
        1.0,
    ),
    _rule(
        "reveal_prompt",
        r"\b(reveal|show|print|repeat|output|display|leak|tell me)\b.{0,30}\b(your|the|system|"
        r"hidden|initial)\b.{0,15}\b(instructions?|prompt|system prompt|rules|guidelines)\b",
        1.0,
    ),
    _rule("system_prompt_mention", r"\bsystem\s*prompt\b", 0.6),
    _rule("persona_switch", r"\byou\s+are\s+now\b|\bfrom\s+now\s+on\s+you\b", 0.7),
    _rule(
        "role_play",
        r"\b(pretend\s+(to\s+be|you\s+are)|act\s+as\s+(an?\s+)?(unrestricted|unfiltered|evil|"
        r"different)|role-?play\s+as)\b",
        0.6,
    ),
    _rule("jailbreak_terms", r"\b(jailbreak|DAN\b|do\s+anything\s+now|developer\s+mode)\b", 1.0),
    _rule(
        "no_restrictions", r"\bwithout\s+(any\s+)?(restrictions|filters|limitations|rules)\b", 0.5
    ),
    _rule("new_instructions", r"\b(new|updated)\s+instructions?\s*:", 0.8),
    _rule("fake_role_tags", r"<\s*/?\s*(system|assistant|instructions?)\s*>|#{2,}\s*system\b", 1.0),
)


@dataclass(frozen=True, slots=True)
class InjectionResult:
    score: float
    matched: tuple[str, ...]
    blocked: bool


def detect_prompt_injection(text: str, *, block_score: float) -> InjectionResult:
    matched = tuple(rule.name for rule in INJECTION_RULES if rule.pattern.search(text))
    score = round(sum(r.weight for r in INJECTION_RULES if r.name in matched), 3)
    return InjectionResult(score=score, matched=matched, blocked=score >= block_score)


# ---------------------------------------------------------------- PII redaction
_PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    # Aadhaar: 12 digits, first digit 2-9, often grouped 4-4-4.
    ("AADHAAR", re.compile(r"(?<![\d-])[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}(?![\d-])")),
    # PAN: 5 letters, 4 digits, 1 letter.
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b", re.IGNORECASE)),
    # Indian mobile numbers with optional +91/0 prefix and common separators.
    ("PHONE", re.compile(r"(?<![\d+])(?:\+?91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")),
)


@dataclass(frozen=True, slots=True)
class RedactionResult:
    text: str
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def redacted(self) -> bool:
        return bool(self.counts)


def redact_pii(text: str) -> RedactionResult:
    """Replace Aadhaar, PAN, phone numbers and emails with [REDACTED_<TYPE>] placeholders."""
    counts: Counter[str] = Counter()
    for label, pattern in _PII_PATTERNS:
        text, n = pattern.subn(f"[REDACTED_{label}]", text)
        if n:
            counts[label] += n
    return RedactionResult(text=text, counts=dict(counts))


# ---------------------------------------------------------------- harmful intent
# Asking HOW to commit or conceal an offence is refused; asking what the law SAYS is fine.
_HOW_TO = (
    r"\b(how\s+(do|can|could|should|would|to)\s+(i|we|you|one|someone)?\s*|help\s+me\s+(to\s+)?"
    r"|ways?\s+to\s+|steps?\s+to\s+|tips?\s+(on|for)\s+|teach\s+me\s+(how\s+)?to\s+)"
)
_HARMFUL_ACTS = (
    r"(commit|get\s+away\s+with|escape\s+punishment|evade\s+(the\s+)?(police|arrest|law|"
    r"detection|tax)|avoid\s+(getting\s+)?(caught|arrested|detected|detection)|hide\s+"
    r"(evidence|a\s+body|the\s+body|money|proceeds)|destroy\s+(the\s+)?evidence|tamper\s+with\s+"
    r"(evidence|witnesses)|launder|bribe\s+(a|the|an)|forge|fake\s+(a\s+)?(document|signature|"
    r"certificate)|stalk|kill|murder|poison|kidnap|smuggle|threaten\s+(a\s+)?witness|"
    r"hack\s+into|steal)"
)
HARMFUL_INTENT_RE = re.compile(_HOW_TO + r".{0,40}?\b" + _HARMFUL_ACTS + r"\b", re.IGNORECASE)


def detect_harmful_intent(text: str) -> bool:
    return bool(HARMFUL_INTENT_RE.search(text))
