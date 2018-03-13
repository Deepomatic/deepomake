import hashlib
import json
import yaml

import dmake.common as common

def get_env_hash(env):
    """Return a stable hash for the `env` environment."""
    return hashlib.sha256(json.dumps(sorted(env.items()))).hexdigest()[:10]

def generate_config_map(env, name, labels = None):
    """Return a kubernetes manifest defining a ConfigMap storing `env`."""
    data = yaml.load("""
apiVersion: v1
kind: ConfigMap
metadata:
  name: ""
  labels: {}
data: {}
""")
    data['metadata']['name'] = name
    if labels:
        data['metadata']['labels'] = labels
    data['data'] = env
    return data

def generate_config_map_file(env, name_prefix, output_filepath, labels = None):
    """Generate a ConfigMap manifest file with unique env-hashed name, and return the name."""
    env_hash = get_env_hash(env)
    name = "%s-env-%s" % (name_prefix, env_hash)
    data = generate_config_map(env, name, labels)
    with open(output_filepath, 'w') as configmap_file:
        yaml.dump(data, configmap_file, default_flow_style=False)
    return name

def add_labels(resource, labels):
    if 'labels' not in resource['metadata']:
        resource['metadata']['labels'] = {}
    resource['metadata']['labels'].update(labels)

def dump_all_str_and_add_labels(data_str, file, labels):
    data = common.yaml_ordered_load(data_str, all=True)
    for resource in data:
        add_labels(resource, labels)
    common.yaml_ordered_dump(data, file, all=True)