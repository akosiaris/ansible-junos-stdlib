#!/usr/bin/env python

# Copyright 2016 Jason Edelman <jason@networktocode.com>
# Network to Code, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

DOCUMENTATION = '''
---
module: junos_get_table
author: Jason Edelman (@jedelman8)
version_added: "1.9.0"
short_description: Retrieve data from a Junos device using Tables/Views
description:
    - Retrieve data from a Junos device using Tables/Views
requirements:
    - junos-eznc >= 1.2.2
options:
    host:
        description:
            - Set to {{ inventory_hostname }}
        required: true
    user:
        description:
            - Login username
        required: false
        default: $USER
    passwd:
        description:
            - Login password
        required: false
        default: assumes ssh-key active
    logfile:
        description:
            - Path on the local server where the progress status is logged
              for debugging purposes
        required: false
        default: None

    port:
        description:
            - TCP port number to use when connecting to the device
        required: false
        default: 830
    table:
        description:
            - Name of PyEZ Table
        required: false
        default: None
    file:
        description:
            - YAML file that has the table specified in table parameter
        required: false
        default: None
    path:
        description:
            - Path of location of the YAML file
        required: false
        default: op directory in jnpr.junos.op
    response_type:
        description:
            - Option to change how data is returned from the
              module.  Either list of dictionaries or the
              Juniper PyEZ default (list of tuples, which becomes
              lists by the time it gets to Ansible)
        required: false
        options: ['list_of_dicts', 'juniper_items']
        default: list_of_dicts

'''

EXAMPLES = '''
# GET NEIGHBOR INFO USING STD LLDP TABLE
- junos_get_table: table=LLDPNeighborTable file=lldp.yml host={{ inventory_hostname }} user={{ un }} passwd={{ pwd }}

# GET NEIGHBOR INFO USING CUSTOM LLDP TABLE IN CUSTOM PATH
- junos_get_table: table=NTCNeighborTable path=tables/ file=ntclldp.yaml host={{ inventory_hostname }} user={{ un }} passwd={{ pwd }}

'''

RETURN = '''

resource:
    description: Dictionary of facts
    returned: always
    type: list of dictionaries or list of tuples (default items from PyEZ)
    sample:
        [
            {
                "neighbor_interface": "fxp0",
                "local_interface": "fxp0",
                "neighbor": "vmx2"
            },
            {
                "neighbor_interface": "ge-0/0/2",
                "local_interface": "ge-0/0/2",
                "neighbor": "vmx2"
            },
            {
                "neighbor_interface": "fxp0",
                "local_interface": "fxp0",
                "neighbor": "vmx3"
            }
        ]

'''

from distutils.version import LooseVersion
import logging
import os
from lxml import etree
from lxml.builder import E
from jnpr.junos.factory.factory_loader import FactoryLoader
import yaml

try:
    from jnpr.junos import Device
    from jnpr.junos.version import VERSION
    import jnpr.junos.op as tables_dir
    if not LooseVersion(VERSION) >= LooseVersion('1.2.2'):
        HAS_PYEZ = False
    else:
        HAS_PYEZ = True
except ImportError:
    HAS_PYEZ = False

TABLE_PATH = os.path.dirname(os.path.abspath(tables_dir.__file__))
CHOICES = ['list_of_dicts', 'juniper_items']


def juniper_items_to_list_of_dicts(data):
    """Convert Juniper PyEZ Table/View items to list of dictionaries
    """

    list_of_resources = []
    # data.items() is a list of tuples
    for table_key, table_fields in data.items():
        # sample:
        # ('fxp0', [('neighbor_interface', '1'), ('local_interface', 'fxp0'),
        # ('neighbor', 'vmx2')]
        # table_key - element 0 is the key from the Table - not using at all
        # table_fields - element 1 is also a list of uples
        temp = {}
        for normalized_key, normalized_value in table_fields:
            # calling it normalized value because
            # YOU/WE created the keys
            temp[normalized_key] = normalized_value
        list_of_resources.append(temp)
    return list_of_resources


def main():

    module = AnsibleModule(
        argument_spec=dict(host=dict(required=True,
                           default=None),  # host or ipaddr
                           user=dict(required=False,
                                     default=os.getenv('USER')),
                           passwd=dict(required=False, default=None),
                           port=dict(required=False, default=830),
                           logfile=dict(required=False, default=None),
                           file=dict(required=True, default=None),
                           path=dict(required=False, default=TABLE_PATH),
                           table=dict(required=True, default=None),
                           response_type=dict(choices=CHOICES,
                                              default='list_of_dicts')
                           ),
        supports_check_mode=False)

    if not HAS_PYEZ:
        module.fail_json(msg='junos-eznc >= 1.2.2 is required for this module')

    args = module.params

    logfile = args['logfile']
    response_type = args['response_type']

    if not args['file'].endswith('.yml'):
        module.fail_json(msg='file must end with .yml extension')

    if logfile is not None:
        logging.basicConfig(filename=logfile, level=logging.INFO,
                            format='%(asctime)s:%(name)s:%(message)s')
        logging.getLogger().name = 'CONFIG:' + args['host']

    logging.info("connecting to host: {0}@{1}:{2}".format(args['user'],
                                                          args['host'],
                                                          args['port']))
    try:
        dev = Device(args['host'], user=args['user'], password=args['passwd'],
                     port=args['port'], gather_facts=False).open()
    except Exception as err:
        msg = 'unable to connect to {0}: {1}'.format(args['host'], str(err))
        logging.error(msg)
        module.fail_json(msg=msg)
        # --- UNREACHABLE ---

    resource = []
    try:
        file_name = os.path.join(args['path'], args['file'])
        try:
            globals().update(FactoryLoader().load(
                yaml.load(open(file_name).read())))
        except IOError as err:
            module.fail_json(msg='Unable to find file: {0}'.format(file_name))
        logging.info("Getting data from device")
        try:
            data = globals()[args['table']](dev)
        except KeyError:
            module.fail_json(msg='Unable to find Table in provided yaml file',
                             table=args['table'], file=file_name)
        data.get()
        if response_type == 'list_of_dicts':
            resource = juniper_items_to_list_of_dicts(data)
        else:
            resource = data.items()
    except Exception as err:
        msg = 'Uncaught exception - please report: {0}'.format(str(err))
        logging.error(msg)
        dev.close()
        module.fail_json(msg=msg)

    dev.close()

    module.exit_json(resource=resource)

from ansible.module_utils.basic import *

if __name__ == "__main__":
    main()
