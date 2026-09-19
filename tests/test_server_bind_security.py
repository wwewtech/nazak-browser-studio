"""Phase 5: GUI/API server must bind to loopback by default (never 0.0.0.0)."""


def test_default_host_is_loopback():
    from nazak.config import DEFAULT_HOST

    assert DEFAULT_HOST == "127.0.0.1"


def test_server_thread_defaults_to_loopback():
    from nazak.gui.main_window import ServerThread

    # Default constructor must not silently expose the API to the LAN.
    thread = ServerThread.__new__(ServerThread)  # no __init__ side effects
    assert ServerThread.__init__.__defaults__[:2] == ("127.0.0.1", 8899)


def test_launch_gui_signature_defaults():
    import inspect

    from nazak.gui.main_window import launch_gui

    sig = inspect.signature(launch_gui)
    assert sig.parameters["host"].default == "127.0.0.1"