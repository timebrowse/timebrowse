#!/usr/bin/env python
#
# copyright(c) 2011 - Jiro SEKIBA <jir@unicus.jp>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2 of the License, or (at your option) any later version.
#

"""NILFS2 module"""

__author__    = "Jiro SEKIBA"
__copyright__ = "Copyright (c) 2011 - Jiro SEKIBA <jir@unicus.jp>"
__license__   = "LGPL"
__version__   = "0.5"

import commands
import re
import time

class NILFS2:
    def __init__(self, device):
        self.cpinfo_regex = re.compile(
            r'^ +([1-9]|[1-9][0-9]+) +([^ ]+ [^ ]+) +(ss|cp) +([^ ]+) +.*$',
            re.M)
        self.device = device

    def __run_cmd__(self, line):
        result = commands.getstatusoutput(line)
        if result[0] != 0:
            raise Exception(result[1])
        return result[1]

    def __parse_lscp_output__(self, output):
        a = self.cpinfo_regex.findall(output)

        a = [ {'cno'  : int(e[0]),
               'date' : time.strptime(e[1], "%Y-%m-%d %H:%M:%S"),
               'ss'  : e[2] == 'ss'}
               for e in a if e[3] != 'i' ]

        if not a:
            return []

        # Drop checkpoints that have the same timestamp with its
        # predecessor.  If a snapshot is present in the series of
        # coinstantaneous checkpoints, we leave it rather than plain
        # checkpoints.
        prev = a.pop(0)
        if not a:
            return [prev]

        ss = prev if prev['ss'] else None
        l = []
        for e in a:
            if e['date'] != prev['date']:
                l.append(ss if ss else prev)
                ss = None
            prev = e
            if prev['ss']:
                ss = prev
        l.append(ss if ss else a[-1])
        return l

    def lscp(self, index=1):
        result = self.__run_cmd__("lscp -i %d %s" % (index, self.device))
        return self.__parse_lscp_output__(result)

    def chcp(self, cno, ss=False):
        line = "chcp cp "
        if ss:
            line = "chcp ss "
        line += self.device + " %i" % cno
        return self.__run_cmd__(line)

    def mkcp(self, ss=False):
        line = "mkcp"
        if ss:
            line += " -s"
        line += " " + self.device
        return self.__run_cmd__(line)

if __name__ == '__main__':
    import sys
    nilfs = NILFS2(sys.argv[1])
    a = nilfs.lscp()[:]
    prev = a.pop(0)
    for e in a:
        if e['date'] == prev['date']:
            print "%d is same as %d" % (e['cno'], prev['cno'])
            print e['date']
            print prev['date']
        else:
            print "%d is different from %d" % (e['cno'], prev['cno'])
        prev = e
       
