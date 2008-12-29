"""AutoQueue: an automatic queueing plugin library.
version 0.3

Copyright 2007-2008 Eric Casteleijn <thisfred@gmail.com>,
                    Wim Schut
                    
This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2, or (at your option)
any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301  USA.
"""

import sqlite3, Queue, thread
from threading import Thread
from time import sleep

_threadex = thread.allocate_lock()
qthreads = 0
sqlqueue = Queue.Queue()

ConnectCmd = "connect"
SqlCmd = "SQL"
StopCmd = "stop"


class DbCmd:
    def __init__(self, cmd, arg=None):
        self.cmd = cmd
        self.arg = arg

class DbWrapper(Thread):
    def __init__(self, path, nr):
        Thread.__init__(self)
        self.path = path
        self.nr = nr
    def run(self):
        global qthreads
        con = sqlite3.connect(self.path)
        while True:
            s = sqlqueue.get()
            if s.cmd == SqlCmd:
                sql = s.arg
                res = []
                if not sql[0].upper().startswith("SELECT"): 
                    con.execute(*sql)
                    con.commit()
                else:
                    res = [row for row in con.execute(*sql)]
                s.resultqueue.put(res)
            else:
                _threadex.acquire()
                qthreads -= 1
                _threadex.release()
                # allow other threads to stop
                s.resultqueue.put(None)
                break

def execSQL(s):
    if s.cmd == ConnectCmd:
        global qthreads
        _threadex.acquire()
        qthreads += 1
        _threadex.release()
        wrap = DbWrapper(s.arg, qthreads)
        wrap.start()
    elif s.cmd == StopCmd:
        s.resultqueue = Queue.Queue()
        sqlqueue.put(s)
        # sleep until all threads are stopped
        while qthreads > 0: sleep(0.1)
    else:
        s.resultqueue = Queue.Queue()
        sqlqueue.put(s)
        return s.resultqueue.get()
