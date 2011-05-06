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

OPTIONAL = {}
DATA_FILES = [
    ('lib/autoqueue', ['bin/autoqueue-similarity-service']),
    ('share/dbus-1/services/', [SERVICE_FILE])]

if os.path.exists('/usr/share/pyshared/quodlibet/plugins/'):
    DATA_FILES.extend(
        [('share/pyshared/quodlibet/plugins/events/',
         ['quodlibet_autoqueue.py']),
        ('share/pyshared/quodlibet/plugins/songsmenu/',
         ['mirage_songs.py',
          'mirage_miximize.py'])])
if os.path.exists('/usr/lib/rhythmbox/plugins'):
    DATA_FILES.append(
        ('lib/rhythmbox/plugins/rhythmbox_autoqueue',
         ['rhythmbox_autoqueue/rhythmbox_autoqueue.rb-plugin',
          'rhythmbox_autoqueue/__init__.py']),)

if DATA_FILES:
    optional = {                        # pylint: disable=C0103
        'data_files': DATA_FILES}

DistUtilsExtra.auto.setup(
    name='autoqueue',
    description='A cross music player plugin that queues similar tracks',
    version='1.0.0-alpha7',
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
    **optional)
