import sonilo_video_kit


def test_import():
    assert hasattr(sonilo_video_kit, "__all__")


def test_default_clients_identify_as_the_video_kit(monkeypatch):
    """Only the kit's own default client is tagged; a caller-supplied client
    keeps its owner's identity."""
    from sonilo_video_kit._version import __version__
    from sonilo_video_kit.duck import _default_client

    # _default_client() builds Sonilo() with no explicit key, so the SDK reads
    # the environment — set one, or this fails wherever no key is configured.
    monkeypatch.setenv("SONILO_API_KEY", "sk-test")
    client = _default_client()
    try:
        assert client._http.headers["x-sonilo-client"] == "kit-python-video"
        assert client._http.headers["x-sonilo-client-version"] == __version__
    finally:
        client.close()
