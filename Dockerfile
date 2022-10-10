FROM jupyterhub/k8s-hub:2.0.0

# Add Nectar theme
COPY --chown=1000 ./theme /usr/local/etc/jupyterhub/theme/

# Add Nectar theme config
COPY --chown=1000 jupyterhub_config_theme.py /usr/local/etc/jupyterhub/jupyterhub_config.d/
