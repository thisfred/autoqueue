from setuptools import setup

setup(
    name='autoqueue',
    version='0.1',
    packages=['autoqueue', 'mirage'],
    license='GPL v2',
    author='Eric Casteleijn',
    author_email='thisfred@gmail.com',
    description='A cross music player plugin that queues similar tracks.',
    url='https://launchpad.net/autoqueue',
    data_files= [
        ('/usr/lib/rhythmbox/plugins/rhythmbox_autoqueue',
         ['plugins/rhythmbox/autoqueue.rb-plugin',
          'plugins/rhythmbox/__init__.py']),
        ('/usr/share/pyshared/quodlibet/plugins/events/',
         ['plugins/quodlibet/quodlibet_autoqueue.py']),
        ('/usr/share/pyshared/quodlibet/plugins/songsmenu/',
         ['plugins/quodlibet/mirage_songs.py',
          'plugins/quodlibet/mirage_miximize.py']),
        ]
    )
