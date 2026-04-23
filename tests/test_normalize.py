from topsongs.normalize import normalize_name


def test_normalize_remaster_and_case() -> None:
    assert normalize_name("Army of the Night - Remastered 2019") == "army of the night"


def test_normalize_feat_and_accents() -> None:
    assert normalize_name("Beyoncé (feat. Jay-Z)") == "beyonce"
