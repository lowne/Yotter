import sys
from os.path import join as joinpath, dirname
import app.ytlshim.settings

sys.modules['settings'] = settings
__path__ = [joinpath(joinpath(dirname(dirname(dirname(__file__))), 'youtube-local'), 'youtube')]

class yt_app:
    def route(*a, **kw): return lambda f: f
