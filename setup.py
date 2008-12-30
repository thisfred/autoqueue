from setuptools import setup, find_packages
setup(
    name = "autoqueue",
    version = "0.3",
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
    package_dir={'': 'src'},
    packages=['autoqueue', 'mirage'],
    package_data={"autoqueue": ["res/*.filter"]},
    include_package_data = True,
    zip_safe=False,

)
