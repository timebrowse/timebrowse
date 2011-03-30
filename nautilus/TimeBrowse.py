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
__version__   = "0.6"

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
import threading

class NILFSException(Exception):
    "A private exception class to pass error information"
    def __init__(self, info):
        Exception.__init__(self,info)

class NILFSMounts:
    "NILFS Snapshot enumerator class"
    def __init__(self):
        self.nilfs_entry_regex = re.compile('^ *([^ ]+) +([^ ]+) +nilfs2 +([^ ]+) +([^ ]+) +([^ ]+) *$', re.M)
        self.cp_regex = re.compile('.*cp=.*')
        self.nilfs_cp_entry_regex = re.compile('^ *([^ ]+) +([^ ]+) +nilfs2 +([^ ]*cp=([\d]+)[^ ]*) +([^ ]+) +([^ ]+) *$', re.M)

    def find_nilfs_in_mtab(self):
        """
        List all mount points of NILFS snapshots which appear in
        /proc/mounts.  This method first finds NILFS volumes in
        /etc/mtab, then enumerates all snapshot mounts for each NILFS
        volume by using /proc/mounts.

        On success, a list of mount point dictionaries will be
        returned in the following form:

          [ { 'dev': <device name>,
              'mp': <pathname of mount point>,
              'cps': [ <cpinfo-a>, <cpinfo-b>, <cpinfo-c>, ... ]},
             ...  ]

        where each <cpinfo-?> represents a checkpoint information,
        which is a tuple (a pair) consisting of a path name and a
        checkpoint number for each snapshot mount.

        The device names and path names in the dictionaries are
        normalized.  The list entries of NILFS volume are sorted with
        their mountpoint path names so that shorter path names come
        before longer ones.  The cpinfo entries are also sorted with
        checkpoint numbers so that smaller checkpoints number come
        before larger ones.

        On error, this method will raise a NILFSException exception.
        """
        with open("/etc/mtab") as f:
            entries = self.nilfs_entry_regex.findall(f.read())

        # Device paths and mount points in mtab are normalized
        actives = [{'dev' : str(e[0]), 'mp' : str(e[1])}
                    for e in entries if not self.cp_regex.match(e[2])]
   
        if len(actives) == 0:
            raise NILFSException("can not find active NILFS volume in mtab")

        # sort by mount point length. the longer, the earlier
        actives.sort(lambda a, b: -cmp(len(a['mp']), len(b['mp'])))

        # Make a dictionary of checkpoints sorted by device name
        # from /proc/mounts
        checkpoints = {}
        with open("/proc/mounts") as f:
            ms = self.nilfs_cp_entry_regex.findall(f.read())
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

    def find_nilfs_mounts(self, realpath):
        """
        Find a NILFS volume whose mount point starts with the given
        path name and return a dictionary containing information of
        the NILFS volume and associated snapshot mounts in the form
        explained in the docstring of find_nilfs_in_mtab() method.
        """
        mount_list = self.find_nilfs_in_mtab()
        for e in mount_list:
            if realpath.startswith(e['mp']):
                return e 
        raise NILFSException("file not in NILFS volume: %s" % realpath)



    def age_repr(self, val, unit):
        if abs(int(val)) > 1:
            unit += "s"  # conjugate 'unit' to plural form
        return "%d %s %s" % (abs(val), unit, "ago" if val > 0 else "later")

    def pretty_format(self, time):
        if time == 0:
           return "latest"
        if abs(time) < 60:
            return self.age_repr(time, "sec")
        time = time/60
        if abs(time) < 60:
            return self.age_repr(time, "minute")
        time = time/60
        if abs(time) < 24:
            return self.age_repr(time, "hour")
        time = time/24
        if abs(time) < 30:
            return self.age_repr(time, "day")
        m = time/30
        if abs(m) < 30:
            return self.age_repr(m, "month")
        y = time/365
        return self.age_repr(y, "year")

    def get_dir_info(self, directory):
        """
        Return update time and size of a directory.  The update time
        is currently calculated as the latest mtime of the directory
        and its child nodes.
        """
        stat = os.stat(directory)
        newest = stat.st_mtime
        size = stat.st_size
        for e in os.listdir(directory):
            mtime = os.lstat("%s/%s" % (directory, e)).st_mtime
            if newest < mtime:
                newest = mtime
        return (newest, size)

    def get_file_info(self, path):
        """
        Return mtime and size of a node.  For directories, this calls
        get_dir_info method.  For symlinks, this returns mtime and
        size of the symlink itself.
        """
        if os.path.isdir(path) and not os.path.islink(path):
            return self.get_dir_info(path)
        else:
            stat = os.lstat(path)
            return (stat.st_mtime, stat.st_size)
  
    def list_history(self, cps, relpath):
        """
        Make a version list entry of the given object with a relative
        path @relpath, and return it in a coroutine manner.

        The version list entry is a dictionary in the following form:

          { 'path': <pathname>, 'mtime': <mtime>, 'size': <filesize>,
            'age': <string representing age of the object> }
        """
        current_time = time.time()
        last_mtime = current_time
        unyield_count = 0
        for cp in cps:
            f = cp[0] + '/' + relpath
            if os.path.exists(f):
                (mtime, size) = self.get_file_info(f)
                if last_mtime != mtime:
                    entry = {'path' : f, 'mtime' : mtime, 'size' : size,
                             'age' : self.pretty_format(current_time - mtime)}
                    unyield_count = 0
                    yield entry
                last_mtime = mtime
            if (unyield_count&0xFF) == 0xFF:
                unyield_count = 0
                yield None
            unyield_count += 1

    def get_history(self, path):
        """
        Get a version list entry of the object on @path if it's stored
        in a nilfs volume.
        """
        try:
            realpath = os.path.realpath(path)
            mounts = self.find_nilfs_mounts(realpath)
            relpath = os.path.relpath(realpath, mounts['mp'])
            return  self.list_history(mounts['cps'], relpath)

        except KeyError, (e):
            sys.stderr.write("configuration is not valid. missig %s key\n" % e)

        except NILFSException, (e):
            sys.stderr.write(str(e) + "\n")

        return None

class PixbufFactory:
    def __init__(self, lang=None):
        self.thumbnail_cache = {}
        self.pdf = re.compile('.*PDF.*')
        server = "unoconv --listener"
        if lang:
            server = "LANG=%s %s" % (lang, server)
        os.system(server + " &")

    def create_thumbnail_pixbuf(self, path):
        mime = gio.content_type_guess(path)
        if mime == "application/pdf":
            pdf = path
        elif mime.startswith("image/"):
            return gtk.gdk.pixbuf_new_from_file(path)
        elif mime.startswith("text/"):
            pdf = self.topdf(path)
        elif mime.startswith("application/vnd.oasis.opendocument"):
            #openoffice documents
            pdf = self.topdf(path)
        elif mime.startswith("application/vnd.openxmlformats-officedocument"):
            #ooxml documents
            pdf = self.topdf(path)
        elif (mime.startswith("application/vnd.ms-powerpoint") or
              mime.startswith("application/vnd.ms-excel") or
              mime.startswith("application/vnd.ms-word") ):
            #MS Office documents (non ooxml formats)
            pdf = self.topdf(path)
        else:
            m = commands.getstatusoutput("file %s" % path)
            if m[0] != 0 or not re.match(".* text.*", m[1]):
                print >> sys.stderr, "mime type: %s" % mime
                print >> sys.stderr, "magic: %s" % m[1]
                return None
            pdf = self.topdf(path)

        pix = None
        if pdf:
            ppm = self.pdftoppm(pdf)
            if pdf != path:
                os.unlink(pdf)
            if ppm:
                pix = gtk.gdk.pixbuf_new_from_file(ppm)
                os.unlink(ppm)

        return pix

    def __execute_cmd__(self, cmd):
        tmp = tempfile.NamedTemporaryFile(delete=False)
        ret = commands.getstatusoutput(cmd + " > " + tmp.name)
        if not ret[0] == 0:
            os.unlink(tmp.name)
            return None
        return tmp.name

    def topdf(self, path):
        cmd = "unoconv --stdout %s" % path
        return self.__execute_cmd__(cmd)

    def pdftoppm(self, path, page=1):
        cmd = "pdftoppm -f %d -l %d %s" % (page, page, path)
        return self.__execute_cmd__(cmd)

    def create_pixbuf(self, path):
        pix = self.create_thumbnail_pixbuf(path)
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

    def cached_pixbuf(self, path):
        if not self.thumbnail_cache.has_key(path):
            self.thumbnail_cache[path] = self.create_pixbuf(path)
        return self.thumbnail_cache[path]

    def icon_pixbuf(self, path):
        pix = self.create_pixbuf(path)
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

def confirm_dialog_factory(icon_factory):
    def create_dialog(dest):
        dialog = gtk.Dialog("Confirm", None, gtk.DIALOG_MODAL,
                            ("OK", True, "Cancel", False))

        t = "file"
        if os.path.islink(dest):
            t = "link"
        elif os.path.isdir(dest):
            t = "directory"

        message = "There is already a %s with the same name" % t
        message += " in the destination folder.\n"
        message += "Replace it?"
        label = gtk.Label(message)

        pix = icon_factory.icon_pixbuf(dest)
        image = gtk.image_new_from_pixbuf(pix)

        hbox = gtk.HBox(False, 0)
        hbox.pack_start(image, False, False, 5)
        hbox.pack_start(label, False, False, 5)
        hbox.show_all()

        dialog.vbox.pack_start(hbox)

        return dialog
    return create_dialog

def copy_to_desktop(source, confirm_dialog_factory):
    basename = os.path.basename(source)
    desktop = glib.get_user_special_dir(glib.USER_DIRECTORY_DESKTOP)
    dest = desktop + "/" + basename

    restore_to(source, dest, confirm_dialog_factory)

def restore_to(source, dest, confirm_dialog_factory):
    restore = True
    if os.path.exists(dest):
        dialog = confirm_dialog_factory(dest)
        restore = dialog.run()
        dialog.destroy()

    if restore:
        target = os.path.dirname(dest)
        line = "rsync -ax --delete --inplace '%s' '%s'" % (source, target)
        result = commands.getstatusoutput(line)

class FlexibleImage(gtk.DrawingArea):
    def __init__(self):
        gtk.DrawingArea.__init__(self)
        self.pixbuf = None
        self.connect("expose-event", self.expose)

    def expose(self, w, e):
        pix = self.__fit_pixbuf__(self.allocation)
        x = (self.allocation.width - pix.get_width())/2
        y = (self.allocation.height - pix.get_height())/2

        ctxt = self.window.cairo_create()
        ctxt.set_source_pixbuf(pix,x,y)
        ctxt.paint()

    def set_from_pixbuf(self, pixbuf):
        self.pixbuf = pixbuf
        self.queue_draw()

    def __fit_pixbuf__(self, rect):
        w = self.pixbuf.get_width()
        h = self.pixbuf.get_height()
        ww = rect.width
        wh = rect.height
        if ww == 0 or wh == 0:
           ww = wh = 1
        if h * float(ww)/float(w) <= wh:
            destw = ww
            desth = int(h * float(ww)/float(w))
            if desth <= 0:
                desth = 1
        else:
            desth = wh
            destw = int(w * float(wh)/float(h))
            if destw <= 0:
                destw = 1
        return self.pixbuf.scale_simple(destw, desth, gtk.gdk.INTERP_BILINEAR)

def create_list_gui(current, icon_factory):
    nilfs = NILFSMounts()

    store = gtk.ListStore(gobject.TYPE_STRING,
                          gobject.TYPE_INT64,
                          gobject.TYPE_STRING,
                          gobject.TYPE_INT,
                          gobject.TYPE_STRING,)
    store.clear()

    tree = gtk.TreeView()
    tree.set_rules_hint(True)
    tree.set_headers_clickable(True)
    tree.set_model(store)

    rederer = gtk.CellRendererText()

    column = gtk.TreeViewColumn("date", rederer, text=2)
    column.set_sort_column_id(1)
    column.set_resizable(True)
    tree.append_column(column)

    column = gtk.TreeViewColumn("size", rederer, text=3)
    column.set_sort_column_id(3)
    column.set_resizable(True)
    tree.append_column(column)

    column = gtk.TreeViewColumn("age", rederer, text=4)
    column.set_sort_column_id(1) # same as date
    column.set_resizable(True)
    tree.append_column(column)

    tree.enable_model_drag_source(gtk.gdk.BUTTON1_MASK,
                                  [('text/uri-list', 0, 1)],
                                   gtk.gdk.ACTION_COPY)
    def get_drag_data(tv, context, selection, target_id, etime):
        path = get_selected_path(tv)
        selection.set_uris(["file://%s" % path])
    tree.connect("drag_data_get", get_drag_data)

    def double_clicked(treeview, path, view_column, user):
        path = get_selected_path(treeview)
        open_with(path)
    tree.connect("row-activated", double_clicked, None)

    scroll = gtk.ScrolledWindow()
    scroll.add(tree)

    frame = gtk.Frame("History")
    frame.set_shadow_type(gtk.SHADOW_ETCHED_IN)
    frame.add(scroll)
    frame.set_size_request(-1,150) #default height

    vbox = gtk.VBox(False, 0)
    searching_history_label = gtk.Label("searching history..")
    vbox.pack_start(searching_history_label)

    hbox = gtk.HBox(False, 0)
    bbox = gtk.VBox(False, 0)
    copy_to_btn = gtk.Button("Copy To Desktop")
    bbox.pack_end(copy_to_btn, False, False, 10);
    restore_to_btn = gtk.Button("Restore")
    bbox.pack_end(restore_to_btn, False, False, 10);
    open_in_dir_btn = gtk.Button("Open in Directory")
    bbox.pack_end(open_in_dir_btn, False, False, 10);
    hbox.pack_end(bbox, False, False, 10);

    image = FlexibleImage()
    image.w = image.h = 0
    hbox.pack_start(image, True, True, 0);

    def row_selected(treeview, user):
        path = get_selected_path(treeview)
        if path != False:
            image.set_from_pixbuf(icon_factory.cached_pixbuf(path))
    tree.connect("cursor-changed", row_selected, None)

    def copy_to_desktop_button_clicked(widget, info):
        source = get_selected_path(info)
        if not source:
            return
        copy_to_desktop(source, confirm_dialog_factory(icon_factory))
    copy_to_btn.connect("clicked", copy_to_desktop_button_clicked, tree)

    def restore_button_clicked(widget, info):
        source = get_selected_path(info)
        if not source:
            return
        restore_to(source, current, confirm_dialog_factory(icon_factory))
    restore_to_btn.connect("clicked", restore_button_clicked, tree)

    def open_in_dir_button_clicked(widget, info):
        source = get_selected_path(info)
        if not source:
            return
        open_with(os.path.dirname(source))
    open_in_dir_btn.connect("clicked", open_in_dir_button_clicked, tree)

    condition = threading.Event()
    def add_list_entry(e):
        store.append([e['path'], e['mtime'],
                     time.strftime("%x %X",
                                   time.localtime(e['mtime'])),
                     e['size'], e['age']])

    def add_history(gen):
        if condition.isSet():
            return
        try:
            e = gen.next() 
            if e != None:
                add_list_entry(e)
            glib.idle_add(add_history, gen)

        except StopIteration:
            pass

    def add_first_history(gen):
        if condition.isSet():
            return
        try:
            if gen == None:
                raise StopIteration()
            e = gen.next()
            if e == None:
                glib.idle_add(add_first_history, gen)
            else:
                image.set_from_pixbuf(icon_factory.cached_pixbuf(e['path']))
                add_list_entry(e)

                vbox.remove(searching_history_label)
                vpaned = gtk.VPaned()
                vpaned.add1(frame)
                vpaned.add2(hbox)
                vbox.pack_start(vpaned)
                vbox.show_all()  

                glib.idle_add(add_history, gen)

        except StopIteration:
            if not condition.isSet():
                vbox.remove(searching_history_label)
                vbox.pack_start(gtk.Label("no history")) 
                vbox.show_all()  

    g = nilfs.get_history(current)
    glib.idle_add(add_first_history, g)

    def stop_generator(w, u):
        u.set()
    vbox.connect("destroy", stop_generator, condition)

    return vbox

class NILFS2PropertyPage(nautilus.PropertyPageProvider):
    def __init__(self):
        self.factory = PixbufFactory()

    def get_property_pages(self, files):
        if len(files) != 1:
            return

        f = files[0]
        if f.get_uri_scheme() != 'file':
            return

        target = f.get_uri()[7:]

        self.property_label = gtk.Label("History")
        self.property_label.show()

        self.vbox = create_list_gui(target, self.factory)
        self.vbox.show_all()

        return nautilus.PropertyPage("NautilusPython::nilfs2",
                                     self.property_label, self.vbox),
