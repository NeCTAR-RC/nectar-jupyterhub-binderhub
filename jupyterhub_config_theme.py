import tornado.web

c.JupyterHub.template_paths = ['/usr/local/etc/jupyterhub/theme/templates']
c.JupyterHub.logo_file = '/usr/local/etc/jupyterhub/theme/static/images/nectar-icon.svg'

c.JupyterHub.extra_handlers = [
    (r'/custom/(.*)', tornado.web.StaticFileHandler, {'path': '/usr/local/etc/jupyterhub/theme/static'}),
]

c.JupyterHub.template_vars = {
    'primary_color': '#F8B20E',
    'secondary_color': '#969696',
    'accent_color': '#8E489B',
    'info_color': '#00A2C4',
    'danger_color': "#E51875",
    'warning_color': "#F8B20E",
    'success_color': "#62C400",
}
