#!/usr/bin/python
#
# Copyright (c) 2017 Rob Bagby <rob.bagby@microsoft.com> and Bruno Terkaly <bterkaly@microsoft.com>
#
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type


ANSIBLE_METADATA = {'metadata_version': '1.1',
                    'status': ['preview'],
                    'supported_by': 'community'}


DOCUMENTATION = '''
---
module: azure_rm_container_registry

version_added: "2.4"

short_description: Manage Azure Container Registry

description:
    - Create, update and delete Azure Container Registry

options:
    location:
        description:
            - Valid azure location. Defaults to location of the resource group.
        default: resource_group location
        required: false
    name:
        description:
            - Name of the container registry
        required: true
    resource_group:
        description:
            - Name of a resource group where the container registry exists or will be created.
        required: true
    sku_name:
        description:
            - Choose between the Classic SKU and new SKUs, currently in preview, that provide capabilities
              Azure AD individual identity, Webhooks, and Delete.  With more features coming soon to the preview SKU.ANSIBLE_METADATA
              Currently only Basic is supported.
        required: false
    state:
        description:
            - Assert the state of the container registry. Use 'present' to create or update a container registry and
              'absent' to delete a container registry.
        default: present
        choices:
            - absent
            - present
        required: false
    storage_account_name:
        description:
            - The name of the storage account to be used by the container registry.
        required: true
    tags:
        description:
            - Limit results by providing a list of tags. Format tags as 'key' or 'key:value'.
        required: false
        default: null
extends_documentation_fragment:
    - azure
    - azure_tags

author:
    - "Rob Bagby (@rbagby)"
    - "Bruno Terkaly (@brunoterkaly)"
'''

EXAMPLES = '''
    - name: Create / Update Container Registry
      azure_rm_container_registry:
        admin_user_enabled: false
        location: westus
        name: myregistry
        resource_group: myresourcegroup
        sku_name: Basic
        state: present
        storage_account_name: mystorageaccount
        tags:
          env: dev
          type: service

    - name: Delete Container Registry
      azure_rm_container_registry:
        name: myregistry
        resource_group: myresourcegroup
        state: absent
'''

RETURN = '''
state:
    description: Current state of the container registry
    returned: always
    type: dict
changed:
    description: Whether or not the resource has changed
    returned: always
    type: bool
'''

import datetime
from ansible.module_utils.azure_rm_common import AzureRMModuleBase

try:
    from msrestazure.azure_exceptions import CloudError
    from azure.common import AzureHttpError
    from azure.mgmt.containerregistry.models import (
        StorageAccountParameters,
        RegistryCreateParameters,
        RegistryUpdateParameters,
        Sku
    )
    from azure.mgmt.compute.models import (
        Registry
    )
    from azure.storage.cloudstorageaccount import CloudStorageAccount


except ImportError:
    # This is handled in azure_rm_common
    pass


class AzureContainerRegistry(AzureRMModuleBase):
    """Configuration class for an Azure Container Registry resource"""

    def __init__(self):
        self.module_arg_spec = dict(
            resource_group=dict(type='str', required=True),
            name=dict(type='str', required=True),
            state=dict(type='str', required=False, default='present', choices=['present', 'absent']),
            location=dict(type='str', required=False),
            storage_account_name=dict(type='str', required=False),
            admin_user_enabled=dict(type='bool', required=False, default=False),
            sku_name=dict(type='str', required=False, default='Basic', choices=['Basic']),
            tags=dict(type='dict'),
        )

        self.resource_group = None
        self.name = None
        self.location = None
        self.storage_account_name = None
        self.admin_user_enabled = None
        self.tags = None

        self.results = dict(changed=False, state=dict())

        super(AzureContainerRegistry, self).__init__(derived_arg_spec=self.module_arg_spec,
                                                     supports_check_mode=True,
                                                     supports_tags=True)

    def exec_module(self, **kwargs):
        # import pdb; pdb.set_trace()
        for key in list(self.module_arg_spec.keys()) + ['tags']:
            setattr(self, key, kwargs[key])

        resource_group = self.get_resource_group(self.resource_group)
        if (resource_group is None):
            self.fail("Parameter error: An existing resource group is required")

        if not self.location:
            self.location = resource_group.location

        if len(self.name) < 5 or len(self.name) > 50:
            self.fail("Parameter error: name length must be between 5 and 50 characters.")

        if self.state == 'present':
            response = self.get_container_registry()

            if not response:
                self.create_container_registry()
            else:
                self.update_container_registry(response)

        elif self.state == 'absent':
            self.delete_container_registry()

        return self.results

    def delete_container_registry(self):
        self.log('Delete container registry {0}'.format(self.name))

        if self.check_mode:
            self.log('check_mode is true')
            response = None
            self.results['changed'] = True
            self.results['state'] = response
            return

        existing_registry = self.get_container_registry()
        if existing_registry is None:
            self.results['changed'] = False
            return True

        self.results['changed'] = True
        if not self.check_mode:
            try:
                status = self.container_registry_client.registries.delete(self.resource_group, self.name)
                self.log("delete status: ")
                self.log(str(status))
            except CloudError as e:
                self.fail("Failed to delete the container registry: {0}".format(str(e)))
        return True

    def get_container_registry(self):
        self.log('Get properties for container registry {0}'.format(self.name))
        registry_obj = None
        registry_dict = None

        try:
            registry_obj = self.container_registry_client.registries.get(self.resource_group, self.name)
        except CloudError:
            pass

        if registry_obj:
            registry_dict = self.registry_obj_to_dict(registry_obj)

        return registry_dict

    def get_storage_account_key(self):
        account_keys = None
        try:
            account_keys = self.storage_client.storage_accounts.list_keys(self.resource_group, self.storage_account_name)
        except CloudError:
            pass
        if account_keys is None:
            self.fail("Parameter error: A valid storage account is required.")
        primary_key = account_keys.keys[0].value
        return primary_key

    def update_container_registry(self, registry_dictionary):
        self.log('Evaluating if there is a need to update container registry {0}'.format(self.name))

        if (self.storage_account_name is None):
            self.fail("Parameter error: A valid storage account name is required.")

        update_parameters = RegistryUpdateParameters()

        if self.admin_user_enabled != registry_dictionary['admin_user_enabled']:
            self.results['changed'] = True
            update_parameters.admin_user_enabled = self.admin_user_enabled

        if self.storage_account_name != registry_dictionary['storage_account_name']:
            self.results['changed'] = True
            primary_key = self.get_storage_account_key()
            saparams = StorageAccountParameters(self.storage_account_name, primary_key)
            update_parameters.storage_account = saparams

        update_tags, registry_dictionary['tags'] = self.update_tags(registry_dictionary['tags'])

        if update_tags:
            self.results['changed'] = True
            update_parameters.tags = registry_dictionary['tags']

        if self.results['changed'] is False:
            self.log('No changes detected for container registry {0}'.format(self.name))
            return

        self.log('Updating container registry {0}'.format(self.name))

        if self.check_mode:
            self.log('check_mode is true')
            response = self.self_to_dict()
            self.results['state'] = response
            return

        try:
            self.container_registry_client.registries.update(
                resource_group_name=self.resource_group,
                registry_name=self.name,
                registry_update_parameters=update_parameters)
        except Exception as exc:
            self.fail("Failed to update container registry: {0}".format(str(exc)))

        self.results['changed'] = True
        self.results['state'] = self.get_container_registry()

        return

    def create_container_registry(self):
        self.log('Creating container registry {0}'.format(self.name))

        if self.check_mode:
            self.log('check_mode is true')
            response = self.self_to_dict()
            self.results['changed'] = True
            self.results['state'] = response
            return

        if (self.storage_account_name is None):
            self.fail("Parameter error: A valid storage account name is required.")

        primary_key = self.get_storage_account_key()

        saparams = StorageAccountParameters(self.storage_account_name, primary_key)

        registry_create_parameters = RegistryCreateParameters(
            location=self.location,
            sku=Sku(self.sku_name),
            storage_account=saparams,
            admin_user_enabled=self.admin_user_enabled,
            tags=self.tags)

        try:
            poller = self.container_registry_client.registries.create(
                resource_group_name=self.resource_group,
                registry_name=self.name,
                registry_create_parameters=registry_create_parameters)

            self.get_poller_result(poller)
        except Exception as exc:
            self.fail("Failed to create container registry: {0}".format(str(exc)))

        self.results['changed'] = True
        self.results['state'] = self.get_container_registry()

        return

    def registry_obj_to_dict(self, registry_obj):
        account_dict = dict(
            id=registry_obj.id,
            name=registry_obj.name,
            type=registry_obj.type,
            location=registry_obj.location,
            login_server=registry_obj.login_server,
            creation_date=registry_obj.creation_date,
            provisioning_state=registry_obj.provisioning_state.value,
            admin_user_enabled=registry_obj.admin_user_enabled,
            storage_account_name=registry_obj.storage_account.name,
            sku_name=registry_obj.sku.name
        )

        account_dict['tags'] = None
        if registry_obj.tags:
            account_dict['tags'] = registry_obj.tags
        return account_dict

    def self_to_dict(self):
        account_dict = dict(
            id=".../Microsoft.ContainerRegistry/registries/" + self.name,
            name=self.name,
            type="Microsoft.ContainerRegistry/registries",
            location=self.location,
            login_server=self.name + ".azurecr.io",
            creation_date=datetime.datetime.now(),
            provisioning_state="Succeeded",
            admin_user_enabled=self.admin_user_enabled,
            storage_account_name=self.storage_account_name,
            sku_name=self.sku_name
        )

        account_dict['tags'] = None
        if self.tags:
            account_dict['tags'] = self.tags
        return account_dict


def main():
    """Main execution"""
    AzureContainerRegistry()

if __name__ == '__main__':
    main()
