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

import commands
import re
import time

class NILFS2:
    def __init__(self, device):
        self.device = device
        result = self.__run_cmd__("lscp " + self.device)
        self.cps = self.__parse_lscp_output__(result)

    def __run_cmd__(self, line):
        result = commands.getstatusoutput(line)
        if result[0] != 0:
            raise Exception(result[1])
        return result[1]

    def __parse_lscp_output__(self, output):
        regex = r'^ +([1-9]|[1-9][0-9]+) +([^ ]+ [^ ]+) +(ss|cp) +([^ ]+) +.*$'
        a = re.findall(regex, output, re.M)

        a = [ {'cno'  : int(e[0]),
               'date' : time.strptime(e[1], "%Y-%m-%d %H:%M:%S"),
               'ss'  : e[2] == 'ss'}
               for e in a if e[3] != 'i' ]

        if len(a) == 0:
            return []

        # remove checkpoints that have same date
        # pick first checkpoint out of the same date
        prev = a.pop(0)
        l = [prev]
        for e in a:
            if e['date'] != prev['date']:
                l.append(e)
            prev = e

        return l

    def lscp(self):
        last = self.cps[-1] 
        cn = last['cno'] + 1
        result = self.__run_cmd__("lscp -i %d" % cn + " " + self.device)

        l = self.__parse_lscp_output__(result)

        # remove checkpoints that have same date of the last checkpoint
        while (len(l) != 0) and (l[0]['date'] == last['date']):
            l.pop(0)
	self.cps += l

	return self.cps

    def chcp(self, cno, ss=False):
        line = "chcp cp "
        if ss:
            line = "chcp ss "
        line += self.device + " %i" % cno
        result = self.__run_cmd__(line)
        for cp in self.cps:
            if cno == cp['cno']:
                cp['ss'] = ss
                break
        self.lscp()
        return result

    def mkcp(self, ss=False):
        line = "mkcp"
        if ss:
            line += " -s"
        line += " " + self.device
        result = self.__run_cmd__(line)
        self.lscp()
        return result

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
       
