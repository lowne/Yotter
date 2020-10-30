from collections import namedtuple
import sys
import os
from yaml import safe_load as yaml_load
from environs import Env


class DEFAULT_CONFIG:
    behind_https_proxy = False
    max_instance_users = 0
    admin_user = ""
    require_login = True
    restricted_mode = False

    max_old_user_days = 60

    proxy_images = True
    proxy_videos = True
    external_proxy = ''

    temp_dir = 'var'
    sqlite_db_file = 'yotter.db'
    database_url = ''

    cache_dir = 'var/cache'
    cache_backend = ''
    cache_url = ''

    server_name = ''
    server_location = ''
    show_admin_message = False
    admin_message_title = ''
    admin_message = ''
    maintenance_mode = False
    donate_url = ''
    donate_yotter = True


basedir = os.path.abspath(os.path.dirname(__file__))
env = Env()
# env.read_env('.env.default', recurse=False)
env.read_env()
CONFIG_FILE = env('YOTTER_CONFIG_FILE', os.path.join(basedir, 'yotter-config.yaml'))
try:
    file_config = yaml_load(open(CONFIG_FILE))
    print(f'Loaded configuration from {CONFIG_FILE}')
except FileNotFoundError as e:
    sys.stderr.write(e)
    sys.stderr.write('Using default values for configuration')
    file_config = {}

default_config = {k: v for k, v in DEFAULT_CONFIG.__dict__.items() if not k.startswith('_')}

user_config = dict(default_config, **file_config)

with env.prefixed('YOTTER_'):
    dict_config = {k: getattr(env, type(v).__name__)(k.upper(), v) for k, v in user_config.items()}

config = namedtuple('config', dict_config.keys())(*dict_config.values())
print(config)
os.makedirs(config.temp_dir, exist_ok=True)

class FlaskConfig(object):
    SECRET_KEY = env('SECRET_KEY', 'you-will-never-guess')
    SQLALCHEMY_DATABASE_URI = config.database_url or f'sqlite:///{config.sqlite_db_file}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
