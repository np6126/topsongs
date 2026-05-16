from topsongs.sanitize import sanitize_for_filename, sanitize_untrusted_text


def test_sanitize_untrusted_text_removes_control_chars_and_ansi() -> None:
    value = "Hello\x1b[31m\nWorld\r\tTest"
    assert sanitize_untrusted_text(value) == "Hello World Test"


def test_sanitize_untrusted_text_limits_length() -> None:
    value = "a" * 500
    assert len(sanitize_untrusted_text(value)) == 200


def test_sanitize_for_filename_replaces_illegal_chars() -> None:
    assert sanitize_for_filename("AC/DC") == "AC_DC"
    assert sanitize_for_filename('A<B>C:D"E/F\\G|H?I*J') == "A_B_C_D_E_F_G_H_I_J"


def test_sanitize_for_filename_leaves_normal_names_unchanged() -> None:
    assert sanitize_for_filename("Powerwolf") == "Powerwolf"
    assert sanitize_for_filename("Guns N' Roses") == "Guns N' Roses"
