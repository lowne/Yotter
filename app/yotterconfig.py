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

DEFAULT_CONFIG = """
server_name: ""
max_instance_users: 100
server_location: "?"
proxy_images: false
proxy_videos: false
external_proxy: false
maintenance_mode: false
show_admin_message: false
admin_message_title: "Message from the admin"
admin_message: "Message from the admin text"
admin_user: "admin_username"
max_old_user_days: 60
donate_url: ""
"""


default_config = yaml_load(DEFAULT_CONFIG)
file_config = yaml_load(open('yotter-config.yaml'))

# merge
dict_config = dict(default_config, **file_config)

config = namedtuple('config', dict_config.keys())(*dict_config.values())

def get_config():
    return config
