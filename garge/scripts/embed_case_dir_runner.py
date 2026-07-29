#!/usr/bin/env python3
"""Embed Case Directory Runner

Usage example (run from any project):

python scripts/embed_case_dir_runner.py \
    --source-dir "/Users/leandrodisconzi/Documents/sa_server/aware-agents/workspace/01_Latam-Guarulhos/4thApril@2_05" \
    --main-project-root "/Users/leandrodisconzi/Documents/sa_server/garage" \
    --collection-name "guarulhos_4th_apr" \
    --embedding-dim 384

What it does:
1. Creates/overwrites directory_tree.md in the source directory.
2. Creates (or recreates) a symlink under the main project's expected ingestion path:
   static/latam/violations_data/Case/latam_fiasco/transcript_analyses/<case_name>
3. Calls the running API endpoint POST /v1/qdrant/embed-case-directory
4. Fetches the collection info and writes it to
   <source_dir>/04_vector_db_info/collection_info.json (overwrites if exists)

Requires: Python 3.8+
"""

from __future__ import annotations
import argparse
import os
import sys
import json
import textwrap
import shutil
from pathlib import Path
from datetime import datetime
import subprocess
import urllib.request
import urllib.error
import urllib.parse


def build_tree_markdown(root: Path, max_depth: int = 10) -> str:
    """Generate a tree-like markdown for `root` directory."""
    lines = [f"# Directory tree for {root}\n", "```"]

    def _walk(path: Path, prefix: str = "", depth: int = 0):
        if depth > max_depth:
            return
        try:
            entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except PermissionError:
            lines.append(prefix + "[permission denied]")
            return

        for i, entry in enumerate(entries):
            connector = "└── " if i == len(entries) - 1 else "├── "
            lines.append(prefix + connector + entry.name)
            if entry.is_dir():
                extension = "    " if i == len(entries) - 1 else "│   "
                _walk(entry, prefix + extension, depth + 1)

    _walk(root)
    lines.append("```")
    return "\n".join(lines)


def http_post_json(url: str, payload: dict, timeout: int = 300) -> tuple[int, dict]:
    """Post JSON to URL; return (status_code, response_json_or_text)."""
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode('utf-8')
            status = resp.getcode()
            try:
                return status, json.loads(body)
            except Exception:
                return status, {"raw": body}
    except urllib.error.HTTPError as he:
        try:
            body = he.read().decode('utf-8')
            return he.code, json.loads(body)
        except Exception:
            return he.code, {"error": he.reason}
    except Exception as e:
        return 599, {"error": str(e)}


def http_get_json(url: str, timeout: int = 60) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode('utf-8')
            try:
                return resp.getcode(), json.loads(body)
            except Exception:
                return resp.getcode(), {"raw": body}
    except urllib.error.HTTPError as he:
        try:
            body = he.read().decode('utf-8')
            return he.code, json.loads(body)
        except Exception:
            return he.code, {"error": he.reason}
    except Exception as e:
        return 599, {"error": str(e)}


def ensure_symlink(source: Path, main_project_root: Path, case_name: str, recreate: bool = False):
    target_base = main_project_root / "static/latam/violations_data/Case/latam_fiasco/transcript_analyses"
    target_base.mkdir(parents=True, exist_ok=True)
    symlink_path = target_base / case_name

    if symlink_path.exists() or symlink_path.is_symlink():
        if recreate:
            if symlink_path.is_dir() and not symlink_path.is_symlink():
                # existing real directory — we won't remove it
                raise RuntimeError(f"Path {symlink_path} exists and is a real directory. Remove it first or pick different case name.")
            else:
                symlink_path.unlink()
        else:
            # Already exists; ensure it points to source
            if symlink_path.resolve() == source.resolve():
                return symlink_path
            else:
                # doesn't point to the source
                if not recreate:
                    raise RuntimeError(f"Symlink {symlink_path} exists and points elsewhere. Use --recreate to overwrite.")
                symlink_path.unlink()

    os.symlink(source.resolve(), symlink_path)
    return symlink_path


def main():
    parser = argparse.ArgumentParser(description="Embed a case directory via local API and save collection info")
    parser.add_argument("--source-dir", required=True, help="Source directory to embed (absolute path)")
    parser.add_argument("--collection-name", default=None, help="Qdrant collection name to create/use")
    parser.add_argument("--case-name", default=None, help="Case directory name to use (basename). Defaults to source dir basename")
    parser.add_argument("--main-project-root", default="/Users/leandrodisconzi/Documents/sa_server/garage", help="Path to the main project where static ingestion path exists")
    parser.add_argument("--api-url", default="http://localhost:8066", help="API base URL")
    parser.add_argument("--embedding-dim", type=int, default=384, help="Embedding dimension")
    parser.add_argument("--recreate-symlink", action="store_true", help="Recreate symlink in the main project if it exists")
    parser.add_argument("--output-subdir", default="04_vector_db_info", help="Subdir (in source) to write collection info to")
    parser.add_argument("--overwrite-meta", action="store_true", help="Overwrite existing meta file in output subdir")
    args = parser.parse_args()

    source = Path(args.source_dir)
    if not source.exists() or not source.is_dir():
        print(f"Source directory does not exist: {source}")
        sys.exit(2)

    case_name = args.case_name or source.name
    collection_name = args.collection_name or f"{case_name.lower().replace(' ', '_')}_collection"
    # But if user provided not, default as in their ask (guarulhos_4th_apr) - the script allows override

    print(f"Generating directory tree for: {source}")
    md = build_tree_markdown(source)
    tree_md_path = source / 'directory_tree.md'
    with open(tree_md_path, 'w') as f:
        f.write(md)
    print(f"Wrote tree to {tree_md_path}")

    main_root = Path(args.main_project_root)
    print(f"Creating symlink under main project {main_root} -> case {case_name}")
    try:
        symlink = ensure_symlink(source, main_root, case_name, recreate=args.recreate_symlink)
        print(f"Symlink created: {symlink} -> {os.readlink(symlink)}")
    except Exception as e:
        print(f"Symlink error: {e}")
        sys.exit(3)

    # Call embed-case-directory endpoint
    embed_url = urllib.parse.urljoin(args.api_url, '/v1/qdrant/embed-case-directory')
    payload = {
        'case_directory': case_name,
        'collection_name': collection_name,
        'embedding_dim': args.embedding_dim
    }
    print(f"Calling embed endpoint {embed_url} with payload {payload} (this can take a while)")
    status, resp = http_post_json(embed_url, payload)
    print(f"Embed response: status={status}")
    print(json.dumps(resp, indent=2) if isinstance(resp, dict) else resp)

    if status != 200:
        print("Embedding failed or returned non-200 status. See details above.")

    # Wait a small amount before asking for collection info (server usually finished)
    info_url = urllib.parse.urljoin(args.api_url, f'/v1/ingestion/collections/{collection_name}/info')
    print(f"Fetching collection info from {info_url}")
    st, collection_info = http_get_json(info_url)
    print(f"Info response status={st}")

    output_dir = source / args.output_subdir
    output_dir.mkdir(parents=True, exist_ok=True)
    info_path = output_dir / 'collection_info.json'

    if info_path.exists() and not args.overwrite_meta:
        print(f"Meta file {info_path} already exists. Use --overwrite-meta to replace it.")
    else:
        with open(info_path, 'w') as f:
            json.dump({'status_code': st, 'body': collection_info}, f, indent=2)
        print(f"Wrote collection info to {info_path}")

    print("Done.")


if __name__ == '__main__':
    main()
