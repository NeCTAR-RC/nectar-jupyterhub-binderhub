"""Tests for nectar_notebook_telemetry.

Run:  python -m pytest test_telemetry.py -q
oslo.messaging is not required (publishing is mocked); it IS exercised by
the construction check when installed.
"""

from types import SimpleNamespace
from unittest import mock

import pytest

import nectar_notebook_telemetry as nt


def fake_spawner(username="alice@ardc.edu.au", server_name="", profile="scipy-environment"):
    return SimpleNamespace(
        user=SimpleNamespace(name=username),
        name=server_name,
        user_options={"profile": profile} if profile else {},
        image="registry.rc.nectar.org.au/nectar/jupyter-scipy-notebook:65c0fb081828",
    )


def make_notifier(**kwargs):
    kwargs.setdefault("transport_url", "rabbit://x:y@example.org:5672/")
    kwargs.setdefault("hub", "jupyterhub.rctest.nectar.org.au")
    return nt.NotebookNotifier(**kwargs)


def test_event_types_follow_house_convention():
    # <service>.<resource>.<action>, as with warre.reservation.*
    assert nt.EVENT_START == "jupyterhub.notebook.start"
    assert nt.EVENT_STOP == "jupyterhub.notebook.stop"


def test_resource_id_deterministic():
    a = nt.notebook_resource_id("hub1", "alice@ardc.edu.au", "")
    b = nt.notebook_resource_id("hub1", "alice@ardc.edu.au", "")
    assert a == b
    # different hub, user, or server -> different resource
    assert a != nt.notebook_resource_id("hub2", "alice@ardc.edu.au", "")
    assert a != nt.notebook_resource_id("hub1", "bob@ardc.edu.au", "")
    assert a != nt.notebook_resource_id("hub1", "alice@ardc.edu.au", "named")
    # valid UUID string
    import uuid

    assert str(uuid.UUID(a)) == a


def test_payload_from_spawner():
    n = make_notifier()
    payload = n.payload_from_spawner(fake_spawner())
    assert payload == {
        # id / user_id keys per warre payload convention: mapped to the
        # resource_id / user_id traits by default event definitions
        "id": nt.notebook_resource_id(
            "jupyterhub.rctest.nectar.org.au", "alice@ardc.edu.au", ""
        ),
        "user_id": "alice@ardc.edu.au",
        "server_name": "",
        "profile": "scipy-environment",
        "image": "registry.rc.nectar.org.au/nectar/jupyter-scipy-notebook:65c0fb081828",
        "hub": "jupyterhub.rctest.nectar.org.au",
        "repo_url": "",
        "ref_url": "",
    }


def test_payload_binderhub_launch():
    """BinderHub launches carry the git repo and resolved ref in
    user_options (see binderhub launcher.py / builder.py extra_args)."""
    n = make_notifier(hub="binder.rctest.nectar.org.au")
    spawner = fake_spawner(profile=None)
    spawner.user_options = {
        "image": "binder-registry/r2d-example:sha",
        "repo_url": "https://github.com/example/my-repo",
        "token": "secret",
        "binder_ref_url": "https://github.com/example/my-repo/tree/abc123",
        "binder_request": "v2/gh/example/my-repo/main",
        "binder_persistent_request": "v2/gh/example/my-repo/abc123",
    }
    payload = n.payload_from_spawner(spawner)
    assert payload["repo_url"] == "https://github.com/example/my-repo"
    assert payload["ref_url"] == "https://github.com/example/my-repo/tree/abc123"
    assert payload["profile"] == ""
    # the token must never leak into telemetry
    assert "token" not in payload.values()
    assert "secret" not in payload.values()


def test_payload_no_profile_no_image():
    n = make_notifier()
    spawner = fake_spawner(profile=None)
    spawner.image = None
    spawner.user_options = None
    payload = n.payload_from_spawner(spawner)
    assert payload["profile"] == ""
    assert payload["image"] == ""


def _drain(notifier):
    """Wait for the single worker thread to finish queued sends."""
    notifier._executor.submit(lambda: None).result(timeout=5)


def test_hooks_emit_events():
    n = make_notifier()
    sent = []
    with mock.patch.object(n, "_get_notifier") as get_notifier:
        get_notifier.return_value.info.side_effect = (
            lambda ctx, event_type, payload: sent.append((event_type, payload))
        )
        spawner = fake_spawner()
        n.pre_spawn_hook(spawner)
        n.post_stop_hook(spawner)
        _drain(n)
    assert [e for e, _ in sent] == [nt.EVENT_START, nt.EVENT_STOP]
    assert sent[0][1]["id"] == sent[1][1]["id"]


def test_disabled_without_transport_url(monkeypatch):
    monkeypatch.delenv("NOTEBOOK_TELEMETRY_TRANSPORT_URL", raising=False)
    n = nt.NotebookNotifier(transport_url="", hub="h")
    with mock.patch.object(n, "_get_notifier") as get_notifier:
        n.pre_spawn_hook(fake_spawner())
        _drain(n)
    get_notifier.assert_not_called()


def test_send_failure_never_raises_and_resets():
    n = make_notifier()
    with mock.patch.object(n, "_get_notifier", side_effect=RuntimeError("amqp down")):
        # must not raise into the hook
        n.pre_spawn_hook(fake_spawner())
        _drain(n)
    # notifier reset so the next send rebuilds the transport
    assert n._notifier is None


def test_env_configuration(monkeypatch):
    monkeypatch.setenv("NOTEBOOK_TELEMETRY_TRANSPORT_URL", "rabbit://u:p@h:5672/")
    monkeypatch.setenv("NOTEBOOK_TELEMETRY_HUB", "jupyterhub.example.org")
    monkeypatch.setenv("NOTEBOOK_TELEMETRY_TOPIC", "custom-topic")
    n = nt.NotebookNotifier()
    assert n.transport_url == "rabbit://u:p@h:5672/"
    assert n.hub == "jupyterhub.example.org"
    assert n.topic == "custom-topic"
    assert n.publisher_id == "jupyterhub.example.org"


def test_deepcopy_safe():
    """traitlets deepcopies Spawner config values (incl. our bound-method
    hooks) on every Spawner instantiation; the executor's SimpleQueue is
    unpicklable, so copying must return the same instance."""
    import copy

    n = make_notifier()
    assert copy.copy(n) is n
    assert copy.deepcopy(n) is n
    # the failing path: deepcopy of a bound method copies __self__
    hook = copy.deepcopy(n.pre_spawn_hook)
    assert hook.__self__ is n


def test_oslo_notifier_construction():
    """Integration: real oslo.messaging Notifier construction (no send)."""
    pytest.importorskip("oslo_messaging")
    n = make_notifier(transport_url="rabbit://guest:guest@localhost:5672/")
    notifier = n._get_notifier()
    assert notifier is not None
    # cached on second call
    assert n._get_notifier() is notifier
    # Broker settings are forced in code: the hub has no oslo config file,
    # and queue durability/type must match Ceilometer's declarations
    rabbit_conf = notifier.transport.conf.oslo_messaging_rabbit
    assert rabbit_conf.ssl is True
    assert rabbit_conf.amqp_durable_queues is True
    assert rabbit_conf.rabbit_quorum_queue is True
