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
