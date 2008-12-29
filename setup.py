from setuptools import setup, find_packages
setup(
    name = "autoqueue",
    version = "0.3",
    packages = find_packages(),
    package_data = {'': ['*.filter'],},
    # metadata for upload to PyPI
    author = "Eric Casteleijn",
    author_email = "thisfred@gmail.com",
    description = "A Cross Player plugin that queues similar songs.",
    license = "GPL",
    keywords = "quodlibet rhythmbox mpd music similarity last.fm",
    url = "http://code.google.com/p/autoqueue/",
    extras_require = {
    'mirage': ['ctypes', 'scipy'],
    },
    include_package_data = True
)
