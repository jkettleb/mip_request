#!/usr/bin/env python

import ConfigParser
import os
import csv
import string
from mip_parser import parseMipTable as mip_table_read

class VariableEntry(object):
    """
    Represents an entry in a xxx_variables file.

    Example
    ------

    >>> entry = VariableEntry('apm_variables','od550aer', dict(lbproc=128,
    ...          lbuser5=3, miptable='CMIP5_aero', outputs_per_file='10'))
    >>> entry.stream, entry.mip_id, entry.published, entry.selection
    ('apm', 'CMIP5_aero_od550aer', 'CMIP5 (aero, od550aer)', 'lbproc: 128, lbuser5: 3')

    >>> entry = VariableEntry('apm_variables', 'sbl_1', dict(miptable='CMIP5_Lmon'))
    >>> entry.mip_id
    'CMIP5_Lmon_sbl'
    """
    
    _SELECTORS = ('lbproc', 'lbuser5', 'blev')
    _SEP = '_'
    
    def __init__(self, fname, section, options):
        self.stream = fname.split(self._SEP)[0]
        self._section = section.split(self._SEP)[0]
        doptions = dict(options)
        self.mip_id = doptions.pop('miptable') + self._SEP + self._section
        self._published(doptions)
        if 'outputs_per_file' in doptions:
            doptions.pop('outputs_per_file')
        self.stash_mapping = self.published
        self._options = doptions
        
    def __getattr__(self, attname):
        return self._options[attname]
    
    @property
    def selection(self):
        selectors = {k:v for k, v in self._options.iteritems() if k in self._SELECTORS}
        return ', '.join(['{}: {}'.format(k, v) for k, v in selectors.iteritems()])
    
    def _published(self, options):
        if 'mapping_id' in options:
            result = options.pop('mapping_id')
        else:
            result = "{} ({}, {})".format(*self.mip_id.split('_'))
        self.published = result
            

def read_variables_file(fname):
    """Read the xxx_variables file returning a list of entries."""
    with open(fname, 'r') as fi:
        parser = ConfigParser.SafeConfigParser()
        parser.readfp(fi)
    stream = os.path.basename(fname)
    return [VariableEntry(stream, section, parser.items(section)) for section in parser.sections()]

def read_variables_dir(dname):
    fnames = [fname for fname in os.listdir(dname) if 'variables' in fname]
    variables = list()
    for fname in fnames:
        variables.extend(read_variables_file(os.path.join(dname, fname)))
    return variables  


class MappingExpression(object):
    
    _T = string.maketrans(' ', '_')
    
    def __init__(self, adict):
        adict.pop('')
        self._attdict = self._strip(adict)
        
    def _strip(self, adict):
        return {k[2:-2].translate(self._T).lower(): v.strip() for k,v in adict.iteritems()}

    def __getattr__(self, attname):
        if attname not in self._attdict:
            raise AttributeError()
        else:
            return self._attdict[attname]
        
    def for_version(self, version):
        """Return True if this expression is appropriate for version."""
        return eval('{} {}'.format(version, self.um_version))

def read_stash_mapping(mi, version):
    mapping_reader = csv.DictReader(mi, delimiter = '|')
    expressions = (MappingExpression(entry) for entry in mapping_reader)

    expressions = [expression for expression in expressions if expression.for_version(version)]
    return expressions


class NoExpression(object):
    stash_mapping = ''
    selection = ''
    units = ''
    positive = ''
    stream = ''
    comment = ''
    notes = ''

class MipTableVariableEntry(object):
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
        self.mip_id = self._SEP.join((table_name, entry))
        self.short_mip_id = self._SEP.join((self.table, self.entry))
        self.variable = NoExpression()
       
        for attname in ('positive', 'cell_methods'):
            adict.setdefault(attname, '')

        self._attdict = adict
        
    def __getattr__(self, attname):
        if attname not in self._attdict:
            raise AttributeError('Attribute not found: {}'.format(attname))
        else:
            return self._attdict[attname]

    def as_row(self):
        try:
            
            result = (self.entry, self.long_name, self.table, self.standard_name, 'NotAvailable',
                      self.cell_methods, self.dimensions, self.units, self.positive, self.modeling_realm,
                      self.variable.stash_mapping, self.variable.selection, 
                      self.variable.units, self.variable.positive, self.variable.stream)
        except:
            result = (self.entry, self.long_name, self.table)

        return result

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
    >>> v = MipCsvVariableEntry(dict(cmor_label='tas', miptable='Amon'))
    >>> v.short_mip_id
    'Amon_tas'

    Will also correct 'cfsites' to 'cfSites':
    >>> v = MipCsvVariableEntry(dict(cmor_label='tas', miptable='cfsites'))
    >>> v.short_mip_id
    'cfSites_tas'
    """
    
    def __init__(self, adict):
        self.entry = adict['cmor_label']
        self.table = adict['miptable']
        if self.table == 'cfsites':
            self.table = 'cfSites'
        self.short_mip_id = '_'.join((self.table, self.entry))
        self.attdict = adict
        self._tidy_dict()

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
    table = mip_table_read(fname)
    tname = os.path.basename(fname)
    requests = (MipTableVariableEntry(tname, entryname, entry)
                  for entryname, entry in table['vars'].iteritems())
    return filter(lambda r: r.is_variable, requests)

def read_cmip6_csv(fi):
    reader = csv.DictReader(fi)
    return [MipCsvVariableEntry(record) for record in reader]

def expression_for_variables(variables, expressions):
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
       for cmip6 in recs1:
        for cmip5 in requests:
            if cmip6.short_mip_id == cmip5.short_mip_id:
                cmip6.attdict['Variable_mapping'] = cmip5.variable.stash_mapping
                cmip6.attdict['PP_constraint'] = cmip5.variable.selection
                cmip6.attdict['Comment'] = cmip5.variable.comment
                cmip6.attdict['Notes'] = cmip5.variable.notes
                cmip6.attdict['Model_positive'] = cmip5.variable.positive
                cmip6.attdict['Model_units'] = cmip5.variable.units
                
def write_csv(fi, requests):
    writer = csv.writer(fi)
    col_titles = ('cmor_label', 'title',
                  'miptable', 'cf_std_name',
                  'description', 'cell_methods',
                  'dimension', 'units',
                  'positive', 'realm',
                  'expression', 'constraint', 
                  'model_units', 'model_positive',
                  'stream')
    writer.writerow(col_titles)
    for request in requests:
        writer.writerow(request.as_row())

def build_cmip5_table(mfile, vdir, tdir, ofile):
    """Build and write the mapping expressions used in CMIP5."""
    
    with open(mfile, 'r') as mi:
        expressions = read_stash_mapping(mi, 6.6)
    variables = read_variables_dir(vdir)
    expression_for_variables(variables, expressions)
    
    requests = read_mip_dir(tdir, 'CMIP5') # improve this CMIP5 hard coded
    variable_for_request(requests, variables)

    with open(ofile, 'wb') as fo:
        write_csv(fo, requests)


def fill_cmip6(mip_csv, mfile, vdir, tdir, ofile):
    with open(mfile, 'r') as mi:
        expressions = read_stash_mapping(mi, 6.6)
    variables = read_variables_dir(vdir)
    expression_for_variables(variables, expressions)
    
    requests = read_mip_dir(tdir, 'CMIP5') # improve this CMIP5 hard coded
    variable_for_request(requests, variables)

    requests = filter(lambda r: r.has_mapping, requests) # only CMIP5 with requests

    with open(mip_csv, 'r') as mi:
        recs1 = read_cmip6_csv(mi)

    known_for_required(recs1, requests)    
    write_csv2(ofile, recs1)

def write_csv2(ofile, recs1):
    with open(ofile, 'wb') as mi:
        fieldnames = "cmor_label,title,miptable,cf_std_name,description,cell_methods,dimension,units,positive,realm,priority,requesting_mips,UKESM_component,Owner,Variable_mapping,PP_constraint,Model_units,Model_positive,Stream,Plan,Ticket,Comment,Notes".split(',')

        writer = csv.DictWriter(mi, fieldnames=fieldnames)
        writer.writeheader()
        for rec in recs1:
            writer.writerow(rec.attdict)
                
def main(mfile, vdir, tdir, ofile):
    fill_cmip6('CMIP6_data_req_20151126.csv', mfile, vdir, tdir, 'out2.csv')
    
if __name__ == '__main__':

    bdir = '/project/ipcc/ar5/etc'
    ofile = 'out.csv'
    tdir = os.path.join(bdir, 'mip_tables/CMIP5/20130717')
    vdir = '/project/cfmip/ar5_proc_CMIP5_MOHC/trunk/HadGEM2-ES'
    mfile = os.path.join(bdir, 'mapping_tables/stash_mappings.txt')
        
    main(mfile, vdir, tdir, ofile)
