#!/usr/bin/env python
#
#  copyright(c) 2011 - Jiro SEKIBA <jir@unicus.jp>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

"""nilfs property page extension"""

__author__    = "Jiro SEKIBA"
__copyright__ = "Copyright (c) 2011 - Jiro SEKIBA <jir@unicus.jp>"
__license__   = "GPL2"

import gtk
import nautilus
import sys
import os
import re
import gobject
import time

class NILFSException(Exception):
    def __init__(self, info):
        Exception.__init__(self,info)

def extract_checkpoint(option_string):
    cp=r'.*cp=([\d]+).*'
    a = re.findall(cp, option_string)
    return int(a[0])

def find_nilfs_in_mtab():
    regex=r'^ *([^ ]+) +([^ ]+) +([^ ]+) +([^ ]+) +([^ ]+) +([^ ]+) *$'
    cp=r'.*cp=.*'
    with open("/etc/mtab") as f:
         a = re.findall(regex, f.read(), re.M)

    actives = [{'dev' : os.path.realpath(str(e[0])),
                'mp'  : os.path.realpath(str(e[1]))}
                for e in a if e[2] == 'nilfs2' and not re.match(cp, e[3])]
   
    if len(actives) == 0:
        raise NILFSException("can not find active NILFS volume in mtab")

    # sort by mount point length. the longer, the earlier
    actives.sort(lambda a, b: -cmp(len(a['mp']), len(b['mp'])))

    checkpoints = [{'dev' : os.path.realpath(str(e[0])),
                    'mp'  : os.path.realpath(str(e[1])),
                    'cp'  : extract_checkpoint(e[3])}
                    for e in a if e[2] == 'nilfs2' and re.match(cp, e[3])]
    # sort by checkpoint number
    checkpoints.sort(lambda a, b: cmp(a['cp'], b['cp']))

    return [{'mp' : e['mp'],
             'cps': [c['mp'] for c in checkpoints ]}
            for e in actives]

def find_nilfs_mounts(realpath):
    mount_list = find_nilfs_in_mtab()
    for e in mount_list:
        if realpath.startswith(e['mp']):
            return e 
    raise NILFSException("file not in NILFS volume: %s" % realpath)


def list_history(cp_mps, relpath):
    l = []
    for mp in cp_mps:
        p = mp + '/' + relpath
        if os.path.exists(p):
            l.append(p)
    return l

def filter_by_mtime(current, history):
    #last_mtime = os.stat(current).st_mtime
    last_mtime = os.stat(current).st_mtime
    l = []
    for f in history:
        mtime = os.stat(f).st_mtime
        if last_mtime != mtime:
            l.append({'path' : f, 'mtime' : mtime})
        last_mtime = mtime
    return l

def get_history(path):
    try:
        realpath = os.path.realpath(path)
        mounts = find_nilfs_mounts(realpath)
        relpath = os.path.relpath(realpath, mounts['mp'])
        history = list_history(mounts['cps'], relpath)
        return filter_by_mtime(path, history)

    except KeyError, (e):
        print "configuration is not valid. missig %s key" % e

    except NILFSException, (e):
        print e

    return []


def create_list_gui(history):
    store = gtk.ListStore(gobject.TYPE_STRING,
                          gobject.TYPE_STRING,
                          gobject.TYPE_STRING,)
    store.clear()

    for e in history:
        store.append([time.strftime("%Y.%m.%d-%H.%M.%S",
                                    time.localtime(e['mtime'])),
                      "black", e['path']])

    tree = gtk.TreeView()
    tree.set_model(store)

    rederer = gtk.CellRendererText()
    column = gtk.TreeViewColumn("date", rederer, text=0, foreground=1)
    tree.append_column(column)
    column = gtk.TreeViewColumn("path", rederer, text=2, foreground=1)
    tree.append_column(column)

    scroll = gtk.ScrolledWindow()
    scroll.add(tree)

    return scroll

class NILFS2PropertyPage(nautilus.PropertyPageProvider):
    def __init__(self):
        pass

    def get_property_pages(self, files):
        if len(files) != 1:
            return

        f = files[0]
        if f.get_uri_scheme() != 'file':
            return

        history = get_history(f.get_uri()[7:])

        if len(history) == 0:
            return

        tree = create_list_gui(history)
        self.property_label = gtk.Label("History")
        self.property_label.show()

        frame = gtk.Frame("History")
        frame.set_shadow_type(gtk.SHADOW_ETCHED_IN)
        frame.add(tree)

        self.vbox = gtk.VBox(0, False)
        self.vbox.pack_start(frame)
        self.vbox.show_all()


        return nautilus.PropertyPage("NautilusPython::nilfs2",
                                     self.property_label, self.vbox),
