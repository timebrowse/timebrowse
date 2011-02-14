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

import commands
import gtk
import nautilus
import sys
import os
import re
import gobject
import glib
import time

class NILFSException(Exception):
    def __init__(self, info):
        Exception.__init__(self,info)

def extract_checkpoint(option_string):
    cp=r'.*cp=([\d]+).*'
    a = re.findall(cp, option_string)
    return int(a[0])

def find_nilfs_in_mtab():
    regex=r'^ *([^ ]+) +([^ ]+) +nilfs2 +([^ ]+) +([^ ]+) +([^ ]+) *$'
    cp=r'.*cp=.*'
    with open("/etc/mtab") as f:
         entries = re.findall(regex, f.read(), re.M)

    # Device paths and mount points in mtab are normalized
    actives = [{'dev' : str(e[0]), 'mp' : str(e[1])}
                for e in entries if not re.match(cp, e[2])]
   
    if len(actives) == 0:
        raise NILFSException("can not find active NILFS volume in mtab")

    # sort by mount point length. the longer, the earlier
    actives.sort(lambda a, b: -cmp(len(a['mp']), len(b['mp'])))

    # Make a dictionary of checkpoints sorted by device name
    checkpoints = {}
    for e in entries:
        if re.match(cp, e[2]):
            cpinfo = str(e[1]), extract_checkpoint(e[2])
            if str(e[0]) in checkpoints:
                checkpoints[str(e[0])].append(cpinfo)
            else:
                checkpoints[str(e[0])] = [cpinfo]

    # Sort checkpoints by checkpoint number
    for cps in checkpoints.itervalues():
        cps.sort(lambda a, b: cmp(a[1], b[1]))

    for a in actives:
        if a['dev'] in checkpoints:
            a['cps'] = checkpoints[a['dev']]

    return actives

def find_nilfs_mounts(realpath):
    mount_list = find_nilfs_in_mtab()
    for e in mount_list:
        if realpath.startswith(e['mp']):
            return e 
    raise NILFSException("file not in NILFS volume: %s" % realpath)


def list_history(cps, relpath):
    l = []
    for cp in cps:
        p = cp[0] + '/' + relpath
        if os.path.exists(p):
            l.append(p)
    return l

def age_repr(val, unit):
    if abs(int(val)) > 1:
        unit += "s"  # conjugate 'unit' to plural form
    return "%d %s %s" % (abs(val), unit, "ago" if val > 0 else "later")

def pretty_format(time):
    if time == 0:
       return "latest"
    if abs(time) < 60:
        return age_repr(time, "sec")
    time = time/60
    if abs(time) < 60:
        return age_repr(time, "minute")
    time = time/60
    if abs(time) < 24:
        return age_repr(time, "hour")
    time = time/24
    if abs(time) < 30:
        return age_repr(time, "day")
    m = time/30
    if abs(m) < 30:
        return age_repr(m, "month")
    y = time/365
    return age_repr(y, "year")

def filter_by_mtime(current, history):
    current_time = os.stat(current).st_mtime
    last_mtime = current_time
    l = []
    for f in history:
        stat = os.stat(f)
        mtime = stat.st_mtime
        if last_mtime != mtime:
            size = str(stat.st_size)
            l.append({'path' : f, 'mtime' : mtime, 'size' : size,
                      'age' : pretty_format(current_time - mtime)})
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
                          gobject.TYPE_STRING,
                          gobject.TYPE_STRING,)
    store.clear()

    for e in history:
        store.append([e['path'], time.strftime("%Y.%m.%d-%H.%M.%S",
                                               time.localtime(e['mtime'])),
                      e['size'], e['age']])

    tree = gtk.TreeView()
    tree.set_model(store)

    rederer = gtk.CellRendererText()
    column = gtk.TreeViewColumn("date", rederer, text=1)
    tree.append_column(column)
    column = gtk.TreeViewColumn("size", rederer, text=2)
    tree.append_column(column)
    column = gtk.TreeViewColumn("age", rederer, text=3)
    tree.append_column(column)


    scroll = gtk.ScrolledWindow()
    scroll.add(tree)

    frame = gtk.Frame("History")
    frame.set_shadow_type(gtk.SHADOW_ETCHED_IN)
    frame.add(scroll)

    vbox = gtk.VBox(False, 0)
    vbox.pack_start(frame)

    hbox = gtk.HBox(False, 0)
    button = gtk.Button("Copy To Desktop")
    hbox.pack_end(button, False, False, 10);
    vbox.pack_start(hbox, False, False, 5);

    def get_selected_path(info):
        select = info.get_selection()
        rows = select.get_selected_rows()
        if len(rows[1]) == 0:
            return False
        row = rows[1][0][0]
        model = info.get_model()
        itr = model.get_iter(row)
        v = model.get_value(itr, 0)
        return v

    def copy_to_desktop(widget, info):
        source = get_selected_path(info)
        if not source:
            return

        basename = os.path.basename(source)
        desktop = glib.get_user_special_dir(glib.USER_DIRECTORY_DESKTOP)
        dest = desktop + "/" + basename

        copy = True
        if os.path.exists(dest):
            dialog = gtk.Dialog("Confirm", None, gtk.DIALOG_MODAL,
                                ("OK", True, "Cancel", False))
            style = gtk.Style()

            icon = style.lookup_icon_set(gtk.STOCK_FILE)
            pix = icon.render_icon(style, gtk.TEXT_DIR_NONE, gtk.STATE_NORMAL,
                                   gtk.ICON_SIZE_DIALOG, None, None)

            t = "file"
            if os.path.islink(dest):
                t = "link"
            elif os.path.isdir(dest):
                t = "directory"
                icon = style.lookup_icon_set(gtk.STOCK_DIRECTORY)
                pix = icon.render_icon(style, gtk.TEXT_DIR_NONE,
                                       gtk.STATE_NORMAL, gtk.ICON_SIZE_DIALOG,
                                       None, None)
  
            message = "There is already a %s with the same name" % t
            message += " in the Desktop.\n"
            message += "Replace it?"
            label = gtk.Label(message)

            image = gtk.image_new_from_pixbuf(pix)

            hbox = gtk.HBox(False, 0)
            hbox.pack_start(image, False, False, 5)
            hbox.pack_start(label, False, False, 5)
            hbox.show_all()

            dialog.vbox.pack_start(hbox)

            copy = dialog.run()
        
            dialog.destroy()

        if copy:
            line = "rm -rf %s" % dest
            result = commands.getstatusoutput(line)
            line = "cp -a %s %s" % (source, desktop)
            result = commands.getstatusoutput(line)

    button.connect("clicked", copy_to_desktop, tree)

    return vbox

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

        self.property_label = gtk.Label("History")
        self.property_label.show()

        self.vbox = create_list_gui(history)
        self.vbox.show_all()

        return nautilus.PropertyPage("NautilusPython::nilfs2",
                                     self.property_label, self.vbox),
