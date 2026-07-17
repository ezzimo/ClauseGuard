import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.anonymizer import mask_pii, unmask_text
from services.anonymizer.regex_rules import get_rules

FIXTURE = Path(__file__).parent / "fixtures" / "contrat_e2e.txt"


def test_1_rib_spaced_masked():
    text = "RIB: 011 780 0000123456789012 34"
    masked, mapping, stats = mask_pii(text)
    assert "[RIB_1]" in masked
    assert "011" not in masked
    assert "0000123456789012" not in masked


def test_2_iban_masked():
    text = "IBAN: MA64011519000001205000534921"
    masked, mapping, stats = mask_pii(text)
    assert "[IBAN_1]" in masked
    assert "MA64011519000001205000534921" not in masked


def test_3_party_full_name_and_surname_masked():
    text = (
        "Rachid Benjelloun et Salma El Fassi signent. "
        "BENJELLOUN accepte. el fassi refuse."
    )
    masked, mapping, stats = mask_pii(text, ["Rachid Benjelloun", "Salma El Fassi"])
    assert "Rachid Benjelloun" not in masked
    assert "Salma El Fassi" not in masked
    assert "Benjelloun" not in masked
    assert "BENJELLOUN" not in masked
    assert "El Fassi" not in masked
    assert "el fassi" not in masked
    assert mapping["[PARTIE_A]"] == "Rachid Benjelloun"
    assert mapping["[PARTIE_B]"] == "Salma El Fassi"


def test_3_signature_block_included():
    text = "\n\nRachid Benjelloun\nSalma El Fassi\n"
    masked, mapping, stats = mask_pii(text, ["Rachid Benjelloun", "Salma El Fassi"])
    assert "Rachid Benjelloun" not in masked
    assert "Salma El Fassi" not in masked


def test_4_first_name_alone_not_masked():
    text = "Rachid Benjelloun et Salma El Fassi signent. Rachid et Salma sont présents."
    masked, mapping, stats = mask_pii(text, ["Rachid Benjelloun", "Salma El Fassi"])
    assert "Rachid" in masked
    assert "Salma" in masked


def test_5_rc_amount_duration_article_preserved():
    text = (
        "RC 445621. Montant 840 000 MAD. Durée trente-six mois. Article 5."
    )
    masked, mapping, stats = mask_pii(text)
    assert "445621" in masked
    assert "840 000 MAD" in masked
    assert "trente-six mois" in masked
    assert "Article 5" in masked


def test_6_contextual_if_cnss_masked_bare_number_preserved():
    text = "IF: 123456. CNSS: 9876543. Référence 87654321."
    masked, mapping, stats = mask_pii(text)
    assert "[IF_1]" in masked
    assert "[CNSS_1]" in masked
    assert "123456" not in masked
    assert "9876543" not in masked
    assert "87654321" in masked


def test_7_spacing_preserved_no_glued_placeholder():
    text = "Tel  0612345678  et suite"
    masked, mapping, stats = mask_pii(text)
    assert "  [PHONE_1] " in masked
    assert not re.search(r"\[PHONE_\d+\]\w", masked)
    assert not re.search(r"\w\[PHONE_\d+\]", masked)


def test_8_verification_pass_second_pass_fixes(monkeypatch):
    # Simulate a first-pass miss: run the normal rule pass, then deliberately
    # restore any phone placeholders so the final verification sweep has to
    # catch the leak and increment second_pass_fixes.
    from services.anonymizer import pipeline

    original_mask_with_rules = pipeline._mask_with_rules

    def faulty_first_pass(text: str, store, stats: dict) -> str:
        masked = original_mask_with_rules(text, store, stats)
        for label, original in list(store.mapping.items()):
            if label.startswith("[PHONE_"):
                masked = masked.replace(label, original)
        return masked

    monkeypatch.setattr(pipeline, "_mask_with_rules", faulty_first_pass)

    text = "tel 0612345678 et 0612345678 aussi"
    masked, mapping, stats = mask_pii(text)
    assert "0612345678" not in masked
    assert stats["second_pass_fixes"] > 0


def test_9_full_fixture_regex_sweep_clean():
    text = FIXTURE.read_text(encoding="utf-8")
    party_names = ["Rachid Benjelloun", "Salma El Fassi"]
    masked, mapping, stats = mask_pii(text, party_names)

    for category, rule in get_rules():
        match = rule.search(masked)
        assert match is None, f"{category} still matches: {match.group(0)!r}"

    for name in party_names:
        assert name not in masked, f"party name leak: {name}"
        tokens = name.split()
        if len(tokens) > 1:
            surname = " ".join(tokens[1:])
            assert surname not in masked, f"party surname leak: {surname}"


def test_10_mapping_round_trip_restores_original():
    text = FIXTURE.read_text(encoding="utf-8")
    party_names = ["Rachid Benjelloun", "Salma El Fassi"]
    masked, mapping, stats = mask_pii(text, party_names)
    restored = unmask_text(masked, mapping)
    assert restored == text



def test_11_contrat_test_e2e_leaks_killed_and_rc_survives():
    """Acceptance test for PROMPT A: party names and RIB masked; RC/amount survive."""
    text = (Path(__file__).parent / "contrat_test_e2e.txt").read_text(encoding="utf-8")
    party_names = ["Rachid Benjelloun", "Salma El Fassi"]
    masked, mapping, stats = mask_pii(text, party_names)

    forbidden = ["Benjelloun", "El Fassi", "0000123456789012"]
    for token in forbidden:
        assert token not in masked, f"leak: {token!r} still present"

    preserved = ["445621", "98745", "840 000 MAD"]
    for token in preserved:
        assert token in masked, f"wrongly masked: {token!r} removed"

    assert "[RIB_1]" in masked
    assert mapping["[PARTIE_A]"] == "Rachid Benjelloun"
    assert mapping["[PARTIE_B]"] == "Salma El Fassi"



def test_12_ner_off_behavior_unchanged(monkeypatch):
    """With ANONYMIZER_NER=off (default), NER does nothing and text is unchanged."""
    from services.anonymizer import ner_detector

    monkeypatch.setattr(ner_detector, "_NER_ENABLED", False)

    text = "Monsieur Rachid Benjelloun signe le contrat."
    masked, mapping, stats = mask_pii(text, party_names=[])
    assert "Rachid Benjelloun" in masked
    assert stats.get("ner_persons", 0) == 0


def test_13_ner_on_catches_uncaught_person(monkeypatch):
    """With ANONYMIZER_NER=on, a person not in party_names is masked as [PERSON_n]."""
    from services.anonymizer import ner_detector

    monkeypatch.setattr(ner_detector, "_NER_ENABLED", True)

    class FakeModel:
        def predict_entities(self, text, labels, threshold):
            return [
                {
                    "label": "person",
                    "score": 0.9,
                    "start": 10,
                    "end": 27,
                    "text": "Rachid Benjelloun",
                }
            ]

    monkeypatch.setattr(ner_detector, "_model", FakeModel())

    text = "Monsieur Rachid Benjelloun signe."
    masked, mapping, stats = mask_pii(text, party_names=[])
    assert "Rachid Benjelloun" not in masked
    assert "[PERSON_1]" in masked
    assert mapping["[PERSON_1]"] == "Rachid Benjelloun"
    assert stats["ner_persons"] == 1


def test_14_ner_exception_never_fails_pipeline(monkeypatch):
    """If NER raises, the pipeline continues with the original text."""
    from services.anonymizer import ner_detector

    monkeypatch.setattr(ner_detector, "_NER_ENABLED", True)

    class BadModel:
        def predict_entities(self, text, labels, threshold):
            raise RuntimeError("OOM")

    monkeypatch.setattr(ner_detector, "_model", BadModel())

    text = "Rachid Benjelloun signe."
    masked, mapping, stats = mask_pii(text, party_names=[])
    assert masked == text
