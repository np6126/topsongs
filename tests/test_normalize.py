import pytest

from topsongs.normalize import normalize_name


def test_normalize_remaster_and_case() -> None:
    assert normalize_name("Army of the Night - Remastered 2019") == "army of the night"


def test_normalize_feat_and_accents() -> None:
    assert normalize_name("Beyoncé (feat. Jay-Z)") == "beyonce"


@pytest.mark.parametrize(
    "title",
    [
        "Wishmaster (Orchestral Version)",
        "Wishmaster (2006 Version)",
        "Wishmaster (Single Version)",
        "Wishmaster (Acoustic)",
        "Wishmaster (Acoustic Version)",
        "Wishmaster (Demo 1997)",
        "Wishmaster (Instrumental)",
        "Wishmaster (Remix)",
        "Wishmaster (Extended Mix)",
        "Wishmaster (Radio Mix)",
        "Wishmaster (Radio Edit)",
        "Wishmaster (Bonus Track)",
        "Wishmaster (Re-Recorded)",
        "Wishmaster (Rerecorded)",
        "Wishmaster (Reprise)",
        "Wishmaster [Orchestral Version]",
        "Wishmaster [Instrumental]",
    ],
)
def test_normalize_strips_alt_version_tags(title: str) -> None:
    assert normalize_name(title) == "wishmaster"


@pytest.mark.parametrize(
    "title,expected",
    [
        # Plain words that merely contain a stripped token must survive.
        ("Mixed Emotions", "mixed emotions"),
        ("The Demolition Man", "the demolition man"),
        ("Versions of Truth", "versions of truth"),
        ("Editorial", "editorial"),
        # Parenthesized content that is not a version tag must survive.
        ("Lappi (Pt. I)", "lappi pt i"),
        ("Song (Part 2)", "song part 2"),
    ],
)
def test_normalize_does_not_overstrip(title: str, expected: str) -> None:
    assert normalize_name(title) == expected
