#!/usr/bin/env pythoh

from itertools import ifilter, imap, count
import re

def _has_content(line):
    return line not in ('\n', ' \n')

def _strip_eol(line):
    return line[:-1]

def _nl(line):
    match = re.search('streq\((.*)\)', line)
    return match.group(1)

def _after_eq(line):
    match = re.search('=(.*)$', line)
    return match.group(1)

def read_nl(fi):
    inp = imap(_strip_eol, ifilter(_has_content, fi))
    while True:
        try:
            namelist = _nl(next(inp))
        except StopIteration:
            break
        dom = _after_eq(next(inp))
        isec = _after_eq(next(inp))
        item = _after_eq(next(inp))
        package = _after_eq(next(inp))
        tim = _after_eq(next(inp))
        use = _after_eq(next(inp))
        yield (namelist, dom, isec, item, tim, use)

def write_records(fo, records):
    fo.write('namelist,dom,isec,item,tim,use\n')
    for record in records:
        fo.write(','.join(record) + '\n')

with open('tim.out', 'r') as fi:
    with open('tim.csv', 'w') as fo:
        records = read_nl(fi)
        write_records(fo, records)
