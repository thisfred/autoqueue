"""Autoqueue setup."""
import os
import sys

try:
    import DistUtilsExtra.auto
except ImportError:
    print >> sys.stderr, 'To build this program you need '\
                         'https://launchpad.net/python-distutils-extra'
    sys.exit(1)

SERVICE_FILE = 'org.autoqueue.service'

CLEANFILES = [SERVICE_FILE, 'MANIFEST']


def replace_prefix(prefix):
    """Replace every '@prefix@' with prefix within 'filename' content."""
    # replace .service file, DATA_DIR constant
    for filename in ([SERVICE_FILE]):
        with open(filename + '.in') as in_file:
            content = in_file.read()
            with open(filename, 'w') as out_file:
                out_file.write(content.replace('@prefix@', prefix))


class Install(DistUtilsExtra.auto.install_auto):
    """Class to install proper files."""

    def run(self):
        """Do the install.

        Read from *.service.in and generate .service files with reeplacing
        @prefix@ by self.prefix.

        """
        replace_prefix(self.prefix)
        DistUtilsExtra.auto.install_auto.run(self)


class Clean(DistUtilsExtra.auto.clean_build_tree):
    """Class to clean up after the build."""

    def run(self):
        """Clean up the built files."""
        for built_file in CLEANFILES:
            if os.path.exists(built_file):
                os.unlink(built_file)

        DistUtilsExtra.auto.clean_build_tree.run(self)

DistUtilsExtra.auto.setup(
    name='autoqueue',
    description='A cross music player plug-in that queues similar tracks',
    long_description=(
        'A cross music player plug-in that adds similar tracks to the'
        'queue. Currently works with quodlibet, rhythmbox and mpd.'),
    version='1.0.0alpha9',
    packages=['autoqueue', 'mirage'],
    license='GNU GPL v2',
    author='Eric Casteleijn',
    author_email='thisfred@gmail.com',
    url='https://launchpad.net/autoqueue',
    package_data={'mirage': ['res/*']},
    requires=['scipy', 'ctypes'],
    provides=['mirage', 'autoqueue'],
    cmdclass={
        'install': Install,
        'clean': Clean,
    },
    data_files=[
        ('lib/autoqueue', ['bin/autoqueue-similarity-service']),
        ('share/dbus-1/services/', [SERVICE_FILE]),
        ('share/pyshared/quodlibet/plugins/events/',
         ['quodlibet_autoqueue.py']),
        ('share/pyshared/quodlibet/plugins/songsmenu/',
         ['mirage_songs.py']),
        ('lib/rhythmbox/plugins/rhythmbox_autoqueue',
         ['rhythmbox_autoqueue/rhythmbox_autoqueue.rb-plugin',
          'rhythmbox_autoqueue/__init__.py'])])
