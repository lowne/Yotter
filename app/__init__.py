from flask import Flask
from config import config, FlaskConfig
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_caching import Cache

app = Flask(__name__)
app.config.from_object(FlaskConfig)
print(f'Using database {app.config["SQLALCHEMY_DATABASE_URI"]}')
db = SQLAlchemy(app)
migrate = Migrate(app, db)
login = LoginManager(app)
login.login_view = 'login'


class KeyCache(Cache):
    def memoize(self, *args, **kwargs):
        def decorator(f):
            cached = super(KeyCache, self).memoize(*args, **kwargs)(f)

            def set_cache(value, *sargs, **skwargs):
                self.cache.set(cached.make_cache_key(cached.uncached, *sargs, **skwargs), value, timeout=cached.cache_timeout)
            cached.set_cache = set_cache

            def del_cache(*dargs, **dkwargs):
                self.cache.delete(cached.make_cache_key(cached.uncached, *dargs, **dkwargs))
            cached.del_cache = del_cache

            return cached
        return decorator


cache = KeyCache(app, config={'CACHE_TYPE': 'simple', 'CACHE_THRESHOLD': 5000, 'CACHE_DEFAULT_TIMEOUT': 86400})

# os.makedirs(config.cache_dir)
fscache = KeyCache(app, config={'CACHE_TYPE': 'filesystem', 'CACHE_DIR': config.cache_dir, 'CACHE_THRESHOLD': 10000, 'CACHE_DEFAULT_TIMEOUT': 86400})


from app import routes, models, errors
