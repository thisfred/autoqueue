from datetime import datetime

from dateutil.tz import tzutc
from quodlibet import _
from quodlibet.plugins.songsmenu import SongsMenuPlugin

from autoqueue.request import Requests

UTC = tzutc()


class RequestPlugin(SongsMenuPlugin):
    PLUGIN_ID = "Request"
    PLUGIN_NAME = _("Autoqueue Request")  # noqa
    PLUGIN_DESC = _(  # noqa
        "Request songs that autoqueue will then work its way toward."
    )
    PLUGIN_ICON = "gtk-find-and-replace"
    PLUGIN_VERSION = "0.1"

    def __init__(self, *args):
        super(RequestPlugin, self).__init__(*args)
        self.requests = Requests()

    def plugin_songs(self, songs):
        """Add the work to the coroutine pool."""
        for song in songs:
            added = datetime.fromtimestamp(song("~#added"), tz=UTC)
            self.requests.add(song("~filename"), added)
