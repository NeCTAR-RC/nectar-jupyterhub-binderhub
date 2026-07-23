"""Publish JupyterHub notebook lifecycle notifications to the OpenStack bus.

Emits oslo.messaging notifications (``jupyterhub.notebook.start`` /
``.stop``) onto the RabbitMQ notifications topic, where the Ceilometer
notification agent records a ``notebook`` resource in Gnocchi -- the
same pipeline Nova instances and warre reservations use.

The payload's ``id`` / ``user_id`` map to the ``resource_id`` /
``user_id`` traits via the ``jupyterhub.*`` event definitions carried
in the Nectar ceilometer image (Ceilometer's catch-all defaults
extract no resource_id, so those definitions are required).

Design notes
------------
* Resource identity is a deterministic UUIDv5 of (hub, username,
  server_name): one Gnocchi resource per user-server slot, recomputable in
  every hook and across hub restarts.  JupyterHub clears
  ``spawner.server`` and ``orm_spawner.started`` *before*
  ``post_stop_hook`` runs (jupyterhub/user.py, User.stop), so nothing
  DB-persisted identifies an individual session at stop time.
* Telemetry must never break spawns: publishing is fire-and-forget on a
  single worker thread, and every failure path logs instead of raising.

Configuration (environment variables)
-------------------------------------
NOTEBOOK_TELEMETRY_TRANSPORT_URL
    oslo.messaging transport URL, e.g.
    ``rabbit://user:pass@rabbitmq.example.org:5671/vhost``.
    TLS is always enabled; the broker must listen on a TLS port.
    If unset, telemetry is disabled (a warning is logged once).
NOTEBOOK_TELEMETRY_HUB
    Identifier for this hub deployment, e.g.
    ``jupyterhub.rctest.nectar.org.au``.  Part of the resource identity;
    do not change it once in production.
NOTEBOOK_TELEMETRY_TOPIC
    Notification topic (default ``notifications``, matching Ceilometer's
    default listener).
NOTEBOOK_TELEMETRY_PUBLISHER_ID
    oslo publisher_id (default: the hub identifier).
"""

import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger("nectar.notebook_telemetry")

#: Namespace for deterministic notebook resource ids. Do not change:
#: resource ids in Gnocchi are derived from it.
NOTEBOOK_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "nectar.org.au")

EVENT_START = "jupyterhub.notebook.start"
EVENT_STOP = "jupyterhub.notebook.stop"


def notebook_resource_id(hub, username, server_name=""):
    """Deterministic Gnocchi resource id for a user's server slot."""
    return str(uuid.uuid5(NOTEBOOK_NAMESPACE, f"{hub}/{username}/{server_name}"))


class NotebookNotifier:
    """Fire-and-forget notifier for notebook lifecycle events.

    All publishing happens on a single worker thread so the blocking
    kombu/RabbitMQ I/O never runs on the hub's event loop, and no
    exception ever propagates into the spawn/stop path.
    """

    def __init__(self, transport_url=None, hub=None, publisher_id=None, topic=None):
        self.hub = hub or os.environ.get("NOTEBOOK_TELEMETRY_HUB", "jupyterhub")
        self.transport_url = transport_url or os.environ.get(
            "NOTEBOOK_TELEMETRY_TRANSPORT_URL", ""
        )
        self.topic = topic or os.environ.get("NOTEBOOK_TELEMETRY_TOPIC", "notifications")
        self.publisher_id = publisher_id or os.environ.get(
            "NOTEBOOK_TELEMETRY_PUBLISHER_ID", self.hub
        )
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="notebook-telemetry"
        )
        self._notifier = None
        if not self.transport_url:
            log.warning(
                "Notebook telemetry disabled: NOTEBOOK_TELEMETRY_TRANSPORT_URL not set"
            )
        else:
            log.info(
                "Notebook telemetry enabled: hub=%s topic=%s publisher_id=%s",
                self.hub,
                self.topic,
                self.publisher_id,
            )

    # The notifier is a process singleton whose executor (and its internal
    # _queue.SimpleQueue) cannot be copied or pickled.  traitlets deepcopies
    # every Spawner config value on each Spawner instantiation, and our hooks
    # are methods bound to this instance, so copying must return the same
    # instance or every spawner page 500s.
    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    # -- oslo plumbing -----------------------------------------------------

    def _get_notifier(self):
        """Lazily build the oslo Notifier (called on the worker thread)."""
        if self._notifier is None:
            import oslo_messaging as messaging
            from oslo_config import cfg

            conf = cfg.ConfigOpts()
            transport = messaging.get_notification_transport(
                conf, url=self.transport_url
            )
            # No oslo config file on the hub, so broker settings here
            conf.set_override("ssl", True, group="oslo_messaging_rabbit")
            conf.set_override(
                "amqp_durable_queues", True, group="oslo_messaging_rabbit"
            )
            conf.set_override(
                "rabbit_quorum_queue", True, group="oslo_messaging_rabbit"
            )
            self._notifier = messaging.Notifier(
                transport,
                publisher_id=self.publisher_id,
                driver="messagingv2",
                topics=[self.topic],
            )
        return self._notifier

    def _send(self, event_type, payload):
        try:
            self._get_notifier().info({}, event_type, payload)
            log.debug("Sent %s for %s", event_type, payload.get("id"))
        except Exception:
            log.exception("Failed to send %s notification", event_type)
            # force a fresh transport on the next attempt
            self._notifier = None

    def emit(self, event_type, payload):
        """Queue a notification; returns immediately, never raises."""
        if not self.transport_url:
            return
        try:
            self._executor.submit(self._send, event_type, payload)
        except Exception:
            log.exception("Failed to queue %s notification", event_type)

    # -- payloads ------------------------------------------------------------

    def payload_from_spawner(self, spawner):
        """Build the notification payload from a Spawner."""
        user_options = spawner.user_options or {}
        return {
            "id": notebook_resource_id(self.hub, spawner.user.name, spawner.name),
            "user_id": spawner.user.name,
            "server_name": spawner.name,
            "profile": user_options.get("profile", "") or "",
            "image": str(getattr(spawner, "image", "") or ""),
            "hub": self.hub,
            # BinderHub launches only (empty on plain JupyterHub): the git
            # repo and the resolved ref URL, from BinderHub's launcher
            "repo_url": user_options.get("repo_url", "") or "",
            "ref_url": user_options.get("binder_ref_url", "") or "",
        }

    # -- Spawner hook adapters -------------------------------------------------

    def pre_spawn_hook(self, spawner):
        """c.Spawner.pre_spawn_hook -- emit jupyterhub.notebook.start."""
        try:
            self.emit(EVENT_START, self.payload_from_spawner(spawner))
        except Exception:
            log.exception("notebook telemetry pre_spawn_hook failed")

    def post_stop_hook(self, spawner):
        """c.Spawner.post_stop_hook -- emit jupyterhub.notebook.stop."""
        try:
            self.emit(EVENT_STOP, self.payload_from_spawner(spawner))
        except Exception:
            log.exception("notebook telemetry post_stop_hook failed")
