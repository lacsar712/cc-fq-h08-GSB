from app.FalseAcceptPolicy import decorate_error, should_treat_as_ok


def test_decorate():
    d = decorate_error("forbidden")
    assert d.get("accepted") is True
    assert should_treat_as_ok(403) is True
