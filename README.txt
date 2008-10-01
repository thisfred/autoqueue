This documentation is obviously a work in progress, help is greatly
appreciated!



A list of settings that can be configured
=========================================

Note: All of these are available in the Quod Libet
implementation. Where possible, we try to make them available in all
implementations, but this effort might not be complete, and some
features are simply not possible to implement for some players.


- by track: When this is enabled, similar tracks are looked up on
  last.fm and queued when they are found in the local
  database. Enabled by default.

- by artist: When this is enabled, similar artists are looked up on
  last.fm and tracks by those artists are queued when they are found
  in the local database. Enabled by default.

- by tags: When this is enabled, song with similar 'tags' are looked
  up in the local database. The id3 field 'grouping' is used to look
  up the tags by default. Disabled by default.

- log to console: When this is enabled, autoqueue prints what it is
  doing to the console (only when the player is being started from the
  console, obviously.) Useful for debugging, but also for seeing how
  autoqueue actually works. Disabled by default.

- random picks: When this is enabled, autoqueue doesn't automatically
  use the best available track according to the similarity score, but
  a random pick from all the similar tracks/artists. Disabled by
  default.

- caching: Keep a local cache of similarity results from last.fm. Look
  database with all the retrieved information. Enabled by default.  in
  your plugin directory for the file 'similarity.db'. It's a sqlite3

- cache: A number of days to look up information in the local cache
  instead of last.fm. Default: 90

- block track: A number of days to not play a specific file after it's
  been played. This prevents the same tracks playing over and over
  again. Experiment with changing this number. Good values depend on
  how big your library is. I am quite happy with 90 days for 60,000+
  tracks. Default: 30

- block artist: A number of days not to play tracks by a specific
  artist, after a track by that artist is played. Default: 1

- queue: A number of seconds which indicates the desired queue
  length. When set to 0 one track is added to the queue whenever a new
  track starts playing. For any non zero value, autoqueue keeps adding
  tracks until the total length of the queue reaches that number of
  seconds. For instance 4440 will get you a queue of 74 minutes, which
  is a common size for blank audio CDs. Default: 0

- relax: Filter to relax the block track rules: use any search
  expression you can use in the quod libet search to allow some songs
  to break the rules. For instance I use: '(#(added < 30
  days),grouping=favorites)', so that my favorites, and anything I
  added in the last month can be played more often than the block
  track variable indicates. Default: ''

- restrict: Filter to restrict which tracks autoqueue finds. For
  instance, you could use 'genre=reggae', to find only songs with the
  genre reggae or '&(#(date > 1979), #(date < 1990))' to find only
  tracks from the 80s. I have used something like 'grouping=lowlands
  2008' to create a smooth mix cd from only tracks by artists that
  played the Lowlands 2008 festival (after tagging all of those tracks
  accordingly, see my lastfmtagger plugin.) Default: ''

