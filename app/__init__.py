from flask import Flask
from config import Config
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_caching import Cache
import functools

app = Flask(__name__)
app.config.from_object(Config)
db = SQLAlchemy(app)
migrate = Migrate(app, db)
login = LoginManager(app)
login.login_view = 'login'


class KeyCache(Cache):
    def memoize(self, *args, **kwargs):
        def decorator(f):
            cached = super(KeyCache, self).memoize(*args, **kwargs)(f)
            # def keyfn(*kargs, **kkwargs):
            #     return cached.make_cache_key(f, *kargs, **kkwargs)
            # cached.get_key = keyfn

            def set_cache(value, *sargs, **skwargs):
                self.cache.set(cached.make_cache_key(cached.uncached, *sargs, **skwargs), value, timeout=cached.cache_timeout)
            cached.set_cache = set_cache

            def del_cache(*dargs, **dkwargs):
                self.cache.delete(cached.make_cache_key(cached.uncached, *dargs, **dkwargs))
            cached.del_cache = del_cache

            return cached
        return decorator

    # def set_fn(self, value, fn, *args, **kwargs):
    #     """ cache.set_key(value, fn, *fn_args, **fn_kwargs)"""
    #     # key = fn.get_key(*args, **kwargs)
    #     key = fn.make_cache_key(fn, *args, **kwargs)
    #     return self.cache.set(key, value, timeout=fn.cache_timeout)


cache = Cache(app, config={'CACHE_TYPE': 'simple', 'CACHE_THRESHOLD': 10000, 'CACHE_DEFAULT_TIMEOUT': 86400})


fscache = KeyCache(app, config={'CACHE_TYPE': 'filesystem', 'CACHE_DIR': 'app/cache', 'CACHE_THRESHOLD': 10000, 'CACHE_DEFAULT_TIMEOUT': 86400})


from app import routes, models, errors
