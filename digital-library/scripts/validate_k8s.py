"""Validate rendered resources with bundled schemas; never connects to Kubernetes."""
import argparse
from pathlib import Path

import yaml
from kubernetes_validate import validate

parser = argparse.ArgumentParser()
parser.add_argument("manifest", type=Path)
parser.add_argument("--version", default="1.35.0")
args = parser.parse_args()
resources = [item for item in yaml.safe_load_all(args.manifest.read_text()) if item]
if not resources:
    raise SystemExit("No Kubernetes resources found")
for resource in resources:
    validate(resource, args.version, strict=True)
    print(f"Validated {resource['kind']}/{resource['metadata']['name']}")
print(f"Validated {len(resources)} resources against Kubernetes {args.version}; no cluster contacted.")
