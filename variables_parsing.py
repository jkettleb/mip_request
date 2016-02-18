#!/usr/bin/env python
"""
Analysis to try to put forward candidate mappings for CMIP6 based
on the CMIP5 information we have.

The CMIP5 information is taken from a the sources of information
we have.  These include:

   1. The XXX_variables files.  These tell us the variables we
      submitted, what mapping expressions where used, what 
      filtering of the pp fields was done and any minimum
      value handling.
   2. The stash_mappings.txt.  This tells us the stash codes
      and how they are used in the mapping expressions (or
      whether the mappings expression was IDL).
   3. The CMIP5 mip tables.  These give us standard names, cell_methods
      etc. for the variables we submitted at CMIP5.

The CMIP6 requested diagnostics are taken from a csv file created from
the Google sheet that Alistair has put together.

Output is written to csv file, that is similar in format to the CMIP6
request csv but 
"""

import ConfigParser
import os
import csv
import string
from mip_parser import parseMipTable as mip_table_read

_SEP='_'
def mip_id(table, section):
    """
    Return a MIP id based on the table and section.

    Examples
    --------
    >>> mip_id('CMIP5_Amon', 'tas')
    'CMIP5_Amon_tas'

    >>> mip_id('Lmon', 'grassFrac')
    'Lmon_grassFrac'
    """
    return _SEP.join((table, section))

class _AttrFromDict(object):
    """
    Base class for classes that derive their attributes from a
    dictionary.
    """
    def __getattr__(self, attname):
        if attname not in self._attdict:
            raise AttributeError('Attribute not found: {}'.format(attname))
        else:
            return self._attdict[attname]
    
class VariableEntry(_AttrFromDict):
    """
    Represents an entry in a xxx_variables file.

    Example
    ------

    >>> entry = VariableEntry('apm','od550aer', dict(lbproc=128,
    ...          lbuser5=3, miptable='CMIP5_aero', outputs_per_file='10'))
    >>> entry.stream, entry.mip_id, entry.published, entry.selection
    ('apm', 'CMIP5_aero_od550aer', 'CMIP5 (aero, od550aer)', 'lbproc: 128, lbuser5: 3')

    >>> entry = VariableEntry('apm', 'sbl_1', dict(miptable='CMIP5_Lmon'))
    >>> entry.mip_id
    'CMIP5_Lmon_sbl'
    >>> entry.min_handling
    ''

    >>> entry = VariableEntry('apm', 'pr', dict(miptable = 'CMIP5_Amon', valid_min='0', tol_min='-1.0e-7'))
    >>> entry.min_handling
    'valid_min: 0, tol_min: -1.0e-7'
    """
    
    _SELECTORS = ('lbproc', 'lbuser5', 'blev')
    _MIN_HANDLING = ('valid_min', 'tol_min')
    
    def __init__(self, fname, section, attdict):
        self.stream = fname
        clean_section = section.split(_SEP)[0] # remove any _1's or _2's
        self.mip_id = mip_id(attdict['miptable'], clean_section)
        self.published = attdict.setdefault('mapping_id', "{} ({}, {})".format(*self.mip_id.split(_SEP)))
        self._attdict = attdict

    def _gather_atts(self, attnames):
        wanted = {k:v for k, v in self._attdict.iteritems() if k in attnames}
        return ', '.join(['{}: {}'.format(k, v) for k, v in wanted.iteritems()])
        
    @property
    def selection(self):
        """Return the stash selections."""
        return self._gather_atts(self._SELECTORS)

    @property
    def min_handling(self):
        """Return information on whether any minimum handling is done."""
        return self._gather_atts(self._MIN_HANDLING)
        

def read_variables_file(fname):
    """Read the xxx_variables file returning a list of entries."""
    
    with open(fname, 'r') as fi:
        parser = ConfigParser.SafeConfigParser()
        parser.readfp(fi)
    stream = os.path.basename(fname).split(_SEP)[0]
    return [VariableEntry(stream, section, dict(parser.items(section))) for section in parser.sections()]

def read_variables_dir(dname):
    """Read a directory of xxx_variables files returning all entries."""
    
    fnames = [fname for fname in os.listdir(dname) if 'variables' in fname]
    variables = list()
    for fname in fnames:
        variables.extend(read_variables_file(os.path.join(dname, fname)))
    return variables  


class MappingExpression(_AttrFromDict):
    """Class representing the entries in the stash mapping table."""
    
    _TRANS = string.maketrans(' ', _SEP)
    
    def __init__(self, adict):
        adict.pop('') # remove leading null column
        self._attdict = self._strip(adict)
        
    def _strip(self, adict):
        return {k[2:-2].translate(self._TRANS).lower(): v.strip() for k,v in adict.iteritems()}
        
    def for_version(self, version):
        """Return True if this expression is appropriate for version."""
        return eval('{} {}'.format(version, self.um_version))

def read_stash_mapping(ifile, version):
    """
    Return the mappings from the stash mapping file at a model code version.
    """
    with open(ifile, 'r') as mi:
        mapping_reader = csv.DictReader(mi, delimiter = '|')
        expressions = (MappingExpression(entry) for entry in mapping_reader)
        expressions = filter(lambda e: e.for_version(version), expressions)
        
    return expressions


class _NoExpression(object):
    stash_mapping = ''
    selection = ''
    units = ''
    positive = ''
    stream = ''
    comment = ''
    notes = ''

class MipTableVariableEntry(_AttrFromDict):
    """
    Class representing and entry from a mip table

    Examples
    --------

    >>> v = MipTableVariableEntry('CMIP5_Amon', 'tas', dict())
    >>> v.mip_id
    'CMIP5_Amon_tas'
    >>> v.short_mip_id
    'Amon_tas'

    >>> v.has_mapping
    False
    """
    _SEP = '_'
    
    def __init__(self, table_name, entry, adict):
        self.entry = entry
        self.table = table_name.split(self._SEP)[1]
        self.table_name = table_name
        self.mip_id = mip_id(table_name, entry)
        self.short_mip_id = mip_id(self.table, self.entry)
        self.variable = _NoExpression()
       
        for attname in ('positive', 'cell_methods'):
            adict.setdefault(attname, '')

        self._attdict = adict
        
    @property       
    def is_variable(self):
        return 'modeling_realm' in self._attdict

    @property
    def has_mapping(self):
        return self.variable.stash_mapping != ''
    
class MipCsvVariableEntry(object):
    """
    Class to represent an entry from the MIP CSV file.
    
    Example
    -------
    >>> atts = {"Notes (this doesn't)": '',
    ...         "Comment (this goes into file metadata?)": '',
    ...         "cmor_label": 'tas', 
    ...         "miptable": 'Amon' }
    >>> v = MipCsvVariableEntry(atts)
    >>> v.short_mip_id
    'Amon_tas'

    Will also correct 'cfsites' to 'cfSites':
    >>> atts = {"Notes (this doesn't)": '',
    ...         "Comment (this goes into file metadata?)": '',
    ...         "cmor_label": 'tas', 
    ...         "miptable": 'cfsites' }
    >>> v = MipCsvVariableEntry(atts)
    >>> v.short_mip_id
    'cfSites_tas'
    """
    
    def __init__(self, adict):
        self.entry = adict['cmor_label']
        self.table = adict['miptable']
        self._correct_atts()
        self.short_mip_id = mip_id(self.table, self.entry)
        self.attdict = adict
        self._tidy_dict()

        
    def _correct_atts(self):
        if self.table == 'cfsites':  # take into account case issues
            self.table = 'cfSites'

    def _tidy_dict(self):
        
        _TO_DELETE = ("Notes (this doesn't)",
                      "Comment (this goes into file metadata?)")
        
        _TO_ADD = ('Notes', 'Comment', 'Model_positive', 'Model_units')
        
        for attname in _TO_DELETE:
            del self.attdict[attname]

        for attname in _TO_ADD:
            self.attdict[attname] = ''
        
def read_mip_dir(dname, project):
    """Read all the mip tables in a directory."""
    files = [os.path.join(dname, fname) 
             for fname in os.listdir(dname) 
             if fname.startswith(project)]
    requests = list()
    for fname in files:
        requests.extend(read_mip_table(fname))
    return requests

def read_mip_table(fname):
    """Return a list of MIP requested variables for a miptable."""
    
    table = mip_table_read(fname)
    tname = os.path.basename(fname)
    requests = (MipTableVariableEntry(tname, entryname, entry)
                  for entryname, entry in table['vars'].iteritems())
    return filter(lambda r: r.is_variable, requests)

def read_cmip6_csv(mip_csv):
    """Return a list of entries from the CMIP6 request spreadsheet."""
    with open(mip_csv, 'r') as mi:
        reader = csv.DictReader(mi)
        return [MipCsvVariableEntry(record) for record in reader]

def add_expression_to_variables(variables, expressions):
    """Matches an expression to a variable using the published attribute."""
        
    for variable in variables:
        for expression in expressions:
            if variable.published == expression.published:
                variable.stash_mapping = expression.stash_mapping
                variable.units = expression.units
                variable.positive = expression.positive
                variable.comment = expression.comment
                variable.notes = expression.notes
                
def variable_for_request(requests, variables):
    """Matches variables against MIP requested variables."""
    
    for request in requests:
        for variable in variables:
            if variable.mip_id == request.mip_id:
                request.variable = variable

def known_for_required(recs1, requests):
    """
    Adds to previous know expression information to the new requests.

    Matches a previous MIP diagnostics  with a new MIP diagnostic
    using the short_mip_id like Amon_tas.
    """
    
    for cmip6 in recs1:
        for cmip5 in requests:
            if cmip6.short_mip_id == cmip5.short_mip_id:
                cmip6.attdict['Variable_mapping'] = cmip5.variable.stash_mapping
                cmip6.attdict['PP_constraint'] = cmip5.variable.selection
                cmip6.attdict['Comment'] = cmip5.variable.comment
                cmip6.attdict['Notes'] = cmip5.variable.notes
                cmip6.attdict['Model_positive'] = cmip5.variable.positive
                cmip6.attdict['Model_units'] = cmip5.variable.units
                cmip6.attdict['Min_handling'] = cmip5.variable.min_handling
                
def known_mappings(vdir, tdir, mfile, version):
    """
    Return a list of known mappings for a model version.

    The mappings are inferred from the XXX_variables files,
    the MIP tables, the stash mapping file. 
    """
    
    expressions = read_stash_mapping(mfile, version)
    variables = read_variables_dir(vdir)
    add_expression_to_variables(variables, expressions)
    
    requests = read_mip_dir(tdir, 'CMIP5') # TODO improve this CMIP5 hard coded
    variable_for_request(requests, variables)

    return filter(lambda r: r.has_mapping, requests) # only CMIP5 with requests

def write_csv(ofile, recs1):
    """
    Write the records to a csv file.
    """
    with open(ofile, 'wb') as mi:
        fieldnames = "cmor_label,title,miptable,cf_std_name,description,cell_methods,dimension,units,positive,realm,priority,requesting_mips,UKESM_component,Owner,Variable_mapping,PP_constraint,Model_units,Model_positive,Stream,Plan,Ticket,Comment,Notes,Min_handling".split(',')

        writer = csv.DictWriter(mi, fieldnames=fieldnames)
        writer.writeheader()
        for rec in recs1:
            writer.writerow(rec.attdict)

def fill_cmip6(mip_csv, mfile, vdir, tdir, ofile):
    """
    Coordinate the reading the known mappings from CMIP5
    comparison with CMIP6 requests and output to file.
    """
    requests = known_mappings(vdir, tdir, mfile, 6.6)  #TODO better version handling
    cmip6 = read_cmip6_csv(mip_csv)

    known_for_required(cmip6, requests)    
    write_csv(ofile, cmip6)

if __name__ == '__main__':

    bdir = '/project/ipcc/ar5/etc'
    ofile = 'out2.csv'
    tdir = os.path.join(bdir, 'mip_tables/CMIP5/20130717')
    mfile = os.path.join(bdir, 'mapping_tables/stash_mappings.txt')
    vdir = '/project/cfmip/ar5_proc_CMIP5_MOHC/trunk/HadGEM2-ES'
    cmip6_requests = 'input/CMIP6_data_req_20151126.csv'
    fill_cmip6(cmip6_requests, mfile, vdir, tdir, ofile)
