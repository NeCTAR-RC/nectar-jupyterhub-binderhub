FROM quay.io/jupyterhub/k8s-hub:4.3.5

USER root

# oslo.messaging for notebook usage notifications (Ceilometer/Gnocchi)
ARG PIP_CACHE_DIR=/tmp/pip-cache
RUN --mount=type=cache,target=${PIP_CACHE_DIR} \
    pip install oslo.messaging

USER 1000

# Add Nectar theme
COPY --chown=1000 ./theme /usr/local/etc/jupyterhub/theme/

# Add Nectar theme config
COPY --chown=1000 jupyterhub_config_theme.py /usr/local/etc/jupyterhub/jupyterhub_config.d/

# Add notebook usage telemetry
COPY --chown=1000 nectar_notebook_telemetry.py /usr/local/etc/jupyterhub/
COPY --chown=1000 jupyterhub_config_telemetry.py /usr/local/etc/jupyterhub/jupyterhub_config.d/
