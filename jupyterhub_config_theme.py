import tornado.web

c.JupyterHub.template_paths = ['/usr/local/etc/jupyterhub/theme/templates']
c.JupyterHub.logo_file = '/usr/local/etc/jupyterhub/theme/static/images/nectar-icon.svg'

c.JupyterHub.extra_handlers = [
    (r'/custom/(.*)', tornado.web.StaticFileHandler, {'path': '/usr/local/etc/jupyterhub/theme/static'}),
]
