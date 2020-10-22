from flask import Flask
from config import Config
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_caching import Cache

app = Flask(__name__)
app.config.from_object(Config)
db = SQLAlchemy(app)
migrate = Migrate(app, db)
login = LoginManager(app)
login.login_view = 'login'

cache = Cache(app,config={'CACHE_TYPE': 'simple'})
fscache = Cache(app,config={'CACHE_TYPE': 'filesystem', 'CACHE_DIR': 'app/cache', 'CACHE_THRESHOLD': 10000, 'CACHE_DEFAULT_TIMEOUT': 86400})

from app import routes, models, errors
