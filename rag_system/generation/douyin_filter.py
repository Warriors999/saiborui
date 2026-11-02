"""Douyin/TikTok prohibited words filter.

Filters content before output to avoid platform compliance issues.
Replaces prohibited terms with safer alternatives rather than just removing them.
"""

import re
from rag_system.generation.glossary import PROHIBITED_PHRASES, PROHIBITED_PATTERNS, FILLER_PHRASES

# (word lists now imported from glossary.py)

def filter_prohibited(text: str) -> tuple[str, list[str]]:
    """Filter prohibited words from text.
    Returns (filtered_text, list_of_replacements_made).
    """
    changes: list[str] = []
    result = text

    # Phase 1: Exact phrase replacement
    for prohibited, replacement in PROHIBITED_PHRASES.items():
        if prohibited in result:
            result = result.replace(prohibited, replacement)
            changes.append(f"「{prohibited}」→「{replacement}」")

    # Phase 2: Regex pattern replacement
    for pattern, replacement in PROHIBITED_PATTERNS:
        matches = re.findall(pattern, result)
        if matches:
            result = re.sub(pattern, replacement, result)
            for m in matches[:3]:
                changes.append(f"「{m}」(正则) → 已替换")

    return result, changes


def validate_no_prohibited(text: str) -> list[str]:
    """Check text for remaining prohibited words. Returns list of violations found."""
    violations = []
    for phrase in PROHIBITED_PHRASES:
        if phrase in text:
            violations.append(phrase)
    return violations


# ── Filler phrase density reducer ──
# These are "口头禅" that the competitive wiki marks as 应避免的低级套路.
# They add no information and make the speaker sound uncertain.
# Strategy: remove standalone instances, reduce consecutive clusters to at most 1.
# (FILLER_PHRASES imported from rag_system.generation.glossary)

# Patterns where a filler is the ENTIRE sentence (just the filler + optional punctuation)
FILLER_STANDALONE = re.compile(
    r'(?:^|\n)(' + '|'.join(re.escape(f) for f in FILLER_PHRASES) + r')(?:[。！？，,\.\s]*(?:\n|$))',
    re.MULTILINE,
)

# Filler clusters: 2+ fillers in a row (with optional whitespace/punctuation between)
FILLER_CLUSTER = re.compile(
    r'(' + '|'.join(re.escape(f) for f in FILLER_PHRASES) + r')'
    r'(?:[。！？，,\s]{0,4}'
    r'(' + '|'.join(re.escape(f) for f in FILLER_PHRASES) + r'))+',
)

# "我用下来" / "我用下来发现" — keep at most 1 per paragraph.
# First pass: mark paragraphs, then limit to 1 instance per paragraph.
OVERUSED_I_USED = re.compile(r'我用下来[发现]?[。，]?')


def reduce_filler_phrases(text: str) -> tuple[str, int]:
    """Reduce filler phrase density in generated scripts.

    Competitive wiki analysis shows that phrases like 说实话/有一说一/不吹不黑
    are the #2 most common quality issue in tech review scripts (72% violation rate).

    Returns (filtered_text, number_of_removals).
    """
    removals = 0
    result = text

    # Step 1: Remove standalone filler "sentences" (filler + period + newline)
    new_result = FILLER_STANDALONE.sub('', result)
    removals += len(result) - len(new_result)
    result = new_result

    # Step 2: Collapse filler clusters to single instance
    def _collapse_cluster(m):
        nonlocal removals
        # Keep only the first filler in the cluster
        parts = m.group(0).split()
        removals += 1
        return m.group(1)  # just the first filler

    # Don't auto-collapse — just remove redundant fillers in obvious clusters
    for filler in FILLER_PHRASES:
        # Remove filler when it appears right before another filler
        for other in FILLER_PHRASES:
            if filler != other:
                pattern = re.escape(filler) + r'[。！？，,\s]{0,4}' + re.escape(other)
                if re.search(pattern, result):
                    result = re.sub(pattern, other, result)
                    removals += 1

    # Step 3: Limit "我用下来" to once per paragraph
    paragraphs = result.split('\n\n')
    cleaned_paras = []
    for para in paragraphs:
        matches = list(OVERUSED_I_USED.finditer(para))
        if len(matches) > 1:
            # Keep first, remove rest
            for m in matches[1:]:
                para = para[:m.start()] + para[m.end():]
                removals += 1
        cleaned_paras.append(para)
    result = '\n\n'.join(cleaned_paras)

    # Step 4: Clean up double punctuation from removals
    result = re.sub(r'[。！？]{2,}', '。', result)
    result = re.sub(r'\n{3,}', '\n\n', result)
    result = re.sub(r'  +', ' ', result)

    return result, removals


def strip_huazi(text: str) -> tuple[str, int]:
    """Remove inline annotations and metadata headers from voiceover text.

    铁律#4: Huazi is separate from VO. Metadata headers (封面/简介/口播正文)
    are production artifacts, not spoken content.
    """
    cleaned = re.sub(r'[（(]花字[：:][^）)]*[）)]', '', text)
    cleaned = re.sub(r'^[（(]花字[：:].*$', '', cleaned, flags=re.MULTILINE)
    # Strip metadata headers
    cleaned = re.sub(r'^封面[ title标题]*[：:].*$', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'^简介[：:].*$', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'^口播正文[：:]?$', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    removed = len(text) - len(cleaned)
    return cleaned.strip(), removed
