#!/usr/bin/env python3
"""Merge all .txt files in a source folder into a single markdown file."""
import os
import glob

BASE = os.path.dirname(os.path.abspath(__file__))

JOBS = [
    ("texts", "general.md")]


def title_from_path(path):
    base = os.path.basename(path)
    name = base[:-4] if base.endswith(".txt") else base
    # strip havan.com.br_ prefix
    name = name.replace("havan.com.br_", "")
    parts = name.split("_")
    out = []
    for p in parts:
        if not p:
            continue
        # keep product code suffix (e.g. _p) meaningfully
        out.append(p.replace("-", " ").strip())
    return " ".join(out).strip().title()


def merge(src_rel, dst_name):
    src_dir = os.path.join(BASE, src_rel)
    files = sorted(glob.glob(os.path.join(src_dir, "*.txt")))
    dst_path = os.path.join(BASE, dst_name)
    with open(dst_path, "w", encoding="utf-8") as out:
        out.write(f"# Havan - {dst_name[:-3].title()}\n\n")
        out.write(f"_Merged from {len(files)} crawled pages._\n\n---\n\n")
        for i, fpath in enumerate(files, 1):
            title = title_from_path(fpath)
            out.write(f"## {i}. {title}\n\n")
            out.write(f"<details>\n<summary>Source: {os.path.basename(fpath)}</summary>\n\n")
            with open(fpath, "r", encoding="utf-8") as fin:
                content = fin.read().strip()
            out.write(content + "\n\n")
            out.write("</details>\n\n---\n\n")
    print(f"Wrote {dst_path} ({len(files)} files)")


for src, dst in JOBS:
    merge(src, dst)
