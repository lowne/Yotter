from collections import namedtuple
from yaml import safe_load as yaml_load

DEPRECATED_CONFIG = """
serverName: "yotter.xyz"
nitterInstance: "https://nitter.net/"
maxInstanceUsers: 100
serverLocation: "Germany"
restrictPublicUsage: true
nginxVideoStream: true
"""



class DEFAULT_CONFIG:
    server_name = ""
    max_instance_users = 0
    server_location = "?"
    proxy_images = False
    proxy_videos = False
    external_proxy = False
    maintenance_mode = False
    show_admin_message = False
    admin_message_title = "Message from the admin"
    admin_message = "Message from the admin text"
    admin_user = ""
    max_old_user_days = 60
    donate_url = ""

    require_login = True
    restricted_mode = False


default_config = {k: v for k, v in DEFAULT_CONFIG.__dict__.items() if not k.startswith('_')}
file_config = yaml_load(open('yotter-config.yaml'))
dict_config = dict(default_config, **file_config)  # merge
config = namedtuple('config', dict_config.keys())(*dict_config.values())
