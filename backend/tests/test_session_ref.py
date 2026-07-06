import pytest

from app.history.session_ref import make_session_key, session_ref_from_parts


def test_session_key_uses_user_script_session():
    ref = session_ref_from_parts("u1", "script1", "sess1")
    assert ref.session_key == "u1:script1:sess1"
    assert make_session_key("u1", "script2", "sess1") != ref.session_key
    assert make_session_key("u2", "script1", "sess1") != ref.session_key


@pytest.mark.parametrize("bad", ["", "has space", "a/b", "a:b"])
def test_session_id_validation_rejects_unsafe_delimiters(bad):
    with pytest.raises(ValueError):
        session_ref_from_parts("u1", "script1", bad)
