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
        self.cpinfo_regex = re.compile(
            r'^ +([1-9]|[1-9][0-9]+) +([^ ]+ [^ ]+) +(ss|cp) +([^ ]+) +.*$',
            re.M)
        self.device = device
        result = self.__run_cmd__("lscp " + self.device)
        self.cps = self.__parse_lscp_output__(result)

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

    def __join_cp_list__(self, l, last):
        # Here, we suppose coinstantaneous checkpoints were shrunk both from
        # l and self.cps.

        # Remove the last checkpoint from self.cps if it has the same
        # timestamp with the head checkpoint of l.
        if l and l[0]['date'] == last['date']:
            if last['ss']:
                # l[0] may be a snapshot, but we select the previous
                # snapshot because it may be busy.
                del l[0]
            else:
                del self.cps[-1]
	self.cps += l

    def __refresh_cp_cache__(self):
        """
        Update state of checkpoint information in lscp cache to
        reflect manual snapshot operations
        """
        cn = self.cps[0]['cno']
        result = self.__run_cmd__("lscp -i %d " % cn + self.device)

        l = self.__parse_lscp_output__(result)

        for cp in self.cps[:]:
            # Skip checkpoints
            while l and cp['cno'] > l[0]['cno']:
                del l[0]
            if cp['ss']:
                pass  # Do not update snapshot
            else:
                if not l or cp['cno'] < l[0]['cno']:
                    # The plain checkpoint was deleted
                    self.cps.remove(cp)
                else:  # cp['cno'] == l[0]['cno']
                    if l[0]['ss']:
                        # A new snapshot found
                        cp['ss'] = True

        if not self.cps:  # if cp cache became empty
            self.cps = l
        else:
            last = self.cps[-1]
            while l and l[0]['cno'] <= last['cno']:
                del l[0]
            self.__join_cp_list__(l, last)

    def lscp(self, refresh=False):
        if not self.cps:
            result = self.__run_cmd__("lscp " + self.device)
            self.cps = self.__parse_lscp_output__(result)
        elif refresh:
            self.__refresh_cp_cache__()
        else:
            last = self.cps[-1]
            cn = last['cno'] + 1
            result = self.__run_cmd__("lscp -i %d " % cn + self.device)
            l = self.__parse_lscp_output__(result)
            self.__join_cp_list__(l, last)

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
       
