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
import gio
import tempfile
import xml.sax.saxutils
import evince
import sx.pisa3 as pisa

class NILFSException(Exception):
    def __init__(self, info):
        Exception.__init__(self,info)

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

    # Make a dictionary of checkpoints sorted by device name from /proc/mounts
    cpregex=r'^ *([^ ]+) +([^ ]+) +nilfs2 +([^ ]*cp=([\d]+)[^ ]*) +([^ ]+) +([^ ]+) *$'
    checkpoints = {}
    with open("/proc/mounts") as f:
        ms = re.findall(cpregex, f.read(), re.M)
        for m in ms:
            cpinfo = m[1], int(m[3])
            dev = m[0]
            if dev in checkpoints:
                checkpoints[dev].append(cpinfo)
            else:
                checkpoints[dev] = [cpinfo]

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
        sys.stderr.write("configuration is not valid. missig %s key\n" % e)

    except NILFSException, (e):
        sys.stderr.write(str(e) + "\n")

    return []

def create_thumbnail_pixbuf(path):
    css = '<style type="text/css"> \
@page { \
  size: letter;\
} \
pre { \
  font-size: 32px;\
} \
</style>'

    meta = '<meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />'

    try:
        document = evince.document_factory_get_document("file://" + path)
    except glib.GError:
        res = commands.getstatusoutput("file " + path + "| cut -d: -f 2")
        text = re.compile(" text( |$)")
        image = re.compile(" image( |,)")
        if text.search(res[1]) != None:
            fd = open(path)
            contents = fd.read(1024) #generante first page only
            data = css + meta + '<pre>\n' + \
                   xml.sax.saxutils.escape(contents) + '\n</pre>'
            fd.close()
            fd = tempfile.NamedTemporaryFile('wb', -1, '.pdf',
                                             'tb', delete=False)
            pisa.CreatePDF(data, fd)
            fd.close()
            f = os.path.abspath(fd.name)
            document = evince.document_factory_get_document("file://" + f)
            os.remove(f)
        elif image.search(res[1]) != None:
            return gtk.gdk.pixbuf_new_from(path)
        else:
            return None

    context = evince.RenderContext(document.get_page(0), 0, 1)
    return evince.DocumentThumbnails.get_thumbnail(document, context, 1)

def create_pixbuf(path):
    pix = create_thumbnail_pixbuf(path)
    if pix != None:
        return pix

    style = gtk.Style()

    icon = style.lookup_icon_set(gtk.STOCK_FILE)
    pix = icon.render_icon(style, gtk.TEXT_DIR_NONE, gtk.STATE_NORMAL,
                           gtk.ICON_SIZE_DIALOG, None, None)

    if not os.path.islink(path) and os.path.isdir(path):
        t = "directory"
        icon = style.lookup_icon_set(gtk.STOCK_DIRECTORY)
        pix = icon.render_icon(style, gtk.TEXT_DIR_NONE,
                               gtk.STATE_NORMAL, gtk.ICON_SIZE_DIALOG,
                               None, None)
    return pix

global_thumbnail_cache = {}
def create_cached_pixbuf(path):
    if global_thumbnail_cache.has_key(path):
        return global_thumbnail_cache[path]
    pix = create_pixbuf(path)
    w= 100.;
    h = pix.get_height() * w/ pix.get_width()
    global_thumbnail_cache[path] = pix.scale_simple(int(w), int(h),
                                                    gtk.gdk.INTERP_BILINEAR)
    return global_thumbnail_cache[path]

def create_icon_pixbuf(path):
    pix = create_pixbuf(path)
    w= 48.;
    h = pix.get_height() * w/ pix.get_width()
    return pix.scale_simple(int(w), int(h), gtk.gdk.INTERP_BILINEAR)

def get_selected_path(treeview):
    select = treeview.get_selection()
    rows = select.get_selected_rows()
    if len(rows[1]) == 0:
        return False
    row = rows[1][0][0]
    model = treeview.get_model()
    itr = model.get_iter(row)
    v = model.get_value(itr, 0)
    return v

def open_with(path):
    context = gtk.gdk.AppLaunchContext()
    path = os.path.abspath(path)

    if os.path.isdir(path):
        path += "/"

    mime_type = gio.content_type_guess(path)
    app_info = gio.app_info_get_default_for_type(mime_type, False)
    if app_info != None:
        app_info.launch([gio.File(path)], context)
    else:
        sys.stderr.write('no application related to "%s"\n' % mime_type)

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

    def double_clicked(treeview, path, view_column, user):
        path = get_selected_path(treeview)
        open_with(path)

    tree.connect("row-activated", double_clicked, None)

    scroll = gtk.ScrolledWindow()
    scroll.add(tree)

    frame = gtk.Frame("History")
    frame.set_shadow_type(gtk.SHADOW_ETCHED_IN)
    frame.add(scroll)

    vbox = gtk.VBox(False, 0)
    vbox.pack_start(frame)

    hbox = gtk.HBox(False, 0)
    bbox = gtk.VBox(False, 0)
    button = gtk.Button("Copy To Desktop")
    bbox.pack_end(button, False, False, 10);
    hbox.pack_end(bbox, False, False, 10);

    pix = create_cached_pixbuf(history[0]['path'])
    image = gtk.image_new_from_pixbuf(pix)
    hbox.pack_start(image, False, False, 20);

    vbox.pack_start(hbox, False, False, 5);

    def row_selected(treeview, user):
        path = get_selected_path(treeview)
        if path != False:
            pix = create_cached_pixbuf(path)
            image.set_from_pixbuf(pix)

    tree.connect("cursor-changed", row_selected, None)

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

            t = "file"
            if os.path.islink(dest):
                t = "link"
            elif os.path.isdir(dest):
                t = "directory"
  
            message = "There is already a %s with the same name" % t
            message += " in the Desktop.\n"
            message += "Replace it?"
            label = gtk.Label(message)

            pix = create_icon_pixbuf(dest)
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

        self.property_label = gtk.Label("History")
        self.property_label.show()

        if len(history) == 0:
            vbox = gtk.VBox(False, 0) 
            label = gtk.Label("no history")
            vbox.pack_start(label, True, True, 10)
            self.vbox = vbox
        else:
            self.vbox = create_list_gui(history)

        self.vbox.show_all()

        return nautilus.PropertyPage("NautilusPython::nilfs2",
                                     self.property_label, self.vbox),
