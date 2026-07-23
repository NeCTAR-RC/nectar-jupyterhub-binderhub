"""Notebook usage telemetry -> RabbitMQ -> Ceilometer -> Gnocchi.

Enabled when NOTEBOOK_TELEMETRY_TRANSPORT_URL is set (via hub.extraEnv);
otherwise the notifier logs a warning and every hook is a no-op.
"""

import sys

sys.path.insert(0, '/usr/local/etc/jupyterhub')

from nectar_notebook_telemetry import NotebookNotifier

notifier = NotebookNotifier()

c.Spawner.pre_spawn_hook = notifier.pre_spawn_hook
c.Spawner.post_stop_hook = notifier.post_stop_hook
