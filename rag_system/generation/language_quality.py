"""Unified language quality checker — shared by auditor modules."""
from dataclasses import dataclass, field
from rag_system.generation.glossary import (
    FORBIDDEN_WORDS, ECOMMERCE_SMELL_ALL, ASSEMBLY_VERBS, FAKE_CASUAL_MARKERS,
)

@dataclass
class LanguageQualityResult:
    passed: bool
    forbidden_words: list[str] = field(default_factory=list)
    ecommerce_smell: list[str] = field(default_factory=list)
    assembly_verbs: list[str] = field(default_factory=list)
    fake_casual: list[str] = field(default_factory=list)
    total_violations: int = 0

def check_language_quality(text: str, tolerance_forbidden=0, tolerance_ecommerce=1,
                           tolerance_assembly=0, tolerance_fake_casual=1) -> LanguageQualityResult:
    forbidden = [w for w in FORBIDDEN_WORDS if w in text]
    ecommerce = [w for w in ECOMMERCE_SMELL_ALL if w in text]
    assembly = [w for w in ASSEMBLY_VERBS if w in text]
    fake = [w for w in FAKE_CASUAL_MARKERS if w in text]
    total = len(forbidden) + len(ecommerce) + len(assembly) + len(fake)
    passed = (len(forbidden) <= tolerance_forbidden and len(ecommerce) <= tolerance_ecommerce
              and len(assembly) <= tolerance_assembly and len(fake) <= tolerance_fake_casual)
    return LanguageQualityResult(passed=passed, forbidden_words=forbidden, ecommerce_smell=ecommerce,
                                 assembly_verbs=assembly, fake_casual=fake, total_violations=total)
