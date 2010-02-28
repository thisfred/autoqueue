from distribute_setup import use_setuptools

use_setuptools()

from setuptools import setup
import os

optional = {}
data_files = []
if os.path.exists('/usr/share/pyshared/quodlibet/plugins/'):
    data_files.extend(
        [('/usr/share/pyshared/quodlibet/plugins/events/',
         ['quodlibet_autoqueue.py']),
        ('/usr/share/pyshared/quodlibet/plugins/songsmenu/',
         ['mirage_songs.py',
          'mirage_miximize.py']),])
if os.path.exists('/usr/lib/rhythmbox/plugins'):
    data_files.append(
        ('/usr/lib/rhythmbox/plugins/rhythmbox_autoqueue',
         ['rhythmbox_autoqueue/rhythmbox_autoqueue.rb-plugin',
          'rhythmbox_autoqueue/__init__.py']),)

if data_files:
    optional = {
        'data_files': data_files}

print optional

setup(
    name='autoqueue',
    version='0.2beta2',
    packages=['autoqueue', 'mirage'],
    package_dir={
        'autoqueue': 'autoqueue',
        'mirage': 'mirage'},
    license='GNU GPL v2',
    author='Eric Casteleijn',
    author_email='thisfred@gmail.com',
    description='A cross music player plugin that queues similar tracks.',
    url='https://launchpad.net/autoqueue',
    package_data={'mirage': ['res/*']},
    requires=['scipy', 'ctypes'],
    provides=['mirage', 'autoqueue'],
    **optional)
