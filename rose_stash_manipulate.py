#!/usr/bin/env python2.7
"""
Script to edit the rose stash in app/um/rose-app.conf and include the data
request from CMIP6

Requires openpyxl version 2.3.3. This is best installed in a virtualenv with:
    pip install openpyxl==2.3.3

This script:
    1. Reads rose-app.conf config file from the suite
        Copies this to a .default file to retain
    2. Does some initial processing
        Convert from climate meaning to stash meaning
        Adds package switches to every diagnostic
    3. Read an externally created conf file which contains new domain, time,
        usage profiles derived from CMIP6
        Try to keep names consistent with CMIP6 where possible, e.g. plev23 etc
        Add these to the suite's config - so that when we assign these profiles
        to the new CMIP6 requests they will be available in rose
    4. Read a template config file for a new stash request rose entry
    5. Read the CMIP6 data request and generate a list of diagnostics required
        a. This involves reading the excel spreadsheet of the CMIP6 data
            request (using other script key_hrmip_spreadsheet)
        b. Process each sheet of this data request
            1. For each line, derive the profile of the diagnostic needed
            2. Match this to a stash variable(s)
                either by the supplied cmor-stash dictionary
                or (currently) by the STASH translation Matthew added to the
                spreadsheet
            3. Also derive the appropriate domain, usage, time profile, package
                name based on information available
            4. Generate a dictionary of these stash requests, containing both
                CMIP6 and STASH information
            5. Write out a bunch of output files documenting:
                The translated cmor variables
                    in stash
                    for NEMO and CICE where appropriate
                Variables that are exact duplicates and hence excluded
                Variables to exclude either:
                    They don't have a stashname match
                    They are not wanted by the Met Office (from the data
                    request)
    6. Loop through the cmor-stash dictionary, and for each variable:
        Generate a rose config-node value in put_stash_into_config (using the
            template from earlier)
        Add this to the general config
    7. Merge these new config node variables back into the original rose config
        for the suite

Further notes:
Note that the temp_fixes namelist sits between streq and time namelists
Want to do:
    1. From default stash:
        Add package switch that reference default stash diagnostics - STD_GA7
        Tag duplicates within reference list and switch off - STD_DUPL - done
            by hand
        Convert to STASH meaning
            Changes time and usage
            Add Time profile for stash meaning and use it appropriately - from
            external file
        Streams (needs pp branch to enable ap0-ap9 and others)
            apl (not to be confused with LBCs)
            apq,r,t,u,v,w,z,0-9
            Adding freq:
                3 hr, 1hr, stash means (3),
                could use extra streams for additional HighResMIP/PRIMAVERA
                    diags
                need to keep 1 frequency per stream
                need a heaviside per stream (when pressure levels)
        Generate namelist additions for HighResMIP based on rose
                [namelist:streq(45091036)] sections
            Need standard dom_name, tim_name and use_name
            This could be driven by the CMIP6 diagnostic request itself
            Currently the profiles are read in from external file as standard
            names for profiles
        Consider what to do about duplicate/overlapping diagnostics (HighResMIP
                and STD_GA7):
            I guess if stash name and frequency are the same, and domain (some
                    are e.g. zonal means)
                then counts as duplicate
        Try a bit more balancing of stream lengths
            problem is I don't want to shift all existing streams if split e.g.
                apb
        Check that only one frequency per stream
        When include HighResMIP, check for equivalent 6hr diagnostics and
            ideally switch off

    Calling:
    Example calling:
    rose_stash_manipulate.py --stashmaster /data/users/hadom/branches/\
            vn10.4_merge_SIMIP_EasyAerosol_stashmaster/rose-meta/um-atmos/\
            HEAD/etc/stash/STASHmaster \
            /home/h06/hadom/roses/u-ag015/app/coupled/rose-app.conf > proc.out
    /home/h06/hadom/workspace/Rose/rose_stash_manipulate.py --stashmaster /data/users/hadom/branches/\
            vn10.6_easyaerosol_v2/rose-meta/um-atmos/\
            HEAD/etc/stash/STASHmaster \
            /home/h06/hadom/roses/u-ai098/app/um/rose-app.conf > proc.out

Shift timestep diagnostics from uph to upt
    Could switch them off (or remove completely) for now.


UPA = day mean
UPB = daily (meaned 6hrly or instantaneous)
UPC = 6 hourly instantaneous (or maximum)
UPD = day mean, max or min
UPE = day mean
UPF = day mean
UPG = monthly mean (6 hr sampling), some zonal means
UPH = timestep (currently) - move to UPT
UPI = empty
UPJ = 30 day instantaneous
UPK = DIURNAL (mean over month) - also 3hr mean precip - move

UPL = empty
UPT
UPU
UPV

UP1 = month mean
UP2 = month mean
UP3 = month mean (UKCA)

Need
1 hour - UP8
3 hour - UP7

For CMIP6 diagnostics via spreadsheet (or otherwise)
CMOR name to Stash mapping needed
Frequency to time profile
Dimensions (longitude latitude zlevel(s) time) to domain - main challenge is
the plev/model level names

Check that same stash code does not go to same stream more than once - this is
    annoying
Need to make sure a heaviside is available in every stream that a pressure
    level field is produced
Could check if diagnostics are going into each (updating) stream - and if not
    switch that stream off, so don't produce empty files
"""
import argparse
import copy
import os
import re
from shutil import move
import StringIO
import sys

import hashlib
import openpyxl
import subprocess

import process_spreadsheet

rose_lib = '/home/h03/fcm/rose/lib/python/'
latest_umversion = '10.6'
rose_meta_lib = ('/home/h03/fcm/rose-meta/um-atmos/vn' +
                 latest_umversion + '/lib/python/')
sys.path.append(rose_lib)
sys.path.append(rose_meta_lib)
import rose.config
import rose.macro
import widget.stash_parse


# Create an xml file containing the details of a stash list
# from a rose-app.conf file.
# Duplicates from GA7 - currently remove by hand:
# 24, TDAYM, UPJ
# 3332, TDAYM, UPJ
# 3236, TDAYMIN, UPJ
# 3236, TDAYM, UPJ
# 3236, TDAYMAX, UPJ
# 5216, TDAYM, UPJ
stash1 = {'stash': 24, 'tim_name': 'TDAYM', 'use_name': 'UPJ',
          'dom_name': 'DIAG'}
stash2 = {'stash': 3332, 'tim_name': 'TDAYM', 'use_name': 'UPJ',
          'dom_name': 'DIAG'}
stash3 = {'stash': 3236, 'tim_name': 'TDAY', 'use_name': 'UPJ',
          'dom_name': 'DIAG'}
stash4 = {'stash': 3236, 'tim_name': 'TDAYMIN', 'use_name': 'UPJ',
          'dom_name': 'DIAG'}
stash5 = {'stash': 3236, 'tim_name': 'TDAYMAX', 'use_name': 'UPJ',
          'dom_name': 'DIAG'}
stash6 = {'stash': 5216, 'tim_name': 'TDAYM', 'use_name': 'UPJ',
          'dom_name': 'DIAG'}
duplicates = [stash1, stash2, stash3, stash4, stash5, stash6]


#CMIP6_DATA_REQUEST = ('/data/users/jseddon/rose_suite_populate/'
#                      'PRIMAVERA_MS21_DRQ_0-beta-32_090916c_MR.xlsx')
#CMIP6_DATA_REQUEST = ('/data/users/hadom/cmip6/data_request/'
#                      'PRIMAVERA_MS21_DRQ_0-beta-37.1.xlsx')
CMIP6_DATA_REQUEST_URL = 'svn://fcm9/utils_svn/MalcolmRoberts/trunk/python/Rose/PRIMAVERA_MS21_DRQ_0-beta-37.5.xlsx'
CMIP6_DATA_REQUEST_REVISION = 16390
CMIP6_DATA_REQUEST = '/data/users/hadom/cmip6/data_request/PRIMAVERA_MS21_DRQ.xlsx'

cmd = 'fcm export --force '+CMIP6_DATA_REQUEST_URL+'@'+str(CMIP6_DATA_REQUEST_REVISION)+ ' '+CMIP6_DATA_REQUEST
sts_proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,stderr=subprocess.PIPE)
sts_out, sts_err = sts_proc.communicate()
print cmd
print sts_out

CMIP6_CMOR_STASH_CONVERSION = '/home/h06/hadom/python/cmip6_mappings.cfg'
# Reference streq template
TEMPLATE_FILE = '/home/h06/hadom/roses/reference/streq_template_10p6.conf'
HIGHRESMIP_FILE = '/home/h06/hadom/roses/reference/highresmip_profiles.conf'

rose_meta_lib = "~fcm/rose-meta/um-atmos/vn{umver}/lib/python"
stashmaster_default_path = "~frum/vn{umver}/ctldata/STASHmaster/"

STASH_SECTION_BASES = ['namelist:domain',
                       'namelist:streq', 'namelist:time',
                       'namelist:use']
STASH_STREQ = ['namelist:streq']
STASH_SECTION_BASES_NO_INCLUDE_OPTS_MAP = {'namelist:domain': ['dom_name'],
                                           'namelist:time': ['tim_name'],
                                           'namelist:use': ['use_name'],
                                           'namelist:items': ['ancilfilename']}
SECTION_FORMAT = '{0}({1}_{2})'


class Profile(object):
    """Base object for Stash profiles."""

    def __init__(self, properties):
        """ properties is a rose.config.ConfigNode object"""
        self.attributes = {}
        self.output_info = {}
        for key, node in properties.walk():
            self.attributes[key[1]] = node.get_value().strip(" '")

    def process(self):
        """
        This is a stub for the process method, it will be over-written
        in the subclass. All we are doing here is taking a copy of the
        raw namelist entries.
        """
        self.output_info = self.attributes.copy()

    def __repr__(self):
        if not self.output_info:
            self.process()
        return "".join("%s : %s\n" % (key, value) for key, value in
                       self.output_info.iteritems())

    def iterate(self):
        """
        This iterate method will iterate over the output information if
        it has been populated. Otherwise it will default to the raw namelist
        entries.
        """
        if self.output_info:
            return self.output_info.iteritems()
        else:
            return self.attributes.iteritems()


def stream_conv(usage):
    """
    Convert the USAGE profile names to stream names. Presumably there
    is a more robust way of doing this compared to "just change the first two
    letters"?
    """
    if usage.startswith('UP') and len(usage) == 3:
        return "AP"+usage[-1]
    elif usage == "UPMEAN":
        return "APM"
    else:
        return usage


class Streq(Profile):
    """
    Stash request class. Describes the actual output diagnostic. It combines
    the diagnostic stash number with the domain, time, and usage profiles.
    """
    def __init__(self, properties):
        """
        Force the addition of the stash variable name, otherwise leave the
        namelist information untouched for potential raw output.
        """
        super(Streq, self).__init__(properties)
        # I'm abusing the globalness of python here when using stash_lookup.
        try:
            self.attributes['name'] = stash_lookup[self.attributes['isec']]\
                [self.attributes['item']]['name']
        except KeyError:
            self.attributes['name'] = ("".join([self.attributes['isec'],
                                                self.attributes['item']]))

    def process(self):
        conversion = {'isec': 'section-number',
                      'item': 'item-number',
                      'dom_name': 'domain-profile',
                      'tim_name': 'time-profile',
                      'use_name': 'usage-profile',
                      'package': 'package'}
        for key, value in self.attributes.iteritems():
            if key in conversion:
                self.output_info[conversion[key]] = value
            else:
                self.output_info[key] = value
        self.output_info['stash-num'] = (self.attributes['isec'].zfill(2) +
                                         self.attributes['item'].zfill(3))
        self.output_info['stream'] = stream_conv(self.attributes['use_name'])
        self.output_info['name'] = self.attributes['name']


class Domain(Profile):
    """
    Domain class. Describes the spatial domain on which the diagnostic is
    output.
    """
    def process(self):
        level_type_codes = {'1': 'Model rho levels',
                            '2': 'Model theta levels',
                            '3': 'Pressure levels',
                            '4': 'Geometric height levels',
                            '5': 'Single level',
                            '6': 'Deep soil levels',
                            '7': 'Potential temperature levels',
                            '8': 'Potential vorticity levels',
                            '9': 'Cloud threshold levels'}
        pseudo_level_codes = {'0': 'None',
                              '1': 'SW radiation bands',
                              '2': 'LW radiation bands',
                              '3': 'Atmospheric assimilation groups',
                              '8': 'HadCM2 Sulphate Loading Pattern Index',
                              '9': 'Land and Vegetation Surface Types',
                              '10': 'Sea ice categories',
                              '11': ('Number of land surface tiles x maximum '
                                     'number of snow layers'),
                              '12': ('COSP pseudo level categories for '
                                     'satellite observation simulator project'),
                              '13': ('COSP pseudo level categories for '
                                     'satellite observation simulator project'),
                              '14': ('COSP pseudo level categories for '
                                     'satellite observation simulator project'),
                              '15': ('COSP pseudo level categories for '
                                     'satellite observation simulator project'),
                              '16': ('COSP pseudo level categories for '
                                     'satellite observation simulator project')}
        horiz_dom_codes = {'1': 'Global',
                           '2': 'N hemisphere',
                           '3': 'S hemisphere',
                           '4': '30-90 N',
                           '5': '30-90 S',
                           '6': '0-30 N',
                           '7': '0-30 S',
                           '8': '30S-30N',
                           '9': 'Area specified in degrees',
                           '10': 'Area specified in gridpoints'}
        gridpoint_codes = {'1': 'All points',
                           '2': 'Land points',
                           '3': 'Sea points',
                           '': 'Unknown'}
        spatial_mean_codes = {'0': 'None',
                              '1': 'Vertical',
                              '2': 'Zonal',
                              '3': 'Meridional',
                              '4': 'Horizontal area',
                              '': 'Unknown'}
        weighting_codes = {'0': 'None',
                           '1': 'Horizontal',
                           '2': 'Volume',
                           '3': 'Mass',
                           '': 'Unknown'}

        self.output_info['dom_name'] = self.attributes['dom_name']
        self.output_info['level-types'] = level_type_codes[
            self.attributes['iopl']]

        if self.attributes['iopl'] in '1 2 6':
            if self.attributes['ilevs'] == "1":
                self.output_info['level-list'] = ('Contiguous range. From '
                                                  '{levb} to {levt}.'.
                                                  format(**self.attributes))
            elif self.attributes['ilevs'] == '2':
                self.output_info['level-list'] = ('List: {levlst}'.
                                                  format(**self.attributes))
        elif self.attributes['iopl'] == '3':
            self.output_info['level-list'] = self.attributes['rlevlst']
        elif self.attributes['plt'] in '1 2 3 8 9 10 11 12 13 14 15 16'.split():
            self.output_info['level-list'] = ('{a} : {pslist}'.
                format(a=pseudo_level_codes[self.attributes['plt']],
                       **self.attributes))

        if self.attributes['iopa'] in '1 2 3 4 5 6 7 8'.split():
            self.output_info['domain-type'] = horiz_dom_codes[
                self.attributes['iopa']]
        elif self.attributes['iopa'] == '9':
            self.output_info['domain-type'] = ('{a}: {inth} N, {isth} S, {iwst}'
                                               ' W, {iest} E'.format(
                a=horiz_dom_codes[self.attributes['iopa']], **self.attributes))

        self.output_info['gridpoints'] = gridpoint_codes[
            self.attributes['imsk']]
        self.output_info['spatial-meaning'] = spatial_mean_codes[
            self.attributes['imn']]
        self.output_info['weighting'] = weighting_codes[self.attributes['iwt']]

        if self.attributes['ts'] == 'Y':
            top = (self.attributes['ttlim']
                   if 'ttlim' in self.attributes
                   else self.attributes['ttlimr'])
            bot = (self.attributes['tblim']
                   if 'tblim' in self.attributes
                   else self.attributes['tblimr'])
            self.output_info['time-series domains'] = ('{tsnum} time series '
                'domains. Horizontal limits: {tnlim} N, {tslim} S, {telim} E, '
                '{twlim} W. Vertical limits {b} - {t}'.
                format(b=bot, t=top, **self.attributes))


class Time(Profile):
    """ Time class. Describes the temporal process of the diagnostic output. """

    def process(self):
        time_processing_codes = {'0': ('Not required by STASH, but space '
                                       'required.'),
                                 '1': 'Replace',
                                 '2': 'Accumulate',
                                 '3': 'Time mean.',
                                 '4': 'Append time-series',
                                 '5': 'Maximum',
                                 '6': 'Minimum',
                                 '7': 'Trajectories'}
        unit_conv = {'DA': 'days',
                     'H': 'hours',
                     'DU': 'dump periods',
                     'T': 'timesteps',
                     '3': 'days',
                     '2': 'hours',
                     '4': 'dump periods',
                     '1': 'timesteps'}

        self.output_info['tim_name'] = self.attributes['tim_name']
        self.output_info['time-processing'] = time_processing_codes[
            self.attributes['ityp']]
        if 'intv' in self.attributes:
            value = ('all' if self.attributes['intv'] == '-1'
                     else self.attributes['intv'])
            self.output_info['processing-period'] = ('{} {}'.
                format(value, unit_conv[self.attributes['unt1']]))
            self.output_info['processing-start'] = ('{ioff} {a}'.
                format(a=unit_conv[self.attributes['unt1']], **self.attributes))
        if self.attributes['ityp'] in [str(x) for x in range(2, 8)]:
            self.output_info['sampling-frequency'] = ('{isam} {a}'.
                format(a=unit_conv[self.attributes['unt2']], **self.attributes))
        if self.attributes['iopt'] == '1':
            self.output_info['output-times'] = (
                'Regular output times. Start: {istr}. End: {iend}. Frequency: '
                '{ifre}. Units: {a}'.
                format(a=unit_conv[self.attributes['unt3']], **self.attributes))
        elif self.attributes['iopt'] == '2':
            self.output_info['output-times'] = ('List of times ({u}): {iser}'.
                format(u=unit_conv[self.attributes['unt3']], **self.attributes))
        elif self.attributes['iopt'] == '3':
            self.output_info['output-times'] = ('Date range. From {isdt} to '
                '{iedt}'.format(**self.attributes))


class Use(Profile):
    """Usage class. Describes where the diagnostic is output to."""

    def process(self):
        output_dest_codes = {'1': 'Dump store with user specified tag',
                             '2': 'Dump store with climate mean tag',
                             '3': 'Fieldsfile',
                             '5': 'Mean diagnostic direct to mean fieldsfile',
                             '6': 'Secondary dump store with user tag'}
        self.output_info['output-destination'] = output_dest_codes[
            self.attributes['locn']]
        if self.attributes['locn'] in '1 2 6':
            if float(umversion) < 9.2:
                self.output_info['output-tag'] = self.attributes['iunt']
            else:
                self.output_info['output-tag'] = self.attributes['macrotag']


def assign_profile(name, properties):
    """This is a factory function for creating the correct profile class"""
    profile_dict = {'time': Time, 'streq': Streq, 'domain': Domain, 'use': Use}
    return profile_dict[name](properties)


def package_duplicates(config, key):
    """
    From the duplicates list of dictionaries above, pick these variables out
    and give them a package switch
    """
    for dup in duplicates:
        if ((config.value[key[0]].value['use_name'].value ==
                         "'"+dup['use_name']+"'") and
                (config.value[key[0]].value['dom_name'].value ==
                             "'"+dup['dom_name']+"'") and
                (config.value[key[0]].value['tim_name'].value ==
                             "'"+dup['tim_name']+"'")):
            config.value[key[0]].value['package'].value = "'DUPLICATE'"


def process_config_file_stashmean(config):
    """process config file to convert from climate meaning to stash meaning"""
    for key, data in config.walk():
        section = key[0]
        if len(key) == 1:
            retxt = re.search(r"namelist:(?P<name>\w+)\((?P<num>[0-9_a-zA-Z]+)", key[0])
            # pick out parts of config that are stash-related
            print 'section ', section
            for section_base in STASH_SECTION_BASES:
                if (section.startswith(section_base) and
                            'domain_nml' not in section):
                    nl = retxt.group('name')
                    print 'nl ', nl
                    profile = assign_profile(nl, data)
                    for profile_key, profile_value in profile.iterate():
                        if profile_key == 'name':
                            stashname = profile_value

                    if nl == 'streq':
                        # comment out duplicate requests
                        package_duplicates(config, key)
                        # if dump mean profile, change to STASH meaning
                        if 'TDMPMN' in config.value[key[0]].value['tim_name'].value:
                            if config.value[key[0]].value['use_name'].value == "'UPMEAN'":
                                config.value[key[0]].value['tim_name'].value = "'TMONMN'"
                                if 'UKCA' in config.value[key[0]].value['package'].value or \
                                'EASYA' in config.value[key[0]].value['package'].value:
                                    config.value[key[0]].value['use_name'].value = "'UP3'"
                                else:
                                    if (config.value[key[0]].value['isec'].value == '30'
                                            or 'Dust' in stashname):
                                        config.value[key[0]].value['use_name'].value = "'UP2'"
                                    else:
                                        config.value[key[0]].value['use_name'].value = "'UP1'"

                        # now deal with COSP diagnostics - use hourly data on
                        # radiation timesteps
                        if 'T6HDMPM' in config.value[key[0]].value['tim_name'].value:
                            if config.value[key[0]].value['use_name'].value == "'UPMEAN'":
                                config.value[key[0]].value['tim_name'].value = "'T6HMONM'"
                                if ((config.value[key[0]].value['isec'].value == '30')
                                        or ('Dust' in stashname)):
                                    config.value[key[0]].value['use_name'].value = "'UP2'"
                                else:
                                    config.value[key[0]].value['use_name'].value = "'UP1'"

                        # now deal with diurnal cycle diagnostics
                        if 'TMPMN' in config.value[key[0]].value['tim_name'].value:
                            config.value[key[0]].value['package'].value = "'DIURNAL'"
                            period = config.value[key[0]].value['tim_name'].value[-3:-1]
                            config.value[key[0]].value['tim_name'].value = "'TMONMN" + period + "'"
                            config.value[key[0]].value['use_name'].value = "'UPK'"

                        # now deal with COSP diagnostics - use hourly data on radiation timesteps
                        if 'TRADDM' in config.value[key[0]].value['tim_name'].value:
                            if config.value[key[0]].value['use_name'].value == "'UPMEAN'":
                                config.value[key[0]].value['tim_name'].value = "'TRADMONM'"
                                config.value[key[0]].value['use_name'].value = "'UP1'"

                        # change 90 day instantaneous to 30 day
                        if 'T90DAY' in config.value[key[0]].value['tim_name'].value:
                            config.value[key[0]].value['tim_name'].value = "'T30DAY'"
                            config.value[key[0]].value['use_name'].value = "'UPU'"

                        # change 90 day instantaneous to 30 day
                        if 'TSTEPGI' in config.value[key[0]].value['tim_name'].value:
                            config.value[key[0]].value['use_name'].value = "'UPT'"
                            config.value[key[0]].value['package'].value = "'TSTEP_STD_GA7'"

                        # set all blank package switches to a standard value
                        if config.value[key[0]].value['package'].value == "''":
                            config.value[key[0]].value['package'].value = "'STD_GA7'"
    # TODO: Consider changing the frequency of reinitialisation of the files in automated way


def merge_configs(target, donor):
    """
    Add the 'namelist' level config nodes from a donor config node object
    to the target one.
    """
    messages = []
    for node_key, node in donor.walk(no_ignore=False):
        if not isinstance(node.value, dict):
            continue

        messages.append((node_key[0], None, None,
                        '{0:s} will be added.'.format(node_key[0])))
        target.set(keys=node_key, value=node.value,
                   state=node.state, comments=node.comments)

    return messages, target


def dump_section(config, section, no_include_opts=None):
    """Return some option=value text used for checksums."""
    new_config = rose.config.ConfigNode()
    if no_include_opts is None:
        no_include_opts = []

    for keylist, opt_node in config.walk([section]):
        option = keylist[1]
        if option in no_include_opts:
            continue
        new_config.value[option] = opt_node

    config_string_file = StringIO.StringIO()
    rose.config.dump(new_config, config_string_file)
    config_string_file.seek(0)
    return config_string_file.read()


def get_index_from_section(section):
    """Return the index string from an indexed section name."""
    return section.rsplit("(", 1)[1].rstrip(")")


def get_new_indices(config, section_base_name, no_include_opts=None):
    """Return a list of errors, if any."""
    if no_include_opts is None:
        no_include_opts = []
    keys = config.value.keys()
    keys.sort(rose.config.sort_settings)
    for section in keys:
        if not section.startswith(section_base_name + "("):
            continue
        print 'text input ', section, no_include_opts
        text = dump_section(config, section, no_include_opts)
        old_index = get_index_from_section(section)
        new_index = hashlib.sha1(text).hexdigest()[:8]
        if old_index != new_index:
            yield (old_index, new_index)


def get_section_new_indices(config):
    """Get newly calculated indices for the config."""
    for section_base in STASH_SECTION_BASES:
        no_include_opts = STASH_SECTION_BASES_NO_INCLUDE_OPTS_MAP.get(
                                                    section_base, [])
        for old_index, new_index in get_new_indices(config, section_base,
                                                    no_include_opts):
            yield section_base, old_index, new_index


def put_stash_into_config(config, stash_code):
    """insert a stash code into a config object"""
    key = config.value.keys()
    # set the values from the stash_list dictionary into this config node
    print stash_code
    print stash_code['dom_name'], stash_code['tim_name'], stash_code['use_name'], stash_code['section'],\
        stash_code['item'], stash_code['cmor']
    for profile in ['tim_name', 'use_name', 'dom_name', 'package']:
        config.value[key[0]].value[profile].value = str("'" +
                                                        stash_code[profile] +
                                                            "'")
    config.value[key[0]].value['item'].value = str(int(stash_code['item']))
    config.value[key[0]].value['isec'].value = str(int(stash_code['section']))

    make_unique_index(config, stash_code)


def make_unique_index(config, stash_code):
    """creates a new key value for this node"""
    for data in get_section_new_indices(config):
        section_base, old_index, new_index = data
        key = config.value.keys()
        isec_item = stash_code['section']+stash_code['item']
        old_index_sections = old_index.split('_')
        old_section = SECTION_FORMAT.format(section_base, old_index_sections[0], old_index_sections[1])
        new_section = SECTION_FORMAT.format(section_base, isec_item, new_index)
        print 'old_section, new', old_section, new_section

        old_node = config.unset([old_section])
        old_id_opt_values = []
        for opt, node in old_node.value.items():
            old_id = rose.CONFIG_DELIMITER.join([old_section, opt])
            old_id_opt_values.append((old_id, opt, node.value))
        # update key value
        config.value.update({new_section: old_node})


def work(args, stash_lookup):
    """
    Read the config file
    Process the config file to:
        convert from climate means to STASH means
        add a package label to every diagnostic
    """
    # read the input rose config file, and write it again to keep the original
    config = rose.config.load(args.input)
    rose.config.dump(config, args.input + '.default')

    # process config file to convert from climate meaning to stash meaning
    process_config_file_stashmean(config)

    conf_out = args.input + '.process_config'
    rose.config.dump(config, conf_out)

    config_profiles = rose.config.load(HIGHRESMIP_FILE)

    messages, upd_config = merge_configs(config, config_profiles)
    rose.config.dump(upd_config, conf_out + '_newprofiles')

    # now load up a reference streq template, and loop over all the new
    # diagnostics, filling in the information as requred

    # read in new diagnostics
    infile = args.datarequest
    outdir = os.path.dirname(args.input)
    cmor_stash_file = (args.cmorstashfile)
    print 'cmor stash file ', cmor_stash_file
    hrmip = openpyxl.load_workbook(infile, use_iterators=True)
    stash_dictionary = process_spreadsheet.work(hrmip, stash_lookup,
                                                  outdir, cmor_stash_file)

    for stash_item in stash_dictionary:
        print 'dictionary ', stash_item
        # read in config template namelist
        config_template = rose.config.load(TEMPLATE_FILE)
        config_tmp = copy.copy(config_template)
        print 'config_tmp old \n', config_tmp

        section_lookup = str(int(stash_dictionary[stash_item]['section']))
        item_lookup = str(int(stash_dictionary[stash_item]['item']))
        section_item = section_lookup + item_lookup
        print 'stashcode ', section_item
        if (section_item == '' or
                    stash_dictionary[stash_item]['stash'][0] != 'm'):
            raise Exception('Not a stash code ' +
                            stash_dictionary[stash_item]['stash'])
        try:
            stashname = stash_lookup[section_lookup][item_lookup]['name']
        except:
            print ('this stashcode does not translate in '
                   'rose_stash {}'.format(section_item))
            continue

        print 'section_lookup ', section_lookup, section_item,\
            stash_dictionary[stash_item]['stash']

        put_stash_into_config(config_tmp, stash_dictionary[stash_item])

        # merge this new node into the full confignode object
        messages, upd_config = merge_configs(upd_config, config_tmp)

    rose.config.dump(upd_config, conf_out + 'added_stash')
    move(conf_out + 'added_stash', args.input)
    os.remove(conf_out + '_newprofiles')
    os.remove(conf_out)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description=("Populate a Rose suite's rose-app.conf file with the "
                     "variable request from the PRIMAVERA project's request"
                     "spreadsheet. Additional files describing the variables"
                     "are also output."))

    parser.add_argument('input', type=str, help='Input path for suite '
                                                'rose-app.conf file')
    parser.add_argument('--um_version', '-u', type=str,
                        help='UM version, in X.Y format.')
    parser.add_argument('--stashmaster', '-m',
                        help=('Path to the stashmaster file. If not specified, '
                              'the default STASHmaster file, in '
                              '$UMDIR/vnX.Y/ctldata/STASHmaster/, '
                              'will be used.'))
    parser.add_argument('--datarequest', '-d', type=str,
                        default=CMIP6_DATA_REQUEST,
                        help='HighResMIP spreadsheet containing data request')
    parser.add_argument('--cmorstashfile', '-c', type=str,
                        default=CMIP6_CMOR_STASH_CONVERSION,
                        help='json file containing cmor-stash conversion')

    args = parser.parse_args()

    # if a STASHmaster_A file exists for this suite, then it may be overriding
    #  the default
    suite_dir = os.path.dirname(args.input)
    if os.path.exists(os.path.join(suite_dir, 'file', 'STASHmaster_A')) \
            and not args.stashmaster:
        raise Exception('Warning - a STASHmaster_A file exists in this suite -'
                        ' should you be using it instead of default?')

    # It might also be possible to get this from the rose-app.conf file.
    # However, I'm not sure if we can rely on it being in there.
    if args.um_version:
        umversion = args.um_version
    else:
        print ('Unable to determine UM version. This can be set with the '
               '--um-version argument, or by UMVERSION environment '
               'variable. Assuming the latest version {}'.
               format(latest_umversion))
        umversion = latest_umversion

    # Here we add the path to the Metadata library. This is released at each
    # UM version so to have the correct one, we need to wait until we've
    # processed the UM version argument.
    # This is required to determine the name of the stash item
    rose_meta_lib_path = os.path.expanduser(rose_meta_lib.
                                            format(umver=umversion))
    if not os.path.isdir(rose_meta_lib_path):
        print ('The rose metadata library is not available at UM version %s'.
               format(umversion))
        rose_meta_lib_path = os.path.expanduser('~fcm/rose-meta/um-atmos/HEAD/'
                                                'lib/python')
        print 'Using the HEAD version: %s'.format(rose_meta_lib_path)
    sys.path.append(rose_meta_lib_path)

    if args.stashmaster:
        stashmaster_path = args.stashmaster
        print 'use input stashmaster ', args.stashmaster
    else:
        stashmaster_path = os.path.expanduser(stashmaster_default_path.
                                              format(umver=umversion))
    stash_parser = widget.stash_parse.StashMasterParserv1(stashmaster_path)
    stash_lookup = stash_parser.get_lookup_dict()

    print args

    work(args, stash_lookup)
