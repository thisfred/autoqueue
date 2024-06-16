"""Autoqueue setup."""

from setuptools import setup

SERVICE_FILE = "org.autoqueue.service"


setup(
    name="autoqueue",
    description="A cross music player plug-in that queues similar tracks",
    long_description=(
        "A cross music player plug-in that adds similar tracks to the"
        "queue. Currently works with quodlibet and mpd."
    ),
    version="1.0.0",
    packages=["autoqueue"],
    license="GNU GPL v2",
    author="Eric Casteleijn",
    author_email="thisfred@gmail.com",
    url="https://launchpad.net/autoqueue",
    install_requires=[
        "python-dateutil",
        "pygeohash",
        "pylast",
        "pyowm",
        "requests",
        "sentence-transformers",
    ],
    provides=["autoqueue"],
    data_files=[
        ("lib/autoqueue", ["bin/autoqueue-similarity-service"]),
        ("share/dbus-1/services/", [SERVICE_FILE]),
        ("share/pyshared/quodlibet/plugins/events/", ["quodlibet_autoqueue.py"]),
        (
            "share/pyshared/quodlibet/plugins/songsmenu/",
            ["analyze_songs.py", "miximize.py", "request.py"],
        ),
    ],
)
