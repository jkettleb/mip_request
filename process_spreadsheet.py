#!/usr/bin/env python2.7
"""
Read in the spreadsheet of variables for HighResMIP
    For each sheet
        for each row
            identify stash value(s) first - since there could be more than 1,
                and need to use the
                same time/domain profile for all stash on this row
            identify corresponding time profile
            figure out which domain is appropriate
                is it multiple levels?
                is it pressure levels
                    if so, which pressure level set
                is it model levels?
                is it zonal mean?
            figure out which stream is appropriate - from the time frequency
                this won't work with the aero sheet
            produce a rose streq block appropriate for this stash request
Issues and exceptions
    Unique cmor to stash mapping - yes (maybe) apart from when a variable can
    be defined on model levels or pressure levels (e.g. ua), in which case
    stash changes
        Can catch this by using
    Unique mokey to stash mapping - yes, apart from pressure level
    instantaneous (no heaviside needed) vs time mean (heaviside needed)
"""
import ConfigParser
import copy
import json
import re

POSSIBLE_FREQ = ['mon', 'day', '6hr', '3hr', '1hr', 'subhr']

USAGE = {'amon': 'UP4',
         'limon': 'UP4',
         'mon': 'UP5',
         'cfmon': 'UP5',
         'monz': 'UPV',
         'day': 'UP6',
         '6hr': 'UP7',
         '3hr': 'UP8',
         '1hr': 'UP9',
         'subhr': 'UPT'}

sheets_to_skip = ['Oclim', 'fx']
latest_umversion = '10.4'


def clean_dims(dimension_name):
    """given a string dimension name remove the string "lev" and any numbers"""
    tmp = re.sub('lev[0-9s]*.?', '', dimension_name)
    if re.match(r'p\d', tmp):
        tmp = 'p'
    return tmp


def process_range(value_processor, cell_range):
    """
    apply processor to cell_range supplied returning a list of processed values
    """
    results = []
    for cell in cell_range:
        results.append(value_processor(cell[0].value))
    return results


def dimension_processor(value):
    """
    turn the dimension specification into a simple key;
    the first two characters of each dimension joined by dashes
    (once each dimension name has been through clean_dims)
    e.g. "latitude longitude plev7 time1" will become "la-lo-p-ti"
    """
    tmp = [clean_dims(i) for i in value.split()]
    mykey = "-".join([i[:2] for i in tmp])
    if mykey == '':
        mykey = 'none'
    return mykey


def dim_processor(value):
    """return the dimensions"""
    try:
        tmp = value.split()
        mykey = '-'.join([i for i in tmp])
        if mykey == '':
            mykey = 'none'
    except:
        mykey = 'none'

    return str(mykey)


def cell_method_processor(value):
    """
    create a key from the cell_methods (time processing); replace ": " with ":"
    and whitespace with "-"
    """
    if value is None:
        return 'None'
    tmp = value.replace(": ", ":").replace(" ", "-")
    return tmp


def time_processor(value):
    """create a key from the frequency cell"""
    if value is None:
        return 'None'
    return value


def unique_processor(value):
    """
    create a key from the cell_methods; replace ": " with ":" and whitespace
    with "-"
    """
    if value is None:
        return 'None'
    return value


def priority_processor(value):
    """return priority of diagnostic"""
    if value is None:
        return "None"
    return str(value)


def metoffice_processor(value):
    """return whether Met Office will produce this diagnostic"""
    if value is None or value == '':
        return "None"
    return str(value)


def derive_variable_priority(ws, cmip6_priority_col, mo_priority_col, max_row):
    """
    derive the priority of variables in sheet by comparing cmip6 and Met Office
    priorities
    """
    # CMIP6 priority key
    cmip6_priority_key = process_range(priority_processor, ws[
        cmip6_priority_col + "2:" + cmip6_priority_col + "%i" % max_row])
    # Met Office producing key
    mo_priority_key = process_range(metoffice_processor, ws[
        mo_priority_col + "2:" + mo_priority_col + "%i" % max_row])

    # jseddon: the next lines could be replaced by a set, but this changes some
    # of the output from the software and so it has been left as it is.
    mo_unique_key = []
    [mo_unique_key.append(item) for item in mo_priority_key
     if item not in mo_unique_key]
    print 'mo_unique_priorities ', mo_unique_key

    priority_key = copy.copy(cmip6_priority_key)

    for ip, (cmip6_pr, mo_pr) in enumerate(
            zip(cmip6_priority_key, mo_priority_key)):
        if cmip6_pr == 'None' and mo_pr == 'None':
            priority_key[ip] = 'None'
        elif cmip6_pr == 'None' and mo_pr != 'None':
            priority_key[ip] = mo_pr
        elif cmip6_pr != 'None' and mo_pr == 'None':
            priority_key[ip] = 'HRMIP_'+cmip6_pr[:1]
        elif mo_pr == 'UM:1':
            priority_key[ip] = 'MO_PR1'
        elif mo_pr == 'UM:2':
            priority_key[ip] = 'MO_PR2'
        elif mo_pr == 'NEMO:1':
            priority_key[ip] = 'MO_NEMO1'
        elif mo_pr == 'CICE:1':
            priority_key[ip] = 'MO_CICE1'
        elif mo_pr == 'JULES:1':
            priority_key[ip] = 'MO_JULES1'
        elif mo_pr == 'CICE:1 & JULES:1':
            priority_key[ip] = 'MO_JULCIC1'
        elif mo_pr == 'LIMITED':
            priority_key[ip] = 'PRIM_LTD'
        elif mo_pr == 'False':
            priority_key[ip] = 'MO_NO_CMIP_'+cmip6_pr
        elif mo_pr == 'CHECK':
            priority_key[ip] = 'MO_CHECK'
        elif 'check' in mo_pr:
            priority_key[ip] = 'MO_RECHECK'
        elif mo_pr == 'ANCIL':
            priority_key[ip] = 'FROM_ANCIL'
        else:
            try:
                if int(cmip6_pr) < int(mo_pr):
                    priority_key[ip] = '1_CMIP_OVER_MO'
                elif int(mo_pr) < int(cmip6_pr):
                    priority_key[ip] = '1_MO_OVER_CMIP'
            except:
                print ('value of  cmip6_pr or mo_pr cannot convert to '
                       'integer  {} {}'.format(cmip6_pr, mo_pr))

    print 'cmip6_priority ', cmip6_priority_key
    print 'mo_priority ', mo_priority_key
    print 'priority ', priority_key
    return priority_key


def check_stash(value):
    """
    return the msi code as a string if it is a STASH code, the strings 'None'
    or 'unknown' otherwise.
    """
    if value is None:
        return 'None'
    elif value[0] != 'm':
        return 'unknown'
    else:
        return str(value)


def derive_time_usage_profile(sheet_period, time_period, cell_method, dbg=True):
    """
    Derive time domain and usage domain for STASH
    Also time component of lbproc

    A monthly frequency with cell_methods point has a time profile and lbproc=0
    >>> derive_time_usage_profile('mon', ['mon'], ['time: point'], dbg=False)
    [('TMON', 'UP5', 0)]

    But a monthly frequency with a time mean will go to the same usage but
    has a different time profile and lbproc.
    >>> derive_time_usage_profile('mon', ['mon'], ['time: mean'], dbg=False)
    [('TMONMN', 'UP5', 128)]

    Similarly for time mins and maxs
    >>> derive_time_usage_profile('mon', ['mon'], ['time: maximum'], dbg=False)
    [('TMONMAX', 'UP5', 8192)]
  
    >>> derive_time_usage_profile('mon', ['mon'], ['time: minimum'], dbg=False)
    [('TMONMIN', 'UP5', 4096)]

    Other tables and frequencies result in different time and usage profiles
    >>> derive_time_usage_profile('day', ['day'], ['time: point'], dbg=False)
    [('TDAY', 'UP6', 0)]

    But if the frequency is not recognised then the usage profile is set as
    'UNKNOWN'
    >>> derive_time_usage_profile('daily', ['daily'], ['time: point'], dbg=False)
    [('TDAILY', 'UNKNOWN', 0)]

    If cell_methods is empty then the time profile cannot be inferred
    so is set as 'unknown'
    >>> derive_time_usage_profile('mon', ['mon'], [''], dbg=False)
    [('unknown', 'UP5', 0)]

    Or cell_methods can have no time or area
    >>> derive_time_usage_profile('mon', ['mon'], ['longitude:mean'], dbg=False)
    [('unknown', 'UP5', 0)]

    """
    if len(time_period) != len(cell_method):
        raise Exception('Length of time periods and cell methods not the same')

    lbproc = 0
    profile = []
    for period, method in zip(time_period, cell_method):
        if period in POSSIBLE_FREQ:
            if period.lower() in sheet_period.lower():
                try:
                    usage_profile = USAGE[sheet_period.lower()]
                except:
                    usage_profile = USAGE[period]
        else:
            usage_profile = 'UNKNOWN'
        try:
            method_proc = method.split(':')[0]
            method_time = method.split(':')[1]
            if dbg:
                print 'method ', method, ', 1 ', method_proc, ', 2 ', method_time
            if 'time' in method_proc:
                if 'mean' in method_time:
                    tprof = 'T' + period.upper() + 'MN'
                    lbproc = 128
                elif 'point' in method_time:
                    tprof = 'T' + period.upper()
                    lbproc = 0
                elif 'minimum' in method_time:
                    tprof = 'T' + period.upper() + 'MIN'
                    lbproc = 4096
                elif 'maximum' in method_time:
                    tprof = 'T' + period.upper() + 'MAX'
                    lbproc = 8192
            elif 'area' in method_proc:
                if 'point' in method:
                    tprof = 'T' + period.upper()
                    lbproc = 0
                elif 'mean' in method:   #TODO: check if this is correct
                    tprof = 'T' + period.upper() + 'MN'
                    lbproc = 128
            else:
                tprof = 'unknown'
                if dbg:
                    print 'time unknown ', method, method_proc, method_time
        except:
            tprof = 'unknown'
        profile.append((tprof, usage_profile, lbproc))

    return profile


def derive_domain_profile(dims):
    """
    Need to derive the appropriate domain name from the dimensions of this
    variable. There could be a finite number - just match all or try to be more
    clever
    CALIPSO - uses p840, p560, p220

    Examples
    --------

    A simple surface field has a DIAG domain profile
    >>> derive_domain_profile(['longitude-latitude-time'])
    (['DIAG'], [0])

    Requested diagnostics on pressure levels return an appropriate
    pressure level domain:
    >>> derive_domain_profile(['longitude-latitude-plev19-time'])
    (['PLEV19'], [0])

    Zonal means are supported, and update the lbproc
    >>> derive_domain_profile(['latitude-plev19-time'])
    (['PLEV19Z'], [64])

    An 'UNKNOWN' domain profile is returned when the input domain
    contains an unrecognised level type:
    >>> derive_domain_profile(['longitude-latitude-theta320-time'])
    (['UNKNOWN'], [0])

    An 'UNKNOWN' is also returned when the domain is not lat-lon or
    zonal mean
    >>> derive_domain_profile(['time'])
    (['UNKNOWN'], [0])


    """
    dprof = copy.copy(dims)
    d_lbproc = copy.copy(dims)
    for index, domain in enumerate(dims):
        d_lbproc[index] = 0
        dim_values = domain.split('-')
        if 'longitude' in domain and 'latitude' in domain:
            # here we have a horizontal field
            if 'alevel' in domain:
                # this makes it either DALLTH or DALLRH, depending on
                # stash code
                dprof[index] = 'DALLTH'
            elif len(dim_values) == 2:
                dprof[index] = 'DIAG'
            elif len(dim_values) == 3 and 'time' in dim_values[2]:
                dprof[index] = 'DIAG'
            elif (len(dim_values) == 5 and
                  ('plev7c' in dim_values or 'plev7' in dim_values) and
                  'time' in dim_values[3] and
                  'tau' in dim_values[4]):
                # this is cosp 7x7
                dprof[index] = 'DCOSP7x7'
            elif 'alevhalf' in domain:
                dprof[index] = 'DALLRH'
            elif 'alev1' in domain:
                dprof[index] = 'DLEV1'
            elif 'plev' in domain and 'plev' in dim_values[2]:
                dprof[index] = dim_values[2].upper()
            elif 'p' in domain and dim_values[2][0] == 'p':
                # careful here, as CALIPSO diagnostics also use p
                if 'p100' in domain:
                    dprof[index] = 'D'+dim_values[2].upper()
            elif 'p' in domain and dim_values[3][0] == 'p':
                # careful here, as CALIPSO diagnostics also use p
                if 'p840' in domain or 'p560' in domain or 'p220' in domain:
                    dprof[index] = 'DIAG'
                else:
                    dprof[index] = 'D'+dim_values[3].upper()
            elif 'alt40' in domain:
                # this is also CALIPSO
                dprof[index] = 'DCOSP40'
            elif 'sza5' in domain:
                # this is also CALIPSO-PARASOL
                dprof[index] = 'DCOSP_5'
            elif 'sdepth1' in domain:
                dprof[index] = 'DSOIL1'
            elif 'sdepth' in domain:
                dprof[index] = 'DSOIL'
            elif 'height' in domain:
                if 'height2m' in dim_values[2] or 'height2m' in dim_values[3]:
                    # here we have a variable on a particular height, may well
                    # be within definition of variable
                    dprof[index] = 'DIAG'
                if 'height10m' in dim_values[2] or 'height10m' in dim_values[3]:
                    # here we have a variable on a particular height, may well
                    # be within definition of variable
                    dprof[index] = 'DIAG'
                if 'height50m' in dim_values[2] or 'height50m' in dim_values[3]:
                    # here we have a variable on a particular height, may well
                    # be within definition of variable
                    dprof[index] = 'DIAG'
                if ('height100m' in dim_values[2] or
                        'height100m' in dim_values[3]):
                    # here we have a variable on a particular height, may well
                    # be within definition of variable
                    dprof[index] = 'RLEVEL3'
            elif 'type' in domain:
                # this could be a vegetation/surface type, make DIAG
                dprof[index] = 'DIAG'
            else:
                dprof[index] = 'UNKNOWN'
        elif 'latitude' in domain and 'longitude' not in domain:
            # here we have a zonal mean
            if 'plev' in domain and 'plev' in dim_values[1]:
                dprof[index] = (dim_values[1]+'z').upper()
                d_lbproc[index] = 64
            else:
                dprof[index] = 'ZNMN_OF_SOME_KIND'
                d_lbproc[index] = 64
        else:
            dprof[index] = 'UNKNOWN'

    return dprof, d_lbproc


def write_stash_dictionary(stash_in, filename):
    """
    write to file each stash request as derived from spreadsheet

    stash_in - list of dictionary stash profiles
    filename - output filename
    """
    with open(filename, 'wb') as fout:
        fout.write('def stash requests() \n')
        for stash_profile in stash_in:
            print stash_profile
            print stash_in[stash_profile].items()
            line = str(stash_in[stash_profile].items())
            fout.write(line + '\n')


def write_stash_json(stash_in, filename):
    """
    write to file each stash request as derived from spreadsheet
    stash_in - list of dictionary stash profiles
    filename - output filename
    """
    json.dump(stash_in, open(filename, 'w'), indent=2)


def write_unique_keys_as_dictionary(dim_key_unique, filename):
    """
    write to file each unique profile defined by the CMIP6 data request
    dimension column (linked by -)

    dim_key_unique - list of all the unique dimensions
    """
    with open(filename, 'wb') as fout:
        fout.write('def unique_profile_keys() \n')
        key_list = []
        for idm, dim in enumerate(dim_key_unique):
            key_str = 'key'+str(idm)
            key_list.append(key_str)
            fout.write("    " + key_str + "={'cmip6_dim':'" + dim +
                       "', 'tim_name':'', 'use_name':'', 'dom_name':''}\n")
        fout.write("    unique_keys = ["+','.join(key_list)+"]"+"\n")
        fout.write("    return unique_keys"+"\n")


def write_cmor_stash_units_as_cfg(cmor_stash_map, cmor_units, filename):
    """
    Write a cfg file (used for cmorisation-lite) to link the cmor name and the
    stash name in blocks

    cmor_stash_map - dictionary of cmor names (as keys) and stash names as
        values
    cmor_units - dictionary of cmor variable name and units
    filename - name of output file to write to
    """
    with open(filename, 'wb') as fout:
        for dim in cmor_stash_map:
            if cmor_stash_map[dim] is not None:
                stash_list = cmor_stash_map[dim].split(',')
                if len(stash_list) == 1 or 's30i3' in stash_list[1]:
                    cmor_name = '[%s]' % dim
                    fout.write(cmor_name+'\n')
                    fout.write('constraint = stash' + '\n')
                    fout.write('positive = None' + '\n')
                    stash_name = 'stash = %s' % stash_list[0]
                    fout.write(stash_name + '\n')
                    if dim in cmor_units:
                        units_name = 'units = %s' % cmor_units[dim]
                        fout.write(units_name+'\n')
                    else:
                        units_name = 'units = %s' % 'None'
                        fout.write(units_name + '\n')

                    fout.write('\n')


def write_cmor_stash_mapping_as_cfg(cmor_stash_map, filename):
    """
    Write a cfg file (used for cmorisation-lite) to link the cmor name and the
    stash name in blocks

    cmor_stash_map - dictionary of cmor names (as keys) and stash names as
        values
    cmor_units - dictionary of cmor variable name and units
    filename - name of output file to write to
    """
    with open(filename, 'wb') as fout:
        for dim in cmor_stash_map:
            if cmor_stash_map[dim] is not None:
                stash_list = cmor_stash_map[dim]['stash'].split(',')
                num_stash_codes = len(stash_list)
                if num_stash_codes == 1 or "s30i3" in stash_list[1]:
                    cmor_name = '[%s]' % dim
                    fout.write(cmor_name + '\n')
                    if cmor_stash_map[dim]['lbproc'] != 0:
                        if num_stash_codes > 1:
                            fout.write('constraint = stash, lbproc, derived'
                                       + '\n')
                        else:
                            fout.write('constraint = stash, lbproc'+'\n')
                        proc_name = ('lbproc = {}'.
                                     format(cmor_stash_map[dim]['lbproc']))
                        fout.write(proc_name+'\n')
                    else:
                        fout.write('constraint = stash'+'\n')
                    fout.write('positive = None'+'\n')
                    stash_name = 'stash = %s' % cmor_stash_map[dim]['stash']
                    fout.write(stash_name+'\n')
                    units_name = 'units = %s' % cmor_stash_map[dim]['units']
                    fout.write(units_name + '\n')

                    fout.write('\n')


def process_stash_translation(section_ws, mokey_col_name, stash_col_name,
                              cmor_col_name, variable_col_name):
    """
    return dictionary, with
    mokey_stash = unique_keys as key and stash_list as value
    cmorkey_stash = cmor name as key and stash as item
    Check for duplicate keys, and if found then check items are the same
    section_ws - input sheets in workbook
    """
    mokey_stash = {}
    cmorkey_stash = {}
    for ws in section_ws:
        max_row = calc_max_occupied_rows(ws)
        sheet_period = ws.title
        # skip ocean/sea-ice diagnostics as they come from NEMO or CICE (hence
        # don't need STASH mapping)
        # aero is currently an issue - both before we figure out EasyAerosol,
        # and the time period is not defined (assume monthly mean?)
        if sheet_period[0:2] == 'em':
            sheet_period = sheet_period[2:]
        elif 'prim' in sheet_period:
            sheet_period = sheet_period[4:]

        print 'sheet period in ', sheet_period
        if sheet_period in sheets_to_skip:
            print 'skip sheet ', sheet_period
            continue

        for cell_id, cell_st, cell_cmor, cell_var in zip(
                ws[mokey_col_name + '2:' + mokey_col_name + '%i' % max_row],
                ws[stash_col_name + '2:' + stash_col_name + '%i' % max_row],
                ws[cmor_col_name + '2:' + cmor_col_name + '%i' % max_row],
                ws[variable_col_name + '2:' + variable_col_name +
                '%i' % max_row]):
            
            # met office key (dimension profile + cmor name)
            if cell_id[0].value not in mokey_stash.keys():
                mokey_stash[cell_id[0].value] = cell_st[0].value
            elif cell_id[0].value in mokey_stash.keys():
                if mokey_stash[cell_id[0].value] != cell_st[0].value:
                    print ('duplicate mokey but different item with different '
                           'stash {} {} {}'.format(cell_id[0].value,
                                           mokey_stash[cell_id[0].value],
                                           cell_st[0].value))

            # cmor name key and stash as item
            if cell_cmor[0].value not in cmorkey_stash.keys():
                cmorkey_stash[cell_cmor[0].value] = cell_st[0].value
            elif cell_cmor[0].value in cmorkey_stash.keys():
                if cmorkey_stash[cell_cmor[0].value] != cell_st[0].value:
                    print ('duplicate cmor with different stash  {} {} {}'.
                           format(cell_cmor[0].value,
                                  cmorkey_stash[cell_cmor[0].value],
                                  cell_st[0].value))
                    
            if cell_var[0].value != cell_cmor[0].value:
                if cell_var[0].value != None and cell_cmor[0].value != None:
                    if cell_var[0].value not in cell_cmor[0].value:
                        # may be that cmor name includes levels number
                        print ('cmor name and variable name disagree  {} {}'.
                               format(cell_cmor[0].value, cell_var[0].value))

    return mokey_stash, cmorkey_stash


def calc_max_occupied_rows(ws):
    """calculate the maximum number of occupied rows"""
    for row_number, row in enumerate(ws.iter_rows()):
        values = [cell.value for cell in row]
        if not any(values):
            print 'last row with data is {0}'.format(row_number)
            break
    return row_number


def check_stash_dependencies(din, stash_lookup):
    """
    Need to check internal consistency
    1. If diagnostic is COSP, need to use hourly meaning (on full radiation ts)
        not every timestep
    2. If diagnostics is instantaneous, do not need heaviside included (on
        package switch)
    3. If STASH name includes TILE, then make the domain DTILE
    4. If STASH name includes SOIL in section 8, then use DSOIL domain
    5. If stash on TEM levels, set domain to DP36CCM (seems to be fixed levels
        for this?)
    6. For stash 2217-2220, need DALLRHP1, radiation timesteps (hourly)
    7. For COSP diagnostics, add extra label
    8. May want to check for zonal means, and if so set lbproc
    9. If priority is LIMITED, set the domain to limited (D_EUROPE), but check
        for multiple levels
    10. If domain includes PLEV, check diagnostic in section 30 - if not then
        query
    11. If section is 30, then this is a pressure level, so check for DIAG and sort out
    12. If domain is DALL??, check further - if WIND in name then should be DALLRH
    13. Check for duplicates in terms of subsets of levels with all other processing the same
    14. Stash 1241 and 1223 need DALLTH but CMIP has no indication of levels
    """
    section = din['section']
    item = din['item']
    section_lookup = str(int(section))
    item_lookup = str(int(item))
    try:
        stashname = stash_lookup[section_lookup][item_lookup]['name']
    except:
        print 'this stashcode does not translate ', section_lookup, item_lookup
        stashname = ''

    if section == '02':
        if int(item) in range(320, 391):
            period = din['period']
            print ('this is COSP diagnostic, need to mean using hourly data '
                   'on radiation TS,  {}'.format(period))
            if 'day' in period.lower():
                din['tim_name'] = 'TRADDAYM'
            elif 'mon' in period.lower():
                din['tim_name'] = 'TRADMONM'
            elif '6hr' in period.lower():
                if din['tim_name'][-2:] != 'MN':
                    din['tim_name'] = 'T6HR'
                else:
                    din['tim_name'] = 'TRAD6HRMN'
            elif '3hr' in period.lower():
                if din['tim_name'][-2:] != 'MN':
                    din['tim_name'] = 'T3HR'
                else:
                    din['tim_name'] = 'TRAD3HRMN'
            else:
                din['tim_name'] = 'UNKNOWN'
                
            if 320 <= int(item) <= 327:
                cosp_type = 'COSP_CAL'
            elif 330 <= int(item) <= 337:
                cosp_type = 'COSP_ISC'
            elif 340 <= int(item) <= 347:
                cosp_type = 'COSP_CAL'
            elif int(item) == 348:
                cosp_type = 'COSP_PAR'
                din['dom_name'] = 'DCOSP_5'
            elif 370 <= int(item) <= 371:
                cosp_type = 'COSP_CAL40'
            elif 372 <= int(item) <= 390:
                cosp_type = 'COSP_CAL'
            din['package'] = din['package'] + '_' + cosp_type
            
            if int(item) == 337:
                print 'this is a histogram, need to do 7x7 domain'
                din['dom_name'] = 'DCOSP7x7'

    # If STASH diagnostic on TILES, then need to account for this in domain
    # profile
    if 'TILE' in stashname:
        din['dom_name'] = 'DTILE'

    # deal with soil levels
    if 'SOIL' in stashname and din['dom_name'] == 'DIAG' and '8' in section:
        din['dom_name'] = 'DSOIL'

# for TEM STASH diagnostics, 30310-30317, can only have 1 set of levels - do not mix them else model
# will fail. They are already zonal mean, so don't have that in the domain
    if section == '30':
        if int(item) in range(310, 317):
            old_domain = din['dom_name']
            if old_domain[-1] == 'Z':
                din['dom_name'] = 'DP39CCM'
#            if old_domain[-1] == 'Z':
#                new_domain = 'DP36CCM'
#            else:
#                new_domain = 'DP36CCM'
#            din['dom_name'] = new_domain

#    if section == '02':
#        if int(item) in range(217, 221):
#            period = din['period']
#            print ('this is radiation diagnostic, need to mean using hourly '
#                   'data on radiation TS,  {}'.format(period))
#            if 'day' in period.lower():
#                din['tim_name'] = 'TRADDAYM'
#            elif 'mon' in period.lower():
#                din['tim_name'] = 'TRADMONM'
#            else:
#                din['tim_name'] = 'UNKNOWN'
#            din['dom_name'] = 'DALLRHP1'

    if 'LTD' in din['package']:
        # make the domain Europe - if multi-level then use appropriate
        domain = copy.copy(din['dom_name'])
        if domain == 'RLEVEL3':
            din['dom_name'] = 'DEUROPER3'
        elif domain == 'RLEVEL2':
            din['dom_name'] = 'DEUROPER2'
        elif domain == 'DIAG':
            din['dom_name'] = 'DEUROPE'
        else:
            raise Exception('No not recognise this domain for LTD package'
                            + domain + str(din))

    if 'PLEV' in din['dom_name'] and section != '30':
        if (section != '06' and section != '16'):
            print ('variable on pressure levels but not section 30  {} {}'.
                   format(stashname, din))
            din['package'] = 'NO_ALEV_PLEV'
        elif section == '06:':
            if 'P LEV' not in stashname:
                din['package'] = 'NO_ALEV_PLEV'
        elif section == '16':
            if not (int(item) in range(202,206) or int(item) == '256'):
                din['package'] = 'NO_ALEV_PLEV'
        
    if section == '30' and (item[0:1] == '2' or item[0:1] == '3'):
        domain = copy.copy(din['dom_name'])
        if domain == 'DIAG':
            # can't have DIAG in pressure level diagnostics
            # try to assume these are ua850, va850, ta850
            try:
                plevel = din['cmor'][-3:]
                din['dom_name'] = 'DP'+plevel
            except:
                din['dom_name'] = 'UNKNOWN'
                
    if 'DALL' in din['dom_name']:
        if 'WIND' in stashname:
            print ('variable DALL but wind in name {} {}'.
               format(stashname, din))
            din['dom_name'] = 'DALLRH'                

    if section == '01' and (item == '223' or item == '241'):
        domain = copy.copy(din['dom_name'])
        if domain == 'DIAG':
            din['dom_name'] = 'DALLTH'                
           
    if section == '02' and (item == '308' or item == '309'):
        domain = copy.copy(din['dom_name'])
        if domain == 'DIAG':
            din['dom_name'] = 'DALLTH'                
           
    if section == '00' and (item == '407' or item == '408'):
        domain = copy.copy(din['dom_name'])
        if domain == 'DIAG':
            if item == '407':
                din['dom_name'] = 'DALLRH'
            elif item == '408':      
                din['dom_name'] = 'DALLTH'                
           
    if section == '03' and (item == '471' or item == '472'):
        domain = copy.copy(din['dom_name'])
        if item == '471':
            din['dom_name'] = 'D52TH'
        elif item == '472':      
            din['dom_name'] = 'D52RH'    
            
    if (section == '02' and item == '205') or (section == '03' and item == '332'):
        domain = copy.copy(din['dom_name'])
        if domain == 'DALLRH':
            din['dom_name'] = 'DIAG'
                        
           
def check_subset_of_levels(stash_dict):
    """
    Would like to remove duplicate levels from same variable, processing, but it is complicated 
    and need to know level set mapping etc
    """
    # PLEV8 is a subset of PLEV23
    # Get duplicated values for daily UP6:
    # 30201, 30202, 
    pass
               

def lookup_cmip6_cmor_stash_translation(cmor_or_var_key, cmip6_file):
    """
    Lookup cmor name in cmip6 dictionary file, and find stash translation
    (if any)
    """
    # TODO: Need to add processing options that can change the stash translation
    try:
        constraints = cmip6_file.get(cmor_or_var_key, 'constraint')
        if 'stash' in constraints:
            cmor_stashname = cmip6_file.get(cmor_or_var_key, 'stash')
        else:
            cmor_stashname = cmor_or_var_key
    except:
        cmor_stashname = 'None'

    return cmor_stashname


def work(loaded_workbook, stash_lookup, outdir, cmor_stash_cmip6_file):
    """
    Read in excel worksheet
    Go through each sheet (noting time period in name)
    Try to translate the definition of the data request to a corresponding
    dictionary of STASH required variables
    """
    cmip6_priority_col = 'A'
    cmor_unit_col_name = 'C'
    variable_col_name = 'F'
    cell_method_name = 'H'
    dim_key_name = 'K'
    cmor_col_name = 'L'
    realm_col_name = 'M'
    time_col_name = 'N'
    unique_col_name = 'S'
    mo_priority_col = 'AG'
    stash_col_name = 'AI'
    # first sheet is the Notes page, last one is the fx page
    section_ws = loaded_workbook.worksheets[1:-1]

    unique_key, cmorkey_stash = process_stash_translation(section_ws,
                                                          unique_col_name,
                                                          stash_col_name,
                                                          cmor_col_name,
                                                          variable_col_name)

    print 'max_row ', loaded_workbook.worksheets[1].max_row
    print 'max_col ', loaded_workbook.worksheets[1].max_column

    config = ConfigParser.ConfigParser()
    config.read(cmor_stash_cmip6_file)

    stash_dict = {}
    ocean_seaice_dict = {}
    stash_undef = {}
    stash_dup = {}
    stash_not_wanted = {}
    key_dict_all = {}
    dim_key_all = []
    cmor_units = {}
    cmor_stash_mapping = {}

    # process each worksheet
    for ws in section_ws:
        max_row = calc_max_occupied_rows(ws)

        sheet_name = copy.copy(ws.title)
        # skip ocean/sea-ice diagnostics as they come from NEMO or CICE (hence
        # don't need STASH mapping)
        # aero is currently an issue - both before we figure out EasyAerosol,
        # and the time period is not defined (assume monthly mean?)
        sheet_period = sheet_name
        if sheet_name[0:2] == 'em':
            sheet_period = sheet_name[2:]
        elif 'prim' in sheet_name:
            sheet_period = sheet_name[4:]
        elif 'aero' in sheet_name:
            sheet_period = 'aeromon'

        if sheet_name in sheets_to_skip:
            print 'skip sheet ', sheet_name
            continue

        print 'process sheet ', sheet_name, sheet_period
        # time processing key
        cell_method_key = process_range(cell_method_processor,
                                        ws[cell_method_name+'2:'+cell_method_name+'%i' % max_row])
        # dimensions key (e.g. longitude latitude time)
        dim_key = process_range(dim_processor, ws[dim_key_name+'2:'+dim_key_name+'%i' % max_row])
        print 'len(dim_key)', len(dim_key)
        # derive priority of variable from CMIP6 and Met Office priorities
        priority_key = derive_variable_priority(ws, cmip6_priority_col,
                                                mo_priority_col, max_row)
        # uid from spreadsheet
        unique_key = process_range(unique_processor, ws[unique_col_name+'2:'+unique_col_name+'%i' % max_row])
        # modelling realm (atmos, ocean, SeaIce) from spreadsheet
        realm_key = process_range(unique_processor, ws[realm_col_name+'2:'+realm_col_name+'%i' % max_row])
        # derive time information for STASH
        time_period = process_range(time_processor,
                                    ws[time_col_name + '2:' + time_col_name +
                                       '%i' % max_row])
        # derive time information for STASH
        time_usage_profile = derive_time_usage_profile(sheet_period,
                                                       time_period,
                                                       cell_method_key)
        # read the STASH translation of CMOR name - currently returns m01s??i???
        stash_key = process_range(check_stash,
                                  ws[stash_col_name + '2:' + stash_col_name +
                                     '%i' % max_row])
        # CMOR name
        cmor_key = process_range(priority_processor,
                                 ws[cmor_col_name + '2:' + cmor_col_name +
                                    '%i' % max_row])
        # CMOR name
        varname_key = process_range(priority_processor,
                                    ws[variable_col_name + '2:' +
                                       variable_col_name + '%i' % max_row])
        # CMOR units
        cmor_units_key = process_range(priority_processor,
                                       ws[cmor_unit_col_name+'2:'+cmor_unit_col_name+'%i' % max_row])
        # try and derive the space domain from the information
        domain_profile, domain_lbproc = derive_domain_profile(dim_key)

        dim_key_all.extend(dim_key)

        # organise all the above information into a dictionary, to be used to
        # derive the rose STASH namelist information
        print ('len  {} {} {} {} {} {} {}'.format(len(unique_key),
                                                  len(time_usage_profile),
                                                  len(dim_key),
                                                  len(domain_profile),
                                                  len(priority_key),
                                                  len(cmor_key),
                                                  len(stash_key)))
        if not (len(unique_key) == len(time_usage_profile) == len(dim_key) ==
                len(domain_profile) == len(priority_key) == len(cmor_key) ==
                len(stash_key) == len(domain_lbproc) == len(time_period) ==
                len(realm_key) == len(varname_key)):
            raise Exception('Length of the stash key inputs is not the same')

        for index, (ukey, tprof, dimk, dprof, prior, cmork, stkey, dproc, tperiod,
                    units, varn) in enumerate(zip(unique_key,
                                                  time_usage_profile,
                                                  dim_key,
                                                  domain_profile,
                                                  priority_key,
                                                  cmor_key, stash_key,
                                                  domain_lbproc,
                                                  time_period,
                                                  cmor_units_key,
                                                  varname_key)):
            key = str(ukey)
            package = prior
            lbproc = dproc + tprof[2]
            print ukey, tprof, dimk, dprof, prior, cmork, stkey

            cmor_or_var_key = cmork
            if cmork == 'None' and not varn == 'None':
                cmor_or_var_key = varn

            cmor_stashname = lookup_cmip6_cmor_stash_translation(
                cmor_or_var_key, config
            )
            if str(cmor_stashname) not in str(stkey):
                print ('different cmor translation:  {} {} {}'.
                       format(cmor_or_var_key, str(cmor_stashname),
                              str(stkey)))

            if cmor_stashname[0:3] == 'm01' or stkey[0:3] == 'm01':
                cmor_stash_mapping[cmork] = {'stash': stkey,
                                             'lbproc': lbproc,
                                             'units': units}
                st_list = [x.strip() for x in stkey.split(',')]
                for nc, code in enumerate(st_list):
                    print 'code ', code
                    # need extra key(s) if there are multiple stash codes
                    if nc > 0:
                        key = str(ukey) + '_' + str(nc)
                    # if the stash code looks like a real one
                    if len(code) == 10 and code[0] == 'm':
                        item = str(code[7:])
                        section = str(code[4:6])
                        stash_dict[key] = {'tim_name': tprof[0],
                                           'use_name': tprof[1],
                                           'cmip_dim': dimk,
                                           'dom_name': dprof,
                                           'priority': prior,
                                           'cmor': cmork,
                                           'package': package,
                                           'period': tperiod,
                                           'sheet_name': sheet_name,
                                           'stash': code,
                                           'item': item,
                                           'section': section,
                                           'lbproc': lbproc}

                        check_stash_dependencies(stash_dict[key], stash_lookup)

                        if len(dprof) > 11:
                            raise Exception('len of dprof ' + dprof + code)
                        stash_hash_key = (stash_dict[key]['section'] +
                                          stash_dict[key]['item'] +
                                          stash_dict[key]['dom_name'] +
                                          stash_dict[key]['tim_name'] +
                                          stash_dict[key]['use_name'] +
                                          stash_dict[key]['package'])
                        key_dict_all[key] = stash_hash_key
                    else:
                        item = 'UKNOWN'
                        section = 'UKNOWN'
                        if 'MO_NO' in package:
                            stash_not_wanted[key] = {'tim_name': tprof[0],
                                                     'use_name': tprof[1],
                                                     'cmip_dim': dimk,
                                                     'dom_name': dprof,
                                                     'priority': prior,
                                                     'cmor': cmork,
                                                     'package': package,
                                                     'period': tperiod,
                                                     'sheet_name': sheet_name,
                                                     'stash': code,
                                                     'item': item,
                                                     'section': section,
                                                     'lbproc': lbproc}
                        else:
                            stash_undef[key] = {'tim_name': tprof[0],
                                                'use_name': tprof[1],
                                                'cmip_dim': dimk,
                                                'dom_name': dprof,
                                                'priority': prior,
                                                'cmor': cmork,
                                                'package': package,
                                                'period': tperiod,
                                                'sheet_name': sheet_name,
                                                'stash': code,
                                                'item': item,
                                                'section': section,
                                                'lbproc': lbproc}
            else:
                ocean_seaice_dict[key] = {'period': tperiod,
                                          'sheet_name': sheet_name,
                                          'cmor': cmork,
                                          'cmip_dim': dimk,
                                          'priority': prior}

        for index, cmor_name in enumerate(cmor_key):
            cmor_units[cmor_key[index]] = cmor_units_key[index]

    print 'finish initial processing'

    # use priority value to make a package switch

    dim_key_unique = []
    [dim_key_unique.append(item) for item in dim_key_all
     if item not in dim_key_unique]

    # based on hash (using section, item, domain, time, usage, package),
    #   spot exact duplicates
    flipped = {}
    for key, value in key_dict_all.items():
        if value not in flipped:
            flipped[value] = [key]
        else:
            flipped[value].append(key)
            print 'flipped ', key, value, stash_dict[key]['stash']
            stash_dup[key] = stash_dict[key]
            print 'removed duplicate stash-cmor ', stash_dict[key]
            del stash_dict[key]
            
    # some of the level sets are subsets, would like to check but this is complex
    #check_subset_of_levels(stash_dict)

    # These are the unique dimensions in the spreadsheet defined by dimensions
    filename_unique_keys = outdir + '/unique_keys.py'
    write_unique_keys_as_dictionary(dim_key_unique, filename_unique_keys)

    # This file can be used for cmor conversion from stash
    filename_cmor_stash_units = outdir + '/cmor_translation_for_python.cfg'
    write_cmor_stash_units_as_cfg(
        cmorkey_stash, cmor_units, filename_cmor_stash_units)

    # This file can be used for cmor conversion from stash
    filename_cmor_stash_units = outdir + '/cmor_stash_mapping_2.cfg'
    write_cmor_stash_mapping_as_cfg(
        cmor_stash_mapping, filename_cmor_stash_units)

    for ndict, fname in zip(
            [stash_dict, ocean_seaice_dict], ['atmos', 'ocean-seaice']):
        fname_dict_out = outdir + '/' + fname + '_dictionary.json'
        write_stash_json(ndict, fname_dict_out)

    filename_stash_duplicate_json = outdir + '/stash_duplicate.json'
    write_stash_json(stash_dup, filename_stash_duplicate_json)

    filename_stash_undefined_json = outdir + '/stash_undefined.json'
    write_stash_json(stash_undef, filename_stash_undefined_json)

    filename_stash_notwanted_json = outdir + '/stash_notwanted.json'
    write_stash_json(stash_not_wanted, filename_stash_notwanted_json)

    return stash_dict
